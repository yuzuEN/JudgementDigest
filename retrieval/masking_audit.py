"""
遮名抽查（A1）：從上線用的檢索資料抽判決，匯出給人看的標註表；標完再算漏遮率。

    python -m retrieval.masking_audit sample --out data_masking/audit_1.xlsx                 # 抽 200 件
    python -m retrieval.masking_audit sample --out data_masking/audit_2.xlsx --exclude-from data_masking/audit_1.xlsx --seed 2
    python -m retrieval.masking_audit sample --out data_masking/audit_1_new.xlsx --ids-from data_masking/audit_1.xlsx \\
        --cases <新建的 cases.sqlite>                                                       # 同一批判決，看新版遮得如何
    python -m retrieval.masking_audit score data_masking/audit_1.xlsx                         # 標完後算漏遮率

讀的是 cases.sqlite 的 sections（相似判決與導讀實際顯示的三段文字，已經遮過名），不碰正式資料庫。
標註表含判決內容，存在 data_masking/（不進版控），不要傳到群組以外的地方。
"""
import argparse
import random
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import pandas as pd

import config
from retrieval.masking import PATTERNS, _NOT_NAME, _SURNAMES, usable_person_names

SECTIONS = {"claim": "原告主張", "defense": "被告答辯", "court": "法院判斷"}
LEAK_COLUMNS = {"漏遮姓名": "name", "漏遮車牌": "plate", "漏遮身分證": "id", "漏遮地址": "address", "漏遮其他": "other"}
EXTRA_COLUMNS = ["誤遮", "備註"]
CELL_LIMIT = 30_000          # Excel 一格最多 32,767 字，長的段落分成幾列
SHEET = "抽查"

GUIDE = [
    ("這份表是什麼", "從上線用的相似判決資料隨機抽出的判決，每件分成原告主張、被告答辯、法院判斷三段（太長的再切成幾列）。"
                   "文字就是網站上會顯示的樣子，【原告】【關係人】【地址】等是已經遮掉的地方。"),
    ("要做什麼", "把每一列從頭讀到尾，看到沒有遮掉、可以認出特定人的資訊，就填進對應的欄位。"),
    ("怎麼填", "一格可以填多個，用「、」分開，例如：王大明、林小華。同一個名字在同一件判決出現好幾次只要寫一次。"
             "沒有漏遮就留白。"),
    ("漏遮姓名", "自然人的全名（王大明）或可以認出人的名字（大明、阿華）。法院已經遮成「王○明」的不算。"
             "法官、書記官、律師的名字也請填，組內再決定要不要遮。"),
    ("漏遮車牌", "像 ABC-1234、123-ABC 的車牌號碼。法院遮過的 000-0000 不算。"),
    ("漏遮身分證／地址", "身分證字號；可以找到住處的地址（要有門牌號碼）。只有路名、沒有門牌的不算。"),
    ("漏遮其他", "其他可以認出特定人的資訊，例如帳號、病歷號、學校班級加座號。"),
    ("誤遮", "不該遮卻被遮掉、讓內容看不懂的地方，例如把「陳述」遮成【關係人】。用來衡量遮太多的代價。"),
    ("提示欄", "程式用簡單規則找的「可能漏遮」，只是幫你注意，不代表一定是漏遮，也可能有沒提示到的。"),
]

_HINT_NAME = re.compile(r"(?<![一-鿿○〇])" + _NOT_NAME + r"([" + _SURNAMES + r"][一-鿿]{2})(?=[於向稱並、，即係已之為與和到])")
_HINT_ID = re.compile(r"(?<![A-Za-z0-9])[A-Z][12489][0-9]{8}(?![0-9])")
_PLATE = dict(PATTERNS)["plate"]


def hints(text: str, ner_names: Iterable[str] = ()) -> str:
    """程式找的可能漏遮（給標註的人參考）。ner_names：人名辨識在這件判決找到的名字，還留在文字裡的會列出來。"""
    out = []
    ner_left = [n for n in usable_person_names(ner_names) if n in text]
    if ner_left:
        out.append("人名辨識：" + "、".join(ner_left[:20]))
    plates = sorted({p for p in (m.group("v") or m.group() for m in _PLATE.finditer(text))
                     if not re.fullmatch(r"[0-]+", p)})      # 000-0000 是法院遮過的
    if plates:
        out.append("車牌？" + "、".join(plates))
    if _HINT_ID.search(text):
        out.append("身分證？" + "、".join(sorted(set(_HINT_ID.findall(text)))))
    names = sorted(set(_HINT_NAME.findall(text)))
    if names:
        out.append("人名？" + "、".join(names[:15]))
    return "；".join(out)


def read_ids(paths: Iterable[Path]) -> List[int]:
    ids = set()
    for p in paths:
        ids.update(int(i) for i in pd.read_excel(p, sheet_name=SHEET).id)
    return sorted(ids)


