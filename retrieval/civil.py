"""
民事的相似判決檢索設定：用原告主張建索引（使用者在平台上只能提供自己這一方的說法），
可以限定在同一案由中類裡找，結果附上勝敗與金額。

語料：文字資料集（預設 v5）中原告主張不是空白的案件，再從分析用資料庫補上金額欄位。
"""
import sqlite3

import pandas as pd

import config

CORPUS_COLUMNS = ["id", "case_number", "court", "year", "case_type_category", "case_type_mid",
                  "outcome", "y", "plaintiff_claim_text"]
AMOUNT_COLUMNS = ["grant_ratio", "claimed_amount", "awarded_amount"]
PARTIAL = "一部勝訴一部敗訴"


def fetch_columns(ids, columns, db=None) -> pd.DataFrame:
    """從分析用資料庫（唯讀）取出這些案件的欄位。"""
    con = sqlite3.connect(f"file:{db or config.WORK_DB}?mode=ro", uri=True)
    try:
        con.execute("CREATE TEMP TABLE ids(id INTEGER PRIMARY KEY)")
        con.executemany("INSERT INTO ids VALUES (?)", [(int(i),) for i in ids])
        cols = ", ".join(f"j.{c}" for c in columns)
        return pd.read_sql(f"SELECT j.id, {cols} FROM judgments j JOIN ids USING (id)", con)
    finally:
        con.close()


def load_corpus(version: str = "v5", amounts: bool = True) -> pd.DataFrame:
    v = pd.read_csv(config.dataset_path(version), usecols=CORPUS_COLUMNS)
    v = v[v.plaintiff_claim_text.fillna("").str.len() > 0].reset_index(drop=True)
    if amounts:
        v = v.merge(fetch_columns(v.id, AMOUNT_COLUMNS), on="id", how="left", validate="1:1")
    return v


def partial_with_ratio(corpus: pd.DataFrame) -> pd.Series:
    """一部勝訴、而且有合理獲償比例（0–1]的案件：金額範圍只用這些案件算。"""
    return (corpus.outcome == PARTIAL) & corpus.grant_ratio.between(0, 1, inclusive="right")
