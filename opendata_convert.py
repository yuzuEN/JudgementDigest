# -*- coding: utf-8 -*-
"""
把 opendata_download.py 下載的每月裁判書 RAR，轉成跟爬蟲資料庫相同欄位的 SQLite（每年一個檔）。

只處理「地方法院刑事」與「簡易庭刑事」資料夾、只留判決（「刑事判決」「刑事簡易判決」），
去掉裁定與附帶民事以外的其他文書；Delete-Infor（已下架）清單上的判決不收。
正文切段沿用 html_parser.parse_html：把 JFULL 每一行包成一個 <div>，標題行（主文、事實及理由…）
由 html_parser 既有的標題白名單辨識，所以結構化欄位跟爬蟲資料一致。

用法:
    python opendata_convert.py --months 202405                 # 先轉一個月檢查
    python opendata_convert.py --months 201601-202512          # 全部
    python opendata_convert.py --months 201601-202512 --delete-rar   # 轉完刪 RAR 省空間

輸出：data_opendata/db/刑事判決_全國地院_{年}.db
"""

import argparse
import csv
import glob
import html
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor

import html_parser
from opendata_download import OUT, SEVEN_ZIP, month_list

DB_DIR = os.path.join(OUT, "db")
URL = "https://judgment.judicial.gov.tw/FJUD/data.aspx?ty=JD&id={}&ot=in"
WANT_FOLDER = re.compile(r"(地方法院|簡易庭(\(.*?\))?)刑事$")
TITLE_RE = re.compile(r"刑事(簡易)?判決")            # 第一行；「刑事附帶民事訴訟判決」不算
CIVIL_RE = re.compile(r"附帶民事")

EXTRA_COLUMNS = [("jid", "TEXT"), ("jtitle", "TEXT"), ("jpdf", "TEXT"),
                 ("folder", "TEXT"), ("proceeding", "TEXT"), ("source_file", "TEXT")]


def deleted_ids():
    path = os.path.join(OUT, "Delete-Infor.csv")
    if not os.path.exists(path):
        print("（沒有 Delete-Infor.csv，不過濾已下架判決）")
        return set()
    with open(path, encoding="utf-8-sig", newline="") as f:
        return {row["裁判ID"].strip() for row in csv.DictReader(f)}


def open_db(year):
    os.makedirs(DB_DIR, exist_ok=True)
    path = os.path.join(DB_DIR, f"刑事判決_全國地院_{year}.db")
    # 借用 html_parser.init_db 建表：欄位（含結構化欄位）與爬蟲資料庫完全相同，也不必先有 judgments.db
    saved, html_parser.DB_PATH = html_parser.DB_PATH, path
    try:
        html_parser.init_db()
    finally:
        html_parser.DB_PATH = saved
    conn = sqlite3.connect(path)
    have = {r[1] for r in conn.execute("pragma table_info(judgments)")}
    for col, typ in EXTRA_COLUMNS:
        if col not in have:
            conn.execute(f"alter table judgments add column {col} {typ}")
    conn.execute("create unique index if not exists ux_jid on judgments(jid)")
    return conn


def proceeding(jcase, first_line):
    if "附民" in jcase or CIVIL_RE.search(first_line):
        return "附帶民事"
    if "上" in jcase:
        return "上訴審"
    return "第一審"


def to_row(d, folder):
    """一份開放資料 JSON → html_parser 的解析結果 dict（欄位同爬蟲資料庫）。"""
    full = d.get("JFULL") or ""
    lines = [ln for ln in full.replace("\r\n", "\n").split("\n")]
    first = re.sub(r"\s+", "", lines[0] if lines else "")
    court = re.sub(r"刑事$", "", folder)
    kind = "刑事簡易判決" if "簡易判決" in first else "刑事判決"
    case_number = f"{court} {d['JYEAR']} 年度 {d['JCASE']} 字第 {d['JNO']} 號{kind}"
    body = "".join(f"<div>{html.escape(ln)}</div>" for ln in lines)
    page = f'<html><body><div id="jud"><div class="htmlcontent">{body}</div></div></body></html>'
    jd = d.get("JDATE", "")
    parsed = html_parser.parse_html(page, crawl_id=None, keyword="開放資料",
                                    case_number_hint=case_number, court_hint=court,
                                    date_hint=f"{jd[:4]}-{jd[4:6]}-{jd[6:8]}",
                                    source_url=URL.format(d["JID"].replace(",", "%2c")))
    parsed["case_type"] = d.get("JTITLE") or parsed.get("case_type")   # 網頁版的「案由」＝開放資料的 JTITLE
    parsed.update({"jid": d["JID"], "jtitle": d.get("JTITLE"), "jpdf": d.get("JPDF"),
                   "folder": folder, "proceeding": proceeding(d.get("JCASE", ""), first)})
    return parsed, first


