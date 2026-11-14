"""
民事：勝訴機率、相似判決、金額範圍、證據對照、常見抗辯、判決導讀。

模型（artifacts/civil_winloss_v1）與檢索資料（artifacts/retrieval_civil_v4）在啟動時讀進記憶體；
任一個不存在時整個民事改回傳示例資料（mock = true），伺服器照樣能啟動，前端照樣能走完流程。

獲償比例模型（artifacts/civil_amount_v1）是選用的：有的話金額範圍用模型推估（若為一部勝訴），
沒有、讀不出來、或這次不適合用模型時（見 _use_amount_model），退回相似判決的分位數（和沒有這個模型之前相同）。
"""
import json
import logging
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from backend import mock
from backend.quality import looks_like_dispute, win_signal
from civil.dataset.text import prepare_input
from civil.insights import (EVIDENCE, QUESTIONNAIRE_EVIDENCE, amount_fields, amount_range, outcome_counts, user_evidence, without_questions, defense_table, evidence_table,
                            guide_paragraphs, GUIDE_LABELER)
from civil.models import amount_service
from civil.models import service as model_service
from retrieval import build as retrieval_build
from retrieval.engine import TfidfIndex

logger = logging.getLogger(__name__)

SHORT_TEXT = 150          # 描述少於這個字數時提醒：測試資料只給前 150 字時，勝訴 recall 從 0.81 降到 0.64
N_NEIGHBORS = 30          # 相似判決統計（證據、抗辯、金額）用的件數，只算對審
N_SHOWN = 10              # 頁面上列出的相似判決
N_CANDIDATES = 60         # 列表從這麼多件裡挑（要去重、限制一造辯論的件數）
MAX_DEFAULT_SHOWN = 3     # 列表裡一造辯論的上限
DUPLICATE_PREFIX = 40     # 摘要開頭這麼多字相同，視為同一種制式案件
MID_VOTE = 0.4            # 沒選糾紛類型時，相似判決的案由投票超過這個比例才採用：口語測試 23 件對 21 件，全部都用只對 47%
MIN_SAME_MID = 10         # 同案由的判決少於這個數時，改在全部案件中找
MIN_AMOUNT_MODEL_CASES = 30   # 獲償比例模型在這個案由的訓練件數少於這個數就不用（16 類、共 113 件；例如債務人異議 11 件）


