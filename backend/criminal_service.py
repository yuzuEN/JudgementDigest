"""
刑事：罪名、法條、刑度分布、相似判決。

模型（artifacts/criminal_v1）與檢索資料（artifacts/retrieval_criminal_v1）在啟動時讀進記憶體。
沒有模型時整個刑事回傳示例資料（mock = true）；有模型、沒有檢索資料時 similar 是空清單，前端顯示「開發中」。
相似判決只在「含預測的第一個罪名」的判決裡找，這類判決太少時才放寬到全部。
刑事判決沒有判決導讀，列表附司法院的原文網址。
"""
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

from backend import mock
from criminal.models import service as model_service
from retrieval import criminal as retrieval_criminal
from retrieval.engine import TfidfIndex

N_SHOWN = 10
N_CANDIDATES = 40         # 列表從這麼多件裡挑（要去掉摘要開頭相同的制式判決）
DUPLICATE_PREFIX = 40
MIN_SAME_CHARGE = 10      # 含這個罪名的判決少於這個數時，改在全部判決中找


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
            rows = self._query("SELECT charges FROM cases ORDER BY row")
            assert len(rows) == len(self.index), "刑事檢索索引和案件清單的件數不同，請重新執行 python -m retrieval.criminal"
            self.charges = [set(json.loads(r[0])) for r in rows]

    @property
    def mock(self) -> bool:
        return self.model is None

    def _query(self, sql: str, params=()) -> List[sqlite3.Row]:
        with closing(sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)) as con:
            con.row_factory = sqlite3.Row
            return con.execute(sql, params).fetchall()

    def report(self, text: str) -> Dict:
        if self.mock:
            return mock.criminal_report()
        charges = self.model.predict(text)
        return {"charges": charges, "similar": self.similar(text, charges[0]["name"] if charges else None),
                "mock": False}

    def search(self, text: str, k: int) -> List[Dict]:
        if self.mock:
            return mock.criminal_report()["similar"][:k]
        return self.similar(text, self.model.predict(text)[0]["name"], k)

    def similar(self, text: str, charge: Optional[str], n: int = N_SHOWN) -> List[Dict]:
        if self.index is None:
            return []
        sim = self.index.scores(model_service.normalize(text))
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
