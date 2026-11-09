"""按赛题建议格式导出测试数据包：python -m data.build_test_package

每条样本一个文件夹（sample_001 …）：
  正文.txt        标题 + 种草正文
  评论.txt        每行一条：昵称|时间|内容（另附 account_age_days/followers/posts 于 评论_账号信息.csv）
  image_N.jpg/png 配图；screenshot_N.png 为小红书笔记截图
  README.txt      数据来源、样本类型、是否伪造、伪造方式、问题维度（机器可读的“键: 值”行）
最终打包为 BeautyGuard_测试数据包.zip。
"""
import csv
import json
import shutil
import zipfile
from pathlib import Path

from core.agent import DIMENSIONS

ROOT = Path(__file__).parent
OUT = ROOT / "test_package"
ZIP = ROOT.parent / "docs" / "BeautyGuard_测试数据包.zip"

IMG_DESC = {
    "real": "真实拍摄风格图片（模拟相机传感器噪声 + JPEG + EXIF），未篡改",
    "beforeafter_real": "真实前后对比图（两次拍摄，含角度/光线差异），未篡改——边缘场景：易被误判为复制或拼接",
    "splice": "拼接伪造：粘贴来自不同压缩历史的“专柜正品/官方认证”贴纸或他牌产品",
    "copymove": "复制-移动伪造：复制同图中的产品以伪造“满柜现货”",
    "retouch": "功效夸大：前后对比图“使用后”局部磨皮+提亮，美图/PS 导出元数据",
    "aigc": "AI 生成风格图：无传感器噪声、2× 上采样网格伪影、生成模型典型分辨率；偶数编号附 Stable Diffusion 生成参数元数据",
}
TEXT_DESC = {
    "genuine_1": "真实用户测评（有肤质、价格、缺点等细节）", "genuine_2": "真实用户测评（持妆记录、含缺点）",
    "aigc_1": "AI 生成的“伪真人测评”文案（模板化排版、大模型套话）", "aigc_2": "AI 生成的“伪真人测评”文案",
    "violate_1": "违规功效宣称：极限词、时限效果、医疗化、无依据数据、站外导流", "violate_2": "违规功效宣称：药妆/治疗/永久不反弹",
    "fake_goods": "假货暗语：原单尾单 1:1、专柜同款白菜价", "ad_unlabeled": "软广未标注广告（带货信号但无“广告/合作”标识）",
}
EDGE = {"P03": "真实前后对比图（边缘场景：不应被判为复制/拼接）", "P18": "真实前后对比图（边缘场景）",
        "P01": "文案含“第一次用”（边缘场景：不应被判为极限词）", "P15": "文案真实，但评论区被刷评（仅评论维度有问题）",
        "P14": "图片真实，仅文案为未标注软广（单一弱维度）"}


def kind_of(path: str):
    name = Path(path).stem
    for k in ("beforeafter_real", "real", "splice", "copymove", "retouch", "aigc"):
        if name.startswith(k):
            return k
    return "real"


