"""
平台用的刑事模型（第一版）：犯罪事實的 TF-IDF ＋ 線性模型，預測罪名、法條與刑度區間。

    python -m criminal.models.service evaluate --shared <共用實驗包資料夾>   # 共用包 fold_01：比較 LinearSVC 與 LR
    python -m criminal.models.service train --data <CAIL 格式 .jsonl>         # 全部資料訓練，存到 artifacts/criminal_v1/

為什麼用線性模型：共用包上 SVM 與 fastText 的罪名、法條 micro-F1 平手（.924／.886），刑期 SVM 較好；
後端只裝 scikit-learn，不用多裝 PyTorch。平台要顯示機率，LinearSVC 只有分數，所以加機率校正（svm_cal）：
留 10% 訓練資料不訓練，在上面把分數換成機率（Platt scaling）。共用包 fold_01 上 SVM 的 macro-F1 比 LR 高約 .03。
  罪名、法條   one-vs-rest LinearSVC（class_weight balanced），每類各自校正
  刑度區間     LinearSVC 6 類，再用 multinomial LR 把 6 個分數換成機率；6 區間與前端相同
               （拘役、罰金／1–6 月／7–12 月／1–3 年／3–10 年／10 年以上）
  罪名對法條   訓練資料裡單一罪名的犯罪，最常引用的法條（保留「之○」，如刑法第 185 條之 4）；
               有幾個候選時，取粗分法條模型機率最高的
刑度是整個案件的分布，每個罪名附同一份。只判罰金（資料集標「刑期未明」）算進「拘役、罰金」；其他刑期未明、有期徒刑併拘役的案件不進刑度模型。
"""
import argparse
import collections
import csv
import json
import random
import re
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import joblib
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.multiclass import OneVsRestClassifier
from sklearn.preprocessing import MultiLabelBinarizer
from sklearn.svm import LinearSVC

import config

MODEL_NAME = "criminal_v1"
BUCKETS = ["拘役、罰金", "1～6 個月", "7～12 個月", "1～3 年", "3～10 年", "10 年以上"]
BUCKET_UPPER = [6, 12, 36, 120]          # 有期徒刑月數上限 → 區間 1–4；超過 120 個月 → 區間 5
MIN_SHOWN = 0.1                           # 機率達到這個值的罪名才列出（最多 MAX_SHOWN 個，至少列最高的一個）
MAX_SHOWN = 3
MAX_SHOWN_PROBABILITY = 0.99             # 校正後常到 1.0；畫面上不顯示 100%，避免讓人以為確定
LAW_CANDIDATES = 3                        # 每個罪名考慮的常見法條數
C_LR = 4.0
CAL_SHARE = 0.1                           # svm_cal：留這個比例的訓練資料校正機率
MIN_CAL_POSITIVES = 5
SEED = 42
LAW_RE = re.compile(r"^(.+?第\d+條(?:之\d+)?)")
# 修法換條號（與 CAIL 格式資料集 v2 的 relevant_articles_merged 相同）：平台顯示現行條號，另外註明舊條號
LAW_RENUMBERED = {"洗錢防制法第14條": "洗錢防制法第19條", "性侵害犯罪防治法第21條": "性侵害犯罪防治法第50條"}
# 不是罪名本身的條文（刑法總則、程序法、定義或加重條文…），與 CAIL 格式資料集 v2 的篩選相同
NOT_LAW = re.compile(
    r"^(?:刑法第([1-9]|[1-9][0-9])條|刑事訴訟法.*|民法.*|刑法施行法.*|憲法.*"
    r"|毒品危害防制條例第(?:2|17|18|19|20|23|24)條|家庭暴力防治法第[23]條|洗錢防制法第(?:2|3|339)條"
    r"|兒童及少年福利與權益保障法第2條|性騷擾防治法第2條|詐欺犯罪危害防制條例第2條"
    r"|道路交通管理處罰條例第86條|組織犯罪防制條例第(?:2|12)條)")


def normalize(text: str) -> str:
    """相容字形轉一般字（判決常見 U+F967「不」），使用者輸入與訓練資料走同一道處理。"""
    return unicodedata.normalize("NFC", text or "")


def bucket_of(meta: Dict) -> Optional[int]:
    kind = meta.get("sentence_kind")
    if kind == "拘役":
        return 0
    # 只判罰金的案件在資料集裡是「刑期未明」（v2 約 5 萬件）：有罰金、沒有拘役與有期徒刑
    if kind == "刑期未明" and (meta.get("punish_of_money") or 0) > 0 and not (meta.get("detention_days") or 0) \
            and not meta["term_of_imprisonment"]["imprisonment"]:
        return 0
    if kind == "死刑或無期徒刑":
        return len(BUCKETS) - 1
    if kind == "有期徒刑" and meta.get("task_validity", {}).get("imprisonment"):
        return bucket_of_months(meta["term_of_imprisonment"]["imprisonment"])
    return None                           # 刑期未明、有期徒刑併拘役、刑期任務不可用


