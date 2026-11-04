"""
後端設定（環境變數）：

    JD_ARTIFACTS_DIR   模型與檢索資料的位置（預設見 config.py：repo 根目錄的 artifacts/）
    JD_BACKEND_MODE    auto（預設）：有模型就用真的，沒有就回傳示例資料；mock：一律回傳示例資料
    JD_CORS_ORIGINS    允許的前端網址，逗號分隔（預設允許本機的 Vite 開發伺服器）
"""
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

import config


@dataclass
class Settings:
    artifacts_dir: Path = config.ARTIFACTS_DIR
    mode: str = "auto"
    cors_origins: List[str] = field(default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"])

    @classmethod
    def from_env(cls) -> "Settings":
        origins = os.environ.get("JD_CORS_ORIGINS")
        return cls(artifacts_dir=config.ARTIFACTS_DIR,
                   mode=os.environ.get("JD_BACKEND_MODE", "auto"),
                   **({"cors_origins": [o.strip() for o in origins.split(",") if o.strip()]} if origins else {}))
