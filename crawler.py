"""
Part 1 — 司法院裁判書自動爬蟲
目標網站: https://judgment.judicial.gov.tw/FJUD/default.aspx

使用方式:
    python crawler.py [關鍵字] [-n 筆數] [--no-headless]
                      [--start-date YYYY/MM/DD] [--end-date YYYY/MM/DD]
                      [--case-year-start 民國年] [--case-year-end 民國年]
                      [--court 法院] [--case-type 民事] [--judgment-type 判決]

範例:
    python crawler.py 詐欺 -n 20
    python crawler.py 勞動契約 -n 10 --start-date 2023/01/01 --end-date 2023/12/31 --no-headless
    python crawler.py -n 50 --court 臺灣臺北地方法院 --case-type 民事 --judgment-type 判決 \
                      --start-date 2025/01/01 --end-date 2025/01/07
"""

import sqlite3
import time
import os
import random
import re
import argparse
import logging
from datetime import date, datetime
from typing import Optional, List, Dict, Tuple
from urllib.parse import unquote

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import (
    TimeoutException, NoSuchElementException, WebDriverException
)
from webdriver_manager.chrome import ChromeDriverManager

# ─── 設定 ────────────────────────────────────────────────────────────────────
BASE_URL    = "https://judgment.judicial.gov.tw/FJUD/default.aspx"
BASE_URL_AD = "https://judgment.judicial.gov.tw/FJUD/default_AD.aspx"  # 進階搜尋（含日期篩選）
DB_PATH   = "judgments.db"
HTML_DIR  = "html_cache"
LOG_FILE  = "crawler.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


# ─── 資料庫初始化 ─────────────────────────────────────────────────────────────
def init_db() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS crawl_records (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            case_number   TEXT    UNIQUE,
            court         TEXT,
            case_title    TEXT,
            judgment_date TEXT,
            source_url    TEXT,
            html_file     TEXT,
            keyword       TEXT,
            crawled_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            parsed        INTEGER   DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()
    logger.info("Database ready: %s", DB_PATH)


# ─── WebDriver 設定 ───────────────────────────────────────────────────────────
def build_driver(headless: bool = True) -> webdriver.Chrome:
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--lang=zh-TW")
    # 停用圖片、字型等非必要資源，大幅減少等待時間
    opts.add_argument("--blink-settings=imagesEnabled=false")
    opts.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    # eager：等待 DOMContentLoaded 即返回（HTML 已解析，圖片/追蹤器仍在背景載入）
    # 裁判書正文在初始 HTML 中，不需等完整頁面；比 "none" 穩定，不會卡住 find_element
    opts.page_load_strategy = "eager"

    # 避免偵測 WebDriver
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)

    service = Service(ChromeDriverManager().install())
    driver  = webdriver.Chrome(service=service, options=opts)
    driver.set_page_load_timeout(90)

    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"},
    )

    # 封鎖字型、追蹤器等非必要請求
    driver.execute_cdp_cmd("Network.enable", {})
    driver.execute_cdp_cmd("Network.setBlockedURLs", {"urls": [
        "*.woff", "*.woff2", "*.ttf", "*.otf", "*.eot",
        "*.mp4", "*.webm", "*.mp3",
        "*google-analytics*", "*googletagmanager*",
        "*facebook.com/tr*", "*doubleclick*", "*adsystem*",
    ]})

    return driver


# ─── 速率控制 ─────────────────────────────────────────────────────────────────
# 全年爬取會送出上萬次請求、連續數小時。固定間隔沒有回饋迴路 —— 伺服器開始拒絕時
# 仍以原速持續敲，只會把情況推得更糟（實測：密集查詢會讓結果集 q= hash 被作廢，
# 清單頁全部變成「查詢設定錯誤」）。Pacer 讓節奏能隨伺服器反應調整：
#   正常   → 基礎間隔 × 隨機抖動（避免固定節奏，也避免與伺服器清理週期共振）
#   出錯   → 全域倍率加倍（上限 8 倍），後續每個請求都跟著放慢
#   連續錯 → 直接長暫停，讓對方喘口氣，而不是硬打
#   恢復   → 連續成功一段時間後倍率減半，逐步回到正常速度
_DEFAULT_DELAY   = 1.0      # 詳細頁基礎間隔（秒）；清單頁與查詢依比例換算
_LIST_DELAY_RATIO = 0.6     # 清單頁翻頁較輕量，用 0.6 倍
_JITTER          = 0.3      # 間隔的隨機抖動幅度（±30%）
_MAX_SLOWDOWN    = 8.0      # 全域降速倍率上限
_RECOVER_STREAK  = 10       # 連續成功幾次後嘗試恢復速度
_BRAKE_THRESHOLD = 5        # 連續失敗幾次觸發長暫停
_BRAKE_PAUSE     = 300.0    # 長暫停秒數


class Pacer:
    """
    請求節奏控制器。單執行緒使用，跨區段共用同一個實例即可讓降速狀態延續。

    kind: "detail"（裁判書詳細頁）/ "list"（清單翻頁）/ "query"（送出查詢）
    """

    def __init__(
        self,
        delay:           float = _DEFAULT_DELAY,
        jitter:          float = _JITTER,
        brake_threshold: int   = _BRAKE_THRESHOLD,
        brake_pause:     float = _BRAKE_PAUSE,
    ):
        self.delay           = max(0.0, delay)
        self.jitter          = jitter
        self.brake_threshold = brake_threshold
        self.brake_pause     = brake_pause
        self.multiplier      = 1.0
        self.requests        = 0
        self.slowdowns       = 0
        self.brakes          = 0
        self.started         = time.time()
        self._ok_streak      = 0
        self._fail_streak    = 0

    def _base(self, kind: str) -> float:
        return self.delay * (_LIST_DELAY_RATIO if kind == "list" else 1.0)

    def wait(self, kind: str = "detail") -> float:
        """送出下一個請求前的等待。回傳實際等待秒數（方便測試與記錄）。"""
        base = self._base(kind) * self.multiplier
        secs = base * random.uniform(1.0 - self.jitter, 1.0 + self.jitter) if base else 0.0
        if secs:
            time.sleep(secs)
        self.requests += 1
        return secs

    def on_success(self) -> None:
        """請求成功。連續成功夠多次就把降速倍率收斂回來。"""
        self._fail_streak = 0
        self._ok_streak  += 1
        if self.multiplier > 1.0 and self._ok_streak >= _RECOVER_STREAK:
            self.multiplier = max(1.0, self.multiplier / 2.0)
            self._ok_streak = 0
            logger.info("速率恢復：間隔倍率 → x%.1f", self.multiplier)

    def on_failure(self, reason: str = "") -> None:
        """
        請求失敗（錯誤頁、逾時、WebDriver 異常）。
        立即全域降速；連續失敗達門檻則長暫停 —— 此時繼續敲只會延長被拒的時間。
        """
        self._ok_streak = 0
        self._fail_streak += 1
        if self.multiplier < _MAX_SLOWDOWN:
            self.multiplier = min(_MAX_SLOWDOWN, self.multiplier * 2.0)
            self.slowdowns += 1
            logger.warning("偵測到失敗（%s）→ 降速，間隔倍率 x%.1f", reason or "?", self.multiplier)
        if self._fail_streak >= self.brake_threshold:
            self.brakes += 1
            logger.error(
                "連續 %d 次失敗 → 暫停 %.0f 秒讓伺服器恢復（第 %d 次）",
                self._fail_streak, self.brake_pause, self.brakes,
            )
            time.sleep(self.brake_pause)
            self._fail_streak = 0

    def summary(self) -> str:
        elapsed = max(1e-9, time.time() - self.started)
        rpm = self.requests / (elapsed / 60.0)
        return (f"請求 {self.requests} 次 / {elapsed / 60.0:.1f} 分鐘 = {rpm:.1f} 次/分；"
                f"降速 {self.slowdowns} 次、長暫停 {self.brakes} 次、"
                f"目前倍率 x{self.multiplier:.1f}")


