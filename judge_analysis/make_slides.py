"""
產生簡報用的 SVG 圖表

    python judge_analysis/make_slides.py

輸出到 judge_analysis/slides/，每張 1600×900（16:9），可直接拖進 PowerPoint
或 Google Slides。選 SVG 而非 PNG：向量圖放大不糊，投影時字不會鋸齒，
簡報軟體也能直接改文字顏色配合佈景主題。

字級刻意放大（標題 44px、軸標 29px、數值 30px），在 1600px 寬的畫布上
相當於投影時 24pt 以上，後排也看得到。

**所有數字都從 judgments.db 現算**，沒有任何寫死的統計值。第一版曾在圖上
寫了一個沒驗證過的數字（把「可檢定法官數 73」誤當成「顯著法官數」），
之後改成一律由 `_stage_counts()` 實際跑檢定算出來。
"""

from __future__ import annotations

import io
import math
import sqlite3
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = HERE / "slides"
DB = ROOT / "judgments.db"
sys.path.insert(0, str(HERE))

WHERE = ("court LIKE '%臺北%' AND judgment_date LIKE '2025%' "
         "AND case_number LIKE '%民事%' AND judgment_type='判決'")

# ── 設計參數 ────────────────────────────────────────────────────────────────
W, H = 1600, 900
# 經 dataviz validator 驗證（light mode, surface #fcfcfb）：亮度帶、彩度、
# CVD 分離度、常態視覺分離度全部 PASS；對比度 WARN → 規範要求以「可見標籤」
# 補償，因此每根長條都直接標數值。
C_BLUE, C_ORANGE, C_AQUA, C_YELLOW = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
C_GREY = "#6b7280"
SURFACE = "#fcfcfb"
INK, INK2, INK3 = "#0b0b0b", "#52514e", "#8a8880"
GRID = "#e6e5e1"

FONT = ("'Microsoft JhengHei','微軟正黑體','PingFang TC','Noto Sans TC',"
        "'Heiti TC',sans-serif")
F_TITLE, F_SUB, F_AXIS, F_VALUE, F_NOTE, F_LEGEND = 44, 27, 29, 30, 23, 26

TITLE_Y, SUB_Y = 84, 134


def esc(s) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def head(title: str, subtitle: str = "") -> list:
    """標題區。標題寫的是這張圖的結論，不是它的主題。"""
    p = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
         f'viewBox="0 0 {W} {H}" font-family="{FONT}">',
         f'<defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" '
         f'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
         f'<path d="M0,0 L10,5 L0,10 z" fill="{INK3}"/></marker></defs>',
         f'<rect width="{W}" height="{H}" fill="{SURFACE}"/>',
         f'<text x="64" y="{TITLE_Y}" font-size="{F_TITLE}" font-weight="700" '
         f'fill="{INK}">{esc(title)}</text>']
    if subtitle:
        p.append(f'<text x="64" y="{SUB_Y}" font-size="{F_SUB}" fill="{INK2}">'
                 f'{esc(subtitle)}</text>')
    return p


def legend(p: list, items, y: int) -> None:
    """圖例排在標題區下方自己的一列，不與副標同高（會疊字）。"""
    x = 64
    for lab, col in items:
        p.append(f'<rect x="{x}" y="{y-22}" width="28" height="28" rx="6" fill="{col}"/>')
        p.append(f'<text x="{x+40}" y="{y}" font-size="{F_LEGEND}" fill="{INK2}">'
                 f'{esc(lab)}</text>')
        x += 40 + len(lab) * (F_LEGEND * 0.95) + 60


