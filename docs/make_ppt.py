"""基于官方模板【PPT模版】BEAUTY TECHATHON.pptx 生成答辩 PPT：python -m docs.make_ppt [--pdf]

模板要求：思源黑体（本机用同一字体的 Noto Sans CJK SC，免费可商用）、封面主标题 44 号并注明作品名称/赛道/队伍名称、
内容包含 作品背景 / 技术实现方式 / 作品使用场景 / 未来完善方向 四大板块。
"""
import copy
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Pt

ROOT = Path(__file__).parent
TEMPLATE = ROOT / "template" / "BEAUTY_TECHATHON_template.pptx"
EVAL = ROOT.parent / "eval"
A, UI = ROOT / "assets", ROOT / "assets" / "ui"
OUT = ROOT / "BeautyGuard_答辩.pptx"

TEAM = "卸妆水研究所"
WORK = "BeautyGuard 美妆内容鉴真 Agent"
TRACK = "赛题2 信任守护师 —— 创造者的 AI 卫士"
FONT = "Noto Sans CJK SC"          # 即思源黑体（Source Han Sans），免费可商用
P1, P2 = RGBColor(0x7A, 0x2B, 0xD0), RGBColor(0xC0, 0x26, 0xD3)
LIGHT, LIGHT2 = RGBColor(0xF6, 0xEE, 0xFF), RGBColor(0xFD, 0xF4, 0xFF)
TXT, GREY, WHITE = RGBColor(0x3F, 0x3F, 0x3F), RGBColor(0x6B, 0x72, 0x80), RGBColor(0xFF, 0xFF, 0xFF)
RED, ORANGE, GREEN = RGBColor(0xDC, 0x26, 0x26), RGBColor(0xEA, 0x58, 0x0C), RGBColor(0x16, 0xA3, 0x4A)
BOTTOM = 16.7   # 内容页底部紫色装饰条从 17.16cm 开始

prs = Presentation(str(TEMPLATE))
L_COVER, L_CONTENT, L_END = prs.slide_layouts[0], prs.slide_layouts[1], prs.slide_layouts[2]
# 删除模板自带的 3 张示例页，只保留版式
for sid in list(prs.slides._sldIdLst):
    prs.part.drop_rel(sid.rId)
    prs.slides._sldIdLst.remove(sid)


def cm(v):
    return Emu(int(v * 360000))


def style_run(r, size, color=TXT, bold=False):
    r.font.size, r.font.bold, r.font.color.rgb = Pt(size), bold, color
    rpr = r._r.get_or_add_rPr()
    for tag in ("a:latin", "a:ea", "a:cs"):
        el = rpr.find(qn(tag))
        if el is None:
            el = rpr.makeelement(qn(tag), {})
            rpr.append(el)
        el.set("typeface", FONT)


def text(s, x, y, w, h, lines, size=14, color=TXT, bold=False, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, spacing=4):
    tb = s.shapes.add_textbox(cm(x), cm(y), cm(w), cm(h))
    tf = tb.text_frame
    tf.word_wrap, tf.vertical_anchor = True, anchor
    tf.margin_left = tf.margin_right = cm(0.1)
    for i, line in enumerate(lines if isinstance(lines, list) else [lines]):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment, p.space_after = align, Pt(spacing)
        parts = line if isinstance(line, list) else [(line, {})]
        for seg in parts:
            seg_text, opt = (seg, {}) if isinstance(seg, str) else seg
            r = p.add_run(); r.text = seg_text
            style_run(r, opt.get("size", size), opt.get("color", color), opt.get("bold", bold))
    return tb


def box(s, x, y, w, h, fill=LIGHT, line=None, radius=0.06, shape=MSO_SHAPE.ROUNDED_RECTANGLE):
    sh = s.shapes.add_shape(shape, cm(x), cm(y), cm(w), cm(h))
    if shape == MSO_SHAPE.ROUNDED_RECTANGLE:
        sh.adjustments[0] = radius
    sh.fill.solid(); sh.fill.fore_color.rgb = fill
    if line:
        sh.line.color.rgb = line; sh.line.width = Pt(1)
    else:
        sh.line.fill.background()
    sh.shadow.inherit = False
    return sh


