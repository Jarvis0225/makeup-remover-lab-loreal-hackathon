"""TruFor 深度篡改检测与定位（集成开源项目 grip-unina/TruFor，CVPR 2023）。

上游代码：third_party/TruFor/test_docker/src（GRIP-UNINA 许可：仅限非营利/研究用途，需保留版权声明并注明原作者）。
权重：third_party/weights/trufor.pth.tar（官方下载地址见 TruFor README）。
输出：像素级篡改概率图 + 整图完整性分数 + 可靠性图。未安装 torch 或缺少权重时自动不可用，Agent 回退到传统取证。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2] / "third_party"
SRC = ROOT / "TruFor" / "test_docker" / "src"
WEIGHTS = Path(os.getenv("TRUFOR_WEIGHTS", ROOT / "weights" / "trufor.pth.tar"))
MAX_SIDE = int(os.getenv("TRUFOR_MAX_SIDE", "1024"))

_model = None
_err: str | None = None


def available() -> bool:
    try:
        import torch  # noqa: F401
    except ImportError:
        return False
    return SRC.exists() and WEIGHTS.exists()


def _device():
    import torch
    pref = os.getenv("TRUFOR_DEVICE", "auto")
    if pref != "auto":
        return pref
    return "cuda" if torch.cuda.is_available() else ("mps" if torch.backends.mps.is_available() else "cpu")


def _load():
    global _model, _err
    if _model is not None or _err:
        return _model
    try:
        import torch
        if str(SRC) not in sys.path:
            sys.path.insert(0, str(SRC))
        from config import _C
        from models.cmx.builder_np_conf import myEncoderDecoder
        cfg = _C.clone()
        cfg.defrost()
        cfg.merge_from_file(str(SRC / "trufor.yaml"))
        model = myEncoderDecoder(cfg=cfg)
        # 安全加载：只放行 checkpoint 元数据里的 numpy 标量/dtype，拒绝任意代码执行
        from numpy._core.multiarray import scalar
        safe = [(scalar, "numpy.core.multiarray.scalar"), np.dtype] + [type(np.dtype(t)) for t in ("f8", "f4", "i8", "i4")]
        with torch.serialization.safe_globals(safe):
            ckpt = torch.load(WEIGHTS, map_location="cpu", weights_only=True)
        model.load_state_dict(ckpt["state_dict"])
        _model = model.eval().to(_device())
    except Exception as e:
        _err = f"{type(e).__name__}: {e}"
    return _model


def infer(img: Image.Image):
    """返回 {score, map(H,W), conf(H,W), size} ；map/conf 对应缩放后的工作尺寸。"""
    import torch
    from torch.nn import functional as F
    model = _load()
    if model is None:
        raise RuntimeError(f"TruFor 加载失败：{_err}")
    rgb = img.convert("RGB")
    if max(rgb.size) > MAX_SIDE:
        s = MAX_SIDE / max(rgb.size)
        rgb = rgb.resize((int(rgb.width * s), int(rgb.height * s)), Image.LANCZOS)
    x = torch.tensor(np.asarray(rgb).transpose(2, 0, 1), dtype=torch.float)[None] / 256.0
    with torch.no_grad():
        pred, conf, det, _ = model(x.to(next(model.parameters()).device))
    return {"score": float(torch.sigmoid(det).item()),
            "map": F.softmax(pred[0], dim=0)[1].cpu().numpy(),
            "conf": torch.sigmoid(conf[0, 0]).cpu().numpy(),
            "size": rgb.size}


def evidence(img: Image.Image, work_size):
    """转换为 Agent 证据格式，区域坐标映射到取证模块的工作尺寸。"""
    r = infer(img)
    m, c = r["map"], r["conf"]
    sx, sy = work_size[0] / r["size"][0], work_size[1] / r["size"][1]
    mask = ((m > 0.5) & (c > 0.5)).astype(np.uint8)
    n, _, stats, _ = cv2.connectedComponentsWithStats(cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8)))
    min_area = 0.002 * mask.size
    regions = [(int(x * sx), int(y * sy), int(w * sx), int(h * sy)) for x, y, w, h, a in stats[1:] if a >= min_area]
    ratio = float(mask.mean())
    raw_score = r["score"]
    # 实测真实照片 0.1~0.3，经平台缩放后可达 0.45：低于 0.45 视为无证据，避免弱分数在融合中累加误报
    score = float(np.clip((raw_score - 0.45) / 0.55, 0, 1))
    tampered = raw_score >= 0.5
    summary = (f"TruFor 深度取证模型判定整图篡改概率 {raw_score:.0%}，定位到 {len(regions)} 处高置信篡改区域（占图 {ratio:.1%}），"
               "该模型融合 RGB 语义与 Noiseprint++ 相机指纹，对拼接、局部修补、AI 局部编辑均敏感。") if tampered else \
        f"TruFor 深度取证模型判定整图篡改概率 {raw_score:.0%}，相机指纹（Noiseprint++）整体一致，未定位到可靠篡改区域。"
    heat = cv2.applyColorMap((np.clip(m, 0, 1) * 255).astype(np.uint8), cv2.COLORMAP_JET)[:, :, ::-1]
    heat = cv2.resize(heat, tuple(work_size))
    ev = {"name": "TruFor 深度篡改定位", "score": score, "confidence": 0.8, "category": "tamper", "summary": summary,
          "details": {"integrity_score": round(raw_score, 4), "tampered_ratio": round(ratio, 4), "model": "TruFor (CVPR 2023)"},
          "regions": regions if tampered else []}
    return ev, heat
