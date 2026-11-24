import { ArrowLeftIcon, DownloadIcon, PencilIcon } from "lucide-react";
import { useEffect, type ReactNode } from "react";
import { cn } from "@/lib/utils";
import { usePhone } from "@/lib/usePhone";
import { Button } from "@/components/ui/button";
import { PrintNotice } from "./casey/DisclaimerFooter";
import { PhoneCollapse } from "./casey/PhoneCollapse";
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

/**
 * 下載 PDF：開瀏覽器的列印，整頁（民事、刑事都在時兩者都印）存成 PDF。
 * 電腦版放在分頁列最右邊；手機版是標題旁的圖示按鈕（icon）。
 */
export function PdfButton({ icon = false }: { icon?: boolean }) {
  if (icon) {
    return (
      <Button variant="outline" size="icon" aria-label="下載 PDF" title="下載 PDF" className="no-print size-11 flex-none" onClick={() => window.print()}>
        <DownloadIcon aria-hidden="true" />
      </Button>
    );
  }
  return <Button variant="outline" className="no-print" onClick={() => window.print()}><DownloadIcon data-icon="inline-start" />下載 PDF</Button>;
}

/**
 * 結果的標題與說明。標題不換行（太長時以刪節號結尾，完整文字放在 title），
 * 只有民事或只有刑事時是 h1；「不確定」兩者都放時各是 h2，頁面的 h1 在外框。
 */
export function ResultHeading({ title, lead, level = 1, id, action }: {
  title: string; lead: ReactNode; level?: 1 | 2; id?: string;
  /** 只在手機上顯示，放在標題右邊（下載 PDF 的圖示按鈕）；電腦版的放在分頁列 */
  action?: ReactNode;
}) {
  const H = level === 1 ? "h1" : "h2";
  const phone = usePhone();
  const heading = <H title={title} className="wrap-anywhere text-balance sm:truncate text-display leading-[1.4] font-extrabold sm:text-[32px]">{title}</H>;
  return (
    <div id={id} className="flex min-w-0 scroll-mt-4 flex-col gap-2 phone:gap-1">
      {phone && action ? <div className="flex items-start justify-between gap-3">{heading}{action}</div> : heading}
      <p className="text-lg leading-[1.8] phone:leading-relaxed text-muted-foreground">{lead}</p>
    </div>
  );
}

/** 結果頁解說員的話：民事、刑事、每個分頁都一樣。 */
export const RESULT_LINE = "你可以參考模型給出的結果，也可以在相似判決中查找前10件最相似的判決書資訊，並參考導讀內容。";

/**
 * 民事、刑事結果頁共用的外框：解說員、示例資料標示、回上一步、這次比對用的描述，
 * 以及只在列印時出現的報告抬頭與每頁頁尾。標題與下載 PDF 由裡面的結果區塊自己放（ResultHeading、PdfButton）。
 */
export function ResultFrame({ label, mock, maskedText, searchText, criminalText, notice, children }: {
  label: string;
  mock: boolean;
  maskedText: string;
  searchText?: string;
  /** 「不確定」時刑事用的文字（刑事寫法的整理，或對方的主張）；和民事用的一樣就不另外列 */
  criminalText?: string;
  notice: ReactNode[];
  children: ReactNode;
}) {
  useOpenDetailsForPrint();
  const civilText = searchText || maskedText;
  const separate = criminalText !== undefined && criminalText.trim() !== "" && criminalText !== civilText;
  const prefix = separate ? "民事" : "這次";
  return (
    <Layout stage={7} scene={{ who: "explainer", line: RESULT_LINE }}>
      {mock && <div className={cn(PAGE, "no-print pt-5 phone:pt-3")}><SampleBanner /></div>}
      <main className={cn(PAGE, "flex flex-col gap-6 pt-7 pb-14 phone:gap-4 phone:pt-4 phone:pb-8")}>
        <div className="print-only">
          <h1 className="mb-1 text-xl font-bold">類案判決參考報告（{label}）</h1>
          <p className="text-sm">產生時間：{new Date().toLocaleString("zh-TW")}／{BRAND} 類案判決參考／結果僅供參考，不是法律意見</p>
          {mock && <p className="font-bold">本報告是示例資料：數字與判決都不是真的，請勿作為判斷依據。</p>}
          <h2 className="mt-3 text-base font-bold">案情描述（已遮名）</h2>
          <p className="text-sm whitespace-pre-wrap wrap-anywhere">{maskedText}</p>
          {searchText && <>
            <h2 className="mt-3 text-base font-bold">{separate ? "民事用來比對的整理文字（已確認）" : "用來比對的整理文字（已確認）"}</h2>
            <p className="text-sm whitespace-pre-wrap wrap-anywhere">{searchText}</p>
          </>}
          {separate && <>
            <h2 className="mt-3 text-base font-bold">刑事用來推估的文字</h2>
            <p className="text-sm whitespace-pre-wrap wrap-anywhere">{criminalText}</p>
          </>}
        </div>

        <div className="flex flex-col gap-4">
          <div className="no-print flex flex-wrap gap-2.5">
            <LinkButton variant="outline" to="/confirm?stage=6" className="border-input text-foreground"><ArrowLeftIcon data-icon="inline-start" />回上一步</LinkButton>
            <LinkButton variant="outline" to="/start?stage=2" className="border-input text-foreground"><PencilIcon data-icon="inline-start" />修改描述</LinkButton>
          </div>
        </div>
        {/* 這次比對實際用的描述（整理後的寫法，或遮名後的原文）；列印版的抬頭已經有，這裡只在畫面上顯示 */}
        {/* 手機上兩段描述都收起來，只留一行標題 */}
        <section aria-labelledby="used-text-title" className="no-print flex flex-col gap-6 phone:gap-3">
          <div className="flex w-full flex-col gap-2 rounded-[16px] border-2 border-dashed border-primary bg-card px-5 py-4 text-left phone:px-4 phone:py-1">
            <PhoneCollapse label={`${prefix}比對用的描述${searchText ? "（整理後的寫法）" : ""}`} className="pb-3"
              heading={(c) => <h2 id="used-text-title" className="text-hint font-bold text-secondary-foreground">{c}</h2>}>
              <p className="leading-loose phone:leading-relaxed whitespace-pre-wrap wrap-anywhere">{civilText}</p>
            </PhoneCollapse>
          </div>
          {separate && (
            <div className="flex w-full flex-col gap-2 rounded-[16px] border-2 border-dashed border-primary bg-card px-5 py-4 text-left phone:px-4 phone:py-1">
              <PhoneCollapse label="刑事推估用的描述" className="pb-3"
                heading={(c) => <h3 className="text-hint font-bold text-secondary-foreground">{c}</h3>}>
                <p className="leading-loose phone:leading-relaxed whitespace-pre-wrap wrap-anywhere">{criminalText}</p>
              </PhoneCollapse>
            </div>
          )}
          <hr className="m-0 h-px border-0 bg-border" />
        </section>
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