def card(s, x, y, w, h, title, lines, size=13, fill=LIGHT, title_color=P1):
    box(s, x, y, w, h, fill)
    box(s, x, y + 0.35, 0.16, 0.75, P1 if title_color == P1 else title_color, radius=0.5)
    text(s, x + 0.45, y + 0.25, w - 0.7, 0.95, title, 16, title_color, True)
    text(s, x + 0.45, y + 1.25, w - 0.8, h - 1.4, lines, size)


def picture(s, path, x, y, w=None, h=None, crop=None, border=True):
    """插入图片；crop=(top, bottom) 为按高度比例裁剪；自动保持比例。"""
    path = Path(path)
    if crop:
        im = Image.open(path)
        cut = im.crop((0, int(im.height * crop[0]), im.width, int(im.height * crop[1])))
        path = A / "_tmp" / f"{path.stem}_{crop[0]}_{crop[1]}.png"
        path.parent.mkdir(exist_ok=True); cut.save(path)
    pic = s.shapes.add_picture(str(path), cm(x), cm(y), width=cm(w) if w else None, height=cm(h) if h else None)
    if border:
        pic.line.color.rgb = RGBColor(0xE5, 0xD5, 0xF7); pic.line.width = Pt(1)
    return pic


def fit(path, w, h, crop=None):
    """计算在 w×h 框内保持比例的尺寸。"""
    im = Image.open(path)
    iw, ih = im.width, im.height * ((crop[1] - crop[0]) if crop else 1)
    r = min(w / iw, h / ih)
    return iw * r, ih * r


def table(s, x, y, w, rows, col_w, size=12, row_h=0.9, head=P1):
    t = s.shapes.add_table(len(rows), len(rows[0]), cm(x), cm(y), cm(w), cm(row_h * len(rows))).table
    for j, cw in enumerate(col_w):
        t.columns[j].width = cm(cw)
    for i, r in enumerate(rows):
        t.rows[i].height = cm(row_h)
        for j, v in enumerate(r):
            c = t.cell(i, j)
            c.text = ""
            c.fill.solid(); c.fill.fore_color.rgb = head if i == 0 else (LIGHT if i % 2 else WHITE)
            c.margin_left = c.margin_right = cm(0.15); c.margin_top = c.margin_bottom = cm(0.05)
            c.vertical_anchor = MSO_ANCHOR.MIDDLE
            run = c.text_frame.paragraphs[0].add_run(); run.text = str(v)
            style_run(run, size, WHITE if i == 0 else TXT, i == 0)
    return t


PAGE = [0]


def page(section, title, subtitle=None):
    s = prs.slides.add_slide(L_CONTENT)
    PAGE[0] += 1
    box(s, 2.3, 0.95, 3.6, 0.8, P1, radius=0.5)
    text(s, 2.3, 0.95, 3.6, 0.8, section, 13, WHITE, True, PP_ALIGN.CENTER, MSO_ANCHOR.MIDDLE)
    text(s, 2.2, 1.85, 29.5, 1.6, title, 30, TXT, True)
    if subtitle:
        text(s, 2.25, 3.3, 29.5, 0.9, subtitle, 14, GREY)
    text(s, 30.0, 17.55, 2.6, 0.8, f"{PAGE[0] + 1:02d}", 12, WHITE, True, PP_ALIGN.RIGHT)
    text(s, 2.3, 17.55, 16, 0.8, f"{WORK} · {TEAM}", 10, WHITE)
    return s


