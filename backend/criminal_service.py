"""
刑事：罪名、法條、刑度分布、相似判決，以及（目前停用的）ELECTRA 刑期模型。

模型（artifacts/criminal_v1）與檢索資料（artifacts/retrieval_criminal_v1）在啟動時讀進記憶體。
沒有模型時整個刑事回傳示例資料（mock = true）；有模型、沒有檢索資料時 similar 是空清單，前端顯示「開發中」。
相似判決只在「含預測的第一個罪名」的判決裡找，這類判決太少時才放寬到全部。
每個罪名另外統計相似判決中含這個罪名的案件的宣告刑分布（similar_sentence），和模型推估並列。
刑事判決沒有判決導讀，列表附司法院的原文網址。

刑期目前用罪名模型（SVM）的 charges[].sentence（6 區間，含拘役、罰金）。
檔案下半部的 CriminalTermService（法律 ELECTRA，只估有期徒刑）保留著，backend/main.py 裡沒有啟用；
要換回來時打開 main.py 裡註解掉的幾行，並在 requirements.txt 裝回 torch、transformers。
"""
import json
import logging
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

from backend import mock
from criminal.models import lay_terms, service as model_service
from retrieval import criminal as retrieval_criminal
from retrieval.engine import TfidfIndex

N_SHOWN = 10
N_CANDIDATES = 40         # 列表從這麼多件裡挑（要去掉摘要開頭相同的制式判決）
DUPLICATE_PREFIX = 40
MIN_SAME_CHARGE = 10      # 含這個罪名的判決少於這個數時，改在全部判決中找
N_SENTENCE_STATS = 50     # 每個罪名的宣告刑分布：取最相似、含這個罪名、有單一宣告刑的這麼多件
MIN_SENTENCE_STATS = 10   # 少於這個數不顯示（件數太少，比例沒有意義）


