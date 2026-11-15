"""
當事人欄與一造辯論的重新解析（步驟 1）。

純函式、不碰資料庫；build_fields.py 負責讀資料庫並呼叫這裡。
規則出處：01_欄位核對方法.md 第 2 節、第二核對者回饋查核報告第 3、5 節。

  parse_party_block(text)  從全文開頭的當事人欄取出原告／被告名單（修斷行、括號、重複、假名字）
  classify_party(name)     自然人／公司團體／政府機關（「X即Y」獨資一律自然人）
  default_party(text, n_def, defendants)  一造辯論與誰缺席

2026-11-12 併入 repo（規則 2.5.2，structuring.defendant_is_corp_of 用它）。全庫回填比對時補了幾種漏網：
名稱中間的機關（「…市政府…大隊」「…檢察署檢察官」「…委員會…中心」）、學校簡稱、名字後接的在監說明、「原居…」舊地址行、機關擔任遺產管理人（「…分署即某某之遺產管理人」）、
「原告即反訴／被告」稱謂斷行、名稱含門牌字的團體（「…10號大樓管理委員會」）。測試在 tests/test_parties.py。
"""
import re

# ───────────────────────── 當事人欄 ─────────────────────────

# 稱謂（代理人類）：該行是代理人，不是當事人；只有「兼」開頭的才同時是當事人
_LABEL_WORDS = ["共同訴訟代理人", "訴訟代理人", "法定代理人", "法定代理", "複代理人", "複代理", "選任辯護人", "指定辯護人",
                "辯護人", "特別代理人", "訴訟輔佐人", "輔佐人", "送達代收人", "代理人", "代表人", "管理人", "清算人",
                "破產管理人", "遺產管理人", "遺囑執行人", "受告知訴訟", "訴訟代理"]
_LABEL_RE = re.compile(r"^(?:共同)?(?:" + "|".join(_LABEL_WORDS) + ")")


def _is_label_fragment(comp):
    """稱謂被斷行拆開的殘片：「法定」「送達代收」「同訴訟代理」。至少 2 字，且是某個稱謂的一部分。"""
    return len(comp) >= 2 and any(comp in w or comp in "共同" + w for w in _LABEL_WORDS)


# 「兼」之後可能斷行的稱謂殘片：訴／訟代理人／法定代理
_JIAN_LABEL_STRIP = re.compile(r"^(?:共同|同|法定代理人|法定代理|訴訟代理人|訴訟代理|訟代理人|訟代理|定代理人|定代理|代理人|訴訟|訴|訟)+")
_JIAN_FRAGMENT_ONLY = re.compile(r"^(?:共同|同|共|法定代理人|法定代理|訴訟代理人|訴訟代理|訟代理人|訟代理|定代理人|代理人|訴訟|訴|訟|人)*$")
_JIAN_IGNORE_LABEL = re.compile(r"^(?:送達代收人|特別代理人|複代理人|辯護人|選任辯護人)")  # 「訴訟代理人兼送達代收人」：不是當事人
_UP_N = re.compile(r"^(?:上|前)(?:列)?(?:[一二三四五六七八九十百0-9]+(?:人|被告|原告)?|被告|原告)?(?:之|共同|共|同)?")

_ROLE_RE = re.compile(r"^(?:追加)?(?:(原|被)告|(聲請人)|(相對人))")
_COUNTER_RE = re.compile(r"^即?反訴(?:原|被)告")
_OTHER_ROLE_RE = re.compile(r"^(?:訴訟|輔助|獨立|補充|追加|共同)?(?:參加人|關係人|第三人|利害關係人|參與人|受告知人|被告知人|告知人)")
_ROLE_PREFIX_SPACED = re.compile(
    r"^\s*(?:追\s*加)?\s*(?:(?:原|被)\s*告|聲\s*請\s*人|相\s*對\s*人)(?:\s*(?:即|兼|及)\s*反訴\s*(?:原|被)\s*告)?\s*")
_ALSO_ROLE = re.compile(r"^即(?:反訴|主參加|參加)?(?:原告|被告)")   # 「即反訴被告 莫漢生」：同一人的另一個稱謂
_MID_ROLE = re.compile(r"(?<=\S)[ \u3000]+((?:原|被)[ \u3000]*告[ \u3000]+(?=\S))")  # 同一行裡又出現「被 告 X」

