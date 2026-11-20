import type {
  CaseType,
  CivilInput,
  CivilRole,
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

// 每種結果只保留最近一次請求，包含進行中的請求；離開導讀再返回不重跑模型。
const reports = new Map<string, { key: string; promise: Promise<unknown> }>();
export function clearReportCache() { reports.clear(); }

function reportRequest<T>(path: string, body: unknown): Promise<T> {
  const key = JSON.stringify(body);
  const cached = reports.get(path);
  if (cached?.key === key) return cached.promise as Promise<T>;
  const promise = request<T>(path, body).catch((error) => {
    if (reports.get(path)?.promise === promise) reports.delete(path);
    throw error;
  });
  reports.set(path, { key, promise });
  return promise;
}

export const api = {
  health: () => request<Health>("/health"),
  options: () => request<Options>("/meta/options"),
  followup: (case_type: CaseType, mid: string | null, text: string, allow_llm = false, role: CivilRole = "plaintiff") =>
    request<FollowupResponse>("/intake/followup", { case_type, role, mid, text, allow_llm }),
  rewrite: (case_type: CaseType, mid: string | null, text: string, role: CivilRole = "plaintiff") =>
    request<RewriteResponse>("/intake/rewrite", { case_type, role, mid, text, allow_llm: true }),
  civilReport: (input: CivilInput) => reportRequest<CivilReport>("/civil/report", input),
  criminalReport: (text: string) => reportRequest<CriminalReport>("/criminal/predict", { text }),
  guide: (source: string, caseId: number) => request<Guide>(`/judgments/${source}/${caseId}/guide`),
};
