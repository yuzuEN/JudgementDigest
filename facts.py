# -*- coding: utf-8 -*-
"""
犯罪事實取得與遮蔽（CAIL 格式資料集用）。

事實來源依序判斷：
  1. 附件：判決寫「犯罪事實…引用檢察官起訴書／聲請簡易判決處刑書（如附件）」→ 到全文裡的檢察官書狀
     （以「…檢察署檢察官起訴書」等抬頭定位）找「犯罪事實」段。找不到書狀抬頭（附件是圖檔或沒公開）
     就回報「附件抓不到」，不再從判決本文硬抓，避免誤抓到理由段。
  2. 事實段：判決自己的「事實」「犯罪事實」欄。
  3. 事實及理由第一段：簡易判決把事實寫在「事實及理由」的「一、」，第二段不論是「二、上揭事實」
     「二、證據」「二、核被告所為」都算。
三種來源最後都切掉結尾交代案件來源的「（二、）案經…移送／報告…偵查起訴」。

遮蔽原則（依人工審核結果訂定）：只遮「把罪名當名稱用」的地方，描述行為的字保留。
  - 犯意句「基於○○之犯意／不確定故意／犯意聯絡」的○○一律遮（含改寫過的罪名，如「酒後駕駛動力交通工具」）
  - 本案罪名後接「罪／罪嫌／案件／犯行」時遮（犯○○罪、○○罪嫌、前因○○案件）
  - 法條只遮「第○條（之○）（第○項）（第○款）」本身，以及緊接在前的法律名稱
  - 不遮：施用、侵占入己、詐欺集團、受有傷害、意圖為自己不法之所有
"""

import re
from typing import Iterable, List, Tuple

MASK = "××"
NUM = "零〇○一二兩三四五六七八九十百千萬壹貳參叁叄肆伍陸柒捌玖拾佰仟0-9"
ZERO_WIDTH = re.compile(r"[​-‏⁠﻿]")

# 判決說事實引用檢察官書狀
REF_RE = re.compile(r"引用[^。]{0,40}(?:起訴書|處刑書|移送併辦意旨書|聲請書)")
# 附件裡檢察官書狀的抬頭
PROSECUTOR_HEAD_RE = re.compile(
    r"檢察署\s*檢察官\s*(?:聲請簡易判決處刑書|簡易判決處刑書|追加起訴書|起訴書|移送併辦意旨書|聲請書)")
# 書狀裡獨立成行的「犯罪事實」標題（排除「茲將犯罪事實及證據…分敘如下」這種句子）
FACT_HEAD_RE = re.compile(
    r"(?:^|\n)[ \t　]*(?:[一二三四五六七八九十]+、[ \t　]*)?犯[ \t　]*罪[ \t　]*事[ \t　]*實"
    r"(?![ \t　]*及[ \t　]*證[ \t　]*據)(?:[ \t　]*要[ \t　]*旨)?[ \t　]*[:：]?")
# 書狀裡事實段的結尾：證據段標題、或交代案件來源的「案經」行
FACT_END_RE = re.compile(
    r"\n[ \t　]*(?:證[ \t　]*據[ \t　]*並[ \t　]*所[ \t　]*犯[ \t　]*法[ \t　]*條"
    r"|證[ \t　]*據[ \t　]*清[ \t　]*單|[一二三四五六七八九十]+、[ \t　]*證[ \t　]*據"
    r"|(?:[一二三四五六七八九十]+、)?[ \t　]*案[ \t　]*經)")
# 事實及理由第一段：「一、（犯罪事實（要旨）：）…」到「二、」之前
FIRST_PARA_RE = re.compile(r"^一、(?:犯罪事實(?:要旨)?[：:])?(.{30,}?)(?=二、)")
NOT_FACT_START = ("按", "本件", "本案", "查", "核", "經查", "公訴意旨", "證據")
# 「被告」開頭可能是事實（「被告甲○○於民國…」「被告○○明知…」）也可能是理由（「被告所為係犯…」）
REASONING_RE = re.compile(r"^被告[^，。]{0,6}?(?:所犯|所為|坦承|自白|之犯行|犯行|於偵查|於警詢|於本院|於審理)")
# 結尾的案件來源句
CASE_ORIGIN_RE = re.compile(
    r"(?:[一二三四五六七八九十]+、)?案經[^。]{0,200}?(?:移送|報告|告訴|告發|訴由|偵查|聲請|起訴|偵辦|簽分|自動檢舉)[^。]*。?$")


def compact(text) -> str:
    return re.sub(r"\s+", "", ZERO_WIDTH.sub("", str(text or "")))


def trim_case_origin(fact: str) -> str:
    """切掉結尾「（二、）案經…偵查起訴。」；中間引述的「案經」不動。"""
    fact = fact.rstrip("。") + "。" if fact else fact
    m = CASE_ORIGIN_RE.search(fact)
    if m and m.start() > 20:
        fact = fact[:m.start()]
    fact = re.sub(r"[二三四五六七八九十]+、$", "", fact)   # 被切掉後殘留的段號
    fact = re.sub(r"。{2,}$", "。", fact)
    return fact.strip()


def attachment_fact(full_text: str, ref_pos: int = 0) -> str:
    """從全文裡的檢察官書狀取「犯罪事實」段；找不到書狀抬頭或標題時回傳空字串。"""
    text = ZERO_WIDTH.sub("", str(full_text or ""))
    for head in PROSECUTOR_HEAD_RE.finditer(text, ref_pos):
        sub = text[head.end():]
        fh = FACT_HEAD_RE.search(sub)
        if not fh:
            continue
        body = sub[fh.end():]
        end = FACT_END_RE.search(body)
        fact = compact(body[:end.start()] if end else body[:3000])
        if len(fact) >= 20:
            return fact
    return ""


