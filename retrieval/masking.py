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
_CITY = r"(?:[臺台](?:北|中|南|東)|新北|桃園|高雄|基隆|新竹|嘉義|苗栗|彰化|南投|雲林|屏東|宜蘭|花蓮|澎湖|金門|連江)[市縣巿]"   # 「巿」是「市」的異體字，判決偶爾會用（「臺東巿」）
# 單字：幾乎不會出現在路名裡的虛詞與動詞；詞：「經」「由」「前」「開」可能是路名（經國路、自由路、前鎮區、開元路），
# 只擋判決常見的詞（「經查」「由於」「之前」「當時」）
_ROAD_STOP_WORDS = "當時|前往|之前|以前|先前|經查|經過|經由|由於|開設|開始|自行|向來|至於|後來|前開|上開|嗣後"
_ROAD_STOP_CHARS = "時於在因即為將之與及等坐落住址號的係而並其該已爭稱到寄搬去送回從赴往位系本沿"
# 詞的第二個字也要擋（「經查」的「查」），否則會從「查」開始遮，留下「經【地址】」
_ROAD_STOP_SECOND = "|".join(f"(?<={w[0]}){w[1]}" for w in _ROAD_STOP_WORDS.split("|"))
_ROAD_CHAR = (r"(?:(?!" + _ROAD_STOP_WORDS + r")(?!" + _ROAD_STOP_SECOND + r")(?![" + _ROAD_STOP_CHARS + r"])[一-鿿])")
_ADDR_NO_CITY = (r"(?:" + _ROAD_CHAR + r"{1,3}[區鄉鎮市巿])?(?:" + _ROAD_CHAR + r"{1,3}[村里])?"
                 + _ROAD_CHAR + r"{1,5}(?:路|街|大道)"
                 r"(?:" + _NUM + r"+段)?(?:" + _NUM + r"+巷)?(?:" + _NUM + r"+弄)?" + _NUM + r"+號"
                 r"(?:之" + _NUM + r"+)?(?:" + _NUM + r"+樓)?(?:之" + _NUM + r"+)?")
