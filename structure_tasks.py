"""從裁判書 Excel 萃取每案的定罪法條、罪名、宣告刑與應執行刑。"""

import argparse
import re
from pathlib import Path
from typing import Optional, Union

from openpyxl import load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from structuring import LAW_ALIASES, LAW_WHITELIST


SOURCE_SHEET = "裁判書資料"
OUTPUT_SHEET = "罪法刑結構化"
NON_GUILTY_WORDS = ("無罪", "不受理", "免訴")
NUM = "零〇○一二兩三四五六七八九十百千萬億壹貳參叁叄肆伍陸柒捌玖拾佰仟0123456789"
# {1,18} 允許單字法律名（民法、刑法）：{2,18} 會要求「法／條例」前至少 2 字，
# 「民法」「刑法」只有 1 字前綴，永遠比對不到（容嫣於 PR #4 留言回報，appendix_parser
# 的 _LAW_PREFIX 已用同樣理由改過）。lazy 量詞會優先取最短，不會因此多抓到
# 「應依」等觸發詞殘留。
LAW_RE = re.compile(
    rf"(?:係犯|共同犯|違反|適用|應依|依|按|犯|準用|及|與|暨|、|，|；|^)"
    rf"([^，、；。：（）()\s]{{1,18}}?(?:條例|法))第[{NUM}]+條"
    rf"(?:之[{NUM}]+)?(?:第[{NUM}]+項)?(?:第[{NUM}]+款)?"
)
LAW_ID_RE = re.compile(rf"^(.+?(?:條例|法))第([{NUM}]+)條(?:之([{NUM}]+))?")
CHARGE_AFTER_LAW_RE = re.compile(r"之?([^，、；。]{2,80}罪)(?=[，、；。]|$)")
VERDICT_CHARGE_RE = re.compile(
    r"(?<!罪)犯(?!罪事實)([^；。]{2,160}?罪)"
    rf"(?=，(?:共?[{NUM}]+罪，)?(?:(?:(?:均)?累犯|未遂)，)?(?:均處|各處|處|科|免刑)|[；。]|$)"
)
CHARGE_COUNT_SUFFIX_RE = re.compile(rf"，(?:(?:均)?累犯，)?共?[{NUM}]+罪$")
APPENDIX_REFERENCE_RE = re.compile(r"^(?:犯)?(?:(?:如|本).{0,12})?附表")
MAIN_END_RE = re.compile(r"(?:犯罪事實及理由|事實及理由|事實與理由|犯罪事實)(?!欄|要旨)")
CONCLUSION_CHARGE_RE = re.compile(r"(?:分別係犯|分別犯|係犯|各犯|均犯)")
LAW_POINT_RE = re.compile(
    r"(?=(?:[㈠㈡㈢㈣㈤㈥㈦㈧㈨㈩]|[（(][一二三四五六七八九十]+[）)]|"
    r"[一二三四五六七八九十]+、))"
)
LAW_REFERENCE_NAMES = (
    "同條例", "前開條例", "上述條例", "上開條例", "該條例", "本條例", "前揭條例", "前述條例",
    "同法", "前開法", "上述法", "上開法", "該法", "本法", "前揭法", "前述法",
)
LAW_REFERENCE_DICTIONARY = set(LAW_WHITELIST) | set(LAW_ALIASES) | {
    "刑法", "毒品危害防制條例", "洗錢防制法",
}
LAW_REFERENCE_RE = re.compile(
    rf"(?P<reference>{'|'.join(map(re.escape, LAW_REFERENCE_NAMES))})"
    rf"(?P<article>第[{NUM}]+條(?:之[{NUM}]+)?(?:第[{NUM}]+項)?(?:第[{NUM}]+款)?)"
)
ELIDED_LAW_ARTICLE_RE = re.compile(
    rf"(?P<connector>[、，及與暨]|準用)"
    rf"(?P<article>第[{NUM}]+條(?:之[{NUM}]+)?(?:第[{NUM}]+項)?(?:第[{NUM}]+款)?)"
)
EXPLICIT_LAW_RE = re.compile(
    rf"(?P<name>[^，。；、：: （）()\s]{{1,30}}?(?:條例|法))(?=第[{NUM}]+條)"
)
# 罰金金額允許千分位逗號，但不併入 NUM，避免法條條號誤接受逗號。
TOTAL_RE = re.compile(
    rf"應執(?:行|刑)(?:之刑為)?(死刑|無期徒刑|有期徒(?:刑)?[{NUM}]+年(?:[{NUM}]+月)?|"
    rf"有期徒(?:刑)?[{NUM}]+月|拘役[{NUM}]+日|罰金(?:新臺幣)?[{NUM},]+元)"
)
# 主刑與罰金分欄時，主刑只保留死刑、無期、有期與拘役。
TOTAL_PRIMARY_RE = re.compile(
    rf"應執(?:行|刑)(?:之刑為)?(死刑|無期徒刑|有期徒(?:刑)?[{NUM}]+年(?:[{NUM}]+月)?|"
    rf"有期徒(?:刑)?[{NUM}]+月|拘役[{NUM}]+日)"
)
TOTAL_FINE_RE = re.compile(rf"應執(?:行|刑)(?:之刑為)?(罰金(?:新臺幣)?[{NUM},]+元)")
SINGLE_RE = re.compile(
    rf"(?<!易)(?:處|科)(死刑|無期徒刑|有期徒(?:刑)?[{NUM}]+年(?:[{NUM}]+月)?|"
    rf"有期徒(?:刑)?[{NUM}]+月|拘役[{NUM}]+日|罰金(?:新臺幣)?[{NUM},]+元)"
)
PRIMARY_RE = re.compile(
    rf"(?<!易)(?:處|科)(死刑|無期徒刑|有期徒(?:刑)?[{NUM}]+年(?:[{NUM}]+月)?|"
    rf"有期徒(?:刑)?[{NUM}]+月|拘役[{NUM}]+日)"
)
FINE_RE = re.compile(rf"(?<!易)(?:處|科|併科)(罰金(?:新臺幣)?[{NUM},]+元)")
CN_DIGITS = {
    "零": 0, "〇": 0, "○": 0, "一": 1, "壹": 1, "二": 2, "兩": 2, "貳": 2,
    "三": 3, "參": 3, "叁": 3, "叄": 3, "四": 4, "肆": 4, "五": 5, "伍": 5,
    "六": 6, "陸": 6, "七": 7, "柒": 7, "八": 8, "捌": 8,
    "九": 9, "玖": 9,
}
CN_UNITS = {"十": 10, "拾": 10, "百": 100, "佰": 100, "千": 1000, "仟": 1000,
            "萬": 10_000, "億": 100_000_000}


