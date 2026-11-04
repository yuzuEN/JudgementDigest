# -*- coding: utf-8 -*-
"""離線測試套件：python -m unittest discover -s tests -t . -v"""

import logging
import sys
from pathlib import Path

# 被測的程式都在 data_pipeline/，彼此以同資料夾的模組名稱 import
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "data_pipeline"))

# crawler.py、html_parser.py 在被匯入時會以 logging.basicConfig 把日誌寫進專案裡真正的
# crawler.log / parser.log。測試會刻意製造「區段未翻完」「清單頁無法復原」等錯誤情境，
# 若照常寫入，就會和正在背景執行的真實爬取日誌混在一起，事後檢查日誌時變成假警報。
# 先在根 logger 放一個 NullHandler：根 logger 已有 handler 時 basicConfig 是 no-op，
# 測試期間便不會寫入任何日誌檔，也不會輸出到主控台。assertLogs 會自行掛上 handler，不受影響。
logging.getLogger().addHandler(logging.NullHandler())
