"""
刑事：罪名、法條、刑度分布、相似判決。

模型（artifacts/criminal_v1）與檢索資料（artifacts/retrieval_criminal_v1）在啟動時讀進記憶體。
沒有模型時整個刑事回傳示例資料（mock = true）；有模型、沒有檢索資料時 similar 是空清單，前端顯示「開發中」。
相似判決只在「含預測的第一個罪名」的判決裡找，這類判決太少時才放寬到全部。
每個罪名另外統計相似判決中含這個罪名的案件的宣告刑分布（similar_sentence），和模型推估並列。
刑事判決沒有判決導讀，列表附司法院的原文網址。
"""
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

from backend import mock
from criminal.models import lay_terms, service as model_service
from retrieval import criminal as retrieval_criminal
from retrieval.engine import TfidfIndex

N_SHOWN = 10
N_CANDIDATES = 40         # 列表從這麼多件裡挑（要去掉摘要開頭相同的制式判決）
DUPLICATE_PREFIX = 40
MIN_SAME_CHARGE = 10      # 含這個罪名的判決少於這個數時，改在全部判決中找
N_SENTENCE_STATS = 50     # 每個罪名的宣告刑分布：取最相似、含這個罪名、有單一宣告刑的這麼多件
MIN_SENTENCE_STATS = 10   # 少於這個數不顯示（件數太少，比例沒有意義）


class CriminalService:
    def __init__(self, artifacts_dir: Path, force_mock: bool = False):
        self.model = self.meta = self.index = None
        self.db_path: Optional[Path] = None
        if force_mock:
            return
        model_dir = model_service.artifact_dir(artifacts_dir)
        if (model_dir / "model.joblib").exists():
            self.model, self.meta = model_service.load(model_dir)
        retrieval_dir = retrieval_criminal.artifact_dir(artifacts_dir)
        if (retrieval_dir / "index.joblib").exists():
            self.index = TfidfIndex.load(retrieval_dir / "index.joblib")
            self.db_path = retrieval_dir / "cases.sqlite"
            rows = self._query("SELECT charges, sentence FROM cases ORDER BY row")
            assert len(rows) == len(self.index), "刑事檢索索引和案件清單的件數不同，請重新執行 python -m retrieval.criminal"
            self.charges = [set(json.loads(r[0])) for r in rows]
            self.buckets = np.array([-1 if b is None else b for b in
                                     (model_service.bucket_of_text(r[1]) for r in rows)])

    @property
    def mock(self) -> bool:
        return self.model is None

    def _query(self, sql: str, params=()) -> List[sqlite3.Row]:
        with closing(sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)) as con:
            con.row_factory = sqlite3.Row
            return con.execute(sql, params).fetchall()

    def model_info(self) -> Dict:
        m = self.meta.get("metrics", {})
        return {"name": self.meta["name"], "description": "犯罪事實的 TF-IDF ＋ SVM（機率經過校正）",
                **{k: m.get(k) for k in ("n_test", "charge_top1", "bucket_accuracy", "bucket_within_one")}}

    @staticmethod
    def query(text: str) -> str:
        """使用者描述 → 模型與檢索的輸入：相容字形轉一般字，口語換成判決書用語（criminal/models/lay_terms.py）。"""
        return lay_terms.to_legal(model_service.normalize(text))

    def report(self, text: str) -> Dict:
        if self.mock:
            return mock.criminal_report()
        text = self.query(text)
        charges = self.model.predict(text)
        sim = self.index.scores(text) if self.index is not None else None
        for c in charges:
            c.update(self.sentence_stats(sim, c["name"]))
        return {"charges": charges, "similar": self.similar(text, charges[0]["name"] if charges else None, sim=sim),
                "model": self.model_info(), "mock": False}

    def sentence_stats(self, sim: Optional[np.ndarray], charge: str) -> Dict:
        """相似判決中、含這個罪名的案件，宣告刑落在各區間的比例；件數太少時不給。"""
        if sim is None:
            return {}
        rows, _ = self.index.top(sim, N_SENTENCE_STATS,
                                 np.array([charge in c for c in self.charges]) & (self.buckets >= 0))
        if len(rows) < MIN_SENTENCE_STATS:
            return {}
        counts = np.bincount(self.buckets[rows], minlength=len(model_service.BUCKETS))
        return {"similar_sentence": [{"label": b, "share": float(n / len(rows))}
                                     for b, n in zip(model_service.BUCKETS, counts)], "n_similar": int(len(rows))}

    def search(self, text: str, k: int) -> List[Dict]:
        if self.mock:
            return mock.criminal_report()["similar"][:k]
        text = self.query(text)
        return self.similar(text, self.model.predict(text)[0]["name"], k)

    def similar(self, text: str, charge: Optional[str], n: int = N_SHOWN, sim: Optional[np.ndarray] = None) -> List[Dict]:
        if self.index is None:
            return []
        sim = self.index.scores(text) if sim is None else sim
        allowed = np.array([charge in c for c in self.charges]) if charge else None
        if allowed is not None and allowed.sum() < MIN_SAME_CHARGE:
            allowed = None
        rows, sims = self.index.top(sim, N_CANDIDATES, allowed)
        if len(rows) == 0:
            return []
        marks = ",".join("?" * len(rows))
        found = {r["row"]: r for r in self._query(f"SELECT * FROM cases WHERE row IN ({marks})", [int(x) for x in rows])}
        out, seen = [], set()
        for row, s in zip(rows, sims):
            r = found[int(row)]
            if r["summary"][:DUPLICATE_PREFIX] in seen:
                continue
            seen.add(r["summary"][:DUPLICATE_PREFIX])
            out.append({"source": "criminal", "case_id": r["id"], "case_number": r["case_number"], "court": r["court"],
                        "year": r["year"], "mid": "、".join(json.loads(r["charges"])), "outcome": "有罪",
                        "similarity": round(float(s), 3), "summary": r["summary"], "sentence": r["sentence"],
                        "url": r["url"] or None})
            if len(out) == n:
                break
        return out
