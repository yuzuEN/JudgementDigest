"""
OpenAI（Chat Completions REST，Structured Outputs）。key 放在 header，不會出現在網址或錯誤訊息裡。
檔名不叫 openai.py，避免和官方套件撞名。
"""
import copy
import json
import logging
import time
from typing import Dict

import httpx

from backend.llm.base import LLMError

URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_MODEL = "gpt-4.1-mini"
TIMEOUT = 20.0
logger = logging.getLogger("uvicorn.error")    # 這個 logger 預設會顯示在 docker logs


def strict_schema(schema: Dict) -> Dict:
    """Structured Outputs 的 strict 模式要求每個 object 都列出全部欄位為 required、不允許多的欄位。"""
    out = copy.deepcopy(schema)

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                node["required"] = list(node["properties"])
                node["additionalProperties"] = False
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(out)
    return out


class OpenAIClient:
    name = "openai"
    vendor = "OpenAI"

    def __init__(self, api_key: str, model: str = "", transport=None):
        self.model = model or DEFAULT_MODEL
        self._http = httpx.Client(timeout=TIMEOUT, transport=transport, headers={"Authorization": f"Bearer {api_key}"})

    def generate_json(self, system: str, user: str, schema: Dict) -> Dict:
        body = {"model": self.model,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "response_format": {"type": "json_schema",
                                    "json_schema": {"name": "result", "strict": True, "schema": strict_schema(schema)}}}
        started = time.time()
        try:
            response = self._http.post(URL, json=body)
        except httpx.HTTPError as e:
            raise LLMError(f"無法連線：{type(e).__name__}") from None
        if response.status_code != 200:
            raise LLMError(f"HTTP {response.status_code}")
        try:
            data = response.json()
            self._log_usage(data, time.time() - started)
            message = data["choices"][0]["message"]
            if message.get("refusal"):
                raise LLMError("模型拒絕回答")
            return json.loads(message["content"])
        except (KeyError, IndexError, TypeError, ValueError):
            raise LLMError("回應格式不對") from None

    def _log_usage(self, data: Dict, seconds: float) -> None:
        """只記 token 數，不記案情內容。"""
        usage = data.get("usage") or {}
        logger.info("LLM 用量 model=%s input=%s output=%s seconds=%.1f", self.model,
                    usage.get("prompt_tokens", "?"), usage.get("completion_tokens", "?"), seconds)