def bucket_of_months(months: float) -> Optional[int]:
    if months <= 0:
        return None
    return 1 + next((i for i, hi in enumerate(BUCKET_UPPER) if months <= hi), len(BUCKET_UPPER))


def bucket_of_text(sentence: Optional[str]) -> Optional[int]:
    """檢索資料的宣告刑文字（retrieval.criminal.sentence_text）→ 區間。"""
    if not sentence:
        return None
    if sentence.startswith(("拘役", "罰金")):
        return 0
    if sentence in ("死刑", "無期徒刑"):
        return len(BUCKETS) - 1
    m = re.match(r"有期徒刑 (?:(\d+) 年)? ?(?:(\d+) 月)?$", sentence)
    return bucket_of_months(int(m.group(1) or 0) * 12 + int(m.group(2) or 0)) if m else None


def law_text(law: str) -> str:
    """刑法第185條之4 → 刑法第 185 條之 4（畫面上好讀）。"""
    return re.sub(r"第(\d+)條(?:之(\d+))?", lambda m: f"第 {m.group(1)} 條" + (f"之 {m.group(2)}" if m.group(2) else ""), law)


def offense_laws(meta: Dict) -> List[tuple]:
    """（罪名, 法條到「之○」）：只取單一罪名的犯罪，法條才確定是那個罪名的。"""
    d = meta.get("label_detail") or {}
    out = []
    for charges, laws in zip(d.get("standard_charges_by_offense") or [], d.get("raw_laws_by_offense") or []):
        if len(charges or []) != 1:
            continue
        for law in laws or []:
            m = LAW_RE.match(str(law))
            if m and not NOT_LAW.match(m.group(1)):
                out.append((charges[0], m.group(1)))
    return out


