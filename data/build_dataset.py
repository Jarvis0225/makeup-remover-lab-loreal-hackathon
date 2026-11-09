"""构造带真值标签的美妆内容演示数据集（图片 + 文案 + 评论）。

图片均为程序化渲染，模拟真实相机成像（传感器噪声 + JPEG + EXIF），再施加真实世界常见的造假操作：
  - splice      拼接：把来自其它来源（不同噪声/压缩历史）的产品/标签粘贴进图
  - copymove    复制-移动：复制同图中的产品以伪造“满柜”或遮盖瑕疵
  - retouch     前后对比图局部磨皮美白，夸大功效
  - aigc        AI 生成风格图（无传感器噪声、生成模型典型尺寸、上采样伪影，部分携带生成参数元数据）
运行：python -m data.build_dataset
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timedelta
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from PIL.PngImagePlugin import PngInfo

ROOT = Path(__file__).parent
IMG = ROOT / "images"
FONT_PATHS = ["/System/Library/Fonts/STHeiti Medium.ttc", "/System/Library/Fonts/Hiragino Sans GB.ttc",
              "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc", "C:/Windows/Fonts/msyh.ttc"]
rng = np.random.default_rng(7)
random.seed(7)


def font(size):
    for p in FONT_PATHS:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


PALETTE = [((246, 214, 214), (205, 92, 120)), ((222, 236, 248), (60, 100, 170)), ((240, 232, 214), (170, 120, 60)),
           ((230, 245, 232), (60, 140, 90)), ((245, 225, 240), (150, 70, 140))]
BRANDS = ["LUMIÈRE", "AURA", "SÉRUM", "VELVET", "BLOOM", "ROSÉE"]


def draw_bottle(d: ImageDraw.ImageDraw, x, y, w, h, body, cap, brand):
    d.rounded_rectangle([x + w * 0.3, y, x + w * 0.7, y + h * 0.18], radius=int(w * 0.06), fill=cap)
    d.rounded_rectangle([x, y + h * 0.16, x + w, y + h], radius=int(w * 0.18), fill=body, outline=tuple(max(0, c - 40) for c in body), width=3)
    d.rectangle([x + w * 0.12, y + h * 0.45, x + w * 0.88, y + h * 0.78], fill=(250, 250, 248))
    d.text((x + w * 0.5, y + h * 0.56), brand, fill=cap, font=font(max(12, int(w * 0.14))), anchor="mm")
    d.text((x + w * 0.5, y + h * 0.7), random.choice(["30ml", "50ml", "15ml", "100ml", "40ml"]), fill=(90, 90, 90),
           font=font(max(10, int(w * 0.09))), anchor="mm")
    d.ellipse([x + w * 0.15, y + h * 0.22, x + w * 0.3, y + h * 0.42], fill=tuple(min(255, c + 45) for c in body))


def render_scene(w=1200, h=900, seed=0, n_bottles=3):
    r = np.random.default_rng(seed)
    bg, accent = PALETTE[seed % len(PALETTE)]
    yy = np.linspace(0, 1, h)[:, None, None]
    base = np.array(bg, np.float32) * (1 - 0.18 * yy) + 12 * r.standard_normal((1, w, 1)) * 0.05
    arr = np.repeat(base, w, axis=1) if base.shape[1] == 1 else base
    arr = np.broadcast_to(arr, (h, w, 3)).copy()
    # 桌面与纹理
    arr[int(h * 0.68):] = arr[int(h * 0.68):] * 0.86
    tex = cv2.GaussianBlur(r.standard_normal((h, w)).astype(np.float32), (0, 0), 6) * 25
    arr += tex[..., None]
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    d = ImageDraw.Draw(img)
    boxes = []
    for i in range(n_bottles):
        bw = int(r.integers(150, 210)); bh = int(bw * r.uniform(1.6, 2.1))
        x = int(w * (0.12 + i * 0.28) + r.integers(-20, 20)); y = int(h * 0.7) - bh
        d.ellipse([x - 10, y + bh - 18, x + bw + 30, y + bh + 22], fill=tuple(int(c * 0.72) for c in bg))
        body = tuple(int(c) for c in np.clip(np.array(accent) + r.integers(-30, 30, 3), 0, 255))
        draw_bottle(d, x, y, bw, bh, body, tuple(max(0, c - 60) for c in accent), BRANDS[(seed + i) % len(BRANDS)])
        boxes.append((x, y, bw, bh))
    img = img.filter(ImageFilter.GaussianBlur(1.0))
    return img, boxes


def camera(img: Image.Image, sigma=3.2, seed=0) -> np.ndarray:
    """模拟相机成像：亮度相关的传感器噪声 + 轻微色彩噪声。"""
    r = np.random.default_rng(seed + 1000)
    a = np.asarray(img, np.float32)
    lum = a.mean(axis=2, keepdims=True) / 255
    noise = r.standard_normal(a.shape[:2])[..., None] * sigma * (0.6 + 0.8 * lum) + r.standard_normal(a.shape) * sigma * 0.35
    return np.clip(a + noise, 0, 255).astype(np.uint8)


def exif_for(i):
    ex = Image.Exif()
    ex[0x010F] = random.choice(["Apple", "HUAWEI", "Xiaomi", "OPPO"])
    ex[0x0110] = random.choice(["iPhone 15 Pro", "Mate 60 Pro", "14 Ultra", "Find X7"])
    ex[0x0132] = (datetime(2026, 9, 1) + timedelta(days=i, hours=i * 3)).strftime("%Y:%m:%d %H:%M:%S")
    return ex


def save_jpg(arr, path, q=90, exif=None):
    im = Image.fromarray(arr)
    im.save(path, "JPEG", quality=q, exif=exif) if exif is not None else im.save(path, "JPEG", quality=q)


# ------------------------------------------------------------------ 各类图片
def make_real(i):
    img, _ = render_scene(seed=i)
    p = IMG / f"real_{i:02d}.jpg"
    save_jpg(camera(img, seed=i), p, q=random.choice([88, 90, 92]), exif=exif_for(i))
    return p


def make_splice(i):
    img, boxes = render_scene(seed=i + 50)
    host = camera(img, seed=i + 50)
    # 外来素材：电商白底“明星同款/认证标签”或其他品牌产品，无传感器噪声、不同压缩历史
    patch = Image.new("RGB", (300, 220), (255, 255, 255))
    d = ImageDraw.Draw(patch)
    if i % 2 == 0:
        d.ellipse([20, 10, 280, 210], fill=(212, 40, 40))
        d.text((150, 85), "专柜正品", fill="white", font=font(46), anchor="mm")
        d.text((150, 145), "官方认证", fill="white", font=font(34), anchor="mm")
    else:
        draw_bottle(d, 70, 5, 150, 210, (30, 30, 30), (200, 170, 90), "LUXE")
    tmp = IMG / "_tmp.jpg"
    patch.save(tmp, "JPEG", quality=60)
    patch = np.asarray(Image.open(tmp))
    tmp.unlink()
    y, x = 90 + (i % 3) * 20, 760 - (i % 3) * 30
    mask = (patch.sum(axis=2) < 740)[..., None] if i % 2 else np.ones(patch.shape[:2] + (1,), bool)
    region = host[y:y + 220, x:x + 300]
    host[y:y + 220, x:x + 300] = np.where(mask, patch, region)
    p = IMG / f"splice_{i:02d}.jpg"
    save_jpg(host, p, q=92, exif=exif_for(i + 50))
    return p


def make_copymove(i):
    img, boxes = render_scene(seed=i + 80, n_bottles=2)
    arr = camera(img, seed=i + 80)
    x, y, bw, bh = boxes[0]
    src = arr[y - 10:y + bh + 10, x - 10:x + bw + 10].copy()
    dx = 760 + (i % 3) * 15
    arr[y - 10:y - 10 + src.shape[0], dx:dx + src.shape[1]] = src
    p = IMG / f"copymove_{i:02d}.jpg"
    save_jpg(arr, p, q=90, exif=exif_for(i + 80))
    return p


def skin_texture(w, h, seed):
    r = np.random.default_rng(seed)
    base = np.array([226, 184, 160], np.float32) + r.integers(-15, 15, 3)
    arr = np.ones((h, w, 3), np.float32) * base
    low = cv2.GaussianBlur(r.standard_normal((h, w)).astype(np.float32), (0, 0), 25) * 30
    pores = cv2.GaussianBlur(r.standard_normal((h, w)).astype(np.float32), (0, 0), 1.2) * 9
    arr += (low + pores)[..., None]
    for _ in range(45):  # 斑点/痘印
        cx, cy, rr = r.integers(0, w), r.integers(0, h), r.integers(4, 12)
        cv2.circle(arr, (int(cx), int(cy)), int(rr), tuple(float(c) for c in base * 0.78), -1)
    arr = cv2.GaussianBlur(arr, (0, 0), 1.0)
    return arr


def make_retouch(i, fake=True):
    """前后对比图。fake=True 时“使用后”被局部磨皮+提亮，夸大效果。"""
    w, h = 520, 640
    before = skin_texture(w, h, i + 200)
    # 真实前后对比是两次拍摄：机位/角度/光线都会略有变化
    M = cv2.getRotationMatrix2D((w / 2, h / 2), 4 + i % 3, 1.07)
    M[:, 2] += (9, -7)
    after = cv2.warpAffine(before, M, (w, h), borderMode=cv2.BORDER_REFLECT) * 1.03
    mask = np.zeros((h, w), np.float32)
    cv2.ellipse(mask, (w // 2, h // 2), (190, 250), 0, 0, 360, 1, -1)
    mask = cv2.GaussianBlur(mask, (0, 0), 25)[..., None]
    if fake:
        smooth = cv2.bilateralFilter(after.astype(np.uint8), 25, 80, 40).astype(np.float32)
        smooth = cv2.GaussianBlur(smooth, (0, 0), 4) * 1.04 + 5
        after = after * (1 - mask) + smooth * mask
    canvas = np.ones((h + 120, w * 2 + 30, 3), np.float32) * 250
    canvas[100:100 + h, 10:10 + w] = before
    canvas[100:100 + h, 20 + w:20 + 2 * w] = after
    im = Image.fromarray(np.clip(canvas, 0, 255).astype(np.uint8))
    d = ImageDraw.Draw(im)
    d.text((10 + w // 2, 50), "使用前", fill=(60, 60, 60), font=font(40), anchor="mm")
    d.text((20 + w * 1.5, 50), "使用 7 天后", fill=(200, 60, 90), font=font(40), anchor="mm")
    arr = camera(im, sigma=2.8, seed=i + 200)
    if fake:  # 修图软件导出时局部被二次平滑（磨皮在噪声之后施加）
        sub = arr[100:100 + h, 20 + w:20 + 2 * w].astype(np.float32)
        arr[100:100 + h, 20 + w:20 + 2 * w] = (sub * (1 - mask) + cv2.GaussianBlur(sub, (0, 0), 2.2) * mask).astype(np.uint8)
    p = IMG / f"{'retouch' if fake else 'beforeafter_real'}_{i:02d}.jpg"
    ex = exif_for(i + 200)
    if fake:
        ex[0x0131] = random.choice(["Meitu XiuXiu 10.2", "Adobe Photoshop 25.0", "BeautyCam"])
    save_jpg(arr, p, q=90, exif=ex)
    return p


def make_aigc(i):
    small, _ = render_scene(512, 512, seed=i + 300, n_bottles=2)
    a = np.asarray(small.filter(ImageFilter.GaussianBlur(1.6)), np.float32)
    # 生成模型风格：2x 最近邻上采样（棋盘/网格伪影）+ 无传感器噪声 + 过度平滑的“完美”质感
    big = cv2.resize(a, (1024, 1024), interpolation=cv2.INTER_NEAREST)
    grid = (np.indices((1024, 1024)).sum(0) % 2)[..., None] * 1.6
    big = np.clip(cv2.GaussianBlur(big, (0, 0), 0.6) + grid, 0, 255).astype(np.uint8)
    im = Image.fromarray(big)
    p = IMG / f"aigc_{i:02d}.png"
    if i % 2 == 0:
        meta = PngInfo()
        meta.add_text("parameters", "luxury skincare serum bottle on marble, soft light, 8k, photorealistic\n"
                                    "Steps: 30, Sampler: DPM++ 2M Karras, CFG scale: 7, Model: sdxl_base_1.0")
        im.save(p, pnginfo=meta)
    else:
        im.save(p)
    return p


# ------------------------------------------------------------------ 文案
TEXTS = {
    "genuine_1": """用了快一个月的XX精华，混油皮来交作业。
