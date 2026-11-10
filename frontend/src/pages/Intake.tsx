import { ArrowRightIcon, CheckIcon, InfoIcon } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Combobox, ComboboxChip, ComboboxChips, ComboboxChipsInput, ComboboxCollection, ComboboxContent, ComboboxEmpty,
  ComboboxGroup, ComboboxItem, ComboboxLabel, ComboboxList, ComboboxValue, useComboboxAnchor,
} from "@/components/ui/combobox";
import { Field, FieldContent, FieldDescription, FieldLabel, FieldLegend, FieldSet, FieldTitle } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { api } from "../api/client";
import type { CaseType, DefendantType, Options } from "../api/types";
import { CARD_TITLE, ErrorBox, PageTitle } from "../components/Common";
import { Layout, PAGE } from "../components/Layout";
import { parseAmount } from "../format";
import { DISPUTE_GROUPS } from "../knowledge";
import { useIntake, type Intake as IntakeState } from "../state";

export const SHORT_TEXT = 150;
const RECOMMENDED = 300;

const CASE_TYPES: { id: CaseType; label: string; hint: string }[] = [
  { id: "civil", label: "民事", hint: "要求賠償、還錢、履行契約" },
  { id: "criminal", label: "刑事", hint: "被警察、檢察官調查，或想告對方犯罪" },
  { id: "unsure", label: "不確定", hint: "由系統幫你判斷，兩種都查" },
];

/** 選了類型之後，告訴使用者會得到什麼。 */
const YOU_GET: Record<CaseType, string[]> = {
  civil: [
    "相似的真實判決（附字號，可自行查證）",
    "類似案件原告贏的比例，以及可能判准的金額範圍",
    "類似案件常用到的證據、對方常見的說法",
    "判決導讀：標出爭點、證據、法院判斷",
  ],
  criminal: [
    "相似的真實判決（附字號，可自行查證）",
    "可能涉及的罪名與法條",
    "相似案件的刑期範圍",
    "判決導讀：標出爭點、證據、法院判斷",
  ],
  unsure: [
    "民事、刑事兩種結果都會查，分開顯示",
    "相似的真實判決（附字號，可自行查證）",
    "民事：原告贏的比例、可能判准的金額範圍",
    "刑事：可能的罪名、法條、刑期範圍",
  ],
};

const DEFENDANT_TYPES: { value: DefendantType | null; label: string }[] = [
  { value: null, label: "不確定" },
  { value: "person", label: "個人" },
  { value: "company", label: "公司、行號" },
  { value: "government", label: "政府機關、學校、醫院" },
];

/** 刑事沒有基本問題，只問手上有哪些證據；會加在描述後面一起送出。 */
const CRIMINAL_EVIDENCE = [
  "驗傷單、診斷證明",
  "監視器、行車紀錄器畫面",
  "照片、影片",
  "LINE、簡訊、錄音",
  "報案紀錄（報案三聯單）",
  "證人",
  "轉帳、匯款紀錄",
  "對方承認的對話或文字",
];

type MidGroup = { value: string; items: string[] };

function toggle(list: string[], key: string) {
  return list.includes(key) ? list.filter((k) => k !== key) : [...list, key];
}

function EvidenceChecks({ items, checked, onToggle }: { items: { key: string; label: string }[]; checked: string[]; onToggle: (key: string) => void }) {
  return (
    <div className="grid gap-x-6 gap-y-1 sm:grid-cols-2">
      {items.map((e) => (
        <Label key={e.key} className="flex min-h-11 cursor-pointer items-center gap-3 text-base font-normal">
          <Checkbox checked={checked.includes(e.key)} onCheckedChange={() => onToggle(e.key)} className="size-5" />
          {e.label}
        </Label>
      ))}
    </div>
  );
}

