import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { applyTheme, initialTheme } from "../theme";
import { renderApp } from "./helpers";

const prefers = (dark: boolean) => {
  vi.spyOn(window, "matchMedia").mockImplementation((q) => ({ matches: dark, media: q } as MediaQueryList));
};

describe("夜間模式", () => {
  afterEach(() => {
    localStorage.clear();
    delete document.documentElement.dataset.theme;
  });

  it("沒選過就跟著系統", () => {
    window.matchMedia ??= (() => ({ matches: false })) as unknown as typeof window.matchMedia;
    prefers(true);
    expect(initialTheme()).toBe("dark");
    prefers(false);
    expect(initialTheme()).toBe("light");
  });

  it("選過的設定優先於系統", () => {
    window.matchMedia ??= (() => ({ matches: false })) as unknown as typeof window.matchMedia;
    prefers(true);
    applyTheme("light", true);
    expect(initialTheme()).toBe("light");
  });

  it("瀏覽器不給存也不會壞", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("blocked"); });
    expect(() => applyTheme("dark", true)).not.toThrow();
    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("按鈕可以來回切換，並記住選擇", async () => {
    const user = userEvent.setup();
    localStorage.setItem("jd-theme", "light");
    renderApp("/");
    await user.click(screen.getByRole("button", { name: "切換成夜間模式" }));
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(localStorage.getItem("jd-theme")).toBe("dark");
    await user.click(screen.getByRole("button", { name: "切換成日間模式" }));
    expect(document.documentElement.dataset.theme).toBe("light");
  });
});
