"""评论区水军/刷评检测：文本近重复聚类 + 模板化 + 时间爆发 + 账号画像。"""
from __future__ import annotations

import re
from datetime import datetime

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .knowledge import DETAIL_CUES, REGULATIONS

GENERIC = ["好用", "回购", "推荐", "绝了", "yyds", "爱了", "无限回购", "闭眼入", "冲", "必入", "宝藏", "种草了",
           "效果很好", "非常好", "很不错", "值得购买", "物超所值", "正品", "五星", "好评", "效果明显", "已经回购",
           "真的很好用", "强烈推荐", "效果惊人", "白了好多", "皮肤变好"]
NICK_RE = re.compile(r"^(用户|user|手机用户|小红薯|momo|tb)[_\-]?[0-9a-zA-Z]{4,}$|^[a-z]{1,3}\d{6,}$", re.I)


def _parse_time(t):
    if isinstance(t, (int, float)):
        return datetime.fromtimestamp(t)
    if t is None or (isinstance(t, float) and np.isnan(t)) or str(t).strip() in ("", "None", "nan"):
        return None
    try:
        ts = pd.to_datetime(t)
        return None if pd.isna(ts) else ts.to_pydatetime()
    except Exception:
        return None


def parse_comments(raw) -> pd.DataFrame:
    """支持 list[dict] / DataFrame / 纯文本（每行一条，可选 `昵称|时间|内容`）。"""
    if isinstance(raw, pd.DataFrame):
        df = raw.copy()
    elif isinstance(raw, list):
        df = pd.DataFrame([x if isinstance(x, dict) else {"text": str(x)} for x in raw])
    else:
        rows = []
        for i, line in enumerate(str(raw).splitlines()):
            line = line.strip()
            if not line:
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 3:
                rows.append({"user": parts[0], "time": parts[1], "text": "|".join(parts[2:])})
            else:
                rows.append({"user": f"匿名{i}", "time": None, "text": line})
        df = pd.DataFrame(rows)
    for col, default in (("user", ""), ("time", None), ("text", ""), ("account_age_days", np.nan),
                         ("followers", np.nan), ("posts", np.nan)):
        if col not in df:
            df[col] = default
    df["text"] = df["text"].fillna("").astype(str)
    return df.reset_index(drop=True)


