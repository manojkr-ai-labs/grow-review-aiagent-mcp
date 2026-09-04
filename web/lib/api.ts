import type {
  JobDTO,
  McpStatus,
  PulseDTO,
  PublishActionResult,
  PublishSummary,
  ReviewDTO,
  ReviewList,
  RunDetail,
  RunSummary,
  SettingsDTO,
  SettingsPatch,
  StatusDTO,
  ThemeDTO,
  ThemeDetail,
} from "./types";

export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

function withRun(path: string, runId?: string | null): string {
  if (!runId) return path;
  const join = path.includes("?") ? "&" : "?";
  return `${path}${join}run_id=${encodeURIComponent(runId)}`;
}

/** Same-origin by default so EventSource uses the Next `/api/v1` rewrite. */
export function jobLogUrl(
  id: string,
  origin: string | undefined = typeof process !== "undefined" ? process.env.NEXT_PUBLIC_API_ORIGIN : undefined,
): string {
  const path = `/api/v1/pipeline/jobs/${encodeURIComponent(id)}/log`;
  const trimmed = (origin || "").replace(/\/$/, "");
  return trimmed ? `${trimmed}${path}` : path;
}

async function parseError(res: Response): Promise<string> {
  const text = await res.text();
  try {
    const json = JSON.parse(text) as { detail?: unknown };
    if (typeof json.detail === "string") return json.detail;
    if (json.detail) return JSON.stringify(json.detail);
  } catch {
    /* raw */
  }
  return text || res.statusText;
}

export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(path, { cache: "no-store" });
  if (!res.ok) throw new ApiError(res.status, await parseError(res));
  return (await res.json()) as T;
}

async function apiSend<T>(path: string, method: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new ApiError(res.status, await parseError(res));
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  status: () => apiGet<StatusDTO>("/api/v1/status"),
  pulse: (runId?: string | null) => apiGet<PulseDTO>(withRun("/api/v1/pulse", runId)),
  themes: (runId?: string | null) => apiGet<ThemeDTO[]>(withRun("/api/v1/themes", runId)),
  theme: (themeId: string, runId?: string | null) =>
    apiGet<ThemeDetail>(withRun(`/api/v1/themes/${encodeURIComponent(themeId)}`, runId)),
  reviews: (params: Record<string, string | number | boolean | undefined | null>, runId?: string | null) => {
    const search = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (value === undefined || value === null || value === "") continue;
      search.set(key, String(value));
    }
    const qs = search.toString();
    return apiGet<ReviewList>(withRun(`/api/v1/reviews${qs ? `?${qs}` : ""}`, runId));
  },
  review: (id: string, runId?: string | null) =>
    apiGet<ReviewDTO>(withRun(`/api/v1/reviews/${encodeURIComponent(id)}`, runId)),
  runs: () => apiGet<RunSummary[]>("/api/v1/runs"),
  run: (id: string) => apiGet<RunDetail>(`/api/v1/runs/${encodeURIComponent(id)}`),
  noteUrl: (id: string) => `/api/v1/runs/${encodeURIComponent(id)}/note`,
  publish: (runId?: string | null) => apiGet<PublishSummary>(withRun("/api/v1/publish", runId)),
  settings: () => apiGet<SettingsDTO>("/api/v1/settings"),
  patchSettings: (patch: SettingsPatch) => apiSend<SettingsDTO>("/api/v1/settings", "PATCH", patch),
  mcpCheck: () => apiSend<McpStatus>("/api/v1/mcp/check", "POST"),
  runPipeline: (body: { window_weeks?: number; dry_run: boolean; send: boolean }) =>
    apiSend<JobDTO>("/api/v1/pipeline/run", "POST", body),
  job: (id: string) => apiGet<JobDTO>(`/api/v1/pipeline/jobs/${encodeURIComponent(id)}`),
  jobLogUrl,
  append: (runId?: string | null) =>
    apiSend<PublishActionResult>("/api/v1/publish/append", "POST", {
      run_id: runId ?? null,
      confirm: false,
    }),
  draft: (runId?: string | null) =>
    apiSend<PublishActionResult>("/api/v1/publish/draft", "POST", {
      run_id: runId ?? null,
      confirm: false,
    }),
  send: (runId?: string | null) =>
    apiSend<PublishActionResult>("/api/v1/publish/send", "POST", {
      run_id: runId ?? null,
      confirm: true,
    }),
};