_NOISE_COMPACT = re.compile(
    r"^(?:(?:上|前)(?:列)?(?:[一二三四五六七八九十0-9]+)?(?:人|被告|原告|當事人)(?:之|共同|均).*|(?:上|前)(?:列)?[^，。]{0,8}人(?:共同|均|之)?|"
    r"共同|均|人|等|等人|即|即.{0,6}反訴.*|以上共同.*|如附表.*|[一二三四五六七八九十百\d]+人|(?:上|前)列.*共同|"
    r"(?:指定)?送達.*|住.*|居.*|地址.*|現(?:住|居|應受送達).*|戶籍.*|籍設.*|設.*|身分證.*|統一編號.*|"
    r"國民身分證.*|郵遞區號.*|電話.*|之\d.*|\d+(?!\d)(?:[號樓之弄巷路街段室鄰村里].*|[^\u4e00-\u9fff].*)?|現於.*|現另案.*|另案.*|原(?:住|居|設|籍).*|[（(].*)$")
# 名字後面直接接在監、另案的說明（「王大明另案於法務部○○監獄執行」）：只留名字
_TRAILING_NOTE = re.compile(r"(?<=[一-鿿○]{2})(?:另案|現於|現在|現另案|在監|現羈押).*$")
_ADDRESS_LIKE = re.compile(r"[路街巷弄樓號]")
# 名稱本身含門牌字（「湯城園區10號大樓管理委員會」）：結尾是團體名稱就不是地址
_ORG_END = re.compile(r"(?:委員會|公司|銀行|工會|協會|合作社|基金會|公會)$")
_COUNTER_WRAP = re.compile(r"((?:^|\n)[ \t　]*(?:原|被)[ \t　]*告[ \t　]*(?:即|兼|及)[ \t　]*反[ \t　]*訴)[ \t　]*\n[ \t　]*((?:原|被)[ \t　]*告)")
_ADDR_CUT = re.compile(r"\s+(?:住|居|設|籍設|籍|地址|現|戶籍|送達|寄|指定|原設|原住|原居|原籍|"
                       r"(?=[\u4e00-\u9fff]{1,4}[縣市](?:○|[\u4e00-\u9fff]{0,6}[鄉鎮市區])))")
_ADDR_INLINE = re.compile(r"(?:住|居|設|籍設|地址)(?=[^\s]{0,4}(?:[縣市]|○○|臺北|台北|新北))")

_FAKE_NAMES = {"人", "原", "被", "告", "等", "共同", "均", "同", "即"}


def _strip_index(s):
    """去掉編號前綴：「1黃廖鳳妹」→「黃廖鳳妹」。只對短名字（人名）做；「21世紀不動產股份有限公司」不動。"""
    m = re.match(r"^\d{1,3}([\u4e00-\u9fff○]{2,5})$", s)
    return m.group(1) if m else s


_NAME_BEFORE_ADDR = re.compile(r"(?:^|\s)([\u4e00-\u9fff○]{2,6})\s+(?:住|居|籍設|設|現)")


def _multi_names(ln):
    """同一行有兩位以上當事人、各自接著地址：「林佳寬 住… 林碧玉 住…」。回傳名字清單（少於 2 位回傳空）。"""
    ns = _NAME_BEFORE_ADDR.findall(ln)
    return ns if len(ns) >= 2 else []


def _balanced(s):
    return s.count("（") + s.count("(") <= s.count("）") + s.count(")")


_BLOCK_END = re.compile(r"^(?:上列(?!(?:被告|原告)?[一二三四五六七八九十0-9]+人)|上當事人|當事人間|主文|事實及理由|本件|按|為.{0,10}事件)")


def party_block(full_text):
    """全文開頭的當事人欄：到「上列當事人間…」「當事人間…」「判決如下」「主文」那一行之前。
    「兼上列一人」「上列三人共同」是當事人欄裡的稱謂，不算結尾。"""
    head = (full_text or "")[:4000]
    out = []
    for ln in head.split("\n"):
        comp = re.sub(r"\s+", "", ln)
        if comp and (_BLOCK_END.match(comp) or re.search(r"判決如下|言詞辯論終結|本院於民國", comp)):
            break
        out.append(ln)
        if len(out) > 400:
            break
    return "\n".join(out)