# ======================================================== 1 封面
s = prs.slides.add_slide(L_COVER)
text(s, 4.1, 4.6, 26, 2.2, WORK, 44, WHITE, True)
text(s, 4.15, 7.0, 26, 3.0, [f"赛道：{TRACK}", f"队伍：{TEAM}"], 24, WHITE, True, spacing=8)
text(s, 4.15, 10.6, 24, 1.8, ["“你还相信你看到的吗？” —— 识别 · 解释 · 决策",
                              "让每一份种草都经得起查证"], 16, RGBColor(0xF3, 0xE8, 0xFF), spacing=6)

# ======================================================== 2 目录
s = page("目录", "CONTENTS")
secs = [("01", "作品背景", ["美妆种草的四类信任危机", "现有方案的不足", "我们的定位与目标"]),
        ("02", "技术实现方式", ["核验 Agent 架构", "多模态检测：图像 · 文案 · 评论", "证据融合与风险决策", "效果验证"]),
        ("03", "作品使用场景", ["平台审核 / 品牌 / 创作者 / 消费者", "小红书截图一键核验", "数据集闭环与处置工单"]),
        ("04", "未来完善方向", ["已知局限与改进", "路线图与落地价值"])]
for k, (n, t, items) in enumerate(secs):
    x = 2.3 + k * 7.45
    box(s, x, 4.4, 7.0, 11.6, LIGHT)
    text(s, x + 0.5, 4.8, 6, 2.0, n, 44, P2, True)
    text(s, x + 0.5, 7.1, 6.2, 1.2, t, 22, P1, True)
    box(s, x + 0.55, 8.45, 1.4, 0.1, P1, radius=0.5)
    text(s, x + 0.5, 9.0, 6.2, 6.5, ["• " + i for i in items], 14, spacing=10)

# ======================================================== 3 背景：痛点
s = page("01 作品背景", "美妆种草内容，正在失去“真实”", "种草笔记已成为美妆消费决策的第一入口，也是造假最集中的地方")
pains = [("种草图片", ["前后对比图局部磨皮，夸大功效", "粘贴“专柜正品/官方认证”贴纸", "复制产品伪造“满柜现货”"]),
         ("AI 生成素材", ["AI “完美皮肤”效果图冒充实拍", "AI 产品大片未作标识", "真实创作者被劣币驱逐"]),
         ("种草文案", ["AI 批量生成“伪真人测评”", "“7 天美白”“根除色斑”违规宣称", "“啵啵间”等谐音软广规避审核"]),
         ("评论区", ["模板化好评、集中爆发刷评", "批量注册水军账号", "好评返现诱导"])]
for k, (t, ls) in enumerate(pains):
    card(s, 2.3 + k * 7.45, 4.4, 7.0, 6.0, t, ["• " + x for x in ls], 13)
box(s, 2.3, 10.9, 29.35, 5.5, LIGHT2, line=RGBColor(0xE9, 0xD5, 0xFF))
text(s, 2.9, 11.2, 28, 1.0, "现有方案的不足", 18, P1, True)
text(s, 2.9, 12.35, 28, 4.0, [
    [("只会打分：", {"bold": True, "color": P1}), ("通用 AIGC 检测只回答“是不是 AI”，不懂美妆语境——“美白”属于需特证的特殊功效、前后对比图是夸大功效的重灾区", {})],
    [("不给依据：", {"bold": True, "color": P1}), ("黑盒分数无法支撑处置，审核员不敢用，创作者无从申诉", {})],
    [("没有决策：", {"bold": True, "color": P1}), ("识别之后缺少分级处置、整改建议与法规依据，无法进入平台审核流程", {})]], 14, spacing=8)

