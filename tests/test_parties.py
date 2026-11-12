"""data_pipeline/parties.py 的單元測試。fixture 來自第二核對者回饋查核報告與資料庫中實際的當事人欄。"""
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "data_pipeline"))
from parties import parse_party_block, classify_party, default_party  # noqa: E402


def names(lst):
    return [p["name"] for p in lst]


class TestParty(unittest.TestCase):
    def test_237_jian_up_two(self):  # 兼上二人法定代理人 → 許伯爭本身也是原告
        blk = "原 告 鄭○○\n鄭○○\n兼 上二人\n法定代理人 許伯爭\n鄭展誠\n被 告 某公司\n"
        p, d = parse_party_block(blk)
        self.assertEqual(names(p), ["鄭○○", "鄭○○", "許伯爭", "鄭展誠"])  # 去識別化的同名是不同的人，不去重

    def test_221_jian_linebreak(self):  # 兼法定代理 / 人 斷行
        blk = "被 告 甲公司\n法定代理人 張琇雯\n兼法定代理 張峻豪\n人\n楊宗燁\n"
        p, d = parse_party_block("原 告 乙\n" + blk)
        self.assertEqual(names(d), ["甲公司", "張峻豪", "楊宗燁"])

    def test_wrapped_jian_with_ren(self):
        blk = "原告 X公司\n被 告 快來電工程有限公司\n兼法定代理 王樹蒼\n人\n被 告 王子建\n顏子晏\n共 同\n訴訟代理人 劉律師\n"
        p, d = parse_party_block(blk)
        self.assertEqual(names(d), ["快來電工程有限公司", "王樹蒼", "王子建", "顏子晏"])

    def test_240_old_name_paren_wrap(self):  # 括號舊名斷行不算第二位原告
        blk = "原 告 農業部林業及自然保育署南投分署（即改制前行政\n院農業委員會林務局南投林區管理處）\n法定代理人 某某\n被 告 乙\n"
        p, d = parse_party_block(blk)
        self.assertEqual(len(p), 1)
        self.assertEqual(classify_party(p[0]["full"]), "政府機關")

    def test_build_name_not_truncated(self):  # 嘉實建設 不被「設」截斷
        blk = "原 告 甲\n被 告 亞昕國際開發股份有限公司\n嘉實建設股份有限公司\n"
        p, d = parse_party_block(blk)
        self.assertEqual(names(d), ["亞昕國際開發股份有限公司", "嘉實建設股份有限公司"])
        self.assertTrue(all(classify_party(x["name"]) == "公司團體" for x in d))

    def test_address_lines_and_designated_delivery(self):
        blk = ("原 告 李春郁 住○○市○○區○○街00巷0號4樓\n訴訟代理人 王聖傑律師\n"
               "被 告 鄧敬餘 籍設臺中市○○區○○路○00號\n（即臺中○○○○○○○○○）\n（現應受送達處所不明）\n"
               "胡軒綾 籍設基隆市○○區○○街0巷00號\n（現應受送達處所不明）\n"
               "指定送達址：彰化縣○○鎮○○路00號\n奕發企業社即黃大中\n籍設新北市○○區○○路00○0號6樓\n"
               "被 告 王智業 住○○市○○區○○路000巷00弄00號\n上 一 人\n訴訟代理人 錢仁杰律師\n")
        p, d = parse_party_block(blk)
        self.assertEqual(names(p), ["李春郁"])
        self.assertEqual(names(d), ["鄧敬餘", "胡軒綾", "奕發企業社即黃大中", "王智業"])

    def test_jian_up_one_ren_agent(self):  # 兼上一人訴/訟代理人 蔡碧美
        blk = ("原 告 張惠君\n被 告 吳昱霖\n徐妙婷\n兼上一人訴\n訟代理人 蔡碧美\n被 告 興富晟開發建設有限公司\n法定代理人 張秀梅\n")
        p, d = parse_party_block(blk)
        self.assertEqual(names(d), ["吳昱霖", "徐妙婷", "蔡碧美", "興富晟開發建設有限公司"])

    def test_class_sole_prop(self):
        for n in ["黃玉霞即馨園園藝社", "張李賢即張李賢建築師事務所", "陳氏映玉即心悅芳越式洗髮"]:
            self.assertEqual(classify_party(n), "自然人", n)

    def test_class_basic(self):
        self.assertEqual(classify_party("臺灣中小企業銀行股份有限公司"), "公司團體")
        self.assertEqual(classify_party("基隆市山海觀公寓大廈管理委員會"), "公司團體")
        self.assertEqual(classify_party("財政部國有財產署"), "政府機關")
        self.assertEqual(classify_party("臺北市政府警察局"), "政府機關")
        self.assertEqual(classify_party("新北市中和區公所"), "政府機關")
        self.assertEqual(classify_party("國立臺灣大學醫學院附設醫院"), "政府機關")
        self.assertEqual(classify_party("新加坡商必威數碼有限公司台灣分公司"), "公司團體")
        self.assertEqual(classify_party("林春燕（即林宏熙之繼承人）"), "自然人")
        self.assertEqual(classify_party("某某地政事務所"), "政府機關")
        self.assertEqual(classify_party("新華醫院即陳有強"), "自然人")
        self.assertEqual(classify_party("FDG KINETIC LIMITED"), "公司團體")
        self.assertEqual(classify_party("謝忠宮"), "自然人")
        self.assertEqual(classify_party("李德堂"), "自然人")
        self.assertEqual(classify_party("臺北榮民總醫院玉里分院"), "政府機關")
        self.assertEqual(classify_party("屏東榮民總醫院"), "政府機關")
        self.assertEqual(classify_party("保安宮"), "公司團體")
        self.assertEqual(classify_party("國家中山科學研究院"), "政府機關")