def get_fact(facts="", criminal_facts="", facts_and_reasons="", reasons="", full_text="") -> Tuple[str, str]:
    """回傳 (事實文字, 來源)。來源：附件／事實段／事實及理由第一段／附件抓不到／無。"""
    body = compact(facts_and_reasons) + compact(reasons)
    if REF_RE.search(body):
        ft = str(full_text or "")
        ref = REF_RE.search(ft)
        fact = attachment_fact(ft, ref.end() if ref else 0)
        return (trim_case_origin(fact), "附件") if fact else ("", "附件抓不到")
    own = compact(facts) + compact(criminal_facts)
    if len(own) >= 20:
        return trim_case_origin(re.sub(r"^(?:事實|犯罪事實)[：:]?", "", own)), "事實段"
    m = FIRST_PARA_RE.search(compact(facts_and_reasons))
    if m and not m.group(1).startswith(NOT_FACT_START) and not REASONING_RE.match(m.group(1)):
        return trim_case_origin(m.group(1)), "事實及理由第一段"
    return "", "無"


# ─── 遮蔽 ─────────────────────────────────────────────────────────────────────
ARTICLE = rf"第[{NUM}]+條(?:之[{NUM}]+)?(?:第[{NUM}]+項)?(?:(?:前段|後段|但書))?(?:第[{NUM}]+款)?(?:(?:前段|後段))?"
# 法律名稱只認列舉的名稱（含「同法」「該條例」等指代），不用「任意字＋法」去猜：
# 舊版用 [一-鿿]{1,12}?(?:條例|法) 會往前吃掉主詞與毒品名稱
# （「甲○○知悉甲基安非他命係毒品危害防制條例第2條」→「××所規定」），人工審核發現後改成列舉。
LAW_NAMES = (
    "中華民國刑法", "陸海空軍刑法", "刑法", "毒品危害防制條例", "洗錢防制法", "組織犯罪防制條例",
    "槍砲彈藥刀械管制條例", "道路交通管理處罰條例", "家庭暴力防治法", "商標法", "藥事法",
    "廢棄物清理法", "個人資料保護法", "兒童及少年性剝削防制條例", "兒童及少年福利與權益保障法",
    "性騷擾防治法", "性侵害犯罪防治法", "跟蹤騷擾防制法", "公司法", "證券交易法", "銀行法",
    "稅捐稽徵法", "商業會計法", "森林法", "就業服務法", "電信法", "著作權法", "野生動物保育法",
    "入出國及移民法", "貪污治罪條例", "懲治走私條例", "公職人員選舉罷免法", "建築法", "水土保持法",
    "區域計畫法", "動物保護法", "妨害兵役治罪條例", "替代役實施條例", "保護令",
    "同法", "同條例", "該法", "該條例", "本法", "本條例", "前開條例", "前揭條例", "上開條例", "上述條例",
)
LAW_CITE_RE = re.compile(
    rf"(?:(?:修正前|修正後)?(?:{'|'.join(map(re.escape, sorted(LAW_NAMES, key=len, reverse=True)))}))?{ARTICLE}")
# 犯意句內可含逗號（「基於意圖營利，供給賭博場所、聚眾賭博之犯意」），但不跨句、不跨另一個「基於」
INTENT_RE = re.compile(r"基於(?P<inner>(?:(?!基於)[^。；]){1,60}?)之(?:不確定故意|未必故意|間接故意|犯意聯絡|犯意|單一犯意|故意)")


def _mask_intent(m: re.Match) -> str:
    """犯意句整串遮成一個××（罪名裡常有「及、與、或」，如「兒童及少年」「參與」，不拆開，也不透露罪數）。"""
    inner = m.group("inner")
    lead = ""
    if "之" in inner:                       # 「縱有人…亦不違背其本意之幫助詐欺取財及洗錢」→只遮最後一段
        cut = inner.rfind("之") + 1
        lead = inner[:cut]
    return m.group(0).replace(inner, lead + MASK, 1)


def charge_keys(charges: Iterable[str]) -> List[str]:
    """罪名字串去掉結尾「罪」，再加上常見簡稱，長的先遮。"""
    keys = set()
    for ch in charges:
        ch = re.sub(r"罪$", "", str(ch or "").strip())
        if len(ch) >= 2:
            keys.add(ch)
    return sorted(keys, key=len, reverse=True)


def mask_fact(fact: str, charges: Iterable[str] = ()) -> str:
    text = INTENT_RE.sub(_mask_intent, fact)
    for key in charge_keys(charges):
        text = re.sub(re.escape(key) + r"(?=(?:等)?(?:罪|案件|犯行))", MASK, text)
    # 法條：只保留遮蔽後的引導詞（「依」「違反」）
    text = re.sub(LAW_CITE_RE, lambda m: MASK, text)
    text = re.sub(rf"{MASK}(?:{MASK})+", MASK, text)
    return text


def leaks(text: str, charges: Iterable[str] = ()) -> bool:
    """遮蔽後是否仍看得到本案罪名名稱或條號。"""
    if re.search(ARTICLE, text):
        return True
    return any(re.search(re.escape(k) + r"(?:等)?(?:罪|案件|犯行)", text) for k in charge_keys(charges))
