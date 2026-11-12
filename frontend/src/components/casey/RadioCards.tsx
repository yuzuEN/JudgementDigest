import { CheckIcon } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";

export interface RadioCardOption<T extends string> {
  value: T;
  title: string;
  hint?: ReactNode;
}

/**
 * 整塊可點的單選卡片（關卡 1 的類型、關卡 6 的寫法）。底層是 RadioGroup，鍵盤用方向鍵切換。
 * 選中時邊框加粗、底色變淺藍，並顯示勾，不只靠顏色區分。
 */
export function RadioCards<T extends string>({ label, value, onChange, options, className }: {
  label: string;
  value: T | "";
  onChange: (value: T) => void;
  options: RadioCardOption<T>[];
  className?: string;
}) {
  return (
    <RadioGroup aria-label={label} value={value || null} onValueChange={(v) => onChange(v as T)} className={cn("grid gap-2.5", className)}>
      {options.map((o) => {
        const on = o.value === value;
        return (
          <label key={o.value}
            className={cn(
              "flex min-h-[60px] cursor-pointer items-center gap-3 rounded-[14px] border-2 bg-card px-4 py-2.5 text-left transition-colors has-focus-visible:outline-3 has-focus-visible:outline-offset-2 has-focus-visible:outline-ring",
              on ? "border-foreground bg-secondary" : "border-input hover:border-primary",
            )}>
            <RadioGroupItem value={o.value} aria-label={o.title} className="sr-only" />
            <span className="flex min-w-0 flex-1 flex-col">
              <span className="font-bold">{o.title}</span>
              {o.hint && <span className="text-[15px] leading-snug text-muted-foreground">{o.hint}</span>}
            </span>
            <span aria-hidden="true" className={cn(
              "grid size-7 flex-none place-items-center rounded-full border-2",
              on ? "border-primary bg-primary text-primary-foreground" : "border-input",
            )}>
              {on && <CheckIcon className="size-4" strokeWidth={3} />}
            </span>
          </label>
        );
      })}
    </RadioGroup>
  );
}
