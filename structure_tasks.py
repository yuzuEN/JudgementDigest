"""從裁判書 Excel 萃取每案的定罪法條、罪名、宣告刑與應執行刑。"""

import argparse
import re
from pathlib import Path
from typing import Optional

from openpyxl import load_workbook
from openpyxl.styles import Alignment, Font, PatternFill


SOURCE_SHEET = "裁判書資料"
OUTPUT_SHEET = "罪法刑結構化"
NON_GUILTY_WORDS = ("無罪", "不受理", "免訴")
NUM = "零〇○一二三四五六七八九十百千萬億壹貳參叁肆伍陸柒捌玖拾佰仟0123456789"
LAW_RE = re.compile(
    rf"(?:係犯|共同犯|違反|適用|應依|依|按|犯|、|，|；|^)"
    rf"([^，、；。：（）()\s]{{2,18}}?(?:條例|法))第[{NUM}]+條"
    rf"(?:之[{NUM}]+)?(?:第[{NUM}]+項)?(?:第[{NUM}]+款)?"
)
CHARGE_AFTER_LAW_RE = re.compile(r"之?([^，、；。]{2,80}罪)(?=[，、；。]|$)")
VERDICT_CHARGE_RE = re.compile(
    r"(?<!罪)犯([^；。]{2,160}?罪)(?=，(?:(?:累犯|未遂)，)?(?:均處|各處|處|科|免刑)|[；。]|$)"
)
APPENDIX_REFERENCE_RE = re.compile(r"^(?:(?:如|本).{0,12})?附表")
MAIN_END_RE = re.compile(r"犯罪事實及理由|事實及理由|事實與理由|犯罪事實")
TOTAL_RE = re.compile(
    rf"應執(?:行|刑)(?:之刑為)?(死刑|無期徒刑|有期徒(?:刑)?[{NUM}]+年(?:[{NUM}]+月)?|"
    rf"有期徒(?:刑)?[{NUM}]+月|拘役[{NUM}]+日|罰金(?:新臺幣)?[{NUM}]+元)"
)
SINGLE_RE = re.compile(
    rf"(?<!易)(?:處|科)(死刑|無期徒刑|有期徒(?:刑)?[{NUM}]+年(?:[{NUM}]+月)?|"
    rf"有期徒(?:刑)?[{NUM}]+月|拘役[{NUM}]+日|罰金(?:新臺幣)?[{NUM}]+元)"
)
CN_DIGITS = {
    "零": 0, "〇": 0, "○": 0, "一": 1, "壹": 1, "二": 2, "貳": 2,
    "三": 3, "參": 3, "叁": 3, "四": 4, "肆": 4, "五": 5, "伍": 5,
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
    for marker in ("係犯", "共同犯", "違反", "適用", "應依", "該罪為", "無論以", "均係"):
        name = name.rsplit(marker, 1)[-1]
    return name + match.group(0).split(match.group(1), 1)[1]


# 依理由、事實、適用法條的順序找法條，先命中即停止，避免較弱來源混入。
def extract_laws(reason: str, applicable_laws: str, facts: str = "") -> list[str]:
    found = []
    for text, conclusions_only in ((reason, True), (facts, True), (applicable_laws, False)):
        passages = [
            sentence for sentence in re.split(r"[。；]", text)
            if not conclusions_only or "係犯" in sentence or ("違反" in sentence and "罪" in sentence)
        ]
        found = [clean_law(match) for passage in passages for match in LAW_RE.finditer(passage)]
        if found:
            break
    return unique(law for law in found if not law.startswith(("刑事訴訟法", "刑法施行法")))


# 主文只接受明載「犯○○罪」的結果，附表引用不是罪名。
def extract_verdict_charges(verdict: str) -> list[str]:
    charges = VERDICT_CHARGE_RE.findall(main_section(verdict))
    return unique(
        charge.removeprefix("共同") for charge in charges
        if not APPENDIX_REFERENCE_RE.match(charge)
        and not any(marker in charge for marker in ("，處", "沒收", "罪所得新臺幣", "無罪", "免訴", "不受理"))
    )


# 輔助文字從已命中的法條結尾定位罪名，避免罪名內的「之」造成截斷。
def extract_supporting_charges(text: str) -> list[str]:
    charges = []
    for sentence in re.split(r"[。；]", text):
        if "係犯" not in sentence and not ("違反" in sentence and "罪" in sentence):
            continue
        for law_match in LAW_RE.finditer(sentence):
            charge_match = CHARGE_AFTER_LAW_RE.match(sentence, law_match.end())
            if charge_match:
                charges.append(charge_match.group(1))
    return unique(charge.removeprefix("共同") for charge in charges if charge)


# 罪名以主文為準；主文沒有具體罪名時，才依序退回理由與事實欄位。
def extract_charges(verdict: str, reason: str, facts: str = "") -> list[str]:
    return (extract_verdict_charges(verdict)
            or extract_supporting_charges(reason)
            or extract_supporting_charges(facts))


# 分開保留所有宣告刑與明載的應執行刑，不推算或加總法院未諭知的執行刑。
def extract_sentences(verdict: str) -> tuple[list[str], list[str]]:
    verdict = main_section(verdict)
    declared = [normalize_sentence(value) for value in SINGLE_RE.findall(verdict)]
    executions = [normalize_sentence(value) for value in TOTAL_RE.findall(verdict)]
    return declared, executions


# 補回少數原文省略的「刑」字，使刑種與月份換算維持一致格式。
def normalize_sentence(sentence: str) -> str:
    return re.sub(r"^有期徒(?!刑)", "有期徒刑", sentence)


# 將單一「有期徒刑…」宣告刑換算成月數；死刑、無期徒刑、拘役與罰金不硬轉成
# 不相容單位，回傳 None。appendix_parser.py 的附表逐列換算也共用這支，
# 避免兩邊各自維護一份「年×12+月」的算法而逐漸不一致。
def sentence_to_months(sentence: str) -> Optional[int]:
    if not sentence.startswith("有期徒刑"):
        return None
    year = re.search(rf"([{NUM}]+)年", sentence)
    month = re.search(rf"([{NUM}]+)月", sentence)
    return (chinese_number(year.group(1)) * 12 if year else 0) + (
        chinese_number(month.group(1)) if month else 0)


# 將整案的宣告刑清單換算成月，供「總執行刑（月）」欄使用。
def sentence_months(sentences: list[str]) -> list[str]:
    return [str(m) for s in sentences if (m := sentence_to_months(s)) is not None]


# 提供案件層級的最高有期徒刑月份；其他刑種不強制換算為月份。
def maximum_sentence_months(sentences: list[str]) -> int | str:
    months = sentence_months(sentences)
    return max(map(int, months)) if months else ""


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
    verdict = compact(row.get("主文"))
    reason = compact(row.get("事實及理由")) + compact(row.get("理由"))
    facts = compact(row.get("事實")) + compact(row.get("犯罪事實"))
    applicable_laws = compact(row.get("適用法條"))
    defendants = compact(row.get("被告／相對人"))
    declared, executions = extract_sentences(verdict)
    charges = extract_charges(verdict, reason, facts)
    laws = extract_laws(reason, applicable_laws, facts)
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
    assert extract_sentences("甲竊盜，科罰金新臺幣壹萬元。")[0] == ["罰金新臺幣壹萬元"]
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
    parser.add_argument("input", nargs="?", default="2425_07-12.xlsx", type=Path)
    parser.add_argument("-o", "--output", type=Path)
    args = parser.parse_args()
    output = args.output or args.input.with_name(f"{args.input.stem}_structured.xlsx")
    self_check()
    count = structure_excel(args.input, output)
    print(f"完成：{count} 筆 → {output}")


if __name__ == "__main__":
    main()
