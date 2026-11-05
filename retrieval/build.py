"""
建立上線用的民事檢索資料：索引、案件清單（已遮名）、每件判決提到的證據與被告抗辯類型。

    python -m retrieval.build                  # 輸出到 artifacts/retrieval_civil_v2/

輸出：
  index.joblib   原告主張的 TF-IDF 索引（列的順序＝cases 表的 row）
  cases.sqlite   cases：字號、法院、年份、案由、結果、金額、證據與抗辯類型、摘要
                 sections：判決導讀用的三段文字（原告主張、被告答辯、法院判斷），當事人姓名已換成角色
  meta.json      建立時間、件數、資料版本
語料見 retrieval/civil.py 的 load_expanded：正式資料庫裡第一審的給付、確認案件，段落用目前的規則重新推導。
"""
import argparse
import json
import sqlite3
import subprocess
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

import config
from civil.insights import defense_types, evidence_mentions
from retrieval.civil import load_expanded
from retrieval.engine import TfidfIndex
from retrieval.masking import mask_parties, third_party_names

NAME = "retrieval_civil_v2"
VOCAB_SAMPLE = 60_000     # 字典與 IDF 只用這麼多筆建（完整語料的字元 n-gram 字典太吃記憶體）
SUMMARY_LEN = 90


def artifact_dir(base: Optional[Path] = None) -> Path:
    return Path(base or config.ARTIFACTS_DIR) / NAME


def provenance(db: Path) -> dict:
    """這份資料是哪個程式版本、哪個規則、哪份資料庫建出來的（資料不進 Git，要靠這些對回去）。"""
    config.use_data_pipeline()
    from structuring import STRUCTURING_VERSION
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=config.ROOT, capture_output=True, text=True)
    with closing(sqlite3.connect(f"file:{db}?mode=ro", uri=True)) as con:
        rows = con.execute("SELECT COUNT(*) FROM judgments").fetchone()[0]
    modified = datetime.fromtimestamp(Path(db).stat().st_mtime, timezone.utc).isoformat(timespec="seconds")
    return {"git_commit": commit.stdout.strip(), "rule_version": STRUCTURING_VERSION,
            "source_rows": rows, "source_modified": modified}


def write_artifacts(corpus: pd.DataFrame, sections: pd.DataFrame, out: Path, version: str = "",
                    extra: Optional[dict] = None) -> Path:
    """
    corpus：id、字號、案由、結果、金額、原告主張，以及 default_judgment、in_stats（沒有時視為對審、納入統計）。
    sections：id ＋ 三段文字與當事人欄位（見 retrieval.civil.expanded_row）。
    """
    corpus = corpus.reset_index(drop=True)
    if "default_judgment" not in corpus:
        corpus = corpus.assign(default_judgment=0, in_stats=1)
    s = corpus[["id"]].merge(sections, on="id", how="left", validate="1:1").fillna("")
    # 第三人的名字用整件判決找：同一個人在別的段落可能沒有寫「訴外人」
    others = [third_party_names("\n".join(parts)) for parts in
              zip(corpus.plaintiff_claim_text, s.plaintiff_claim_text, s.defendant_defense_text, s.court_reasoning_text)]
    masked = {col: [mask_parties(t, p, d, (pa, da), o) for t, p, d, pa, da, o in
                    zip(s[col], s.plaintiff, s.defendant, s.plaintiff_agent, s.defendant_agent, others)]
              for col in ("plaintiff_claim_text", "defendant_defense_text", "court_reasoning_text")}
    summary = [mask_parties(t, p, d, (pa, da), o)[:SUMMARY_LEN] for t, p, d, pa, da, o in
               zip(corpus.plaintiff_claim_text, s.plaintiff, s.defendant, s.plaintiff_agent, s.defendant_agent, others)]
    evidence = [json.dumps(evidence_mentions(c + "\n" + p)) for c, p in
                zip(s.court_reasoning_text, s.plaintiff_claim_text)]
    defenses = [json.dumps(defense_types(t)) for t in s.defendant_defense_text]

    out.mkdir(parents=True, exist_ok=True)
    # 語料很小時（測試用）min_df=10 會把所有字都濾掉
    params = {} if len(corpus) >= 50 else {"min_df": 1, "max_features": None}
    TfidfIndex(**params).fit(corpus.plaintiff_claim_text, sample=VOCAB_SAMPLE).save(out / "index.joblib")
    db = out / "cases.sqlite"
    if db.exists():
        db.unlink()
    con = sqlite3.connect(db)
    try:
        con.execute("""CREATE TABLE cases (row INTEGER PRIMARY KEY, id INTEGER UNIQUE, case_number TEXT,
                       court TEXT, year TEXT, category TEXT, mid TEXT, outcome TEXT, y INTEGER,
                       claimed_amount INTEGER, awarded_amount INTEGER, grant_ratio REAL,
                       evidence TEXT, defenses TEXT, summary TEXT, default_judgment INTEGER, in_stats INTEGER)""")
        con.execute("CREATE TABLE sections (id INTEGER PRIMARY KEY, claim TEXT, defense TEXT, court TEXT)")

        def num(v):
            return None if pd.isna(v) else v

        con.executemany("INSERT INTO cases VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
            (i, int(r.id), r.case_number, r.court, str(r.year), r.case_type_category, r.case_type_mid, r.outcome,
             int(r.y), num(r.claimed_amount), num(r.awarded_amount), num(r.grant_ratio), evidence[i], defenses[i],
             summary[i], int(r.default_judgment), int(r.in_stats)) for i, r in enumerate(corpus.itertuples())])
        con.executemany("INSERT INTO sections VALUES (?,?,?,?)", zip(
            corpus.id.astype(int), masked["plaintiff_claim_text"], masked["defendant_defense_text"],
            masked["court_reasoning_text"]))
        con.commit()
    finally:
        con.close()
    meta = {"name": NAME, "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source": version, "n_cases": int(len(corpus)), "n_stats": int(corpus.in_stats.sum()),
            "n_default": int(corpus.default_judgment.sum()),
            "index": "原告主張，字元 1–3 gram TF-IDF", "sections": "當事人姓名已換成角色", **(extra or {})}
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def build_civil(out: Optional[Path] = None) -> Path:
    corpus, sections = load_expanded()
    print(f"語料 {len(corpus):,} 件，納入統計 {int(corpus.in_stats.sum()):,}，一造辯論 {int(corpus.default_judgment.sum()):,}", flush=True)
    return write_artifacts(corpus, sections, Path(out) if out else artifact_dir(), config.MAIN_DB.name,
                           provenance(config.MAIN_DB))


def main():
    ap = argparse.ArgumentParser(description="建立上線用的民事檢索資料")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    print(f"已存到 {build_civil(a.out)}")


if __name__ == "__main__":
    main()