# ─── HTML 完整性檢查 ──────────────────────────────────────────────────────────
_MIN_COMPLETE_SIZE = 5_000  # 完整裁判書 HTML 最少應有 5 KB

def _is_html_content_complete(html: str) -> bool:
    """True 表示 HTML 字串包含完整裁判書正文（非 stub）。"""
    if len(html) < _MIN_COMPLETE_SIZE:
        return False
    return 'id="jud"' in html or '"htmlcontent"' in html


def _is_html_complete(html_file: str) -> bool:
    """
    True 表示 html_file 存在且包含完整裁判書內容（非 stub 頁面）。
    Stub 頁面：瀏覽器在 JS 注入內容前即停止，僅有 <head> 而無正文，通常 < 5 KB。
    以 id="jud" 或 htmlcontent 作為正文存在的標記。
    """
    if not html_file or not os.path.exists(html_file):
        return False
    if os.path.getsize(html_file) < _MIN_COMPLETE_SIZE:
        return False
    try:
        with open(html_file, encoding="utf-8", errors="ignore") as f:
            chunk = f.read(20_000)
        return 'id="jud"' in chunk or '"htmlcontent"' in chunk
    except OSError:
        return False


# ─── HTML 儲存 ────────────────────────────────────────────────────────────────
def save_html(html: str, case_number: str) -> str:
    safe = re.sub(r'[\\/*?:"<>|,\s]', "_", case_number)
    path = os.path.join(HTML_DIR, f"{safe}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path


# ─── 資料庫寫入 ───────────────────────────────────────────────────────────────
def upsert_record(
    case_number: str,
    court: str,
    case_title: str,
    judgment_date: str,
    source_url: str,
    html_file: str,
    keyword: str,
) -> bool:
    conn = sqlite3.connect(DB_PATH)
    c    = conn.cursor()
    try:
        c.execute(
            """INSERT OR IGNORE INTO crawl_records
               (case_number, court, case_title, judgment_date, source_url, html_file, keyword)
               VALUES (?,?,?,?,?,?,?)""",
            (case_number, court, case_title, judgment_date, source_url, html_file, keyword),
        )
        conn.commit()
        if c.rowcount:
            logger.info("  Saved  → %s", case_number)
            return True
        logger.info("  Skip   → %s (already exists)", case_number)
        return False
    finally:
        conn.close()


def _url_case_key(url: str) -> Tuple[str, str, str]:
    """
    從 data.aspx?id=COURT,YEAR,TYPE,NUM,... 解析 (year, type, number)。
    用於驗證下載的 HTML 內容是否與預期案件對應。
    例：id=SCDV%2c115%2c消債更%2c37%2c... → ('115', '消債更', '37')
    """
    try:
        id_part = url.split("id=", 1)[1].split("&")[0]
        parts   = unquote(id_part).split(",")
        if len(parts) >= 4:
            return parts[1].strip(), parts[2].strip(), parts[3].strip()
    except Exception:
        pass
    return "", "", ""


def _html_matches_url(html: str, url: str) -> bool:
    """
    確認 HTML 頁面標題中包含 URL 所對應的年度、案件類型、案號。
    若三者（year, type, number）均出現在標題中，視為內容相符；
    否則視為 stale page（瀏覽器載入了上一筆案件的快取內容）。
    """
    year, ctype, cnum = _url_case_key(url)
    if not year:
        return True  # 無法解析 URL 時，略過驗證

    title_m = re.search(r"<title>\s*(.*?)\s*</title>", html[:2000], re.DOTALL)
    if not title_m:
        return True  # 無 title 時，略過驗證

    title_norm = re.sub(r"\s+", "", title_m.group(1))
    return all(k in title_norm for k in (year, ctype, cnum))


def _mark_recrawled(case_number: str, html_file: str) -> None:
    """Stub 重新爬取後：更新 html_file 路徑，並重設 parsed=0 觸發重新解析。"""
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "UPDATE crawl_records SET html_file=?, parsed=0, crawled_at=CURRENT_TIMESTAMP "
        "WHERE case_number=?",
        (html_file, case_number),
    )
    conn.commit()
    conn.close()
    logger.info("  Updated → %s (stub replaced with complete HTML)", case_number)


# ─── 單筆裁判書頁面 ───────────────────────────────────────────────────────────
def crawl_detail_page(driver: webdriver.Chrome, url: str, case_number: str) -> Optional[str]:
    """
    導航至 url 並儲存 HTML。
    page_load_strategy="eager"：driver.get() 在 DOMContentLoaded 後返回；
    裁判書正文在初始 HTML 中，此時已可取得。

    Timeout 後偵測 stale page：若 driver.current_url 仍指向上一筆案件，
    代表本次導航尚未成功，直接跳過（避免用錯誤內容覆蓋目標檔案）。
    """
    try:
        driver.get(url)
    except TimeoutException:
        logger.warning("  Page load timeout for %s — checking URL", case_number)
        try:
            driver.execute_script("window.stop()")
        except Exception:
            pass
        time.sleep(0.8)

        # 比對 id= 參數前 20 字元：若不符表示瀏覽器未成功導航，跳過儲存
        def _id(u: str) -> str:
            return u.split("id=", 1)[1][:20] if "id=" in u else ""

        if _id(url) and _id(url) != _id(driver.current_url):
            logger.warning("  Stale page detected for %s (URL mismatch) — skipping", case_number)
            return None
    except Exception as exc:
        logger.error("  Navigation error for %s — %s", case_number, exc)
        return None

    try:
        html = driver.page_source

        # 若頁面尚未完整載入（stub：僅有 <head> 無正文），等待一次再試
        if not _is_html_content_complete(html):
            time.sleep(2.5)
            html = driver.page_source

        # 內容驗證：確認 HTML 頁面標題與預期案號相符（防止 stale page 覆蓋正確檔案）
        if not _html_matches_url(html, url):
            logger.warning(
                "  Content mismatch for %s — page title does not match URL key — skipping",
                case_number,
            )
            return None

        # 二次確認：若仍為 stub，跳過（不存入殘缺檔案）
        if not _is_html_content_complete(html):
            logger.warning(
                "  Stub HTML for %s (size=%d) — content not loaded — skipping",
                case_number, len(html),
            )
            return None

        html_file = save_html(html, case_number)
        return html_file
    except Exception as exc:
        logger.error("  Failed to save HTML for %s — %s", case_number, exc)
        return None


# ─── Debug 輔助 ───────────────────────────────────────────────────────────────
def _save_debug_html(driver: webdriver.Chrome, tag: str = "debug") -> None:
    path = f"{tag}_page.html"
    with open(path, "w", encoding="utf-8") as f:
        f.write(driver.page_source)
    logger.info("Debug HTML → %s  (URL: %s)", path, driver.current_url)


# ─── Step A: 取得結果列表頁網址 ───────────────────────────────────────────────
# 搜尋後司法院頁面在 default.aspx 上以 AJAX 顯示摘要，
# 並提供 qryresultlst.aspx?ty=JUDBOOK&q=<hash> 的「查詢結果」連結。
_LIST_CSS = "a[href*='qryresultlst.aspx?ty=JUDBOOK']"

def _get_results_list_url(driver: webdriver.Chrome) -> Optional[str]:
    """等待並回傳完整結果列表頁的 URL（不含法院篩選參數的版本）。"""
    try:
        WebDriverWait(driver, 25).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, _LIST_CSS))
        )
    except TimeoutException:
        logger.warning("qryresultlst link not found — saving debug HTML")
        _save_debug_html(driver, "search_result")
        return None

    links = driver.find_elements(By.CSS_SELECTOR, _LIST_CSS)
    # 優先選「不含 gy=」的那個（完整結果，非依法院篩選）
    for lnk in links:
        href = lnk.get_attribute("href") or ""
        if href and "gy=" not in href:
            logger.info("Results list URL: %s", href)
            return href
    # 備援：直接用第一個
    href = links[0].get_attribute("href") if links else None
    logger.info("Results list URL (fallback): %s", href)
    return href