def parse_file(args):
    """子行程：讀一份 JSON，回傳 ("row", 解析結果) 或 (略過原因, 說明)。"""
    fn, folder, deleted = args
    try:
        with open(fn, encoding="utf-8-sig") as f:
            d = json.load(f)
        first = re.sub(r"\s+", "", (d.get("JFULL") or "").split("\n")[0])
        if not TITLE_RE.search(first):
            return "裁定等", None
        if d["JID"] in deleted:
            return "已下架", None
        row, _ = to_row(d, folder)
        return "row", row
    except Exception as exc:
        return "錯誤", f"{os.path.basename(fn)}：{exc}"


POOL = None


def write(conn, rows):
    cols = html_parser._BASE_INSERT_COLUMNS + [c for c, _ in html_parser.STRUCTURED_COLUMNS] + [c for c, _ in EXTRA_COLUMNS]
    ph = ",".join("?" * len(cols))
    conn.executemany(f"insert or replace into judgments ({','.join(cols)}) values ({ph})",
                     [tuple(r.get(c) for c in cols) for r in rows])


def convert_month(ym, deleted, delete_rar=False):
    rar = os.path.join(OUT, f"{ym}.rar")
    if not os.path.exists(rar):
        print(f"{ym}：沒有 {rar}，跳過")
        return None
    t0 = time.time()
    tmp = tempfile.mkdtemp(prefix=f"od_{ym}_", dir=OUT)
    try:
        # 只解「…地方法院刑事」「…簡易庭刑事」資料夾（-r 依萬用字元比對路徑）
        subprocess.run([SEVEN_ZIP, "x", "-y", "-sccUTF-8", f"-o{tmp}", rar,
                        f"{ym}\\*地方法院刑事\\*.json", f"{ym}\\*簡易庭*刑事\\*.json"],
                       capture_output=True, check=False)
        stat = {"檔案": 0, "判決": 0, "裁定等": 0, "已下架": 0, "錯誤": 0}
        by_year = {}
        jobs = []
        for folder_path in glob.glob(os.path.join(tmp, ym, "*")):
            folder = os.path.basename(folder_path)
            if WANT_FOLDER.search(folder):
                jobs += [(fn, folder) for fn in glob.glob(os.path.join(folder_path, "*.json"))]
        stat["檔案"] = len(jobs)
        # 解析是 CPU 密集（BeautifulSoup），分給多個行程；寫入資料庫留在主行程
        for kind, payload in POOL.map(parse_file, [(fn, folder, deleted) for fn, folder in jobs], chunksize=200):
            if kind == "row":
                payload["source_file"] = f"{ym}.rar"
                by_year.setdefault(payload["judgment_date"][:4], []).append(payload)
                stat["判決"] += 1
            else:
                stat[kind] += 1
                if kind == "錯誤" and stat["錯誤"] <= 3:
                    print(f"  解析失敗：{payload}")
        for year, rows in by_year.items():
            conn = open_db(year)
            write(conn, rows)
            conn.commit(); conn.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if delete_rar:
        os.remove(rar)
    print(f"{ym}：" + "、".join(f"{k} {v:,}" for k, v in stat.items()) + f"（{time.time() - t0:.0f}s）", flush=True)
    return stat


def main():
    ap = argparse.ArgumentParser(description="開放資料 RAR → 全國地院刑事判決 SQLite")
    ap.add_argument("--months", required=True)
    ap.add_argument("--delete-rar", action="store_true", help="每月轉完刪掉 RAR（要用時可重新下載）")
    args = ap.parse_args()
    global POOL
    deleted = deleted_ids()
    POOL = ProcessPoolExecutor(max_workers=max(1, (os.cpu_count() or 2) - 2))
    total = {}
    for ym in month_list(args.months):
        s = convert_month(ym, deleted, args.delete_rar)
        for k, v in (s or {}).items():
            total[k] = total.get(k, 0) + v
    print("合計：" + "、".join(f"{k} {v:,}" for k, v in total.items()))


if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    main()
