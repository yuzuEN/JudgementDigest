"""
所有 LLM 廠商共用的介面。任務（tasks.py）只認得這裡的東西，換廠商不用改任務。
"""
from typing import Dict, Protocol


class LLMError(Exception):
    """呼叫失敗、逾時或回傳格式不對。呼叫端要有退路，LLM 壞了不能讓網站壞。"""


class LLMClient(Protocol):
    name: str

    def generate_json(self, system: str, user: str, schema: Dict) -> Dict:
        """回傳符合 schema 的 dict；失敗就丟 LLMError。"""
