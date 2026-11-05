# -*- coding: utf-8 -*-
"""
後端 API 的離線測試。兩種情況都要能用：
  1. 伺服器上沒有模型檔（CI、剛 clone 的組員）：民事回傳示例資料，流程照樣走得完
  2. 有模型檔：用合成資料訓練一個小模型、建一個小索引，走和正式環境相同的程式
"""

import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.civil_service import MAX_DEFAULT_SHOWN, CivilService  # noqa: E402
from backend.main import create_app  # noqa: E402
from backend.settings import Settings  # noqa: E402
from civil.models import service  # noqa: E402
from retrieval import build  # noqa: E402
from tests.test_civil_service import LOSE, WIN, synthetic  # noqa: E402

TRAFFIC = "去年三月我騎機車在路口直行，被右轉的汽車撞到，右手骨折住院五天，之後三個月沒辦法工作。" * 3


def build_artifacts(base: Path):
    d = synthetic(150)
    service.train(d, "test", service.artifact_dir(base), {"原告主張＋特徵": {"auc": 0.77, "ece": 0.01, "brier": 0.2}})
    corpus = pd.DataFrame({
        "id": d.id, "case_number": [f"臺灣臺北地方法院 113 年度訴字第 {i} 號" for i in d.id],
        "court": "臺灣臺北地方法院", "year": "2024", "case_type_category": d.case_type_category,
        "case_type_mid": d.mid, "outcome": np.where(d.y == 1, "一部勝訴一部敗訴", "敗訴"), "y": d.y,
        "plaintiff_claim_text": d.text, "claimed_amount": 100000,
        "awarded_amount": np.where(d.y == 1, 60000, 0), "grant_ratio": np.where(d.y == 1, 0.6, 0.0)})
    sections = pd.DataFrame({
        "id": d.id, "plaintiff_claim_text": "原告王小明主張被告陳大華駕車撞傷原告",
        "defendant_defense_text": "被告陳大華則以：原告亦與有過失，請求金額過高等語",
        # 只有勝訴的判決提到診斷證明：證據對照只看相似的「勝訴」判決，比例才會是 100%
        "court_reasoning_text": np.where(
            d.y == 1, "一、本件爭點為被告有無過失。二、原告提出診斷證明書為證，在卷可稽。三、綜上，原告之請求有理由。",
            "一、本件爭點為被告有無過失。二、原告未能舉證，難認可採。三、綜上，原告之請求無理由。"),
        "plaintiff": "王小明", "defendant": "陳大華", "plaintiff_agent": "", "defendant_agent": ""})
    build.write_artifacts(corpus, sections, build.artifact_dir(base), "test")


def listed(summary, similarity, default=False):
    return {"summary": summary, "similarity": similarity, "default_judgment": default}


class TestShortlist(unittest.TestCase):
    def shortlist(self, cases, n=10):
        svc = CivilService.__new__(CivilService)
        svc._cases = lambda rows, sims: cases
        return svc._shortlist([], [], n)

    def test_identical_templates_shown_once(self):
        same = "原告主張被告向原告申請信用卡使用，依約應按期繳款，詎被告未依約還款，尚欠本金及利息未清償" + "，"
        out = self.shortlist([listed(same + "甲", 0.9), listed(same + "乙", 0.8), listed("其他案件", 0.7)])
        self.assertEqual([c["similarity"] for c in out], [0.9, 0.7])

    def test_default_judgments_capped(self):
        cases = [listed(f"一造{i}", 0.9 - i / 100, True) for i in range(8)]
        cases += [listed(f"對審{i}", 0.5 - i / 100) for i in range(12)]
        out = self.shortlist(cases)
        self.assertEqual(len(out), 10)
        self.assertEqual(sum(c["default_judgment"] for c in out), MAX_DEFAULT_SHOWN)
        self.assertEqual([c["summary"] for c in out[:3]], ["一造0", "一造1", "一造2"])

    def test_filled_with_default_judgments_when_contested_run_out(self):
        cases = [listed(f"一造{i}", 0.9 - i / 100, True) for i in range(8)] + [listed("對審", 0.5)]
        out = self.shortlist(cases, n=6)
        self.assertEqual(len(out), 6)
        sims = [c["similarity"] for c in out]
        self.assertEqual(sims, sorted(sims, reverse=True), "補滿之後要照相似度排")

    def test_empty(self):
        self.assertEqual(self.shortlist([]), [])


