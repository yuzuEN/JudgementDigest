import { ExternalLinkIcon } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { JUDICIAL_URL } from "../Layout";

/**
 * 判決導讀側欄的一列：名稱在左、內容在右（和填寫時的「你填的資料」同一種排法）。
 * nowrap 時內容不拆行：放不下就整段換到下一列，仍然靠右（金額「119,307 ／ 142,807 元」不會把「元」單獨折下去）。
 */
export function InfoRow({ label, children, nowrap = false }: { label: ReactNode; children: ReactNode; nowrap?: boolean }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1">
      <dt className="flex-none text-muted-foreground">{label}</dt>
      <dd className={cn("m-0 ml-auto text-right font-bold", nowrap && "whitespace-nowrap")}>{children}</dd>
    </div>
  );
}

/** 導讀頁標題旁的原文連結圖示：有這件判決的網址就開原文，沒有就開司法院裁判書查詢系統。 */
export function OriginalLink({ url, caseNumber }: { url?: string | null; caseNumber: string }) {
  const label = url ? `${caseNumber} 司法院判決原文（開新分頁）` : "司法院裁判書查詢系統（開新分頁）";
  return (
    <a href={url ?? JUDICIAL_URL} target="_blank" rel="noreferrer" aria-label={label} title={url ? "司法院判決原文" : "司法院裁判書查詢系統"}
      className="no-print mt-1.5 inline-flex size-11 flex-none items-center justify-center rounded-full text-primary hover:bg-accent">
      <ExternalLinkIcon className="size-6" aria-hidden="true" />
    </a>
  );
}
