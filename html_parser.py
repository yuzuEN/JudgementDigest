"""
Part 2 — 裁判書 HTML 結構化解析器

司法院裁判書頁面 HTML 結構（實測）：
  div#jud.int-table          → 外層容器（含 metadata 表格 + 正文）
    div.col-th               → 欄位標籤（裁判字號、法院、日期…）
    div.col-td               → 欄位值
    div.col-td.jud_content
      td.tab_content
        div.htmlcontent      → 正文主體
          div.he-h1          → 法院名稱（大標）
          div[id]            → 一般段落（含當事人、程序說明）
          div.notEdit        → 段落標題，如「主　文」「理　由」
          div.he-h3.notEdit  → 同上（另一種格式）
          div[id]            → 該標題下的內容段落
          abbr.termhover     → 法律名詞（行內，不單獨處理）
  div#JudrelaLaw             → 相關法條面板

使用方式:
    python html_parser.py                   # 批次處理所有未解析紀錄
    python html_parser.py --file <path>     # 解析單一 HTML 檔案
"""

import sys, io
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import sqlite3
import os
import re
import argparse
import logging
from typing import Dict, List, Tuple

from bs4 import BeautifulSoup, Tag, NavigableString

# ─── 設定 ────────────────────────────────────────────────────────────────────
DB_PATH  = "judgments.db"
HTML_DIR = "html_cache"
LOG_FILE = "parser.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# 全形空格 U+3000 + 一般空格
_SPACES = re.compile(r"[　  \t]+")

# 從「裁判字號」全文解析法院名稱
_COURT_RE = re.compile(
    r'^(.*?(?:憲法法庭|少年及家事法院|地方法院|高等法院|最高行政法院|最高法院|高等行政法院'
    r'|行政法院|智慧財產及商業法院|智慧財產法院|海事法院)'
    r'(?:\s+\S+分院|\s+地方庭)?)'
)

# 當事人角色 → DB 欄位（含各種縮排空格寫法）
# 長字串放前面，避免「被告」先匹配到「再審被告」的「被告」部分
_PARTY_ROLES: List[Tuple[str, str]] = [
    # 長字串優先，避免短字串（如「被告」）搶先匹配「再審被告」等
    ("反聲請聲請人", "plaintiff"),   # 反聲請程序中提出聲請的一方
    ("反聲請相對人", "defendant"),   # 反聲請程序中被聲請的一方
    ("再審聲請人",   "appellant"),
    ("再審原告",     "plaintiff"),   # 再審之訴的原告方
    ("附帶被上訴人", "appellee"),    # 附帶上訴程序的被上訴人
    ("附帶上訴人",   "appellant"),   # 附帶上訴程序的上訴人
    ("被上訴人",     "appellee"),
    ("再審被告",     "defendant"),
    ("反反請求原告", "plaintiff"),   # 反訴之反訴的原告方（對反請求再提反請求）
    ("反反請求被告", "defendant"),   # 反訴之反訴的被告方
    ("反請求原告",   "plaintiff"),   # 提出反請求的一方（非訟程序）
    ("反請求被告",   "defendant"),   # 反請求的相對方
    ("反訴原告",     "plaintiff"),   # 提出反訴的一方（在反訴中作為原告）
    ("反訴被告",     "defendant"),   # 被反訴的一方（在反訴中作為被告）
    ("主參加原告",   "plaintiff"),   # 主參加訴訟的原告方
    ("主參加被告",   "defendant"),   # 主參加訴訟的被告方
    ("追加原告",     "plaintiff"),   # 訴之追加程序中新增的原告方
    ("追加被告",     "defendant"),   # 訴之追加程序中新增的被告方
    ("受裁定人",     "plaintiff"),   # 非訟或裁定事件的受裁定方（通常兼具原告地位）
    ("公訴人",       "plaintiff"),
    ("自訴人",       "plaintiff"),
    ("再抗告人",     "appellant"),   # 對抗告裁定再為抗告者
    ("原告",         "plaintiff"),
    ("聲請人",       "plaintiff"),   # 聲請更生、聲請假扣押等非訟事件
    ("申請人",       "plaintiff"),   # 行政程序或某些非訟事件的申請方
    ("告訴人",       "plaintiff"),
    ("債權人",       "plaintiff"),
    ("被告",         "defendant"),
    ("受刑人",       "defendant"),
    ("債務人",       "defendant"),
    ("上訴人",       "appellant"),
    ("抗告人",       "appellant"),
    ("異議人",       "appellant"),   # 對裁定聲明異議，性質類似抗告人
    ("相對人",       "defendant"),   # 非訟事件相對方，對應「被告／相對人」欄
]

# 從 _PARTY_ROLES 衍生：用於前言斷行合併
_ROLE_CHARS: frozenset = frozenset(
    c for role, _ in _PARTY_ROLES for c in re.sub(r"\s", "", role)
) | frozenset("即")

_ROLE_SET: frozenset = frozenset(
    re.sub(r"\s*", "", role) for role, _ in _PARTY_ROLES
)

# 停止擷取當事人姓名的標記（後面是地址或其他角色）
_NAME_STOP_RE = re.compile(
    r"(?:住|設|居|籍|（|\(|訴訟\s*代理|辯護|法定\s*代理|複\s*代理|輔佐|律師)"
)