def _collect_court_links(driver: webdriver.Chrome) -> List[Tuple[str, str]]:
    """
    從當前頁面收集所有「依法院」分群子連結。
    回傳 [(url, label), ...] 列表（依頁面出現順序）。
    法院代碼格式如 TPHV（高等法院民事）、TPDV（臺北地方法院民事）等。
    """
    court_links: List[Tuple[str, str]] = []
    seen: set = set()
    for lnk in driver.find_elements(By.CSS_SELECTOR, _LIST_CSS):
        href = lnk.get_attribute("href") or ""
        if "gy=jcourt&gc=" not in href:
            continue
        m = re.search(r"gy=jcourt&gc=([^&]+)", href)
        if not m:
            continue
        code = m.group(1)
        if code in seen:
            continue
        seen.add(code)
        # lnk.text may include a result-count on a second line — keep only the first line
        raw_label = lnk.text.strip()
        label = raw_label.split("\n")[0].strip() or code
        court_links.append((href, label))
    logger.info("Collected %d court sub-links", len(court_links))
    return court_links


def _collect_year_links(driver: webdriver.Chrome) -> List[Tuple[str, int, bool]]:
    """
    從搜尋結果摘要頁收集「依案號年度分群」子連結（?gy=jyear&gc=<民國年>）。
    回傳 [(url, 年度, 是否為統括桶), ...]，依年度由新到舊排序。

    gc 為負值（例如 -110）代表「該年以前」的統括桶，涵蓋多個年度，
    因此仍需搭配本地過濾才能精確切到使用者指定的範圍。
    必須在離開摘要頁前呼叫 —— 導覽到 qryresultlst.aspx 後這些連結就不存在了。
    """
    out: List[Tuple[str, int, bool]] = []
    seen: set = set()
    for lnk in driver.find_elements(By.CSS_SELECTOR, "a[href*='gy=jyear']"):
        href = lnk.get_attribute("href") or ""
        m = re.search(r"gy=jyear&gc=(-?\d+)", href)
        if not m:
            continue
        raw = int(m.group(1))
        if raw in seen:
            continue
        seen.add(raw)
        out.append((href, abs(raw), raw < 0))
    # 由新到舊；統括桶（負值）年度較舊，排在同年度之後
    out.sort(key=lambda t: (t[1], not t[2]), reverse=True)
    logger.info("Collected %d year sub-links", len(out))
    return out


def _case_number_year(url: str) -> Optional[int]:
    """
    從 data.aspx?ty=JD&id=COURT,YEAR,TYPE,NUM,DATE 解析「字號年度」（ROC）。
    例：id=TPHV,112,上,750,20260422 → 112
    ?gy=jyear&gc=<year> 依「字號年度」分群，用此函式保持一致。
    """
    try:
        id_part = url.split("id=", 1)[1].split("&")[0]
        parts   = unquote(id_part).split(",")
        if len(parts) >= 2:
            return int(parts[1].strip())
    except Exception:
        pass
    return None


def _judgment_date(url: str) -> str:
    """
    從 data.aspx?ty=JD&id=COURT,YEAR,TYPE,NUM,DATE 解析「裁判日期」，回傳 ISO(西元) YYYY-MM-DD。
    例：id=TPHV,112,上,750,20260422 → "2026-04-22"
    與 _case_number_year() 取的「案號年度」是兩回事：兩者可相差數年。
    解析失敗回傳空字串。
    """
    try:
        id_part = url.split("id=", 1)[1].split("&")[0]
        parts   = unquote(id_part).split(",")
        if len(parts) >= 5:
            raw = parts[4].strip()
            if len(raw) == 8 and raw.isdigit():
                return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
    except Exception:
        pass
    return ""


# ─── 進階搜尋（default_AD.aspx）───────────────────────────────────────────────
# 簡易搜尋只能用 ?gy=/&gc= 分群，而 gy/gc 是「單一互斥軸」（法院、年度、審級三選一），
# 且每個結果集硬性上限 500 筆 —— 單靠分群無法取得超過 500 筆的完整資料。
# 進階搜尋可把裁判日期寫進查詢本身，每個日期區間產生獨立的 q= hash、
# 各自享有自己的 500 額度，因此切到每段 < 500 就能完整取得。
_RESULT_LIMIT = 500          # 單一結果集可翻取的硬性上限
_AD_DATE_FIELDS = ("dy1", "dm1", "dd1", "dy2", "dm2", "dd2")

# 進階搜尋的「裁判法院」（jud_court 複選清單）選項值。
# 法院與案件類別都寫進查詢本身，因此各自產生獨立的 q= hash、獨立的 500 額度。
_COURT_CODES = {
    "憲法法庭":                   "JCC",
    "司法院刑事補償法庭":         "TPC",
    "司法院－訴願決定":           "TPU",
    "最高法院":                   "TPS",
    "最高行政法院":               "TPA",
    "懲戒法院－懲戒法庭":         "TPP",
    "懲戒法院－職務法庭":         "TPJ",
    "臺灣高等法院":               "TPH",
    "臺灣高等法院－訴願決定":     "001",
    "臺北高等行政法院 高等庭":    "TPB",
    "臺北高等行政法院 地方庭":    "TPT",
    "臺中高等行政法院 高等庭":    "TCB",
    "臺中高等行政法院 地方庭":    "TCT",
    "高雄高等行政法院 高等庭":    "KSB",
    "高雄高等行政法院 地方庭":    "KST",
    "智慧財產及商業法院":         "IPC",
    "臺灣高等法院 臺中分院":      "TCH",
    "臺灣高等法院 臺南分院":      "TNH",
    "臺灣高等法院 高雄分院":      "KSH",
    "臺灣高等法院 花蓮分院":      "HLH",
    "臺灣臺北地方法院":           "TPD",
    "臺灣士林地方法院":           "SLD",
    "臺灣新北地方法院":           "PCD",
    "臺灣宜蘭地方法院":           "ILD",
    "臺灣基隆地方法院":           "KLD",
    "臺灣桃園地方法院":           "TYD",
    "臺灣新竹地方法院":           "SCD",
    "臺灣苗栗地方法院":           "MLD",
    "臺灣臺中地方法院":           "TCD",
    "臺灣彰化地方法院":           "CHD",
    "臺灣南投地方法院":           "NTD",
    "臺灣雲林地方法院":           "ULD",
    "臺灣嘉義地方法院":           "CYD",
    "臺灣臺南地方法院":           "TND",
    "臺灣高雄地方法院":           "KSD",
    "臺灣橋頭地方法院":           "CTD",
    "臺灣花蓮地方法院":           "HLD",
    "臺灣臺東地方法院":           "TTD",
    "臺灣屏東地方法院":           "PTD",
    "臺灣澎湖地方法院":           "PHD",
    "福建高等法院金門分院":       "KMH",
    "福建金門地方法院":           "KMD",
    "福建連江地方法院":           "LCD",
    "臺灣高雄少年及家事法院":     "KSY",
}

# 進階搜尋的「案件類別」（jud_sys checkbox）值。未勾選 = 全選。
_CASE_SYS_CODES = {
    "憲法": "C", "民事": "V", "刑事": "M", "行政": "A", "懲戒": "P",
}

# 裁判種類只能在結果清單頁過濾 —— 進階搜尋沒有「判決／裁定」欄位。
# 清單上的裁判字號尾端固定寫明種類（例：「…第 1 號民事判決」），據此過濾即可，
# 且過濾發生在下載之前，可省下大量不需要的詳細頁請求。
_JUDGMENT_TYPES = ("判決", "裁定")


