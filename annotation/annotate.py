"""
以 Claude API 標註 sample.py 抽出的論點單位（手冊 v0.6、prompt p6.0，民事），寫入 annotations 表。

改寫自階段一、二的 annotate.py，保留：
  - 可中斷續跑：同一段、同一個 run_no、同一個 prompt 版本已標過就跳過，不會重複付費
  - prompt caching：標註規則每次都一樣，快取後重複的部分只收約一成的價
  - 引文逐字驗證（quote_valid）、標籤合法性檢查（不合法的記成 INVALID:xxx）
新增：
  - 指令列參數（不用改檔案）、dry run、預算上限
  - polarity 也檢查合法性（DAM 的方向：酌減／全額准許／不明）
v0.5 新增：
  - CONCL 的方向（有理由／一部有理由／無理由）：CONCL 一定要有方向，其他標籤不能填這三個
  - EV 的 basis（明示評價／依證據推論）存進 annotations.subtype
  - 舊資料庫（v1、v2）沒有 subtype 欄位時自動補上，--reparse 才能用在舊資料
  - 預算預設 $4：論點單位比 v0.4 的段落長（中位數 281 字，但長的到 1,200 字）
v0.6 新增：
  - 引文超過 100 字時可以寫「開頭〔略〕結尾」。程式先整段比對；找不到才依〔略〕切成開頭、結尾，
    先找結尾、再往回找最靠近的開頭，還原完整範圍（resolve_quote）。
    合法條件：開頭至少 8 字、結尾至少 4 字；範圍上限 400 字，RULE 800 字
    （依 v0.6 試標 3,177 筆調整：非 RULE 的範圍最長 385 字；RULE 一次陳述多條法條時常到 400–600 字，
     1,000 字以上的是把整個單位框起來，仍算不合法；結尾常是「並不可採」「核定相當之數額」這類 4–7 字的短結論）
  - quotes 欄位存模型原本寫的引文；完整範圍隨時可以用 resolve_quote(引文, 單位原文) 算回來，不另外存

用法（建議照順序，每步確認沒問題再往下）：
    python -m annotation.annotate --dry-run                 # 只印出第一段的 prompt，不呼叫 API（0 元）
    python -m annotation.annotate --run-no 1 --limit 1      # 只標 1 段（約 1 美分），確認寫入正確
    python -m annotation.annotate --run-no 1                # 第 1 次全部
    python -m annotation.annotate --run-no 2
    python -m annotation.annotate --run-no 3
    python -m annotation.annotate --reparse                 # 解析規則更新後，重新解析舊的失敗列（不呼叫 API）

需要：pip install -r annotation/requirements.txt，以及環境變數 ANTHROPIC_API_KEY。
"""
import argparse
import json
import sqlite3
import sys
import time
from contextlib import closing
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from annotation.sample import OUT_NAME  # noqa: E402
from annotation.cues import MARK  # noqa: E402
from annotation.prompts_v6 import (EV_BASIS, LABELS_CIVIL, MANUAL_VERSION, POLARITY_BY_LABEL_CIVIL,  # noqa: E402
                                   POLARITY_CIVIL, PROMPT_VERSION, SYSTEM_CIVIL, USER_TEMPLATE)

MAX_SPAN = 400                    # 用〔略〕還原的範圍上限（字）：避免模型把整個單位框起來
MAX_SPAN_BY_LABEL = {"RULE": 800}  # 大前提常一次陳述好幾條法條
MIN_HEAD = 8                       # 開頭至少幾個字：開頭是往回找的，太短（例如「原告」）容易對到別處
MIN_TAIL = 4                       # 結尾至少幾個字：結尾先找、而且常是短結論（「並不可採」）


