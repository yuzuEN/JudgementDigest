# -*- coding: utf-8 -*-
"""民事被告端的答辯索引（retrieval/defense_index.py）與後端的合併相似度。"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.main import create_app  # noqa: E402
from backend.settings import Settings  # noqa: E402
from civil.insights import DEFENSE_MARKER  # noqa: E402
from civil.models import service  # noqa: E402
from retrieval import build, defense_index  # noqa: E402
from tests.test_civil_service import synthetic  # noqa: E402

CLAIM = "原告主張被告向原告借款五十萬元，屆期未清償，請求被告返還借款"
ADMIT = "被告則以：對於原告主張之借款事實不爭執，惟目前經濟困難，願意按月分期清償，請求酌減利息等語"
GIFT = "被告則以：否認兩造間有借貸合意，該筆款項係原告基於情誼所為之贈與，並非借款，原告之訴應予駁回等語"


def build_artifacts(base: Path) -> pd.DataFrame:
    """主張都一樣，只有答辯不同：勝訴的被告不爭執、敗訴的被告抗辯是贈與。"""
    d = synthetic(150)
    service.train(d, "test", service.artifact_dir(base), {})
    corpus = pd.DataFrame({
        "id": d.id, "case_number": [f"臺灣臺北地方法院 113 年度訴字第 {i} 號" for i in d.id],
        "court": "臺灣臺北地方法院", "year": "2024", "case_type_category": "契約", "case_type_mid": "民間借貸",
        "outcome": np.where(d.y == 1, "勝訴", "敗訴"), "y": d.y,
        "plaintiff_claim_text": [f"{CLAIM}，案號{i}" for i in d.id], "claimed_amount": 500000,
        "awarded_amount": np.where(d.y == 1, 500000, 0), "grant_ratio": np.where(d.y == 1, 1.0, 0.0)})
    sections = pd.DataFrame({
        "id": d.id, "plaintiff_claim_text": CLAIM, "defendant_defense_text": np.where(d.y == 1, ADMIT, GIFT),
        "court_reasoning_text": "一、本件爭點為兩造間有無借貸合意。", "plaintiff": "王小明", "defendant": "陳大華",
        "plaintiff_agent": "", "defendant_agent": ""})
    build.write_artifacts(corpus, sections, build.artifact_dir(base), "test")
    return d


class TestBuild(unittest.TestCase):
    def test_rows_follow_the_claim_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            d = build_artifacts(base)
            out = defense_index.build(build.artifact_dir(base), defense_index.artifact_dir(base))
            meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
            self.assertEqual(meta["n_cases"], len(d))
            self.assertTrue(defense_index.matches(meta, build.artifact_dir(base), len(d)))
            self.assertFalse(defense_index.matches({**meta, "retrieval_built_at": "舊的"}, build.artifact_dir(base), len(d)))

    def test_clean_defense_drops_mask_tags(self):
        self.assertEqual(defense_index.clean_defense("被告【被告1】則以： 否認"), "被告則以：否認")


class TestBackend(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.base = base = Path(cls.tmp.name)
        build_artifacts(base)
        defense_index.build(build.artifact_dir(base), defense_index.artifact_dir(base))
        cls.client = TestClient(create_app(Settings(artifacts_dir=base)))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def report(self, text, role="defendant"):
        r = self.client.post("/api/civil/report", json={"role": role, "mid": "民間借貸", "text": text})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_health(self):
        self.assertTrue(self.client.get("/api/health").json()["defense_search"])

    def test_defense_pulls_in_cases_with_the_same_defense(self):
        claim = CLAIM * 3
        gift = self.report(f"{claim}\n{DEFENSE_MARKER}\n我否認有借錢，那筆錢是他送我的贈與，並非借款")
        admit = self.report(f"{claim}\n{DEFENSE_MARKER}\n我對借款的事實不爭執，願意分期還")
        self.assertTrue(gift["search_scope"]["defense_used"])
        self.assertGreater(gift["outcomes"]["lose"], admit["outcomes"]["lose"], "答辯相近的判決要排到前面")
        self.assertTrue(all(c["outcome"] == "敗訴" for c in gift["similar"][:3]))

    def test_without_defense_only_the_claim_is_used(self):
        r = self.report(CLAIM * 3)
        self.assertFalse(r["search_scope"]["defense_used"])
        plaintiff = self.report(f"{CLAIM * 3}\n{DEFENSE_MARKER}\n那筆錢是贈與", role="plaintiff")
        self.assertFalse(plaintiff["search_scope"]["defense_used"], "原告不用答辯索引")


class TestMismatchedIndex(unittest.TestCase):
    def test_index_from_another_build_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            build_artifacts(base)
            out = defense_index.build(build.artifact_dir(base), defense_index.artifact_dir(base))
            meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
            (out / "meta.json").write_text(json.dumps({**meta, "retrieval_built_at": "舊的"}), encoding="utf-8")
            client = TestClient(create_app(Settings(artifacts_dir=base)))
            self.assertFalse(client.get("/api/health").json()["defense_search"])


if __name__ == "__main__":
    unittest.main()
