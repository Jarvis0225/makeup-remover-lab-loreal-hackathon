# BeautyGuard · 美妆内容鉴真 Agent

> 欧莱雅美妆科技黑客松 · 赛题2「信任守护师 —— 创造者的 AI 卫士」
>
> 队伍：**卸妆水研究所 · Makeup Remover Lab**（卸掉 AI 与滤镜的“妆”，还原内容的真实）
>
> “你还相信你看到的吗？” 识别种草文案、评论区与 AI 素材中被篡改、拼接或伪造的文案与图片，
> 给出**可解释**的判定依据，并输出**风险预警与处置建议**，形成从识别到决策的完整闭环。

## 快速开始

```bash
cd beautyguard
python3 -m venv .venv && source .venv/bin/activate        # 或 uv venv
pip install -r requirements.txt
python -m data.build_dataset                               # 生成演示数据集（已附带，可跳过）
streamlit run app.py                                       # 打开 http://localhost:8501
```

可选：接入**开源**多模态大模型 Qwen2.5-VL / Qwen2.5（语义级研判、可疑区域放大复核、图文一致性、最终复核）。
按赛题要求只使用开源权重模型：可经阿里云 DashScope 调用，也可本地 vLLM/Ollama 部署后用 `DASHSCOPE_BASE_URL` 指向本地。

```bash
export DASHSCOPE_API_KEY=sk-xxx       # 或在页面侧栏粘贴
# 默认开源模型：BG_VL_MODEL=qwen2.5-vl-72b-instruct  BG_TEXT_MODEL=qwen2.5-72b-instruct
# 本地部署：DASHSCOPE_BASE_URL=http://localhost:8000/v1（vLLM 的 OpenAI 兼容接口）
```

未配置 Key 时系统自动降级为**纯本地取证模式**，全流程仍可运行。

可选：接入开源深度篡改定位模型 **TruFor**（显著提升拼接检测，且抗平台重压缩），安装方法与许可证见 [THIRD_PARTY.md](THIRD_PARTY.md)。
未安装 torch 或缺少权重时自动跳过。违规词库已合并开源 china-compliance-skills（MIT）。

## 命令行评测

```bash
python -m eval.run_eval            # 数据集闭环评测 → eval/results.csv, metrics.json, dimension_metrics.csv
python -m eval.run_eval --llm      # 叠加大模型研判
python -m eval.robustness          # 留出集 + 平台重压缩/缩放鲁棒性 → eval/robustness.json
python -m eval.comment_realworld   # 1 万条真实小红书评论上的误报率 + 刷评注入召回 → eval/comment_realworld.json
python -m data.build_screenshots   # 重新生成模拟小红书截图（截图入口演示用）
python -m video.make_video         # 自动录制带中文配音+字幕的演示视频 → docs/BeautyGuard_演示视频.mp4（需先启动 Demo、联网）
python -m video.make_video --recompose   # 只重新剪辑合成（改字幕/剪辑参数时用，不重录）
python -m eval.probe_images        # 逐图查看各取证器得分（阈值标定用）
```

## 目录结构

```
beautyguard/
├── app.py                    Streamlit 界面：单条核验 / 数据集闭环 / 方法说明
├── core/
│   ├── agent.py              核验 Agent：感知规划 → 工具调用 → 自适应深挖 → 融合 → 决策 → 报告
│   ├── image_forensics.py    ELA、噪声一致性、复制-移动、元数据、频域 AIGC 线索、热力图
│   ├── text_detect.py        违规宣称 / 未标广告 / AI 文案统计特征
│   ├── comment_detect.py     评论近重复聚类、同质化好评、时间爆发、账号画像
│   ├── screenshot.py         小红书截图解析：配图裁剪 + RapidOCR / Qwen-VL 提取正文与评论
│   ├── trufor_tool.py        TruFor 深度篡改定位（开源，CVPR 2023）封装
│   ├── lexicon_oss.py        开源违禁词库（china-compliance-skills，MIT）
│   ├── knowledge.py          违规词库 + 上下文豁免 + 法规知识库（广告法、化妆品监督管理条例、AIGC 标识办法等）
│   ├── llm.py                开源 Qwen2.5-VL / Qwen2.5（OpenAI 兼容接口：DashScope 或本地 vLLM）
│   ├── dataset.py            数据集加载与批量评测
│   └── report.py             Markdown / JSON 报告导出
├── data/
│   ├── build_dataset.py      演示数据集生成器（带真值）
│   ├── images/               17 张图片：真实/拼接/复制-移动/磨皮对比图/AI 生成
│   └── posts.json            18 条笔记（图 + 文 + 评论 + 真值标签）
├── eval/                     评测脚本与结果
└── docs/                     方案说明书、答辩 PPT
```

## 关于演示数据集的说明

`data/` 中的图片为**程序化合成**（模拟相机传感器噪声、JPEG 压缩与 EXIF），再施加真实世界常见的造假操作，
用于完整展示「识别 → 决策」闭环。取证阈值在该数据集上标定，因此 `run_eval` 的指标反映的是**流程正确性**，
不代表真实场景精度；`eval/robustness.py` 使用未参与标定的新随机种子与平台重压缩/缩放来评估泛化能力。
真实部署前应在 CASIA v2、Columbia、IMD2020（篡改）与 GenImage（AIGC）等公开数据集及真实平台样本上重新标定。
