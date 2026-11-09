"""鲁棒性评测：用未参与阈值标定的新随机种子生成留出集，并模拟平台二次压缩/缩放。

python -m eval.robustness
"""
import io
import json
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image

from core import trufor_tool
from core.image_forensics import analyze_image
from data import build_dataset as B

OUT = Path(__file__).parent
KINDS = {"real": (B.make_real, 0), "ba_real": (lambda i: B.make_retouch(i, False), 0), "splice": (B.make_splice, 1),
         "copymove": (B.make_copymove, 1), "retouch": (lambda i: B.make_retouch(i, True), 1), "aigc": (B.make_aigc, 1)}
TRANSFORMS = {
    "原图": lambda im: im,
    "平台重压缩 Q75": lambda im: _jpeg(im, 75),
    "缩放0.75+Q85": lambda im: _jpeg(im.resize((int(im.width * .75), int(im.height * .75)), Image.BICUBIC), 85),
}


def _jpeg(im, q):
    buf = io.BytesIO()
    im.convert("RGB").save(buf, "JPEG", quality=q)
    return Image.open(io.BytesIO(buf.getvalue()))


def _flag(evs):
    tamper = 1 - np.prod([1 - e["score"] * e["confidence"] for e in evs if e["category"] == "tamper"])
    aigc = 1 - np.prod([1 - e["score"] * e["confidence"] for e in evs if e["category"] == "aigc"])
    return int(max(tamper, aigc) >= 0.4)


def flagged(im, raw):
    """返回 (仅传统取证, 传统取证+TruFor) 两种配置的预测，用于消融对比。"""
    rep = analyze_image(im, raw)
    base = _flag(rep.evidences)
    if not trufor_tool.available():
        return base, base
    ev, _ = trufor_tool.evidence(im, rep.meta["work_size"])
    return base, _flag(rep.evidences + [ev])


def main(n=6, seed_offset=500):
    tmp = Path(tempfile.mkdtemp())
    B.IMG = tmp
    rows = []
    for kind, (fn, label) in KINDS.items():
        for k in range(n):
            p = fn(seed_offset + k)
            raw = p.read_bytes()
            base = Image.open(p)
            for tname, tf in TRANSFORMS.items():
                im = tf(base)
                buf = io.BytesIO()
                fmt = im.format or "PNG"
                im.save(buf, fmt) if tname != "原图" else None
                p_base, p_full = flagged(im, raw if tname == "原图" else buf.getvalue())
                rows.append({"kind": kind, "label": label, "transform": tname, "pred_base": p_base, "pred": p_full})
        print("done", kind, flush=True)
    df = pd.DataFrame(rows)
    df["correct"] = (df["pred"] == df["label"]).astype(int)
    df["correct_base"] = (df["pred_base"] == df["label"]).astype(int)
    tab = df.pivot_table(index="kind", columns="transform", values="correct", aggfunc="mean").round(2)[list(TRANSFORMS)]
    tab_base = df.pivot_table(index="kind", columns="transform", values="correct_base", aggfunc="mean").round(2)[list(TRANSFORMS)]
    acc = df.groupby("transform")["correct"].mean().reindex(list(TRANSFORMS)).round(3)
    acc_base = df.groupby("transform")["correct_base"].mean().reindex(list(TRANSFORMS)).round(3)
    print("== 传统取证 ==\n", tab_base.to_string(), "\n", acc_base.to_string())
    print("== 传统取证 + TruFor ==\n", tab.to_string(), "\n", acc.to_string())
    tab.to_csv(OUT / "robustness_by_kind.csv", encoding="utf-8-sig")
    (OUT / "robustness.json").write_text(json.dumps({
        "per_kind": tab.to_dict(), "overall": acc.to_dict(),
        "per_kind_base": tab_base.to_dict(), "overall_base": acc_base.to_dict(),
        "trufor": trufor_tool.available(), "n_per_kind": n}, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
