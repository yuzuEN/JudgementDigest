import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { followSystemTheme, getThemePref, setThemePref, systemPrefersDark, THEME_KEY } from "../theme";
import { renderApp } from "./helpers";

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

const dark = () => document.documentElement.classList.contains("dark");

describe("夜間模式跟著系統", () => {
  afterEach(() => { document.documentElement.classList.remove("dark"); window.localStorage.clear(); });

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

describe("手動切換淺色／深色", () => {
  afterEach(() => { document.documentElement.classList.remove("dark"); window.localStorage.clear(); });

  it("選過之後記住，系統切換也不跟著變；選回跟著系統就清掉記錄", () => {
    const listeners = prefers(false);
    const stop = followSystemTheme();
    setThemePref("dark");
    expect(dark()).toBe(true);
    expect(window.localStorage.getItem(THEME_KEY)).toBe("dark");
    listeners.forEach((l) => l({ matches: false } as MediaQueryListEvent));
    expect(dark()).toBe(true);
    setThemePref("system");
    expect(getThemePref()).toBe("system");
    expect(window.localStorage.getItem(THEME_KEY)).toBeNull();
    expect(dark()).toBe(false);
    stop();
  });

  it("重新開啟時套用記住的選擇", () => {
    prefers(false);
    window.localStorage.setItem(THEME_KEY, "dark");
    followSystemTheme()();
    expect(dark()).toBe(true);
  });

  it("頁首的按鈕可以切換，文字說明切換後的樣子", async () => {
    prefers(false);
    followSystemTheme()();
    const user = userEvent.setup();
    renderApp("/");
    await user.click(screen.getByRole("button", { name: "切換成深色模式" }));
    expect(dark()).toBe(true);
    await user.click(screen.getByRole("button", { name: "切換成淺色模式" }));
    expect(dark()).toBe(false);
    expect(getThemePref()).toBe("light");
  });
});
