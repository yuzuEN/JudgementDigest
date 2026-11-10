import { InfoIcon } from "lucide-react";
import type { ReactNode } from "react";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

/**
 * 結果頁頁尾：一行「不是法律意見」＋「請注意」。滑鼠移上去、鍵盤聚焦、手指點一下都能展開，往上開。
 * 列印時按鈕不印，條列由 PrintNotice 直接印出來（頁尾在列印時是隱藏的）。
 */
export function DisclaimerFooter({ items }: { items: ReactNode[] }) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2.5">
      <p className="m-0 min-w-0 flex-[1_1_320px]">本服務提供的是過去判決的統計參考，<b>不是法律意見</b>，也不是對你案子的預測。</p>
      <Popover>
        <PopoverTrigger openOnHover delay={100}
          className="no-print inline-flex min-h-11 items-center gap-1.5 rounded-full border-[1.5px] border-primary bg-background px-3.5 font-bold text-secondary-foreground">
          <InfoIcon className="size-[1.1em]" aria-hidden="true" />請注意
        </PopoverTrigger>
        <PopoverContent side="top" align="end" sideOffset={10}
          className="w-[min(440px,calc(100vw-32px))] gap-2 rounded-[14px] border-[1.5px] border-primary bg-card p-4 text-[15px] text-foreground shadow-lg ring-0">
          <p className="font-bold">請注意</p>
          <NoticeList items={items} />
        </PopoverContent>
      </Popover>
    </div>
  );
}

function NoticeList({ items }: { items: ReactNode[] }) {
  return <ul className="m-0 grid list-disc gap-1.5 pl-5">{items.map((it, i) => <li key={i}>{it}</li>)}</ul>;
}

/** 列印版：請注意的條列直接印在報告裡。 */
export function PrintNotice({ items }: { items: ReactNode[] }) {
  return (
    <section className="print-only text-sm">
      <h2 className="font-bold">請注意</h2>
      <NoticeList items={items} />
    </section>
  );
}
