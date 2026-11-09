"""生成“小红书笔记详情页”风格的模拟截图（用于截图入口的演示与测试）：python -m data.build_screenshots

出于隐私与版权考虑，不使用真实用户截图；版式参照小红书 App 笔记详情页（顶栏 / 配图 / 标题正文 / 话题 / 评论区）。
"""
from pathlib import Path

from PIL import Image, ImageDraw

from data.build_dataset import font

ROOT = Path(__file__).parent
OUT = ROOT / "screenshots"
W = 1080
GREY, BLACK, LIGHT = (140, 140, 140), (34, 34, 34), (238, 238, 238)


def wrap(d, text, f, width):
    lines, cur = [], ""
    for ch in text:
        if ch == "\n":
            lines.append(cur); cur = ""; continue
        if d.textlength(cur + ch, font=f) > width:
            lines.append(cur); cur = ch
        else:
            cur += ch
    return lines + ([cur] if cur else [])


def render(photo: Path, author, title, body, tags, meta, comments, out: Path):
    canvas = Image.new("RGB", (W, 4200), "white")
    d = ImageDraw.Draw(canvas)
    d.text((60, 30), "9:41", fill=BLACK, font=font(36))
    d.ellipse([60, 110, 150, 200], fill=(250, 200, 210))
    d.text((175, 135), author, fill=BLACK, font=font(38))
    d.rounded_rectangle([830, 120, 1010, 190], radius=35, outline=(255, 36, 66), width=3)
    d.text((920, 155), "关注", fill=(255, 36, 66), font=font(34), anchor="mm")
    im = Image.open(photo).convert("RGB")
    ph = int(W * im.height / im.width)
    canvas.paste(im.resize((W, ph)), (0, 230))
    y = 230 + ph + 30
    for k in range(4):
        d.ellipse([500 + k * 24, y, 512 + k * 24, y + 12], fill=(255, 36, 66) if k == 0 else LIGHT)
    y += 50
    for line in wrap(d, title, font(46), W - 120):
        d.text((60, y), line, fill=BLACK, font=font(46)); y += 66
    y += 10
    for line in wrap(d, body, font(38), W - 120):
        d.text((60, y), line, fill=BLACK, font=font(38)); y += 58
    d.text((60, y + 10), " ".join(f"#{t}" for t in tags), fill=(19, 56, 110), font=font(36)); y += 80
    d.text((60, y), meta, fill=GREY, font=font(32)); y += 70
    d.line([60, y, W - 60, y], fill=LIGHT, width=2); y += 40
    d.text((60, y), f"共 {len(comments)} 条评论", fill=BLACK, font=font(36)); y += 80
    for user, text, when, likes in comments:
        d.ellipse([60, y, 140, y + 80], fill=(210, 225, 245))
        d.text((165, y), user, fill=GREY, font=font(32)); y += 50
        for line in wrap(d, text, font(38), W - 300):
            d.text((165, y), line, fill=BLACK, font=font(38)); y += 56
        d.text((165, y + 4), f"{when}  回复", fill=GREY, font=font(30))
        d.text((990, y - 40), str(likes), fill=GREY, font=font(30), anchor="mm"); y += 80
    d.rectangle([0, y + 20, W, y + 140], fill=(250, 250, 250))
    d.text((60, y + 60), "说点什么...", fill=GREY, font=font(34))
    canvas.crop((0, 0, W, y + 140)).save(out)
    return out


def build():
    OUT.mkdir(exist_ok=True)
    img = ROOT / "images"
    render(img / "splice_00.jpg", "美妆好物分享官", "专柜正品清仓！美白精华全网第一",
           "姐妹们这个美白精华真的绝了，7天美白，28天祛斑，色斑统统根除！临床验证98%的人有效，纯天然零添加，"
           "无任何副作用。专柜同款3折白菜价，想要的私信我～", ["美白", "精华推荐", "护肤"], "编辑于 10-01 广东",
           [("用户582913", "效果真的很好，强烈推荐，已经回购了！", "10-01 河南", 2), ("用户193847", "效果很好，皮肤变好了，强烈推荐！", "10-01 河南", 1),
            ("用户740021", "真的很好用，效果明显，强烈推荐！", "10-01 河南", 0), ("橘子汽水33", "请问敏感肌能用吗？", "10-02 上海", 5),
            ("用户662810", "非常好用，效果惊人，白了好多，强烈推荐！", "10-01 河南", 0), ("用户301954", "好用好用，闭眼入，yyds，强烈推荐！", "10-01 河南", 1),
            ("今天也要早睡", "价格这么低是正品吗，有点怀疑", "10-03 北京", 12)],
           OUT / "xhs_mock_fake.png")
    render(img / "real_01.jpg", "混油皮小鹿", "混油皮一个月精华实测",
           "用了快一个月，混油皮来交作业。质地偏水，上脸吸收挺快，T区不会搓泥。前两周没啥感觉，第三周开始两颊的闭口少了一些，"
           "但下巴那颗还是倔强地在。缺点是瓶口设计不太好，按压量不稳定，30ml 380 块也不算便宜。", ["护肤日常", "精华"], "编辑于 09-28 浙江",
           [("Coco21", "我敏感肌用了有点泛红，大家先试用", "09-28 江苏", 8), ("芝士7", "请问油皮夏天会闷痘吗？", "09-29 四川", 3),
            ("阿紫", "跟风买的，感觉一般般，没有说的那么夸张", "09-30 湖北", 2), ("Luna", "第一次用有点搓泥，后来少量多次就好了", "10-01 上海", 6)],
           OUT / "xhs_mock_genuine.png")
    print("ok", sorted(p.name for p in OUT.iterdir()))


if __name__ == "__main__":
    build()
