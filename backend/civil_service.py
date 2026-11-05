"""
民事：勝訴機率、相似判決、金額範圍、證據對照、常見抗辯、判決導讀。

模型（artifacts/civil_winloss_v1）與檢索資料（artifacts/retrieval_civil_v1）在啟動時讀進記憶體；
任一個不存在時整個民事改回傳示例資料（mock = true），伺服器照樣能啟動，前端照樣能走完流程。
"""
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

from backend import mock
from civil.dataset.text import prepare_input
from civil.insights import (EVIDENCE, QUESTIONNAIRE_EVIDENCE, amount_range, defense_table, evidence_table,
                            guide_paragraphs, GUIDE_LABELER)
from civil.models import service as model_service
from retrieval import build as retrieval_build
from retrieval.engine import TfidfIndex

SHORT_TEXT = 150          # 描述少於這個字數時提醒：測試資料中 150 字時 AUC 從 0.769 降到 0.692
N_NEIGHBORS = 30          # 相似判決統計（證據、抗辯、金額）用的件數，只算對審
N_SHOWN = 10              # 頁面上列出的相似判決
N_CANDIDATES = 60         # 列表從這麼多件裡挑（要去重、限制一造辯論的件數）
MAX_DEFAULT_SHOWN = 3     # 列表裡一造辯論的上限
DUPLICATE_PREFIX = 40     # 摘要開頭這麼多字相同，視為同一種制式案件
MIN_SAME_MID = 10         # 同案由的判決少於這個數時，改在全部案件中找


