"""
Part 3 — 民事裁判書結構化欄位推導（純函式模組）

設計原則
────────
1. **純函式**：本模組不碰資料庫、不碰 HTML、不碰檔案系統。輸入是已解析的
   文字欄位（主文 / 事實及理由 / 理由 / 裁判字號 …），輸出是結構化欄位的
   dict。因此同一份輸入永遠得到同一份輸出，可完整重現、可單元測試。
2. **單一入口**：`derive_structured_fields(row)` 是唯一的對外入口。
   - `html_parser.parse_html()` 在解析當下呼叫它 → 新爬的資料自動帶結構化欄位
   - `backfill_structured.py` 對既有 DB 逐列呼叫它 → 舊資料回填
   兩條路徑共用同一份規則，不會產生「爬蟲版」與「回填版」不一致的問題。
3. **可稽核**：每個推導欄位都附帶來源標記（`*_source`）或品質旗標
   （`quality_flags`），讓下游分析知道哪些值是直接抽取、哪些是推論、
   哪些需要人工複查。

適用範圍：**民事**裁判書。刑事欄位（罪名、刑期）不在本模組範圍內。
"""

from __future__ import annotations

import json
import re
from typing import Dict, List, Optional, Tuple

# ═══════════════════════════════════════════════════════════════════════════
# 0. 中文數字轉換
# ═══════════════════════════════════════════════════════════════════════════

# 大寫（壹貳參…）與小寫（一二三…）共用一張表
_CN_DIGIT = {
    "〇": 0, "零": 0, "○": 0, "0": 0,
    "一": 1, "壹": 1, "1": 1,
    "二": 2, "貳": 2, "兩": 2, "2": 2,
    "三": 3, "參": 3, "叁": 3, "3": 3,
    "四": 4, "肆": 4, "4": 4,
    "五": 5, "伍": 5, "5": 5,
    "六": 6, "陸": 6, "6": 6,
    "七": 7, "柒": 7, "7": 7,
    "八": 8, "捌": 8, "8": 8,
    "九": 9, "玖": 9, "9": 9,
}
_CN_SMALL_UNIT = {"十": 10, "拾": 10, "百": 100, "佰": 100, "千": 1000, "仟": 1000}
_CN_BIG_UNIT = {"萬": 10**4, "億": 10**8, "兆": 10**12}

# 金額字串允許出現的字元（用來判斷一段文字是不是金額）。
# 必須包含小數點：不含的話，「2,000,000.5元」的 token 只能從小數點後面起算，
# 抓到的是「5元」——金額少了 40 萬倍，而且完全無聲（實測 13 筆主文含小數金額，
# 其中一筆 43,009,039.5 元會變成 5 元）。
_CN_NUM_CHARS = ("".join(_CN_DIGIT) + "".join(_CN_SMALL_UNIT)
                 + "".join(_CN_BIG_UNIT) + ",，.．")


