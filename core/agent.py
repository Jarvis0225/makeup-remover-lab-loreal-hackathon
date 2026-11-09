"""内容核验 Agent：感知 → 规划 → 工具调用（取证/检测/大模型）→ 自适应深挖 → 证据融合 → 风险决策 → 报告。"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
from PIL import Image

from . import llm, trufor_tool
from .comment_detect import analyze_comments
from .image_forensics import analyze_image, crop_region
from .knowledge import REGULATIONS
from .text_detect import analyze_text

DIMENSIONS = {
    "tamper": "图片篡改/拼接",
    "aigc": "AI 生成未标识",
    "claim": "虚假/违规宣称",
    "comment": "评论区刷评",
    "consistency": "图文不一致",
}
SEVERE_CLAIMS = {"医疗化宣称", "假货暗语", "虚假评价诱导"}
DIM_WEIGHT = {"tamper": 1.0, "aigc": 0.8, "claim": 0.9, "comment": 0.8, "consistency": 0.7}
LEVELS = [(0.25, "低风险", "#16a34a"), (0.5, "中风险", "#ca8a04"), (0.75, "高风险", "#ea580c"), (1.01, "极高风险", "#dc2626")]


@dataclass
class Content:
    id: str = "content"
    title: str = ""
    text: str = ""
    images: list = field(default_factory=list)      # list[(name, PIL.Image, raw_bytes|None)]
    comments: object = None
    meta: dict = field(default_factory=dict)


@dataclass
class Verdict:
    content_id: str
    trust_score: int
    risk: float
    level: str
    color: str
    verdict: str
    dims: dict
    tags: list
    evidences: list
    actions: dict
    reasons: list
    trace: list
    image_reports: list
    text_report: dict | None
    comment_report: dict | None
    llm_used: bool
    llm_review: dict | None = None


class VerifyAgent:
    def __init__(self, use_llm: bool = True, on_step: Callable | None = None, use_trufor: bool = True):
        self.use_llm = use_llm and llm.available()
        self.use_trufor = use_trufor and trufor_tool.available()
        self.on_step = on_step
        self.trace: list = []

    # ------------------------------------------------------------------ trace
    def _step(self, stage, tool, thought, fn=None):
        t0 = time.time()
        obs, result = "", None
        try:
            if fn:
                result = fn()
                obs = result[1] if isinstance(result, tuple) else ""
                result = result[0] if isinstance(result, tuple) else result
        except Exception as e:  # 单个工具失败不影响整体闭环
            obs = f"工具调用失败：{type(e).__name__}: {str(e)[:160]}"
        item = {"stage": stage, "tool": tool, "thought": thought, "observation": obs, "ms": int((time.time() - t0) * 1000)}
        self.trace.append(item)
        if self.on_step:
            self.on_step(item)
        return result

    # ------------------------------------------------------------------ run
    def run(self, c: Content) -> Verdict:
        self.trace = []
        evidences: list = []
        mods = [m for m, ok in (("图片", c.images), ("文案", c.text.strip()), ("评论", c.comments is not None and len(c.comments) > 0)) if ok]
        plan = []
        if c.images:
            plan += ["图像取证(ELA/噪声/复制-移动/元数据/频域)"] + (["TruFor 深度篡改定位"] if self.use_trufor else []) + \
                    (["Qwen-VL 视觉研判", "可疑区域放大复核"] if self.use_llm else [])
        if c.text.strip():
            plan += ["违规宣称与法规比对", "AI 文案特征分析"] + (["Qwen 文案语义研判"] if self.use_llm else [])
        if c.images and c.text.strip() and self.use_llm:
            plan.append("图文一致性交叉验证")
        if mods and "评论" in mods:
            plan.append("评论区水军检测")
        self._step("感知与规划", "Planner",
                   f"识别到模态：{'、'.join(mods) or '无'}；{'已接入开源多模态大模型 Qwen2.5-VL' if self.use_llm else '未配置大模型，使用本地取证模式'}。",
                   lambda: (None, "执行计划：" + " → ".join(plan + ["证据融合", "风险决策", "生成报告"])))

        # ---- 图像
        image_reports = []
        for name, img, raw in c.images:
            rep = self._step("图像取证", "ImageForensics", f"对图片「{name}」运行多路取证算法，寻找压缩、噪声、复制粘贴与元数据异常。",
                             lambda: self._img_tool(img, raw))
            if rep is None:
                continue
            for e in rep.evidences:
                e["source"] = name
            if self.use_trufor:
                r = self._step("深度篡改定位", "TruFor", f"调用开源深度取证模型 TruFor（CVPR 2023）对「{name}」做像素级篡改定位，弥补 ELA 对平台重压缩敏感的短板。",
                               lambda: self._trufor_tool(img, rep))
                if r:
                    rep.evidences.append(r)
                    rep.regions += r["regions"]
            if c.meta.get("screenshot"):
                self._step("截图来源校正", "SourceCalibrator", "该配图裁自屏幕截图：经过屏幕渲染与重新编码，压缩/噪声/相机指纹类像素证据可靠性下降，置信度减半。",
                           lambda: (None, self._discount(rep.evidences)))
            evidences += [e for e in rep.evidences if e["category"] != "info"]
            image_reports.append((name, img, rep))
            if self.use_llm:
                hint = "；".join(e["summary"] for e in rep.evidences if e["score"] > 0.2)[:600]
                r = self._step("视觉大模型研判", "Qwen-VL", f"让视觉大模型从语义层面审视「{name}」（AI 生成、拼接、美妆特有造假）。",
                               lambda: self._vlm_tool(img, c.title + " " + c.text[:200], hint))
                if r:
                    evidences += [dict(e, source=name) for e in r]
                # 自适应：取证发现可疑区域时，裁剪放大复核
                for k, region in enumerate(sorted(rep.regions, key=lambda b: -b[2] * b[3])[:2]):
                    r = self._step("自适应深挖", "Qwen-VL·RegionZoom",
                                   f"取证在「{name}」区域 {region} 发现异常，裁剪放大让大模型复核，降低算法误报。",
                                   lambda region=region: self._region_tool(img, region, rep.meta["work_size"]))
                    if r:
                        evidences.append(dict(r, source=name))

        # ---- 文案
        text_report = None
        if c.text.strip():
            text_report = self._step("文案检测", "ClaimChecker+AIGCText", "比对广告法/化妆品条例违规词库，并计算 AI 生成文案统计特征。",
                                     lambda: self._text_tool(c.text))
            if text_report:
                evidences += [dict(e, source="文案") for e in text_report["evidences"]]
                if text_report["hits"]:
                    laws = sorted({h["law"] for h in text_report["hits"]})
                    self._step("法规检索", "RegulationKB", "针对命中的违规宣称检索法规依据，形成可解释判定。",
                               lambda: (None, "；".join(f"{REGULATIONS[k][0]}" for k in laws)))
            if self.use_llm:
                r = self._step("文案大模型研判", "Qwen", "让大模型理解语义，识别隐晦夸大、伪真人测评与软广。", lambda: self._llm_text_tool(c.text))
                if r:
                    evidences += [dict(e, source="文案") for e in r]
        if c.images and c.text.strip() and self.use_llm:
            r = self._step("跨模态核验", "Qwen-VL·CrossCheck", "核对配图与文案宣称是否一致（产品、色号、效果）。",
                           lambda: self._cross_tool(c.images[0][1], c.text))
            if r:
                evidences += r

        # ---- 评论
        comment_report = None
        if c.comments is not None and len(c.comments) > 0:
            comment_report = self._step("评论区检测", "AstroturfDetector", "对评论做近重复聚类、时间爆发与账号画像分析，识别刷评水军。",
                                        lambda: self._comment_tool(c.comments))
            if comment_report:
                evidences += [dict(e, source="评论区") for e in comment_report["evidences"]]

        # ---- 融合与决策
        dims, risk = self._step("证据融合", "EvidenceFusion", "按维度对证据做置信度加权的 Noisy-OR 融合，避免单一弱证据误判。",
                                lambda: self._fuse(evidences)) or ({}, 0.0)
        level, color = next((n, col) for t, n, col in LEVELS if risk < t)
        verdict = "真实可信" if risk < 0.25 else ("存疑需复核" if risk < 0.5 else "疑似伪造或违规")
        tags = [DIMENSIONS[d] for d, v in dims.items() if v >= 0.4]
        reasons = [f"[{e.get('source', '')}] {e['name']}：{e['summary']}" for e in
                   sorted(evidences, key=lambda e: -e["score"] * e["confidence"]) if e["score"] >= 0.3][:8]
        actions = self._step("风险决策", "PolicyEngine", f"综合风险 {risk:.2f}（{level}），匹配处置策略库生成平台/创作者/消费者三方建议。",
                             lambda: self._policy(dims, risk, evidences))
        llm_review = None
        if self.use_llm:
            bundle = {"risk": round(risk, 3), "dims": dims, "evidences": [
                {k: e[k] for k in ("name", "score", "summary")} | {"source": e.get("source")} for e in evidences if e["score"] > 0.15]}
            llm_review = self._step("大模型复核决策", "Qwen·Reviewer", "将结构化证据交给大模型做最终复核与自然语言解释。",
                                    lambda: self._review_tool(bundle))
        self._step("生成报告", "Reporter", "输出可解释核验报告：结论、可疑点定位、判定依据、处置建议。",
                   lambda: (None, f"结论：{verdict}｜可信分 {int(round(100 * (1 - risk)))}｜标签：{'、'.join(tags) or '无'}"))
        return Verdict(c.id, int(round(100 * (1 - risk))), risk, level, color, verdict, dims, tags, evidences, actions or {},
                       reasons, self.trace, image_reports, text_report, comment_report, self.use_llm, llm_review)

    # ------------------------------------------------------------------ tools
    @staticmethod
    def _img_tool(img, raw):
        rep = analyze_image(img, raw)
        top = sorted(rep.evidences, key=lambda e: -e["score"])
        return rep, "；".join(f"{e['name']} {e['score']:.2f}" for e in top if e["category"] != "info") + f"；可疑区域 {len(rep.regions)} 处"

    @staticmethod
    def _discount(evs):
        n = 0
        for e in evs:
            if e["category"] in ("tamper", "aigc") and not e["name"].startswith(("元数据", "Qwen")):
                e["confidence"] = round(e["confidence"] * 0.5, 3)
                e["summary"] += "（来源为截图，像素证据置信度已减半）"
                n += 1
        return f"已对 {n} 条像素级证据降权"

    @staticmethod
    def _trufor_tool(img, rep):
        ev, heat = trufor_tool.evidence(img, rep.meta["work_size"])
        rep.trufor_vis = heat
        return ev, f"整图篡改概率 {ev['details']['integrity_score']:.2f}；定位区域 {len(ev['regions'])} 处"

    @staticmethod
    def _vlm_tool(img, ctx, hint):
        r = llm.judge_image(img, ctx, hint)
        evs = []
        finds = "；".join(f"{f.get('issue', '')}（{f.get('location', '')}）" for f in r.get("findings", []) if isinstance(f, dict))
        if "aigc_prob" in r:
            evs.append({"name": "Qwen-VL：AI 生成研判", "score": float(r["aigc_prob"]), "confidence": 0.7, "category": "aigc",
                        "summary": f"{r.get('reasoning', '')} {finds}".strip(), "details": r})
        if "tamper_prob" in r:
            evs.append({"name": "Qwen-VL：篡改/美妆造假研判", "score": float(r["tamper_prob"]), "confidence": 0.65, "category": "tamper",
                        "summary": f"{r.get('reasoning', '')} {finds}".strip(), "details": r})
        return evs, f"AI 生成概率 {r.get('aigc_prob', '?')}，篡改概率 {r.get('tamper_prob', '?')}；{r.get('reasoning', r.get('raw', ''))[:150]}"

    @staticmethod
    def _region_tool(img, region, work_size):
        r = llm.inspect_region(crop_region(img, region, work_size), "压缩误差/噪声水平与周围区域不一致")
        p = float(r.get("prob", 0.5 if r.get("suspicious") else 0.1))
        ev = {"name": "可疑区域放大复核", "score": p, "confidence": 0.6, "category": "tamper",
              "summary": f"区域 {region}：{r.get('observation', '')}", "details": r, "regions": [region]}
        return ev, f"{'确认可疑' if r.get('suspicious') else '未见明显异常（可能为算法误报）'}：{r.get('observation', '')[:120]}"

    @staticmethod
    def _text_tool(text):
        rep = analyze_text(text)
        return rep, f"命中违规片段 {len(rep['hits'])} 处；AI 文案特征 {rep['evidences'][-1]['score'] if rep['evidences'] else 0:.2f}；" + \
            "；".join(e["summary"][:80] for e in rep["evidences"][:2])

    @staticmethod
    def _llm_text_tool(text):
        r = llm.judge_text(text)
        issues = "；".join(f"“{i.get('quote', '')}”{i.get('problem', '')}" for i in r.get("issues", []) if isinstance(i, dict))[:400]
        evs = []
        if "aigc_prob" in r:
            evs.append({"name": "Qwen：AI 文案研判", "score": float(r["aigc_prob"]), "confidence": 0.6, "category": "aigc",
                        "summary": r.get("reasoning", ""), "details": r})
        if "false_claim_prob" in r:
            evs.append({"name": "Qwen：虚假宣称研判", "score": float(r["false_claim_prob"]), "confidence": 0.7, "category": "claim",
                        "summary": f"{r.get('reasoning', '')} {issues}".strip(), "details": r})
        return evs, f"AI 文案概率 {r.get('aigc_prob', '?')}，虚假宣称概率 {r.get('false_claim_prob', '?')}；{issues[:150]}"

    @staticmethod
    def _cross_tool(img, text):
        r = llm.cross_check(img, text)
        p = float(r.get("mismatch_prob", 0 if r.get("consistent", True) else 0.6))
        ev = {"name": "图文一致性核验", "score": p, "confidence": 0.6, "category": "consistency", "source": "图文",
              "summary": f"{r.get('reasoning', '')} {'；'.join(map(str, r.get('issues', [])))}".strip(), "details": r}
        return [ev], f"不一致概率 {p:.2f}；{r.get('reasoning', '')[:120]}"

    @staticmethod
    def _comment_tool(comments):
        rep = analyze_comments(comments)
        return rep, rep["evidences"][0]["summary"] if rep["evidences"] else "无评论"

    @staticmethod
    def _review_tool(bundle):
        r = llm.final_review(bundle)
        return r, f"{r.get('verdict', '')}：{'；'.join(r.get('key_reasons', [])[:3])[:200]}"

    @staticmethod
    def _fuse(evidences):
        dims = {}
        for d in DIMENSIONS:
            items = [e for e in evidences if e.get("category") == d]
            dims[d] = round(float(1 - np.prod([1 - e["score"] * e["confidence"] for e in items])) if items else 0.0, 3)
        # 维度内归一：多路证据互证时增强，单路弱证据时抑制
        risk = float(1 - np.prod([1 - DIM_WEIGHT[d] * v for d, v in dims.items()]))
        risk = max(risk, max(dims.values(), default=0))
        risk = float(np.clip(risk, 0, 1))
        # 比例原则：仅文案宣称一个维度有问题、且不含医疗化/假货/刷评诱导等严重类别时，最高到“高风险→人工复核”，不自动下架
        hot = [d for d, v in dims.items() if v >= 0.4]
        cats = {s["category"] for e in evidences for s in e.get("spans", [])}
        note = ""
        if hot == ["claim"] and not cats & SEVERE_CLAIMS and risk >= 0.75:
            risk, note = 0.74, "（仅文案宣称存疑且无严重违规类别，按比例原则封顶为高风险，交人工复核）"
        return (dims, risk), "；".join(f"{DIMENSIONS[d]} {v:.2f}" for d, v in dims.items()) + f" → 综合风险 {risk:.2f}{note}"

    @staticmethod
    def _policy(dims, risk, evidences):
        plat, creator, consumer = [], [], []
        if risk >= 0.75:
            plat += ["立即下架/屏蔽内容，冻结相关商品链接", "通知创作者并开放申诉通道（48 小时内）", "固化证据快照（原图哈希、取证热力图、报告）存档"]
        elif risk >= 0.5:
            plat += ["限流并进入人工复核队列（P1 优先级，2 小时内处理）", "在内容页展示“内容真实性待核实”风险提示"]
        elif risk >= 0.25:
            plat += ["正常展示但打标提示，进入抽样复核", "持续监测该账号后续发布内容"]
        else:
            plat += ["放行，纳入常规抽检"]
        if dims.get("tamper", 0) >= 0.4:
            plat.append("要求创作者提供原始拍摄文件（含 EXIF）以供比对")
            creator.append("请提供未经修改的原图；对比图请保持同一光线、机位与参数，并标注“图片经过修饰”")
        if dims.get("aigc", 0) >= 0.4:
            plat.append("强制添加“AI 生成”显式标识（《人工智能生成合成内容标识办法》）")
            creator.append("AI 生成或辅助创作的图片/文案需添加显式标识，不得以 AI 图冒充真实使用效果")
            consumer.append("该内容可能由 AI 生成，展示效果不代表真实使用效果")
        if dims.get("claim", 0) >= 0.4:
            plat.append("违规宣称词屏蔽；涉及医疗化/特殊功效的转化妆品合规专员复核特证与功效评价报告")
            creator.append("删除绝对化、医疗化及无法证实的效果承诺；功效宣称需有备案的功效评价依据；商业合作请标明“广告”")
            consumer.append("文中功效宣称未经核实，普通化妆品不具备治疗作用，请以产品备案信息为准")
        if dims.get("comment", 0) >= 0.4:
            plat.append("折叠疑似水军评论，不计入口碑/销量排序；对关联账号与商家启动刷评调查")
            consumer.append("评论区存在疑似刷评，请谨慎参考好评")
        if dims.get("consistency", 0) >= 0.4:
            plat.append("核查图片来源，比对是否盗用他人图片")
            creator.append("请使用本人实拍图并确保图文一致")
        if any("假货" in e.get("summary", "") for e in evidences):
            plat.append("转品牌方打假/法务团队，核验商品真伪与授权渠道")
            consumer.append("疑似非授权渠道商品，建议通过品牌官方渠道购买")
        if not creator:
            creator.append("内容未见明显问题，继续保持真实分享")
        if not consumer:
            consumer.append("未发现明显风险")
        laws = {}
        for e in evidences:
            for name, text in e.get("laws", []):
                laws[name] = text
        return {"platform": plat, "creator": creator, "consumer": consumer, "laws": laws}, " | ".join(plat[:3])
