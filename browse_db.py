"""
用 Datasette 在瀏覽器瀏覽 judgments.db。網頁本身是唯讀的，不會改動資料。

    python browse_db.py            # 開在 http://127.0.0.1:8001
    python browse_db.py -p 8002    # 其餘參數原樣轉交給 datasette

啟動前會替分面用的幾個欄位補建索引（已存在就跳過），並放寬 Datasette 預設
的查詢時間上限：資料庫有 8 萬多筆、近 2 GB，分面統計超過預設的 200 毫秒就會
被放棄。
"""

import os
import sqlite3
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))

SETTINGS = {
    "sql_time_limit_ms": "10000",    # 單一查詢上限（預設 1000）
    "facet_time_limit_ms": "5000",   # 分面統計上限（預設 200）
    "truncate_cells_html": "300",    # 列表頁長文字截斷字數（預設 2048）
    "suggest_facets": "off",         # 不對每個欄位試算建議分面（每個都要掃整張表）
}


# 分面與預設排序用到的欄位。這些欄位排在 full_text 之後，沒有索引時每次統計
# 都要讀過整個 2 GB 的檔案（表格頁約 8 秒）；有索引後只讀索引本身。
# 索引只加快查詢、不改動任何資料；html_parser.py --reparse 清空重建時也會保留。
INDEXED_COLUMNS = ("court", "judgment_type", "case_type", "case_kind_category", "judgment_date")


def ensure_indexes(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(judgments)")}
        for col in INDEXED_COLUMNS:
            if col in cols:
                conn.execute(f"CREATE INDEX IF NOT EXISTS idx_judgments_{col} ON judgments({col})")
        conn.commit()
    finally:
        conn.close()


def main() -> int:
    db_path = os.path.join(ROOT, "judgments.db")
    if not os.path.exists(db_path):
        print(f"找不到資料庫：{db_path}")
        return 1
    ensure_indexes(db_path)
    cmd = [sys.executable, "-m", "datasette", "serve", db_path,
           "--metadata", os.path.join(ROOT, "datasette_metadata.yml")]
    for k, v in SETTINGS.items():
        cmd += ["--setting", k, v]
    cmd += sys.argv[1:]
    # Windows 預設用系統編碼（cp1252／cp950）讀設定檔，中文會解碼失敗
    env = dict(os.environ, PYTHONUTF8="1")
    try:
        return subprocess.call(cmd, env=env)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
