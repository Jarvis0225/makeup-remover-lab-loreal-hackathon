"""批量评测：python -m eval.run_eval [--llm]"""
import json
import sys
from pathlib import Path

from core import llm
from core.dataset import evaluate, load_posts

OUT = Path(__file__).parent


def main():
    use_llm = "--llm" in sys.argv and llm.available()
    df, m, dim_df, _ = evaluate(load_posts(), use_llm=use_llm, progress=lambda p, i: print(f"\r{p:.0%} {i}", end=""))
    print()
    df.to_csv(OUT / "results.csv", index=False, encoding="utf-8-sig")
    dim_df.to_csv(OUT / "dimension_metrics.csv", index=False, encoding="utf-8-sig")
    (OUT / "metrics.json").write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
    print(df[["id", "title", "label", "pred", "trust_score", "level", "truth_dims", "pred_dims"]].to_string())
    print(dim_df.to_string())
    print({k: (round(v, 3) if isinstance(v, float) else v) for k, v in m.items()}, "LLM:", use_llm)


if __name__ == "__main__":
    main()
