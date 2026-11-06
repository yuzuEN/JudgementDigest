"""
金額（10/27 老師的回饋）：v5、加入請求金額／案件類型／損害子項目，比較「預測獲償比例」與「直接預測判准金額」，
改用誤差（MAE、RMSE、誤差倍數、落在範圍內的比例）評估，並列出個案。用 .venv 執行。

    .venv\\Scripts\\python -m civil.models.amount          # 一部勝訴（主分析）
    .venv\\Scripts\\python -m civil.models.amount win      # 勝訴＋一部勝訴（直接預測金額的參考）

老師的回饋與對應：
  - 「求償金額要當變數」→ 每個模型都放 log10(請求金額)（10/21 的 amount_tfidf.py 已有，這裡保留）
  - 「案件類型當結構化變數」→ 結構化變數（text_vs_structured.FEATS）本來就含案由中類；另加「案由中類中位數」基準線
  - 「有沒有醫療費用等子項目，判賠差很多」→ 從原告主張抽 13 個子項目旗標（醫療費、住院、手術、骨折、看護、勞動能力、
    工作損失、慰撫金、車損、死亡／喪葬、律師費、違約金、租金）與項目數
  - 「乾脆預測金額」→ 兩種目標：獲償比例、log10(判准金額)；都換算回比例與金額，用同一組指標比較
  - 「不要只看 Spearman，要知道差多少、看個案」→ 比例：MAE、RMSE、±10／±20 個百分點內的比例；
    金額：誤差倍數中位數、2 倍／1.5 倍內的比例、MAE／RMSE（元）；另存每件的預測，列出誤差最大的 30 件
  - 「先不放法官的事實認定」→ 文字只用兩造主張（同 v5），不用法院判斷段
樣本（同 amount_tfidf.py 的篩選）：判決結果、獲償比例是算出來的、沒有「判准大於請求」旗標、比例在 (0, 1]、請求金額 > 0、
  請求金額是從聲明直接抽到的。金額欄位是規則 2.4.0（暫定；同學的金額 2.5.0 合併後要重跑）。
切分：v5 的 fold 欄。每一折 k：測試＝fold==k；驗證集＝fold==(k+1)%5 且 val_half==1（同勝敗模型）；其餘為訓練。
  所有模型只在訓練上 fit；驗證集只用來決定「＋Longformer」的合併權重（有跑完 GPU 的話）。
模型（每種目標各一組）：
  0. 全體中位數（訓練集的獲償比例中位數 × 請求金額）
  1. 案由中類中位數（訓練集中同中類 ≥30 件時用該類中位數，否則用全體）
  2. 請求金額＋結構化（Ridge）
  3. 請求金額＋結構化＋子項目（梯度提升樹，可以學到非線性，例如「有住院」在不同案由的效果不同）
  4. 文字（TF-IDF 兩造，Ridge）
  5. 文字＋請求金額＋結構化＋子項目（Ridge）
  6. 5＋Longformer（output/longformer_amount_pd_fold{k}_v5_L4096_t2s_last4/；5 折都有時才算，權重只用驗證集）
輸出：output/amount_v5_{樣本}.md、_指標.csv、_個案.csv、_分組.csv；主分析另存 amount_v5_sample.csv（給 Longformer 金額任務）
"""
import argparse
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix, hstack
from scipy.stats import spearmanr
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import LinearRegression, Ridge

SAMPLE = "part"   # part：一部勝訴（主分析）；win：勝訴＋一部勝訴。由 main() 依命令列設定
QUICK = False     # 試跑：只取 3,000 件，輸出檔名加 _quick（--quick 或環境變數 QUICK=1）

import config                                            # noqa: E402
from civil.models import structured as tvs               # noqa: E402  同一套結構化變數
from civil.models.tfidf import vec                       # noqa: E402  同一套 TF-IDF 設定

OUT = config.OUTPUT_DIR
LF = "longformer_amount_pd_fold{k}_v5_L4096_t2s_last4"
ITEMS = {"醫療費": r"醫療費|醫藥費", "住院": r"住院", "手術": r"手術", "骨折": r"骨折", "看護": r"看護",
         "勞動能力": r"勞動能力", "工作損失": r"工作損失|不能工作|無法工作|薪資損失|營業損失",
         "慰撫金": r"慰撫金|精神上?之?損害|非財產上", "車損": r"修復費|修理費|維修費|車損|車輛損害",
         "死亡喪葬": r"死亡|喪葬", "律師費": r"律師費", "違約金": r"違約金", "租金": r"租金"}
