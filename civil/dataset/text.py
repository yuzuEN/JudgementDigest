"""
文字資料集的清理規則：建資料集（build_dataset.py）和後端處理使用者輸入共用這一份，
訓練時看到的文字和上線時看到的文字才會一致。

版本差異（詳見 build_dataset.py 的說明）：
  v3   刪除聲明句、含「主文」的子句
  v4   再刪「假執行」的聲明殘段；整段 NFKC
  v4b  同 v4，但只轉 BERT 字典沒有的字（帶括號的編號、全形英數），中文標點保留
  v5   聲明整段刪、段尾編號刪；正規化同 v4b，另把 ㊀–㊉ 轉成 ㈠–㈩
"""
import re
import unicodedata

VERSIONS = ("v3", "v4", "v4b", "v5")


def normalize_text(t: str, version: str = "v5") -> str:
    """
    v4：整段 NFKC。但這會把中文全形標點（，：（）；）也改成半形，改動了約 5.6% 的字元（逗號就占 4%），
        而 BERT 預訓練的中文幾乎都用全形標點；v4 的 BERT 比 v3 低了約 0.016，TF-IDF 只低 0.005。
    v4b：只轉 BERT 字典沒有的字——帶括號或圈的編號（㈠、⑴、①、⒈）與全形英數字（Ａ、１），
        中文標點保持原樣（約改動 0.2% 的字元）。
    """
    if version == "v4":
        return unicodedata.normalize("NFKC", t)
    if version == "v5":   # ㊀（U+3280）NFKC 後是沒有括號的「一」，先轉成 ㈠（U+3220）
        t = "".join(chr(ord(c) - 0x60) if 0x3280 <= ord(c) <= 0x3289 else c for c in t)
    return "".join(unicodedata.normalize("NFKC", c)
                   if (0x3220 <= ord(c) <= 0x3243 or 0x2460 <= ord(c) <= 0x24FF
                       or 0xFF10 <= ord(c) <= 0xFF19 or 0xFF21 <= ord(c) <= 0xFF3A
                       or 0xFF41 <= ord(c) <= 0xFF5A)
                   else c for c in t)


DEFAULT_RE = re.compile(r"由其?一造辯論|一造辯論而為判決")
PROC_HEAD_RE = re.compile(r"管轄|準據法|合先敘明")


def leak_re(version: str = "v5") -> "re.Pattern":
    """法院判斷用語（敏感度分析 A6 的規則）＋ 法院整理的爭點、不爭執事項。v5 起「經查證」不算「經查」。"""
    return re.compile(r"本院(?:認|判斷|審酌|斟酌|查|按)|經查" + ("(?!證)" if version == "v5" else "") +
                      r"|得心證|堪信為真|足認"
                      r"|不爭執事項|爭執事項|兩造不爭執|協同兩造|兩造之爭點|本件爭點")


PLAINTIFF_PRAYER_END_RE = re.compile(r"願供擔保[，,]?請准宣告假執行。?$")
ABSENT_RE = re.compile(r"未於(?:最後)?言詞辯論期日到場|未到場|經合法通知")
PROVISIONAL_START_RE = re.compile(r"(?:並(?:答辯|陳明|稱))?[，,；;：:]?\s*(?:[㈠-㈩]|[(（][一二三四五六七八九十][)）])?\s*"
                                  r"(?:[\d①-⑩⒈-⒑]+[.、]?)?\s*(?:原告|被告|伊)?\s*(?:如受不利|願供擔保|請准(?:宣告|免為)?)")
CASE_NO_LINE = re.compile(r"\s*\d+\s*年度\s*\S{1,6}\s*字第\s*\d+\s*號\s*")


def strip_prayer(text: str, drop_provisional: bool = False) -> str:
    """
    刪除聲明與「主文」的部分，保留前面的論述（以「。」分句後逐句處理）：
      - 句中有「聲明」：只保留「聲明」之前的文字（「…等語，資為抗辯，並聲明：原告之訴駁回。」只留論述）
      - 剩下的部分仍有「主文」：刪掉含「主文」的子句（以，；切分）
      - （v4）drop_provisional：再刪掉含「假執行」的子句（沒寫「聲明」兩字的聲明殘留，如「㈡願供擔保請准宣告假執行」）
    """
    out = []
    for sent in re.split(r"(?<=。)", text):
        i = sent.find("聲明")
        if i >= 0:
            sent = re.sub(r"[，,；;：:並及暨]*$", "", sent[:i].rstrip("並"))
        if "主文" in sent:
            sent = "".join(c for c in re.split(r"(?<=[，；,;])", sent) if "主文" not in c)
        # 必須在「聲明」截斷之後：若先刪，含「聲明」的子句（「並聲明：㈠…假執行之聲請均駁回」）會被整句刪掉，
        # 截斷就找不到「聲明」，反而留下後面的聲明殘段（「㈡如受不利判決，願供擔保，」）
        if drop_provisional and "假執行" in sent:
            # 從假執行聲明的開頭截斷（含前面的「並答辯」與編號㈡、(二)、2.），找不到開頭才只刪含「假執行」的子句
            m = PROVISIONAL_START_RE.search(sent)
            if m:
                sent = sent[:m.start()]
            else:
                sent = "".join(c for c in re.split(r"(?<=[，；,;])", sent) if "假執行" not in c)
            sent = re.sub(r"[，,；;：:並及暨]+$", "", sent)
        out.append(sent)
    return "".join(out)


