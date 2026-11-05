"""
相似判決檢索的共用核心：字元 1–3 gram TF-IDF、餘弦相似度。民事、刑事各自決定用哪段文字建索引、
用什麼條件篩選（retrieval/civil.py、retrieval/criminal.py），這裡只負責建索引、存檔、查前 k 件。

TF-IDF 的列向量已經 L2 正規化，兩列的內積就是餘弦相似度。
"""
from pathlib import Path
from typing import Optional, Sequence, Tuple

import joblib
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

# 和服務化評估（retrieval_v5，10/27 試做）相同的設定
VECTORIZER_PARAMS = dict(analyzer="char", ngram_range=(1, 3), min_df=10, max_features=100_000,
                         sublinear_tf=True, dtype=np.float32)


class TfidfIndex:
    def __init__(self, **params):
        self.params = {**VECTORIZER_PARAMS, **params}
        self.vectorizer: Optional[TfidfVectorizer] = None
        self.matrix = None

    def fit(self, texts: Sequence[str]) -> "TfidfIndex":
        self.vectorizer = TfidfVectorizer(**self.params)
        self.matrix = self.vectorizer.fit_transform(texts).tocsr()
        return self

    def __len__(self) -> int:
        return 0 if self.matrix is None else self.matrix.shape[0]

    def search(self, query: str, k: int = 10, allowed: Optional[np.ndarray] = None) -> Tuple[np.ndarray, np.ndarray]:
        """
        一筆查詢的前 k 件：回傳（列號, 相似度），相似度由高到低。
        allowed：布林陣列，只在 True 的列裡找（例如同一案由）；沒有任何一列符合時回傳空陣列。
        """
        sim = (self.matrix @ self.vectorizer.transform([query]).T).toarray().ravel()
        if allowed is not None:
            sim = np.where(allowed, sim, -1.0)
        k = min(k, int((sim >= 0).sum()))
        if k <= 0:
            return np.array([], dtype=int), np.array([], dtype=np.float32)
        top = np.argpartition(-sim, k - 1)[:k]
        top = top[np.argsort(-sim[top], kind="stable")]
        return top, sim[top].astype(np.float32)

    def neighbors(self, rows: np.ndarray, k: int = 10, groups: Optional[np.ndarray] = None,
                  chunk: int = 500) -> Tuple[np.ndarray, np.ndarray]:
        """
        索引內每一列（rows）的前 k 個鄰居，排除本身；評估用。
        groups：每一列的類別（例如案由中類），給了就只在同一類裡找。
        """
        X = self.matrix
        nn, sim = [], []
        for j in range(0, len(rows), chunk):
            qq = rows[j:j + chunk]
            S = (X[qq] @ X.T).toarray().astype(np.float32)
            S[np.arange(len(qq)), qq] = -1                     # 排除本身
            if groups is not None:
                S[groups[qq][:, None] != groups[None, :]] = -1
            o = np.argsort(-S, axis=1)[:, :k]
            nn.append(o)
            sim.append(np.take_along_axis(S, o, 1))
        return np.vstack(nn), np.vstack(sim)

    def save(self, path: Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"params": self.params, "vectorizer": self.vectorizer, "matrix": self.matrix}, path)

    @classmethod
    def load(cls, path: Path) -> "TfidfIndex":
        obj = joblib.load(path)
        index = cls(**obj["params"])
        index.vectorizer, index.matrix = obj["vectorizer"], obj["matrix"]
        return index
