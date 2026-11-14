"""
判決法院判斷段的層級解析，以及「論點單位」切分（原型）。

台灣判決的編號層級（由大到小）：壹、→ 一、→ ㈠／(一) → ⒈／1. → ⑴／(1) → ①
法院判斷段沒有換行，編號只能從文字中辨識，誤判風險高（「第一、二審」「1.5萬元」「第184條第1項(3)」）。
因此加上順序檢查：候選編號必須
  (a) 接續同一層的上一個號碼（二 接在 一 後面），或
  (b) 是比目前更深一層的第一個號碼（開新的子層）
才會被接受為編號；否則當作一般文字。

論點單位：由上往下，一個節點（含所有子項）在 max_len 字內就整塊當一個單位；
太長才拆成下一層的子節點；沒有子節點又太長，才在句號處切。
"""
import re

CN = {c: i for i, c in enumerate("一二三四五六七八九十", start=1)}
FORMAL = {c: i for i, c in enumerate("壹貳參肆伍陸柒捌玖拾", start=1)}
FORMAL["叁"] = 3


def cn_num(s: str) -> int:
    """一～九十九的中文數字。"""
    if s in CN:
        return CN[s]
    if s.startswith("十"):
        return 10 + (CN[s[1]] if len(s) > 1 else 0)
    if len(s) >= 2 and s[1] == "十":
        return CN[s[0]] * 10 + (CN[s[2]] if len(s) > 2 else 0)
    return -1


# (層級, 正規表示式, 取號碼的函式)。層級數字越小越上層。
PATTERNS = [
    (1, re.compile(r"[壹貳參叁肆伍陸柒捌玖拾]、"), lambda m: FORMAL[m.group()[0]]),
    (2, re.compile(r"(?<![第\d一二三四五六七八九十])[一二三四五六七八九十]{1,3}、"), lambda m: cn_num(m.group()[:-1])),
    (3, re.compile(r"[㈠-㈩]"), lambda m: ord(m.group()) - ord("㈠") + 1),
    (3, re.compile(r"[(（][一二三四五六七八九十]{1,3}[)）]"), lambda m: cn_num(m.group()[1:-1])),
    (4, re.compile(r"[⒈-⒛]"), lambda m: ord(m.group()) - ord("⒈") + 1),
    (4, re.compile(r"(?<![\d.,，．第])\d{1,2}[.．、](?![\d])"), lambda m: int(re.match(r"\d+", m.group()).group())),
    (5, re.compile(r"[⑴-⒇]"), lambda m: ord(m.group()) - ord("⑴") + 1),
    (5, re.compile(r"[(（]\d{1,2}[)）]"), lambda m: int(re.search(r"\d+", m.group()).group())),
    (6, re.compile(r"[①-⑳]"), lambda m: ord(m.group()) - ord("①") + 1),
]


def candidates(text: str) -> list:
    """所有候選編號 (位置, 層級, 號碼, 符號)，依位置排序。"""
    out = []
    for level, rx, num in PATTERNS:
        for m in rx.finditer(text):
            n = num(m)
            if n > 0:
                out.append((m.start(), level, n, m.group()))
    out.sort()
    return out


BOUNDARY = set("。：:；;」）)") | {" ", "\u3000"}   # 「、」不算：「報告表㈠、㈡可參」是引用


def at_boundary(text: str, pos: int) -> bool:
    """標題幾乎都在句子開頭：前一個字是句號、冒號、分號、右括號、引號，或是全文開頭。
    內文引用（「如不爭執事項㈠所示」「報告表㈠、㈡」）前面是一般文字或頓號，會被擋下。"""
    return pos == 0 or text[pos - 1] in BOUNDARY


def headings(text: str) -> tuple:
    """
    通過檢查的編號 [(位置, 層級, 號碼)] 與被拒絕的候選數。
    兩道檢查：
      位置：在句子開頭；或緊接在剛收的標題之後 16 字內的第一號（「三、得心證之理由㈠本件⋯」）
      順序：同層接續上一號；或該層目前沒有開著（不論號碼，處理「四、」開頭與上層漏收）；
            或同層重新從 1 開始（中間漏收了上層標題；只限 ⒈／1. 以下，避免誤收法條的款、目）
    stack 記錄目前開著的各層 (層級, 號碼)。
    """
    accepted, rejected, stack = [], 0, []
    last_pos = None
    for pos, level, n, _ in candidates(text):
        near_title = last_pos is not None and n == 1 and 0 < pos - last_pos <= 16
        if not (at_boundary(text, pos) or near_title):
            rejected += 1
            continue
        same = next((i for i in range(len(stack) - 1, -1, -1) if stack[i][0] == level), None)
        if same is not None and stack[same][1] == n - 1:
            del stack[same:]                        # 同層下一號：關掉更深的層
        elif same is None:
            while stack and stack[-1][0] > level:   # 該層沒開著：接受，並關掉更深的層
                stack.pop()
        elif n == 1 and level >= 4:
            # 同層重新從 1 開始：中間漏了上層標題。只限 ⒈／1. 以下：
            # 「一、」「（一）」也是法條款、目的寫法，判決引用法條時（「依下列規定：一、⋯」）會誤收
            del stack[same:]
        else:
            rejected += 1
            continue
        stack.append((level, n))
        accepted.append((pos, level, n))
        last_pos = pos
    return accepted, rejected


def build_tree(text: str) -> dict:
    """節點：{start, end, level, num, children}。根節點 level=0，涵蓋全文。"""
    heads, _ = headings(text)
    root = {"start": 0, "end": len(text), "level": 0, "num": 0, "children": []}
    stack = [root]
    for pos, level, n in heads:
        while stack[-1]["level"] >= level:
            stack[-1]["end"] = pos
            stack.pop()
        node = {"start": pos, "end": len(text), "level": level, "num": n, "children": []}
        stack[-1]["children"].append(node)
        stack.append(node)
    return root


def _sentence_split(text: str, start: int, end: int, max_len: int) -> list:
    """沒有子編號又太長：在句號處切成不超過 max_len 的片段。"""
    out, p = [], start
    while end - p > max_len:
        cut = text.rfind("。", p, p + max_len)
        cut = cut + 1 if cut > p + max_len // 3 else p + max_len
        out.append((p, cut, "sentence"))
        p = cut
    if end > p:
        out.append((p, end, "sentence" if out else "structure"))
    return out


def units(text: str, max_len: int = 1200) -> list:
    """論點單位 [(start, end, how)]，how = structure（沿編號切）或 sentence（句號硬切）。"""
    out = []

    def visit(node):
        s, e = node["start"], node["end"]
        if e - s <= max_len:
            out.append((s, e, "structure"))
            return
        kids = node["children"]
        if not kids:
            out.extend(_sentence_split(text, s, e, max_len))
            return
        if kids[0]["start"] > s:                    # 子節點前的標題或引言
            head_end = kids[0]["start"]
            if head_end - s <= 40 and kids:         # 很短的標題併到第一個子節點，避免孤立標題
                kids[0] = dict(kids[0], start=s)
            else:
                out.extend(_sentence_split(text, s, head_end, max_len))
        for k in kids:
            visit(k)

    visit(build_tree(text))
    return [(s, e, how) for s, e, how in out if text[s:e].strip()]