export default function Intake() {
  const { intake, update } = useIntake();
  const navigate = useNavigate();
  const [options, setOptions] = useState<Options | null>(null);
  const [error, setError] = useState("");

  const load = () => {
    setError("");
    api.options().then(setOptions).catch((e: Error) => setError(e.message));
  };
  useEffect(load, []);

  const len = intake.text.trim().length;
  const lenHint = len === 0 ? `建議 ${RECOMMENDED} 字以上` : len < SHORT_TEXT ? "再多寫一些，結果會比較準" : "長度足夠";
  const lenClass = len === 0 ? "text-muted-foreground" : len < SHORT_TEXT ? "font-medium text-caution" : "font-medium text-success";
  const showCivil = intake.caseType !== "criminal";
  const amountInvalid = intake.claimedAmount.trim() !== "" && parseAmount(intake.claimedAmount) === null;

  return (
    <Layout step={1}>
      <main className={cn(PAGE, "py-8 pb-16")}>
        <form onSubmit={(e) => { e.preventDefault(); navigate("/confirm"); }} className="flex flex-col gap-6">
          <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_340px] lg:gap-8">
            <div className="flex min-w-0 flex-col gap-6">
              <PageTitle title="描述你遇到的糾紛" lead="我們會從全國地方法院的真實判決中，找出和你的情況相似的案件，告訴你這類案件打到判決時通常怎麼判。" />
              <CaseTypeCard intake={intake} onChange={(caseType) => update({ caseType })} />

              <Card>
                <CardHeader>
                  <CardTitle className={CARD_TITLE}><Label htmlFor="facts" className="text-lg font-bold">發生了什麼事？</Label></CardTitle>
                  <CardDescription id="facts-help" className="text-[15px]">
                    依時間順序寫下經過、你受到的損害、你想要求什麼。不用寫法律用語，但請盡量完整：描述太短時，參考結果會比較不準。
                  </CardDescription>
                </CardHeader>
                <CardContent className="flex flex-col gap-3">
                  <Textarea id="facts" rows={9} className="min-h-56 resize-y text-base" aria-describedby="facts-help facts-count" value={intake.text}
                    onChange={(e) => update({ text: e.target.value })}
                    placeholder="例如：去年三月我騎機車在路口被一輛右轉的汽車撞到，右手骨折住院五天，之後復健三個月沒辦法工作……" />
                  <div id="facts-count" className="flex flex-wrap justify-between gap-2 text-sm">
                    <span className="text-muted-foreground">已輸入 {len} 字</span>
                    <span className={lenClass}>{lenHint}</span>
                  </div>
                  <p className="text-sm text-muted-foreground">有起訴書或起訴狀？可以直接把「犯罪事實」或「事實及理由」那一段貼上來。</p>
                </CardContent>
              </Card>

              {showCivil && (
                <Card aria-labelledby="civil-title">
                  <CardHeader>
                    <CardTitle id="civil-title" className={CARD_TITLE}>幾個基本問題</CardTitle>
                    <CardDescription className="text-[15px]">這些資料會和你的描述一起用來推估結果。不確定的可以跳過。</CardDescription>
                  </CardHeader>
                  <CardContent className="flex flex-col gap-6">
                    {error && <ErrorBox message={`選項載入失敗：${error}`} onRetry={load} />}
                    <div className="grid gap-5 sm:grid-cols-2">
                      <DisputeTypeField options={options} mids={intake.mids} onChange={(mids) => update({ mids })} />
                      <Field>
                        <FieldLabel htmlFor="amount" className="text-base">想請求的金額（新臺幣）</FieldLabel>
                        <Input id="amount" type="text" inputMode="numeric" placeholder="例如 500000 或 50萬" value={intake.claimedAmount}
                          aria-invalid={amountInvalid} onChange={(e) => update({ claimedAmount: e.target.value })} />
                        {amountInvalid && <FieldDescription className="font-medium text-caution">看不懂這個金額，請只填數字，例如 500000 或 50萬</FieldDescription>}
                      </Field>
                      <Field>
                        <FieldLabel htmlFor="defendant" className="text-base">對方是</FieldLabel>
                        <Select items={DEFENDANT_TYPES} value={intake.defendantType || null}
                          onValueChange={(v) => update({ defendantType: (v ?? "") as DefendantType | "" })}>
                          <SelectTrigger id="defendant" className="w-full"><SelectValue /></SelectTrigger>
                          <SelectContent>
                            {DEFENDANT_TYPES.map((d) => <SelectItem key={d.label} value={d.value}>{d.label}</SelectItem>)}
                          </SelectContent>
                        </Select>
                      </Field>
                      <CourtField courts={options?.courts ?? []} value={intake.court} onChange={(court) => update({ court })} />
                    </div>
                    <FieldSet>
                      <FieldLegend className="text-base">你有請律師嗎？</FieldLegend>
                      <RadioGroup className="flex flex-wrap gap-6" value={intake.lawyer || null}
                        onValueChange={(v) => update({ lawyer: v as IntakeState["lawyer"] })}>
                        {([["yes", "有"], ["no", "還沒有"]] as const).map(([v, label]) => (
                          <Label key={v} className="flex min-h-11 cursor-pointer items-center gap-2.5 text-base font-normal">
                            <RadioGroupItem value={v} className="size-5" />{label}
                          </Label>
                        ))}
                      </RadioGroup>
                    </FieldSet>
                    <FieldSet>
                      <FieldLegend className="text-base">你手上有哪些證據？</FieldLegend>
                      <FieldDescription>只要勾「有沒有」，不用上傳任何文件。</FieldDescription>
                      <EvidenceChecks items={options?.evidence ?? []} checked={intake.evidence}
                        onToggle={(key) => update({ evidence: toggle(intake.evidence, key) })} />
                    </FieldSet>
                  </CardContent>
                </Card>
              )}

              {intake.caseType === "criminal" && (
                <Card aria-labelledby="crim-ev-title">
                  <CardHeader>
                    <CardTitle id="crim-ev-title" className={CARD_TITLE}>你手上有哪些證據？</CardTitle>
                    <CardDescription className="text-[15px]">只要勾「有沒有」，不用上傳任何文件。勾選的項目會加在描述後面一起送出。</CardDescription>
                  </CardHeader>
                  <CardContent>
                    <EvidenceChecks items={CRIMINAL_EVIDENCE.map((label) => ({ key: label, label }))} checked={intake.criminalEvidence}
                      onToggle={(key) => update({ criminalEvidence: toggle(intake.criminalEvidence, key) })} />
                  </CardContent>
                </Card>
              )}

              {intake.caseType === "unsure" && (
                <Card>
                  <CardHeader>
                    <CardTitle className={CARD_TITLE}>刑事案件</CardTitle>
                    <CardDescription className="text-[15px]">請盡量寫出行為的經過（時間、地點、做了什麼、造成什麼結果）。系統會以這段事實推估可能的罪名、法條與刑期範圍。</CardDescription>
                  </CardHeader>
                </Card>
              )}
            </div>

            <SideHelp intake={intake} />
          </div>

          <div className="flex flex-wrap items-center gap-4">
            <Button type="submit" size="lg" disabled={len === 0 || amountInvalid}>下一步：確認內容<ArrowRightIcon data-icon="inline-end" /></Button>
            <span className="text-sm text-muted-foreground">送出前會先讓你預覽，並遮掉姓名、身分證字號、電話。</span>
          </div>
        </form>
      </main>
    </Layout>
  );
}