lines = []


def say(s=""):
    print(s, flush=True)
    lines.append(s)


def load():
    d = tvs.load("v5")
    con = sqlite3.connect(f"file:{config.WORK_DB}?mode=ro", uri=True)
    con.execute("CREATE TEMP TABLE ids(id INTEGER PRIMARY KEY)")
    con.executemany("INSERT INTO ids VALUES (?)", [(int(i),) for i in d.id])
    a = pd.read_sql("""SELECT j.id, j.grant_ratio, j.grant_ratio_source, j.claimed_amount, j.claimed_source, j.quality_flags
                       FROM judgments j JOIN ids USING (id)""", con)
    d = d.merge(a, on="id", how="left", validate="1:1")
    flow = [("v5 全部", len(d))]
    keep = ["一部勝訴一部敗訴"] if SAMPLE == "part" else ["勝訴", "一部勝訴一部敗訴"]
    d = d[d.outcome.isin(keep)]; flow.append(("、".join(keep), len(d)))
    d = d[d.grant_ratio_source == "計算"]; flow.append(("獲償比例是算出來的", len(d)))
    d = d[~d.quality_flags.fillna("").str.contains("判准大於請求")]; flow.append(("排除「判准大於請求」旗標", len(d)))
    d = d[(d.grant_ratio > 0) & (d.grant_ratio <= 1) & (d.claimed_amount > 0)]
    flow.append(("比例在 (0, 1]、請求金額 > 0", len(d)))
    d = d[d.claimed_source.fillna("").str.startswith("直接抽取")]; flow.append(("請求金額從聲明直接抽取", len(d)))
    if QUICK:
        d = d.sample(3000, random_state=0)
    d = d.reset_index(drop=True)
    for nm, pat in ITEMS.items():
        d["項_" + nm] = d.p.str.contains(pat).astype(int)
    d["項目數"] = d[["項_" + nm for nm in ITEMS]].sum(1)
    return d, flow


def evaluate(r_true, claim, r_pred):
    """比例與金額兩組指標。預測的比例裁到 [0.001, 1]（樣本的比例都在 (0, 1]）。"""
    r_pred = np.clip(r_pred, 0.001, 1)
    a_true, a_pred = r_true * claim, r_pred * claim
    e = np.abs(r_pred - r_true)
    le = np.abs(np.log10(a_pred) - np.log10(a_true))
    return {"比例_MAE": e.mean(), "比例_RMSE": np.sqrt((e ** 2).mean()), "比例_誤差中位數": np.median(e),
            "比例_±10點內": (e <= 0.10).mean(), "比例_±20點內": (e <= 0.20).mean(),
            "比例_Spearman": spearmanr(r_true, r_pred).statistic,
            "金額_誤差倍數中位數": 10 ** np.median(le), "金額_1.5倍內": (le <= np.log10(1.5)).mean(),
            "金額_2倍內": (le <= np.log10(2)).mean(), "金額_MAE元": np.abs(a_pred - a_true).mean(),
            "金額_RMSE元": np.sqrt(((a_pred - a_true) ** 2).mean()), "金額_誤差中位數元": np.median(np.abs(a_pred - a_true)),
            "金額_Spearman": spearmanr(a_true, a_pred).statistic}


def boot_diff(r_true, claim, a, b, keys, n=1000):
    rng = np.random.default_rng(42)
    res = {k: [] for k in keys}
    for _ in range(n):
        i = rng.integers(0, len(r_true), len(r_true))
        ea, eb = evaluate(r_true[i], claim[i], a[i]), evaluate(r_true[i], claim[i], b[i])
        for k in keys:
            res[k].append(ea[k] - eb[k])
    return {k: (np.mean(v), np.percentile(v, 2.5), np.percentile(v, 97.5)) for k, v in res.items()}


