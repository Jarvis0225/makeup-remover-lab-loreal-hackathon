"""种草文案检测：违规宣称 / 未标广告 / AI 生成文案统计特征。"""
from __future__ import annotations

import re

import numpy as np

from .knowledge import (AD_LABELS, AI_LABELS, AI_PHRASES, COMMERCIAL_CUES, CONTEXT_EXEMPT, DETAIL_CUES, EVASION_RE, LEXICON,
                        NEGATION_BEFORE, REGULATIONS, SUGGEST)

EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF\u2B50\u2728]")
SENT_SPLIT = re.compile(r"[。！？!?\n～~]+")


def _ev(name, score, confidence, summary, details=None, category="claim", spans=None, laws=None):
    return {"name": name, "score": float(np.clip(score, 0, 1)), "confidence": float(confidence), "summary": summary,
            "details": details or {}, "category": category, "spans": spans or [], "laws": laws or []}


def _exempt(text: str, m) -> str | None:
    word, after = m.group(0), text[m.end():m.end() + 6]
    for wpat, apat, why in CONTEXT_EXEMPT:
        if re.search(wpat, word) and re.search(apat, after):
            return why
    if NEGATION_BEFORE.search(text[max(0, m.start() - 4):m.start()]):
        return "否定语境"
    return None


def find_violations(text: str, exempted: list | None = None):
    hits = []
    for pat, cat, sev, law, why in LEXICON:
        for m in re.finditer(pat, text, flags=re.I):
            ex = _exempt(text, m)
            if ex:
                if exempted is not None:
                    exempted.append({"text": m.group(0), "context": text[max(0, m.start() - 6):m.end() + 6], "reason": ex})
                continue
            hits.append({"text": m.group(0), "start": m.start(), "end": m.end(), "category": cat,
                         "severity": sev, "law": law, "reason": why, "suggest": SUGGEST.get(m.group(0), "")})
    # 去除被更长片段覆盖的重复命中
    hits.sort(key=lambda h: (h["start"], -(h["end"] - h["start"])))
    out, last_end = [], -1
    for h in hits:
        if h["start"] >= last_end:
            out.append(h); last_end = h["end"]
    return out


def claim_evidence(text: str, exempted: list | None = None):
    hits = find_violations(text, exempted)
    evs = []
    if hits:
        by_cat: dict = {}
        for h in hits:
            by_cat.setdefault(h["category"], []).append(h)
        # 同一词重复出现只计一次，避免“美白”说 7 遍被叠加成极高风险
        uniq = {(h["text"], h["category"]): h for h in hits}.values()
        sev = 1 - np.prod([1 - h["severity"] * 0.8 for h in uniq])
        # 仅命中“特殊功效宣称”（需核验特证，并非直接违规）时封顶为中风险
        if all(h["category"] == "特殊功效宣称" for h in uniq):
            sev = min(sev, 0.45)
        laws = sorted({h["law"] for h in hits})
        lines = [f"【{c}】" + "、".join(f"“{h['text']}”" for h in hs[:5]) + f"——{hs[0]['reason']}" for c, hs in by_cat.items()]
        evs.append(_ev("违规/夸大宣称", sev, 0.85, "；".join(lines), {"hits": len(hits), "by_category": {k: len(v) for k, v in by_cat.items()}},
                       spans=hits, laws=[REGULATIONS[k] for k in laws]))
    ev_hits = sorted(set(m.group(0) for m in re.finditer(EVASION_RE, text)))
    if ev_hits:
        evs.append(_ev("谐音/代称规避审核", 0.55, 0.65, f"使用“{'、'.join(ev_hits)}”等谐音或代称指代直播间/电商平台，常见于规避平台审核的软广带货。",
                       laws=[REGULATIONS["net_ad_9"]]))
    commercial = any(re.search(p, text) for p in COMMERCIAL_CUES) or bool(ev_hits)
    labeled = any(re.search(p, text, re.I) for p in AD_LABELS)
    if commercial and not labeled:
        evs.append(_ev("疑似未标注广告", 0.6, 0.7, "文案含购买/价格/链接等带货信号，但未标明“广告/合作”，可能为软广伪装成真实测评。",
                       laws=[REGULATIONS["net_ad_9"]]))
    return evs, hits