# 代理人/辯護人行：匹配角色前綴並捕捉後方姓名（Group 1）
_AGENT_RE = re.compile(
    r"^(?:訴訟\s*代理\s*人|法定\s*代理\s*人|複\s*代理\s*人|特別\s*代理\s*人"
    r"|送達\s*代收\s*人"          # 兼任送達代收人時另起一行的格式
    r"|選任\s*辯護\s*人|指定\s*辯護\s*人|辯護\s*人|代\s*理\s*人)\s*(.+)"
)
# 其他輔助角色（輔佐人），不提取姓名，直接跳過
_AUX_SKIP_RE = re.compile(r"^(?:輔佐)")
# 地址行識別：以數字或英文開頭
_ADDR_ONLY_RE = re.compile(r"^[\d\sA-Za-z]")
# 前言頁尾標記：出現即停止擷取當事人（裁定類文件無段落標題時前言會包含頁尾）
_PREAMBLE_STOP_RE = re.compile(
    r"中\s*華\s*民\s*國\s*\d{2,3}\s*年"
    r"|以上正本證明"
    r"|書記官\s*\S"
    r"|如不服本(?:判決|裁定)"
)
# 驗證 court_hint / date_hint 來自舊版 crawl_records 時是否有效
_COURT_VALID_RE = re.compile(r"法院")
_DATE_HINT_RE   = re.compile(r"\d{2,3}[./年]\d{1,2}")


