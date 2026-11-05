"""
測試與本機開發用：JD_LLM_PROVIDER=fake，不連線、不花錢，記下送出的內容。
"""
from typing import Dict, List, Optional


class FakeClient:
    name = "fake"

    def __init__(self, reply: Optional[Dict] = None, error: Optional[Exception] = None):
        self.reply = reply if reply is not None else {"questions": [
            {"text": "（測試）對方有沒有說過為什麼不處理？", "why": "（測試）對方的理由常是爭點。"}]}
        self.error = error
        self.sent: List[str] = []

    def generate_json(self, system: str, user: str, schema: Dict) -> Dict:
        self.sent.append(user)
        if self.error:
            raise self.error
        return self.reply
