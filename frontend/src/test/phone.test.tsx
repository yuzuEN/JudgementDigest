import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PhoneCollapse } from "../components/casey/PhoneCollapse";

/** 模擬手機寬度：只有手機的條件（screen and (width < 40rem)）成立。 */
const asPhone = () => {
  window.matchMedia = vi.fn((q: string) => ({
    matches: q.includes("40rem"), media: q,
    addEventListener: () => {}, removeEventListener: () => {},
  })) as unknown as typeof window.matchMedia;
};

afterEach(() => {
  // jsdom 本來沒有 matchMedia，測完拿掉，不影響別的測試
  delete (window as { matchMedia?: unknown }).matchMedia;
});

const titled = (
  <PhoneCollapse label="這次比對用的描述" heading={(c) => <h2>{c}</h2>}>
    <p>去年三月我騎機車在路口直行</p>
  </PhoneCollapse>
);

describe("PhoneCollapse：手機上收起次要說明", () => {
  it("電腦版：標題和內容原樣顯示，沒有展開按鈕", () => {
    render(titled);
    expect(screen.getByRole("heading", { name: "這次比對用的描述" })).toBeInTheDocument();
    expect(screen.getByText("去年三月我騎機車在路口直行")).toBeVisible();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("手機版：標題裡是展開按鈕，內容預設收起，點了才出現", async () => {
    asPhone();
    const user = userEvent.setup();
    render(titled);
    const button = screen.getByRole("button", { name: "這次比對用的描述" });
    expect(button.closest("h2")).not.toBeNull();
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByText("去年三月我騎機車在路口直行")).not.toBeVisible();
    await user.click(button);
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("去年三月我騎機車在路口直行")).toBeVisible();
  });

  it("手機版可以換一個按鈕文字（例如帶上進度）", () => {
    asPhone();
    render(
      <PhoneCollapse label="可補充的細節（寫到時會標記）" phoneLabel="可補充的細節：已寫到 3／6" heading={(c) => <p>{c}</p>}>
        <ul><li>時間</li></ul>
      </PhoneCollapse>,
    );
    expect(screen.getByRole("button", { name: "可補充的細節：已寫到 3／6" })).toBeInTheDocument();
  });

  it("沒有標題的說明：電腦版只有內容，手機版是一顆「說明」按鈕", () => {
    const plain = <PhoneCollapse label="說明"><p>範圍只說明判多少</p></PhoneCollapse>;
    const { unmount } = render(plain);
    expect(screen.getByText("範圍只說明判多少")).toBeVisible();
    expect(screen.queryByText("說明")).not.toBeInTheDocument();
    unmount();
    asPhone();
    render(plain);
    expect(screen.getByRole("button", { name: "說明" })).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByText("範圍只說明判多少")).not.toBeVisible();
  });
});
