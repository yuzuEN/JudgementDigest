/** 夜間模式一律跟著系統設定，系統切換時頁面也跟著換。 */
export function systemPrefersDark(): boolean {
  return Boolean(window.matchMedia?.("(prefers-color-scheme: dark)").matches);
}

export function applyTheme(dark: boolean) {
  document.documentElement.classList.toggle("dark", dark);
}

export function followSystemTheme(): () => void {
  applyTheme(systemPrefersDark());
  const query = window.matchMedia?.("(prefers-color-scheme: dark)");
  if (!query?.addEventListener) return () => {};
  const onChange = (e: MediaQueryListEvent) => applyTheme(e.matches);
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}
