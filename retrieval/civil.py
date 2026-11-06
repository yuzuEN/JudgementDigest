"""
民事的相似判決檢索設定：用原告主張建索引（使用者在平台上只能提供自己這一方的說法），
可以限定在同一案由中類裡找，結果附上勝敗與金額。

評估用的語料（load_corpus）：文字資料集（預設 v5）中原告主張不是空白的案件，再從分析用資料庫補上金額欄位。

上線用的語料（load_expanded）：訓練模型要嚴格篩選（要有被告答辯、不能洩漏答案），檢索是找真實案例給人看，
不需要那些條件，所以從正式資料庫取全部第一審的給付、確認案件（含簡易庭、一造辯論）。
一造辯論的被告沒有出庭，原告幾乎都贏，也沒有答辯，所以分兩層：
  in_stats = 1          對審且有被告答辯：金額範圍、證據對照、常見抗辯只用這些案件
  default_judgment = 1  一造辯論：可以出現在相似判決列表，標示「被告未到庭」
"""
import re
import sqlite3
from typing import Dict, Optional, Tuple

import pandas as pd

import config
from civil.dataset.text import ABSENT_RE, DEFAULT_RE, n_case_numbers, normalize_text, strip_prayer_v5

CORPUS_COLUMNS = ["id", "case_number", "court", "year", "case_type_category", "case_type_mid",
                  "outcome", "y", "plaintiff_claim_text"]
AMOUNT_COLUMNS = ["grant_ratio", "claimed_amount", "awarded_amount"]
PARTIAL = "一部勝訴一部敗訴"
OUTCOMES = ("勝訴", PARTIAL, "敗訴", "確認勝訴")
EXCLUDED_CATEGORIES = ("身分／家事", "非訟／除權")
MIN_CLAIM, MIN_DEFENSE = 50, 30


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


def expanded_row(row: Dict, derived: Dict) -> Optional[Tuple[Dict, Dict]]:
    """
    一件判決（資料庫原始欄位、規則推導的欄位）→（案件, 導讀用的段落）；不適合放進檢索就回傳 None。
    排除：結果不是勝敗類、家事與非訟、簡上附民移簡（刑事第二審移送）、一份判決合併多案、段落切分失敗。
    """
    kind = derived["case_kind"] or ""
    full_text = row.get("full_text") or ""
    if (derived["outcome"] not in OUTCOMES or derived["case_kind_category"] != "給付確認"
            or derived["case_type_category"] in EXCLUDED_CATEGORIES or "上" in kind
            or derived["section_split_status"] != "成功" or n_case_numbers(full_text[:400]) >= 2):
        return None
    claim_raw = derived["plaintiff_claim_text"] or ""
    defense_raw = derived["defendant_defense_text"] or ""
    claim = normalize_text(strip_prayer_v5(claim_raw))
    if len(claim) < MIN_CLAIM:
        return None
    defense = strip_prayer_v5(defense_raw)
    absent = bool(ABSENT_RE.search(defense)) and len(defense) <= 150
    default = bool(derived["is_default_judgment"]) or bool(DEFAULT_RE.search(re.sub(r"\s+", "", full_text)))
    case = {"id": row["id"], "case_number": row["case_number"], "court": row["court"],
            "year": (row.get("judgment_date") or "")[:4], "case_type_category": derived["case_type_category"],
            "case_type_mid": derived["case_type_mid"], "outcome": derived["outcome"],
            "y": int(derived["outcome"] != "敗訴"), "plaintiff_claim_text": claim,
            "claimed_amount": derived["claimed_amount"], "awarded_amount": derived["awarded_amount"],
            "grant_ratio": derived["grant_ratio"], "default_judgment": int(default),
            "in_stats": int(not default and len(defense) >= MIN_DEFENSE and not absent)}
    section = {"id": row["id"], "plaintiff_claim_text": claim_raw, "defendant_defense_text": defense_raw,
               "court_reasoning_text": derived["court_reasoning_text"] or "", "plaintiff": row.get("plaintiff") or "",
               "defendant": row.get("defendant") or "", "plaintiff_agent": row.get("plaintiff_agent") or "",
               "defendant_agent": row.get("defendant_agent") or ""}
    return case, section


def load_expanded(db=None, chunk: int = 5000) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """從正式資料庫取第一審的給付、確認案件，用目前的規則在記憶體裡重新推導段落（資料庫不寫入）。"""
    config.use_data_pipeline()
    import structuring as S
    con = sqlite3.connect(f"file:{db or config.MAIN_DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        ids = [r[0] for r in con.execute("SELECT id FROM judgments WHERE party_posture = '第一審對審' "
                                         "AND case_kind_category = '給付確認' ORDER BY id")]
        cols = ", ".join(["id"] + S.SOURCE_COLUMNS)
        cases, sections = [], []
        for start in range(0, len(ids), chunk):
            part = ids[start:start + chunk]
            marks = ",".join("?" * len(part))
            for r in con.execute(f"SELECT {cols} FROM judgments WHERE id IN ({marks})", part):
                row = dict(r)
                kept = expanded_row(row, S.derive_structured_fields(row))
                if kept:
                    cases.append(kept[0])
                    sections.append(kept[1])
            print(f"  {min(start + chunk, len(ids)):,} / {len(ids):,}，保留 {len(cases):,}", flush=True)
    finally:
        con.close()
    return pd.DataFrame(cases), pd.DataFrame(sections)