质地偏水，上脸吸收挺快，T区不会搓泥。前两周没啥感觉，第三周开始两颊的闭口少了一些，但下巴那颗还是倔强地在😂
缺点是瓶口设计不太好，每次按压量不稳定，30ml 380 块也不算便宜。敏感肌建议先在耳后试试，我第一次用鼻翼有点轻微刺痛。
总体会继续用完这瓶再决定要不要回购。""",
    "genuine_2": """记录一下这支粉底液的真实持妆：干皮，冬天北方暖气房。
早上8点上妆，中午12点鼻翼开始卡粉，下午4点两颊有点斑驳，氧化大概半个色号。我买的是1.5号，自然光下偏黄一点。
优点是遮瑕力还行，痘印能盖住。不推荐大干皮单独用，要配保湿妆前。""",
    "aigc_1": """✨ 夏日肌肤的秘密武器，终于被我找到了！✨
🌸 首先，这款精华的质地轻盈细腻，一抹即化，宛如为肌肤披上一层水润薄纱。
💧 其次，它蕴含多重植萃精华，能够深层滋养，由内而外焕发肌肤光彩。
🌟 此外，无论是干皮还是油皮，都能轻松驾驭，让你随时随地绽放自信光彩。
💖 值得一提的是，它温和不刺激，全方位呵护你的肌肤。
总的来说，这是一款不可或缺的护肤必备单品，开启你的美肌之旅吧！""",
    "aigc_2": """🌿 作为一名护肤爱好者，我今天要为你推荐这款面霜。
