"""Markdown → PDF（pandoc 转 HTML + 无头 Chrome 打印）：python -m docs.make_pdf"""
import subprocess
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).parent
CSS = """
body{font-family:'PingFang SC','Hiragino Sans GB',sans-serif;font-size:13px;line-height:1.7;color:#1f2937;max-width:900px;margin:0 auto}
h1{color:#be123c;border-bottom:3px solid #be123c;padding-bottom:6px} h2{color:#be123c;margin-top:28px;border-left:5px solid #be123c;padding-left:10px}
h3{color:#9f1239} table{border-collapse:collapse;width:100%;margin:10px 0;font-size:12px}
th{background:#be123c;color:#fff} th,td{border:1px solid #fecdd3;padding:5px 8px;text-align:left;vertical-align:top}
tr:nth-child(even) td{background:#fff1f2} code,pre{background:#f8fafc;font-size:11.5px} pre{padding:10px;border-radius:6px;white-space:pre-wrap}
blockquote{color:#6b7280;border-left:4px solid #fecdd3;margin:0;padding-left:12px} img{max-width:100%}
"""


def md_to_pdf(md: Path, pdf: Path, title: str):
    html = md.with_suffix(".html")
    css = ROOT / "_pdf.css"
    css.write_text(CSS, encoding="utf-8")
    subprocess.run(["pandoc", str(md), "-s", "-o", str(html), "--metadata", f"pagetitle={title}", "-c", css.name,
                    "--resource-path", str(md.parent)], check=True, cwd=md.parent)
    with sync_playwright() as pw:
        b = pw.chromium.launch(channel="chrome", headless=True)
        p = b.new_page()
        p.goto(html.resolve().as_uri())
        p.wait_for_timeout(500)
        p.pdf(path=str(pdf), format="A4", print_background=True, margin={"top": "16mm", "bottom": "16mm", "left": "14mm", "right": "14mm"})
        b.close()
    html.unlink(); css.unlink()
    return pdf


if __name__ == "__main__":
    print(md_to_pdf(ROOT / "方案说明书.md", ROOT / "BeautyGuard_方案说明书.pdf", "BeautyGuard 方案说明书"))