def parse_party_block(text):
    """
    回傳 (plaintiffs, defendants)：兩個名單，每個元素 dict(name, full)。
    name＝去掉括號註記的主名稱；full＝含括號註記的完整名稱（括號斷行已接回）。
    規則（01_欄位核對方法.md 第 2 節）：「兼」的人也是當事人；法定代理人、訴訟代理人、律師不是；
    「X即Y」算一人；括號裡的舊名不算另一人；斷行的稱謂與括號先接回。
    """
    # 「原告即反訴／被告 某某」：稱謂斷在「反訴」之後，下一行的「被告」不是新的一造，接回同一行
    text = _COUNTER_WRAP.sub(lambda m: m.group(1) + m.group(2), text or "")
    text = _MID_ROLE.sub(
        lambda m: m.group(0) if re.sub(r"\s+", "", m.string[:m.start()]).endswith(("追加", "反訴", "即", "主參加")) else "\n" + m.group(1),
        text or "")
    lines = [ln.strip() for ln in text.replace("\r", "").split("\n")]
    sides = {"原": [], "被": []}
    st = {"role": None, "pending": False, "in_agent": False, "last": None}

    def add(raw):
        raw = re.sub(r"\s+", "", raw)
        raw = _ALSO_ROLE.sub("", raw)
        raw = re.sub(r"^主?參加(?:原告|被告)", "", raw)
        raw = re.sub(r"(?<=[^\d])\d{3,}$", "", raw)
        raw = _strip_index(raw)
        raw = _TRAILING_NOTE.sub("", raw)
        m_in = _ADDR_INLINE.search(raw)
        if m_in and m_in.start() >= 2:
            raw = raw[:m_in.start()]
        if not raw or re.search(r"[，。]", raw):
            return
        main = re.split(r"[（(]", raw, maxsplit=1)[0]
        if (len(main) < 2 and main not in "甲乙丙丁戊己庚辛壬癸" and not main.startswith("○")) or main in _FAKE_NAMES:
            return
        if len(main) <= 10 and re.search(r"被告|原告|代理|代收|告知|共同", main) and not re.search(r"(公司|委員會|合作社|協會|基金會)$", main):
            return
        d = {"name": main, "full": raw}
        sides[st["role"]].append(d)
        st["last"] = d

    def jian(comp):
        """處理「兼…」行（comp 已去空白、已去掉開頭的「兼」）。"""
        st["in_agent"] = False
        r = re.sub(r"^(?:被告|原告|反訴原告|反訴被告)", "", _UP_N.sub("", comp))
        if _JIAN_IGNORE_LABEL.match(r):
            st["pending"] = False
            st["in_agent"] = True
            return
        if _JIAN_FRAGMENT_ONLY.match(r):
            st["pending"] = True
            return
        r = _JIAN_LABEL_STRIP.sub("", r)
        r = re.sub(r"^人(?=.{2,})", "", r)
        if _is_label_fragment(r) or r == "":
            st["pending"] = True
            return
        add(re.split(r"[（(]", r, maxsplit=1)[0] if r.startswith(("住", "居", "設")) is False else r)
        st["pending"] = False

    for ln in lines:
        if not ln:
            continue
        comp = re.sub(r"\s+", "", ln)
        last = st["last"]

        # 括號斷行：上一位的括號還沒閉合，這行若是接續（沒有自己的開括號、有右括號）就接回；
        # 否則判定原文括號漏了右半，補上並照一般行處理（否則會吞掉後面所有當事人）。
        if last is not None and not _balanced(last["full"]):
            if "（" not in comp and "(" not in comp and (")" in comp or "）" in comp) and len(comp) <= 60:
                last["full"] += comp
                continue
            if "（" not in comp and "(" not in comp and len(comp) <= 30 and not re.search(r"[即兼]", comp[:2]) \
                    and not _ROLE_RE.match(comp) and not _LABEL_RE.match(comp) and not st.get("cont"):
                st["cont"] = True   # 允許再接一行（舊名斷成兩行以上）
                last["full"] += comp
                continue
            last["full"] += "）"
        st["cont"] = False

        if _COUNTER_RE.match(comp) and st["role"] is not None:   # 「原告即／反訴被告 丁世昌」：同一人的另一個稱謂
            rest = re.sub(r"^\s*即?\s*反\s*訴\s*(?:原|被)\s*告\s*", "", ln)
            rest_c = re.sub(r"\s+", "", rest)
            if rest_c and not _NOISE_COMPACT.match(rest_c) and not _LABEL_RE.match(rest_c):
                add(_ADDR_CUT.split(rest, maxsplit=1)[0])
            elif _LABEL_RE.match(rest_c):
                st["in_agent"] = True
            continue
        m = _ROLE_RE.match(comp)
        if m:
            st["role"] = m.group(1) or ("原" if m.group(2) else "被")
            st["pending"] = False
            st["in_agent"] = False
            rest = _ROLE_PREFIX_SPACED.sub("", ln, count=1)
            rest = _ADDR_CUT.split(rest, maxsplit=1)[0]
            rest_c = re.sub(r"\s+", "", rest)
            if rest_c.startswith("兼"):
                jian(rest_c[1:])
                continue
            if _LABEL_RE.match(rest_c):
                st["in_agent"] = True
                continue
            rest_c2 = _ALSO_ROLE.sub("", rest_c)
            if rest_c2 and not _NOISE_COMPACT.match(rest_c2) and not (_ADDRESS_LIKE.search(rest_c2) and re.search(r"[\d○]", rest_c2)
                                                                       and not _ORG_END.search(rest_c2)):
                add(rest)
            continue
        if _OTHER_ROLE_RE.match(comp):
            st["role"] = None
            st["last"] = None
            st["pending"] = False
            st["in_agent"] = False
            continue
        if st["role"] is None:
            continue

        if comp.startswith("兼"):
            jian(comp[1:])
            continue
        if st["pending"]:
            st["in_agent"] = False
            r = _JIAN_LABEL_STRIP.sub("", re.sub(r"^[一二三四五六七八九十百\d]+人(?:之|共同)?", "", _UP_N.sub("", comp)))
            r = re.sub(r"^人(?=.{2,})", "", r)
            if _JIAN_IGNORE_LABEL.match(comp):
                st["pending"] = False
                st["in_agent"] = True
                continue
            if r == "" or _JIAN_FRAGMENT_ONLY.match(r):
                continue
            add(re.split(r"[（(]", r, maxsplit=1)[0])
            st["pending"] = False
            continue

        if _LABEL_RE.match(comp) or _is_label_fragment(comp):
            st["in_agent"] = True
            continue
        if st["in_agent"]:
            continue
        if comp.endswith("律師") and not re.search(r"(事務所|公司)", comp):
            continue
        if len(comp) == 1 and comp != "人" and last is not None:
            last["name"] += comp  # 「…台灣分公／司」之類的斷行
            last["full"] += comp
            continue
        c2 = _ALSO_ROLE.sub("", comp)
        if c2 != comp:  # 「即反訴被告 莫漢生」
            rest = re.sub(r"^\s*即\s*(?:反訴|主參加|參加)?\s*(?:原|被)\s*告\s*", "", ln)
            if rest.strip() and not _NOISE_COMPACT.match(re.sub(r"\s+", "", rest)):
                add(_ADDR_CUT.split(rest, maxsplit=1)[0])
            continue
        comp_nd = _strip_index(comp)
        if _NOISE_COMPACT.match(comp_nd):
            # 「（現應受送達處所不明）」之類接在上一位後面
            if last is not None and comp.startswith(("（", "(")):
                last["full"] += comp
            continue
        mn = _multi_names(ln)
        if mn:
            for n in mn:
                add(n)
            continue
        name = _ADDR_CUT.split(ln, maxsplit=1)[0]
        nc = re.sub(r"\s+", "", name)
        if _ADDRESS_LIKE.search(nc) and re.search(r"[\d○]", nc) and not re.search(r"(公司|銀行|工會|協會)", nc) \
                and not _ORG_END.search(nc):
            continue
        add(name)

    out = []
    for side in ("原", "被"):
        seen, lst = set(), []
        for p in sides[side]:
            if p["name"] in seen and not re.search(r"[○Ｏ]|(?<!\d)0{2,}", p["name"]):   # 去識別化代號（○○○、李00）不同人可同名，不去重
                continue
            seen.add(p["name"])
            lst.append(p)
        out.append(lst)
    return out[0], out[1]


