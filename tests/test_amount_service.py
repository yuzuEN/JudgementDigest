# -*- coding: utf-8 -*-
"""civil/models/amount_service.py：平台用的獲償比例模型（若為一部勝訴，原告贏幾成）。用合成資料測，不需要真實資料。"""
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from civil import features  # noqa: E402
from civil.models import amount, amount_service as A  # noqa: E402
from tests.test_civil_service import LOSE, WIN, synthetic  # noqa: E402


def amount_frame(n=200):
    """勝訴那一半的獲償比例 0.8、敗訴那一半 0.3（文字就分得出來）；請求金額各不相同。"""
    d = synthetic(n)
    d["ratio"] = np.where(d.y == 1, 0.8, 0.3)
    d["claimed_amount"] = [100_000.0 * (1 + i % 5) for i in range(len(d))]
    return d


ANSWERS = {"mid": "侵權：交通事故", "court": "臺北", "plaintiff_has_lawyer": False, "defendant_is_corp": True}


class TestKeywordTableShared(unittest.TestCase):
    def test_both_use_the_shared_table(self):
        """分析腳本和平台模型都從 civil/features.py import，只有一份。"""
        self.assertIs(A.ITEMS, features.ITEMS)
        self.assertIs(amount.ITEMS, features.ITEMS)


class TestSelectSample(unittest.TestCase):
    def frame(self):
        return pd.DataFrame({
            "outcome": ["一部勝訴一部敗訴"] * 6 + ["勝訴", "敗訴"],
            "grant_ratio_source": ["計算"] * 5 + ["敗訴"] + ["計算"] * 2,
            "quality_flags": [""] * 4 + ["判准大於請求", ""] + [""] * 2,
            "grant_ratio": [0.5, 0.4, 1.0, 0.0, 0.5, 0.5, 1.0, 0.0],
            "claimed_amount": [100, 100, 100, 100, 100, 100, 100, 100],
            "claimed_source": ["直接抽取"] * 3 + ["直接抽取"] * 3 + ["直接抽取"] * 2})

    def test_keeps_only_partial_wins_with_computed_valid_ratio(self):
        d = A.select_sample(self.frame())
        # 一部勝訴 6 件 → 比例是算出來的 5 件 → 沒有「判准大於請求」旗標 4 件 → 比例在 (0, 1] 3 件
        self.assertEqual(len(d), 3)
        self.assertEqual([n for _, n in d.attrs["flow"]], [8, 6, 5, 4, 3, 3])
        self.assertTrue(((d.grant_ratio > 0) & (d.grant_ratio <= 1)).all())

    def test_claim_must_be_extracted_directly(self):
        f = self.frame()
        f.loc[0, "claimed_source"] = "備用推算"
        self.assertEqual(len(A.select_sample(f)), 2)


class TestUnknowns(unittest.TestCase):
    def test_share_and_determinism(self):
        d = amount_frame(1000)
        a, b = A.with_unknowns(d), A.with_unknowns(d)
        self.assertTrue(a.equals(b))
        self.assertAlmostEqual((a.court == A.UNKNOWN).mean(), A.UNKNOWN_SHARE, delta=0.06)
        self.assertAlmostEqual(a.claimed_amount.isna().mean(), A.UNKNOWN_SHARE, delta=0.06)

    def test_does_not_touch_the_original(self):
        d = amount_frame(50)
        A.with_unknowns(d)
        self.assertFalse(d.claimed_amount.isna().any())
        self.assertNotIn(A.UNKNOWN, set(d.court))


