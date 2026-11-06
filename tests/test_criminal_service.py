# -*- coding: utf-8 -*-
"""criminal/models/service.py：刑度區間、罪名對法條、用合成資料訓練後 predict 的輸出格式。"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from criminal.models import service  # noqa: E402

DRUNK = "被告飲用啤酒後，吐氣所含酒精濃度達每公升零點四毫克，仍騎乘機車上路，為警攔查。"
THEFT = "被告徒手竊取店內商品，得手後離去，經店員報警查獲。"


def meta(charge, law, raw_law, kind="有期徒刑", months=3):
    return {"accusation": [charge], "relevant_articles": [law], "sentence_kind": kind,
            "task_validity": {"accusation": True, "article": True, "imprisonment": kind == "有期徒刑"},
            "term_of_imprisonment": {"imprisonment": months, "death_penalty": False, "life_imprisonment": False},
            "label_detail": {"standard_charges_by_offense": [[charge]], "raw_laws_by_offense": [[raw_law, "刑法第41條第1項"]]}}


def synthetic(n=60):
    rows = []
    for i in range(n):
        if i % 2:
            m = meta("酒駕罪", "刑法第185條", "刑法第185條之3第1項第1款", "拘役" if i % 4 == 1 else "有期徒刑", 4)
            text = DRUNK + f"第{i}次。"
        else:
            m = meta("竊盜罪", "刑法第320條", "刑法第320條第1項", months=8)
            text = THEFT + f"第{i}次。"
        rows.append({"fact": text, "meta": m})
    return rows


def write_jsonl(rows, path: Path):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def train_artifacts(base: Path) -> Path:
    src = base / "cail.jsonl"
    write_jsonl(synthetic(), src)
    return service.train(service.read(src), service.artifact_dir(base), src.name)


class TestLabels(unittest.TestCase):
    def test_bucket_of(self):
        def b(kind, months=0, valid=True):
            return service.bucket_of({"sentence_kind": kind, "task_validity": {"imprisonment": valid},
                                      "term_of_imprisonment": {"imprisonment": months}})
        self.assertEqual([b("有期徒刑", m) for m in (2, 6, 7, 12, 13, 36, 37, 120, 121)], [1, 1, 2, 2, 3, 3, 4, 4, 5])
        self.assertEqual((b("拘役"), b("死刑或無期徒刑")), (0, 5))
        self.assertIsNone(b("刑期未明"))
        self.assertIsNone(b("有期徒刑", 5, valid=False))

    def test_offense_laws_keep_suffix_and_drop_general_part(self):
        m = meta("酒駕罪", "刑法第185條", "刑法第185條之3第1項第1款")
        self.assertEqual(service.offense_laws(m), [("酒駕罪", "刑法第185條之3")])
        m["label_detail"]["standard_charges_by_offense"] = [["酒駕罪", "竊盜罪"]]   # 兩個罪名的犯罪，分不出法條屬於誰
        self.assertEqual(service.offense_laws(m), [])

    def test_input_is_nfc_normalized(self):
        self.assertEqual(service.normalize("不確定故意"), "不確定故意")


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

    def test_meta(self):
        self.assertEqual((self.meta["name"], self.meta["charges"], self.meta["n_train"]), ("criminal_v1", 2, 60))


if __name__ == "__main__":
    unittest.main()
