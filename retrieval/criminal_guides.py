"""刑事判決導讀：把判決全文依原本的順序切成段落，標出每段在做什麼，補進刑事檢索庫（不重建索引、不改案件 ID）。

    python -m retrieval.criminal_guides --db judgments.db --cases artifacts/retrieval_criminal_v1/cases.sqlite \
        [--data <CAIL 格式 .jsonl 或 .zip>]

刑事導讀使用「完整原文＋段落標示」，不是萃取結果：
  案件資訊（法院、字號、當事人、案由）→ 主文 → 犯罪事實 → 理由（再分成證據、論罪科刑、法條）
  → 署名與上訴說明 → 附錄法條 → 附表 → 附件（起訴書、聲請簡易判決處刑書，裡面一樣分段）
段落的切法只看判決書本身的標題行（「主文」「犯罪事實」「理由」「附表一：」…）與段落編號，是規則，可能有誤。

全文來自 judgments.db（以司法院判決識別碼對應，同一個識別碼有多件時不用）。
judgments.db 沒有的案件，--data 提供時改用資料集的犯罪事實（只有這一段，標示為資料集節錄）。
"""
import argparse
import json
import re
import unicodedata
import sqlite3
import zipfile
from contextlib import closing
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional
from urllib.parse import parse_qs, urlparse

from retrieval.criminal import ROLES, _OWNER_NAME_RE, masked
from retrieval.masking import _NAME, _NOT_NAME, mask, party_names, third_party_names

LABELER = "criminal-rule-v1"
FUNCTIONS = {"info": "案件資訊", "verdict": "主文", "facts": "犯罪事實", "evidence": "證據", "court": "論罪科刑",
             "laws": "法條", "table": "附表", "other": "其他"}

_CJK = r"[^\x00-\x7f]"
# 司法院網頁把法律名詞做成連結，存下來的全文在名詞前後多了空白（「 意圖 為自己」）；中文字旁邊的空白都拿掉
_SPACE_RE = re.compile(rf"(?<={_CJK})[ 　]+|[ 　]+(?={_CJK})")
# 舊格式全文開頭／結尾的系統欄位（「檔名：[…]」「主文：[…]」），可能跨好幾行
_META_RE = re.compile(r"^(?:檔名|旗標|檢查單號|裁判類別|原因|主文|裁判字號|裁判日期|裁判案由)：\[")
_DATE_RE = re.compile(r"^中華民國\d{2,3}年\d{1,2}月\d{1,2}日$")
_TABLE_RE = re.compile(r"^附表[一二三四五六七八九十\d]*(?:[：:（(].{0,30})?$")
_ATTACHMENT_RE = re.compile(r"^附件[一二三四五六七八九十\d]*[：:]?$")
_ATTACHMENT_TITLE_RE = re.compile(r"(追加起訴書|起訴書|聲請簡易判決處刑書|移送併辦意旨書|併辦意旨書|上訴書)")
# 段落編號：一、 ㈠ （一） 壹、 甲、。前面是「第」「欄」「編號」「、」時是內文（第一、二級毒品；犯罪事實欄一、三），不切
# 編號只在句子開頭才算：前面是段首或「。：；」。「備忘錄三（五）規定」的（五）是引用，不切
_HEAD_SPLIT = re.compile(r"(?:^|(?<=[。：:；;]))(?=(?:[一二三四五六七八九十]{1,3}|[壹貳參叁肆伍陸柒捌玖拾]|[甲乙丙丁戊])、"
                         r"|[㈠-㈩]|[(（][一二三四五六七八九十]{1,3}[)）])")
