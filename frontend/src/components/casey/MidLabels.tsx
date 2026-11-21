import { cn } from "@/lib/utils";

/** 「侵權：交通事故」只留「交通事故」；沒有大類前綴的原樣顯示。 */
export const midName = (mid: string) => (mid.includes("：") ? mid.split("：").slice(1).join("：") : mid);

/** 已選的糾紛類型：一個類型一個標籤，只顯示名稱。vertical 時一個一列（靠右對齊，放在摘要表的右欄）。 */
export function MidLabels({ mids, vertical = false, className }: { mids: string[]; vertical?: boolean; className?: string }) {
  return (
    <ul className={cn("m-0 flex list-none gap-1.5 p-0", vertical ? "flex-col items-end" : "flex-wrap", className)}>
      {mids.map((m) => (
        <li key={m} title={m} className="rounded-full bg-secondary px-2.5 py-0.5 text-sm leading-[1.6] font-bold text-secondary-foreground">{midName(m)}</li>
      ))}
    </ul>
  );
}
