# -*- coding: utf-8 -*-
"""criminal/models/lay_terms.py：使用者口語 → 判決書用語。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from criminal.models.lay_terms import to_legal  # noqa: E402


class TestLayTerms(unittest.TestCase):
    def test_common_lay_words(self):
        self.assertEqual(to_legal("我在超商偷了兩瓶飲料"), "被告在超商竊取兩瓶飲料")
        self.assertEqual(to_legal("我打了他一拳"), "被告毆打了他一拳")
        self.assertEqual(to_legal("撞到人之後沒有停下來就直接開走"), "撞擊人之後逃逸")
        self.assertEqual(to_legal("我把帳戶借給網友"), "被告把帳戶交付網友")

    def test_does_not_double_replace(self):
        self.assertEqual(to_legal("被詐騙集團騙了"), "被詐騙集團詐騙")
        self.assertEqual(to_legal("偷偷"), "偷偷")

    def test_steal_idioms_are_not_theft(self):
        # 2026-11-14 E1 檢索評估：「罵她去偷男人」被換成「竊取男人」，罪名猜成竊盜
        for text in ("罵她去偷男人", "說她偷客兄", "他偷吃被抓到", "在廁所偷拍", "偷看她洗澡"):
            self.assertNotIn("竊取", to_legal(text), text)
        self.assertEqual(to_legal("偷人家的錢"), "竊取人家的錢")
        self.assertEqual(to_legal("偷走機車"), "竊取機車")

    def test_my_relatives_are_not_the_defendant(self):
        self.assertEqual(to_legal("我拿刀砍我哥哥"), "被告持刀砍殺我哥哥")
        self.assertEqual(to_legal("我的手機"), "我的手機")


if __name__ == "__main__":
    unittest.main()