# ======================================================== 4 背景：定位
s = page("01 作品背景", "我们的定位：懂美妆的“AI 鉴真专家”", "不是又一个打分模型，而是会查证、会推理、会给出处置建议的核验 Agent")
for k, (t, ls) in enumerate([("传统取证 × 开源大模型互补", ["像素级、可复现的物理证据（压缩、噪声、相机指纹）", "大模型语义判断，并对算法可疑区放大复核"]),
                             ("每一个结论都有依据", ["证据 = 异常分 × 方法置信度 × 说明", "× 可疑区域/文本片段定位 × 法规条款"]),
                             ("可降级、可落地、全开源", ["无大模型也能纯本地跑完整闭环", "TruFor / RapidOCR / Qwen2.5-VL 均为开源模型"])]):
    card(s, 2.3 + k * 9.9, 4.4, 9.45, 4.6, t, ["• " + x for x in ls], 13)
text(s, 2.3, 9.5, 29, 0.9, "对照赛题考察方向：全链条覆盖", 18, P1, True)
table(s, 2.3, 10.5, 29.35, [["考察要求", "BeautyGuard 的实现"],
                            ["多模态鉴伪", "图片：TruFor 深度定位 + ELA / 噪声 / 复制-移动 / 元数据 / 频域；文案：违规宣称 + AI 文案特征；评论：水军检测"],
                            ["语义一致性校验", "图文一致性（Qwen2.5-VL）、作者评论并入宣称检测、截图来源自动校正证据置信度"],
                            ["决策与建议输出", "四级风险 + 比例原则；平台 / 创作者 / 消费者三方建议，附法规依据与证据快照"],
                            ["可运行、可展示", "Streamlit 交互 Demo：单条核验、小红书截图入口、数据集批量闭环、报告导出"]],
      [6.0, 23.35], 13, 1.15)

# ======================================================== 5 技术：架构
s = page("02 技术实现方式", "核验 Agent：感知 → 取证 → 深挖 → 融合 → 决策", "每一步“思考 → 动作 → 观察”全程留痕，可审计、可申诉")
steps = [("① 感知规划", "识别图 / 文 / 评论\n动态生成工具计划"), ("② 多模态工具", "TruFor · ELA · 噪声\n复制-移动 · 元数据\n违规词 × 法规库\n水军检测 · OCR"),
         ("③ 自适应深挖", "可疑区域裁剪放大\nQwen2.5-VL 复核"), ("④ 证据融合", "维度内置信度加权\nNoisy-OR"),
         ("⑤ 风险决策", "四级分级\n比例原则 · 策略库"), ("⑥ 可解释报告", "平台 / 创作者 / 消费者\nMarkdown · JSON")]
for k, (t, d) in enumerate(steps):
    x = 2.3 + k * 4.95
    hot = k in (1, 4)
    box(s, x, 4.5, 4.55, 6.3, P1 if hot else LIGHT)
    text(s, x + 0.1, 4.8, 4.35, 1.0, t, 16, WHITE if hot else P1, True, PP_ALIGN.CENTER)
    text(s, x + 0.1, 6.1, 4.35, 4.5, d.split("\n"), 12.5, WHITE if hot else TXT, align=PP_ALIGN.CENTER, spacing=6)
    if k < 5:
        arr = s.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, cm(x + 4.58), cm(7.4), cm(0.35), cm(0.5))
        arr.fill.solid(); arr.fill.fore_color.rgb = P2; arr.line.fill.background()
text(s, 2.3, 11.3, 29, 0.9, "开源组件（赛题要求使用开源模型）", 18, P1, True)
table(s, 2.3, 12.3, 29.35, [["组件", "用途", "说明"],
                            ["TruFor（CVPR 2023）", "深度篡改检测与像素级定位", "RGB + Noiseprint++ 相机指纹融合；Apple 芯片 MPS 加速约 1.5 秒/图"],
                            ["RapidOCR", "小红书截图识别", "本地 ONNX 推理，提取标题、正文、评论与评论时间"],
                            ["Qwen2.5-VL / Qwen2.5（可选）", "语义研判、区域复核、图文一致性", "开源权重；DashScope 调用或本地 vLLM 部署；未接入时自动降级"]],
      [7.5, 8.5, 13.35], 12, 1.0)

