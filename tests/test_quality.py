# -*- coding: utf-8 -*-
"""
backend/quality.py 的離線測試：看起來不像法律糾紛的描述要提醒，真實的糾紛不能誤判。
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.quality import looks_like_dispute  # noqa: E402


class TestLooksLikeDispute(unittest.TestCase):
    def test_everyday_text(self):
        for text in ("今天天氣很好，我想去海邊走走。", "請問紅燒牛肉要怎麼做才會入味？", "測試測試測試", "asdfghjkl", ""):
            self.assertFalse(looks_like_dispute(text), text)

    def test_disputes_in_plain_words(self):
        for text in ("朋友借我五萬元沒有還。", "房東不退押金", "老闆一直沒發薪水", "樓上一直漏水到我家", "對方開車撞到我",
                     "我被網路投資騙了", "收到地檢署的傳票", "爸爸的遺產被哥哥拿走"):
            self.assertTrue(looks_like_dispute(text), text)

    def test_amount_alone_counts(self):
        self.assertTrue(looks_like_dispute("對方要我付三十萬"))
        self.assertTrue(looks_like_dispute("總共 12,000 元"))


if __name__ == "__main__":
    unittest.main()
