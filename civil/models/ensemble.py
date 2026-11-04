"""
勝敗的合併模型與 precision／recall 評估（TF-IDF、結構化、BERT、Longformer）。

    python -m civil.models.ensemble v5
    python -m civil.models.ensemble v5 --quick      # 試跑：只取 3,000 件，輸出檔名加 _quick

老師的回饋（10/27）：
  1. 不要只報 AUC，要報「原告勝訴」與「原告敗訴」各自的 precision、recall
  2. 合併改成 TF-IDF＋Longformer＋結構化（三種取得資訊的方式不同）；BERT 和 Longformer 讀的東西差不多，不必重複
做法：每一折 k，測試＝fold==k；驗證集＝fold==(k+1)%5 且 val_half==1；其餘為訓練。
  - TF-IDF（兩造、只用原告、只用被告）與結構化（structured.FEATS，logistic regression）在訓練上 fit
  - BERT、Longformer 讀實驗輸出的 val_pred.csv、pred.csv（epoch 由驗證集選）；還沒跑完的折就略過
  - 合併權重只用驗證集決定（blend）；測試折只算最後的指標
指標（全部用折外預測合起來算；門檻 0.5，事先固定）：
  AUC；原告勝訴（y=1）與原告敗訴（y=0）各自的 precision、recall、F1、平均 precision（PR 曲線下面積）；
  正確率；「最有把握的 20%」的 precision（預測機率最高 20% 判勝、最低 20% 判敗）。
  主要指標附成對 bootstrap 95% CI（1,000 次）。
  某個模型有缺折時，只在它有預測的折上算，表格會標出用了哪些折；比較兩個模型時只用兩者共有的案件。
輸出：pr_ensemble_{版本}.md、_指標.csv、_分大類.csv、_PR曲線.csv、_合併權重.csv、_oof.csv
"""
import argparse
import time

import numpy as np
import pandas as pd
from scipy.sparse import hstack
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score

import config
from civil.models.structured import load
from civil.models.structured import design as structured_design
from civil.models.tfidf import logreg, vec

RNG = np.random.default_rng(42)
MAIN = "TF-IDF＋Longformer＋結構化（老師建議）"


