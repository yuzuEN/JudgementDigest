import { InfoIcon, RotateCwIcon, TriangleAlertIcon } from "lucide-react";
import type { ReactNode } from "react";
import type { SearchScope } from "@/api/types";
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
 * 相似判決表格上方的說明：從哪個範圍、多少件判決裡找出來的，怎麼排序。
 * 不顯示相似度的數字或百分比：口語描述查到的最接近判決通常也只有 0.1–0.2；換成「比 99.99% 的判決相近」
 * 每件都一樣高，換成和其他查詢比的分段，口語測試裡和「找得對不對」的關係也很弱（E5，2026-11-18）。
 * 改說清楚範圍，民事每件再列用結構化欄位比對的「相同點」。
 */
export function corpusLead({ scope, shown, civil }: {
  scope?: SearchScope | null; shown: number; civil: boolean;
}): string {
  const n = scope?.n.toLocaleString("en-US");
  const group = scope?.mid ?? scope?.charge;
  const from = !scope ? "" : group ? `從 ${n} 件「${group}」判決中，` : `從 ${n} 件判決中，`;
  const inferred = scope?.mid && scope.mid_inferred ? `「${scope.mid}」是系統依你的描述判斷的類型。` : "";
  const common = civil ? "「相同點」是這件判決和你填的資料一樣的地方。" : "";
  const pickMid = civil && scope && !scope.mid ? "選了糾紛類型，找到的判決會更貼近。" : "";
  return `${from}找出和你的描述用字最接近的 ${shown} 件，越上面越接近。${inferred}${common}用字接近不代表案情或結果相同，請點判決導讀自己判斷。${pickMid}`;
}

/** 民事每件相似判決下方：和使用者的情況相同的地方（後端用案由、金額、證據類型、法院比對）。 */
export function CommonPoints({ points }: { points?: string[] | null }) {
  if (!points || points.length === 0) return null;
  return (
    <span className="mt-1 flex flex-wrap items-center gap-1.5 text-sm">
      <span className="text-muted-foreground">相同點</span>
      {points.map((p) => (
        <span key={p} className="rounded-full border border-input bg-secondary px-2 leading-6 text-secondary-foreground">{p}</span>
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
