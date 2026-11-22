import { ArrowRightIcon, ArrowUpIcon, CheckIcon, ChevronDownIcon, DatabaseIcon, ExternalLinkIcon, EyeOffIcon, FileTextIcon, LockIcon, ScaleIcon, ShieldAlertIcon, ShieldCheckIcon, SparklesIcon, UserRoundXIcon, type LucideIcon } from "lucide-react";
import { useEffect, type ReactNode } from "react";
import { useLocation } from "react-router-dom";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { OutcomeBar } from "../components/casey/OutcomeBar";
import { LAF_URL } from "../components/Common";
import { JUDICIAL_URL, Layout, PAGE } from "../components/Layout";
import { LinkButton } from "../components/LinkButton";

const CIVIL_GETS = ["相似判決裡，原告贏的比例", "可能判准的金額範圍", "相似的真實判決", "勝訴的案子通常拿出哪些證據", "對方常見的說法（抗辯）"];
const CRIMINAL_GETS = ["可能的罪名與法條", "刑期落在哪個範圍", "相似的真實判決"];

const CHAPTERS = [
  { n: "第一章", title: "描述案情", text: "選擇案件類型，描述事情經過，再填寫金額、對方身分和手上的證據。" },
  { n: "第二章", title: "確認內容", text: "檢查個資是否已遮蔽，再補充細節。也可以請 AI 將描述整理成判決書的寫法。" },
  { n: "第三章", title: "參考結果", text: "查看相似判決與統計結果，或下載 PDF，與律師、法扶或家人討論。" },
];

const PRIVACY: [LucideIcon, string][] = [
  [UserRoundXIcon, "免註冊、不記錄個資"], [EyeOffIcon, "提供個資遮名"],
  [ShieldAlertIcon, "敏感資料另行徵求同意"], [SparklesIcon, "提供 AI 改寫描述，增強搜尋結果"],
];

const FAQ = [
  ["要付費嗎？", "查詢免費，也不需要註冊。"],
  ["結果準不準？", "它告訴你「過去類似的案件」怎麼判，不是你這件會怎麼判。數字越極端或相似判決越少，越要保守看待。"],
  ["我分不清楚是民事還是刑事", "選「不確定」。結果頁上面是民事、下面是刑事，兩邊都可以看；被告了也可以選，再選「被告」就好。"],
  ["我的名字會被別人看到嗎？", "送出前會先遮掉姓名、身分證字號、電話、email 和地址，而且你可以先預覽。"],
  ["看完結果之後可以做什麼？", "可以下載 PDF，帶去給律師、法扶或家人討論。「說明與法律小知識」也整理了下一步可以怎麼做。"],
];

/** 首頁各段同一個底色；段與段之間只畫一條和內容同寬的分隔線（divider）。 */
function Section({ id, divider = true, children, className }: { id?: string; divider?: boolean; children: ReactNode; className?: string }) {
  return (
    <section id={id} className="scroll-mt-4">
      {divider && <div className={PAGE}><hr className="m-0 h-px border-0 bg-border" /></div>}
      <div className={cn(PAGE, "py-9 sm:py-14", className)}>{children}</div>
    </section>
  );
}

/** primary：首頁的重點段落（查詢流程、資料處理），標題放大一級。 */
function H2({ icon, children, id, primary = false }: { icon?: ReactNode; children: ReactNode; id?: string; primary?: boolean }) {
  return (
    <h2 id={id} className={cn("flex items-center gap-3 leading-[1.4] font-extrabold text-balance",
      primary ? "text-[26px] sm:text-[34px]" : "text-[20px] sm:text-[24px]")}>
      {icon}{children}
    </h2>
  );
}

function Checks({ items }: { items: string[] }) {
  return (
    <ul className="m-0 grid list-none gap-2 p-0">
      {items.map((t) => (
        <li key={t} className="flex items-start gap-3"><CheckIcon className="mt-1 size-5 flex-none text-primary" aria-hidden="true" />{t}</li>
      ))}
    </ul>
  );
}