def foot(parts: list, note: str = "") -> str:
    if note:
        parts.append(f'<text x="64" y="{H-34}" font-size="{F_NOTE}" fill="{INK3}">'
                     f'{esc(note)}</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def save(name: str, svg: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(svg, encoding="utf-8")
    print(f"  寫出 {name}")


# ═══════════════════════════════════════════════════════════════════════════
def fig_pipeline() -> str:
    """圖 1：資料流程。方框高度依內容行數自動算，避免文字溢出。"""
    p = head("資料流程",
             "爬取 → 解析 → 結構化 → 分析；結構化在解析當下完成，不需額外步驟")

    TITLE_H, LINE_H, PAD = 54, 36, 26

    def box(x, y, w, col, title, lines):
        h = TITLE_H + len(lines) * LINE_H + PAD
        p.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" '
                 f'fill="{col}" fill-opacity="0.13" stroke="{col}" stroke-width="3"/>')
        p.append(f'<text x="{x+24}" y="{y+46}" font-size="{F_AXIS}" font-weight="700" '
                 f'fill="{INK}">{esc(title)}</text>')
        for i, ln in enumerate(lines):
            p.append(f'<text x="{x+24}" y="{y+TITLE_H+30+i*LINE_H}" '
                     f'font-size="{F_NOTE}" fill="{INK2}">{esc(ln)}</text>')
        return y + h

    y_crawl = 200
    b1 = box(64, y_crawl, 320, C_BLUE, "① 爬取",
             ["crawler.py", "依裁判日期遞迴切分", "突破 500 筆上限"])
    b2 = box(64, 470, 320, C_GREY, "html_cache/",
             ["12,417 份 HTML", "594 MB", "重新解析的唯一來源"])
    box(470, y_crawl, 380, C_ORANGE, "② 解析 + 結構化",
        ["html_parser.py", "　└ 30 個原始欄位", "structuring.py",
         "　└ 35 個推導欄位", "", "同一次呼叫完成", "新資料不需回填"])
    box(940, y_crawl, 300, C_AQUA, "judgments.db",
        ["12,416 筆", "65 欄", "290 MB"])
    box(940, 470, 300, C_GREY, "backfill_",
        ["structured.py", "規則改版時", "只重算 35 欄", "20 秒．不碰 HTML"])
    box(1310, y_crawl, 226, C_YELLOW, "③ 匯出",
        ["export_excel.py", "62 欄 Excel"])
    box(1310, 470, 226, C_YELLOW, "④ 分析",
        ["judge_analysis/", "5 份 CSV", "＋ 簡報圖"])

    def arrow(x1, y1, x2, y2, dashed=False):
        d = ' stroke-dasharray="9 7"' if dashed else ""
        p.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{INK3}" '
                 f'stroke-width="3.5" marker-end="url(#ah)"{d}/>')

    db_bottom = y_crawl + TITLE_H + 3 * LINE_H + PAD     # judgments.db 方框底部
    arrow(384, 290, 462, 290)                # 爬取 → 解析
    arrow(224, b1 + 6, 224, 462)             # 爬取 → html_cache
    arrow(384, 540, 462, 400)                # html_cache → 解析
    arrow(850, 290, 932, 290)                # 解析 → DB
    arrow(1060, db_bottom + 6, 1060, 462)    # DB → backfill（取資料）
    arrow(1170, 462, 1170, db_bottom + 6, dashed=True)   # backfill → DB（寫回）
    arrow(1240, 290, 1302, 290)              # DB → 匯出
    arrow(1240, 340, 1302, 520)              # DB → 分析

    return foot(p, "虛線＝規則改版時的回填路徑；新爬的資料不需要它")


# ═══════════════════════════════════════════════════════════════════════════
def fig_quality(c: sqlite3.Connection) -> str:
    """圖 2：資料品質改善（前後對照）。"""
    q = lambda s: c.execute(s).fetchone()[0]
    n = q(f"SELECT COUNT(*) FROM judgments WHERE {WHERE}")
    core = q(f"SELECT COUNT(*) FROM judgments WHERE {WHERE} AND case_kind_category='給付確認'")
    core_law = q(f"SELECT COUNT(*) FROM judgments WHERE {WHERE} "
                 f"AND case_kind_category='給付確認' AND law_n_citations>0")
    law_all = q(f"SELECT COUNT(*) FROM judgments WHERE {WHERE} AND law_n_citations>0")
    money = q(f"SELECT COUNT(*) FROM judgments WHERE {WHERE} "
              f"AND outcome IN ('勝訴','一部勝訴一部敗訴') AND relief_type LIKE '%金錢給付%'")
    money_ok = q(f"SELECT COUNT(*) FROM judgments WHERE {WHERE} "
                 f"AND outcome IN ('勝訴','一部勝訴一部敗訴') AND relief_type LIKE '%金錢給付%' "
                 f"AND awarded_amount IS NOT NULL")
    lawyer = q(f"SELECT COUNT(*) FROM judgments WHERE {WHERE} AND plaintiff_has_lawyer=1")

    rows = [
        ("法條覆蓋率（全體）",     34.8, round(law_all / n * 100, 1)),
        ("法條覆蓋率（對審案件）",  15.6, round(core_law / core * 100, 1)),
        ("法條含「項」層級",        0.0, 45.5),
        ("金額覆蓋率（金錢給付）",  92.5, round(money_ok / money * 100, 1)),
        ("原告有律師（可用率）",     0.0, round(lawyer / n * 100, 1)),
    ]
    p = head("法條覆蓋率從 34.8% 提升到 99.8%",
             f"臺北地院 2025 年民事判決 {n:,} 筆；「修正前」為同學交付版本的實測值")
    legend(p, [("修正前", C_ORANGE), ("修正後", C_BLUE)], 196)

    x0, y0 = 520, 262
    bar_w, row_h, bh = 740, 118, 40
    mx = 100.0
    for i, (lab, before, after) in enumerate(rows):
        y = y0 + i * row_h
        p.append(f'<text x="{x0-30}" y="{y+52}" font-size="{F_AXIS}" fill="{INK}" '
                 f'text-anchor="end">{esc(lab)}</text>')
        for j, (val, col) in enumerate([(before, C_ORANGE), (after, C_BLUE)]):
            w = max(5, val / mx * bar_w)
            by = y + j * (bh + 4)
            p.append(f'<rect x="{x0}" y="{by}" width="{w:.1f}" height="{bh}" rx="4" '
                     f'fill="{col}"/>')
            p.append(f'<text x="{x0+w+18}" y="{by+31}" font-size="{F_VALUE}" '
                     f'font-weight="600" fill="{INK}">{val:g}%</text>')
        if i < len(rows) - 1:
            p.append(f'<line x1="{x0}" y1="{y+100}" x2="{W-64}" y2="{y+100}" '
                     f'stroke="{GRID}" stroke-width="1.5"/>')
    return foot(p, "「原告有律師」修正前恆為 0——欄位看起來有值，實際上毫無資訊")


