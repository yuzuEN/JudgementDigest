"""
Gemini（generateContent REST）。key 放在 header，不會出現在網址或錯誤訊息裡。
"""
import json
from typing import Dict

import httpx

from backend.llm.base import LLMError

BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
DEFAULT_MODEL = "gemini-3.1-flash-lite"
TIMEOUT = 20.0


class GeminiClient:
    name = "gemini"

    def __init__(self, api_key: str, model: str = "", transport=None):
        self.model = model or DEFAULT_MODEL
        self._http = httpx.Client(timeout=TIMEOUT, transport=transport, headers={"x-goog-api-key": api_key})

    def generate_json(self, system: str, user: str, schema: Dict) -> Dict:
        body = {"systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {"responseMimeType": "application/json", "responseJsonSchema": schema}}
        try:
            response = self._http.post(f"{BASE_URL}/{self.model}:generateContent", json=body)
        except httpx.HTTPError as e:
            raise LLMError(f"無法連線：{type(e).__name__}") from None
        if response.status_code != 200:
            raise LLMError(f"HTTP {response.status_code}")
        try:
            parts = response.json()["candidates"][0]["content"]["parts"]
            return json.loads("".join(p.get("text", "") for p in parts))
        except (KeyError, IndexError, TypeError, ValueError):
            raise LLMError("回應格式不對（可能被安全機制擋下）") from None
