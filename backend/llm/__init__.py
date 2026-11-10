"""
依設定選擇 LLM 廠商。新增廠商：寫一個有 generate_json 的類別，在 create_client 加一行。
沒有設定或沒有 key 時回傳 None，系統改用固定題庫。
"""
from typing import Optional

from backend.llm.base import LLMClient, LLMError
from backend.llm.fake import FakeClient
from backend.llm.gemini import GeminiClient
from backend.llm.openai_client import OpenAIClient

__all__ = ["LLMClient", "LLMError", "create_client"]


def create_client(provider: str, model: str = "", api_key: str = "") -> Optional[LLMClient]:
    if not provider:
        return None
    if provider == "fake":
        return FakeClient()
    if provider == "gemini":
        if not api_key:
            raise RuntimeError("JD_LLM_PROVIDER=gemini 但沒有設定 GEMINI_API_KEY")
        return GeminiClient(api_key, model)
    if provider == "openai":
        if not api_key:
            raise RuntimeError("JD_LLM_PROVIDER=openai 但沒有設定 OPENAI_API_KEY")
        return OpenAIClient(api_key, model)
    raise RuntimeError(f"不認得的 JD_LLM_PROVIDER：{provider}")
