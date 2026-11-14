"""
從民事檢索資料（cases.sqlite 的 sections.court，法院判斷段）抽出要標註的段落。

段落切分直接用 civil.insights._paragraphs()，和判決導讀畫面上的段落一模一樣，
標註結果才能用（案件 id, 段落序號）對回導讀頁。

抽兩批：
  random    隨機分層樣本：依段落在判決中的位置（前／中／後三分之一）平均抽，每件判決最多 1 段。
            用來估計各標籤的實際比例。
  enriched  線索加抽：先用 cues.py 的線索篩出可能是 DAM、SUB、送達的段落，再各抽 n 段。
            只用來抽查精確度，不能拿來估比例（batch 欄寫 enriched:DAM 等）。

用法：
    python -m annotation.sample                                  # 預設讀 artifacts/retrieval_civil_v4/cases.sqlite
    python -m annotation.sample --cases civil_sample_3000.sqlite  # 讀抽出來的小檔案
    python -m annotation.sample --n-random 200 --n-enriched 30

輸出：artifacts/annotation_civil_v1/annotation.sqlite 的 paragraphs 表，以及 meta.json。
重跑會清空 paragraphs 表重抽，但不動 annotations 表，請確認沒有已標註的資料再重跑。
"""
import argparse
import json
from contextlib import closing
import random
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from annotation.cues import CUES  # noqa: E402
from civil.insights import _paragraphs  # noqa: E402

OUT_NAME = "annotation_civil_v1"
FIRST_ID = 1001          # 與舊的 samples（1–528）分開，避免混淆
MIN_LEN = 20             # 少於 20 字不標（手冊規則）
ENRICH_LABELS = ("DAM", "SUB", "SERVICE")

SCHEMA = """
CREATE TABLE IF NOT EXISTS paragraphs (
    sample_id   INTEGER PRIMARY KEY,
    case_id     INTEGER,      -- cases.id，對回判決導讀
    para_idx    INTEGER,      -- _paragraphs() 切出來的第幾段（從 0 起）
    n_paras     INTEGER,
    position    TEXT,         -- 前段／中段／後段
    batch       TEXT,         -- random／enriched:DAM／enriched:SUB／enriched:SERVICE
    category    TEXT,         -- cases.category（案由大類）
    prev_text   TEXT,
    para_text   TEXT,
    next_text   TEXT
);
CREATE TABLE IF NOT EXISTS annotations (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    sample_id      INTEGER,
    annotator      TEXT,
    run_no         INTEGER,
    label          TEXT,
    polarity       TEXT,
    quote          TEXT,
    confidence     TEXT,
    quote_valid    INTEGER,
    manual_version TEXT,
    prompt_version TEXT,
    raw_response   TEXT,
    created_at     TEXT
);
"""


def position_of(i: int, n: int) -> str:
    r = i / n
    return "前段" if r < 1 / 3 else ("中段" if r < 2 / 3 else "後段")


def split_case(case_id: int, category: str, court: str) -> list:
    """一件判決的法院判斷段切成段落，附上前後段與位置。"""
    paras = _paragraphs(court)
    out = []
    for i, p in enumerate(paras):
        if len(p.strip()) < MIN_LEN:
            continue
        out.append({
            "case_id": case_id, "category": category, "para_idx": i, "n_paras": len(paras),
            "position": position_of(i, len(paras)),
            "prev_text": paras[i - 1] if i > 0 else "", "para_text": p,
            "next_text": paras[i + 1] if i + 1 < len(paras) else "",
        })
    return out


