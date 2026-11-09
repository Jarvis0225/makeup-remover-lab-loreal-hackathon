"""开源大模型多模态研判（默认开源权重的 Qwen2.5-VL / Qwen2.5，经 OpenAI 兼容接口调用）。

赛题要求“使用开源大模型而非闭源模型”：默认模型均为开源权重模型，可通过阿里云 DashScope 调用，
也可设置 DASHSCOPE_BASE_URL 指向本地 vLLM / Ollama 等部署的同名开源模型。未配置 Key 时自动降级为纯本地取证模式。
"""
from __future__ import annotations

import base64
import io
import json
import os
import re

from PIL import Image

BASE_URL = os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
VL_MODEL = os.getenv("BG_VL_MODEL", "qwen2.5-vl-72b-instruct")   # 开源权重
TEXT_MODEL = os.getenv("BG_TEXT_MODEL", "qwen2.5-72b-instruct")   # 开源权重

SYSTEM = ("你是“美妆内容鉴真专家”，熟悉美妆种草内容生态、化妆品法规与图像取证。"
          "你必须客观、审慎，只依据可观察到的证据下结论，不确定时明确说明。只输出 JSON，不要输出其他文字。")

_client = None
_key_override: str | None = None


def set_api_key(key: str | None):
    global _client, _key_override
    _key_override = (key or "").strip() or None
    _client = None


def available() -> bool:
    return bool(_key_override or os.getenv("DASHSCOPE_API_KEY"))


def _get_client():
    global _client
    if _client is None:
        from openai import OpenAI
        _client = OpenAI(api_key=_key_override or os.getenv("DASHSCOPE_API_KEY"), base_url=BASE_URL, timeout=90)
    return _client


def _img_url(img: Image.Image, max_side=1280) -> str:
    im = img.convert("RGB")
    if max(im.size) > max_side:
        s = max_side / max(im.size)
        im = im.resize((int(im.width * s), int(im.height * s)))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=92)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _parse_json(s: str) -> dict:
    s = s.strip()
    m = re.search(r"\{.*\}", s, re.S)
    if not m:
        return {"raw": s}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {"raw": s}


def _chat(model, content, temperature=0.1) -> dict:
    resp = _get_client().chat.completions.create(
        model=model, temperature=temperature,
        messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": content}])
    return _parse_json(resp.choices[0].message.content)


def judge_image(img: Image.Image, context: str = "", forensic_hint: str = "") -> dict:
    prompt = f"""请鉴别这张美妆内容图片的真实性。
发布语境：{context or '未提供'}
传统取证工具的初步发现（供参考，可能有误报）：{forensic_hint or '无'}

请重点检查：
1. 是否为 AI 生成（皮肤/毛发纹理过度完美、手指/文字/Logo/瓶身文字畸形、光影不物理、背景语义错误）；
2. 是否被篡改/拼接（边缘光晕、光照方向不一致、透视错误、局部模糊或涂抹、产品被替换、批号/日期被修改）；
3. 美妆特有造假：前后对比图滤镜/磨皮夸大效果、试色色差、伪造检测报告/备案截图、冒用明星或专柜场景、包装与正品不符。

输出 JSON：{{"aigc_prob":0-1,"tamper_prob":0-1,"findings":[{{"issue":"","location":"图中位置描述","evidence":""}}],"reasoning":"一句话综合结论"}}"""
    return _chat(VL_MODEL, [{"type": "image_url", "image_url": {"url": _img_url(img)}}, {"type": "text", "text": prompt}])


def inspect_region(crop: Image.Image, why: str) -> dict:
    prompt = f"""这是从一张美妆图片中裁剪出的可疑区域，取证算法提示：{why}。
请放大审视该区域是否存在拼接边缘、涂抹、克隆纹理、文字/数字被修改或与周围不协调的痕迹。
输出 JSON：{{"suspicious":true/false,"prob":0-1,"observation":""}}"""
    return _chat(VL_MODEL, [{"type": "image_url", "image_url": {"url": _img_url(crop, 768)}}, {"type": "text", "text": prompt}])


def judge_text(text: str) -> dict:
    prompt = f"""请分析以下美妆种草文案：
\"\"\"{text[:3000]}\"\"\"

判断：(1) 是否疑似 AI 批量生成的“伪真人测评”；(2) 是否存在虚假/夸大/医疗化功效宣称、无依据数据、假货暗语、未标明广告；
(3) 是否像真实用户体验（有无具体肤质、使用周期、缺点等细节）。
输出 JSON：{{"aigc_prob":0-1,"false_claim_prob":0-1,"issues":[{{"quote":"原文片段","problem":""}}],"reasoning":""}}"""
    return _chat(TEXT_MODEL, prompt)


def cross_check(img: Image.Image, text: str) -> dict:
    prompt = f"""以下为同一篇美妆笔记的配图与文案：
\"\"\"{text[:1500]}\"\"\"
请检查图文是否一致：图中产品/品牌/色号/使用效果是否与文案宣称相符，是否存在“图不对文”、盗图、用他人效果图冒充自身体验。
输出 JSON：{{"consistent":true/false,"mismatch_prob":0-1,"issues":[""],"reasoning":""}}"""
    return _chat(VL_MODEL, [{"type": "image_url", "image_url": {"url": _img_url(img)}}, {"type": "text", "text": prompt}])


def final_review(bundle: dict) -> dict:
    prompt = f"""你是内容安全审核 Agent 的决策模块。以下是多个检测工具对一条美妆内容的结构化证据（JSON）：
{json.dumps(bundle, ensure_ascii=False)[:6000]}

请综合证据，避免被单一弱证据误导，给出：
输出 JSON：{{"verdict":"真实可信/存疑需复核/疑似伪造或违规","key_reasons":["按重要性排序的判定依据，引用具体证据"],
"advice_platform":"对平台的处置建议","advice_creator":"对创作者的整改建议","advice_consumer":"给消费者的提示"}}"""
    return _chat(TEXT_MODEL, prompt, temperature=0.2)
