import { describe, expect, it } from "vitest";
import { money, outcomeLabel, outcomeTone, parseAmount, percent, sensitiveKinds, splitMasked } from "../format";

describe("money", () => {
  it("萬以上用萬", () => {
    expect(money(310000)).toBe("31 萬");
    expect(money(12000)).toBe("1.2 萬");
    expect(money(1_234_000)).toBe("123 萬");
  });
  it("萬以下用元", () => expect(money(8000)).toBe("8,000 元"));
  it("沒有值", () => {
    expect(money(null)).toBe("—");
    expect(money(undefined)).toBe("—");
  });
});

describe("parseAmount", () => {
  it.each([
    ["500000", 500000], ["500,000", 500000], ["50萬", 500000], ["1.5萬", 15000], ["30000元", 30000], [" 2 萬 ", 20000],
  ])("%s → %d", (input, expected) => expect(parseAmount(input)).toBe(expected));
  it("看不懂就是 null", () => {
    expect(parseAmount("")).toBeNull();
    expect(parseAmount("五十萬")).toBeNull();
    expect(parseAmount("50k")).toBeNull();
  });
});

describe("其他", () => {
  it("percent", () => expect(percent(0.623)).toBe("62%"));
  it("判決結果", () => {
    expect(outcomeTone("一部勝訴一部敗訴")).toBe("partial");
    expect(outcomeTone("確認勝訴")).toBe("win");
    expect(outcomeTone("敗訴")).toBe("lose");
    expect(outcomeTone("有罪")).toBe("neutral");
    expect(outcomeLabel("一部勝訴一部敗訴")).toBe("一部勝訴");
  });
  it("敏感個資依法定類別偵測", () => {
    expect(sensitiveKinds("右手骨折住院")).toEqual(["病歷、醫療"]);
    expect(sensitiveKinds("做過健康檢查，也有前科"))
      .toEqual(["健康檢查", "犯罪前科"]);
    expect(sensitiveKinds("基因檢測顯示性取向")).toEqual(["基因", "性生活"]);
  });
  it("日常用語不算敏感個資", () => {
    const texts = ["借了五十萬沒有還", "我受傷了", "對方涉嫌傷害", "有點失眠"];
    for (const text of texts) expect(sensitiveKinds(text)).toEqual([]);
  });
  it("splitMasked", () => {
    expect(splitMasked("我是【姓名】，電話【電話】。")).toEqual([
      { text: "我是", masked: false }, { text: "【姓名】", masked: true }, { text: "，電話", masked: false },
      { text: "【電話】", masked: true }, { text: "。", masked: false },
    ]);
  });
});