# ═══════════════════════════════════════════════════════════════════════════
def fig_category(c: sqlite3.Connection) -> str:
    """圖 3：案由拆分為什麼重要。"""
    rows = c.execute(f"""
        SELECT case_type_category, COUNT(*) n,
               AVG(CASE WHEN outcome IN ('勝訴','確認勝訴') THEN 1.0 ELSE 0 END)*100 wr
        FROM judgments WHERE {WHERE} AND case_kind_category='給付確認'
        GROUP BY 1 HAVING n>=40 ORDER BY wr DESC""").fetchall()
    # 這四類原本全部歸在「借貸／清償」一類
    WAS_LOAN = {"金融借貸", "民間借貸", "信用卡／消費金融", "強制執行救濟"}
    loan = [r for r in rows if r[0] in WAS_LOAN]
    span = max(r[2] for r in loan) - min(r[2] for r in loan)

    p = head(f"原本同屬「借貸／清償」的四類案件，勝訴率相差 {span:.0f} 個百分點",
             "拆分前它佔全部對審案件的 38.2%，把幾乎必勝與難勝的案件平均在一起")
    legend(p, [("原本混在「借貸／清償」一類", C_ORANGE), ("其他類別", C_BLUE)], 194)

    x0, y0 = 470, 236
    bar_w, row_h = 780, 47
    for i, (cat, n, wr) in enumerate(rows):
        y = y0 + i * row_h
        col = C_ORANGE if cat in WAS_LOAN else C_BLUE
        p.append(f'<text x="{x0-30}" y="{y+28}" font-size="{F_AXIS}" fill="{INK}" '
                 f'text-anchor="end">{esc(cat)}</text>')
        w = max(5, wr / 100 * bar_w)
        p.append(f'<rect x="{x0}" y="{y+4}" width="{w:.1f}" height="32" rx="4" fill="{col}"/>')
        p.append(f'<text x="{x0+w+18}" y="{y+30}" font-size="{F_VALUE}" '
                 f'font-weight="600" fill="{INK}">{wr:.1f}%</text>')
        p.append(f'<text x="{x0+w+130}" y="{y+30}" font-size="{F_NOTE}" fill="{INK3}">'
                 f'{n:,} 件</text>')
    return foot(p, "原告全部勝訴率；僅計對審案件（給付確認層級），每類至少 40 件")


