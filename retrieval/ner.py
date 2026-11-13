"""
用 CKIP 的人名辨識，找出民事判決裡沒有寫稱謂的人名（masking.third_party_names 只認得「訴外人」「證人」後面的名字）。

只在建檢索資料前跑一次，結果存成檔案給 retrieval.build 讀；網站與部署不需要這個模型。
需要 torch 和 ckip-transformers，主程式的 .venv 沒有裝，另外建一個環境（建議有 GPU）：

    python -m venv .venv-ner
    .venv-ner/Scripts/pip install "torch>=2.6" --index-url https://download.pytorch.org/whl/cu124
    .venv-ner/Scripts/pip install ckip-transformers transformers==4.56.2 pandas scikit-learn joblib openpyxl

    .venv-ner/Scripts/python -m retrieval.ner --out data_masking/ner_civil.jsonl              # 全部（RTX 4060 約 8 小時）
    .venv-ner/Scripts/python -m retrieval.ner --out data_masking/ner_audit.jsonl --ids-from data_masking/audit_1.xlsx  # 只跑抽查的判決

輸出每行一件：{"id": 123, "names": ["王大明", ...]}。可以中斷，重跑同一個指令會略過已經有的 id。
names 是模型標成 PERSON 的原始結果；要拿來遮之前，retrieval.build 會再用 masking.usable_person_names 篩過。
會讀正式資料庫（judgments.db）整份，爬蟲在跑的時候不要執行。
"""
import argparse
import json
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import pandas as pd

SECTIONS = ("plaintiff_claim_text", "defendant_defense_text", "court_reasoning_text")


def read_names(path: Path) -> Dict[int, List[str]]:
    """讀 ner.py 的輸出：{判決 id: 人名}。"""
    out = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                out[int(r["id"])] = r["names"]
    return out


def ids_from_sheet(path: Path) -> List[int]:
    """抽查表（retrieval.masking_audit 匯出的 .xlsx）裡的判決 id。"""
    return sorted({int(i) for i in pd.read_excel(path, sheet_name="抽查").id})


def person_names(tokens) -> List[str]:
    return sorted({t.word.strip() for t in tokens if t.ner == "PERSON" and t.word.strip()})


# 速度與結果的取捨（RTX 4060，100 件判決實測，2026-11-13）：
#   use_delim=True 先在標點切句再辨識，比整段切 500 字多找到約 20% 的人名（不切句會漏掉「吳羽彤」「翁朝棟」這類），
#   但每句都補到 max_length，max_length=500 時每秒只有 0.44 件。句子本來就短，max_length=64 只比 128 少一個雜訊詞，
#   再加上 fp16，每秒約 5.6 件，15.8 萬件約 8 小時。
MAX_LENGTH = 64


def run(out: Path, only: Optional[Iterable[int]] = None, model: str = "bert-base", batch_size: int = 128,
        chunk: int = 500, device: int = 0) -> Path:
    from ckip_transformers.nlp import CkipNerChunker   # 只有這個指令需要，import 放這裡

    from retrieval.civil import load_expanded

    done = set(read_names(out)) if out.exists() else set()
    _, sections = load_expanded(only=only)
    sections = sections[~sections.id.isin(done)].reset_index(drop=True)
    print(f"要辨識 {len(sections):,} 件（已有 {len(done):,} 件）", flush=True)
    if sections.empty:
        return out
    ner = CkipNerChunker(model=model, device=device)
    if device >= 0:
        ner.model.half()        # 結果和 fp32 相同，快約 3 倍
    out.parent.mkdir(parents=True, exist_ok=True)
    started = time.time()
    with open(out, "a", encoding="utf-8") as f:
        for start in range(0, len(sections), chunk):
            part = sections.iloc[start:start + chunk]
            # 三段分開送：段落之間沒有關係，分開送也不會切在奇怪的地方
            texts = [row[col] or "" for row in part.to_dict("records") for col in SECTIONS]
            tokens = ner(texts, batch_size=batch_size, max_length=MAX_LENGTH, use_delim=True, show_progress=False)
            for i, case_id in enumerate(part.id):
                names = set()
                for t in tokens[i * len(SECTIONS):(i + 1) * len(SECTIONS)]:
                    names.update(person_names(t))
                f.write(json.dumps({"id": int(case_id), "names": sorted(names)}, ensure_ascii=False) + "\n")
            f.flush()
            n = min(start + chunk, len(sections))
            rate = n / (time.time() - started)
            print(f"  {n:,} / {len(sections):,}，每秒 {rate:.1f} 件，約剩 {(len(sections) - n) / rate / 60:.0f} 分鐘",
                  flush=True)
    return out


def main():
    ap = argparse.ArgumentParser(description="用 CKIP 找出民事判決裡的人名，給 retrieval.build 遮名")
    ap.add_argument("--out", required=True, type=Path, help="輸出的 .jsonl（已經有的 id 會略過）")
    ap.add_argument("--ids-from", type=Path, help="只跑這份抽查表（.xlsx）裡的判決")
    ap.add_argument("--model", default="bert-base", help="CKIP 模型：bert-base（預設，較準）或 albert-tiny（較快）")
    ap.add_argument("--batch-size", type=int, default=128)
    ap.add_argument("--device", type=int, default=0, help="GPU 編號；-1 用 CPU（很慢）")
    a = ap.parse_args()
    only = ids_from_sheet(a.ids_from) if a.ids_from else None
    print(f"已存到 {run(a.out, only, a.model, a.batch_size, device=a.device)}")


if __name__ == "__main__":
    main()