class CriminalService:
    def __init__(self, artifacts_dir: Path, force_mock: bool = False):
        self.model = self.meta = self.index = None
        self.db_path: Optional[Path] = None
        if force_mock:
            return
        model_dir = model_service.artifact_dir(artifacts_dir)
        if (model_dir / "model.joblib").exists():
            self.model, self.meta = model_service.load(model_dir)
        retrieval_dir = retrieval_criminal.artifact_dir(artifacts_dir)
        if (retrieval_dir / "index.joblib").exists():
            self.index = TfidfIndex.load(retrieval_dir / "index.joblib")
            self.db_path = retrieval_dir / "cases.sqlite"
            rows = self._query("SELECT charges, sentence FROM cases ORDER BY row")
            assert len(rows) == len(self.index), "刑事檢索索引和案件清單的件數不同，請重新執行 python -m retrieval.criminal"
            self.charges = [set(json.loads(r[0])) for r in rows]
            self.buckets = np.array([-1 if b is None else b for b in
                                     (model_service.bucket_of_text(r[1]) for r in rows)])

    @property
    def mock(self) -> bool:
        return self.model is None

    def _query(self, sql: str, params=()) -> List[sqlite3.Row]:
        with closing(sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)) as con:
            con.row_factory = sqlite3.Row
            return con.execute(sql, params).fetchall()

    def model_info(self) -> Dict:
        m = self.meta.get("metrics", {})
        return {"name": self.meta["name"], "description": "犯罪事實的 TF-IDF ＋ SVM（機率經過校正）",
                **{k: m.get(k) for k in ("n_test", "charge_top1", "bucket_accuracy", "bucket_within_one")}}

    @staticmethod
    def query(text: str) -> str:
        """使用者描述 → 模型與檢索的輸入：相容字形轉一般字，口語換成判決書用語（criminal/models/lay_terms.py）。"""
        return lay_terms.to_legal(model_service.normalize(text))

    def report(self, text: str) -> Dict:
        if self.mock:
            return mock.criminal_report()
        text = self.query(text)
        charges = self.model.predict(text)
        sim = self.index.scores(text) if self.index is not None else None
        for c in charges:
            c.update(self.sentence_stats(sim, c["name"]))
        return {"charges": charges, "similar": self.similar(text, charges[0]["name"] if charges else None, sim=sim),
                "model": self.model_info(), "mock": False}

    def sentence_stats(self, sim: Optional[np.ndarray], charge: str) -> Dict:
        """相似判決中、含這個罪名的案件，宣告刑落在各區間的比例；件數太少時不給。"""
        if sim is None:
            return {}
        rows, _ = self.index.top(sim, N_SENTENCE_STATS,
                                 np.array([charge in c for c in self.charges]) & (self.buckets >= 0))
        if len(rows) < MIN_SENTENCE_STATS:
            return {}
        counts = np.bincount(self.buckets[rows], minlength=len(model_service.BUCKETS))
        return {"similar_sentence": [{"label": b, "share": float(n / len(rows))}
                                     for b, n in zip(model_service.BUCKETS, counts)], "n_similar": int(len(rows))}

    def search(self, text: str, k: int) -> List[Dict]:
        if self.mock:
            return mock.criminal_report()["similar"][:k]
        text = self.query(text)
        return self.similar(text, self.model.predict(text)[0]["name"], k)

    def similar(self, text: str, charge: Optional[str], n: int = N_SHOWN, sim: Optional[np.ndarray] = None) -> List[Dict]:
        if self.index is None:
            return []
        sim = self.index.scores(text) if sim is None else sim
        allowed = np.array([charge in c for c in self.charges]) if charge else None
        if allowed is not None and allowed.sum() < MIN_SAME_CHARGE:
            allowed = None
        rows, sims = self.index.top(sim, N_CANDIDATES, allowed)
        if len(rows) == 0:
            return []
        marks = ",".join("?" * len(rows))
        found = {r["row"]: r for r in self._query(f"SELECT * FROM cases WHERE row IN ({marks})", [int(x) for x in rows])}
        out, seen = [], set()
        for row, s in zip(rows, sims):
            r = found[int(row)]
            if r["summary"][:DUPLICATE_PREFIX] in seen:
                continue
            seen.add(r["summary"][:DUPLICATE_PREFIX])
            out.append({"source": "criminal", "case_id": r["id"], "case_number": r["case_number"], "court": r["court"],
                        "year": r["year"], "mid": "、".join(json.loads(r["charges"])), "outcome": "有罪",
                        "similarity": round(float(s), 3), "summary": r["summary"], "sentence": r["sentence"],
                        "url": r["url"] or None})
            if len(out) == n:
                break
        return out


# ════════════════════════════════════════════════════════════════════════════
# 刑期：法律 ELECTRA（目前停用，main.py 沒有建立這個服務）
#
# 模型檔放在 artifacts/criminal_term/（Kaggle 訓練輸出的 checkpoints/fold_01）：
#     best.pt          state_dict（訓練時的 FrozenFastTextDualTermModel，beta = 0）
#     tokenizer/       斷詞器
#     encoder_config/  ELECTRA 設定，從這裡建 encoder，不連網下載
#     metrics.json     訓練紀錄（選用 epoch、驗證分數）
# beta = 0 時罪名／法條向量那條分支對輸出沒有影響，所以只建 encoder 和刑期的頭。
# 只估有期徒刑，不含拘役、罰金；2025 年判決上最可能區間猜中約六成。
# 沒有模型檔、或沒有裝 torch 時 available = False。
# ════════════════════════════════════════════════════════════════════════════
logger = logging.getLogger(__name__)

TERM_MODEL_DIR = "criminal_term"
TERM_MAX_LEN = 512
# 和訓練程式 baseline/evaluate.py 的 BINS 一致（單位：月）；第 7 類「無期／死刑」訓練資料裡沒有，不顯示
TERM_BUCKETS = ["1–2 個月", "3–6 個月", "7–12 個月", "1–3 年", "3–10 年", "10 年以上"]

