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

/** 一列：名稱、長條、數字。證據對照、抗辯比例、刑期分布共用。 */
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
    <div className={cn("grid grid-cols-[minmax(0,1fr)_56px] items-center gap-x-3 gap-y-1.5 sm:grid-cols-[150px_minmax(0,1fr)_56px]", className)}>
      <span className="font-bold max-sm:col-span-2">{label}</span>
      <Bar value={value} label={alt} fill={fill} />
      <span className="text-right font-bold tabular-nums">{valueText}</span>
      {children}
    </div>
  );
}
