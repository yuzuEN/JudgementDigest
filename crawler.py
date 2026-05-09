"""
Part 1 — 司法院裁判書自動爬蟲
目標網站: https://judgment.judicial.gov.tw/FJUD/default.aspx

使用方式:
    python crawler.py <關鍵字> [-n 筆數] [--no-headless] [--start-date YYYY/MM/DD] [--end-date YYYY/MM/DD]

範例:
    python crawler.py 詐欺 -n 20
    python crawler.py 勞動契約 -n 10 --start-date 2023/01/01 --end-date 2023/12/31 --no-headless
"""

import sqlite3
import time
import os
import re
import argparse
import logging
from datetime import datetime
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

def _parse_case_rows(driver: webdriver.Chrome) -> List[Dict]:
    """從 qryresultlst.aspx 擷取個別案件的連結與基本資訊。"""
    rows: List[Dict] = []
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
                "judgment_date": tds[2].text.strip() if len(tds) > 2 else "",
                "case_title":    tds[3].text.strip() if len(tds) > 3 else "",
                "url":           href,
            })
        except Exception:
            rows.append({
                "case_number": case_number,
                "court": court, "judgment_date": "", "case_title": "",
                "url": href,
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
) -> int:
    """
    搜尋並爬取裁判書。

    流程：
      1. default.aspx 輸入關鍵字 → 送出查詢
      2. 等待 qryresultlst.aspx 結果列表連結出現 → 導航過去
      3. 在結果列表頁找個別 data.aspx 案件連結 → 逐一下載 HTML
      4. 翻頁直到達到 max_results
    """
    os.makedirs(HTML_DIR, exist_ok=True)
    init_db()

    driver    = build_driver(headless)
    wait      = WebDriverWait(driver, 30)
    collected = 0

    try:
        # ── 1. 關鍵字搜尋（簡易搜尋頁）取得查詢 hash ─────────────────
        # 日期篩選不走表單（進階搜尋頁在 headless 模式下 input 無法互動），
        # 改用搜尋結果的年度分群 URL（?gy=jyear&gc=<ROC年>）做篩選。
        # 若 driver.get(BASE_URL) 因 renderer 崩潰而失敗，最多重試 2 次。
        logger.info("Opening search page: %s", BASE_URL)
        for _attempt in range(3):
            try:
                driver.get(BASE_URL)
                break
            except TimeoutException as _exc:
                logger.warning("driver.get(BASE_URL) timed out (attempt %d/3) — stopping page load",
                               _attempt + 1)
                try:
                    driver.execute_script("window.stop();")
                except Exception:
                    pass
                break  # 頁面可能部分載入，繼續嘗試找輸入框
            except WebDriverException as _exc:
                if _attempt == 2:
                    raise
                logger.warning("driver.get(BASE_URL) failed (attempt %d/3): %s — rebuilding driver",
                               _attempt + 1, _exc)
                try:
                    driver.quit()
                except Exception:
                    pass
                time.sleep(15)
                driver = build_driver(headless)
                wait   = WebDriverWait(driver, 30)
        time.sleep(3)

        # 找關鍵字輸入框
        kw_input = None
        for kw_id in ("txtKW", "KeyWord", "kw"):
            try:
                kw_input = wait.until(EC.presence_of_element_located((By.ID, kw_id)))
                break
            except TimeoutException:
                pass
        if kw_input is None:
            inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='text']")
            kw_input = inputs[0] if inputs else None
        if kw_input is None:
            logger.error("Cannot find keyword input — aborting")
            return 0

        kw_input.clear()
        kw_input.send_keys(keyword)
        logger.info("Keyword entered: %s", keyword)

        # 點擊查詢按鈕
        # TimeoutException 表示頁面超過 page_load_timeout 秒才載入完成；
        # 用 window.stop() 停止繼續等待，後續再確認是否有結果。
        clicked = False
        for btn_id in ("btnSimpleQry", "btnQuery", "BtnQuery", "Query"):
            try:
                driver.find_element(By.ID, btn_id).click()
                clicked = True
                break
            except NoSuchElementException:
                pass
            except TimeoutException:
                logger.warning("Search button click timed out — stopping page load and continuing")
                try:
                    driver.execute_script("window.stop();")
                except Exception:
                    pass
                clicked = True
                break
        if not clicked:
            try:
                driver.find_element(By.CSS_SELECTOR, "input[type='submit']").click()
                clicked = True
            except NoSuchElementException:
                pass
            except TimeoutException:
                logger.warning("Submit button click timed out — stopping page load and continuing")
                try:
                    driver.execute_script("window.stop();")
                except Exception:
                    pass
                clicked = True
        if not clicked:
            logger.error("Cannot find search button — aborting")
            return 0

        logger.info("Search submitted, waiting for results link …")
        time.sleep(2)

        # ── 2. 取得查詢 hash URL，同時收集法院子連結 ─────────────────
        # 法院子連結（?gy=jcourt&gc=<code>）出現在 default.aspx 搜尋結果摘要頁，
        # 導覽至 qryresultlst.aspx 之後就看不到了，必須在此時收集。
        base_results_url = _get_results_list_url(driver)
        if not base_results_url:
            logger.error("Cannot find results list URL — aborting")
            return 0
        logger.info("Base results URL: %s", base_results_url)

        # 等待法院分群側邊欄渲染後再收集（伺服器較慢時側邊欄可能延後出現）
        time.sleep(4)
        court_links = _collect_court_links(driver)
        logger.info("Collected %d court sub-links from search result page", len(court_links))

        # ── 3. 決定 ROC 年度範圍 ──────────────────────────────────────
        def _date_to_roc(date_str: str) -> int:
            return int(date_str.replace("/", "-").split("-")[0]) - 1911

        if start_date or end_date:
            today_roc = datetime.now().year - 1911
            start_roc = _date_to_roc(start_date) if start_date else 104
            end_roc   = _date_to_roc(end_date)   if end_date   else today_roc
        else:
            start_roc = end_roc = None

        if start_roc is not None:
            roc_years = list(range(end_roc, start_roc - 1, -1))  # 新 → 舊
        else:
            roc_years = [None]

        # ── 4. Phase A: 法院逐一收集，Python 層做年度範圍過濾 ─────────
        # 策略 A（有法院子連結）：
        #   每個法院 URL（?gy=jcourt&gc=<code>）只導覽一次，
        #   再用「字號年度」在 Python 層過濾到目標年度範圍。
        #   這樣 25 個法院只需 25 次導覽，而非「年度數 × 法院數」次。
        #
        # 策略 B（無法院子連結，fallback）：
        #   逐年度直接導覽年度篩選頁（?gy=jyear&gc=<year>）並翻頁收集。
        logger.info("Phase A: collecting case URLs …")
        all_items: List[Dict] = []

        if court_links:
            logger.info("Strategy A: %d courts (year range ROC%s–ROC%s)",
                        len(court_links),
                        start_roc if start_roc is not None else "?",
                        end_roc   if end_roc   is not None else "?")

            for court_url, court_label in court_links:
                if len(all_items) >= max_results:
                    break
                logger.info("  [Court] %s", court_label)
                driver.get(court_url)
                time.sleep(2)

                while len(all_items) < max_results:
                    raw_items = _parse_case_rows(driver)
                    if not raw_items:
                        break

                    # ?gy=jcourt 傳回該法院所有年度；用字號年度做範圍過濾
                    if start_roc is not None:
                        page_items = [
                            it for it in raw_items
                            if _case_number_year(it.get("url", "")) is None
                            or start_roc <= _case_number_year(it.get("url", "")) <= end_roc
                        ]

                        # 若本頁所有可解析的年度都比 start_roc 還舊，
                        # 代表後續頁面（更舊）也不會有符合的案件 → 提早結束此法院
                        if not page_items:
                            page_years = [
                                _case_number_year(it.get("url", ""))
                                for it in raw_items
                            ]
                            known_years = [y for y in page_years if y is not None]
                            if known_years and max(known_years) < start_roc:
                                logger.info(
                                    "    All cases on this page (max year ROC%d) older than "
                                    "range start ROC%d — stopping [%s]",
                                    max(known_years), start_roc, court_label,
                                )
                                break
                    else:
                        page_items = raw_items

                    needed = max_results - len(all_items)
                    all_items.extend(page_items[:needed])
                    logger.info(
                        "    %d / %d  [%s]",
                        len(all_items), max_results, court_label,
                    )

                    if len(all_items) >= max_results:
                        break
                    if not page_items:
                        # 過濾後無符合案件但尚未超出範圍 → 繼續翻頁
                        if not _go_next_page(driver):
                            break
                        continue
                    if not _go_next_page(driver):
                        break
        else:
            # Fallback：無法院子連結，逐年度直接翻頁
            logger.info("Strategy B (fallback): year URL pagination")
            for roc_year in roc_years:
                if len(all_items) >= max_results:
                    break

                if roc_year is not None:
                    lst_url = f"{base_results_url}&gy=jyear&gc={roc_year}"
                    logger.info("── Year ROC%d ──", roc_year)
                else:
                    lst_url = base_results_url
                    logger.info("── All years ──")

                driver.get(lst_url)
                time.sleep(2)

                while len(all_items) < max_results:
                    page_items = _parse_case_rows(driver)
                    if not page_items:
                        break
                    needed = max_results - len(all_items)
                    all_items.extend(page_items[:needed])
                    logger.info("  %d / %d  [fallback ROC%s]", len(all_items), max_results, roc_year)
                    if len(all_items) >= max_results:
                        break
                    if not _go_next_page(driver):
                        break

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
                driver = _renew_driver()
                try:
                    html_file = crawl_detail_page(driver, item["url"], case_number)
                    _session_requests += 1
                except WebDriverException as exc2:
                    logger.error("Retry also failed for %s: %s — skipping", case_number, exc2)

            if html_file:
                if existing:
                    _mark_recrawled(case_number, html_file)
                else:
                    upsert_record(
                        case_number, item["court"], item["case_title"],
                        item["judgment_date"], item["url"], html_file, keyword
                    )
                collected += 1

            time.sleep(1.0)

    except WebDriverException as exc:
        logger.error("WebDriver error (outer): %s", exc, exc_info=True)
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    logger.info("Crawl complete — collected %d / %d", collected, max_results)
    return collected


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
    ap.add_argument("--start-date", default="",            help="裁判日期起 YYYY/MM/DD")
    ap.add_argument("--end-date",   default="",            help="裁判日期迄 YYYY/MM/DD")
    ap.add_argument("--recrawl-stubs", action="store_true",
                    help="重新爬取資料庫中所有 stub/不完整 HTML（不需關鍵字）")
    args = ap.parse_args()

    if args.recrawl_stubs:
        n = recrawl_stubs(headless=not args.no_headless)
        print(f"\n完成！共重新爬取 {n} 筆 stub 裁判書。")
    elif args.keyword:
        n = search_and_crawl(
            keyword=args.keyword,
            max_results=args.num,
            headless=not args.no_headless,
            start_date=args.start_date,
            end_date=args.end_date,
        )
        print(f"\n完成！共爬取 {n} 筆裁判書。")
    else:
        ap.print_help()