def resolve_quote(quote: str, para: str, label: str = None, min_head: int = MIN_HEAD, min_tail: int = MIN_TAIL):
    """
    引文在單位原文裡的完整範圍 (start, end)；找不到或不合法回傳 None。
      1. 整段比對：原文本來就含有省略號的引文，也會在這一步直接找到
      2. 有一個〔略〕：切成開頭、結尾。先找結尾，再往回找最靠近、而且在結尾之前結束的開頭，
         這樣切出來的是最短的範圍，不會把兩個請求混在一起；結尾出現好幾次時依序試
    """
    if not quote:
        return None
    i = para.find(quote)
    if i >= 0:
        return (i, i + len(quote))
    if quote.count(MARK) != 1:
        return None
    head, tail = (x.strip() for x in quote.split(MARK))
    if len(head) < min_head or len(tail) < min_tail:
        return None
    max_span = MAX_SPAN_BY_LABEL.get(label, MAX_SPAN)
    e = para.find(tail)
    while e >= 0:
        s = para.rfind(head, 0, e)
        if s >= 0 and e + len(tail) - s <= max_span:
            return (s, e + len(tail))
        e = para.find(tail, e + 1)
    return None

MODEL = "claude-sonnet-5-5"
# 美元／百萬 token（https://platform.claude.com/docs/en/about-claude/pricing）
PRICE = {"input": 2.0, "cache_write": 2.5, "cache_read": 0.2, "output": 10.0}


def last_labels_json(raw: str):
    """
    回應中最後一個含 "labels" 的 JSON 物件；找不到回傳 None。

    v0.3 試標時約 4% 的回應不是純 JSON，兩種情況：
      - 模型先寫一段推理說明，最後才附上 JSON
      - 模型給了答案後自我修正（例如發現引文出自後段），再給第二個 JSON
    兩種都應取最後一個：前者是唯一的答案，後者是修正後的答案。
    markdown 程式碼框（```json）也一併處理，因為只看大括號。
    """
    decoder = json.JSONDecoder()
    found = None
    i = (raw or "").find("{")
    while i != -1:
        try:
            obj, end = decoder.raw_decode(raw, i)
        except ValueError:
            i = raw.find("{", i + 1)
            continue
        if isinstance(obj, dict) and "labels" in obj:
            found = obj
        i = raw.find("{", end)
    return found


PARSE_ERROR = ("PARSE_ERROR", None, None, None, 0, None)


def check_polarity(code: str, polarity, valid_polarity=POLARITY_CIVIL, by_label=POLARITY_BY_LABEL_CIVIL):
    """
    polarity 合法就原樣回傳，不合法回傳 "INVALID:xxx"。三道檢查：
      1. 在整體的清單裡
      2. 有專屬清單的標籤（EV、DAM、CONCL），填了值就要在自己的清單裡（CONCL 填「有利原告」不合法）
      3. CONCL 一定要有方向；其他標籤不能填 CONCL 的方向（EV 填「有理由」不合法）
    """
    bad = f"INVALID:{polarity}"
    if polarity not in valid_polarity:
        return bad
    own = by_label.get(code)
    if own is not None and polarity is not None and polarity not in own:
        return bad
    concl = by_label.get("CONCL", [])
    if code == "CONCL" and polarity is None:
        return bad
    if code != "CONCL" and polarity in concl:
        return bad
    return polarity


def parse_response(raw: str, para: str, valid_labels=LABELS_CIVIL, valid_polarity=POLARITY_CIVIL) -> list:
    """
    模型回應 → 要寫入的標籤列 [(label, polarity, quote, confidence, quote_valid, subtype), ...]。
    subtype：EV 的 basis（明示評價／依證據推論），其他標籤為 None。
    找不到可用的 JSON 回傳 [PARSE_ERROR]。
    """
    obj = last_labels_json(raw)
    if obj is None or not isinstance(obj.get("labels"), list):
        return [PARSE_ERROR]
    labels = [item for item in obj["labels"] if isinstance(item, dict)]

    rows = []
    for item in labels:
        code = item.get("code", "")
        quote = item.get("quote") or ""
        valid = 1 if code == "NONE" else int(resolve_quote(quote, para, code) is not None)
        polarity = check_polarity(code, item.get("polarity"), valid_polarity)
        subtype = None
        if code == "EV":
            basis = item.get("basis")
            # 舊版（p4 以前）的回應沒有 basis，記 None；有填但不在清單裡才算不合法
            subtype = basis if basis in EV_BASIS or basis is None else f"INVALID:{basis}"
        if code not in valid_labels:
            code, valid = f"INVALID:{code}", 0
        rows.append((code, polarity, quote, item.get("confidence"), valid, subtype))
    return rows or [PARSE_ERROR]