# ─── 資料庫 ───────────────────────────────────────────────────────────────────
def init_db() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS crawl_records (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            case_number   TEXT    UNIQUE,
            court         TEXT,
            case_title    TEXT,
            judgment_date TEXT,
            source_url    TEXT,
            html_file     TEXT,
            keyword       TEXT,
            crawled_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            parsed        INTEGER   DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS judgments (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            crawl_id          INTEGER REFERENCES crawl_records(id),
            case_number       TEXT,
            court             TEXT,
            judgment_date     TEXT,
            case_type         TEXT,
            judgment_type     TEXT,
            source_url        TEXT,
            verdict           TEXT,
            facts             TEXT,
            facts_and_reasons TEXT,
            criminal_facts    TEXT,
            reasons           TEXT,
            conclusion        TEXT,
            applicable_laws   TEXT,
            judges            TEXT,
            clerk             TEXT,
            plaintiff         TEXT,
            plaintiff_agent   TEXT,
            defendant         TEXT,
            defendant_agent   TEXT,
            appellant         TEXT,
            appellant_agent   TEXT,
            appellee          TEXT,
            appellee_agent    TEXT,
            party_roles       TEXT,
            other_parties     TEXT,
            full_text         TEXT,
            keyword           TEXT,
            parsed_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(crawl_id)
        );
    """)
    # 對舊版資料庫補齊新增欄位
    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(judgments)")}
    for col, typedef in (
        ("source_url",        "TEXT DEFAULT ''"),
        ("facts_and_reasons", "TEXT DEFAULT ''"),
        ("plaintiff_agent",   "TEXT DEFAULT ''"),
        ("defendant_agent",   "TEXT DEFAULT ''"),
        ("appellant_agent",   "TEXT DEFAULT ''"),
        ("appellee_agent",    "TEXT DEFAULT ''"),
        ("party_roles",       "TEXT DEFAULT ''"),
        ("clerk",             "TEXT DEFAULT ''"),
        ("judgment_type",     "TEXT DEFAULT ''"),
    ):
        if col not in existing_cols:
            conn.execute(f"ALTER TABLE judgments ADD COLUMN {col} {typedef}")
    conn.commit()
    conn.close()


# ─── 輔助 ─────────────────────────────────────────────────────────────────────
def _t(elem) -> str:
    """取得元素文字，折疊多餘空白。"""
    if elem is None:
        return ""
    raw = elem.get_text(" ", strip=True)
    return _SPACES.sub(" ", raw).strip()


def _normalize_section_title(text: str) -> str:
    """移除全形與一般空格，取得純標題文字。例：'主　文' → '主文'"""
    return _SPACES.sub("", text.strip())


def _cap(s: str, n: int = 30000) -> str:
    return s[:n] + "…(截斷)" if len(s) > n else s


# 頁尾典型起始詞（出現即截斷段落內容）
_FOOTER_RE = re.compile(
    r"(?:中\s*華\s*民\s*國\s*\d{2,3}\s*年"
    r"|以上正本證明"
    r"|如不服本(?:判決|裁定)"
    r"|本件判決確定)"
)
# 前言收尾句：「上列...事件，判決如下：」—— 標準文件有此句且後接段落標題
# 無此結尾的長句代表整篇無標題，本身即為裁定主文
_PREAMBLE_INTRO_RE = re.compile(r"(?:如下|以下)\s*[：:]?\s*$")

def _strip_footer(text: str) -> str:
    """移除裁判書結尾的法院日期、書記官等頁尾資訊。"""
    m = _FOOTER_RE.search(text)
    return text[:m.start()].strip() if m else text


# ─── Step 1：從結構化 metadata 表格取得基本欄位 ────────────────────────────────
def _extract_metadata(soup: BeautifulSoup) -> Dict[str, str]:
    meta: Dict[str, str] = {
        "case_number": "", "court": "", "judgment_date": "",
        "case_type": "", "judges": "",
    }

    jud = soup.find("div", id="jud")
    if not jud:
        return meta

    # col-th 緊接著 col-td，逐對讀取
    for th in jud.find_all("div", class_="col-th"):
        label = _t(th).rstrip("：:")
        td = th.find_next_sibling("div", class_="col-td")
        if not td:
            continue
        value = _t(td)

        if "裁判字號" in label:
            meta["case_number"] = value
            # 裁判字號全文格式：「<法院> <案號> <裁判種類>」
            # 從中解析法院名稱（無獨立的裁判法院欄位）
            cm = _COURT_RE.match(value)
            if cm:
                meta["court"] = cm.group(1).strip()
        elif "裁判法院" in label:
            meta["court"] = value          # 若有獨立欄位則優先使用
        elif "裁判日期" in label:
            meta["judgment_date"] = value
        elif "案件類型" in label or "裁判案由" in label:
            meta["case_type"] = value

    return meta


# ─── Step 2：找到正文容器 ─────────────────────────────────────────────────────
def _find_content_container(soup: BeautifulSoup):
    """回傳包含所有段落 div 的容器元素，優先用 .htmlcontent。永不回傳 None。"""
    for sel in (
        {"class": "htmlcontent"},
        {"class": "tab_content"},
        {"class": "jud_content"},
    ):
        elem = soup.find(True, sel)
        if elem and len(elem.get_text()) > 100:
            return elem
    # soup.body 可能為 None（頁面未完整載入），回傳空的 Tag 讓呼叫端優雅降級
    return soup.body or BeautifulSoup("<div></div>", "lxml").div


# ─── Step 3a：text-pre 格式（憲法法庭等）的段落切割 ──────────────────────────
_TP_HEADING_RE = re.compile(
    r'^(?:主文|理由|事實及理由|事實|犯罪事實|結論|據上論斷)$'
)


def _extract_sections_text_pre(text_pre_elem) -> Tuple[Dict[str, str], str, List[str]]:
    """
    解析 text-pre 格式（憲法法庭等）：
    正文為一個整塊的預格式文字，`abbr` 元素的文字視為行內文字，
    行號以原始文字節點中的 \\n 還原。
    """
    # 保留 \\n 的文字提取：直接連接子節點文字（abbr 視為行內）
    parts: List[str] = []
    for node in text_pre_elem.children:
        if isinstance(node, NavigableString):
            parts.append(str(node))
        elif isinstance(node, Tag):
            parts.append(node.get_text())  # abbr 等行內標籤
    raw = "".join(parts)

    lines = [_SPACES.sub(" ", ln).strip() for ln in raw.split("\n")]
    lines = [ln for ln in lines if ln]

    sections: Dict[str, str] = {}
    preamble_lines: List[str] = []
    current_title: str = ""
    current_buf: List[str] = []
    in_preamble = True

    def flush() -> None:
        nonlocal current_title, current_buf
        if current_title and current_buf:
            content = "\n".join(current_buf).strip()
            if current_title in sections:
                sections[current_title] += "\n" + content
            else:
                sections[current_title] = content
        current_buf = []

    for ln in lines:
        norm = _SPACES.sub("", ln)

        if _TP_HEADING_RE.match(norm):
            flush()
            in_preamble = False
            current_title = norm
            continue

        if in_preamble:
            if _PREAMBLE_STOP_RE.search(ln):
                break
            preamble_lines.append(ln)
        else:
            if _PREAMBLE_STOP_RE.search(ln):
                flush()
                break
            current_buf.append(ln)

    flush()

    # 無標題文件（body_buf 全在 preamble）→ 從前言結尾行後截取主文
    if not sections and preamble_lines:
        for i, ln in enumerate(preamble_lines):
            if _PREAMBLE_INTRO_RE.search(ln):
                body = _strip_footer("\n".join(preamble_lines[i + 1:]))
                if body:
                    sections["主文"] = body
                preamble_lines = preamble_lines[: i + 1]
                break

    for k in sections:
        sections[k] = _strip_footer(sections[k])

    return sections, "\n".join(lines), preamble_lines


# ─── Step 3：將正文容器依段落標題切割成 sections ──────────────────────────────
def _extract_sections(container) -> Tuple[Dict[str, str], str, List[str]]:
    """
    回傳:
      sections  — { 正規化標題: 段落文字 }
      full_text — 全文純文字
      preamble_lines — 第一個標題之前的每行文字（用於擷取當事人）
    """
    # text-pre 格式偵測（憲法法庭等）：htmlcontent 為空，正文在 div.text-pre
    if hasattr(container, "find"):
        text_pre = container.find("div", class_="text-pre")
        html_content_elem = container.find("div", class_="htmlcontent")
        if (text_pre and len(text_pre.get_text()) > 50
                and (not html_content_elem or len(html_content_elem.get_text()) < 50)):
            return _extract_sections_text_pre(text_pre)

    sections: Dict[str, str] = {}
    full_parts: List[str] = []
    preamble_lines: List[str] = []
    body_buf: List[str] = []     # 無標題裁定書的主文本體
    current_title: str = ""   # "" 代表 preamble（第一個標題前）
    current_buf: List[str] = []
    in_preamble = True
    after_preamble_intro = False  # True once "上列…如下：" closing line is seen

    def flush():
        nonlocal current_title, current_buf
        content = "\n".join(current_buf).strip()
        if current_title:
            # 同名段落後面覆蓋前面（通常後面更完整）
            if current_title in sections:
                sections[current_title] = sections[current_title] + "\n" + content
            else:
                sections[current_title] = content
        current_buf = []

    for child in container.children:
        if not isinstance(child, Tag):
            continue
        if child.name not in ("div", "p", "td"):
            continue

        classes = set(child.get("class") or [])
        text = _t(child)
        if not text:
            continue

        full_parts.append(text)

        is_heading = (
            "notEdit" in classes                              # 新舊格式都有
            and "he-h1" not in classes                        # 排除法院名稱大標
            and len(text) <= 20                               # 標題不應太長
            and re.search(r'[主文事實理由結論法條犯罪據上聲明陳述附]', text)
        )

        if is_heading:
            flush()
            in_preamble = False
            body_buf = []          # 遇到標題代表文件有結構，捨棄暫存的 body_buf
            current_title = _normalize_section_title(text)
        else:
            if in_preamble:
                # 「上列…事件，判決如下：」是前言收尾行（有結構的文件）
                # 「上列…事件，（裁定內容）。」不以「如下」結尾 → 無標題文件的主文本體
                is_preamble_closing = (
                    text.startswith("上列")
                    and bool(_PREAMBLE_INTRO_RE.search(text))
                )
                is_body_start = (
                    text.startswith("上列")
                    and not _PREAMBLE_INTRO_RE.search(text)
                )
                if is_preamble_closing:
                    # 記錄前言已結束，後續有編號段落的文件（補字裁定等）
                    # 其正文會在下一輪進入 body_buf
                    preamble_lines.append(text)
                    after_preamble_intro = True
                elif is_body_start or body_buf or after_preamble_intro:
                    body_buf.append(text)
                else:
                    preamble_lines.append(text)
            else:
                current_buf.append(text)

    flush()

    # 無標題裁定書：body_buf 中的內容即為主文，去掉頁尾後存入 sections["主文"]
    if body_buf and not sections:
        body_text = _strip_footer("\n".join(body_buf)).strip()
        if body_text:
            sections["主文"] = body_text

    # 每個段落都去掉頁尾
    for k in sections:
        sections[k] = _strip_footer(sections[k])
    full_text = "\n".join(full_parts)
    return sections, full_text, preamble_lines


def _is_valid_role_compound(s: str) -> bool:
    """True if s is a simple role or a 即-compound of valid roles (e.g. '上訴人即附帶被上訴人')."""
    if s in _ROLE_SET:
        return True
    parts = s.split("即")
    return len(parts) > 1 and all(p in _ROLE_SET for p in parts if p)


def _premerge_preamble(lines: List[str]) -> List[str]:
    """
    合併被 HTML 斷行的角色稱謂碎片行。
    例：["再", "抗告", "人  范源昌"] → ["再抗告人 范源昌"]
        ["上訴", "人即附", "帶被", "上訴人", "林玟杰"] → ["上訴人即附帶被上訴人 林玟杰"]
    判斷原則：≤8 字且所有字元均在角色字集內視為「碎片行」。
    """
    merged: List[str] = []
    pending: str = ""   # accumulated role-only chars (no spaces)

    for line in lines:
        no_space = _SPACES.sub("", line.strip())
        if not no_space:
            continue

        is_fragment = len(no_space) <= 8 and all(c in _ROLE_CHARS for c in no_space)

        if is_fragment:
            pending += no_space
            continue

        if pending:
            # Special case: "roleX即" + agent-role line
            # e.g. pending="聲請人即", line="原告訴訟代理人  孫治平律師"
            # → the person named is the roleX holder; emit "roleX <name>"
            if pending.endswith("即"):
                line_norm = _SPACES.sub(" ", line.strip())
                agent_m = re.search(r'(?:代\s*理\s*人|辯護\s*人)\s+(.+)', line_norm)
                if agent_m:
                    base_role = pending[:-1]   # strip trailing 即
                    merged.append(base_role + " " + agent_m.group(1).strip())
                    pending = ""
                    continue

            combined = pending + no_space
            # Walk forward while chars are in ROLE_CHARS
            i = 0
            while i < len(combined) and combined[i] in _ROLE_CHARS:
                i += 1
            role_part = combined[:i]
            name_part = combined[i:]

            if name_part and _is_valid_role_compound(role_part):
                merged.append(role_part + " " + name_part)
            else:
                # Could not form a valid compound; keep them separate
                merged.append(pending)
                merged.append(_SPACES.sub(" ", line.strip()))
            pending = ""
            continue

        merged.append(_SPACES.sub(" ", line.strip()))

    if pending:
        merged.append(pending)

    return merged


# ─── Step 4：從 preamble 行中擷取當事人及其訴訟代理人（狀態機）─────────────
def _extract_parties(preamble_lines: List[str]) -> Dict[str, str]:
    preamble_lines = _premerge_preamble(preamble_lines)
    _fields = list(dict.fromkeys(v for _, v in _PARTY_ROLES))  # 保序去重
    parties: Dict[str, List[str]] = {f: [] for f in _fields}
    agents:  Dict[str, List[str]] = {f: [] for f in _fields}   # 同角色的代理人/辯護人
    current_field: str = ""
    in_agent_context: bool = False   # True 表示上一行是代理人行，延續行應歸代理人

    # 用於 party_roles：記錄真實角色稱謂與姓名的對應（保序）
    # 格式：{"聲請人": ["邱彥豪"], "相對人": ["全日通電梯有限公司"]}
    roles_order: List[str] = []
    roles_names: Dict[str, List[str]] = {}
    current_actual_role: List[str] = [""]   # mutable，讓 _add_name 閉包可讀取

    def _add_name(field: str, raw: str, check_len: bool = True) -> None:
        stop = _NAME_STOP_RE.search(raw)
        name = raw[: stop.start()].strip() if stop else raw.strip()
        if not name or re.search(r"律師|辯護", name):
            return
        # Reject pure connector strings even when check_len=False
        if re.fullmatch(r"[即及與，,、；;。\s]+", name):
            return
        if check_len:
            core = re.sub(r"[（(][^）)]*[）)]", "", name).strip()
            if not (1 <= len(core) <= 20):
                return
        parties[field].append(name)
        # 同步記錄到真實角色清單
        role = current_actual_role[0]
        if role:
            if role not in roles_names:
                roles_order.append(role)
                roles_names[role] = []
            roles_names[role].append(name)

    def _add_agent(field: str, raw: str) -> None:
        """提取代理人/辯護人姓名（截斷到律師等標記前）並加入 agents 欄位。"""
        stop = _NAME_STOP_RE.search(raw)
        name = raw[: stop.start()].strip() if stop else raw.strip()
        # 過濾：連接詞（兼、及…）或空白後剩餘字元 < 2 的碎片
        if not name or len(re.sub(r"\s", "", name)) < 2:
            return
        if re.fullmatch(r"[兼及與、，,；;。\s]+", name):
            return
        agents[field].append(name)

    def _match_role(text: str):
        """回傳 (field, actual_role_label, remaining_text) 或 None。"""
        for role, field in _PARTY_ROLES:
            pat = r"\s*".join(re.escape(c) for c in role)
            # Standard: role + whitespace + name
            m = re.match(rf"^{pat}\s+(.+)", text)
            if m:
                return field, role, m.group(1).strip()
            # Compound inline: roleA即roleB [name]  e.g. "上訴人即附帶被上訴人 林玟杰"
            m2 = re.match(rf"^{pat}(即\S+)(?:\s+(.+))?$", text)
            if m2:
                ji_part  = m2.group(1)            # e.g. "即附帶被上訴人"
                remaining = (m2.group(2) or "").strip()
                return field, role + ji_part, remaining
            # Role alone (line ends here)
            if re.match(rf"^{pat}\s*$", text):
                return field, role, ""
        return None

    for line in preamble_lines:
        collapsed = _SPACES.sub(" ", line).strip()
        if not collapsed:
            continue

        # 0. 頁尾標記：停止處理（裁定類文件前言可能包含頁尾）
        if _PREAMBLE_STOP_RE.search(collapsed):
            break

        has_ji = collapsed.startswith("即")
        ji_stripped = re.sub(r"^即\s*", "", collapsed) if has_ji else collapsed

        # 1. 比對角色（含「即+角色」格式）
        result = _match_role(ji_stripped)
        if result:
            role_field, actual_role, raw = result
            if has_ji:
                # 「即被告 XXX」→ 名字歸入先前角色欄，並將稱謂更新為複合形式
                # 例：current="上訴人" + 即+"被告" → "上訴人即被告"
                target = current_field or role_field
                if current_actual_role[0]:
                    current_actual_role[0] = current_actual_role[0] + "即" + actual_role
                else:
                    current_actual_role[0] = actual_role
            else:
                current_field = role_field
                current_actual_role[0] = actual_role
                in_agent_context = False
                target = role_field
            if raw:
                _add_name(target, raw, check_len=False)
            continue

        # 2. 跳過組別標記（「上三人」、「上 三 人」、「上列」、「前列」、「共 同」等）
        if re.match(
            r"^(?:"
            r"[上前]\s*(?:[〇一二三四五六七八九十百千萬]+\s*人|列)"  # 上三人 / 前列
            r"|共\s*同"                                               # 共 同
            r")",
            collapsed,
        ):
            continue

        # 3. 代理人/辯護人行 → 提取姓名歸入 agents[current_field]
        agent_m = _AGENT_RE.match(collapsed)
        if agent_m:
            if current_field:
                _add_agent(current_field, agent_m.group(1))
            in_agent_context = True
            continue

        # 4. 其他輔助角色行（輔佐人等）→ 跳過
        if _AUX_SKIP_RE.match(collapsed):
            continue

        # 5. 跳過地址行（數字/英文開頭）
        if _ADDR_ONLY_RE.match(collapsed):
            continue

        # 6. 延續行：若為代理人上下文或含「律師」則歸代理人，否則歸當事人
        if current_field:
            # 前言結尾句（「…如下：」「…如下」）及頁尾句直接跳過，不作為姓名
            if _PREAMBLE_INTRO_RE.search(collapsed) or _PREAMBLE_STOP_RE.search(collapsed):
                continue
            if in_agent_context or re.search(r"律師", collapsed):
                _add_agent(current_field, collapsed)
            else:
                _add_name(current_field, collapsed, check_len=True)

    # 建立功能性欄位結果
    result: Dict[str, str] = {k: "；".join(v) if v else "" for k, v in parties.items()}
    for f in _fields:
        result[f"{f}_agent"] = "；".join(agents[f]) if agents[f] else ""

    # 建立 party_roles：「聲請人：邱彥豪；相對人：全日通電梯有限公司」
    result["party_roles"] = "；".join(
        f"{role}：{'、'.join(names)}"
        for role in roles_order
        if (names := roles_names.get(role))
    )
    return result


# ─── Step 5：擷取相關法條 ─────────────────────────────────────────────────────
# 「附錄本案論罪科刑法條：」/ 「所犯法條：」等末尾法條附錄標記
_LAW_APPENDIX_RE = re.compile(
    r"(?:附錄(?:本案)?(?:論罪科刑)?法條(?:全文)?|所犯法條)\s*[：:]\s*"
    r"(?!分敘)",          # 排除「所犯法條分敘如下」（那是正文，不是附錄）
)
# 「據上論斷，依 ... 判決如主文」中的條文引用
# (.{1,300}?) 限制長度，避免從段落中間的「依」一路撐到文末的「判決如主文」而抓到無關內容
_YIJU_RE = re.compile(r"依\s*(.{1,300}?)\s*[,，]\s*(?:判決|裁定)如主文", re.DOTALL)
# 條文引用：「刑法第339條之4」「民法第148條」「刑事訴訟法第101條第1項」等
# {1,15} 允許單字法律名（民法、刑法），避免 {2,15} 造成多字詞前綴（如「惟依民法」）被誤抓
_LAW_CITE_RE = re.compile(
    r"(?:[^\s，；、（\(]{1,15}(?:法|條例|規則))"
    r"\s*第\s*[\d百千一二三四五六七八九十]+\s*條[之第\d\s]*"
)


def _extract_laws(soup: BeautifulSoup, sections: Dict[str, str], full_text: str = "") -> str:
    # 1. 法條附錄（出現在頁尾日期之後，故從 full_text 中尋找）
    if full_text:
        m = _LAW_APPENDIX_RE.search(full_text)
        if m:
            # 附錄之後的所有文字即是法條（保留至多 3000 字）
            return full_text[m.end():].strip()[:3000]

    # 2. 從「據上論斷」提取緊湊的條文引用
    #    同時搜尋 sections["據上論斷"] 和 理由/事實及理由 的末尾
    candidates = [
        sections.get("據上論斷", ""),
        sections.get("理由", ""),
        sections.get("事實及理由", ""),
    ]
    for src in candidates:
        if not src:
            continue
        # 找 "依...判決如主文" 子句
        m = _YIJU_RE.search(src[-3000:])   # 只搜結尾部分，效率較高
        if m:
            cited = _LAW_CITE_RE.findall(m.group(1))
            if cited:
                return "；".join(dict.fromkeys(cited))[:1000]

    return ""


# ─── Step 6：法官 / 書記官擷取 ───────────────────────────────────────────────
_JUDGE_NOISE_RE = re.compile(r"獨任|審理|書記|主任|股長|庭長")

# CJK 姓名：允許字間「水平」空格（不跨行），最多 6 字（含空格前後各字）
# [^\S\n]* = 任意非換行空白，可為零寬，不會跨行
_CJK_NAME_RE = r"([一-鿿](?:[^\S\n]*[一-鿿]){1,5})"

# 頁尾常見詞語：出現在姓名後代表已到達文件結尾或附件標記
_NAME_TAIL_NOISE_RE = re.compile(
    r"(?:以上|附表|附件|附錄|正本|如不|書記|係照|據上|所犯|中華)"
)


def _clean_cjk_name(raw: str) -> str:
    """去除姓名內的空白並截斷頁尾雜訊（同行的「以上正本」、「附表」等）。"""
    n = re.sub(r"\s+", "", raw)
    m = _NAME_TAIL_NOISE_RE.search(n)
    return n[: m.start()] if m else n


def _extract_judges_and_clerk(full_text: str) -> Tuple[str, str]:
    """
    從裁判書簽名區擷取法官姓名（含合議庭）與書記官姓名。

    策略：
    1. 在 full_text 全文找出所有法官 match，取最後一個有效位置為簽名區。
       向前 300 字收集合議庭其他法官，不設定尾端窗口上限，
       避免長文書（附錄、嵌入起訴書）把簽名區推到窗口外。
    2. 書記官限定在「最後一位法官」起算後 600 字內搜尋，
       避免抓到 HTML 末尾嵌入起訴書或正本認證章的書記官。
    """
    # 在全文找所有法官 pattern（不限尾端窗口大小）
    all_matches = list(re.finditer(
        rf"(?:審判長\s*)?法\s*官\s+{_CJK_NAME_RE}", full_text
    ))

    # 過濾假名（獨任、審理…）
    valid = [(m, _clean_cjk_name(m.group(1))) for m in all_matches]
    valid = [(m, n) for m, n in valid if n and not _JUDGE_NOISE_RE.search(n)]

    if not valid:
        return "", ""

    # 最後一個有效法官 = 簽名區起點
    last_m, _ = valid[-1]
    sig_pos     = last_m.start()
    panel_start = max(0, sig_pos - 300)   # 合議庭其他法官範圍

    seen: set = set()
    unique: list = []
    for m, n in valid:
        if m.start() >= panel_start:
            if n not in seen:
                seen.add(n)
                unique.append(n)
    judges = "；".join(unique)[:200]

    # 書記官：在最後一位法官起算 600 字內搜尋
    clerk_window = full_text[sig_pos : sig_pos + 600]
    cm = re.search(rf"書\s*記\s*官\s+{_CJK_NAME_RE}", clerk_window)
    if cm:
        n = _clean_cjk_name(cm.group(1))
        clerk = n if 1 <= len(n) <= 6 else ""
    else:
        clerk = ""

    return judges, clerk


# ─── 核心解析入口 ─────────────────────────────────────────────────────────────
def parse_html(
    html_content: str,
    crawl_id:     int,
    keyword:           str = "",
    case_number_hint:  str = "",
    court_hint:        str = "",
    date_hint:         str = "",
    source_url:        str = "",
) -> Dict:
    soup = BeautifulSoup(html_content, "lxml")
    for tag in soup(["script", "style", "nav", "noscript"]):
        tag.decompose()

    # 1. Metadata（裁判字號、法院、日期）
    meta = _extract_metadata(soup)

    if not meta["case_number"] and case_number_hint:
        meta["case_number"] = case_number_hint

    if not meta["court"]:
        # 驗證 court_hint：必須含「法院」，否則可能是舊版 DB 誤填的日期值
        if court_hint and _COURT_VALID_RE.search(court_hint):
            meta["court"] = court_hint
        else:
            # 從裁判字號解析法院（stub HTML 無 #jud 時的保底）
            cn = meta["case_number"] or case_number_hint
            if cn:
                cm = _COURT_RE.match(cn)
                if cm:
                    meta["court"] = cm.group(1).strip()

    if not meta["judgment_date"]:
        # 驗證 date_hint：必須含日期格式，否則可能是誤填的案件類型
        if date_hint and _DATE_HINT_RE.search(date_hint):
            meta["judgment_date"] = date_hint

    # 2. 正文容器
    container = _find_content_container(soup)

    # 3. 段落切割
    sections, full_text, preamble = _extract_sections(container)

    # 4. 當事人
    parties = _extract_parties(preamble)

    # 5. 適用法條（需要 full_text 才能找到頁尾法條附錄）
    applicable_laws = _extract_laws(soup, sections, full_text)

    # 6. 法官 / 書記官
    judges_extracted, clerk = _extract_judges_and_clerk(full_text)
    judges = meta.get("judges") or judges_extracted

    # ── 段落欄位對應 ──────────────────────────────────────────────
    # facts_and_reasons: 合體版「事實及理由」→ 專屬欄位
    # facts / reasons:   分開撰寫版 → 各自欄位
    facts_and_reasons_val = (
        sections.get("事實及理由", "")
        or sections.get("事實暨理由", "")
        or sections.get("事實與理由", "")
    )
    facts_val   = sections.get("事實", "")
    reasons_val = (
        sections.get("理由", "")
        or sections.get("認定犯罪事實所憑之證據及理由", "")
    )

    # 裁定 or 判決：從裁判字號或案件類型末尾辨識
    cn_for_type = meta["case_number"] or case_number_hint
    if "判決" in cn_for_type:
        judgment_type = "判決"
    elif "裁定" in cn_for_type:
        judgment_type = "裁定"
    elif cn_for_type:
        judgment_type = "其他"
    else:
        judgment_type = ""

    return {
        "crawl_id":           crawl_id,
        "case_number":        meta["case_number"],
        "court":              meta["court"],
        "judgment_date":      meta["judgment_date"],
        "case_type":          meta["case_type"],
        "judgment_type":      judgment_type,
        "source_url":         source_url,
        "verdict":            _cap(sections.get("主文", ""),               10000),
        "facts":              _cap(facts_val,                               30000),
        "facts_and_reasons":  _cap(facts_and_reasons_val,                   50000),
        "criminal_facts":     _cap(sections.get("犯罪事實", ""),            30000),
        "reasons":            _cap(reasons_val,                             50000),
        "conclusion":         _cap(sections.get("結論", sections.get("據上論斷", "")), 5000),
        "applicable_laws":    _cap(applicable_laws,                         3000),
        "judges":             judges,
        "clerk":              clerk,
        "plaintiff":          parties["plaintiff"],
        "plaintiff_agent":    parties["plaintiff_agent"],
        "defendant":          parties["defendant"],
        "defendant_agent":    parties["defendant_agent"],
        "appellant":          parties["appellant"],
        "appellant_agent":    parties["appellant_agent"],
        "appellee":           parties["appellee"],
        "appellee_agent":     parties["appellee_agent"],
        "party_roles":        parties.get("party_roles", ""),
        "other_parties":      "",
        "full_text":          _cap(full_text,                              100000),
        "keyword":            keyword,
    }


# ─── DB 寫入 ──────────────────────────────────────────────────────────────────
def save_judgment(data: Dict) -> bool:
    conn = sqlite3.connect(DB_PATH)
    c    = conn.cursor()
    try:
        c.execute(
            """INSERT OR REPLACE INTO judgments (
                   crawl_id, case_number, court, judgment_date, case_type, judgment_type,
                   source_url,
                   verdict, facts, facts_and_reasons, criminal_facts, reasons,
                   conclusion, applicable_laws, judges, clerk,
                   plaintiff, plaintiff_agent,
                   defendant, defendant_agent,
                   appellant, appellant_agent,
                   appellee,  appellee_agent,
                   party_roles, other_parties, full_text, keyword
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                data["crawl_id"], data["case_number"], data["court"],
                data["judgment_date"], data["case_type"], data["judgment_type"],
                data["source_url"],
                data["verdict"], data["facts"], data["facts_and_reasons"],
                data["criminal_facts"], data["reasons"], data["conclusion"],
                data["applicable_laws"], data["judges"], data["clerk"],
                data["plaintiff"],       data["plaintiff_agent"],
                data["defendant"],       data["defendant_agent"],
                data["appellant"],       data["appellant_agent"],
                data["appellee"],        data["appellee_agent"],
                data["party_roles"],
                data["other_parties"], data["full_text"], data["keyword"],
            ),
        )
        c.execute("UPDATE crawl_records SET parsed=1 WHERE id=?", (data["crawl_id"],))
        conn.commit()
        logger.info("  Parsed → %s", data["case_number"])
        return True
    except Exception as exc:
        logger.error("  DB error: %s", exc)
        conn.rollback()
        return False
    finally:
        conn.close()