# 移除排版空白，讓跨法院、跨年度的相同句型可共用規則。
def compact(value) -> str:
    return re.sub(r"\s+", "", str(value or ""))


# 截掉誤併入主文欄的事實與理由，避免把後文論罪或前科當成本案主文。
def main_section(verdict: str) -> str:
    marker = re.search(r"主文[：:]", verdict)
    if marker:
        verdict = verdict[marker.end():]
    return MAIN_END_RE.split(verdict, maxsplit=1)[0]


# 將中文大小寫數字或阿拉伯數字轉為整數，供刑期月份正規化使用。
# 支援阿拉伯數字與中文單位混寫（如「10萬」「3萬6千」）：逐字掃描時，連續的
# 阿拉伯數字要當成一個多位數整體讀入，不能像中文數字那樣一字一位，否則
# 「10萬」會因為阿拉伯字元不在 CN_DIGITS 裡被忽略、算成 0。
def chinese_number(value: str) -> int:
    if value.isdigit():
        return int(value)
    total = section = number = 0
    i, length = 0, len(value)
    while i < length:
        char = value[i]
        if char.isdigit():
            j = i + 1
            while j < length and value[j].isdigit():
                j += 1
            number = int(value[i:j])
            i = j
            continue
        if char in CN_DIGITS:
            number = CN_DIGITS[char]
        elif char in CN_UNITS:
            unit = CN_UNITS[char]
            if unit >= 10_000:
                section = (section + number) * unit
                total += section
                section = number = 0
            else:
                section += (number or 1) * unit
                number = 0
        i += 1
    return total + section + number


