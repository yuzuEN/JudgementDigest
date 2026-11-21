"""
民事被告端的「答辯索引」：用判決的被告答辯段建 TF-IDF，讓被告寫的答辯也能影響相似判決。

    python -m retrieval.defense_index build       # → artifacts/retrieval_civil_defense_v1/（從 retrieval_civil_v6 的 sections 表建）
    python -m retrieval.defense_index evaluate    # 只用主張 vs 主張＋答辯（不同權重），輸出 defense_retrieval_eval.md

主張索引（retrieval_civil_v6/index.joblib）是判決的原告主張；這個索引的列順序和它完全相同（cases 表的 row），
所以兩個相似度可以直接加權合併：sim = (1 − w)·主張相似度 ＋ w·答辯相似度。
答辯太短（少於 MIN_DEFENSE 字，例如一造辯論沒有答辯）的判決在這個索引裡是零向量，答辯相似度是 0。

答辯段是遮名後的文字（【被告1】這類標記），建索引前拿掉標記、去掉空白，和使用者輸入的處理（prepare_input）對齊。
"""
import argparse
import json
import re
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
from sklearn.metrics import roc_auc_score

import config
from civil.dataset.text import prepare_input
from retrieval import build as retrieval_build
from retrieval.engine import TfidfIndex

NAME = "retrieval_civil_defense_v1"
MIN_DEFENSE = 30          # 答辯少於這個字數的判決不建（零向量）
VOCAB_SAMPLE = 60_000
MASK_TAG = re.compile(r"【[^】]{0,12}】")

# 評估
N_QUERIES = 3000
K = 30                    # 和後端統計用的件數（N_NEIGHBORS）相同
MIN_SAME_MID = 10
NEAR_DUPLICATE = 0.9      # 主張相似度這麼高的鄰居視為同一案的分案或制式起訴，兩種方法都排除
WEIGHTS = (0.0, 0.2, 0.3, 0.4, 0.5, 0.6, 0.8, 1.0)
SEED = 0


def artifact_dir(base: Optional[Path] = None) -> Path:
    return Path(base or config.ARTIFACTS_DIR) / NAME


def clean_defense(text: str) -> str:
    return prepare_input(MASK_TAG.sub("", text or ""))


def _read(retrieval_dir: Path, sql: str):
    with closing(sqlite3.connect(f"file:{retrieval_dir / 'cases.sqlite'}?mode=ro", uri=True)) as con:
        return con.execute(sql).fetchall()


def load_defenses(retrieval_dir: Path) -> List[str]:
    """依 cases 表的 row 順序，回傳每件判決處理過的答辯（太短的是空字串）。"""
    rows = _read(retrieval_dir, "SELECT c.row, s.defense FROM cases c LEFT JOIN sections s ON s.id = c.id ORDER BY c.row")
    assert [r[0] for r in rows] == list(range(len(rows))), "cases 表的 row 不連續"
    out = [clean_defense(d) for _, d in rows]
    return [d if len(d) >= MIN_DEFENSE else "" for d in out]


def source_meta(retrieval_dir: Path) -> Dict:
    meta = json.loads((retrieval_dir / "meta.json").read_text(encoding="utf-8"))
    return {"retrieval": meta.get("name"), "retrieval_built_at": meta.get("built_at"), "n_cases": meta.get("n_cases")}


def build(retrieval_dir: Path, out: Path) -> Path:
    defenses = load_defenses(retrieval_dir)
    n_with = sum(bool(d) for d in defenses)
    print(f"{len(defenses):,} 件，有答辯（{MIN_DEFENSE} 字以上）{n_with:,} 件", flush=True)
    params = {} if len(defenses) >= 50 else {"min_df": 1, "max_features": None}
    index = TfidfIndex(**params).fit(defenses, sample=VOCAB_SAMPLE)
    out.mkdir(parents=True, exist_ok=True)
    index.save(out / "index.joblib")
    meta = {"name": NAME, "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), **config.build_info(),
            **source_meta(retrieval_dir), "n_with_defense": n_with, "min_defense": MIN_DEFENSE,
            "index": "被告答辯（拿掉遮名標記），字元 1–3 gram TF-IDF；列順序和主張索引相同"}
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def matches(meta: Dict, retrieval_dir: Path, n_rows: int) -> bool:
    """答辯索引是不是用這份檢索資料建的：列數和建置時間都要對得上，否則列順序可能不同。"""
    src = source_meta(retrieval_dir)
    return meta.get("retrieval_built_at") == src["retrieval_built_at"] and meta.get("n_cases") == n_rows


# ── 評估 ──

