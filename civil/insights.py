"""
從相似判決整理給使用者的參考：證據對照、對方常見的抗辯、判准金額範圍、判決導讀的段落標示。

全部是規則式（關鍵字詞典），結果只表示「判決裡提到」，不代表法院採信——頁面上要照這樣說明。
段落功能標註（annotation/）完成後，判決導讀改用標註模型；這裡的規則是第一版（rule-v0）。
"""
import re
from typing import Dict, Iterable, List, Optional, Sequence

import numpy as np

# 證據：前 6 項和問卷的勾選項目相同（key 一致），後 2 項只出現在結果頁
EVIDENCE = [
    ("medical", "診斷證明、病歷", r"診斷證明|病歷|就醫紀錄|醫療費用?收據"),
    ("receipt", "收據、發票、估價單", r"收據|發票|估價單|報價單|單據"),
    ("transfer", "匯款、轉帳紀錄", r"匯款|轉帳|存摺|交易明細|匯出"),
    ("chat", "LINE、簡訊、錄音", r"LINE|Line|line|簡訊|對話紀錄|錄音|通訊軟體"),
    ("contract", "契約、借據、本票", r"契約書|合約書?|借據|本票|切結書|協議書|借款契約"),
    ("video", "照片、監視器、行車紀錄器", r"照片|監視器|錄影|行車紀錄器|影片|現場圖"),
    ("accident", "交通事故鑑定、肇事分析", r"初步分析研判表|肇事.{0,4}鑑定|鑑定意見書|車禍鑑定|事故鑑定"),
    ("salary", "薪資證明", r"薪資證明|薪資單|扣繳憑單|所得清單|在職證明|薪轉"),
]
QUESTIONNAIRE_EVIDENCE = [k for k, _, _ in EVIDENCE[:6]]

DEFENSES = [
    ("contributory", "你也有過失（與有過失）", "主張你對損害的發生也有責任，要求減少賠償", r"與有過失"),
    ("excessive", "請求的金額太高", "質疑損害項目或金額過高、不必要", r"過高|過鉅|顯不相當|不必要|並無必要"),
    ("paid", "已經付過或已經和解", "主張已經清償、賠償，或應扣除已領的保險金", r"已清償|已給付|已償還|已支付|已賠償|和解|強制險|保險金"),
    ("limitation", "請求權已經過了時效", "主張請求權因時效消滅", r"時效"),
    ("causation", "損害和行為沒有因果關係", "主張你的損害不是他的行為造成的", r"因果關係"),
    ("no_fault", "自己沒有過失或責任", "主張自己沒有過失，不必負責", r"並無過失|無過失|不負.{0,6}責任|無庸負責"),
    ("offset", "用對你的債權抵銷", "主張你也欠他錢，要互相抵銷", r"抵銷"),
    ("dispute_fact", "否認事實或文件真實", "否認有借款、簽約等事實，或主張文件是偽造的", r"否認|偽造|不實|虛偽|未曾"),
]

_EVIDENCE_RE = [(k, re.compile(rx)) for k, _, rx in EVIDENCE]
_DEFENSE_RE = [(k, re.compile(rx)) for k, _, _, rx in DEFENSES]


def evidence_mentions(text: str) -> List[str]:
    return [k for k, rx in _EVIDENCE_RE if rx.search(text or "")]


def defense_types(text: str) -> List[str]:
    return [k for k, rx in _DEFENSE_RE if rx.search(text or "")]


def evidence_table(neighbor_evidence: Sequence[Iterable[str]], user_has: Iterable[str]) -> List[Dict]:
    """
    相似「勝訴」判決裡提到各項證據的比例，和使用者有沒有這項證據並列。
    neighbor_evidence：每一件相似勝訴判決提到的證據 key。比例由高到低排序，沒有任何判決提到的不列。
    """
    have = set(user_has)
    n = len(neighbor_evidence)
    rows = []
    for key, label, _ in EVIDENCE:
        hits = sum(key in set(e) for e in neighbor_evidence)
        if n and hits:
            rows.append({"key": key, "label": label, "share": hits / n, "user_has": key in have})
    return sorted(rows, key=lambda r: -r["share"])