# 保留原出現順序並去除重複標籤，避免同一法條在主文與理由重複輸出。
def unique(values):
    return list(dict.fromkeys(value for value in values if value))


# 在同一編號大點內將「同法／前開條例」回指至前方最近的完整法名。
def resolve_law_references(text: str, law_names) -> str:
    """只在 ㈠／（一）／一、等同一大點內解析承前指稱，不跨段推測。"""
    known_names = sorted(set(law_names), key=len, reverse=True)
    resolved_points = []
    for point in LAW_POINT_RE.split(compact(text)):
        tokens = []
        for match in EXPLICIT_LAW_RE.finditer(point):
            raw_name = match.group("name")
            if any(raw_name.endswith(reference) for reference in LAW_REFERENCE_NAMES):
                continue
            recognized = next((name for name in known_names if raw_name.endswith(name)), "")
            tokens.append((match.start(), "law", recognized, raw_name, match))
        for match in LAW_REFERENCE_RE.finditer(point):
            tokens.append((match.start(), "reference", match.group("reference"), "", match))
        for match in ELIDED_LAW_ARTICLE_RE.finditer(point):
            tokens.append((match.start(), "elided", match.group("article"), "", match))
        tokens.sort(key=lambda token: (token[0], token[1] == "reference"))

        previous_laws = []
        replacements = []
        for _, kind, value, raw_name, match in tokens:
            if kind == "law":
                # 未識別的法名仍會阻斷向更遠處回指，避免跨過最近候選誤配。
                previous_laws.append((raw_name.endswith("條例"), value))
                continue
            if kind == "elided":
                referent = next((name for _, name in reversed(previous_laws) if name), "")
                if referent:
                    replacements.append((
                        match.start(), match.end(), match.group("connector") + referent + value,
                    ))
                    previous_laws.append((referent.endswith("條例"), referent))
                continue
            wants_regulation = value.endswith("條例")
            referent = next(
                (name for is_regulation, name in reversed(previous_laws)
                 if is_regulation == wants_regulation),
                "",
            )
            if referent:
                replacements.append((match.start(), match.end(), referent + match.group("article")))
                previous_laws.append((wants_regulation, referent))
        for start, end, replacement in reversed(replacements):
            point = point[:start] + replacement + point[end:]
        resolved_points.append(point)
    return "".join(resolved_points)


# 以使用者指定的 [A,B,C] 文字格式寫入多標籤欄位。
def labels(values) -> str:
    return "[" + ",".join(unique(values)) + "]"


# 刑期清單保留重複值，因為相同刑度可能分別屬於不同罪或不同被告。
def sentence_labels(values) -> str:
    return "[" + ",".join(values) + "]"


# 依主文是否同時包含定罪與非有罪諭知，判斷整案結果。
def case_result(verdict: str) -> str:
    verdict = main_section(verdict)
    non_guilty = [word for word in NON_GUILTY_WORDS if word in verdict]
    guilty = bool(re.search(
        r"犯.{0,80}?罪|處(?:死刑|無期徒刑|有期徒刑|拘役|罰金)|(?<!易)科罰金",
        verdict,
    ))
    if guilty and non_guilty:
        return "混合"
    if guilty:
        return "有罪"
    return "／".join(non_guilty) if non_guilty else "其他"


# 清掉法條前被正則一併捕捉的論述文字，只留下法規名稱與條項。
def clean_law(match: re.Match) -> str:
    name = match.group(1)
    for marker in (
        "分別係犯", "分別犯", "係犯", "共同犯", "違反", "適用", "應依", "依",
        "該罪為", "無論以", "均係",
    ):
        name = name.rsplit(marker, 1)[-1]
    name = re.sub(r"^(?:附錄本案所犯法條全文)?(?:中華民國)?", "", name)
    return name + match.group(0).split(match.group(1), 1)[1]


