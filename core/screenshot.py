"""小红书笔记截图解析：裁出配图 + OCR 提取标题/正文/评论 → 交给核验 Agent。

OCR 使用开源 RapidOCR（https://github.com/RapidAI/RapidOCR，Apache-2.0，本地 ONNX 推理）；
配置了 DashScope Key 时优先用 Qwen-VL 做版面理解，失败自动回退 OCR。
注意：截图是屏幕重新渲染的图像，像素级取证（ELA/噪声/TruFor）只能“尽力而为”，Agent 会自动降低其置信度。
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

import numpy as np
from PIL import Image

from . import llm

_ocr = None
META_RE = re.compile(r"^(\d{4}-\d{1,2}-\d{1,2}|\d{1,2}-\d{1,2}|\d+\s*分钟前|\d+\s*小时前|\d+\s*天前|昨天(\s*\d{1,2}:\d{2})?|刚刚)\s*(\S{0,6})?\s*(回复)?$")
HEADER_RE = re.compile(r"共\s*\d+\s*条评论|\d+\s*条评论|^评论$")
NOISE_RE = re.compile(r"^(\d{1,2}:\d{2}|关注|已关注|说点什么.*|分享|回复|\d+|[•·.。]+|作者|置顶|置顶评论|展开.*|收起|\d+/\d+)$")
AUTHOR_TAG = re.compile(r"\s*作者$")
EDIT_RE = re.compile(r"^(编辑于|发布于)?\s*(\d{4}-)?\d{1,2}-\d{1,2}.*$|^编辑于.*")


def _engine():
    global _ocr
    if _ocr is None:
        from rapidocr_onnxruntime import RapidOCR
        _ocr = RapidOCR()
    return _ocr


def find_photo_band(img: Image.Image, bg_tol=14, min_frac=0.8, gap_ratio=0.04):
    """按行统计“非背景像素占比”，最长的连续高占比行带即配图区域（不依赖 OCR，配图里有字也不受影响）。
    实测：配图行约 100%，低分辨率截图里密集中文行最高约 55%；配图内白色标签/贴纸造成的短暂下降按图高 4% 以内合并。"""
    max_gap = int(gap_ratio * img.height)
    a = np.asarray(img.convert("RGB"), np.int16)
    bg = np.median(a[:, :8].reshape(-1, 3), axis=0)
    nonbg = (np.abs(a - bg).max(axis=2) > bg_tol)
    row = nonbg.mean(axis=1)
    runs, cur = [], None
    for y, v in enumerate(list(row) + [0]):
        if v >= min_frac and cur is None:
            cur = y
        elif v < min_frac and cur is not None:
            runs.append([cur, y]); cur = None
    merged = []
    for r in runs:
        if merged and r[0] - merged[-1][1] < max_gap:
            merged[-1][1] = r[1]
        else:
            merged.append(r)
    y0, y1 = max(merged, key=lambda r: r[1] - r[0]) if merged else (0, 0)
    if y1 - y0 < 0.12 * img.height:
        return None
    cols = nonbg[y0:y1].mean(axis=0)
    xs = np.where(cols > 0.5)[0]
    return (int(xs[0]), y0, int(xs[-1]) + 1, y1) if len(xs) else (0, y0, img.width, y1)


def _to_time(s: str, now: datetime):
    s = s.strip()
    if m := re.match(r"(\d+)\s*分钟前", s):
        return (now - timedelta(minutes=int(m.group(1)))).isoformat()
    if m := re.match(r"(\d+)\s*小时前", s):
        return (now - timedelta(hours=int(m.group(1)))).isoformat()
    if m := re.match(r"(\d+)\s*天前", s):
        return (now - timedelta(days=int(m.group(1)))).isoformat()
    if s.startswith("昨天"):
        return (now - timedelta(days=1)).isoformat()
    if m := re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", s):
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
    if m := re.match(r"(\d{1,2})-(\d{1,2})", s):
        return datetime(now.year, int(m.group(1)), int(m.group(2))).isoformat()
    return None


def _ocr_lines(img: Image.Image):
    res, _ = _engine()(np.asarray(img.convert("RGB")))
    lines = []
    for box, text, score in res or []:
        xs, ys = [p[0] for p in box], [p[1] for p in box]
        lines.append({"x0": min(xs), "y0": min(ys), "x1": max(xs), "y1": max(ys), "h": max(ys) - min(ys), "text": text.strip(), "score": score})
    return sorted(lines, key=lambda l: (round(l["y0"] / 8), l["x0"]))


def parse_ocr(img: Image.Image, now: datetime | None = None) -> dict:
    now = now or datetime.now()
    band = find_photo_band(img)
    lines = [l for l in _ocr_lines(img) if l["text"]]
    W = img.width
    if band:
        lines = [l for l in lines if not (band[1] - 5 <= l["y0"] and l["y1"] <= band[3] + 5)]
    hdr = next((i for i, l in enumerate(lines) if HEADER_RE.search(l["text"])), None)
    n_meta = sum(1 for l in lines if META_RE.match(l["text"]))
    if hdr is None and n_meta >= 2 and not band:
        # 评论续页（往下滑后的截图）：没有“共 N 条评论”标题，顶栏以下全部视为评论区
        bar_y = max((l["y1"] for l in lines if l["text"] in ("关注", "已关注")), default=0.1 * img.height)
        top, rest = [], [l for l in lines if l["y0"] > bar_y]
    else:
        top = lines[:hdr] if hdr is not None else lines
        rest = lines[hdr + 1:] if hdr is not None else []
    if band:
        top = [l for l in top if l["y0"] > band[3]]
    # 正文：去掉 UI 噪声与“编辑于”行；字号最大的首行视为标题
    body = [l for l in top if not NOISE_RE.match(l["text"]) and not EDIT_RE.match(l["text"]) and l["x1"] - l["x0"] > 0.05 * W]
    title = ""
    if body:
        hmax = max(l["h"] for l in body)
        if body[0]["h"] >= 0.9 * hmax and len(body) > 1:
            title = body.pop(0)["text"]
    text = "".join(l["text"] + ("" if l["x1"] > 0.8 * W else "\n") for l in body).strip()
    # 评论：以“日期 地点 回复”行作为一条评论的结束；之前的首行为昵称，其余为内容
    comments, author_comments, buf = [], [], []
    for l in rest:
        t = l["text"]
        if META_RE.match(t) or (re.search(r"回复$", t) and re.match(r"^(\d|昨天|刚刚)", t)):
            if buf:
                user, content = (buf[0], "".join(buf[1:])) if len(buf) > 1 else ("（上一屏截断）", buf[0])
                item = {"user": AUTHOR_TAG.sub("", user), "time": _to_time(t, now), "text": content}
                # 作者本人的回复不是“水军”，但常含带货话术 → 并入文案做宣称检测
                (author_comments if AUTHOR_TAG.search(user) else comments).append(item)
            buf = []
        elif not NOISE_RE.match(t) and not (l["x0"] > 0.85 * W and t.isdigit()):
            buf.append(t)
    if len(buf) > 1:
        comments.append({"user": buf[0], "time": None, "text": "".join(buf[1:])})
    return {"title": title, "text": text, "comments": comments, "author_comments": author_comments,
            "photo_box": band, "method": "RapidOCR", "n_lines": len(lines)}


def parse_vlm(img: Image.Image) -> dict:
    prompt = f"""这是一张小红书笔记详情页截图（宽 {img.width}px，高 {img.height}px）。请提取：
