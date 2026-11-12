import { cn } from "@/lib/utils";

/**
 * 判准範圍條：low／median／high 都是 0–1 的比例。
 * 模型推估用虛線填色（比較不確定），相似判決用實線。條上只標中位數，兩端寫在下面。
 */
export function RangeBar({ low, median, high, dashed, medianLabel, startLabel, endLabel, label }: {
  low: number;
  median: number;
  high: number;
  dashed: boolean;
  medianLabel: string;
  startLabel: string;
  endLabel: string;
  label: string;
}) {
  const pct = (v: number) => `${Math.max(0, Math.min(1, v)) * 100}%`;
  // 中位數的文字太靠邊時往內收，不要超出卡片
  const labelAlign = median < 0.15 ? "translate-x-0" : median > 0.85 ? "-translate-x-full" : "-translate-x-1/2";
  return (
    <figure role="group" aria-label={label} className="m-0">
      <div className="relative mx-1.5 mt-11 mb-2 h-[30px]" aria-hidden="true">
        <div className="absolute inset-x-0 top-2 h-3.5 rounded-[7px] border-[1.5px] border-input bg-muted" />
        <div
          className={cn("absolute top-1 h-[22px] rounded-[11px] border-2 border-outcome-part-fg",
            dashed ? "bg-[repeating-linear-gradient(90deg,var(--outcome-part)_0_8px,transparent_8px_14px)]" : "bg-outcome-part")}
          style={{ left: pct(low), width: `calc(${pct(high)} - ${pct(low)})` }} />
        <div className="absolute -top-1.5 h-[42px] w-1 -translate-x-1/2 rounded-sm bg-foreground" style={{ left: pct(median) }} />
        <span className={cn("absolute -top-11 text-sm leading-tight font-bold whitespace-nowrap", labelAlign)} style={{ left: pct(median) }}>{medianLabel}</span>
      </div>
      <figcaption className="mx-1.5 flex justify-between text-sm text-muted-foreground" aria-hidden="true">
        <span>{startLabel}</span><span>{endLabel}</span>
      </figcaption>
    </figure>
  );
}