# ───────────────────────── 當事人類型 ─────────────────────────

# 公司團體：有當事人能力的私法人與非法人團體（分公司、管理委員會、寺廟、祭祀公業等）
_CORP = re.compile(
    r"(股份有限公司|有限公司|無限公司|兩合公司|公司|銀行|商業銀行|信用合作社|合作社|合作農場|基金會|協會|學會|"
    r"工會|公會|商會|農會|漁會|社團法人|財團法人|醫療法人|管理委員會|管理負責人|分公司|辦事處|"
    r"祭祀公業|教會|聯合會|促進會|重劃會|儲蓄互助社|有限合夥|合夥|事務所|"
    r"保險|證券|票券|租賃|資產管理|金控|控股|企業社|企業行|商行|商號|工廠|診所|醫院|藥局|旅行社|飯店|公同共有|"
    r"(?i:LIMITED|LTD|INC|CORP|LLC|GMBH|PTE|CO\.|COMPANY|BANK|S\.A\.))")
# 政府機關：中央與地方機關、公立學校與醫院
_GOV_PREFIX = re.compile(r"^(?:.{0,4}榮民總醫院|.{0,4}榮總|中華民國|國立|市立|縣立|省立|公立|國軍|榮民|國防部|法務部|財政部|衛生福利部|教育部|內政部|經濟部|交通部|外交部|"
                         r"勞動部|文化部|農業部|環境部|數位發展部|行政院|考試院|監察院|立法院|司法院|中央研究院|中央|國家|臺灣省|台灣省|"
                         r"陸軍|海軍|空軍|憲兵|海巡|國軍)")
