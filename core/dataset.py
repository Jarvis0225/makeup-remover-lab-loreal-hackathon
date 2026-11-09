"""数据集加载与批量评测。"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image

from .agent import DIMENSIONS, Content, VerifyAgent

DATA = Path(__file__).resolve().parent.parent / "data"


def load_posts(path: Path = DATA / "posts.json") -> list[dict]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def to_content(p: dict, base: Path = DATA) -> Content:
    imgs = []
    for rel in p.get("images", []):
        fp = base / rel
        raw = fp.read_bytes()
        imgs.append((fp.name, Image.open(fp), raw))
    return Content(id=p["id"], title=p.get("title", ""), text=p.get("text", ""), images=imgs, comments=p.get("comments"))


def evaluate(posts: list[dict], use_llm=False, progress=None, dim_thr=0.4):
    rows, verdicts = [], {}
    for k, p in enumerate(posts):
        v = VerifyAgent(use_llm=use_llm).run(to_content(p))
        verdicts[p["id"]] = v
        pred_dims = [d for d, s in v.dims.items() if s >= dim_thr]
        rows.append({"id": p["id"], "title": p["title"], "label": p["label"], "truth_dims": "、".join(DIMENSIONS[d] for d in p["truth_dims"]),
                     "pred": int(v.risk >= 0.25), "trust_score": v.trust_score, "risk": round(v.risk, 3), "level": v.level,
                     "verdict": v.verdict, "pred_dims": "、".join(DIMENSIONS[d] for d in pred_dims),
                     "action": v.actions.get("platform", [""])[0], **{f"dim_{d}": s for d, s in v.dims.items()},
                     "_truth": p["truth_dims"], "_pred": pred_dims})
        if progress:
            progress((k + 1) / len(posts), p["id"])
    df = pd.DataFrame(rows)
    y, yh = df["label"].values, df["pred"].values
    tp, fp = int(((y == 1) & (yh == 1)).sum()), int(((y == 0) & (yh == 1)).sum())
    fn, tn = int(((y == 1) & (yh == 0)).sum()), int(((y == 0) & (yh == 0)).sum())
    prec = tp / max(tp + fp, 1); rec = tp / max(tp + fn, 1)
    metrics = {"样本数": len(df), "准确率": (tp + tn) / max(len(df), 1), "精确率": prec, "召回率": rec,
               "F1": 2 * prec * rec / max(prec + rec, 1e-9), "confusion": {"TP": tp, "FP": fp, "FN": fn, "TN": tn}}
    dim_rows = []
    for d, name in DIMENSIONS.items():
        t = np.array([d in r for r in df["_truth"]]); pr = np.array([d in r for r in df["_pred"]])
        dtp = int((t & pr).sum())
        dim_rows.append({"维度": name, "真实正例": int(t.sum()), "检出": int(pr.sum()), "命中": dtp,
                         "精确率": round(dtp / max(pr.sum(), 1), 3), "召回率": round(dtp / max(t.sum(), 1), 3)})
    return df.drop(columns=["_truth", "_pred"]), metrics, pd.DataFrame(dim_rows), verdicts