def analyze_comments(raw):
    df = parse_comments(raw)
    n = len(df)
    if n == 0:
        return {"evidences": [], "table": df, "clusters": []}
    reasons = [[] for _ in range(n)]
    scores = np.zeros((n, 5))

    # 1) 近重复聚类
    clusters = []
    if n >= 3 and df["text"].str.len().max() >= 2:
        vec = TfidfVectorizer(analyzer="char", ngram_range=(2, 4), min_df=1)
        X = vec.fit_transform(df["text"].str.replace(r"\s+", "", regex=True))
        sim = cosine_similarity(X)
        np.fill_diagonal(sim, 0)
        visited = set()
        for i in range(n):
            if i in visited:
                continue
            members = [i] + [j for j in range(n) if sim[i, j] > 0.55 and j not in visited]
            if len(members) >= 3:
                visited.update(members)
                clusters.append(members)
                for j in members:
                    scores[j, 0] = min(1, 0.45 + 0.08 * len(members))
                    reasons[j].append(f"与另外 {len(members) - 1} 条评论高度雷同（模板复制）")

    # 2) 空泛模板化好评
    generic = np.zeros(n, bool)
    for i, t in enumerate(df["text"]):
        g = sum(1 for w in GENERIC if w in t)
        detail = sum(len(re.findall(p, t)) for p in DETAIL_CUES)
        if g >= 2 and detail == 0 and len(t) < 60:
            generic[i] = True
            scores[i, 1] = min(0.6, 0.2 + 0.1 * g)
            reasons[i].append("空泛夸赞、无具体使用细节")
        if re.search(r"(返现|好评送|加v|私信|v[xX])", t):
            scores[i, 1] = max(scores[i, 1], 0.7)
            reasons[i].append("含返现/导流话术")
    # 2b) 评论区层面的同质化：单条空泛好评可能是真人，但同一评论区大量出现就是刷评信号（无账号/时间信息时尤其关键）
    gen_ratio = float(generic.mean()) if n else 0.0
    if generic.sum() >= 3 and gen_ratio >= 0.1:
        for i in np.where(generic)[0]:
            scores[i, 4] = min(0.6, 0.35 + 0.8 * gen_ratio)
            reasons[i].append(f"评论区同质化空泛好评占比异常（{gen_ratio:.0%}）")

    # 3) 时间爆发
    times = [_parse_time(t) for t in df["time"]]
    burst_info = None
    valid = [(i, t) for i, t in enumerate(times) if t is not None]
    if len(valid) >= 5:
        valid.sort(key=lambda x: x[1])
        ts = np.array([t.timestamp() for _, t in valid])
        win = 600
        best = (0, 0, 0)
        for a in range(len(ts)):
            b = np.searchsorted(ts, ts[a] + win, side="right")
            if b - a > best[0]:
                best = (b - a, a, b)
        span_h = max((ts[-1] - ts[0]) / 3600, 1e-3)
        expected = len(ts) * (win / 3600) / span_h
        if best[0] >= max(5, 3 * expected) and best[0] / len(ts) > 0.25:
            burst_info = {"count": best[0], "start": str(valid[best[1]][1]), "ratio": best[0] / len(ts)}
            for k in range(best[1], best[2]):
                i = valid[k][0]
                scores[i, 2] = 0.4
                reasons[i].append(f"处于 10 分钟内 {best[0]} 条评论的集中爆发时段")

    # 4) 账号画像
    for i, r in df.iterrows():
        s, why = 0.0, []
        if pd.notna(r["account_age_days"]) and r["account_age_days"] < 30:
            s += 0.3; why.append(f"新注册账号（{int(r['account_age_days'])} 天）")
        if pd.notna(r["followers"]) and r["followers"] < 5 and pd.notna(r["posts"]) and r["posts"] < 3:
            s += 0.25; why.append("零粉丝零内容")
        if NICK_RE.match(str(r["user"])):
            s += 0.2; why.append("系统默认/批量昵称")
        if s:
            scores[i, 3] = min(s, 0.7); reasons[i] += why

    total = 1 - np.prod(1 - scores, axis=1)
    df["suspicion"] = total.round(3)
    df["reasons"] = ["；".join(dict.fromkeys(r)) for r in reasons]
    df["label"] = np.where(total >= 0.5, "疑似水军", np.where(total >= 0.3, "存疑", "正常"))
    bot_ratio = float((total >= 0.5).mean())

    evs = []
    summary = [f"共 {n} 条评论，疑似水军 {int((total >= 0.5).sum())} 条（{bot_ratio:.0%}）"]
    if clusters:
        summary.append(f"发现 {len(clusters)} 个雷同评论簇（最大 {max(map(len, clusters))} 条）")
    if burst_info:
        summary.append(f"{burst_info['start'][:16]} 起 10 分钟内集中出现 {burst_info['count']} 条评论")
    # 刷评占比 20% 即达中高风险（真实评论区实测误判率为 0，见 eval/comment_realworld.py）
    score = min(1.0, bot_ratio * 2.5 + (0.15 if clusters else 0) + (0.1 if burst_info else 0))
    if bot_ratio < 0.1 and not clusters:
        score = bot_ratio
    evs.append({"name": "评论区刷评/水军检测", "score": float(score), "confidence": 0.7, "summary": "；".join(summary) + "。",
                "details": {"bot_ratio": round(bot_ratio, 3), "clusters": len(clusters), "burst": burst_info},
                "category": "comment", "laws": [REGULATIONS["net_aucl"], REGULATIONS["aucl_8"]] if score >= 0.3 else []})
    return {"evidences": evs, "table": df, "clusters": clusters, "bot_ratio": bot_ratio}
