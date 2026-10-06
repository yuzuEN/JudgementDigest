"""將罪法刑結構化結果另存為「標準化」工作表，提供常見法主條與罪名粗分類。"""

import argparse
import re
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.styles import Alignment, Font, PatternFill

from structure_tasks import chinese_number


SOURCE_SHEET = "罪法刑結構化"
OUTPUT_SHEET = "標準化"
ARTICLE_RE = re.compile(
    r"第(?P<article>[零〇○一二三四五六七八九十百千萬壹貳參叁肆伍陸柒捌玖拾佰仟0-9]+)條"
)
# 依有罪案件的案件出現次數選取前十個實體／特別法；程序法不作為定罪標籤。
COMMON_LAWS = (
    "刑法", "毒品危害防制條例", "洗錢防制法", "組織犯罪防制條例",
    "道路交通管理處罰條例", "商業會計法", "商標法",
    "槍砲彈藥刀械管制條例", "藥事法", "家庭暴力防治法",
)
CHARGE_RULES = (
    (re.compile(r"尿液所含毒品|駕駛動力交通工具.*毒品"), "毒駕罪"),
    (re.compile(r"酒.*濃度|酒類.*駕駛|不能安全駕駛|第一百八十五條之三"), "酒駕罪"),
    (re.compile(r"過失傷害|過失.*(?:受傷|傷害)"), "過失傷害罪"),
    (re.compile(r"過失致死|過失致人於死"), "過失致死罪"),
    (re.compile(r"過失致重傷"), "過失致重傷罪"),
    (re.compile(r"詐欺"), "詐欺罪"),
    (re.compile(r"竊盜"), "竊盜罪"),
    (re.compile(r"施用.*毒品"), "施用毒品罪"),
    (re.compile(r"持有.*毒品"), "持有毒品罪"),
    (re.compile(r"販賣.*毒品"), "販賣毒品罪"),
    (re.compile(r"轉讓.*毒品"), "轉讓毒品罪"),
    (re.compile(r"運輸.*毒品"), "運輸毒品罪"),
    (re.compile(r"製造.*毒品"), "製造毒品罪"),
    (re.compile(r"行使.*文書|偽造.*文書|登載不實"), "偽造文書罪"),
    (re.compile(r"偽造.*有價證券|行使.*有價證券"), "偽造有價證券罪"),
    (re.compile(r"偽造署押"), "偽造署押罪"),
    (re.compile(r"填製不實.*(?:會計憑證|罪)|不實.*會計憑證"), "填製不實會計憑證罪"),
    (re.compile(r"侵占"), "侵占罪"),
    (re.compile(r"竊佔"), "竊佔罪"),
    (re.compile(r"恐嚇"), "恐嚇罪"),
    (re.compile(r"毀損|毀棄損壞|致令他人物品不堪用"), "毀損罪"),
    (re.compile(r"公然侮辱|誹謗"), "妨害名譽罪"),
    (re.compile(r"傷害"), "傷害罪"),
    (re.compile(r"洗錢"), "洗錢罪"),
    (re.compile(r"犯罪組織|參與組織"), "組織犯罪罪"),
    (re.compile(r"妨害公務|侮辱公務員|公務員.*施.*強暴|強暴侮辱"), "妨害公務罪"),
    (re.compile(r"強制性交"), "強制性交罪"),
    (re.compile(r"強制猥褻"), "強制猥褻罪"),
    (re.compile(r"殺人"), "殺人罪"),
    (re.compile(r"強盜"), "強盜罪"),
    (re.compile(r"搶奪"), "搶奪罪"),
    (re.compile(r"強制.*罪"), "強制罪"),
    (re.compile(r"公共危險罪"), "公共危險罪"),
    (re.compile(r"肇事.*逃逸|交通事故.*逃逸"), "肇事逃逸罪"),
    (re.compile(r"賭博|供給賭博場所|聚眾賭博"), "賭博罪"),
    (re.compile(r"違反保護令"), "違反保護令罪"),
    (re.compile(r"媒介.*性交|性交.*媒介|容留.*(?:性交|猥褻)"), "妨害風化罪"),
    (re.compile(r"未繳納股款|收回股款"), "未繳納股款罪"),
    (re.compile(r"背信"), "背信罪"),
    (re.compile(r"剝奪(?:他)?人.*行動自由|私行拘禁"), "剝奪行動自由罪"),
    (re.compile(r"侵害商標權"), "侵害商標權罪"),
    (re.compile(r"誣告"), "誣告罪"),
    (re.compile(r"性騷擾"), "性騷擾罪"),
    (re.compile(r"轉讓(?:禁藥|偽藥)"), "轉讓禁藥罪"),
    (re.compile(r"(?:自動付款|收費)設備"), "不正利用自動設備罪"),
    (re.compile(r"妨害兵役|妨害.*(?:徵兵|召集)|妨害役男"), "妨害兵役罪"),
    (re.compile(r"偽證"), "偽證罪"),
    (re.compile(r"侵入.*(?:住宅|建築物)"), "侵入住宅罪"),
    (re.compile(r"公然猥褻"), "公然猥褻罪"),
    (re.compile(r"乘機性交"), "乘機性交罪"),
    (re.compile(r"乘機猥褻"), "乘機猥褻罪"),
    (re.compile(r"非法經營證券業務"), "非法經營證券業務罪"),
    (re.compile(r"非法經營期貨"), "非法經營期貨業務罪"),
    (re.compile(r"內線交易"), "內線交易罪"),
    (re.compile(r"損壞公務員.*掌管"), "損壞公務物品罪"),
    (re.compile(r"贓物"), "贓物罪"),
    (re.compile(r"竊錄|妨害秘密"), "妨害秘密罪"),
    (re.compile(r"(?:持有|寄藏).*(?:槍枝|手槍|子彈|空氣槍|槍砲.*零件|爆裂物)"), "槍砲罪"),
    (re.compile(r"未經許可.*刀械|非法.*刀械"), "非法持有刀械罪"),
    (re.compile(r"妨害公眾往來安全"), "妨害公眾往來安全罪"),
    (re.compile(r"公共場所聚集三人以上|聚集三人以上.*強暴"), "聚眾施強暴罪"),
    (re.compile(r"非法經營銀行|非法.*收受存款|非法辦理.*匯兌"), "非法經營銀行業務罪"),
    (re.compile(r"私運管制物品"), "私運管制物品罪"),
    (re.compile(r"頂替"), "頂替罪"),
    (re.compile(r"重利"), "重利罪"),
    (re.compile(r"(?:相姦|通姦)"), "通姦罪"),
    (re.compile(r"(?:未滿十六歲|未滿16歲|未滿十四歲|未滿14歲).*(?:性交|猥褻)"), "與未成年人性交猥褻罪"),
    (re.compile(r"非法執行醫療"), "非法執行醫療業務罪"),
    (re.compile(r"輸入禁藥"), "輸入禁藥罪"),
    (re.compile(r"未經許可入國"), "未經許可入國罪"),
    (re.compile(r"損害債權"), "損害債權罪"),
    (re.compile(r"逃漏稅捐"), "逃漏稅捐罪"),
    (re.compile(r"侵害.*著作財產權|著作權法.*罪"), "侵害著作權罪"),
    (re.compile(r"放火"), "放火罪"),
    (re.compile(r"失火"), "失火罪"),
    (re.compile(r"非法營業"), "非法營業罪"),
    (re.compile(r"跟蹤騷擾"), "跟蹤騷擾罪"),
    (re.compile(r"商品虛偽標記"), "商品虛偽標記罪"),
    (re.compile(r"個人資料|個資法|非法利用個人資料"), "違反個人資料保護法罪"),
    (re.compile(r"性侵害犯罪防治法|加害人屆期不履行"), "違反性侵害防治義務罪"),
    (re.compile(r"電腦.*不實財產權.*取財"), "電腦詐欺罪"),
    (re.compile(r"盜用電信"), "盜用電信罪"),
    (re.compile(r"非法經營證券投資顧問"), "非法經營投資顧問業務罪"),
    (re.compile(r"使.*大陸地區人民非法進入"), "使大陸地區人民非法進入罪"),
    (re.compile(r"填載不實"), "填製不實會計憑證罪"),
    (re.compile(r"散布猥褻"), "散布猥褻物品罪"),
    (re.compile(r"少年.*猥褻|兒童.*猥褻"), "兒少性剝削罪"),
    (re.compile(r"違法重建"), "違法重建罪"),
    (re.compile(r"輸入私菸"), "輸入私菸罪"),
    (re.compile(r"非法(?:僱用|留用)"), "非法僱用罪"),
    (re.compile(r"無故.*(?:取得|變更|刪除).*電腦.*電磁紀錄"), "妨害電腦使用罪"),
    (re.compile(r"妨害醫事人員"), "妨害醫事人員執行業務罪"),
    (re.compile(r"偽造.*(?:紙幣|通用貨幣)"), "偽造貨幣罪"),
    (re.compile(r"重傷"), "重傷罪"),
    (re.compile(r"媒介.*猥褻|猥褻.*(?:媒介|容留)"), "妨害風化罪"),
    (re.compile(r"選舉.*(?:賄賂|交付)|交付賄賂"), "選舉賄賂罪"),
    (re.compile(r"發還股款"), "未繳納股款罪"),
    (re.compile(r"冒用身分.*身分證"), "冒用身分證罪"),
    (re.compile(r"使開標發生不正確結果"), "妨害投標罪"),
    (re.compile(r"受禁止出國處分而出國"), "違反禁止出國處分罪"),
    (re.compile(r"主管事務圖利|利用職務.*詐取財物"), "貪污罪"),
    (re.compile(r"財務報表.*不實"), "財報不實罪"),
    (re.compile(r"偽造印文"), "偽造印文罪"),
    (re.compile(r"護照交付他人|冒名使用.*護照"), "違反護照條例罪"),
    (re.compile(r"侵入.*(?:住居|住所)"), "侵入住宅罪"),
    (re.compile(r"湮滅.*證據"), "湮滅證據罪"),
    (re.compile(r"偽造.*(?:信用卡|支付卡)|行使偽造信用卡"), "偽造信用卡罪"),
    (re.compile(r"非法清理廢棄物"), "非法清理廢棄物罪"),
    (re.compile(r"散播.*疫情.*不實"), "散播疫情不實訊息罪"),
)


