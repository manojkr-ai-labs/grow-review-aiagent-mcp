"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { formatIst, formatNumber, storeRun } from "@/lib/format";
import { useRunId } from "@/lib/useRunId";
import { useHeader } from "@/components/chrome/AppShell";
import { Card, CardHeader } from "@/components/ui/Card";
import { Chip } from "@/components/ui/Chip";
import { EmptyState, ErrorState } from "@/components/ui/EmptyState";
import { Icon } from "@/components/icons/Icon";
import type { RunSummary } from "@/lib/types";

const MAX_WORDS = 250;

type Filter = "all" | "success" | "dry-run" | "gated";

function matches(run: RunSummary, filter: Filter, needle: string): boolean {
  if (filter === "success" && (!run.gates_passed || run.rejected)) return false;
  if (filter === "dry-run" && run.publish_mode !== "dry-run") return false;
  if (filter === "gated" && !(run.rejected || !run.gates_passed)) return false;
  if (!needle) return true;
  const hay = `${run.run_id} ${run.iso_week ?? ""}`.toLowerCase();
  return hay.includes(needle);
}

function publishTone(mode: string): "accent" | "warn" | "critical" | "neutral" {
  if (mode === "sent" || mode === "draft") return "accent";
  if (mode === "dry-run") return "warn";
  if (mode === "gated") return "critical";
  return "neutral";
}

function artifactIcon(name: string): string {
  if (name.includes("rejected")) return "report";
  if (name.startsWith("note")) return "description";
  if (name === "manifest.json") return "receipt_long";
  if (name === "clusters.json") return "hub";
  if (name === "publish.json") return "data_object";
  if (name.includes("debug")) return "bug_report";
  return "draft";
}

function artifactHint(name: string): string {
  if (name === "note.md") return "Weekly pulse markdown for the selected run.";
  if (name === "note.rejected.md") return "Rejected note after a failed gate. Nothing was published.";
  if (name === "manifest.json") return "Pipeline execution manifest and gate checks.";
  if (name === "clusters.json") return "Theme clustering output (ward + MiniLM).";
  if (name === "publish.json") return "MCP publish payload (Docs append / Gmail).";
  return "Run artifact.";
}

function noteDownloadable(name: string): boolean {
  return name === "note.md" || name === "note.rejected.md";
}