# ======================================================== 6 技术：图像取证
s = page("02 技术实现方式", "多模态检测 ①：图像取证", "开源深度模型 + 五路传统取证 + 视觉大模型，每一路都为美妆场景设计了误报控制")
table(s, 2.3, 4.4, 29.35, [["检测器", "能发现的造假", "误报控制"],
                           ["TruFor 深度定位", "拼接贴纸、局部修补、磨皮；抗平台重压缩", "只取高可靠性区域；分数 < 0.45 视为无证据"],
                           ["ELA 误差水平分析", "粘贴的认证贴纸、替换的产品 / 批号", "纹理回归去内容化；屏蔽叠加文字强边缘与图像边界"],
                           ["传感器噪声一致性", "前后对比图局部磨皮 / 美白、跨来源拼接", "排除饱和块；整图无噪声时交由 AIGC 检测"],
                           ["复制-移动（SIFT + RANSAC）", "复制产品伪造“满柜现货”、遮盖瑕疵", "前后对比两次拍摄（旋转缩放）不误判；重复文字不计"],
                           ["元数据取证", "美图 / PS 导出痕迹、SD / ComfyUI 生成参数、C2PA", "无 EXIF 仅作弱线索（平台会剥离）"],
                           ["频域 + 纹理统计", "上采样网格伪影、“完美皮肤”过度平滑", "多线索累加，单一线索不定罪"],
                           ["Qwen2.5-VL + 区域放大", "畸形文字 / Logo、光影错误、伪造检测报告", "对算法可疑区二次确认，压低误报"]],
      [8.0, 11.0, 10.35], 13, 1.45)

# ======================================================== 7 技术：可视化
s = page("02 技术实现方式", "可疑之处“看得见”：篡改区域可视化", "原图 → 可疑区域热力图 → TruFor 篡改概率图 → ELA / 噪声 / 复制-移动中间图")
w, h = fit(UI / "tab_image.png", 18.5, 12.0)
picture(s, UI / "tab_image.png", 2.3, 4.4, w=w)
y = 4.4
for img, cap in [("splice_00_panel.png", "拼接：粘贴“专柜正品”贴纸被精确框出"), ("copymove_00_panel.png", "复制-移动：位移一致的特征点连线")]:
    pw, ph = fit(A / img, 10.3, 4.6)
    picture(s, A / img, 21.35, y, w=pw)
    text(s, 21.35, y + ph + 0.1, 10.3, 0.8, cap, 11.5, GREY)
    y += ph + 1.2
text(s, 21.35, y + 0.2, 10.3, 3.5, ["左图：前后对比图磨皮夸大的真实检测界面——", "噪声断层 + TruFor 定位 + 美图导出元数据三路互证"], 12, P1, True)

# ======================================================== 8 技术：文案 & 评论
s = page("02 技术实现方式", "多模态检测 ②：文案与评论区", "违规宣称 × 法规知识库；评论区文本 + 时间 + 账号三重画像")
for k, (img, t, ls) in enumerate([
        ("tab_text.png", "种草文案", ["开源违禁词库（200+）× 广告法 / 化妆品条例，附合规替换建议",
                                     "上下文豁免：“第一次用”“最大的缺点是贵”不误报",
                                     "倍数数据、即时功效、谐音软广（啵啵间）识别；AI 伪测评统计特征"]),
        ("tab_comment.png", "评论区", ["字符 n-gram 近重复聚类 → 雷同评论簇",
                                     "评论区同质化好评（无账号信息时尤其关键）",
                                     "10 分钟时间爆发 + 新注册 / 零粉 / 批量昵称账号画像"])]):
    x = 2.3 + k * 14.9
    pw, ph = fit(UI / img, 14.45, 7.3)
    picture(s, UI / img, x, 4.4, w=pw)
    card(s, x, 4.4 + ph + 0.35, 14.45, 16.6 - (4.4 + ph + 0.35), t, ["• " + i for i in ls], 12.5)

