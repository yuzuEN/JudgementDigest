"""
法官分析 — 指標計算

核心方法論
──────────
比較法官之間的「寬嚴」不能直接比原始勝訴率。法官手上的案件組合不同：
專辦清償借款（銀行告債務人，證據明確，原告勝訴率極高）的法官，
勝訴率自然高於專辦侵權損害賠償的法官。這個差異來自案件分派，不是心證。

所以本模組計算的是 **案件組合調整後的差異**：

    期望勝訴數 E = Σ（該案所屬案由大類的全體平均勝訴率）
    實際勝訴數 O
    差異 = O − E

並以常態近似計算雙尾 p 值，再用 Benjamini–Hochberg 控制偽發現率。
不做多重比較校正的話，86 位法官在 α=0.05 下平均會有 4 位純靠運氣「顯著」。

這個模組只計算描述性統計與單變量檢定。它**不能**證明因果——
差異也可能來自案件分派並非隨機（例如複雜案件集中分給資深法官）。
結論寫作時必須保留這個但書。
"""

from __future__ import annotations

import math
from typing import Dict, List

import numpy as np
import pandas as pd

# 只有案件數達到此門檻的法官才進行統計檢定。低於此數的法官仍會列入
# 描述性統計，但檢定結果沒有意義（n=3 的勝訴率是 100% 不代表任何事）。
MIN_CASES_FOR_TEST = 30

STRICT_WIN = ("勝訴", "確認勝訴")


def _norm_sf(z: float) -> float:
    """標準常態分布的雙尾機率。手寫是因為環境沒有 scipy。"""
    return math.erfc(abs(z) / math.sqrt(2))


def benjamini_hochberg(pvals: List[float], alpha: float = 0.05) -> List[bool]:
    """
    Benjamini–Hochberg 偽發現率控制。

    86 位法官各做一次檢定，等於做了 86 次；不校正的話，
    在 α=0.05 下光靠隨機就會冒出約 4 個「顯著」結果。
    """
    n = len(pvals)
    if n == 0:
        return []
    order = np.argsort(pvals)
    sorted_p = np.asarray(pvals)[order]
    thresholds = alpha * (np.arange(1, n + 1) / n)
    passed = sorted_p <= thresholds
    k = np.nonzero(passed)[0].max() + 1 if passed.any() else 0
    result = np.zeros(n, dtype=bool)
    if k:
        result[order[:k]] = True
    return result.tolist()


# ═══════════════════════════════════════════════════════════════════════════
def _mix_adjusted_test(adv: pd.DataFrame, base: pd.Series, overall: float,
                       index: pd.Index, prefix: str = "") -> pd.DataFrame:
    """
    對一組「法官×案件」資料做案件組合調整後的檢定。

    回傳欄位以 prefix 區隔，讓同一張表可以同時放「全部參與案件」與
    「僅獨任案件」兩組結果。
    """
    if adv.empty:
        return pd.DataFrame(index=index)
    adv = adv.copy()
    adv["strict_win"] = adv["outcome"].isin(STRICT_WIN).astype(int)
    adv["expected_p"] = adv["case_type_category"].map(base).fillna(overall)
    g = adv.groupby("judge")

    obs = g["strict_win"].sum()
    exp = g["expected_p"].sum()
    var = g["expected_p"].apply(lambda s: float((s * (1 - s)).sum()))
    with np.errstate(divide="ignore", invalid="ignore"):
        z = (obs - exp) / np.sqrt(var.replace(0, np.nan))

    out = pd.DataFrame({
        f"{prefix}對審案件數": g.size(),
        f"{prefix}全部勝訴率": g["strict_win"].mean(),
        f"{prefix}期望全部勝訴率": g["expected_p"].mean(),
        f"{prefix}z": z,
    }).reindex(index)
    out[f"{prefix}差異"] = out[f"{prefix}全部勝訴率"] - out[f"{prefix}期望全部勝訴率"]
    out[f"{prefix}p值"] = [_norm_sf(v) if pd.notna(v) else np.nan for v in out[f"{prefix}z"]]

    testable = out[f"{prefix}對審案件數"].fillna(0) >= MIN_CASES_FOR_TEST
    out[f"{prefix}可檢定"] = testable
    out[f"{prefix}顯著(BH)"] = False
    sub = out[testable & out[f"{prefix}p值"].notna()]
    if len(sub):
        out.loc[sub.index, f"{prefix}顯著(BH)"] = benjamini_hochberg(sub[f"{prefix}p值"].tolist())
    return out


