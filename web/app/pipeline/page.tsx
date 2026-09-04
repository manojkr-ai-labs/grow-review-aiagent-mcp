"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, api } from "@/lib/api";
import { formatIst, formatNumber, storeRun } from "@/lib/format";
import { useRunId } from "@/lib/useRunId";
import { useStatus } from "@/components/chrome/AppShell";
import { Button } from "@/components/ui/Button";
import { Card, CardHeader } from "@/components/ui/Card";
import { Chip } from "@/components/ui/Chip";
import { ConfirmModal } from "@/components/ui/ConfirmModal";
import { ErrorState } from "@/components/ui/EmptyState";
import { Icon } from "@/components/icons/Icon";
import type { StageDTO } from "@/lib/types";

const WINDOWS = [4, 8, 12] as const;

const FALLBACK_STAGES: StageDTO[] = [
  { id: "fetch", label: "Fetch Play reviews", status: "idle", detail: "google-play-scraper → data/raw/" },
  { id: "ingest", label: "Ingest & cleanse", status: "idle", detail: "PII scrub → SQLite" },
  { id: "cluster", label: "Cluster", status: "idle", detail: "MiniLM + ward linkage" },
  { id: "pulse", label: "Pulse synthesis", status: "idle", detail: "Gemini gemini-3.6-flash" },
  { id: "validate", label: "Validate", status: "idle", detail: "Seven gates before publish" },
  { id: "publish", label: "Publish & dispatch", status: "idle", detail: "MCP Docs + Gmail" },
];

