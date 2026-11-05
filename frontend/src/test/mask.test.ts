import { describe, expect, it } from "vitest";
import { maskText } from "../mask";
import cases from "./masking_cases.json";

describe("瀏覽器遮名", () => {
  it.each(cases)("$text", ({ text, names, expected }) => {
    expect(maskText(text, names)).toBe(expected);
  });
});
