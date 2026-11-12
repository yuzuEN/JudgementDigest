import { ArrowRightIcon, CheckIcon, ChevronDownIcon, DatabaseIcon, ExternalLinkIcon, FileTextIcon, InfoIcon, LockIcon, ScaleIcon, ShieldCheckIcon } from "lucide-react";
import { useEffect, type ReactNode } from "react";
import { useLocation } from "react-router-dom";
import { cn } from "@/lib/utils";
import { Card } from "@/components/ui/card";
import { OutcomeBar } from "../components/casey/OutcomeBar";
import { LAF_URL } from "../components/Common";
import { Layout, PAGE } from "../components/Layout";
import { LinkButton } from "../components/LinkButton";

const CIVIL_GETS = ["相似判決裡，原告贏的比例", "可能判准的金額範圍", "相似的真實判決", "勝訴的案子通常拿出哪些證據", "對方常見的說法（抗辯）"];
const CRIMINAL_GETS = ["可能的罪名與法條", "刑期落在哪個範圍", "相似的真實判決"];

const CHAPTERS = [
  { n: "第一章", title: "描述案情", keys: "類型、案情、資料", text: "選案件類型，用白話說發生了什麼事，再補金額、對方和手上的證物。" },
  { n: "第二章", title: "確認內容", keys: "遮名、補充、改寫", text: "送出前先遮掉姓名、身分證字號、電話，可以補充細節，也可以看判決書寫法。" },
  { n: "第三章", title: "參考結果", keys: "", text: "解說員用分頁說明相似判決的結果。可以下載 PDF，帶去給律師、法扶或家人看。" },
];

const PRIVACY = [
  ["不用註冊、不保存", "不需要帳號，也不用留下聯絡方式。你填的內容只暫存在這個瀏覽器分頁，關掉分頁就清除，不會存到我們的伺服器。"],
  ["先預覽、先遮名", "姓名、身分證字號、電話、email、地址會在送出前遮掉。你看過、確認過才會送出。"],
  ["敏感資料傳給 AI 前要你同意", "如果描述裡有病歷、前科這類內容，要傳給 AI 服務前會先問你同意；不同意就不用 AI，結果照樣看得到。"],
  ["AI 只在你選擇時才用", "補充細節有兩種：固定題目不會傳給 AI；選「請 AI 幫我看還缺什麼」才會用到 AI。"],
];

const FAQ = [
  ["要付費嗎？", "不用。免註冊、免費。"],
  ["結果準不準？", "它告訴你「過去類似的案件」怎麼判，不是你這件會怎麼判。數字越極端或相似判決越少，越要保守看待。"],
  ["我分不清楚是民事還是刑事", "選「不確定」。結果頁會有民事、刑事兩個分頁，你可以都看。"],
  ["我的名字會被別人看到嗎？", "送出前會先遮掉姓名、身分證字號、電話、email 和地址，而且你可以先預覽。"],
  ["看完結果之後可以做什麼？", "可以下載 PDF，帶去給律師、法扶或家人討論。「說明與法律小知識」也整理了下一步可以怎麼做。"],
];

function Section({ id, alt, children, className }: { id?: string; alt?: boolean; children: ReactNode; className?: string }) {
  return (
    <section id={id} className={cn("scroll-mt-4 py-9 sm:py-14", alt && "border-y bg-muted")}>
      <div className={cn(PAGE, className)}>{children}</div>
    </section>
  );
}

