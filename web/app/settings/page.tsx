"use client";

import type { ReactNode } from "react";
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, api } from "@/lib/api";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Chip } from "@/components/ui/Chip";
import { ErrorState } from "@/components/ui/EmptyState";
import { Icon } from "@/components/icons/Icon";
import type { SettingsDTO, SettingsPatch } from "@/lib/types";

const WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"] as const;

type FormState = {
  window_weeks: number;
  min_words: number;
  english_only: boolean;
  operator_initials: string;
  recipient_alias: string;
  document_id: string;
  schedule_weekday: string;
  schedule_hour: number;
  schedule_minute: number;
  schedule_timezone: string;
  schedule_window_weeks: number;
  schedule_send_email: boolean;
  schedule_skip_if_no_new: boolean;
};

function fromDto(data: SettingsDTO): FormState {
  return {
    window_weeks: data.window_weeks,
    min_words: data.min_words,
    english_only: data.english_only,
    operator_initials: data.operator_initials,
    recipient_alias: data.recipient_alias,
    document_id: data.document_id,
    schedule_weekday: data.schedule_weekday,
    schedule_hour: data.schedule_hour,
    schedule_minute: data.schedule_minute,
    schedule_timezone: data.schedule_timezone,
    schedule_window_weeks: data.schedule_window_weeks,
    schedule_send_email: data.schedule_send_email,
    schedule_skip_if_no_new: data.schedule_skip_if_no_new,
  };
}