# 同一法條的全文標題、主條與詳細條項只留最精確版本；不同項款不互相覆蓋。
def specific_substantive_laws(laws: list[str]) -> list[str]:
    """排除程序／施行法，並將同一法條的簡略重複值收斂為最詳細引文。"""
    kept: list[str] = []
    for law in laws:
        if any(excluded in law for excluded in ("刑事訴訟法", "刑法施行法")):
            continue
        match = LAW_ID_RE.match(law)
        identity = match.groups() if match else None
        replaced = False
        for index, existing in enumerate(kept):
            existing_match = LAW_ID_RE.match(existing)
            if not identity or not existing_match or existing_match.groups() != identity:
                continue
            if existing == law or existing.startswith(law):
                replaced = True
                break
            if law.startswith(existing):
                kept[index] = law
                replaced = True
                break
        if not replaced:
            kept.append(law)
    return kept


# 依理由、事實、適用法條的順序找法條，先命中即停止，避免較弱來源混入。
def extract_laws(reason: str, applicable_laws: str, facts: str = "") -> list[str]:
    found = []
    for text, conclusions_only in ((reason, True), (facts, True), (applicable_laws, False)):
        passages = [
            sentence for sentence in re.split(r"[。；]", text)
            if not conclusions_only or CONCLUSION_CHARGE_RE.search(sentence)
            or ("違反" in sentence and "罪" in sentence)
        ]
        found = specific_substantive_laws([
            clean_law(match) for passage in passages for match in LAW_RE.finditer(passage)
        ])
        if found:
            break
    return unique(found)


# 主文優先接受明載「犯○○罪」的結果，並移除罪數與累犯尾碼。
def extract_verdict_charges(verdict: str) -> list[str]:
    charges = VERDICT_CHARGE_RE.findall(main_section(verdict))
    return unique(
        CHARGE_COUNT_SUFFIX_RE.sub("", charge).removeprefix("共同") for charge in charges
        if not APPENDIX_REFERENCE_RE.match(charge)
        and not any(marker in charge for marker in ("，處", "沒收", "罪所得新臺幣", "無罪", "免訴", "不受理"))
    )


# 主文未寫「犯」或「罪」時，以被告名後、宣告刑前的文字作為罪名描述。
# 併科、易科與應執行不是單罪宣告刑起點；附表引用與程序性主文也不收。
def extract_verdict_descriptions(verdict: str, defendants: str = "") -> list[str]:
    descriptions = []
    names = sorted((name for name in re.split(r"[；;]", defendants) if name), key=len, reverse=True)
    for clause in re.split(r"[。；]", main_section(verdict)):
        if re.match(r"\s*應執(?:行|刑)", clause):
            continue
        primary = PRIMARY_RE.search(clause)
        standalone_fine = re.search(rf"(?<![易併])(?:處|科)罰金(?:新臺幣)?[{NUM},]+元", clause)
        sentence = min(
            (match for match in (primary, standalone_fine) if match),
            key=lambda match: match.start(),
            default=None,
        )
        if not sentence:
            continue
        description = clause[:sentence.start()].rstrip("，,均各")
        description = description.removeprefix("又").removeprefix("另").removeprefix("被告")
        changed = True
        while changed:
            changed = False
            for name in names:
                if description.startswith(name):
                    description = description[len(name):].lstrip("、，,")
                    changed = True
        description = re.sub(rf"，(?:均)?累犯(?:，共?[{NUM}]+罪)?$", "", description)
        description = re.sub(rf"，共?[{NUM}]+罪$", "", description)
        if (len(description) >= 2
                and not APPENDIX_REFERENCE_RE.match(description)
                and not any(word in description for word in ("無罪", "免訴", "不受理", "撤銷", "駁回"))):
            descriptions.append(description)
    return unique(descriptions)


# 輔助文字從已命中的法條結尾定位罪名，避免罪名內的「之」造成截斷。
def extract_supporting_charges(text: str) -> list[str]:
    charges = []
    for sentence in re.split(r"[。；]", text):
        if not CONCLUSION_CHARGE_RE.search(sentence) and not ("違反" in sentence and "罪" in sentence):
            continue
        charges.extend(charge for _, charge in law_charge_pairs(sentence))
    return unique(charge.removeprefix("共同") for charge in charges if charge)


