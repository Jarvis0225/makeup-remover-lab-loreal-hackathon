"""评论区检测 · 真实数据验证：python -m eval.comment_realworld

数据：RedBookletReview（https://github.com/zz-zik/RedBookletReview，MIT），约 1.3 万条真实小红书评论。
注意：该数据集原始标注为情感（正/负面），并非水军标注，因此：
  实验 1：纯真实评论区 → 衡量“真实评论被误判为水军”的误报率；
  实验 2：在真实评论区中注入模板化刷评 → 衡量注入刷评的召回率与精确率（半合成）。
数据集无昵称/时间/账号信息，本实验只验证文本特征（雷同聚类、空泛好评、导流话术）。
"""
import json
import random
from pathlib import Path

import numpy as np
import pandas as pd

from core.comment_detect import analyze_comments

DATA = Path(__file__).resolve().parents[2] / "third_party" / "datasets" / "RedBookletReview"
OUT = Path(__file__).parent

OPEN = ["", "真的", "姐妹们", "亲测", "绝了，", "家人们", "谁懂啊"]
BODY = ["效果很好", "效果真的很好", "皮肤变好了", "白了一个度", "用完水水润润", "效果明显", "毛孔都小了", "痘痘全消了", "质地超好"]
CLOSE = ["强烈推荐！", "已经回购了", "闭眼入", "无限回购", "yyds", "物超所值", "冲就完事了", "五星好评！"]
EMO = ["", "", "❤️", "👍", "✨", "🔥"]


# 留出写法 B：手写、非模板拼接，不参与任何调参，用于检验是否过拟合模板 A
HELDOUT = ["这个真的太好用了吧必须安利给大家", "朋友推荐买的果然没失望，好评好评", "用了一周皮肤变好了，值得购买",
           "包装精美效果也不错，五星好评", "已经回购第三次了，非常好用推荐", "效果惊人！强烈推荐给姐妹们",
           "物超所值，真的很不错，推荐购买", "宝藏好物，闭眼入不会错", "回购无数次了，效果明显，爱了",
           "一直在用，非常好，强烈推荐", "真的很好用！已经推荐给闺蜜了", "颜值高效果好，值得购买，好评",
           "用完皮肤白了好多，正品，推荐", "超级好用，无限回购，yyds", "很不错，效果很好，会继续回购的"]


def load_real():
    texts = []
    for f in ["train.tsv", "dev.tsv", "test.tsv"]:
        df = pd.read_csv(DATA / "RedBookletReview" / f, sep="\t", quoting=3, on_bad_lines="skip")
        texts += df.iloc[:, 1].astype(str).tolist()
    df = pd.read_csv(DATA / "results" / "RedBookletReview.tsv", sep="\t", quoting=3, on_bad_lines="skip")
    texts += df["text"].astype(str).tolist()
    return sorted({t.strip() for t in texts if 4 <= len(t.strip()) <= 200})


def shill(r: random.Random):
    parts = [r.choice(OPEN), r.choice(BODY), "，" + r.choice(BODY) if r.random() < 0.4 else "", "，" + r.choice(CLOSE), r.choice(EMO)]
    return "".join(parts)


def run(n_sections=200, size=30, seed=7):
    r = random.Random(seed)
    real = load_real()
    res = {"real_pool": len(real), "n_sections": n_sections, "section_size": size}

    # 实验 1：纯真实评论区
    fp, total, sec_flag = 0, 0, 0
    for _ in range(n_sections):
        rep = analyze_comments(r.sample(real, size))
        fp += int((rep["table"]["label"] == "疑似水军").sum()); total += size
        sec_flag += int(rep["evidences"][0]["score"] >= 0.4)
    res["exp1"] = {"comment_fpr": round(fp / total, 4), "section_false_alarm": round(sec_flag / n_sections, 4)}

    # 实验 2：注入刷评（A=模板拼接，B=留出手写）
    res["exp2"] = {}
    for gen_name, gen in (("A模板", lambda: shill(r)), ("B留出", lambda: r.choice(HELDOUT))):
      for k in (3, 6, 10):
        tp = fp = fn = 0; sec_hit = 0
        for _ in range(n_sections):
            items = [(t, 0) for t in r.sample(real, size - k)] + [(gen(), 1) for _ in range(k)]
            r.shuffle(items)
            rep = analyze_comments([t for t, _ in items])
            pred = (rep["table"]["label"] == "疑似水军").values
            y = np.array([l for _, l in items], bool)
            tp += int((pred & y).sum()); fp += int((pred & ~y).sum()); fn += int((~pred & y).sum())
            sec_hit += int(rep["evidences"][0]["score"] >= 0.4)
        p, rc = tp / max(tp + fp, 1), tp / max(tp + fn, 1)
        res["exp2"][f"{gen_name}_inject_{k}_of_{size}"] = {"precision": round(p, 4), "recall": round(rc, 4),
                                                "f1": round(2 * p * rc / max(p + rc, 1e-9), 4), "section_detect": round(sec_hit / n_sections, 4)}
    return res


if __name__ == "__main__":
    res = run()
    print(json.dumps(res, ensure_ascii=False, indent=1))
    (OUT / "comment_realworld.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
