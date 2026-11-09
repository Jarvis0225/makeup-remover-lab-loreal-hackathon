"""对按赛题格式组织的测试数据包（sample_xxx 文件夹）逐条运行核验 Agent 并对照 README 真值：
python -m eval.run_package <数据包目录>   （默认 data/test_package）
"""
import io
import re
import sys
from pathlib import Path

import pandas as pd
from PIL import Image

from core.agent import Content, VerifyAgent

DEFAULT = Path(__file__).resolve().parents[1] / "data" / "test_package"


def load_sample(d: Path) -> tuple[Content, dict]:
    meta = dict(re.findall(r"^(\S+?): (.+)$", (d / "README.txt").read_text(encoding="utf-8"), re.M)) if (d / "README.txt").exists() else {}
    title, text = "", ""
    if (d / "正文.txt").exists():
        head, _, body = (d / "正文.txt").read_text(encoding="utf-8").partition("\n\n")
        title, text = head.strip(), body.strip()
    comments = None
    if (d / "评论_账号信息.csv").exists():
        comments = pd.read_csv(d / "评论_账号信息.csv").drop(columns=["is_shill"], errors="ignore")
    elif (d / "评论.txt").exists():
        comments = (d / "评论.txt").read_text(encoding="utf-8")
    imgs = [(f.name, Image.open(f), f.read_bytes()) for f in sorted(d.glob("image_*"))]
    shots = sorted(d.glob("screenshot_*"))
    is_shot = bool(shots)
    if shots:
        from core.screenshot import merge, parse_screenshot
        m = merge([parse_screenshot(Image.open(f)) for f in shots])
        title, text = title or m["title"], text or m["text"]
        comments = comments if comments is not None else (m["comments"] or None)
        for k, ph in enumerate(m["photos"], 1):
            buf = io.BytesIO(); ph.save(buf, "PNG")
            imgs.append((f"截图配图{k}.png", ph, buf.getvalue()))
    return Content(d.name, title, text, imgs, comments, meta={"screenshot": is_shot}), meta


def main():
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    rows = []
    for d in sorted(p for p in root.iterdir() if p.is_dir() and p.name.startswith("sample_")):
        c, meta = load_sample(d)
        v = VerifyAgent(use_llm=False).run(c)
        truth = meta.get("是否为伪造样本", "")
        rows.append({"样本": d.name, "真值": truth, "结论": v.verdict, "可信分": v.trust_score, "风险等级": v.level,
                     "检出问题": "、".join(v.tags) or "无", "真值问题": meta.get("问题维度", ""), "首要处置": v.actions.get("platform", [""])[0]})
        print(f"{d.name}  真值={truth[:4]:<4}  {v.verdict}  可信分 {v.trust_score:3d}  {rows[-1]['检出问题']}", flush=True)
    df = pd.DataFrame(rows)
    out = root / "核验结果.csv"
    df.to_csv(out, index=False, encoding="utf-8-sig")
    labeled = df[df["真值"].isin(["是", "否"])]
    acc = ((labeled["真值"] == "是") == (labeled["结论"] != "真实可信")).mean() if len(labeled) else float("nan")
    print(f"\n共 {len(df)} 条；有明确真值的 {len(labeled)} 条中判定准确率 {acc:.1%}；结果已写入 {out}")


if __name__ == "__main__":
    main()
