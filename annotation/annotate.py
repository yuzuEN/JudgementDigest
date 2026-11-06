"""
以 Claude API 標註 sample.py 抽出的段落（手冊 v0.3、prompt p3.0，民事），寫入 annotations 表。

改寫自階段一、二的 annotate.py，保留：
  - 可中斷續跑：同一段、同一個 run_no、同一個 prompt 版本已標過就跳過，不會重複付費
  - prompt caching：標註規則每次都一樣，快取後重複的部分只收約一成的價
  - 引文逐字驗證（quote_valid）、標籤合法性檢查（不合法的記成 INVALID:xxx）
新增：
  - 指令列參數（不用改檔案）、dry run、預算上限
  - polarity 也檢查合法性（DAM 的方向：酌減／全額准許／不明）

用法（建議照順序，每步確認沒問題再往下）：
    python -m annotation.annotate --dry-run                 # 只印出第一段的 prompt，不呼叫 API（0 元）
    python -m annotation.annotate --run-no 1 --limit 1      # 只標 1 段（約 1 美分），確認寫入正確
    python -m annotation.annotate --run-no 1                # 第 1 次全部
    python -m annotation.annotate --run-no 2
    python -m annotation.annotate --run-no 3

需要：pip install -r annotation/requirements.txt，以及環境變數 ANTHROPIC_API_KEY。
"""
import argparse
import json
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from annotation.prompts_v3 import (LABELS_CIVIL, MANUAL_VERSION, POLARITY_CIVIL, PROMPT_VERSION,  # noqa: E402
                                   SYSTEM_CIVIL, USER_TEMPLATE)

MODEL = "claude-sonnet-5-5"
# 美元／百萬 token（https://platform.claude.com/docs/en/about-claude/pricing）
PRICE = {"input": 2.0, "cache_write": 2.5, "cache_read": 0.2, "output": 10.0}


def parse_response(raw: str, para: str, valid_labels=LABELS_CIVIL, valid_polarity=POLARITY_CIVIL) -> list:
    """
    模型回應 → 要寫入的標籤列 [(label, polarity, quote, confidence, quote_valid), ...]。
    JSON 解析失敗回傳 [("PARSE_ERROR", None, None, None, 0)]。
    """
    cleaned = (raw or "").strip()
    if cleaned.startswith("```"):          # 模型偶爾會包 markdown 框
        cleaned = cleaned.split("```")[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()
    try:
        labels = json.loads(cleaned).get("labels", [])
    except (ValueError, AttributeError):
        return [("PARSE_ERROR", None, None, None, 0)]

    rows = []
    for item in labels:
        code = item.get("code", "")
        quote = item.get("quote") or ""
        polarity = item.get("polarity")
        valid = 1 if code == "NONE" else int(bool(quote) and quote in para)
        if code not in valid_labels:
            code, valid = f"INVALID:{code}", 0
        if polarity not in valid_polarity:
            polarity = f"INVALID:{polarity}"
        rows.append((code, polarity, quote, item.get("confidence"), valid))
    return rows or [("PARSE_ERROR", None, None, None, 0)]


def main():
    ap = argparse.ArgumentParser(description="以 Claude API 標註段落")
    ap.add_argument("--db", type=Path, default=config.ARTIFACTS_DIR / "annotation_civil_v1" / "annotation.sqlite")
    ap.add_argument("--run-no", type=int, default=1)
    ap.add_argument("--limit", type=int, default=None, help="只標前 N 段（試跑用）")
    ap.add_argument("--dry-run", action="store_true", help="只印出第一段的 prompt，不呼叫 API")
    ap.add_argument("--budget", type=float, default=2.0, help="本次估算花費超過此金額（美元）就停止")
    ap.add_argument("--max-tokens", type=int, default=4000, help="thinking 區塊也算輸出 token，要留足夠空間")
    args = ap.parse_args()

    con = sqlite3.connect(args.db)
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
        con.executemany(
            "INSERT INTO annotations (sample_id, annotator, run_no, label, polarity, quote, confidence, "
            "quote_valid, manual_version, prompt_version, raw_response, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [(sid, MODEL, args.run_no, lab, pol, q, conf, v, MANUAL_VERSION, PROMPT_VERSION, raw, now)
             for lab, pol, q, conf, v in rows])
        con.commit()  # 每段都存，中斷也不會丟
        n_ok += rows[0][0] != "PARSE_ERROR"
        n_fail += rows[0][0] == "PARSE_ERROR"
        if (i + 1) % 20 == 0:
            print(f"  進度 {i + 1}/{len(todo)}　估算花費 ${cost:.3f}　{(time.time() - t0) / 60:.1f} 分")
        time.sleep(0.3)

    bad = con.execute(
        "SELECT COUNT(*) FROM annotations WHERE run_no = ? AND prompt_version = ? "
        "AND (label = 'PARSE_ERROR' OR label LIKE 'INVALID:%' OR polarity LIKE 'INVALID:%' OR quote_valid = 0)",
        (args.run_no, PROMPT_VERSION)).fetchone()[0]
    print(f"\n完成 {n_ok} 段、失敗 {n_fail} 段，估算花費 ${cost:.3f}（實際以 Console 的 Usage 為準）")
    print(f"本 run 解析失敗、不合法或引文驗證失敗的列數：{bad}")
    con.close()


if __name__ == "__main__":
    main()