# ======================================================== 9 技术：决策
s = page("02 技术实现方式", "从识别到决策：证据融合与分级处置", "维度内 1 − Π(1 − 分数 × 置信度)：多路证据互证则升高，单一弱证据被抑制；可信分 = 100 × (1 − 风险)")
pw, ph = fit(UI / "verdict.png", 15.5, 6.2, (0, 0.235))
picture(s, UI / "verdict.png", 2.3, 4.4, w=pw, crop=(0, 0.235))
table(s, 2.3, 4.4 + ph + 0.5, 15.5, [["风险等级", "可信分", "平台处置"], ["低风险", "≥ 75", "放行，常规抽检"], ["中风险", "50–75", "打标提示 + 抽样复核"],
                                    ["高风险", "25–50", "限流 + P1 人工复核"], ["极高风险", "< 25", "下架 + 证据固化 + 48h 申诉"]], [3.6, 3.2, 8.7], 12.5, 0.95)
card(s, 18.4, 4.4, 13.25, 6.1, "专项处置（按命中维度追加）", ["• AI 未标识 → 强制添加“AI 生成”显式标识", "• 违规宣称 → 屏蔽违规词，合规专员核验特证",
                                                   "• 图片篡改 → 要求提供原始拍摄文件", "• 刷评 → 折叠评论，启动刷评调查", "• 假货暗语 → 转品牌打假 / 法务"], 12.5)
card(s, 18.4, 10.9, 13.25, 5.7, "比例原则：不误伤创作者", ["• 仅文案宣称存疑、且无医疗化 / 假货等严重类别时，",
                                                  "  最高判为“高风险 → 人工复核”，不自动下架", "• 同一词重复出现只计一次；“美白”等特殊功效",
                                                  "  仅提示核验特证，而非直接定性违规"], 12.5)

# ======================================================== 10 技术：效果验证
m = json.loads((EVAL / "metrics.json").read_text(encoding="utf-8"))
rb = json.loads((EVAL / "robustness.json").read_text(encoding="utf-8"))
cr = json.loads((EVAL / "comment_realworld.json").read_text(encoding="utf-8"))
s = page("02 技术实现方式", "效果验证：不只在演示集上好看", "留出集（未参与标定的新随机种子）+ 平台重压缩 / 缩放 + 1 万条真实小红书评论")
for k, key in enumerate(["准确率", "精确率", "召回率", "F1"]):
    box(s, 2.3 + k * 3.75, 4.4, 3.45, 2.6, LIGHT)
    text(s, 2.3 + k * 3.75, 4.55, 3.45, 1.3, f"{m[key]:.0%}", 26, P1, True, PP_ALIGN.CENTER)
    text(s, 2.3 + k * 3.75, 5.95, 3.45, 0.8, f"演示集{key}", 11, GREY, align=PP_ALIGN.CENTER)
cols = ["原图", "平台重压缩 Q75", "缩放0.75+Q85"]
kinds = [("real", "真实实拍"), ("ba_real", "真实前后对比"), ("copymove", "复制-移动"), ("retouch", "磨皮夸大"), ("aigc", "AI 生成"), ("splice", "拼接")]
pair = lambda c, k: f"{rb['per_kind_base'][c][k]:.2f} → {rb['per_kind'][c][k]:.2f}"
table(s, 2.3, 7.4, 14.6, [["留出集（传统 → +TruFor）", "原图", "重压缩", "缩放"]] + [[n] + [pair(c, k) for c in cols] for k, n in kinds]
      + [["整体"] + [f"{rb['overall_base'][c]:.2f} → {rb['overall'][c]:.2f}" for c in cols]], [5.0, 3.2, 3.2, 3.2], 11.5, 0.98)
