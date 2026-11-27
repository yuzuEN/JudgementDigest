"""
刑事相似判決的判決全文（遮名後），給刑事判決導讀用。只取檢索語料裡的案件，存成 cases.sqlite 的 full_text 表。

    python -m retrieval.criminal_fulltext --data <CAIL 格式 .jsonl> --db-dir <開放資料資料庫資料夾>
    python -m retrieval.criminal_fulltext --remask-only [--out <檢索資料夾>]   # 已建好的 full_text 只補遮 extra_names
        # 預設寫進 artifacts/retrieval_criminal_v1/cases.sqlite（要先跑 python -m retrieval.criminal）

全文來自司法院資料開放平臺轉成的資料庫（data_pipeline/opendata_convert.py，每年一份 刑事判決_全國地院_<年>.db），
用 CAIL 資料集的 jid 對應。遮名（retrieval.masking.mask_parties）：
  - 被告：資料集的 criminals 與資料庫的 defendant 欄 →【被告】
  - 辯護人、代理人：defendant_agent、plaintiff_agent →【代理人】
  - 被害人、證人、店員等有稱謂的人名，以及 third_party_names 找到的第三人 →【關係人】
  - 「案經A、B訴由」列出的告訴人、稱謂後列舉的第二個以後的名字 →【關係人】；「委任／委請X律師」→【代理人】（extra_names）
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
from typing import Dict, Iterable, List, Optional

from retrieval.criminal import _OWNER_NAME_RE, _ROLE_NAME_RE, artifact_dir
from retrieval.masking import _NAME, mask_parties, third_party_names

DB_NAME = "刑事判決_全國地院_{year}.db"
CHUNK = 900                                   # SQLite 一次 IN (...) 的上限內
_SPACED = re.compile(r"^[一-鿿][\s　]+[一-鿿]{1,2}$")   # 「王 韡」「黃 虎」：中間有空白的名字

# 「案經王大明、李小華訴由○○分局報告」：告訴人列在「案經」後面，沒有稱謂（2026-11-17 抽查，約兩成判決有）
_CASE_BY = re.compile(r"案經(.{1,300}?)(?:分別)?(?:訴由|告訴|告發|訴請|委任|委由|委請|共同委任|提出告訴)")
_CASE_BY_SPLIT = re.compile(r"[、，,及與和暨]")
_CASE_BY_ROLE = re.compile(r"^(?:告訴人|被害人|告發人|自訴人)")
# 「委任王大明律師訴由」「委請劉大華訴由」：告訴代理人
_ATTORNEY = re.compile(r"(?:委任|委由|委請)(" + _NAME + r")(?=律師|訴由|告訴|提出|、|，|$)")
_ORG = re.compile(r"公司|局|署|銀行|政府|所$|會$|院|處$|班$|店$|社$|部$|中心|學|協會|分行|機構|集團|科$|隊$|室$|廠|行$|館")
_FULL_NAME = re.compile(_NAME)
# 「告訴人王大明、李小華、陳大同提出告訴」：列舉時只有第一個名字有稱謂
_NAME_LIST = re.compile(r"、(" + _NAME + r")(?=[、，。）)及與和等共均]|$)")


def _follow_list(text: str, end: int, names: set) -> None:
    while True:
        item = _NAME_LIST.match(text, end)
        if not item:
            return
        names.add(item.group(1))
        end = item.end()


def extra_names(text: str) -> "tuple[set, set]":
    """規則版補遮：回傳 (關係人, 代理人)。只找沒被遮的名字（【…】裡的不算）。"""
    others, agents = set(), set()
    for m in _CASE_BY.finditer(text):
        for item in _CASE_BY_SPLIT.split(m.group(1)):
            item = _CASE_BY_ROLE.sub("", item.strip())
            if not _ORG.search(item) and _FULL_NAME.fullmatch(item):
                others.add(item)
    agents |= set(_ATTORNEY.findall(text))
    # 「告訴人王大明、李小華」：只有第一個名字有稱謂（第一個已經遮成【關係人】時也一樣）
    for m in list(_ROLE_NAME_RE.finditer(text)) + list(re.finditer("【關係人】", text)):
        _follow_list(text, m.end(), others)
    return others - agents, agents


def _flex(name: str) -> str:
    """全文每二十幾個字就換行，名字常被切成兩行（「王小」換行「明」）：字和字之間允許空白、換行。"""
    return "(?<!【)" + r"[\s　]*".join(map(re.escape, name))


def remask(text: str, defendants: Iterable[str] = (), rounds: int = 4) -> str:
    """已經遮過的全文再補遮（不用重讀原始資料庫）。
    名字要在去掉換行的文字上找，取代時允許名字中間有換行；被告用資料集的 criminals。
    遮掉一個名字後，後面「、李小華」的列舉才接得上，所以重複到找不到新名字為止。"""
    for n in sorted({re.sub(r"[\s　]+", "", d) for d in defendants if d and d.strip()}, key=len, reverse=True):
        if len(n) >= 2:
            text = re.sub(_flex(n), "【被告】", text)
    for _ in range(rounds):
        flat = re.sub(r"[\r\n]+", "", text)
        others, agents = extra_names(flat)
        others |= set(_ROLE_NAME_RE.findall(flat)) | set(third_party_names(flat)) | set(_OWNER_NAME_RE.findall(flat))
        others -= agents
        found = [(n, "【代理人】") for n in agents] + [(n, "【關係人】") for n in others]
        new = [(n, tag) for n, tag in found if re.search(_flex(n), text)]
        if not new:
            break
        for n, tag in sorted(new, key=lambda x: len(x[0]), reverse=True):
            text = re.sub(_flex(n), tag, text)
    return text


def masked_full_text(text: str, criminals: List[str], defendant: str, agents: List[str]) -> str:
    names = [n for n in [defendant or ""] + list(criminals) if n]
    # 兩個字的名字常寫成「王 韡」：party_names 會在空白處切開而遮不到，先整個換掉，並把去掉空白的寫法加進被告
    for name in sorted({n.strip() for n in names if _SPACED.search(n.strip())}, key=len, reverse=True):
        text = text.replace(name, "【被告】")
        names.append(re.sub(r"\s+", "", name))
    others = set(third_party_names(text)) | set(_ROLE_NAME_RE.findall(text)) | set(_OWNER_NAME_RE.findall(text))
    defendants = "；".join(n for n in names if not _SPACED.search(n.strip()))
    others -= {n for n in others if n in defendants}
    return remask(mask_parties(text, None, defendants, agents, sorted(others, key=len, reverse=True)), names)


def remask_db(db: Path, data: Optional[Path] = None) -> int:
    """已經建好的 full_text 表直接補遮（不用原始資料庫）；給 data（CAIL .jsonl）時被告也再遮一次。回傳改到的件數。"""
    lines = case_lines(db)
    criminals = {lines[i]: m["criminals"] for i, m in read_meta(data, lines).items()} if data else {}
    con = sqlite3.connect(db)
    try:
        changed = []
        for r, t in con.execute("SELECT row, text FROM full_text").fetchall():
            new = remask(t, criminals.get(r, ()))
            if new != t:
                changed.append((new, r))
        con.executemany("UPDATE full_text SET text = ? WHERE row = ?", changed)
        con.commit()
        return len(changed)
    finally:
        con.close()


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
    ap.add_argument("--data", type=Path, help="建檢索時用的 CAIL 格式 .jsonl（行號要相同）")
    ap.add_argument("--db-dir", type=Path, help="刑事判決_全國地院_<年>.db 所在的資料夾")
    ap.add_argument("--out", type=Path, default=None, help="檢索資料夾（預設 artifacts/retrieval_criminal_v1）")
    ap.add_argument("--remask-only", action="store_true", help="不重建，只對現有 full_text 表補遮")
    a = ap.parse_args()
    db = (a.out or artifact_dir()) / "cases.sqlite"
    if a.remask_only:
        print(f"補遮 {remask_db(db, a.data):,} 件：{db}")
        return
    if not (a.data and a.db_dir):
        ap.error("要給 --data 與 --db-dir（或用 --remask-only）")
    count = build(a.data, a.db_dir, db)
    meta_path = db.parent / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["full_text"] = {"n_cases": sum(count.values()), "source": "司法院資料開放平臺（data_opendata/db）",
                         "masking": "被告、辯護人、有稱謂的第三人換成角色；公訴人、法官、書記官不遮"}
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"共 {sum(count.values()):,} 件，寫進 {db}")


if __name__ == "__main__":
    main()
