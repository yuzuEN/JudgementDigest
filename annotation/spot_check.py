"""
v0.3 的驗證（沒有法律專業人員時的做法，見手冊第七節）：

  export  1. 模型三次的自身一致性
          2. 隨機樣本中各標籤的比例（多數決）
          3. 輸出抽查表：DAM、SUB、EV、PROC 各挑最多 n 段「模型標了該標籤」的段落，
             附上引文與自動線索檢查，由人工判斷是否符合手冊的定義
  score   讀回填好的抽查表，算各標籤的精確度與 95% Wilson 信賴區間

抽查只能估「精確度」（模型標出來的對不對），不能估「召回率」（模型漏標多少）。

用法：
    python -m annotation.spot_check export            # → artifacts/annotation_civil_v1/抽查表_v0.3.xlsx
    python -m annotation.spot_check score             # 讀回填好的抽查表
"""
import argparse
import collections
from contextlib import closing
import itertools
import math
import random
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from annotation.cues import CUES, INTEREST_SERVICE  # noqa: E402
from annotation.prompts_v3 import PROMPT_VERSION  # noqa: E402

OUT_DIR = config.ARTIFACTS_DIR / "annotation_civil_v1"
CHECK_LABELS = ("DAM", "SUB", "EV", "PROC")
# 每個標籤優先從哪一批抽：稀有的從加抽批，常見的從隨機批
PREFER_BATCH = {"DAM": "enriched:DAM", "SUB": "enriched:SUB", "EV": "random", "PROC": "enriched:SERVICE"}
VERDICTS = ("符合", "不符合", "不確定")


def load_runs(con: sqlite3.Connection, prompt_version: str = PROMPT_VERSION) -> dict:
    """{sample_id: {run_no: {label: (polarity, quote)}}}；同一段同時有 NONE 和其他標籤時去掉 NONE。"""
    runs = collections.defaultdict(lambda: collections.defaultdict(dict))
    for sid, run, label, pol, quote in con.execute(
            "SELECT sample_id, run_no, label, polarity, quote FROM annotations WHERE prompt_version = ?",
            (prompt_version,)):
        runs[sid][run][label] = (pol, quote)
    for rr in runs.values():
        for labels in rr.values():
            if len(labels) > 1:
                labels.pop("NONE", None)
    return runs


def majority(rr: dict) -> set:
    """超過半數的 run 出現的標籤（三次就是至少兩次）。"""
    need = len(rr) // 2 + 1
    cnt = collections.Counter(l for labels in rr.values() for l in labels)
    m = {l for l, k in cnt.items() if k >= need}
    if len(m) > 1:
        m.discard("NONE")
    return m or {"NONE"}


def wilson(k: int, n: int, z: float = 1.96) -> tuple:
    """比例 k/n 的 Wilson 信賴區間。小樣本、比例接近 0 或 1 時比常態近似穩定。"""
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (centre - half, centre + half)