class _MockCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.client = TestClient(create_app(Settings(artifacts_dir=Path(cls.tmp.name))))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()


class TestWithoutModel(_MockCase):
    def test_health(self):
        r = self.client.get("/api/health").json()
        self.assertEqual((r["status"], r["civil"], r["criminal"]), ("ok", "mock", "mock"))

    def test_options(self):
        r = self.client.get("/api/meta/options").json()
        self.assertTrue(r["mock"])
        self.assertEqual([e["key"] for e in r["evidence"]],
                         ["medical", "receipt", "transfer", "chat", "contract", "video"])
        self.assertTrue(r["mid_groups"] and r["courts"])

    def test_civil_report_is_marked_mock(self):
        r = self.client.post("/api/civil/report", json={"text": TRAFFIC, "claimed_amount": 500000,
                                                         "evidence": ["medical"]}).json()
        self.assertTrue(r["mock"] and r["prediction"]["mock"])
        self.assertEqual(r["amount_range"]["claimed"], 500000)
        self.assertTrue(next(e for e in r["evidence"] if e["key"] == "medical")["user_has"])
        self.assertTrue(all(c["case_number"].startswith("臺灣○○") for c in r["similar"]))

    def test_civil_report_without_claim(self):
        r = self.client.post("/api/civil/report", json={"text": "短"}).json()
        self.assertIsNone(r["amount_range"])

    def test_mock_guide(self):
        case_id = self.client.post("/api/civil/report", json={"text": TRAFFIC}).json()["similar"][0]["case_id"]
        r = self.client.get(f"/api/judgments/civil/{case_id}/guide").json()
        self.assertTrue(r["mock"])
        self.assertEqual([p["function"] for p in r["paragraphs"]], ["claim", "defense", "issue", "evidence", "court"])

    def test_forced_mock_mode(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        build_artifacts(Path(tmp.name))
        client = TestClient(create_app(Settings(artifacts_dir=Path(tmp.name), mode="mock")))
        self.assertEqual(client.get("/api/health").json()["civil"], "mock")


class TestStartupErrors(unittest.TestCase):
    def test_real_cause_is_not_hidden_from_uvicorn(self):
        """uvicorn 遇到 AttributeError 只會說找不到 app，讀模型檔失敗時要看得到真正的原因。"""
        import backend.main as main
        with mock.patch.object(main, "create_app", side_effect=AttributeError("讀不出模型檔")),                 mock.patch.object(main, "_app", None):
            with self.assertRaisesRegex(RuntimeError, "讀不出模型檔"):
                main.__getattr__("app")


class TestCommonEndpoints(_MockCase):
    def test_validation(self):
        self.assertEqual(self.client.post("/api/civil/report", json={"text": ""}).status_code, 422)
        self.assertEqual(self.client.post("/api/civil/report", json={"text": "x", "claimed_amount": -1}).status_code, 422)
        self.assertEqual(self.client.post("/api/civil/report",
                                          json={"text": "x", "defendant_type": "alien"}).status_code, 422)
        self.assertEqual(self.client.post("/api/civil/report", json={"text": "x" * 20001}).status_code, 422)

    def test_mask(self):
        r = self.client.post("/api/intake/mask", json={"text": "我是王小明，電話0912345678", "names": ["王小明"]}).json()
        self.assertEqual(r["masked_text"], "我是【姓名】，電話【電話】")
        self.assertEqual([s["kind"] for s in r["spans"]], ["name", "phone"])
        self.assertEqual(r["spans"][1]["label"], "電話")

    def test_followup_traffic(self):
        r = self.client.post("/api/intake/followup", json={"case_type": "civil", "mid": "侵權：交通事故",
                                                            "text": "我被車撞"}).json()
        self.assertEqual(r["source"], "rules")
        ids = [q["id"] for q in r["questions"]]
        self.assertEqual(ids[:3], ["signal", "injury", "insurance"])
        self.assertLessEqual(len(ids), 4)
        self.assertTrue(all(q["why"] for q in r["questions"]))

    def test_followup_skips_answered(self):
        r = self.client.post("/api/intake/followup", json={"case_type": "civil", "mid": "侵權：交通事故",
                                                            "text": "我直行綠燈，右手骨折住院，已經領了強制險"}).json()
        self.assertNotIn("signal", [q["id"] for q in r["questions"]])
        self.assertNotIn("insurance", [q["id"] for q in r["questions"]])

    def test_followup_without_text_gives_the_whole_pool(self):
        """打開確認頁時瀏覽器不送描述，要自己用 skip_if 篩。"""
        r = self.client.post("/api/intake/followup", json={"case_type": "civil", "mid": "侵權：交通事故", "text": ""}).json()
        self.assertGreater(len(r["questions"]), 4)
        self.assertTrue(any(q["skip_if"] for q in r["questions"]))

    def test_followup_criminal(self):
        r = self.client.post("/api/intake/followup", json={"case_type": "criminal", "text": ""}).json()
        self.assertEqual(r["questions"][0]["id"], "act")

    def test_criminal_is_mock(self):
        r = self.client.post("/api/criminal/predict", json={"text": "開車撞到人"}).json()
        self.assertTrue(r["mock"])
        self.assertEqual(len(r["charges"][0]["sentence"]), 6)
        self.assertAlmostEqual(sum(b["share"] for b in r["charges"][0]["sentence"]), 1.0, places=5)
        case_id = r["similar"][0]["case_id"]
        self.assertEqual(self.client.get(f"/api/judgments/criminal/{case_id}/guide").status_code, 200)

    def test_guide_not_found(self):
        self.assertEqual(self.client.get("/api/judgments/civil/999999/guide").status_code, 404)
        self.assertEqual(self.client.get("/api/judgments/criminal/999999/guide").status_code, 404)
        self.assertEqual(self.client.get("/api/judgments/family/1/guide").status_code, 404)

    def test_search_types(self):
        both = self.client.post("/api/retrieval/search", json={"type": "both", "text": TRAFFIC, "k": 2}).json()
        self.assertEqual((len(both["civil"]), len(both["criminal"])), (2, 2))
        crim = self.client.post("/api/retrieval/search", json={"type": "criminal", "text": TRAFFIC}).json()
        self.assertEqual(crim["civil"], [])

    def test_openapi_docs(self):
        paths = self.client.get("/openapi.json").json()["paths"]
        for p in ("/api/civil/report", "/api/criminal/predict", "/api/intake/mask", "/api/retrieval/search"):
            self.assertIn(p, paths)


class TestMidInference(unittest.TestCase):
    def service(self, mids, sims):
        svc = CivilService.__new__(CivilService)
        svc.mids = np.array(mids)
        svc.default = np.zeros(len(mids), dtype=bool)
        svc.index = mock.Mock()
        svc.index.top.return_value = (np.arange(len(mids)), np.array(sims, dtype=float))
        return svc

    def test_clear_vote_is_used(self):
        svc = self.service(["甲", "甲", "乙"], [0.5, 0.4, 0.1])
        self.assertEqual(svc._infer_mid(None), ("甲", ["甲", "乙"]))

    def test_split_vote_only_gives_candidates(self):
        svc = self.service(["甲", "乙", "丙", "丁"], [0.3, 0.3, 0.2, 0.2])
        mid, likely = svc._infer_mid(None)
        self.assertIsNone(mid)
        self.assertEqual(len(likely), 3)

    def test_other_is_never_the_answer(self):
        svc = self.service(["其他", "其他", "甲"], [0.5, 0.4, 0.1])
        self.assertEqual(svc._infer_mid(None)[0], None)

    def test_chosen_mid_is_not_overridden(self):
        svc = self.service(["甲", "甲"], [0.5, 0.4])
        self.assertEqual(svc._resolve_mid(mock.Mock(mid="乙", text=TRAFFIC), None), ("乙", None))

    def test_notice_says_what_was_assumed(self):
        svc = self.service(["甲", "甲"], [0.5, 0.4])
        mid, note = svc._resolve_mid(mock.Mock(mid=None, text=TRAFFIC), None)
        self.assertEqual(mid, "甲")
        self.assertIn("「甲」", note)

    def test_candidates_listed_when_unsure(self):
        svc = self.service(["甲", "乙", "丙", "丁"], [0.3, 0.3, 0.2, 0.2])
        mid, note = svc._resolve_mid(mock.Mock(mid=None, text=TRAFFIC), None)
        self.assertIsNone(mid)
        self.assertIn("比較接近的有", note)

    def test_unrelated_text_is_not_classified(self):
        svc = self.service(["甲", "甲"], [0.5, 0.4])
        mid, note = svc._resolve_mid(mock.Mock(mid=None, text="今天天氣很好"), None)
        self.assertIsNone(mid)
        self.assertNotIn("甲", note)


class TestTwoTiers(unittest.TestCase):
    """最像的是一造辯論的案件時：列表可以出現但有上限，統計完全不算它們。"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        base = Path(cls.tmp.name)
        d = synthetic(150)
        service.train(d, "test", service.artifact_dir(base), {"原告主張＋特徵": {"auc": 0.77, "ece": 0.01, "brier": 0.2}})
        n_default = 40
        default = np.arange(len(d)) < n_default
        text = np.where(default, [f"一造案件{i}，" + TRAFFIC[:40] for i in range(len(d))],
                        [f"對審案件{i}，" + TRAFFIC[10:30] + "，其餘情節完全不同，請求賠償" for i in range(len(d))])
        corpus = pd.DataFrame({
            "id": d.id, "case_number": [f"第 {i} 號" for i in d.id], "court": "臺北", "year": "2024",
            "case_type_category": "侵權", "case_type_mid": "侵權：交通事故",
            "outcome": np.where(default, "勝訴", "一部勝訴一部敗訴"), "y": 1, "plaintiff_claim_text": text,
            "claimed_amount": 100000, "awarded_amount": np.where(default, 100000, 50000),
            "grant_ratio": np.where(default, 1.0, 0.5), "default_judgment": default.astype(int),
            "in_stats": (~default).astype(int)})
        sections = pd.DataFrame({
            "id": d.id, "plaintiff_claim_text": "原告主張",
            "defendant_defense_text": np.where(default, "", "被告則以：原告亦與有過失等語"),
            "court_reasoning_text": np.where(default, "原告提出LINE對話紀錄為證。", "原告提出診斷證明書為證。"),
            "plaintiff": "", "defendant": "", "plaintiff_agent": "", "defendant_agent": ""})
        build.write_artifacts(corpus, sections, build.artifact_dir(base), "test")
        cls.client = TestClient(create_app(Settings(artifacts_dir=base)))
        cls.report = cls.client.post("/api/civil/report", json={"text": TRAFFIC, "mid": "侵權：交通事故",
                                                                "claimed_amount": 100000}).json()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_list_marks_and_caps_default_judgments(self):
        flags = [c["default_judgment"] for c in self.report["similar"]]
        self.assertEqual(len(flags), 10)
        self.assertEqual(sum(flags), MAX_DEFAULT_SHOWN)
        self.assertTrue(all(flags[:MAX_DEFAULT_SHOWN]), "一造辯論的案件在這份資料裡最像，要排在前面")

    def test_statistics_ignore_default_judgments(self):
        r = self.report
        self.assertEqual(r["n_compared"], 30)
        self.assertEqual(r["amount_range"]["ratio_median"], 0.5, "一造辯論全額勝訴，算進來中位數就不是 0.5")
        self.assertEqual([e["key"] for e in r["evidence"]], ["medical"], "LINE 只出現在一造辯論的案件")
        self.assertEqual(r["defenses"][0]["share"], 1)

    def test_contested_cases_listed_even_if_default_judgments_fill_the_candidates(self):
        """金融類的情況：相似度最高的幾十件全是一造辯論，對審還是要進得了列表。"""
        with mock.patch("backend.civil_service.N_CANDIDATES", 5):
            cases = self.client.post("/api/retrieval/search", json={
                "text": TRAFFIC, "type": "civil", "mid": "侵權：交通事故", "k": 5}).json()["civil"]
        self.assertEqual(sum(c["default_judgment"] for c in cases), MAX_DEFAULT_SHOWN)
        self.assertEqual(len(cases), 5)

    def test_evidence_from_answers_is_recognized(self):
        text = TRAFFIC + "\n追問：有診斷證明嗎？\n回答：有診斷證明書"
        rows = self.client.post("/api/civil/report", json={"text": text, "mid": "侵權：交通事故"}).json()["evidence"]
        self.assertTrue(next(r for r in rows if r["key"] == "medical")["user_has"])

    def test_questions_do_not_reach_the_model(self):
        with mock.patch("civil.models.service.ServiceModel.predict_one", return_value=0.5) as predict:
            self.client.post("/api/civil/predict", json={"text": TRAFFIC + "\n追問：有車禍鑑定嗎？\n回答：沒有"})
        self.assertNotIn("鑑定", predict.call_args[0][0])
        self.assertIn("沒有", predict.call_args[0][0])

    def test_unrelated_text_gets_a_warning(self):
        r = self.client.post("/api/civil/report", json={"text": "今天天氣很好，我想去海邊走走。" * 12}).json()
        self.assertTrue(any("不像法律糾紛" in w for w in r["prediction"]["warnings"]))
        self.assertFalse(any("不像法律糾紛" in w for w in self.report["prediction"]["warnings"]))

    def test_inferred_mid_reaches_the_model(self):
        with mock.patch("civil.models.service.ServiceModel.predict_one", return_value=0.5) as predict:
            r = self.client.post("/api/civil/predict", json={"text": TRAFFIC}).json()
        self.assertEqual(predict.call_args[0][1]["mid"], "侵權：交通事故")
        self.assertTrue(any("侵權：交通事故" in w for w in r["warnings"]))

    def test_search_uses_the_same_list(self):
        r = self.client.post("/api/retrieval/search", json={"text": TRAFFIC, "type": "civil", "mid": "侵權：交通事故"}).json()
        cases = r["civil"]
        self.assertEqual(sum(c["default_judgment"] for c in cases), MAX_DEFAULT_SHOWN)


class TestWithModel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        build_artifacts(Path(cls.tmp.name))
        cls.client = TestClient(create_app(Settings(artifacts_dir=Path(cls.tmp.name))))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def report(self, **body):
        r = self.client.post("/api/civil/report", json={"mid": "侵權：交通事故", **body})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_health_and_options(self):
        self.assertEqual(self.client.get("/api/health").json()["civil"], "model")
        r = self.client.get("/api/meta/options").json()
        self.assertFalse(r["mock"])
        self.assertEqual({g["category"] for g in r["mid_groups"]}, {"侵權", "契約"})

    def test_probability_follows_text(self):
        win = self.client.post("/api/civil/predict", json={"text": WIN[0] * 5, "mid": "侵權：交通事故"}).json()
        lose = self.client.post("/api/civil/predict", json={"text": LOSE[0] * 5, "mid": "侵權：交通事故"}).json()
        self.assertFalse(win["mock"])
        self.assertGreater(win["win_probability"], lose["win_probability"])
        self.assertEqual(win["model"]["auc"], 0.77)
        self.assertEqual(win["warnings"], [])

    def test_warnings(self):
        r = self.client.post("/api/civil/predict", json={"text": "被車撞了"}).json()
        self.assertEqual(len(r["warnings"]), 2)

    def test_report(self):
        r = self.report(text=WIN[0] * 5, claimed_amount=200000, evidence=["medical"],
                        plaintiff_has_lawyer=False, defendant_type="company", court="臺北")
        self.assertFalse(r["mock"])
        self.assertEqual(len(r["similar"]), 10)
        self.assertEqual(r["n_compared"], 30)
        self.assertTrue(all(c["mid"] == "侵權：交通事故" for c in r["similar"]), "選了案由就在同案由裡找")
        sims = [c["similarity"] for c in r["similar"]]
        self.assertEqual(sims, sorted(sims, reverse=True))
        self.assertEqual(r["amount_range"]["amount_median"], 120000)   # 合成資料的獲償比例都是 0.6
        medical = next(e for e in r["evidence"] if e["key"] == "medical")
        self.assertTrue(medical["user_has"])
        self.assertEqual(medical["share"], 1.0)
        self.assertEqual([d["key"] for d in r["defenses"]][:2], ["contributory", "excessive"])

    def test_unknown_mid_searches_everything(self):
        r = self.report(text=LOSE[1] * 3, mid="沒有這個案由")
        self.assertEqual(len(r["similar"]), 10)

    def test_guide_masks_party_names(self):
        case_id = self.report(text=WIN[0])["similar"][0]["case_id"]
        r = self.client.get(f"/api/judgments/civil/{case_id}/guide").json()
        self.assertFalse(r["mock"])
        self.assertEqual(r["labeler"], "rule-v0")
        functions = [p["function"] for p in r["paragraphs"]]
        self.assertEqual(functions, ["claim", "defense", "issue", "evidence", "court"])
        text = "".join(p["text"] for p in r["paragraphs"])
        self.assertNotIn("王小明", text)
        self.assertNotIn("陳大華", text)
        self.assertIn("【原告】", text)

    def test_search(self):
        r = self.client.post("/api/retrieval/search", json={"type": "civil", "text": WIN[1], "k": 3}).json()
        self.assertFalse(r["mock"])
        self.assertEqual(len(r["civil"]), 3)


if __name__ == "__main__":
    unittest.main()