def aigc_text_features(text: str):
    sents = [s.strip() for s in SENT_SPLIT.split(text) if len(s.strip()) >= 2]
    n_chars = max(len(text), 1)
    lens = np.array([len(s) for s in sents]) if sents else np.array([n_chars])
    cv = float(lens.std() / (lens.mean() + 1e-6))
    phrase_hits = [p for p in AI_PHRASES if p in text]
    phrase_density = len(phrase_hits) / (n_chars / 100)
    detail = sum(len(re.findall(p, text)) for p in DETAIL_CUES)
    detail_density = detail / (n_chars / 100)
    emojis = EMOJI_RE.findall(text)
    lines = [l for l in text.split("\n") if l.strip()]
    emoji_line_start = sum(1 for l in lines if EMOJI_RE.match(l.strip())) / max(len(lines), 1)
    structured = bool(re.search(r"(^|\n)\s*([1-9][.、]|[①②③④⑤]|[一二三四五]、)", text))
    ai_label = any(re.search(p, text, re.I) for p in AI_LABELS)

    cues, s = [], 0.0
    if len(sents) >= 4 and cv < 0.35:
        cues.append(f"句长高度均匀（变异系数 {cv:.2f}），缺少人类写作的长短起伏"); s += 0.22
    if phrase_density > 1.2:
        cues.append(f"大模型惯用表达密集（{len(phrase_hits)} 处：{'、'.join(phrase_hits[:6])}）"); s += min(0.35, 0.1 * phrase_density)
    if detail_density < 0.4 and n_chars > 80:
        cues.append("缺少肤质、用量、价格、使用瑕疵等第一人称具体体验细节"); s += 0.2
    if emoji_line_start > 0.5 and len(lines) >= 4:
        cues.append(f"{emoji_line_start:.0%} 的段落以 emoji 开头，呈模板化排版"); s += 0.12
    if structured and phrase_density > 0.8:
        cues.append("“首先/其次/总之”或编号式结构化行文"); s += 0.1
    s = float(np.clip(s, 0, 0.9))
    summary = ("AI 生成文案线索：" + "；".join(cues) + "。") if cues else "文案具有个人化细节与自然的表达起伏，未见明显 AI 生成特征。"
    feats = {"sent_len_cv": round(cv, 3), "ai_phrase_density": round(phrase_density, 2), "detail_density": round(detail_density, 2),
             "emoji_count": len(emojis), "ai_label_present": ai_label}
    evs = [_ev("AI 生成文案统计特征", s, 0.5, summary, feats, category="aigc")]
    if s >= 0.4 and not ai_label:
        evs.append(_ev("AI 内容未标识", 0.35, 0.45, "文案疑似 AI 生成，但未添加“AI 生成”显式标识。", category="aigc",
                       laws=[REGULATIONS["aigc_label"]]))
    return evs, feats


def analyze_text(text: str):
    text = text or ""
    exempted: list = []
    claim_evs, hits = claim_evidence(text, exempted)
    ai_evs, feats = aigc_text_features(text)
    exempted = list({(e["text"], e["context"]): e for e in exempted}.values())
    return {"evidences": claim_evs + ai_evs, "hits": hits, "features": feats, "exempted": exempted}


def highlight_html(text: str, hits) -> str:
    import html
    out, pos = [], 0
    colors = {"极限用语": "#ffe08a", "医疗化宣称": "#ff9a9a", "夸大效果": "#ffb878", "无依据数据": "#ffd6a5",
              "无依据背书": "#ffd6a5", "假货暗语": "#ff7b7b", "站外导流": "#c7d2fe", "虚假评价诱导": "#ff9a9a",
              "特殊功效宣称": "#fde68a", "误导性成分宣称": "#fcd5ce", "诱导消费": "#e0e7ff", "贬低竞品": "#fbcfe8"}
    for h in sorted(hits, key=lambda x: x["start"]):
        out.append(html.escape(text[pos:h["start"]]))
        out.append(f"<mark title='{h['category']}：{h['reason']}' style='background:{colors.get(h['category'], '#ffe08a')};"
                   f"padding:1px 3px;border-radius:3px'>{html.escape(h['text'])}<sup style='font-size:10px;color:#b91c1c'>{h['category']}</sup></mark>")
        pos = h["end"]
    out.append(html.escape(text[pos:]))
    return "".join(out).replace("\n", "<br>")
