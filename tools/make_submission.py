"""组装交给评委的提交包：python -m tools.make_submission

输出：../BeautyGuard_赛题2_提交包/（文件夹）与 ../BeautyGuard_赛题2_提交包.zip
文件按编号排序，演示视频排在最前；源代码不含虚拟环境、模型权重与临时文件。
"""
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
OUT = ROOT.parent / "BeautyGuard_赛题2_提交包"
ZIP = OUT.with_suffix(".zip")
CODE_EXCLUDE_DIRS = {"__pycache__", "build", "test_package", ".ipynb_checkpoints", "assets"}
CODE_EXCLUDE_FILES = {".DS_Store"}
CODE_EXCLUDE_SUFFIX = {".mp4", ".zip", ".pptx", ".pdf", ".pyc"}

FILES = [
    ("01_【演示视频】BeautyGuard_核心功能演示.mp4", DOCS / "BeautyGuard_演示视频.mp4"),
    ("02_【展示PPT】BeautyGuard.pptx", DOCS / "BeautyGuard_答辩.pptx"),
    ("02_【展示PPT】BeautyGuard（PDF版，字体已嵌入）.pdf", DOCS / "BeautyGuard_答辩.pdf"),
    ("03_【测试数据包】BeautyGuard_测试数据包.zip", DOCS / "BeautyGuard_测试数据包.zip"),
    ("04_【方案说明书】BeautyGuard.pdf", DOCS / "BeautyGuard_方案说明书.pdf"),
]

GUIDE = """BeautyGuard · 懂美妆内容生态的 AI 鉴真 Agent
欧莱雅第二届美妆科技黑客松 · 赛题2「信任守护师 —— 创造者的 AI 卫士」
队伍：卸妆水研究所

========================================
▶ 建议评委先看：01_【演示视频】（约 5 分钟，中文配音 + 字幕）
========================================

提交内容
  01_【演示视频】  实际使用演示：核心案例 → 真实测评不误伤 → TruFor 篡改定位 → 小红书截图核验 → 数据集闭环
  02_【展示PPT】   基于官方模板：作品背景、技术实现方式、作品使用场景、未来完善方向（另附字体已嵌入的 PDF 版）
  03_【测试数据包】21 条样本（sample_001…021），每条含 正文.txt / 评论.txt / 图片 / README.txt（来源、类型、是否伪造、伪造方式）
                   覆盖种草内容核验、评论区真实性核验、AI 生成视觉素材鉴伪三大场景，含边缘场景
  04_【方案说明书】完整技术方案、评测结果与局限说明
  05_【源代码与运行指南】可运行 Demo 源码，运行方法见压缩包内 README.md

一句话介绍
  多模态检测（TruFor 深度篡改定位 + ELA/噪声/复制-移动/元数据取证 + 违规宣称×法规库 + 水军检测）
  → Agent 自适应深挖与证据融合 → 四级风险决策 → 平台/创作者/消费者三方处置建议，全程可解释、可审计。

技术合规
  全部使用开源模型：TruFor（CVPR 2023）、RapidOCR；可选开源 Qwen2.5-VL / Qwen2.5（开源权重）。不依赖闭源模型。
  第三方组件与许可证见源码包内 THIRD_PARTY.md。

快速运行（详见源码包 README.md）
  cd beautyguard
  pip install -r requirements.txt
  streamlit run app.py          → 浏览器打开 http://localhost:8501
  python -m eval.run_package <测试数据包解压目录>   → 对测试数据包逐条核验并对照真值

说明
  演示数据为程序化合成，演示集指标仅代表流程正确；真实性验证（留出集 + 平台重压缩、1 万条真实小红书评论）见方案说明书第 5 章。
  截图样本中的真实笔记已对头像打码；系统结论为风险提示，不构成对任何品牌或博主的违规认定。
"""


def code_zip(dst: Path):
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(ROOT.rglob("*")):
            rel = f.relative_to(ROOT)
            if not f.is_file() or set(rel.parts) & CODE_EXCLUDE_DIRS or f.name in CODE_EXCLUDE_FILES or f.suffix in CODE_EXCLUDE_SUFFIX:
                continue
            if rel.parts[0] == "video" and rel.suffix not in (".py",):
                continue
            z.write(f, Path("beautyguard") / rel)


def build():
    missing = [str(src) for _, src in FILES if not src.exists()]
    if missing:
        raise SystemExit(f"缺少文件：{missing}")
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()
    (OUT / "00_请先看我.txt").write_text(GUIDE, encoding="utf-8")
    for name, src in FILES:
        shutil.copy(src, OUT / name)
    code_zip(OUT / "05_【源代码与运行指南】BeautyGuard_源码.zip")
    if ZIP.exists():
        ZIP.unlink()
    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_STORED) as z:   # 内含 mp4/zip，已压缩，直接存储
        for f in sorted(OUT.iterdir()):
            z.write(f, Path(OUT.name) / f.name)
    for f in sorted(OUT.iterdir()):
        print(f"{f.stat().st_size / 1e6:8.1f} MB  {f.name}")
    print(f"\n提交包文件夹：{OUT}\n整体压缩包：{ZIP}（{ZIP.stat().st_size / 1e6:.1f} MB）")


if __name__ == "__main__":
    build()
