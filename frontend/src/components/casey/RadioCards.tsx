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
              "flex min-h-[60px] cursor-pointer items-center gap-3 rounded-[14px] border-2 bg-card px-4 py-2.5 text-left transition-colors phone:min-h-[52px] phone:gap-1.5 phone:px-2.5 has-focus-visible:outline-3 has-focus-visible:outline-offset-2 has-focus-visible:outline-ring",
              on ? "border-foreground bg-secondary" : "border-input hover:border-primary",
            )}>
            {/* 直接在 RadioGroupItem 上加 sr-only 會被它自己的 relative／size-4 蓋掉，還是佔 16px＋間距；包一層才真的不佔位置 */}
            <span className="sr-only"><RadioGroupItem value={o.value} aria-label={o.title} /></span>
            <span className="flex min-w-0 flex-1 flex-col">
              <span className="font-bold">{o.title}</span>
              {o.hint && <span className="text-hint leading-snug text-muted-foreground">{o.hint}</span>}
            </span>
            <span aria-hidden="true" className={cn(
              "grid size-7 flex-none place-items-center rounded-full border-2 phone:size-5",
              on ? "border-primary bg-primary text-primary-foreground" : "border-input",
            )}>
              {on && <CheckIcon className="size-4 phone:size-3.5" strokeWidth={3} />}
            </span>
          </label>
        );
      })}
    </RadioGroup>
  );
}