class TestRange(unittest.TestCase):
    def test_calibrate_gives_ordered_quantiles_per_bin(self):
        rng = np.random.default_rng(0)
        pred = rng.uniform(0.1, 0.9, 2000)
        truth = np.clip(pred + rng.normal(0, 0.1, 2000), 0, 1)
        edges, q = A.calibrate(pred, truth)
        self.assertEqual(len(edges), A.N_BINS - 1)
        self.assertEqual(q.shape, (A.N_BINS, 3))
        self.assertTrue((q[:, 0] < q[:, 1]).all() and (q[:, 1] < q[:, 2]).all())

    def test_interval_is_ordered_and_clipped(self):
        edges, q = np.array([0.3, 0.6]), np.array([[-0.5, 0.0, 0.5]] * 3)
        out = A.interval(np.array([0.05, 0.5, 0.95]), edges, q)
        self.assertTrue(((out[:, 0] <= out[:, 1]) & (out[:, 1] <= out[:, 2])).all())
        self.assertTrue(((out >= A.MIN_RATIO) & (out <= 1.0)).all())
        self.assertEqual(out[0, 0], A.MIN_RATIO)       # 0.05 − 0.5 < 0 → 裁到下限
        self.assertEqual(out[2, 2], 1.0)               # 0.95 + 0.5 > 1 → 裁到 1

    def test_coverage_is_close_to_nominal_on_held_out_data(self):
        rng = np.random.default_rng(1)
        make = lambda n: (lambda p: (p, np.clip(p + rng.normal(0, 0.15, n), 0, 1)))(rng.uniform(0.2, 0.8, n))   # noqa: E731
        (p1, t1), (p2, t2) = make(4000), make(4000)
        edges, q = A.calibrate(p1, t1)
        m = A.metrics(t2, A.interval(p2, edges, q))
        self.assertAlmostEqual(m["coverage"], A.HIGH - A.LOW, delta=0.04)
        self.assertAlmostEqual(m["coverage"] + m["below"] + m["above"], 1.0, places=6)


