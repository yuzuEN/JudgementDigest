import { cn } from "@/lib/utils";

const clamp = (v: number) => Math.max(0, Math.min(1, v));

/** 長條：value 是 0–1。有 label 時是一張圖（role="img"），沒有時只是裝飾（旁邊要有數字文字）。 */
export function Bar({ value, className, fill = "bg-primary", label }: { value: number; className?: string; fill?: string; label?: string }) {
  return (
    <div className={cn("h-2.5 overflow-hidden rounded-full border bg-muted", className)}
      role={label ? "img" : undefined} aria-label={label} aria-hidden={label ? undefined : true}>
      <span className={cn("block h-full rounded-full", fill)} style={{ width: `${clamp(value) * 100}%` }} />
    </div>
  );
}

/**
 * 一列：名稱、長條、數字（證據對照用）。
 * 窄螢幕排兩行：名稱｜數字，長條｜children（例如「你有提到」）；sm 以上一行排開，順序照 DOM。
 */
export function MiniBarRow({ label, value, valueText, alt, fill, className, children }: {
  label: string;
  value: number;
  valueText: string;
  alt: string;
  fill?: string;
  className?: string;
  children?: React.ReactNode;
}) {
  return (
    <div className={cn("grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1.5 sm:grid-cols-[150px_minmax(0,1fr)_56px]", className)}>
      <span className="order-1 font-bold sm:order-none">{label}</span>
      <Bar value={value} label={alt} fill={fill} className="order-3 sm:order-none" />
      <span className="order-2 text-right font-bold tabular-nums sm:order-none">{valueText}</span>
      {children}
    </div>
  );
}