_PUBLIC_MID = re.compile(r"[國省市縣鄉鎮區]立")
_TEMPLE_END = re.compile(r"(?:寺|宮|廟|堂|庵|殿|禪寺|佛堂)$")
_TEMPLE_MID = set("天聖福德仁慈武關保玉太正廣回法樂善佛祥龍鳳靈媽安朝極清濟惠")
_BIZ_END = re.compile(r"(?:店|館|行|社|坊|廠|企業|實業|科技|工程|貿易|開發|建設|營造|醫院|診所)$")
_GOV_OFFICE = re.compile(r"(?:地政|戶政|稅務|公證|登記|衛生|監理|管理|工務|農田水利|水利|山地)(?:事務所|所)$")
_GOV_END = re.compile(
    r"(政府|公所|署|分署|局|分局|處|分處|廳|部|議會|代表會|法院|檢察署|監獄|看守所|派出所|"
    r"學校|大學|國中|國小|高中|國民中學|國民小學|幼兒園)$")
_GOV_COMMITTEE = re.compile(r"委員會$")
_NOT_GOV_COMMITTEE = re.compile(r"(管理|福利|籌備|自救|地下室|社區|大樓|大廈|公寓|重劃|整體開發|聯合|同鄉|同學|校友|籌建)")
# 2.5.2 全庫回填時找到的漏網：名稱中間出現機關（「新北市政府違章建築拆除大隊」「臺灣屏東地方檢察署檢察官」），
# 以及學校簡稱（「新北市達觀國中小學」）。人名不會含這些字。
_GOV_ANYWHERE = re.compile(r"政府|檢察署|法院|檢察官$|署|(?<!管理)委員會.+(?:中心|處|局|署|隊|所|館)$")
_SCHOOL_END = re.compile(r"(?:小學|中學|大學|國中小|學校)$")
_PRIVATE = re.compile(r"私立|財團法人|社團法人")
_ORG_NAME = re.compile(r"(股份|有限)公司|銀行")


def _is_gov(main):
    """「X即Y」左邊是不是機關：只認明確的機關字樣（部會開頭、X立、政府、署、法院）。
    只看結尾（廳、處、局）會把「北極熊咖啡廳即某某」這類獨資商號誤判成機關。"""
    if _ORG_NAME.search(main):
        return False
    return bool(_GOV_PREFIX.match(main) or _PUBLIC_MID.search(main) or _GOV_ANYWHERE.search(main))


