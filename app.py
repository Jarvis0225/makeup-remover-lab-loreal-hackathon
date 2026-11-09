"""BeautyGuard 美妆内容鉴真 Agent —— streamlit run app.py"""
from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from PIL import Image

from core import llm
from core.agent import DIMENSIONS, Content, VerifyAgent
from core.dataset import DATA, evaluate, load_posts, to_content
from core.report import to_json, to_markdown
from core.text_detect import highlight_html

st.set_page_config(page_title="BeautyGuard · 美妆内容鉴真 Agent", page_icon="🛡️", layout="wide")
st.markdown("""<style>
.block-container{padding-top:1.6rem}
.vcard{border-radius:14px;padding:18px 22px;color:white;margin-bottom:8px}
.vcard h2{margin:0;color:white}.vcard p{margin:4px 0 0 0;opacity:.95}
.tag{display:inline-block;padding:2px 10px;margin:2px;border-radius:12px;background:#fee2e2;color:#b91c1c;font-size:13px}
.step{border-left:3px solid #e11d48;padding:4px 10px;margin:4px 0;background:#fff7f8;border-radius:4px;font-size:14px}
.step b{color:#be123c}
</style>""", unsafe_allow_html=True)

# ------------------------------------------------------------------ 侧栏
with st.sidebar:
    st.markdown("## 🛡️ BeautyGuard\n**信任守护师 · 创造者的 AI 卫士**")
    key = st.text_input("DashScope API Key（可选）", type="password", help="接入开源 Qwen2.5-VL / Qwen2.5 做语义级研判；不填则使用本地取证模式")
    if key:
        llm.set_api_key(key)
    use_llm = st.toggle("启用开源大模型多模态研判", value=llm.available(), disabled=not llm.available())
    st.caption(f"状态：{'✅ 大模型已接入（' + llm.VL_MODEL + ' / ' + llm.TEXT_MODEL + '）' if llm.available() else '⚪ 本地取证模式'}")
    st.divider()
    st.markdown("""**检测能力**
- 🖼️ 图片：拼接 / 复制-移动 / 局部磨皮 / AI 生成 / 元数据
- 📝 文案：违规功效宣称 / 假货暗语 / 未标广告 / AI 文案
- 💬 评论：雷同刷评 / 时间爆发 / 水军账号
- 🔗 图文一致性（大模型）""")

# ------------------------------------------------------------------ 结果渲染
def gauge(score, color):
    fig = go.Figure(go.Indicator(mode="gauge+number", value=score, number={"suffix": "/100"},
                                 gauge={"axis": {"range": [0, 100]}, "bar": {"color": color},
                                        "steps": [{"range": [0, 25], "color": "#fee2e2"}, {"range": [25, 50], "color": "#ffedd5"},
                                                  {"range": [50, 75], "color": "#fef9c3"}, {"range": [75, 100], "color": "#dcfce7"}]},
                                 title={"text": "内容可信分"}))
    fig.update_layout(height=230, margin=dict(l=20, r=20, t=40, b=0))
    return fig


def radar(dims):
    names = [DIMENSIONS[d] for d in dims] + [DIMENSIONS[list(dims)[0]]]
    vals = list(dims.values()) + [list(dims.values())[0]]
    fig = go.Figure(go.Scatterpolar(r=vals, theta=names, fill="toself", line_color="#e11d48"))
    fig.update_layout(polar=dict(radialaxis=dict(range=[0, 1])), height=260, margin=dict(l=40, r=40, t=20, b=20), showlegend=False)
    return fig


def render_trace(trace):
    for i, t in enumerate(trace, 1):
        st.markdown(f"<div class='step'><b>Step {i} · {t['stage']}</b> <code>{t['tool']}</code> <span style='color:#888'>{t['ms']}ms</span><br>"
                    f"💭 {t['thought']}<br>👁️ {t['observation']}</div>", unsafe_allow_html=True)


