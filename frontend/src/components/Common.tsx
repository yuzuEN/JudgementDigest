import { ExternalLinkIcon, InfoIcon, RotateCwIcon, TriangleAlertIcon } from "lucide-react";
import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";

export const LAF_URL = "https://www.laf.org.tw/";

/** 欄位名稱旁的 i，開新分頁到說明頁，不會中斷目前的流程。 */
export function InfoLink({ to, label }: { to: string; label: string }) {
  return (
    <a data-slot="info-link" className="no-print relative inline-flex size-6 items-center justify-center rounded-full text-primary after:absolute after:-inset-2.5 after:content-[''] hover:bg-accent"
      href={`/guide#${encodeURIComponent(to)}`} target="_blank" rel="noreferrer" aria-label={`${label}（開新分頁）`} title={label}>
      <InfoIcon className="size-4" aria-hidden="true" />
    </a>
  );
}

/** 民事每件相似判決下方：和使用者的情況相同的地方（後端用案由、金額、證據類型、法院比對）。 */
export function CommonPoints({ points }: { points?: string[] | null }) {
  if (!points || points.length === 0) return null;
  return (
    <span className="mt-1 flex flex-wrap items-center gap-1.5 text-sm">
      {points.map((p) => (
        // 圓角固定 12px（一行高 24px，看起來和膠囊一樣）；窄螢幕折成兩三行時不會變成大圓弧
        <span key={p} className="rounded-[12px] border border-input bg-secondary px-2 leading-6 text-secondary-foreground">{p}</span>
      ))}
    </span>
  );
}

/** 相似判決的字號：有司法院原文網址時，整個字號就是原文連結（開新分頁）。 */
export function CaseNumber({ c }: { c: { case_number: string; url?: string | null } }) {
  if (!c.url) return <b>{c.case_number}</b>;
  return (
    <a href={c.url} target="_blank" rel="noreferrer" aria-label={`${c.case_number}（司法院判決原文，開新分頁）`}
      className="inline font-bold text-foreground decoration-1 underline-offset-3 hover:text-primary">
      {c.case_number}<ExternalLinkIcon className="ml-1 inline size-4 align-[-2px] text-primary" aria-hidden="true" />
    </a>
  );
}

/** 出錯時：說明恢復方式，提供重試。只影響出錯的那一個區塊。 */
export function ErrorBox({ message, onRetry, hint = "請稍後再試。", children }: {
  message: string;
  onRetry?: () => void;
  hint?: string;
  children?: ReactNode;
}) {
  return (
    <div role="alert" className="flex flex-col gap-3 rounded-[18px] border-[1.5px] border-input bg-card p-5">
      <p className="flex items-center gap-3 text-xl font-bold">
        <TriangleAlertIcon className="size-7 flex-none text-secondary-foreground" aria-hidden="true" />無法載入資料
      </p>
      <p className="text-hint text-muted-foreground">{hint}</p>
      <p className="text-sm text-muted-foreground">（{message}）</p>
      {(onRetry || children) && (
        <div className="flex flex-wrap gap-2.5">
          {onRetry && <Button onClick={onRetry}><RotateCwIcon data-icon="inline-start" />再試一次</Button>}
          {children}
        </div>
      )}
    </div>
  );
}
