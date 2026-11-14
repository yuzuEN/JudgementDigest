"""
從民事檢索資料（cases.sqlite 的 sections.court，法院判斷段）抽出要標註的「論點單位」。

v0.5 起改用論點單位（annotation/structure.py）：依判決的層級編號（壹、一、㈠、⒈、⑴、①）
解析成樹，一個節點（含子項）在 1,200 字內就整塊當一個單位，太長才往下一層拆，
沒有子編號又太長才在句號處切。這樣一個爭點的大前提、事實認定與結論多半落在同一單位。
標註結果用逐字引文在法院判斷段中的位置對回判決導讀的段落（unit_start／unit_end 記錄單位位置）。
v0.4 以前用的是 civil.insights._paragraphs()（400 字硬切），結果在 annotation_civil_v1、v2。

抽兩批：
  random    隨機分層樣本：依單位在判決中的位置（前／中／後三分之一）平均抽，每件判決最多 1 段。
            用來估計各標籤的實際比例。
  enriched  線索加抽：先用 cues.py 的線索篩出可能是 DAM、SUB、EXP 的單位，再各抽 n 段。
            只用來抽查精確度，不能拿來估比例（batch 欄寫 enriched:DAM 等）。

用法：
    python -m annotation.sample                                  # 預設讀 artifacts/retrieval_civil_v3/cases.sqlite
    python -m annotation.sample --cases civil_sample_3000.sqlite  # 讀抽出來的小檔案
    python -m annotation.sample --n-random 200 --n-enriched 30

輸出：artifacts/annotation_civil_v3/annotation.sqlite 的 paragraphs 表，以及 meta.json。
預設排除先前各輪（annotation_civil_v1、v2）用過的判決，確保新版手冊以新段落驗證。
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
from annotation.structure import units  # noqa: E402

OUT_NAME = "annotation_civil_v3"     # v0.5 起；v0.3 在 annotation_civil_v1、v0.4 在 annotation_civil_v2
PREV_NAMES = ("annotation_civil_v1", "annotation_civil_v2")  # 先前各輪：抽樣時排除這些輪用過的判決
FIRST_ID = 3001          # v0.4 為 2001 起、v0.3 為 1001 起、更早的 samples 為 1–528
MIN_LEN = 20             # 少於 20 字不標（手冊規則）
MAX_UNIT = 1200          # 論點單位的長度上限（v0.5 以 3,000 件判決測試選定）
CONTEXT = 300            # 前後文只取相鄰單位的末／首 300 字：單位較長，整段放進去費用會變成三倍
ENRICH_LABELS = ("DAM", "SUB", "EXP")

SCHEMA = """
CREATE TABLE IF NOT EXISTS paragraphs (
    sample_id   INTEGER PRIMARY KEY,
    case_id     INTEGER,      -- cases.id，對回判決導讀
    para_idx    INTEGER,      -- 第幾個論點單位（從 0 起）
    n_paras     INTEGER,
    position    TEXT,         -- 前段／中段／後段
    batch       TEXT,         -- random／enriched:DAM／enriched:SUB／enriched:EXP
    category    TEXT,         -- cases.category（案由大類）
    prev_text   TEXT,         -- 前一單位的最後 CONTEXT 字
    para_text   TEXT,         -- 本單位全文
    next_text   TEXT,         -- 後一單位的前 CONTEXT 字
    unit_start  INTEGER,      -- 本單位在 sections.court 的起訖位置，用來把引文對回導讀段落
    unit_end    INTEGER,
    split_how   TEXT,         -- structure（沿編號切）／sentence（句號硬切）
    outcome     TEXT,         -- cases.outcome：勝訴／一部勝訴一部敗訴／敗訴／確認勝訴（CONCL 自動比對用）
    grant_ratio REAL
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
    subtype        TEXT,      -- v0.5：EV 的子欄位（明示評價／依證據推論）
    manual_version TEXT,
    prompt_version TEXT,
    raw_response   TEXT,
    created_at     TEXT
);
"""


def position_of(i: int, n: int) -> str:
    r = i / n
    return "前段" if r < 1 / 3 else ("中段" if r < 2 / 3 else "後段")


def split_case(case_id: int, category: str, court: str, outcome=None, grant_ratio=None) -> list:
    """一件判決的法院判斷段切成論點單位，附上前後文、位置與判決結果。"""
    us = units(court, MAX_UNIT)
    out = []
    for i, (s, e, how) in enumerate(us):
        text = court[s:e]
        if len(text.strip()) < MIN_LEN:
            continue
        prev = court[us[i - 1][0]:us[i - 1][1]][-CONTEXT:] if i > 0 else ""
        nxt = court[us[i + 1][0]:us[i + 1][1]][:CONTEXT] if i + 1 < len(us) else ""
        out.append({
            "case_id": case_id, "category": category, "para_idx": i, "n_paras": len(us),
            "position": position_of(i, len(us)), "prev_text": prev, "para_text": text, "next_text": nxt,
            "unit_start": s, "unit_end": e, "split_how": how, "outcome": outcome, "grant_ratio": grant_ratio,
        })
    return out


def used_case_ids(dbs) -> set:
    """先前各輪抽過的判決 id。新一輪的手冊由先前的抽查結果導出，驗證不能再用同一批判決。"""
    used = set()
    for db in dbs:
        if Path(db).exists():
            with closing(sqlite3.connect(db)) as con:
                used |= {r[0] for r in con.execute("SELECT DISTINCT case_id FROM paragraphs")}
    return used


def build_sample(cases_db: Path, out_db: Path, n_random: int, n_enriched: int, seed: int,
                 exclude_cases: set = frozenset(), first_id: int = FIRST_ID) -> dict:
    # 連線用完一定要關：Windows 不能刪除或覆蓋還開著的資料庫檔
    with closing(sqlite3.connect(cases_db)) as src:
        got_pos, got_enr, n_source = _draw(src, n_random, n_enriched, seed, exclude_cases)
    per_pos_keys = list(got_pos)

    rows = [dict(p, batch="random") for k in per_pos_keys for p in got_pos[k]]
    rows += [dict(p, batch=f"enriched:{k}") for k in ENRICH_LABELS for p in got_enr[k]]

    out_db.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(out_db)) as out:
        out.executescript(SCHEMA)
        out.execute("DELETE FROM paragraphs")
        out.executemany(
            "INSERT INTO paragraphs (sample_id, case_id, para_idx, n_paras, position, batch, category, prev_text, "
            "para_text, next_text, unit_start, unit_end, split_how, outcome, grant_ratio) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(first_id + i, r["case_id"], r["para_idx"], r["n_paras"], r["position"], r["batch"],
              r["category"], r["prev_text"], r["para_text"], r["next_text"], r["unit_start"], r["unit_end"],
              r["split_how"], r["outcome"], r["grant_ratio"]) for i, r in enumerate(rows)])
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
            "splitter": f"annotation.structure.units(max_len={MAX_UNIT})", "context_chars": CONTEXT, "min_len": MIN_LEN, "first_sample_id": first_id,
            "n_excluded_cases": len(exclude_cases),
            "counts": counts, "git_commit": commit}
    (out_db.parent / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return counts


def _draw(src: sqlite3.Connection, n_random: int, n_enriched: int, seed: int,
          exclude_cases: set = frozenset()) -> tuple:
    """依打亂後的順序逐件讀判決，先抽滿隨機樣本，再做線索加抽。回傳 (隨機, 加抽, 來源件數)。"""
    ids = [r[0] for r in src.execute(
        "SELECT s.id FROM sections s WHERE length(s.court) > 0 ORDER BY s.id")]
    rng = random.Random(seed)
    rng.shuffle(ids)
    ids = [i for i in ids if i not in exclude_cases]

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
            f"SELECT s.id, c.category, s.court, c.outcome, c.grant_ratio FROM sections s LEFT JOIN cases c ON c.id = s.id "
            f"WHERE s.id IN ({','.join('?' * len(chunk))})", chunk).fetchall()
        rows.sort(key=lambda r: chunk.index(r[0]))
        for case_id, category, court, outcome, grant_ratio in rows:
            if full():
                break
            paras = split_case(case_id, category, court, outcome, grant_ratio)
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
    ap = argparse.ArgumentParser(description="抽出要標註的民事法院判斷段論點單位")
    ap.add_argument("--cases", type=Path, default=config.ARTIFACTS_DIR / "retrieval_civil_v3" / "cases.sqlite")
    ap.add_argument("--out", type=Path, default=config.ARTIFACTS_DIR / OUT_NAME / "annotation.sqlite")
    ap.add_argument("--n-random", type=int, default=200)
    ap.add_argument("--n-enriched", type=int, default=30, help="每個加抽類別的段數")
    ap.add_argument("--seed", type=int, default=20261114)
    ap.add_argument("--exclude", type=Path, nargs="*",
                    default=[config.ARTIFACTS_DIR / n / "annotation.sqlite" for n in PREV_NAMES],
                    help="排除這些資料庫用過的判決（預設：先前各輪）")
    args = ap.parse_args()
    exclude = used_case_ids(args.exclude)
    print(f"排除先前各輪用過的判決：{len(exclude)} 件")
    counts = build_sample(args.cases, args.out, args.n_random, args.n_enriched, args.seed, exclude)
    print("隨機樣本：", counts["random"])
    print("線索加抽：", counts["enriched"])
    print("輸出：", args.out)


if __name__ == "__main__":
    main()