# 罪名以主文為準；主文沒有可用描述時，才依序退回理由與事實欄位。
def extract_charges(verdict: str, reason: str, facts: str = "", defendants: str = "") -> list[str]:
    return (extract_verdict_charges(verdict)
            or extract_verdict_descriptions(verdict, defendants)
            or extract_supporting_charges(reason)
            or extract_supporting_charges(facts))


# 從單一文字片段取出實體法條，排除程序法與施行法。
def laws_in_text(text: str) -> list[str]:
    """保留片段內明載法條的出現順序。"""
    return specific_substantive_laws([clean_law(match) for match in LAW_RE.finditer(text)])


# 理由、事實與適用法條只在同一片段同時出現罪名時才可用來配對。
def matched_laws(charge: str, standardized: str, main_clause: str,
                 reason: str, facts: str, applicable_laws: str,
                 normalizer=None) -> tuple[list[str], str]:
    """優先回傳同罪名法條，無結果時退回案件層級法條。"""
    direct = laws_in_text(main_clause)
    if direct:
        return direct, "主文同子句"
    terms = unique(term for term in (charge, standardized, standardized.removesuffix("罪")) if len(term) >= 2)
    for source_name, text, conclusions_only in (
        ("理由", reason, True), ("事實", facts, True), ("適用法條", applicable_laws, False),
    ):
        for passage in re.split(r"[。；]", text):
            if (conclusions_only and not CONCLUSION_CHARGE_RE.search(passage)
                    and not ("違反" in passage and "罪" in passage)):
                continue
            pairs = law_charge_pairs(passage)
            exact_laws = unique(
                law for law, candidate in pairs if compact(candidate) == compact(charge)
            )
            paired_laws = exact_laws or unique(
                law for law, candidate in pairs
                if normalizer and standardized and normalizer(candidate) == standardized
            )
            if paired_laws:
                return paired_laws, source_name
            related_by_text = any(term in passage for term in terms)
            related_by_class = bool(
                normalizer and standardized
                and any(normalizer(candidate) == standardized for candidate in charges_after_laws(passage))
            )
            if not (related_by_text or related_by_class) or "罪" not in passage:
                continue
            laws = laws_in_text(passage)
            if laws:
                return laws, source_name
    fallback = extract_laws(reason, applicable_laws, facts)
    if fallback:
        return fallback, "案件法條備援"
    return [], ""


# 從已定位法條後取出罪名，供正式罪名與粗分類交叉比對。
def law_charge_pairs(text: str) -> list[tuple[str, str]]:
    """把罪名前連續法條歸給該罪，並在下一個罪名後重新開始配對。"""
    pairs = []
    pending_laws = []
    law_matches = list(LAW_RE.finditer(text))
    for index, law_match in enumerate(law_matches):
        law = clean_law(law_match)
        if not law.startswith(("刑事訴訟法", "刑法施行法")):
            pending_laws.append(law)
        segment_end = law_matches[index + 1].start() if index + 1 < len(law_matches) else len(text)
        segment = text[law_match.end():segment_end].rstrip("及與暨")
        charge_match = CHARGE_AFTER_LAW_RE.match(segment)
        if charge_match:
            charge = charge_match.group(1).removeprefix("共同")
            pairs.extend((law, charge) for law in pending_laws)
            pending_laws = []
    return pairs


# 將法條後明載的罪名提供給粗分類比對，複合句已由 law_charge_pairs 分開。
def charges_after_laws(text: str) -> list[str]:
    """回傳同一片段內各法條所對應的明載罪名。"""
    return unique(charge for _, charge in law_charge_pairs(text))


# 以主文罪刑子句為單位，保留罪名、主刑與罰金的相同索引。
def extract_offense_clauses(verdict: str, defendants: str = "") -> list[dict[str, str]]:
    """將主文依出現順序拆成可對齊的罪刑紀錄。"""
    offenses = []
    for clause in re.split(r"[。；]", main_section(verdict)):
        charges = extract_verdict_charges(clause) or extract_verdict_descriptions(clause, defendants)
        if not charges:
            continue
        primaries = [normalize_sentence(value) for value in PRIMARY_RE.findall(clause)]
        fines = FINE_RE.findall(clause)
        size = max(len(charges), len(primaries), len(fines), 1)
        if len(charges) == 1 and size > 1:
            charges *= size
        for index, charge in enumerate(charges):
            offenses.append({
                "charge": charge,
                "primary": primaries[index] if index < len(primaries) else "",
                "fine": fines[index] if index < len(fines) else "",
                "clause": clause,
            })
    return offenses


