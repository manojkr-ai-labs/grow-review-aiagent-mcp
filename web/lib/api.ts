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
  deskQueue: () => apiGet<DeskQueueRow[]>("/api/desk/queue"),
  deskQuestion: (text: string) =>
    apiSend<Record<string, unknown>>("/api/desk/questions", "POST", { text }),
  deskCase: (caseId: string) =>
    apiGet<DeskCaseDetail>(`/api/desk/cases/${encodeURIComponent(caseId)}`),
  deskDecision: (caseId: string, body: { decision: "approve" | "reject"; approver_ref: string }) =>
    apiSend<{ run?: { state?: string; content_hash?: string | null } }>(
      `/api/desk/cases/${encodeURIComponent(caseId)}/decision`,
      "POST",
      body,
    ),
  deskRefine: (caseId: string, body: { instruction: string; reply: string }) =>
    apiSend<DeskRefineResult>(
      `/api/desk/cases/${encodeURIComponent(caseId)}/refine`,
      "POST",
      body,
    ),
  deskPublish: (caseId: string) =>
    apiSend<Record<string, unknown>>(`/api/desk/cases/${encodeURIComponent(caseId)}/publish`, "POST", {}),
  capstonePackage: (runId: string) =>
    apiGet<WeeklyPackage>(`/api/capstone/runs/${encodeURIComponent(runId)}/package`),
  capstoneDecision: (
    runId: string,
    body: { decision: "approve" | "reject"; approver_ref: string; action: "append" | "draft" | "send" },
  ) =>
    apiSend<{ decision?: string; content_hash?: string }>(
      `/api/capstone/runs/${encodeURIComponent(runId)}/decision`,
      "POST",
      body,
    ),
  capstonePublish: (runId: string, body: { package_hash: string; action: "append" | "draft" | "send" }) =>
    apiSend<{ ok?: boolean; package_hash?: string; action?: string }>(
      `/api/capstone/runs/${encodeURIComponent(runId)}/publish`,
      "POST",
      body,
    ),
};

export type DeskQueueRow = {
  case_id: string;
  sanitized_text: string;
  draft: string | null;
  not_covered: boolean;
  citation: string[];
  reviewer_flag: string | null;
  state: string;
  coverage: string;
  pattern_signal: string | null;
  matching_count: number | null;
  window_start: string | null;
  window_end: string | null;
  theme_id: string | null;
  compliance_decision: string | null;
  pii_redacted: boolean;
  redaction_blocked: boolean;
};

export type DeskClaim = {
  claim: string;
  source_url: string;
  source_title: string;
  last_checked: string | null;
};

export type DeskCaseDetail = {
  case_id: string;
  draft: { text: string; sentence_count: number } | null;
  routing_note: {
    team: string;
    priority: string;
    reason: string;
    pattern_signal: string;
    matching_count: number;
    facts_coverage: string;
    citation_refs: string[];
    next_action: string;
    disagreement: string | null;
    limitations: string[];
    analysis_window?: { start: string | null; end: string | null } | null;
  } | null;
  agent_timings: Array<{
    agent: string;
    started_at: string | null;
    ended_at: string | null;
  }>;
  claims: DeskClaim[];
  searched_urls: string[];
  reviewer_findings: Array<{ code?: string; message?: string }>;
  state?: string | null;
  content_hash?: string | null;
  document_id?: string | null;
  recipient?: string | null;
};

export type PackageBullet = {
  text: string;
  url?: string | null;
  last_checked?: string | null;
};

export type PackageSignal = {
  week_id: string;
  question_key: string;
  count: number;
  evidence_type: string;
};

export type WeeklyPackage = {
  note: string;
  explainer: {
    week_id?: string;
    fee_theme: string | null;
    bullets: PackageBullet[];
  };
  signals: PackageSignal[];
  package_hash: string;
  fee_theme: string | null;
  ledger: unknown[];
  approval?: PackageApproval | null;
};

export type PackageApproval = {
  decision: string | null;
  content_hash: string | null;
  action: string;
  matches: boolean;
};

export type DeskRefineResult = {
  result?: { reply?: { text?: string } };
  run?: { state?: string; content_hash?: string | null };
  refinements?: Array<{ accepted?: boolean }>;
};

export const PACKAGE_FILES = ["note.md", "explainer.json", "support_signals.json"] as const;

export const EMPTY_LEDGER_SENTENCE = "No queued question in this week was outside the corpus.";

export function queueSignalLine(signal: PackageSignal): string {
  return `Support was asked "${signal.question_key}" ${signal.count} times in ${signal.week_id}. This line is the question log, not review volume.`;
}