INSERT = ("INSERT INTO annotations (sample_id, annotator, run_no, label, polarity, quote, confidence, "
          "quote_valid, subtype, manual_version, prompt_version, raw_response, created_at) "
          "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)")


def ensure_subtype(con: sqlite3.Connection) -> None:
    """v0.4 以前的資料庫沒有 subtype 欄位：補上（舊資料的值是 NULL）。"""
    cols = {r[1] for r in con.execute("PRAGMA table_info(annotations)")}
    if "subtype" not in cols:
        con.execute("ALTER TABLE annotations ADD COLUMN subtype TEXT")
        con.commit()


def reparse(db: Path) -> tuple:
    """
    用資料庫裡已存的 raw_response 重新解析 PARSE_ERROR 的列，不呼叫 API、不花錢。
    救回的列會取代原本的 PARSE_ERROR 列（同一段、同一個 run、同一個 prompt 版本）。
    回傳 (原本失敗筆數, 救回筆數)。
    """
    with closing(sqlite3.connect(db)) as con:
        ensure_subtype(con)
        failed = con.execute(
            "SELECT DISTINCT a.sample_id, a.annotator, a.run_no, a.manual_version, a.prompt_version, "
            "a.raw_response, a.created_at, p.para_text FROM annotations a JOIN paragraphs p USING (sample_id) "
            "WHERE a.label = 'PARSE_ERROR'").fetchall()
        fixed = 0
        for sid, annotator, run, manual, prompt, raw, created, para in failed:
            rows = parse_response(raw, para)
            if rows[0][0] == "PARSE_ERROR":
                continue
            con.execute("DELETE FROM annotations WHERE sample_id = ? AND annotator = ? AND run_no = ? "
                        "AND prompt_version = ? AND label = 'PARSE_ERROR'", (sid, annotator, run, prompt))
            con.executemany(INSERT, [(sid, annotator, run, lab, pol, q, conf, v, sub, manual, prompt, raw, created)
                                     for lab, pol, q, conf, v, sub in rows])
            fixed += 1
        con.commit()
    print(f"原本解析失敗 {len(failed)} 筆，重新解析後救回 {fixed} 筆（未呼叫 API）")
    return len(failed), fixed


def revalidate(db: Path) -> tuple:
    """
    依目前的 resolve_quote 規則，重新判定所有標註的 quote_valid（引文驗證規則調整後用）。
    只更新 quote_valid 一欄，不刪除、不新增任何列，不呼叫 API。回傳 (改變的筆數, 仍不合法的筆數)。
    """
    with closing(sqlite3.connect(db)) as con:
        rows = con.execute(
            "SELECT a.id, a.label, a.quote, a.quote_valid, p.para_text FROM annotations a "
            "JOIN paragraphs p USING (sample_id) "
            "WHERE a.label NOT IN ('NONE', 'PARSE_ERROR') AND a.label NOT LIKE 'INVALID:%'").fetchall()
        changed, invalid = 0, 0
        for rid, label, quote, old, para in rows:
            new = int(resolve_quote(quote, para, label) is not None)
            invalid += (new == 0)
            if new != old:
                con.execute("UPDATE annotations SET quote_valid = ? WHERE id = ?", (new, rid))
                changed += 1
        con.commit()
    print(f"重新判定引文 {len(rows)} 筆：{changed} 筆改變，仍不合法 {invalid} 筆（未呼叫 API）")
    return changed, invalid