# 讓舊工作表與精簡審核表共用罪刑對齊、承前法名及同罪名法條配對規則。
def extract_aligned_case(verdict: str, reason: str, facts: str, applicable_laws: str,
                         defendants: str, declared: list[str], normalizer):
    """回傳逐罪的主文罪刑、對應法條及來源；無主文罪名時才以理由備援。"""
    reason = resolve_law_references(reason, LAW_REFERENCE_DICTIONARY)
    facts = resolve_law_references(facts, LAW_REFERENCE_DICTIONARY)
    applicable_laws = resolve_law_references(applicable_laws, LAW_REFERENCE_DICTIONARY)
    offenses = extract_offense_clauses(verdict, defendants)
    charge_source = "主文" if offenses else ""
    supporting_charges = extract_supporting_charges(reason) or extract_supporting_charges(facts)
    if offenses and len(supporting_charges) == len(offenses):
        replaced = False
        for offense, supporting_charge in zip(offenses, supporting_charges):
            if "罪" not in offense["charge"]:
                offense["charge"] = supporting_charge
                replaced = True
        if replaced:
            charge_source = "主文罪刑＋理由／事實正式罪名"
    if (not offenses and len(supporting_charges) == 1 and len(declared) == 1
            and "如附表" in verdict):
        offenses = [{
            "charge": supporting_charges[0], "primary": declared[0], "fine": "", "clause": verdict,
        }]
        charge_source = "主文刑期＋理由／事實正式罪名"
    if not offenses:
        fallback_charges = supporting_charges or extract_charges("", reason, facts, defendants)
        offenses = [{"charge": charge, "primary": "", "fine": "", "clause": ""}
                    for charge in fallback_charges]
        charge_source = "理由／事實備援" if offenses else ""

    laws_by_offense = []
    law_sources = []
    for offense in offenses:
        charge = offense["charge"]
        laws, source_name = matched_laws(
            charge, normalizer(charge), offense["clause"], reason, facts,
            applicable_laws, normalizer,
        )
        laws_by_offense.append(laws)
        law_sources.append(source_name)
    return offenses, laws_by_offense, charge_source, law_sources


# 分開保留所有宣告主刑與明載的應執行主刑，罰金由專用欄位處理。
def extract_sentences(verdict: str) -> tuple[list[str], list[str]]:
    verdict = main_section(verdict)
    declared = [normalize_sentence(value) for value in PRIMARY_RE.findall(verdict)]
    executions = [normalize_sentence(value) for value in TOTAL_PRIMARY_RE.findall(verdict)]
    return declared, executions


# 應執行罰金屬案件層級，不硬配到單一罪名。
def extract_execution_fines(verdict: str) -> list[str]:
    """取出主文明載的應執行罰金。"""
    return TOTAL_FINE_RE.findall(main_section(verdict))


# 補回少數原文省略的「刑」字，使刑種與月份換算維持一致格式。
def normalize_sentence(sentence: str) -> str:
    return re.sub(r"^有期徒(?!刑)", "有期徒刑", sentence)


# 將有期徒刑換算成整月、拘役按 30 日一月換算至小數二位；其他刑種回傳 None。
# appendix_parser.py 也共用這支，避免主文與附表採用不同換算規則。
def sentence_to_months(sentence: str) -> Optional[Union[int, float]]:
    if sentence.startswith("拘役"):
        day = re.search(rf"([{NUM}]+)日", sentence)
        return round(chinese_number(day.group(1)) / 30, 2) if day else None
    if sentence.startswith("有期徒刑"):
        year = re.search(rf"([{NUM}]+)年", sentence)
        month = re.search(rf"([{NUM}]+)月", sentence)
        return (chinese_number(year.group(1)) * 12 if year else 0) + (
            chinese_number(month.group(1)) if month else 0)
    return None