# 拆開 structure_tasks.py 使用的 [A,B,C] 多標籤格式，空清單不產生項目。
def split_labels(value: object) -> list[str]:
    text = str(value or "").strip()
    if not text or text == "[]":
        return []
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    return [item.strip() for item in text.split(",") if item.strip()]


# 只保留前十個常見法的正式名稱與主條號；指代詞只承接同列前一個白名單法規。
def normalize_law_levels(value: object) -> tuple[str, str]:
    normalized: list[str] = []
    previous_name = ""
    for raw in split_labels(value):
        compact = re.sub(r"\s+", "", raw)
        compact = re.sub(r"^(?:(?:中華民國|修正前|修正後|前開)+)", "", compact)
        name = next((law for law in COMMON_LAWS if compact.startswith(f"{law}第")), "")
        if not name and previous_name and any(word in compact for word in ("同法", "該法", "同條例", "該條例")):
            name = previous_name
        match = ARTICLE_RE.search(compact)
        if not name or not match:
            continue
        previous_name = name
        law = f'{name}第{chinese_number(match.group("article"))}條'
        if law not in normalized:
            normalized.append(law)
    if not normalized:
        return "", ""
    labels = "[" + ",".join(normalized) + "]"
    return labels, labels


# 以明確的犯罪家族規則移除細節前綴；任一罪名未命中時整格留空，避免高估成功率。
def normalize_charges(value: object) -> str:
    normalized: list[str] = []
    for charge in split_labels(value):
        standard = next((label for pattern, label in CHARGE_RULES if pattern.search(charge)), "")
        if not standard:
            return ""
        if standard not in normalized:
            normalized.append(standard)
    return "[" + ",".join(normalized) + "]" if normalized else ""


