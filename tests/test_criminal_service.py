# -*- coding: utf-8 -*-
"""criminal/models/service.py：刑度區間、罪名對法條、用合成資料訓練後 predict 的輸出格式。
下半部：backend/criminal_service.py 的 ELECTRA 刑度模型，用很小的隨機 ELECTRA 測；沒裝 torch 時略過。"""

import json
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from criminal.models import service  # noqa: E402
from retrieval import criminal as retrieval_criminal  # noqa: E402
from retrieval.criminal_fulltext import masked_full_text  # noqa: E402
from backend.criminal_service import CriminalService, CriminalTermService, term_test_scores, to_training_style  # noqa: E402

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
    def test_full_text_masking(self):
        text = ("聲 請 人 臺灣臺中地方檢察署檢察官\n被 告 王小明\n選任辯護人 陳大文律師\n"
                "王小明於店內竊取被害人林美華之手機，經店員張志強發現。\n本案經檢察官李正義聲請。\n法 官 劉國賓")
        out = masked_full_text(text, ["王小明"], "王小明", ["陳大文", ""])
        for name in ("王小明", "陳大文", "林美華", "張志強"):
            self.assertNotIn(name, out)
        self.assertIn("【被告】", out)
        self.assertIn("【代理人】律師", out)
        for kept in ("臺灣臺中地方檢察署檢察官", "劉國賓"):      # 機關、執行職務的公務員不遮
            self.assertIn(kept, out)

    def test_full_text_masking_spaced_name(self):
        # 兩個字的名字中間有空白（「王 韡」），去掉空白的寫法也要遮
        out = masked_full_text("被 告 王 韡\n王韡於超商竊取商品。", ["王 韡"], "王 韡", [""])
        self.assertNotIn("王 韡", out)
        self.assertNotIn("王韡", out)
        self.assertEqual(out.count("【被告】"), 2)

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

    def test_vocabulary_stored_in_feature_order(self):
        # 依出現順序存放的話，照順序讀得回第一份訓練判決的開頭
        vocab = self.model.vec.vocabulary_
        self.assertEqual(list(vocab.values()), sorted(vocab.values()))
        self.assertNotIn("stop_words_", vars(self.model.vec))
        import sklearn
        self.assertEqual(self.meta["sklearn"], sklearn.__version__)
        self.assertIn("git_commit", self.meta)

    def test_vocabulary_is_not_stored_in_text_order(self):
        """字典照出現順序存的話，依序讀出來就是訓練判決的原文；存檔前要照欄位編號（字典序）重排。"""
        vocab = self.model.vec.vocabulary_
        self.assertEqual(list(vocab), sorted(vocab))
        self.assertEqual(list(vocab.values()), list(range(len(vocab))))


# ── ELECTRA 刑度 ──
try:
    import torch
    from torch import nn
    from transformers import BertTokenizerFast, ElectraConfig, ElectraModel
except ImportError:          # 本機開發環境可能沒裝 torch；Docker 映像檔有
    torch = None

CONFUSION = [[8, 2, 0, 0, 0, 0], [1, 6, 3, 0, 0, 0], [0, 0, 0, 0, 0, 0],
             [0, 0, 0, 0, 0, 0], [0, 0, 0, 0, 0, 0], [0, 0, 0, 0, 0, 0]]