export default function RunsPage() {
  const router = useRouter();
  const search = useSearchParams();
  const runId = useRunId();
  const [filter, setFilter] = useState<Filter>("all");
  const [q, setQ] = useState("");
  const [copied, setCopied] = useState<string | null>(null);

  const runs = useQuery({ queryKey: ["runs"], queryFn: api.runs });

  const selectedId = useMemo(() => {
    if (!runs.data?.length) return null;
    if (runId && runs.data.some((item) => item.run_id === runId)) return runId;
    return runs.data.find((item) => item.current)?.run_id ?? runs.data[0].run_id;
  }, [runs.data, runId]);

  const detail = useQuery({
    queryKey: ["run", selectedId],
    queryFn: () => api.run(selectedId!),
    enabled: Boolean(selectedId),
  });

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return (runs.data ?? []).filter((item) => matches(item, filter, needle));
  }, [runs.data, filter, q]);

  const counts = useMemo(() => {
    const list = runs.data ?? [];
    return {
      all: list.length,
      success: list.filter((item) => item.gates_passed && !item.rejected).length,
      dry: list.filter((item) => item.publish_mode === "dry-run").length,
      gated: list.filter((item) => item.rejected || !item.gates_passed).length,
    };
  }, [runs.data]);

  const selected = runs.data?.find((item) => item.run_id === selectedId) ?? null;
  const hasNote = Boolean(selected?.artifacts.some(noteDownloadable));

  useHeader({
    exportLabel: "Export note",
    onExport: hasNote && selectedId ? () => { window.location.href = api.noteUrl(selectedId); } : undefined,
  });

  function inspect(id: string) {
    storeRun(id);
    const next = new URLSearchParams(search.toString());
    next.set("run", id);
    router.replace(`/runs?${next.toString()}`, { scroll: false });
  }

  async function copyId(id: string) {
    try {
      await navigator.clipboard.writeText(id);
      setCopied(id);
      window.setTimeout(() => setCopied((prev) => (prev === id ? null : prev)), 1600);
    } catch {
      /* clipboard may be denied */
    }
  }

  if (runs.isError) return <ErrorState message="Could not load run history." />;
  if (!runs.data) return <div className="text-sm text-muted">Loading runs…</div>;
  if (runs.data.length === 0) {
    return (
      <EmptyState
        title="No runs yet"
        body="Run a dry-run pipeline to write artifacts under runs/ and inspect them here."
        cta="Run Pipeline (dry-run)"
        onCta={() => {
          void api.runPipeline({ dry_run: true, send: false });
          router.push("/pipeline");
        }}
      />
    );
  }

  const checkEntries = Object.entries(detail.data?.manifest_checks ?? {});
  const checksPassed = checkEntries.filter(([, ok]) => ok).length;

  return (
    <div className="mx-auto max-w-[1520px] space-y-4">
      <Card className="flex flex-wrap items-center justify-between gap-3 p-3">
        <div className="flex flex-wrap gap-2">
          <FilterChip active={filter === "all"} onClick={() => setFilter("all")} label="All runs" count={counts.all} />
          <FilterChip
            active={filter === "success"}
            onClick={() => setFilter("success")}
            label="Successful"
            count={counts.success}
            tone="accent"
          />
          <FilterChip
            active={filter === "dry-run"}
            onClick={() => setFilter("dry-run")}
            label="Dry-run"
            count={counts.dry}
            tone="warn"
          />
          <FilterChip
            active={filter === "gated"}
            onClick={() => setFilter("gated")}
            label="Failed / gated"
            count={counts.gated}
            tone="critical"
          />
        </div>
        <div className="relative min-w-[220px] flex-1 sm:max-w-xs">
          <Icon name="search" className="absolute left-3 top-1/2 -translate-y-1/2 text-faint" size={16} />
          <input
            className="w-full rounded-control border border-line bg-canvas py-1.5 pl-9 pr-3 font-mono text-xs text-ink placeholder:text-faint"
            placeholder="Search run id or ISO week…"
            value={q}
            onChange={(event) => setQ(event.target.value)}
            aria-label="Search runs"
          />
        </div>
      </Card>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-12">
        <Card className="overflow-hidden xl:col-span-8">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-line bg-rail font-mono text-[11px] uppercase tracking-wider text-faint">
                  <th className="px-4 py-2.5">Run ID</th>
                  <th className="px-3 py-2.5">ISO week</th>
                  <th className="px-3 py-2.5">Window</th>
                  <th className="px-3 py-2.5">Reviews</th>
                  <th className="px-3 py-2.5">Themes</th>
                  <th className="px-3 py-2.5">Word count</th>
                  <th className="px-3 py-2.5">Gates</th>
                  <th className="px-3 py-2.5">Publish mode</th>
                  <th className="px-3 py-2.5">Timestamp</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {filtered.map((run) => {
                  const active = run.run_id === selectedId;
                  const words = run.word_count ?? 0;
                  const over = run.word_count != null && run.word_count > MAX_WORDS;
                  const pct = Math.min(100, Math.round((words / MAX_WORDS) * 100));
                  return (
                    <tr
                      key={run.run_id}
                      className={`cursor-pointer transition-colors duration-150 ${
                        run.rejected
                          ? "border-l-2 border-l-critical bg-critical/5 hover:bg-critical/10"
                          : active
                            ? "border-l-2 border-l-accent bg-nested hover:bg-nested"
                            : "hover:bg-nested"
                      }`}
                      onClick={() => inspect(run.run_id)}
                    >
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <span className={`font-mono text-xs ${run.rejected ? "text-critical" : active ? "text-accent" : "text-ink"}`}>
                            {run.run_id}
                          </span>
                          <button
                            type="button"
                            className="text-faint hover:text-accent"
                            title="Copy run id"
                            aria-label={`Copy ${run.run_id}`}
                            onClick={(event) => {
                              event.stopPropagation();
                              void copyId(run.run_id);
                            }}
                          >
                            <Icon name={copied === run.run_id ? "check" : "content_copy"} size={14} />
                          </button>
                        </div>
                        {active ? (
                          <div className="mt-0.5 font-mono text-[10px] uppercase tracking-wider text-accent">
                            Current inspection target
                          </div>
                        ) : run.rejected ? (
                          <div className="mt-0.5 flex items-center gap-1 text-[11px] text-critical">
                            <Icon name="warning" size={12} />
                            Gate failure
                          </div>
                        ) : null}
                      </td>
                      <td className="whitespace-nowrap px-3 py-3 font-mono text-xs">{run.iso_week || "—"}</td>
                      <td className="whitespace-nowrap px-3 py-3 font-mono text-xs text-muted">
                        {run.window ? (
                          <>
                            <span>{run.window.weeks}w</span>
                            {run.window.actual_weeks != null && run.window.actual_weeks !== run.window.weeks ? (
                              <span className="block text-[10px] text-faint">{run.window.actual_weeks}w act</span>
                            ) : null}
                          </>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="px-3 py-3">
                        <div className="font-mono text-xs nums">{formatNumber(run.counts.clustered)}</div>
                        <div className="font-mono text-[10px] uppercase text-faint">
                          from {formatNumber(run.counts.window_reviews)}
                        </div>
                      </td>
                      <td className="px-3 py-3">
                        <Chip>{run.theme_count} themes</Chip>
                      </td>
                      <td className="px-3 py-3">
                        <div className={`font-mono text-xs nums ${over ? "text-critical" : ""}`}>
                          {run.word_count == null ? "—" : `${formatNumber(run.word_count)}`}
                          <span className="text-faint"> / {MAX_WORDS}w</span>
                        </div>
                        {run.word_count != null ? (
                          <div className="mt-1 h-1 w-20 overflow-hidden rounded-full bg-nested">
                            <div
                              className={`h-full ${over ? "bg-critical" : "bg-accent"}`}
                              style={{ width: `${pct}%` }}
                            />
                          </div>
                        ) : null}
                      </td>
                      <td className="px-3 py-3">
                        <Chip tone={run.gates_passed && !run.rejected ? "accent" : "critical"}>
                          {run.gates_passed && !run.rejected ? "Passed" : "Failed"}
                        </Chip>
                      </td>
                      <td className="px-3 py-3">
                        <Chip tone={publishTone(run.publish_mode)}>{run.publish_mode || "none"}</Chip>
                      </td>
                      <td className="whitespace-nowrap px-3 py-3 font-mono text-xs text-muted">
                        {formatIst(run.timestamp)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="flex items-center justify-between border-t border-line px-4 py-3 font-mono text-[11px] text-faint">
            <span>
              Showing {formatNumber(filtered.length)} of {formatNumber(runs.data.length)} runs · SQLite store, not a live job log
            </span>
            {copied ? <span className="text-accent">Copied {copied}</span> : <span>Select a row to inspect artifacts</span>}
          </div>
        </Card>

        <Card className="flex min-h-[480px] flex-col overflow-hidden xl:col-span-4">
          <CardHeader
            title="Artifact inspector"
            icon={<Icon name="folder_open" className="text-accent" />}
            action={selected ? <Chip tone={selected.rejected ? "critical" : "accent"}>{selected.publish_mode}</Chip> : null}
          />
          {!selected ? (
            <p className="p-5 text-sm text-muted">Select a run to inspect its artifacts.</p>
          ) : (
            <div className="flex flex-1 flex-col overflow-hidden">
              <div className="space-y-3 border-b border-line p-5">
                <div className="flex items-start justify-between gap-2">
                  <h3 className="break-all font-mono text-sm font-semibold text-ink">{selected.run_id}</h3>
                  <button
                    type="button"
                    className="shrink-0 text-faint hover:text-accent"
                    title="Copy run id"
                    aria-label="Copy selected run id"
                    onClick={() => void copyId(selected.run_id)}
                  >
                    <Icon name="content_copy" size={16} />
                  </button>
                </div>
                <div className="flex flex-wrap gap-2">
                  {selected.iso_week ? <Chip>{selected.iso_week}</Chip> : null}
                  <Chip tone={selected.gates_passed && !selected.rejected ? "accent" : "critical"}>
                    {selected.rejected ? "Rejected" : selected.gates_passed ? "Gates passed" : "Gates failed"}
                  </Chip>
                </div>
                <div className="flex flex-wrap gap-2 text-xs">
                  <Link href={`/?run=${encodeURIComponent(selected.run_id)}`} className="rounded-control border border-line px-2 py-1 hover:bg-nested">
                    Open pulse
                  </Link>
                  <Link href={`/publish?run=${encodeURIComponent(selected.run_id)}`} className="rounded-control border border-line px-2 py-1 hover:bg-nested">
                    Publish
                  </Link>
                  {hasNote ? (
                    <a href={api.noteUrl(selected.run_id)} className="rounded-control border border-line px-2 py-1 hover:bg-nested">
                      Download note
                    </a>
                  ) : null}
                </div>
              </div>

              <div className="flex-1 space-y-3 overflow-y-auto p-5">
                <p className="font-mono text-[11px] uppercase tracking-wider text-faint">
                  Artifacts ({selected.artifacts.length})
                </p>
                {selected.artifacts.length === 0 ? (
                  <p className="text-sm text-muted">No artifact files on disk for this run.</p>
                ) : (
                  selected.artifacts.map((name) => (
                    <div key={name} className="rounded-control border border-line bg-nested p-3">
                      <div className="flex items-start justify-between gap-2">
                        <div className="flex items-start gap-2.5">
                          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-control border border-line bg-card text-accent">
                            <Icon name={artifactIcon(name)} size={16} />
                          </span>
                          <div>
                            <div className="font-mono text-xs font-semibold text-ink">{name}</div>
                            <p className="mt-0.5 text-xs text-muted">{artifactHint(name)}</p>
                          </div>
                        </div>
                        {noteDownloadable(name) ? (
                          <a
                            href={api.noteUrl(selected.run_id)}
                            className="shrink-0 text-faint hover:text-accent"
                            title={`Download ${name}`}
                            aria-label={`Download ${name}`}
                          >
                            <Icon name="download" size={16} />
                          </a>
                        ) : null}
                      </div>
                    </div>
                  ))
                )}

                {detail.isError ? <ErrorState message="Could not load run detail." /> : null}

                {checkEntries.length ? (
                  <div className="rounded-control border border-line p-3">
                    <p className="font-mono text-[11px] uppercase tracking-wider text-faint">
                      Manifest checks {checksPassed}/{checkEntries.length}
                    </p>
                    <ul className="mt-2 space-y-1">
                      {checkEntries.map(([gate, ok]) => (
                        <li key={gate} className="flex items-center justify-between font-mono text-[11px]">
                          <span className="text-muted">{gate}</span>
                          <span className={ok ? "text-accent" : "text-critical"}>{ok ? "pass" : "fail"}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}

                {selected.rejected ? (
                  <div className="rounded-control border border-critical/40 bg-critical/10 p-3 text-sm text-critical">
                    Gates failed — MCP publish was not attempted. Open the rejected note if it exists.
                  </div>
                ) : null}

                {detail.data?.note_preview ? (
                  <div>
                    <p className="mb-2 font-mono text-[11px] uppercase tracking-wider text-faint">Note preview</p>
                    <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded-control border border-line bg-canvas p-3 font-mono text-[11px] leading-5 text-muted">
                      {detail.data.note_preview}
                    </pre>
                  </div>
                ) : null}
              </div>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}

function FilterChip({
  active,
  onClick,
  label,
  count,
  tone = "neutral",
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  count: number;
  tone?: "accent" | "warn" | "critical" | "neutral";
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`inline-flex items-center gap-1.5 rounded-control border px-2.5 py-1 font-mono text-[11px] uppercase tracking-wider ${
        active ? "border-line bg-nested text-accent" : "border-line bg-card text-muted hover:text-ink"
      }`}
    >
      <span className={tone === "critical" && !active ? "text-critical" : ""}>{label}</span>
      <span className="rounded bg-canvas px-1.5 py-0.5 text-ink">{formatNumber(count)}</span>
    </button>
  );
}
