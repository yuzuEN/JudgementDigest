import { InfoIcon, Loader2Icon, RotateCwIcon, TriangleAlertIcon } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export const LAF_URL = "https://www.laf.org.tw/";

export function MockBadge({ show, children = "示例資料：數字與判決都不是真的" }: { show: boolean; children?: ReactNode }) {
  return show ? <Badge variant="secondary" className="h-auto rounded-md px-3 py-1 text-sm">{children}</Badge> : null;
}

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

export function Loading({ children = "載入中……" }: { children?: ReactNode }) {
  return (
    <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
      <Loader2Icon className="size-4 animate-spin motion-reduce:animate-[spin_3s_linear_infinite]" aria-hidden="true" />{children}
    </p>
  );
}

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

/** 提醒用的暖色卡片（「這不是法律意見」等）。 */
export function WarnCard({ title, children, className, id }: { title: ReactNode; children: ReactNode; className?: string; id?: string }) {
  return (
    <Card className={cn("bg-warn text-warn-foreground ring-warn-border", className)} aria-labelledby={id}>
      <CardHeader><CardTitle id={id} className="text-base text-warn-title">{title}</CardTitle></CardHeader>
      <CardContent className="text-[15px] leading-relaxed">{children}</CardContent>
    </Card>
  );
}

/** 結果頁底下的「怎麼看這些結果」。 */
export function ResultNotes({ items }: { items: ReactNode[] }) {
  return (
    <WarnCard title="怎麼看這些結果" id="notes-title">
      <ul className="flex list-disc flex-col gap-1.5 pl-5">
        {items.map((item, i) => <li key={i}>{item}</li>)}
      </ul>
    </WarnCard>
  );
}

/** 頁面標題與說明。 */
export function PageTitle({ title, lead, className }: { title: ReactNode; lead?: ReactNode; className?: string }) {
  return (
    <div className={cn("flex flex-col gap-2", className)}>
      <h1 className="text-3xl font-bold tracking-tight">{title}</h1>
      {lead && <p className="text-muted-foreground">{lead}</p>}
    </div>
  );
}

/** 卡片標題用的大小。 */
export const CARD_TITLE = "text-lg font-bold";