class CivilService:
    def __init__(self, artifacts_dir: Path, force_mock: bool = False):
        self.model = self.meta = self.index = None
        self.db_path: Optional[Path] = None
        if force_mock:
            return
        model_dir = model_service.artifact_dir(artifacts_dir)
        retrieval_dir = retrieval_build.artifact_dir(artifacts_dir)
        if (model_dir / "model.joblib").exists() and (retrieval_dir / "index.joblib").exists():
            self.model, self.meta = model_service.load(model_dir)
            self.index = TfidfIndex.load(retrieval_dir / "index.joblib")
            self.db_path = retrieval_dir / "cases.sqlite"
            rows = self._query("SELECT mid, y, grant_ratio, evidence, defenses, in_stats, default_judgment "
                               "FROM cases ORDER BY row")
            assert len(rows) == len(self.index), "檢索索引和案件清單的件數不同，請重新執行 python -m retrieval.build"
            self.mids = np.array([r[0] or "" for r in rows])
            self.y = np.array([r[1] for r in rows])
            self.grant_ratio = np.array([np.nan if r[2] is None else r[2] for r in rows], dtype=float)
            self.case_evidence = [json.loads(r[3]) for r in rows]
            self.case_defenses = [json.loads(r[4]) for r in rows]
            self.in_stats = np.array([bool(r[5]) for r in rows])
            self.default = np.array([bool(r[6]) for r in rows])

    @property
    def mock(self) -> bool:
        return self.model is None

    def _query(self, sql: str, params=()) -> List[sqlite3.Row]:
        # 每次查詢開一條唯讀連線、查完就關：FastAPI 的同步端點跑在執行緒池裡，sqlite 連線不能跨執行緒共用；
        # 留著不關的話，Windows 上資料庫檔會一直被鎖住，重建檢索資料時刪不掉
        with closing(sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)) as con:
            con.row_factory = sqlite3.Row
            return con.execute(sql, params).fetchall()

    # ── 問卷選項 ──
    def options(self) -> Dict:
        source = mock.MOCK_OPTIONS if self.mock else self.meta["options"]
        return {**source, "evidence": [{"key": k, "label": label} for k, label, _ in EVIDENCE
                                       if k in QUESTIONNAIRE_EVIDENCE], "mock": self.mock}

    # ── 勝訴機率 ──
    def _model_info(self) -> Dict:
        if self.mock:
            return {"name": "mock", "description": "示例資料（伺服器上沒有模型檔）"}
        m = self.meta.get("metrics", {}).get("原告主張＋特徵", {})
        return {"name": self.meta["name"], "description": self.meta["description"],
                "auc": m.get("auc"), "ece": m.get("ece")}

    @staticmethod
    def answers(req) -> Dict:
        corp = None if req.defendant_type is None else req.defendant_type in ("company", "government")
        return {"mid": req.mid, "court": req.court, "plaintiff_has_lawyer": req.plaintiff_has_lawyer,
                "defendant_is_corp": corp}

    def warnings(self, req) -> List[str]:
        out = []
        if len(prepare_input(req.text)) < SHORT_TEXT:
            out.append(f"描述少於 {SHORT_TEXT} 字，結果可能比較不準；補充經過、損害與對方的說法會更可靠。")
        if not req.mid:
            out.append("沒有選擇糾紛類型，相似判決會在全部案件中找。")
        return out

    def predict(self, req) -> Dict:
        if self.mock:
            return mock.civil_report(req.text, req.claimed_amount, req.evidence)["prediction"]
        p = self.model.predict_one(req.text, self.answers(req))
        return {"win_probability": round(p, 4), "model": self._model_info(), "warnings": self.warnings(req),
                "mock": False}

    # ── 相似判決 ──
    def _allowed(self, mid: Optional[str], tier: Optional[np.ndarray] = None) -> Optional[np.ndarray]:
        """tier 裡同案由的案件；同案由太少時不限案由。"""
        same = None if not mid else (self.mids == mid if tier is None else (self.mids == mid) & tier)
        return same if same is not None and same.sum() >= MIN_SAME_MID else tier

    def _listed(self, sim: np.ndarray, mid: Optional[str], n: int) -> List[Dict]:
        """候選是全部案件和對審案件各取前幾名：金融類的制式一造辯論很多，只取全部的話對審會被擠出去。"""
        allowed = self._allowed(mid)
        contested = ~self.default if allowed is None else allowed & ~self.default
        k = max(N_CANDIDATES, n * 6)
        rows = np.union1d(self.index.top(sim, k, allowed)[0], self.index.top(sim, k, contested)[0])
        rows = rows[np.argsort(-sim[rows], kind="stable")]
        return self._shortlist(rows, sim[rows], n)

    def _shortlist(self, rows, sims, n: int) -> List[Dict]:
        """
        給人看的列表：去掉內容幾乎相同的判決（銀行、電信的制式起訴），一造辯論最多 MAX_DEFAULT_SHOWN 件。
        被告沒到庭的案件原告幾乎都贏，放太多會讓人以為這類糾紛都會贏；對審的不夠時才用多的一造辯論補滿。
        """
        picked, spare, seen, defaults = [], [], set(), 0
        for case in self._cases(rows, sims):
            key = case["summary"][:DUPLICATE_PREFIX]
            if key in seen:
                continue
            seen.add(key)
            if case["default_judgment"] and defaults >= MAX_DEFAULT_SHOWN:
                spare.append(case)
                continue
            defaults += case["default_judgment"]
            picked.append(case)
        picked = picked[:n]
        if len(picked) < n:
            picked = sorted(picked + spare[:n - len(picked)], key=lambda c: -c["similarity"])
        return picked

    def _cases(self, rows, sims) -> List[Dict]:
        if len(rows) == 0:
            return []
        marks = ",".join("?" * len(rows))
        found = {r["row"]: r for r in self._query(f"SELECT * FROM cases WHERE row IN ({marks})",
                                                  [int(x) for x in rows])}
        return [self._case(found[int(row)], float(sim)) for row, sim in zip(rows, sims)]

    @staticmethod
    def _case(r, similarity: float) -> Dict:
        return {"source": "civil", "case_id": r["id"], "case_number": r["case_number"], "court": r["court"],
                "year": r["year"], "mid": r["mid"] or "", "outcome": r["outcome"], "similarity": round(similarity, 3),
                "summary": r["summary"], "claimed_amount": r["claimed_amount"], "awarded_amount": r["awarded_amount"],
                "default_judgment": bool(r["default_judgment"])}

    def search(self, text: str, mid: Optional[str], k: int) -> List[Dict]:
        if self.mock:
            return mock.civil_cases(mid)[:k]
        return self._listed(self.index.scores(prepare_input(text)), mid, k)

    # ── 完整的參考結果 ──
    def report(self, req) -> Dict:
        if self.mock:
            return mock.civil_report(req.text, req.claimed_amount, req.evidence)
        prediction = self.predict(req)
        sim = self.index.scores(prepare_input(req.text))
        # 統計只用對審、有被告答辯的案件；一造辯論只出現在列表（見 retrieval/civil.py）
        rows, _ = self.index.top(sim, N_NEIGHBORS, self._allowed(req.mid, self.in_stats))
        winners = [r for r in rows if self.y[r] == 1]
        return {
            "prediction": prediction,
            "amount_range": amount_range(self.grant_ratio[winners], req.claimed_amount),
            "similar": self._listed(sim, req.mid, N_SHOWN),
            "evidence": evidence_table([self.case_evidence[r] for r in winners], req.evidence),
            "defenses": defense_table([self.case_defenses[r] for r in rows]),
            "n_compared": int(len(rows)),
            "mock": False,
        }

    # ── 判決導讀 ──
    def guide(self, case_id: int) -> Optional[Dict]:
        if self.mock:
            cases = {c["case_id"]: c for c in mock.civil_cases()}
            return mock.guide(cases[case_id]) if case_id in cases else None
        found = self._query("SELECT * FROM cases WHERE id = ?", (case_id,))
        if not found:
            return None
        r = found[0]
        s = self._query("SELECT claim, defense, court FROM sections WHERE id = ?", (case_id,))[0]
        return {"case": self._case(r, 0.0), "paragraphs": guide_paragraphs(s["claim"], s["defense"], s["court"]),
                "labeler": GUIDE_LABELER, "mock": False}
