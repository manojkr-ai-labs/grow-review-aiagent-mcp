export type WindowDTO = {
  weeks: number;
  requested_start: string | null;
  requested_end: string | null;
  actual_start: string | null;
  actual_end: string | null;
  actual_weeks: number | null;
};

export type CountsDTO = {
  window_reviews: number;
  clustered: number;
  dropped_low_signal: number;
  themes: number;
  negative: number;
};

export type ThemeDTO = {
  theme_id: string;
  rank: number;
  label: string;
  summary: string;
  line: string | null;
  size: number;
  mean_rating: number | null;
  neg_share: number;
  priority: number;
  trend: number | null;
  emerging: boolean;
  in_note: boolean;
  keywords: string[];
  top_terms: string[];
  label_source: string | null;
};

export type QuoteDTO = {
  review_id: string;
  theme_id: string;
  text: string;
  rating: number | null;
  words: number | null;
};

export type ActionDTO = {
  text: string;
  theme_ids: string[];
};

export type GateDTO = {
  gate: string;
  passed: boolean;
  detail: string;
};

export type StageDTO = {
  id: string;
  label: string;
  status: string;
  detail: string;
};

export type PublishActionResult = {
  ok: boolean;
  skipped: boolean;
  detail: string;
  publish: PublishSummary | null;
};

export type PublishSummary = {
  mode: string;
  published: boolean;
  idempotency_key: string | null;
  doc_id: string | null;
  doc_url: string | null;
  draft_id: string | null;
  message_id: string | null;
  recipient: string | null;
  skipped_append: boolean;
  skipped_send: boolean;
  subject: string | null;
};

export type McpStatus = {
  ok: boolean;
  label: string;
  detail: string | null;
  url: string | null;
  document_id: string | null;
  cached: boolean;
};

export type JobDTO = {
  job_id: string;
  status: string;
  dry_run: boolean;
  send: boolean;
  window_weeks: number;
  error: string | null;
  run_id: string | null;
  started_at: string | null;
  finished_at: string | null;
  log_lines: number;
};

export type StatusDTO = {
  package_id: string;
  operator_initials: string;
  iso_week: string | null;
  last_run_id: string | null;
  last_run_at: string | null;
  window: WindowDTO | null;
  mcp: McpStatus;
  lock_held: boolean;
  store_count: number;
  pipeline: JobDTO | null;
};

export type PulseDTO = {
  run_id: string;
  iso_week: string | null;
  window: WindowDTO;
  counts: CountsDTO;
  mean_rating: number | null;
  word_count: number;
  max_words: number;
  compose_source: string | null;
  compose_provider: string | null;
  compose_model: string | null;
  top_themes: ThemeDTO[];
  quotes: QuoteDTO[];
  actions: ActionDTO[];
  gates: GateDTO[];
  gates_passed: number;
  gates_total: number;
  all_gates_passed: boolean;
  rejected: boolean;
  publish: PublishSummary;
  stages: StageDTO[];
  note_available: boolean;
  clustering: Record<string, string | null | undefined>;
};

export type ThemeDetail = {
  run_id: string;
  theme: ThemeDTO;
  rating_histogram: Record<string, number>;
  member_count: number;
  in_note: boolean;
};

export type ReviewDTO = {
  review_id: string;
  source: string;
  rating: number | null;
  text_clean: string;
  date: string;
  lang: string | null;
  scrub_flags: string[];
  theme_id: string | null;
  theme_label: string | null;
};

export type ReviewList = {
  items: ReviewDTO[];
  next_cursor: string | null;
  total: number;
  window_reviews: number;
  clustered: number;
  dropped_low_signal: number;
  scrub_flag_counts: Record<string, number>;
};

export type RunSummary = {
  run_id: string;
  iso_week: string | null;
  timestamp: string | null;
  window: WindowDTO | null;
  counts: CountsDTO;
  word_count: number | null;
  theme_count: number;
  gates_passed: boolean;
  rejected: boolean;
  publish_mode: string;
  artifacts: string[];
  current: boolean;
};

export type RunDetail = {
  summary: RunSummary;
  note_preview: string | null;
  rejected: boolean;
  manifest_checks: Record<string, boolean>;
  publish: PublishSummary;
};

export type SettingsDTO = {
  package_id: string;
  window_weeks: number;
  min_words: number;
  english_only: boolean;
  operator_initials: string;
  recipient_alias: string;
  document_id: string;
  mcp_url: string;
  mcp_configured: boolean;
  mcp_token_configured: boolean;
  groq_configured: boolean;
  gemini_configured: boolean;
  groq_model: string;
  gemini_model: string;
  groq_hint: string | null;
  gemini_hint: string | null;
  embedding_model: string;
  linkage: string;
  store: string;
  schedule_weekday: string;
  schedule_hour: number;
  schedule_minute: number;
  schedule_timezone: string;
  schedule_window_weeks: number;
  schedule_send_email: boolean;
  schedule_skip_if_no_new: boolean;
  api_host: string;
  api_port: number;
};

export type SettingsPatch = Partial<
  Pick<
    SettingsDTO,
    | "window_weeks"
    | "min_words"
    | "english_only"
    | "operator_initials"
    | "recipient_alias"
    | "document_id"
    | "schedule_weekday"
    | "schedule_hour"
    | "schedule_minute"
    | "schedule_timezone"
    | "schedule_window_weeks"
    | "schedule_send_email"
    | "schedule_skip_if_no_new"
  >
>;