def evaluate(retrieval_dir: Path, defense_dir: Path, n_queries: int = N_QUERIES) -> Dict:
    """
    抽對審、有答辯的判決當查詢（排除本身與近似重複），在同案由的對審判決裡找前 K 件，
    用鄰居的原告勝訴比例預測查詢的實際結果，比較 AUC、Brier。
    只是代理指標：查詢是判決書的文字，使用者寫的口語答辯效果會比較差。
    """
    claim = TfidfIndex.load(retrieval_dir / "index.joblib")
    defense = TfidfIndex.load(defense_dir / "index.joblib")
    assert len(claim) == len(defense), "兩個索引的列數不同"
    rows = _read(retrieval_dir, "SELECT mid, y, in_stats FROM cases ORDER BY row")
    mids = np.array([r[0] or "" for r in rows])
    y = np.array([r[1] for r in rows])
    stats = np.array([bool(r[2]) for r in rows])
    has_defense = np.asarray(defense.matrix.getnnz(axis=1) > 0)
    pool = np.flatnonzero(stats & has_defense)
    queries = np.random.default_rng(SEED).choice(pool, min(n_queries, len(pool)), replace=False)
    mid_counts = {m: int(((mids == m) & stats).sum()) for m in set(mids[queries])}

    preds = {w: np.zeros(len(queries)) for w in WEIGHTS}
    chunk = 200
    for j in range(0, len(queries), chunk):
        qq = queries[j:j + chunk]
        sc = (claim.matrix[qq] @ claim.matrix.T).toarray()
        sd = (defense.matrix[qq] @ defense.matrix.T).toarray()
        for i, q in enumerate(qq):
            allowed = stats.copy()
            if mid_counts[mids[q]] >= MIN_SAME_MID:
                allowed &= mids == mids[q]
            allowed[q] = False
            allowed &= sc[i] < NEAR_DUPLICATE
            for w in WEIGHTS:
                sim = np.where(allowed, (1 - w) * sc[i] + w * sd[i], -1.0)
                top = np.argpartition(-sim, K - 1)[:K]
                preds[w][j + i] = y[top].mean()
        print(f"  {min(j + chunk, len(queries)):,} / {len(queries):,}", flush=True)
    truth = y[queries]
    return {"n_queries": int(len(queries)), "base_rate": float(truth.mean()),
            "results": {str(w): {"auc": float(roc_auc_score(truth, p)), "brier": float(np.mean((p - truth) ** 2))}
                        for w, p in preds.items()}}


def report(r: Dict) -> str:
    lines = ["# 被告端相似判決：只用主張 vs 主張＋答辯\n",
             f"查詢：{r['n_queries']:,} 件對審、有答辯的判決（原告勝訴比例 {r['base_rate']:.3f}），"
             f"在同案由的對審判決裡找前 {K} 件（排除本身、主張相似度 ≥ {NEAR_DUPLICATE} 的近似重複）。",
             "用前 30 件的原告勝訴比例預測查詢的實際結果。w 是答辯的權重：w = 0 就是現在只用主張。\n",
             "| 答辯權重 w | AUC | Brier |", "|---:|---:|---:|"]
    for w, m in r["results"].items():
        lines.append(f"| {w} | {m['auc']:.3f} | {m['brier']:.4f} |")
    lines.append("\n查詢是判決書的文字；使用者自己寫的答辯是口語，實際效果會比這裡差。")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description="民事被告端的答辯索引")
    ap.add_argument("action", choices=("build", "evaluate"))
    ap.add_argument("--retrieval", default=None, help="主張的檢索資料；預設 artifacts/retrieval_civil_v6")
    ap.add_argument("--out", default=None, help="答辯索引的資料夾；預設 artifacts/retrieval_civil_defense_v1")
    ap.add_argument("--queries", type=int, default=N_QUERIES)
    a = ap.parse_args()
    t0 = time.time()
    retrieval_dir = Path(a.retrieval) if a.retrieval else retrieval_build.artifact_dir()
    out = Path(a.out) if a.out else artifact_dir()
    if a.action == "build":
        print(f"已存到 {build(retrieval_dir, out)}")
    else:
        r = evaluate(retrieval_dir, out, a.queries)
        text = report(r)
        (config.OUTPUT_DIR / "defense_retrieval_eval.md").write_text(text, encoding="utf-8")
        (config.OUTPUT_DIR / "defense_retrieval_eval.json").write_text(json.dumps(r, ensure_ascii=False, indent=2),
                                                                        encoding="utf-8")
        print(text)
    print(f"完成，{(time.time() - t0) / 60:.1f} 分鐘")


if __name__ == "__main__":
    main()