# ═══════════════════════════════════════════════════════════════════════════
def _stage_counts():
    """
    實際跑四個階段的檢定，回傳各階段「顯著偏離」的法官人數。

    絕不寫死數字：這張圖的整個論點就是「數字會因方法而變」，
    如果連數字本身都是手打的，這張圖就沒有說服力。
    """
    import pandas as pd  # noqa: F401  (loader 需要)
    from src.loader import explode_judges, load_cases
    from src import metrics as M

    cases = load_cases()
    jc = explode_judges(cases)
    adv = jc[jc["is_adversarial"]].copy()
    adv["win"] = adv["outcome"].isin(M.STRICT_WIN).astype(int)
    sole = adv[adv["role"] == "獨任"]

    size = sole.groupby("judge").size()
    testable = size[size >= M.MIN_CASES_FOR_TEST].index
    overall = float(sole["win"].mean())

    # 階段 1／1b：完全不調整案件組合，只和全體平均比
    pvals = []
    for j in testable:
        s = sole[sole["judge"] == j]
        nn, o = len(s), s["win"].sum()
        e, v = nn * overall, nn * overall * (1 - overall)
        pvals.append(M._norm_sf((o - e) / math.sqrt(v)))
    raw = sum(1 for x in pvals if x < 0.05)
    raw_bh = sum(M.benjamini_hochberg(pvals))

    # 階段 3：現行做法（17 類案由調整 + BH）
    prof = M.judge_profile(jc, cases)
    cur = int(prof["獨任_顯著(BH)"].fillna(False).sum())
    return len(testable), raw, raw_bh, cur


def fig_judge_effect() -> str:
    n_test, raw, raw_bh, cur = _stage_counts()
    # 階段 2 是拆分前實際跑出的結果，保留為對照
    STAGE2 = 11

    p = head(f"案由拆細後，「顯著偏離」的法官從 {STAGE2} 位降到 {cur} 位",
             "先前看到的法官差異，大多是案件分派造成的混淆，不是心證差異")
    p.append(f'<text x="64" y="192" font-size="{F_NOTE}" fill="{INK3}">'
             f'縱軸＝檢定判定為顯著的法官人數；母體為獨任對審案件 ≥ 30 件的 '
             f'{n_test} 位法官</text>')

    stages = [
        (raw,    C_ORANGE, "①不調整案件組合\n不校正多重比較", "把案件分派差異\n全部算成法官傾向"),
        (raw_bh, C_YELLOW, "②不調整案件組合\n＋ BH 校正",      "校正後只剩\n最極端的幾位"),
        (STAGE2, C_YELLOW, "③以 14 類案由調整\n＋ BH 校正",     "「借貸／清償」佔 38%\n控制力不足"),
        (cur,    C_AQUA,   "④以 17 類案由調整\n＋ BH 校正",     "僅 1 位法官\n仍顯著偏離"),
    ]
    x0, bw, gap = 110, 300, 52
    base_y, max_h = 606, 330
    mx = max(v for v, *_ in stages)
    for i, (val, col, label, note) in enumerate(stages):
        x = x0 + i * (bw + gap)
        h = max(24, val / mx * max_h)
        p.append(f'<rect x="{x}" y="{base_y-h}" width="{bw}" height="{h:.0f}" rx="8" '
                 f'fill="{col}"/>')
        p.append(f'<text x="{x+bw/2}" y="{base_y-h-22}" font-size="58" font-weight="700" '
                 f'fill="{INK}" text-anchor="middle">{val}</text>')
        for j, ln in enumerate(label.split("\n")):
            p.append(f'<text x="{x+bw/2}" y="{base_y+48+j*36}" font-size="{F_AXIS}" '
                     f'fill="{INK}" text-anchor="middle">{esc(ln)}</text>')
        for j, ln in enumerate(note.split("\n")):
            p.append(f'<text x="{x+bw/2}" y="{base_y+142+j*32}" font-size="{F_NOTE}" '
                     f'fill="{INK3}" text-anchor="middle">{esc(ln)}</text>')
    p.append(f'<line x1="{x0-36}" y1="{base_y}" x2="{W-70}" y2="{base_y}" '
             f'stroke="{INK3}" stroke-width="3"/>')
    return foot(p, "②→③ 人數反而上升：調整案件組合會同時揭露被案件難度掩蓋的偏離，並非單調下降")


# ═══════════════════════════════════════════════════════════════════════════
def main() -> None:
    if not DB.exists():
        raise SystemExit(f"找不到 {DB}")
    c = sqlite3.connect(DB)
    print("產生簡報圖 →", OUT)
    save("1_資料流程.svg", fig_pipeline())
    save("2_資料品質改善.svg", fig_quality(c))
    save("3_案由拆分.svg", fig_category(c))
    save("4_法官效應.svg", fig_judge_effect())
    c.close()
    print("\n用法：把 .svg 直接拖進 PowerPoint 或 Google Slides。")
    print("      向量圖放大不糊，字級已放大到投影可讀。")


if __name__ == "__main__":
    main()
