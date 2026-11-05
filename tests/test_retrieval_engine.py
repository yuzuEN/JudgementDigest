# -*- coding: utf-8 -*-
"""
retrieval/engine.py 的離線測試：用小語料確認排序、篩選、排除本身與存檔讀回。
"""

import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from retrieval.engine import TfidfIndex  # noqa: E402

CORPUS = [
    "原告騎機車直行遭被告汽車右轉撞擊受傷住院",
    "原告騎機車在路口被右轉汽車撞傷骨折",
    "被告向原告借款五十萬元屆期未清償",
    "被告借款未還原告請求返還借款",
    "承租人積欠租金經催告仍未給付",
    "房東請求返還房屋並給付積欠租金",
]
MID = np.array(["交通", "交通", "借貸", "借貸", "租賃", "租賃"])


def small_index():
    return TfidfIndex(min_df=1, max_features=None).fit(CORPUS)


class TestSearch(unittest.TestCase):
    def test_most_similar_first(self):
        rows, sim = small_index().search("機車在路口被汽車撞到受傷", k=3)
        self.assertIn(rows[0], (0, 1))
        self.assertTrue(np.all(np.diff(sim) <= 0), "相似度要由高到低")
        self.assertEqual(len(rows), 3)

    def test_allowed_mask(self):
        rows, _ = small_index().search("借款未清償", k=5, allowed=MID == "租賃")
        self.assertEqual(set(rows), {4, 5})

    def test_nothing_allowed(self):
        rows, sim = small_index().search("借款", k=5, allowed=np.zeros(len(CORPUS), bool))
        self.assertEqual(len(rows), 0)
        self.assertEqual(len(sim), 0)

    def test_k_larger_than_corpus(self):
        rows, _ = small_index().search("借款", k=50)
        self.assertEqual(len(rows), len(CORPUS))


class TestNeighbors(unittest.TestCase):
    def test_excludes_self_and_respects_groups(self):
        index = small_index()
        rows = np.arange(len(CORPUS))
        nn, sim = index.neighbors(rows, k=1, groups=MID)
        self.assertTrue(np.all(nn[:, 0] != rows), "鄰居不能是自己")
        self.assertTrue(np.all(MID[nn[:, 0]] == MID), "只在同一類裡找")
        self.assertEqual(list(nn[:, 0]), [1, 0, 3, 2, 5, 4])

    def test_allowed_limits_neighbors(self):
        index = small_index()
        allowed = np.array([False, True, False, True, False, True])
        nn, _ = index.neighbors(np.arange(len(CORPUS)), k=1, allowed=allowed)
        self.assertTrue(np.all(allowed[nn[:, 0]]))

    def test_chunking_gives_same_result(self):
        index = small_index()
        rows = np.arange(len(CORPUS))
        a, _ = index.neighbors(rows, k=2)
        b, _ = index.neighbors(rows, k=2, chunk=2)
        self.assertTrue(np.array_equal(a, b))


class TestFitSample(unittest.TestCase):
    def test_vocabulary_from_sample_but_all_rows_indexed(self):
        full = small_index()
        part = TfidfIndex(min_df=1, max_features=None).fit(CORPUS, sample=3)
        self.assertEqual(len(part), len(CORPUS))
        self.assertLess(len(part.vectorizer.vocabulary_), len(full.vectorizer.vocabulary_))

    def test_sample_is_reproducible(self):
        a = TfidfIndex(min_df=1, max_features=None).fit(CORPUS, sample=3)
        b = TfidfIndex(min_df=1, max_features=None).fit(CORPUS, sample=3)
        self.assertEqual(a.vectorizer.vocabulary_, b.vectorizer.vocabulary_)

    def test_sample_larger_than_corpus_uses_everything(self):
        index = TfidfIndex(min_df=1, max_features=None).fit(CORPUS, sample=100)
        self.assertEqual(index.vectorizer.vocabulary_, small_index().vectorizer.vocabulary_)


class TestScores(unittest.TestCase):
    def test_top_of_scores_equals_search(self):
        index = small_index()
        query = "機車被汽車撞傷"
        a, _ = index.search(query, 3)
        b, _ = index.top(index.scores(query), 3)
        self.assertEqual(list(a), list(b))

    def test_top_respects_allowed(self):
        index = small_index()
        rows, _ = index.top(index.scores("機車被汽車撞傷"), 2, MID == "租賃")
        self.assertEqual(sorted(rows), [4, 5])


class TestSaveLoad(unittest.TestCase):
    def test_roundtrip(self):
        index = small_index()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sub" / "index.joblib"
            index.save(path)
            loaded = TfidfIndex.load(path)
        self.assertEqual(len(loaded), len(CORPUS))
        a = index.search("房屋租金", k=2)
        b = loaded.search("房屋租金", k=2)
        self.assertTrue(np.array_equal(a[0], b[0]))
        self.assertTrue(np.allclose(a[1], b[1]))


if __name__ == "__main__":
    unittest.main()
