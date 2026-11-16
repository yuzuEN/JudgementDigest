"""
相似判決檢索的共用核心：字元 1–3 gram TF-IDF、餘弦相似度。民事、刑事各自決定用哪段文字建索引、
用什麼條件篩選（retrieval/civil.py、retrieval/criminal.py），這裡只負責建索引、存檔、查前 k 件。

TF-IDF 的列向量已經 L2 正規化，兩列的內積就是餘弦相似度。
"""
import re
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import joblib
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

# 不當成關鍵詞的 n-gram：含標點、空白、數字、遮名標記（○、×、【】）的
_NOT_TERM = re.compile(r"[\s\d○×【】「」『』（）()〔〕，。、；：！？,.;:!?／/\-－—…%％]")
# 含人稱代名詞的 n-gram 是口語的寫法（「我在」「說他」），不是案情的關鍵
_PRONOUN = re.compile(r"[我你妳他她們咱]")
# 關鍵詞的 IDF 範圍：太低是判決裡到處都有的詞（「萬元」「請求」），太高是判決幾乎不用的口語（「後來就」「兩次」）
TERM_IDF = (2.5, 6.5)
# 判決裡到處都有、看了沒有幫助的詞
_GENERIC = {"原告", "被告", "請求", "給付", "新臺幣", "本院", "之後", "因為", "所以", "但是", "如果", "已經", "沒有", "對方",
            "後來", "現在", "另外", "也不", "個月", "一定", "費用", "時候", "這段", "期間", "有人", "發現", "知道", "覺得"}
# 詞組頭尾的虛字去掉（「路口時」→「路口」）
_EDGE = "時的了也就都再又同和與及並且而"


def _phrases(query: str, weights: Dict[str, float], n: int) -> List[str]:
    """把貢獻大的 n-gram 在查詢原文裡相連的部分接成詞組，依貢獻排序取前 n 個。"""
    grams = sorted(weights, key=weights.get, reverse=True)[:40]
    score = np.zeros(len(query))
    for g in grams:
        start = query.find(g)
        while start >= 0:
            score[start:start + len(g)] = np.maximum(score[start:start + len(g)], weights[g])
            start = query.find(g, start + 1)
    found: Dict[str, float] = {}
    i = 0
    while i < len(query):
        if score[i] == 0:
            i += 1
            continue
        j = i
        while j < len(query) and score[j] > 0:
            j += 1
        phrase = query[i:j].strip(_EDGE)
        if len(phrase) >= 2 and phrase not in _GENERIC:
            found[phrase] = max(found.get(phrase, 0.0), float(score[i:j].sum()))
        i = j
    picked: List[str] = []
    for phrase in sorted(found, key=found.get, reverse=True):
        if not any(phrase in p for p in picked):        # 「機車修理費」已經選了，就不再列「機車修理」「機車」
            picked.append(phrase)
        if len(picked) == n:
            break
    return picked

# 和服務化評估（retrieval_v5，10/27 試做）相同的設定
VECTORIZER_PARAMS = dict(analyzer="char", ngram_range=(1, 3), min_df=10, max_features=100_000,
                         sublinear_tf=True, dtype=np.float32)


def sort_vocabulary(vectorizer: TfidfVectorizer) -> TfidfVectorizer:
    """存檔前依特徵編號重排詞彙，並拿掉 stop_words_。

    fit 之後 vocabulary_ 依「第一次出現」的順序存放，照順序讀出來就是訓練用的第一份判決的開頭（含人名）。
    特徵編號本來就依字典序排，重排只改存放順序，transform 的結果不變。
    """
    vectorizer.vocabulary_ = dict(sorted(vectorizer.vocabulary_.items(), key=lambda kv: kv[1]))
    vectorizer.__dict__.pop("stop_words_", None)
    return vectorizer