def main():
    ap = argparse.ArgumentParser(description="以 Claude API 標註段落")
    ap.add_argument("--db", type=Path, default=config.ARTIFACTS_DIR / OUT_NAME / "annotation.sqlite")
    ap.add_argument("--run-no", type=int, default=1)
    ap.add_argument("--limit", type=int, default=None, help="只標前 N 段（試跑用）")
    ap.add_argument("--dry-run", action="store_true", help="只印出第一段的 prompt，不呼叫 API")
    ap.add_argument("--budget", type=float, default=4.0, help="本次估算花費超過此金額（美元）就停止")
    ap.add_argument("--max-tokens", type=int, default=4000, help="thinking 區塊也算輸出 token，要留足夠空間")
    ap.add_argument("--reparse", action="store_true",
                    help="不呼叫 API：用已存的原始回應重新解析之前的 PARSE_ERROR，並依目前規則重新判定所有引文")
    args = ap.parse_args()

    if args.reparse:
        reparse(args.db)
        revalidate(args.db)
        return

    con = sqlite3.connect(args.db)
    ensure_subtype(con)
    done = {r[0] for r in con.execute(
        "SELECT DISTINCT sample_id FROM annotations WHERE annotator = ? AND run_no = ? AND prompt_version = ?",
        (MODEL, args.run_no, PROMPT_VERSION))}
    todo = [r for r in con.execute(
        "SELECT sample_id, prev_text, para_text, next_text FROM paragraphs ORDER BY sample_id")
        if r[0] not in done]
    if args.limit:
        todo = todo[:args.limit]
    print(f"run {args.run_no}：已完成 {len(done)} 段，本次要標 {len(todo)} 段")

    if args.dry_run or not todo:
        con.close()
    if args.dry_run:
        if todo:
            sid, prev, para, nxt = todo[0]
            print(f"\n===== sample_id {sid} =====")
            print(SYSTEM_CIVIL[:300], "⋯\n-----")
            print(USER_TEMPLATE.format(prev=prev, target=para, next=nxt))
        return
    if not todo:
        return

    import anthropic  # dry run 不需要安裝
    client = anthropic.Anthropic()

    cost, n_ok, n_fail = 0.0, 0, 0
    t0 = time.time()
    for i, (sid, prev, para, nxt) in enumerate(todo):
        if cost > args.budget:
            print(f"!! 估算花費 ${cost:.3f} 超過上限 ${args.budget}，停止。已完成的不會重跑。")
            break
        resp = None
        for attempt in range(3):
            try:
                resp = client.messages.create(
                    model=MODEL, max_tokens=args.max_tokens,
                    system=[{"type": "text", "text": SYSTEM_CIVIL, "cache_control": {"type": "ephemeral"}}],
                    messages=[{"role": "user", "content": USER_TEMPLATE.format(prev=prev, target=para, next=nxt)}],
                )
                break
            except Exception as e:  # 網路、速率限制等，稍等重試
                print(f"  [{sid}] 重試 {attempt + 1}：{type(e).__name__} {str(e)[:80]}")
                time.sleep(2 ** attempt)
        if resp is None:
            n_fail += 1
            continue  # 不寫入，下次重跑會補

        u = resp.usage
        cost += (u.input_tokens * PRICE["input"]
                 + (getattr(u, "cache_creation_input_tokens", 0) or 0) * PRICE["cache_write"]
                 + (getattr(u, "cache_read_input_tokens", 0) or 0) * PRICE["cache_read"]
                 + u.output_tokens * PRICE["output"]) / 1e6

        raw = "".join(b.text for b in resp.content if b.type == "text").strip()
        rows = parse_response(raw, para)
        now = datetime.now().isoformat()
        con.executemany(INSERT, [(sid, MODEL, args.run_no, lab, pol, q, conf, v, sub, MANUAL_VERSION,
                                  PROMPT_VERSION, raw, now) for lab, pol, q, conf, v, sub in rows])
        con.commit()  # 每段都存，中斷也不會丟
        n_ok += rows[0][0] != "PARSE_ERROR"
        n_fail += rows[0][0] == "PARSE_ERROR"
        if (i + 1) % 20 == 0:
            print(f"  進度 {i + 1}/{len(todo)}　估算花費 ${cost:.3f}　{(time.time() - t0) / 60:.1f} 分")
        time.sleep(0.3)

    bad = con.execute(
        "SELECT COUNT(*) FROM annotations WHERE run_no = ? AND prompt_version = ? "
        "AND (label = 'PARSE_ERROR' OR label LIKE 'INVALID:%' OR polarity LIKE 'INVALID:%' "
        "OR subtype LIKE 'INVALID:%' OR quote_valid = 0)",
        (args.run_no, PROMPT_VERSION)).fetchone()[0]
    print(f"\n完成 {n_ok} 段、失敗 {n_fail} 段，估算花費 ${cost:.3f}（實際以 Console 的 Usage 為準）")
    print(f"本 run 解析失敗、不合法或引文驗證失敗的列數：{bad}")
    con.close()


if __name__ == "__main__":
    main()