# 將整案的有期徒刑與拘役清單換算成月，保留拘役的小數月數。
def sentence_months(sentences: list[str]) -> list[str]:
    return [f"{m:g}" for s in sentences if (m := sentence_to_months(s)) is not None]


# 提供案件層級的最高自由刑月份；死刑、無期徒刑與罰金不換算。
def maximum_sentence_months(sentences: list[str]) -> Union[int, float, str]:
    months = sentence_months(sentences)
    if not months:
        return ""
    maximum = max(map(float, months))
    return int(maximum) if maximum.is_integer() else maximum


# 區分法院明載執行刑、僅有宣告刑及缺少刑期，供模型篩選標籤品質。
def sentence_data_status(declared: list[str], executions: list[str], defendants: str) -> str:
    if executions:
        return "有應執行刑"
    if declared and "；" in defendants and len(declared) > 1:
        return "多被告未配對"
    if declared:
        return "僅宣告刑"
    return "無刑期"


# 結合主文、理由與適用法條，產生單一案件的一列結構化資料。
def structure_row(row: dict) -> list[object]:
    from normalize import normalize_charge

    verdict = compact(row.get("主文"))
    reason = compact(row.get("事實及理由")) + compact(row.get("理由"))
    facts = compact(row.get("事實")) + compact(row.get("犯罪事實"))
    applicable_laws = compact(row.get("適用法條"))
    defendants = compact(row.get("被告／相對人"))
    declared, executions = extract_sentences(verdict)
    offenses, laws_by_offense, _, _ = extract_aligned_case(
        verdict, reason, facts, applicable_laws, defendants, declared, normalize_charge,
    )
    charges = [offense["charge"] for offense in offenses]
    laws = unique(law for offense_laws in laws_by_offense for law in offense_laws)
    result = case_result(verdict)
    sentence_status = sentence_data_status(declared, executions, defendants)
    status = "完整" if declared or executions else "無刑期"
    if ("如附表" in verdict and not charges) or (result in ("有罪", "混合") and (not laws or not charges)):
        status = "需人工核對"
    return [
        row.get("裁判字號", ""), row.get("裁判書連結", ""),
        row.get("裁判種類", ""), row.get("案件類型", ""), result,
        labels(laws), labels(charges), sentence_labels(declared), sentence_labels(sentence_months(declared)),
        maximum_sentence_months(declared), sentence_labels(executions),
        sentence_labels(sentence_months(executions)), bool(executions), sentence_status, status,
    ]


# 複製來源活頁簿並新增結構化工作表，保留原始資料供人工回查。
def structure_excel(source: Path, output: Path) -> int:
    if not source.exists():
        raise FileNotFoundError(f"找不到輸入檔：{source}")
    workbook = load_workbook(source)
    if SOURCE_SHEET not in workbook.sheetnames:
        raise ValueError(f"找不到工作表：{SOURCE_SHEET}")
    source_sheet = workbook[SOURCE_SHEET]
    headers = [cell.value for cell in source_sheet[1]]
    required = {
        "裁判字號", "裁判書連結", "裁判種類", "案件類型", "主文",
        "事實及理由", "理由", "適用法條",
    }
    missing = required - set(headers)
    if missing:
        raise ValueError(f"缺少必要欄位：{', '.join(sorted(missing))}")

    if OUTPUT_SHEET in workbook.sheetnames:
        del workbook[OUTPUT_SHEET]
    target = workbook.create_sheet(OUTPUT_SHEET)
    target.append([
        "裁判字號", "裁判書連結", "裁判種類", "案件類型", "案件結果",
        "法條", "罪名", "所有宣告刑", "宣告刑（月）", "宣告刑最大值（月）",
        "應執行刑", "應執行刑（月）", "是否明載應執行刑", "刑期資料狀態", "萃取狀態",
    ])
    for values in source_sheet.iter_rows(min_row=2, values_only=True):
        target.append(structure_row(dict(zip(headers, values))))

    for cell in target[1]:
        cell.font = Font(color="FFFFFF", bold=True)
        cell.fill = PatternFill("solid", fgColor="1F3864")
    target.freeze_panes = "A2"
    target.auto_filter.ref = target.dimensions
    target.column_dimensions["A"].width = 38
    target.column_dimensions["B"].width = 55
    for column in "CDEFGHIJKLMNO":
        target.column_dimensions[column].width = 28
    for row in target.iter_rows():
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    workbook.save(output)
    return target.max_row - 1


