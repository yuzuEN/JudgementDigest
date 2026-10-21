"""不能安全駕駛的酒／毒分類；無證據或互相衝突時留空。"""
import re

DRIVING_RE = re.compile(r"不能安全駕駛|駕駛動力交通工具|酒駕|毒駕")
DRUG_RE = re.compile(r"毒品|麻醉藥品|安非他命|[愷凱]他命|海洛因|大麻|嗎啡|可卡因")
ALCOHOL_RE = re.compile(r"酒精|酒類|飲酒|酒後|醉酒|酒駕")
# 2018–2025 資料：第1、2款為酒精；舊第3款與新第3、4款為毒品。
DRIVING_CLAUSE_RE = re.compile(
    r"刑法第(?:185|一百八十五|一八五|壹佰捌拾伍)條之(?:3|三|參)"
    r"第(?:1|一|壹)項((?:第[1234一二三四壹貳參肆]款[、及與暨]?)+)"
)


def is_driving_charge(text):
    text = re.sub(r"\s+", "", text)
    return bool(DRIVING_RE.search(text)) and not re.search(r"逃逸|過失", text)


def driving_charge_kinds(text):
    """僅供單一罪名／其相連法條使用，不以整案提到酒毒便分類。"""
    text = re.sub(r"\s+", "", text)
    if not is_driving_charge(text):
        return set()
    kinds = set()
    for match in DRIVING_CLAUSE_RE.finditer(text):
        for item in re.findall(r"第(.)款", match[1]):
            kinds.add("酒駕罪" if item in "12一二壹貳" else "毒駕罪")
    if DRUG_RE.search(text) or "毒駕" in text:
        kinds.add("毒駕罪")
    if ALCOHOL_RE.search(text):
        kinds.add("酒駕罪")
    return kinds


def driving_charge_kind(text):
    kinds = driving_charge_kinds(text)
    return next(iter(kinds)) if len(kinds) == 1 else ""


def explicitly_mixed_driving(text):
    """雙款或名稱明載酒毒才是混合；單款與名稱互相矛盾不算。"""
    text = re.sub(r"\s+", "", text)
    items = {item for match in DRIVING_CLAUSE_RE.finditer(text) for item in re.findall(r"第(.)款", match[1])}
    return bool((items & set('12一二壹貳') and items & set('34三四參肆'))
                or (DRUG_RE.search(text) and ALCOHOL_RE.search(text)))


def strip_law_quotations(text):
    # 先移除完整法條引文，再切句；引文內的分號／句號不能讓後半段
    # 「吸食毒品…駕車」失去「規定」前綴而被當成本案行為。
    return re.sub(r"(?:規定|條文|明定)\s*[：:]?\s*[「『][\s\S]*?[」』]", "", text)


def driving_fact_kinds(text):
    """限同句的施用／飲酒後駕車或酒測證據，排除前案及泛論法條。"""
    text = strip_law_quotations(text)
    kinds = set()
    for sentence in re.split(r"[。；\n]", text):
        sentence = re.sub(r"\s+", "", sentence)
        if re.search(r"規定|修正|前案|曾因|前曾|另案|證人|告訴人|公訴意旨|起訴意旨|不構成|無罪", sentence):
            continue
        drive = r"(?:駕駛|駕車|開車|騎乘|騎車)"
        if (not re.search(r"未(?:曾)?(?:施用|服用|吸食)|並無(?:施用|服用|吸食)|否認.*(?:施用|服用|吸食)", sentence)
                and re.search(r"(?:施用|服用|吸食)[^，、]{0,20}(?:" + DRUG_RE.pattern + r")[\s\S]{0,160}" + drive, sentence)):
            kinds.add("毒駕罪")
        if not re.search(r"未飲|沒有飲|並無飲|否認.*飲酒", sentence):
            if re.search(r"(?:飲酒|飲用[^，。]{0,15}酒|酒後)[\s\S]{0,160}" + drive, sentence):
                kinds.add("酒駕罪")
        if re.search(drive, sentence):
            readings = re.findall(r"(?:吐氣|呼氣|血液).*?酒精濃度(?:約)?(?:達|為|測得)[每公升每百毫升]*([0-9]+\.[0-9]+)", sentence)
            if any(float(value) > 0 for value in readings):
                kinds.add("酒駕罪")
    return kinds


def mixed_driving_in_conviction(text):
    """論罪科刑內，同句明確認定被告酒毒後駕車；不只檢查關鍵字共現。"""
    text = strip_law_quotations(re.sub(r"\s+", "", text))
    for section in re.split(r"論罪(?:科刑)?(?:之依據|之理由)?[：:]", text)[1:]:
        section = re.split(r"(?:[一二三四五六七八九十]+、)?(?:沒收|量刑|據上論斷|證據能力|附件|附錄)[：:]", section)[0]
        for sentence in re.split(r"[。；]", section):
            if '被告' not in sentence or re.search(r"明知|不得|不應|可能|如果|否認|無證據|證據不足|不成立|不構成", sentence):
                continue
            if driving_fact_kinds(sentence) == {'酒駕罪', '毒駕罪'}:
                return True
    return False
