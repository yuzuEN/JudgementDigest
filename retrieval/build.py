"""
建立上線用的民事檢索資料：索引、案件清單（已遮名）、每件判決提到的證據與被告抗辯類型。

    python -m retrieval.build                  # 輸出到 artifacts/retrieval_civil_v1/

輸出：
  index.joblib   原告主張的 TF-IDF 索引（列的順序＝cases 表的 row）
  cases.sqlite   cases：字號、法院、年份、案由、結果、金額、證據與抗辯類型、摘要
                 sections：判決導讀用的三段文字（原告主張、被告答辯、法院判斷），當事人姓名已換成角色
  meta.json      建立時間、件數、資料版本
索引用的原告主張取自文字資料集（和模型相同的清理）；導讀的三段取自分析用資料庫（規則 2.4.0 的段落切分）。
"""
import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

import config
from civil.insights import defense_types, evidence_mentions
from retrieval.civil import fetch_columns, load_corpus
from retrieval.engine import TfidfIndex
from retrieval.masking import mask_parties

NAME = "retrieval_civil_v1"
SECTION_COLUMNS = ["plaintiff_claim_text", "defendant_defense_text", "court_reasoning_text",
                   "plaintiff", "defendant", "plaintiff_agent", "defendant_agent"]
SUMMARY_LEN = 90


def artifact_dir(base: Optional[Path] = None) -> Path:
    return Path(base or config.ARTIFACTS_DIR) / NAME


def write_artifacts(corpus: pd.DataFrame, sections: pd.DataFrame, out: Path, version: str = "") -> Path:
    """
    corpus：load_corpus() 的欄位（id、字號、案由、結果、金額、原告主張）。
    sections：id ＋ SECTION_COLUMNS（分析用資料庫的段落與當事人欄位）。
    """
    corpus = corpus.reset_index(drop=True)
    s = corpus[["id"]].merge(sections, on="id", how="left", validate="1:1").fillna("")
    masked = {col: [mask_parties(t, p, d, (pa, da)) for t, p, d, pa, da in
                    zip(s[col], s.plaintiff, s.defendant, s.plaintiff_agent, s.defendant_agent)]
              for col in ("plaintiff_claim_text", "defendant_defense_text", "court_reasoning_text")}
    summary = [mask_parties(t, p, d, (pa, da))[:SUMMARY_LEN] for t, p, d, pa, da in
               zip(corpus.plaintiff_claim_text, s.plaintiff, s.defendant, s.plaintiff_agent, s.defendant_agent)]
    evidence = [json.dumps(evidence_mentions(c + "\n" + p)) for c, p in
                zip(s.court_reasoning_text, s.plaintiff_claim_text)]
    defenses = [json.dumps(defense_types(t)) for t in s.defendant_defense_text]

    out.mkdir(parents=True, exist_ok=True)
    # 語料很小時（測試用）min_df=10 會把所有字都濾掉
    params = {} if len(corpus) >= 50 else {"min_df": 1, "max_features": None}
    TfidfIndex(**params).fit(corpus.plaintiff_claim_text).save(out / "index.joblib")
    db = out / "cases.sqlite"
    if db.exists():
        db.unlink()
    con = sqlite3.connect(db)
    try:
        con.execute("""CREATE TABLE cases (row INTEGER PRIMARY KEY, id INTEGER UNIQUE, case_number TEXT,
                       court TEXT, year TEXT, category TEXT, mid TEXT, outcome TEXT, y INTEGER,
                       claimed_amount INTEGER, awarded_amount INTEGER, grant_ratio REAL,
                       evidence TEXT, defenses TEXT, summary TEXT)""")
        con.execute("CREATE TABLE sections (id INTEGER PRIMARY KEY, claim TEXT, defense TEXT, court TEXT)")

        def num(v):
            return None if pd.isna(v) else v

        con.executemany("INSERT INTO cases VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
            (i, int(r.id), r.case_number, r.court, str(r.year), r.case_type_category, r.case_type_mid, r.outcome,
             int(r.y), num(r.claimed_amount), num(r.awarded_amount), num(r.grant_ratio), evidence[i], defenses[i],
             summary[i]) for i, r in enumerate(corpus.itertuples())])
        con.executemany("INSERT INTO sections VALUES (?,?,?,?)", zip(
            corpus.id.astype(int), masked["plaintiff_claim_text"], masked["defendant_defense_text"],
            masked["court_reasoning_text"]))
        con.commit()
    finally:
        con.close()
    meta = {"name": NAME, "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "dataset": f"text_dataset_{version}.csv" if version else "", "n_cases": int(len(corpus)),
            "index": "原告主張，字元 1–3 gram TF-IDF", "sections": "分析用資料庫的段落切分（規則 2.4.0），當事人姓名已換成角色"}
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def build_civil(version: str = "v5", out: Optional[Path] = None) -> Path:
    corpus = load_corpus(version)
    sections = fetch_columns(corpus.id, SECTION_COLUMNS)
    return write_artifacts(corpus, sections, Path(out) if out else artifact_dir(), version)


def main():
    ap = argparse.ArgumentParser(description="建立上線用的民事檢索資料")
    ap.add_argument("--version", default="v5")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    print(f"已存到 {build_civil(a.version, a.out)}")


if __name__ == "__main__":
    main()