# 執行最小自我檢查，確保中文數字、混合案件與總刑期規則未被改壞。
def self_check() -> None:
    assert chinese_number("貳仟壹佰捌拾捌萬肆仟肆佰") == 21_884_400
    assert case_result("甲犯竊盜罪，處有期徒刑參月。乙無罪。") == "混合"
    assert case_result("甲科罰金新臺幣壹萬元。") == "有罪"
    assert case_result("無罪。事實與理由：檢察官認被告犯罪。") == "無罪"
    declared, executions = extract_sentences(
        "各處有期徒刑參月；另處有期徒刑參月。應執行有期徒刑壹年貳月。"
    )
    assert declared == ["有期徒刑參月", "有期徒刑參月"]
    assert executions == ["有期徒刑壹年貳月"] and sentence_months(executions) == ["14"]
    assert extract_sentences("甲竊盜，科罰金新臺幣壹萬元。")[0] == []
    assert extract_offense_clauses("甲竊盜，科罰金新臺幣壹萬元。", "甲")[0]["fine"] == "罰金新臺幣壹萬元"
    assert extract_sentences("甲犯竊盜罪，處有期徒陸月。")[0] == ["有期徒刑陸月"]
    assert extract_sentences("應執刑有期徒刑肆年。")[1] == ["有期徒刑肆年"]
    assert extract_sentences(
        "處有期徒刑肆月，如易科罰金，以新臺幣壹仟元折算壹日。"
    )[0] == ["有期徒刑肆月"]
    assert extract_charges("", compact(
        "核被告所為，係犯刑法第185條之3第1項第3款之"
        "駕駛動力交通工具而有尿液所含毒品達行政院公告之品項及濃度值以上之情形罪。"
    )) == ["駕駛動力交通工具而有尿液所含毒品達行政院公告之品項及濃度值以上之情形罪"]
    assert extract_charges("", compact(
        "核被告所為，係犯毒品危害防制條例第10條第2項施用第二級毒品罪。"
    )) == ["施用第二級毒品罪"]
    assert extract_charges(
        compact("甲犯竊盜罪，處有期徒刑參月。"),
        compact("核被告所為，係犯刑法第335條第1項之侵占罪。"),
    ) == ["竊盜罪"]
    assert extract_charges(compact(
        "甲犯本判決附表乙編號一「罪名、宣告刑（含執行刑）」欄內所示之罪，"
        "處如附表所示之刑。"
    ), "") == []
    assert extract_charges(compact(
        "甲犯汽車駕駛人，行近行人穿越道不依規定讓行人優先通行，"
        "因而過失致人受傷罪，處有期徒刑參月。"
    ), "") == ["汽車駕駛人，行近行人穿越道不依規定讓行人優先通行，因而過失致人受傷罪"]
    assert extract_charges(compact(
        "甲犯竊盜罪，處有期徒刑參月。事實與理由：核被告所為，"
        "係犯刑法第335條第1項之侵占罪。"
    ), "") == ["竊盜罪"]
    assert structure_row({
        "主文": "甲犯如附表所示之罪，應執行有期徒刑壹年。",
    })[-1] == "需人工核對"


# 提供可直接套用預設檔名的命令列入口，也允許覆寫輸入與輸出路徑。
def main() -> None:
    parser = argparse.ArgumentParser(description="萃取每案罪名、法條、宣告刑與應執行刑")
    parser.add_argument("input", type=Path)
    parser.add_argument("-o", "--output", type=Path)
    args = parser.parse_args()
    output = args.output or args.input.with_name(f"{args.input.stem}_structured.xlsx")
    self_check()
    count = structure_excel(args.input, output)
    print(f"完成：{count} 筆 → {output}")


if __name__ == "__main__":
    main()