标题、正文（不含话题标签和“编辑于”行）、所有评论（昵称、时间文字、内容），以及笔记配图在截图中的像素坐标。
只输出 JSON：{{"title":"","body":"","comments":[{{"user":"","time":"","text":""}}],"photo_box":[x0,y0,x1,y1]}}"""
    r = llm._chat(llm.VL_MODEL, [{"type": "image_url", "image_url": {"url": llm._img_url(img, 2000)}}, {"type": "text", "text": prompt}])
    if "body" not in r:
        raise ValueError("Qwen-VL 未返回结构化结果")
    now = datetime.now()
    box = r.get("photo_box")
    sx = img.width / min(img.width, 2000) if max(img.size) > 2000 else 1
    return {"title": r.get("title", ""), "text": r.get("body", ""), "method": "Qwen-VL",
            "comments": [{"user": c.get("user", ""), "time": _to_time(c.get("time", ""), now), "text": c.get("text", "")} for c in r.get("comments", [])],
            "photo_box": tuple(int(v * sx) for v in box) if box and len(box) == 4 else find_photo_band(img)}


def parse_screenshot(img: Image.Image, prefer_vlm: bool = True) -> dict:
    out = None
    if prefer_vlm and llm.available():
        try:
            out = parse_vlm(img)
        except Exception as e:
            out = None
            err = str(e)[:80]
    if out is None:
        out = parse_ocr(img)
        if prefer_vlm and llm.available():
            out["note"] = f"Qwen-VL 解析失败，已回退 OCR：{err}"
    box = out.get("photo_box")
    out["photo"] = img.convert("RGB").crop(box) if box else None
    return out


def merge(parsed: list[dict]) -> dict:
    """多张截图（如正文页 + 评论页）合并：标题/正文取第一个非空，评论按内容去重拼接。"""
    title = next((p["title"] for p in parsed if p["title"]), "")
    text = next((p["text"] for p in parsed if p["text"]), "")
    seen, comments, author = set(), [], []
    for p in parsed:
        for c in p["comments"]:
            if c["text"] and c["text"] not in seen:
                seen.add(c["text"]); comments.append(c)
        author += [c["text"] for c in p.get("author_comments", []) if c["text"] not in author]
    if author:
        text = (text + "\n【作者评论区补充】" + "\n".join(author)).strip()
    photos = [p["photo"] for p in parsed if p.get("photo") is not None]
    return {"title": title, "text": text, "comments": comments, "photos": photos, "methods": sorted({p["method"] for p in parsed})}