function BackToTop() {
  const toTop = () => window.scrollTo({ top: 0, behavior: window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  return <Button size="lg" variant="outline" onClick={toTop} className="max-sm:w-full">回到最上方<ArrowUpIcon data-icon="inline-end" /></Button>;
}

/** 「查詢結果範例」：示例資料，用虛線框與「示例」標籤標示（首頁專用的米色 #F3EFE5）。 */
function SampleCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Card aria-label={`${title}（示例）`} className="gap-4 px-6.5 ring-0 border-2 border-dashed border-[#F3EFE5] dark:border-[#4A4536]">
      <div className="flex items-center justify-between gap-3">
        <p className="font-bold">{title}</p>
        <span className="rounded-full border-2 border-dashed border-[#F3EFE5] bg-[#F3EFE5] px-2.5 text-sm leading-[1.7] font-bold text-foreground dark:border-[#4A4536] dark:bg-[#4A4536]">示例</span>
      </div>
      {children}
    </Card>
  );
}

function CivilSample() {
  return (
    <SampleCard title="民事查詢結果範例">
      <p className="text-[15px] text-muted-foreground">民事交通事故，比對 30 件相似判決</p>
      <OutcomeBar counts={{ win: 15, partial: 10, lose: 5 }} legend={false} />
      <p className="text-[15px]">30 件裡：<b>全部勝訴 15 件、一部勝訴 10 件、敗訴 5 件</b></p>
      <hr className="m-0 h-px border-0 bg-border" />
      <p className="text-[15px] text-muted-foreground">如果判決是「一部勝訴」，可能判准的金額</p>
      <p className="text-[30px] leading-tight font-extrabold tabular-nums">約 2 萬～58 萬元</p>
      <p className="text-[15px] text-muted-foreground">10 件有 8 件落在這個範圍</p>
    </SampleCard>
  );
}

function CriminalSample() {
  return (
    <SampleCard title="刑事查詢結果範例">
      <p className="text-[15px] text-muted-foreground">刑事竊盜，比對 30 件相似判決</p>
      <p className="text-[15px] text-muted-foreground">可能的罪名與法條</p>
      <p className="text-xl font-extrabold">竊盜罪（刑法第 320 條第 1 項）</p>
      <hr className="m-0 h-px border-0 bg-border" />
      <p className="text-[15px] text-muted-foreground">相似判決的刑期</p>
      <p className="text-[30px] leading-tight font-extrabold tabular-nums">拘役～有期徒刑 6 個月</p>
      <p className="text-[15px] text-muted-foreground">10 件有 8 件落在這個範圍</p>
    </SampleCard>
  );
}