def sample_rows(cases: Path, n: int = 200, seed: int = 1, exclude: Iterable[int] = (),
                ids: Optional[Iterable[int]] = None, ner_names: Optional[Dict[int, List[str]]] = None) -> pd.DataFrame:
    with closing(sqlite3.connect(f"file:{cases}?mode=ro", uri=True)) as con:
        if ids is None:
            pool = sorted(set(r[0] for r in con.execute("SELECT id FROM sections")) - set(exclude))
            ids = random.Random(seed).sample(pool, min(n, len(pool)))
        ids = sorted(int(i) for i in ids)
        found = {}
        for start in range(0, len(ids), 500):
            part = ids[start:start + 500]
            marks = ",".join("?" * len(part))
            for r in con.execute(f"SELECT s.id, c.case_number, s.claim, s.defense, s.court FROM sections s "
                                 f"JOIN cases c ON c.id = s.id WHERE s.id IN ({marks})", part):
                found[r[0]] = r
    rows = []
    for case_id in ids:
        if case_id not in found:
            raise SystemExit(f"{cases} 裡沒有 id {case_id}（是不是用了不同版本的檢索資料？）")
        _, number, *texts = found[case_id]
        for (key, label), text in zip(SECTIONS.items(), texts):
            text = text or ""
            parts = [text[i:i + CELL_LIMIT] for i in range(0, len(text), CELL_LIMIT)] or [""]
            for k, chunk in enumerate(parts):
                rows.append({"id": case_id, "字號": number,
                             "段落": label if len(parts) == 1 else f"{label}（{k + 1}/{len(parts)}）",
                             "文字": chunk, "提示": hints(chunk, (ner_names or {}).get(case_id, ())),
                             **{c: "" for c in list(LEAK_COLUMNS) + EXTRA_COLUMNS}})
    return pd.DataFrame(rows)


def write_sheet(rows: pd.DataFrame, out: Path, settings: Dict[str, str]) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(out, engine="openpyxl") as w:
        rows.to_excel(w, sheet_name=SHEET, index=False)
        pd.DataFrame(GUIDE, columns=["項目", "說明"]).to_excel(w, sheet_name="說明", index=False)
        pd.DataFrame(list(settings.items()), columns=["設定", "值"]).to_excel(w, sheet_name="設定", index=False)
        ws = w.sheets[SHEET]
        from openpyxl.styles import Alignment
        widths = {"A": 9, "B": 26, "C": 12, "D": 90, "E": 30}
        for col in "FGHIJKL":
            widths[col] = 16
        for col, width in widths.items():
            ws.column_dimensions[col].width = width
        for row in ws.iter_rows(min_row=2):
            for cell in row:
                cell.alignment = Alignment(wrap_text=True, vertical="top")
        ws.freeze_panes = "D2"
        guide = w.sheets["說明"]
        guide.column_dimensions["A"].width = 18
        guide.column_dimensions["B"].width = 100
        for row in guide.iter_rows(min_row=2):
            row[1].alignment = Alignment(wrap_text=True, vertical="top")
    return out


_SPLIT = re.compile(r"[、,，;；\n]+")


def items(cell) -> List[str]:
    if cell is None or (isinstance(cell, float) and pd.isna(cell)):
        return []
    return [x.strip() for x in _SPLIT.split(str(cell)) if x.strip()]


def score(rows: pd.DataFrame) -> pd.DataFrame:
    """每一類漏遮：有漏遮的件數、漏掉的個數（同一件判決同樣的字串只算一次）、每 100 件漏幾個。"""
    n_cases = rows.id.nunique()
    out = []
    for column in list(LEAK_COLUMNS) + ["誤遮"]:
        per_case = rows.groupby("id")[column].apply(lambda s: {x for cell in s for x in items(cell)})
        leaks = int(per_case.map(len).sum())
        out.append({"類別": column, "抽查件數": n_cases, "有問題的件數": int((per_case.map(len) > 0).sum()),
                    "個數": leaks, "每 100 件": round(leaks / n_cases * 100, 1) if n_cases else 0.0})
    return pd.DataFrame(out)


def main():
    ap = argparse.ArgumentParser(description="遮名抽查：匯出標註表、計算漏遮率")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sample", help="抽判決，匯出標註表（.xlsx）")
    s.add_argument("--out", required=True, type=Path)
    s.add_argument("--cases", type=Path, default=Path(config.ARTIFACTS_DIR) / "retrieval_civil_v4" / "cases.sqlite")
    s.add_argument("--n", type=int, default=200)
    s.add_argument("--seed", type=int, default=1)
    s.add_argument("--exclude-from", type=Path, nargs="*", default=[], help="不要抽到這些標註表裡的判決")
    s.add_argument("--ids-from", type=Path, help="不重新抽，改匯出這份標註表裡同樣的判決")
    s.add_argument("--ner-names", type=Path, help="retrieval.ner 的輸出；還沒遮掉的人名會列在提示欄")
    c = sub.add_parser("score", help="讀填好的標註表，算漏遮率")
    c.add_argument("sheet", type=Path)
    a = ap.parse_args()

    if a.cmd == "sample":
        ids = read_ids([a.ids_from]) if a.ids_from else None
        ner = None
        if a.ner_names:
            from retrieval.ner import read_names
            ner = read_names(a.ner_names)
        rows = sample_rows(a.cases, a.n, a.seed, read_ids(a.exclude_from), ids, ner)
        meta = a.cases.parent / "meta.json"
        settings = {"檢索資料": str(a.cases), "檢索資料建立時間": "", "抽樣": f"{rows.id.nunique()} 件，seed {a.seed}",
                    "排除": "、".join(map(str, a.exclude_from)) or "無",
                    "沿用判決": str(a.ids_from or "否")}
        if meta.exists():
            import json
            m = json.loads(meta.read_text(encoding="utf-8"))
            settings["檢索資料建立時間"] = m.get("built_at", "")
            settings["遮名方式"] = m.get("masking", "規則")
        print(f"已存到 {write_sheet(rows, a.out, settings)}（{rows.id.nunique()} 件、{len(rows)} 列）")
    else:
        result = score(pd.read_excel(a.sheet, sheet_name=SHEET))
        print(result.to_string(index=False))


if __name__ == "__main__":
    main()