class CivilService:
    def __init__(self, artifacts_dir: Path, force_mock: bool = False):
        self.model = self.meta = self.index = None
        self.amount_model = self.amount_meta = None
        self.db_path: Optional[Path] = None
        if force_mock:
            return
        model_dir = model_service.artifact_dir(artifacts_dir)
        retrieval_dir = retrieval_build.artifact_dir(artifacts_dir)
        if (model_dir / "model.joblib").exists() and (retrieval_dir / "index.joblib").exists():
            self.model, self.meta = model_service.load(model_dir)
            self.index = TfidfIndex.load(retrieval_dir / "index.joblib")
            self.db_path = retrieval_dir / "cases.sqlite"
            rows = self._query("SELECT mid, y, grant_ratio, evidence, defenses, in_stats, default_judgment, outcome "
                               "FROM cases ORDER BY row")
            assert len(rows) == len(self.index), "檢索索引和案件清單的件數不同，請重新執行 python -m retrieval.build"
            self.mids = np.array([r[0] or "" for r in rows])
            self.y = np.array([r[1] for r in rows])
            self.grant_ratio = np.array([np.nan if r[2] is None else r[2] for r in rows], dtype=float)
            self.case_evidence = [json.loads(r[3]) for r in rows]
            self.case_defenses = [json.loads(r[4]) for r in rows]
            self.in_stats = np.array([bool(r[5]) for r in rows])
            self.default = np.array([bool(r[6]) for r in rows])
            self.outcomes = [r[7] for r in rows]
            self._load_amount_model(artifacts_dir)

    def _load_amount_model(self, artifacts_dir: Path) -> None:
        """獲償比例模型是選用的：沒有、或讀不出來（例如 scikit-learn 版本不同）都退回相似判決，不影響其他功能。"""
        path = amount_service.artifact_dir(artifacts_dir)
        if not (path / "model.joblib").exists():
            return
        try:
            self.amount_model, self.amount_meta = amount_service.load(path)
        except amount_service.StaleModel as e:
            logger.warning("獲償比例模型 %s 不能用：%s；金額範圍改用相似判決的分位數", path, e)
            self.amount_model = self.amount_meta = None
        except Exception:
            logger.warning("獲償比例模型 %s 讀取失敗，金額範圍改用相似判決的分位數", path, exc_info=True)
            self.amount_model = self.amount_meta = None

    @property
    def amount_source(self) -> str:
        """/health 用：金額範圍目前用模型還是相似判決。"""
        if self.mock:
            return "mock"
        return "model" if self.amount_model is not None else "similar"

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
        return {"name": self.meta["name"], "description": self.meta["description"], "ece": m.get("ece"),
                **{k: m.get(k) for k in ("win_precision", "win_recall", "lose_precision", "lose_recall")}}

    @staticmethod
    def answers(req) -> Dict:
        corp = None if req.defendant_type is None else req.defendant_type in ("company", "government")
        return {"mid": req.mid, "court": req.court, "plaintiff_has_lawyer": req.plaintiff_has_lawyer,
                "defendant_is_corp": corp}

    def _infer_mid(self, sim: np.ndarray) -> Tuple[Optional[str], List[str]]:
        """使用者沒選糾紛類型時，用最相似的對審判決投票。回傳（有把握的案由, 可能的案由）。"""
        rows, sims = self.index.top(sim, N_NEIGHBORS, ~self.default)
        votes: Dict[str, float] = {}
        for row, s in zip(rows, sims):
            votes[self.mids[row]] = votes.get(self.mids[row], 0.0) + float(s)
        ranked = sorted(votes, key=lambda m: -votes[m])
        ranked = [m for m in ranked if m and m != "其他"]
        total = sum(votes.values())
        if not ranked or total <= 0:
            return None, []
        return (ranked[0] if votes[ranked[0]] / total >= MID_VOTE else None), ranked[:3]

    def _resolve_mid(self, req, sim: np.ndarray) -> Tuple[Optional[str], Optional[str]]:
        """回傳（要用的案由, 給使用者的提醒）。"""
        if req.mid:
            return req.mid, None
        if not looks_like_dispute(req.text):
            return None, "沒有選擇糾紛類型，相似判決會在全部案件中找。"
        mid, likely = self._infer_mid(sim)
        if mid:
            return mid, f"沒有選擇糾紛類型，系統判斷比較接近「{mid}」。如果不對，請回上一步選擇。"
        hint = f"比較接近的有：{'、'.join(likely)}。" if likely else ""
        return None, f"沒有選擇糾紛類型，相似判決會在全部案件中找。{hint}回上一步選擇，結果會比較準。"

    def warnings(self, req, mid_note: Optional[str] = None) -> List[str]:
        out = []
        if not looks_like_dispute(req.text):
            out.append("這段描述看起來不像法律糾紛，下面的結果可能沒有參考價值。請寫下發生了什麼事、你想要對方做什麼。")
        if len(prepare_input(req.text)) < SHORT_TEXT:
            out.append(f"描述少於 {SHORT_TEXT} 字，結果可能比較不準；補充經過、損害與對方的說法會更可靠。")
        if mid_note:
            out.append(mid_note)
        return out

    def _similarity(self, req) -> np.ndarray:
        """使用者確認過的改寫只用來搜尋；勝訴機率仍用原本的描述（口語測試中改寫沒有提高判斷力）。"""
        return self.index.scores(prepare_input(without_questions(req.search_text or req.text)))

    def predict(self, req) -> Dict:
        if self.mock:
            return mock.civil_report(req.text, req.claimed_amount, req.evidence)["prediction"]
        text = without_questions(req.text)
        sim = self._similarity(req)
        mid, note = self._resolve_mid(req, sim)
        p = self.model.predict_one(text, {**self.answers(req), "mid": mid})
        return {"win_probability": round(p, 4), "signal": win_signal(p, text), "model": self._model_info(),
                "warnings": self.warnings(req, note),
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
                "default_judgment": bool(r["default_judgment"]),
                # 11/13 以前建的檢索資料沒有 url 欄，照樣能用，只是不顯示原文連結
                "url": (r["url"] or None) if "url" in r.keys() else None}

    def search(self, text: str, mid: Optional[str], k: int) -> List[Dict]:
        if self.mock:
            return mock.civil_cases(mid)[:k]
        return self._listed(self.index.scores(prepare_input(text)), mid, k)

    # ── 完整的參考結果 ──
    def report(self, req) -> Dict:
        if self.mock:
            return mock.civil_report(req.text, req.claimed_amount, req.evidence)
        prediction = self.predict(req)
        sim = self._similarity(req)
        # 統計只用對審、有被告答辯的案件；一造辯論只出現在列表（見 retrieval/civil.py）
        mid, _ = self._resolve_mid(req, sim)
        rows, _ = self.index.top(sim, N_NEIGHBORS, self._allowed(mid, self.in_stats))
        winners = [r for r in rows if self.y[r] == 1]
        similar_range = amount_range(self.grant_ratio[winners], req.claimed_amount)
        if similar_range:
            similar_range = {"source": "similar", "scope": "win", **similar_range}
        # 相似的勝訴判決裡有幾件是全部勝訴：模型只回答「若為一部勝訴」，全勝多的案由要讓使用者知道
        full_wins = {"n_wins": len(winners), "n_full_wins": sum(self.outcomes[r] in ("勝訴", "確認勝訴") for r in winners)}
        amount = self._amount_range(req, mid, similar_range)
        return {
            "prediction": prediction,
            "amount_range": {**amount, **full_wins} if amount else None,
            "similar": self._listed(sim, mid, N_SHOWN),
            "evidence": evidence_table([self.case_evidence[r] for r in winners], user_evidence(req.text, req.evidence)),
            "defenses": defense_table([self.case_defenses[r] for r in rows]),
            "outcomes": outcome_counts([self.outcomes[r] for r in rows]),
            # 被告未到庭的判決不算進比例，但要讓使用者知道有多少：看不分層的前 N_NEIGHBORS 件
            "default_cases": int(self.default[self.index.top(sim, N_NEIGHBORS, self._allowed(mid))[0]].sum()),
            "n_compared": int(len(rows)),
            "mock": False,
        }

    def _use_amount_model(self, req) -> bool:
        """
        什麼時候用獲償比例模型（其他時候用相似判決的分位數）：
        - 使用者自己選了單一個案由（系統猜的不算：沒選案由時模型的中位數會偏很多）
        - 法院、請求金額至少填了一項（兩者都沒填時，評估裡模型比相似判決差：MAE +0.007）
        - 這個案由的訓練件數夠（MIN_AMOUNT_MODEL_CASES）
        """
        return (self.amount_model is not None and bool(req.mid) and bool(req.court or req.claimed_amount)
                and amount_service.usable_for(self.amount_meta, req.mid, MIN_AMOUNT_MODEL_CASES))

    def _amount_range(self, req, mid: Optional[str], similar: Optional[Dict]) -> Optional[Dict]:
        """
        用模型時：範圍是「若為一部勝訴」的模型推估；相似判決的分布（件數與 buckets）留著當佐證，但不是範圍的依據。
        不用模型時：就是相似的勝訴判決的分位數。描述看不出是糾紛時兩種都不給（空白描述也會算出一個範圍，沒有意義）。
        """
        if not looks_like_dispute(req.text):
            return None
        if not self._use_amount_model(req):
            return similar
        try:
            r = self.amount_model.predict_one(without_questions(req.text), {**self.answers(req), "mid": mid},
                                              req.claimed_amount)
        except Exception:
            # 金額模型出錯不能拖垮整個結果頁（勝訴機率、相似判決都還要顯示）
            logger.warning("獲償比例模型預測失敗，這次改用相似判決的分位數", exc_info=True)
            return similar
        return {"source": "model", "scope": "partial_win",
                "n_cases": similar["n_cases"] if similar else None,
                "ratio_low": r["ratio_low"], "ratio_median": r["ratio_median"], "ratio_high": r["ratio_high"],
                "coverage": r["coverage"],
                **amount_fields(r["ratio_low"], r["ratio_median"], r["ratio_high"], req.claimed_amount),
                "buckets": similar["buckets"] if similar else []}

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
