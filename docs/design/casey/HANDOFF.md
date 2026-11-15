# CasEY（類案判決參考）前端實作交接

> 檔案位置：設計稿在 `docs/design/casey/reference/`，`tokens.css` 在 `docs/design/casey/`（實作時合併進 `frontend/src/index.css`），角色圖在 `frontend/src/assets/casey/`。下文提到的 `reference/`、`assets/` 指這些位置。這份交接依據的設計需求是 `docs/design/介面改版spec.md`。

給 Claude Code：請先讀完這份，再動手。設計稿放在 `reference/`，是 HTML 原型，**只拿來看版面、文字、狀態和互動**，不要複製裡面的 class 或 DOM，要用下面指定的技術棧重做。

## 0. 技術限制

- Vite + React 19（單頁應用，不是 Next.js）、Tailwind CSS v4、shadcn/ui `base-nova` 風格（底層是 Base UI，不是 Radix）、圖示用 lucide-react。
- 用這套元件能做到的就用；做不到的，在第 3 節標成「新元件」，請放在 `src/components/casey/` 並說明為什麼需要。
- Base UI 沒有 `asChild`，要換元素用 `render` prop。專案裡實際安裝了哪些 shadcn 元件，以 `src/components/ui/` 為準；缺的用 `npx shadcn add` 補，不要手刻。
- 顏色、字體、圓角全部走 `tokens.css`（Tailwind v4 的 `@theme`）。**不要在元件裡寫死色碼，也不要用 Tailwind 預設的 red-/green- 色階。**
- 路由建議用 `react-router`：`/`、`/start`（關卡 1–3）、`/confirm`（關卡 4–6）、`/result/civil`、`/result/criminal`、`/judgment/:id`、`/guide`。分頁用 `?tab=`。已有路由方案就沿用。

## 1. 設計稿對照

`reference/` 內每個檔案對應一個畫面。畫布上每一關、每個結果分頁都有獨立設計稿，內容都來自下列檔案（用 `start-stage`、`start-tab` 這類參數切換）。

| 檔案 | 內容 | 建議路由 |
|---|---|---|
| `Main.dc.html` | 色票、字級、按鈕、卡片、結果顏色語言 | — |
| `C2-Home.dc.html` | 首頁 | `/` |
| `C2-Start.dc.html` | 關卡 1 選類型、關卡 2 描述案情、關卡 3 補充資料 | `/start` |
| `C2-Confirm.dc.html` | 關卡 4 確認遮名、關卡 5 補充細節、關卡 6 改寫與確認 | `/confirm` |
| `C2-Civil.dc.html` | 民事結果：整體結果、可能的金額、證據對照、對方的說法、相似判決 | `/result/civil` |
| `C2-Criminal.dc.html` | 刑事結果：可能的罪名、刑期範圍、相似判決 | `/result/criminal` |
| `C2-Judgment.dc.html` | 判決導讀（五類標色） | `/judgment/:id` |
| `C2-Guide.dc.html` | 說明與法律小知識 | `/guide` |
| `States.dc.html` | 載入、錯誤、資料不足、示例資料、極端數字 | 不是頁面，是狀態規格 |
| `CTop.dc.html` / `Amount.dc.html` | 共用元件：頁首＋進度＋角色場景／金額區塊 | — |

`jd.css` 是原型的樣式，**只當數值參考**（間距、尺寸、斷點）。

目前**沒有設計**：手機版（375px）、民事結果列印／PDF 版、各頁深色模式的逐頁確認。桌機設計寫成容器查詢（620px、720px 以下換成單欄），實作時可對應 Tailwind 的 `sm`/`md`。先做桌機，手機先做到「單欄不破版、按鈕 ≥ 44px」，之後再補設計。

## 2. 流程與每一關的資料

流程：首頁 → 第一章 描述案情（關卡 1–3）→ 第二章 確認內容（關卡 4–6）→ 第三章 結果（民事／刑事）→ 判決導讀。進度圖共 7 個節點：類型、案情、資料、遮名、補充、改寫、結果。

