"""逐图打印各取证器得分，用于阈值标定。"""
from pathlib import Path

from PIL import Image

from core.image_forensics import analyze_image

for p in sorted((Path(__file__).parent.parent / "data" / "images").glob("*.*")):
    raw = p.read_bytes()
    rep = analyze_image(Image.open(p), raw)
    s = " | ".join(f"{e['name'][:6]}={e['score']:.2f}" for e in rep.evidences if e["category"] != "info")
    det = {e["name"][:4]: e["details"] for e in rep.evidences[:4]}
    print(f"{p.name:26s} {s}\n    {det}")
