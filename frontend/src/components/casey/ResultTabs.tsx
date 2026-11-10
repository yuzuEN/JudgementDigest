import { Tabs } from "@base-ui/react/tabs";
import { InfoIcon, LoaderCircleIcon } from "lucide-react";
import type { ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import { SampleTag } from "./Sample";

export interface ResultTab<K extends string> {
  key: K;
  label: string;
  content: ReactNode;
}

/** 目前的分頁：網址的 ?tab=，不認得就用第一個。 */
export function useResultTab<K extends string>(keys: readonly K[]): [K, (k: K) => void] {
  const [params, setParams] = useSearchParams();
  const raw = params.get("tab");
  const tab = keys.includes(raw as K) ? (raw as K) : keys[0];
  return [tab, (k) => setParams({ tab: k }, { replace: true })];
}

/**
 * 結果頁的資料夾式分頁。用 Base UI 的分頁元件自己排（shadcn 的兩種樣式和設計稿不合）。
 * 沒在看的分頁也留在頁面上（keepMounted），列印時全部印出來（index.css）。
 */
export function ResultTabs<K extends string>({ tabs, value, onChange, mock }: {
  tabs: ResultTab<K>[];
  value: K;
  onChange: (k: K) => void;
  mock: boolean;
}) {
  return (
    <Tabs.Root value={value} onValueChange={(v) => onChange(v as K)} className="flex flex-col">
      <Tabs.List aria-label="結果分頁" className="no-print relative z-10 -mb-0.5 flex gap-1.5 overflow-x-auto">
        {tabs.map((t) => (
          <Tabs.Tab key={t.key} value={t.key}
            className="min-h-[50px] flex-none rounded-t-[12px] border-2 border-b-0 border-input bg-muted px-[18px] font-bold whitespace-nowrap text-muted-foreground hover:text-foreground data-active:border-foreground data-active:bg-card data-active:text-foreground">
            {t.label}
          </Tabs.Tab>
        ))}
      </Tabs.List>
      {tabs.map((t, i) => (
        <Tabs.Panel key={t.key} value={t.key} keepMounted data-slot="tabs-content"
          className={cn("flex flex-col gap-4 rounded-[16px] border-2 bg-card p-[18px] outline-none sm:p-[22px] [&[hidden]]:hidden",
            i === 0 && "rounded-tl-none", mock ? "border-dashed border-sample-line" : "border-foreground")}>
          {t.content}
        </Tabs.Panel>
      ))}
    </Tabs.Root>
  );
}

/** 整頁載入中：骨架維持最終版面的位置，同時說明正在做什麼。 */
export function LoadingPanel({ children = "正在比對相似判決…" }: { children?: ReactNode }) {
  return (
    <div aria-busy="true" className="flex flex-col gap-3.5 rounded-[16px] border-2 border-input bg-card p-[22px]">
      <p role="status" className="flex flex-wrap items-center gap-3">
        <LoaderCircleIcon className="size-5 animate-spin text-primary motion-reduce:animate-none" aria-hidden="true" />
        <b>{children}</b><span className="text-[15px] text-muted-foreground">大約需要幾秒</span>
      </p>
      <div className="flex flex-col gap-3" aria-hidden="true">
        <Skeleton className="h-[22px] w-2/5" /><Skeleton className="h-[22px] rounded-[11px]" />
        <Skeleton className="h-[18px] w-[70%]" /><Skeleton className="h-[18px] w-3/5" /><Skeleton className="h-24" />
      </div>
    </div>
  );
}

export function PanelTitle({ children, mock, action }: { children: ReactNode; mock?: boolean; action?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
      <h2 className="text-[22px] leading-[1.45] font-extrabold sm:text-[26px]">{children}</h2>
      <div className="flex flex-wrap items-center gap-3">{action}{mock && <SampleTag />}</div>
    </div>
  );
}

export function InfoNote({ children, title }: { children: ReactNode; title?: string }) {
  return (
    <div className="flex items-start gap-3 rounded-[14px] border border-info-line bg-info px-4 py-3.5">
      <InfoIcon className="mt-1 size-5 flex-none text-secondary-foreground" aria-hidden="true" />
      <div className="flex min-w-0 flex-col gap-1">
        {title && <p className="font-bold">{title}</p>}
        <div className="text-[15px]">{children}</div>
      </div>
    </div>
  );
}