PATTERNS = [
    ("id", re.compile(r"(?<![A-Za-z0-9])[A-Z][12489]\d{8}(?![0-9])")),
    ("email", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    ("phone", re.compile(r"(?<!\d)(?:\+886[-\s]?9|09)\d{2}[-\s]?\d{3}[-\s]?\d{3}(?!\d)"
                         r"|(?<!\d)\(?0[2-8]\d?\)?[-\s]?\d{3,4}[-\s]?\d{4}(?!\d)")),
    ("address", re.compile(_CITY + r"(?:[一-鿿]{1,3}?[區鄉鎮市巿])?"
                           r"[一-鿿]{1,6}?[路街道大道](?:" + _NUM + r"+段)?(?:" + _NUM + r"+巷)?"
                           r"(?:" + _NUM + r"+弄)?" + _NUM + r"+號(?:之" + _NUM + r"+)?(?:" + _NUM + r"+樓)?")),
    ("address", re.compile(_ADDR_NO_CITY)),
    # 車牌有兩種寫法。一看就是車牌的格式直接遮：汽車 ABC-1234、AB-1234、1234-AB、A1-2345，機車 ABC-123、123-ABC。
    # 前後不能再接英數字或「-」，「7345-ST-A03」這類圖號才不會被切出一段。ISO-9001 這類標準編號除外。
    # 其他格式（AB-123、123-AB、法院遮過的 000-0000）要前面寫了「車牌」「車號」才遮；值放在 v 群組，只遮車牌本身。
    # 出生年月日（法院公開判決時不含，但偶爾漏掉）：「89年4月6日生，」「民國41年1月15日出生」。
    # 後面要接標點、「之」或結尾，「112年1月4日生送達效力」「…日生效」才不會被遮（「46年6月29日生之原告」要遮）。
    ("birth", re.compile(r"(?:民國)?(?<![0-9])[0-9]{2,3}年[0-9]{1,2}月[0-9]{1,2}日(?:出生|生)(?=[，,。、；;（(）)\s之及於等至」』…]|現年|當時|計至|$)")),
    ("plate", re.compile(r"(?<![A-Za-z0-9-])(?!ISO|CNS|SOP|IEC|RFC)"
                         r"(?:[A-Z]{3}-[0-9]{3,4}|[0-9]{3}-[A-Z]{3}|[0-9]{4}-[A-Z]{2}|[A-Z]{2}-[0-9]{4}"
                         r"|[A-Z][0-9]-[0-9]{4}|[0-9]{4}-[A-Z][0-9])(?![A-Za-z0-9-])"
                         r"|(?:車牌|車號|牌照|號牌)(?:號碼|號)?[：:為是即]?\s?(?P<v>[A-Z0-9]{2,4}-?[A-Z0-9]{2,4})(?![A-Za-z0-9-])")),
    # 沒有連字號、前面是「機車」「車輛」這類詞的：「機車FBL922」「車輛ARK6316號」「牌號EQE3228」。
    # 一定要英文字母和數字都有，「車輛2023年」才不會被遮；型號（「GLE350的車子」）前面不是這些詞，不會遮
    ("plate", re.compile(r"(?:機車|車輛|汽車|貨車|小客車|小貨車|車斗|拖車|牌號)(?:號碼)?[：:為是即]?\s?"
                         r"(?P<v>[A-Z]{2,3}-?[0-9]{3,4}|[0-9]{3,4}-?[A-Z]{2,3})(?![A-Za-z0-9-])")),
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


# 中文字：常用字以外也要包含擴充區的罕用字（「陳奕𤋱」的「𤋱」在擴充 B 區）
_HAN = "一-鿿㐀-䶿\U00020000-\U0003134F"

# 判決的當事人欄位：多人以「；」「、」分隔，可能帶稱謂（「即○○商行」「兼法定代理人」）
_PARTY_SPLIT = re.compile(r"[；;、,，\s]+")
_PARTY_NOISE = re.compile(r"即.*$|兼.*$|（.*?）|\(.*?\)")
# 當事人欄位解析不完整時會混進角色詞：代理人欄位出現「被告兼下一人；陳晁遠」（原文是「被告兼下一人之法定代理人 陳晁遠」），
# 清掉「兼…」後只剩「被告」。角色詞不能當名字，否則全文的「被告」都會被換掉
_ROLE_WORD = re.compile(r"原告|被告|代理人|上訴人|參加人|聲請人|相對人|債務人|債權人|下一人")


def _party_parts(field: Optional[str]):
    """當事人欄位 → [(角色或 None, 名字或 None)]：「被告兼下一人」只有角色，「被告葉麗玉」兩者都有。"""
    out = []
    for raw in _PARTY_SPLIT.split(field or ""):
        role = None
        m = re.match(r"^(原告|被告)", raw)
        if m:
            role = m.group(1)
            raw = raw[m.end():]
        part = _PARTY_NOISE.sub("", raw).strip()
        if _ROLE_WORD.search(part) or not (2 <= len(part) <= 30) or "○" in part or "〇" in part:
            part = None
        if role or part:
            out.append((role, part))
    return out


def party_names(*fields: Optional[str]) -> List[str]:
    """從判決的原告、被告、代理人欄位取出可以遮的名字（含「○」的已經遮過，不必再遮；角色詞不算名字）。"""
    return [name for field in fields for _, name in _party_parts(field) if name]


def party_roles(plaintiffs: Optional[str], defendants: Optional[str],
                agents: Iterable[Optional[str]] = ()) -> "tuple[List[str], List[str], List[str]]":
    """
    （原告, 被告, 代理人）的名字。代理人欄位裡寫明是原告或被告的人歸到當事人：
    「被告兼下一人；陳晁遠」的陳晁遠、「被告葉麗玉」的葉麗玉是被告，不是代理人。
    """
    found = {"原告": party_names(plaintiffs), "被告": party_names(defendants)}
    agent_names = []
    for field in agents:
        pending = None
        for role, name in _party_parts(field):
            role = role or pending
            pending = role if name is None else None        # 只有角色的那一格，角色給下一個名字
            if name:
                (found[role] if role else agent_names).append(name)
    return found["原告"], found["被告"], agent_names


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
    r"([" + _SURNAMES + r"](?:(?![" + _NAME_STOP + r"])[" + _HAN + r"]){1,2})")


_NAME = r"[" + _SURNAMES + r"](?:(?![" + _NAME_STOP + r"])[" + _HAN + r"]){1,2}"
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


_CJK_NAME = re.compile(r"[" + _HAN + r"]{2,4}")
# 人名辨識在判決裡常見的誤判（100 件實測）：判決用語黏到名字上（「利云云」「固可認」「卷可佐」「伊前夫」「主張渠等」→「張渠」），
# 以及計算方法等專有名詞。開頭是虛詞、或姓氏之後出現這些字的，都不當人名。
_NER_BAD_FIRST = set("伊渠其於自更固卷上又詎該本此並另嗣經即")
# 「之、渠、其、開」不放：「張之瑋」「吳渭渠」「陳其邁」「儲開軒」是真名；「云」也不放（「曾湘云」），只排除「云云」。
# 「伊」也不放：它是代名詞（「約定伊」「陳稱伊」），也是常見的名字用字（「謝伊婷」「林芷伊」），另外用 _yi_name_ok 判斷
_NER_BAD_INNER = set("可卷於無庸僅參尚")
# 「之孫鄭維德」會被辨識出「孫鄭」：親屬稱謂接姓氏的兩個字不是人名（取代時還會切斷後面的「鄭宇峰」）
_KINSHIP_FIRST = set("孫子女妻夫父母兄弟姊妹姪甥媳婿")
# 法院給未成年人或匿名者的代稱（「蘇童」＝姓蘇的兒童、「王姓」「陳某」「林女」），不是真名，不用遮
_PSEUDONYM_SECOND = set("童姓某氏男女")
_NOT_PERSON = {"霍夫曼", "萊布尼茲", "萊布尼滋", "張冠李戴", "烏克麗麗", "亞帝芬奇", "三樓馬達", "卓見", "毛遂", "余裕"}
# 四個字的辨識結果常是三個字的名字多黏了一個字：「經查張德滿」→「查張德滿」、「王怡文固」「陳國輝代」。去掉黏上的字
_GLUED_FIRST = set("查代姊兄弟妹母父")
# 「蔡如滿伊」「錢祥瑞伊」：三個字的名字後面接代名詞「伊」；「劉伊峯嗣」：接「嗣後」
_GLUED_LAST = set("固業代公斯君等伊嗣")


_TOP_SURNAMES = set("陳林黃張李王吳劉蔡楊")
RARE_MAX_DF = 10      # 兩個字的名字：在全部判決裡出現的件數不超過這個才算人名
COMMON_MIN_DF = 1000  # 名字裡有「伊」時，前兩個字出現在這麼多件判決以上就是一般詞（「金錢」「程序」「陳稱」）

# 名字裡有「伊」時的判斷（2026-11-14，全部 15.8 萬件的辨識結果裡，原本只因為「伊」被擋掉的有 422 種）：
# 代名詞的「伊」前後是動詞或虛詞（「陳稱伊」「明知伊」「伊及伊」），名字的「伊」前面是姓（「黃伊弘」）或名字用字（「林芷伊」）。
# 「致」不放：「呂致伊」是名字
_YI_FUNC = set("稱述知定時因及與說請以向對將把被為在於使令讓給告約示認悉證查依按斯云謂指跟和替叫拿帶由自故後不若")
_YI_SURNAMES = set(_SURNAMES) | set("饒殷葛覃穆崔聶房章祝喬賈雷齊廉龍萬易岳文温黄凌戚柴畢竇茆蒲闕陶霍靳麥奚塗巢官池")
# 姓開頭的動詞接代名詞「伊」（「羅織伊入罪」「杜撰伊有專長」）：在判決裡不常見，出現件數擋不掉
_YI_VERBS = {"羅織", "杜撰", "誣指", "誣陷", "陷害", "誣告", "詆毀", "污衊", "汙衊", "蒙騙", "誘騙", "唆使", "毆打"}


def _yi_prefix(n: str) -> Optional[str]:
    """「林芷伊」這種「伊」在第三個字以後的名字，要看前兩個字是不是一般詞（「金錢伊」「程序伊」）；回傳要查的前兩個字。"""
    return n[:2] if "伊" in n[2:] and "伊" not in n[:2] else None


def _yi_name_ok(n: str, common_words: Optional[set]) -> bool:
    """有「伊」的辨識結果是不是人名。common_words：在全部判決裡很常見的兩個字（common_bigrams）；沒給時，「伊」不在第二個字的一律不收。"""
    if n.count("伊") != 1 or n[0] not in _YI_SURNAMES:
        return False
    i = n.index("伊")
    if n[i - 1] in _YI_FUNC or (i + 1 < len(n) and n[i + 1] in _YI_FUNC):
        return False
    prefix = _yi_prefix(n)
    if prefix in _YI_VERBS:
        return False
    return prefix is None or (common_words is not None and prefix not in common_words)


def _two_char_candidate(n: str) -> bool:
    """兩個字的辨識結果，排除一看就不是名字的；是不是一般詞要再看 rare_two_char_names。"""
    return (len(n) == 2 and n[0] in _SURNAMES and n[1] not in "一二三四五六七八九十百千伊渠其"
            and n[1] not in _PSEUDONYM_SECOND and n[1] not in _TOP_SURNAMES
            and not (n[0] in _KINSHIP_FIRST and n[1] in _SURNAMES))


def rare_two_char_names(candidates: Iterable[str], texts: Iterable[str], max_df: int = RARE_MAX_DF) -> set:
    """
    兩個字的候選名字裡，在 texts（全部判決）出現不超過 max_df 件的。
    一般詞會出現在很多判決（15.8 萬件裡「陳情」1,016 件、「馬達」687 件、「周全」204 件），
    人名通常只有一兩件（「劉旭」3 件、「張蕾」2 件），用出現的件數分開。
    """
    return name_word_frequencies(candidates, texts, max_df)[0]


_COMPOUND_SURNAMES = {"歐陽", "司馬", "諸葛", "上官", "張簡", "范姜", "司徒", "東方", "夏侯", "長孫", "慕容", "端木",
                      "皇甫", "尉遲", "公孫"}


def _trim_glued(n: str) -> str:
    if len(n) == 4 and n[0] in _GLUED_FIRST and n[1] in _SURNAMES:
        return n[1:]
    if len(n) == 4 and n[3] in _GLUED_LAST and n[:2] not in _COMPOUND_SURNAMES:   # 「歐陽芷伊」是四個字的名字
        # 接「伊」「嗣」的，第一個字要是姓，否則整個不收（「茲陳報伊」「不爭執伊」「鏡週刊嗣」是一般詞）
        if n[3] in "伊嗣" and n[0] not in _YI_SURNAMES:
            return ""
        return n[:3]
    return n


def name_word_frequencies(candidates: Iterable[str], texts: Iterable[str], max_df: int = RARE_MAX_DF,
                          common_df: int = COMMON_MIN_DF) -> "tuple[set, set]":
    """
    讀一次全部判決，回傳（rare_two_char, common_words）：
    rare_two_char：兩個字的候選名字裡出現不超過 max_df 件的（見 rare_two_char_names）
    common_words：有「伊」的候選名字（「金錢伊」「林芷伊」）的前兩個字裡，出現 common_df 件以上的一般詞
    """
    candidates = {(n or "").strip() for n in candidates}
    two = {n for n in candidates if _two_char_candidate(n)}
    prefixes = {p for p in (_yi_prefix(_trim_glued(n)) for n in candidates if len(n) >= 3) if p}
    cands = two | prefixes
    if not cands:
        return set(), set()
    firsts = {n[0] for n in cands}
    df = {}
    for t in texts:
        t = t or ""
        for b in {t[i:i + 2] for i in range(len(t) - 1) if t[i] in firsts} & cands:
            df[b] = df.get(b, 0) + 1
    return ({n for n in two if df.get(n, 0) <= max_df},
            {p for p in prefixes if df.get(p, 0) >= common_df})


def usable_person_names(names: Iterable[str], rare_two_char: Optional[set] = None,
                        common_words: Optional[set] = None) -> List[str]:
    """
    人名辨識（retrieval/ner.py）找到的名字，挑出可以拿來全文取代的。
    取代是整件判決找同樣的字串，不像人名的會把一般用語一起遮掉，所以：
    - 3–4 個中文字（含罕用字）。四個字的去掉黏上的字（「查張德滿」→「張德滿」）
    - 兩個字的只收 rare_two_char 裡的（rare_two_char_names：在全部判決裡很少出現的）；沒給就不收。
      人工抽查時「馬達」被當成人名遮掉，兩個字的辨識結果多半是一般詞（「陳情」「周全」）
    - 已經遮過（含「○」）的、和 _NOT_NAME 的常見詞（「陳述」「簡易」）開頭相同的不收
    - 有「伊」的看 _yi_name_ok；common_words 是 name_word_frequencies 算出的一般詞
    """
    kept = set()
    for n in names:
        n = (n or "").strip()
        if len(n) == 2:
            if (rare_two_char and n in rare_two_char and n not in _NOT_PERSON and _two_char_candidate(n)
                    and re.match(_NOT_NAME, n)):
                kept.add(n)
            continue
        n = _trim_glued(n)
        if not _CJK_NAME.fullmatch(n) or len(n) < 3:
            continue
        if n in _NOT_PERSON or n[0] in _NER_BAD_FIRST or _NER_BAD_INNER & set(n[1:]) or "云云" in n:
            continue
        if "伊" in n and not _yi_name_ok(n, common_words):
            continue
        if n.endswith("之"):        # 「余梅之出資」「許北之」：後面的字黏上來
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
    p, d, a = party_roles(plaintiffs, defendants, agents)
    tags = {}
    for names, role in ((p, "原告"), (d, "被告"), (a, "代理人"), (list(others), "關係人")):
        for name, tag in _role_tags(names, role).items():
            tags.setdefault(name, tag)        # 同一個名字出現在兩種角色時，以前面的角色為準
    # 兩個字的姓（「頴川建忠」「頴川萬和」）：人名辨識有時只抓到「川欽和」，遮完會留下「頴【關係人1】」。
    # 這件判決裡已經有某個名字以「頴川」開頭時，「頴」＋「川欽和」也是同一個人，用同一個標籤
    heads = {n[:2] for n in tags if len(n) == 4}
    for name in [n for n in tags if len(n) == 3]:
        for head in heads:
            if head[1] == name[0] and head + name[1:] in text:
                tags.setdefault(head + name[1:], tags[name])
    # 長的名字先全部換掉，再換短的：「曾孫鄭宇峰」裡，誤判的「孫鄭」不會比「鄭宇峰」先換掉而切斷它。
    # 換的時候先放私用區的記號，最後才換成標籤：否則後面換短名字時，會換到前面已經放進去的標籤裡（「【被告】」裡的「被告」）
    codes = {name: f"{k}" for k, name in enumerate(tags)}
    for length in sorted({len(n) for n in tags}, reverse=True):
        text = _replace_names(text, {n: c for n, c in codes.items() if len(n) == length})
    order = list(tags)
    text = re.sub("([0-9]+)", lambda m: tags[order[int(m.group(1))]], text)
    return mask(text)[0]