一次只顯示一關。用單一表單 store（Context + useReducer，或 zustand），關卡之間保留資料，重新整理後從 `sessionStorage` 還原。**不要用 localStorage 存案情內容。**

| 關卡 | 欄位 | 規則 |
|---|---|---|
| 1 類型 | `caseType`: `civil` \| `criminal` \| `unsure` | 必選。選了之後顯示「選○○，你會得到：…」。`unsure` 的結果頁有民事、刑事兩個分頁 |
| 2 案情 | `story` 字串；`kinds` 字串陣列（只有民事） | `story` 30–3000 字，不到 30 字不能下一關，下方顯示「再多寫一點：至少 30 字」。寫作提示（時間、地點、對方做了什麼、損失）用規則比對，寫到就亮起來，只是提示，不擋下一關。`kinds` 是糾紛類型，15 大類 46 類，要做成可搜尋、可多選的清單，右側顯示已選類型的說明。刑事不選糾紛類型，改顯示「刑事案件怎麼寫」提示卡 |
| 3 資料 | `court`、`amount`、`party`（`person`\|`company`\|`gov`）、`lawyer`（`yes`\|`no`）、`evidence`（6 個布林） | `court`、`amount`、`party` 只有民事才有。`court` 可不選，預設「不指定」。`amount` 可空白（空白就只顯示比例，不顯示金額範圍）。證物欄只勾選「手上有」，不上傳檔案。刑事只填 `lawyer` 和 `evidence` |
| 4 遮名 | `extraMasks` 字串陣列；`sensitiveConsent`: `yes` \| `no` | 系統自動遮身分證、電話、email、地址，預覽裡用橘色標出。使用者可加要遮的字，文字中所有相同字串都遮掉。案情含病歷等敏感資料時，要使用者選「我同意」才能下一關；選「不同意」就導回關卡 2 修改 |
| 5 補充 | `extraMode`: `fixed` \| `ai`；各題答案 | 可略過。固定題目的答案**不會傳給 AI**，要在畫面上明說。AI 模式有五種狀態：有題目、載入中、失敗、今日次數用完、不像法律糾紛，每種都有對應文案，並提供「改用固定題目」的出口 |
| 6 改寫 | `rewrite` 字串；`useRewrite`: `rewrite` \| `original` | AI 把口語改成判決書寫法，使用者可直接編輯。**改寫文字裡出現原文沒有的數字，要顯示警告並列出那些數字**。送出前最後確認摘要。同意狀態沒過不能按「看參考結果」，並顯示原因 |

金額解析（關卡 3）：接受 `648000`、`648,000`、`64萬8千`、`50萬`，前後可有「元」「NT$」。看不懂時顯示「看不懂這個金額。請輸入數字，例如 50萬 或 648000。」並擋下一關；看得懂時顯示「我讀成：648,000 元」。請寫成純函式並加單元測試。

## 3. 元件對照

### 用現成 shadcn（base-nova）

| 設計稿 | 用什麼 | 調整 |
|---|---|---|
| 按鈕（主要／次要／文字） | `Button`（default／outline／ghost） | 高度 48px，大按鈕 56px，圓角 12px，文字 16px 以上 |
| 卡片 | `Card` | 圓角 18px，淺色有陰影，深色沒有 |
| 輸入框、文字區、下拉 | `Input`、`Textarea`、`Select`，包在 `Field`／`Label` 裡 | 邊框用 `--input`（比一般邊框深）。文字區下方顯示字數與狀態訊息，要有 `role="status"` |
| 結果分頁 | `Tabs` | 分頁文字永遠顯示，不要只有圖示 |
| 可展開說明（金額細節、抗辯、糾紛類型） | `Accordion` 或 `Collapsible` | 列印時要全部展開 |
| 表格（相似判決） | `Table` | 窄螢幕用橫向捲動，不要壓成多欄擠在一起 |
| 提示框、示例資料橫幅、錯誤框 | `Alert` | 做三種：`info`（藍灰）、`sample`（紫灰）、`notice`（粗邊框）。**不做紅色** |
| 「只看原告勝訴的」開關 | `Switch` | 有文字標籤 |
| 骨架畫面 | `Skeleton` | 位置與最終版面一致，不跳動 |
| 糾紛類型、寫作提示、遮名標籤 | `Badge` 或 `Toggle` | 可點的用 `Toggle`（要有 `aria-pressed`），遮名標籤帶移除按鈕 |
| 對方、律師的二選一／三選一 | `ToggleGroup`（單選） | 每個選項 ≥ 44px 高 |
| 「請注意」提醒 | `Popover`（Base UI 的 `openOnHover`） | 見下方「提醒元件」 |

