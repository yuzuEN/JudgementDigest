export type Theme = "light" | "dark";

const KEY = "jd-theme";

/** 使用者選過就用選過的，否則跟著系統。瀏覽器不給用 localStorage 時也要能用。 */
export function initialTheme(): Theme {
  try {
    const saved = localStorage.getItem(KEY);
    if (saved === "light" || saved === "dark") return saved;
  } catch { /* 私密模式等情況 */ }
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function applyTheme(theme: Theme, save = false) {
  document.documentElement.dataset.theme = theme;
  if (!save) return;
  try {
    localStorage.setItem(KEY, theme);
  } catch { /* 只是記不住，這次瀏覽還是有效 */ }
}
