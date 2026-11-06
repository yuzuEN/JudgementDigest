"""
後端設定（環境變數）：

    JD_ARTIFACTS_DIR   模型與檢索資料的位置（預設見 config.py：repo 根目錄的 artifacts/）
    JD_BACKEND_MODE    auto（預設）：有模型就用真的，沒有就回傳示例資料；mock：一律回傳示例資料
    JD_CORS_ORIGINS    允許的前端網址，逗號分隔（預設允許本機的 Vite 開發伺服器）
    JD_LLM_PROVIDER    gemini、fake；留空就不用 LLM，追問用固定題庫
    JD_LLM_MODEL       模型名稱（留空用該廠商的預設）
    GEMINI_API_KEY     Gemini 的 key
    JD_LLM_PER_IP_HOUR 同一個 IP 每小時最多呼叫 LLM 幾次（預設 10）
    JD_LLM_PER_DAY     全站每天最多呼叫 LLM 幾次（預設 300）

本機開發時可以寫在 repo 根目錄的 .env（範本是 .env.example，.env 不進 Git）。
"""
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from dotenv import load_dotenv

import config


@dataclass
class Settings:
    artifacts_dir: Path = config.ARTIFACTS_DIR
    mode: str = "auto"
    llm_provider: str = ""
    llm_model: str = ""
    llm_api_key: str = field(default="", repr=False)
    llm_per_ip_hour: int = 10
    llm_per_day: int = 300
    cors_origins: List[str] = field(default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"])

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv(config.ROOT / ".env")      # 已經設定的環境變數優先
        origins = os.environ.get("JD_CORS_ORIGINS")
        return cls(artifacts_dir=config.ARTIFACTS_DIR,
                   mode=os.environ.get("JD_BACKEND_MODE", "auto"),
                   llm_provider=os.environ.get("JD_LLM_PROVIDER", "").strip().lower(),
                   llm_model=os.environ.get("JD_LLM_MODEL", "").strip(),
                   llm_api_key=os.environ.get("GEMINI_API_KEY", "").strip(),
                   llm_per_ip_hour=int(os.environ.get("JD_LLM_PER_IP_HOUR") or 10),
                   llm_per_day=int(os.environ.get("JD_LLM_PER_DAY") or 300),
                   **({"cors_origins": [o.strip() for o in origins.split(",") if o.strip()]} if origins else {}))