_TOP_RE = re.compile(r"^(?:[一二三四五六七八九十]{1,3}|[壹貳參叁肆伍陸柒捌玖拾]|[甲乙丙丁戊])、")
_SUB_RE = re.compile(r"^(?:[㈠-㈩]|[(（][一二三四五六七八九十]{1,3}[)）])")
# 判決原文每行固定寬度換行（約 26 個中文字）；寬度接近的行是被折行，和下一行接起來
_WRAP_MIN, _WRAP_MAX = 46, 62
_CLOSE_RE = re.compile(r"^[，。、；：:）)」』〕】％%]")
_NUM = r"^(?:[一二三四五六七八九十]{1,3}、|[壹貳參叁肆伍陸柒捌玖拾]、|[甲乙丙丁戊]、|[㈠-㈩]|[(（][一二三四五六七八九十]{1,3}[)）])*"
_LAWS_PARA_RE = re.compile(_NUM + r"(?:據上論[斷結]|應適用之法條|本案論罪科刑法條)")
# 「依刑事訴訟法第449條…逕以簡易判決處刑如主文」是判決的法條依據；理由中途引用的「依刑事訴訟法第159條」不是
_LAWS_BY_CPC_RE = re.compile(_NUM + r"依刑事訴訟法第.{0,300}?(?:如主文|提起公訴|判決如下)")
# 列舉的人名：「證人Ａ女、劉怡伶、邵○霈、黃新明」只有第一個前面有稱謂，後面的也要遮
_GUIDE_ROLES = (*ROLES, "同案被告", "共同被告", "共犯", "人員", "董事長", "會長", "幹部", "法官", "檢察官", "書記官", "辯護人", "律師")
_GUIDE_ROLE_RE = re.compile(r"(?:" + "|".join(_GUIDE_ROLES) + r")(?:即|為)?" + _NOT_NAME + r"(" + _NAME + r")")
_LIST_START_RE = re.compile(r"(?:" + "|".join(_GUIDE_ROLES) + r")(?:即|為)?|(?=【(?:被告|關係人|姓名)】)")
_LIST_ITEM_RE = re.compile(_NOT_NAME + r"(" + _NAME + r"|[Ａ-ＺA-Z][女男]|[一-鿿]○[○一-鿿]?|【(?:被告|關係人|姓名)】[一-鿿]?)(?=[、及與和於之等，。（）()]|$)")
_LIST_NOTE_RE = re.compile(r"[（(][^（）()]*[）)]")
_OTHER_PARA_RE = re.compile(_NUM + r"(?:如不服本|本案經|本件經|此致|中華民國\d)")
_FACTS_PARA_RE = re.compile(r"^.{0,20}犯罪事實.{0,30}(?:引用|如附件|如下)|" + _NUM + r"(?:本件)?(?:犯罪)?事實(?:概要)?[：:]")
_COURT_HEAD_RE = re.compile(r"論罪|科刑|量刑|審酌|量處|核被告|係犯|沒收|追徵|緩刑|新舊法|累犯|減輕|競合|罪數|免刑|無罪|不受理|"
                            r"免訴|易科|易服|定應執行")
_EVIDENCE_RE = re.compile(r"證據|為證|在卷可(?:稽|按|參|佐|憑)|有.{0,30}可(?:稽|參|憑|佐)|供述|證述|證稱|指訴|自白|坦承|"
                          r"鑑定|監視器|筆錄|照片|紀錄表|明細|辯稱|所辯")

HEADINGS = {"主文": "verdict", "犯罪事實": "facts", "事實": "facts", "理由": "reasons", "事實及理由": "reasons",
            "犯罪事實及理由": "reasons", "事實及理由要領": "reasons", "證據並所犯法條": "reasons",
            "證據及所犯法條": "reasons", "犯罪事實及證據": "reasons", "證據": "reasons"}
PREFORMATTED = ("laws", "table", "info", "other")    # 保留原本的換行（法條、表格、當事人列表）


def judgment_id(url: Optional[str]) -> Optional[str]:
    parsed = urlparse(url or "")
    if parsed.hostname != "judgment.judicial.gov.tw":
        return None
    ids = parse_qs(parsed.query).get("id", [])
    return ids[0] if len(ids) == 1 and ids[0] else None


def _width(line: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in line.rstrip())


def clean(line: str) -> str:
    return _SPACE_RE.sub("", line.strip())


