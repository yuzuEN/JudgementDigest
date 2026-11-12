import { ArrowLeftIcon, DownloadIcon, PencilIcon } from "lucide-react";
import { useEffect, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { useIntake } from "../state";
import { DisclaimerFooter, PrintNotice } from "./casey/DisclaimerFooter";
import { SampleBanner } from "./casey/Sample";
import { LinkButton } from "./LinkButton";
import { BRAND, Layout, PAGE } from "./Layout";

/** 列印或存成 PDF 時展開所有摺疊內容，印完恢復。按瀏覽器的列印也有效。 */
function useOpenDetailsForPrint() {
  useEffect(() => {
    let opened: HTMLDetailsElement[] = [];
    const open = () => {
      const closed = Array.from(document.querySelectorAll<HTMLDetailsElement>("details:not([open])"));
      closed.forEach((d) => { d.open = true; });
      opened.push(...closed);   // 事件可能連續觸發兩次，不能蓋掉前一次的清單
    };
    const restore = () => {
      opened.forEach((d) => { d.open = false; });
      opened = [];
    };
    window.addEventListener("beforeprint", open);
    window.addEventListener("afterprint", restore);
    return () => {
      window.removeEventListener("beforeprint", open);
      window.removeEventListener("afterprint", restore);
    };
  }, []);
}

/** 「不確定」時才有民事／刑事兩個分頁；選了民事或刑事就只有那一邊。 */
function CaseSwitch({ active }: { active: "civil" | "criminal" }) {
  const tab = (key: "civil" | "criminal", label: string) => {
    const cls = "inline-flex min-h-11 items-center rounded-[var(--radius-control)] border-2 px-5 font-bold no-underline";
    return key === active
      ? <span className={cn(cls, "border-primary bg-primary text-primary-foreground")} aria-current="page">{label}</span>
      : <Link to={`/result/${key}`} className={cn(cls, "border-input bg-card text-foreground hover:border-primary")}>{label}</Link>;
  };
  return (
    <nav aria-label="結果類型" className="no-print flex flex-wrap items-center gap-2">
      {tab("civil", "民事")}{tab("criminal", "刑事")}
      <span className="text-[15px] text-muted-foreground">你選了「不確定」，可切換查看民事與刑事結果。</span>
    </nav>
  );
}

/**
 * 民事、刑事結果頁共用的外框：解說員、示例資料標示、標題、下載 PDF、頁尾的「請注意」，
 * 以及只在列印時出現的報告抬頭與每頁頁尾。
 */
export function ResultFrame({ active, title, lead, mock, maskedText, searchText, sceneLine, notice, children }: {
  active: "civil" | "criminal";
  title: string;
  lead: ReactNode;
  mock: boolean;
  maskedText: string;
  searchText?: string;
  sceneLine: ReactNode;
  notice: ReactNode[];
  children: ReactNode;
}) {
  useOpenDetailsForPrint();
  const { intake } = useIntake();
  const label = active === "civil" ? "民事" : "刑事";
  return (
    <Layout stage={7} scene={{ who: "explainer", line: sceneLine }} footer={<DisclaimerFooter items={notice} />}>
      {mock && <div className={cn(PAGE, "no-print pt-5")}><SampleBanner /></div>}
      <main className={cn(PAGE, "flex flex-col gap-6 pt-7 pb-14")}>
        <div className="print-only">
          <h1 className="mb-1 text-xl font-bold">類案判決參考報告（{label}）</h1>
          <p className="text-sm">產生時間：{new Date().toLocaleString("zh-TW")}／{BRAND} 類案判決參考／結果僅供參考，不是法律意見</p>
          {mock && <p className="font-bold">本報告是示例資料：數字與判決都不是真的，請勿作為判斷依據。</p>}
          <h2 className="mt-3 text-base font-bold">案情描述（已遮名）</h2>
          <p className="text-sm whitespace-pre-wrap">{maskedText}</p>
          {searchText && <>
            <h2 className="mt-3 text-base font-bold">用來比對的整理文字（已確認）</h2>
            <p className="text-sm whitespace-pre-wrap">{searchText}</p>
          </>}
        </div>

        <div className="flex flex-col gap-4">
          <div className="no-print flex flex-wrap gap-2.5">
            <LinkButton variant="outline" to="/confirm?stage=6" className="border-input text-foreground"><ArrowLeftIcon data-icon="inline-start" />回上一步</LinkButton>
            <LinkButton variant="outline" to="/start?stage=2" className="border-input text-foreground"><PencilIcon data-icon="inline-start" />修改描述</LinkButton>
          </div>
          {intake.caseType === "unsure" && <CaseSwitch active={active} />}
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="flex min-w-0 flex-[1_1_420px] flex-col gap-2">
              <h1 className="text-[26px] leading-[1.4] font-extrabold text-balance sm:text-[32px]">{title}</h1>
              <p className="text-lg leading-[1.8] text-muted-foreground">{lead}</p>
            </div>
            <Button variant="outline" className="no-print" onClick={() => window.print()}><DownloadIcon data-icon="inline-start" />下載 PDF</Button>
          </div>
        </div>
        {children}
        <PrintNotice items={notice} />
      </main>
      {/* 列印時固定在每一頁底部 */}
      <div className="print-only print-page-footer text-xs">
        {mock && <p className="font-bold text-sample-fg">※ 示例資料，不是真實的查詢結果。</p>}
        <p>{BRAND} 類案判決參考（非法律意見）</p>
      </div>
    </Layout>
  );
}