def _court_code(name: str) -> str:
    """法院名稱或代碼 → jud_court 選項值；無法辨識回傳空字串。"""
    raw = (name or "").strip()
    if not raw:
        return ""
    if raw.upper() in set(_COURT_CODES.values()):
        return raw.upper()
    norm = raw.replace("台", "臺")
    if norm in _COURT_CODES:
        return _COURT_CODES[norm]
    # 允許簡寫（例如「臺北地方法院」「臺北地院」）—— 僅在唯一命中時接受
    cand = [c for n, c in _COURT_CODES.items() if norm in n]
    if len(cand) == 1:
        return cand[0]
    if not cand and norm.endswith("地院"):
        return _court_code(norm[:-2] + "地方法院")
    return ""


def _sys_code(name: str) -> str:
    """案件類別名稱或代碼 → jud_sys checkbox 值；無法辨識回傳空字串。"""
    raw = (name or "").strip()
    if not raw:
        return ""
    if raw.upper() in set(_CASE_SYS_CODES.values()):
        return raw.upper()
    return _CASE_SYS_CODES.get(raw, "")


def _parse_ad_date(date_str: str) -> Optional[date]:
    """
    西元 YYYY/MM/DD（或 YYYY-MM-DD）→ date；無法解析時回傳 None。

    用 date() 建構而非單純 split，是為了連「不存在的日期」一起擋掉：
    2024/13/45、2025/02/30 原本都會被拆成數字送進查詢表單。年份 <= 1911
    則多半是誤把民國年填進來（114/03/01 會算出 -1797 年）。
    """
    try:
        y, m, d = re.split(r"[/-]", date_str.strip())
        g = date(int(y), int(m), int(d))
    except Exception:
        return None
    return g if g.year > 1911 else None


def _roc_parts(date_str: str) -> Optional[Tuple[int, int, int]]:
    """西元 YYYY/MM/DD（或 YYYY-MM-DD）→ (民國年, 月, 日)。"""
    g = _parse_ad_date(date_str)
    return (g.year - 1911, g.month, g.day) if g else None


def parse_date_arg(value: str) -> date:
    """
    CLI 的日期參數 → date。不合法時拋 ValueError，訊息可直接交給 argparse 顯示。

    日期參數若被靜默忽略，查詢會變成「沒有日期範圍」—— 使用者以為在抓一週，
    實際上在抓全部。所以寧可在開瀏覽器之前就中止。
    """
    g = _parse_ad_date(value)
    if g is None:
        raise ValueError(f"日期格式錯誤：{value}（應為西元 YYYY/MM/DD，例如 2025/01/07）")
    return g


def resolve_date_range(
    start_date: str = "",
    end_date:   str = "",
    start_year: int = 2015,
    end_year:   Optional[int] = None,
    today:      Optional[date] = None,
) -> Tuple[date, date]:
    """
    把 CLI 的四個日期參數收斂成 (起日, 迄日)。任何一項不合法都拋 ValueError。

    --start-date / --end-date 各自覆蓋對應的 --start-year / --end-year；
    年份參數展開為該年的 1/1 與 12/31。未指定 --end-year 時迄日是「今天」
    而非當年 12/31 —— 爬未來日期沒有意義。
    """
    today = today or date.today()

    if start_date:
        sd = parse_date_arg(start_date)
    else:
        try:
            sd = date(start_year, 1, 1)
        except ValueError:
            raise ValueError(f"起始年份無效：{start_year}")

    if end_date:
        ed = parse_date_arg(end_date)
    elif end_year:
        try:
            ed = date(end_year, 12, 31)
        except ValueError:
            raise ValueError(f"結束年份無效：{end_year}")
    else:
        ed = today

    if sd > ed:
        raise ValueError(
            f"起始日期 {sd:%Y/%m/%d} 晚於結束日期 {ed:%Y/%m/%d}")
    return sd, ed


def _dismiss_alert(driver: webdriver.Chrome) -> str:
    """
    關閉可能出現的 JS alert 並回傳其文字。
    進階搜尋的表單驗證失敗會跳 alert（例如裁判字號填不完整），
    未處理會讓後續所有 driver 操作拋 UnexpectedAlertPresentException。
    """
    try:
        alert = driver.switch_to.alert
        text  = alert.text
        alert.accept()
        logger.warning("Dismissed alert: %s", text)
        return text
    except Exception:
        return ""


def _result_total(driver: webdriver.Chrome) -> Optional[int]:
    """
    從搜尋結果摘要頁取得總筆數（頁面顯示為「查詢結果 4082」）。
    取不到回傳 None（呼叫端應保守地當作可能超過上限）。
    """
    for css in ("div[id*='ount']", "span[id*='ount']", "#jud_count"):
        for el in driver.find_elements(By.CSS_SELECTOR, css):
            m = re.search(r"查詢結果\s*([\d,]+)", el.text or "")
            if m:
                return int(m.group(1).replace(",", ""))
    try:
        m = re.search(r"查詢結果\s*([\d,]+)",
                      driver.find_element(By.TAG_NAME, "body").text)
        if m:
            return int(m.group(1).replace(",", ""))
    except Exception:
        pass
    return None


def _ad_search(
    driver:     webdriver.Chrome,
    keyword:    str,
    start_date: str = "",
    end_date:   str = "",
    court:      str = "",
    case_types: Tuple[str, ...] = (),
) -> Tuple[Optional[str], Optional[int]]:
    """
    在進階搜尋頁送出「關鍵字 + 裁判日期區間 + 裁判法院 + 案件類別」查詢。
    日期以民國年月日分別填入 dy1/dm1/dd1（起）與 dy2/dm2/dd2（迄）。
    法院與案件類別同樣是查詢條件（非結果頁分群），故各條件組合都有自己的 500 額度。
    回傳 (結果列表 URL, 總筆數)；查詢失敗回傳 (None, None)。
    """
    # 日期先驗證再開瀏覽器。無法解析的日期若只印 warning 就跳過，查詢會變成
    # 「沒有日期範圍」——使用者以為在抓一週，實際在抓全部，而且不會有任何錯誤訊息。
    values: Dict[str, int] = {}
    for label, ds in (("1", start_date), ("2", end_date)):
        if not ds:
            continue
        parts = _roc_parts(ds)
        if parts is None:
            logger.error("Invalid date %r (expected YYYY/MM/DD) — search aborted", ds)
            return None, None
        values[f"dy{label}"], values[f"dm{label}"], values[f"dd{label}"] = parts

    driver.get(BASE_URL_AD)
    time.sleep(2.5)
    _dismiss_alert(driver)

    # 重新載入查詢頁時，瀏覽器會還原上一次填過的表單內容（同一個 driver 會跨多次
    # 查詢重複使用）。因此每個欄位都必須明確設定 —— 未指定的條件要主動清掉，
    # 否則上一段的關鍵字／法院／類別會悄悄留下來，讓這一段查到錯誤的結果集。
    kw = driver.find_element(By.ID, "jud_kw")
    kw.clear()
    if keyword:
        kw.send_keys(keyword)

    sel = Select(driver.find_element(By.ID, "jud_court"))
    sel.deselect_all()                  # 含預設選取的「所有法院」空值選項
    if court:
        code = _court_code(court)
        if code:
            sel.select_by_value(code)
        else:
            logger.warning("Unknown court %r — ignored (查詢將涵蓋所有法院)", court)

    wanted_sys = set()
    for ct in case_types:
        code = _sys_code(ct)
        if code:
            wanted_sys.add(code)
        else:
            logger.warning("Unknown case type %r — ignored", ct)
    for el in driver.find_elements(By.CSS_SELECTOR, "input[name='jud_sys']"):
        if el.is_selected() != (el.get_attribute("value") in wanted_sys):
            # JS click：checkbox 被 label 覆蓋時原生 click 會被攔截
            driver.execute_script("arguments[0].click();", el)

    if court or wanted_sys:
        # 勾選法院／案件類別會觸發「常用字別」的 AJAX，稍候再送出以免競態
        time.sleep(1.0)

    for fid in _AD_DATE_FIELDS:
        el = driver.find_element(By.ID, fid)
        el.clear()                      # 未指定日期時也要清掉殘留值
        if fid in values:
            el.send_keys(str(values[fid]))

    driver.find_element(By.ID, "btnQry").click()
    time.sleep(3.5)

    alert_text = _dismiss_alert(driver)
    if alert_text:
        logger.error("Advanced search rejected: %s", alert_text)
        return None, None

    total = _result_total(driver)
    url   = _get_results_list_url(driver)
    logger.info("AD search [%s ~ %s] court=%s sys=%s → total=%s",
                start_date or "*", end_date or "*",
                court or "*", "/".join(case_types) or "*", total)
    return url, total


