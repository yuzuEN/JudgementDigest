# -*- coding: utf-8 -*-
"""criminal/models/service.py：刑度區間、罪名對法條、用合成資料訓練後 predict 的輸出格式。"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from criminal.models import service  # noqa: E402
from retrieval import criminal as retrieval_criminal  # noqa: E402

DRUNK = "被告飲用啤酒後，吐氣所含酒精濃度達每公升零點四毫克，仍騎乘機車上路，為警攔查。"
THEFT = "被告徒手竊取店內商品，得手後離去，經店員報警查獲。"


def meta(charge, law, raw_law, kind="有期徒刑", months=3):
    return {"accusation": [charge], "relevant_articles": [law], "sentence_kind": kind,
            "task_validity": {"accusation": True, "article": True, "imprisonment": kind == "有期徒刑"},
            "term_of_imprisonment": {"imprisonment": months, "death_penalty": False, "life_imprisonment": False},
            "label_detail": {"standard_charges_by_offense": [[charge]], "raw_laws_by_offense": [[raw_law, "刑法第41條第1項"]]},
            "detention_days": 20 if kind == "拘役" else 0, "punish_of_money": 0, "criminals": ["王大明"],
            "court": "臺北地方法院", "year": 2024, "judgment_date": "2024-05-01",
            "source_url": "https://judgment.judicial.gov.tw/FJUD/data.aspx?ty=JD&id=TPDM"}


def synthetic(n=60):
    rows = []
    for i in range(n):
        if i % 2:
            m = meta("酒駕罪", "刑法第185條", "刑法第185條之3第1項第1款", "拘役" if i % 4 == 1 else "有期徒刑", 4)
            text = f"民國{100 + i}年，王大明" + DRUNK
        else:
            m = meta("竊盜罪", "刑法第320條", "刑法第320條第1項", months=8)
            text = f"民國{100 + i}年，" + THEFT
        m["case_number"] = f"臺灣臺北地方法院 113 年度 簡 字第 {i} 號刑事簡易判決"
        rows.append({"fact": text, "meta": m})
    return rows


def write_jsonl(rows, path: Path):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def train_artifacts(base: Path, retrieval: bool = True) -> Path:
    src = base / "cail.jsonl"
    write_jsonl(synthetic(), src)
    if retrieval:
        retrieval_criminal.write_artifacts(retrieval_criminal.load_corpus(src), retrieval_criminal.artifact_dir(base))
    return service.train(service.read(src), service.artifact_dir(base), src.name)


class TestLabels(unittest.TestCase):
    def test_bucket_of(self):
        def b(kind, months=0, valid=True):
            return service.bucket_of({"sentence_kind": kind, "task_validity": {"imprisonment": valid},
                                      "term_of_imprisonment": {"imprisonment": months}})
        self.assertEqual([b("有期徒刑", m) for m in (2, 6, 7, 12, 13, 36, 37, 120, 121)], [1, 1, 2, 2, 3, 3, 4, 4, 5])
        self.assertEqual((b("拘役"), b("死刑或無期徒刑")), (0, 5))
        self.assertIsNone(b("刑期未明"))
        fine = {"sentence_kind": "刑期未明", "punish_of_money": 10000, "detention_days": 0,
                "term_of_imprisonment": {"imprisonment": 0}}
        self.assertEqual(service.bucket_of(fine), 0)          # 只判罰金
        self.assertIsNone(b("有期徒刑", 5, valid=False))

    def test_offense_laws_keep_suffix_and_drop_general_part(self):
        m = meta("酒駕罪", "刑法第185條", "刑法第185條之3第1項第1款")
        self.assertEqual(service.offense_laws(m), [("酒駕罪", "刑法第185條之3")])
        m["label_detail"]["standard_charges_by_offense"] = [["酒駕罪", "竊盜罪"]]   # 兩個罪名的犯罪，分不出法條屬於誰
        self.assertEqual(service.offense_laws(m), [])

    def test_bucket_of_text(self):
        texts = ["拘役 20 日", "罰金 10,000 元", "有期徒刑 3 月", "有期徒刑 1 年", "有期徒刑 1 年 2 月", "有期徒刑 12 年",
                 "無期徒刑", None, "有期徒刑併拘役"]
        self.assertEqual([service.bucket_of_text(t) for t in texts], [0, 0, 1, 2, 3, 5, 5, None, None])

    def test_renumbered_law_shows_current_article(self):
        m = service.CriminalModel()
        m.laws = {"洗錢罪": ["洗錢防制法第14條"], "竊盜罪": ["刑法第320條"], "新法洗錢": ["洗錢防制法第19條"]}
        self.assertEqual(m.law_info("洗錢罪", {}), {
            "law": "洗錢防制法第 19 條", "law_note": "修法後改為洗錢防制法第 19 條；修法前的行為適用舊法洗錢防制法第 14 條"})
        self.assertEqual(m.law_info("新法洗錢", {})["law_note"], "修法前為洗錢防制法第 14 條")
        self.assertEqual(m.law_info("竊盜罪", {}), {"law": "刑法第 320 條", "law_note": None})

    def test_input_is_nfc_normalized(self):
        self.assertEqual(service.normalize("不確定故意"), "不確定故意")


class TestRetrieval(unittest.TestCase):
    def test_sentence_text(self):
        t = lambda kind, months=0, days=0, money=0: retrieval_criminal.sentence_text(
            {"sentence_kind": kind, "detention_days": days, "punish_of_money": money,
             "term_of_imprisonment": {"imprisonment": months, "death_penalty": False}})
        self.assertEqual([t("有期徒刑", 3), t("有期徒刑", 14), t("有期徒刑", 24)],
                         ["有期徒刑 3 月", "有期徒刑 1 年 2 月", "有期徒刑 2 年"])
        self.assertEqual((t("拘役", days=20), t("刑期未明", money=10000)), ("拘役 20 日", "罰金 10,000 元"))
        self.assertIsNone(t("有期徒刑併拘役"))

    def test_corpus_caps_each_charge_and_masks_defendant(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "cail.jsonl"
            write_jsonl(synthetic(), src)
            corpus = retrieval_criminal.load_corpus(src, per_charge=5)
            self.assertEqual(sorted(corpus.charges.str[0].value_counts().tolist()), [5, 5])
            self.assertFalse(corpus.text.str.contains("王大明").any())

    def test_named_third_parties_keep_only_surname(self):
        text = "被告徒手竊取由店經理賴美君所管領之商品，經警員林建丞到場，賴美君報警。"
        self.assertEqual(retrieval_criminal.masked(text, []),
                         "被告徒手竊取由店經理賴○○所管領之商品，經警員林○○到場，賴○○報警。")
        self.assertEqual(retrieval_criminal.masked("在羅智平加盟經營之全家便利商店", []), "在羅○○加盟經營之全家便利商店")


class TestTrainedModel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.model, cls.meta = service.load(train_artifacts(Path(cls.tmp.name)))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_predict_format(self):
        charges = self.model.predict(DRUNK)
        self.assertEqual(charges[0]["name"], "酒駕罪")
        self.assertEqual(charges[0]["law"], "刑法第 185 條之 3")
        self.assertTrue(0 < charges[0]["probability"] <= 1)
        self.assertEqual([b["label"] for b in charges[0]["sentence"]], service.BUCKETS)
        self.assertAlmostEqual(sum(b["share"] for b in charges[0]["sentence"]), 1.0, places=5)
        self.assertLessEqual(len(charges), service.MAX_SHOWN)

    def test_platform_metrics(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "cail.jsonl"
            write_jsonl(synthetic(), src)
            m = service.platform_metrics(self.model, service.read(src))
        self.assertEqual(m["n_test"], 60)
        self.assertGreater(m["charge_top1"], 0.9)
        self.assertGreaterEqual(m["bucket_within_one"], m["bucket_accuracy"])

    def test_meta(self):
        self.assertEqual((self.meta["name"], self.meta["charges"], self.meta["n_train"]), ("criminal_v1", 2, 60))


if __name__ == "__main__":
    unittest.main()
