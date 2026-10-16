# -*- coding: utf-8 -*-
"""
從司法院資料開放平臺下載每月裁判書 RAR（會員資料，需登入）。

帳號密碼在執行時由使用者自己輸入（getpass，不顯示、不存檔），只在記憶體中換成 Token 使用。

用法:
    python opendata_download.py --months 202405 --list-only     # 先下載一個月，看壓縮檔裡的結構
    python opendata_download.py --months 201801-202512           # 之後再批次下載
    python opendata_download.py --delete-list                    # 已下架的裁判書清單

壓縮檔放在 data_opendata/（.gitignore 已排除 data_*/）。
"""

import argparse
import getpass
import json
import os
import re
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request

BASE = "https://opendata.judicial.gov.tw"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data_opendata")
SEVEN_ZIP = r"C:\Program Files\7-Zip\7z.exe"

# 司法院憑證缺 Subject Key Identifier，Python 3.13 的嚴格模式會擋；仍驗證憑證鏈，只關嚴格檢查
CTX = ssl.create_default_context()
CTX.verify_flags &= ~ssl.VERIFY_X509_STRICT


def http(url, data=None, headers=None, method=None):
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"User-Agent": "Mozilla/5.0", **(headers or {})})
    return urllib.request.urlopen(req, timeout=120, context=CTX)


class Session:
    """登入一次；Token 快過期或被拒絕時，用同一次執行輸入的帳密自動重新登入（帳密只留在記憶體）。"""

    def __init__(self):
        self.account = input("司法院開放資料平臺 會員帳號：").strip()
        self._pwd = getpass.getpass("密碼（輸入時不會顯示）：")
        self.token, self.got_at = None, 0.0
        self.refresh()

    def refresh(self):
        body = json.dumps({"memberAccount": self.account, "pwd": self._pwd}).encode("utf-8")
        with http(f"{BASE}/api/MemberTokens", data=body, headers={"Content-Type": "application/json"}) as r:
            res = json.loads(r.read())
        if not res.get("token"):
            sys.exit(f"登入失敗：{res.get('message', res)}")
        self.token, self.got_at = res["token"], time.time()
        print(f"登入成功，Token 有效到 {res.get('expires')}")

    def headers(self):
        if time.time() - self.got_at > 5 * 3600:      # 有效 6 小時，提早 1 小時換新的
            print("Token 快過期，重新登入")
            self.refresh()
        return {"Authorization": f"Bearer {self.token}"}


def month_list(spec: str):
    out = []
    for part in spec.split(","):
        part = part.strip()
        m = re.fullmatch(r"(\d{6})(?:-(\d{6}))?", part)
        if not m:
            sys.exit(f"月份格式錯誤：{part}（例：202405 或 201801-202512）")
        a, b = m.group(1), m.group(2) or m.group(1)
        y, mo = int(a[:4]), int(a[4:])
        while f"{y}{mo:02d}" <= b:
            out.append(f"{y}{mo:02d}")
            mo += 1
            if mo == 13:
                y, mo = y + 1, 1
    return out


DELETE_LIST_FILESET = 70692   # 資料集「Delete-Infor裁判書」


def catalog():
    with http(f"{BASE}/data/api/rest/categories/051/resources") as r:
        data = json.loads(r.read())
    cat = {}
    for x in data:
        m = re.match(r"(\d{6})裁判書", x["title"])
        if m:
            cat[m.group(1)] = (x["title"], x["filesets"][0]["fileSetId"])
    return cat


def download(sess, fid, path, retry=True):
    tmp = path + ".part"
    try:
        r = http(f"{BASE}/api/FilesetLists/{fid}/file", headers=sess.headers())
    except urllib.error.HTTPError as e:
        if retry and e.code in (401, 403, 500):        # Token 失效時平臺可能回 401／500，重新登入再試一次
            print(f"  HTTP {e.code}，重新登入後再試一次")
            sess.refresh()
            return download(sess, fid, path, retry=False)
        raise
    with r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        got, t0, last = 0, time.time(), 0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            got += len(chunk)
            if time.time() - last > 5:
                last = time.time()
                speed = got / max(time.time() - t0, 1) / 1e6
                pct = f"{100 * got / total:.0f}%" if total else ""
                print(f"\r  {got / 1e9:.2f} GB {pct}  {speed:.1f} MB/s", end="", flush=True)
    os.replace(tmp, path)
    print(f"\r  完成 {os.path.getsize(path) / 1e9:.2f} GB，{(time.time() - t0) / 60:.1f} 分鐘")


def list_archive(path):
    """列出壓縮檔的資料夾結構：每個資料夾有幾個檔，方便決定要解壓哪些。"""
    res = subprocess.run([SEVEN_ZIP, "l", "-ba", "-slt", path], capture_output=True, text=True, encoding="utf-8", errors="replace")
    names = [l[7:] for l in res.stdout.splitlines() if l.startswith("Path = ")]
    folders = {}
    for n in names:
        d = os.path.dirname(n)
        folders[d] = folders.get(d, 0) + 1
    print(f"  共 {len(names):,} 個檔案、{len(folders):,} 個資料夾。前 40 個資料夾：")
    for d, c in sorted(folders.items())[:40]:
        print(f"    {c:6,}  {d}")
    with open(path + ".filelist.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(names))
    print(f"  完整清單存在 {path}.filelist.txt")


def main():
    ap = argparse.ArgumentParser(description="下載司法院開放資料平臺的每月裁判書")
    ap.add_argument("--months", default="", help="例：202405 或 201801-202512")
    ap.add_argument("--delete-list", action="store_true",
                    help="另外下載「Delete-Infor」：已下架的裁判書清單（CSV），用來從資料中移除")
    ap.add_argument("--list-only", action="store_true", help="下載後只列出壓縮檔結構，不解壓")
    args = ap.parse_args()

    if not args.months and not args.delete_list:
        ap.error("請至少指定 --months 或 --delete-list")
    os.makedirs(OUT, exist_ok=True)
    cat = catalog()
    sess = Session()
    if args.delete_list:
        path = os.path.join(OUT, "Delete-Infor.csv")
        print("Delete-Infor：已下架的裁判書清單")
        download(sess, DELETE_LIST_FILESET, path)
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            head = [next(f, "") for _ in range(6)]
        print("  前幾行：")
        for line in head:
            print("   ", line.rstrip()[:200])
    for ym in (month_list(args.months) if args.months else []):
        if ym not in cat:
            print(f"{ym}：平臺上沒有這個月份，跳過")
            continue
        title, fid = cat[ym]
        path = os.path.join(OUT, f"{ym}.rar")
        print(f"{ym}：{title}（fileSetId {fid}）")
        if os.path.exists(path):
            print("  已下載過，跳過下載")
        else:
            try:
                download(sess, fid, path)
            except urllib.error.HTTPError as e:
                print(f"  下載失敗 HTTP {e.code}：{e.read()[:200]!r}")
                continue
        if args.list_only:
            list_archive(path)


if __name__ == "__main__":
    main()