export default function Home() {
  const { hash } = useLocation();
  // 從其他頁的連結回到首頁的某一段時，捲到那一段
  useEffect(() => {
    if (hash) document.getElementById(decodeURIComponent(hash.slice(1)))?.scrollIntoView?.();
  }, [hash]);

  return (
    <Layout scene={{ who: "organizer", line: "我是 CasEY 的整理員，會陪你整理案情。準備好後，按「開始查詢」。" }}>
      <main>
        <Section divider={false} className="flex flex-col items-center gap-8">
          <h1 className="text-center text-[30px] leading-[1.3] font-extrabold text-balance sm:text-[44px]">遇到糾紛，<br />先看看類似的案件怎麼判</h1>
          <div className="grid w-full gap-4 md:grid-cols-2">
            <CivilSample />
            <CriminalSample />
          </div>
          <LinkButton size="lg" to="/start" className="max-sm:w-full">開始查詢<ArrowRightIcon data-icon="inline-end" /></LinkButton>
        </Section>

        <Section id="how" className="flex flex-col gap-6">
          <div className="flex flex-col gap-2">
            <H2 primary>查詢流程</H2>
            <p className="text-muted-foreground">流程分為三個階段，共七個步驟。填寫時可以返回前一步修改，已填的資料會保留。</p>
          </div>
          <ol className="m-0 grid list-none gap-4 p-0 md:grid-cols-3">
            {CHAPTERS.map((c) => (
              <li key={c.n}>
                <Card className="h-full gap-2 px-6.5">
                  <span className="w-fit rounded-full border-[1.5px] border-outcome-part bg-outcome-part-bg px-3 text-sm leading-[1.9] font-bold text-outcome-part-fg">{c.n}</span>
                  <h3 className="text-2xl font-extrabold">{c.title}</h3>
                  <p className="text-base leading-relaxed text-muted-foreground">{c.text}</p>
                </Card>
              </li>
            ))}
          </ol>
        </Section>

        <Section className="flex flex-col gap-6">
          <H2 primary icon={<LockIcon className="size-8 text-primary" aria-hidden="true" />}>你的資料怎麼處理</H2>
          <ul className="m-0 grid list-none gap-4 p-0 md:grid-cols-2">
            {PRIVACY.map(([Icon, title]) => (
              <li key={title} className="flex items-center gap-4 text-xl font-bold">
                <span className="grid size-12 flex-none place-items-center rounded-[12px] bg-secondary text-secondary-foreground"><Icon className="size-6" aria-hidden="true" /></span>
                {title}
              </li>
            ))}
          </ul>
        </Section>

        <Section className="flex flex-col gap-6">
          <H2>可以查到哪些資料</H2>
          <div className="grid gap-4 md:grid-cols-2">
            <Card className="gap-4 px-6.5">
              <h3 className="flex items-center gap-3 text-lg font-bold text-balance">
                <span className="grid size-11 place-items-center rounded-[11px] bg-primary text-primary-foreground"><FileTextIcon className="size-6" aria-hidden="true" /></span>
                民事：賠償、還款與契約糾紛
              </h3>
              <Checks items={CIVIL_GETS} />
            </Card>
            <Card className="gap-4 px-6.5">
              <h3 className="flex items-center gap-3 text-lg font-bold text-balance">
                <span className="grid size-11 place-items-center rounded-[11px] bg-primary text-primary-foreground"><ScaleIcon className="size-6" aria-hidden="true" /></span>
                刑事：犯罪案件的可能判決結果
              </h3>
              <Checks items={CRIMINAL_GETS} />
            </Card>
          </div>
        </Section>

        <Section id="data" className="grid items-start gap-6 md:grid-cols-2">
          <div className="flex flex-col gap-4 md:pt-6.5">
            <H2 icon={<DatabaseIcon className="size-6 text-primary" aria-hidden="true" />}>資料來源</H2>
            <p>來自臺灣司法院的公開判決資料。</p>
            <a href={JUDICIAL_URL} target="_blank" rel="noreferrer" className="inline-flex w-fit items-center gap-1 font-semibold">
              司法院裁判書查詢系統<ExternalLinkIcon className="size-4" aria-hidden="true" />
            </a>
          </div>
          <Card className="gap-4 px-6.5 ring-primary">
            <H2 icon={<ShieldCheckIcon className="size-6 text-primary" aria-hidden="true" />}>結果的使用限制</H2>
            <p>我們提供相似判決的統計整理，但無法取代律師的專業判斷。</p>
            <p>需要專業協助，可以洽詢
              <span className="whitespace-nowrap"><a href={LAF_URL} target="_blank" rel="noreferrer" className="inline-flex items-center gap-0.5">法律扶助基金會<ExternalLinkIcon className="size-4" aria-hidden="true" /></a>。</span>
            </p>
          </Card>
        </Section>

        <Section id="faq" className="flex max-w-[820px] flex-col gap-6">
          <H2>常見問題</H2>
          <div className="flex flex-col gap-2">
            {FAQ.map(([q, a], i) => (
              <details key={q} open={i === 0} className="group rounded-[12px] border bg-card">
                <summary className="flex min-h-12 cursor-pointer list-none items-center gap-2 px-4 py-2 font-bold [&::-webkit-details-marker]:hidden">
                  {q}
                  <ChevronDownIcon aria-hidden="true" className="ml-auto size-5 transition-transform group-open:rotate-180 motion-reduce:transition-none" />
                </summary>
                <p className="px-4 pt-1 pb-4 text-muted-foreground">{a}</p>
              </details>
            ))}
          </div>
          <div className="flex justify-center pt-2"><BackToTop /></div>
        </Section>
      </main>
    </Layout>
  );
}