# ─── Step B: 從結果列表頁解析個別案件 ────────────────────────────────────────
# qryresultlst.aspx 上每筆案件的連結指向
# data.aspx?ty=JD&id=<court>,<year>,<type>,<num>,<date>
_CASE_LINK_CSS = (
    "a[href*='data.aspx?ty=JD'],"
    "a[href*='data.aspx?ty=jd']"
)

# 從「裁判字號」全文（含法院名稱）解析法院名稱
# 例：「臺灣新竹地方法院 113 年度…」→「臺灣新竹地方法院」
_COURT_RE = re.compile(
    r'^(.*?(?:憲法法庭|少年及家事法院|地方法院|高等法院|最高行政法院|最高法院|高等行政法院'
    r'|行政法院|智慧財產及商業法院|智慧財產法院|海事法院)'
    r'(?:\s+\S+分院|\s+地方庭)?)'
)

# ─── 清單頁錯誤偵測 ───────────────────────────────────────────────────────────
# 伺服器端的查詢結果集（q= hash）會失效：翻頁翻到一半、或短時間內查詢過於密集時，
# 清單頁會變成「查詢設定錯誤，請重新設定查詢條件後查詢」的系統訊息頁。
# 這種頁面「沒有案件連結」，若當成「已翻完」就會靜靜少收一批資料 —— 必須和
# 「真的查無資料」分開處理：前者要重送查詢並回到原頁，後者才是結束。
_LIST_ERROR_MARKERS = (
    "查詢設定錯誤",          # q hash 失效／查詢條件遺失
    "請重新設定查詢條件",
    "Request Rejected",      # 前端 bot-defense
)


def _list_page_error(driver: webdriver.Chrome) -> str:
    """目前頁面若是錯誤頁，回傳命中的特徵字串；正常頁（含真的查無資料）回傳空字串。"""
    try:
        html = driver.page_source or ""
    except WebDriverException:
        return "WebDriver error"
    for marker in _LIST_ERROR_MARKERS:
        if marker in html:
            return marker
    return ""


def _page_url(base_url: str, page: int) -> str:
    """
    組出清單頁第 N 頁的網址。

    清單頁本身的「下一頁」連結即為 qryresultlst.aspx?q=<hash>&sort=DS&page=N&ot=in，
    因此頁碼可直接定址 —— 復原時才能跳回中斷的那一頁，而不必從第 1 頁重來。
    分群桶網址（&gy=jyear&gc=114 等）同樣適用。
    """
    base = re.sub(r"[?&](?:sort|page|ot)=[^&]*", "", base_url)
    sep  = "&" if "?" in base else "?"
    return f"{base}{sep}sort=DS&page={page}&ot=in"


def _carry_group_params(old_url: str, new_url: str) -> str:
    """把舊清單網址的分群參數（gy/gc）接到重新查詢取得的新網址上。"""
    parts = re.findall(r"[?&]((?:gy|gc)=[^&]*)", old_url)
    return new_url + ("&" + "&".join(parts) if parts else "")


def _parse_case_rows(driver: webdriver.Chrome) -> List[Dict]:
    """從 qryresultlst.aspx 擷取個別案件的連結與基本資訊。"""
    rows: List[Dict] = []
    err = _list_page_error(driver)
    if err:
        # 錯誤頁不會有案件連結，直接返回，省下 25 秒的等待
        logger.warning("Results list page is an error page (%s)", err)
        return rows
    try:
        WebDriverWait(driver, 25).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, _CASE_LINK_CSS))
        )
    except TimeoutException:
        logger.warning("Case links not found on results list page — saving debug HTML")
        _save_debug_html(driver, "results_list")
        return rows

    seen: set = set()
    for lnk in driver.find_elements(By.CSS_SELECTOR, _CASE_LINK_CSS):
        href = lnk.get_attribute("href") or ""
        if not href or href in seen:
            continue
        seen.add(href)

        # 實際欄位順序：td[0]=序號  td[1]=裁判字號(含link)  td[2]=裁判日期  td[3]=案由
        # 無獨立法院欄 — 法院名稱內嵌在裁判字號文字的開頭
        case_number = lnk.text.strip()
        cm = _COURT_RE.match(case_number)
        court = cm.group(1).strip() if cm else ""
        try:
            tr  = lnk.find_element(By.XPATH, "./ancestor::tr[1]")
            tds = tr.find_elements(By.TAG_NAME, "td")
            rows.append({
                "case_number":   case_number,
                "court":         court,
                # 裁判日期以 URL id 第 5 欄為準（西元 ISO，可直接字串比較/排序）；
                # td 版型若變動仍可用，故保留 td 文字作為備援。
                "judgment_date": _judgment_date(href) or (
                    tds[2].text.strip() if len(tds) > 2 else ""),
                "case_title":    tds[3].text.strip() if len(tds) > 3 else "",
                "url":           href,
            })
        except Exception:
            rows.append({
                "case_number": case_number,
                "court": court, "judgment_date": _judgment_date(href),
                "case_title": "", "url": href,
            })

    logger.info("Found %d cases on current page", len(rows))
    return rows


# ─── Step C: 翻頁 ─────────────────────────────────────────────────────────────
def _go_next_page(driver: webdriver.Chrome) -> bool:
    """
    點擊「下一頁」並等待新頁案件連結出現。
    使用 JS click 避免元素被遮擋時的 ElementClickInterceptedException。
    """
    next_el = None
    for sel in ("a[title='下一頁']", "a.page-next", "[class*='nextpage'] a"):
        try:
            el = driver.find_element(By.CSS_SELECTOR, sel)
            if el.is_displayed() and el.is_enabled():
                next_el = el
                break
        except NoSuchElementException:
            pass
    if next_el is None:
        try:
            el = driver.find_element(By.LINK_TEXT, "下一頁")
            if el.is_displayed() and el.is_enabled():
                next_el = el
        except NoSuchElementException:
            pass
    if next_el is None:
        return False

    for _pg_attempt in range(2):
        try:
            driver.execute_script("arguments[0].click();", next_el)
        except Exception as exc:
            logger.warning("Next page click failed (attempt %d/2): %s", _pg_attempt + 1, exc)
            if _pg_attempt == 0:
                time.sleep(10)
                continue
            return False

        # 等待新頁的案件連結出現（舊連結會因 DOM 更新而失效）
        time.sleep(1)
        try:
            WebDriverWait(driver, 25).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, _CASE_LINK_CSS))
            )
            return True
        except TimeoutException:
            driver.execute_script("window.stop();")
            time.sleep(1)
            if _pg_attempt == 0:
                logger.warning("Next page load timed out — retrying after 10 s")
                time.sleep(10)
                # 重新尋找「下一頁」按鈕（DOM 可能已更新）
                next_el = None
                for sel in ("a[title='下一頁']", "a.page-next", "[class*='nextpage'] a"):
                    try:
                        el = driver.find_element(By.CSS_SELECTOR, sel)
                        if el.is_displayed() and el.is_enabled():
                            next_el = el
                            break
                    except NoSuchElementException:
                        pass
                if next_el is None:
                    return False
                continue
            return False  # 第二次逾時仍未載入 → 放棄翻頁
    return False