function H2({ icon, children, id }: { icon?: ReactNode; children: ReactNode; id?: string }) {
  return (
    <h2 id={id} className="flex items-center gap-3 text-[22px] leading-[1.45] font-extrabold text-balance sm:text-[26px]">
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

function StartButton({ center = false }: { center?: boolean }) {
  return (
    <div className={cn("flex flex-col gap-2", center ? "items-center text-center max-sm:w-full" : "items-start")}>
      <LinkButton size="lg" to="/start" className="max-sm:w-full">開始查詢<ArrowRightIcon data-icon="inline-end" /></LinkButton>
      <p className="text-[15px] text-muted-foreground">免註冊，5 分鐘免費查詢</p>
    </div>
  );
}

/** 「結果大概長這樣」：示例資料，用紫灰色虛線框標示。 */
function SampleCard() {
  return (
    <Card aria-label="結果預覽（示例）" className="gap-4 px-6.5 ring-0 border-[1.5px] border-dashed border-sample-line">
      <div className="flex items-center justify-between gap-3">
        <p className="font-bold">結果大概長這樣</p>
        <span className="rounded-full border-[1.5px] border-dashed border-sample-line bg-sample px-2.5 text-sm leading-[1.7] font-bold text-sample-fg">示例</span>
      </div>
      <p className="text-[15px] text-muted-foreground">民事 · 交通事故 · 比對了 30 件相似判決</p>
      <OutcomeBar counts={{ win: 0, partial: 30, lose: 0 }} legend={false} />
      <p className="text-[15px]">30 件裡：<b>全部勝訴 0 件、一部勝訴 30 件、敗訴 0 件</b></p>
      <hr className="m-0 h-px border-0 bg-border" />
      <p className="text-[15px] text-muted-foreground">如果判決是「一部勝訴」，可能判准的金額</p>
      <p className="text-[30px] leading-tight font-extrabold tabular-nums">約 2 萬～58 萬元</p>
      <p className="text-[15px] text-muted-foreground">10 件約有 8 件落在這個範圍。範圍很寬，請當作粗略參考。</p>
    </Card>
  );
}

export default function Home() {
  const { hash } = useLocation();
  // 從其他頁的連結回到首頁的某一段時，捲到那一段
  useEffect(() => {
    if (hash) document.getElementById(decodeURIComponent(hash.slice(1)))?.scrollIntoView?.();
  }, [hash]);

  return (
    <Layout scene={{ who: "organizer", note: true, line: "你好，我是 CasEY 的整理員。遇到糾紛，先看看類似的案件通常怎麼判。我會一關一關帶你把事情整理好，再由解說員告訴你過去的判決怎麼說。" }}>
      <main>
        <Section className="grid items-center gap-12 md:grid-cols-[minmax(0,1.15fr)_minmax(0,.85fr)]">
          <div className="flex flex-col gap-6">
            <p className="text-[15px] font-bold tracking-[.04em] text-secondary-foreground">免註冊 · 免費 · 用真實判決回答</p>
            <h1 className="text-[30px] leading-[1.3] font-extrabold text-balance sm:text-[44px]">遇到糾紛，先看看<br />類似的案件通常怎麼判</h1>
            <p className="text-lg leading-[1.8] text-muted-foreground">用白話描述你遇到的事，CasEY 從全國地方法院的真實判決裡，找出情況相近的案件，讓你知道過去大多是怎麼收場的。</p>
            <StartButton />
            <p className="flex max-w-[520px] items-start gap-1.5 text-[15px] text-muted-foreground">
              <InfoIcon className="mt-1 size-4 flex-none" aria-hidden="true" />結果是統計上的參考，不是法律意見，也不是對你案子的預測。
            </p>
          </div>
          <SampleCard />
        </Section>

        <Section alt className="flex flex-col gap-6">
          <div className="flex flex-col gap-2">
            <H2>你會得到什麼</H2>
            <p className="text-muted-foreground">依案件類型，給你不同的參考資料。每一項都附上真實判決，可以點進去看。</p>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <Card className="gap-4 px-6.5">
              <h3 className="flex items-center gap-3 text-xl font-bold">
                <span className="grid size-11 place-items-center rounded-[11px] bg-primary text-primary-foreground"><FileTextIcon className="size-6" aria-hidden="true" /></span>
                民事：要錢、還錢、履行契約
              </h3>
              <Checks items={CIVIL_GETS} />
            </Card>
            <Card className="gap-4 px-6.5">
              <h3 className="flex items-center gap-3 text-xl font-bold">
                <span className="grid size-11 place-items-center rounded-[11px] bg-primary text-primary-foreground"><ScaleIcon className="size-6" aria-hidden="true" /></span>
                刑事：被調查，或想告對方
              </h3>
              <Checks items={CRIMINAL_GETS} />
              <p className="text-[15px] text-muted-foreground">分不清楚是民事還是刑事？選「不確定」，兩邊都幫你看。</p>
            </Card>
          </div>
        </Section>

        <Section id="how" className="flex flex-col gap-6">
          <div className="flex flex-col gap-2">
            <H2>怎麼使用：三章、七關</H2>
            <p className="text-muted-foreground">一次只做一件事。每一關都看得到進度，可以隨時回上一關，資料會保留。</p>
          </div>
          <ol className="m-0 grid list-none gap-4 p-0 md:grid-cols-3">
            {CHAPTERS.map((c) => (
              <li key={c.n}>
                <Card className="h-full gap-2 px-6.5">
                  <span className="w-fit rounded-full border-[1.5px] border-outcome-part bg-outcome-part-bg px-3 text-sm leading-[1.9] font-bold text-outcome-part-fg">{c.n}</span>
                  <h3 className="text-xl font-bold">{c.title}</h3>
                  <p className="text-[15px] text-muted-foreground">{c.keys && <b>{c.keys}。</b>}{c.text}</p>
                </Card>
              </li>
            ))}
          </ol>
        </Section>

        <Section id="data" alt className="grid items-start gap-6 md:grid-cols-2">
          <div className="flex flex-col gap-4">
            <H2 icon={<DatabaseIcon className="size-7 text-primary" aria-hidden="true" />}>資料來源</H2>
            <p>全國地方法院公開的真實判決。我們把每一件判決的案由、結果、金額、證據與雙方說法整理起來，再找出和你的情況相近的案件。</p>
            <p className="text-[15px] text-muted-foreground">不起訴、撤回，或和解後沒有判決的案件，不在資料裡，所以統計不代表所有紛爭的結果。</p>
          </div>
          <Card className="gap-4 px-6.5 ring-primary">
            <H2 icon={<ShieldCheckIcon className="size-7 text-primary" aria-hidden="true" />}>這不是法律意見</H2>
            <p>結果是過去判決的統計整理，不是對你案子的預測，也不能取代律師。每個案子的細節都不一樣。</p>
            <p>需要專業協助，可以洽詢
              <a href={LAF_URL} target="_blank" rel="noreferrer" className="inline-flex items-center gap-0.5">法律扶助基金會<ExternalLinkIcon className="size-4" aria-hidden="true" /></a>。
            </p>
          </Card>
        </Section>

        <Section className="flex flex-col gap-6">
          <H2 icon={<LockIcon className="size-7 text-primary" aria-hidden="true" />}>你的資料怎麼處理</H2>
          <div className="grid gap-4 md:grid-cols-2">
            {PRIVACY.map(([title, text]) => (
              <div key={title} className="flex flex-col gap-2">
                <h3 className="text-xl font-bold">{title}</h3>
                <p className="text-[15px] text-muted-foreground">{text}</p>
              </div>
            ))}
          </div>
        </Section>

        <Section id="faq" alt className="flex max-w-[820px] flex-col gap-6">
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
          <div className="flex justify-center pt-2"><StartButton center /></div>
        </Section>
      </main>
    </Layout>
  );
}
