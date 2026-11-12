"""
資料、實驗輸出與模型檔的路徑。資料與模型不進 repo，預設是作者本機的位置，
其他人用環境變數指到自己的位置即可（例：set JD_DATASET_DIR=D:\\jd\\data）。

    JD_MAIN_DB        正式資料庫（judgments.db，含簡易庭；相似判決檢索用）
    JD_WORK_DB        分析用資料庫（judgments_work_20261112.db，規則 2.5.2 的固定副本；舊的 20261108、20261014 保留）
    JD_DATASET_DIR    文字資料集 text_dataset_{版本}.csv 所在的資料夾
    JD_FIELDS_PKL     analysis_fields.pkl（v5 的樣本母體與結構化變數，見 docs/資料版本.md）
    JD_OUTPUT_DIR     實驗輸出（metrics、預測、報告）
    JD_ARTIFACTS_DIR  上線用的模型與檢索索引（後端讀這裡）

模型與檢索資料的 meta.json 用 build_info() 記錄是哪個程式版本、哪個 scikit-learn 建的；
載入模型時用 warn_if_other_sklearn() 比對，版本不同就在 log 提醒。
"""
import logging
import os
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _path(env: str, default: Path) -> Path:
    value = os.environ.get(env)
    return Path(value) if value else default


MAIN_DB = _path("JD_MAIN_DB", ROOT / "judgments.db")
WORK_DB = _path("JD_WORK_DB", ROOT / "judgments_work_20261112.db")
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


def git_commit() -> str:
    """目前的 commit（短）；工作區有還沒 commit 的改動就加上 -dirty。不在 Git 裡（或沒有 git）回傳空字串。"""
    def git(*args):
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=10)
    try:
        head = git("rev-parse", "--short", "HEAD")
        if head.returncode:
            return ""
        dirty = git("status", "--porcelain", "--untracked-files=no").stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""
    return head.stdout.strip() + ("-dirty" if dirty else "")


def build_info() -> dict:
    """寫進 meta.json：用哪個程式版本、哪個 scikit-learn 與 Python 訓練（模型檔不進 Git，要靠這些對回去）。"""
    import sklearn
    return {"git_commit": git_commit(), "sklearn": sklearn.__version__, "python": platform.python_version()}


def warn_if_other_sklearn(meta: dict, name: str) -> None:
    """模型是用別的 scikit-learn 版本訓練的就在 log 提醒（版本不同時讀出來的模型可能壞掉或結果不同）。
    舊的 meta 沒有記錄版本，不提醒。"""
    import sklearn
    trained = meta.get("sklearn")
    if trained and trained != sklearn.__version__:
        logging.getLogger(__name__).warning(
            "%s 是用 scikit-learn %s 訓練的，目前安裝的是 %s；請換成 requirements 固定的版本或重新訓練",
            name, trained, sklearn.__version__)
