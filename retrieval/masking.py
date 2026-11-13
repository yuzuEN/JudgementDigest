"""
遮名：顯示判決時遮掉當事人姓名，送出使用者輸入前遮掉身分證字號、電話、電子郵件、地址與指定的姓名。

規則式、不呼叫外部服務。使用者輸入的遮名在瀏覽器完成（frontend/src/mask.ts），規則要和這裡一致，
兩邊用同一份測試案例 frontend/src/test/masking_cases.json；這裡的 mask() 用於判決與送給 LLM 前的第二道防線。
自動辨識不認識的人名（CKIP 等）之後再加；目前姓名由兩個來源提供：
判決的當事人欄位（建檢索索引時），以及使用者在預覽時自己補上的名字。
"""
import re
from typing import Iterable, List, NamedTuple, Optional

TAGS = {"id": "身分證字號", "phone": "電話", "email": "電子郵件", "address": "地址", "plate": "車牌", "birth": "出生日期", "name": "姓名"}

_NUM = r"[0-9０-９一二三四五六七八九十百之-]"
# 地址有兩條規則：從縣市開始的完整地址，以及沒寫縣市、但有門牌號碼的地址（「中庄街71巷56號」）。
# 沒寫縣市的地址一律遮，不看前後文（2026-11-13 改）：只看「門牌」「房屋」這類前後文時，
# 「承租富宜路270號」「不動產所在地：楊梅鎮高獅路711號」都會漏掉。代價是車禍地點也會遮（「停於【地址】前」），句子仍讀得懂。
# 路名不能含「時、於、在、因」這類虛詞：「住在…」「因當時東門街68號」才會從路名開始遮，不會把前面的字吃掉。
_CITY = r"(?:[臺台](?:北|中|南|東)|新北|桃園|高雄|基隆|新竹|嘉義|苗栗|彰化|南投|雲林|屏東|宜蘭|花蓮|澎湖|金門|連江)[市縣]"
# 單字：幾乎不會出現在路名裡的虛詞與動詞；詞：「經」「由」「前」「開」可能是路名（經國路、自由路、前鎮區、開元路），
# 只擋判決常見的詞（「經查」「由於」「之前」「當時」）
_ROAD_STOP_WORDS = "當時|前往|之前|以前|先前|經查|經過|經由|由於|開設|開始|自行|向來|至於|後來|前開|上開|嗣後"
_ROAD_STOP_CHARS = "時於在因即為將之與及等坐落住址號的係而並其該已爭稱到寄搬去送回從赴往位系本沿"
# 詞的第二個字也要擋（「經查」的「查」），否則會從「查」開始遮，留下「經【地址】」
_ROAD_STOP_SECOND = "|".join(f"(?<={w[0]}){w[1]}" for w in _ROAD_STOP_WORDS.split("|"))
_ROAD_CHAR = (r"(?:(?!" + _ROAD_STOP_WORDS + r")(?!" + _ROAD_STOP_SECOND + r")(?![" + _ROAD_STOP_CHARS + r"])[一-鿿])")
_ADDR_NO_CITY = (r"(?:" + _ROAD_CHAR + r"{1,3}[區鄉鎮市])?(?:" + _ROAD_CHAR + r"{1,3}[村里])?"
                 + _ROAD_CHAR + r"{1,5}(?:路|街|大道)"
                 r"(?:" + _NUM + r"+段)?(?:" + _NUM + r"+巷)?(?:" + _NUM + r"+弄)?" + _NUM + r"+號"
                 r"(?:之" + _NUM + r"+)?(?:" + _NUM + r"+樓)?(?:之" + _NUM + r"+)?")