# ─── 主爬蟲函式 ───────────────────────────────────────────────────────────────
def search_and_crawl(
    keyword:     str,
    max_results: int  = 10,
    headless:    bool = True,
    start_date:  str  = "",
    end_date:    str  = "",
    case_year_start: Optional[int] = None,
    case_year_end:   Optional[int] = None,
    court:         str = "",
    case_types:    Tuple[str, ...] = (),
    judgment_type: str = "",
    keyword_label: str = "",
    driver:      Optional[webdriver.Chrome] = None,
    pacer:       Optional["Pacer"] = None,
    skip_if_truncated: bool = False,
) -> Dict[str, object]:
    """
    以「關鍵字 + 裁判日期區間 + 法院 + 案件類別」搜尋並爬取裁判書。

    流程：
      1. default_AD.aspx 進階搜尋：關鍵字 + 裁判日期起迄 → 取得該區間專屬的 q= hash
      2. 讀摘要頁「查詢結果 N」判斷是否超過單一結果集上限（_RESULT_LIMIT=500）
      3. 未超過 → 翻頁收集所有案件連結；超過 → 回報 truncated 交由呼叫端切分日期區間
      4. 逐一下載案件 HTML

    參數：
      start_date / end_date       裁判日期起迄（西元 YYYY/MM/DD），伺服器端篩選
      case_year_start / _end      案號年度起迄（民國年）。以伺服器端年度分群
                                  （?gy=jyear&gc=<年>）只取符合的年度桶，
                                  並保留本地過濾切精確邊界（統括桶需要）。
                                  註：進階搜尋的 jud_year 須與字別、案號同時給定，
                                  無法單獨當範圍條件，故走分群而非表單欄位。
      court                       裁判法院（名稱或代碼，如「臺灣臺北地方法院」/`TPD`），
                                  伺服器端查詢條件
      case_types                  案件類別（如 ("民事",)），伺服器端查詢條件；
                                  空 tuple = 全部類別
      judgment_type               裁判種類（「判決」或「裁定」）。進階搜尋沒有此欄位，
                                  於結果清單頁依裁判字號過濾 —— 在下載前就濾掉，
                                  可大幅減少詳細頁請求數。未給關鍵字時，另以該詞做
                                  全文檢索當伺服器端粗篩，縮小結果集、減少翻頁
      keyword_label               寫入 DB keyword 欄的標籤。未指定時沿用 keyword；
                                  無關鍵字查詢（僅法院／類別）時用它標記這批資料，
                                  供 export_excel 的 -k 篩選
      driver                      傳入既有 driver 可跨多次呼叫重複使用（不會被關閉）
      pacer                       請求節奏控制（見 Pacer）。跨區段傳入同一個實例，
                                  降速狀態才能延續 —— 否則每段都從全速重新開始，
                                  一被擋就會反覆踩同一個坑
      skip_if_truncated           True 時，一旦偵測到結果被截斷就立即返回不翻頁

    回傳 {"collected": 實際下載數, "total": 該區間總筆數, "truncated": 是否被截斷,
          "page_errors": 清單頁錯誤且復原失敗的次數,
          "truncated_buckets": 本身即達 500 上限的分群桶（資料不完整、重跑也救不回）,
          "driver": 目前有效的 WebDriver}
    page_errors > 0 代表該區段的清單沒有翻完，資料不完整，呼叫端應重跑該區段。
    注意 driver：Phase B 每 80 筆會重建 session（舊的會被 quit），
    因此傳入自己的 driver 時，下一次呼叫務必改用回傳的這一個。
    """
    os.makedirs(HTML_DIR, exist_ok=True)
    init_db()

    own_driver = driver is None
    if own_driver:
        driver = build_driver(headless)
    if pacer is None:
        pacer = Pacer()
    collected = 0
    page_errors = 0       # 清單頁出現錯誤頁且無法復原的次數（> 0 代表該區段可能不完整）
    truncated_buckets: List[str] = []   # 分群桶本身 >= 500 筆而被截斷（重跑也救不回）
    # 只要某種裁判（判決／裁定）且沒有關鍵字時，以該詞做全文檢索當伺服器端粗篩：
    # 每份判決書本文（標題「…民事判決」、「判決如下」）必含「判決」，大量本票類裁定則不含，
    # 實測單日 976 筆 → 55 筆、漏抓 0。結果集縮小後幾乎不會再破 500 上限，翻頁量也大減。
    # 清單頁仍會依裁判字號精篩，所以粗篩多抓進來的裁定不會被下載。
    query_keyword = keyword or judgment_type
    total: Optional[int] = None
    truncated = False
    court_links: List[Tuple[str, str]] = []
    year_links:  List[Tuple[str, int, bool]] = []

    try:
        # ── 1. 進階搜尋取得該日期區間專屬的結果集 ─────────────────────
        pacer.wait("query")
        base_results_url, total = _ad_search(
            driver, query_keyword, start_date, end_date, court, tuple(case_types))
        if not base_results_url:
            logger.error("Advanced search returned no results URL — aborting")
            return {"collected": 0, "total": total, "truncated": False,
                    "page_errors": page_errors,
            "truncated_buckets": truncated_buckets, "driver": driver}

        # ── 2. 判斷是否觸及單一結果集上限 ─────────────────────────────
        # 結果按裁判日期由新到舊排序，截斷時被砍掉的是最舊的部分。
        if total is not None and total >= _RESULT_LIMIT:
            truncated = True
            logger.warning(
                "Result set truncated: total=%d >= limit=%d  [%s ~ %s]",
                total, _RESULT_LIMIT, start_date or "*", end_date or "*",
            )
            if skip_if_truncated:
                logger.info("skip_if_truncated — returning for caller to split")
                return {"collected": 0, "total": total, "truncated": True,
                        "page_errors": page_errors,
            "truncated_buckets": truncated_buckets, "driver": driver}

            # 呼叫端表示已無法再切分日期（例如區間已縮到單日），
            # 最後手段：改用結果頁分群把同一個日期區間再切細。
            # 分群與日期條件不衝突 —— 日期在查詢裡，分群是該結果集的切面，
            # 每個桶各自獨立計算 500 額度。
            # 必須在離開摘要頁前收集，導覽到 qryresultlst.aspx 後就看不到這些連結。
            if court:
                # 法院已是查詢條件 → 法院分群只會有一桶，改用案號年度軸細分
                year_links = _collect_year_links(driver)
                if year_links:
                    logger.info("Fallback: subdividing by case-number year (%d buckets)",
                                len(year_links))
            else:
                court_links = _collect_court_links(driver)
                if court_links:
                    logger.info("Fallback: subdividing by court (%d courts)", len(court_links))

        # 指定案號年度時，改用伺服器端的年度分群（?gy=jyear&gc=<年>），
        # 只取回符合的年度而非整個日期區間，可省下大量無用翻頁。
        # gy/gc 一次只能用一條軸 —— 若已因單日超限而啟用法院分群，
        # 該區段就讓法院軸優先，案號年度退回本地過濾（正確性不受影響）。
        if (case_year_start is not None or case_year_end is not None) and not court_links:
            year_links = _collect_year_links(driver)
            if year_links:
                _lo = case_year_start if case_year_start is not None else -10 ** 6
                _hi = case_year_end   if case_year_end   is not None else 10 ** 6
                # 一般桶：年度落在範圍內即取；
                # 統括桶（涵蓋「該年及更早」）：只要其上界不低於 _lo 就可能有符合資料
                year_links = [
                    (u, y, catch) for (u, y, catch) in year_links
                    if (_lo <= y <= _hi) or (catch and y >= _lo)
                ]
                logger.info("Case-year %s~%s → %d year bucket(s) server-side",
                            case_year_start, case_year_end, len(year_links))

        # ── 3. Phase A: 翻頁收集案件連結（新 → 舊）────────────────────
        logger.info("Phase A: collecting case URLs …")
        all_items: List[Dict] = []
        seen_urls: set = set()

        def _filter_by_case_year(items: List[Dict]) -> List[Dict]:
            """案號年度後過濾（與裁判日期是兩個不同維度，可各自獨立指定）。"""
            if case_year_start is None and case_year_end is None:
                return items
            lo = case_year_start if case_year_start is not None else -10 ** 6
            hi = case_year_end   if case_year_end   is not None else 10 ** 6
            return [
                it for it in items
                if _case_number_year(it.get("url", "")) is None
                or lo <= _case_number_year(it.get("url", "")) <= hi
            ]

        def _filter_by_judgment_type(items: List[Dict]) -> List[Dict]:
            """裁判種類過濾（清單頁的裁判字號尾端就寫明「…民事判決」／「…民事裁定」）。"""
            if not judgment_type:
                return items
            return [it for it in items if judgment_type in (it.get("case_number") or "")]

        def _recover_list_page(base_url: str, page: int, marker: str, label: str) -> bool:
            """
            清單頁變成錯誤頁時的復原程序：
              1. 稍候重載同一頁（多半是暫時性的）
              2. 仍失敗 → 重新送出同一組查詢條件取得新的 q hash，再跳回同一頁
            成功回傳 True（呼叫端可直接重新解析目前頁面）。
            """
            if not base_url:
                return False
            logger.warning("清單頁異常（%s）%s page=%d — 嘗試復原", marker, label or "", page)
            pacer.on_failure(marker)          # 全域降速：這是伺服器在抗議
            for wait in (3, 10, 30):
                time.sleep(wait)
                driver.get(_page_url(base_url, page))
                time.sleep(1.5)
                if not _list_page_error(driver):
                    logger.info("  ↳ 重載成功，自 page=%d 續翻", page)
                    pacer.on_success()
                    return True

            # q hash 已失效 → 重送查詢。分群參數（gy/gc）沿用舊網址的設定。
            new_url, _new_total = _ad_search(
                driver, query_keyword, start_date, end_date, court, tuple(case_types))
            if not new_url:
                return False
            driver.get(_page_url(_carry_group_params(base_url, new_url), page))
            time.sleep(1.5)
            ok = not _list_page_error(driver)
            logger.info("  ↳ 重新查詢後%s（page=%d）", "復原成功" if ok else "仍失敗", page)
            return ok

        def _paginate(label: str, base_url: str = "") -> int:
            """
            從目前頁面一路翻頁收集，直到無下一頁或達 max_results。
            回傳翻到的原始列數（過濾前）—— 判斷分群桶是否撞到 500 上限必須看這個，
            看過濾後的筆數會在只收判決時嚴重低估，截斷就會被忽略。
            """
            nonlocal page_errors
            page = 1
            raw_seen = 0
            while len(all_items) < max_results:
                raw_items = _parse_case_rows(driver)
                if not raw_items:
                    # 空清單有兩種意義：真的翻完了，或伺服器丟回錯誤頁。
                    # 後者若當成翻完，這一段就會靜靜地少收資料。
                    marker = _list_page_error(driver)
                    if marker:
                        if _recover_list_page(base_url, page, marker, label):
                            continue          # 復原成功 → 重新解析同一頁
                        page_errors += 1
                        logger.error(
                            "清單頁無法復原（%s）%s page=%d — 此區段資料不完整",
                            marker, label or "", page,
                        )
                    break
                raw_seen += len(raw_items)
                fresh = [it for it in _filter_by_judgment_type(_filter_by_case_year(raw_items))
                         if it.get("url") and it["url"] not in seen_urls]
                needed = max_results - len(all_items)
                for it in fresh[:needed]:
                    seen_urls.add(it["url"])
                    all_items.append(it)
                pacer.on_success()
                logger.info("  %d / %d collected%s", len(all_items), max_results, label)
                if len(all_items) >= max_results:
                    break
                if not _go_next_page(driver):
                    break
                page += 1
                pacer.wait("list")
            return raw_seen

        if court_links:
            # 最後手段路徑：同一日期區間內再依法院逐桶收集
            for court_url, court_label in court_links:
                if len(all_items) >= max_results:
                    break
                logger.info("  [Court] %s", court_label)
                driver.get(court_url)
                time.sleep(2.0)
                raw = _paginate(f"  [{court_label}]", court_url)
                if raw >= _RESULT_LIMIT:
                    truncated_buckets.append(f"{start_date}~{end_date} {court_label}")
                    logger.warning(
                        "  ⚠ 法院桶 %s 翻到 %d 列已達單一結果集上限，該桶較舊的部分取不到",
                        court_label, raw,
                    )
        elif year_links:
            # 伺服器端案號年度篩選：只翻符合年度的桶（由新到舊）。
            # _paginate 內仍會套用本地過濾 —— 統括桶需要它才能精確切到範圍，
            # 同時也是伺服器端篩選若失效時的安全網。
            for year_url, roc, is_catch_all in year_links:
                if len(all_items) >= max_results:
                    break
                tag = f"ROC{roc}{'以前' if is_catch_all else ''}"
                logger.info("  [CaseYear] %s", tag)
                driver.get(year_url)
                time.sleep(2.0)
                raw = _paginate(f"  [{tag}]", year_url)
                if raw >= _RESULT_LIMIT:
                    truncated_buckets.append(f"{start_date}~{end_date} {tag}")
                    logger.warning(
                        "  ⚠ 年度桶 %s 翻到 %d 列已達單一結果集上限，該桶較舊的部分取不到",
                        tag, raw,
                    )
        else:
            driver.get(base_results_url)
            time.sleep(2.5)
            _paginate("", base_results_url)

        # 防護：摘要頁的總筆數若讀不到（頁面改版等），改以「恰好收滿上限」反推截斷。
        # 未指定案號年度過濾時，收到剛好 _RESULT_LIMIT 筆幾乎必然代表被截斷。
        if (total is None and not truncated and not court_links
                and case_year_start is None and case_year_end is None
                and not judgment_type
                and len(all_items) >= _RESULT_LIMIT
                and max_results >= _RESULT_LIMIT):
            truncated = True
            logger.warning(
                "Total unknown but collected exactly %d — assuming truncated  [%s ~ %s]",
                _RESULT_LIMIT, start_date or "*", end_date or "*",
            )

        logger.info("Phase A complete — %d cases queued", len(all_items))

        # ── 6. Phase B: 下載每個案件 ─────────────────────────────────
        # 每 _SESSION_RENEW_EVERY 筆實際請求（非跳過）重建 WebDriver session，
        # 避免 Chrome renderer 因記憶體耗盡或伺服器限流而崩潰。
        _SESSION_RENEW_EVERY = 80   # 每 80 筆換一次 session
        _session_requests    = 0    # 本 session 已發出的請求數

        def _renew_driver() -> webdriver.Chrome:
            nonlocal driver
            logger.info("Renewing WebDriver session (will sleep 15 s) …")
            try:
                driver.quit()
            except Exception:
                pass
            time.sleep(15)
            driver = build_driver(headless)
            logger.info("New WebDriver session ready.")
            return driver

        logger.info("Phase B: downloading case pages …")
        for item in all_items:
            case_number = item["case_number"] or f"unknown_{collected + 1}"
            logger.info("[%d/%d] %s", collected + 1, len(all_items), case_number)

            # 查詢 DB 是否已有紀錄
            chk = sqlite3.connect(DB_PATH)
            existing = chk.execute(
                "SELECT html_file FROM crawl_records WHERE case_number=?", (case_number,)
            ).fetchone()
            chk.close()

            existing_html = existing[0] if existing else None

            if existing and _is_html_complete(existing_html):
                # 已爬取且 HTML 完整 → 跳過
                logger.info("  Skip   → %s (already downloaded, complete)", case_number)
                collected += 1
                time.sleep(0.2)
                continue

            if existing:
                # 紀錄存在但 HTML 不完整（stub 或遺失）→ 重新爬取
                logger.info("  Re-crawl → %s (stub/incomplete HTML detected)", case_number)

            # 定期重建 session
            if _session_requests > 0 and _session_requests % _SESSION_RENEW_EVERY == 0:
                driver = _renew_driver()

            html_file = None
            try:
                html_file = crawl_detail_page(driver, item["url"], case_number)
                _session_requests += 1
            except WebDriverException as exc:
                logger.warning("WebDriver error on %s: %s — restarting session and retrying",
                               case_number, exc)
                pacer.on_failure("WebDriver error")
                driver = _renew_driver()
                try:
                    html_file = crawl_detail_page(driver, item["url"], case_number)
                    _session_requests += 1
                except WebDriverException as exc2:
                    logger.error("Retry also failed for %s: %s — skipping", case_number, exc2)
                    pacer.on_failure("detail page retry failed")

            if html_file:
                pacer.on_success()
                if existing:
                    _mark_recrawled(case_number, html_file)
                else:
                    upsert_record(
                        case_number, item["court"], item["case_title"],
                        item["judgment_date"], item["url"], html_file,
                        keyword_label or keyword,
                    )
                collected += 1

            pacer.wait("detail")

    except WebDriverException as exc:
        logger.error("WebDriver error (outer): %s", exc, exc_info=True)
    finally:
        # 由呼叫端傳入的 driver 交還呼叫端管理（供跨區間重複使用），不在此關閉
        if own_driver:
            try:
                driver.quit()
            except Exception:
                pass

    logger.info("Crawl complete — collected %d / %d (total=%s, truncated=%s, page_errors=%d)",
                collected, max_results, total, truncated, page_errors)
    # driver 一併回傳：Phase B 每 80 筆會重建 session，舊的已被 quit，
    # 呼叫端必須換用回傳的這個，否則下一段會拿到失效的 session。
    return {"collected": collected, "total": total, "truncated": truncated,
            "page_errors": page_errors,
            "truncated_buckets": truncated_buckets, "driver": driver}


