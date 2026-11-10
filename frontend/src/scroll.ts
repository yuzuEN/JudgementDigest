/** 平滑捲到頁面中的某一段（使用者設定減少動態時直接跳過去），網址的 #hash 跟著換，但不觸發路由。 */
export function scrollToSection(id: string) {
  const target = document.getElementById(id);
  if (!target) return false;
  const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  target.scrollIntoView?.({ behavior: reduce ? "auto" : "smooth", block: "start" });
  history.replaceState(history.state, "", `#${encodeURIComponent(id)}`);
  return true;
}