# 讀取結構化工作表並新增標準化工作表；刑期維持原樣以免改變量刑語意。
def normalize_workbook(source: Path, output: Path) -> int:
    if not source.exists():
        raise FileNotFoundError(f"找不到輸入檔：{source}")
    workbook = load_workbook(source)
    if SOURCE_SHEET not in workbook.sheetnames:
        raise ValueError(f"找不到工作表：{SOURCE_SHEET}")

    source_sheet = workbook[SOURCE_SHEET]
    headers = [cell.value for cell in source_sheet[1]]
    required = {"裁判字號", "法條", "罪名", "所有宣告刑", "應執行刑"}
    missing = required - set(headers)
    if missing:
        raise ValueError(f"缺少必要欄位：{', '.join(sorted(missing))}")

    if OUTPUT_SHEET in workbook.sheetnames:
        del workbook[OUTPUT_SHEET]
    target = workbook.create_sheet(OUTPUT_SHEET)
    target.append([
        "判決書名稱", "法條（原始）", "法條標準鍵", "法條粗分類",
        "罪名（原始）", "罪名（標準化）", "所有宣告刑", "應執行刑",
    ])
    for values in source_sheet.iter_rows(min_row=2, values_only=True):
        row = dict(zip(headers, values))
        standard_laws, coarse_laws = normalize_law_levels(row.get("法條"))
        target.append([
            row.get("裁判字號", ""), row.get("法條", ""), standard_laws, coarse_laws,
            row.get("罪名", ""), normalize_charges(row.get("罪名")),
            row.get("所有宣告刑", ""), row.get("應執行刑", ""),
        ])

    for cell in target[1]:
        cell.font = Font(color="FFFFFF", bold=True)
        cell.fill = PatternFill("solid", fgColor="1F3864")
    target.freeze_panes = "A2"
    target.auto_filter.ref = target.dimensions
    for column, width in zip("ABCDEFGH", (38, 45, 45, 45, 45, 35, 32, 32)):
        target.column_dimensions[column].width = width
    for row in target.iter_rows():
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    workbook.save(output)
    return target.max_row - 1