def read(path: Path, keep: Optional[set] = None) -> List[Dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            if keep is not None and i not in keep:
                continue
            r = json.loads(line)
            m = r["meta"]
            v = m.get("task_validity") or {}
            rows.append({"line": i, "text": normalize(r["fact"]),
                         "charges": m["accusation"] if v.get("accusation") else None,
                         "articles": m["relevant_articles"] if v.get("article") else None,
                         "bucket": bucket_of(m), "laws": offense_laws(m)})
    return rows


def vectorizer():
    return TfidfVectorizer(analyzer="char", ngram_range=(1, 2), min_df=3, max_features=300_000,
                           sublinear_tf=True, dtype=np.float32)


def classifier(kind: str, jobs: int):
    if kind in ("svm", "svm_cal"):
        return OneVsRestClassifier(LinearSVC(C=0.5, class_weight="balanced"), n_jobs=jobs)
    weight = "balanced" if kind == "lr_balanced" else None
    return OneVsRestClassifier(LogisticRegression(C=C_LR, solver="liblinear", class_weight=weight), n_jobs=jobs)


class Platt:
    """每個類別各自用 sigmoid 把 SVM 分數換成機率，在沒參與訓練的校正資料上擬合（Platt scaling）。
    校正資料裡正例太少的類別，改用所有類別合起來擬合的一條 sigmoid。"""

    def __init__(self, scores: np.ndarray, Y: np.ndarray):
        pooled = LogisticRegression(C=1e4).fit(scores.reshape(-1, 1), Y.reshape(-1))
        self.a = np.full(Y.shape[1], pooled.coef_[0, 0])
        self.b = np.full(Y.shape[1], pooled.intercept_[0])
        for j in range(Y.shape[1]):
            if MIN_CAL_POSITIVES <= Y[:, j].sum() < len(Y):
                lr = LogisticRegression(C=1e4).fit(scores[:, [j]], Y[:, j])
                self.a[j], self.b[j] = lr.coef_[0, 0], lr.intercept_[0]

    def __call__(self, scores: np.ndarray) -> np.ndarray:
        return 1 / (1 + np.exp(-(scores * self.a + self.b)))


class CriminalModel:
    """kind：svm（只有分數，評估用）、svm_cal（SVM＋機率校正，平台用）、lr、lr_balanced。"""

    def __init__(self, kind: str = "svm_cal", jobs: int = 1):
        self.kind, self.jobs = kind, jobs
        self.vec = self.charge = self.article = self.term = None
        self.charge_mlb = self.article_mlb = None
        self.charge_cal = self.article_cal = self.term_cal = None
        self.laws: Dict[str, List[str]] = {}

    def fit(self, rows: List[Dict]) -> "CriminalModel":
        t0 = time.time()
        self.vec = vectorizer().fit([r["text"] for r in rows])
        print(f"TF-IDF 完成（{time.time() - t0:.0f}s）", flush=True)
        cal = []
        if self.kind == "svm_cal":                    # 留一部分不訓練，用來校正機率
            order = random.Random(SEED).sample(range(len(rows)), len(rows))
            n_cal = int(len(rows) * CAL_SHARE)
            cal, rows = [rows[i] for i in order[:n_cal]], [rows[i] for i in order[n_cal:]]
        self.charge, self.charge_mlb = self._fit_multilabel(rows, "charges", cal)
        print(f"罪名完成（{time.time() - t0:.0f}s）", flush=True)
        self.article, self.article_mlb = self._fit_multilabel(rows, "articles", cal)
        print(f"法條完成（{time.time() - t0:.0f}s）", flush=True)
        t = [r for r in rows if r["bucket"] is not None]
        X = self.vec.transform([r["text"] for r in t])
        y = [r["bucket"] for r in t]
        self.term = (LinearSVC(C=0.5) if self.kind.startswith("svm") else
                     LogisticRegression(C=C_LR, max_iter=1000)).fit(X, y)
        if cal:
            c = [r for r in cal if r["bucket"] is not None]
            D = self.term.decision_function(self.vec.transform([r["text"] for r in c]))
            self.term_cal = LogisticRegression(C=1e4, max_iter=1000).fit(D, [r["bucket"] for r in c])
        print(f"刑度完成（{time.time() - t0:.0f}s）", flush=True)
        counts = collections.defaultdict(collections.Counter)
        for r in rows:
            for charge, law in r["laws"]:
                counts[charge][law] += 1
        self.laws = {c: [law for law, _ in n.most_common(LAW_CANDIDATES)] for c, n in counts.items()}
        return self

    def _fit_multilabel(self, rows, key, cal=()):
        a = [r for r in rows if r[key]]
        mlb = MultiLabelBinarizer().fit([r[key] for r in a])
        clf = classifier(self.kind, self.jobs).fit(self.vec.transform([r["text"] for r in a]),
                                                   mlb.transform([r[key] for r in a]))
        c = [r for r in cal if r[key]]
        if c:
            known = set(mlb.classes_)
            Y = mlb.transform([[x for x in r[key] if x in known] for r in c])
            setattr(self, "charge_cal" if key == "charges" else "article_cal",
                    Platt(clf.decision_function(self.vec.transform([r["text"] for r in c])), Y))
        return clf, mlb

    @staticmethod
    def _scores(clf, X, cal=None):
        if cal is not None:
            return cal(clf.decision_function(X))
        return clf.predict_proba(X) if hasattr(clf, "predict_proba") and hasattr(clf.estimators_[0], "predict_proba") \
            else clf.decision_function(X)

    def charge_scores(self, texts) -> np.ndarray:
        return self._scores(self.charge, self.vec.transform([normalize(t) for t in texts]), self.charge_cal)

    def article_scores(self, texts) -> np.ndarray:
        return self._scores(self.article, self.vec.transform([normalize(t) for t in texts]), self.article_cal)

    def term_dist(self, texts) -> np.ndarray:
        """每筆 6 個區間的機率；訓練資料沒出現的區間補 0。"""
        X = self.vec.transform([normalize(t) for t in texts])
        p = np.zeros((X.shape[0], len(BUCKETS)))
        if self.term_cal is not None:
            p[:, self.term.classes_[self.term_cal.classes_]] = self.term_cal.predict_proba(self.term.decision_function(X))
        else:
            p[:, self.term.classes_] = self.term.predict_proba(X)
        return p

    def law_info(self, charge: str, article_p: Dict[str, float]) -> Dict[str, Optional[str]]:
        """罪名對應的法條（現行條號）；修法換過條號的，law_note 註明舊條號。"""
        cands = self.laws.get(charge) or []
        if not cands:
            return {"law": "", "law_note": None}
        # 候選依出現次數排序；粗分法條（去掉「之○」）機率較高的優先，同分維持次數順序
        best = cands[max(range(len(cands)),
                         key=lambda i: (round(article_p.get(re.sub(r"之\d+$", "", cands[i]), 0.0), 2), -i))]
        current = LAW_RENUMBERED.get(best, best)
        note = f"修法後改為{law_text(current)}；修法前的行為適用舊法{law_text(best)}" if current != best else None
        if best in LAW_RENUMBERED.values():
            old = next(k for k, v in LAW_RENUMBERED.items() if v == best)
            note = f"修法前為{law_text(old)}"
        return {"law": law_text(current), "law_note": note}

    def predict(self, text: str) -> List[Dict]:
        """平台用：機率最高的幾個罪名，各附法條與刑度分布（CriminalReport.charges 的格式）。"""
        pc = self.charge_scores([text])[0]
        pa = dict(zip(self.article_mlb.classes_, self.article_scores([text])[0]))
        dist = self.term_dist([text])[0]
        order = [i for i in np.argsort(-pc)[:MAX_SHOWN] if pc[i] >= MIN_SHOWN] or [int(np.argmax(pc))]
        sentence = [{"label": b, "share": float(s)} for b, s in zip(BUCKETS, dist)]
        return [{"name": self.charge_mlb.classes_[i], **self.law_info(self.charge_mlb.classes_[i], pa),
                 "probability": min(float(pc[i]), MAX_SHOWN_PROBABILITY), "sentence": sentence} for i in order]


# ─── 評估（共用實驗包）─────────────────────────────────────────────────────────
def at_least_one(scores: np.ndarray, threshold: float) -> np.ndarray:
    p = (scores >= threshold).astype(int)
    p[np.arange(len(p)), scores.argmax(1)] = 1
    return p


def f1(Y: np.ndarray, P: np.ndarray) -> Dict[str, float]:
    Y, P = Y.astype(bool), P.astype(bool)
    tp, fp, fn = (Y & P).sum(0), (~Y & P).sum(0), (Y & ~P).sum(0)
    d = 2 * tp + fp + fn
    per = np.where(d > 0, 2 * tp / np.maximum(d, 1), 0.0)
    return {"micro": float(2 * tp.sum() / max(2 * tp.sum() + fp.sum() + fn.sum(), 1)), "macro": float(per.mean())}


def scores_of(model: CriminalModel, rows: List[Dict], threshold: Optional[float] = None) -> Dict[str, float]:
    out = {}
    threshold = (0.0 if model.kind == "svm" else 0.5) if threshold is None else threshold
    for key, fn, mlb in (("charges", model.charge_scores, model.charge_mlb),
                         ("articles", model.article_scores, model.article_mlb)):
        b = [r for r in rows if r[key]]
        Y = mlb.transform([[x for x in r[key] if x in set(mlb.classes_)] for r in b])
        s = f1(Y, at_least_one(fn([r["text"] for r in b]), threshold))
        name = "罪名" if key == "charges" else "法條"
        out[f"{name} micro"], out[f"{name} macro"] = s["micro"], s["macro"]
    t = [r for r in rows if r["bucket"] is not None]
    X = model.vec.transform([r["text"] for r in t])
    out["刑度區間 accuracy"] = float((model.term.predict(X) == np.array([r["bucket"] for r in t])).mean())
    return out


def shared_rows(shared: Path, fold: str) -> Dict[str, List[Dict]]:
    with open(shared / "shared_fold_assignments.csv", encoding="utf-8-sig") as f:
        role = {int(a["sample_line_1based"]): a[fold] for a in csv.DictReader(f)}
    jsonl = next(p for p in (shared / "shared_100k.jsonl", shared / "shared_100k_with_article_suffix.jsonl") if p.exists())
    rows = read(jsonl, {i for i, r in role.items() if r in ("train", "test", "holdout")})
    return {k: [r for r in rows if role[r["line"]] == k] for k in ("train", "test", "holdout")}


def evaluate(shared: Path, fold: str, kinds: Iterable[str], jobs: int, out: Path) -> None:
    sp = shared_rows(shared, fold)
    lines = [f"# 刑事平台模型：線性模型比較（共用包 {shared.name}，{fold}）", "",
             f"train {len(sp['train']):,}、test {len(sp['test']):,}、holdout（2025）{len(sp['holdout']):,}。"
             "罪名、法條：LR 機率 ≥ 0.5、SVM 分數 ≥ 0，都至少取一個；刑度區間 6 類（與前端相同）。", "",
             "| 模型 | 資料 | 罪名 micro | 罪名 macro | 法條 micro | 法條 macro | 刑度區間 accuracy | 訓練秒數 |",
             "|---|---|---|---|---|---|---|---|"]
    for kind in kinds:
        t0 = time.time()
        m = CriminalModel(kind, jobs).fit(sp["train"])
        sec = time.time() - t0
        for threshold in ([None] if kind == "svm" else [None, 0.3]):
            label = kind if threshold is None else f"{kind}（機率 >= {threshold}）"
            for split in ("test", "holdout"):
                s = scores_of(m, sp[split], threshold)
                lines.append(f"| {label} | {split} | " + " | ".join(f"{s[k]:.3f}" for k in
                             ("罪名 micro", "罪名 macro", "法條 micro", "法條 macro", "刑度區間 accuracy")) + f" | {sec:.0f} |")
                print(lines[-1], flush=True)
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")   # 每個模型寫一次，中途停掉也留得下


def platform_metrics(model: CriminalModel, rows: List[Dict]) -> Dict[str, float]:
    """給使用者看的測試結果（沒參與訓練的判決）：第一個罪名猜中、刑度區間猜中、差一格以內。"""
    a = [r for r in rows if r["charges"]]
    pc = model.charge_scores([r["text"] for r in a])
    top = model.charge_mlb.classes_[pc.argmax(1)]
    t = [r for r in rows if r["bucket"] is not None]
    pred = model.term_dist([r["text"] for r in t]).argmax(1)
    y = np.array([r["bucket"] for r in t])
    s = scores_of(model, rows)
    return {"n_test": len(rows), "charge_top1": float(np.mean([c in r["charges"] for c, r in zip(top, a)])),
            "charge_micro": s["罪名 micro"], "article_micro": s["法條 micro"],
            "bucket_accuracy": float((pred == y).mean()), "bucket_within_one": float((np.abs(pred - y) <= 1).mean())}


# ─── 正式模型 ──────────────────────────────────────────────────────────────────
def artifact_dir(base: Optional[Path] = None) -> Path:
    return Path(base or config.ARTIFACTS_DIR) / MODEL_NAME


def train(rows: List[Dict], out: Path, source: str, jobs: int = 1) -> Path:
    import sklearn
    model = CriminalModel("svm_cal", jobs).fit(rows)
    out.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, out / "model.joblib", compress=3)
    meta = {"name": MODEL_NAME, "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source": source, "n_train": len(rows), "sklearn": sklearn.__version__, "kind": model.kind,
            "calibration_share": CAL_SHARE,
            "charges": len(model.charge_mlb.classes_), "articles": len(model.article_mlb.classes_), "buckets": BUCKETS}
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def load(path: Optional[Path] = None):
    """回傳（模型, meta）。"""
    path = Path(path or artifact_dir())
    return joblib.load(path / "model.joblib"), json.loads((path / "meta.json").read_text(encoding="utf-8"))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("evaluate")
    e.add_argument("--shared", required=True, type=Path)
    e.add_argument("--fold", default="fold_01")
    e.add_argument("--kinds", default="svm_cal,svm,lr")
    e.add_argument("--jobs", type=int, default=3)
    e.add_argument("--out", type=Path, default=Path("criminal_service_eval.md"))
    t = sub.add_parser("train")
    t.add_argument("--data", required=True, type=Path)
    t.add_argument("--jobs", type=int, default=3)
    t.add_argument("--out", type=Path, default=None)
    mt = sub.add_parser("metrics", help="在沒參與訓練的判決上測試已訓練的模型，結果寫進 meta.json")
    mt.add_argument("--data", required=True, type=Path, help="CAIL 格式 .jsonl（和 train 同一份）")
    mt.add_argument("--lines", required=True, type=Path,
                    help="測試用的行號：每行一個 JSON、含 line（如 criminal_bucket_electra/test.jsonl）")
    t.add_argument("--max-rows", type=int, default=300_000,
                   help="隨機抽這麼多筆訓練；全量 113 萬筆的 TF-IDF 矩陣要 5 GB 以上記憶體。學習曲線上 20 萬筆以後 micro 幾乎不再上升")
    a = ap.parse_args()
    if a.cmd == "evaluate":
        evaluate(a.shared, a.fold, a.kinds.split(","), a.jobs, a.out)
    elif a.cmd == "metrics":
        keep = {json.loads(l)["line"] for l in open(a.lines, encoding="utf-8")}
        model, meta = load()
        meta["metrics"] = {**platform_metrics(model, read(a.data, keep)), "test_lines": a.lines.parent.name + "/" + a.lines.name}
        (artifact_dir() / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(meta["metrics"], ensure_ascii=False, indent=2))
    else:
        with open(a.data, encoding="utf-8") as f:
            n = sum(1 for _ in f)
        keep = set(random.Random(SEED).sample(range(1, n + 1), min(a.max_rows, n)))
        out = train(read(a.data, keep), a.out or artifact_dir(), a.data.name, a.jobs)
        print("存到", out)


if __name__ == "__main__":
    main()