### 新元件（shadcn 沒有，需要自己做）

| 元件 | 用途 | 實作重點 |
|---|---|---|
| `StageMap` | 7 個節點的進度圖，分三章 | `<ol>`，目前節點 `aria-current="step"`，已完成節點顯示打勾，每個節點下面有文字 |
| `CharacterScene` | 頁首場景：整理員（左）、解說員（右）、中間對話框 | 兩位角色是輔助角色，**不叫律師或法官**。只有說話的那一位是正常亮度，另一位淡一點。圖在 `assets/`。對話框有 `role="status"` |
| `RadioCard` | 關卡 1 的類型選擇、關卡 6 的寫法選擇 | 底層用 `RadioGroup`，外觀是整塊可點的卡片，選中時邊框加粗、顯示勾，不能只靠顏色區分 |
| `EvidenceSlot` | 證物欄的 6 個格子 | 底層用 `Toggle`，選中時右上角有打勾徽章，高度約 100px |
| `AmountInput` | 金額欄 | 內含解析函式、即時回饋文字、「快速填入」按鈕 |
| `OutcomeBar` | 全部勝訴／一部勝訴／敗訴的比例條 | 純 div，不用圖表庫。三色：深靛、淺藍、沙灰斜線。**0 件的區段不畫，但圖例文字永遠都在**。要有 `role="img"` 和完整的 `aria-label` |
| `RangeBar` | 判准金額範圍（最低、中位、最高） | 模型推估用虛線填色，相似判決用實線。標籤只放必要的幾個數字，不要全擠在條上 |
| `MiniBar`／`Histogram` | 證據對照、抗辯比例、刑期分布 | 每一列都有數字文字，`aria-label` 說明數值 |
| `MaskMark` | 預覽文字中被遮掉的片段 | 用 `<mark>`，橘色底，內容如「［電話已遮］」 |
| `JudgmentPassage` ＋ 篩選器 | 判決導讀的分段標色 | 五類（原告主張、被告抗辯、爭點、證據、法院判斷）各有底色，**每段有文字標籤，不只靠顏色**。上方可切換只看某一類 |
| `DisclaimerFooter` | 頁尾「不是法律意見」＋「請注意」按鈕 | 見下方 |

### 提醒元件（重要）

每個結果頁底部有一行：「本服務提供的是過去判決的統計參考，**不是法律意見**，也不是對你案子的預測」，旁邊一顆「請注意」按鈕。

- 滑鼠移上去、鍵盤聚焦、**手指點一下**都要能展開（手機沒有 hover，不能只靠 hover）。
- 展開內容往上開，是 3–4 條條列。民事和刑事的條列不同，文字在 `reference/C2-Civil.dc.html`、`reference/C2-Criminal.dc.html`。
- 列印時按鈕隱藏，條列直接印出來。
- 結果頁其他地方**不要**再放提醒條。角色說明（不是律師或法官）只出現在首頁和關卡 1。

### 圖示（lucide-react）