class TfidfIndex:
    def __init__(self, **params):
        self.params = {**VECTORIZER_PARAMS, **params}
        self.vectorizer: Optional[TfidfVectorizer] = None
        self.matrix = None

    def fit(self, texts: Sequence[str], sample: Optional[int] = None, seed: int = 0) -> "TfidfIndex":
        """sample：語料很大時只用這麼多筆建字典與 IDF，再轉換全部（字元 n-gram 的完整字典很吃記憶體）。"""
        self.vectorizer = TfidfVectorizer(**self.params)
        texts = list(texts)
        if sample and len(texts) > sample:
            picked = np.random.default_rng(seed).choice(len(texts), sample, replace=False)
            self.vectorizer.fit([texts[i] for i in picked])
            self.matrix = self.vectorizer.transform(texts).tocsr()
        else:
            self.matrix = self.vectorizer.fit_transform(texts).tocsr()
        return self

    def __len__(self) -> int:
        return 0 if self.matrix is None else self.matrix.shape[0]

    def search(self, query: str, k: int = 10, allowed: Optional[np.ndarray] = None) -> Tuple[np.ndarray, np.ndarray]:
        """
        一筆查詢的前 k 件：回傳（列號, 相似度），相似度由高到低。
        allowed：布林陣列，只在 True 的列裡找（例如同一案由）；沒有任何一列符合時回傳空陣列。
        """
        return self.top(self.scores(query), k, allowed)

    def scores(self, query: str) -> np.ndarray:
        """查詢和每一列的相似度。同一筆查詢要取好幾種前 k 件時，算一次再用 top()。"""
        return (self.matrix @ self.vectorizer.transform([query]).T).toarray().ravel()

    def shared_terms(self, query: str, rows: Sequence[int], n: int = 5,
                     idf_range: Tuple[float, float] = TERM_IDF, display: Optional[str] = None) -> List[List[str]]:
        """
        每一列和查詢共有、對相似度貢獻最大的詞，給人看「為什麼找到這件」。

        相似度是兩個 TF-IDF 向量的內積，每個 n-gram 的貢獻是兩邊權重相乘。取貢獻最大的 2、3 字 n-gram，
        回到查詢原文把相連的 n-gram 接成詞組（「左轉」「轉未」「未讓」→「左轉未讓」）。
        詞組只從查詢（使用者自己的描述）取，不會帶出判決裡的文字。
        idf_range 依民事語料（15.8 萬件）訂的；小語料（測試）的 IDF 都很低，要放寬。
        display：使用者原本的描述。查詢先換過用語時（刑事把「騙」換成「詐騙」），詞組只從原本的描述取，
        原本沒寫的詞不會出現。
        """
        q = self.vectorizer.transform([query]).tocsr()
        if q.nnz == 0:
            return [[] for _ in rows]
        names, idf = self._feature_names(), self.vectorizer.idf_
        out = []
        for row in rows:
            prod = q.multiply(self.matrix[int(row)]).tocsr()
            weights = {names[j]: float(w) for j, w in zip(prod.indices, prod.data)
                       if len(names[j]) >= 2 and idf_range[0] <= idf[j] <= idf_range[1]
                       and not _NOT_TERM.search(names[j]) and not _PRONOUN.search(names[j])}
            out.append(_phrases(query if display is None else display, weights, n))
        return out

    def _feature_names(self) -> np.ndarray:
        if getattr(self, "_names", None) is None:
            names = np.empty(len(self.vectorizer.vocabulary_), dtype=object)
            for term, j in self.vectorizer.vocabulary_.items():
                names[j] = term
            self._names = names
        return self._names

    @staticmethod
    def top(sim: np.ndarray, k: int, allowed: Optional[np.ndarray] = None) -> Tuple[np.ndarray, np.ndarray]:
        if allowed is not None:
            sim = np.where(allowed, sim, -1.0)
        k = min(k, int((sim >= 0).sum()))
        if k <= 0:
            return np.array([], dtype=int), np.array([], dtype=np.float32)
        top = np.argpartition(-sim, k - 1)[:k]
        top = top[np.argsort(-sim[top], kind="stable")]
        return top, sim[top].astype(np.float32)

    def neighbors(self, rows: np.ndarray, k: int = 10, groups: Optional[np.ndarray] = None,
                  chunk: int = 500, allowed: Optional[np.ndarray] = None) -> Tuple[np.ndarray, np.ndarray]:
        """
        索引內每一列（rows）的前 k 個鄰居，排除本身；評估用。
        groups：每一列的類別（例如案由中類），給了就只在同一類裡找。
        allowed：布林陣列，鄰居只能是 True 的列。
        """
        X = self.matrix
        nn, sim = [], []
        for j in range(0, len(rows), chunk):
            qq = rows[j:j + chunk]
            S = (X[qq] @ X.T).toarray().astype(np.float32)
            S[np.arange(len(qq)), qq] = -1                     # 排除本身
            if groups is not None:
                S[groups[qq][:, None] != groups[None, :]] = -1
            if allowed is not None:
                S[:, ~allowed] = -1
            o = np.argsort(-S, axis=1)[:, :k]
            nn.append(o)
            sim.append(np.take_along_axis(S, o, 1))
        return np.vstack(nn), np.vstack(sim)

    def save(self, path: Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        sort_vocabulary(self.vectorizer)
        joblib.dump({"params": self.params, "vectorizer": self.vectorizer, "matrix": self.matrix}, path)

    @classmethod
    def load(cls, path: Path) -> "TfidfIndex":
        obj = joblib.load(path)
        index = cls(**obj["params"])
        index.vectorizer, index.matrix = obj["vectorizer"], obj["matrix"]
        return index