def write_comments(folder: Path, comments):
    if not comments:
        return
    (folder / "评论.txt").write_text("\n".join(f"{c.get('user', '')}|{c.get('time', '')}|{c['text']}" for c in comments), encoding="utf-8")
    with open(folder / "评论_账号信息.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["user", "time", "text", "account_age_days", "followers", "posts", "is_shill"])
        for c in comments:
            w.writerow([c.get("user"), c.get("time"), c["text"], c.get("account_age_days"), c.get("followers"), c.get("posts"), c.get("truth", "")])


def readme(folder: Path, fields: dict, notes: list[str]):
    lines = [f"{k}: {v}" for k, v in fields.items()] + [""] + notes
    (folder / "README.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def build():
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()
    posts = json.loads((ROOT / "posts.json").read_text(encoding="utf-8"))
    index = []
    for n, p in enumerate(posts, 1):
        sd = OUT / f"sample_{n:03d}"
        sd.mkdir()
        (sd / "正文.txt").write_text(f"{p['title']}\n\n{p['text']}", encoding="utf-8")
        write_comments(sd, p["comments"])
        img_notes = []
        for k, rel in enumerate(p["images"], 1):
            src = ROOT / rel
            dst = sd / f"image_{k}{src.suffix}"
            shutil.copy(src, dst)
            img_notes.append(f"  {dst.name}：{IMG_DESC[kind_of(rel)]}")
        shill = sum(1 for c in p["comments"] if c.get("truth") == 1)
        dims = "、".join(DIMENSIONS[d] for d in p["truth_dims"]) or "无"
        types = ["种草内容"] + (["评论区"] if p["comments"] else []) + (["AI生成素材"] if "aigc" in p["truth_dims"] else [])
        fields = {"样本编号": sd.name, "原始ID": p["id"], "数据来源平台": "模拟小红书种草笔记（团队自建合成数据）",
                  "样本类型": "、".join(types), "是否为伪造样本": "是" if p["label"] else "否", "问题维度": dims}
        notes = ["伪造方式说明：", f"  文案：{TEXT_DESC[p['text_type']]}", "  配图：", *img_notes,
                 f"  评论区：共 {len(p['comments'])} 条，其中刷评 {shill} 条（模板化好评 + 10 分钟集中爆发 + 新注册零粉账号）" if shill
                 else f"  评论区：共 {len(p['comments'])} 条真实风格评论，无刷评"]
        if p["id"] in EDGE:
            notes.append(f"边缘场景：{EDGE[p['id']]}")
        readme(sd, fields, notes)
        index.append({"样本": sd.name, "标题": p["title"], "是否伪造": fields["是否为伪造样本"], "问题维度": dims, "类型": fields["样本类型"]})

    # 公开仓库仅含模拟截图；真实笔记截图（含他人信息）未随仓库发布，存在时自动加入
    shots = [("xhs_mock_fake.png",), ("xhs_mock_genuine.png",), ("xhs_real_1_note.png", "xhs_real_2_comments.png")]
    shot_meta = [
        ({"数据来源平台": "模拟小红书笔记截图（按 App 版式生成，无真实用户）", "样本类型": "种草内容、评论区（截图）", "是否为伪造样本": "是",
          "问题维度": "虚假/违规宣称、评论区刷评、图片篡改/拼接"}, ["伪造方式说明：", "  截图内配图为拼接伪造（粘贴“专柜正品”贴纸）；文案含极限词/时限效果/医疗化宣称；评论区 5 条模板刷评。"]),
        ({"数据来源平台": "模拟小红书笔记截图（按 App 版式生成，无真实用户）", "样本类型": "种草内容、评论区（截图）", "是否为伪造样本": "否",
          "问题维度": "无"}, ["说明：真实风格测评截图，用于检验截图入口不误伤。"]),
        ({"数据来源平台": "小红书（真实公开笔记截图，团队成员提供，头像已打码）", "样本类型": "种草内容、评论区（截图，2 张：正文页 + 评论页）",
          "是否为伪造样本": "否（非伪造，但存在风险宣称）", "问题维度": "虚假/违规宣称（待人工核验）"},
         ["说明：真实平台样本，用于检验真实版式下的截图解析与宣称检测。",
          "  风险点：“快了近两倍”无来源倍数数据；“即刻亮了一度两度”即时功效；“+7啵啵间”谐音指代直播间、带货未标广告；美白/淡斑需核验特证。",
          "  系统结论仅为风险提示，不构成对品牌或博主的违规认定。"]),
    ]
    for files, (fields, notes) in zip(shots, shot_meta):
        if not all((ROOT / "screenshots" / f).exists() for f in files):
            continue
        n += 1
        sd = OUT / f"sample_{n:03d}"
        sd.mkdir()
        for k, f in enumerate(files, 1):
            shutil.copy(ROOT / "screenshots" / f, sd / f"screenshot_{k}.png")
        readme(sd, {"样本编号": sd.name, **fields}, notes)
        index.append({"样本": sd.name, "标题": "（截图样本）", "是否伪造": fields["是否为伪造样本"], "问题维度": fields["问题维度"], "类型": fields["样本类型"]})

    n_fake = sum(1 for r in index if r["是否伪造"] == "是")
    md = ["# BeautyGuard 测试数据包", "",
          f"共 {len(index)} 条样本（伪造/违规 {n_fake} 条，真实 {len(index) - n_fake} 条），覆盖赛题三大场景：**种草内容核验、评论区真实性核验、AI 生成视觉素材鉴伪**。", "",
          "## 目录结构", "", "```", "sample_001/", "  正文.txt            标题 + 种草正文", "  评论.txt            昵称|时间|内容（每行一条）",
          "  评论_账号信息.csv   评论 + 账号注册天数/粉丝/发帖数 + 是否刷评真值", "  image_1.jpg         配图（截图样本为 screenshot_N.png）",
          "  README.txt          来源平台、样本类型、是否伪造、伪造方式、问题维度", "```", "",
          "## 构造方式", "",
          "- **图片**：程序化渲染，模拟真实相机成像（亮度相关传感器噪声 + JPEG + EXIF），再施加真实造假操作：拼接贴纸、复制-移动、前后对比图局部磨皮、AI 生成风格（无噪声 + 上采样伪影 + SD 生成参数）。",
          "- **文案**：真实测评 / AI 伪测评 / 违规功效宣称 / 假货暗语 / 未标注软广 五类。",
          "- **评论**：真实风格评论与刷评（模板好评 + 10 分钟爆发 + 新注册零粉账号）混合，逐条附真值。",
          "- **截图**：2 张按小红书版式模拟生成 + 1 组真实公开笔记截图（头像已打码）。",
          "- **边缘场景**：真实前后对比图（易误判复制/拼接）、“第一次用”等合法表述、仅评论区被刷的真实笔记、仅软广未标注的单一弱维度样本。", "",
          "## 一键核验本数据包", "", "```bash", "cd beautyguard", "python -m eval.run_package ../提交包解压路径/BeautyGuard_测试数据包", "```", "",
          "## 样本索引", "", "| 样本 | 标题 | 是否伪造 | 问题维度 | 类型 |", "|---|---|---|---|---|"]
    md += [f"| {r['样本']} | {r['标题']} | {r['是否伪造']} | {r['问题维度']} | {r['类型']} |" for r in index]
    (OUT / "数据包说明.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    ZIP.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(OUT.rglob("*")):
            if f.is_file():
                z.write(f, Path("BeautyGuard_测试数据包") / f.relative_to(OUT))
    print(f"{len(index)} 条样本 → {OUT}\nzip → {ZIP} ({ZIP.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    build()
