"""
刑事相似判決的判決全文（遮名後），給刑事判決導讀用。只取檢索語料裡的案件，存成 cases.sqlite 的 full_text 表。

    python -m retrieval.criminal_fulltext --data <CAIL 格式 .jsonl> --db-dir <開放資料資料庫資料夾>
        # 預設寫進 artifacts/retrieval_criminal_v1/cases.sqlite（要先跑 python -m retrieval.criminal）

全文來自司法院資料開放平臺轉成的資料庫（data_pipeline/opendata_convert.py，每年一份 刑事判決_全國地院_<年>.db），
用 CAIL 資料集的 jid 對應。遮名（retrieval.masking.mask_parties）：
  - 被告：資料集的 criminals 與資料庫的 defendant 欄 →【被告】
  - 辯護人、代理人：defendant_agent、plaintiff_agent →【代理人】
  - 被害人、證人、店員等有稱謂的人名，以及 third_party_names 找到的第三人 →【關係人】
  - 身分證字號、電話、電子郵件、地址等用 mask() 的規則
  - 公訴人（檢察署）、法官、書記官不遮：是機關或執行職務的公務員
規則版仍可能漏掉沒有稱謂的人名，repo 一定要維持私人。
"""
import argparse
import collections
import json
import re
import sqlite3
from pathlib import Path
from typing import Dict, List

from retrieval.criminal import _OWNER_NAME_RE, _ROLE_NAME_RE, artifact_dir
from retrieval.masking import mask_parties, third_party_names

DB_NAME = "刑事判決_全國地院_{year}.db"
CHUNK = 900                                   # SQLite 一次 IN (...) 的上限內
_SPACED = re.compile(r"^[一-鿿][\s　]+[一-鿿]{1,2}$")   # 「王 韡」「黃 虎」：中間有空白的名字


def masked_full_text(text: str, criminals: List[str], defendant: str, agents: List[str]) -> str:
    names = [n for n in [defendant or ""] + list(criminals) if n]
    # 兩個字的名字常寫成「王 韡」：party_names 會在空白處切開而遮不到，先整個換掉，並把去掉空白的寫法加進被告
    for name in sorted({n.strip() for n in names if _SPACED.search(n.strip())}, key=len, reverse=True):
        text = text.replace(name, "【被告】")
        names.append(re.sub(r"\s+", "", name))
    others = set(third_party_names(text)) | set(_ROLE_NAME_RE.findall(text)) | set(_OWNER_NAME_RE.findall(text))
    defendants = "；".join(n for n in names if not _SPACED.search(n.strip()))
    others -= {n for n in others if n in defendants}
    return mask_parties(text, None, defendants, agents, sorted(others, key=len, reverse=True))


def case_lines(db: Path) -> Dict[int, int]:
    """cases.sqlite 裡的案件：CAIL 資料集的行號 → row。"""
    con = sqlite3.connect(db)
    try:
        return {int(i): int(r) for r, i in con.execute("SELECT row, id FROM cases")}
    finally:
        con.close()


def read_meta(path: Path, lines: Dict[int, int]) -> Dict[int, Dict]:
    out = {}
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            if i in lines:
                m = json.loads(line)["meta"]
                out[i] = {"jid": m["jid"], "year": m.get("year"), "criminals": m.get("criminals") or []}
    return out


def build(data: Path, db_dir: Path, out_db: Path) -> collections.Counter:
    lines = case_lines(out_db)
    meta = read_meta(data, lines)
    by_year = collections.defaultdict(list)
    for i, m in meta.items():
        by_year[m["year"]].append(i)
    count = collections.Counter()
    out = sqlite3.connect(out_db)
    try:
        out.execute("DROP TABLE IF EXISTS full_text")
        out.execute("CREATE TABLE full_text (row INTEGER PRIMARY KEY, text TEXT)")
        for year, ids in sorted(by_year.items()):
            src = sqlite3.connect(f"file:{db_dir / DB_NAME.format(year=year)}?mode=ro", uri=True)
            jid_to_line = {meta[i]["jid"]: i for i in ids}
            jids = list(jid_to_line)
            rows = []
            for k in range(0, len(jids), CHUNK):
                part = jids[k:k + CHUNK]
                q = ("SELECT jid, full_text, defendant, defendant_agent, plaintiff_agent FROM judgments "
                     f"WHERE jid IN ({','.join('?' * len(part))})")
                for jid, text, defendant, d_agent, p_agent in src.execute(q, part):
                    i = jid_to_line[jid]
                    rows.append((lines[i], masked_full_text(text or "", meta[i]["criminals"], defendant, [d_agent, p_agent])))
            src.close()
            out.executemany("INSERT INTO full_text VALUES (?, ?)", rows)
            out.commit()
            count[year] = len(rows)
            print(f"{year}：{len(rows):,}／{len(ids):,}", flush=True)
    finally:
        out.close()
    return count


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True, type=Path, help="建檢索時用的 CAIL 格式 .jsonl（行號要相同）")
    ap.add_argument("--db-dir", required=True, type=Path, help="刑事判決_全國地院_<年>.db 所在的資料夾")
    ap.add_argument("--out", type=Path, default=None, help="檢索資料夾（預設 artifacts/retrieval_criminal_v1）")
    a = ap.parse_args()
    db = (a.out or artifact_dir()) / "cases.sqlite"
    count = build(a.data, a.db_dir, db)
    meta_path = db.parent / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["full_text"] = {"n_cases": sum(count.values()), "source": "司法院資料開放平臺（data_opendata/db）",
                         "masking": "被告、辯護人、有稱謂的第三人換成角色；公訴人、法官、書記官不遮"}
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"共 {sum(count.values()):,} 件，寫進 {db}")


if __name__ == "__main__":
    main()