PATTERNS = [
    ("id", re.compile(r"(?<![A-Za-z0-9])[A-Z][12489]\d{8}(?![0-9])")),
    ("email", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    ("phone", re.compile(r"(?<!\d)(?:\+886[-\s]?9|09)\d{2}[-\s]?\d{3}[-\s]?\d{3}(?!\d)"
                         r"|(?<!\d)\(?0[2-8]\d?\)?[-\s]?\d{3,4}[-\s]?\d{4}(?!\d)")),
    ("address", re.compile(_CITY + r"(?:[一-鿿]{1,3}?[區鄉鎮市])?"
                           r"[一-鿿]{1,6}?[路街道大道](?:" + _NUM + r"+段)?(?:" + _NUM + r"+巷)?"
                           r"(?:" + _NUM + r"+弄)?" + _NUM + r"+號(?:之" + _NUM + r"+)?(?:" + _NUM + r"+樓)?")),
    ("address", re.compile(_ADDR_NO_CITY)),
    # 車牌有兩種寫法。一看就是車牌的格式直接遮：汽車 ABC-1234、AB-1234、1234-AB、A1-2345，機車 ABC-123、123-ABC。
    # 前後不能再接英數字或「-」，「7345-ST-A03」這類圖號才不會被切出一段。ISO-9001 這類標準編號除外。
    # 其他格式（AB-123、123-AB、法院遮過的 000-0000）要前面寫了「車牌」「車號」才遮；值放在 v 群組，只遮車牌本身。
    # 出生年月日（法院公開判決時不含，但偶爾漏掉）：「89年4月6日生，」「民國41年1月15日出生」。
    # 後面要接標點或結尾，「112年1月4日生送達效力」「…日生效」才不會被遮。
    ("birth", re.compile(r"(?:民國)?(?<![0-9])[0-9]{2,3}年[0-9]{1,2}月[0-9]{1,2}日(?:出生|生)(?=[，,。、；;（(）)\s]|$)")),
    ("plate", re.compile(r"(?<![A-Za-z0-9-])(?!ISO|CNS|SOP|IEC|RFC)"
                         r"(?:[A-Z]{3}-[0-9]{3,4}|[0-9]{3}-[A-Z]{3}|[0-9]{4}-[A-Z]{2}|[A-Z]{2}-[0-9]{4}"
                         r"|[A-Z][0-9]-[0-9]{4}|[0-9]{4}-[A-Z][0-9])(?![A-Za-z0-9-])"
                         r"|(?:車牌|車號|牌照|號牌)(?:號碼|號)?[：:為是即]?\s?(?P<v>[A-Z0-9]{2,4}-?[A-Z0-9]{2,4})(?![A-Za-z0-9-])")),
]


# 中文輸入法常打出全形數字與英文。比對前轉成半形，長度不變，所以位置可以直接對回原文
_HALF_WIDTH = {code: code - 0xFEE0 for code in range(0xFF01, 0xFF5F)}


class Span(NamedTuple):
    start: int
    end: int
    kind: str
    text: str


def _name_pattern(names: Iterable[str]) -> Optional["re.Pattern"]:
    # 長的名字先比對：「王小明」不會先被「王小」吃掉
    names = sorted({n.strip() for n in names if n and n.strip()}, key=len, reverse=True)
    return re.compile("|".join(map(re.escape, names))) if names else None


def find_spans(text: str, names: Iterable[str] = ()) -> List[Span]:
    """找出要遮的片段；重疊時保留先找到、範圍較長的那一個。"""
    found = []
    half = text.translate(_HALF_WIDTH)
    for kind, rx in PATTERNS:
        for m in rx.finditer(half):
            start, end = m.span("v") if "v" in rx.groupindex and m.group("v") else m.span()
            found.append(Span(start, end, kind, text[start:end]))
    pattern = _name_pattern(names)
    if pattern:
        for m in pattern.finditer(text):
            found.append(Span(m.start(), m.end(), "name", m.group()))
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
    r"(?:訴外人|證人|鑑定人|受僱人|配偶|之子|之女|之妻|之夫|父親|母親|兒子|女兒|胞兄|胞弟|胞姊|胞妹|之孫|曾孫|孫女|孫子|"
    r"友人|朋友|同事|鄰居|女友|男友|前妻|前夫|同居人|房東|房客)"
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


def _follow_list(text: str, end: int, names: set) -> None:
    """從 end 開始往後找「、王大明、謝新潭」這種列舉，找到的名字加進 names。"""
    while True:
        item = _NAME_LIST_RE.match(text, end)
        if not item:
            return
        names.add(item.group(1))
        end = item.end()


def third_party_names(text: str) -> List[str]:
    text = text or ""
    names = set(_THIRD_PARTY_RE.findall(text)) | set(_NAMED_AS_RE.findall(text))
    for found in list(_THIRD_PARTY_RE.finditer(text)) + list(_NAMED_AS_RE.finditer(text)):
        _follow_list(text, found.end(), names)
    return sorted(names)


def listed_with(text: str, known: Iterable[str]) -> List[str]:
    """
    列舉裡跟在已知名字後面的名字（「【關係人80】、吳渭渠、【關係人83】」原文是一串人名，
    人名辨識漏掉其中一個時，靠前一個已知的名字補上）。回傳新找到的名字。
    """
    text = text or ""
    known = {n for n in known if n}
    pattern = _name_pattern(known)
    if not pattern:
        return []
    found = set()
    for m in pattern.finditer(text):
        _follow_list(text, m.end(), found)
    return sorted(found - known)


_CJK_NAME = re.compile(r"[一-鿿]{2,4}")
# 人名辨識在判決裡常見的誤判（100 件實測）：判決用語黏到名字上（「利云云」「固可認」「卷可佐」「伊前夫」「主張渠等」→「張渠」），
# 以及計算方法等專有名詞。開頭是虛詞、或姓氏之後出現這些字的，都不當人名。
_NER_BAD_FIRST = set("伊渠其於自更固卷上又詎該本此並另嗣經即")
# 「之、渠、其、開」不放：「張之瑋」「吳渭渠」「陳其邁」「儲開軒」是真名；「云」也不放（「曾湘云」），只排除「云云」
_NER_BAD_INNER = set("伊可卷於無庸僅參尚")
# 「之孫鄭維德」會被辨識出「孫鄭」：親屬稱謂接姓氏的兩個字不是人名（取代時還會切斷後面的「鄭宇峰」）
_KINSHIP_FIRST = set("孫子女妻夫父母兄弟姊妹姪甥媳婿")
# 法院給未成年人或匿名者的代稱（「蘇童」＝姓蘇的兒童、「王姓」「陳某」「林女」），不是真名，不用遮
_PSEUDONYM_SECOND = set("童姓某氏男女")
_NOT_PERSON = {"霍夫曼", "萊布尼茲", "萊布尼滋"}


def usable_person_names(names: Iterable[str]) -> List[str]:
    """
    人名辨識（retrieval/ner.py）找到的名字，挑出可以拿來全文取代的。
    取代是整件判決找同樣的字串，太短或不像人名的會把一般用語一起遮掉，所以：
    只收 2–4 個中文字；兩個字的要以常見姓氏開頭（「建國」可能是人名，也會出現在「建國路」）；
    已經遮過（含「○」）的、和 _NOT_NAME 的常見詞（「陳述」「簡易」）開頭相同的不收。
    """
    kept = set()
    for n in names:
        n = (n or "").strip()
        if not _CJK_NAME.fullmatch(n):
            continue
        if len(n) == 2 and (n[0] not in _SURNAMES or n[1] in "一二三四五六七八九十百千"):
            continue          # 「張一」會把「主張一部」也遮掉
        if n in _NOT_PERSON or n[0] in _NER_BAD_FIRST or _NER_BAD_INNER & set(n[1:]) or "云云" in n:
            continue
        if n.endswith("之"):        # 「余梅之出資」「許北之」：後面的字黏上來
            continue
        if len(n) == 2 and (n[1] in _PSEUDONYM_SECOND or n[1] in "伊渠其"
                            or (n[0] in _KINSHIP_FIRST and n[1] in _SURNAMES)):
            continue
        if re.match(_NOT_NAME, n) is None:   # _NOT_NAME 是否定預查，比對失敗＝開頭是常見詞
            continue
        kept.add(n)
    return sorted(kept)


def by_appearance(names: Iterable[str], text: str) -> List[str]:
    """名字依在 text 裡第一次出現的位置排序（給【關係人1】【關係人2】編號用）；沒出現的排最後。"""
    names = list(dict.fromkeys(n for n in names if n))
    return sorted(names, key=lambda n: (text.find(n) if n in text else len(text), n))


def _role_tags(names: Iterable[str], role: str) -> dict:
    """同一個角色只有一個人時是【被告】；多個人時依順序編號【被告1】【被告2】，讀者才分得出誰是誰。"""
    names = list(dict.fromkeys(n.strip() for n in names if n and n.strip()))
    if len(names) == 1:
        return {names[0]: f"【{role}】"}
    return {n: f"【{role}{k}】" for k, n in enumerate(names, 1)}


def _replace_names(text: str, tags: dict) -> str:
    pattern = _name_pattern(tags)
    return pattern.sub(lambda m: tags[m.group()], text) if pattern else text


def mask_parties(text: str, plaintiffs: Optional[str], defendants: Optional[str],
                 agents: Iterable[Optional[str]] = (), others: Iterable[str] = ()) -> str:
    """
    顯示判決時用：原告、被告、代理人的名字換成角色，其餘個資用 mask() 的規則。
    同一個角色有多人時編號（【被告1】【被告2】），編號依當事人欄位的順序。
    others：這件判決裡的第三人（third_party_names、人名辨識），換成【關係人】或【關係人1】【關係人2】，
    編號依 others 的順序（用 by_appearance 排成在判決裡出現的順序）。要用整件判決找出來的名字，
    同一個人在別的段落可能沒有寫稱謂；同一件判決的每一段都要傳同樣的 others，編號才會一致。
    """
    text = text or ""
    tags = {}
    for names, role in ((party_names(plaintiffs), "原告"), (party_names(defendants), "被告"),
                        (party_names(*agents), "代理人"), (list(others), "關係人")):
        for name, tag in _role_tags(names, role).items():
            tags.setdefault(name, tag)        # 同一個名字出現在兩種角色時，以前面的角色為準
    # 長的名字先全部換掉，再換短的：「曾孫鄭宇峰」裡，誤判的「孫鄭」不會比「鄭宇峰」先換掉而切斷它
    for length in sorted({len(n) for n in tags}, reverse=True):
        text = _replace_names(text, {n: t for n, t in tags.items() if len(n) == length})
    return mask(text)[0]