def defense_table(neighbor_defenses: Sequence[Iterable[str]], top: int = 3) -> List[Dict]:
    """相似判決的被告答辯中，各類抗辯出現的比例，取前 top 類。"""
    n = len(neighbor_defenses)
    rows = []
    for key, label, desc, _ in DEFENSES:
        hits = sum(key in set(d) for d in neighbor_defenses)
        if n and hits:
            rows.append({"key": key, "label": label, "description": desc, "share": hits / n})
    return sorted(rows, key=lambda r: -r["share"])[:top]


def amount_range(ratios: Sequence[float], claimed: Optional[float], low: float = 0.1, high: float = 0.9,
                 min_cases: int = 5) -> Optional[Dict]:
    """
    相似的勝訴、一部勝訴判決的獲償比例（判准／請求），取 10%–90% 分位數，乘上使用者請求的金額。
    件數不到 min_cases 就不給範圍（回傳 None），免得用兩三件判決說出一個數字。
    """
    r = np.asarray([x for x in ratios if x is not None and 0 < x <= 1], dtype=float)
    if len(r) < min_cases:
        return None
    lo, mid, hi = np.quantile(r, [low, 0.5, high])
    out = {"n_cases": int(len(r)), "ratio_low": float(lo), "ratio_median": float(mid), "ratio_high": float(hi),
           "coverage": high - low}
    if claimed and claimed > 0:
        out.update(amount_low=round(claimed * lo), amount_median=round(claimed * mid),
                   amount_high=round(claimed * hi), claimed=round(claimed))
    return out


# ── 判決導讀：段落與功能（rule-v0）──
GUIDE_LABELER = "rule-v0"
FUNCTIONS = {"claim": "原告主張", "defense": "被告答辯", "issue": "爭點", "evidence": "證據", "court": "法院判斷"}
_HEAD_SPLIT = re.compile(r"(?=(?:[一二三四五六七八九十]{1,3}|[壹貳參叁肆伍陸柒捌玖拾])、)|(?=[㈠-㈩])|(?=[(（][一二三四五六七八九十]{1,3}[)）])")
_ISSUE_RE = re.compile(r"爭點|爭執事項|不爭執|兩造所不爭")
_EVIDENCE_PARA_RE = re.compile(r"為證|在卷可(?:稽|按|參)|有.{0,20}可(?:稽|參|憑)|證述|鑑定|附卷|提出.{0,20}(?:證明|照片|收據|紀錄)")


def _paragraphs(text: str, max_len: int = 400) -> List[str]:
    """依段落編號切開；沒有編號的長段落，在句號處切成不超過 max_len 字的段。"""
    parts = [p for p in _HEAD_SPLIT.split(text or "") if p.strip()]
    out = []
    for p in parts:
        while len(p) > max_len:
            cut = p.rfind("。", 0, max_len)
            cut = cut + 1 if cut > max_len // 3 else max_len
            out.append(p[:cut]); p = p[cut:]
        if p.strip():
            out.append(p)
    return out


def guide_paragraphs(claim: str, defense: str, court: str) -> List[Dict]:
    """原告主張、被告答辯整段標示；法院判斷段再分成爭點、證據與法院判斷。"""
    out = []
    for text, fn in ((claim, "claim"), (defense, "defense")):
        for p in _paragraphs(text):
            out.append({"function": fn, "label": FUNCTIONS[fn], "text": p})
    for p in _paragraphs(court):
        fn = "issue" if _ISSUE_RE.search(p[:80]) else ("evidence" if _EVIDENCE_PARA_RE.search(p) else "court")
        out.append({"function": fn, "label": FUNCTIONS[fn], "text": p})
    return out
