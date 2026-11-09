"""自动生成带中文配音与字幕的产品演示视频：python -m video.make_video

架构参照开源项目 NeuraScreen / demoreel（Playwright 录制浏览器 + TTS 配音 + ffmpeg 合成），
改为免费中文 TTS（edge-tts）、系统 Chrome、Streamlit 专用交互，并烧录字幕。
前提：Streamlit 已在 http://localhost:8501 运行；需要联网调用 edge-tts。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
import time
from pathlib import Path

import edge_tts
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build"
OUT = ROOT.parent / "docs" / "BeautyGuard_演示视频.mp4"
URL = "http://localhost:8501"
W, H = 1440, 900
VOICE, RATE = "zh-CN-XiaoxiaoNeural", "+8%"

ROSE = "#7a2bd0"   # 与官方 PPT 模板的紫色主题一致
CARD_CSS = f"""
body{{margin:0;width:{W}px;height:{H}px;font-family:'PingFang SC','Hiragino Sans GB',sans-serif;background:#fff;color:#1f2937;overflow:hidden}}
.cover{{background:linear-gradient(120deg,#3b0a7a 0%,{ROSE} 55%,#c026d3 100%);color:#fff;height:100%;display:flex;flex-direction:column;justify-content:center;padding:0 120px;box-sizing:border-box}}
.cover h1{{font-size:88px;margin:0}} .cover h2{{font-size:44px;margin:18px 0 0}} .cover p{{font-size:26px;opacity:.9;margin-top:36px}}
.page{{padding:70px 90px;box-sizing:border-box;height:100%;border-left:16px solid {ROSE}}}
.page h1{{font-size:50px;margin:0 0 40px}}
.grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:24px}}
.box{{background:#f6eeff;border-radius:18px;padding:26px;font-size:24px;line-height:1.6}}
.box b{{color:{ROSE};font-size:28px;display:block;margin-bottom:10px}}
.flow{{display:flex;gap:14px;align-items:stretch;margin-top:20px}}
.step{{flex:1;background:#f6eeff;border-radius:16px;padding:22px 14px;text-align:center;font-size:22px;line-height:1.5}}
.step b{{display:block;color:{ROSE};font-size:26px;margin-bottom:8px}} .step.hot{{background:{ROSE};color:#fff}} .step.hot b{{color:#fff}}
table{{border-collapse:collapse;font-size:24px;width:100%}} td,th{{padding:12px 16px;border-bottom:1px solid #e9d5ff;text-align:left}} th{{background:{ROSE};color:#fff}}
.note{{font-size:22px;color:#6b7280;margin-top:26px;line-height:1.6}}
"""


def card(body: str) -> str:
    return f"<html><head><meta charset='utf-8'><style>{CARD_CSS}</style></head><body>{body}</body></html>"


def metrics_card():
    ev = ROOT.parent / "eval"
    rb = json.loads((ev / "robustness.json").read_text(encoding="utf-8"))
    cr = json.loads((ev / "comment_realworld.json").read_text(encoding="utf-8"))
    sp = rb["per_kind"]; sb = rb["per_kind_base"]
    b = cr["exp2"]["B留出_inject_6_of_30"]
    return card(f"""<div class='page'><h1>不只在演示集上好看：真实性验证</h1>
<table><tr><th>验证</th><th>结果</th></tr>
<tr><td>留出集 · 拼接检测（平台重压缩 Q75）</td><td>传统取证 {sb['平台重压缩 Q75']['splice']:.0%} → 接入开源 TruFor 后 <b>{sp['平台重压缩 Q75']['splice']:.0%}</b></td></tr>
<tr><td>留出集 · 整体准确率（原图 / 重压缩）</td><td>{rb['overall']['原图']:.1%} / {rb['overall']['平台重压缩 Q75']:.1%}</td></tr>
<tr><td>1 万条真实小红书评论 · 误判为水军</td><td><b>{cr['exp1']['comment_fpr']:.0%}</b></td></tr>
<tr><td>真实评论区注入留出刷评（6/30）</td><td>精确率 {b['precision']:.1%} · 召回率 {b['recall']:.1%} · 评论区告警 {b['section_detect']:.0%}</td></tr></table>
<div class='note'>说明：演示集为程序化合成，100% 仅代表流程正确；已知局限——缩放后的真实前后对比拼图会被 TruFor 误判为合成，转人工复核。</div></div>""")


COVER = card("""<div class='cover'><h1>BeautyGuard</h1><h2>懂美妆内容生态的 AI 鉴真 Agent</h2>
<p>“你还相信你看到的吗？” —— 识别 · 解释 · 决策<br>欧莱雅美妆科技黑客松 · 赛题2 信任守护师 ｜ 队伍：卸妆水研究所</p></div>""")
PAIN = card("""<div class='page'><h1>美妆种草内容正在失去“真实”</h1><div class='grid'>
<div class='box'><b>种草图片</b>前后对比图局部磨皮<br>粘贴“专柜正品”贴纸<br>复制产品伪造现货</div>
<div class='box'><b>AI 素材</b>AI“完美皮肤”冒充实拍<br>AI 产品大片不标识</div>
<div class='box'><b>种草文案</b>AI 批量“伪真人测评”<br>“7天美白”违规宣称<br>谐音软广规避审核</div>
<div class='box'><b>评论区</b>模板化好评<br>集中爆发刷评<br>批量注册水军</div></div>
<div class='note'>现有工具只给一个分数：说不清假在哪、依据是什么、该怎么处理。</div></div>""")
ARCH = card("""<div class='page'><h1>一个会“查证、推理、决策”的核验 Agent</h1><div class='flow'>
<div class='step'><b>① 感知规划</b>识别图/文/评论<br>动态生成计划</div>
<div class='step hot'><b>② 多模态工具</b>TruFor · ELA · 噪声<br>复制-移动 · 元数据<br>违规词×法规库<br>水军检测</div>
<div class='step'><b>③ 自适应深挖</b>可疑区域<br>放大复核</div>
<div class='step'><b>④ 证据融合</b>置信度加权<br>Noisy-OR</div>
<div class='step hot'><b>⑤ 风险决策</b>四级分级<br>比例原则</div>
<div class='step'><b>⑥ 可解释报告</b>平台/创作者<br>/消费者</div></div>
<div class='note'>全部基于开源模型：TruFor（CVPR 2023）深度篡改定位 · RapidOCR 截图识别 · china-compliance-skills 违禁词库 · 可选 Qwen2.5-VL（开源权重）</div></div>""")
END = card("""<div class='cover'><h1 style='font-size:64px'>让每一份“种草”都经得起查证</h1>
<h2 style='font-size:34px'>BeautyGuard · 卸妆水研究所</h2><p>信任守护师 —— 创造者的 AI 卫士</p></div>""")


# ------------------------------------------------------------------ 浏览器动作
def flash(page, loc):
    """无头录制看不到鼠标：点击前在目标处画一个高亮圈。"""
    try:
        b = loc.bounding_box()
        if b:
            page.evaluate("""([x,y,w,h])=>{const d=document.createElement('div');
              Object.assign(d.style,{position:'fixed',left:(x-6)+'px',top:(y-6)+'px',width:(w+12)+'px',height:(h+12)+'px',
              border:'4px solid #e11d48',borderRadius:'12px',zIndex:99999,pointerEvents:'none',boxShadow:'0 0 18px #e11d48'});
              document.body.appendChild(d);setTimeout(()=>d.remove(),900);}""", [b["x"], b["y"], b["width"], b["height"]])
            page.wait_for_timeout(450)
    except Exception:
        pass


def click(page, loc):
    loc = loc.first
    loc.scroll_into_view_if_needed()
    flash(page, loc)
    loc.click()


def vis(loc):
    return loc.filter(visible=True)


def select(page, idx, option):
    box = vis(page.locator('[data-testid="stSelectbox"]')).nth(idx)
    click(page, box.get_by_role("button", name="Open"))
    click(page, page.get_by_role("option", name=option, exact=True))
    wait_idle(page)


def button(page, name):
    click(page, vis(page.get_by_role("button", name=name)))


def tab(page, name):
    click(page, vis(page.get_by_role("tab", name=name)))
    page.wait_for_timeout(700)


def wheel(page, dy, steps=6):
    page.mouse.move(W * 0.55, H * 0.6)
    for _ in range(steps):
        page.mouse.wheel(0, dy / steps)
        page.wait_for_timeout(60)


def top(page):
    page.evaluate("""()=>{for(const el of [document.querySelector('[data-testid="stMain"]'),document.scrollingElement])
                        if(el) el.scrollTo({top:0,behavior:'instant'})}""")
    page.wait_for_timeout(400)


def wait_idle(page, timeout=120):
    """等 Streamlit 脚本重跑结束：右上角运行指示器消失并稳定 1 秒。"""
    page.wait_for_timeout(800)
    t0, calm = time.monotonic(), 0
    while time.monotonic() - t0 < timeout and calm < 4:
        running = page.locator('[data-testid="stStatusWidget"]').filter(visible=True).count()
        calm = 0 if running else calm + 1
        page.wait_for_timeout(250)


def wait_done(page, timeout=90000):
    wait_idle(page, timeout / 1000)
    page.get_by_text("核验完成").first.wait_for(timeout=timeout)
    page.wait_for_timeout(600)


def show(page, text):
    loc = page.get_by_text(text, exact=False).first
    loc.scroll_into_view_if_needed()
    page.wait_for_timeout(300)


def goto_app(page):
    page.goto(URL)
    page.get_by_text("BeautyGuard · 美妆内容鉴真 Agent").first.wait_for(timeout=60000)
    page.wait_for_timeout(1500)


def sample(page, label):
    tab(page, "🔍 单条内容核验")
    top(page)
    click(page, vis(page.get_by_text("演示数据集样例", exact=True)))
    select(page, 0, label)


def run_single(page):
    button(page, "🚀 开始核验")
    wait_done(page)


def result_tab(page, name):
    show(page, "核心判定依据")
    tab(page, name)
    wheel(page, 350)


# ------------------------------------------------------------------ 分镜（旁白 + 画面动作）
SCENES = [
    ("cover", "大家好，我们是卸妆水研究所。这是 BeautyGuard，一个懂美妆内容生态的 AI 鉴真 Agent。",
     lambda p: p.set_content(COVER)),
    ("pain", "美妆种草里，有 P 过的前后对比图，有 AI 生成的完美皮肤，有 AI 批量写的伪测评，还有成片的水军好评。现有工具往往只给一个分数，说不清假在哪里，也说不清该怎么处理。",
     lambda p: p.set_content(PAIN)),
    ("arch", "BeautyGuard 是一个会查证、推理和决策的 Agent。它先感知内容、规划要调用的工具，再融合多路证据做风险分级，最后给出平台、创作者和消费者三方的处置建议。",
     lambda p: p.set_content(ARCH)),
    ("open", "我们打开系统，先看一条问题最多的笔记：美白精华全网第一。",
     lambda p: (goto_app(p), sample(p, "P07 · 美白精华全网第一"))),
    ("run", "点击开始核验。Agent 的每一步，在想什么、调用了哪个工具、看到了什么，都实时展示出来：图像取证、TruFor 深度模型、违规宣称与法规比对、评论区水军检测，最后融合证据做出决策。",
     lambda p: run_single(p)),
    ("verdict", "结论是疑似伪造或违规，可信分只有个位数，属于极高风险。右侧雷达图显示，图片篡改、违规宣称和评论区刷评三个维度同时亮红灯。",
     lambda p: show(p, "核心判定依据")),
    ("img", "在图片取证里，这是一张使用前和使用七天后的对比图。热力图框出了脸部被局部磨皮的区域，噪声残差图上能看到明显的噪声断层，元数据还显示经过美图软件导出。",
     lambda p: result_tab(p, "🖼️ 图片取证")),
    ("text", "文案分析会高亮每一处违规片段：全网第一、七天美白、根除色斑、临床验证百分之九十八。每一条都对应广告法或化妆品监督管理条例的具体条款，并给出合规替换建议。",
     lambda p: result_tab(p, "📝 文案分析")),
    ("comment", "评论区里，系统标出了疑似水军：内容高度雷同、十分钟内集中爆发、而且都是新注册的默认昵称账号。",
     lambda p: result_tab(p, "💬 评论区")),
    ("action", "最后是从识别到决策：平台该怎么处置、创作者该怎么整改、消费者该注意什么，三方建议一目了然，并附上法规依据。",
     lambda p: result_tab(p, "🧭 处置建议")),
    ("genuine", "再看一条真实测评。它写了肤质、价格，也写了缺点，系统判定为真实可信；像第一次用这种合法表述，也不会被误判成违规词。",
     lambda p: (sample(p, "P01 · 混油皮一个月精华实测"), run_single(p), show(p, "核心判定依据"))),
    ("trufor", "这是一张被粘贴了专柜正品贴纸的图片。我们集成了开源深度取证模型 TruFor，它能精确定位贴纸区域，而且经过平台重新压缩之后依然能检出。",
     lambda p: (sample(p, "P10 · 新品香水开箱"), run_single(p), result_tab(p, "🖼️ 图片取证"))),
    ("shot1", "小红书没有开放笔记和评论接口，我们也不做爬虫。所以系统支持直接上传笔记截图。这是一篇真实笔记的正文页和评论页。",
     lambda p: (tab(p, "🔍 单条内容核验"), top(p), click(p, vis(p.get_by_text("小红书截图", exact=True))), p.wait_for_timeout(800),
                button(p, "📷 解析截图"), p.get_by_text("自动裁出的配图").first.wait_for(timeout=90000), p.wait_for_timeout(800),
                show(p, "自动裁出的配图"))),
    ("shot2", "系统自动裁出配图，用开源 OCR 在本地识别出标题、正文和评论，还能区分作者本人的回复。识别结果可以人工修正后再核验。",
     lambda p: wheel(p, 300)),
    ("shot3", "核验结果是高风险，建议限流并人工复核。依据包括：快了近两倍这种没有来源的倍数数据，即刻亮了一度这种即时功效宣称，以及用啵啵间谐音指代直播间的软广。注意，它不会因为只是文案存疑就直接下架。",
     lambda p: (button(p, "🚀 开始核验"), wait_done(p), show(p, "核心判定依据"))),
    ("batch", "接下来是数据集闭环。我们让 Agent 批量核验全部十八条带真值标签的笔记，模拟真实的平台审核流程。",
     lambda p: (top(p), tab(p, "📊 数据集闭环（识别→决策）"), button(p, "▶️ 批量运行数据集"))),
    ("batch_wait", "在批量处理的同时，介绍一下决策逻辑。每条证据都带有异常分数和方法置信度，同一维度内多路证据互相印证时风险上升，单一弱证据则被抑制。综合风险分为低、中、高、极高四级，分别对应放行、打标抽检、限流加人工复核、下架并开放申诉。",
     lambda p: (p.get_by_text("处置工单").first.wait_for(timeout=180000), p.wait_for_timeout(800), show(p, "准确率"))),
    ("batch2", "结果出来了：准确率、混淆矩阵、风险分级分布，以及按风险排序的处置工单。每一条都有首要处置动作，点开任意一条，都能查看完整的证据链和 Agent 轨迹。",
     lambda p: show(p, "处置工单")),
    ("metrics", "我们也坦诚说明评测：演示集是合成数据，百分之百只代表流程正确。在留出集和平台重压缩下，接入 TruFor 后拼接检测达到百分之百；在一万条真实小红书评论上，水军误判为零。",
     lambda p: p.set_content(metrics_card())),
    ("end", "BeautyGuard，让每一份种草都经得起查证。谢谢大家。",
     lambda p: p.set_content(END)),
]


# ------------------------------------------------------------------ 合成
async def _tts(text, path):
    await edge_tts.Communicate(text, VOICE, rate=RATE).save(str(path))


def duration(path):
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)]).strip())


def tts_all():
    BUILD.mkdir(parents=True, exist_ok=True)
    out = {}
    for sid, say, _ in SCENES:
        p = BUILD / f"{sid}_{hashlib.md5((VOICE + RATE + say).encode()).hexdigest()[:8]}.mp3"
        if not p.exists():
            asyncio.run(_tts(say, p))
        out[sid] = (p, duration(p))
    return out


def srt_time(t):
    h, m, s = int(t // 3600), int(t % 3600 // 60), t % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")


def write_srt(timeline, path):
    import re
    lines, n = [], 1
    for start, dur, say in timeline:
        chunks = [c for c in re.split(r"(?<=[，。：；！？])", say) if c.strip()]
        merged, cur = [], ""
        for c in chunks:
            if len(cur) + len(c) > 26 and cur:
                merged.append(cur); cur = c
            else:
                cur += c
        merged.append(cur)
        total = sum(len(c) for c in merged)
        t = start
        for c in merged:
            d = dur * len(c) / total
            lines += [str(n), f"{srt_time(t)} --> {srt_time(t + d)}", c.strip("，。"), ""]
            n += 1; t += d
    path.write_text("\n".join(lines), encoding="utf-8")


# 这些分镜讲的是“过程”，旁白与动作同时开始；其余分镜先做动作、画面就绪后再讲（与 NeuraScreen 推荐的模式一致）
NARRATE_DURING = {"run", "batch", "batch_wait"}


def record(audio):
    timeline = []
    vdir = BUILD / "raw"
    vdir.mkdir(exist_ok=True)
    for f in vdir.glob("*.webm"):
        f.unlink()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=True)
        ctx = browser.new_context(viewport={"width": W, "height": H}, record_video_dir=str(vdir),
                                  record_video_size={"width": W, "height": H}, locale="zh-CN")
        t0 = time.monotonic()
        page = ctx.new_page()
        page.set_default_timeout(60000)
        page.goto("about:blank"); page.set_content(card("")); page.wait_for_timeout(1500)  # 录屏预热，剪辑时自动丢弃
        for sid, say, act in SCENES:
            s = time.monotonic() - t0
            print(f"[{s:6.1f}s] {sid}", flush=True)
            act(page)
            a = s if sid in NARRATE_DURING else time.monotonic() - t0
            dur = audio[sid][1]
            remain = a + dur + 0.7 - (time.monotonic() - t0)
            if remain > 0:
                page.wait_for_timeout(int(remain * 1000))
            timeline.append((s, a, dur, say))
        total = time.monotonic() - t0
        video = page.video
        ctx.close(); browser.close()
        return Path(video.path()), timeline, total


def cut_plan(timeline, total, pad=0.8, tail=2.0, head=1.2, lead=2.0):
    """自动剪辑，剪掉纯等待：
    动作段 [s,a]：过长时只保留开头 head 秒（看到点击）+ 结尾 lead 秒（结果出现）；
    旁白段 [a, a+dur+pad] 全保留；旁白后到下一分镜的剩余等待只保留最后 tail 秒。"""
    segs, new_tl, t = [], [], 0.0

    def keep(x, y):
        nonlocal t
        if y > x:
            segs.append((x, y)); t += y - x

    for k, (s, a, dur, say) in enumerate(timeline):
        e = timeline[k + 1][0] if k + 1 < len(timeline) else total
        if a - s > head + lead + 0.5:
            keep(s, s + head); keep(a - lead, a)
        else:
            keep(s, a)
        new_tl.append((t, dur, say))
        n_end = min(e, a + dur + pad)
        keep(a, n_end)
        if e - n_end > tail + 0.5:
            keep(e - tail, e)
        else:
            keep(n_end, e)
    return segs, new_tl, t


def compose(raw, audio, timeline, total):
    segs, timeline, total = cut_plan(timeline, total)
    srt = BUILD / "subs.srt"
    write_srt(timeline, srt)
    inputs, filters = ["-i", str(raw)], []
    for k, (a, b) in enumerate(segs):
        filters.append(f"[0:v]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS[v{k}]")
    filters.append("".join(f"[v{k}]" for k in range(len(segs))) + f"concat=n={len(segs)}:v=1:a=0[vcat]")
    for k, (sid, _, _) in enumerate(SCENES):
        inputs += ["-i", str(audio[sid][0])]
        ms = int(timeline[k][0] * 1000)
        filters.append(f"[{k + 1}:a]adelay={ms}|{ms}[a{k}]")
    filters.append("".join(f"[a{k}]" for k in range(len(SCENES))) + f"amix=inputs={len(SCENES)}:normalize=0[aout]")
    style = "FontName=Hiragino Sans GB,FontSize=14,PrimaryColour=&H00FFFFFF,BackColour=&H99000000,BorderStyle=4,Outline=0,Shadow=0,MarginV=26"
    filters.append(f"[vcat]subtitles={srt}:fontsdir=/System/Library/Fonts:force_style='{style}'[vout]")
    OUT.parent.mkdir(exist_ok=True)
    cmd = ["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(filters), "-map", "[vout]", "-map", "[aout]",
           "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-r", "30",
           "-c:a", "aac", "-b:a", "160k", "-t", f"{total:.2f}", "-movflags", "+faststart", str(OUT)]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    return OUT


def main():
    import sys
    audio = tts_all()
    print("配音总时长 %.1fs" % sum(d for _, d in audio.values()))
    cache = BUILD / "timeline.json"
    if "--recompose" in sys.argv and cache.exists():   # 只重新剪辑合成，不重新录制
        j = json.loads(cache.read_text(encoding="utf-8"))
        raw, timeline, total = Path(j["raw"]), [tuple(x) for x in j["timeline"]], j["total"]
    else:
        raw, timeline, total = record(audio)
        cache.write_text(json.dumps({"raw": str(raw), "timeline": timeline, "total": total}, ensure_ascii=False), encoding="utf-8")
    out = compose(raw, audio, timeline, total)
    print("视频已生成：", out, "时长 %.1fs" % duration(out))


if __name__ == "__main__":
    main()
