# -*- coding: utf-8 -*-
"""
civil/models 的離線測試：合併權重、precision／recall 指標、TF-IDF 設定，
以及模組在 import 時不讀命令列參數（舊版讀 sys.argv 決定版本，被別的程式 import 時會出錯）。
訓練與評估本身要用真實資料，不在這裡跑；BERT／Longformer 需要 torch，沒裝時略過。
"""

import importlib
import importlib.util
import sys
import subprocess
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from civil.models.ensemble import blend, logit, pr  # noqa: E402
from civil.models.tfidf import vec  # noqa: E402


class TestBlend(unittest.TestCase):
    def test_learns_to_trust_the_informative_model(self):
        rng = np.random.default_rng(0)
        y = rng.integers(0, 2, 2000)
        good = np.clip(0.5 + (y - 0.5) * 0.6 + rng.normal(0, 0.1, len(y)), 0.01, 0.99)
        noise = rng.uniform(0.01, 0.99, len(y))
        pred, w = blend(y[:1000], [good[:1000], noise[:1000]], [good[1000:], noise[1000:]])
        self.assertEqual(pred.shape, (1000,))
        self.assertGreater(w[0], abs(w[1]) * 5)
        self.assertTrue(np.all((pred > 0) & (pred < 1)))

    def test_logit_is_finite_at_the_edges(self):
        self.assertTrue(np.all(np.isfinite(logit(np.array([0.0, 1.0, 0.5])))))


class TestPrecisionRecall(unittest.TestCase):
    def test_perfect_predictions(self):
        y = np.array([1, 1, 1, 0, 0])
        m = pr(y, np.array([0.9, 0.8, 0.7, 0.2, 0.1]))
        for key in ("勝訴_precision", "勝訴_recall", "敗訴_precision", "敗訴_recall", "正確率", "AUC"):
            self.assertAlmostEqual(m[key], 1.0, msg=key)

    def test_threshold_and_both_sides(self):
        y = np.array([1, 1, 0, 0])
        m = pr(y, np.array([0.9, 0.4, 0.6, 0.1]))
        self.assertAlmostEqual(m["勝訴_precision"], 0.5)   # 判勝：0.9（對）、0.6（錯）
        self.assertAlmostEqual(m["勝訴_recall"], 0.5)
        self.assertAlmostEqual(m["敗訴_precision"], 0.5)
        self.assertAlmostEqual(m["正確率"], 0.5)


class TestTfidfSettings(unittest.TestCase):
    def test_char_ngrams_hashed(self):
        X = vec().fit_transform(["原告主張", "被告抗辯"])
        self.assertEqual(X.shape, (2, 2 ** 20))
        self.assertAlmostEqual(float((X[0].multiply(X[0])).sum()), 1.0, places=5)   # 每列 L2 正規化


class TestNoArgvAtImport(unittest.TestCase):
    MODULES = ["civil.models.tfidf", "civil.models.structured", "civil.models.ensemble",
               "civil.dataset.build_dataset", "civil.dataset.leak_check", "civil.models.amount", "retrieval.evaluate"]

    def test_import_with_unrelated_argv(self):
        with mock.patch.object(sys, "argv", ["uvicorn", "backend.main:app", "--reload"]):
            for name in self.MODULES:
                with self.subTest(module=name):
                    importlib.reload(importlib.import_module(name))
                    self.assertEqual(sys.argv, ["uvicorn", "backend.main:app", "--reload"], "import 時改了 sys.argv")


@unittest.skipUnless(importlib.util.find_spec("torch") and importlib.util.find_spec("transformers"),
                     "需要 torch 與 transformers（.venv-bert）")
class TestTransformerScriptsImport(unittest.TestCase):
    def test_import(self):
        for name in ('civil.models.train_bert', 'civil.models.train_bert_amount', 'civil.models.train_longformer'):
            with self.subTest(module=name):
                importlib.reload(importlib.import_module(name))

    def test_helpers_do_not_load_transformers(self):
        # An installed, incompatible optional PEFT package must not affect helper imports.
        code = """
import importlib, sys
sys.modules['transformers'] = None
for name in ('civil.models.train_bert', 'civil.models.train_bert_amount', 'civil.models.train_longformer'):
    importlib.import_module(name)
"""
        result = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_help_without_transformers(self):
        for name in ('civil.models.train_bert', 'civil.models.train_bert_amount', 'civil.models.train_longformer'):
            with self.subTest(module=name):
                code = "import runpy, sys; sys.modules['transformers'] = None; sys.argv = ['train', '--help']; runpy.run_module(%r, run_name='__main__')" % name
                result = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1],
                                        capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('usage:', result.stdout)


if __name__ == "__main__":
    unittest.main()
