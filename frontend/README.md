# frontend/：網頁

React 19＋Vite＋TypeScript，介面用 Tailwind CSS 4＋shadcn/ui（Base UI 版）元件與 lucide 圖示。版面是 CasEY 改版（PR #44），設計稿與交接說明在 [docs/design/casey/](../docs/design/casey/HANDOFF.md)。

使用流程是七關、分三章：

| 章 | 關卡 | 頁面 |
|---|---|---|
| 描述案情 | 1 類型、2 案情、3 資料 | `/start?stage=1`～`3` |
| 確認內容 | 4 遮名、5 補充、6 改寫 | `/confirm?stage=4`～`6` |
| 參考結果 | 7 結果 | `/result/civil`、`/result/criminal`（分頁在 `?tab=`） |

另有判決導讀（`/judgment/:source/:caseId`）和說明頁（`/guide`）。

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173 ；/api 會轉給 http://127.0.0.1:8000 的後端
npm test           # 測試
npm run build      # 型別檢查＋建置到 dist/
```

後端在別的位址時：`VITE_API_PROXY=http://其他位址:8000 npm run dev`。

## 檔案

| 位置 | 內容 |
|---|---|
| `src/api/` | `types.ts`（和 `backend/schemas.py` 一一對應）、`client.ts`（呼叫 API） |
| `src/state.tsx` | 使用者填的內容。放在這個分頁的 `sessionStorage`：重新整理還在，關掉分頁就清掉；不用 `localStorage`，也不送去保存 |
| `src/pages/` | `Home`、`Intake`（關卡 1–3）、`Confirm`（關卡 4–6：遮名、敏感個人資料同意、追問、AI 整理敘述）、`CivilResult`、`CriminalResult`、`Reading`（判決導讀）、`Guide`（說明頁） |
| `src/components/` | 頁面寬度（`Layout`）、結果頁外框與下載 PDF（`ResultFrame`）、像按鈕的連結（`LinkButton`）、共用的小元件（`Common`） |
| `src/components/casey/` | 改版的元件：關卡圖（`StageMap`）、結果分頁（`ResultTabs`）、勝敗與金額的長條（`OutcomeBar`、`RangeBar`、`Bars`）、示例資料標示（`Sample`）、主題切換（`ThemeToggle`）等，各檔開頭有說明 |
| `src/components/ui/` | shadcn/ui 元件（`npx shadcn add <元件>` 產生，可以直接改） |
| `src/assets/casey/` | 兩個角色的圖（整理員、解說員） |
| `src/format.ts` | 金額、比例、判決結果的顯示；敏感個人資料的判斷 |
| `src/mask.ts` | 瀏覽器內的遮名 |
| `src/knowledge.ts` | 說明頁的內容：糾紛類型與名詞 |
| `src/theme.ts` | 淺色／深色：預設跟著系統，使用者在頁首切換過就記在 `localStorage`（只是外觀偏好，不是案情）；列印一律淺色 |
| `src/index.css` | 顏色（CasEY 的 tokens 併進 shadcn 的 CSS 變數，淺色與深色各一組）、細捲軸、列印用的樣式 |
| `src/test/` | 測試：各頁面的行為，以及從首頁走到判決導讀的完整流程 |

## 設計上的決定

- **送出的一律是遮名後的文字**：遮名在瀏覽器完成（`src/mask.ts`），原文和使用者加入的姓名不會傳到伺服器；規則要和 `retrieval/masking.py` 一致，兩邊跑同一份 `src/test/masking_cases.json`
- **敏感個人資料要另外同意**：描述提到病歷、醫療、健康檢查、基因、性生活、犯罪前科時，要勾選同意才能看結果（個資法第 6 條）
- **下載 PDF 用瀏覽器的列印**：按「下載 PDF」會開啟列印，選「另存為 PDF」。列印版會加上產生時間、遮名後的描述與免責說明，展開摺疊內容並印出畫面上篩掉的項目，隱藏按鈕與選單；伺服器不保存任何東西
- **整理敘述要使用者確認**：LLM 改寫的內容可以修改，確認後才用來搜尋相似判決，確認時會再遮一次名；描述或姓名改了就要重新整理
- **示例資料一定標示**：API 回傳 `mock: true` 時，頁面上方、每個區塊、PDF 每頁都會顯示「示例資料」
- **案情只放 sessionStorage**：只有主題偏好可以放 `localStorage`，案情、姓名、遮名後的文字都不行
