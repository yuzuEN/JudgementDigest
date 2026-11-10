import { ArrowRightIcon, DatabaseIcon, FileSearchIcon, ListChecksIcon, ScaleIcon, ShieldCheckIcon, TriangleAlertIcon } from "lucide-react";
import { useEffect, type ReactNode } from "react";
import { useLocation } from "react-router-dom";
import { cn } from "@/lib/utils";
import { LinkButton } from "../components/LinkButton";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { LAF_URL } from "../components/Common";
import { Layout, PAGE, SiteNav } from "../components/Layout";

const FAQ = [
  ["我的描述會被保存嗎？", "不會。結果只在你的瀏覽器裡顯示，重新整理就會清空；要留存可以下載成 PDF。我們只記錄你何時同意了哪一版資料使用說明。"],
  ["和直接問 AI 聊天機器人有什麼不同？", "聊天機器人可能編造不存在的判決。這裡的每一件相似判決都是真的、附字號；機率是從真實判決統計出來的。"],
  ["結果有多準？", "勝敗的推估在測試資料上明顯優於隨機猜測，但仍會出錯；金額只能給範圍。描述越完整，結果越可靠。"],
];

const GET = [
  { icon: FileSearchIcon, title: "相似的真實判決", text: "每一件都附字號，可以到司法院網站查證，不會是編造的判決。" },
  { icon: ScaleIcon, title: "可能的結果範圍", text: "民事：贏的機會有多大、大概能拿回多少錢。刑事：可能的罪名、法條、刑期範圍。" },
  { icon: ListChecksIcon, title: "準備的方向", text: "類似案件常用到哪些證據、對方常怎麼反駁，以及標好重點的判決導讀。" },
];

const HOW = [
  { title: "描述案情", text: "用自己的話寫下經過，回答幾個基本問題。" },
  { title: "確認與遮名", text: "補充細節，先看過遮掉姓名後要送出的內容。" },
  { title: "看參考結果", text: "可以下載成 PDF，帶去和律師或家人討論。" },
];

function SectionTitle({ id, children }: { id?: string; children: ReactNode }) {
  return <h2 id={id} className="text-center text-3xl font-bold tracking-tight">{children}</h2>;
}

export default function Home() {
  const { hash } = useLocation();
  // 從其他頁的導覽列點「常見問題」等回到首頁時，捲到那一段
  useEffect(() => {
    if (hash) document.getElementById(decodeURIComponent(hash.slice(1)))?.scrollIntoView?.();
  }, [hash]);

  return (
    <Layout nav={<SiteNav />}>
      <main>
        <section className="border-b bg-card">
          <div className={cn(PAGE, "flex flex-col items-center gap-6 py-20 text-center sm:py-24")}>
            <h1 className="text-4xl leading-tight font-bold tracking-tight text-balance sm:text-5xl">
              遇到法律糾紛，<br />先看看類似的案子法院怎麼判
            </h1>
            <p className="max-w-2xl text-lg text-pretty text-muted-foreground">
              用自己的話說說發生了什麼事，我們會從法院真正判過的案子裡，找出跟你最像的幾件，讓你知道這類案子通常會怎麼收場、可以先準備什麼。
            </p>
            <div className="flex flex-col items-center gap-3">
              <LinkButton size="lg" to="/start">
                開始描述案情<ArrowRightIcon data-icon="inline-end" />
              </LinkButton>
              <span className="text-sm text-muted-foreground">免註冊，5 分鐘免費查詢</span>
            </div>
          </div>
        </section>

        <div className={cn(PAGE, "flex flex-col gap-20 py-16")}>
          <section className="flex flex-col gap-8" aria-labelledby="get-title">
            <SectionTitle id="get-title">你會得到什麼</SectionTitle>
            <div className="grid gap-5 md:grid-cols-3">
              {GET.map(({ icon: Icon, title, text }) => (
                <Card key={title}>
                  <CardHeader className="gap-3">
                    <span className="flex size-10 items-center justify-center rounded-lg bg-accent text-accent-foreground"><Icon className="size-5" aria-hidden="true" /></span>
                    <CardTitle className="text-lg font-bold">{title}</CardTitle>
                    <CardDescription className="text-[15px] leading-relaxed">{text}</CardDescription>
                  </CardHeader>
                </Card>
              ))}
            </div>
          </section>

          <section id="how" className="flex scroll-mt-20 flex-col gap-8" aria-labelledby="how-title">
            <SectionTitle id="how-title">怎麼使用</SectionTitle>
            <ol className="grid gap-6 md:grid-cols-3">
              {HOW.map(({ title, text }, i) => (
                <li key={title} className="flex items-start gap-4">
                  <span className="flex size-10 flex-none items-center justify-center rounded-full bg-primary font-bold text-primary-foreground">{i + 1}</span>
                  <span className="flex flex-col gap-0.5"><strong className="text-base">{title}</strong><span className="text-sm text-muted-foreground">{text}</span></span>
                </li>
              ))}
            </ol>
            <div id="data" className="grid scroll-mt-20 gap-5 lg:grid-cols-3">
              <Card>
                <CardHeader className="gap-3">
                  <DatabaseIcon className="size-5 text-primary" aria-hidden="true" />
                  <CardTitle className="text-lg font-bold">資料來源</CardTitle>
                </CardHeader>
                <CardContent className="text-[15px] leading-relaxed text-muted-foreground">
                  司法院公開的全國地方法院判決。以規則切分段落、擷取事實與判決結果，建立結構化資料集；判決書中的人名在顯示時會自動遮掉，但可能有遺漏。
                </CardContent>
              </Card>
              <Card className="bg-warn text-warn-foreground ring-warn-border">
                <CardHeader className="gap-3">
                  <TriangleAlertIcon className="size-5 text-warn-title" aria-hidden="true" />
                  <CardTitle className="text-lg font-bold text-warn-title">這不是法律意見</CardTitle>
                </CardHeader>
                <CardContent className="text-[15px] leading-relaxed">
                  結果是統計參考，不預測你的案件一定會怎麼判。和解、撤回的案件沒有判決書，不在資料裡。重要決定請諮詢律師或<a href={LAF_URL}>法律扶助基金會</a>。
                </CardContent>
              </Card>
              <Card>
                <CardHeader className="gap-3">
                  <ShieldCheckIcon className="size-5 text-success" aria-hidden="true" />
                  <CardTitle className="text-lg font-bold">你的資料怎麼處理</CardTitle>
                </CardHeader>
                <CardContent className="text-[15px] leading-relaxed text-muted-foreground">
                  不上傳文件、不保存你的描述。送出前會遮名並讓你預覽；需要用到敏感個人資料時，會另外請你同意。
                </CardContent>
              </Card>
            </div>
          </section>

          <section id="faq" className="flex scroll-mt-20 flex-col gap-8" aria-labelledby="faq-title">
            <SectionTitle id="faq-title">常見問題</SectionTitle>
            <Card className="mx-auto w-full max-w-3xl py-0">
              <Accordion className="px-5">
                {FAQ.map(([q, a]) => (
                  <AccordionItem key={q} value={q}>
                    <AccordionTrigger className="py-4 text-base hover:no-underline">{q}</AccordionTrigger>
                    <AccordionContent className="pb-4 text-[15px] leading-relaxed text-muted-foreground">{a}</AccordionContent>
                  </AccordionItem>
                ))}
              </Accordion>
            </Card>
          </section>
        </div>
      </main>
    </Layout>
  );
}
