import { ChevronDownIcon } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/** 可展開的說明（原生 details）：列印時 ResultFrame 會全部展開。 */
export function Disclosure({ summary, children, className }: { summary: ReactNode; children: ReactNode; className?: string }) {
  return (
    <details className={cn("group/disclosure rounded-[12px] border bg-card", className)}>
      <summary className="flex min-h-12 cursor-pointer list-none items-center gap-2 px-4 py-2 font-bold [&::-webkit-details-marker]:hidden">
        {summary}
        <ChevronDownIcon className="ml-auto size-5 flex-none transition-transform group-open/disclosure:rotate-180 motion-reduce:transition-none" aria-hidden="true" />
      </summary>
      <div className="flex flex-col gap-2 px-4 pt-1 pb-4">{children}</div>
    </details>
  );
}
