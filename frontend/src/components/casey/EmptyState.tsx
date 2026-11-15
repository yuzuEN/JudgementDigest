import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/** 資料不足：不留白、不顯示 0，說明為什麼沒有、可以怎麼辦。 */
export function EmptyState({ title, children, icon, className }: { title: string; children: ReactNode; icon?: ReactNode; className?: string }) {
  return (
    <div className={cn("flex flex-col items-center gap-1.5 rounded-[14px] border-2 border-dashed border-input p-6 text-center", className)}>
      {icon}
      <p className="font-bold">{title}</p>
      <div className="max-w-[460px] text-[15px] text-muted-foreground">{children}</div>
    </div>
  );
}
