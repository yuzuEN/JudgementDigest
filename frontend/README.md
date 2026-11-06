# frontend/：網頁

React＋Vite＋TypeScript。版面依設計原型：首頁、描述案情、確認與遮名、民事／刑事結果、判決導讀、說明頁。

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
| `src/state.tsx` | 使用者填的內容。只放在記憶體裡，重新整理就清空，不寫進瀏覽器儲存空間 |
| `src/pages/` | `Home`、`Intake`（描述案情）、`Confirm`（追問、遮名預覽、敏感個人資料同意）、`CivilResult`、`CriminalResult`、`Reading`（判決導讀）、`Guide`（說明頁） |
| `src/components/` | 頁首頁尾、結果頁外框（分頁、下載 PDF）、整理敘述（`RewriteCard`）、共用元件 |
| `src/format.ts` | 金額、比例、判決結果的顯示；敏感個人資料的判斷 |
| `src/mask.ts` | 瀏覽器內的遮名 |
| `src/knowledge.ts` | 說明頁的內容：糾紛類型與名詞 |
| `src/theme.ts` | 淺色、夜間模式 |
| `src/styles.css` | 顏色與版面（和設計原型一致），含列印用的樣式 |
| `src/test/` | 測試：各頁面的行為，以及從首頁走到判決導讀的完整流程 |

## 設計上的決定

- **送出的一律是遮名後的文字**：遮名在瀏覽器完成（`src/mask.ts`），原文和使用者加入的姓名不會傳到伺服器；規則要和 `retrieval/masking.py` 一致，兩邊跑同一份 `src/test/masking_cases.json`
- **敏感個人資料要另外同意**：描述提到病歷、醫療、健康檢查、基因、性生活、犯罪前科時，要勾選同意才能看結果（個資法第 6 條）
- **下載 PDF 用瀏覽器的列印**：按「下載 PDF」會開啟列印，選「另存為 PDF」。列印版會加上產生時間、遮名後的描述與免責說明，展開摺疊內容並印出畫面上篩掉的項目，隱藏按鈕與選單；伺服器不保存任何東西
- **整理敘述要使用者確認**：LLM 改寫的內容可以修改，確認後才用來搜尋相似判決，確認時會再遮一次名；描述或姓名改了就要重新整理
- **示例資料一定標示**：API 回傳 `mock: true` 時，頁面上會顯示「示例資料」
