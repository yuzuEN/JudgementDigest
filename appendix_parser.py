"""附表解析原型：從裁判書 HTML 的附表 <table> 讀出「每個被告、每個罪、每個宣告刑」。

只處理表頭含「宣告刑」或「主文」欄的最內層表格；輸出一列一個宣告刑。
"""

import re
from typing import Dict, List, Optional

from bs4 import BeautifulSoup

from structure_tasks import NUM, SINGLE_RE, chinese_number

_HEADER_HINT = re.compile(r"編號|宣告刑|主文|罪名")
_SENT_HEADER = re.compile(r"宣告刑|主文|判處|罪刑")
_CHARGE_HEADER = re.compile(r"罪名")
_DEFENDANT_HEADER = re.compile(r"被告|姓名")
# 貪婪：遇到罪名本身含「犯罪」兩字（如「…犯罪組織罪」）時，非貪婪會在第一個「罪」
# 字就停下、漏掉後半段；貪婪會找到子句內最後一個「罪」，含「、」分隔的多罪名也保留。
_CHARGE_IN_CELL = re.compile(r"犯([^，。；]{2,60}罪)")
_FINE = re.compile(rf"併科罰金(?:新臺幣)?([{NUM},]+)元")
_MAIN_FINE = re.compile(rf"罰金(?:新臺幣)?([{NUM},]+)元")
_MARK = re.compile(
    r"^(?:[⑴-⒛①-⑳㈠-㈩]|[\(（][\d一二三四五六七八九十]+[\)）]|[\dIVXivx]{1,3}[.．、]|"
    r"[一二三四五六七八九十百]+[、.．])+"
)
# 法條前綴：法規名稱至少 1 字，涵蓋「刑法」「民法」這類雙字全名（「法」本身佔 1 字）。
_LAW_PREFIX = re.compile(
    rf"^(?P<law>[^，、；。]{{1,25}}?(?:法|條例)第[{NUM}]+條(?:之[{NUM}]+)?(?:第[{NUM}]+項)?"
    rf"(?:第[{NUM}]+款)?(?:前段|後段|但書)?)之?(?P<charge>.+罪)$"
)


