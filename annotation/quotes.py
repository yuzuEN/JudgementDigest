"""
引文還原：模型寫的引文 → 在原文裡的完整範圍。標註（annotate.py）、抽查（spot_check.py）
和後端的判決導讀（backend/reasoning.py）共用，所以獨立成不依賴 API 的小模組。

v0.6：引文超過 100 字時寫「開頭〔略〕結尾」（手冊 v0.6 規則三）。
"""

from annotation.cues import MARK

__all__ = ["MARK", "MAX_SPAN", "MAX_SPAN_BY_LABEL", "MIN_HEAD", "MIN_TAIL", "resolve_quote"]

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
