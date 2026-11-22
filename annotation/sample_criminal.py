"""
刑事抽樣：從刑事檢索庫的判決導讀段落抽出待標段落，
寫成和民事 sample.py 相同格式的 annotation.sqlite，後面的 annotate.py、spot_check.py 可以直接沿用。

    python -m annotation.sample_criminal --n 300                     # 預設讀 artifacts/retrieval_criminal_v1/cases.sqlite
    python -m annotation.annotate --db <輸出的 annotation.sqlite> --run-no 1 --limit 1   # 自動用刑事的 prompt

做法：
  - 段落來源和後端的刑事導讀頁相同（backend/criminal_service.guide）：
    cases.sqlite 有 full_text 表（遮名原文包）時，用 criminal_guides.segment(全文) 當場分段；
    沒有時才讀舊版的 guides 表（只取 source = judgment，資料集犯罪事實節錄的不取）
  - 只標法院自己的判斷：判決本文裡功能為「證據」（evidence）或「論罪科刑」（court）的段落。
    犯罪事實、主文、法條、附表都不標；附在判決後面的檢察官書類（part＝「附件：⋯」）整段不標
  - 每件判決隨機抽一段，前後段（不論功能）各取末／首 300 字當脈絡
  - 導讀段落已遮名、最長約 600 字（criminal_guides._paragraphs），直接當作標註單位，不再切論點單位
  - unit_start／unit_end 記錄本段在導讀段落裡的範圍（就是整段），para_idx 是導讀段落的序號，
    之後要把引文對回刑事導讀頁，用 para_idx 加上引文在段內的位置即可
  - batch 寫成 criminal-random，annotate.py 看到就自動改用刑事的 prompt 與標籤
"""
import argparse
import json
import random
import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from annotation.sample import CONTEXT, MIN_LEN, SCHEMA, position_of, used_case_ids  # noqa: E402
from retrieval.criminal_guides import segment  # noqa: E402

OUT_NAME = "annotation_criminal_v1"
CASES_NAME = "retrieval_criminal_v1"
FIRST_ID = 9001            # 刑事從 9001 起，和民事的 sample_id 分開
FUNCTIONS = ("evidence", "court")
BATCH = "criminal-random"


def eligible(paragraphs: list, functions=FUNCTIONS) -> list:
    """可以標的段落序號：功能是證據或論罪科刑、不是表格或預排版、至少 MIN_LEN 字，
    而且是判決本文（part 為空）。簡易判決常把檢察官的聲請簡易判決處刑書、起訴書附在後面（part＝「附件：⋯」），
    裡面的「犯嫌應堪認定」「罪嫌」是檢察官的判斷，不是法院的，不標（刑事 v0.6 抽查：EV 錯的 9 個裡有 7 個是附件）。"""
    return [i for i, p in enumerate(paragraphs)
            if p.get("function") in functions and not p.get("pre") and not p.get("part")
            and len((p.get("text") or "").strip()) >= MIN_LEN]


def unit_row(case_id: int, paragraphs: list, i: int, charges, sentence) -> dict:
    text = paragraphs[i]["text"]
    prev = paragraphs[i - 1]["text"][-CONTEXT:] if i > 0 else ""
    nxt = paragraphs[i + 1]["text"][:CONTEXT] if i + 1 < len(paragraphs) else ""
    try:
        charge_list = json.loads(charges) if charges else []
    except (TypeError, ValueError):
        charge_list = []
    return {"case_id": case_id, "para_idx": i, "n_paras": len(paragraphs),
            "position": position_of(i, len(paragraphs)), "batch": BATCH,
            "category": "、".join(charge_list) if charge_list else None,
            "prev_text": prev, "para_text": text, "next_text": nxt,
            "unit_start": 0, "unit_end": len(text), "split_how": f"criminal-guide:{paragraphs[i]['function']}",
            "outcome": sentence, "grant_ratio": None}