export default function PipelinePage() {
  const router = useRouter();
  const search = useSearchParams();
  const queryClient = useQueryClient();
  const runId = useRunId();
  const status = useStatus();
  const pulse = useQuery({ queryKey: ["pulse", runId], queryFn: () => api.pulse(runId) });
  const [weeks, setWeeks] = useState(12);
  const [dryRun, setDryRun] = useState(true);
  const [lines, setLines] = useState<string[]>([]);
  const [confirmSend, setConfirmSend] = useState(false);
  const jobId = search.get("job") || status.data?.pipeline?.job_id || null;

  const job = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => api.job(jobId!),
    enabled: Boolean(jobId),
    refetchInterval: (query) => {
      const state = query.state.data?.status;
      return state === "queued" || state === "running" ? 1200 : false;
    },
  });

  useEffect(() => {
    if (!jobId) return;
    setLines([]);
    const source = new EventSource(api.jobLogUrl(jobId));
    source.onmessage = (event) => {
      try {
        setLines((prev) => [...prev, String(JSON.parse(event.data))]);
      } catch {
        setLines((prev) => [...prev, event.data]);
      }
    };
    source.addEventListener("done", (event) => {
      try {
        const payload = JSON.parse((event as MessageEvent).data) as { run_id?: string | null };
        if (payload.run_id) storeRun(payload.run_id);
      } catch {
        /* ignore */
      }
      queryClient.invalidateQueries();
      source.close();
    });
    source.onerror = () => {
      if (source.readyState === EventSource.CLOSED) {
        return;
      }
    };
    return () => source.close();
  }, [jobId, queryClient]);

  const start = useMutation({
    mutationFn: (send: boolean) => api.runPipeline({ window_weeks: weeks, dry_run: dryRun && !send, send }),
    onSuccess: (created) => {
      storeRun(null);
      queryClient.invalidateQueries({ queryKey: ["status"] });
      router.push(`/pipeline?job=${created.job_id}`);
    },
  });

  const live = job.data;
  const running =
    live?.status === "queued" || live?.status === "running" || status.data?.lock_held || start.isPending;
  const pipelineStatus = running
    ? "RUNNING"
    : live?.status === "failed"
      ? "FAILED"
      : live?.status === "succeeded"
        ? "SUCCEEDED"
        : "IDLE / READY";
  const stages = pulse.data?.stages?.length ? pulse.data.stages : FALLBACK_STAGES;
  const startError = start.error instanceof ApiError ? start.error.detail : start.error instanceof Error ? start.error.message : null;

  const tone = useMemo(() => {
    if (pipelineStatus === "RUNNING") return "warn" as const;
    if (pipelineStatus === "FAILED") return "critical" as const;
    if (pipelineStatus === "SUCCEEDED") return "accent" as const;
    return "neutral" as const;
  }, [pipelineStatus]);

  return (
    <div className="mx-auto max-w-[1520px] space-y-6">
      <Card className="flex flex-wrap items-center justify-between gap-4 p-4">
        <div className="flex flex-wrap items-center gap-4">
          <span className="font-mono text-[11px] uppercase tracking-wider text-faint">Window</span>
          <div className="inline-flex rounded-lg border border-line bg-nested p-0.5">
            {WINDOWS.map((value) => (
              <button
                key={value}
                type="button"
                className={`rounded-control px-2.5 py-1 font-mono text-xs uppercase ${
                  weeks === value ? "border border-line bg-card font-semibold text-accent" : "text-muted hover:text-ink"
                }`}
                onClick={() => setWeeks(value)}
                disabled={running}
              >
                {value === 12 ? "12 weeks" : `${value}w`}
              </button>
            ))}
          </div>
          <div className="h-5 w-px bg-line" />
          <label className="flex items-center gap-2 text-sm">
            <span className="font-mono text-[11px] uppercase tracking-wider text-ink">Dry-run</span>
            <button
              type="button"
              role="switch"
              aria-checked={dryRun}
              disabled={running}
              onClick={() => setDryRun((v) => !v)}
              className={`relative h-5 w-9 rounded-full p-0.5 transition-colors ${dryRun ? "bg-accent" : "bg-line"}`}
            >
              <span className={`block h-4 w-4 rounded-full bg-canvas transition-transform ${dryRun ? "translate-x-4" : ""}`} />
            </button>
          </label>
          {dryRun ? (
            <Chip tone="warn">
              Dry-run writes SQLite + runs/ only. No Google Doc or Gmail write.
            </Chip>
          ) : (
            <Chip tone="critical">Live MCP publish enabled</Chip>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <Chip tone={tone}>Pipeline: {pipelineStatus}</Chip>
          <Button
            variant="primary"
            disabled={running}
            onClick={() => start.mutate(false)}
            aria-label="Run full pipeline"
          >
            <Icon name={running ? "progress_activity" : "sync"} size={16} />
            Run full pipeline
          </Button>
          <div className="relative" title={dryRun ? "Disabled while dry-run is on" : "Live send_email via MCP"}>
            <Button variant="danger" disabled={running || dryRun} onClick={() => setConfirmSend(true)}>
              <Icon name="lock" size={16} />
              Run with send
            </Button>
          </div>
        </div>
      </Card>

      {startError ? <ErrorState message={startError === "lock_held" ? "Pipeline lock is held — another job is running." : startError} /> : null}

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-12">
        <div className="space-y-4 xl:col-span-7">
          <div className="flex items-center gap-2">
            <Icon name="low_priority" className="text-accent" />
            <h2 className="text-base font-semibold">Execution stages</h2>
          </div>
          {stages.map((stage) => (
            <Card key={stage.id} className="flex items-start gap-4 p-4">
              <span
                className={`mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border ${
                  stage.status === "ok"
                    ? "border-accent bg-accent text-canvas"
                    : stage.status === "failed"
                      ? "border-critical bg-critical/20 text-critical"
                      : running
                        ? "border-warn text-warn"
                        : "border-line text-faint"
                }`}
              >
                <Icon
                  name={stage.status === "ok" ? "check" : stage.status === "failed" ? "close" : "circle"}
                  size={16}
                />
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex items-center justify-between gap-2">
                  <h3 className="text-sm font-semibold">{stage.label}</h3>
                  <span className="font-mono text-[11px] uppercase text-faint">{stage.status}</span>
                </div>
                <p className="mt-1 font-mono text-xs text-muted">{stage.detail}</p>
                <p className="mt-2 text-[11px] text-faint">
                  Step run is display-only in v1 — trigger the full pipeline above.
                </p>
              </div>
            </Card>
          ))}
        </div>

        <Card className="flex min-h-[480px] flex-col overflow-hidden xl:col-span-5">
          <CardHeader
            title="Live log"
            icon={<Icon name="terminal" className="text-accent" />}
            action={
              <Chip>
                {live ? `${live.window_weeks}w · ${live.dry_run ? "dry-run" : live.send ? "send" : "draft"}` : "idle"}
              </Chip>
            }
          />
          <pre className="flex-1 overflow-auto bg-canvas p-4 font-mono text-[11px] leading-5 text-muted">
            {lines.length
              ? lines.join("\n")
              : jobId
                ? "Waiting for log stream…"
                : "No job selected. Run the pipeline to stream orchestrator output."}
            {live?.error ? `\n[error] ${live.error}` : ""}
          </pre>
          <div className="flex items-center justify-between border-t border-line px-4 py-2 font-mono text-[11px] text-faint">
            <span>
              {live?.run_id ? `run ${live.run_id}` : "no run yet"} · {formatNumber(lines.length)} lines
            </span>
            <span>
              {live?.started_at ? formatIst(live.started_at) : "—"}
              {live?.finished_at ? ` → ${formatIst(live.finished_at)}` : ""}
            </span>
          </div>
        </Card>
      </div>

      <ConfirmModal
        open={confirmSend}
        title="Run pipeline with send?"
        body="This will fetch, cluster, compose, append the Google Doc, and send the weekly email via MCP. Same-week send is skipped if a message_id is already stored."
        confirmLabel="Run with send"
        danger
        onCancel={() => setConfirmSend(false)}
        onConfirm={() => {
          setConfirmSend(false);
          setDryRun(false);
          start.mutate(true);
        }}
      />
    </div>
  );
}