# ─── 批次解析（將 parsed=0 的紀錄全部處理） ───────────────────────────────────
def parse_all_unparsed() -> int:
    init_db()
    conn  = sqlite3.connect(DB_PATH)
    rows  = conn.execute(
        "SELECT id, case_number, court, judgment_date, html_file, keyword, source_url "
        "FROM crawl_records WHERE parsed=0"
    ).fetchall()
    conn.close()

    logger.info("Unparsed records: %d", len(rows))
    success = 0

    for crawl_id, case_number, court, jdate, html_file, keyword, source_url in rows:
        if not html_file or not os.path.exists(html_file):
            logger.warning("  HTML not found: %s", html_file)
            continue
        try:
            with open(html_file, encoding="utf-8") as f:
                html = f.read()
            data = parse_html(
                html, crawl_id,
                keyword=keyword or "",
                case_number_hint=case_number or "",
                court_hint=court or "",
                date_hint=jdate or "",
                source_url=source_url or "",
            )
            if save_judgment(data):
                success += 1
        except Exception as exc:
            logger.error("  Error parsing %s: %s", html_file, exc, exc_info=True)

    logger.info("Parsing complete: %d / %d", success, len(rows))
    return success


# ─── 重新解析已解析過的紀錄 ───────────────────────────────────────────────────
def reparse_all() -> int:
    """將所有 crawl_records.parsed 重設為 0，再重新解析。"""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE crawl_records SET parsed=0")
    conn.execute("DELETE FROM judgments")
    conn.commit()
    conn.close()
    logger.info("Reset all parsed flags — re-parsing everything")
    return parse_all_unparsed()


