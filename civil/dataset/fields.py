"""
樣本母體與結構化變數（v6 起從分析用資料庫直接算，取代 analysis_fields.pkl）。

    python -m civil.dataset.fields v6        # 產生 fields_v6.csv、fields_v6_meta.json（放在 DATASET_DIR）

母體的定義沿用產生 analysis_fields.pkl 的 factor_base.load()（repo 改結構前的本機程式），條件不變：
  - 地方法院的民事判決，裁判日期 2022–2025 年，案件類別是「給付確認」
  - 程序別（proc_type）：再審、聲請等非一般訴訟排除；簡易、小額排除；家事字別排除
  - 被告是否為法人不是空值（上訴審沒有「被告」）
  - 結果是勝訴、確認勝訴、一部勝訴一部敗訴、敗訴之一
用 judgments_work_20261112.db（規則 2.5.2）算出 102,329 件，pkl 的 102,328 件全部在內；
律師、一造辯論兩欄和 pkl 完全相同，被告是否為法人有 4,896 件不同（2.5.x 的規則改了這一欄）。

輸出不含當事人姓名：模型只用到下面的欄位。

load_fields(version)：v6 起讀 fields_{版本}.csv，更早的版本照舊讀 config.FIELDS_PKL，v5 的結果才能重現。
"""
import argparse
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Optional

import pandas as pd

import config

FROM_DB = ("v6",)
YEARS = ("2022", "2025")
OUTCOMES = ["勝訴", "確認勝訴", "一部勝訴一部敗訴", "敗訴"]
PROCS = ["一般", "重訴", "附民移送"]
FAMILY_RE = re.compile(r"家|^重?(?:婚|親|養|監|輔)")
FLAGS = ["is_default_judgment", "plaintiff_has_lawyer", "defendant_has_lawyer", "defendant_is_corp",
         "has_counterclaim"]
COLUMNS = ["id", "case_number", "court", "court_s", "judgment_date", "case_kind", "proc", "case_type_category",
           "case_type_mid", "claim_basis_group", "claim_basis_primary", "outcome", *FLAGS]


def proc_type(kind: Optional[str]) -> Optional[str]:
    """程序別：再審、聲請等非一般訴訟回傳 None；簡易小額另成一類（之後排除）。更一、更二不影響程序別。"""
    k = re.sub(r"更[一二三]$", "", kind or "")
    if not k or re.search(r"[再聲補救全撤選破法續調]", k):
        return None
    if "附民" in k:
        return "附民移送"
    if k.endswith("簡") or k.endswith("小"):
        return "簡易小額"
    if "重" in k:
        return "重訴"
    return "一般"


def population(db: Path) -> pd.DataFrame:
    """分析用資料庫 → 樣本母體（含一造辯論；建文字資料集時再排除）。資料庫以唯讀開啟。"""
    with closing(sqlite3.connect(f"file:{db}?mode=ro", uri=True)) as con:
        versions = [r[0] for r in con.execute("SELECT DISTINCT structuring_version FROM judgments")]
        df = pd.read_sql(f"""
            SELECT id, case_number, court, judgment_date, case_kind, case_type_category, case_type_mid,
                   claim_basis_group, claim_basis_primary, outcome, {", ".join(FLAGS)}
            FROM judgments
            WHERE case_number LIKE '%民事判決' AND court LIKE '%地方法院'
              AND substr(judgment_date, 1, 4) BETWEEN ? AND ?
              AND case_kind_category = '給付確認'""", con, params=YEARS)
    df["proc"] = df.case_kind.map(proc_type)
    family = df.case_kind.fillna("").str.contains(FAMILY_RE)
    df = df[df.proc.isin(PROCS) & df.defendant_is_corp.notna() & df.outcome.isin(OUTCOMES) & ~family].copy()
    df["court_s"] = df.court.str.replace("臺灣|福建|地方法院", "", regex=True)
    for c in FLAGS:
        df[c] = df[c].astype(int)
    df.attrs["structuring_versions"] = sorted(v for v in versions if v)
    return df[COLUMNS].sort_values("id").reset_index(drop=True)


def fields_path(version: str) -> Path:
    return config.DATASET_DIR / f"fields_{version}.csv"


def load_fields(version: str) -> pd.DataFrame:
    """建資料集與訓練模型用的母體與結構化變數。v6 起讀 fields_{版本}.csv，更早的版本讀 analysis_fields.pkl。"""
    if version in FROM_DB:
        return pd.read_csv(fields_path(version), encoding="utf-8")
    return pd.read_pickle(config.FIELDS_PKL)


def build(version: str, db: Optional[Path] = None) -> pd.DataFrame:
    assert version in FROM_DB, f"只有 {', '.join(FROM_DB)} 從資料庫算；更早的版本用 analysis_fields.pkl"
    config.use_data_pipeline()
    from structuring import STRUCTURING_VERSION
    db = Path(db or config.WORK_DB)
    df = population(db)
    versions = df.attrs["structuring_versions"]
    assert versions == [STRUCTURING_VERSION], \
        f"資料庫的規則版本是 {versions}，目前的 structuring.py 是 {STRUCTURING_VERSION}，請先全量回填"
    out = fields_path(version)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False, encoding="utf-8")
    meta = {"version": version, **config.build_info(), "rule_version": STRUCTURING_VERSION, "source_db": db.name,
            "years": list(YEARS), "n_cases": int(len(df)), "n_contested": int((df.is_default_judgment == 0).sum()),
            "outcomes": {k: int(v) for k, v in df.outcome.value_counts().items()},
            "defendant_is_corp": int(df.defendant_is_corp.sum())}
    (out.parent / f"fields_{version}_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
                                                            encoding="utf-8")
    print(f"{len(df):,} 件（其中對審 {meta['n_contested']:,} 件），規則 {STRUCTURING_VERSION}，來源 {db.name}")
    print(f"已輸出 {out}")
    return df


def main():
    ap = argparse.ArgumentParser(description="從分析用資料庫算樣本母體與結構化變數")
    ap.add_argument("version", choices=FROM_DB)
    ap.add_argument("--db", default=None, help="分析用資料庫；預設 config.WORK_DB")
    a = ap.parse_args()
    build(a.version, a.db)


if __name__ == "__main__":
    main()
