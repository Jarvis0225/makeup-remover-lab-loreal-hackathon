"""图像取证：ELA、噪声一致性、复制-移动、元数据、频域 AIGC 线索。

每个检测器返回 Evidence 字典：
    {name, score(0-1), confidence(0-1), summary, details, regions(可选 bbox 列表)}
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field

import cv2
import numpy as np
from PIL import ExifTags, Image

BLOCK = 32

EDIT_SOFTWARE = ["photoshop", "meitu", "美图", "lightroom", "snapseed", "picsart", "faceapp",
                 "facetune", "beautycam", "gimp", "醒图", "photoroom", "remini"]
AIGC_SOFTWARE = ["midjourney", "stable diffusion", "dall", "novelai", "comfyui", "firefly",
                 "通义万相", "wanx", "flux", "sdxl", "dreamina", "即梦", "可灵", "kling", "imagen"]
AIGC_PNG_KEYS = ["parameters", "prompt", "workflow", "sd-metadata", "invokeai_metadata", "dream"]


@dataclass
class ImageReport:
    evidences: list = field(default_factory=list)
    heatmap: np.ndarray | None = None          # 叠加热力图 (RGB)
    ela_vis: np.ndarray | None = None
    noise_vis: np.ndarray | None = None
    copymove_vis: np.ndarray | None = None
    trufor_vis: np.ndarray | None = None
    regions: list = field(default_factory=list)  # 可疑区域 bbox (x,y,w,h)
    meta: dict = field(default_factory=dict)


def _ev(name, score, confidence, summary, details=None, regions=None, category="tamper"):
    return {"name": name, "score": float(np.clip(score, 0, 1)), "confidence": float(np.clip(confidence, 0, 1)),
            "summary": summary, "details": details or {}, "regions": regions or [], "category": category}


def _robust_z(x: np.ndarray, floor: float = 0.0) -> np.ndarray:
    med = np.median(x)
    mad = max(np.median(np.abs(x - med)) * 1.4826, floor, 1e-6)
    return (x - med) / mad


def _block_stat(gray: np.ndarray, fn, block=BLOCK) -> np.ndarray:
    h, w = gray.shape
    hb, wb = h // block, w // block
    g = gray[: hb * block, : wb * block].reshape(hb, block, wb, block)
    return fn(g, axis=(1, 3))


def _anomaly_regions(zmap: np.ndarray, thr: float, block=BLOCK, min_blocks=2):
    mask = (zmap > thr).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    out = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area >= min_blocks:
            out.append((int(x * block), int(y * block), int(w * block), int(h * block)))
    return out, mask


# ---------------------------------------------------------------- ELA
def error_level_analysis(img: Image.Image, quality=90):
    rgb = img.convert("RGB")
    buf = io.BytesIO()
    rgb.save(buf, "JPEG", quality=quality)
    re = Image.open(io.BytesIO(buf.getvalue()))
    diff = np.abs(np.asarray(rgb, np.float32) - np.asarray(re, np.float32)).max(axis=2)
    gray = np.asarray(rgb.convert("L"), np.float32)
    grad = np.abs(cv2.Laplacian(gray, cv2.CV_32F, ksize=3))
    blk = _block_stat(diff, np.mean)
    gblk = _block_stat(grad, np.mean)
    # ELA 天然随纹理/边缘增强：先用全图块拟合 ELA~纹理 的关系，只看残差（排除内容影响）
    A = np.stack([np.ones(gblk.size), np.sqrt(gblk.ravel())], 1)
    coef = np.linalg.lstsq(A, blk.ravel(), rcond=None)[0]
    resid = blk - (A @ coef).reshape(blk.shape)
    z = _robust_z(resid, floor=0.05 * float(np.median(blk)) + 0.05)
    # 强边缘块（叠加文字、贴纸描边）ELA 天然偏高，不参与判定，降低图文笔记误报
    z[gblk > np.percentile(gblk, 90)] = 0
    z[[0, -1], :] = 0; z[:, [0, -1]] = 0
    regions, mask = _anomaly_regions(np.abs(z), 6.0, min_blocks=3)
    ratio = mask.mean()
    peak = float(np.percentile(np.abs(z), 99.5)) if z.size else 0
    score = 0.0
    if 0.004 < ratio < 0.3 and peak > 12 and regions:
        score = min(1.0, 0.55 + 0.03 * (peak - 12) + 2.0 * ratio)
    z = np.abs(z)
    vis = np.clip(diff / (diff.max() + 1e-6) * 255 * 1.5, 0, 255).astype(np.uint8)
    vis = cv2.applyColorMap(vis, cv2.COLORMAP_INFERNO)[:, :, ::-1]
    summary = (f"ELA 压缩误差在 {len(regions)} 个局部区域显著偏高（峰值 z={peak:.1f}，异常块占比 {ratio:.1%}），"
               "提示这些区域与整体的压缩历史不一致，可能为后期粘贴/修补。") if score > 0 else \
        f"ELA 压缩误差分布整体均匀（峰值 z={peak:.1f}），未见明显局部二次编辑痕迹。"
    return _ev("ELA 误差水平分析", score, 0.72, summary,
               {"peak_z": round(peak, 2), "anomaly_ratio": round(float(ratio), 4)}, regions), z, vis


# ---------------------------------------------------------------- 噪声一致性
def noise_inconsistency(img: Image.Image):
    gray = np.asarray(img.convert("L"), np.float32)
    resid = gray - cv2.medianBlur(gray.astype(np.uint8), 3).astype(np.float32)
    # 只在非饱和、非平坦区域估计噪声，降低内容影响
    blk_std = _block_stat(resid, np.std)
    blk_lum = _block_stat(gray, np.mean)
    valid = (blk_lum > 15) & (blk_lum < 240)
    vals = blk_std[valid] if valid.any() else blk_std.ravel()
    med = np.median(vals)
    mad = np.median(np.abs(vals - med)) * 1.4826 + 1e-6
    z = (blk_std - med) / mad
    z[~valid] = 0
    low_z = -z  # 噪声异常低（磨皮/AI 平滑/粘贴自干净素材）
    regions_low, mask_low = _anomaly_regions(low_z, 3.0, min_blocks=4)
    regions_high, mask_high = _anomaly_regions(z, 4.5, min_blocks=3)
    ratio = float(mask_low.mean() + mask_high.mean())
    score = 0.0
    # 整图几乎无噪声（合成/AI 图）时局部噪声对比失去意义，交由 AIGC 线索处理
    if med > 0.8 and 0.05 < ratio < 0.45 and (regions_low or regions_high):
        score = min(1.0, 0.35 + 2.0 * ratio)
    vis = np.clip(np.abs(resid) * 12, 0, 255).astype(np.uint8)
    vis = cv2.applyColorMap(vis, cv2.COLORMAP_JET)[:, :, ::-1]
    parts = []
    if regions_low:
        parts.append(f"{len(regions_low)} 处区域噪声显著偏低（疑似局部磨皮/涂抹或粘贴自无噪声素材）")
    if regions_high:
        parts.append(f"{len(regions_high)} 处区域噪声显著偏高（疑似来自不同相机/压缩源的拼接）")
    summary = ("传感器噪声在全图不一致：" + "；".join(parts) + "。") if score > 0 else "全图传感器噪声水平一致，未见拼接或局部修饰造成的噪声断层。"
    return _ev("噪声一致性分析", score, 0.65, summary,
               {"global_noise": round(float(med), 3), "inconsistent_ratio": round(ratio, 4)},
               regions_low + regions_high), np.maximum(np.abs(z), 0), vis, float(med)


# ---------------------------------------------------------------- 复制-移动
def copy_move(img: Image.Image, max_side=1024):
    rgb = np.asarray(img.convert("RGB"))
    scale = min(1.0, max_side / max(rgb.shape[:2]))
    small = cv2.resize(rgb, None, fx=scale, fy=scale) if scale < 1 else rgb
    gray = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY)
    sift = cv2.SIFT_create(nfeatures=4000, contrastThreshold=0.02)
    kps, des = sift.detectAndCompute(gray, None)
    vis = small.copy()
    if des is None or len(kps) < 10:
        return _ev("复制-移动检测", 0, 0.3, "关键点不足，无法进行复制-移动检测。"), vis
    matcher = cv2.BFMatcher(cv2.NORM_L2)
    knn = matcher.knnMatch(des, des, k=3)
    pairs = []
    for ms in knn:
        for m in ms[1:]:
            p1, p2 = np.array(kps[m.queryIdx].pt), np.array(kps[m.trainIdx].pt)
            if np.linalg.norm(p1 - p2) > 25 and m.distance < 0.55 * max(ms[-1].distance, 1e-6) + 60:
                if m.distance < 120:
                    pairs.append((p1, p2))
    # 按位移向量聚类：真实复制-移动会产生大量相同位移
    groups: dict = {}
    for p1, p2 in pairs:
        d = p2 - p1
        if d[0] < 0 or (d[0] == 0 and d[1] < 0):
            d, p1, p2 = -d, p2, p1
        key = (int(round(d[0] / 6)), int(round(d[1] / 6)))
        groups.setdefault(key, []).append((p1, p2))
    best = max(groups.values(), key=len) if groups else []
    # 复制-移动应为近似纯平移；前后对比图/同一物体两次拍摄存在旋转缩放，不应视为复制
    transform_ok = False
    norm_pairs = [v for vs in groups.values() for v in vs]
    if len(best) >= 10:
        src = np.float32([a for a, _ in norm_pairs]); dst = np.float32([b for _, b in norm_pairs])
        M, inl = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=2.0)
        if M is not None:
            sc = float(np.hypot(M[0, 0], M[1, 0])); ang = float(np.degrees(np.arctan2(M[1, 0], M[0, 0])))
            transform_ok = abs(sc - 1) < 0.015 and abs(ang) < 1.0 and inl.sum() >= 0.6 * len(best)
            if transform_ok:
                best = [p for p, ok in zip(norm_pairs, inl.ravel()) if ok]
                # 重复文字（如“使用前/使用后”中的相同字）只构成细长小区域，不视为物体级复制
                ext = np.ptp(np.float32([a for a, _ in best]), axis=0)
                transform_ok = min(ext) >= 80
    uniq = {(int(a[0]), int(a[1])) for a, _ in best}
    n = len(uniq) if transform_ok else 0
    regions = []
    # 同款产品、重复图案本身会产生少量匹配，需足够多的同位移特征点才判定
    if n >= 30:
        src = np.array([a for a, _ in best]); dst = np.array([b for _, b in best])
        for pts, color in ((src, (0, 255, 0)), (dst, (255, 0, 0))):
            x0, y0 = pts.min(0); x1, y1 = pts.max(0)
            regions.append(tuple(int(v / scale) for v in (x0, y0, x1 - x0 + 1, y1 - y0 + 1)))
            cv2.rectangle(vis, (int(x0), int(y0)), (int(x1), int(y1)), color, 2)
        for a, b in best[:80]:
            cv2.line(vis, tuple(map(int, a)), tuple(map(int, b)), (255, 255, 0), 1)
    score = 0 if n < 30 else min(1.0, 0.5 + (n - 30) / 60)
    summary = (f"发现 {n} 组位移一致的重复特征点，图像中存在被复制并粘贴到其他位置的区域"
               "（常见于伪造“满柜货品”、遮盖瑕疵、复制产品/批号）。") if score else "未发现同图内区域复制粘贴的特征点群。"
    return _ev("复制-移动检测", score, 0.75, summary, {"matched_groups": n}, regions), vis


# ---------------------------------------------------------------- 元数据
def metadata_check(img: Image.Image, raw: bytes | None):
    info: dict = {"format": img.format, "size": f"{img.width}x{img.height}"}
    exif = {}
    try:
        for k, v in (img.getexif() or {}).items():
            exif[ExifTags.TAGS.get(k, k)] = str(v)[:120]
    except Exception:
        pass
    info["exif"] = exif
    text_chunks = {k: str(v)[:300] for k, v in (img.info or {}).items() if isinstance(v, (str, bytes)) and k not in ("icc_profile", "exif")}
    info["text_chunks"] = text_chunks
    findings, aigc, edit = [], 0.0, 0.0
    software = (exif.get("Software", "") + " " + " ".join(text_chunks.values())).lower()
    for kw in AIGC_SOFTWARE:
        if kw in software:
            findings.append(f"元数据含 AI 生成工具标识「{kw}」"); aigc = max(aigc, 0.95)
    for k in text_chunks:
        if k.lower() in AIGC_PNG_KEYS:
            findings.append(f"PNG 文本块含生成参数字段「{k}」（Stable Diffusion/ComfyUI 等工具特征）"); aigc = max(aigc, 0.95)
    for kw in EDIT_SOFTWARE:
        if kw in software:
            findings.append(f"元数据显示经过编辑软件「{kw}」处理"); edit = max(edit, 0.55)
    if raw is not None:
        low = raw[:200000].lower()
        if b"c2pa" in low or b"jumbf" in low:
            findings.append("文件含 C2PA 内容凭证（Content Credentials），可追溯生成/编辑链路")
            info["c2pa"] = True
        if b"aigc" in low and (b"label" in low or b"contentproducer" in low):
            findings.append("文件含 AIGC 隐式标识字段（符合《人工智能生成合成内容标识办法》元数据标识）"); aigc = max(aigc, 0.9)
    has_cam = any(k in exif for k in ("Make", "Model", "DateTimeOriginal"))
    if not exif:
        findings.append("无 EXIF 拍摄信息（可能被平台压缩剥离，也可能为合成图，仅作弱线索）")
    elif has_cam:
        findings.append(f"含相机拍摄信息：{exif.get('Make', '')} {exif.get('Model', '')} {exif.get('DateTimeOriginal', '')}".strip())
    q = None
    if getattr(img, "quantization", None):
        t = img.quantization.get(0)
        if t:
            q = int(np.clip(100 - (np.mean(list(t)) - 1) * 1.6, 1, 100))
            info["jpeg_quality_est"] = q
    out = []
    if aigc:
        out.append(_ev("元数据：AI 生成标识", aigc, 0.95, "；".join(f for f in findings if "AI" in f or "生成" in f or "AIGC" in f), info, category="aigc"))
    if edit:
        out.append(_ev("元数据：编辑软件痕迹", edit, 0.7, "；".join(f for f in findings if "编辑软件" in f), info, category="tamper"))
    out.append(_ev("元数据概览", 0.0, 0.3, "；".join(findings) or "元数据无异常", info, category="info"))
    return out, info, has_cam


# ---------------------------------------------------------------- 频域 / AIGC 统计线索
def aigc_statistics(img: Image.Image, global_noise: float, has_cam: bool):
    gray = np.asarray(img.convert("L"), np.float32)
    h, w = gray.shape
    g = gray[: min(h, 1024), : min(w, 1024)]
    g = g - cv2.GaussianBlur(g, (0, 0), 2)
    spec = np.log1p(np.abs(np.fft.fftshift(np.fft.fft2(g))))
    cy, cx = np.array(spec.shape) // 2
    yy, xx = np.indices(spec.shape)
    r = np.hypot(yy - cy, xx - cx)
    ring = (r > min(cy, cx) * 0.25)
    sv = spec[ring]
    # 生成模型上采样造成的周期性亮点：频谱中远离中心的孤立峰值
    thr = sv.mean() + 6 * sv.std()
    peaks = int((spec[ring] > thr).sum())
    cues, s = [], 0.0
    if peaks > 12:
        cues.append(f"频谱存在 {peaks} 个周期性高频峰（上采样/反卷积网格伪影特征）"); s += 0.35
    if global_noise < 0.3:
        cues.append(f"全图几乎不存在传感器噪声（σ≈{global_noise:.2f}，真实照片即便经平台压缩通常 >1），纹理过度平滑"); s += 0.45
    elif global_noise < 0.55:
        cues.append(f"全图传感器噪声极低（σ≈{global_noise:.2f}），纹理过度平滑，不符合真实相机成像"); s += 0.3
    if (w % 64 == 0 and h % 64 == 0) and (w, h) in {(512, 512), (768, 768), (1024, 1024), (1024, 1536), (1536, 1024), (832, 1216), (1216, 832), (896, 1152), (1152, 896), (2048, 2048)}:
        cues.append(f"分辨率 {w}x{h} 为主流生成模型的典型输出尺寸"); s += 0.15
    if not has_cam:
        s += 0.05
    s = min(s, 0.85)
    summary = ("AIGC 统计线索：" + "；".join(cues) + "。") if cues else "频谱与纹理统计未见典型生成模型伪影。"
    return _ev("频域/纹理 AIGC 线索", s, 0.65, summary, {"fft_peaks": peaks, "noise_sigma": round(global_noise, 3)}, category="aigc"), spec


# ---------------------------------------------------------------- 汇总
def _overlay(rgb: np.ndarray, zmaps: list[np.ndarray], regions):
    h, w = rgb.shape[:2]
    acc = np.zeros((h, w), np.float32)
    for z in zmaps:
        zz = cv2.resize(np.clip(z, 0, 10).astype(np.float32), (w, h), interpolation=cv2.INTER_LINEAR)
        acc = np.maximum(acc, zz)
    acc = np.clip((acc - 2.5) / 5, 0, 1)
    heat = cv2.applyColorMap((acc * 255).astype(np.uint8), cv2.COLORMAP_JET)[:, :, ::-1]
    out = (rgb * (1 - 0.45 * acc[..., None]) + heat * 0.45 * acc[..., None]).astype(np.uint8)
    for (x, y, bw, bh) in regions:
        cv2.rectangle(out, (x, y), (x + bw, y + bh), (255, 0, 80), max(2, w // 300))
    return out


def analyze_image(img: Image.Image, raw: bytes | None = None) -> ImageReport:
    rep = ImageReport()
    work = img.convert("RGB")
    if max(work.size) > 1600:
        s = 1600 / max(work.size)
        work = work.resize((int(work.width * s), int(work.height * s)), Image.LANCZOS)
    meta_evs, info, has_cam = metadata_check(img, raw)
    ela_ev, ela_z, rep.ela_vis = error_level_analysis(work)
    noise_ev, noise_z, rep.noise_vis, gnoise = noise_inconsistency(work)
    cm_ev, rep.copymove_vis = copy_move(work)
    aigc_ev, _ = aigc_statistics(img, gnoise, has_cam)
    # 对于整图都很“干净”的 AI 图，ELA/噪声局部异常意义下降，避免重复计分
    rep.evidences = [ela_ev, noise_ev, cm_ev, aigc_ev] + meta_evs
    rep.regions = [r for e in (ela_ev, noise_ev, cm_ev) if e["score"] > 0 for r in e["regions"]]
    rep.heatmap = _overlay(np.asarray(work), [ela_z if ela_ev["score"] else ela_z * 0,
                                              noise_z if noise_ev["score"] else noise_z * 0],
                           rep.regions)
    rep.meta = info
    rep.meta["work_size"] = work.size
    return rep


def crop_region(img: Image.Image, region, work_size, pad=0.25) -> Image.Image:
    sx, sy = img.width / work_size[0], img.height / work_size[1]
    x, y, w, h = region
    px, py = w * pad, h * pad
    box = (max(0, int((x - px) * sx)), max(0, int((y - py) * sy)),
           min(img.width, int((x + w + px) * sx)), min(img.height, int((y + h + py) * sy)))
    return img.crop(box)