class TestDefault(unittest.TestCase):
    D3 = [{"name": n, "full": n} for n in ["德沅工業有限公司", "丁世章", "黃枷蓁"]]

    def test_all(self):
        t = "壹、程序方面：被告德沅工業有限公司、丁世章、黃枷蓁經合法通知，未於言詞辯論期日到場，核無民事訴訟法第386條所列各款情形，爰依原告聲請，由其一造辯論而為判決。"
        self.assertEqual(default_party(t, self.D3)[0], "全部被告缺席")

    def test_all_generic(self):
        t = "一、被告經合法通知，均未於最後1次言詞辯論期日到場，核無民事訴訟法第386條所列各款情形，爰依原告之聲請，由其一造辯論而為判決。"
        self.assertEqual(default_party(t, self.D3)[0], "全部被告缺席")

    def test_partial_names(self):
        t = "三、被告丁世章經合法通知，未於言詞辯論期日到場，核無民事訴訟法第386條各款所列情形，爰依原告之聲請，由其一造辯論而為判決。"
        self.assertEqual(default_party(t, self.D3)[0], "部分被告缺席")

    def test_partial_etc_n(self):
        D = [{"name": f"被告{i}", "full": ""} for i in range(11)]
        t = "二、本件被告游玉英、許游玉女（下稱被告游玉英等5人）均經合法通知，未於最後言詞辯論期日到場，核無民事訴訟法第386條各款所列情形，爰依原告之聲請，由其一造辯論而為判決。"
        self.assertEqual(default_party(t, D)[0], "部分被告缺席")

    def test_count_only(self):
        D = [{"name": "甲甲", "full": ""}, {"name": "乙乙", "full": ""}]
        for sub in ("本件被告二人均", "被告2人", "被告等"):
            t = f"一、{sub}經合法通知，未於言詞辯論期日到場，核無民事訴訟法第386條所列各款情形，爰依原告之聲請，由其一造辯論而為判決。"
            self.assertEqual(default_party(t, D)[0], "全部被告缺席", sub)

    def test_plaintiff_absent(self):
        t = "一、原告經合法通知，未於言詞辯論期日到場，核無民事訴訟法第386條所列各款情形，爰依被告之聲請，由其一造辯論而為判決。"
        self.assertEqual(default_party(t, self.D3)[0], "原告缺席")

    def test_linebreak(self):  # 「一造」「辯論」被換行切開
        t = "被告經合法通知，未於言詞辯論期日到場，核無民事訴訟法第386條所列各款情形，爰依原告之聲請，由其一造\n辯論而為判決。"
        r = default_party(t, self.D3)
        self.assertEqual(r[:2], ("全部被告缺席", "換行漏抓"))

    def test_none(self):
        t = "被告則以：伊已清償。原告主張不可採。"
        self.assertEqual(default_party(t, self.D3)[0], "無")

    def test_reference_to_other_case(self):
        t = "嗣因恆怡公司經合法通知未到庭爭執而為一造辯論判決在案，亦有卷附本院判決可憑。"
        self.assertEqual(default_party(t, self.D3)[0], "無法判定")



