"""生成方案文档/PPT 用的取证可视化素材：python -m docs.make_assets"""
from pathlib import Path

import numpy as np
from PIL import Image

from core.image_forensics import analyze_image

ROOT = Path(__file__).parent
IMG = ROOT.parent / "data" / "images"
OUT = ROOT / "assets"


def panel(name, views):
    rep = analyze_image(Image.open(IMG / name), (IMG / name).read_bytes())
    ims = [Image.open(IMG / name).convert("RGB").resize(rep.meta["work_size"])] + [Image.fromarray(getattr(rep, v)) for v in views]
    h = 360
    ims = [im.resize((int(im.width * h / im.height), h)) for im in ims]
    canvas = Image.new("RGB", (sum(i.width for i in ims) + 10 * (len(ims) - 1), h), "white")
    x = 0
    for im in ims:
        canvas.paste(im, (x, 0)); x += im.width + 10
    canvas.save(OUT / f"{Path(name).stem}_panel.png")


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    panel("splice_00.jpg", ["heatmap", "ela_vis"])
    panel("retouch_00.jpg", ["heatmap", "noise_vis"])
    panel("copymove_00.jpg", ["copymove_vis"])
    panel("aigc_01.png", ["noise_vis"])
    print("ok", sorted(p.name for p in OUT.iterdir()))