def judge_profile(judge_case: pd.DataFrame, cases: pd.DataFrame) -> pd.DataFrame:
    """
    每位法官一列的綜合輪廓。

    欄位說明：
      案件數        該法官參與的判決數（合議庭案件對每位法官都計 1）
      獨任案件數    role=='獨任'，這是最能反映個人傾向的子集
      獨任比例      解讀本表的前提，見下方註解
      對審案件數    只有給付確認層級的案件才有輸贏可言
      原告勝訴指數  全部勝訴=1、一部=0.5、敗訴=0 的平均，0~1
      全部勝訴率    嚴格定義，用於統計檢定
      期望全部勝訴率 依案件組合調整後的基準線
      差異          實際 − 期望，正值代表比同樣案件組合的平均更偏原告
      p 值 / 顯著   常態近似雙尾檢定 + BH 校正
      獨任_*        同上，但只計算該法官獨任審理的案件
    """
    adv = judge_case[judge_case["is_adversarial"]].copy()
    if adv.empty:
        return pd.DataFrame()

    adv["strict_win"] = adv["outcome"].isin(STRICT_WIN).astype(int)

    # 各案由大類的全體勝訴率＝基準線
    base = (cases[cases["is_adversarial"]]
            .assign(strict_win=lambda d: d["outcome"].isin(STRICT_WIN).astype(int))
            .groupby("case_type_category")["strict_win"].mean())
    overall = float(cases[cases["is_adversarial"]]["outcome"].isin(STRICT_WIN).mean())

    g = adv.groupby("judge")
    prof = pd.DataFrame({
        "案件數": judge_case.groupby("judge").size(),
        "獨任案件數": judge_case[judge_case["role"] == "獨任"].groupby("judge").size(),
        "審判長案件數": judge_case[judge_case["role"] == "審判長"].groupby("judge").size(),
        "原告勝訴指數": g["plaintiff_won"].mean(),
        "一部勝訴率": g["outcome"].apply(lambda s: (s == "一部勝訴一部敗訴").mean()),
        "敗訴率": g["outcome"].apply(lambda s: (s == "敗訴").mean()),
        "判准金額中位數": g["awarded_amount"].median(),
        "獲償比例中位數": g["grant_ratio"].median(),
        "費用原告負擔中位數": g["cost_share_plaintiff"].median(),
        "論理字數中位數": g["reasoning_length"].median(),
        "一造辯論比例": g["is_default_judgment"].mean(),
        "被告法人比例": g["defendant_is_corp"].mean(),
        "被告有律師比例": g["defendant_has_lawyer"].mean(),
    })
    prof[["獨任案件數", "審判長案件數"]] = prof[["獨任案件數", "審判長案件數"]].fillna(0).astype(int)
    # 獨任比例是**解讀這張表的前提**。某位法官 76 件案子全是陪席時，
    # 他的「勝訴率」其實是他所屬合議庭的勝訴率，不是他個人的傾向。
    # 把這個比例放在顯眼位置，避免讀表的人把合議結果誤讀成個人心證。
    prof["獨任比例"] = (prof["獨任案件數"] / prof["案件數"]).round(4)

    # 兩組檢定：
    #   （無前綴）全部參與案件——回答「這位法官經手的案件結果如何」
    #   獨任_       僅獨任案件——回答「這位法官自己決定時判得如何」
    # 後者才是個人傾向的乾淨證據，但樣本較小、可檢定的人也較少。
    prof = prof.join(_mix_adjusted_test(adv, base, overall, prof.index))
    sole = judge_case[(judge_case["role"] == "獨任") & judge_case["is_adversarial"]]
    prof = prof.join(_mix_adjusted_test(sole, base, overall, prof.index, prefix="獨任_"))

    return prof.sort_values("案件數", ascending=False)