class TestBlock(unittest.TestCase):
    def test_jian_up_list_not_block_end(self):  # 「兼上列一人」不是「上列當事人間」
        txt = "臺灣高雄地方法院民事判決\n111年度訴字第353號\n原 告 陳聰傑\n被 告 凃崇仁\n凃銘軒\n兼上列一人\n法定代理人 許惠珠\n上列當事人間請求損害賠償事件\n主文\n"
        p, d = parse_party_block(party_block_(txt))
        self.assertEqual(names(d), ["凃崇仁", "凃銘軒", "許惠珠"])

    def test_no_shanglie(self):  # 沒有「上列」，以「當事人間」結束
        from parties import party_block
        txt = "原 告 謝璨宇\n被 告 陳百川\n當事人間違反職務職役案件，原告提起刑事附帶民事訴訟\n主 文\n被告應給付原告新台幣貳萬元\n"
        p, d = parse_party_block(party_block(txt))
        self.assertEqual(names(d), ["陳百川"])

    def test_jian_gongtong_agent(self):  # 兼共同訴訟代理人 → 也是被告
        blk = "原 告 X\n被 告 李香妹\n林秀真\n兼共同\n訴訟代理人 林達偉\n"
        p, d = parse_party_block(blk)
        self.assertEqual(names(d), ["李香妹", "林秀真", "林達偉"])

    def test_notified_person_not_defendant(self):
        blk = "原 告 陳豐文\n被 告 郭惠敏\n受告知人 楊采芳\n陳麗名\n"
        p, d = parse_party_block(blk)
        self.assertEqual(names(d), ["郭惠敏"])

    def test_lawyer_continuation_and_digits(self):
        blk = "原 告 A\n被 告 田公司\n訴訟代理人 甲律師\n乙律師\n被 告 許建暉 000000\n"
        p, d = parse_party_block(blk)
        self.assertEqual(names(d), ["田公司", "許建暉"])


def party_block_(t):
    from parties import party_block
    return party_block(t)



class TestBlock2(unittest.TestCase):
    def test_agent_jian_sendai_not_party(self):
        blk = "原 告 謝昀容\n訴訟代理人\n兼\n送達代收人 林冠宇律師\n吳品蓁律師\n被 告 王冠賢（原名：吳柏毅）\n王國懿\n"
        p, d = parse_party_block(blk)
        self.assertEqual(names(p), ["謝昀容"])
        self.assertEqual(names(d), ["王冠賢", "王國懿"])

    def test_jian_up_three_gongtong(self):
        blk = "原 告 邱仁美\n黃月素\n兼\n上三人共同\n訴訟代理人 陳淑華\n原 告 傅子容\n兼上 一 人\n訴訟代理人 康立業\n"
        p, d = parse_party_block(blk)
        self.assertEqual(names(p), ["邱仁美", "黃月素", "陳淑華", "傅子容", "康立業"])

    def test_also_counterclaim_role(self):
        blk = "原 告\n即反訴被告 莫漢生\n訴訟代理人 陳健律師\n被 告\n即反訴原告 大佶機電股份有限公司\n法定代理人 謝居明\n"
        p, d = parse_party_block(blk)
        self.assertEqual(names(p), ["莫漢生"])
        self.assertEqual(names(d), ["大佶機電股份有限公司"])

    def test_role_line_jian(self):
        blk = "原 告 X銀行\n被 告 達群環匯股份有限公司\n被告兼上法定代理人\n蔡明潔\n"
        p, d = parse_party_block(blk)
        self.assertEqual(names(d), ["達群環匯股份有限公司", "蔡明潔"])

    def test_role_in_same_line(self):
        blk = "原 告 台北富邦商業銀行股份有限公司\n法定代理人 郭倍廷\n訴訟代理人 廖啓邦 住○○市○○區○○○路0段00號7樓 被 告 林泓亦 住○○市○○區○○街000巷00號\n"
        p, d = parse_party_block(blk)
        self.assertEqual(names(p), ["台北富邦商業銀行股份有限公司"])
        self.assertEqual(names(d), ["林泓亦"])

    def test_special_agent_wrap(self):
        blk = "原 告 甲乙\n追加 原告 吳葉瓊珠\n葉榮裕\n上一人 之\n特別代理人 韓銘峰律師\n被 告 張時櫻\n葉志輝\n上四人共同\n訴訟代理人 魏翠亭律師\n"
        p, d = parse_party_block(blk)
        self.assertEqual(names(p), ["甲乙", "吳葉瓊珠", "葉榮裕"])
        self.assertEqual(names(d), ["張時櫻", "葉志輝"])

    def test_wrapped_company_name(self):
        blk = "原 告 潘隆生\n被 告 英屬百慕達商友邦人壽保險股份有限公司台灣分公\n司\n法定代理人 侯文成\n"
        p, d = parse_party_block(blk)
        self.assertEqual(names(d), ["英屬百慕達商友邦人壽保險股份有限公司台灣分公司"])