def _blocks(full_text: str) -> List[Dict]:
    """依標題行把全文切成區塊：{"kind", "part", "lines"}。kind 是 HEADINGS 的值或 info／laws／table／other。"""
    blocks: List[Dict] = []
    kind, part, in_meta = "info", None, False

    def start(k, heading=None):
        blocks.append({"kind": k, "part": part, "lines": [heading] if heading else [], "wrap": [False] if heading else []})

    start("info")
    for raw in (full_text or "").splitlines():
        line = clean(raw)
        b = blocks[-1]
        if line and b["lines"] and _CLOSE_RE.match(line):   # 「罰金\n。」：標點被折到下一行
            b["wrap"][-1] = True
        if not line:
            continue
        if in_meta or _META_RE.match(line):
            in_meta = not line.endswith("]")
            continue
        key = re.sub(r"\s", "", line).rstrip("：:")
        if key in HEADINGS:
            kind = HEADINGS[key]; start(kind)
        elif (key.startswith("附錄") and "法條" in key) or (kind == "other" and len(key) <= 12 and key.endswith(("法條", "法條全文"))):
            kind = "laws"; start(kind, line)
        elif _TABLE_RE.match(key):
            kind = "table"; start(kind, line)
        elif _ATTACHMENT_RE.match(key):
            part = "附件"; kind = "info"; start(kind, line)
        elif _DATE_RE.match(key) and kind in ("verdict", "facts", "reasons"):
            kind = "other"; start(kind, line)
        else:
            if part == "附件" and kind == "info" and _ATTACHMENT_TITLE_RE.search(key) and len(key) <= 30:
                part = "附件：" + _ATTACHMENT_TITLE_RE.search(key).group(1)
                blocks[-1]["part"] = part
            blocks[-1]["lines"].append(line)
            blocks[-1]["wrap"].append(_WRAP_MIN <= _width(raw) <= _WRAP_MAX and not line.endswith(("。", "：", ":", "號")))
    return [b for b in blocks if b["lines"]]


def _unwrap(b: Dict) -> str:
    """保留原本的分行（法條各項、署名），但把固定寬度造成的折行接回去。"""
    out = ""
    for i, line in enumerate(b["lines"]):
        out += line
        if i < len(b["lines"]) - 1:
            out += "" if b["wrap"][i] else "\n"
    return out


