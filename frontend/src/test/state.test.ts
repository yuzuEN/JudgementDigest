import { describe, expect, it } from "vitest";
import { civilInput, EMPTY_INTAKE, fullText } from "../state";

describe("fullText", () => {
  it("描述加上有回答的追問", () => {
    const intake = {
      ...EMPTY_INTAKE, text: " 被車撞 ",
      followupAnswers: {
        signal: { question: "當時是什麼燈？", answer: "綠燈" },
        skip: { question: "沒回答的問題？", answer: "  " },
      },
    };
    expect(fullText(intake)).toBe("被車撞\n當時是什麼燈？綠燈");
  });
});

describe("civilInput", () => {
  it("送遮名後的文字，問卷轉成 API 的欄位", () => {
    const input = civilInput({
      ...EMPTY_INTAKE, text: "我是王小明", maskedText: "我是【姓名】", mid: "民間借貸",
      lawyer: "no", defendantType: "company", claimedAmount: "50萬", evidence: ["transfer"],
    });
    expect(input).toEqual({
      text: "我是【姓名】", mid: "民間借貸", court: null, plaintiff_has_lawyer: false,
      defendant_type: "company", claimed_amount: 500000, evidence: ["transfer"],
    });
  });
  it("沒填的是 null", () => {
    const input = civilInput({ ...EMPTY_INTAKE, text: "x", maskedText: "x" });
    expect(input.mid).toBeNull();
    expect(input.plaintiff_has_lawyer).toBeNull();
    expect(input.defendant_type).toBeNull();
    expect(input.claimed_amount).toBeNull();
  });
});