class TestBlock3(unittest.TestCase):
    def test_spaced_tianjia(self):  # 「追 加 被告」不是一個叫「追加」的人
        blk = "原 告 劉志明\n被 告 陳蔡美沙（陳美玲之承受訴訟人）\n追 加 被告 陳麗娜\n共 同\n訴訟代理人 何曜男律師\n"
        p, d = parse_party_block(blk)
        self.assertEqual(names(d), ["陳蔡美沙", "陳麗娜"])

    def test_counterclaim_alias_lines(self):  # 原告即／反訴被告 丁世昌 → 仍是原告
        blk = "原告 即\n反訴被告 丁世昌\n丁世文\n共 同\n訴訟代理人 朱坤棋律師\n被告 即\n反訴原告 詹前插\n訴訟代理人 盧江陽律師\n"
        p, d = parse_party_block(blk)
        self.assertEqual(names(p), ["丁世昌", "丁世文"])
        self.assertEqual(names(d), ["詹前插"])

    def test_digit_leading_company(self):
        blk = "原 告 黃家順\n被 告 造豐開發有限公司\n法定代理人 孫世堅\n上三人共同\n訴訟代理人 李淵源律師\n被 告 21世紀不動產股份有限公司\n法定代理人 王福漲\n"
        p, d = parse_party_block(blk)
        self.assertEqual(names(d), ["造豐開發有限公司", "21世紀不動產股份有限公司"])

    def test_three_line_jian_wrap(self):
        blk = "原 告 徐嘉鴻\n被 告 富士康廣告有限公司\n日立光電有限公司\n兼上二人共\n同法定代理\n人 李泰龍\n被 告 王雅怡\n"
        p, d = parse_party_block(blk)
        self.assertEqual(names(d), ["富士康廣告有限公司", "日立光電有限公司", "李泰龍", "王雅怡"])

    def test_dangling_paren_does_not_swallow(self):
        blk = ("原 告 X公司\n被 告 鄭語薇（即鄭黃菊之繼承人暨蔡靜榆之承受訴訟\n鄭語慧（即鄭黃菊之繼承人暨蔡靜榆之承受訴訟\n"
               "李若豪（即鄭黃菊之繼承人）\n李果餘（即鄭黃菊之繼承人）\n")
        p, d = parse_party_block(blk)
        self.assertEqual(names(d), ["鄭語薇", "鄭語慧", "李若豪", "李果餘"])