def classify_party(name_full):
    """回傳 '自然人' / '公司團體' / '政府機關'。name_full 可含括號註記。"""
    s = re.sub(r"\s+", "", name_full or "")
    main = re.split(r"[（(]", s, maxsplit=1)[0]
    paren = s[len(main):]
    if not main:
        return "自然人"
    # 「X即Y」：獨資商號／事務所／醫院與主人一體，當事人是自然人（最高法院 43 台上 601）。
    # 例外：兩邊都是公司（更名）。
    if "即" in main:
        left, right = main.split("即", 1)
        if re.search(r"(?:股份)?有限公司$", left) and re.search(r"(?:股份)?有限公司", right) and "破產" not in right:
            main = left
        elif "即" not in left and _is_gov(left):
            # 「財政部國有財產署北區分署即某某之遺產管理人」：機關擔任管理人，不是獨資商號
            return "政府機關"
        else:
            return "自然人"
    if _GOV_ANYWHERE.search(main) and not _ORG_NAME.search(main):
        return "政府機關"
    if _SCHOOL_END.search(main) and len(main) >= 4:
        return "公司團體" if _PRIVATE.search(main) else "政府機關"
    if (_GOV_PREFIX.match(main) or _PUBLIC_MID.search(main)) and not re.search(r"(股份|有限)公司|銀行|財團法人|社團法人", main):
        return "政府機關"
    if _TEMPLE_END.search(main) and (len(main) >= 4 or (len(main) == 3 and main[-1] in "宮寺廟庵" and main[1] in _TEMPLE_MID)):
        return "公司團體"
    if _GOV_OFFICE.search(main):
        return "政府機關"
    if _CORP.search(main):
        return "公司團體"
    if _GOV_COMMITTEE.search(main):
        return "公司團體" if _NOT_GOV_COMMITTEE.search(main) else "政府機關"
    if _GOV_END.search(main) and len(main) >= 3:
        return "政府機關"
    if _BIZ_END.search(main) and len(main) >= 4:
        return "公司團體"
    # 括號內為「即改制前…」的舊名：主名稱沒有線索時看括號
    if "改制" in paren and _GOV_END.search(re.sub(r"[（()）]", "", paren)):
        return "政府機關"
    return "自然人"


# ───────────────────────── 一造辯論 ─────────────────────────

_CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
_ANCHOR = re.compile(r"(?:第)?386條(?:各款|所列|所定|之各款|之規定|所載)")
_YIZAO = re.compile(r"一造辯論")
_ABSENT = re.compile(r"未[^，。；]{0,12}到場|不到場|均未到庭|未到庭|未出庭|無正當理由.{0,6}到場")


def _num(s):
    if s.isdigit():
        return int(s)
    if s in _CN_NUM:
        return _CN_NUM[s]
    return None


def _clause_before_anchor(c, pos):
    """386 條那句之前、同一句中的主語子句（到前一個「。」或「、」編號為止）。"""
    start = max(c.rfind("。", 0, pos), c.rfind("：", 0, pos), c.rfind("；", 0, pos)) + 1
    return c[start:pos]


_HEAD = re.compile(r"^.*?(?:[一二三四五六七八九十壹貳參肆伍陸柒捌玖拾甲乙丙丁]、|程序事項|程序方面|程序部分|程序上|事實及理由)")
_CONJ = re.compile(r"^(?:又|另|再|而|惟|但|且|按|次按|復按|經查)+")


def _strip_heading(cl):
    """去掉子句前面的標題與編號（「事實及理由壹、程序事項本件被告…」→「本件被告…」）。"""
    prev = None
    while prev != cl:
        prev = cl
        cl = _HEAD.sub("", cl, count=1) if len(_HEAD.sub("", cl, count=1)) >= 4 else cl
    return _CONJ.sub("", cl)


_GENERIC = re.compile(r"當事人之一造|定有明文|得依到場|按言詞辯論期日|次按|揆諸|判決在案|另案|前案|依上開規定|查詢")
_SUBJ_CUT = re.compile(r"(?:且|並|經|而)?核無|爰|依民事訴訟法|依同法|准|應依|依到場|是以|故")