def cn_numeral_to_int(raw: str) -> Optional[int]:
    """
    將中文 / 阿拉伯 / 混合寫法的數字字串轉為整數。

    支援：
      - 大寫國字：壹佰貳拾參萬肆仟伍佰陸拾柒 → 1234567
      - 小寫國字：一百二十三萬四千五百六十七 → 1234567
      - 阿拉伯數字：1,234,567 / 1234567 → 1234567
      - 混合寫法：21萬6201 → 216201、2,000萬 → 20000000
      - 十位簡寫：十五 → 15、二十 → 20

    無法解析時回傳 None（例如只剩「萬」而沒有數字的殘缺片段）。
    元以下（角、分）一律無條件捨去，因為判決主文的金額單位是「元」，
    小數部分在統計上無意義且會讓 int 型別失去意義。
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None

    # 先在「元」處截斷，元以下（角、分）一律捨去。
    # 必須先截斷再去除單位字，否則「貳佰捌拾伍元柒角」會被接成「貳佰捌拾伍柒」＝337。
    head = re.split(r"[元圓]", s)[0]
    if head.strip():
        s = head
    s = re.split(r"[角分]", s)[0]
    # 去掉千分位與空白
    s = re.sub(r"[,，\s元圓]", "", s)
    if not s:
        return None

    s = s.replace("．", ".")

    # 純阿拉伯數字（含小數）
    if re.fullmatch(r"\d+(?:\.\d+)?", s):
        return int(float(s))

    # 小數 + 單位（1.5億 / 2.5萬）。下面的中文位值解析是逐字累加的，
    # 碰到小數點會判定「有無法辨識的字元」而回傳 None，所以這種寫法單獨換算。
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([萬億兆千百十仟佰拾])", s)
    if m:
        unit = _CN_BIG_UNIT.get(m.group(2)) or _CN_SMALL_UNIT[m.group(2)]
        val = float(m.group(1)) * unit
        # 「000萬」這種殘缺片段換算出來是 0。0 不是金額，往下交給位值解析，
        # 由它回傳 None——回傳 0 等於憑空捏造一筆「0 元」的給付。
        if val > 0:
            return int(val)

    # 混合寫法的角分（「92萬0084.19元」）：小數部分是元以下，捨去後
    # 交給下面的位值解析處理整數部分。不特別處理的話整個 token 會因為
    # 含有小數點而解析失敗，金額整筆消失。
    m = re.fullmatch(r"(.+?)\.\d+", s)
    if m:
        s = m.group(1)

    # 全部字元都必須是可辨識的數字字元，否則視為無法解析
    if not all(ch in _CN_DIGIT or ch in _CN_SMALL_UNIT or ch in _CN_BIG_UNIT for ch in s):
        return None

    total = 0        # 已結算（遇到萬/億時累加）
    section = 0      # 當前小節（萬以下）
    number = 0       # 當前數字緩衝
    has_digit = False

    for ch in s:
        if ch in _CN_DIGIT:
            # 連續阿拉伯/國字數字視為位值串接（如「6201」＝6,2,0,1）
            number = number * 10 + _CN_DIGIT[ch]
            has_digit = True
        elif ch in _CN_SMALL_UNIT:
            unit = _CN_SMALL_UNIT[ch]
            # 「十五」開頭省略一 → 視為 1
            section += (number if number else 1) * unit
            number = 0
            has_digit = True
        elif ch in _CN_BIG_UNIT:
            unit = _CN_BIG_UNIT[ch]
            if section == 0 and number == 0:
                # 只剩「萬」而沒有任何數字 → 殘缺片段，無法解析。
                # 不可默默當成 1 萬，那會憑空捏造一個金額。
                return None
            total += (section + number) * unit
            section = 0
            number = 0
            has_digit = True

    if not has_digit:
        return None
    return total + section + number


# ═══════════════════════════════════════════════════════════════════════════
# 1. 案由代碼（裁判字號中的「字別」）與案件層級分類
# ═══════════════════════════════════════════════════════════════════════════

_CASE_KIND_RE = re.compile(r"年度\s*([^\s字]{1,10}?)\s*字第")

# 字別 → 案件層級。決定該案適不適合做「誰贏誰輸」的分類。
#   給付確認 : 第一審對審案件，主文是給付/確認宣告 → 適合分類輸贏
#   非對審   : 除權判決、公示催告、消債等，幾乎都會准，沒有真正的對造
#   上訴抗告 : 主文是「維持或推翻原判」，不是輸贏
#   家事形成 : 離婚、認領等形成判決，法院多會准，無輸贏概念
_NON_ADVERSARIAL = {"除", "催", "司消債核", "司消債更", "司消債清", "消債", "司催"}
_APPEAL_KINDS = {
    "簡上", "上易", "上", "小上", "再易", "再", "勞簡上", "家簡上", "金簡上",
    "建簡上", "保險簡上", "醫簡上", "消簡上", "重上", "抗", "勞抗", "家聲抗",
}
_FAMILY_FORMATIVE = {"婚", "親", "家婚", "家親", "重婚", "家聲", "養"}


def extract_case_kind(case_number: str) -> str:
    """從裁判字號取出字別，如「113年度訴字第123號」→「訴」。"""
    if not case_number:
        return ""
    m = _CASE_KIND_RE.search(case_number)
    return m.group(1).strip() if m else ""


# 發回更審的字別是在母字別後綴「更一」「更二」…（除更一、簡上更一、婚更一）。
# 更審不改變案件的性質，分類必須沿用母字別，否則「除更一」會從「非對審」
# 掉進「給付確認」，被算進勝訴率分母。
_RETRIAL_SUFFIX_RE = re.compile(r"更[一二三四五六七八九十百]+$")


def case_kind_category(kind: str) -> str:
    """字別 → 案件層級分類。未知字別以字尾規則推定，避免新字別靜默漏失。"""
    if not kind:
        return "未知"
    stripped = _RETRIAL_SUFFIX_RE.sub("", kind)
    if stripped and stripped != kind:
        return case_kind_category(stripped)
    if kind in _NON_ADVERSARIAL:
        return "非對審"
    if kind in _APPEAL_KINDS:
        return "上訴抗告"
    if kind in _FAMILY_FORMATIVE:
        return "家事形成"
    # 字尾推定：新字別（如「勞小上」）也能落到正確分類，不會掉進「未知」
    if kind.endswith(("簡上", "上", "抗")) and kind not in ("上",):
        return "上訴抗告"
    if kind.startswith("司消債") or kind.startswith("消債"):
        return "非對審"
    if kind.startswith("家") and kind.endswith(("婚", "親")):
        return "家事形成"
    return "給付確認"


# ═══════════════════════════════════════════════════════════════════════════
# 2. 主文前處理：切出「實體判項」，排除訴訟費用與假執行擔保
# ═══════════════════════════════════════════════════════════════════════════

# 抽金額時要排除的子句：訴訟費用、裁判費、假執行擔保金。
# 不排除的話「供擔保新臺幣 100 萬元」會被誤當成判准金額。
_AMOUNT_EXCLUDE_RE = re.compile(
    r"(訴訟費用|程序費用|裁判費|供擔保|預供擔保|免為假執行|擔保金額|"
    r"得假執行|不得假執行|本判決得|本判決第)"
)

# 判斷輸贏時要排除的子句：只排除「純程序性」子句。
# 這裡不能沿用上面那條嚴格規則——「原告之訴及假執行之聲請均駁回」含有
# 「假執行之聲請」，用嚴格規則會把整句丟掉，導致 795 筆敗訴案件的
# 主文被清空、結果變成空值。這是一個會造成靜默資料缺漏的陷阱。
_OUTCOME_EXCLUDE_RE = re.compile(
    r"^(?:訴訟費用|程序費用|第[一二三四五六七八九十\d]+審訴訟費用|"
    r"本判決|[一二三四五六七八九十\d、.]*本?判決第)")
_PURE_SECURITY_RE = re.compile(r"(供擔保|預供擔保|免為假執行|得假執行)")

_CLAUSE_SPLIT_RE = re.compile(r"[。；\n]+")

# 少數判決的「主文」欄位混入了後續的理由段落（段落標題辨識失敗所致）。
# 這些文字會帶進大量「應給付」「駁回」而汙染分類與金額抽取，
# 必須在結構化之前截斷。
_VERDICT_BLEED_RE = re.compile(
    r"(事實(?:及|與)理由|理\s*由\s*[一壹1]\s*[、.]|^\s*理\s*由\s*$|"
    r"按原告之訴|上列當事人間)", re.MULTILINE)


def clean_verdict(verdict: str) -> str:
    """截去混入主文欄位的理由段落。"""
    if not verdict:
        return ""
    m = _VERDICT_BLEED_RE.search(verdict)
    return verdict[: m.start()] if m and m.start() > 0 else verdict


def split_verdict_clauses(verdict: str) -> List[str]:
    """把主文切成子句。判項編號（一、二、1.）本身不切，靠句號切即可。"""
    if not verdict:
        return []
    text = re.sub(r"\s+", "", clean_verdict(verdict))
    return [c for c in _CLAUSE_SPLIT_RE.split(text) if c]


def substantive_clauses(verdict: str) -> List[str]:
    """抽金額用：排除訴訟費用與假執行擔保等含有干擾金額的子句。"""
    return [c for c in split_verdict_clauses(verdict) if not _AMOUNT_EXCLUDE_RE.search(c)]


def outcome_clauses(verdict: str) -> List[str]:
    """
    判輸贏用：只排除純程序性子句。

    一個子句只有在「談的是擔保/假執行，而且既沒有駁回也沒有實體給付」時
    才會被丟掉；「原告之訴及假執行之聲請均駁回」因為含有駁回而被保留。
    """
    out = []
    for c in split_verdict_clauses(verdict):
        if _OUTCOME_EXCLUDE_RE.search(c):
            continue
        # 只有「談的是擔保/假執行，而且不含任何實體內容」的子句才丟掉。
        # 實體內容不只有「應…給付」一種寫法：「聲請人以新臺幣13萬2千元為
        # 相對人供擔保後，…強制執行事件…准予停止執行」整句都是實體判項，
        # 只因為出現「供擔保」就被丟掉的話，結果會變成空值。
        if (_PURE_SECURITY_RE.search(c) and "駁回" not in c
                and not _GRANT_RE.search(c)
                and not _OTHER_GRANT_RE.search(c)
                and not _CONFIRM_GRANT_RE.search(c)
                and not _PARTITION_RE.search(c)):
            continue
        if _PROV_EXEC_ONLY_DISMISS_RE.match(c):
            continue
        out.append(c)
    return out


# ═══════════════════════════════════════════════════════════════════════════
# 3. 訴訟結果分類（本訴 / 反訴分離）
# ═══════════════════════════════════════════════════════════════════════════

# 准許類判項的動詞
_GRANT_VERBS = (r"給付|返還|交付|移轉|塗銷|遷讓|遷出|騰空|拆除|拆除|移除|辦理|履行|"
                r"協同|容忍|停止|除去|回復|支付|賠償|清償|開立|提出|登記|變賣|分配")

# 「應」與動詞之間的最大間隔。不動產類主文的受詞極長，例如
# 「應將臺北市○○區○○段000000000地號土地（權利範圍：10000分之435）及其上
#   …00號建物（門牌號碼…權利範圍：全部）移轉登記為…」——中間隔了 120 幾個字。
# 間隔設得太小會讓整個准許判項消失、案件掉進「其他/不明確」。
# 放寬是安全的：否定環視確保這段間隔沒有跨到「駁回」，且子句已先以「。；」切開。
_GRANT_GAP = 150

# 「應」與動詞之間常夾著受詞或限定語，例如
#   「被告應**將如附表所示之不動產**移轉登記予原告」
#   「被告應**於繼承被繼承人○○之遺產範圍內**給付原告…」
# 舊規則要求「應」後面直接接動詞，於是這兩種寫法全部漏掉（實測 288 筆被
# 誤歸為「其他/不明確」）。這裡允許最多 40 字的中介，但用否定環視確保
# 這段中介沒有跨到「駁回」，以免把「…之訴駁回」誤認成准許。
_GRANT_RE = re.compile(
    rf"應(?![^。；]{{0,{_GRANT_GAP}}}駁回)[^。；]{{0,{_GRANT_GAP}}}?(?:{_GRANT_VERBS})")
# 確認判項有兩種寫法：明示「確認…存在/不存在」，以及
# 「確認甲對被告有新臺幣381,192元…之債權」這種不帶「存在」二字的寫法。
# 只認前者會讓後者掉進「其他/不明確」。判項若以「確認」開頭且非駁回，
# 一律視為確認勝訴判項。
_CONFIRM_GRANT_RE = re.compile(
    r"(?:確認.{0,100}?(?:存在|不存在|無效|有效|成立|不成立|為真正)|"
    r"^[一二三四五六七八九十\d、.㈠-㈩]*確認(?![^。；]{0,60}駁回))")
# 分割共有物／分割遺產的主文寫法極為分歧，只認「准予分割」會漏掉
# 「准予合併分割」「分割由原告單獨取得」「分配予○○」等常見寫法。
_PARTITION_RE = re.compile(
    r"(?:准予(?:合併)?分割|應予(?:合併)?分割|分割方法|變價分割|原物分割|裁判分割|"
    r"應予(?:變價|原物|變賣)|分割由|分割為|分配予|分配與|分割如(?:附圖|附表|下)|"
    r"所示之?(?:不動產|土地|遺產)分割|所示方法分割|方法分割|分割方式|"
    r"欄所示分割|應分割如|應按.{0,40}?分割|應依.{0,40}?方法分割|"
    r"所得價金由.{0,30}分配)")
# 只認「明確准許」的寫法。早期版本用裸的「撤銷」「准許」會把
# 「原告請求撤銷…之訴駁回」「不予准許」誤判成勝訴判項。
_OTHER_GRANT_RE = re.compile(
    r"(?:准予(?!分割)|准[^。；]{0,12}(?:離婚|終止收養|認領)|應予准許|應予撤銷|"
    r"(?:執行)?程序.{0,8}應予撤銷|不得執[^。]{0,40}強制執行)")

# 駁回類判項
_DISMISS_REST_RE = re.compile(r"(?:其餘|其他|逾此範圍|超過部分|其餘部分).{0,12}?(?:之訴)?.{0,8}?駁回")
_DISMISS_MAIN_RE = re.compile(r"(?<!反訴)(?:原告|上訴人|聲請人)?.{0,6}?之(?:訴|請求|聲請)[^。]{0,40}?駁回")
_DISMISS_ANY_RE = re.compile(r"駁回")
_COUNTER_DISMISS_RE = re.compile(r"反訴[^。]{0,40}?駁回")

# 非終局判項（承受訴訟、移送管轄、更正、補充判決、命補繳裁判費、停止程序）
_NON_FINAL_RE = re.compile(
    r"(承受訴訟|移送.{0,8}管轄|移送(?:臺灣|台灣)|更正為|應補充判決|補充判決為|"
    r"停止訴訟程序|裁定更正|繳納.{0,8}裁判費|命.{0,6}補繳)")

_COUNTER_TOKEN_RE = re.compile(r"反訴")

# 「原告假執行之聲請駁回」只是不准假執行，不是實體請求被駁回。
# 把它當成敗訴判項會讓全部勝訴的案件被誤標成一部勝訴一部敗訴。
# 但「原告之訴及假執行之聲請均駁回」同時駁回實體請求，必須保留。
_PROV_EXEC_ONLY_DISMISS_RE = re.compile(
    r"^[一二三四五六七八九十\d、.㈠-㈩]*(?:原告|被告|反訴原告)?(?:其餘)?假執行之聲請(?:均)?駁回$")

# 結果標籤（與既有資料集詞彙一致，確保可比較）
WIN = "勝訴"
PARTIAL = "一部勝訴一部敗訴"
LOSE = "敗訴"
CONFIRM_WIN = "確認勝訴"
PARTITION = "分割類"
OTHER = "其他/不明確"
NON_FINAL = "非終局"


def _any(pattern: re.Pattern, clauses: List[str]) -> bool:
    """
    逐子句比對，**不可先把子句接起來再比對**。

    _GRANT_RE 用否定環視排除「…駁回」，這個環視是以子句為範圍設計的。
    若先 join 再比對，「被告應給付原告26,000元」與「原告其餘之訴駁回」會
    黏成一句，環視就看見了不屬於該判項的「駁回」，准許判項整個消失，
    一部勝訴的案件被誤判為敗訴（實測 92 筆）。
    """
    return any(pattern.search(c) for c in clauses)


def _classify_side(clauses: List[str], is_counter: bool) -> str:
    """對單一側（本訴或反訴）的判項集合分類。"""
    if not clauses:
        return ""

    has_grant = _any(_GRANT_RE, clauses)
    has_confirm = _any(_CONFIRM_GRANT_RE, clauses)
    has_partition = _any(_PARTITION_RE, clauses)
    has_other_grant = _any(_OTHER_GRANT_RE, clauses)
    has_rest_dismiss = _any(_DISMISS_REST_RE, clauses)

    any_grant = has_grant or has_confirm or has_partition or has_other_grant

    if _any(_NON_FINAL_RE, clauses) and not any_grant:
        return NON_FINAL

    if is_counter:
        full_dismiss = _any(_COUNTER_DISMISS_RE, clauses) and not has_rest_dismiss
    else:
        full_dismiss = _any(_DISMISS_MAIN_RE, clauses) and not has_rest_dismiss

    if any_grant and has_rest_dismiss:
        return PARTIAL
    if any_grant and not full_dismiss:
        # 分割共有物與確認之訴各自成類，因為它們沒有「請求金額 vs 判准金額」
        # 的比例概念，混進「勝訴」會汙染金額分析的分母。
        if has_partition:
            return PARTITION
        if has_confirm and not has_grant:
            return CONFIRM_WIN
        return WIN
    if full_dismiss and not any_grant:
        return LOSE
    if any_grant and full_dismiss:
        # 同時有准許與全部駁回 → 通常是「先位駁回、備位准許」
        return PARTIAL
    if _any(_DISMISS_ANY_RE, clauses) and not any_grant:
        return LOSE
    return OTHER


def classify_outcome(verdict: str, kind_category: str = "給付確認") -> Dict[str, str]:
    """
    分類訴訟結果。

    回傳：
      outcome        本訴結果（僅在「給付確認」層級才有值）
      main_outcome   本訴結果（同 outcome，明確命名）
      counter_outcome 反訴結果（無反訴時為空字串）
      has_counterclaim 是否有反訴
    """
    result = {
        "outcome": "",
        "main_outcome": "",
        "counter_outcome": "",
        "has_counterclaim": 0,
    }
    if not verdict:
        return result

    clauses = outcome_clauses(verdict)
    if not clauses:
        return result

    has_counter = any(_COUNTER_TOKEN_RE.search(c) for c in clauses)
    result["has_counterclaim"] = 1 if has_counter else 0

    if has_counter:
        main_clauses, counter_clauses = [], []
        for c in clauses:
            if _COUNTER_TOKEN_RE.search(c):
                counter_clauses.append(c)
                # 「原告之訴及被告之反訴均駁回」這類子句同時提到兩造，
                # 必須同時計入本訴，否則本訴結果會靜默漏失。
                #
                # 但要先把「反訴原告」「反訴被告」整個詞拿掉再判斷：
                # 「反訴原告之訴駁回」裡的「原告」是反訴原告，不是本訴原告。
                # 不先剝除的話，本訴全部勝訴的案件會因為反訴被駁回而
                # 被誤判成一部勝訴一部敗訴（實測 24 筆）。
                stripped = c.replace("反訴原告", "").replace("反訴被告", "").replace("反訴", "")
                if re.search(r"(?:原告|本訴)", stripped):
                    main_clauses.append(c)
            else:
                main_clauses.append(c)
        main = _classify_side(main_clauses, is_counter=False)
        counter = _classify_side(counter_clauses, is_counter=True)
    else:
        main = _classify_side(clauses, is_counter=False)
        counter = ""

    result["main_outcome"] = main
    result["counter_outcome"] = counter
    # 僅「給付確認」層級的案件才輸出 outcome，其餘留空以免誤用
    result["outcome"] = main if kind_category == "給付確認" else ""
    return result


# ── 上訴審結果（維持 / 廢棄）─────────────────────────────────────────────
_APPEAL_DISMISS_RE = re.compile(r"上訴(?:及.{0,12})?駁回|抗告駁回")
# 「原判決…廢棄」中間會逐項列出被廢棄的範圍（金額、利息起算日、假執行宣告、
# 訴訟費用裁判），實測距離可達 168 字，原本的 .{0,40} 視窗會整批漏掉：
# 549 筆上訴抗告中有 51 筆（9.3%）因此被判成「上訴駁回」而非「一部廢棄」，
# 讓「一部廢棄」少算 54%。改以「同一句內」為界（不跨 。），既涵蓋長列舉，
# 又不會把上一句的「原判決」和下一句的「廢棄」湊成一對。
_APPEAL_REVERSE_RE = re.compile(r"(?:原判決|原裁定)[^。]{0,300}?(?:廢棄|撤銷)")


def classify_appeal_outcome(verdict: str) -> str:
    """上訴/抗告案件的結果：上訴駁回（維持原判）／原判決廢棄／一部廢棄。"""
    if not verdict:
        return ""
    text = re.sub(r"\s+", "", verdict)
    reverse = bool(_APPEAL_REVERSE_RE.search(text))
    dismiss = bool(_APPEAL_DISMISS_RE.search(text))
    if reverse and dismiss:
        return "一部廢棄"
    if reverse:
        return "原判決廢棄"
    if dismiss:
        return "上訴駁回"
    return ""


# ═══════════════════════════════════════════════════════════════════════════
# 4. 給付類型與幣別
# ═══════════════════════════════════════════════════════════════════════════

_CURRENCY_MAP = {
    "新臺幣": "TWD", "新台幣": "TWD", "台幣": "TWD", "NT$": "TWD", "NT": "TWD",
    "美金": "USD", "美元": "USD", "US$": "USD",
    "人民幣": "CNY", "日圓": "JPY", "日幣": "JPY", "歐元": "EUR",
    "港幣": "HKD", "英鎊": "GBP", "澳幣": "AUD", "加幣": "CAD", "韓元": "KRW",
}
_CURRENCY_RE = re.compile("(" + "|".join(sorted(
    (re.escape(k) for k in _CURRENCY_MAP), key=len, reverse=True)) + ")")

# 與 _GRANT_RE 同樣允許「應」與動詞之間夾受詞（「應於繼承…範圍內給付」）
_MONEY_VERB_RE = re.compile(
    r"應(?![^。；]{0,40}駁回)[^。；]{0,40}?(?:給付|返還|賠償|支付|清償)")
_NON_MONEY_VERB_RE = re.compile(
    r"應(?![^。；]{0,40}駁回)[^。；]{0,40}?(?:交付|移轉|塗銷|遷讓|拆除|辦理|協同|容忍|停止|除去|回復|登記|開立|提出)")


def extract_relief_type(verdict: str) -> str:
    """
    判別主文的給付類型。這是把「不該有金額的案件」移出金額分母的關鍵欄位：
    形成判決、意思表示判決、不作為判決本來就沒有金額，不能算成「抽取失敗」。
    """
    if not verdict:
        return ""
    clauses = outcome_clauses(verdict)
    joined = "".join(clauses)
    if not joined:
        return ""

    types = []
    # 「返還」「給付」等動詞本身不足以判定是金錢給付——
    # 「被告應返還原告如附表所示之虛擬資產」用的也是「返還」。
    # 必須該判項裡真的出現「…元」的金額，才算金錢給付；否則這些案件
    # 會被誤列進金額分母，變成假的「抽取失敗」。
    if any(_MONEY_VERB_RE.search(c) and re.search(r"\d|[零壹貳參肆伍陸柒捌玖拾佰仟萬]", c)
           and "元" in c for c in clauses):
        types.append("金錢給付")
    if _NON_MONEY_VERB_RE.search(joined):
        types.append("非金錢給付")
    if _CONFIRM_GRANT_RE.search(joined):
        types.append("確認")
    if _PARTITION_RE.search(joined):
        types.append("形成（分割）")
    if re.search(r"(?:准.{0,6}離婚|離婚|認領|終止收養|改定.{0,8}親權)", joined):
        types.append("形成（身分）")
    if re.search(r"不得(?:為|執|使用|妨害|干擾)", joined):
        types.append("不作為")

    if not types:
        return "其他"
    return "／".join(dict.fromkeys(types))


def detect_currency(text: str) -> str:
    """回傳文字中出現的幣別代碼（多種時以 / 連接），沒有則預設 TWD。"""
    if not text:
        return ""
    found = dict.fromkeys(_CURRENCY_MAP[m] for m in _CURRENCY_RE.findall(text))
    return "/".join(found) if found else ""


# ═══════════════════════════════════════════════════════════════════════════
# 5. 金額抽取
# ═══════════════════════════════════════════════════════════════════════════

# 金額 token：阿拉伯（含千分位）、國字、或兩者混合（21萬6201）
_AMOUNT_TOKEN = rf"[{re.escape(_CN_NUM_CHARS)}]{{1,24}}"
# 幣別可選（「新臺幣（下同）」之後的金額會省略幣別），後面必須接「元」
_AMOUNT_RE = re.compile(
    rf"(?:(?P<cur>{'|'.join(sorted((re.escape(k) for k in _CURRENCY_MAP), key=len, reverse=True))})\s*)?"
    rf"(?:（下同）|\(下同\))?\s*"
    rf"(?P<num>{_AMOUNT_TOKEN})\s*元"
)

# 「應給付」之後到金額之間允許的距離（字元）。超過此距離代表金額多半屬於
# 另一個子句（例如利息起算日後面的另一筆數字），不應歸入本判項。
_AMOUNT_WINDOW = 60

_TABLE_REF_RE = re.compile(r"附表|附件|如附")


def _iter_amounts_in_clause(clause: str, default_currency: str = "TWD") -> List[Dict]:
    """
    在一段文字內抽出所有給付金額。

    視窗處理的兩個重點：
      1. 視窗在「及自…起」「按週年利率」處截斷——利息子句裡的數字
         （日期、利率）不是給付金額。
      2. 視窗**不得跨到下一個給付動詞**。否則
         「被告甲應給付10萬元、被告乙應給付20萬元」中，20萬會先被第一個
         視窗吃進去、再被第二個視窗吃一次，總額憑空多算一倍。
         同時用絕對位置去重，雙重保險。
    """
    verbs = list(_MONEY_VERB_RE.finditer(clause))
    out: List[Dict] = []
    seen_spans: set = set()

    for i, vm in enumerate(verbs):
        start = vm.end()
        # 視窗右界：下一個給付動詞的起點 與 固定視窗長度，取較小者
        hard_stop = verbs[i + 1].start() if i + 1 < len(verbs) else len(clause)
        stop = min(start + _AMOUNT_WINDOW, hard_stop, len(clause))
        if stop <= start:
            continue
        window = clause[start:stop]

        # 截斷點有兩類：
        #   利息子句（及自…起 / 按週年利率）——後面的數字是日期與利率
        #   明細子句（及其中…元 / 內含…元）——「其中」之後的金額是**本金拆解**，
        #     不是另一筆給付。不截斷的話「給付70萬8,932元，及其中51萬3,935元自…」
        #     會被加總成 122 萬，憑空多出一半。
        cut = re.search(r"及自|自民國|按(?:週|年)|其中|內含|包含|含.{0,4}元", window)
        if cut:
            window = window[: cut.start()]

        for am in _AMOUNT_RE.finditer(window):
            span = (start + am.start(), start + am.end())
            if span in seen_spans:
                continue
            num = cn_numeral_to_int(am.group("num"))
            if num is None or num <= 0:
                continue
            seen_spans.add(span)
            cur = _CURRENCY_MAP.get(am.group("cur"), default_currency) if am.group("cur") else default_currency
            out.append({"amount": num, "currency": cur, "raw": am.group(0).strip()})
    return out


# 不真正連帶的「重複給付免責」條款。
#
# 數人基於**不同法律原因**對同一債權人負同一給付（例：保險人依保險契約、
# 加害人依侵權行為）時，法律沒有「連帶」的明文可援用，主文因此不能寫「連帶」，
# 只能分列各項、再用一句話講明重複給付的效果：
#     「前二項給付，如任一被告為給付，其餘被告於給付範圍內，免除給付責任。」
# 兩個判項各有金額，但原告只能拿一次——把它們加起來會憑空多一倍
# （實測 111 年度訴字第 4265 號：440,897 × 2 被算成 881,794）。
#
# 真正連帶（民法 §272）不受影響：主文寫成「被告甲、乙應連帶給付…10 萬元」，
# 只有一個給付動詞、一筆金額，本來就只會抽到一次。
_JOINT_RELEASE_RE = re.compile(
    r"(?:任一|其中一|其中任一|任何一|之一)(?:人|造|被告|債務人)?[^。；]{0,40}?(?:已)?為給付"
    r"[^。；]{0,60}?(?:他|其他|其餘|另)[^。；]{0,25}?(?:同免|免除|免)[^。；]{0,12}?給付"
)


def extract_awarded_amounts(verdict: str) -> Dict:
    """
    從主文抽出判准金額。

    與舊版規則的差異（以及為什麼）：
      1. **抽全部判項而非只抽第一筆**。多被告／多原告／本金與違約金分列時，
         只取第一筆會系統性低估總額（實測 14.2% 的案件受影響）。
      2. **先剔除訴訟費用與假執行擔保子句**，避免把擔保金誤當判准金額。
      3. **記錄幣別**，外幣案件不再被當成抽取失敗。
      4. **標記附表**，金額寫在附表裡的案件明確標為 `附表` 而非空值。

    回傳 items（明細）、total（同幣別合計）、currency、n_items、flags。
    """
    res = {
        "awarded_items": [],
        "awarded_total": None,
        "awarded_currency": "",
        "awarded_n_items": 0,
        "awarded_in_table": 0,
        "awarded_joint_release": 0,
    }
    if not verdict:
        return res

    clauses = substantive_clauses(verdict)
    if not clauses:
        return res

    # 「新臺幣（下同）」宣告後，後續金額省略幣別仍是新臺幣
    declared = detect_currency("".join(clauses)) or "TWD"
    default_cur = declared.split("/")[0]

    items: List[Dict] = []
    for c in clauses:
        if _MONEY_VERB_RE.search(c):
            if _TABLE_REF_RE.search(c):
                res["awarded_in_table"] = 1
            items.extend(_iter_amounts_in_clause(c, default_cur))

    if not items:
        return res

    res["awarded_items"] = items
    res["awarded_n_items"] = len(items)
    currencies = dict.fromkeys(i["currency"] for i in items)
    res["awarded_currency"] = "/".join(currencies)

    # 重複給付免責條款只有在抽到多筆金額時才造成重複計算：單筆時總額就是那一筆，
    # 沒有東西可加，作廢反而會丟掉好資料（實測 31 筆命中中有 5 筆是單筆）。
    if len(items) > 1 and _JOINT_RELEASE_RE.search(re.sub(r"\s+", "", verdict)):
        res["awarded_joint_release"] = 1

    # 只有單一幣別才合計；混幣不做匯率換算，避免捏造數字。
    # 重複給付免責同理：實際總額取決於免責範圍（實測 26 筆中有 14 筆各判項
    # 金額不同，屬部分重疊），去重或取最大值都是猜測——留空並以旗標說明。
    if len(currencies) == 1 and not res["awarded_joint_release"]:
        res["awarded_total"] = sum(i["amount"] for i in items)
    return res


# ── 請求金額 ─────────────────────────────────────────────────────────────
# 聲明段落的定位錨點，依可靠度排序。
#
# 只用寬鬆的「聲明[：]」會命中程序段落裡引用法條的句子，例如
# 「按訴狀送達後…但擴張或減縮應受判決事項之**聲明**者，不在此限」，
# 於是抓到的是舊聲明或管轄權論述裡的數字，造成「判准大於請求」的矛盾。
# 因此先找明確的錨點，找不到才退而求其次，且要求該段落後方真的出現金額。
_CLAIM_ANCHORS = [
    re.compile(r"訴之聲明\s*[:：]?"),
    re.compile(r"變更後聲明\s*[:：]?"),
    re.compile(r"並\s*聲明\s*[:：]"),
    re.compile(r"聲明\s*[:：]"),
]
# 錨點後方必須在合理距離內出現「給付…元」，否則視為誤命中
_CLAIM_VALIDATE_RE = re.compile(r"(?:給付|返還|賠償|支付|清償)[^。]{0,60}?元")
_AS_VERDICT_RE = re.compile(r"如主文(?:第[一二三四五六七八九十\d]+項)?所示")
# 聲明段落中的編號符號，先剝除才能正確判斷「如主文所示」是否為整段內容
_ENUM_PREFIX_RE = re.compile(r"^[\s\d一二三四五六七八九十㈠-㈩\(（][\s\d一二三四五六七八九十㈠-㈩\)）.、,]*")


def extract_claimed_amount(
    facts_and_reasons: str,
    facts: str,
    awarded_total: Optional[int],
    outcome: str,
) -> Dict:
    """
    抽取請求金額，**並明確標記來源**。

    這是舊版最危險的缺陷：全部勝訴且聲明寫「如主文所示」時，請求金額是用
    判准金額回推的。實測 4,425 筆兩欄皆有值的案件中，有 3,391 筆（76.6%）
    兩者相等。若不標記來源就拿去算「獲償比例＝判准/請求」，這些案件會一律
    得到 100%，屬於循環論證，會嚴重高估法院的准許程度。

    claimed_source 取值：
      直接抽取  — 從聲明段落實際讀到金額
      主文回推  — 聲明寫「如主文所示」且全部勝訴，以判准金額代入
      未取得    — 兩者皆不可得
    """
    res = {"claimed_total": None, "claimed_currency": "", "claimed_source": "未取得",
           "claimed_n_items": 0}

    body = facts_and_reasons or facts or ""
    if body:
        text = re.sub(r"\s+", "", body)
        seg = ""
        for anchor in _CLAIM_ANCHORS:
            for am in anchor.finditer(text):
                cand = text[am.end(): am.end() + 1500]
                # 錨點後 300 字內要看得到「給付…元」，才認定這是真的聲明段落
                if _CLAIM_VALIDATE_RE.search(cand[:300]) or _AS_VERDICT_RE.search(cand[:200]):
                    seg = cand
                    break
            if seg:
                break
        if not seg:
            seg = text[:1500]
        seg = _ENUM_PREFIX_RE.sub("", seg)

        default_cur = (detect_currency(seg) or "TWD").split("/")[0]
        # 聲明段落與主文使用同一套金額抽取邏輯，確保兩邊的口徑一致——
        # 口徑不一致的話，「獲償比例」這個比值就沒有意義。
        items = _iter_amounts_in_clause(seg, default_cur)
        if items:
            currencies = dict.fromkeys(i["currency"] for i in items)
            res["claimed_n_items"] = len(items)
            res["claimed_currency"] = "/".join(currencies)
            if len(currencies) == 1:
                res["claimed_total"] = sum(i["amount"] for i in items)
                res["claimed_source"] = "直接抽取"
                return res

        # 聲明寫「如主文所示」→ 只有全部勝訴時，請求金額才等於判准金額
        if _AS_VERDICT_RE.search(seg[:200]) and outcome == WIN and awarded_total:
            res["claimed_total"] = awarded_total
            res["claimed_currency"] = "TWD"
            res["claimed_source"] = "主文回推"
            return res

    if awarded_total and outcome == WIN:
        res["claimed_total"] = awarded_total
        res["claimed_currency"] = "TWD"
        res["claimed_source"] = "主文回推"
    return res


# ═══════════════════════════════════════════════════════════════════════════
# 6. 法條引用結構化
# ═══════════════════════════════════════════════════════════════════════════

# 法規名白名單。採「最長後綴匹配」而非「切連接詞」：
# 舊規則用 [^\s，；、（(]{1,15} 貪婪往左吃字，於是「原告依民法」「爰依民事訴訟法」
# 「訴訟費用負擔之依據：民事訴訟法」都被當成法規名（實測 3.9% 髒值）。
# 白名單一旦建立，法規名就只可能是清單內的值，髒值在結構上不可能發生。
LAW_WHITELIST = {
    # 基本法典
    "民法", "民事訴訟法", "民事訴訟法施行法", "刑法", "刑事訴訟法", "憲法",
    "行政訴訟法", "行政程序法", "行政執行法", "強制執行法", "非訟事件法",
    "家事事件法", "涉外民事法律適用法", "法院組織法", "提存法", "公證法", "律師法",
    "民法總則施行法", "民法債編施行法", "民法物權編施行法",
    "民法親屬編施行法", "民法繼承編施行法",
    # 民事特別法
    "公司法", "商業登記法", "商業會計法", "票據法", "海商法", "保險法",
    "證券交易法", "期貨交易法", "銀行法", "信託法", "仲裁法", "企業併購法",
    "金融機構合併法", "金融消費者保護法", "證券投資信託及顧問法",
    "動產擔保交易法", "電子支付機構管理條例", "信用合作社法",
    "消費者債務清理條例", "洗錢防制法", "詐欺犯罪危害防制條例",
    # 土地/不動產
    "土地法", "土地法施行法", "土地登記規則", "平均地權條例", "土地稅法",
    "公寓大廈管理條例", "不動產經紀業管理條例", "都市計畫法", "都市更新條例",
    "建築法", "住宅法", "租賃住宅市場發展及管理條例", "國民住宅條例", "房屋稅條例",
    # 消費者/競爭/智財
    "消費者保護法", "公平交易法", "個人資料保護法", "著作權法", "專利法",
    "商標法", "營業秘密法", "政府採購法",
    # 勞動
    "勞動基準法", "勞動基準法施行細則", "勞動事件法", "勞工退休金條例",
    "勞工保險條例", "就業服務法", "職業安全衛生法", "職業災害勞工保護法",
    "性別平等工作法", "性別工作平等法", "大量解僱勞工保護法", "工會法",
    "團體協約法", "勞資爭議處理法", "勞工請假規則", "勞工職業災害保險及保護法",
    # 身分/家事
    "兒童及少年福利與權益保障法", "兒童及少年性剝削防制條例",
    "家庭暴力防治法", "性侵害犯罪防治法", "姓名條例", "戶籍法", "國籍法",
    "司法院釋字第七四八號解釋施行法",
    # 醫療/交通/保險
    "醫療法", "醫師法", "藥事法", "護理人員法",
    "道路交通管理處罰條例", "道路交通安全規則", "強制汽車責任保險法",
    "國家賠償法", "冤獄賠償法", "刑事補償法",
    # 兩岸/涉外
    "臺灣地區與大陸地區人民關係條例", "香港澳門關係條例",
    # 稅務/其他
    "所得稅法", "稅捐稽徵法", "遺產及贈與稅法", "加值型及非加值型營業稅法",
    "電信法", "電信管理法", "公路法", "民用航空法", "鐵路法",
    "農業發展條例", "水利法", "森林法", "漁業法", "礦業法",
    "人民團體法", "政黨法", "會計師法", "農會法", "漁會法",
    "全民健康保險法", "就業保險法", "老人福利法", "身心障礙者權益保障法",
    "社會秩序維護法", "警察職權行使法", "公務人員保障法", "國軍老舊眷村改建條例",
}

# 常見簡稱 → 正式名稱。不做正規化的話，「勞基法」（1,370 次）與
# 「勞動基準法」（373 次）會被統計成兩個不同的法規，所有法條分析都會被拆散。
LAW_ALIASES = {
    "勞基法": "勞動基準法",
    "勞基法施行細則": "勞動基準法施行細則",
    "勞退條例": "勞工退休金條例",
    "勞事法": "勞動事件法",
    "消保法": "消費者保護法",
    "消債條例": "消費者債務清理條例",
    "個資法": "個人資料保護法",
    "國賠法": "國家賠償法",
    "證交法": "證券交易法",
    "金保法": "金融消費者保護法",
    "性平法": "性別平等工作法",
    "兩性工作平等法": "性別工作平等法",
    "公交法": "公平交易法",
    "家暴法": "家庭暴力防治法",
    "民訴法": "民事訴訟法",
    "強執法": "強制執行法",
    "道交條例": "道路交通管理處罰條例",
    "強制險法": "強制汽車責任保險法",
    "健保法": "全民健康保險法",
    "公寓大廈條例": "公寓大廈管理條例",
    "政採法": "政府採購法",
}

_ALL_LAW_KEYS = sorted(set(LAW_WHITELIST) | set(LAW_ALIASES), key=len, reverse=True)
_LAW_NAME_RE = re.compile("(" + "|".join(re.escape(k) for k in _ALL_LAW_KEYS) + ")$")

# 條文引用主體：第X條[之Y][第Z項][第W款][前段/後段/但書/本文]
_NUM = r"[\d〇零○一二三四五六七八九十百千]+"
_CITATION_RE = re.compile(
    rf"第\s*(?P<article>{_NUM})\s*條"
    rf"(?:\s*之\s*(?P<sub>{_NUM}))?"
    rf"(?:\s*第\s*(?P<para>{_NUM})\s*項)?"
    rf"(?:\s*第\s*(?P<item>{_NUM})\s*款)?"
    rf"(?:\s*(?P<pos>前段|後段|但書|本文|中段))?"
)

# 「同法」「同條例」回指
_SAME_LAW_RE = re.compile(r"同(?:法|條例|規則|辦法)$")

# 這些詞出現在「第X條」之前，代表那是契約條款、章程、規約，不是法規
_CONTRACT_CTX_RE = re.compile(
    r"(契約|條款|章程|規約|約定|協議|合約|辦法|須知|規章|會員|保單|公約書|管理規約)$")

# 法規名最長字數（防呆）：實務上最長的法規名不超過 30 字
_MAX_LAW_NAME = 30


def _resolve_law_name(prefix: str, last_law: Optional[str]) -> Optional[str]:
    """
    由引用位置往左解析法規名。

    策略（依序）：
      1. 白名單最長後綴匹配 → 命中即為法規名（「原告依民法」→「民法」）
      2. 「同法／同條例」→ 回指前一個具名法規
      3. 契約條款脈絡 → 回傳 None（排除「會員條款第7條」這類非法規引用）
      4. 緊接「、」「及」「暨」等連接詞 → 沿用前一個法規（處理
         「民法第184條第1項前段、第185條」這種串接引用）
    """
    tail = prefix[-_MAX_LAW_NAME:]

    m = _LAW_NAME_RE.search(tail)
    if m:
        name = m.group(1)
        return LAW_ALIASES.get(name, name)

    if _SAME_LAW_RE.search(tail):
        return last_law

    if _CONTRACT_CTX_RE.search(tail):
        return None

    # 串接引用：「…第184條第1項前段、第185條」
    if last_law and re.search(r"[、,，]\s*$|[及暨與或]\s*$|項\s*$|款\s*$|段\s*$|條\s*$", tail):
        return last_law

    return None


def extract_law_citations(*texts: str) -> List[Dict]:
    """
    從判決本文抽出結構化的法條引用。

    與舊版規則最關鍵的差異：**改從判決本文（理由／事實及理由）抽取，
    而不是只讀司法院頁尾的「適用法條」欄位**。舊做法的覆蓋率只有 34.8%，
    且缺的正好是第一審主力案件（「訴」字案只有 16.2%）；實測沒有「適用法條」
    欄位的 6,879 筆案件中，有 98.8% 的本文裡確實寫了「第X條」。

    另外新增 **項 / 款 / 前後段**。民法第184條第1項前段（過失侵權）、
    第1項後段（背俗故意）、第2項（違反保護他人之法律）是三個不同的請求權
    基礎，法官選哪一個正是法律見解的核心，壓成「民法184」會把資訊抹平。

    回傳依出現順序去重後的清單，每筆為
    {law, article, sub, paragraph, item, position, key}
    """
    out: List[Dict] = []
    seen = set()

    for text in texts:
        if not text:
            continue
        t = re.sub(r"[ \t　]+", "", text)
        last_law: Optional[str] = None
        for m in _CITATION_RE.finditer(t):
            law = _resolve_law_name(t[: m.start()], last_law)
            if not law:
                continue
            last_law = law

            article = cn_numeral_to_int(m.group("article"))
            if article is None or article <= 0:
                continue
            sub = cn_numeral_to_int(m.group("sub")) if m.group("sub") else None
            para = cn_numeral_to_int(m.group("para")) if m.group("para") else None
            item = cn_numeral_to_int(m.group("item")) if m.group("item") else None
            pos = m.group("pos") or ""

            # key 採法律人習慣的寫法，且各層級用不同字樣分隔，
            # 避免「第184條之1」與「第184條第1項」壓成同一個字串。
            key = f"{law}§{article}"
            if sub:
                key += f"之{sub}"
            if para:
                key += f"第{para}項"
            if item:
                key += f"第{item}款"
            if pos:
                key += pos

            if key in seen:
                continue
            seen.add(key)
            out.append({
                "law": law,
                "article": article,
                "sub": sub,
                "paragraph": para,
                "item": item,
                "position": pos,
                "key": key,
            })
    return out


# 純程序法。幾乎每一份民事判決都會在結尾引用民事訴訟法第78、79條
# （訴訟費用負擔），所以用「引用次數最多」挑主要法規的話，
# 九成以上的案件都會得到「民事訴訟法」，這個欄位就完全沒有資訊量。
# 挑主要法規時先排除程序法，挑出來的才是這個案子真正的請求權基礎。
PROCEDURAL_LAWS = {
    "民事訴訟法", "民事訴訟法施行法", "家事事件法", "非訟事件法",
    "法院組織法", "提存法", "公證法", "勞動事件法",
}


def _pick_primary_law(cites: List[Dict]) -> str:
    """
    選出案件的主要法規（請求權基礎所在的法典）。

    規則：先排除程序法，在剩下的實體法中取引用次數最多者；
    次數相同時取**最先出現**者（判決書論理習慣先寫主要依據）。
    全是程序法時才退回程序法，確保欄位不會因為排除而變空。
    """
    if not cites:
        return ""
    first_seen: Dict[str, int] = {}
    counts: Dict[str, int] = {}
    for i, c in enumerate(cites):
        counts[c["law"]] = counts.get(c["law"], 0) + 1
        first_seen.setdefault(c["law"], i)

    substantive = {k: v for k, v in counts.items() if k not in PROCEDURAL_LAWS}
    pool = substantive or counts
    return max(pool, key=lambda k: (pool[k], -first_seen[k]))


# ═══════════════════════════════════════════════════════════════════════════
# 7. 法官拆分與角色標記
# ═══════════════════════════════════════════════════════════════════════════

# judges 欄位以全形分號分隔（html_parser._extract_judges_and_clerk 的輸出格式）。
# 用頓號切會完全失效——這是實務上很容易踩到的坑。
_JUDGE_SPLIT_RE = re.compile(r"[；;、,，/｜|]+")

# 中文姓名長度 2–4 字。超出此範圍的一定不是姓名。
_JUDGE_NAME_RE = re.compile(r"^[一-鿿]{2,4}$")

# 判決書後面常附筆錄或譯文，裡面出現「法官」二字後接對話，上游的
# _extract_judges_and_clerk 會把那些文字當成姓名抓進來，例如
# 「今日筆錄記載」「政治傾向為你」「准一造辯論判」。這些垃圾值會讓
# judge_profile 憑空多出不存在的「法官」，必須在此濾掉。
_JUDGE_NOISE_WORDS = re.compile(
    r"(筆錄|辯論|宣判|宣示|延展|提示|原證|當庭|可否|是否|傾向|判決|本件|本院|"
    r"對於|今日|上訴|抗告|訴訟|原告|被告|聲請|法官|書記|命令|裁定|期日|到場)")


def _is_plausible_judge_name(name: str) -> bool:
    """姓名必須是 2–4 個中文字，且不含明顯的程序用語。"""
    return bool(_JUDGE_NAME_RE.match(name)) and not _JUDGE_NOISE_WORDS.search(name)


def split_judges(judges: str, full_text: str = "") -> List[Dict]:
    """
    拆分法官欄位並標記角色。

    角色只分「獨任 / 審判長 / 陪席」三種，依據是判決書簽名欄的實際標示
    （「審判長法官○○○」）。**不推定「受命法官」**，因為判決書簽名欄
    不標示受命法官，任何推定都是捏造。
    """
    if not judges:
        return []
    names = [n.strip() for n in _JUDGE_SPLIT_RE.split(judges) if n.strip()]
    names = [n for n in names if _is_plausible_judge_name(n)]
    if not names:
        return []

    presiding = set()
    if full_text:
        # 姓名內允許水平空白但**不得跨行**。用 \s* 會讓貪婪匹配從
        # 「審判長法 官 姜悌文\n法 官 賴錦華」一路吃到下一行，
        # 於是抓到「姜悌文法官賴錦」這種不存在的姓名，審判長就永遠對不上。
        for m in re.finditer(
                r"審判長[^\S\n]*法[^\S\n]*官[^\S\n]*([一-鿿](?:[^\S\n]*[一-鿿]){1,5})",
                full_text):
            presiding.add(re.sub(r"\s+", "", m.group(1)))

    out = []
    for idx, n in enumerate(names):
        if len(names) == 1:
            role = "獨任"
        elif n in presiding:
            role = "審判長"
        else:
            role = "陪席"
        out.append({"name": n, "role": role, "seat": idx})

    # 保底：合議庭一定有審判長。若簽名欄沒抓到明示標記，
    # 依簽名慣例（審判長列首位）指定第一位，避免整庭都變成「陪席」。
    if len(out) > 1 and not any(j["role"] == "審判長" for j in out):
        out[0]["role"] = "審判長"
    return out


def panel_key(judges: str) -> str:
    """合議庭組合鍵（姓名排序後串接），用來分析「哪些法官常同庭」。"""
    parts = sorted(n.strip() for n in _JUDGE_SPLIT_RE.split(judges or "") if n.strip())
    return "|".join(parts)


# ═══════════════════════════════════════════════════════════════════════════
# 8. 案由正規化
# ═══════════════════════════════════════════════════════════════════════════

# 案由大類對照：依關鍵字比對，順序即優先序（先命中者勝）
#
# 「借貸／清償」原本是單一類別，佔臺北地院 2025 民事判決的 38.2%（4,024 筆）。
# 一個佔近四成的類別在法官分析裡形同沒有控制：銀行信用卡債（被告多半未到庭、
# 一造辯論、原告幾乎必勝）和自然人之間的借貸糾紛（爭點多、舉證困難）被歸成
# 同一類，用它當基準線來調整案件組合是無效的。因此拆成三類，
# 並把「債務人異議之訴」移出——那是強制執行救濟，根本不是借貸案件。
_CASE_TYPE_RULES: List[Tuple[str, str]] = [
    (r"除權判決|公示催告", "非訟／除權"),
    (r"消費者債務清理|更生|清算", "債務清理"),
    (r"債務人異議|第三人異議|分配表異議|撤銷.{0,6}執行", "強制執行救濟"),
    (r"離婚|夫妻|剩餘財產|贍養|婚姻|收養|認領|親權|扶養|監護", "身分／家事"),
    (r"繼承|遺產|遺囑|特留分", "繼承"),
    (r"薪資|工資|資遣|退休金|職業災害|勞動|解僱|確認僱傭", "勞動"),
    (r"簽帳卡|信用卡|現金卡|消費款", "信用卡／消費金融"),
    (r"票款|本票|支票|匯票", "票據"),
    (r"保險", "保險"),
    (r"分割共有物|共有物分割|拆屋還地|返還土地|所有權|地上權|抵押權|租賃|遷讓房屋|點交", "物權／不動產"),
    (r"侵權行為|損害賠償|車禍|醫療", "侵權"),
    (r"不當得利", "不當得利"),
    (r"借款|借貸|清償|墊款|債務|保證", "借貸／清償"),
    (r"買賣|承攬|委任|租金|工程款|貨款|服務費|報酬|契約|給付", "契約"),
    (r"確認", "確認"),
]

# 金融機構原告。同樣是「清償借款」，銀行告債務人與自然人之間的借貸
# 在證據結構與到庭率上差很多，不分開的話這個控制變數等於沒用。
_FINANCIAL_PLAINTIFF_RE = re.compile(
    r"(商業銀行|銀行|信用合作社|農會信用部|漁會信用部|資產管理|融資|租賃股份|"
    r"人壽保險|產物保險|證券|投信|票券|信用卡|星展|花旗|匯豐|渣打)")

_CASE_TYPE_NOISE_RE = re.compile(r"[（(].*?[)）]|等$|事件$")


def normalize_case_type(case_type: str, plaintiff: str = "") -> Tuple[str, str]:
    """
    案由正規化 + 大類歸屬。

    原始案由有 717 種，其中「損害賠償」「損害賠償等」「侵權行為損害賠償」
    其實是同一類。不合併的話，法官 × 案由的交叉分析會被稀釋到每格只有
    個位數，統計上做不出任何東西。

    `plaintiff` 用來把借貸案再分金融／民間兩類：同樣是「清償借款」，
    銀行告債務人（被告多半未到庭、一造辯論、原告幾乎必勝）與自然人之間的
    借貸糾紛差異極大，合成一類會讓案件組合調整失去意義。
    """
    if not case_type:
        return "", ""
    norm = _CASE_TYPE_NOISE_RE.sub("", str(case_type)).strip()
    norm = re.sub(r"[　\s]+", "", norm) or str(case_type).strip()
    for pat, cat in _CASE_TYPE_RULES:
        if re.search(pat, norm):
            if cat == "借貸／清償":
                return norm, ("金融借貸" if _FINANCIAL_PLAINTIFF_RE.search(plaintiff or "")
                              else "民間借貸")
            return norm, cat
    return norm, "其他"


# ═══════════════════════════════════════════════════════════════════════════
# 9. 程序特徵與當事人特徵（法官分析的控制變數）
# ═══════════════════════════════════════════════════════════════════════════

_CORP_RE = re.compile(r"(股份有限公司|有限公司|公司|銀行|商業銀行|合作社|基金會|協會|"
                      r"學會|工會|事務所|管理委員會|農會|漁會|社團法人|財團法人)")
_AGENT_SPLIT_RE = re.compile(r"[；;、,，]+")


def _agent_has_lawyer(agents: str, full_text: str) -> int:
    """
    判斷某造的代理人中是否有律師。

    不能直接在代理人欄位裡找「律師」二字：解析器（`_extract_parties`）只保留
    姓名，「律師」的職稱已經被剝掉了。早期版本就是這樣寫的，結果這兩個欄位
    **全部 10,561 筆都是 0**——看起來有值，實際上毫無資訊。

    正確做法是拿代理人姓名回全文比對，看該姓名後面是否緊接「律師」。
    這樣同時能正確排除法定代理人（「法定代理人 黃黎兼」後面沒有律師）。
    """
    if not agents or not full_text:
        return 0
    for name in _AGENT_SPLIT_RE.split(agents):
        name = name.strip()
        if len(name) < 2:
            continue
        if re.search(re.escape(name) + r"\s*律\s*師", full_text):
            return 1
    return 0
_DEFAULT_JUDGMENT_RE = re.compile(r"一造辯論")
_PROVISIONAL_RE = re.compile(r"得假執行")


def _cost_share_plaintiff(verdict: str) -> Optional[float]:
    """
    從主文的訴訟費用分擔推算原告負擔比例。

    訴訟費用比例是「一部勝訴的程度」最精確的代理變數：主文只說
    「一部勝訴一部敗訴」，但「由被告負擔百分之97」和「百分之3」是天差地別的
    結果。這個連續變數讓法官寬嚴程度可以被量化比較。
    """
    if not verdict:
        return None
    # 判決書混用全形％與半形%，不統一會讓「負擔50％」整批漏掉
    text = re.sub(r"\s+", "", verdict).replace("％", "%")
    # 「訴訟費用**新臺幣壹萬肆仟柒佰貳拾壹元**由被告負擔」這種寫法在
    # 「訴訟費用」與「由」之間夾了金額，要求兩者相鄰會整批漏掉。
    m = re.search(r"訴訟費用[^，。；]{0,30}?由(?P<who>[^，。；]{0,20}?)負擔(?P<frac>[^，。；]{0,24})", text)
    if not m:
        return None
    who, frac = m.group("who"), m.group("frac")

    # 主文寫比例的方式有四種，缺一種就會整批落空：
    #   百分之二十 / 20%  ·  千分之七  ·  二分之一  ·  5/100
    ratio = None
    fm = re.search(r"(?:百分之\s*|[\d.]+\s*%|%)\s*([\d〇零一二三四五六七八九十百]*)", frac)
    if re.search(r"百分之|%", frac):
        fm = re.search(r"(?:百分之\s*)([\d〇零一二三四五六七八九十百]+)", frac) \
             or re.search(r"([\d.]+)\s*%", frac)
        if fm:
            v = cn_numeral_to_int(fm.group(1))
            if v is not None and 0 <= v <= 100:
                ratio = v / 100.0
    elif "千分之" in frac:
        fm = re.search(r"千分之\s*([\d〇零一二三四五六七八九十百千]+)", frac)
        if fm:
            v = cn_numeral_to_int(fm.group(1))
            if v is not None and 0 <= v <= 1000:
                ratio = v / 1000.0
    else:
        fm = re.search(r"([\d一二三四五六七八九十百]+)分之([\d一二三四五六七八九十百]+)", frac)
        if fm:
            den = cn_numeral_to_int(fm.group(1))
            num = cn_numeral_to_int(fm.group(2))
            if den and num is not None and den > 0 and num <= den:
                ratio = num / den
        else:
            # 「負擔5/100」這種寫法：分子在前、分母在後，與國字「X分之Y」相反
            fm = re.search(r"(\d+)\s*/\s*(\d+)", frac)
            if fm:
                num, den = int(fm.group(1)), int(fm.group(2))
                if den > 0 and num <= den:
                    ratio = num / den

    if ratio is None:
        # 沒有比例 → 全部由某一方負擔
        ratio = 1.0 if "原告" in who else (0.0 if "被告" in who else None)
        return ratio

    # 主文寫的是「由某方負擔 X」，換算成原告負擔比例
    if "被告" in who:
        return round(1.0 - ratio, 4)
    if "原告" in who:
        return round(ratio, 4)
    return None


# ═══════════════════════════════════════════════════════════════════════════
# 10. 單一入口
# ═══════════════════════════════════════════════════════════════════════════

# 寫入 DB / 匯出 Excel 的結構化欄位（DB 欄位名 → SQLite 型別）
STRUCTURED_COLUMNS: List[Tuple[str, str]] = [
    ("case_kind",              "TEXT"),
    ("case_kind_category",     "TEXT"),
    ("outcome",                "TEXT"),
    ("main_outcome",           "TEXT"),
    ("counter_outcome",        "TEXT"),
    ("has_counterclaim",       "INTEGER"),
    ("appeal_outcome",         "TEXT"),
    ("relief_type",            "TEXT"),
    ("awarded_amount",         "INTEGER"),
    ("awarded_currency",       "TEXT"),
    ("awarded_n_items",        "INTEGER"),
    ("awarded_items_json",     "TEXT"),
    ("awarded_in_table",       "INTEGER"),
    ("claimed_amount",         "INTEGER"),
    ("claimed_currency",       "TEXT"),
    ("claimed_source",         "TEXT"),
    ("grant_ratio",            "REAL"),
    ("cost_share_plaintiff",   "REAL"),
    ("applicable_laws_json",   "TEXT"),
    ("law_n_citations",        "INTEGER"),
    ("law_primary",            "TEXT"),
    ("judges_json",            "TEXT"),
    ("judge_count",            "INTEGER"),
    ("presiding_judge",        "TEXT"),
    ("panel_key",              "TEXT"),
    ("case_type_norm",         "TEXT"),
    ("case_type_category",     "TEXT"),
    ("defendant_is_corp",      "INTEGER"),
    ("plaintiff_has_lawyer",   "INTEGER"),
    ("defendant_has_lawyer",   "INTEGER"),
    ("is_default_judgment",    "INTEGER"),
    ("has_provisional_exec",   "INTEGER"),
    ("reasoning_length",       "INTEGER"),
    ("quality_flags",          "TEXT"),
    ("structuring_version",    "TEXT"),
]

# 規則版本。規則異動時遞增，讓回填過的資料可以辨識是用哪一版規則產生的。
STRUCTURING_VERSION = "2.0.0"


def derive_structured_fields(row: Dict) -> Dict:
    """
    從一筆已解析的裁判書欄位推導出全部結構化欄位。

    row 需要（缺少者以空字串處理）：
      case_number, case_type, verdict, facts, facts_and_reasons, reasons,
      conclusion, applicable_laws, judges, full_text,
      defendant, plaintiff_agent, defendant_agent
    """
    g = lambda k: (row.get(k) or "") if isinstance(row, dict) else ""

    verdict = g("verdict")
    flags: List[str] = []

    # ── 案件層級 ──
    kind = extract_case_kind(g("case_number"))
    kind_cat = case_kind_category(kind)
    # 裁定（命補繳裁判費、承受訴訟、移送管轄…）的主文不是「誰贏誰輸」，
    # 硬套輸贏規則只會產生假資料，故獨立成一類、不輸出 outcome。
    if "裁定" in (g("judgment_type") or g("case_number")):
        kind_cat = "裁定"

    # ── 訴訟結果 ──
    oc = classify_outcome(verdict, kind_cat)
    appeal_outcome = classify_appeal_outcome(verdict) if kind_cat == "上訴抗告" else ""

    # ── 給付類型與金額 ──
    relief = extract_relief_type(verdict)
    aw = extract_awarded_amounts(verdict)
    cl = extract_claimed_amount(
        g("facts_and_reasons"), g("facts"), aw["awarded_total"], oc["outcome"])

    # ── 獲償比例：只在來源是「直接抽取」且幣別一致時才計算 ──
    grant_ratio = None
    # 幣別不同就無從比較。不標記的話，「判准 39,000 TWD / 請求 87 USD」
    # 這種列看起來像是判准遠大於請求，其實只是兩個幣別的數字放在一起。
    if (aw["awarded_currency"] and cl["claimed_currency"]
            and aw["awarded_currency"] != cl["claimed_currency"]):
        flags.append("判准與請求幣別不同")

    if (aw["awarded_total"] and cl["claimed_total"]
            and cl["claimed_source"] == "直接抽取"
            and aw["awarded_currency"] == cl["claimed_currency"]
            and cl["claimed_total"] > 0):
        raw_ratio = aw["awarded_total"] / cl["claimed_total"]
        grant_ratio = round(raw_ratio, 4)
        # 比較未四捨五入的原值。用 round 後的值比較會讓 1.0000295 變成
        # 1.0，差幾十元的矛盾就靜靜溜過去（實測 2 筆）。
        if raw_ratio > 1.0:
            # 判准高於請求在邏輯上不可能（法院不得訴外裁判），代表聲明段落
            # 只抓到部分項目。這種比值必須**作廢**而不只是標記——留著它，
            # 下游只要沒注意到旗標就會把錯的數字算進平均獲償比例。
            grant_ratio = None
            flags.append("判准大於請求")
            # 來源標記也要一併降級。值本身仍有參考價值（是請求金額的下界），
            # 所以保留數字；但繼續標成「直接抽取」會讓人以為它可信，
            # 凡是照 claimed_source 篩選的分析都會把這 169 筆當成好資料。
            cl["claimed_source"] = "直接抽取（不完整）"

    # ── 金額缺漏的原因標記（區分「真的沒有」與「抽不到」）──
    if oc["outcome"] in (WIN, PARTIAL) and not aw["awarded_total"]:
        if aw["awarded_joint_release"]:
            # 總額是「刻意不算」而非「抽不到」，理由由 重複給付免責 旗標說明。
            pass
        elif re.search(r"按(?:月|年|日|季)[^。；]{0,20}給付", verdict or ""):
            # 定期金給付（按月給付租金、薪資）沒有「總額」可言，
            # 總額取決於未定的終期。這不是抽取失敗，是本質上不存在的欄位。
            flags.append("定期給付")
        elif aw["awarded_in_table"]:
            flags.append("金額於附表")
        elif "金錢給付" not in relief:
            flags.append("非金錢給付")
        elif aw["awarded_currency"] and aw["awarded_currency"] != "TWD":
            flags.append("外幣")
        else:
            flags.append("金額抽取失敗")
    if aw["awarded_currency"] and "/" in aw["awarded_currency"]:
        flags.append("混合幣別未合計")
    if aw["awarded_joint_release"]:
        flags.append("重複給付免責")

    # ── 法條（從本文抽取，頁尾欄位作為補充來源）──
    # 必須包含 facts。部分判決（尤其銀行請求清償借款的一造辯論判決）只有
    # 「事　實」一段，論理與法條全寫在裡面，沒有獨立的「理由」段。
    # 漏掉 facts 的話這些案件的法條引用數會是 0（實測 37 筆）。
    cites = extract_law_citations(
        g("reasons"), g("facts_and_reasons"), g("facts"),
        g("conclusion"), g("applicable_laws"))
    if not cites:
        flags.append("無法條引用")
    law_primary = _pick_primary_law(cites)

    # ── 法官 ──
    jl = split_judges(g("judges"), g("full_text"))
    presiding = next((j["name"] for j in jl if j["role"] in ("審判長", "獨任")), "")
    if not jl:
        flags.append("無法官")

    # ── 案由 ──
    ct_norm, ct_cat = normalize_case_type(g("case_type"), g("plaintiff"))

    # ── 當事人與程序特徵 ──
    defendant = g("defendant")
    full_text = g("full_text")

    return {
        "case_kind":            kind,
        "case_kind_category":   kind_cat,
        "outcome":              oc["outcome"],
        "main_outcome":         oc["main_outcome"],
        "counter_outcome":      oc["counter_outcome"],
        "has_counterclaim":     oc["has_counterclaim"],
        "appeal_outcome":       appeal_outcome,
        "relief_type":          relief,
        "awarded_amount":       aw["awarded_total"],
        "awarded_currency":     aw["awarded_currency"],
        "awarded_n_items":      aw["awarded_n_items"],
        "awarded_items_json":   json.dumps(aw["awarded_items"], ensure_ascii=False) if aw["awarded_items"] else "",
        "awarded_in_table":     aw["awarded_in_table"],
        "claimed_amount":       cl["claimed_total"],
        "claimed_currency":     cl["claimed_currency"],
        "claimed_source":       cl["claimed_source"],
        "grant_ratio":          grant_ratio,
        "cost_share_plaintiff": _cost_share_plaintiff(verdict),
        "applicable_laws_json": json.dumps(cites, ensure_ascii=False) if cites else "",
        "law_n_citations":      len(cites),
        "law_primary":          law_primary,
        "judges_json":          json.dumps(jl, ensure_ascii=False) if jl else "",
        "judge_count":          len(jl),
        "presiding_judge":      presiding,
        "panel_key":            panel_key(g("judges")),
        "case_type_norm":       ct_norm,
        "case_type_category":   ct_cat,
        "defendant_is_corp":    1 if _CORP_RE.search(defendant) else 0,
        "plaintiff_has_lawyer": _agent_has_lawyer(g("plaintiff_agent"), full_text),
        "defendant_has_lawyer": _agent_has_lawyer(g("defendant_agent"), full_text),
        "is_default_judgment":  1 if _DEFAULT_JUDGMENT_RE.search(full_text) else 0,
        "has_provisional_exec": 1 if _PROVISIONAL_RE.search(verdict) else 0,
        # 論理段落的總字數。判決書用「理由」「事實及理由」「事實」三種格式
        # 擇一撰寫，所以三者相加才是完整的論理長度。
        # 舊欄名叫 reasons_length，會讓人以為只算「理由」段。
        "reasoning_length":     len(g("reasons")) + len(g("facts_and_reasons")) + len(g("facts")),
        "quality_flags":        "|".join(dict.fromkeys(flags)),
        "structuring_version":  STRUCTURING_VERSION,
    }
