import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";

/** 二選一、三選一：ToggleGroup 單選，再點一次可以取消（等於不確定）。required 時不能取消（一定有一個選中）。 */
export function Segmented({ labelledBy, value, items, onChange, className, required = false, stackOnPhone = false }: {
  labelledBy: string;
  value: string;
  items: { value: string; label: ReactNode }[];
  onChange: (value: string) => void;
  className?: string;
  required?: boolean;
  /** 手機上改成上下排（選項文字長、三選一時用） */
  stackOnPhone?: boolean;
}) {
  return (
    <ToggleGroup aria-labelledby={labelledBy} spacing={0} value={value ? [value] : []}
      onValueChange={(v: string[]) => { if (v[0] || !required) onChange(v[0] ?? ""); }}
      className={cn("w-full overflow-hidden rounded-[12px] border-2 border-input bg-card", stackOnPhone && "phone:flex-col", className)}>
      {items.map((it) => (
        <ToggleGroupItem key={it.value} value={it.value}
          className={cn("h-auto min-h-[50px] flex-1 rounded-none! border-l-2 border-input gap-1.5 px-2 text-base font-bold whitespace-normal text-foreground first:border-l-0 hover:bg-secondary aria-pressed:bg-primary aria-pressed:text-primary-foreground aria-pressed:hover:bg-primary",
            stackOnPhone && "phone:w-full phone:border-t-2 phone:border-l-0 phone:first:border-t-0")}>
          {it.label}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  );
}