class TestDefault2(unittest.TestCase):
    def test_conjunction_prefix(self):
        D = [{"name": "謝雨彤", "full": ""}]
        for pre in ("三、再者，", "三、末按，查本件", "壹、程序上理由本件", "二、經查，", "二、"):
            t = f"{pre}被告經合法通知，未於言詞辯論期日到場，核無民事訴訟法第386條所列各款情形，爰依原告之聲請，由其一造辯論而為判決。"
            self.assertEqual(default_party(t, D)[0], "全部被告缺席", pre)

    def test_no_386_wording(self):
        D = [{"name": "蔡志偉", "full": ""}]
        t = "經查，被告經合法通知，無正當理由未到場，無民事訴訟法第386條各款所列情形，爰依原告之聲請，由其一造辯論而為判決。"
        self.assertEqual(default_party(t, D)[0], "全部被告缺席")

    def test_deidentified_codes_all(self):
        D = [{"name": "何俊霆", "full": ""}, {"name": "䝉奕錡", "full": ""}]
        t = "一、被告甲○○、乙○○(下合稱被告，分稱甲○○、乙○○)經合法通知未於言詞辯論期日到場，核無民事訴訟法第386條所列各款情形，爰依原告之聲請，由其一造辯論而為判決。"
        self.assertEqual(default_party(t, D)[0], "全部被告缺席")

    def test_deidentified_codes_partial(self):
        D = [{"name": "詹豐益", "full": ""}, {"name": "楊博安", "full": ""}, {"name": "陳○安", "full": ""}]
        t = "壹、程序方面被告乙○○經本院合法通知，未於言詞辯論期日到場，核無民事訴訟法第386條所列各款事由，爰依原告之聲請，由其一造辯論而為判決。"
        self.assertEqual(default_party(t, D)[0], "部分被告缺席")



class TestBlock4(unittest.TestCase):
    def test_two_names_one_line(self):
        blk = "原 告 王耀聲\n被 告 李岳勳\n林佳寬 住○○市○○區○○○路00號 林碧玉 住○○市○○區○○○街0段00號0樓\n李士長\n"
        p, d = parse_party_block(blk)
        self.assertEqual(names(d), ["李岳勳", "林佳寬", "林碧玉", "李士長"])



class TestBlock5(unittest.TestCase):
    def test_qianlie_names_gongtong_line(self):
        blk = "原 告 邱錦鑫\n邱昌瑞\n邱昌德\n前列邱錦鑫、邱昌瑞、邱昌德共同\n訴訟代理人 張婉娟律師\n被 告 新竹市政府\n"
        p, d = parse_party_block(blk)
        self.assertEqual(names(p), ["邱錦鑫", "邱昌瑞", "邱昌德"])

    def test_role_count_line(self):  # 「原告十四人」是人數說明，不是人
        blk = "原 告 林振長\n陳美玲\n原告十四人\n共同訴訟代\n理人 陳建勛律師\n被 告 周雪麗\n"
        p, d = parse_party_block(blk)
        self.assertEqual(names(p), ["林振長", "陳美玲"])



class TestBlock6(unittest.TestCase):
    def test_placeholder_names_not_deduped(self):
        blk = "原 告 ○○○\n被 告 ○○○\n○○○\n"
        p, d = parse_party_block(blk)
        self.assertEqual(len(d), 2)

    def test_jian_counterclaim_plaintiff(self):
        blk = "原 告 黃纖雅\n被 告 林俊志\n兼反訴原告 顏銘慧\n上二人共同\n訴訟代理人 謝佳蓁律師\n"
        p, d = parse_party_block(blk)
        self.assertEqual(names(d), ["林俊志", "顏銘慧"])

    def test_jian_n_people_lines(self):
        blk = ("原 告 陳自安\n被 告 陳啓源\n王坤滿\n被告兼上列\n二十一人之\n訴訟代理人 陳啓清\n"
               "被 告 陳昌仁\n陳昌杰\n被告兼上列\n二人之訴訟\n訴訟代理人 陳昌盛\n被 告 陳定國\n")
        p, d = parse_party_block(blk)
        self.assertEqual(names(d), ["陳啓源", "王坤滿", "陳啓清", "陳昌仁", "陳昌杰", "陳昌盛", "陳定國"])



class TestBlock7(unittest.TestCase):
    def test_shanglie_count_line_not_block_end(self):
        txt = ("臺灣士林地方法院民事判決\n原 告 陳春源\n被 告 龍大地住戶互助委員會\n兼法定代理人 謝豐義\n上列被告 6人\n共 同\n"
               "訴 訟代理 人 徐佩琪律師\n被 告 李昆鴻\n上列當事人間確認決議無效事件\n主 文\n")
        from parties import party_block
        p, d = parse_party_block(party_block(txt))
        self.assertEqual(names(d), ["龍大地住戶互助委員會", "謝豐義", "李昆鴻"])