def judge_case_mix(judge_case: pd.DataFrame, min_cases: int = MIN_CASES_FOR_TEST
                   ) -> pd.DataFrame:
    """法官 × 案由大類的案件數交叉表（看「誰在辦什麼案子」）。"""
    keep = judge_case.groupby("judge").size()
    keep = keep[keep >= min_cases].index
    sub = judge_case[judge_case["judge"].isin(keep)]
    return pd.crosstab(sub["judge"], sub["case_type_category"])


def judge_outcome_by_casetype(judge_case: pd.DataFrame, min_n: int = 10) -> pd.DataFrame:
    """
    法官 × 案由大類的勝訴率長表。

    這是回答「某法官是否對特定類型案件總是判特定結果」的基礎資料。
    只保留格內樣本數 ≥ min_n 的組合——格內只有兩三件時，
    勝訴率不是 0% 就是 100%，看起來極端但毫無統計意義。
    """
    adv = judge_case[judge_case["is_adversarial"]].copy()
    adv["strict_win"] = adv["outcome"].isin(STRICT_WIN).astype(int)
    g = adv.groupby(["judge", "case_type_category"])
    out = pd.DataFrame({
        "案件數": g.size(),
        "全部勝訴率": g["strict_win"].mean(),
        "原告勝訴指數": g["plaintiff_won"].mean(),
        "判准金額中位數": g["awarded_amount"].median(),
    }).reset_index()
    return out[out["案件數"] >= min_n].sort_values(["judge", "案件數"], ascending=[True, False])


def judge_law_preference(citations: pd.DataFrame, min_cases: int = 30) -> pd.DataFrame:
    """
    法官 × 主要法規的引用分布。

    用「審判長／獨任法官」當作法官維度，因為 citations 是案件層級的資料，
    合議庭案件無法歸屬到特定法官。
    """
    if citations.empty:
        return pd.DataFrame()
    citations = citations[citations["presiding_judge"].astype(str).str.strip().ne("")
                          & citations["presiding_judge"].notna()]
    if citations.empty:
        return pd.DataFrame()
    keep = citations.groupby("presiding_judge")["case_id"].nunique()
    keep = keep[keep >= min_cases].index
    sub = citations[citations["presiding_judge"].isin(keep)]
    tab = pd.crosstab(sub["presiding_judge"], sub["law"])
    # 只保留全體引用數前 20 的法規，其餘長尾對比較沒有幫助
    top = tab.sum().sort_values(ascending=False).head(20).index
    return tab[top]


def panel_stats(cases: pd.DataFrame, min_n: int = 5) -> pd.DataFrame:
    """合議庭組合的出現次數與結果分布（看「誰常跟誰同庭」）。"""
    panels = cases[(cases["judge_count"] > 1) & cases["panel_key"].astype(bool)].copy()
    if panels.empty:
        return pd.DataFrame()
    panels["strict_win"] = panels["outcome"].isin(STRICT_WIN).astype(int)
    g = panels.groupby("panel_key")
    # 勝訴率只算對審案件：非對審案件（除權判決等）幾乎都會准，
    # 混進來會把每個合議庭的勝訴率都往上拉。
    adv_only = panels[panels["is_adversarial"]].groupby("panel_key")["strict_win"]
    out = pd.DataFrame({
        "案件數": g.size(),
        "對審案件數": g["is_adversarial"].sum(),
        "全部勝訴率": adv_only.mean(),
    })
    return out[out["案件數"] >= min_n].sort_values("案件數", ascending=False)


def corpus_summary(cases: pd.DataFrame) -> Dict[str, object]:
    """整體語料的摘要，用來對照個別法官的數字。"""
    adv = cases[cases["is_adversarial"]]
    ratio = cases["grant_ratio"].dropna()
    return {
        "案件總數": len(cases),
        "對審案件數": len(adv),
        "不同法官人數": cases["presiding_judge"].replace("", np.nan).nunique(),
        "合議庭案件比例": float((cases["judge_count"] > 1).mean()),
        "全體全部勝訴率": float(adv["outcome"].isin(STRICT_WIN).mean()),
        "全體原告勝訴指數": float(adv["plaintiff_won"].mean()),
        "有判准金額比例": float(cases["awarded_amount"].notna().mean()),
        "獲償比例可用筆數": int(len(ratio)),
        "獲償比例中位數": float(ratio.median()) if len(ratio) else None,
        "有法條引用比例": float((cases["law_n_citations"] > 0).mean()),
    }
