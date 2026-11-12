"""
文字預測（TF-IDF／BERT）用的資料集。

    python -m civil.dataset.build_dataset v5              # 產生 text_dataset_v5.csv
    python -m civil.dataset.build_dataset v5 _試建        # 輸出 text_dataset_v5_試建.csv，不覆蓋正式檔

輸入（路徑見 config.py，資料版本見 docs/資料版本.md）：
  - 分析用資料庫 judgments_work_20261108.db（規則 2.5.1 的固定副本，唯讀；和 20261014 的 id 相同）
  - analysis_fields.pkl：A2 對審樣本（is_default_judgment=0、結果為四類之一）
  - v5 另讀 text_dataset_v4.csv，沿用 v4 案件的折別
母體：A2 對審樣本，再：
  排除（樣本定義）
    - 一造辯論被換行切開而漏抓的案件（去空白後含「由其一造辯論／一造辯論而為判決」）
    - 案由大類為「身分／家事」「非訟／除權」（不屬於給付確認的勝敗問題）
    - 一份判決合併多個案號（兩案的主張混在一起）
  排除（文字品質，見欄位核對報告 3.9 節）
    - 段落切分狀態不是「成功」
    - 原告主張段少於 50 字，或被告答辯段空白（切分點提前的主要症狀）
    - （v1）被告答辯少於 30 字（被切斷），或答辯段只有「被告未到場」的陳述（實質缺席）
    - （v2）答辯段以原告的聲明收尾：原告主張被誤切進答辯段
  文字處理（v3）：刪除兩段中「聲明」之後的文字與含「主文」的子句（全勝時聲明常寫成「如主文所示」，會洩漏結果）
    - 原告主張段開頭 300 字是程序事項（管轄、準據法、合先敘明）
    - 原告主張或被告答辯段含法院判斷或法院整理的用語（洩漏）
依變數 y：結果不是「敗訴」＝1（勝訴、一部勝訴、確認勝訴），與敏感度分析 A2 相同。
5 折：依 y 分層，種子 42。所有模型（TF-IDF、BERT、結構化變數）共用同一組切分。
每一步排除的筆數寫進 樣本流程_{版本}.csv。

v4（2026-10-14）：
  - 排除「簡上附民移簡」：刑事簡易案件第二審移送民事庭，不是一般的一審對審案件（勝訴率 97%）
  - 聲明之外，再刪除含「假執行」的句子（「願供擔保請准宣告假執行」「免為假執行」也是聲明的一部分）
  - 文字做 NFKC 正規化（㈠→(一)、全形英數→半形），排除與洩漏判斷都在正規化之前做，和 v3 相同
  - 模板化的系列訴訟（原告主張去空白後前 150 字相同）放在同一折：StratifiedGroupKFold
  - 驗證集欄 val_half：測試折為 k 時，驗證集＝fold==(k+1)%5 且 val_half==1 的案件（全部的 10%），
    之後所有「看結果做選擇」（epoch、合併權重）都只看驗證集

v5（2026-10-25，規則 2.5.0）：
  - 判決結果與兩造段落改用規則 2.5.0 在記憶體裡重新推導（structuring.py），資料庫仍是 2.4.0、不寫入
  - 聲明整段刪；段尾的段落編號刪掉；正規化同 v4b，另把 ㊀–㊉ 轉成 ㈠–㈩
  - 法院用語的排除規則同 v4，只有「經查證」不算「經查」
  - 折別：v4 有的案件沿用 v4 的 fold、val_half；新案件併進同模板組所在的折，其餘重新分層分組
"""
import argparse
import re
import sqlite3
import unicodedata

import pandas as pd
from sklearn.model_selection import StratifiedGroupKFold, StratifiedKFold

import config
from civil.dataset.text import (ABSENT_RE, DEFAULT_RE, PLAINTIFF_PRAYER_END_RE, PROC_HEAD_RE, VERSIONS,
                                leak_re, n_case_numbers, normalize_text, strip_for_version)

SEED = 42
OUTCOMES = ["勝訴", "一部勝訴一部敗訴", "敗訴", "確認勝訴"]