def _paragraphs(text: str, max_len: int = 600) -> List[str]:
    """依段落編號切開；沒有編號的長段落，在句號處切成不超過 max_len 字的段。"""
    parts, carry = [], ""
    for p in (p for p in _HEAD_SPLIT.split(text or "") if p.strip()):
        if len(p.strip()) <= 8:          # 只有編號的短段（「六、經查：」）併到下一段
            carry += p
        else:
            parts.append(carry + p); carry = ""
    if carry:                            # 最後的短段（「本件公訴不受理。」）不能丟
        if parts:
            parts[-1] += carry
        else:
            parts.append(carry)
    out = []
    for p in parts:
        while len(p) > max_len:
            # 先找句號，沒有再找分號、逗號，避免切在詞中間（「、林文豪」「頁）在卷可稽」）
            cut = next((c + 1 for mark in "。；，" if (c := p.rfind(mark, 0, max_len)) > max_len // 3), max_len)
            out.append(p[:cut]); p = p[cut:]
        if p.strip():
            out.append(p)
    return out


def _classify(text: str, kind: str) -> str:
    """理由裡的段落再分成：證據、論罪科刑、法條、其他（上訴說明），規則依段落開頭的字。"""
    if kind != "reasons":
        return kind
    head = text[:40]
    if _LAWS_PARA_RE.search(head) or _LAWS_BY_CPC_RE.match(text):
        return "laws"
    if _OTHER_PARA_RE.search(head):
        return "other"
    if _FACTS_PARA_RE.search(head):
        return "facts"
    if _COURT_HEAD_RE.search(head):
        return "court"
    return "evidence" if _EVIDENCE_RE.search(text[:120]) else "court"


def listed_names(text: str) -> set:
    """稱謂後面用「、」「及」列舉的名字；已遮過的（邵○霈、Ａ女）跳過但繼續往下找。"""
    found = set()
    for start in _LIST_START_RE.finditer(text):
        pos = start.end()
        while (item := _LIST_ITEM_RE.match(text, pos)):
            name = item.group(1)
            if "○" not in name and "【" not in name and not re.fullmatch(r"[Ａ-ＺA-Z][女男]", name):
                found.add(name)
            pos = item.end()
            # 卷頁或另案處分的括註不會結束人名清單。
            if note := _LIST_NOTE_RE.match(text, pos):
                pos = note.end()
            if pos < len(text) and text[pos] in "、及與和":
                pos += 1
            else:
                break
    return found


def masker(blocks: List[Dict], defendants: Iterable[str]) -> Callable[[str], str]:
    """被告換成「被告」；有稱謂及列舉的人名換成【關係人】，全文每一處都換。
    判決原文每行固定字數換行，名字可能被換行切開（陳小\n華），比對時允許名字中間有換行。
    沒有稱謂的人名（「被告與王大明互毆」）找不到，這是規則的限制。"""
    names = {n for n in defendants if n and len(n) >= 2}
    # 不把不同區塊的末尾與開頭拼成姓名；區塊內則接回固定寬度換行。
    joined = "\n".join("".join(b["lines"]) for b in blocks)
    names.update(re.findall(r"被告" + _NOT_NAME + r"(" + _NAME + r")", joined))
    others = (set(_GUIDE_ROLE_RE.findall(joined)) | set(_OWNER_NAME_RE.findall(joined)) | listed_names(joined)
              | set(third_party_names(joined))) - names
    replace = [(n, "被告") for n in names] + [(n, "【關係人】") for n in others]
    replace.sort(key=lambda x: len(x[0]), reverse=True)
    patterns = [(re.compile("\n?".join(map(re.escape, n))), r) for n, r in replace]

    def apply(text: str) -> str:
        for pattern, repl in patterns:
            text = pattern.sub(repl, text)
        return re.sub(r"被告(?:被告)+", "被告", mask(text)[0])
    return apply


def segment(full_text: str, defendants: Iterable[str] = ()) -> List[Dict]:
    """全文 → 段落清單 [{function, label, text, pre, part}]，順序和原文相同。
    先遮整個區塊再切段落，名字才不會剛好被切在兩段之間而漏遮。"""
    blocks = _blocks(full_text)
    hide = masker(blocks, defendants)
    out = []
    for b in blocks:
        pre = b["kind"] in PREFORMATTED
        joined = hide(("\n".join(b["lines"]) if b["kind"] == "table" else _unwrap(b)) if pre else "".join(b["lines"]))
        top = prev = None
        for t in ([joined] if pre else _paragraphs(joined, max_len=600)):
            fn = _classify(t, b["kind"])
            if b["kind"] == "reasons":
                # 同一個大標（一、犯罪事實）底下的小項與被切開的長段，沿用大標的標示
                if _TOP_RE.match(t):
                    top = fn
                elif not _SUB_RE.match(t) and prev:
                    fn = prev
                elif top == "facts" and fn not in ("laws", "other"):
                    fn = top
                elif top == "evidence" and fn not in ("laws", "other") and not _COURT_HEAD_RE.search(t[:40]):
                    fn = top
                prev = fn
            out.append({"function": fn, "label": FUNCTIONS[fn], "text": t, "pre": pre, "part": b["part"]})
    return out


def judgment_guide(row) -> Dict:
    return {"source": "judgment", "judgment_date": row["judgment_date"] or "",
            "paragraphs": segment(row["full_text"], party_names(row["defendant"]))}


def dataset_rows(path: Path):
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            files = [name for name in archive.namelist() if name.endswith(".jsonl")]
            if len(files) != 1:
                raise ValueError("壓縮檔必須只有一份 JSONL 資料集")
            with archive.open(files[0]) as stream:
                for line in stream:
                    yield json.loads(line)
    else:
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                yield json.loads(line)


def dataset_guide(row) -> Dict:
    """資料集只有犯罪事實（罪名、法條已遮成「××」），沒有主文與理由。"""
    meta = row["meta"]
    fact = masked(row.get("fact") or "", meta.get("criminals") or [])
    return {"source": "dataset", "judgment_date": meta.get("judgment_date") or "",
            "paragraphs": [{"function": "facts", "label": FUNCTIONS["facts"], "text": t, "pre": False, "part": "資料集節錄"}
                           for t in _paragraphs(fact, max_len=600)]}


def source_databases(db):
    paths = [db] if isinstance(db, Path) else list(db)
    sources = []
    for path in paths:
        matches = sorted(path.glob("刑事判決_全國地院_*.db")) if path.is_dir() else [path]
        if not matches:
            raise ValueError(f"找不到全國刑事原文庫：{path}")
        for match in matches:
            if not match.is_file():
                raise FileNotFoundError(match)
            resolved = match.resolve()
            if resolved not in sources:
                sources.append(resolved)
    if not sources:
        raise ValueError("請提供至少一個原文資料庫")
    return sources


def build(db, cases: Path, data: Optional[Path] = None, require_full: bool = False) -> Dict:
    sources = source_databases(db)
    if require_full and data:
        raise ValueError("完整原文模式不能使用 CAIL fact 備援")
    with closing(sqlite3.connect(f"file:{cases}?mode=rw", uri=True)) as target:
        urls: Dict[str, List[int]] = {}
        for case_id, url in target.execute("SELECT id, url FROM cases"):
            key = judgment_id(url)
            if key:
                urls.setdefault(key, []).append(case_id)
        found, duplicates = {}, set()
        for path in sources:
            with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as source:
                source.row_factory = sqlite3.Row
                # 先比對輕量欄位，只讀檢索樣本的全文，避免把全國原文全部載入。
                rows = []
                for row in source.execute("SELECT rowid AS rid, source_url FROM judgments WHERE case_number LIKE '%刑%'"):
                    if judgment_id(row["source_url"]) in urls:
                        rows.append(row["rid"])
                for start in range(0, len(rows), 500):
                    batch = rows[start:start + 500]
                    marks = ",".join("?" for _ in batch)
                    query = ("SELECT full_text, judgment_date, defendant, source_url FROM judgments "
                             f"WHERE rowid IN ({marks})")
                    for row in source.execute(query, batch):
                        key = judgment_id(row["source_url"])
                        if not (row["full_text"] or "").strip():
                            continue
                        if key in found:
                            duplicates.add(key)
                        else:
                            guide = judgment_guide(row)
                            if guide["paragraphs"]:
                                found[key] = guide
        if data:
            from_dataset = {}
            for row in dataset_rows(data):
                key = judgment_id(row["meta"].get("source_url"))
                if key not in urls or key in found or key in duplicates:
                    continue
                if key in from_dataset:
                    duplicates.add(key)
                else:
                    from_dataset[key] = dataset_guide(row)
            found.update(from_dataset)
        total = target.execute("SELECT count(*) FROM cases").fetchone()[0]
        full = sum(len(urls[key]) for key, guide in found.items()
                   if key not in duplicates and guide["source"] == "judgment")
        if require_full and full != total:
            raise ValueError(f"原文只對上 {full:,}/{total:,} 件，缺少或有歧義 {total - full:,} 件；保留既有導讀資料")
        with target:
            target.execute("DROP TABLE IF EXISTS guides")
            target.execute("CREATE TABLE guides (case_id INTEGER PRIMARY KEY, source TEXT NOT NULL, "
                           "judgment_date TEXT NOT NULL, paragraphs TEXT NOT NULL)")
            target.executemany("INSERT INTO guides VALUES (?, ?, ?, ?)", (
                (case_id, g["source"], g["judgment_date"], json.dumps(g["paragraphs"], ensure_ascii=False))
                for key, g in found.items() if key not in duplicates for case_id in urls[key]))
            counts = dict(target.execute("SELECT source, count(*) FROM guides GROUP BY source").fetchall())
        return {"total": target.execute("SELECT count(*) FROM cases").fetchone()[0],
                "from_judgment": counts.get("judgment", 0), "from_dataset": counts.get("dataset", 0),
                "ambiguous_urls": len(duplicates)}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", required=True, type=Path, nargs="+", help="原文資料庫，可提供多個檔案或全國年度資料庫目錄")
    parser.add_argument("--cases", required=True, type=Path)
    parser.add_argument("--data", type=Path, help="同一批樣本的 CAIL JSONL 或 ZIP：judgments.db 沒有的案件改用資料集的犯罪事實")
    parser.add_argument("--require-full", action="store_true", help="全部檢索樣本都對上原文才更新，不允許 fact 備援")
    args = parser.parse_args()
    print(json.dumps(build(args.db, args.cases, args.data, args.require_full), ensure_ascii=False))


if __name__ == "__main__":
    main()
