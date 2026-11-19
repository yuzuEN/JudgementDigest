"""
判決導讀「法院怎麼認定」（D3）用的標註：指定幾件判決，把整篇法院判斷段標註完，匯出給後端。

和 sample.py 的差別：sample.py 每件判決只抽一個論點單位，用來驗證手冊；
這裡是 demo 會點進去的判決，每件的所有論點單位都要標，導讀頁才完整。

步驟（資料都在 JD_ARTIFACTS_DIR/annotation_guide_v1/，不進 git）：
    1. python -m annotation.guide_batch build --case-ids 101,205,318      # 或 --ids-file ids.txt（一行一個 id）
    2. python -m annotation.annotate --db C:/jd_artifacts/annotation_guide_v1/annotation.sqlite --run-no 1
       （要多數決就再跑 --run-no 2、3）
    3. python -m annotation.guide_batch export                              # → guide.sqlite，後端讀這個
之後要加判決：再跑一次 build（已有的判決和標註會保留），再跑 annotate（只會標新的單位）和 export。

判決文字讀 retrieval_civil_v4（和後端導讀頁同一份），引文位置才對得上畫面上的文字。

export 的規則：
  - 每個單位取多數決的標籤（只跑一輪時就是那一輪的標籤），NONE 不匯出
  - 該標籤取最早一輪的全部引文（同一標籤可以有多段），只取通過引文驗證的
  - 引文的位置換算成在整篇法院判斷段的位置（unit_start + 引文在單位內的位置）
  - EV 只留引文通過規則十的（引文含評價用語，cues.quote_anchored）。v0.6 抽查：EV 整體 21/25，
    錯誤都是「有⋯⋯可參」這類只列舉證據的句子（規則十一A），引文都沒有評價用語；
    只看通過規則十的是 19/20。其他標籤不篩：SUB 沒通過自動檢查的 6 筆裡 5 筆是對的（用語清單涵蓋不完）
"""

import argparse
import json
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # repo 根目錄

import config  # noqa: E402
from annotation.cues import quote_anchored  # noqa: E402
from annotation.prompts_v6 import MANUAL_VERSION, PROMPT_VERSION  # noqa: E402
from annotation.quotes import resolve_quote  # noqa: E402
from annotation.sample import SCHEMA, split_case  # noqa: E402
from annotation.spot_check import load_runs, majority  # noqa: E402

GUIDE_DIR = "annotation_guide_v1"
GUIDE_DB = "guide.sqlite"          # 後端讀的檔名（backend/reasoning.py）
ANCHOR_REQUIRED = ("EV",)          # 匯出時引文必須通過規則十的標籤

GUIDE_SCHEMA = """
CREATE TABLE reasoning (
    case_id   INTEGER,
    unit_idx  INTEGER,   -- 第幾個論點單位
    label     TEXT,
    polarity  TEXT,      -- EV 傾向、DAM 方向、CONCL 方向；其他 NULL
    basis     TEXT,      -- EV 的 basis（明示評價／依證據推論）
    quote     TEXT,      -- 模型寫的引文（可能含〔略〕）
    span_start INTEGER,  -- 完整範圍在法院判斷段（sections.court）的起訖位置
    span_end   INTEGER
);
CREATE INDEX reasoning_case ON reasoning (case_id);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
"""


def parse_ids(text: str) -> list:
    """「101,205 318」或一行一個 → [101, 205, 318]（去重、保留順序）。"""
    out = []
    for tok in text.replace(",", " ").replace("，", " ").split():
        if tok.isdigit() and int(tok) not in out:
            out.append(int(tok))
    return out