def logit(p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def blend(yv, Pv, Pt):
    """在驗證集上，以各模型預測的 logit 為變數 fit logistic regression，再套到測試集。回傳（測試預測, 權重）。"""
    m = LogisticRegression(max_iter=1000).fit(np.column_stack([logit(p) for p in Pv]), yv)
    return m.predict_proba(np.column_stack([logit(p) for p in Pt]))[:, 1], m.coef_[0]


def tfidf_fit(d, tr, targets):
    """TF-IDF 原告＋被告（兩造各一個向量器）在訓練列上 fit，回傳每個 targets 的預測。"""
    vp, vd = vec(), vec()
    X = hstack([vp.fit_transform(d.p[tr]), vd.fit_transform(d.d[tr])]).tocsr()
    m = logreg().fit(X, d.y.values[tr])
    return [m.predict_proba(hstack([vp.transform(d.p[t]), vd.transform(d.d[t])]).tocsr())[:, 1] for t in targets]


def tfidf_one(d, col, tr, targets):
    v = vec()
    m = logreg().fit(v.fit_transform(d[col][tr]), d.y.values[tr])
    return [m.predict_proba(v.transform(d[col][t]))[:, 1] for t in targets]


def pr(y, p, thr=0.5):
    """原告勝訴（y=1）與敗訴（y=0）各自的 precision、recall、F1，加上正確率與最有把握 20% 的 precision。"""
    yhat = p >= thr
    out = {}
    for lab, pos, s in (("勝訴", y == 1, p), ("敗訴", y == 0, 1 - p)):
        pred_pos = yhat if lab == "勝訴" else ~yhat
        tp = (pred_pos & pos).sum()
        prec = tp / max(pred_pos.sum(), 1)
        rec = tp / max(pos.sum(), 1)
        out[f"{lab}_precision"] = prec
        out[f"{lab}_recall"] = rec
        out[f"{lab}_F1"] = 2 * prec * rec / max(prec + rec, 1e-12)
        out[f"{lab}_AP"] = average_precision_score(pos, s)
        top = s >= np.quantile(s, 0.8)                     # 最有把握判成這一邊的 20%
        out[f"{lab}_最有把握20%_precision"] = pos[top].mean()
    out["正確率"] = (yhat == (y == 1)).mean()
    out["AUC"] = roc_auc_score(y, p)
    return out


def boot(y, p, keys, n=1000):
    idx = [RNG.integers(0, len(y), len(y)) for _ in range(n)]
    vals = [pr(y[i], p[i]) for i in idx]
    return {k: (np.percentile([v[k] for v in vals], 2.5), np.percentile([v[k] for v in vals], 97.5)) for k in keys}


def boot_diff(y, a, b, keys, n=1000):
    idx = [RNG.integers(0, len(y), len(y)) for _ in range(n)]
    pairs = [(pr(y[i], a[i]), pr(y[i], b[i])) for i in idx]
    out = {}
    for key in keys:
        diff = [pa[key] - pb[key] for pa, pb in pairs]
        out[key] = (np.mean(diff), np.percentile(diff, 2.5), np.percentile(diff, 97.5))
    return out


def read_pred(tag, ids, file):
    """BERT／Longformer 的折外預測（實驗輸出資料夾）。還沒跑完（沒有 metrics.json）就回傳 None。"""
    p = config.OUTPUT_DIR / tag
    if not (p / "metrics.json").exists():
        return None
    b = pd.read_csv(p / file).set_index("id")
    assert set(ids) <= set(b.index), f"{tag}/{file} 的案件和資料集不一致"
    return b.loc[ids, "prob"].values


def main():
    ap = argparse.ArgumentParser(description="勝敗合併模型與 precision／recall 評估")
    ap.add_argument("version", nargs="?", default="v5")
    ap.add_argument("--quick", action="store_true", help="試跑：只取 3,000 件")
    a = ap.parse_args()
    ver, quick = a.version, a.quick
    suffix = "_quick" if quick else ""
    out_dir = config.OUTPUT_DIR
    lf_tag = "longformer_pd_fold{k}_" + ver + "_L4096_t2s"
    bt_tag = "bert_pd_fold{k}_" + ver + "_headtail_val"
    lines = []

    def say(s=""):
        print(s, flush=True)
        lines.append(s)

    t0 = time.time()
    d = load(ver)
    if quick:
        d = d.sample(3000, random_state=0).reset_index(drop=True)
    y = d.y.values
    S = structured_design(d)
    base = ["TF-IDF 兩造", "TF-IDF 只用原告", "TF-IDF 只用被告", "結構化", "BERT", "Longformer"]
    combos = {"TF-IDF＋結構化": ("TF-IDF 兩造", "結構化"),
              "TF-IDF＋Longformer": ("TF-IDF 兩造", "Longformer"),
              MAIN: ("TF-IDF 兩造", "Longformer", "結構化"),
              "TF-IDF＋BERT＋Longformer（10/26 簡報）": ("TF-IDF 兩造", "BERT", "Longformer"),
              "TF-IDF＋BERT＋Longformer＋結構化（參考）": ("TF-IDF 兩造", "BERT", "Longformer", "結構化")}
    names = base + list(combos)
    oof = {nm: np.full(len(d), np.nan) for nm in names}
    weights = []
    for k in range(5):
        te = (d.fold == k).values
        va = ((d.fold == (k + 1) % 5) & (d.val_half == 1)).values
        tr = (d.fold != k).values & ~va
        iv, it = d.id.values[va], d.id.values[te]
        P = {"TF-IDF 兩造": tuple(tfidf_fit(d, tr, [va, te])),
             "TF-IDF 只用原告": tuple(tfidf_one(d, "p", tr, [va, te])),
             "TF-IDF 只用被告": tuple(tfidf_one(d, "d", tr, [va, te]))}
        st = LogisticRegression(penalty=None, max_iter=3000).fit(S[tr], y[tr])
        P["結構化"] = (st.predict_proba(S[va])[:, 1], st.predict_proba(S[te])[:, 1])
        for nm, tag in (("BERT", bt_tag.format(k=k)), ("Longformer", lf_tag.format(k=k))):
            v, t = read_pred(tag, iv, "val_pred.csv"), read_pred(tag, it, "pred.csv")
            if v is not None:
                P[nm] = (v, t)
        for nm, parts in combos.items():
            if all(p in P for p in parts):
                pt, w = blend(y[va], [P[p][0] for p in parts], [P[p][1] for p in parts])
                P[nm] = (None, pt)
                weights.append({"fold": k, "合併": nm, **{p: round(x, 2) for p, x in zip(parts, w)}})
        for nm in P:
            oof[nm][te] = P[nm][1]
        print(f"  fold {k} 完成：{', '.join(P)}（{(time.time() - t0) / 60:.1f} 分）", flush=True)

    folds = {nm: sorted(int(k) for k in d.fold[~np.isnan(oof[nm])].unique()) for nm in names}
    names = [nm for nm in names if folds[nm]]
    rows = []
    for nm in names:
        m = ~np.isnan(oof[nm])
        rows.append({"模型": nm, "折": ",".join(map(str, folds[nm])), "件數": int(m.sum()), **pr(y[m], oof[nm][m])})
    r = pd.DataFrame(rows)
    r.to_csv(out_dir / f"pr_ensemble_{ver}{suffix}_指標.csv", index=False, encoding="utf-8-sig")

    say(f"# 勝敗：precision／recall 與 TF-IDF＋Longformer＋結構化（文字資料集 {ver}，{len(d):,} 件）\n")
    say(f"原告勝訴的比例 {y.mean():.3f}。門檻 0.5（事先固定）。合併權重只用驗證集決定。"
        "「最有把握 20%」＝預測機率最高的 20% 判勝訴（或最低的 20% 判敗訴）時的 precision。\n")
    say("## 1. 各模型\n")
    say("| 模型 | 折 | AUC | 勝訴 precision | 勝訴 recall | 勝訴 F1 | 敗訴 precision | 敗訴 recall | 敗訴 F1 | 正確率 | 勝訴 最有把握20% | 敗訴 最有把握20% |")
    say("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for _, x in r.iterrows():
        say(f"| {x['模型']} | {x['折']} | {x.AUC:.3f} | {x['勝訴_precision']:.3f} | {x['勝訴_recall']:.3f} | {x['勝訴_F1']:.3f} | "
            f"{x['敗訴_precision']:.3f} | {x['敗訴_recall']:.3f} | {x['敗訴_F1']:.3f} | {x['正確率']:.3f} | "
            f"{x['勝訴_最有把握20%_precision']:.3f} | {x['敗訴_最有把握20%_precision']:.3f} |")
    say("\n平均 precision（PR 曲線下面積）：" + "；".join(f"{x['模型']} 勝訴 {x['勝訴_AP']:.3f}、敗訴 {x['敗訴_AP']:.3f}"
                                               for _, x in r.iterrows()))

    if MAIN in names:
        m = ~np.isnan(oof[MAIN])
        keys = ["勝訴_precision", "勝訴_recall", "敗訴_precision", "敗訴_recall", "AUC"]
        ci = boot(y[m], oof[MAIN][m], keys)
        say(f"\n## 2. {MAIN} 的 95% CI（折 {','.join(map(str, folds[MAIN]))}）\n")
        say("| 指標 | 值 | 95% CI |")
        say("|---|---:|---|")
        val = pr(y[m], oof[MAIN][m])
        for k_ in keys:
            say(f"| {k_} | {val[k_]:.3f} | {ci[k_][0]:.3f}～{ci[k_][1]:.3f} |")
        say("\n## 3. 成對比較（只用兩者共有的案件）\n")
        say("| 比較 | 指標 | 差值 | 95% CI |")
        say("|---|---|---:|---|")
        for b in ("TF-IDF＋BERT＋Longformer（10/26 簡報）", "TF-IDF＋Longformer", "TF-IDF 兩造", "Longformer"):
            if b not in names:
                continue
            mm = m & ~np.isnan(oof[b])
            for key, (mean, lo, hi) in boot_diff(y[mm], oof[MAIN][mm], oof[b][mm], ("AUC", "勝訴_F1", "敗訴_F1")).items():
                say(f"| {MAIN} − {b} | {key} | {mean:+.4f} | {lo:+.4f}～{hi:+.4f} |")

        # 分大類：哪些案件類型 precision／recall 比較差
        g = []
        for cat, sub in d[m].groupby("case_type_category"):
            if len(sub) < 200:
                continue
            ii = sub.index.values
            x = pr(y[ii], oof[MAIN][ii])
            g.append({"案由大類": cat, "件數": len(sub), "勝訴比例": round(y[ii].mean(), 3),
                      **{k_: round(x[k_], 3) for k_ in ("AUC", "勝訴_precision", "勝訴_recall", "敗訴_precision", "敗訴_recall")}})
        g = pd.DataFrame(g).sort_values("件數", ascending=False)
        g.to_csv(out_dir / f"pr_ensemble_{ver}{suffix}_分大類.csv", index=False, encoding="utf-8-sig")
        say(f"\n## 4. {MAIN}：分案由大類（≥200 件）\n")
        say("| " + " | ".join(g.columns) + " |")
        say("|" + "---|" * len(g.columns))
        for _, x in g.iterrows():
            say("| " + " | ".join(str(v) for v in x.values) + " |")

    # PR 曲線（畫圖用）：門檻 0.05–0.95
    curve = []
    for nm in names:
        m = ~np.isnan(oof[nm])
        for thr in np.round(np.arange(0.05, 0.96, 0.05), 2):
            x = pr(y[m], oof[nm][m], thr)
            curve.append({"模型": nm, "門檻": thr, **{k_: x[k_] for k_ in
                          ("勝訴_precision", "勝訴_recall", "敗訴_precision", "敗訴_recall")}})
    pd.DataFrame(curve).to_csv(out_dir / f"pr_ensemble_{ver}{suffix}_PR曲線.csv", index=False, encoding="utf-8-sig")
    if weights:
        w = pd.DataFrame(weights)
        say("\n## 5. 合併權重（各折平均，logit 的係數）\n")
        for nm, sub in w.groupby("合併", sort=False):
            say(f"- {nm}：" + "、".join(f"{c} {sub[c].mean():.2f}" for c in sub.columns[2:] if sub[c].notna().any()))
        w.to_csv(out_dir / f"pr_ensemble_{ver}{suffix}_合併權重.csv", index=False, encoding="utf-8-sig")
    o = d[["id", "fold", "y", "case_type_category"]].copy()
    for nm in names:
        o[nm] = oof[nm]
    o.to_csv(out_dir / f"pr_ensemble_{ver}{suffix}_oof.csv", index=False, encoding="utf-8-sig")
    (out_dir / f"pr_ensemble_{ver}{suffix}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"完成，{(time.time() - t0) / 60:.1f} 分鐘")


if __name__ == "__main__":
    main()