e1, e2 = cr["exp1"], cr["exp2"]
rows = [["真实小红书评论（1 万条）", "精确率", "召回率", "区告警"], ["纯真实评论（6000 条）", "—", f"误判 {e1['comment_fpr']:.0%}", f"{e1['section_false_alarm']:.0%}"]]
for g, gn in (("A模板", "模板刷评"), ("B留出", "留出写法刷评")):
    for kk in (3, 10):
        d = e2[f"{g}_inject_{kk}_of_30"]
        rows.append([f"注入{gn} {kk}/30", f"{d['precision']:.1%}", f"{d['recall']:.1%}", f"{d['section_detect']:.0%}"])
table(s, 17.4, 4.4, 14.25, rows, [6.0, 2.75, 2.75, 2.75], 11.5, 0.98)
card(s, 17.4, 10.6, 14.25, 6.0, "诚实说明", ["• 演示集为程序化合成、阈值在其上标定，100% 仅代表流程正确",
                                         "• 接入开源 TruFor：拼接检测 0–50% → 100%，不受重压缩 / 缩放影响",
                                         "• 真实评论首测召回仅约 30%，据此新增“同质化好评”特征",
                                         "• 已知局限：缩放后的真实前后对比拼图会被判为合成 → 人工复核"], 12)

# ======================================================== 11 场景：四类用户
s = page("03 作品使用场景", "谁在用：一个 Agent，服务内容生态四方", "同一份证据链，输出给不同角色的不同动作")
for k, (t, ls) in enumerate([("内容平台 · 审核", ["自动分级分流，高风险 P1 复核", "处置附证据快照与法规依据", "可直接生成工单、支持申诉"]),
                             ("品牌方（欧莱雅）", ["监测品牌冒用、假货暗语", "达人合作内容发布前合规预检", "识别竞品刷评与虚假背书"]),
                             ("创作者", ["发布前自检，获得具体整改建议", "补 AI 标识 / 改违规词 / 标明广告", "真实分享不被水军与 AI 稀释"]),
                             ("消费者", ["“该内容可能由 AI 生成”", "“功效宣称未经核实”", "“评论区疑似刷评，谨慎参考”"])]):
    card(s, 2.3 + k * 7.45, 4.4, 7.0, 5.0, t, ["• " + x for x in ls], 12.5)
text(s, 2.3, 9.75, 29, 0.8, "实际输出示例（P07 核心案例的三方处置建议）", 13, P1, True)
pw, ph = fit(UI / "tab_action.png", 29.35, 6.0, (0, 0.62))
picture(s, UI / "tab_action.png", 2.3 + (29.35 - pw) / 2, 10.6, w=pw, crop=(0, 0.62))

# ======================================================== 12 场景：截图入口
s = page("03 作品使用场景", "小红书截图一键核验：真实笔记实测", "平台未开放笔记 / 评论接口、我们也不做爬虫——审核员或消费者截个图即可核验")
pw, ph = fit(UI / "screenshot_parse.png", 16.0, 12.2, (0, 0.47))
picture(s, UI / "screenshot_parse.png", 2.3, 4.4, w=pw, crop=(0, 0.47))
x2 = 2.3 + pw + 0.5
vw, vh = fit(UI / "screenshot_verdict.png", 31.65 - x2, 4.6, (0, 0.36))
picture(s, UI / "screenshot_verdict.png", x2, 4.4, w=vw, crop=(0, 0.36))
card(s, x2, 4.4 + vh + 0.35, 31.65 - x2, 16.6 - (4.4 + vh + 0.35), "判定：高风险（可信分 26）→ 限流 + 人工复核", [
    "• “快了近两倍”：无来源的倍数比较数据", "• “即刻亮了一度两度”：即时功效宣称", "• “+7啵啵间”：谐音指代直播间，带货未标广告",
    "• 美白 / 淡斑：特殊功效，需核验特证", "• 自动裁出配图、识别作者回复；截图像素证据自动降权",
    [("结论为风险提示，不构成对品牌或博主的违规认定", {"color": GREY, "size": 10.5})]], 12)

