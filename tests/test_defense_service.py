# -*- coding: utf-8 -*-
"""民事被告端：被告端模型（civil/models/defense_service.py）、答辯的切分與抗辯表，以及後端的被告路徑。"""

import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.civil_service import DEFENSE_FALLBACK_NOTE  # noqa: E402
from backend.main import create_app  # noqa: E402
from backend.settings import Settings  # noqa: E402
from civil.insights import DEFENSE_MARKER, defense_table, split_defense, user_defense_types  # noqa: E402
from civil.models import defense_service as D  # noqa: E402
from tests.test_backend import build_artifacts  # noqa: E402
from tests.test_civil_service import WIN  # noqa: E402

CLAIM = "原告主張被告駕車撞傷原告，請求賠償醫療費用與工作損失"
ADMIT = ["被告對於原告主張之事實不爭執", "被告承認有撞傷原告", "被告對於請求金額沒有意見"]
DENY = ["被告否認有撞到原告，原告無法證明", "被告已經全部清償並和解，提出收據", "被告主張請求權已罹於時效"]


def defense_frame(n=150, seed=0) -> pd.DataFrame:
    """勝負只由答辯決定：被告承認時原告勝訴、否認或已清償時原告敗訴。"""
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        y = int(i % 2 == 0)
        rows.append({"id": i + 1, "claim": f"{CLAIM}，案號{i}", "defense": (ADMIT if y else DENY)[rng.integers(0, 3)],
                     "y": y, "fold": i % 5, "case_type_category": "侵權", "mid": "侵權：交通事故",
                     "court": ["臺北", "臺中", "高雄"][i % 3], "court_s": ["臺北", "臺中", "高雄"][i % 3],
                     "defendant_has_lawyer": str(i % 2), "defendant_is_corp": str((i // 2) % 2)})
    return pd.DataFrame(rows)


class TestSplitDefense(unittest.TestCase):
    def test_split(self):
        self.assertEqual(split_defense(f"對方說我欠錢\n{DEFENSE_MARKER}\n我已經還了"), ("對方說我欠錢", "我已經還了"))
        self.assertEqual(split_defense("沒有答辯"), ("沒有答辯", ""))
        self.assertEqual(split_defense(""), ("", ""))


class TestUserDefenseTypes(unittest.TestCase):
    def test_colloquial_defenses(self):
        found = user_defense_types("是對方闖紅燈；看護費一天三千元太高，而且我已經付過十萬元。")
        self.assertEqual(found, ["contributory", "excessive", "paid"])

    def test_negated_is_not_counted(self):
        self.assertEqual(user_defense_types("我沒有付過任何錢"), [])
        self.assertEqual(user_defense_types("我沒有錯"), ["no_fault"])


class TestDefenseTable(unittest.TestCase):
    def test_lose_share_and_user_mentions(self):
        neighbors = [["contributory"]] * 6 + [["excessive"]] * 2 + [[]] * 2
        wins = [1, 1, 0, 0, 0, 0] + [1, 1] + [1, 1]
        rows = defense_table(neighbors, top=1, wins=wins, user_has=["excessive"])
        self.assertEqual([r["key"] for r in rows], ["contributory", "excessive"], "自己提到的說法不在前幾名也要列")
        self.assertAlmostEqual(rows[0]["lose_share"], 4 / 6)
        self.assertEqual(rows[0]["n_raised"], 6)
        self.assertIsNone(rows[1]["lose_share"], "件數太少不算比例")
        self.assertTrue(rows[1]["user_has"])

    def test_plaintiff_default_is_unchanged(self):
        rows = defense_table([["contributory"], []])
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["lose_share"])
        self.assertFalse(rows[0]["user_has"])


class TestDefenseModel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        d = defense_frame()
        cls.model = D.DefenseModel().fit(d.claim, d.defense, d, d.y)

    def test_defense_text_moves_the_probability(self):
        admit = self.model.predict_one(CLAIM, ADMIT[0], {})
        deny = self.model.predict_one(CLAIM, DENY[0], {})
        self.assertGreater(admit, deny)

    def test_works_without_defense_and_answers(self):
        p = self.model.predict_one(CLAIM, "", {})
        self.assertTrue(0 <= p <= 1)

    def test_features_frame(self):
        f = D.features_frame([{"defendant_has_lawyer": True}])
        self.assertEqual(f.iloc[0].to_dict(), {"mid": D.UNKNOWN, "court": D.UNKNOWN,
                                               "defendant_has_lawyer": "1", "defendant_is_corp": D.UNKNOWN})

    def test_augment_blanks_some_defenses(self):
        d = D.augment(defense_frame(400))
        share = (d.defense == "").mean()
        self.assertTrue(0.2 < share < 0.4, share)


class TestBackendDefendant(unittest.TestCase):
    """artifacts 裡多了被告端模型：role = defendant 時用它，主張＋答辯一起看。"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        base = Path(cls.tmp.name)
        build_artifacts(base)
        D.train(defense_frame(), "test", D.artifact_dir(base), {D.MAIN: {"win_precision": 0.7, "ece": 0.02}})
        cls.client = TestClient(create_app(Settings(artifacts_dir=base)))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def report(self, **body):
        r = self.client.post("/api/civil/report", json={"mid": "侵權：交通事故", **body})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_health(self):
        self.assertEqual(self.client.get("/api/health").json()["defense"], "model")

    def test_defendant_uses_the_defense_model_and_the_defense_text(self):
        claim = WIN[0] * 5
        admit = self.report(role="defendant", text=f"{claim}\n{DEFENSE_MARKER}\n{ADMIT[0]}")
        deny = self.report(role="defendant", text=f"{claim}\n{DEFENSE_MARKER}\n{DENY[1]}，而且原告也與有過失")
        self.assertEqual(admit["role"], "defendant")
        self.assertEqual(admit["prediction"]["model"]["name"], D.MODEL_NAME)
        self.assertGreater(admit["prediction"]["win_probability"], deny["prediction"]["win_probability"])
        self.assertNotIn(DEFENSE_FALLBACK_NOTE, admit["prediction"]["warnings"])
        # 自己提到的說法標出來；相似判決用主張找，和沒寫答辯時一樣
        self.assertIn("contributory", [d["key"] for d in deny["defenses"] if d["user_has"]])
        self.assertEqual([c["case_id"] for c in admit["similar"]], [c["case_id"] for c in deny["similar"]])

    def test_plaintiff_is_unchanged(self):
        r = self.report(text=WIN[0] * 5)
        self.assertEqual(r["role"], "plaintiff")
        self.assertEqual(r["prediction"]["model"]["name"], "civil_winloss_v1")

    def test_defendant_followup_asks_about_your_side(self):
        r = self.client.post("/api/intake/followup", json={"case_type": "civil", "role": "defendant", "text": ""}).json()
        self.assertIn("dispute", [q["id"] for q in r["questions"]])
        plaintiff = self.client.post("/api/intake/followup", json={"case_type": "civil", "text": ""}).json()
        self.assertNotIn("dispute", [q["id"] for q in plaintiff["questions"]])


class TestBackendDefendantWithoutModel(unittest.TestCase):
    """沒有被告端模型：被告的查詢改用原告端模型（只看主張），並提醒使用者。"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        build_artifacts(Path(cls.tmp.name))
        cls.client = TestClient(create_app(Settings(artifacts_dir=Path(cls.tmp.name))))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_falls_back_to_the_plaintiff_model(self):
        self.assertEqual(self.client.get("/api/health").json()["defense"], "fallback")
        r = self.client.post("/api/civil/report", json={"role": "defendant", "mid": "侵權：交通事故",
                                                        "text": f"{WIN[0] * 5}\n{DEFENSE_MARKER}\n{ADMIT[0]}"}).json()
        self.assertEqual(r["prediction"]["model"]["name"], "civil_winloss_v1")
        self.assertIn(DEFENSE_FALLBACK_NOTE, r["prediction"]["warnings"])


if __name__ == "__main__":
    unittest.main()