def render_verdict(v, title="", text=""):
    c1, c2, c3 = st.columns([1.3, 1, 1.2])
    with c1:
        st.markdown(f"<div class='vcard' style='background:{v.color}'><h2>{v.verdict}</h2>"
                    f"<p>{v.level} · 综合风险 {v.risk:.2f}</p></div>", unsafe_allow_html=True)
        st.markdown("".join(f"<span class='tag'>{t}</span>" for t in v.tags) or "<span class='tag' style='background:#dcfce7;color:#166534'>未发现明显风险</span>",
                    unsafe_allow_html=True)
        st.markdown("**核心判定依据**")
        for r in v.reasons[:5]:
            st.markdown(f"- {r}")
    c2.plotly_chart(gauge(v.trust_score, v.color), width="stretch")
    c3.plotly_chart(radar(v.dims), width="stretch")

    tabs = st.tabs(["🖼️ 图片取证", "📝 文案分析", "💬 评论区", "🧭 处置建议", "🔎 全部证据", "🤖 Agent 轨迹", "📄 报告导出"])
    with tabs[0]:
        if not v.image_reports:
            st.info("未提供图片")
        for name, img, rep in v.image_reports:
            st.markdown(f"#### {name}")
            views = [("原图", img.convert("RGB")), ("可疑区域热力图", rep.heatmap), ("TruFor 篡改概率图", rep.trufor_vis),
                     ("ELA 误差图", rep.ela_vis), ("噪声残差图", rep.noise_vis), ("复制-移动匹配", rep.copymove_vis)]
            views = [v for v in views if v[1] is not None]
            for col, (cap, im) in zip(st.columns(len(views)), views):
                col.image(im, caption=cap, width="stretch")
            for e in sorted(rep.evidences, key=lambda e: -e["score"]):
                icon = "🔴" if e["score"] >= 0.5 else ("🟠" if e["score"] >= 0.25 else "🟢")
                st.markdown(f"{icon} **{e['name']}** `{e['score']:.2f}` — {e['summary']}")
            llm_evs = [e for e in v.evidences if e.get("source") == name and ("Qwen" in e["name"] or "放大" in e["name"])]
            for e in llm_evs:
                st.markdown(f"🤖 **{e['name']}** `{e['score']:.2f}` — {e['summary']}")
            with st.expander("元数据详情"):
                st.json(rep.meta, expanded=False)
    with tabs[1]:
        if v.text_report:
            st.markdown("**可疑片段高亮**（悬停查看原因）")
            st.markdown(f"<div style='line-height:2;padding:12px;border:1px solid #eee;border-radius:8px'>{highlight_html(text, v.text_report['hits'])}</div>",
                        unsafe_allow_html=True)
            if v.text_report["hits"]:
                st.dataframe(pd.DataFrame(v.text_report["hits"])[["text", "category", "reason", "suggest", "law"]]
                             .rename(columns={"text": "片段", "category": "类别", "reason": "原因", "suggest": "合规替换建议", "law": "法规"}),
                             width="stretch", hide_index=True)
            if v.text_report.get("exempted"):
                with st.expander(f"已排除的合法语境（{len(v.text_report['exempted'])} 处，避免误报）"):
                    for e in v.text_report["exempted"]:
                        st.markdown(f"- “{e['text']}”（…{e['context']}…）：{e['reason']}")
            for e in [e for e in v.evidences if e.get("source") == "文案"]:
                st.markdown(f"- **{e['name']}** `{e['score']:.2f}` — {e['summary']}")
            with st.expander("AI 文案统计特征"):
                st.json(v.text_report["features"])
        else:
            st.info("未提供文案")
    with tabs[2]:
        if v.comment_report is not None:
            cr = v.comment_report
            st.markdown(cr["evidences"][0]["summary"])
            df = cr["table"][["user", "time", "text", "suspicion", "label", "reasons"]].sort_values("suspicion", ascending=False)
            st.dataframe(df.style.apply(lambda r: ["background-color:#fee2e2" if r["label"] == "疑似水军" else
                                                   ("background-color:#fef9c3" if r["label"] == "存疑" else "")] * len(r), axis=1),
                         width="stretch", hide_index=True)
            if cr["clusters"]:
                st.markdown("**雷同评论簇**")
                for k, c in enumerate(cr["clusters"], 1):
                    st.markdown(f"簇 {k}（{len(c)} 条）：" + " / ".join(f"“{cr['table'].loc[i, 'text']}”" for i in c[:4]))
        else:
            st.info("未提供评论")
    with tabs[3]:
        a = v.actions
        c1, c2, c3 = st.columns(3)
        c1.markdown("##### 🏛️ 平台处置\n" + "\n".join(f"- {x}" for x in a.get("platform", [])))
        c2.markdown("##### ✍️ 创作者整改\n" + "\n".join(f"- {x}" for x in a.get("creator", [])))
        c3.markdown("##### 🛍️ 消费者提示\n" + "\n".join(f"- {x}" for x in a.get("consumer", [])))
        if a.get("laws"):
            with st.expander("📚 法规依据", expanded=True):
                for k, t in a["laws"].items():
                    st.markdown(f"- **{k}**：{t}")
        if v.llm_review:
            st.markdown("##### 🤖 大模型复核意见")
            st.json(v.llm_review)
    with tabs[4]:
        st.dataframe(pd.DataFrame([{"来源": e.get("source"), "证据": e["name"], "维度": DIMENSIONS.get(e["category"], e["category"]),
                                    "分数": round(e["score"], 2), "置信度": e["confidence"], "说明": e["summary"]} for e in v.evidences]),
                     width="stretch", hide_index=True)
    with tabs[5]:
        render_trace(v.trace)
    with tabs[6]:
        md = to_markdown(v, title)
        c1, c2 = st.columns(2)
        c1.download_button("⬇️ 下载 Markdown 报告", md, f"report_{v.content_id}.md", "text/markdown")
        c2.download_button("⬇️ 下载 JSON 结构化结果", to_json(v), f"report_{v.content_id}.json", "application/json")
        st.markdown(md)