def main():
    global SAMPLE, QUICK
    ap = argparse.ArgumentParser(description="金額：比例 vs 金額、加入子項目")
    ap.add_argument("sample", nargs="?", default="part", choices=("part", "win"))
    ap.add_argument("--quick", action="store_true", help="試跑：只取 3,000 件")
    a = ap.parse_args()
    SAMPLE, QUICK = a.sample, a.quick or __import__("os").environ.get("QUICK") == "1"
    sys.stdout.reconfigure(encoding="utf-8")
    t0 = time.time()
    d, flow = load()
    for s, n in flow:
        print(f"  {s}: {n:,}")
    if SAMPLE == "part" and not QUICK:
        d[["id", "grant_ratio"]].to_csv(OUT / "amount_v5_sample.csv", index=False)   # 給 train_longformer.py --task amount
    r = d.grant_ratio.values.astype(float)
    claim = d.claimed_amount.values.astype(float)
    la = np.log10(r * claim)
    lc = np.log10(claim)
    C = np.column_stack([lc, lc ** 2])
    S = pd.get_dummies(d[tvs.FEATS].astype({c: str for c in tvs.CATS}), drop_first=True).astype(float).values
    F = d[["項_" + nm for nm in ITEMS] + ["項目數"]].values.astype(float)
    use_lf = all((OUT / LF.format(k=k) / "metrics.json").exists() for k in range(5))

    models = ["0. 全體中位數", "1. 案由中類中位數", "2. 請求金額＋結構化", "3. 請求金額＋結構化＋子項目（樹）",
              "4. 文字", "5. 文字＋請求金額＋結構化＋子項目"] + (["6. 5＋Longformer"] if use_lf else [])
    targets = ["比例", "金額"]
    keys = [(m, t) for m in models for t in targets if not (m.startswith(("0.", "1.")) and t == "金額")]
    pred = {k: np.zeros(len(d)) for k in keys}         # 一律存成「預測的獲償比例」
    for k in range(5):
        te = (d.fold == k).values
        va = ((d.fold == (k + 1) % 5) & (d.val_half == 1)).values
        tr = (d.fold != k).values & ~va
        vp, vd = vec(), vec()
        Ttr = hstack([vp.fit_transform(d.p[tr]), vd.fit_transform(d.d[tr])]).tocsr()
        Tva = hstack([vp.transform(d.p[va]), vd.transform(d.d[va])]).tocsr()
        Tte = hstack([vp.transform(d.p[te]), vd.transform(d.d[te])]).tocsr()
        D = np.column_stack([C, S, F])
        mu, sd = D[tr].mean(0), D[tr].std(0) + 1e-9
        Dz = (D - mu) / sd
        CSz = Dz[:, :C.shape[1] + S.shape[1]]
        med = np.median(r[tr])
        pred[(models[0], "比例")][te] = med
        mids = d["mid"].values
        mm = pd.Series(r[tr]).groupby(mids[tr]).agg(["median", "size"])
        mm = mm["median"].where(mm["size"] >= 30)
        pred[(models[1], "比例")][te] = pd.Series(mids[te]).map(mm).fillna(med).values
        for t in targets:
            yt = r if t == "比例" else la
            back = (lambda p, i: p) if t == "比例" else (lambda p, i: 10 ** p / claim[i])   # 換算回獲償比例
            ite, iva = np.where(te)[0], np.where(va)[0]
            p2 = Ridge(alpha=1.0).fit(CSz[tr], yt[tr]).predict(CSz[te])
            p3 = HistGradientBoostingRegressor(random_state=42).fit(D[tr], yt[tr]).predict(D[te])
            p4 = Ridge(alpha=1.0).fit(Ttr, yt[tr]).predict(Tte)
            X5 = lambda T, m: hstack([T, csr_matrix(Dz[m])]).tocsr()          # noqa: E731
            m5 = Ridge(alpha=1.0).fit(X5(Ttr, tr), yt[tr])
            p5, p5v = m5.predict(X5(Tte, te)), m5.predict(X5(Tva, va))
            pred[(models[2], t)][te] = back(p2, ite)
            pred[(models[3], t)][te] = back(p3, ite)
            pred[(models[4], t)][te] = back(p4, ite)
            pred[(models[5], t)][te] = back(p5, ite)
            if use_lf:
                lf = pd.read_csv(OUT / LF.format(k=k) / "pred.csv").set_index("id").loc[d.id.values[te], "pred"].values
                lfv = pd.read_csv(OUT / LF.format(k=k) / "val_pred.csv").set_index("id").loc[d.id.values[va], "pred"].values
                if t == "金額":                         # Longformer 預測的是比例；金額目標時換成 log10(比例 × 請求)
                    lf, lfv = np.log10(np.clip(lf, 0.001, 1) * claim[te]), np.log10(np.clip(lfv, 0.001, 1) * claim[va])
                bl = LinearRegression().fit(np.column_stack([p5v, lfv]), yt[va])        # 權重只看驗證集
                pred[(models[6], t)][te] = back(bl.predict(np.column_stack([p5, lf])), ite)
        print(f"  fold {k} 完成（{(time.time() - t0) / 60:.1f} 分）", flush=True)

    rows = [{"模型": m, "目標": t, **evaluate(r, claim, pred[(m, t)])} for m, t in keys]
    res = pd.DataFrame(rows)
    res.to_csv(OUT / f"amount_v5_{SAMPLE}{'_quick' if QUICK else ''}_指標.csv", index=False, encoding="utf-8-sig")

    say(f"# 金額：比例 vs 金額、加入子項目、用誤差評估（v5，樣本：{SAMPLE}，{len(d):,} 件）\n")
    say("樣本流程：" + " → ".join(f"{s} {n:,}" for s, n in flow) + "\n")
    say(f"獲償比例中位數 {np.median(r):.3f}、平均 {r.mean():.3f}；請求金額中位數 {np.median(claim):,.0f} 元。"
        "金額欄位是規則 2.4.0（暫定）。目標「金額」＝預測 log10(判准金額)，再換算成比例；兩種目標用同一組指標。")
    say(f"獲償比例 < 0.01 的案件 {(r < 0.01).sum():,} 件（{(r < 0.01).mean():.1%}）：試跑時誤差最大的幾乎都是這類，"
        "可能是金額擷取問題（例如只抓到利息或零頭），要和同學的金額 2.5.0 對照。\n")
    say("## 1. 比例的誤差（獲償比例，0–1）\n")
    say("| 模型 | 目標 | MAE | RMSE | 誤差中位數 | ±10 點內 | ±20 點內 | Spearman |")
    say("|---|---|---:|---:|---:|---:|---:|---:|")
    for _, x in res.iterrows():
        say(f"| {x['模型']} | {x['目標']} | {x['比例_MAE']:.3f} | {x['比例_RMSE']:.3f} | {x['比例_誤差中位數']:.3f} | "
            f"{x['比例_±10點內']:.1%} | {x['比例_±20點內']:.1%} | {x['比例_Spearman']:.3f} |")
    say("\n## 2. 金額的誤差（判准金額，元）\n")
    say("| 模型 | 目標 | 誤差倍數中位數 | 1.5 倍內 | 2 倍內 | MAE（萬元） | RMSE（萬元） | 誤差中位數（萬元） | Spearman |")
    say("|---|---|---:|---:|---:|---:|---:|---:|---:|")
    for _, x in res.iterrows():
        say(f"| {x['模型']} | {x['目標']} | {x['金額_誤差倍數中位數']:.2f} | {x['金額_1.5倍內']:.1%} | {x['金額_2倍內']:.1%} | "
            f"{x['金額_MAE元'] / 1e4:,.1f} | {x['金額_RMSE元'] / 1e4:,.1f} | {x['金額_誤差中位數元'] / 1e4:,.1f} | {x['金額_Spearman']:.3f} |")
    say("\nRMSE（元）會被少數上億元的案件主導，看「誤差倍數」與「2 倍內」比較能代表一般案件。")

    best = models[-1]
    comps = [((best, "比例"), (models[1], "比例")), ((best, "金額"), (best, "比例")),
             ((models[3], "比例"), (models[2], "比例")), ((models[5], "比例"), (models[4], "比例"))]
    say("\n## 3. 成對比較（bootstrap 1,000 次）\n")
    say("| 比較 | 比例 MAE 差 | 金額 2 倍內 差 |")
    say("|---|---|---|")
    for a, b in comps:
        bd = boot_diff(r, claim, pred[a], pred[b], ["比例_MAE", "金額_2倍內"])
        say(f"| {a[0]}（{a[1]}）− {b[0]}（{b[1]}） | {bd['比例_MAE'][0]:+.4f}（{bd['比例_MAE'][1]:+.4f}～{bd['比例_MAE'][2]:+.4f}） | "
            f"{bd['金額_2倍內'][0]:+.3f}（{bd['金額_2倍內'][1]:+.3f}～{bd['金額_2倍內'][2]:+.3f}） |")

    # 分組：案由大類、請求金額級距
    bins = [0, 5e5, 1.5e6, 5e6, np.inf]
    labels = ["≤50 萬", "50–150 萬", "150–500 萬", ">500 萬"]
    d["請求級距"] = pd.cut(claim, bins, labels=labels)
    g = []
    for col in ("case_type_category", "請求級距"):
        for v, sub in d.groupby(col, observed=True):
            if len(sub) < 200:
                continue
            i = sub.index.values
            for m in (models[1], best):
                x = evaluate(r[i], claim[i], pred[(m, "比例")][i])
                g.append({"分組": col.replace("case_type_category", "案由大類"), "值": v, "件數": len(i), "模型": m,
                          "比例_MAE": round(x["比例_MAE"], 3), "金額_2倍內": round(x["金額_2倍內"], 3),
                          "金額_誤差倍數中位數": round(x["金額_誤差倍數中位數"], 2)})
    g = pd.DataFrame(g)
    g.to_csv(OUT / f"amount_v5_{SAMPLE}{'_quick' if QUICK else ''}_分組.csv", index=False, encoding="utf-8-sig")
    say(f"\n## 4. 分組（{models[1]} vs {best}，目標：比例；≥200 件）\n")
    say("| 分組 | 值 | 件數 | 模型 | 比例 MAE | 金額 2 倍內 | 誤差倍數中位數 |")
    say("|---|---|---:|---|---:|---:|---:|")
    for _, x in g.iterrows():
        say(f"| {x['分組']} | {x['值']} | {x['件數']} | {x['模型']} | {x['比例_MAE']:.3f} | {x['金額_2倍內']:.1%} | {x['金額_誤差倍數中位數']:.2f} |")

    # 個案：每件的預測；誤差最大的 30 件
    o = d[["id", "case_number", "fold", "case_type_category", "case_type_mid", "claimed_amount", "grant_ratio"]
          + ["項_" + nm for nm in ITEMS] + ["項目數"]].copy()
    o["判准金額"] = r * claim
    for (m, t), p in pred.items():
        o[f"{m}｜{t}"] = np.clip(p, 0.001, 1)
    bp = np.clip(pred[(best, "比例")], 0.001, 1)
    o["最佳_預測金額"] = bp * claim
    o["最佳_誤差倍數"] = 10 ** np.abs(np.log10(bp) - np.log10(r))
    o.to_csv(OUT / f"amount_v5_{SAMPLE}{'_quick' if QUICK else ''}_個案.csv", index=False, encoding="utf-8-sig")
    say(f"\n## 5. 誤差最大的 30 件（{best}，目標：比例）\n")
    say("| 案號 | 案由中類 | 請求（萬元） | 判准（萬元） | 實際比例 | 預測比例 | 誤差倍數 |")
    say("|---|---|---:|---:|---:|---:|---:|")
    for _, x in o.sort_values("最佳_誤差倍數", ascending=False).head(30).iterrows():
        say(f"| {x.case_number} | {x.case_type_mid} | {x.claimed_amount / 1e4:,.1f} | {x['判准金額'] / 1e4:,.1f} | "
            f"{x.grant_ratio:.3f} | {x['最佳_預測金額'] / x.claimed_amount:.3f} | {x['最佳_誤差倍數']:.1f} |")
    say("\n子項目旗標的比例：" + "、".join(f"{nm} {d['項_' + nm].mean():.1%}" for nm in ITEMS))
    (OUT / f"amount_v5_{SAMPLE}{'_quick' if QUICK else ''}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"完成，{(time.time() - t0) / 60:.1f} 分鐘")


if __name__ == "__main__":
    main()