function CaseTypeCard({ intake, onChange }: { intake: IntakeState; onChange: (t: CaseType) => void }) {
  return (
    <Card aria-labelledby="type-title">
      <CardHeader><CardTitle id="type-title" className={CARD_TITLE}>這是哪一類的事情？</CardTitle></CardHeader>
      <CardContent className="flex flex-col gap-5">
        <RadioGroup aria-labelledby="type-title" className="grid gap-3 sm:grid-cols-3" value={intake.caseType} onValueChange={(v) => onChange(v as CaseType)}>
          {CASE_TYPES.map((t) => (
            <FieldLabel key={t.id} htmlFor={`type-${t.id}`} className="cursor-pointer has-data-checked:border-primary has-data-checked:bg-accent has-data-checked:ring-1 has-data-checked:ring-primary has-focus-visible:ring-3 has-focus-visible:ring-ring/50">
              <Field orientation="horizontal">
                <FieldContent>
                  <FieldTitle className="text-base font-bold">{t.label}</FieldTitle>
                  <FieldDescription className="text-[13px]">{t.hint}</FieldDescription>
                </FieldContent>
                {/* 選取狀態只用外框表示；圓點留給螢幕報讀與鍵盤操作，畫面上不顯示 */}
                <RadioGroupItem value={t.id} id={`type-${t.id}`} aria-label={t.label} className="sr-only" />
              </Field>
            </FieldLabel>
          ))}
        </RadioGroup>
        <Separator />
        <div aria-live="polite" className="flex flex-col gap-2">
          <h3 className="text-sm font-semibold text-muted-foreground">選「{CASE_TYPES.find((t) => t.id === intake.caseType)!.label}」，你會得到</h3>
          <ul className="grid gap-2 sm:grid-cols-2">
            {YOU_GET[intake.caseType].map((item) => (
              <li key={item} className="flex items-start gap-2 text-[15px]">
                <CheckIcon className="mt-1 size-4 flex-none text-primary" aria-hidden="true" />{item}
              </li>
            ))}
          </ul>
        </div>
      </CardContent>
    </Card>
  );
}