export default function SettingsPage() {
  const queryClient = useQueryClient();
  const settings = useQuery({ queryKey: ["settings"], queryFn: api.settings });
  const [form, setForm] = useState<FormState | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (settings.data) setForm(fromDto(settings.data));
  }, [settings.data]);

  const save = useMutation({
    mutationFn: (patch: SettingsPatch) => api.patchSettings(patch),
    onSuccess: (data) => {
      setForm(fromDto(data));
      setSaved(true);
      queryClient.setQueryData(["settings"], data);
      queryClient.invalidateQueries({ queryKey: ["status"] });
      window.setTimeout(() => setSaved(false), 2000);
    },
  });

  const mcp = useMutation({
    mutationFn: api.mcpCheck,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["status"] }),
  });

  if (settings.isError) return <ErrorState message="Could not load settings." />;
  if (!settings.data || !form) return <div className="text-sm text-muted">Loading settings…</div>;

  const data = settings.data;
  const saveError =
    save.error instanceof ApiError ? save.error.detail : save.error instanceof Error ? save.error.message : null;

  function patch<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((prev) => (prev ? { ...prev, [key]: value } : prev));
  }

  return (
    <div className="mx-auto max-w-[960px] space-y-6">
      <p className="text-sm text-muted">
        Non-secret keys from settings.toml. API keys and MCP_AUTH_TOKEN are never returned — rotate them in{" "}
        <code className="font-mono text-xs text-ink">.env</code>, not here.
      </p>
      {saveError ? <ErrorState message={saveError} /> : null}
      {saved ? <Chip tone="accent">Saved</Chip> : null}

      <Card className="space-y-4 p-5">
        <Section title="Application & ingestion" icon="tune" />
        <Field label="package_id" hint="Read-only Play listing">
          <div className="flex items-center justify-between rounded-control border border-line bg-canvas px-3 py-2">
            <span className="font-mono text-sm">{data.package_id}</span>
            <Chip>locked</Chip>
          </div>
        </Field>
        <Field label="Window weeks">
          <div className="grid grid-cols-3 gap-2 rounded-control border border-line p-1">
            {[4, 8, 12].map((n) => (
              <button
                key={n}
                type="button"
                onClick={() => patch("window_weeks", n)}
                className={`rounded-control py-1.5 font-mono text-sm ${
                  form.window_weeks === n ? "border border-accent text-accent" : "text-muted hover:text-ink"
                }`}
              >
                {n} weeks
              </button>
            ))}
          </div>
        </Field>
        <Field label="Min words" hint="Drop short praise before store">
          <div className="flex items-center justify-between rounded-control border border-line bg-canvas px-3 py-2">
            <span className="font-mono text-lg font-semibold nums">{form.min_words}</span>
            <div className="flex gap-1">
              <Button type="button" variant="icon" aria-label="Decrease min words" onClick={() => patch("min_words", Math.max(1, form.min_words - 1))}>
                −
              </Button>
              <Button type="button" variant="icon" aria-label="Increase min words" onClick={() => patch("min_words", form.min_words + 1)}>
                +
              </Button>
            </div>
          </div>
        </Field>
        <Toggle
          label="English-only ingest"
          hint="Rule-based language filter before embeddings"
          on={form.english_only}
          onChange={(v) => patch("english_only", v)}
        />
        <Field label="Operator initials">
          <input
            className="w-24 rounded-control border border-line bg-canvas px-3 py-2 font-mono text-sm uppercase"
            value={form.operator_initials}
            maxLength={4}
            onChange={(e) => patch("operator_initials", e.target.value)}
            aria-label="Operator initials"
          />
        </Field>
      </Card>

      <Card className="space-y-4 p-5">
        <Section title="Models (names + configured flags only)" icon="psychology" />
        <Row
          label="Theme labels"
          value={`Groq ${data.groq_model} · ${data.groq_configured ? `configured ${data.groq_hint || ""}` : "not configured"}`}
        />
        <Row
          label="Pulse compose"
          value={`Gemini ${data.gemini_model} · ${data.gemini_configured ? `configured ${data.gemini_hint || ""}` : "not configured"}`}
        />
        <Row label="Embeddings" value={`${data.embedding_model} · ${data.linkage} linkage`} />
        <Row label="Store" value={data.store} />
        <p className="text-xs text-faint">Hints show last-4 only. Secrets are not writable from this page.</p>
      </Card>

      <Card className="space-y-4 p-5">
        <Section title="MCP / Docs / Gmail" icon="cloud" />
        <Row label="MCP URL" value={data.mcp_url || "unset"} />
        <div className="flex flex-wrap gap-2">
          <Chip tone={data.mcp_configured ? "accent" : "critical"}>{data.mcp_configured ? "MCP configured" : "MCP missing"}</Chip>
          <Chip tone={data.mcp_token_configured ? "accent" : "warn"}>
            {data.mcp_token_configured ? "Token present" : "Token unset"}
          </Chip>
        </div>
        <Field label="Google Doc id">
          <input
            className="w-full rounded-control border border-line bg-canvas px-3 py-2 font-mono text-xs"
            value={form.document_id}
            onChange={(e) => patch("document_id", e.target.value)}
            aria-label="Google Doc id"
          />
        </Field>
        <Field label="Recipient alias">
          <input
            className="w-full rounded-control border border-line bg-canvas px-3 py-2 font-mono text-sm"
            value={form.recipient_alias}
            onChange={(e) => patch("recipient_alias", e.target.value)}
            aria-label="Recipient alias"
          />
        </Field>
        <Button
          type="button"
          variant="secondary"
          onClick={() => mcp.mutate()}
          disabled={mcp.isPending}
          aria-label="Test MCP"
        >
          <Icon name="wifi_tethering" size={16} />
          {mcp.isPending ? "Checking…" : "Test MCP"}
        </Button>
        {mcp.data ? (
          <Chip tone={mcp.data.ok ? "accent" : "critical"}>
            {mcp.data.label}
            {mcp.data.detail ? ` · ${mcp.data.detail}` : ""}
          </Chip>
        ) : null}
        {mcp.error ? (
          <ErrorState message={mcp.error instanceof Error ? mcp.error.message : "MCP check failed"} />
        ) : null}
      </Card>

      <Card className="space-y-4 p-5">
        <Section title="Weekly schedule" icon="calendar_month" />
        <Field label="Weekday">
          <select
            className="rounded-control border border-line bg-canvas px-3 py-2 text-sm"
            value={form.schedule_weekday}
            onChange={(e) => patch("schedule_weekday", e.target.value)}
            aria-label="Schedule weekday"
          >
            {WEEKDAYS.map((day) => (
              <option key={day} value={day}>
                {day}
              </option>
            ))}
          </select>
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Hour">
            <input
              type="number"
              min={0}
              max={23}
              className="w-full rounded-control border border-line bg-canvas px-3 py-2 font-mono"
              value={form.schedule_hour}
              onChange={(e) => patch("schedule_hour", Number(e.target.value))}
              aria-label="Schedule hour"
            />
          </Field>
          <Field label="Minute">
            <input
              type="number"
              min={0}
              max={59}
              className="w-full rounded-control border border-line bg-canvas px-3 py-2 font-mono"
              value={form.schedule_minute}
              onChange={(e) => patch("schedule_minute", Number(e.target.value))}
              aria-label="Schedule minute"
            />
          </Field>
        </div>
        <Field label="Timezone">
          <input
            className="w-full rounded-control border border-line bg-canvas px-3 py-2 font-mono text-sm"
            value={form.schedule_timezone}
            onChange={(e) => patch("schedule_timezone", e.target.value)}
            aria-label="Schedule timezone"
          />
        </Field>
        <Field label="Schedule window weeks">
          <input
            type="number"
            min={1}
            max={52}
            className="w-32 rounded-control border border-line bg-canvas px-3 py-2 font-mono"
            value={form.schedule_window_weeks}
            onChange={(e) => patch("schedule_window_weeks", Number(e.target.value))}
            aria-label="Schedule window weeks"
          />
        </Field>
        <Toggle label="Send email on schedule" hint="Uses MCP send_email" on={form.schedule_send_email} onChange={(v) => patch("schedule_send_email", v)} />
        <Toggle
          label="Skip if no new reviews"
          hint="Default off — a quiet week still gets a rolling-window pulse"
          on={form.schedule_skip_if_no_new}
          onChange={(v) => patch("schedule_skip_if_no_new", v)}
        />
        <Row label="Console bind" value={`${data.api_host}:${data.api_port}`} />
      </Card>

      <Button
        variant="primary"
        disabled={save.isPending}
        onClick={() => save.mutate(form)}
      >
        Save non-secret settings
      </Button>
    </div>
  );
}

function Section({ title, icon }: { title: string; icon: string }) {
  return (
    <div className="flex items-center gap-2 border-b border-line pb-3">
      <Icon name={icon} className="text-accent" />
      <h2 className="text-base font-semibold">{title}</h2>
    </div>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between">
        <label className="font-mono text-[11px] uppercase tracking-wider text-faint">{label}</label>
        {hint ? <span className="text-xs text-faint">{hint}</span> : null}
      </div>
      {children}
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
      <span className="font-mono text-[11px] uppercase text-faint">{label}</span>
      <span className="font-mono text-xs text-ink">{value}</span>
    </div>
  );
}

function Toggle({
  label,
  hint,
  on,
  onChange,
}: {
  label: string;
  hint: string;
  on: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-4 rounded-control border border-line bg-nested p-3">
      <div>
        <div className="text-sm font-medium">{label}</div>
        <div className="text-xs text-muted">{hint}</div>
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={on}
        aria-label={label}
        onClick={() => onChange(!on)}
        className={`relative h-6 w-11 rounded-full p-0.5 ${on ? "bg-accent" : "bg-line"}`}
      >
        <span className={`block h-5 w-5 rounded-full bg-canvas transition-transform ${on ? "translate-x-5" : ""}`} />
      </button>
    </div>
  );
}
