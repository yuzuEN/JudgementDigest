import { CheckIcon, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { Toggle } from "@/components/ui/toggle";

/**
 * 證物欄的一格：點一下＝手上有。底層是 Toggle（aria-pressed），選中時右上角有打勾徽章、邊框加粗。
 * 只勾選，不上傳檔案。
 */
export function EvidenceSlot({ label, icon: Icon, pressed, onPressedChange }: {
  label: string;
  icon: LucideIcon;
  pressed: boolean;
  onPressedChange: (pressed: boolean) => void;
}) {
  return (
    <Toggle pressed={pressed} onPressedChange={onPressedChange}
      className={cn(
        "relative grid h-auto min-h-[100px] w-full place-items-center content-center gap-1 rounded-[14px] border-2 bg-card p-2.5 text-center text-[15px] leading-snug font-bold whitespace-normal text-foreground",
        "hover:bg-card hover:border-primary aria-pressed:bg-secondary aria-pressed:hover:bg-secondary",
        pressed ? "border-foreground" : "border-input",
      )}>
      {pressed && (
        <span aria-hidden="true" className="absolute top-1.5 right-1.5 grid size-6 place-items-center rounded-full bg-primary text-primary-foreground">
          <CheckIcon className="size-3.5" strokeWidth={3} />
        </span>
      )}
      <Icon className="size-7 text-secondary-foreground" aria-hidden="true" />
      <span>{label}</span>
    </Toggle>
  );
}
