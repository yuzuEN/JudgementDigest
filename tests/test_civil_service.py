# -*- coding: utf-8 -*-
"""
civil/models/service.py 與 retrieval/build.py 的離線測試：用合成的小資料訓練、存檔、讀回、預測，
確認後端拿到的模型和檢索資料長得對（真正的訓練要用文字資料集，不在這裡跑）。
"""

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from civil.models import service as S  # noqa: E402
from retrieval.build import write_artifacts  # noqa: E402
from retrieval.engine import TfidfIndex  # noqa: E402

WIN = ["被告駕車闖紅燈撞傷原告，原告受有骨折並住院治療，提出診斷證明為證",
       "被告借款五十萬元未還，原告提出借據與匯款紀錄",
       "被告未依約給付工程款，原告已完成工程並經驗收"]
LOSE = ["原告主張被告應負責但無任何證據可以證明",
        "原告請求返還款項但該款項係贈與並非借貸",
        "原告主張被告違約但契約已經合意解除"]


def synthetic(n=120, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        y = int(i % 2 == 0)
        rows.append({"id": i + 1, "text": (WIN if y else LOSE)[rng.integers(0, 3)] + f"，案號{i}",
                     "y": y, "fold": i % 5, "case_type_category": "侵權" if i % 3 else "契約",
                     "mid": "侵權：交通事故" if i % 3 else "契約：買賣",
                     "court": ["臺北", "臺中", "高雄"][i % 3], "court_s": ["臺北", "臺中", "高雄"][i % 3],
                     "plaintiff_has_lawyer": str(i % 2), "defendant_is_corp": str((i // 2) % 2)})
    return pd.DataFrame(rows)


class TestFeatures(unittest.TestCase):
    def test_unanswered_is_unknown(self):
        f = S.features_frame([{"mid": "侵權：交通事故"}])
        self.assertEqual(f.iloc[0].to_dict(), {"mid": "侵權：交通事故", "court": S.UNKNOWN,
                                               "plaintiff_has_lawyer": S.UNKNOWN, "defendant_is_corp": S.UNKNOWN})

    def test_flags(self):
        f = S.features_frame([{"plaintiff_has_lawyer": True, "defendant_is_corp": False},
                              {"plaintiff_has_lawyer": "1", "defendant_is_corp": "0"}])
        self.assertEqual(list(f.plaintiff_has_lawyer), ["1", "1"])
        self.assertEqual(list(f.defendant_is_corp), ["0", "0"])

    def test_unknown_courts_share(self):
        d = synthetic(1000)
        share = (S.with_unknown_courts(d).court == S.UNKNOWN).mean()
        self.assertAlmostEqual(share, S.COURT_UNKNOWN_SHARE, delta=0.05)
        self.assertFalse((d.court == S.UNKNOWN).any(), "不能改到原本的資料")


class TestModel(unittest.TestCase):
    def test_learns_and_predicts_probabilities(self):
        d = synthetic()
        m = S.ServiceModel().fit(d.text, d, d.y)
        p_win = m.predict_one(WIN[0], {"mid": "侵權：交通事故"})
        p_lose = m.predict_one(LOSE[0], {"mid": "侵權：交通事故"})
        self.assertGreater(p_win, p_lose)
        self.assertTrue(0 < p_lose < p_win < 1)

    def test_unseen_categories_do_not_crash(self):
        d = synthetic()
        m = S.ServiceModel().fit(d.text, d, d.y)
        p = m.predict_one("隨便寫一點", {"mid": "從來沒看過的案由", "court": "火星"})
        self.assertTrue(0 < p < 1)

    def test_text_only_and_features_only(self):
        d = synthetic()
        for t, f in ((True, False), (False, True)):
            p = S.ServiceModel(t, f).fit(d.text, d, d.y).predict_proba(d.text[:3], d[:3])
            self.assertEqual(p.shape, (3,))

    def test_calibration(self):
        y = np.array([0, 0, 1, 1])
        c = S.calibration(y, np.array([0.05, 0.05, 0.95, 0.95]))
        self.assertAlmostEqual(c["ece"], 0.05)
        self.assertEqual(sum(row["n"] for row in c["table"]), 4)

    def test_evaluate_reports_all_variants(self):
        r = S.evaluate(synthetic())
        self.assertEqual(set(r), {"只用原告主張", "原告主張＋特徵", "只用特徵",
                                  "原告主張＋特徵（法院不知道）", "原告主張＋特徵（都不知道）"})
        self.assertGreater(r["只用原告主張"]["auc"], 0.9)

    def test_train_save_load_roundtrip(self):
        d = synthetic()
        with tempfile.TemporaryDirectory() as tmp:
            out = S.train(d, "test", Path(tmp) / S.MODEL_NAME, {"x": {"auc": 0.5}})
            model, meta = S.load(out)
        self.assertEqual(meta["n_cases"], len(d))
        self.assertEqual(meta["features"], S.FEATURES)
        groups = {g["category"]: [m["value"] for m in g["mids"]] for g in meta["options"]["mid_groups"]}
        self.assertEqual(groups, {"侵權": ["侵權：交通事故"], "契約": ["契約：買賣"]})
        self.assertEqual(set(meta["options"]["courts"]), {"臺北", "臺中", "高雄"})
        self.assertTrue(0 < model.predict_one(WIN[1], {}) < 1)


class TestRetrievalArtifacts(unittest.TestCase):
    def test_write_artifacts(self):
        d = synthetic(30)
        corpus = pd.DataFrame({"id": d.id, "case_number": [f"臺灣臺北地方法院 113 年度訴字第 {i} 號" for i in d.id],
                               "court": "臺灣臺北地方法院", "year": "2024", "case_type_category": d.case_type_category,
                               "case_type_mid": d.mid, "outcome": np.where(d.y == 1, "一部勝訴一部敗訴", "敗訴"),
                               "y": d.y, "plaintiff_claim_text": "原告王小明主張" + d.text,
                               "claimed_amount": 100000, "awarded_amount": np.where(d.y == 1, 50000, 0),
                               "grant_ratio": np.where(d.y == 1, 0.5, 0.0)})
        sections = pd.DataFrame({"id": d.id, "plaintiff_claim_text": "原告王小明主張被告陳大華撞傷原告，提出診斷證明為證",
                                 "defendant_defense_text": "被告陳大華則以：原告亦與有過失等語",
                                 "court_reasoning_text": "一、本件爭點為被告有無過失。二、原告提出診斷證明為證。",
                                 "plaintiff": "王小明", "defendant": "陳大華", "plaintiff_agent": "", "defendant_agent": ""})
        with tempfile.TemporaryDirectory() as tmp:
            out = write_artifacts(corpus, sections, Path(tmp) / "r", "test")
            index = TfidfIndex.load(out / "index.joblib")
            self.assertEqual(len(index), 30)
            con = sqlite3.connect(out / "cases.sqlite")
            row = con.execute("SELECT evidence, defenses, summary FROM cases WHERE row = 0").fetchone()
            sec = con.execute("SELECT claim, defense FROM sections WHERE id = 1").fetchone()
            n = con.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
            con.close()
            meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
        self.assertEqual(n, 30)
        self.assertEqual(json.loads(row[0]), ["medical"])
        self.assertEqual(json.loads(row[1]), ["contributory"])
        self.assertNotIn("王小明", row[2])
        self.assertTrue(row[2].startswith("原告【原告】主張"))
        self.assertNotIn("陳大華", sec[0] + sec[1])
        self.assertEqual(meta["n_cases"], 30)


if __name__ == "__main__":
    unittest.main()