def build_sample(cases_db: Path, out_db: Path, n_random: int, n_enriched: int, seed: int) -> dict:
    # 連線用完一定要關：Windows 不能刪除或覆蓋還開著的資料庫檔
    with closing(sqlite3.connect(cases_db)) as src:
        got_pos, got_enr, n_source = _draw(src, n_random, n_enriched, seed)
    per_pos_keys = list(got_pos)

    rows = [dict(p, batch="random") for k in per_pos_keys for p in got_pos[k]]
    rows += [dict(p, batch=f"enriched:{k}") for k in ENRICH_LABELS for p in got_enr[k]]

    out_db.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(out_db)) as out:
        out.executescript(SCHEMA)
        out.execute("DELETE FROM paragraphs")
        out.executemany(
            "INSERT INTO paragraphs VALUES (?,?,?,?,?,?,?,?,?,?)",
            [(FIRST_ID + i, r["case_id"], r["para_idx"], r["n_paras"], r["position"], r["batch"],
              r["category"], r["prev_text"], r["para_text"], r["next_text"]) for i, r in enumerate(rows)])
        out.commit()

    counts = {"random": {k: len(v) for k, v in got_pos.items()},
              "enriched": {k: len(v) for k, v in got_enr.items()}}
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                                cwd=Path(__file__).parent).stdout.strip()
    except OSError:
        commit = ""
    meta = {"name": OUT_NAME, "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source": str(cases_db), "n_source_cases": n_source, "seed": seed,
            "splitter": "civil.insights._paragraphs", "min_len": MIN_LEN, "first_sample_id": FIRST_ID,
            "counts": counts, "git_commit": commit}
    (out_db.parent / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return counts


def _draw(src: sqlite3.Connection, n_random: int, n_enriched: int, seed: int) -> tuple:
    """依打亂後的順序逐件讀判決，先抽滿隨機樣本，再做線索加抽。回傳 (隨機, 加抽, 來源件數)。"""
    ids = [r[0] for r in src.execute(
        "SELECT s.id FROM sections s WHERE length(s.court) > 0 ORDER BY s.id")]
    rng = random.Random(seed)
    rng.shuffle(ids)

    per_pos = {"前段": n_random // 3, "中段": n_random // 3, "後段": n_random - 2 * (n_random // 3)}
    got_pos = {k: [] for k in per_pos}
    got_enr = {k: [] for k in ENRICH_LABELS}
    used_cases = set()

    def full():
        return (all(len(got_pos[k]) >= per_pos[k] for k in per_pos)
                and all(len(got_enr[k]) >= n_enriched for k in ENRICH_LABELS))

    # 依打亂後的順序逐件讀，一件判決最多貢獻 1 段（不論哪一批）
    for start in range(0, len(ids), 500):
        if full():
            break
        chunk = ids[start:start + 500]
        rows = src.execute(
            f"SELECT s.id, c.category, s.court FROM sections s LEFT JOIN cases c ON c.id = s.id "
            f"WHERE s.id IN ({','.join('?' * len(chunk))})", chunk).fetchall()
        rows.sort(key=lambda r: chunk.index(r[0]))
        for case_id, category, court in rows:
            if full():
                break
            paras = split_case(case_id, category, court)
            if not paras:
                continue
            rng.shuffle(paras)
            picked = None
            random_full = all(len(got_pos[k]) >= per_pos[k] for k in per_pos)
            if not random_full:
                # 隨機樣本先抽滿，而且完全不看線索，比例的估計才不會偏
                for p in paras:
                    if len(got_pos[p["position"]]) < per_pos[p["position"]]:
                        got_pos[p["position"]].append(p)
                        picked = p
                        break
            else:
                # 隨機樣本滿了之後，剩下的判決才拿來加抽（稀有的類別優先）
                for label in ENRICH_LABELS:
                    if len(got_enr[label]) < n_enriched:
                        hit = next((p for p in paras if CUES[label].search(p["para_text"])), None)
                        if hit:
                            got_enr[label].append(hit)
                            picked = hit
                            break
            if picked is not None:
                used_cases.add(case_id)

    return got_pos, got_enr, len(ids)


def main():
    ap = argparse.ArgumentParser(description="抽出要標註的民事法院判斷段落")
    ap.add_argument("--cases", type=Path, default=config.ARTIFACTS_DIR / "retrieval_civil_v4" / "cases.sqlite")
    ap.add_argument("--out", type=Path, default=config.ARTIFACTS_DIR / OUT_NAME / "annotation.sqlite")
    ap.add_argument("--n-random", type=int, default=200)
    ap.add_argument("--n-enriched", type=int, default=30, help="每個加抽類別的段數")
    ap.add_argument("--seed", type=int, default=20261106)
    args = ap.parse_args()
    counts = build_sample(args.cases, args.out, args.n_random, args.n_enriched, args.seed)
    print("隨機樣本：", counts["random"])
    print("線索加抽：", counts["enriched"])
    print("輸出：", args.out)


if __name__ == "__main__":
    main()
