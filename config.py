"""
資料、實驗輸出與模型檔的路徑。資料與模型不進 repo，預設是作者本機的位置，
其他人用環境變數指到自己的位置即可（例：set JD_DATASET_DIR=D:\\jd\\data）。

    JD_MAIN_DB        正式資料庫（judgments.db，含簡易庭；相似判決檢索用）
    JD_WORK_DB        分析用資料庫（judgments_work_20261108.db，規則 2.5.1 的固定副本；舊的 20261014 保留）
    JD_DATASET_DIR    文字資料集 text_dataset_{版本}.csv 所在的資料夾
    JD_FIELDS_PKL     analysis_fields.pkl（v5 的樣本母體與結構化變數，見 docs/資料版本.md）
    JD_OUTPUT_DIR     實驗輸出（metrics、預測、報告）
    JD_ARTIFACTS_DIR  上線用的模型與檢索索引（後端讀這裡）
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _path(env: str, default: Path) -> Path:
    value = os.environ.get(env)
    return Path(value) if value else default


MAIN_DB = _path("JD_MAIN_DB", ROOT / "judgments.db")
WORK_DB = _path("JD_WORK_DB", ROOT / "judgments_work_20261108.db")
DATASET_DIR = _path("JD_DATASET_DIR", ROOT / "text_analysis" / "data")
FIELDS_PKL = _path("JD_FIELDS_PKL", ROOT / "field_validation" / "analysis_fields.pkl")
OUTPUT_DIR = _path("JD_OUTPUT_DIR", ROOT / "text_analysis" / "output")
ARTIFACTS_DIR = _path("JD_ARTIFACTS_DIR", ROOT / "artifacts")


def dataset_path(version: str) -> Path:
    return DATASET_DIR / f"text_dataset_{version}.csv"


def use_data_pipeline() -> None:
    """data_pipeline/ 的程式以同資料夾的模組名稱互相 import，要用它們（structuring 等）時先把資料夾加進路徑。"""
    path = str(ROOT / "data_pipeline")
    if path not in sys.path:
        sys.path.insert(0, path)
