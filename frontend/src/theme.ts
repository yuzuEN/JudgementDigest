/**
 * 淺色／深色主題。預設跟著系統設定（系統切換時頁面也跟著換）；
 * 使用者在頁首按過切換鈕，就記住他的選擇。這只是外觀偏好，不是案情內容，所以可以放 localStorage。
 * 列印、存成 PDF 一律是淺色（index.css 的深色只套在 screen）。
 */
export type ThemePref = "system" | "light" | "dark";

export const THEME_KEY = "casey-theme";
const CHANGE = "casey-theme-change";

export function systemPrefersDark(): boolean {
  return Boolean(window.matchMedia?.("(prefers-color-scheme: dark)").matches);
}

export function getThemePref(): ThemePref {
  try {
    const v = window.localStorage.getItem(THEME_KEY);
    return v === "light" || v === "dark" ? v : "system";
  } catch {
    return "system";
  }
}

export function isDark(pref: ThemePref = getThemePref()): boolean {
  return pref === "system" ? systemPrefersDark() : pref === "dark";
}

export function applyTheme(dark: boolean) {
  document.documentElement.classList.toggle("dark", dark);
  window.dispatchEvent(new Event(CHANGE));
}

/** 記住使用者的選擇並立刻套用；"system" 會清掉記錄，回到跟著系統。 */
export function setThemePref(pref: ThemePref) {
  try {
    if (pref === "system") window.localStorage.removeItem(THEME_KEY);
    else window.localStorage.setItem(THEME_KEY, pref);
  } catch {
    // 儲存被封鎖：這次照樣切換，只是下次不會記得
  }
  applyTheme(isDark(pref));
}

/** 套用目前的偏好；偏好是「跟著系統」時，系統切換頁面也跟著換。回傳取消監聽的函式。 */
export function followSystemTheme(): () => void {
  applyTheme(isDark());
  const query = window.matchMedia?.("(prefers-color-scheme: dark)");
  if (!query?.addEventListener) return () => {};
  const onChange = (e: MediaQueryListEvent) => {
    if (getThemePref() === "system") applyTheme(e.matches);
  };
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}

/** 訂閱主題改變（頁首的切換鈕用）。 */
export function onThemeChange(listener: () => void): () => void {
  window.addEventListener(CHANGE, listener);
  return () => window.removeEventListener(CHANGE, listener);
}

export function currentlyDark(): boolean {
  return document.documentElement.classList.contains("dark");
}
