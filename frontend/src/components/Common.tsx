import { InfoIcon, RotateCwIcon, TriangleAlertIcon } from "lucide-react";
import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";

export const LAF_URL = "https://www.laf.org.tw/";

/** 欄位名稱旁的 i，開新分頁到說明頁，不會中斷目前的流程。 */
export function InfoLink({ to, label }: { to: string; label: string }) {
  return (
    <a data-slot="info-link" className="no-print inline-flex size-6 items-center justify-center rounded-full text-primary hover:bg-accent"
      href={`/guide#${encodeURIComponent(to)}`} target="_blank" rel="noreferrer" aria-label={`${label}（開新分頁）`} title={label}>
      <InfoIcon className="size-4" aria-hidden="true" />
    </a>
  );
}

export const SIMILARITY_NOTE = "相似度是用字接近的程度（0 到 1），只用來排列結果，不是百分比，也不代表案情或結果相同。";

/** 出錯時：說清楚不是使用者填錯，給重試。只影響出錯的那一個區塊。 */
export function ErrorBox({ message, onRetry, hint = "暫時沒有載入成功，不是你填錯了什麼。", children }: {
  message: string;
  onRetry?: () => void;
  hint?: string;
  children?: ReactNode;
}) {
  return (
    <div role="alert" className="flex flex-col gap-3 rounded-[18px] border-[1.5px] border-input bg-card p-5">
      <p className="flex items-center gap-3 text-xl font-bold">
        <TriangleAlertIcon className="size-7 flex-none text-secondary-foreground" aria-hidden="true" />出了點問題
      </p>
      <p className="text-[15px] text-muted-foreground">{hint}</p>
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