def run_agent(content: Content):
    box = st.status("🤖 核验 Agent 运行中…", expanded=True)
    def on_step(t):
        box.markdown(f"**{t['stage']}** · `{t['tool']}` — {t['thought']}  \n↳ {t['observation']}")
    v = VerifyAgent(use_llm=use_llm, on_step=on_step).run(content)
    box.update(label=f"✅ 核验完成：{v.verdict}（可信分 {v.trust_score}）", state="complete", expanded=False)
    return v


# ------------------------------------------------------------------ 页面
st.markdown("# 🛡️ BeautyGuard · 美妆内容鉴真 Agent")
st.caption("“你还相信你看到的吗？” —— 识别种草文案、评论区与 AI 素材中的篡改、拼接与伪造，给出可解释判定与处置建议")
tab1, tab2, tab3 = st.tabs(["🔍 单条内容核验", "📊 数据集闭环（识别→决策）", "📘 方法与依据"])
posts = load_posts() if (DATA / "posts.json").exists() else []

with tab1:
    src = st.radio("内容来源", ["演示数据集样例", "小红书截图", "自定义上传"], horizontal=True)
    if src == "小红书截图":
        st.caption("上传笔记详情页截图（可多张：正文页 + 评论页）。自动裁出配图，并用 "
                   + ("Qwen-VL" if llm.available() else "开源 RapidOCR") + " 提取标题、正文与评论；提取结果可手动修正后再核验。")
        demo_dir = DATA / "screenshots"
        demo_sets = {"模拟截图：假货 + 违规宣称 + 水军": ["xhs_mock_fake.png"],
                     "模拟截图：真实测评": ["xhs_mock_genuine.png"]}
        demo_sets = {k: v for k, v in demo_sets.items() if all((demo_dir / f).exists() for f in v)}
        c1, c2 = st.columns([1, 1])
        shots = c1.file_uploader("上传截图", type=["png", "jpg", "jpeg", "webp"], accept_multiple_files=True)
        pick = c2.selectbox("或使用示例截图", ["—"] + list(demo_sets), index=1 if demo_sets else 0)
        imgs_in = [Image.open(io.BytesIO(f.getvalue())) for f in shots or []] or \
                  ([Image.open(demo_dir / f) for f in demo_sets[pick]] if pick != "—" else [])
        if imgs_in and st.button("📷 解析截图", key="parse_shot"):
            from core.screenshot import merge, parse_screenshot
            with st.spinner("解析截图中…"):
                st.session_state["shot"] = (merge([parse_screenshot(im) for im in imgs_in]), imgs_in)
                st.session_state["shot_n"] = st.session_state.get("shot_n", 0) + 1
        if "shot" in st.session_state:
            m, raw_imgs = st.session_state["shot"]
            sk = st.session_state.get("shot_n", 0)  # 每次重新解析换一组控件 key，避免沿用上一张截图的内容
            c1, c2, c3 = st.columns([0.8, 1, 1.4])
            for k, ri in enumerate(raw_imgs):
                c1.image(ri, caption=f"原始截图 {k + 1}", width="stretch")
            for k, ph in enumerate(m["photos"]):
                c2.image(ph, caption=f"自动裁出的配图 {k + 1}", width="stretch")
            with c3:
                st.caption(f"解析方式：{' / '.join(m['methods'])}")
                title = st.text_input("标题", m["title"], key=f"shot_title_{sk}")
                text = st.text_area("正文", m["text"], height=170, key=f"shot_text_{sk}")
                cdf = st.data_editor(pd.DataFrame(m["comments"] or [{"user": "", "time": None, "text": ""}]), num_rows="dynamic",
                                     width="stretch", key=f"shot_comments_{sk}")
            if st.button("🚀 开始核验", type="primary", key="run_shot"):
                imgs = []
                for k, ph in enumerate(m["photos"]):
                    buf = io.BytesIO(); ph.save(buf, "PNG")
                    imgs.append((f"截图配图{k + 1}.png", ph, buf.getvalue()))
                comments = cdf[cdf["text"].astype(str).str.strip() != ""]
                st.session_state["single"] = (run_agent(Content("screenshot", title, text, imgs, comments if len(comments) else None,
                                                                meta={"screenshot": True})), title, text)
    elif src == "演示数据集样例" and posts:
        opt = {f"{p['id']} · {p['title']}": p for p in posts}
        p = opt[st.selectbox("选择样例笔记", list(opt))]
        c1, c2 = st.columns([1, 1.4])
        with c1:
            for rel in p["images"]:
                st.image(str(DATA / rel), width="stretch")
        with c2:
            st.markdown(f"**{p['title']}**")
            st.text(p["text"])
            st.caption(f"评论 {len(p['comments'])} 条 · 真值：{'伪造/违规' if p['label'] else '真实'} {p['truth_dims']}")
        if st.button("🚀 开始核验", type="primary", key="run_sample"):
            st.session_state["single"] = (run_agent(to_content(p)), p["title"], p["text"])
    else:
        c1, c2 = st.columns(2)
        with c1:
            title = st.text_input("笔记标题")
            text = st.text_area("种草文案", height=200, placeholder="粘贴笔记正文…")
            files = st.file_uploader("配图（可多张）", type=["jpg", "jpeg", "png", "webp"], accept_multiple_files=True)
        with c2:
            ctext = st.text_area("评论区（每行一条，可用 `昵称|时间|内容` 格式）", height=200,
                                 placeholder="小鹿|2026-10-01 10:00|用了两周还行\n用户123456|2026-10-01 10:01|效果很好强烈推荐")
            cfile = st.file_uploader("或上传评论 CSV（列：user,time,text[,account_age_days,followers,posts]）", type=["csv"])
        if st.button("🚀 开始核验", type="primary", key="run_custom"):
            imgs = []
            for f in files or []:
                raw = f.getvalue()
                imgs.append((f.name, Image.open(io.BytesIO(raw)), raw))
            comments = pd.read_csv(cfile) if cfile else (ctext if ctext.strip() else None)
            if not (imgs or text.strip() or comments is not None):
                st.warning("请至少提供图片、文案或评论之一")
            else:
                st.session_state["single"] = (run_agent(Content("custom", title, text, imgs, comments)), title, text)
    if "single" in st.session_state:
        st.divider()
        render_verdict(*st.session_state["single"])

