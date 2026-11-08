import type {
  CaseType,
  CivilInput,
  CivilReport,
  RewriteResponse,
  CriminalReport,
  FollowupResponse,
  Guide,
  Health,
  Options,
} from "./types";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, body?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api${path}`, {
      method: body === undefined ? "GET" : "POST",
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "連不上伺服器，請確認網路或稍後再試。");
  }
  if (!res.ok) {
    throw new ApiError(res.status, res.status === 422 ? "送出的內容格式不正確，請回上一步檢查。" : "伺服器發生錯誤，請稍後再試。");
  }
  return (await res.json()) as T;
}

export const api = {
  health: () => request<Health>("/health"),
  options: () => request<Options>("/meta/options"),
  followup: (case_type: CaseType, mid: string | null, text: string, allow_llm = false) =>
    request<FollowupResponse>("/intake/followup", { case_type, mid, text, allow_llm }),
  rewrite: (mid: string | null, text: string) =>
    request<RewriteResponse>("/intake/rewrite", { mid, text, allow_llm: true }),
  civilReport: (input: CivilInput) => request<CivilReport>("/civil/report", input),
  criminalReport: (text: string) => request<CriminalReport>("/criminal/predict", { text }),
  guide: (source: string, caseId: number) => request<Guide>(`/judgments/${source}/${caseId}/guide`),
};