def export(db: Path, out: Path, n_per_label: int, seed: int) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.worksheet.datavalidation import DataValidation

    with closing(sqlite3.connect(db)) as con:   # Windows 不能刪除還開著的資料庫檔
        runs = load_runs(con)
        paras = {r[0]: r[1:] for r in con.execute("SELECT sample_id, batch, para_text FROM paragraphs")}
    if not runs:
        print("還沒有任何標註結果。")
        return

    # 1. 模型自身一致性
    run_ids = sorted({r for rr in runs.values() for r in rr})
    print("== 模型三次的一致性（標籤集合完全相同）==")
    for a, b in itertools.combinations(run_ids, 2):
        both = [s for s in runs if a in runs[s] and b in runs[s]]
        same = sum(set(runs[s][a]) == set(runs[s][b]) for s in both)
        print(f"  run{a} vs run{b}：{same}/{len(both)} = {same / max(len(both), 1):.1%}")

    # 2. 隨機樣本中的比例
    maj = {s: majority(rr) for s, rr in runs.items()}
    rand = [s for s in maj if paras.get(s, ("",))[0] == "random"]
    print(f"\n== 隨機樣本（{len(rand)} 段）中各標籤的比例（多數決）==")
    cnt = collections.Counter(l for s in rand for l in maj[s])
    for label, k in cnt.most_common():
        lo, hi = wilson(k, len(rand))
        print(f"  {label:<7} {k:>4} 段　{k / len(rand):6.1%}　95% CI [{lo:.1%}, {hi:.1%}]")

    # 3. 抽查表
    rng = random.Random(seed)
    wb = Workbook()
    ws = wb.active
    ws.title = "填寫說明"
    for i, line in enumerate([
        "抽查表（手冊 v0.3）",
        "每一列是模型（三次多數決）標了某個標籤的段落。請依手冊 v0.3 的定義，判斷這個標籤對不對。",
        "「判定」欄選：符合／不符合／不確定。不確定的請在備註寫原因。",
        "「線索」欄是程式自動檢查：段落裡有沒有手冊列出的線索。有線索不代表一定對，沒線索也不代表一定錯。",
        "PROC 的列特別注意：段落如果只是「起訴狀繕本送達翌日起」算利息，依手冊不應標 PROC。",
        "只判斷「標出來的對不對」，不用找漏標的。",
    ], start=1):
        ws.cell(i, 1, line).font = Font(bold=(i == 1), size=14 if i == 1 else 11)
    ws.column_dimensions["A"].width = 110

    headers = ["sample_id", "批次", "標籤", "傾向／方向", "引文", "待標段落", "線索", "判定", "備註"]
    widths = [10, 16, 8, 12, 36, 80, 14, 10, 30]
    fill = PatternFill("solid", fgColor="FFDDDDDD")
    for label in CHECK_LABELS:
        ws = wb.create_sheet(label)
        for j, (h, w) in enumerate(zip(headers, widths), start=1):
            c = ws.cell(1, j, h)
            c.font, c.fill = Font(bold=True), fill
            ws.column_dimensions[chr(64 + j)].width = w
        ws.freeze_panes = "A2"
        cand = [s for s in maj if label in maj[s]]
        pref = [s for s in cand if paras[s][0] == PREFER_BATCH[label]]
        rest = [s for s in cand if paras[s][0] != PREFER_BATCH[label]]
        rng.shuffle(pref)
        rng.shuffle(rest)
        chosen = (pref + rest)[:n_per_label]
        for i, s in enumerate(sorted(chosen), start=2):
            batch, text = paras[s]
            pol, quote = next((runs[s][r][label] for r in sorted(runs[s]) if label in runs[s][r]), (None, ""))
            cue = CUES.get(label)
            if label == "PROC":
                hint = "利息起算" if INTEREST_SERVICE.search(text) else ""
            else:
                hint = "有" if cue and cue.search(text) else "無"
            for j, v in enumerate([s, batch, label, pol, quote, text, hint, None, None], start=1):
                ws.cell(i, j, v).alignment = Alignment(wrap_text=True, vertical="top")
            ws.row_dimensions[i].height = 110
        dv = DataValidation(type="list", formula1='"' + ",".join(VERDICTS) + '"', allow_blank=True)
        dv.add(f"H2:H{max(len(chosen) + 1, 2)}")
        ws.add_data_validation(dv)
        print(f"  抽查表 {label}：{len(chosen)} 段（模型標了 {len(cand)} 段）")

    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    print(f"\n已輸出 {out}")


def score(sheet: Path) -> None:
    from openpyxl import load_workbook
    wb = load_workbook(sheet, read_only=True)   # 唯讀模式會一直開著檔案，最後要 close
    print("== 精確度（模型標出來的，人工判定符合的比例）==")
    for label in CHECK_LABELS:
        if label not in wb.sheetnames:
            continue
        verdicts = [r[7] for r in wb[label].iter_rows(min_row=2, values_only=True) if r and r[0] is not None]
        ok, bad, unsure = (sum(v == x for v in verdicts) for x in VERDICTS)
        blank = sum(v is None for v in verdicts)
        n = ok + bad
        head = f"  {label:<5} 符合 {ok}／不符合 {bad}／不確定 {unsure}／未填 {blank}　"
        if n == 0:
            print(head + "尚未判定")
            continue
        lo, hi = wilson(ok, n)
        print(head + f"精確度 {ok / n:.1%}　95% CI [{lo:.1%}, {hi:.1%}]（不確定與未填不計入）")
    wb.close()


def main():
    ap = argparse.ArgumentParser(description="v0.3 線索抽查")
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export")
    e.add_argument("--db", type=Path, default=OUT_DIR / "annotation.sqlite")
    e.add_argument("--out", type=Path, default=OUT_DIR / "抽查表_v0.3.xlsx")
    e.add_argument("--n", type=int, default=25, help="每個標籤最多抽幾段")
    e.add_argument("--seed", type=int, default=20261106)
    s = sub.add_parser("score")
    s.add_argument("--sheet", type=Path, default=OUT_DIR / "抽查表_v0.3.xlsx")
    args = ap.parse_args()
    if args.cmd == "export":
        export(args.db, args.out, args.n, args.seed)
    else:
        score(args.sheet)


if __name__ == "__main__":
    main()
