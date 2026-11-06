"""
刑事：罪名、法條、刑度分布。

模型（artifacts/criminal_v1）在啟動時讀進記憶體；不存在時回傳示例資料（mock = true），伺服器照樣能啟動。
刑事的相似判決檢索還沒做：有模型時 similar 回傳空清單，前端顯示「開發中」，不拿示例判決充當真的。
"""
from pathlib import Path
from typing import Dict

from backend import mock
from criminal.models import service as model_service


class CriminalService:
    def __init__(self, artifacts_dir: Path, force_mock: bool = False):
        self.model = self.meta = None
        if force_mock:
            return
        model_dir = model_service.artifact_dir(artifacts_dir)
        if (model_dir / "model.joblib").exists():
            self.model, self.meta = model_service.load(model_dir)

    @property
    def mock(self) -> bool:
        return self.model is None

    def report(self, text: str) -> Dict:
        if self.mock:
            return mock.criminal_report()
        return {"charges": self.model.predict(text), "similar": [], "mock": False}
