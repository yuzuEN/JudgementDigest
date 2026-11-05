"""
遮名：顯示判決時遮掉當事人姓名，送出使用者輸入前遮掉身分證字號、電話、電子郵件、地址與指定的姓名。

規則式、不呼叫外部服務。自動辨識不認識的人名（CKIP 等）之後再加；目前姓名由兩個來源提供：
判決的當事人欄位（建檢索索引時），以及使用者在預覽時自己補上的名字。
"""
import re
from typing import Iterable, List, NamedTuple, Optional

TAGS = {"id": "身分證字號", "phone": "電話", "email": "電子郵件", "address": "地址", "name": "姓名"}

_NUM = r"[0-9０-９一二三四五六七八九十百之-]"
# 地址一定要從縣市開始：不限定的話「住在臺北市…」會從「在」開始遮，把前面的字吃掉。
# 只寫區、路的地址不會自動遮，使用者可以在預覽時補上。
_CITY = r"(?:[臺台](?:北|中|南|東)|新北|桃園|高雄|基隆|新竹|嘉義|苗栗|彰化|南投|雲林|屏東|宜蘭|花蓮|澎湖|金門|連江)[市縣]"
PATTERNS = [
    ("id", re.compile(r"(?<![A-Za-z0-9])[A-Z][12489]\d{8}(?![0-9])")),
    ("email", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    ("phone", re.compile(r"(?<!\d)(?:\+886[-\s]?9|09)\d{2}[-\s]?\d{3}[-\s]?\d{3}(?!\d)"
                         r"|(?<!\d)\(?0[2-8]\d?\)?[-\s]?\d{3,4}[-\s]?\d{4}(?!\d)")),
    ("address", re.compile(_CITY + r"(?:[一-鿿]{1,3}?[區鄉鎮市])?"
                           r"[一-鿿]{1,6}?[路街道大道](?:" + _NUM + r"+段)?(?:" + _NUM + r"+巷)?"
                           r"(?:" + _NUM + r"+弄)?" + _NUM + r"+號(?:之" + _NUM + r"+)?(?:" + _NUM + r"+樓)?")),
]


class Span(NamedTuple):
    start: int
    end: int
    kind: str
    text: str


def _name_pattern(names: Iterable[str]) -> Optional["re.Pattern"]:
    # 長的名字先比對：「王小明」不會先被「王小」吃掉
    names = sorted({n.strip() for n in names if n and len(n.strip()) >= 2}, key=len, reverse=True)
    return re.compile("|".join(map(re.escape, names))) if names else None


def find_spans(text: str, names: Iterable[str] = ()) -> List[Span]:
    """找出要遮的片段；重疊時保留先找到、範圍較長的那一個。"""
    found = []
    pattern = _name_pattern(names)
    rules = PATTERNS + ([("name", pattern)] if pattern else [])
    for kind, rx in rules:
        for m in rx.finditer(text):
            found.append(Span(m.start(), m.end(), kind, m.group()))
    found.sort(key=lambda s: (s.start, -(s.end - s.start)))
    spans, last = [], -1
    for s in found:
        if s.start >= last:
            spans.append(s)
            last = s.end
    return spans


def mask(text: str, names: Iterable[str] = ()) -> "tuple[str, List[Span]]":
    """回傳（遮名後的文字, 被遮的片段）。片段的位置是原文的位置。"""
    text = text or ""
    spans = find_spans(text, names)
    out, pos = [], 0
    for s in spans:
        out.append(text[pos:s.start])
        out.append(f"【{TAGS[s.kind]}】")
        pos = s.end
    out.append(text[pos:])
    return "".join(out), spans


# 判決的當事人欄位：多人以「；」「、」分隔，可能帶稱謂（「即○○商行」「兼法定代理人」）
_PARTY_SPLIT = re.compile(r"[；;、,，\s]+")
_PARTY_NOISE = re.compile(r"即.*$|兼.*$|（.*?）|\(.*?\)")


def party_names(*fields: Optional[str]) -> List[str]:
    """從判決的原告、被告、代理人欄位取出可以遮的名字（含「○」的已經遮過，不必再遮）。"""
    names = []
    for field in fields:
        for part in _PARTY_SPLIT.split(field or ""):
            part = _PARTY_NOISE.sub("", part).strip()
            if 2 <= len(part) <= 30 and "○" not in part and "〇" not in part:
                names.append(part)
    return names


# 判決裡的第三人（訴外人、證人、親屬）不在當事人欄位，只能從稱謂後面找。
# 稱謂後面要接常見姓氏，「訴外人即原告」「證人身分」才不會被當成人名；
# 名字遇到虛詞就停，「證人林文表示」不會把「表」算進去。這是規則，一定有漏網的人名。
_SURNAMES = ("陳林黃張李王吳劉蔡楊許鄭謝郭洪曾邱廖賴徐周葉蘇莊呂江何蕭羅高潘簡朱鍾彭游詹胡施沈余趙盧梁顏柯孫魏翁戴"
             "范宋方鄧杜傅侯曹薛丁卓阮馬董溫唐藍石蔣古紀姚連馮歐程湯田康姜白汪鄒尤巫鐘黎涂龔嚴韓袁金童陸夏柳邵錢伍倪"
             "于譚駱熊任甘秦顧毛賀史")
_NAME_STOP = "於和與及等到之的為在表稱證並則就係已曾亦是向對將把被有無不所以而但"
_THIRD_PARTY_RE = re.compile(
    r"(?:訴外人|證人|鑑定人|受僱人|配偶|之子|之女|之妻|之夫|父親|母親|兒子|女兒|胞兄|胞弟|胞姊|胞妹)"
    r"(?!方面|任何|連同|高度|金額|程度|石油)"
    r"([" + _SURNAMES + r"](?:(?![" + _NAME_STOP + r"])[一-鿿]){1,2})")


_NAME = r"[" + _SURNAMES + r"](?:(?![" + _NAME_STOP + r"])[一-鿿]){1,2}"
_NOT_NAME = (r"(?!何人|何者|何以|何時|何處|高雄|高等|高院|方式|方法|方面|任何|任意|連同|連帶|金額|金融|程度|石油|江蘇|馬祖|連江|新北|白天|"
             r"田地|古蹟|陳報|陳述|陳明|施作|施加|施工|施行|董事|曾經|曾匯|曾於|曾向|曾與|簡易|簡稱)")
# 「原名林朝文」「繼承人即蔡淑智」「前所有權人為蔡志陽」：沒有寫訴外人，但前面的字足以判斷是人名
_NAMED_AS_RE = re.compile(
    r"(?:原名[：:]?|(?:訴外人|第三人|繼承人|債務人|保證人|負責人|代表人|所有權人|之父|之母|其子|其女|祖父|祖母)(?:即|為)|"
    r"第三人|繼承人|其子|其女|祖父|祖母)" + _NOT_NAME + r"(" + _NAME + r")")
# 「訴外人王大明、謝新潭、陳榮坤合資」：列舉時只有第一個名字有稱謂
_NAME_LIST_RE = re.compile(r"、" + _NOT_NAME + r"(" + _NAME + r")(?=[、，。）)及與和等共合均]|$)")


def third_party_names(text: str) -> List[str]:
    text = text or ""
    names = set(_THIRD_PARTY_RE.findall(text)) | set(_NAMED_AS_RE.findall(text))
    for found in list(_THIRD_PARTY_RE.finditer(text)) + list(_NAMED_AS_RE.finditer(text)):
        end = found.end()
        while True:
            item = _NAME_LIST_RE.match(text, end)
            if not item:
                break
            names.add(item.group(1))
            end = item.end()
    return sorted(names)


def mask_parties(text: str, plaintiffs: Optional[str], defendants: Optional[str],
                 agents: Iterable[Optional[str]] = (), others: Iterable[str] = ()) -> str:
    """
    顯示判決時用：原告、被告、代理人的名字換成角色，其餘個資用 mask() 的規則。
    others：這件判決裡的第三人（third_party_names），換成【關係人】。要用整件判決找出來的名字，
    同一個人在別的段落可能沒有寫稱謂。
    """
    text = text or ""
    for role, field in (("原告", plaintiffs), ("被告", defendants)):
        pattern = _name_pattern(party_names(field))
        if pattern:
            text = pattern.sub(f"【{role}】", text)
    pattern = _name_pattern(party_names(*agents))
    if pattern:
        text = pattern.sub("【代理人】", text)
    pattern = _name_pattern(others)
    if pattern:
        text = pattern.sub("【關係人】", text)
    return mask(text)[0]
