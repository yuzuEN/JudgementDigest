# -*- coding: utf-8 -*-
"""
model/evaluate.py 的離線測試：所有模型共用的切分與評分，算錯的話每個模型的分數都會錯。

只用 numpy（CI 不裝 scikit-learn／PyTorch）；F1 的定義對齊 sklearn f1_score(zero_division=0)。
"""

import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))

import evaluate as E  # noqa: E402


def record(fold, acc=("竊盜罪",), art=("刑法第320條",), months=3, term_task=True, validity=None):
    meta = {"fold": fold, "accusation": list(acc), "relevant_articles": list(art), "term_task": term_task,
            "term_of_imprisonment": {"death_penalty": False, "life_imprisonment": False, "imprisonment": months}}
    if validity is not None:
        meta["task_validity"] = validity
    return {"fact": f"事實{fold}", "meta": meta}


class TestMultilabelScores(unittest.TestCase):
    def test_micro_macro_match_hand_calculation(self):
        Y = np.array([[1, 0, 0], [1, 1, 0], [0, 1, 0]])
        P = np.array([[1, 0, 0], [1, 0, 1], [0, 1, 0]])
        s = E.multilabel_scores(Y, P)
        # 類別 0：tp2 → F1 1；類別 1：tp1 fn1 → 2/3；類別 2：fp1 → 0（沒出現也算進 macro）
        self.assertAlmostEqual(s["macro"], (1 + 2 / 3 + 0) / 3)
        # 合計 tp3 fp1 fn1 → 6/8
        self.assertAlmostEqual(s["micro"], 0.75)

    def test_rest_macro_excludes_top_classes_and_unseen(self):
        Y = np.array([[1, 0, 0], [1, 1, 0], [0, 1, 0]])
        P = np.array([[1, 0, 0], [1, 0, 1], [0, 1, 0]])
        s = E.multilabel_scores(Y, P, top=[0])
        self.assertAlmostEqual(s["其餘 macro"], 2 / 3)   # 類別 2 測試集沒出現，不算

    def test_at_least_one_label(self):
        p = E.at_least_one(np.array([[-1.0, -0.2], [0.5, 0.3]]))
        self.assertEqual(p.tolist(), [[0, 1], [1, 1]])


class TestTermScores(unittest.TestCase):
    def test_cail_score_bands(self):
        self.assertEqual(E.cail_score([6], [6]), 1.0)
        self.assertAlmostEqual(E.cail_score([6], [9]), 0.8)       # |log7 − log10| ≈ 0.36
        self.assertEqual(E.cail_score([E.LIFE], [E.LIFE]), 1.0)
        self.assertEqual(E.cail_score([E.LIFE], [120]), 0.0)

    def test_bin_of(self):
        self.assertEqual([E.bin_of(m) for m in (0, 2, 2.5, 3, 6, 7, 120, 121, E.DEATH)], [0, 0, 1, 1, 1, 2, 4, 5, 6])


class TestLoadAndSplit(unittest.TestCase):
    def test_validity_from_task_validity_or_legacy_fields(self):
        new = E.to_row(record(0, validity={"accusation": True, "article": False, "imprisonment": True}))
        self.assertEqual(new["valid"], {"accusation": True, "article": False, "imprisonment": True})
        old = E.to_row(record(0, art=(), term_task=False))      # v1.1：沒有 task_validity
        self.assertEqual(old["valid"], {"accusation": True, "article": False, "imprisonment": False})

    def test_load_jsonl_and_zip(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "x.jsonl")
            with open(path, "w", encoding="utf-8") as f:
                for k in range(3):
                    f.write(json.dumps(record(k), ensure_ascii=False) + "\n")
            zpath = os.path.join(d, "x.zip")
            with zipfile.ZipFile(zpath, "w") as z:
                z.write(path, "cail.jsonl")
            self.assertEqual(E.load(path), E.load(zpath))

    def test_holdout_split_is_deterministic_and_disjoint(self):
        rows = [E.to_row(record(i % 10)) for i in range(200)]
        for i, r in enumerate(rows):
            r["id"] = i
        pool, val, test = E.holdout_split(rows, test_fold=3, test_n=10, val_n=20)
        again = E.holdout_split(rows, test_fold=3, test_n=10, val_n=20)
        self.assertEqual([r["id"] for r in pool], [r["id"] for r in again[0]])
        self.assertEqual(len(test), 10); self.assertEqual(len(val), 20); self.assertEqual(len(pool), 160)
        self.assertTrue(all(r["fold"] == 3 for r in test))
        ids = [r["id"] for r in pool + val + test]
        self.assertEqual(len(ids), len(set(ids)))
        full = E.holdout_split(rows, test_fold=3, test_n=None)[2]
        self.assertEqual(len(full), 20)                            # test_n=None：整個 fold

    def test_task_rows_filters_invalid(self):
        rows = [E.to_row(record(0, validity={"accusation": v, "article": True, "imprisonment": True})) for v in (True, False)]
        self.assertEqual(len(E.task_rows(rows, "accusation")), 1)


if __name__ == "__main__":
    unittest.main()