/** 糾紛類型：可以多選，清單太長時可以捲動，也可以打字篩選。 */
function DisputeTypeField({ options, mids, onChange }: { options: Options | null; mids: string[]; onChange: (mids: string[]) => void }) {
  const anchor = useComboboxAnchor();
  const groups: MidGroup[] = (options?.mid_groups ?? []).map((g) => ({ value: g.category, items: g.mids.map((m) => m.value) }));
  const showHelp = () => document.getElementById("dispute-help")?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  return (
    <Field className="sm:col-span-2">
      <span className="flex items-center gap-1.5">
        <FieldLabel htmlFor="mid" className="text-base">糾紛類型</FieldLabel>
        <Tooltip>
          <TooltipTrigger render={<Button type="button" variant="ghost" size="icon-xs" className="text-primary" aria-label="糾紛類型說明" onClick={showHelp} />}>
            <InfoIcon className="size-4" />
          </TooltipTrigger>
          <TooltipContent>各類型的說明在旁邊，可以多選</TooltipContent>
        </Tooltip>
      </span>
      <Combobox items={groups} multiple value={mids} onValueChange={(v) => onChange(v as string[])}>
        <ComboboxChips ref={anchor} className="w-full">
          <ComboboxValue>
            {(values: string[]) => (
              <>
                {values.map((v) => <ComboboxChip key={v} aria-label={v}>{v}</ComboboxChip>)}
                <ComboboxChipsInput id="mid" placeholder={values.length ? "" : "不確定（可以多選，也可以打字找）"} />
              </>
            )}
          </ComboboxValue>
        </ComboboxChips>
        <ComboboxContent anchor={anchor}>
          <ComboboxEmpty>找不到這個類型</ComboboxEmpty>
          <ComboboxList>
            {(group: MidGroup) => (
              <ComboboxGroup key={group.value} items={group.items}>
                <ComboboxLabel>{group.value}</ComboboxLabel>
                <ComboboxCollection>
                  {(item: string) => <ComboboxItem key={item} value={item}>{item}</ComboboxItem>}
                </ComboboxCollection>
              </ComboboxGroup>
            )}
          </ComboboxList>
        </ComboboxContent>
      </Combobox>
      <FieldDescription>不確定可以留空；選好幾類時，系統會從你的描述判斷最接近的一類。</FieldDescription>
    </Field>
  );
}