with tab2:
    st.markdown("在带真值标签的演示数据集上批量运行 Agent，展示 **识别 → 研判 → 风险分级 → 处置工单** 的完整闭环与量化效果。")
    if st.button("▶️ 批量运行数据集", type="primary"):
        bar = st.progress(0.0)
        res = evaluate(posts, use_llm=use_llm, progress=lambda p, i: bar.progress(p, text=f"核验 {i}"))
        st.session_state["batch"] = res
    if "batch" in st.session_state:
        df, m, dim_df, verdicts = st.session_state["batch"]
        cols = st.columns(5)
        for col, k in zip(cols, ["样本数", "准确率", "精确率", "召回率", "F1"]):
            col.metric(k, f"{m[k]:.1%}" if isinstance(m[k], float) else m[k])
        c1, c2, c3 = st.columns([1, 1.2, 1.2])
        cm = m["confusion"]
        fig = go.Figure(go.Heatmap(z=[[cm["TN"], cm["FP"]], [cm["FN"], cm["TP"]]], x=["预测真实", "预测伪造/违规"], y=["实际真实", "实际伪造/违规"],
                                   text=[[cm["TN"], cm["FP"]], [cm["FN"], cm["TP"]]], texttemplate="%{text}", colorscale="Reds", showscale=False))
        fig.update_layout(height=280, margin=dict(l=10, r=10, t=30, b=10), title="混淆矩阵")
        c1.plotly_chart(fig, width="stretch")
        lv = df["level"].value_counts().reindex(["低风险", "中风险", "高风险", "极高风险"]).fillna(0)
        fig2 = go.Figure(go.Pie(labels=lv.index, values=lv.values, hole=.45, marker_colors=["#16a34a", "#ca8a04", "#ea580c", "#dc2626"]))
        fig2.update_layout(height=280, margin=dict(l=10, r=10, t=30, b=10), title="风险分级分布")
        c2.plotly_chart(fig2, width="stretch")
        c3.markdown("**分维度检出效果**")
        c3.dataframe(dim_df, hide_index=True, width="stretch")
        st.markdown("#### 🗂️ 处置工单（按风险排序）")
        show = df.sort_values("risk", ascending=False)[["id", "title", "trust_score", "level", "verdict", "pred_dims", "truth_dims", "action", "label"]]
        show = show.rename(columns={"trust_score": "可信分", "level": "风险等级", "verdict": "结论", "pred_dims": "检出问题", "truth_dims": "真值问题",
                                    "action": "首要处置动作", "label": "真值(1=伪造)"})
        st.dataframe(show, hide_index=True, width="stretch")
        st.download_button("⬇️ 导出评测结果 CSV", df.to_csv(index=False).encode("utf-8-sig"), "batch_results.csv", "text/csv")
        pick = st.selectbox("查看单条详情", list(verdicts))
        p = next(x for x in posts if x["id"] == pick)
        render_verdict(verdicts[pick], p["title"], p["text"])

