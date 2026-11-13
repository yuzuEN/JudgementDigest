# -*- coding: utf-8 -*-
"""
civil/models/service.py 與 retrieval/build.py 的離線測試：用合成的小資料訓練、存檔、讀回、預測，
確認後端拿到的模型和檢索資料長得對（真正的訓練要用文字資料集，不在這裡跑）。
"""

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from civil.models import service as S  # noqa: E402
from retrieval.build import build_civil, provenance, write_artifacts  # noqa: E402
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

    def test_outcome_counts(self):
        from civil.insights import outcome_counts
        r = outcome_counts(["勝訴", "確認勝訴", "一部勝訴一部敗訴", "敗訴"])
        self.assertEqual(r, {"total": 4, "win": 2, "partial": 1, "lose": 1})

    def test_win_signal(self):
        from backend.quality import win_signal
        text = "我騎機車被右轉汽車撞到受傷，想請求賠償五十萬元，對方保險公司只願意賠十萬元，雙方一直談不攏，我手上有診斷證明。"
        self.assertEqual(win_signal(0.5, text), "strong")
        self.assertEqual(win_signal(0.49, text), "weak")
        self.assertEqual(win_signal(0.9, "被撞到"), "insufficient", "內容太少時不給強弱")
        self.assertEqual(win_signal(0.9, "今天天氣很好，我去公園散步，吃了牛肉麵，然後回家看電視，覺得今天過得很開心很放鬆，真的很不錯。"), "insufficient")

    def test_classification_scores_both_outcomes(self):
        r = S.classification([1, 1, 0, 0], [0.9, 0.2, 0.8, 0.1])
        self.assertEqual((r["win_precision"], r["win_recall"]), (0.5, 0.5))
        self.assertEqual((r["lose_precision"], r["lose_recall"]), (0.5, 0.5))
        self.assertEqual(r["accuracy"], 0.5)

    def test_classification_guessing_win_gets_no_credit_for_losses(self):
        r = S.classification([1, 0], [0.9, 0.9])
        self.assertEqual(r["win_recall"], 1.0)
        self.assertEqual(r["lose_recall"], 0.0)

    def test_evaluate_reports_all_variants(self):
        r = S.evaluate(synthetic())
        self.assertEqual(set(r), {"只用原告主張", "原告主張＋特徵", "只用特徵",
                                  "原告主張＋特徵（法院不知道）", "原告主張＋特徵（都不知道）"})
        self.assertGreater(r["只用原告主張"]["auc"], 0.9)
        self.assertGreater(r["只用原告主張"]["win_f1"], 0.8)
        self.assertGreater(r["只用原告主張"]["lose_f1"], 0.8)

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
        import sklearn
        self.assertEqual(meta["sklearn"], sklearn.__version__)
        self.assertIn("git_commit", meta)

    def test_load_warns_about_another_sklearn_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = S.train(synthetic(), "test", Path(tmp) / S.MODEL_NAME)
            meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
            (out / "meta.json").write_text(json.dumps({**meta, "sklearn": "0.0.1"}), encoding="utf-8")
            with self.assertLogs("config", "WARNING"):
                S.load(out)


