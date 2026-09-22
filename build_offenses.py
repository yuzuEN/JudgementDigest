"""從 html_cache 的附表建立 offenses 表（一列 = 一個被告的一個罪的一個宣告刑）。

不動 judgments 表，可重複執行（每次重建 offenses）。
用法: python build_offenses.py [--keyword ADV:TPD:M] [-o offenses.xlsx]
      加 -o 時建表後匯出 Excel；只想匯出、不重建可加 --export-only。
"""

import argparse
import sqlite3

from appendix_parser import extract_appendix_offenses

DB_PATH = "judgments.db"


def build(keyword: str = "ADV:TPD:M") -> None:
    """重建 offenses 表。

    建在暫存表 offenses_new，全部寫入成功後才 DROP 舊表、改名頂替，
    這樣中途出錯（例如某份 HTML 解析炸掉）不會讓既有的 offenses 表被清空；
    單一檔案的錯誤只跳過該檔並計入 errors，不會中斷整批。
    """
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
        DROP TABLE IF EXISTS offenses_new;
        CREATE TABLE offenses_new (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            crawl_id    INTEGER REFERENCES crawl_records(id),
            case_number TEXT,
            table_idx   INTEGER,
            row_no      TEXT,
            defendant   TEXT,
            law         TEXT,
            charge      TEXT,
            sentence    TEXT,
            months      INTEGER,
            days        INTEGER,
            fine        INTEGER,
            fine_type   TEXT,
            raw         TEXT
        );
    """)
    rows = conn.execute(
        "SELECT c.id, c.case_number, c.html_file, j.defendant FROM crawl_records c "
        "LEFT JOIN judgments j ON j.crawl_id = c.id "
        "WHERE c.keyword LIKE ? AND c.case_number LIKE '%判決' "
        "AND instr(COALESCE(j.full_text, ''), '判決') > 0", (keyword + "%",)).fetchall()
    hit = n = errors = 0
    for crawl_id, case_number, html_file, defendants in rows:
        if not html_file:
            errors += 1
            continue
        try:
            with open(html_file, encoding="utf-8") as f:
                html = f.read()
            offs = extract_appendix_offenses(
                html, names=[nm.strip() for nm in (defendants or "").split("；") if nm.strip()])
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            errors += 1
            print(f"  [WARN] 解析失敗，略過：{html_file}（{exc}）")
            continue
        if offs:
            hit += 1
        conn.executemany(
            "INSERT INTO offenses_new (crawl_id, case_number, table_idx, row_no, defendant, law, charge,"
            " sentence, months, days, fine, fine_type, raw) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(crawl_id, case_number, o["table"], o["no"], o["defendant"], o["law"], o["charge"],
              o["sentence"], o["months"], o["days"], o["fine"], o["fine_type"], o["raw"]) for o in offs])
        n += len(offs)
    conn.executescript("""
        DROP TABLE IF EXISTS offenses;
        ALTER TABLE offenses_new RENAME TO offenses;
        CREATE INDEX idx_offenses_case ON offenses(case_number);
    """)
    conn.commit()
    conn.close()
    err_note = f"，{errors} 筆解析失敗已略過" if errors else ""
    print(f"判決 {len(rows)} 筆，其中 {hit} 筆有附表宣告刑，共寫入 {n} 列{err_note}")


EXPORT_COLUMNS = [
    ("裁判字號", "case_number"), ("裁判日期", "judgment_date"), ("被告", "defendant"),
    ("法條", "law"), ("罪名", "charge"), ("宣告刑", "sentence"),
    ("宣告刑（月）", "months"), ("拘役（日）", "days"), ("罰金（元）", "fine"), ("罰金類型", "fine_type"),
    ("附表列號", "row_no"), ("原文", "raw"),
]


def export_excel(path: str) -> int:
    """把 offenses 表匯出成 Excel（一列一個被告×罪×宣告刑），回傳列數。"""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    conn = sqlite3.connect(DB_PATH)
    if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='offenses'").fetchone():
        conn.close()
        raise SystemExit("offenses 表不存在，請先不加 --export-only 跑一次建表。")
    cols = ", ".join(f"o.{c}" if c != "judgment_date" else "j.judgment_date" for _, c in EXPORT_COLUMNS)
    rows = conn.execute(
        f"SELECT {cols} FROM offenses o LEFT JOIN judgments j ON j.crawl_id = o.crawl_id "
        "ORDER BY j.judgment_date, o.case_number, o.id").fetchall()
    conn.close()

    wb = Workbook()
    ws = wb.active
    ws.title = "附表宣告刑"
    ws.append([name for name, _ in EXPORT_COLUMNS])
    for row in rows:
        ws.append(list(row))
    for cell in ws[1]:
        cell.font = Font(color="FFFFFF", bold=True)
        cell.fill = PatternFill("solid", fgColor="1F3864")
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    for col, width in zip("ABCDEFGHIJKL", (38, 14, 16, 30, 28, 20, 12, 10, 14, 10, 10, 60)):
        ws.column_dimensions[col].width = width
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    wb.save(path)
    return len(rows)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--keyword", default="ADV:TPD:M")
    ap.add_argument("-o", "--output", default="", help="匯出 Excel 檔名")
    ap.add_argument("--export-only", action="store_true", help="不重建 offenses 表，只匯出現有內容（需搭配 -o）")
    args = ap.parse_args()
    if args.export_only and not args.output:
        ap.error("--export-only 需要搭配 -o 指定輸出檔名")
    if not args.export_only:
        build(args.keyword)
    if args.output:
        print(f"匯出 {export_excel(args.output)} 列 → {args.output}")
