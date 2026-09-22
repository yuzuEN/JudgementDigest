"""
法官分析 — 資料載入層

把 `judgments` 資料表攤平成三張分析用的 tidy 表：

  cases      一列一個案件（分析單位＝案件）
  judge_case 一列一個「法官×案件」（合議庭案件會展開成 3 列）
  citations  一列一個「案件×法條」

為什麼要拆成三張表
──────────────────
`judges` 與 `applicable_laws_json` 都是「一格多值」的欄位。直接在原表上做
group by，合議庭的三位法官會被當成一個字串類別、法條清單也無法統計。
先攤平成長表，之後所有分析都只是單純的 group by，不必再處理字串切割，
也不會因為每個分析腳本各自切一次而產生不一致。

這一層只做「讀取與攤平」，不做任何判斷或推導——所有規則都在
專案根目錄的 `structuring.py`，確保分析結果可以回溯到單一份規則。
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from typing import Optional

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

DB_PATH = str(ROOT / "judgments.db")

# 讀入分析所需欄位。刻意不讀 full_text / reasons 等大欄位，
# 一萬多筆全文約數百 MB，載進記憶體對分析毫無幫助。
CASE_COLUMNS = [
    "id", "case_number", "court", "judgment_date", "case_type", "judgment_type",
    "case_kind", "case_kind_category", "case_type_norm", "case_type_category",
    "outcome", "main_outcome", "counter_outcome", "has_counterclaim", "appeal_outcome",
    "relief_type", "awarded_amount", "awarded_currency", "claimed_amount",
    "claimed_currency", "claimed_source", "grant_ratio", "cost_share_plaintiff",
    "law_primary", "law_n_citations", "applicable_laws_json",
    "judges", "judges_json", "judge_count", "presiding_judge", "panel_key",
    "defendant_is_corp", "plaintiff_has_lawyer", "defendant_has_lawyer",
    "is_default_judgment", "has_provisional_exec", "reasoning_length",
    "quality_flags", "structuring_version",
]


def load_cases(
    db_path: str = DB_PATH,
    court: Optional[str] = "臺北地方法院",
    year: Optional[str] = "2025",
    civil_only: bool = True,
    judgments_only: bool = True,
) -> pd.DataFrame:
    """
    載入案件表。

    預設限定臺北地院 2025 年民事判決——這是目前唯一完整回填過的範圍。
    分析其他範圍前請先跑 `python backfill_structured.py`，
    否則結構化欄位會是空的，所有統計都會是假的。
    """
    where, params = ["1=1"], []
    if court:
        where.append("court LIKE ?")
        params.append(f"%{court}%")
    if year:
        where.append("judgment_date LIKE ?")
        params.append(f"{year}%")
    if civil_only:
        where.append("case_number LIKE ?")
        params.append("%民事%")
    if judgments_only:
        # 裁定的主文不是「誰贏誰輸」，混進來會稀釋所有結果統計
        where.append("judgment_type = ?")
        params.append("判決")

    conn = sqlite3.connect(db_path)
    try:
        df = pd.read_sql_query(
            f"SELECT {','.join(CASE_COLUMNS)} FROM judgments WHERE {' AND '.join(where)}",
            conn, params=params)
    except (pd.errors.DatabaseError, sqlite3.OperationalError) as e:
        # 從未跑過結構化的舊資料庫連欄位都沒有，SELECT 會直接失敗，
        # 下面「結構化欄位全為空」的友善提示根本摸不到。
        if "no such column" in str(e) or "no such table" in str(e):
            raise SystemExit(
                "資料庫缺少結構化欄位（這是尚未升級的舊資料庫）。請先執行：\n"
                "  python backfill_structured.py\n"
                f"（原始錯誤：{e}）") from None
        raise
    finally:
        conn.close()

    if df.empty:
        raise SystemExit("查無資料。請確認 judgments.db 存在且已執行 backfill_structured.py。")
    if df["structuring_version"].isna().all():
        raise SystemExit(
            "結構化欄位全為空。請先執行：python backfill_structured.py")

    df["judgment_date"] = pd.to_datetime(df["judgment_date"], errors="coerce")
    df["month"] = df["judgment_date"].dt.to_period("M").astype(str)
    for c in ("awarded_amount", "claimed_amount", "grant_ratio",
              "cost_share_plaintiff", "reasoning_length"):
        df[c] = pd.to_numeric(df[c], errors="coerce")

    # 分析用的二元依變數。只在「給付確認」層級有意義，其餘設為 NaN，
    # 避免把除權判決（幾乎 100% 准）算進法官的勝訴率而拉高分母。
    adversarial = df["case_kind_category"] == "給付確認"
    df["is_adversarial"] = adversarial
    df["plaintiff_won"] = pd.NA
    df.loc[adversarial & df["outcome"].isin(["勝訴", "確認勝訴"]), "plaintiff_won"] = 1
    df.loc[adversarial & df["outcome"].isin(["敗訴"]), "plaintiff_won"] = 0
    df.loc[adversarial & (df["outcome"] == "一部勝訴一部敗訴"), "plaintiff_won"] = 0.5
    df["plaintiff_won"] = pd.to_numeric(df["plaintiff_won"], errors="coerce")

    return df


def explode_judges(cases: pd.DataFrame) -> pd.DataFrame:
    """
    攤平成「法官 × 案件」長表。

    合議庭案件會展開成 3 列。這代表同一個案件會被計入 3 位法官——
    這在「某法官參與過哪些案件」的問題下是正確的，但要注意它不是
    「該法官獨自決定的案件」。因此表中保留 `role`，需要時可以只取
    獨任案件（role=='獨任'）來做最乾淨的個人傾向比較。
    """
    rows = []
    for rec in cases.to_dict("records"):
        raw = rec.get("judges_json") or ""
        try:
            judges = json.loads(raw) if raw else []
        except (ValueError, TypeError):
            judges = []
        for j in judges:
            rows.append({
                "judge": j.get("name", ""),
                "role": j.get("role", ""),
                "seat": j.get("seat"),
                **{k: rec[k] for k in cases.columns if k not in ("judges_json",)},
            })
    out = pd.DataFrame(rows)
    return out[out["judge"].astype(bool)] if not out.empty else out


def explode_citations(cases: pd.DataFrame) -> pd.DataFrame:
    """攤平成「案件 × 法條」長表。"""
    rows = []
    for rec in cases.to_dict("records"):
        raw = rec.get("applicable_laws_json") or ""
        try:
            cites = json.loads(raw) if raw else []
        except (ValueError, TypeError):
            cites = []
        for c in cites:
            rows.append({
                "case_id": rec["id"],
                "case_number": rec["case_number"],
                "case_type_category": rec["case_type_category"],
                "outcome": rec["outcome"],
                "presiding_judge": rec["presiding_judge"],
                "law": c.get("law", ""),
                "article": c.get("article"),
                "paragraph": c.get("paragraph"),
                "item": c.get("item"),
                "position": c.get("position", ""),
                "key": c.get("key", ""),
            })
    return pd.DataFrame(rows)
