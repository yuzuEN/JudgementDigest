import { afterEach, describe, expect, it, vi } from "vitest";
import { followSystemTheme, systemPrefersDark } from "../theme";

type Listener = (e: MediaQueryListEvent) => void;

const prefers = (dark: boolean) => {
  const listeners: Listener[] = [];
  window.matchMedia ??= (() => ({ matches: false })) as unknown as typeof window.matchMedia;
  vi.spyOn(window, "matchMedia").mockImplementation((q) => ({
    matches: dark, media: q,
    addEventListener: (_: string, l: Listener) => listeners.push(l),
    removeEventListener: (_: string, l: Listener) => listeners.splice(listeners.indexOf(l), 1),
  } as unknown as MediaQueryList));
  return listeners;
};

describe("夜間模式跟著系統", () => {
  afterEach(() => document.documentElement.classList.remove("dark"));

  it("讀系統設定", () => {
    prefers(true);
    expect(systemPrefersDark()).toBe(true);
    prefers(false);
    expect(systemPrefersDark()).toBe(false);
  });

  it("系統切換時頁面也跟著換", () => {
    const listeners = prefers(false);
    const stop = followSystemTheme();
    expect(document.documentElement.classList.contains("dark")).toBe(false);
    listeners.forEach((l) => l({ matches: true } as MediaQueryListEvent));
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    stop();
    expect(listeners).toHaveLength(0);
  });

  it("瀏覽器沒有 matchMedia 也不會壞", () => {
    vi.spyOn(window, "matchMedia").mockImplementation(undefined as unknown as typeof window.matchMedia);
    expect(() => followSystemTheme()).not.toThrow();
  });
});