# ─── CLI ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="解析裁判書 HTML 並存入資料庫")
    ap.add_argument("--file",   default="", help="解析單一 HTML 檔案")
    ap.add_argument("--reparse", action="store_true",
                    help="重新解析所有記錄（清空 judgments 表並重新跑）")
    args = ap.parse_args()

    if args.reparse:
        n = reparse_all()
        print(f"\n完成！重新解析 {n} 筆。")
    elif args.file:
        if not os.path.exists(args.file):
            print(f"檔案不存在: {args.file}")
        else:
            init_db()
            conn = sqlite3.connect(DB_PATH)
            conn.execute(
                "INSERT OR IGNORE INTO crawl_records (case_number, html_file) VALUES (?,?)",
                (os.path.basename(args.file), args.file),
            )
            conn.commit()
            cid = conn.execute(
                "SELECT id FROM crawl_records WHERE html_file=?", (args.file,)
            ).fetchone()[0]
            conn.close()
            with open(args.file, encoding="utf-8") as f:
                html = f.read()
            data = parse_html(html, cid)
            save_judgment(data)
            print(f"解析完成：{data['case_number']}")
            print(f"  主文  : {data['verdict'][:80]}")
            print(f"  事實  : {data['facts'][:80]}")
            print(f"  理由  : {data['reasons'][:80]}")
            print(f"  原告  : {data['plaintiff']}")
            print(f"  被告  : {data['defendant']}")
    else:
        n = parse_all_unparsed()
        print(f"\n完成！共解析 {n} 筆裁判書。")