class TestPairedBootstrap(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(2)
        self.truth = rng.uniform(0.05, 1, 3000)
        self.good = np.column_stack([self.truth - 0.2, self.truth, self.truth + 0.2])          # 中位數就是答案、全部涵蓋
        self.bad = np.column_stack([self.truth + 0.1, self.truth + 0.2, self.truth + 0.3])     # 偏高 0.2、全部沒涵蓋

    def test_same_method_has_zero_difference(self):
        r = A.paired_bootstrap(self.truth, self.good, self.good, n=200)
        for key in ("mae", "coverage", "width"):
            self.assertEqual((r[key]["diff"], r[key]["low"], r[key]["high"]), (0.0, 0.0, 0.0))

    def test_signs_and_intervals(self):
        r = A.paired_bootstrap(self.truth, self.good, self.bad, n=200)
        self.assertAlmostEqual(r["mae"]["diff"], -0.2, places=6)          # 前者比較準 → 負的
        self.assertLess(r["mae"]["high"], 0)                              # 區間不含 0
        self.assertAlmostEqual(r["coverage"]["diff"], 1.0, places=6)      # 前者全部涵蓋、後者全部沒有
        self.assertAlmostEqual(r["width"]["diff"], 0.2, places=6)         # 前者寬 0.4、後者寬 0.2
        self.assertLessEqual(r["mae"]["low"], r["mae"]["diff"] + 1e-9)
        self.assertLessEqual(r["mae"]["diff"], r["mae"]["high"] + 1e-9)

    def test_report_includes_the_comparison_table(self):
        r = A.paired_bootstrap(self.truth, self.good, self.bad, n=50)
        m = A.metrics(self.truth, self.good)
        text = A.report({"甲": m, "_baseline_mae_global_median": 0.28, "_bootstrap": {"甲 − 乙": r}},
                        "test", [("全部", 3000)], "2.5.1")
        self.assertIn("金額欄位規則 2.5.1", text)
        self.assertIn("| 甲 − 乙 | -0.2000", text)


class TestBaselines(unittest.TestCase):
    def test_knn_quantiles_uses_same_mid_then_top_k(self):
        mids_tr = np.array(["甲"] * 12 + ["乙"] * 12)
        ratio_tr = np.array([0.9] * 12 + [0.1] * 12)
        sim = np.ones((2, 24))
        out = A.knn_quantiles(sim, mids_tr, ratio_tr, np.array(["甲", "乙"]), k=5)
        self.assertTrue((out[0] == 0.9).all() and (out[1] == 0.1).all())

    def test_knn_quantiles_falls_back_to_all_when_mid_is_rare(self):
        mids_tr = np.array(["甲"] * 20 + ["乙"] * 3)
        ratio_tr = np.array([0.9] * 20 + [0.1] * 3)
        sim = np.zeros((1, 23))
        sim[0, 20:] = 1.0                                # 乙只有 3 件（< min_same），改在全部找，最相似的是這 3 件
        out = A.knn_quantiles(sim, mids_tr, ratio_tr, np.array(["乙"]), k=3)
        self.assertEqual(out[0, 1], 0.1)

    def test_group_quantiles_small_groups_use_overall(self):
        out = A.group_quantiles(np.array(["甲"] * 40 + ["乙"] * 5), np.array([0.2] * 40 + [0.9] * 5), np.array(["甲", "乙"]))
        self.assertEqual(out[0, 1], 0.2)
        self.assertEqual(out[1, 1], 0.2)                 # 乙不到 30 件 → 用全體


class TestModel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = amount_frame(200)
        rows = A.with_unknowns(cls.d)
        cls.model = A.AmountModel().fit(rows.text, rows, rows.claimed_amount, rows.ratio)
        cls.model.edges, cls.model.q = A.calibrate(
            cls.model.predict(cls.d.text, cls.d, cls.d.claimed_amount), cls.d.ratio.values)

    def test_prediction_follows_text(self):
        win, lose = (self.model.predict_one(t[0] * 5, ANSWERS, 500_000) for t in (WIN, LOSE))
        self.assertGreater(win["ratio_median"], lose["ratio_median"])

    def test_range_is_ordered_and_between_zero_and_one(self):
        r = self.model.predict_one(WIN[0] * 5, ANSWERS, 500_000)
        self.assertLessEqual(r["ratio_low"], r["ratio_median"])
        self.assertLessEqual(r["ratio_median"], r["ratio_high"])
        self.assertGreaterEqual(r["ratio_low"], A.MIN_RATIO)
        self.assertLessEqual(r["ratio_high"], 1.0)
        self.assertAlmostEqual(r["coverage"], 0.8)

    def test_user_may_leave_everything_blank(self):
        for answers, claimed in (({}, None), ({"mid": "沒看過的案由", "court": "不存在的法院"}, 0), (ANSWERS, None)):
            r = self.model.predict_one("被車撞了", answers, claimed)
            self.assertTrue(0 < r["ratio_low"] <= r["ratio_median"] <= r["ratio_high"] <= 1, (answers, claimed))

    def test_claimed_amount_is_a_feature_but_optional(self):
        a = self.model.predict_one(WIN[0] * 5, ANSWERS, None)
        b = self.model.predict_one(WIN[0] * 5, ANSWERS, 300_000)
        self.assertEqual(a.keys(), b.keys())

    def test_point_prediction_is_clipped_to_valid_ratio(self):
        """Ridge 可能預測出負的或超過 1 的比例，要裁回 [MIN_RATIO, 1]。"""
        class Wild:
            def predict(self, X):
                return np.array([-0.7, 0.4, 1.9])
        m = A.AmountModel()
        m.__dict__.update(self.model.__dict__)
        m.ridge = Wild()
        d = self.d.head(3)
        self.assertEqual(list(m.predict(d.text, d, d.claimed_amount)), [A.MIN_RATIO, 0.4, 1.0])

    def test_damage_item_flags(self):
        dense = self.model._dense(["原告住院手術並請求醫療費與慰撫金", "沒有任何子項目"], [100_000, 100_000], fit=False).toarray()
        n_items = len(A.ITEM_PATTERNS)
        flags, count = dense[:, 3:3 + n_items], dense[:, -1]
        self.assertEqual(flags[0].sum(), 4)                 # 住院、手術、醫療費、慰撫金
        self.assertEqual(flags[1].sum(), 0)
        self.assertEqual(list(count), [4 / 5, 0.0])         # 項目數（除以 5）

    def test_claimed_amount_is_clipped_to_the_training_range(self):
        """請求金額遠超出訓練範圍時不外插（平方項會讓 10 億、1 兆給出亂跳的結果）：都裁到訓練資料的第 99 百分位。"""
        lo, hi = self.model.claim_range
        top = 10 ** hi
        same = [self.model.predict_one(WIN[0] * 5, ANSWERS, c)["ratio_median"] for c in (top, 1e9, 1e12)]
        self.assertEqual(len(set(same)), 1, same)
        small = [self.model.predict_one(WIN[0] * 5, ANSWERS, c)["ratio_median"] for c in (10 ** lo, 1, 10)]
        self.assertEqual(len(set(small)), 1, small)

    def test_missing_claim_is_flagged_and_neutral(self):
        """沒填的請求金額：標成「沒填」，數值放平均（z＝0），模型才學得到使用者沒填的情況。"""
        dense = self.model._dense(["甲", "乙", "丙"], [np.nan, 0, 250_000], fit=False).toarray()
        z, z2, missing = dense[:, 0], dense[:, 1], dense[:, 2]
        self.assertEqual(list(missing), [1.0, 1.0, 0.0])    # 沒填與 0 元都算沒填
        self.assertEqual((z[0], z[1], z2[0], z2[1]), (0.0, 0.0, 0.0, 0.0))
        self.assertNotEqual(z[2], 0.0)


class TestTrainAndLoad(unittest.TestCase):
    def test_roundtrip(self):
        d = amount_frame(150)
        with tempfile.TemporaryDirectory() as tmp:
            out = A.train(d, "test", A.artifact_dir(Path(tmp)), {"模型：全部填": {"mae": 0.2}}, "2.5.1")
            self.assertEqual(out, A.artifact_dir(Path(tmp)))
            model, meta = A.load(out)
        self.assertEqual((meta["name"], meta["n_cases"], meta["amount_rules"]), (A.MODEL_NAME, 150, "2.5.1"))
        self.assertEqual(meta["interval"], [A.LOW, A.HIGH])
        self.assertEqual(meta["metrics"]["模型：全部填"]["mae"], 0.2)
        self.assertEqual(meta["mid_counts"], {"侵權：交通事故": 100, "契約：買賣": 50})
        self.assertEqual(meta["items"], features.ITEMS)
        self.assertEqual(meta["claim_log10_range"], list(model.claim_range))
        self.assertEqual(len(model.edges), A.N_BINS - 1)
        r = model.predict_one(WIN[0] * 5, ANSWERS, 500_000)
        self.assertTrue(0 < r["ratio_low"] <= r["ratio_high"] <= 1)

    def test_refuses_stale_model_files(self):
        """舊格式（沒有各案由件數），或關鍵字表改了沒重訓：讀取時就拒絕，後端改用相似判決。"""
        import json
        with tempfile.TemporaryDirectory() as tmp:
            out = A.train(amount_frame(150), "test", A.artifact_dir(Path(tmp)), {}, "2.5.1")
            meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
            for broken, why in (({k: v for k, v in meta.items() if k != "mid_counts"}, "舊格式"),
                                ({**meta, "items": {**meta["items"], "醫療費": "醫療費"}}, "關鍵字")):
                (out / "meta.json").write_text(json.dumps(broken, ensure_ascii=False), encoding="utf-8")
                with self.assertRaises(A.StaleModel) as e:
                    A.load(out)
                self.assertIn(why, str(e.exception))

    def test_usable_for_needs_enough_training_cases(self):
        meta = {"mid_counts": {"民間借貸": 883, "強制執行救濟：債務人異議等": 11}}
        self.assertTrue(A.usable_for(meta, "民間借貸", 30))
        self.assertFalse(A.usable_for(meta, "強制執行救濟：債務人異議等", 30))
        self.assertFalse(A.usable_for(meta, "沒看過的案由", 30))
        self.assertFalse(A.usable_for(meta, None, 30))

    def test_pickled_class_is_importable_by_its_module_name(self):
        """用 python -m 訓練時類別不能記成 __main__.AmountModel，否則後端讀不出來。"""
        self.assertEqual(A.AmountModel.__module__, "civil.models.amount_service")


if __name__ == "__main__":
    unittest.main()
