"""核验报告导出（Markdown / JSON）。"""
from __future__ import annotations

import json
from datetime import datetime

from .agent import DIMENSIONS, Verdict


def to_markdown(v: Verdict, title: str = "") -> str:
    L = [f"# 美妆内容核验报告 · {v.content_id}", "",
         f"- 内容标题：{title or '-'}", f"- 核验时间：{datetime.now():%Y-%m-%d %H:%M:%S}",
         f"- 研判模式：{'取证算法 + 开源多模态大模型 Qwen2.5-VL' if v.llm_used else '本地取证算法（未接入大模型）'}", "",
         "## 一、结论", "", f"**{v.verdict}**｜可信分 **{v.trust_score}/100**｜{v.level}", "",
         f"风险标签：{'、'.join(v.tags) or '无'}", "", "| 维度 | 风险分 |", "|---|---|"]
    L += [f"| {DIMENSIONS[d]} | {s:.2f} |" for d, s in v.dims.items()]
    L += ["", "## 二、判定依据（按证据强度排序）", ""]
    L += [f"{i}. {r}" for i, r in enumerate(v.reasons, 1)] or ["未发现显著风险证据。"]
    if v.text_report and v.text_report["hits"]:
        L += ["", "## 三、文案可疑片段", "", "| 片段 | 类别 | 说明 |", "|---|---|---|"]
        L += [f"| {h['text']} | {h['category']} | {h['reason']} |" for h in v.text_report["hits"]]
    if v.image_reports:
        L += ["", "## 四、图片可疑区域", ""]
        for name, _, rep in v.image_reports:
            L.append(f"- **{name}**：可疑区域 {rep.regions or '无'}")
            L += [f"  - {e['name']}（{e['score']:.2f}）：{e['summary']}" for e in rep.evidences if e["score"] > 0.2]
    if v.comment_report is not None:
        df = v.comment_report["table"]
        sus = df[df["label"] == "疑似水军"]
        L += ["", "## 五、评论区", "", v.comment_report["evidences"][0]["summary"], ""]
        L += [f"- {r['user']}：“{r['text']}” —— {r['reasons']}" for _, r in sus.head(10).iterrows()]
    a = v.actions
    L += ["", "## 六、处置建议", "", "**平台处置**", ""] + [f"- {x}" for x in a.get("platform", [])]
    L += ["", "**创作者整改**", ""] + [f"- {x}" for x in a.get("creator", [])]
    L += ["", "**消费者提示**", ""] + [f"- {x}" for x in a.get("consumer", [])]
    if a.get("laws"):
        L += ["", "## 七、法规依据（要点摘录，以原文为准）", ""] + [f"- {k}：{t}" for k, t in a["laws"].items()]
    if v.llm_review:
        L += ["", "## 八、大模型复核意见", "", "```json", json.dumps(v.llm_review, ensure_ascii=False, indent=1), "```"]
    L += ["", "## 附：Agent 核验轨迹", "", "| # | 阶段 | 工具 | 思考 | 观察 | 耗时 |", "|---|---|---|---|---|---|"]
    L += [f"| {i} | {t['stage']} | {t['tool']} | {t['thought']} | {str(t['observation'])[:160].replace('|', '/')} | {t['ms']}ms |"
          for i, t in enumerate(v.trace, 1)]
    return "\n".join(L)


def to_json(v: Verdict) -> str:
    return json.dumps({
        "content_id": v.content_id, "verdict": v.verdict, "trust_score": v.trust_score, "risk": v.risk, "level": v.level,
        "dims": v.dims, "tags": v.tags, "reasons": v.reasons, "actions": v.actions, "llm_review": v.llm_review,
        "evidences": [{k: e.get(k) for k in ("source", "name", "category", "score", "confidence", "summary", "regions")} for e in v.evidences],
        "trace": v.trace}, ensure_ascii=False, indent=1, default=str)