def build(cases_db: Path, out_db: Path, case_ids: list) -> dict:
    """把指定判決的所有論點單位寫進 out_db 的 paragraphs 表。已在裡面的判決跳過，標註保留。"""
    with closing(sqlite3.connect(cases_db)) as src:
        q = ",".join("?" * len(case_ids))
        found = src.execute(f"SELECT s.id, c.category, s.court, c.outcome, c.grant_ratio FROM sections s "
                            f"LEFT JOIN cases c ON c.id = s.id WHERE s.id IN ({q})", case_ids).fetchall()
    by_id = {r[0]: r for r in found}
    missing = [i for i in case_ids if i not in by_id or not (by_id[i][2] or "").strip()]

    out_db.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(out_db)) as out:
        out.executescript(SCHEMA)
        have = {r[0] for r in out.execute("SELECT DISTINCT case_id FROM paragraphs")}
        next_id = (out.execute("SELECT MAX(sample_id) FROM paragraphs").fetchone()[0] or 0) + 1
        rows, added = [], []
        for cid in case_ids:
            if cid in have or cid in missing:
                continue
            _, category, court, outcome, ratio = by_id[cid]
            for u in split_case(cid, category, court, outcome, ratio):
                rows.append((next_id, cid, u["para_idx"], u["n_paras"], u["position"], "guide", u["category"],
                             u["prev_text"], u["para_text"], u["next_text"], u["unit_start"], u["unit_end"],
                             u["split_how"], u["outcome"], u["grant_ratio"]))
                next_id += 1
            added.append(cid)
        out.executemany(
            "INSERT INTO paragraphs (sample_id, case_id, para_idx, n_paras, position, batch, category, prev_text, "
            "para_text, next_text, unit_start, unit_end, split_how, outcome, grant_ratio) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        out.commit()
    return {"added": added, "units": len(rows), "skipped": sorted(have & set(case_ids)), "missing": missing}


def export(db: Path, out: Path, prompt_version: str = PROMPT_VERSION) -> dict:
    """標註結果 → guide.sqlite（後端讀）。回傳 {判決數, 項目數, 各標籤數}。"""
    with closing(sqlite3.connect(db)) as con:
        units = {r[0]: r[1:] for r in con.execute(
            "SELECT sample_id, case_id, para_idx, unit_start, para_text FROM paragraphs")}
        runs = load_runs(con, prompt_version)
        quotes = {}   # (sample_id, run_no, label) -> [(polarity, subtype, quote), ...]
        for sid, run, label, pol, sub, quote in con.execute(
                "SELECT sample_id, run_no, label, polarity, subtype, quote FROM annotations "
                "WHERE prompt_version = ? AND quote_valid = 1 ORDER BY id", (prompt_version,)):
            quotes.setdefault((sid, run, label), []).append((pol, sub, quote))
        n_runs = con.execute("SELECT COUNT(DISTINCT run_no) FROM annotations WHERE prompt_version = ?",
                             (prompt_version,)).fetchone()[0]

    items, per_label = [], {}
    for sid, rr in runs.items():
        if sid not in units:
            continue
        case_id, unit_idx, unit_start, text = units[sid]
        for label in sorted(majority(rr) - {"NONE"}):
            run = next((r for r in sorted(rr) if label in rr[r] and (sid, r, label) in quotes), None)
            if run is None:
                continue
            for pol, sub, quote in quotes[(sid, run, label)]:
                span = resolve_quote(quote, text, label)
                if span is None or (label in ANCHOR_REQUIRED and not quote_anchored(label, quote)):
                    continue
                pol = None if (pol or "").startswith("INVALID:") else pol
                sub = None if (sub or "").startswith("INVALID:") else sub
                items.append((case_id, unit_idx, label, pol, sub, quote, unit_start + span[0], unit_start + span[1]))
                per_label[label] = per_label.get(label, 0) + 1

    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    with closing(sqlite3.connect(out)) as g:
        g.executescript(GUIDE_SCHEMA)
        g.executemany('INSERT INTO reasoning (case_id, unit_idx, label, polarity, basis, quote, span_start, span_end) '
                      "VALUES (?,?,?,?,?,?,?,?)", items)
        meta = {"manual_version": MANUAL_VERSION, "prompt_version": prompt_version, "runs": str(n_runs),
                "source": str(db), "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        g.executemany("INSERT INTO meta VALUES (?, ?)", list(meta.items()))
        g.commit()
    return {"cases": len({i[0] for i in items}), "items": len(items), "labels": per_label, "runs": n_runs}


def main():
    base = config.ARTIFACTS_DIR / GUIDE_DIR
    ap = argparse.ArgumentParser(description="判決導讀「法院怎麼認定」用的整篇標註")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="把指定判決的所有論點單位放進標註資料庫")
    b.add_argument("--case-ids", default="", help="逗號或空白分隔，例如 101,205,318")
    b.add_argument("--ids-file", type=Path, help="一行一個判決 id")
    b.add_argument("--cases", type=Path, default=config.ARTIFACTS_DIR / "retrieval_civil_v4" / "cases.sqlite")
    b.add_argument("--db", type=Path, default=base / "annotation.sqlite")
    e = sub.add_parser("export", help="匯出 guide.sqlite 給後端")
    e.add_argument("--db", type=Path, default=base / "annotation.sqlite")
    e.add_argument("--out", type=Path, default=base / GUIDE_DB)
    args = ap.parse_args()

    if args.cmd == "build":
        text = args.case_ids + (" " + args.ids_file.read_text(encoding="utf-8") if args.ids_file else "")
        ids = parse_ids(text)
        if not ids:
            ap.error("請用 --case-ids 或 --ids-file 指定判決 id")
        r = build(args.cases, args.db, ids)
        print(f"新增 {len(r['added'])} 件判決、{r['units']} 個論點單位 → {args.db}")
        if r["skipped"]:
            print(f"已經在資料庫裡、跳過：{r['skipped']}")
        if r["missing"]:
            print(f"找不到或沒有法院判斷段：{r['missing']}")
        print(f"下一步：python -m annotation.annotate --db \"{args.db}\" --run-no 1")
    else:
        r = export(args.db, args.out)
        print(f"匯出 {r['cases']} 件判決、{r['items']} 個項目（{r['runs']} 輪）→ {args.out}")
        print("各標籤：" + json.dumps(r["labels"], ensure_ascii=False))


if __name__ == "__main__":
    main()
