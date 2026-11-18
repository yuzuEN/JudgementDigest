"""
論點單位切法比較：組員的 400 字段落（civil.insights._paragraphs）vs annotation.structure.units（N=800–2000）。

用法（在 repo 根目錄執行）：
    python tools/evaluate_units.py C:/jd_artifacts/civil_sample_3000.sqlite
不給路徑時讀目前資料夾的 civil_sample_3000.sqlite。
"""
import collections
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # repo 根目錄

from annotation.structure import headings, units  # noqa: E402
from civil.insights import _paragraphs  # noqa: E402

RULE = re.compile(r"(?:^|[。：:；，、）)\s])(?:次|又|復|再|惟|另|末)?按|所謂.{0,30}係指|定有明文")
CONCL = re.compile(r"為有理由|為無理由|應予准許|不應准許|即無不合|洵屬有據|並非無據|即非有據|於法有據|自得請求|係犯|核屬|即屬|自屬|應屬|構成(?!要件)|堪信|足認|堪認|難認|足見|不足採|無足採|以.{0,12}元為適當|為適當")

db = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('civil_sample_3000.sqlite')
c = sqlite3.connect(db)
docs = [r[0] for r in c.execute('select court from sections where length(court) > 0')]
n_head = [len(headings(t)[0]) for t in docs]
rej = sum(headings(t)[1] for t in docs); cand = sum(len(headings(t)[0]) for t in docs) + rej
lv = collections.Counter(l for t in docs for _, l, _ in headings(t)[0])
print(f"判決 {len(docs)} 件；有任何編號 {sum(x>0 for x in n_head)/len(docs):.1%}；"
      f"候選編號 {cand}，接受 {cand-rej}（{(cand-rej)/cand:.1%}）")
print("各層編號數:", dict(sorted(lv.items())))

def stats(name, seg_of):
    lens, sent, rule_units, rule_with_concl, n_units = [], 0, 0, 0, 0
    docs_trunc = 0
    for t in docs:
        segs = seg_of(t)
        trunc = False
        for text, how in segs:
            n_units += 1; lens.append(len(text))
            if how == "sentence":
                sent += 1; trunc = True
            if RULE.search(text):
                rule_units += 1; rule_with_concl += bool(CONCL.search(text))
        docs_trunc += trunc
    lens.sort()
    print(f"{name:<16} 單位數 {n_units:6d}  每件 {n_units/len(docs):5.1f}  長度中位數 {lens[len(lens)//2]:5d}  "
          f"90% {lens[int(len(lens)*.9)]:5d}  句號硬切 {sent/n_units:6.1%}  有硬切的判決 {docs_trunc/len(docs):6.1%}  "
          f"大前提與結論同單位 {rule_with_concl}/{rule_units} = {rule_with_concl/max(rule_units,1):.1%}")

def teammates(t):
    out = []
    for p in _paragraphs(t):
        out.append((p, "structure"))
    # 標記 400 字硬切：連續片段中，前一片段不是以編號結束、本片段不是以編號開頭 → 近似為硬切
    parts = [p for p in re.split(r"(?=(?:[一二三四五六七八九十]{1,3}|[壹貳參叁肆伍陸柒捌玖拾])、)|(?=[㈠-㈩])|(?=[(（][一二三四五六七八九十]{1,3}[)）])", t) if p.strip()]
    hard = sum(max(0, -(-len(p)//400) - 1) for p in parts)  # 每個原段落被 400 字切開的次數（近似）
    return [(p, "sentence" if i < hard else "structure") for i, (p, _) in enumerate(out)]

stats("組員(400字)", teammates)
for N in (800, 1200, 1600, 2000):
    stats(f"論點單位 N={N}", lambda t, N=N: [(t[s:e], how) for s, e, how in units(t, N)])