| 設計稿 | lucide |
|---|---|
| check / info / help | `Check` / `Info` / `CircleHelp` |
| right / back / down | `ChevronRight` 或 `ArrowRight` / `ArrowLeft` / `ChevronDown` |
| download / file / book | `Download` / `FileText` / `BookOpen` |
| scale（logo） / shield | `Scale` / `ShieldCheck` |
| alert / lock / clock | `TriangleAlert` / `Lock` / `Clock` |
| pencil / plus / minus / x | `Pencil` / `Plus` / `CircleMinus` / `X` |
| search / sparkle / retry | `Search` / `Sparkles` / `RotateCw` |
| loader / external / db | `LoaderCircle`（加旋轉）/ `ExternalLink` / `Database` |

圖示旁一定要有文字，純圖示的按鈕要加 `aria-label`。

## 4. 文案與設計原則（不能動）

1. **不做保證**：不出現「你會贏」「勝率」「穩了」，不用儀表、紅綠燈、勝率大字。
2. **範圍一定搭配白話**：例如「10 件約有 8 件」。機率和模型數字收在「模型細節」裡，並寫明「不是你會贏的機率」。
3. **結果顏色不分好壞**：深靛、淺藍、沙灰斜線，不用紅綠；**顏色以外一律附文字**。「敗訴」只是結果之一，不是警告。
4. **專屬色**：遮名只用橘色，示例資料只用紫灰色，這兩種顏色不要用在別處。
5. **相似度**是 0 到 1 之間的小數（例如 0.14），不是百分比。
6. **角色不是律師或法官**：整理員、解說員只是輔助角色。結果頁**不要**用「開庭」「判決」之類的演出，不要讓人誤以為是法院。
7. **字級與目標大小**：內文 16px 以上，輔助文字不小於 14px；可點元素高度 ≥ 44px；文字與背景對比符合 WCAG AA。目標使用者含年長者與手機使用者。
8. **每個圖表都要有文字替代**：`aria-label` 或旁邊的文字摘要。
9. **狀態要完整**：載入（骨架畫面）、錯誤（說「不是你填錯」並給重試）、資料不足（說明原因，不顯示 0 或留白）、示例資料（三個位置都標：頁面上方、每個區塊、PDF 每頁頁尾）、極端數字（100%、0 件，版面不能壞）。詳見 `States.dc.html`。
10. 單一區塊出錯，其他區塊照常顯示。

## 5. 待確認（不要自行假設）

- **法律用語**：`C2-Guide.dc.html` 的名詞解釋、糾紛類型說明，是暫擬的白話文字，需要有法律背景的人審過。
- **刑事相似判決**：`C2-Criminal.dc.html` 第 3 分頁的三列是「版面示意」，字號與相似度是 `○` 佔位，要換成真實資料。
- **資料來源與欄位名稱**：後端 API 的欄位尚未對接，請先用型別（TypeScript `type`）定義畫面需要的資料形狀，並用假資料驅動，之後再接 API。示例資料（`sample`）模式要保留，沒有連到模型時整頁顯示示例資料標示。
- **AI 補充題與改寫**：真正的呼叫、次數限制、失敗處理由後端決定；前端只負責五種狀態的畫面。

## 6. 建議實作順序

1. 把 `tokens.css` 併進專案，確認淺色與深色都能切換，字體載入 Noto Sans TC。
2. 共用元件：`StageMap`、`CharacterScene`、`RadioCard`、`DisclaimerFooter`、頁首與頁尾。
3. 首頁與關卡 1–3（含金額解析與驗證、表單 store）。
4. 關卡 4–6（遮名預覽、同意閘門、改寫數字比對）。
5. 民事結果（先整體結果與可能的金額，再證據、對方的說法、相似判決），再做刑事結果。
6. 判決導讀、說明頁。
7. 各種狀態（`States.dc.html`）、手機版調整、列印／PDF。

每完成一個畫面，請和 `reference/` 對照：文字有沒有照原稿、狀態有沒有缺、色彩有沒有用錯，再往下做。