# v5：聲明的開頭。「聲明異議」「聲明參與分配」「聲明承受訴訟」是程序行為，不是訴之聲明
PRAYER_RE = re.compile(r"聲明(?!異議|參與|承受|書|撤回|不服|放棄|拋棄|人)")
# 聲明前面的前綴：「並答辯聲明」「㈢並均聲明」「爰聲明」「先位聲明」
PRAYER_PREFIX_RE = re.compile(
    r"(?:[㈠-㈩㊀-㊉]|[(（][一二三四五六七八九十\d]{1,3}[)）]|\d{1,2}[.、．]|[⒈-⒛①-⑳⑴-⒇])?"
    r"[，,；;：:\s]*(?:並|爰|乃|且|另)?(?:均|為|就此)?(?:答辯|訴之|起訴|先位|備位|上訴|反訴|追加)?$")
# 聲明之後接著的條列項目：以編號開頭，或是聲明的固定寫法
PRAYER_ITEM_RE = re.compile(
    r"^(?:[㈠-㈩㊀-㊉]|[(（][一二三四五六七八九十\d]{1,3}[)）]|\d{1,2}[.、．](?!\d)|[⒈-⒛①-⑳⑴-⒇])"
    r"|^(?:如受不利|願供擔保|請准|訴訟費用|原告之訴|被告應|確認|備位|先位)")
# 聲明之後出現另一段當事人的陳述（「㈡被告甲○○則以：」「（二）李宜璋部分：」），聲明就結束了。
# 不檢查的話，多位被告各寫一段時，第二位被告的整段答辯會被當成聲明的第 ㈡ 項刪掉
# （v5 人工核對 342473、405550；全部 v5 中 1,566 件）
PARTY_OPEN_RE = re.compile(
    r"^(?:[㈠-㈩㊀-㊉]|[(（][一二三四五六七八九十\d]{1,3}[)）]|\d{1,2}[.、．]|[⒈-⒛①-⑳⑴-⒇])?[^。]{0,30}?"
    r"(?:則以|抗辯|辯稱|答辯|部分[：:]|方面[：:]|主張[：:]|陳述|略以)")
# 聲明的一項可以分成好幾句，第二句不一定以編號開頭（「⒈被告應給付…利息。被告許美燕就其所有…按月給付原告…」）
PRAYER_BODY_RE = re.compile(r"(?:應|願|准|按[月日年])[^。]{0,120}?(?:給付|返還|移轉|塗銷|拆除|遷讓|騰空|負擔|假執行|擔保|登記)")
TRAILING_HEAD_RE = re.compile(
    r"(?:(?:[一二三四五六七八九十]{1,3}|[壹貳參叁肆伍陸柒捌玖拾]|[甲乙丙丁戊])、"
    r"|[㈠-㈩㊀-㊉]|[(（][一二三四五六七八九十\d]{1,3}[)）]|\d{1,2}[.、．]|[⒈-⒛①-⑳⑴-⒇])+$")


def strip_prayer_v5(text: str) -> str:
    """
    v5：聲明整段刪（問題 B）。以「。」分句：
      - 句中有聲明：保留聲明之前的論述，連前綴（並答辯、㈢並均）一起刪
      - 聲明之後的句子只要是條列項目（㈡願供擔保…、⒉訴訟費用…）或聲明的內容（應給付、願供擔保…），一起刪；
        遇到一般論述，或另一段當事人的陳述（「㈡被告甲○○則以」）就停
      - 其餘同 v4：含「主文」的子句、含「假執行」的子句刪除
    最後刪掉段尾的段落編號（問題 A）。
    """
    out, in_prayer = [], False
    for sent in re.split(r"(?<=。)", text):
        if in_prayer and not PARTY_OPEN_RE.search(sent) and (PRAYER_ITEM_RE.search(sent) or PRAYER_BODY_RE.search(sent)):
            continue
        in_prayer = False
        m = PRAYER_RE.search(sent)
        if m:
            sent = PRAYER_PREFIX_RE.sub("", sent[:m.start()])
            sent = re.sub(r"[，,；;：:並及暨]+$", "", sent)
            in_prayer = True
        if "主文" in sent:
            sent = "".join(c for c in re.split(r"(?<=[，；,;])", sent) if "主文" not in c)
        if "假執行" in sent:
            pm = PROVISIONAL_START_RE.search(sent)
            if pm:
                sent = sent[:pm.start()]
            else:
                sent = "".join(c for c in re.split(r"(?<=[，；,;])", sent) if "假執行" not in c)
            sent = re.sub(r"[，,；;：:並及暨]+$", "", sent)
        out.append(sent)
    t = "".join(out)
    prev = None
    while prev != t:   # 「…等語。(三)二、」這種連續的編號要刪到乾淨
        prev = t
        t = TRAILING_HEAD_RE.sub("", t)
        t = re.sub(r"[，,；;：:並及暨]+$", "", t)
    return t


def strip_for_version(text: str, version: str = "v5") -> str:
    """依資料集版本刪除聲明（v3 只刪聲明句；v4、v4b 另刪假執行殘段；v5 聲明整段刪）。"""
    if version == "v5":
        return strip_prayer_v5(text)
    return strip_prayer(text, drop_provisional=version in ("v4", "v4b"))


def n_case_numbers(head: str) -> int:
    n = 0
    for line in (head or "").split("\n")[1:8]:
        if CASE_NO_LINE.fullmatch(line):
            n += 1
        elif re.search(r"原\s*告|上\s*訴\s*人|聲\s*請\s*人", line):
            break
    return n


def prepare_input(text: str, version: str = "v5") -> str:
    """
    使用者輸入在送進模型前的處理，對齊資料集裡原告主張段的樣子：
    判決書的段落切分會去掉所有空白（structuring.split_reasoning_sections），資料集再做版本的正規化。
    不刪聲明：使用者的描述不是書狀，沒有訴之聲明，誤刪的風險大於好處。
    """
    return normalize_text(re.sub(r"\s+", "", text or ""), version)
