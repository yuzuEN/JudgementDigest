"""
TF-IDF ＋ logistic regression：只用兩造主張的文字預測勝敗（步驟 3 / M7）。

    python -m civil.models.tfidf v5

方法（Aletras et al. 2016 的 n-gram＋線性模型；中文不斷詞，用字元 1–3 gram）：
  - 字元 n-gram（1–3），雜湊到 2^20 維後做 TF-IDF 加權（sublinear tf）；完整字典會記憶體不足
  - LogisticRegression（liblinear，C=1，class_weight 不調整）
  - 5 折交叉驗證，切分用資料集裡的 fold 欄（所有模型共用）；TF-IDF 只在訓練折上 fit，避免洩漏
比較：
  1. 只用案由中間分類（one-hot）——判斷文字是不是只學到案由
  2. 只用原告主張、只用被告答辯、兩者
  3. 兩者 ＋ 案由中間分類
  4. 各案由中間分類內的 AUC（用「兩者」的折外預測，n≥300 且兩類都有）
  5. 最能區分勝敗的字詞（抽 8,000 筆 fit 一次有名稱的「兩者」模型，只供解讀）
輸出：tfidf_auc_{版本}.csv、tfidf_auc_by_mid_{版本}.csv、tfidf_top_terms_{版本}.csv、
      tfidf_oof_{版本}.csv（折外預測，給之後和 BERT、結構化變數比較）
"""
import argparse
import time

import numpy as np
import pandas as pd
from scipy.sparse import hstack
from sklearn.feature_extraction.text import HashingVectorizer, TfidfTransformer, TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder

import config


def vec():
    # 字元 1–3 gram 的完整字典在 3.5 萬份文件上會用掉十幾 GB 記憶體（MemoryError），
    # 改用雜湊（2^20 維，不需要先建字典）＋ TF-IDF 加權；評估用，不需要還原特徵名稱。
    return make_pipeline(HashingVectorizer(analyzer="char", ngram_range=(1, 3), n_features=2 ** 20,
                                           alternate_sign=False, norm=None, dtype=np.float32),
                         TfidfTransformer(sublinear_tf=True))


def vec_named():
    # 只用來看「哪些字詞最能區分勝敗」：在 8,000 筆抽樣上建有名稱的字典
    return TfidfVectorizer(analyzer="char", ngram_range=(1, 3), min_df=10, max_features=100_000,
                           sublinear_tf=True, dtype=np.float32)


def logreg():
    return LogisticRegression(C=1.0, solver="liblinear", max_iter=2000)


def load(version: str) -> pd.DataFrame:
    df = pd.read_csv(config.dataset_path(version), encoding="utf-8")
    df["p"] = df.plaintiff_claim_text.fillna("")
    df["d"] = df.defendant_defense_text.fillna("")
    df["mid"] = df.case_type_mid.fillna("（空白）")
    return df


def run(df, name, use_p, use_d, use_mid):
    oof = np.zeros(len(df))
    aucs = []
    for k in range(5):
        tr, te = (df.fold != k).values, (df.fold == k).values
        Xtr, Xte = [], []
        if use_p:
            v = vec(); Xtr.append(v.fit_transform(df.p[tr])); Xte.append(v.transform(df.p[te]))
        if use_d:
            v = vec(); Xtr.append(v.fit_transform(df.d[tr])); Xte.append(v.transform(df.d[te]))
        if use_mid:
            o = OneHotEncoder(handle_unknown="ignore")
            Xtr.append(o.fit_transform(df[["mid"]][tr])); Xte.append(o.transform(df[["mid"]][te]))
        m = logreg()
        m.fit(hstack(Xtr).tocsr(), df.y[tr])
        oof[te] = m.predict_proba(hstack(Xte).tocsr())[:, 1]
        aucs.append(roc_auc_score(df.y[te], oof[te]))
    print(f"  {name:<24} AUC {np.mean(aucs):.3f} ± {np.std(aucs):.3f}", flush=True)
    return {"模型": name, "AUC平均": round(np.mean(aucs), 4), "AUC標準差": round(np.std(aucs), 4),
            **{f"fold{k}": round(a, 4) for k, a in enumerate(aucs)}}, oof


def main():
    ap = argparse.ArgumentParser(description="TF-IDF＋logistic regression 預測勝敗（5 折）")
    ap.add_argument("version", nargs="?", default="v5")
    ver = ap.parse_args().version
    out = config.OUTPUT_DIR
    t0 = time.time()
    df = load(ver)
    print(f"text_dataset_{ver}.csv：{len(df):,} 筆，y＝1 比例 {df.y.mean():.3f}", flush=True)

    specs = [("只用案由中間分類", False, False, True),
             ("只用原告主張", True, False, False),
             ("只用被告答辯", False, True, False),
             ("原告＋被告", True, True, False),
             ("原告＋被告＋案由", True, True, True)]
    rows, oofs = [], {}
    for name, p, d, mid in specs:
        r, oof = run(df, name, p, d, mid)
        rows.append(r); oofs[name] = oof
    pd.DataFrame(rows).to_csv(out / f"tfidf_auc_{ver}.csv", index=False, encoding="utf-8-sig")

    oof_df = df[["id", "fold", "y", "mid"]].copy()
    for name, o in oofs.items():
        oof_df[name] = o
    oof_df.to_csv(out / f"tfidf_oof_{ver}.csv", index=False, encoding="utf-8-sig")

    by = []
    for mid, g in oof_df.groupby("mid"):
        if len(g) >= 300 and g.y.nunique() == 2:
            by.append({"案由中間分類": mid, "n": len(g), "勝訴率": round(g.y.mean(), 3),
                       "AUC_原告＋被告": round(roc_auc_score(g.y, g["原告＋被告"]), 4),
                       "AUC_只用原告": round(roc_auc_score(g.y, g["只用原告主張"]), 4),
                       "AUC_只用被告": round(roc_auc_score(g.y, g["只用被告答辯"]), 4)})
    by = pd.DataFrame(by).sort_values("n", ascending=False)
    by.to_csv(out / f"tfidf_auc_by_mid_{ver}.csv", index=False, encoding="utf-8-sig")
    print("\n各案由中間分類內的 AUC（n≥300）：")
    print(by.to_string(index=False))

    # 係數解讀：抽 8,000 筆 fit 一次有名稱的模型（不用來評估）
    s = df.sample(8000, random_state=42)
    vp, vd = vec_named(), vec_named()
    X = hstack([vp.fit_transform(s.p), vd.fit_transform(s.d)]).tocsr()
    m = logreg().fit(X, s.y)
    names = np.array(["原告｜" + t for t in vp.get_feature_names_out()] +
                     ["被告｜" + t for t in vd.get_feature_names_out()])
    coef = m.coef_[0]
    order = np.argsort(coef)
    top = pd.concat([pd.DataFrame({"方向": "傾向原告勝", "特徵": names[order[::-1][:100]],
                                   "係數": coef[order[::-1][:100]].round(3)}),
                     pd.DataFrame({"方向": "傾向原告敗", "特徵": names[order[:100]],
                                   "係數": coef[order[:100]].round(3)})])
    top.to_csv(out / f"tfidf_top_terms_{ver}.csv", index=False, encoding="utf-8-sig")
    print("\n傾向原告勝（前 20）：", "、".join(top[top.方向 == "傾向原告勝"].特徵.head(20)))
    print("傾向原告敗（前 20）：", "、".join(top[top.方向 == "傾向原告敗"].特徵.head(20)))
    print(f"\n完成，{(time.time() - t0) / 60:.1f} 分鐘")


if __name__ == "__main__":
    main()