def build(version: str, suffix: str = "") -> pd.DataFrame:
    assert version in VERSIONS, "只支援 v3、v4、v4b、v5（v0–v2 的規則已併入 v3）"
    v4 = version in ("v4", "v4b", "v5")
    v5 = version == "v5"
    tag = version + suffix
    config.use_data_pipeline()
    import structuring as S

    base = pd.read_pickle(config.FIELDS_PKL)
    a2 = base[base.is_default_judgment == 0]
    con = sqlite3.connect(f"file:{config.WORK_DB}?mode=ro", uri=True)
    con.execute("CREATE TEMP TABLE ids(id INTEGER PRIMARY KEY)")
    con.executemany("INSERT INTO ids VALUES (?)", [(int(i),) for i in a2.id])
    if v5:
        # 資料庫是 2.4.0；v5 用目前的 structuring.py（2.5.0）在記憶體裡重新推導，不寫回資料庫
        src = ", ".join(f"j.{c}" for c in S.SOURCE_COLUMNS)
        df = pd.read_sql(f"SELECT j.id, {src} FROM judgments j JOIN ids USING (id)", con)
        derived = pd.DataFrame([S.derive_structured_fields(r) for r in
                                df[S.SOURCE_COLUMNS].to_dict("records")], index=df.index)
        keep_cols = ["case_kind", "case_type_category", "case_type_mid", "outcome", "structuring_version",
                     "section_split_status", "plaintiff_claim_text", "defendant_defense_text",
                     "is_default_judgment"]
        df = pd.concat([df[["id", "case_number", "court", "judgment_date", "case_type", "full_text"]],
                        derived[keep_cols]], axis=1)
        df["head"] = df.full_text.fillna("").str[:400]
        # A2 的定義（沒有一造辯論）用 2.5.0 重算的值；規則沒改這一欄，應該和 analysis_fields 相同
        assert (df.is_default_judgment == 0).all()
    else:
        df = pd.read_sql("""
            SELECT j.id, j.case_number, j.court, j.judgment_date, j.case_kind, j.case_type,
                   j.case_type_category, j.case_type_mid, j.outcome, j.structuring_version,
                   j.section_split_status, j.plaintiff_claim_text, j.defendant_defense_text,
                   substr(j.full_text, 1, 400) AS head, j.full_text
            FROM judgments j JOIN ids USING (id)""", con)
    con.close()
    rule = S.STRUCTURING_VERSION if v5 else "2.4.0"
    assert set(df.structuring_version) == {rule}

    leak = leak_re(version)
    flow = [(f"A2 對審樣本（{rule} 結果為四類之一）", None)]
    df = df[df.outcome.isin(OUTCOMES)].copy()
    flow[0] = (flow[0][0], len(df))
    squeezed = df.full_text.fillna("").map(lambda t: re.sub(r"\s+", "", t))
    steps = [
        ("排除：一造辯論換行漏抓", squeezed.str.contains(DEFAULT_RE)),
        ("排除：案由大類為身分／家事、非訟／除權", df.case_type_category.isin(["身分／家事", "非訟／除權"])),
        ("排除：一份判決合併多個案號", df["head"].map(n_case_numbers) >= 2),
    ]
    if v4:
        steps.append(("（v4）排除：簡上附民移簡（刑事簡易第二審移送）", df.case_kind.fillna("").str.contains("簡上")))
    pc = df.plaintiff_claim_text.fillna("")
    dd = df.defendant_defense_text.fillna("")
    steps += [
        ("排除：段落切分不是「成功」", df.section_split_status != "成功"),
        ("排除：原告主張少於 50 字", pc.str.len() < 50),
        ("排除：被告答辯段空白", dd.str.len() == 0),
        # v1 新增：答辯段被切斷（少於 30 字，如「被告則以：對於」），或答辯段只有「被告未到場」的陳述
        # （實質上被告全部缺席，勝訴率 95%，模型會只學到「被告沒來」）
        ("排除：被告答辯少於 30 字", dd.str.len() < 30),
        ("排除：答辯段只有被告未到場的陳述", dd.str.contains(ABSENT_RE) & (dd.str.len() <= 150)),
        # v2 新增：原告主張中出現「被告…部分」（如「被告就該部分瑕疵修繕後」），切分規則誤當答辯開頭，
        # 原告主張後半段連同原告的聲明被分進答辯段。特徵是答辯段以原告的聲明收尾（抽 4 筆都確認是這種錯誤）
        ("排除：答辯段以原告的聲明收尾（原告主張被誤切進答辯）",
         dd.str[-200:].str.contains(PLAINTIFF_PRAYER_END_RE) & ~dd.str[-200:].str.contains(r"免為假執行|駁回")),
        ("排除：原告主張開頭是程序事項", pc.str[:300].str.contains(PROC_HEAD_RE)),
        ("排除：原告主張段有法院判斷或整理用語", pc.str.contains(leak)),
        ("排除：被告答辯段有法院判斷或整理用語", dd.str.contains(leak)),
    ]
    keep = pd.Series(True, index=df.index)
    for name, mask in steps:
        drop = keep & mask.fillna(False)
        keep &= ~drop
        flow.append((name, -int(drop.sum())))
    df = df[keep].copy()

    # v3：刪除「聲明」與「主文」所在的句子（以。分句）。法官在原告全部勝訴時常把聲明簡寫成
    # 「並聲明：如主文第1項所示」（含「主文」的原告主張 98% 勝訴），被告答辯寫「如主文所示」時多半是
    # 原告敗訴；沒全勝時才寫出完整聲明，所以「有沒有完整聲明」本身也透露結果。兩造的聲明一律刪除。
    for col in ("plaintiff_claim_text", "defendant_defense_text"):
        df[col] = df[col].fillna("").map(lambda t: strip_for_version(t, version))
    n_before = len(df)
    df = df[(df.plaintiff_claim_text.str.len() >= 50) & (df.defendant_defense_text.str.len() >= 30)].copy()
    short = "v5" if v5 else ("v4" if v4 else "v3")
    flow.append((f"（{short}）刪除聲明句後，原告主張少於 50 字或答辯少於 30 字", -(n_before - len(df))))
    if v4:   # 正規化放在所有篩選之後：㈠→(一) 會讓字數變多，放在前面會改變長度門檻的結果
        for col in ("plaintiff_claim_text", "defendant_defense_text"):
            df[col] = df[col].map(lambda t: normalize_text(t, version))
    flow.append(("文字資料集", len(df)))
    df["y"] = (df.outcome != "敗訴").astype(int)
    df["year"] = df.judgment_date.str[:4]
    df["fold"] = -1
    if not v4:
        skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=SEED)
        for k, (_, te) in enumerate(skf.split(df, df.y)):
            df.iloc[te, df.columns.get_loc("fold")] = k
    else:
        # 模板化的系列訴訟：原告主張去空白後前 150 字相同的案件為一組，同組放在同一折
        # 分組一律用 NFKC 後的文字算，v4 與 v4b 的分組、折別、驗證集才會完全相同（只差在文字正規化）
        key = df.plaintiff_claim_text.map(lambda t: re.sub(r"\s+", "", unicodedata.normalize("NFKC", t))[:150])
        df["group"] = pd.factorize(key)[0]
        df["val_half"] = 0
        if v5:
            # v4 有的案件沿用 v4 的折別與驗證集，v4 與 v5 才能在同一批案件上做成對比較（G9 消融）。
            # 同一模板組的新案件放進該組 v4 案件最多的那一折；整組都是新案件的，另外分層分組。
            prev = pd.read_csv(config.dataset_path("v4"), usecols=["id", "fold", "val_half"])
            df = df.merge(prev.rename(columns={"fold": "fold4", "val_half": "vh4"}), on="id", how="left")
            old = df[df.fold4.notna()]
            g_fold = old.groupby("group").fold4.agg(lambda s: s.mode().iloc[0])
            g_vh = old.groupby("group").vh4.agg(lambda s: s.mode().iloc[0])
            n_conflict = int((old.fold4 != old.group.map(g_fold)).sum())
            print(f"v4 案件 {len(old):,}（模板組內 v4 折別不一致而改折的 {n_conflict} 件）")
            hit = df.group.isin(g_fold.index)
            df.loc[hit, "fold"] = df.loc[hit, "group"].map(g_fold).astype(int)
            df.loc[hit, "val_half"] = df.loc[hit, "group"].map(g_vh).astype(int)
            new = df[~hit]
            sgk = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=SEED)
            for k, (_, te) in enumerate(sgk.split(new, new.y, new.group)):
                df.loc[new.index[te], "fold"] = k
            for k in range(5):
                part = df[(df.fold == k) & ~hit]
                if part.group.nunique() >= 2:
                    half = StratifiedGroupKFold(n_splits=2, shuffle=True, random_state=SEED)
                    _, h = next(half.split(part, part.y, part.group))
                    df.loc[part.index[h], "val_half"] = 1
            df["in_v4"] = df.fold4.notna().astype(int)
        else:
            sgk = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=SEED)
            for k, (_, te) in enumerate(sgk.split(df, df.y, df.group)):
                df.iloc[te, df.columns.get_loc("fold")] = k
            # 每一折再分成兩半（同樣分層、分組），val_half==1 的那半當「前一折」的驗證集
            for k in range(5):
                part = df[df.fold == k]
                half = StratifiedGroupKFold(n_splits=2, shuffle=True, random_state=SEED)
                _, h = next(half.split(part, part.y, part.group))
                df.loc[part.index[h], "val_half"] = 1
        n_grp = df.group.map(df.group.value_counts())
        print(f"模板組：{int((df.group.value_counts() > 1).sum())} 組、{int((n_grp > 1).sum())} 筆")

    cols = ["id", "case_number", "court", "year", "case_kind", "case_type", "case_type_category",
            "case_type_mid", "outcome", "y", "fold", "plaintiff_claim_text", "defendant_defense_text"]
    if v4:
        cols[cols.index("fold") + 1:cols.index("fold") + 1] = ["val_half", "group"] + (["in_v4"] if v5 else [])
    out = config.DATASET_DIR / f"text_dataset_{tag}.csv"
    df[cols].to_csv(out, index=False, encoding="utf-8")
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(flow, columns=["步驟", "筆數"]).to_csv(config.OUTPUT_DIR / f"樣本流程_{tag}.csv",
                                                     index=False, encoding="utf-8-sig")
    for name, n in flow:
        print(f"{name:<30}{n:>8,}")
    print(f"\ny＝1 比例 {df.y.mean():.3f}；原告主張字數中位數 {df.plaintiff_claim_text.str.len().median():.0f}；"
          f"答辯中位數 {df.defendant_defense_text.str.len().median():.0f}")
    print(f"已輸出 {out}")
    return df[cols]


def main():
    ap = argparse.ArgumentParser(description="建立文字預測用的資料集")
    ap.add_argument("version", nargs="?", default="v4b", choices=VERSIONS)
    ap.add_argument("suffix", nargs="?", default="", help="輸出檔名的後綴，試建時不覆蓋正式檔（例：_試建）")
    a = ap.parse_args()
    build(a.version, a.suffix)


if __name__ == "__main__":
    main()