class TestTrainFromCommandLine(unittest.TestCase):
    def test_model_trained_with_python_m_can_be_loaded(self):
        """REGRESSION：python -m 訓練時類別曾被記成 __main__.ServiceModel，後端讀模型檔就失敗。"""
        d = synthetic(60)
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            pd.DataFrame({"id": d.id, "case_type_category": d.case_type_category, "case_type_mid": d.mid, "y": d.y,
                          "fold": d.fold, "plaintiff_claim_text": d.text}).to_csv(base / "text_dataset_vt.csv", index=False)
            pd.DataFrame({"id": d.id, "court_s": d.court_s, "plaintiff_has_lawyer": d.plaintiff_has_lawyer.astype(int),
                          "defendant_is_corp": d.defendant_is_corp.astype(int)}).to_pickle(base / "fields.pkl")
            env = {**os.environ, "JD_DATASET_DIR": tmp, "JD_FIELDS_PKL": str(base / "fields.pkl"),
                   "JD_OUTPUT_DIR": tmp, "JD_ARTIFACTS_DIR": tmp, "PYTHONIOENCODING": "utf-8"}
            r = subprocess.run([sys.executable, "-m", "civil.models.service", "train", "--version", "vt"], env=env,
                               cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(r.returncode, 0, r.stderr)
            model, _ = S.load(S.artifact_dir(base))
        self.assertEqual(type(model).__module__, "civil.models.service")
        self.assertTrue(0 < model.predict_one(WIN[0], {}) < 1)


class TestRetrievalArtifacts(unittest.TestCase):
    def test_write_artifacts(self):
        d = synthetic(30)
        corpus = pd.DataFrame({"id": d.id, "case_number": [f"臺灣臺北地方法院 113 年度訴字第 {i} 號" for i in d.id],
                               "court": "臺灣臺北地方法院", "year": "2024", "case_type_category": d.case_type_category,
                               "case_type_mid": d.mid, "outcome": np.where(d.y == 1, "一部勝訴一部敗訴", "敗訴"),
                               "y": d.y, "plaintiff_claim_text": "原告王小明主張" + d.text,
                               "claimed_amount": 100000, "awarded_amount": np.where(d.y == 1, 50000, 0),
                               "grant_ratio": np.where(d.y == 1, 0.5, 0.0)})
        sections = pd.DataFrame({"id": d.id, "plaintiff_claim_text": "原告王小明主張被告陳大華撞傷原告，由簡建祥送醫，提出診斷證明為證",
                                 "defendant_defense_text": "被告陳大華則以：原告亦與有過失等語",
                                 "court_reasoning_text": "一、本件爭點為被告有無過失。二、原告提出診斷證明為證，證人簡建祥亦到庭。",
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
        self.assertNotIn("簡建祥", sec[0], "別的段落寫了稱謂，這段也要遮")
        self.assertEqual(meta["n_cases"], 30)
        self.assertEqual(meta["masking"], "規則")

    def test_write_artifacts_with_ner_names(self):
        """人名辨識找到、但沒有稱謂的名字也要遮；不像人名的結果不拿來取代。"""
        d = synthetic(30)
        corpus = pd.DataFrame({"id": d.id, "case_number": "第 1 號", "court": "臺北", "year": "2024",
                               "case_type_category": "侵權", "case_type_mid": d.mid, "outcome": "勝訴", "y": 1,
                               "plaintiff_claim_text": "原告主張李惠明於當日陳述" + d.text, "claimed_amount": 1,
                               "awarded_amount": 1, "grant_ratio": 1.0})
        sections = pd.DataFrame({"id": d.id, "plaintiff_claim_text": "李惠明於當日交付款項", "defendant_defense_text": "",
                                 "court_reasoning_text": "李惠明之陳述可採", "plaintiff": "", "defendant": "",
                                 "plaintiff_agent": "", "defendant_agent": ""})
        ner = {int(i): ["李惠明", "陳述"] for i in d.id}
        with tempfile.TemporaryDirectory() as tmp:
            out = write_artifacts(corpus, sections, Path(tmp) / "r", "test", ner_names=ner)
            con = sqlite3.connect(out / "cases.sqlite")
            summary = con.execute("SELECT summary FROM cases WHERE row = 0").fetchone()[0]
            claim, court = con.execute("SELECT claim, court FROM sections WHERE id = 1").fetchone()
            con.close()
            meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
        self.assertEqual(claim, "【關係人】於當日交付款項")
        self.assertEqual(court, "【關係人】之陳述可採")
        self.assertTrue(summary.startswith("原告主張【關係人】於當日陳述"))
        self.assertEqual(meta["masking"], "規則＋人名辨識（CKIP）")


class TestProvenance(unittest.TestCase):
    def test_build_writes_provenance_into_meta(self):
        d = synthetic(60)
        corpus = pd.DataFrame({"id": d.id, "case_number": "第 1 號", "court": "臺北", "year": "2024",
                               "case_type_category": "侵權", "case_type_mid": d.mid, "outcome": "勝訴", "y": 1,
                               "plaintiff_claim_text": d.text, "claimed_amount": 1, "awarded_amount": 1,
                               "grant_ratio": 1.0, "default_judgment": 0, "in_stats": 1})
        sections = pd.DataFrame({"id": d.id, "plaintiff_claim_text": "", "defendant_defense_text": "",
                                 "court_reasoning_text": "", "plaintiff": "", "defendant": "",
                                 "plaintiff_agent": "", "defendant_agent": ""})
        with tempfile.TemporaryDirectory() as tmp,                 mock.patch("retrieval.build.load_expanded", lambda: (corpus, sections)),                 mock.patch("retrieval.build.provenance", lambda db: {"rule_version": "9.9.9"}),                 mock.patch("builtins.print"):
            out = build_civil(Path(tmp) / "out")
            meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["rule_version"], "9.9.9")
        self.assertEqual((meta["n_cases"], meta["n_stats"], meta["n_default"]), (60, 60, 0))

    def test_records_where_the_data_came_from(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "judgments.db"
            con = sqlite3.connect(db)
            con.execute("CREATE TABLE judgments (id INTEGER)")
            con.executemany("INSERT INTO judgments VALUES (?)", [(1,), (2,)])
            con.commit()
            con.close()
            p = provenance(db)
        self.assertEqual(p["source_rows"], 2)
        self.assertRegex(p["rule_version"], r"^\d+\.\d+\.\d+$")
        self.assertIn("git_commit", p)
        self.assertIn("source_modified", p)


if __name__ == "__main__":
    unittest.main()