# ─── 重新爬取 stub 紀錄 ───────────────────────────────────────────────────────
def recrawl_stubs(headless: bool = True) -> int:
    """找出所有 stub/不完整 HTML 紀錄並重新下載。"""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, case_number, source_url, html_file FROM crawl_records "
        "WHERE source_url IS NOT NULL AND source_url != ''"
    ).fetchall()
    conn.close()

    to_recrawl = []
    for cid, case_number, source_url, html_file in rows:
        if not _is_html_complete(html_file):
            to_recrawl.append((cid, case_number, source_url))

    logger.info("Found %d stub/missing records to re-crawl", len(to_recrawl))
    if not to_recrawl:
        return 0

    os.makedirs(HTML_DIR, exist_ok=True)
    driver    = build_driver(headless)
    recrawled = 0
    _SESSION_RENEW_EVERY = 80
    try:
        for i, (cid, case_number, source_url) in enumerate(to_recrawl, 1):
            logger.info("[%d/%d] Re-crawling: %s", i, len(to_recrawl), case_number)
            if i > 1 and (i - 1) % _SESSION_RENEW_EVERY == 0:
                logger.info("Renewing WebDriver session (will sleep 15 s) …")
                try:
                    driver.quit()
                except Exception:
                    pass
                time.sleep(15)
                driver = build_driver(headless)
            try:
                new_html = crawl_detail_page(driver, source_url, case_number)
            except WebDriverException as exc:
                logger.warning("WebDriver error on %s: %s — restarting and retrying", case_number, exc)
                try:
                    driver.quit()
                except Exception:
                    pass
                time.sleep(15)
                driver = build_driver(headless)
                try:
                    new_html = crawl_detail_page(driver, source_url, case_number)
                except WebDriverException as exc2:
                    logger.error("Retry failed for %s: %s — skipping", case_number, exc2)
                    new_html = None
            if new_html:
                _mark_recrawled(case_number, new_html)
                recrawled += 1
            time.sleep(1.0)
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    logger.info("Re-crawled %d / %d stubs", recrawled, len(to_recrawl))
    return recrawled


