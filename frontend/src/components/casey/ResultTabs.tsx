import { Tabs } from "@base-ui/react/tabs";
import { InfoIcon, LoaderCircleIcon } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import { SampleTag } from "./Sample";

export interface ResultTab<K extends string> {
  key: K;
  label: string;
  content: ReactNode;
}

/**
 * 目前的分頁：網址的 ?tab=（param 可以換，民事、刑事放在同一頁時各用一個），不認得就用第一個。
 * 換分頁只改自己的參數，其他參數保留。
 */
export function useResultTab<K extends string>(keys: readonly K[], param = "tab"): [K, (k: K) => void] {
  const [params, setParams] = useSearchParams();
  const raw = params.get(param);
  const tab = keys.includes(raw as K) ? (raw as K) : keys[0];
  return [tab, (k) => setParams((prev) => { const next = new URLSearchParams(prev); next.set(param, k); return next; }, { replace: true })];
}

/**
 * 結果頁的資料夾式分頁。用 Base UI 的分頁元件自己排（shadcn 的兩種樣式和設計稿不合）。
 * 沒在看的分頁也留在頁面上（keepMounted），列印時全部印出來（index.css）。
 */
export function ResultTabs<K extends string>({ tabs, value, onChange, mock, action }: {
  tabs: ResultTab<K>[];
  value: K;
  onChange: (k: K) => void;
  mock: boolean;
  /** 放在頁籤同一列最右邊（下載 PDF），和面板右邊界對齊 */
  action?: ReactNode;
}) {
  const listRef = useRef<HTMLDivElement>(null);
  const moved = useRef(false);

  // 手機上頁籤會超出寬度：選中的頁籤不在畫面內時，只把頁籤列橫向捲過去（不用 scrollIntoView，免得整頁跟著捲）。
  // 從判決導讀回來（?tab=cases）也會落在畫面外，所以第一次就要捲。
  useLayoutEffect(() => {
    const list = listRef.current;
    const tab = list?.querySelector<HTMLElement>('[aria-selected="true"]');
    if (!list || !tab) return;
    const start = tab.offsetLeft, end = start + tab.offsetWidth;
    const view = list.scrollLeft, width = list.clientWidth;
    let left: number | null = null;
    if (start < view) left = Math.max(0, start - 16);
    else if (end > view + width) left = end - width + 16;
    if (left !== null) {
      const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
      list.scrollTo?.({ left, behavior: moved.current && !reduce ? "smooth" : "auto" });
    }
    moved.current = true;
  }, [value]);

  // 兩側還有沒露出的頁籤時，邊緣淡出，提示可以左右滑
  useEffect(() => {
    const list = listRef.current;
    if (!list) return;
    const update = () => {
      list.toggleAttribute("data-more-start", list.scrollLeft > 1);
      list.toggleAttribute("data-more-end", list.scrollLeft + list.clientWidth < list.scrollWidth - 1);
    };
    update();
    list.addEventListener("scroll", update, { passive: true });
    const ro = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(update);
    ro?.observe(list);
    return () => { list.removeEventListener("scroll", update); ro?.disconnect(); };
  }, []);

  return (
    <Tabs.Root value={value} onValueChange={(v) => onChange(v as K)} className="flex flex-col">
      {/*
        資料夾式頁籤：整列往下壓 2px（面板框線的粗細）。沒選的頁籤留 2px 底距，停在框線上方，
        框線從它們底下連續通過；選中的頁籤往下延伸 2px、用面板的底色蓋住框線，和面板接成一體。
      */}
      {/* 手機上「下載 PDF」移到頁籤上方，頁籤才有整列的寬度 */}
      <div className="relative z-10 -mb-0.5 flex flex-wrap items-end gap-x-3 gap-y-2">
      <Tabs.List ref={listRef} aria-label="結果分頁"
        className="no-print flex min-w-0 flex-1 items-end gap-1.5 overflow-x-auto data-more-end:mask-r-from-[calc(100%-2.5rem)] data-more-start:mask-l-from-[calc(100%-2.5rem)]">
        {tabs.map((t) => (
          <Tabs.Tab key={t.key} value={t.key}
            className={cn(
              "mb-0.5 min-h-[50px] phone:min-h-11 flex-none rounded-t-[12px] border-2 border-b-0 border-input bg-muted px-[18px] phone:px-3.5 font-bold whitespace-nowrap text-muted-foreground hover:text-foreground",
              "data-active:mb-0 data-active:min-h-[52px] phone:data-active:min-h-[46px] data-active:pb-0.5 data-active:bg-card data-active:text-foreground",
              mock ? "data-active:border-dashed data-active:border-sample-line" : "data-active:border-foreground",
            )}>
            {t.label}
          </Tabs.Tab>
        ))}
      </Tabs.List>
      {action && <div className="no-print mb-2 flex-none phone:order-first phone:mb-0 phone:flex phone:w-full phone:justify-end">{action}</div>}
      </div>
      {/* 左上角永遠是直角：第一個頁籤的左邊框和面板的左邊框接成一直線，不管選哪一頁 */}
      {tabs.map((t) => (
        <Tabs.Panel key={t.key} value={t.key} keepMounted data-slot="tabs-content"
          className={cn("flex flex-col gap-4 rounded-[16px] rounded-tl-none border-2 bg-card p-[18px] outline-none sm:p-[22px] [&[hidden]]:hidden",
            mock ? "border-dashed border-sample-line" : "border-foreground")}>
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
        <b>{children}</b><span className="text-hint text-muted-foreground">大約需要幾秒</span>
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
      <h2 className="text-title leading-[1.45] font-extrabold sm:text-[26px]">{children}</h2>
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
        <div className="text-hint">{children}</div>
      </div>
    </div>
  );
}