# 訓練資料的人名是「乙○○」這種寫法，地址、車牌是 ○ 與 0；網站遮名用【姓名】這類標記，模型沒看過。
# 送進模型前換成訓練資料裡的寫法。只影響模型輸入，顯示給使用者的文字不變。
_TO_TRAINING_STYLE = [
    (re.compile(r"【姓名】|【關係人】|【原告】|【被告】"), "甲○○"),
    (re.compile(r"【地址】"), "○○市○○區○○路000號"),
    (re.compile(r"【電話】"), "0000000000"),
    (re.compile(r"【身分證字號】"), "Z000000000"),
    (re.compile(r"【電子郵件】"), "○○○"),
]


def to_training_style(text: str) -> str:
    for pattern, repl in _TO_TRAINING_STYLE:
        text = pattern.sub(repl, text)
    return text


class CriminalTermService:
    def __init__(self, artifacts_dir: Path, force_mock: bool = False):
        self.available = False
        self.meta: Dict = {}
        folder = Path(artifacts_dir) / TERM_MODEL_DIR
        if force_mock or not (folder / "best.pt").exists():
            return
        try:
            self._load(folder)
            self.available = True
        except ImportError as e:
            logger.warning("沒有裝 torch／transformers，刑期改回傳示例資料：%s", e)

    def _load(self, folder: Path) -> None:
        import torch
        from torch import nn
        from transformers import AutoTokenizer, ElectraConfig, ElectraModel

        torch.set_num_threads(max(1, min(4, torch.get_num_threads())))
        self._torch = torch
        self.tokenizer = AutoTokenizer.from_pretrained(folder / "tokenizer")

        class TermModel(nn.Module):
            """只留推論需要的部分；屬性名稱和訓練時一樣，權重才對得上。"""
            def __init__(self, config):
                super().__init__()
                self.encoder = ElectraModel(config)
                hidden = config.hidden_size
                self.head = nn.Module()
                self.head.mlp = nn.Sequential(nn.Linear(hidden, 512), nn.ReLU(), nn.Dropout(0.1),
                                              nn.Linear(512, 256), nn.ReLU(), nn.Dropout(0.1))
                self.head.bin = nn.Linear(256, 7)

            def forward(self, input_ids, attention_mask):
                cls = self.encoder(input_ids=input_ids, attention_mask=attention_mask).last_hidden_state[:, 0]
                return self.head.bin(self.head.mlp(cls))

        model = TermModel(ElectraConfig.from_pretrained(folder / "encoder_config"))
        state = torch.load(folder / "best.pt", map_location="cpu", weights_only=True)
        beta = float(state.get("beta", torch.tensor(0.0)))
        if beta != 0.0:
            raise ValueError(f"這個 checkpoint 的 beta = {beta}，需要罪名／法條向量，不能只用 ELECTRA 推論")
        wanted = model.state_dict().keys()
        missing = [k for k in wanted if k not in state]
        if missing:
            raise ValueError(f"checkpoint 少了 {len(missing)} 個權重，例如 {missing[:3]}")
        model.load_state_dict({k: state[k] for k in wanted})
        model.eval()
        self.model = model

        metrics_path = folder / "metrics.json"
        metrics = json.loads(metrics_path.read_text(encoding="utf-8")) if metrics_path.exists() else {}
        self.meta = {"name": "legal-electra-term",
                     "description": "法律 ELECTRA 刑期模型（有期徒刑區間）",
                     "selected_epoch": metrics.get("selected_epoch")}

    def predict_buckets(self, text: str) -> List[Dict]:
        """有期徒刑六個區間的機率，加總為 1。"""
        torch = self._torch
        enc = self.tokenizer([to_training_style(text)], truncation=True, max_length=TERM_MAX_LEN, return_tensors="pt")
        with torch.inference_mode():
            logits = self.model(enc["input_ids"], enc["attention_mask"])[0, :len(TERM_BUCKETS)]
        probs = logits.float().softmax(-1).tolist()
        return [{"label": label, "share": round(p, 4)} for label, p in zip(TERM_BUCKETS, probs)]

    def sentence(self, text: str) -> Optional[Dict]:
        if not self.available:
            return None
        return {"buckets": self.predict_buckets(text), "mock": False,
                "model": {"name": self.meta["name"], "description": self.meta["description"]}}