def _clean(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _is_data_row(row: List[str]) -> bool:
    """資料列：編號欄以數字開頭，或任一儲存格含「處…刑」句型（有些表第一欄不是編號）。"""
    if row and re.match(r"[\d一二三四五六七八九十百]", row[0]):
        return True
    return any(SINGLE_RE.search(c) for c in row)


def table_grid(table) -> List[List[str]]:
    """把 <table> 展開成矩陣，處理 rowspan / colspan；只取這張表自己的列。"""
    rows = [tr for tr in table.find_all("tr") if tr.find_parent("table") is table]
    grid: List[List[str]] = []
    pending: Dict[int, List] = {}  # 欄位 -> [剩餘列數, 文字]
    for tr in rows:
        cells = tr.find_all(["td", "th"], recursive=False)
        row: List[str] = []
        col = ci = 0
        while ci < len(cells) or col in pending:
            if col in pending:
                remaining, txt = pending[col]
                row.append(txt)
                if remaining <= 1:
                    del pending[col]
                else:
                    pending[col][0] = remaining - 1
                col += 1
                continue
            cell = cells[ci]
            ci += 1
            txt = _clean(cell.get_text(" ", strip=True))
            rowspan = int(cell.get("rowspan") or 1)
            colspan = int(cell.get("colspan") or 1)
            for _ in range(colspan):
                row.append(txt)
                if rowspan > 1:
                    pending[col] = [rowspan - 1, txt]
                col += 1
        grid.append(row)
    return grid


def _months(sentence: str) -> Optional[int]:
    if not sentence.startswith("有期徒刑"):
        return None
    year = re.search(rf"([{NUM}]+)年", sentence)
    month = re.search(rf"([{NUM}]+)月", sentence)
    return (chinese_number(year.group(1)) * 12 if year else 0) + (
        chinese_number(month.group(1)) if month else 0)


def _amount(text: str) -> Optional[int]:
    return chinese_number(text.replace(",", "")) if text else None


def _days(sentence: str) -> Optional[int]:
    m = re.fullmatch(rf"拘役([{NUM}]+)日", sentence)
    return chinese_number(m.group(1)) if m else None


def _split_defendant(before: str, names) -> tuple:
    """從「被告…犯」之前的文字切出被告名。回傳 (defendant, charge_from_rest_or_None)。"""
    cm = _CHARGE_IN_CELL.search(before) if "犯" in before else None
    if cm:
        head = before[:before.index(cm.group(0))]
        head = _MARK.sub("", re.sub(r"(?:共同|幫助|教唆)$", "", head)).strip()
        head = re.sub(r"^被告", "", head)
        ascii_name = bool(re.fullmatch(r"[A-Za-z .\-·,]+", head))
        who = head if 0 < len(head) <= (40 if ascii_name else 12) else ""
        return who, cm.group(1)
    # 沒有「犯」字（例如「許元鴻販賣第二級毒品，處…」）：用已知被告名或遮蔽名（○○）切出被告
    rest = _MARK.sub("", before).strip()
    rest = re.sub(r"^被告", "", rest)
    who = ""
    for nm in sorted(names, key=len, reverse=True):
        if nm and rest.startswith(nm):
            who, rest = nm, rest[len(nm):]
            break
    else:
        nm = re.match(r"^(?:[A-Za-z][A-Za-z .\-·]*[（(][^）)]+[）)]|[A-Za-z][A-Za-z .\-·]{3,}|[一-鿿]○+)", rest)
        if nm:
            who, rest = nm.group(0), rest[nm.end():]
    rest = re.sub(r"^(?:共同|共犯|幫助|教唆)", "", rest)
    rest = re.sub(r"[，,].*$", "", rest).strip()
    return who, (rest if who and rest else None)


def parse_sentence_cell(text: str, charge_hint: str = "", names=(), column_defendant: str = "") -> List[Dict]:
    """把一個「罪名及宣告刑／主文」儲存格拆成多個 (被告, 罪名, 宣告刑)。

    同一子句內可能有多個被告各自的「處…刑」（用逗號而非句號分隔，例如
    「甲○○犯…罪，處有期徒刑陸月，乙○○犯…罪，處有期徒刑肆月」），逐一
    掃描該子句內每個宣告刑，而不是只取第一個，否則後面被告的刑期會整段消失。
    """
    names = [re.sub(r"\s+", "", n) for n in names if n]
    out = []
    for clause in re.split(r"[。；]", text):
        matches = list(SINGLE_RE.finditer(clause))
        if not matches:
            continue
        for idx, m in enumerate(matches):
            sentence = m.group(1)
            seg_start = matches[idx - 1].end() if idx > 0 else 0
            before = clause[seg_start:m.start()].lstrip("，,")
            who, rest_charge = _split_defendant(before, names)
            charge = rest_charge or charge_hint
            if not who and column_defendant and len(matches) == 1:
                # 表格本身有「被告」欄且整格只有一個宣告刑時，用該欄位當備援
                who = column_defendant
            seg_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(clause)
            tail = clause[m.end():seg_end]
            if sentence.startswith("罰金"):          # 主刑罰金：金額就在宣告刑本身
                fm = _MAIN_FINE.match(sentence)
                fine, fine_type = (_amount(fm.group(1)) if fm else None), "主刑"
            else:
                fm = _FINE.search(tail)
                fine, fine_type = (_amount(fm.group(1)) if fm else None), ("併科" if fm else "")
            law = ""
            lm = _LAW_PREFIX.match(charge or "")
            if lm:
                law, charge = lm.group("law"), lm.group("charge")
            out.append({
                "raw": clause[seg_start:seg_end],
                "defendant": who, "law": law, "charge": charge, "sentence": sentence,
                "months": _months(sentence), "days": _days(sentence),
                "fine": fine, "fine_type": fine_type,
            })
    return out


def extract_appendix_offenses(html: str, names=()) -> List[Dict]:
    soup = BeautifulSoup(html, "lxml")
    results: List[Dict] = []
    for ti, table in enumerate(soup.find_all("table")):
        if table.find("table"):          # 外層排版表格，略過
            continue
        grid = table_grid(table)
        hdr_i = next((i for i, r in enumerate(grid[:3]) if any(_HEADER_HINT.search(c) for c in r)), None)
        if hdr_i is None:
            continue
        # 表頭可能佔多列（例如第二列才有「罪名與宣告刑」）：往下併入到第一個資料列（編號欄以數字開頭）為止
        h_end = hdr_i + 1
        while h_end < min(len(grid), hdr_i + 3) and not _is_data_row(grid[h_end]):
            h_end += 1
        width = max(len(grid[i]) for i in range(hdr_i, h_end))
        header = [" ".join(dict.fromkeys(grid[i][j] for i in range(hdr_i, h_end) if j < len(grid[i])))
                  for j in range(width)]
        sent_cols = [j for j, h in enumerate(header) if _SENT_HEADER.search(h)]
        if not sent_cols:
            continue
        charge_cols = [j for j, h in enumerate(header) if _CHARGE_HEADER.search(h) and not _SENT_HEADER.search(h)]
        defendant_cols = [j for j, h in enumerate(header)
                           if _DEFENDANT_HEADER.search(h) and not _SENT_HEADER.search(h) and not _CHARGE_HEADER.search(h)]
        for r in grid[h_end:]:
            if len(r) < len(header):
                continue
            hint = r[charge_cols[0]] if charge_cols else ""
            col_defendant = r[defendant_cols[0]] if defendant_cols else ""
            for j in sent_cols:
                for off in parse_sentence_cell(r[j], charge_hint=hint, names=names,
                                                column_defendant=col_defendant):
                    off.update(table=ti, no=r[0])
                    results.append(off)
    return results
