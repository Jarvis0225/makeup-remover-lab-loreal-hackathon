"""抓取 Demo 界面元素级截图供 PPT 使用：python -m docs.capture_ui（需 Streamlit 在 8501 运行）"""
from pathlib import Path

from playwright.sync_api import sync_playwright

from video.make_video import URL, button, click, select, show, tab, top, vis, wait_done, wait_idle

OUT = Path(__file__).parent / "assets" / "ui"


def el(page, name, loc, max_h=None):
    loc = loc.first
    loc.scroll_into_view_if_needed()
    page.wait_for_timeout(700)
    box = loc.bounding_box()
    if max_h and box["height"] > max_h:
        page.evaluate("y=>window.scrollBy(0,0)", 0)
        page.screenshot(path=str(OUT / f"{name}.png"), clip={"x": box["x"], "y": box["y"], "width": box["width"], "height": max_h}, full_page=True)
    else:
        loc.screenshot(path=str(OUT / f"{name}.png"))


def panel(page):
    return page.locator('[data-testid="stTabPanel"]').filter(visible=True).filter(has=page.locator("text=/./")).last


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        b = pw.chromium.launch(channel="chrome", headless=True)
        p = b.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=2)
        p.set_default_timeout(90000)
        p.goto(URL); p.get_by_text("BeautyGuard · 美妆内容鉴真 Agent").first.wait_for(); wait_idle(p)
        # 隐藏顶部悬浮栏，避免截图时遮挡内容
        p.add_style_tag(content='[data-testid="stHeader"],[data-testid="stToolbar"],[data-testid="stDecoration"]{display:none!important}')
        select(p, 0, "P07 · 美白精华全网第一")
        button(p, "🚀 开始核验"); wait_done(p)
        hb = p.locator('[data-testid="stHorizontalBlock"]').filter(has=p.locator(".vcard"))
        el(p, "verdict", hb)
        for name, t, h in [("tab_image", "🖼️ 图片取证", 520), ("tab_text", "📝 文案分析", 420), ("tab_comment", "💬 评论区", 420)]:
            show(p, "核心判定依据"); tab(p, t)
            el(p, name, panel(p), max_h=h)
        show(p, "核心判定依据"); tab(p, "🧭 处置建议")
        el(p, "tab_action", p.locator('[data-testid="stHorizontalBlock"]').filter(has=p.get_by_text("平台处置")).filter(visible=True))
        top(p); click(p, vis(p.get_by_text("小红书截图", exact=True))); wait_idle(p)
        button(p, "📷 解析截图"); p.get_by_text("自动裁出的配图").first.wait_for(); wait_idle(p)
        el(p, "screenshot_parse", p.locator('[data-testid="stHorizontalBlock"]').filter(has=p.get_by_text("自动裁出的配图")).last)
        button(p, "🚀 开始核验"); wait_done(p)
        el(p, "screenshot_verdict", p.locator('[data-testid="stHorizontalBlock"]').filter(has=p.locator(".vcard")))
        top(p); tab(p, "📊 数据集闭环（识别→决策）"); button(p, "▶️ 批量运行数据集")
        p.get_by_text("处置工单").first.wait_for(timeout=180000); wait_idle(p)
        el(p, "batch_metrics", p.locator('[data-testid="stHorizontalBlock"]').filter(has=p.get_by_text("准确率")).first)
        el(p, "batch_charts", p.locator('[data-testid="stHorizontalBlock"]').filter(has=p.get_by_text("分维度检出效果")).first)
        el(p, "batch_orders", p.locator('[data-testid="stDataFrame"]').filter(visible=True).nth(1))
        b.close()
    print(sorted(f.name for f in OUT.iterdir() if "crop" not in f.name))


if __name__ == "__main__":
    main()