with tab3:
    st.markdown("### 系统架构")
    st.graphviz_chart("""digraph G { rankdir=LR; node[shape=box style="rounded,filled" fillcolor="#fff1f2" color="#e11d48" fontname="PingFang SC"];
in[label="美妆笔记\\n图片+文案+评论"]; plan[label="感知与规划\\nPlanner"];
subgraph cluster_t{label="工具层"; style=dashed; img[label="图像取证\\nELA/噪声/复制-移动\\n元数据/频域"]; vlm[label="Qwen-VL\\n视觉研判+区域放大"];
txt[label="文案检测\\n违规词库+法规库\\nAI文案特征"]; qw[label="Qwen\\n语义研判"]; cm[label="评论检测\\n聚类/爆发/画像"]; cross[label="图文一致性"];}
fuse[label="证据融合\\n置信度加权 Noisy-OR"]; pol[label="风险决策\\n分级+策略库"]; rev[label="大模型复核"]; out[label="可解释报告\\n平台/创作者/消费者"];
in->plan; plan->img; plan->txt; plan->cm; img->vlm[label="可疑区域"]; plan->vlm; txt->qw; plan->cross; img->fuse; vlm->fuse; txt->fuse; qw->fuse; cm->fuse; cross->fuse; fuse->pol->rev->out; }""")
    st.markdown("""
### 检测方法
| 模态 | 方法 | 能发现的造假 |
|---|---|---|
| 图片 | **ELA 误差水平分析**（纹理回归去内容化 + 强边缘屏蔽） | 粘贴的“正品认证”贴纸、替换的产品、修改的批号 |
| 图片 | **传感器噪声一致性**（中值残差分块 + 鲁棒 z 分数） | 前后对比图局部磨皮/美白、跨来源拼接 |
| 图片 | **复制-移动检测**（SIFT 自匹配 + 位移聚类 + RANSAC 纯平移校验） | 复制产品伪造“满柜现货”、遮盖瑕疵 |
| 图片 | **元数据取证**（EXIF/PNG 文本块/C2PA/AIGC 隐式标识） | 美图/PS 处理痕迹、SD/ComfyUI 生成参数 |
| 图片 | **频域 + 纹理统计** | 生成模型上采样网格伪影、过度平滑的“完美皮肤” |
| 图片 | **Qwen-VL 语义研判 + 可疑区域放大复核** | 畸形文字/Logo、光影不一致、试色色差、伪造报告 |
| 文案 | **违规宣称词库 × 法规知识库** | 极限词、医疗化宣称、时限效果承诺、假货暗语、站外导流 |
| 文案 | **AI 文案统计特征**（句长变异、套话密度、细节密度、模板排版） | AI 批量生成的“伪真人测评” |
| 评论 | **字符 n-gram 近重复聚类 + 时间爆发 + 账号画像** | 水军刷评、好评返现、批量注册账号 |

### 决策逻辑
1. 每条证据给出 `score`（异常程度）与 `confidence`（方法可靠度）；
2. 维度内 **Noisy-OR 融合**：多路证据互相印证时风险上升，单一弱证据被抑制；
3. 维度间加权得综合风险 → **可信分 = 100 × (1 − 风险)**；
4. 风险分级：低（<0.25 放行）/ 中（打标抽检）/ 高（限流+人工复核）/ 极高（下架+留证+申诉通道）；
5. 按命中维度匹配策略库，生成 **平台 / 创作者 / 消费者** 三方建议，并附法规依据。
""")