✨ 质地细腻，层层滋润，锁住水分，让肌肤的每一寸都充满活力。
🌸 不仅如此，它还能全方位修护肌肤屏障，由内而外改善肌肤状态。
💫 总而言之，这是一款值得拥有的完美面霜，希望对你有帮助！""",
    "violate_1": """姐妹们！！这个美白精华真的绝了，全网第一！7天美白，28天祛斑，色斑黄褐斑统统根除！
临床验证98%的人有效，医生推荐，纯天然零添加，孕妇都能用，无任何副作用！
专柜同款3折白菜价，想要的私信我或者加V：mei123，链接在主页～""",
    "violate_2": """这款药妆面膜真的能治疗痘痘，消炎杀菌效果最好，用一次痘痘就消失！敏感肌也能脱敏。
用了三天年轻10岁，永久不反弹，无效退款。到手价99，戳链接下单！""",
    "fake_goods": """家人们，大牌原单尾单清仓，1:1正品品质，专柜同款2折白菜价！工厂直供，和专柜一模一样，懂的来，看主页～""",
    "ad_unlabeled": """最近在用这款身体乳，香味是白茶调，挺清新的，涂完不黏。干皮冬天用刚好，夏天可能有点厚。
直播间今晚到手价89，还送小样，囤了两瓶，链接放评论区了。""",
}

# ------------------------------------------------------------------ 评论
ORGANIC = ["用了两周，混油皮觉得还行，就是有点贵", "我敏感肌用了泛红了，大家先试用", "请问油皮夏天会闷痘吗？", "色号偏黄，黄一白慎入",
           "回购第三瓶了，主要是吸收快", "跟风买的，感觉一般般，没有博主说的那么夸张", "包装好看但按压头容易坏", "请问和xx比哪个好？",
           "第一次用有点搓泥，后来少量多次就好了", "我觉得保湿还行，美白没感觉", "学生党觉得价格不太友好", "求问孕期能用吗"]
SHILL = ["效果真的很好，强烈推荐，已经回购了！", "效果真的非常好，强烈推荐大家购买，已回购！", "真的很好用，效果明显，强烈推荐！",
         "效果很好，皮肤变好了，强烈推荐，无限回购！", "非常好用，效果惊人，白了好多，强烈推荐！", "正品，效果很好，物超所值，五星好评！",
         "好用好用，闭眼入，yyds，强烈推荐！", "效果明显，皮肤白了好多，值得购买，强烈推荐！"]


def gen_comments(kind, seed):
    r = random.Random(seed)
    t0 = datetime(2026, 10, 1, 9, 0)
    rows = []
    n_org = 10 if kind == "organic" else 5
    for text in r.sample(ORGANIC, n_org):
        rows.append({"user": r.choice(["小鹿", "橘子汽水", "Coco", "今天也要早睡", "momo酱", "阿紫", "Luna", "芝士"]) + str(r.randint(1, 99)),
                     "time": (t0 + timedelta(hours=r.uniform(0, 96))).isoformat(), "text": text,
                     "account_age_days": r.randint(200, 2000), "followers": r.randint(20, 3000), "posts": r.randint(10, 300), "truth": 0})
    if kind == "shill":
        burst = t0 + timedelta(hours=r.uniform(20, 40))
        for k in range(14):
            rows.append({"user": f"用户{r.randint(100000, 999999)}", "time": (burst + timedelta(seconds=r.uniform(0, 500))).isoformat(),
                         "text": r.choice(SHILL), "account_age_days": r.randint(1, 20), "followers": r.randint(0, 3),
                         "posts": r.randint(0, 2), "truth": 1})
    r.shuffle(rows)
    return rows


def build():
    IMG.mkdir(parents=True, exist_ok=True)
    imgs = {}
    for i in range(4):
        imgs[f"real_{i}"] = make_real(i)
    for i in range(3):
        imgs[f"splice_{i}"] = make_splice(i)
        imgs[f"copymove_{i}"] = make_copymove(i)
        imgs[f"aigc_{i}"] = make_aigc(i)
    for i in range(2):
        imgs[f"retouch_{i}"] = make_retouch(i, True)
        imgs[f"ba_real_{i}"] = make_retouch(i + 10, False)

    rel = lambda k: str(imgs[k].relative_to(ROOT))
    # 每条帖子：真值 label（0=真实可信，1=伪造/违规），truth_dims 为真实存在的问题维度
    posts = [
        ("P01", "混油皮一个月精华实测", "genuine_1", ["real_0"], "organic", 0, []),
        ("P02", "粉底液北方冬季持妆记录", "genuine_2", ["real_1"], "organic", 0, []),
        ("P03", "前后对比，坚持就有效果", "genuine_1", ["ba_real_0"], "organic", 0, []),
        ("P04", "真实空瓶记录", "genuine_2", ["real_2", "real_3"], "organic", 0, []),
        ("P05", "夏日护肤秘密武器", "aigc_1", ["aigc_0"], "organic", 1, ["aigc"]),
        ("P06", "宝藏面霜推荐", "aigc_2", ["aigc_1"], "shill", 1, ["aigc", "comment"]),
        ("P07", "美白精华全网第一", "violate_1", ["retouch_0"], "shill", 1, ["claim", "tamper", "comment"]),
        ("P08", "药妆面膜祛痘神器", "violate_2", ["retouch_1"], "organic", 1, ["claim", "tamper"]),
        ("P09", "专柜正品清仓", "fake_goods", ["splice_0"], "shill", 1, ["claim", "tamper", "comment"]),
        ("P10", "新品香水开箱", "genuine_2", ["splice_1"], "organic", 1, ["tamper"]),
        ("P11", "囤货柜展示", "ad_unlabeled", ["copymove_0"], "organic", 1, ["tamper", "claim"]),
        ("P12", "库存充足现货", "fake_goods", ["copymove_1"], "shill", 1, ["claim", "tamper", "comment"]),
        ("P13", "精华液质感大片", "aigc_1", ["aigc_2"], "organic", 1, ["aigc"]),
        ("P14", "白茶身体乳分享", "ad_unlabeled", ["real_2"], "organic", 1, ["claim"]),
        ("P15", "大家都说好的面霜", "genuine_1", ["real_3"], "shill", 1, ["comment"]),
        ("P16", "精华开箱", "genuine_2", ["splice_2"], "organic", 1, ["tamper"]),
        ("P17", "补货啦", "genuine_1", ["copymove_2"], "organic", 1, ["tamper"]),
        ("P18", "日常分享", "genuine_2", ["ba_real_1"], "organic", 0, []),
    ]
    out = []
    for pid, title, tk, ik, ck, label, dims in posts:
        out.append({"id": pid, "title": title, "text": TEXTS[tk], "text_type": tk, "images": [rel(k) for k in ik],
                    "comments": gen_comments(ck, int(pid[1:])), "label": label, "truth_dims": dims})
    (ROOT / "posts.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"生成 {len(out)} 条帖子、{len(imgs)} 张图片 → {ROOT}")


if __name__ == "__main__":
    build()
