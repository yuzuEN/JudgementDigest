import { useSyncExternalStore } from "react";

/** 和 CSS 的 phone 變體同一個條件（index.css 的 @custom-variant phone）。 */
const QUERY = "screen and (width < 40rem)";

function subscribe(onChange: () => void): () => void {
  const query = window.matchMedia?.(QUERY);
  if (!query?.addEventListener) return () => {};
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}

const isPhone = () => Boolean(window.matchMedia?.(QUERY).matches);

/**
 * 是不是手機寬度的螢幕。只用在「手機上要換成不同元素」的地方（例如收合按鈕）；
 * 單純改樣式用 CSS 的 phone: 就好。沒有 matchMedia（測試環境）時當作電腦。
 */
export function usePhone(): boolean {
  return useSyncExternalStore(subscribe, isPhone, () => false);
}