def tables(src: sqlite3.Connection) -> set:
    return {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def candidates(src: sqlite3.Connection) -> list:
    """有導讀段落可抽的判決 id（依 id 排序）：新版看 full_text，舊版看 guides。"""
    if "full_text" in tables(src):
        return [r[0] for r in src.execute("SELECT c.id FROM cases c JOIN full_text f ON f.row = c.row "
                                          "WHERE f.text IS NOT NULL AND f.text != '' ORDER BY c.id")]
    return [r[0] for r in src.execute("SELECT case_id FROM guides WHERE source = 'judgment' ORDER BY case_id")]


def paragraphs_of(src: sqlite3.Connection, case_id: int) -> tuple:
    """(導讀段落, charges, sentence)；和後端刑事導讀頁同一種分段。"""
    c = src.execute("SELECT row, charges, sentence FROM cases WHERE id = ?", (case_id,)).fetchone()
    if c is None:
        return [], None, None
    if "full_text" in tables(src):
        t = src.execute("SELECT text FROM full_text WHERE row = ?", (c[0],)).fetchone()
        return (segment(t[0]) if t and t[0] else []), c[1], c[2]
    g = src.execute("SELECT paragraphs FROM guides WHERE case_id = ?", (case_id,)).fetchone()
    return (json.loads(g[0]) if g else []), c[1], c[2]


def draw(src: sqlite3.Connection, n: int, seed: int, exclude: set = frozenset()) -> tuple:
    """隨機排序有導讀段落的判決，依序取到 n 件有可標段落的；回傳 (單位列, 候選判決數)。"""
    ids = [i for i in candidates(src) if i not in exclude]
    rng = random.Random(seed)
    rng.shuffle(ids)
    rows = []
    for case_id in ids:
        if len(rows) >= n:
            break
        paragraphs, charges, sentence = paragraphs_of(src, case_id)
        ok = eligible(paragraphs)
        if ok:
            rows.append(unit_row(case_id, paragraphs, rng.choice(ok), charges, sentence))
    return rows, len(ids)


def build_sample(cases_db: Path, out_db: Path, n: int, seed: int, exclude: set = frozenset(),
                 first_id: int = FIRST_ID) -> dict:
    with closing(sqlite3.connect(f"file:{cases_db}?mode=ro", uri=True)) as src:
        rows, n_source = draw(src, n, seed, exclude)
    out_db.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(out_db)) as out:
        out.executescript(SCHEMA)
        if out.execute("SELECT COUNT(*) FROM paragraphs").fetchone()[0]:
            raise SystemExit(f"{out_db} 已經有段落了；要重抽請換一個 --out，避免和已標註的資料混在一起")
        out.executemany(
            "INSERT INTO paragraphs (sample_id, case_id, para_idx, n_paras, position, batch, category, prev_text, "
            "para_text, next_text, unit_start, unit_end, split_how, outcome, grant_ratio) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(first_id + k, r["case_id"], r["para_idx"], r["n_paras"], r["position"], r["batch"], r["category"],
              r["prev_text"], r["para_text"], r["next_text"], r["unit_start"], r["unit_end"], r["split_how"],
              r["outcome"], r["grant_ratio"]) for k, r in enumerate(rows)])
        out.commit()
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                                cwd=Path(__file__).resolve().parents[1]).stdout.strip() or None
    except OSError:
        commit = None
    funcs = {}
    for r in rows:
        funcs[r["split_how"]] = funcs.get(r["split_how"], 0) + 1
    meta = {"source": str(cases_db), "domain": "criminal", "seed": seed, "n": len(rows), "n_source_cases": n_source,
            "n_excluded_cases": len(exclude), "functions": list(FUNCTIONS), "by_function": funcs,
            "first_id": first_id, "created_at": datetime.now().isoformat(), "git_commit": commit}
    (out_db.parent / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def main():
    ap = argparse.ArgumentParser(description="刑事抽樣：從判決導讀抽出證據、論罪科刑段落")
    ap.add_argument("--cases", type=Path, default=config.ARTIFACTS_DIR / CASES_NAME / "cases.sqlite")
    ap.add_argument("--out", type=Path, default=config.ARTIFACTS_DIR / OUT_NAME / "annotation.sqlite")
    ap.add_argument("--n", type=int, default=300, help="抽幾件判決（每件一段）")
    ap.add_argument("--seed", type=int, default=20261122)
    ap.add_argument("--exclude", type=Path, nargs="*", default=[], help="先前刑事各輪的 annotation.sqlite，排除用過的判決")
    args = ap.parse_args()
    if not args.cases.exists():
        raise SystemExit(f"找不到 {args.cases}：先跑 scripts/sync_criminal_models.sh 下載刑事檢索庫")
    with closing(sqlite3.connect(f"file:{args.cases}?mode=ro", uri=True)) as con:
        found = tables(con)
        if not found & {"full_text", "guides"}:
            raise SystemExit(f"{args.cases} 沒有 full_text 表（遮名原文包）也沒有 guides 表，抽不到判決導讀段落；"
                             f"目前的表：{sorted(found)}")
        print(f"段落來源：{'full_text（遮名原文，當場分段）' if 'full_text' in found else 'guides（舊版導讀表）'}")
    exclude = used_case_ids(args.exclude) if args.exclude else set()
    meta = build_sample(args.cases, args.out, args.n, args.seed, exclude)
    print(f"抽出 {meta['n']} 段（候選判決 {meta['n_source_cases']:,} 件，排除 {meta['n_excluded_cases']} 件）")
    print(f"段落功能：{meta['by_function']}")
    print(f"已寫入 {args.out}")


if __name__ == "__main__":
    main()
