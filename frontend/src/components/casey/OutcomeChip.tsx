import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import type { Tone } from "../../format";

/** 結果標籤：深靛（全部勝訴）、淺藍（一部勝訴）、沙灰虛線（敗訴）。顏色不分好壞，一律有文字。 */
const STYLE: Record<Tone, string> = {
  win: "border-outcome-full bg-outcome-full text-outcome-full-fg",
  partial: "border-outcome-part bg-outcome-part-bg text-outcome-part-fg",
  lose: "border-dashed border-outcome-lose-line bg-outcome-lose-bg text-outcome-lose-fg",
  neutral: "border-input bg-muted text-foreground",
};

export function OutcomeChip({ tone, children, className }: { tone: Tone; children: ReactNode; className?: string }) {
  return (
    <span className={cn("inline-flex w-fit items-center gap-1.5 rounded-full border-[1.5px] px-3 text-sm leading-[1.9] font-bold whitespace-nowrap", STYLE[tone], className)}>
      {children}
    </span>
  );
}