def save_tiny_checkpoint(folder: Path, drop: str = "") -> None:
    """和 Kaggle 訓練程式（ElectraBucket）存的一樣：tokenizer/、encoder_config/、best.pt、experiment_summary.json。"""
    vocab = ["[PAD]", "[UNK]", "[CLS]", "[SEP]", "[MASK]"] + list("被告打人受傷甲○")
    (folder / "tokenizer").mkdir(parents=True)
    (folder / "vocab.txt").write_text("\n".join(vocab), encoding="utf-8")
    BertTokenizerFast(vocab_file=str(folder / "vocab.txt")).save_pretrained(folder / "tokenizer")
    config = ElectraConfig(vocab_size=len(vocab), embedding_size=16, hidden_size=16, num_hidden_layers=1,
                           num_attention_heads=2, intermediate_size=32, max_position_embeddings=64)
    config.save_pretrained(folder / "encoder_config")
    torch.manual_seed(0)
    state = {f"encoder.{k}": v for k, v in ElectraModel(config).state_dict().items()}
    mlp = nn.Sequential(nn.Linear(16, 512), nn.ReLU(), nn.Dropout(), nn.Linear(512, 256))
    state.update({f"mlp.{k}": v for k, v in mlp.state_dict().items()})
    state.update({"head.weight": torch.randn(6, 256), "head.bias": torch.zeros(6)})
    state.pop(drop, None)
    torch.save(state, folder / "best.pt")
    summary = {"selected_epoch": 14, "evaluations": {"test": {"confusion_matrix": CONFUSION}}}
    (folder / "experiment_summary.json").write_text(json.dumps(summary), encoding="utf-8")


class TestTermHelpers(unittest.TestCase):
    def test_mask_tags_become_training_style(self):
        self.assertEqual(to_training_style("【姓名】打【被告】，住【地址】"), "甲○○打甲○○，住○○市○○區○○路000號")

    def test_scores_from_confusion_matrix(self):
        self.assertEqual(term_test_scores({"evaluations": {"test": {"confusion_matrix": CONFUSION}}}),
                         {"n_test": 20, "accuracy": 0.7, "within_one": 1.0})
        self.assertEqual(term_test_scores({}), {})

    def test_missing_files_fall_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(CriminalTermService(Path(tmp)).available)


@unittest.skipIf(torch is None, "沒有裝 torch")
class TestTermTinyModel(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_predicts_six_buckets(self):
        save_tiny_checkpoint(self.root / "criminal_term")
        s = CriminalTermService(self.root)
        self.assertTrue(s.available)
        p = s.predict("被告打人，【姓名】受傷")
        self.assertEqual(len(p), 6)
        self.assertAlmostEqual(sum(p), 1.0, places=3)
        self.assertEqual((s.meta["selected_epoch"], s.meta["n_test"], s.meta["accuracy"]), (14, 20, 0.7))

    def test_long_text_is_truncated(self):
        save_tiny_checkpoint(self.root / "criminal_term")
        s = CriminalTermService(self.root)
        with unittest.mock.patch("backend.criminal_service.TERM_MAX_LEN", 64):
            self.assertEqual(len(s.predict("打" * 5000)), 6)

    def test_force_mock(self):
        save_tiny_checkpoint(self.root / "criminal_term")
        self.assertFalse(CriminalTermService(self.root, force_mock=True).available)

    def test_rejects_incomplete_checkpoint(self):
        save_tiny_checkpoint(self.root / "criminal_term", drop="head.weight")
        with self.assertRaisesRegex(ValueError, "少了"):
            CriminalTermService(self.root)

    def test_service_uses_electra_for_sentence(self):
        train_artifacts(self.root)
        svm_only = CriminalService(self.root).report(DRUNK)
        save_tiny_checkpoint(self.root / "criminal_term")
        c = CriminalService(self.root)
        r = c.report(DRUNK)
        expected = c.term.predict(c.query(DRUNK))
        for charge in r["charges"]:
            self.assertEqual([b["label"] for b in charge["sentence"]], service.BUCKETS)
            self.assertEqual([b["share"] for b in charge["sentence"]], expected)
        self.assertNotEqual(r["charges"][0]["sentence"], svm_only["charges"][0]["sentence"])
        self.assertEqual(r["charges"][0]["name"], svm_only["charges"][0]["name"])      # 罪名仍是 SVM 的
        self.assertEqual((r["model"]["sentence_description"], r["model"]["bucket_accuracy"]), ("法律 ELECTRA", 0.7))
        self.assertNotIn("sentence_description", svm_only["model"])


if __name__ == "__main__":
    unittest.main()
