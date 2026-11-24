import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";

/** 二選一、三選一：ToggleGroup 單選，再點一次可以取消（等於不確定）。required 時不能取消（一定有一個選中）。 */
export function Segmented({ labelledBy, value, items, onChange, className, required = false }: {
  labelledBy: string;
  value: string;
  items: { value: string; label: ReactNode }[];
  onChange: (value: string) => void;
  className?: string;
  required?: boolean;
}) {
  return (
    <ToggleGroup aria-labelledby={labelledBy} spacing={0} value={value ? [value] : []}
      onValueChange={(v: string[]) => { if (v[0] || !required) onChange(v[0] ?? ""); }}
      className={cn("w-full items-stretch overflow-hidden rounded-[12px] border-2 border-input bg-card", className)}>
      {items.map((it) => (
        <ToggleGroupItem key={it.value} value={it.value}
          className="h-auto min-h-[50px] flex-1 rounded-none! border-l-2 border-input gap-1.5 px-2 py-1.5 text-base leading-snug font-bold whitespace-normal text-foreground first:border-l-0 hover:bg-secondary aria-pressed:bg-primary aria-pressed:text-primary-foreground aria-pressed:hover:bg-primary phone:min-h-11 phone:px-1.5">
          {it.label}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  );
}
