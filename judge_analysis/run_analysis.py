"""
法官資料分析 — 主程式

    python judge_analysis/run_analysis.py
    python judge_analysis/run_analysis.py --court 臺北 --year 2025 --min-cases 30

產出（judge_analysis/output/）：
    judge_profile.csv            每位法官一列的綜合輪廓
    judge_case_mix.csv           法官 × 案由大類 案件數
    judge_outcome_by_casetype.csv 法官 × 案由大類 勝訴率
    judge_law_preference.csv     法官 × 法規 引用次數
    panel_stats.csv              合議庭組合
    judge_analysis.xlsx          以上全部整合成一份活頁簿

所有數字都可由 judgments.db 重新產生：先跑 backfill_structured.py，再跑本檔。
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

import pandas as pd

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from src.loader import explode_citations, explode_judges, load_cases   # noqa: E402
from src import metrics as M                                           # noqa: E402

OUT = HERE / "output"


def main() -> None:
    ap = argparse.ArgumentParser(description="法官判決傾向分析")
    ap.add_argument("--court", default="臺北地方法院")
    ap.add_argument("--year", default="2025")
    ap.add_argument("--min-cases", type=int, default=M.MIN_CASES_FOR_TEST,
                    help="納入統計檢定的最低案件數")
    a = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)

    print(f"載入 {a.court} {a.year} 民事判決…")
    cases = load_cases(court=a.court, year=a.year)
    jc = explode_judges(cases)
    cites = explode_citations(cases)

    print(f"  案件 {len(cases)} 筆 / 法官×案件 {len(jc)} 列 / 法條引用 {len(cites)} 列")

    summary = M.corpus_summary(cases)
    print("\n── 語料摘要 ──")
    for k, v in summary.items():
        print(f"  {k:<18}{v if not isinstance(v, float) else round(v, 4)}")

    prof = M.judge_profile(jc, cases)
    mix = M.judge_case_mix(jc, a.min_cases)
    by_type = M.judge_outcome_by_casetype(jc)
    laws = M.judge_law_preference(cites, a.min_cases)
    panels = M.panel_stats(cases)

    outputs = {
        "judge_profile": prof,
        "judge_case_mix": mix,
        "judge_outcome_by_casetype": by_type,
        "judge_law_preference": laws,
        "panel_stats": panels,
    }
    for name, df in outputs.items():
        if df is None or df.empty:
            print(f"  （{name} 無資料，略過）")
            continue
        path = OUT / f"{name}.csv"
        df.to_csv(path, encoding="utf-8-sig")
        print(f"  寫出 {path.name}（{len(df)} 列）")

    xlsx = OUT / "judge_analysis.xlsx"
    with pd.ExcelWriter(xlsx, engine="openpyxl") as w:
        pd.DataFrame([summary]).T.rename(columns={0: "值"}).to_excel(w, sheet_name="語料摘要")
        for name, df in outputs.items():
            if df is not None and not df.empty:
                df.to_excel(w, sheet_name=name[:31])
    print(f"  寫出 {xlsx.name}")

    # ── 主控台摘要 ──
    cols = ["對審案件數", "獨任比例", "全部勝訴率", "期望全部勝訴率", "差異", "p值", "顯著(BH)"]
    sole_cols = ["獨任_對審案件數", "獨任_全部勝訴率", "獨任_期望全部勝訴率",
                 "獨任_差異", "獨任_p值", "獨任_顯著(BH)"]

    testable = prof[prof["可檢定"]]
    print(f"\n── 可檢定法官（對審案件 ≥ {a.min_cases}）：{len(testable)} 位 ──")
    print("\n最偏原告（全部參與案件，案件組合調整後）：")
    print(testable.nlargest(8, "差異")[cols].round(4).to_string())
    print("\n最偏被告（全部參與案件，案件組合調整後）：")
    print(testable.nsmallest(8, "差異")[cols].round(4).to_string())

    sig = testable[testable["顯著(BH)"]]
    print(f"\n經 BH 校正後顯著偏離基準線：{len(sig)} 位（以全部參與案件計）")
    if len(sig):
        print(sig[cols].round(4).to_string())

    # 合議庭案件無法歸屬給單一位法官，獨任案件才是個人心證的乾淨證據。
    sole = prof[prof["獨任_可檢定"].fillna(False)]
    print(f"\n── 僅計獨任案件（≥ {a.min_cases} 件）：{len(sole)} 位 ──")
    sig_sole = sole[sole["獨任_顯著(BH)"].fillna(False)]
    print(f"經 BH 校正後顯著者：{len(sig_sole)} 位")
    if len(sig_sole):
        print(sig_sole.sort_values("獨任_差異")[sole_cols].round(4).to_string())
    else:
        print("  （沒有。代表在控制案件類型後，獨任法官之間的勝訴率差異"
              "可以用隨機變異解釋。）")

    only_panel = prof[prof["可檢定"] & (prof["獨任比例"] < 0.2)]
    if len(only_panel):
        print(f"\n⚠ 有 {len(only_panel)} 位法官八成以上的案件來自合議庭，其「勝訴率」"
              "反映的是所屬合議庭而非個人傾向，不可單獨解讀：")
        print("  " + "、".join(only_panel.index.tolist()))


if __name__ == "__main__":
    main()
