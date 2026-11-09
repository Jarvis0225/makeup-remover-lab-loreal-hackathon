# 第三方开源组件

| 组件 | 用途 | 来源 | 许可证 | 集成方式 |
|---|---|---|---|---|
| **TruFor**（CVPR 2023） | 深度篡改检测与定位（拼接/局部修补/AI 局部编辑） | https://github.com/grip-unina/TruFor | GRIP-UNINA License：**仅限非营利/研究用途**，需保留版权声明并注明原作者 | `../third_party/TruFor`（未修改上游代码），由 `core/trufor_tool.py` 调用 |
| **cn-compliance-guard** 词库 | 广告法违禁词（绝对化、医疗、虚假宣传、诱导消费、贬低竞品）+ 安全替换建议 | https://github.com/feichangai-team/china-compliance-skills | MIT | 已按美妆场景筛选并合并至 `core/lexicon_oss.py`，保留署名 |
| **RapidOCR** | 小红书截图入口：提取标题/正文/评论 | https://github.com/RapidAI/RapidOCR | Apache-2.0 | pip 依赖 `rapidocr-onnxruntime`，由 `core/screenshot.py` 调用 |
| **RedBookletReview** 数据集 | 评论区检测的真实数据验证（约 1.08 万条真实小红书评论） | https://github.com/zz-zik/RedBookletReview | MIT | `../third_party/datasets/RedBookletReview`，由 `eval/comment_realworld.py` 读取；原标注为情感，未作水军真值 |
| content-compliance-checker | 上下文豁免与否定语境检测的**思路** | https://github.com/mengbao/content-compliance-checker | 未声明许可证 | 仅参考思路，在 `core/knowledge.py` 中独立实现，未拷贝其词表 |

## 关于小红书数据来源

- 小红书开放平台只提供电商类接口（商品/订单/物流等），**没有笔记、配图、评论的读取接口**。
- 本项目不使用爬虫抓取小红书（违反平台协议，且评论含他人个人信息）。
- 截图入口示例：`xhs_mock_*.png` 为按小红书版式**模拟生成**，不含真实用户信息。比赛中使用过的真实笔记截图含他人昵称，**未随公开仓库发布**。
  使用真实截图时请对他人昵称、头像打码；系统结论仅为风险提示，不构成对品牌或博主的违规认定。

## TruFor 安装

```bash
cd ..  # 项目根目录
mkdir -p third_party && cd third_party
git clone --depth 1 https://github.com/grip-unina/TruFor.git
# 官方权重（260MB）：https://www.grip.unina.it/download/prog/TruFor/TruFor_weights.zip ，解压得到 trufor.pth.tar
mkdir -p weights && mv <解压路径>/trufor.pth.tar weights/
```

- 可用环境变量覆盖：`TRUFOR_WEIGHTS`（权重路径）、`TRUFOR_DEVICE`（cpu/mps/cuda，默认自动）、`TRUFOR_MAX_SIDE`（默认 1024）。
- 权重以 `torch.load(weights_only=True)` 安全模式加载，仅放行 numpy 标量元数据。
- Apple Silicon 上自动使用 MPS，单图约 1–2 秒；纯 CPU 约 7–20 秒。

**参赛/商用提示**：TruFor 许可禁止营利性使用。比赛演示属于非营利研究用途；若后续商业化，需替换为商用许可模型或联系 GRIP-UNINA 获取授权。
