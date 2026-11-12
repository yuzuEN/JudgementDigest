import { BookOpenIcon } from "lucide-react";

/** 示例資料（沒有連到模型時）：紫灰色只用在這個用途。頁面上方、每個區塊、PDF 每頁都要標。 */
export function SampleBanner({ detail }: { detail?: string }) {
  return (
    <div role="status" className="flex items-start gap-3 rounded-[14px] border-[1.5px] border-sample-line bg-sample px-4 py-3 text-sample-fg">
      <BookOpenIcon className="mt-1 size-5 flex-none" aria-hidden="true" />
      <div>
        <p className="font-bold">這一頁是示例資料</p>
        <p className="text-[15px]">{detail ?? "目前沒有連到比對模型，下面的數字是示範用的，不是你這個案子的查詢結果。每個分頁和下載的 PDF 都會標上「示例資料」。"}</p>
      </div>
    </div>
  );
}

export function SampleTag() {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border-[1.5px] border-dashed border-sample-line bg-sample px-2.5 text-sm leading-[1.7] font-bold text-sample-fg">
      <BookOpenIcon className="size-4" aria-hidden="true" />示例資料
    </span>
  );
}