# 執行最小自我檢查，涵蓋常見法白名單、指代承接及常見罪名粗分類。
def self_check() -> None:
    assert normalize_law_levels("[刑法第一百八十五條之三第1項,同法第339條之4]") == (
        "[刑法第185條,刑法第339條]", "[刑法第185條,刑法第339條]"
    )
    assert normalize_law_levels(
        "[中華民國刑法第參佰貳拾條第1項,修正前刑法第320條]"
    ) == (
        "[刑法第320條]", "[刑法第320條]"
    )
    assert normalize_law_levels("[刑事訴訟法第158條]") == ("", "")
    assert normalize_law_levels("[前開商標法第95條第1項]") == (
        "[商標法第95條]", "[商標法第95條]"
    )
    assert normalize_law_levels("[]") == ("", "")
    assert normalize_charges("[三人以上共同詐欺取財未遂罪,攜帶兇器竊盜罪]") == (
        "[詐欺罪,竊盜罪]"
    )
    assert normalize_charges("[吐氣所含酒精濃度達每公升0.25毫克以上而駕駛動力交通工具罪]") == (
        "[酒駕罪]"
    )
    assert normalize_charges("[駕駛動力交通工具而有尿液所含毒品達公告濃度值以上之情形罪]") == (
        "[毒駕罪]"
    )
    assert normalize_charges("[不能安全駕駛動力交通工具罪,圖利聚眾賭博罪]") == (
        "[酒駕罪,賭博罪]"
    )
    assert normalize_charges("[商標法第九十七條之非法販賣侵害商標權之商品罪]") == (
        "[侵害商標權罪]"
    )
    assert normalize_charges("[]") == ""
    assert normalize_charges("[尚未建立分類之罪]") == ""


# 提供原檔新增工作表的預設操作，也允許另存新檔以保留輸入檔。
def main() -> None:
    parser = argparse.ArgumentParser(description="新增罪法刑標準化工作表")
    parser.add_argument("input", type=Path)
    parser.add_argument("-o", "--output", type=Path)
    args = parser.parse_args()
    output = args.output or args.input
    self_check()
    count = normalize_workbook(args.input, output)
    print(f"完成：{count} 筆 → {output}（{OUTPUT_SHEET}）")


if __name__ == "__main__":
    main()