class TestDefault3(unittest.TestCase):
    def test_subject_in_previous_sentence(self):
        D = [{"name": "欣發工程行即彭瑞發", "full": ""}, {"name": "賴景陞", "full": ""}]
        t = "一、被告欣發工程行即彭瑞發（下稱彭瑞發）經合法通知，始終未於言詞辯論期日到場，且核無民事訴訟法第386條各款情形。爰依原告聲請，由其一造辯論而為判決。"
        self.assertEqual(default_party(t, D)[0], "部分被告缺席")

    def test_single_defendant_representative_in_jail(self):
        D = [{"name": "富士康家庭事業有限公司", "full": ""}]
        t = "二、本件被告法定代理人李泰龍在監執行中，已以書狀具體表明不願於言詞辯論期日到場，本院依前揭說明未提訊其到庭，並依原告聲請，准由其一造辯論而為判決。"
        self.assertEqual(default_party(t, D)[0], "全部被告缺席")


class TestFoundInBackfill252(unittest.TestCase):
    """REGRESSION：2.5.2 全庫回填和 2.5.1 比對時找到的錯（判決書的寫法照原文，人名換掉）。"""

    def test_government_named_in_the_middle(self):
        for name in ("新北市政府違章建築拆除大隊", "台北市政府地政局土地開發總隊",
                     "新北市政府家庭暴力暨性侵害防治中心", "臺灣屏東地方檢察署檢察官"):
            self.assertEqual(classify_party(name), "政府機關", name)
        for name in ("海洋委員會海巡署艦隊分署第十六海巡隊", "客家委員會客家文化發展中心"):
            self.assertEqual(classify_party(name), "政府機關", name)
        self.assertEqual(classify_party("某某大廈管理委員會"), "公司團體")
        self.assertEqual(classify_party("甲部署科技股份有限公司"), "公司團體")

    def test_notes_after_a_name_are_not_part_of_it(self):
        """在監、另案的說明接在名字後面時只留名字；「原居…」的舊地址行不是當事人。"""
        blk = ("原 告 林小華\n被 告 王大明另案於法務部○○○○○○○○○執行\n"
               "陳小美\n原居1350 MARKET ST., SAN FRANCISCO\n")
        p, d = parse_party_block(blk)
        self.assertEqual(names(d), ["王大明", "陳小美"])
        self.assertTrue(all(classify_party(x["full"]) == "自然人" for x in d))

    def test_schools(self):
        self.assertEqual(classify_party("新北市達觀國中小學"), "政府機關")
        self.assertEqual(classify_party("私立某某高級中學"), "公司團體")

    def test_agency_acting_as_estate_administrator(self):
        """機關擔任遺產管理人不是獨資商號；人擔任的（會計師、律師）仍是自然人。"""
        self.assertEqual(classify_party("財政部國有財產署北區分署即王大明之遺產管理人"), "政府機關")
        self.assertEqual(classify_party("財政部國有財產署中區分署即王大明之財產管理人"), "政府機關")
        self.assertEqual(classify_party("林小華會計師即被繼承人王大明之遺產管理人"), "自然人")
        self.assertEqual(classify_party("小明建築師事務所即林小明"), "自然人")
        self.assertEqual(classify_party("國軍退除役官兵輔導委員會某縣榮民服務處即王大明之遺產管理人"), "政府機關")
        # 獨資商號的名稱剛好以「廳」「處」結尾，仍是自然人
        self.assertEqual(classify_party("北極熊咖啡廳即林小明"), "自然人")
        self.assertEqual(classify_party("小美美容工作處即陳小美"), "自然人")

    def test_counterclaim_role_wrapped_to_next_line(self):
        blk = ("原告即反訴\n被告 林小華\n訴訟代理人 陳律師\n"
               "被告即反訴\n原告 甲實業股份有限公司\n法定代理人 王大明\n")
        p, d = parse_party_block(blk)
        self.assertEqual(names(p), ["林小華"])
        self.assertEqual(names(d), ["甲實業股份有限公司"])

    def test_organisation_name_with_house_number(self):
        blk = ("原 告 林小華\n被 告 某園區10號大樓管理委員會\n設新北市○○區○○路0段000巷00○0 號\n"
               "兼法定代理\n人 王大明\n被 告 陳小美\n")
        p, d = parse_party_block(blk)
        self.assertEqual(names(d), ["某園區10號大樓管理委員會", "王大明", "陳小美"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
