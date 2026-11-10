import { describe, expect, it } from "vitest";
import { civilInput, EMPTY_INTAKE, fullText, loadIntake, STORAGE_KEY } from "../state";

describe("fullText", () => {
  it("描述加上有回答的追問", () => {
    const intake = {
      ...EMPTY_INTAKE, text: " 被車撞 ",
      followupAnswers: {
        signal: { question: "當時是什麼燈？", answer: "綠燈" },
        skip: { question: "沒回答的問題？", answer: "  " },
      },
    };
    expect(fullText(intake)).toBe("被車撞\n追問：當時是什麼燈？\n回答：綠燈");
  });
  it("刑事把律師和勾選的證據加在最後，民事不加（民事 API 有自己的欄位）", () => {
    const base = { ...EMPTY_INTAKE, text: "被打", lawyer: "no" as const, criminalEvidence: ["驗傷單、診斷證明", "證人"] };
    expect(fullText({ ...base, caseType: "criminal" })).toBe("被打\n有沒有請律師：沒有\n手上的證據：驗傷單、診斷證明、證人");
    expect(fullText({ ...base, caseType: "civil" })).toBe("被打");
    expect(fullText({ ...base, caseType: "criminal", lawyer: "" })).toBe("被打\n手上的證據：驗傷單、診斷證明、證人");
  });
});

describe("civilInput", () => {
  it("送遮名後的文字，問卷轉成 API 的欄位", () => {
    const input = civilInput({
      ...EMPTY_INTAKE, text: "我是王小明", maskedText: "我是【姓名】", mids: ["民間借貸"],
      lawyer: "no", defendantType: "company", claimedAmount: "50萬", evidence: ["transfer"],
    });
    expect(input).toEqual({
      text: "我是【姓名】", search_text: null, mid: "民間借貸", court: null, plaintiff_has_lawyer: false,
      defendant_type: "company", claimed_amount: 500000, evidence: ["transfer"],
    });
  });
  it("沒填的是 null", () => {
    const input = civilInput({ ...EMPTY_INTAKE, text: "x", maskedText: "x" });
    expect(input.mid).toBeNull();
    expect(civilInput({ ...EMPTY_INTAKE, text: "x", mids: ["民間借貸", "票據"] }).mid).toBeNull();   // 選好幾類就讓系統判斷
    expect(input.plaintiff_has_lawyer).toBeNull();
    expect(input.defendant_type).toBeNull();
    expect(input.claimed_amount).toBeNull();
  });
});

describe("重新整理後還原（sessionStorage）", () => {
  it("讀回這個分頁存的內容，缺的欄位用預設值", () => {
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ text: "被車撞", caseType: "criminal" }));
    expect(loadIntake()).toEqual({ ...EMPTY_INTAKE, text: "被車撞", caseType: "criminal" });
  });
  it("沒有或壞掉時從空白開始", () => {
    expect(loadIntake()).toEqual(EMPTY_INTAKE);
    window.sessionStorage.setItem(STORAGE_KEY, "{壞掉");
    expect(loadIntake()).toEqual(EMPTY_INTAKE);
  });
  it("不寫進 localStorage", () => {
    loadIntake();
    expect(window.localStorage.getItem(STORAGE_KEY)).toBeNull();
  });
});