function CourtField({ courts, value, onChange }: { courts: string[]; value: string; onChange: (court: string) => void }) {
  const items = [{ value: null as string | null, label: "還不知道" }, ...courts.map((c) => ({ value: c as string | null, label: `${c}地方法院` }))];
  return (
    <Field>
      <FieldLabel htmlFor="court" className="text-base">打算在哪個法院（可不選）</FieldLabel>
      <Select items={items} value={value || null} onValueChange={(v) => onChange((v as string | null) ?? "")}>
        <SelectTrigger id="court" className="w-full"><SelectValue /></SelectTrigger>
        <SelectContent>
          {items.map((c) => <SelectItem key={c.label} value={c.value}>{c.label}</SelectItem>)}
        </SelectContent>
      </Select>
    </Field>
  );
}

/** 右側說明：民事顯示糾紛類型說明，選到的類型會標出來並捲到那裡。高度和左邊齊平，超出可以捲動。 */
function SideHelp({ intake }: { intake: IntakeState }) {
  const viewport = useRef<HTMLDivElement>(null);
  const last = intake.mids[intake.mids.length - 1];

  useEffect(() => {
    const root = viewport.current?.closest<HTMLElement>("[data-slot=scroll-area]")?.querySelector<HTMLElement>("[data-slot=scroll-area-viewport]");
    const target = last ? document.getElementById(`dt-${last}`) : null;
    if (!root || !target?.getBoundingClientRect) return;
    const top = target.getBoundingClientRect().top - root.getBoundingClientRect().top + root.scrollTop - 8;
    root.scrollTo?.({ top, behavior: "smooth" });
  }, [last]);

  if (intake.caseType === "criminal") {
    return (
      <aside className="relative min-w-0">
        <Card id="dispute-help" className="lg:absolute lg:inset-0" aria-labelledby="crim-help-title">
          <CardHeader><CardTitle id="crim-help-title" className="text-base font-bold">刑事案件怎麼寫</CardTitle></CardHeader>
          <ScrollArea className="min-h-0 flex-1">
            <CardContent className="flex flex-col gap-4 text-[15px] leading-relaxed">
              <p>依時間順序寫出：<strong>什麼時候、在哪裡、誰做了什麼、造成什麼結果</strong>。</p>
              <p>有沒有受傷、財物損失多少、事後有沒有報警或和解，也請寫進去。</p>
              <p className="text-muted-foreground">告訴乃論的罪（例如過失傷害）如果雙方和解、撤回告訴，通常不會有判決。</p>
              <p className="text-muted-foreground">同一件事可能有民事也有刑事：例如車禍受傷，刑事上可能是過失傷害，民事上可以請求賠償。</p>
            </CardContent>
          </ScrollArea>
        </Card>
      </aside>
    );
  }

  return (
    <aside className="relative min-w-0">
      <Card id="dispute-help" className="lg:absolute lg:inset-0" aria-labelledby="dispute-help-title">
        <CardHeader>
          <CardTitle id="dispute-help-title" className="text-base font-bold">糾紛類型說明</CardTitle>
          <CardDescription>選最接近的一類就好，可以多選。分類依判決的案由和內容整理，不是法律上的正式分類。</CardDescription>
        </CardHeader>
        <ScrollArea className="h-96 min-h-0 lg:h-auto lg:flex-1">
          <div ref={viewport} className="flex flex-col gap-5 px-4 pb-2">
            {DISPUTE_GROUPS.map((group) => (
              <section key={group.title} className="flex flex-col gap-1.5">
                <h3 className="text-sm font-semibold text-muted-foreground">{group.title}</h3>
                <dl className="flex flex-col gap-1">
                  {group.types.map((t) => {
                    const on = intake.mids.includes(t.id);
                    return (
                      <div key={t.id} id={`dt-${t.id}`} className={cn("rounded-lg px-2.5 py-2 transition-colors", on && "bg-accent ring-1 ring-primary/40")}>
                        <dt className={cn("text-sm font-semibold", on && "text-accent-foreground")}>{t.id}</dt>
                        <dd className="text-sm">{t.summary}<span className="block text-[13px] text-muted-foreground">例如：{t.example}</span></dd>
                      </div>
                    );
                  })}
                </dl>
              </section>
            ))}
          </div>
        </ScrollArea>
      </Card>
    </aside>
  );
}