def default_party(full_text, defendants, plaintiffs=()):
    """
    回傳 (default_party, detail, clause)。
      default_party ∈ {'無', '全部被告缺席', '部分被告缺席', '原告缺席', '無法判定'}
      detail：'換行漏抓'（原本的規則抓不到、去空白後才抓到）、'簡稱未對應'（子句點名的被告對不上名單）、
              '無一造辯論字樣但被告未到場'
      clause：據以判斷的主語子句（供稽核）
    判斷依據：每個「一造辯論」之前、同一句裡的主語子句（誰未到場）；法條引述、他案引述的子句略過。
    """
    raw = full_text or ""
    c = re.sub(r"\s+", "", raw)
    has_raw = bool(_YIZAO.search(raw))
    positions = [m.start() for m in _YIZAO.finditer(c)]
    detail = []
    if positions and not has_raw:
        detail.append("換行漏抓")

    if not positions:
        if re.search(r"被告.{0,40}未於[^，。]{0,10}(言詞辯論)?期日到場", c[:12000]) and not re.search(r"被告(?:則)?(?:以|辯稱|抗辯|答辯)", c):
            return "無", "無一造辯論字樣但被告未到場", ""
        return "無", "", ""

    n_def = len(defendants)
    names = [d["name"] for d in defendants]
    absent_def, plaintiff_absent, all_flag, unmatched = set(), False, False, False
    used = []
    for pos in positions:
        start = max(c.rfind(ch, 0, pos) for ch in "。：:") + 1
        cl = c[start:pos]
        if not re.search(r"到場|到庭|出庭|通知|送達|提訊", cl) and start > 1:
            # 「…且核無第386條各款情形。爰依原告聲請，由其一造辯論」：主語在上一句，再往前接一句
            start2 = max(c.rfind(ch, 0, start - 1) for ch in "。：:") + 1
            cl = c[start2:pos]
            start = start2
        if len(cl) > 500 or _GENERIC.search(cl) or "反訴" in cl:
            continue
        cut = _SUBJ_CUT.search(cl)
        subj_raw = cl[:cut.start()] if cut else cl
        if not re.search(r"被告|原告|兩造|本件|到場|到庭|出庭", subj_raw):
            continue
        tail = c[pos - 40:pos + 4]
        req = r"被告(?:\d+人|[一二三四五六七八九十]人|等人?)?(?:之|等之)?(?:聲請|請求)"
        if re.search(r"(?:依|准|應准|依據|經)" + req, c[start:pos + 6]) or \
                (re.search(req, cl) and "原告" in subj_raw):
            plaintiff_absent = True
            used.append(subj_raw)
            continue
        subj = _strip_heading(subj_raw)
        used.append(subj)
        m0 = re.search(r"(?:本件|兩造|認|查)?被告(?:等人|等|(\d+|[一二三四五六七八九十]+)人)(?:均|皆)?(?:經|未|無|於|因|在|就|雖|受)", subj)
        if m0:  # 「被告等」「被告二人」「被告2人」：沒點名，只給人數
            k0 = _num(m0.group(1)) if m0.group(1) else None
            if k0 is None or not n_def or k0 >= n_def:
                all_flag = True
            else:
                absent_def |= {f"#{i}" for i in range(k0)}
            continue
        m = re.search(r"等(\d+|[一二三四五六七八九十]+)人", subj)
        hit = {n for n in names if n and n in subj}
        codes = set(re.findall(r"[甲乙丙丁戊己庚辛壬癸][○Ｏ0]{1,2}", subj))   # 去識別化代號：甲○○、乙○○
        if codes and not hit and not m:
            if n_def and len(codes) >= n_def:
                all_flag = True
            else:
                absent_def |= {f"#{c}" for c in codes}
            continue
        if re.search(r"被告(?:均|皆|二人|兩人)?(?:經|未|無|於|因|在|就|雖|受)", subj) and not subj.startswith("原告") \
                and not hit and not m and not codes:
            all_flag = True
        elif m:
            k = _num(m.group(1))
            if k is not None and n_def and k >= n_def:
                all_flag = True
            else:
                absent_def |= hit if hit else {f"#{i}" for i in range(k or 1)}
        else:
            absent_def |= hit
            if not hit and re.match(r"^(?:本件|兩造)?被告", subj):
                unmatched = True  # 子句點名了被告，但名字對不上名單（簡稱、去識別化代號）
    clause = " | ".join(used)[:160]
    dstr = "、".join(detail)
    if plaintiff_absent and not absent_def and not all_flag and not unmatched:
        return "原告缺席", dstr, clause
    if n_def <= 1 and (absent_def or all_flag or unmatched):
        return "全部被告缺席", dstr, clause
    if all_flag or (names and set(names) <= absent_def):
        return "全部被告缺席", dstr, clause
    if absent_def:
        return "部分被告缺席", dstr, clause
    if unmatched:
        return "部分被告缺席", "、".join(detail + ["簡稱未對應"]), clause
    if n_def == 1 and any(re.search(r"原告(?:之)?聲請|准由其一造|准.{0,4}一造", c[max(0, q - 60):q + 6]) for q in positions) \
            and not plaintiff_absent:
        return "全部被告缺席", "、".join(detail + ["單一被告推定"]), clause   # 例：法定代理人在監不願出庭
    return "無法判定", dstr, clause
