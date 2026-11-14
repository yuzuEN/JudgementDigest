import { ExternalLinkIcon } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { Card } from "@/components/ui/card";
import { JUDICIAL_URL, Layout, PAGE } from "../components/Layout";
import { LinkButton } from "../components/LinkButton";

// 改這頁時，要和實際做法一致：確認頁的「資料使用說明」（Confirm.tsx）、docs/部署.md 的「Log 與隱私」。
const OPENDATA_URL = "https://opendata.judicial.gov.tw/";
// 目前接的 LLM 廠商；換廠商（.env 的 JD_LLM_PROVIDER）時要一起改
const LLM_VENDOR = "Google Gemini";

function Block({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section id={id} aria-labelledby={`${id}-title`} className="flex scroll-mt-6 flex-col gap-3">
      <h2 id={`${id}-title`} className="text-[22px] leading-[1.45] font-extrabold sm:text-[26px]">{title}</h2>
      {children}
    </section>
  );
}

function Points({ items }: { items: ReactNode[] }) {
  return <ul className="m-0 flex list-disc flex-col gap-2 pl-5">{items.map((item, i) => <li key={i}>{item}</li>)}</ul>;
}

export default function Privacy() {
  return (
    <Layout scene={{ who: "explainer", line: "你輸入的案情怎麼處理、會傳給誰、結果從哪裡來，都寫在這一頁。" }}>
      <div className={cn(PAGE, "pt-8 pb-16")}>
        <article className="mx-auto flex max-w-[760px] flex-col gap-10">
          <header className="flex flex-col gap-2">
            <h1 className="text-[26px] leading-[1.4] font-extrabold sm:text-[32px]">隱私與資料使用</h1>
            <p className="text-lg leading-[1.8] text-muted-foreground">本服務由 JudgementDigest 專題團隊製作，用途是提供類案判決參考，不是法律意見。</p>
          </header>

          <Card className="gap-3 px-6">
            <h2 className="text-xl font-bold">重點</h2>
            <Points items={[
              <><strong>不保存你的描述。</strong>伺服器只在產生這次結果時使用，不寫進資料庫或紀錄檔。</>,
              <><strong>姓名在你的瀏覽器裡遮掉</strong>，原文和你加入的姓名不會傳到伺服器。</>,
              <><strong>只有你按下按鈕，才會傳給 AI 服務</strong>（目前是 {LLM_VENDOR}），傳的是遮名後的內容。</>,
            ]} />
          </Card>

          <Block id="input" title="你輸入的內容">
            <Points items={[
              "遮名在你的瀏覽器裡完成。送到伺服器的是遮名後的內容（包含你補充的回答）。",
              "你填的內容只暫存在這個瀏覽器分頁：重新整理還在，關掉分頁就清除；不會存在電腦上，也不會存到我們的伺服器。",
              "伺服器收到描述後，只用來產生這次的參考結果（預測與相似判決），不保存。",
              "病歷、醫療、健康檢查、基因、性生活、犯罪前科是法律特別保護的資料。描述裡有這些內容時，同樣只用來產生這次的結果、不保存。不想提供的話，刪掉這些描述就好，只是結果可能比較不準。",
            ]} />
          </Block>

          <Block id="ai" title="AI 服務">
            <Points items={[
              <>「補充細節」與「判決書寫法」兩個步驟可以請 AI 幫忙。只有在你按下「傳給 AI，開始提問」或「請 AI 整理敘述」時，遮名後的內容才會傳給 {LLM_VENDOR}。</>,
              <>我們使用的是 {LLM_VENDOR} 的付費 API，傳過去的內容不會被用來訓練或改善它的模型。</>,
              "不按這些按鈕也能完成查詢：追問會改用固定題目，相似判決用你原本的描述搜尋。",
              "為了控制費用，每個連線位址每小時、全站每天可以使用 AI 的次數有上限，超過時會自動改用固定題目。",
            ]} />
          </Block>

          <Block id="logs" title="伺服器紀錄">
            <Points items={[
              "伺服器會記錄每次連線的 IP 位址、時間、網址路徑與結果狀態（例如成功或失敗），用來防止濫用（每個 IP 的使用次數上限）和排除故障。",
              "紀錄不包含你輸入的描述，也不包含 AI 的回應內容；呼叫 AI 時只記用了多少字數（token）和花了幾秒。",
              "紀錄檔有大小上限，舊的紀錄會自動刪除。",
              "連線全程使用 HTTPS 加密。",
            ]} />
          </Block>

          <Block id="sources" title="結果的資料來源">
            <Points items={[
              <>民事判決來自<a href={JUDICIAL_URL} target="_blank" rel="noreferrer" className="inline-flex items-center gap-0.5">司法院裁判書查詢系統<ExternalLinkIcon className="size-4" aria-hidden="true" /></a>公開的全國地方法院判決（含簡易庭，2022 年 1 月至 2026 年 4 月）。</>,
              <>刑事判決來自<a href={OPENDATA_URL} target="_blank" rel="noreferrer" className="inline-flex items-center gap-0.5">司法院資料開放平臺<ExternalLinkIcon className="size-4" aria-hidden="true" /></a>的全國地方法院第一審判決（2016 至 2025 年）。</>,
              "預測結果由我們用這些判決訓練的模型產生，是過去判決的統計參考，不代表你的案件會有相同結果。",
            ]} />
          </Block>

          <div className="flex flex-wrap gap-3">
            <LinkButton size="lg" to="/start">開始查詢</LinkButton>
            <LinkButton variant="outline" size="lg" to="/guide" className="border-input text-foreground">說明與法律小知識</LinkButton>
          </div>
        </article>
      </div>
    </Layout>
  );
}
