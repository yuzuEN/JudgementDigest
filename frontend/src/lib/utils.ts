import { createCn } from "cn/config";

/**
 * 合併 class（clsx + tailwind-merge）。index.css 自訂的字級 token（text-hint／title／display）要登記成字級，
 * 不然會被當成文字顏色，和 text-muted-foreground 之類放在一起時被刪掉。
 */
export const cn = createCn({
  extend: { classGroups: { "font-size": [{ text: ["hint", "title", "display"] }] } },
});
