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

/**
 * 相似判決表格上方的說明：從多少件判決裡找出來的、怎麼排序、共同關鍵詞是什麼。
 * 不顯示相似度的數字：口語描述和判決的寫法不同，最接近的判決通常也只有 0.1–0.2，數字看起來很低，
 * 反而讓人以為不像；排序和共同關鍵詞已經說明了接近的程度與原因。
 */
export function corpusLead(nCorpus: number | null | undefined, shown: number): string {
  const from = nCorpus ? `從 ${nCorpus.toLocaleString("en-US")} 件判決中，` : "";
  return `${from}找出和你的描述用字最接近的 ${shown} 件，越上面越接近。「共同關鍵詞」是你的描述和這件判決共有的詞。用字接近不代表案情或結果相同，請點判決導讀自己判斷。`;
}

/** 每件相似判決下方：和使用者描述共有、最能說明為什麼找到這件的詞（後端只從使用者的描述取）。 */
export function SharedTerms({ terms }: { terms?: string[] | null }) {
  if (!terms || terms.length === 0) return null;
  return (
    <span className="mt-1 flex flex-wrap items-center gap-1.5 text-sm">
      <span className="text-muted-foreground">共同關鍵詞</span>
      {terms.map((t) => (
        <span key={t} className="rounded-full border border-input bg-secondary px-2 leading-6 text-secondary-foreground">{t}</span>
      ))}
    </span>
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
