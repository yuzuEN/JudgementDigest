import { ArrowLeftIcon, DownloadIcon, PenLineIcon } from "lucide-react";
import { useEffect, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { cn } from "@/lib/utils";
import { LinkButton } from "./LinkButton";
import { Button } from "@/components/ui/button";
import { useIntake } from "../state";
import { MockBadge } from "./Common";
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

function ResultTab({ to, active, disabled, title, children }: { to: string; active: boolean; disabled: boolean; title: string; children: ReactNode }) {
  const base = "inline-flex h-9 items-center rounded-md px-4 text-sm font-medium no-underline transition-colors";
  if (disabled) return <span className={cn(base, "cursor-not-allowed text-muted-foreground/60")} aria-disabled="true" title={title}>{children}</span>;
  return (
    <Link to={to} aria-current={active ? "page" : undefined}
      className={cn(base, active ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground")}>
      {children}
    </Link>
  );
}

/** 民事、刑事結果頁共用的外框：分頁、標題、下載 PDF，以及只在列印時出現的報告抬頭。 */
export function ResultFrame({ active, title, lead, mock, maskedText, searchText, children }: {
  active: "civil" | "criminal";
  title: string;
  lead: ReactNode;
  mock: boolean;
  maskedText: string;
  searchText?: string;
  children: ReactNode;
}) {
  useOpenDetailsForPrint();
  const { intake } = useIntake();
  return (
    <Layout step={3}>
      <main className={cn(PAGE, "flex flex-col gap-6 py-8 pb-16")}>
        <div className="print-only">
          <h1 className="mb-1 text-xl font-bold">類案判決參考報告（{active === "civil" ? "民事" : "刑事"}）</h1>
          <p className="text-sm text-muted-foreground">產生時間：{new Date().toLocaleString("zh-TW")}／{BRAND} 刑事及民事類案判決參考平台／結果僅供參考，不是法律意見</p>
          {mock && <p><strong>本報告是示例資料：數字與判決都不是真的，請勿作為判斷依據。</strong></p>}
          <h2 className="mt-3 text-base font-bold">案情描述（已遮名）</h2>
          <p className="text-sm whitespace-pre-wrap">{maskedText}</p>
          {searchText && <>
            <h2 className="mt-3 text-base font-bold">用來搜尋相似判決的文字（已確認）</h2>
            <p className="text-sm whitespace-pre-wrap">{searchText}</p>
          </>}
        </div>

        <div className="flex flex-wrap items-end justify-between gap-4">
          <div className="flex flex-col gap-3">
            <nav aria-label="結果類型" className="no-print inline-flex w-fit gap-1 rounded-lg bg-muted p-1">
              <ResultTab to="/result/civil" active={active === "civil"} disabled={intake.caseType === "criminal"} title="這次選的是刑事">民事</ResultTab>
              <ResultTab to="/result/criminal" active={active === "criminal"} disabled={intake.caseType === "civil"} title="這次選的是民事">刑事</ResultTab>
            </nav>
            <h1 className="text-3xl font-bold tracking-tight">{title}</h1>
            <p className="text-muted-foreground">{lead}</p>
          </div>
          <div className="no-print flex flex-wrap items-center gap-3">
            <MockBadge show={mock} />
            <Button variant="outline" onClick={() => window.print()}><DownloadIcon data-icon="inline-start" />下載 PDF</Button>
          </div>
        </div>
        {children}
        <div className="no-print flex flex-wrap gap-3">
          <LinkButton variant="outline" to="/confirm"><ArrowLeftIcon data-icon="inline-start" />回上一步</LinkButton>
          <LinkButton variant="outline" to="/start"><PenLineIcon data-icon="inline-start" />修改描述</LinkButton>
        </div>
      </main>
    </Layout>
  );
}