# ─── CLI ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="司法院裁判書自動爬蟲")
    ap.add_argument("keyword", nargs="?", default="",      help="搜尋關鍵字")
    ap.add_argument("-n", "--num",   type=int, default=10, help="爬取筆數 (預設: 10)")
    ap.add_argument("--no-headless", action="store_true",  help="顯示瀏覽器視窗 (debug 用)")
    ap.add_argument("--start-date", default="",
                    help="裁判日期起 YYYY/MM/DD（西元，伺服器端精確篩選）")
    ap.add_argument("--end-date",   default="",
                    help="裁判日期迄 YYYY/MM/DD（西元，伺服器端精確篩選）")
    ap.add_argument("--case-year-start", type=int, default=None,
                    help="案號年度起（民國年，如 113）；與裁判日期是不同維度，伺服器端分群")
    ap.add_argument("--case-year-end",   type=int, default=None,
                    help="案號年度迄（民國年，如 115）；與裁判日期是不同維度，伺服器端分群")
    ap.add_argument("--court", default="",
                    help="裁判法院（名稱或代碼，如「臺灣臺北地方法院」或 TPD），伺服器端篩選")
    ap.add_argument("--case-type", default="",
                    help="案件類別，逗號分隔（憲法/民事/刑事/行政/懲戒），伺服器端篩選")
    ap.add_argument("--judgment-type", default="", choices=("", *_JUDGMENT_TYPES),
                    help="裁判種類（判決／裁定）；於結果清單頁過濾，下載前就濾掉")
    ap.add_argument("--label", default="",
                    help="寫入 DB keyword 欄的標籤（無關鍵字查詢時用來標記這批資料）")
    ap.add_argument("--delay", type=float, default=_DEFAULT_DELAY,
                    help="請求基礎間隔秒數（預設: 1.0）；遇錯自動降速、連續失敗長暫停")
    ap.add_argument("--recrawl-stubs", action="store_true",
                    help="重新爬取資料庫中所有 stub/不完整 HTML（不需關鍵字）")
    args = ap.parse_args()

    case_types = tuple(t.strip() for t in args.case_type.split(",") if t.strip())

    # 日期在開瀏覽器之前就驗證；本檔把日期當字串傳給查詢表單，
    # 不擋的話打錯一個字就會静默變成「沒有日期範圍」的查詢。
    for _flag, _raw in (("--start-date", args.start_date), ("--end-date", args.end_date)):
        if _raw:
            try:
                parse_date_arg(_raw)
            except ValueError as exc:
                ap.error(f"{_flag}：{exc}")
    if args.start_date and args.end_date:
        if parse_date_arg(args.start_date) > parse_date_arg(args.end_date):
            ap.error(f"起始日期 {args.start_date} 晚於結束日期 {args.end_date}")

    if args.recrawl_stubs:
        n = recrawl_stubs(headless=not args.no_headless)
        print(f"\n完成！共重新爬取 {n} 筆 stub 裁判書。")
    elif args.keyword or args.court or case_types:
        res = search_and_crawl(
            keyword=args.keyword,
            max_results=args.num,
            headless=not args.no_headless,
            start_date=args.start_date,
            end_date=args.end_date,
            case_year_start=args.case_year_start,
            case_year_end=args.case_year_end,
            court=args.court,
            case_types=case_types,
            judgment_type=args.judgment_type,
            keyword_label=args.label,
            pacer=Pacer(delay=args.delay),
        )
        print("")
        print(f"完成！共爬取 {res['collected']} 筆裁判書"
              f"（該區間總筆數 {res['total']}）。")
        if res["truncated"]:
            _axis = "案號年度分群" if args.court else "法院分群"
            print(f"  ⚠ 結果集達單一查詢上限 {_RESULT_LIMIT} 筆"
                  f"（該條件共 {res['total']} 筆）→ 已改用{_axis}逐桶收集。")
            print(f"    {_axis}的涵蓋上限為「各桶取前 500 筆」之總和，")
            print("    若某一桶在此條件下超過 500 筆，其較舊的部分仍取不到。")
            print("    需要完整資料請改用 crawl_batched.py —— 它會自動細分裁判日期區間，")
            print("    把每段壓到 500 筆以下，不受此限制。")
    else:
        ap.print_help()