# ======================================================== 13 场景：数据集闭环
s = page("03 作品使用场景", "数据集闭环：从识别到处置工单", "批量核验 → 指标 → 风险分布 → 按风险排序的处置工单，模拟平台审核流水线")
LW = 19.5
pw, ph = fit(UI / "batch_metrics.png", LW, 1.6)
picture(s, UI / "batch_metrics.png", 2.3, 4.4, w=pw)
y = 4.4 + ph + 0.3
cw, chh = fit(UI / "batch_charts.png", LW, 9.5)
picture(s, UI / "batch_charts.png", 2.3, y, w=cw)
y += chh + 0.3
ow, oh = fit(UI / "batch_orders.png", LW, 16.6 - y, (0, 0.6))
picture(s, UI / "batch_orders.png", 2.3, y, w=ow, crop=(0, 0.6))
card(s, 22.3, 4.4, 9.35, 12.2, "测试数据包（21 条）", [
    "按赛题格式：sample_xxx / 正文.txt + 评论.txt + 图片 + README.txt", "覆盖种草内容、评论区、AI 生成素材三大场景",
    "含边缘场景：真实前后对比图、“第一次用”、仅评论区被刷", "含 3 组小红书截图样本（1 组真实笔记）", "一键核验：python -m eval.run_package"], 12)

# ======================================================== 14 未来
s = page("04 未来完善方向", "已知局限与路线图", "坦诚面对局限，每一项都有明确的改进路径")
table(s, 2.3, 4.4, 29.35, [["当前局限", "改进方向"],
                           ["缩放后的真实前后对比拼图会被 TruFor 判为合成", "拼图版式识别 + 逐面板检测；结合 Qwen2.5-VL 判断是否为正常拼图"],
                           ["本地 AIGC 图像检测基于统计线索", "接入开源 UnivFD / AIDE 等检测器；读取 C2PA 与 AIGC 隐式标识作为强证据"],
                           ["演示数据以合成为主", "与平台合作获取真实标注样本，持续标定阈值；扩充真实 AIGC 种草图"],
                           ["违禁词库需人工维护", "法规库更新 + 审核反馈驱动的词库与策略自学习"],
                           ["暂未覆盖视频种草", "关键帧取证复用图像管线；口播 ASR 复用文案检测"],
                           ["TruFor 许可仅限非营利用途", "商业化时替换为商用许可模型或获取授权"]],
      [13.5, 15.85], 13, 1.15)
box(s, 2.3, 12.85, 29.35, 3.75, LIGHT2, line=RGBColor(0xE9, 0xD5, 0xFF))
text(s, 2.9, 13.1, 28.5, 1.0, "落地价值", 18, P1, True)
text(s, 2.9, 14.2, 28.5, 2.4, ["品牌侧：发布前合规预检 + 全网冒用 / 假货监测；平台侧：审核分流降本、处置可追溯；",
                               "社会侧：呼应《人工智能生成合成内容标识办法》，守护消费者知情权与真实创作者的生存空间。"], 14, spacing=6)

# ======================================================== 15 THANKS
s = prs.slides.add_slide(L_END)
text(s, 0, 7.0, 33.87, 3.0, "THANKS!", 72, WHITE, True, PP_ALIGN.CENTER)
text(s, 0, 10.2, 33.87, 1.2, f"{WORK} · {TEAM}", 18, RGBColor(0xF3, 0xE8, 0xFF), align=PP_ALIGN.CENTER)

prs.save(OUT)
print("saved", OUT, len(prs.slides), "slides")

if "--pdf" in sys.argv:
    pdf = OUT.with_suffix(".pdf")
    subprocess.run(["osascript", "-e", f'''tell application "Keynote"
  set d to open POSIX file "{OUT}"
  delay 2
  export d to POSIX file "{pdf}" as PDF with properties {{PDF image quality:Best}}
  close d saving no
end tell'''], check=True)
    print("pdf", pdf)
