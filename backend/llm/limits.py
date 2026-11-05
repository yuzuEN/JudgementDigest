"""
LLM 的用量上限：API 是公開的，沒有上限時任何人都能把預付額度刷完。
次數記在記憶體，重啟就歸零；後端只跑一個程序，所以這樣就夠。要跑多個程序時要改用共用的儲存。
"""
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Callable, Deque, Dict

TAIPEI = timezone(timedelta(hours=8))
HOUR = 3600


class UsageLimiter:
    def __init__(self, per_ip_hour: int, per_day: int, clock: Callable[[], float] = time.time):
        self.per_ip_hour, self.per_day, self.clock = per_ip_hour, per_day, clock
        self._lock = threading.Lock()
        self._recent: Dict[str, Deque[float]] = defaultdict(deque)
        self._day = ""
        self._today = 0

    def allow(self, ip: str) -> bool:
        """還有額度就記一次並回傳 True。"""
        now = self.clock()
        day = datetime.fromtimestamp(now, TAIPEI).strftime("%Y-%m-%d")
        with self._lock:
            if day != self._day:
                self._day, self._today = day, 0
                self._recent.clear()
            recent = self._recent[ip]
            while recent and now - recent[0] >= HOUR:
                recent.popleft()
            if self._today >= self.per_day or len(recent) >= self.per_ip_hour:
                return False
            recent.append(now)
            self._today += 1
            return True
