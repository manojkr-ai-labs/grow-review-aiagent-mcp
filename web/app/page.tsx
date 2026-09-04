"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { formatNumber, formatPct, formatRating } from "@/lib/format";
import { useRunId } from "@/lib/useRunId";
import { useHeader } from "@/components/chrome/AppShell";
import { Card, CardHeader } from "@/components/ui/Card";
import { Chip } from "@/components/ui/Chip";
import { EmptyState, ErrorState } from "@/components/ui/EmptyState";
import { GateList } from "@/components/ui/GateList";
import { Icon } from "@/components/icons/Icon";
import { KpiCard } from "@/components/ui/KpiCard";
import { QuoteCallout } from "@/components/ui/QuoteCallout";

export default function PulsePage() {
  const runId = useRunId();
  const pulse = useQuery({ queryKey: ["pulse", runId], queryFn: () => api.pulse(runId) });

  useHeader({
    exportLabel: "Export Brief",
    onExport: () => {
      if (!pulse.data) return;
      window.location.href = api.noteUrl(pulse.data.run_id);
    },
  });

  if (pulse.isError) {
    const message = pulse.error instanceof Error ? pulse.error.message : "Failed to load pulse";
    if (message.includes("no runs")) {
      return (
        <EmptyState
          title="No pulse yet"
          body="Run a dry-run pipeline to cluster reviews and compose the weekly note."
          cta="Run Pipeline (dry-run)"
          onCta={() => api.runPipeline({ dry_run: true, send: false })}
        />
      );
    }
    return <ErrorState message={message} />;
  }
  if (!pulse.data) {
    return <div className="text-sm text-muted">Loading pulse…</div>;
  }

  const data = pulse.data;
  const rank1 = data.top_themes[0];
  const budget = data.max_words ? Math.round((data.word_count / data.max_words) * 100) : 0;

  return (
    <div className="mx-auto max-w-[1440px] space-y-6">
      <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard
          label="Reviews analysed"
          value={formatNumber(data.counts.clustered)}
          hint={`from ${formatNumber(data.counts.window_reviews)} in window · ${formatNumber(data.counts.dropped_low_signal)} dropped praise`}
          footer={
            <>
              <span>Signal filter</span>
              <span className="text-accent">
                {data.counts.window_reviews
                  ? formatPct(data.counts.clustered / data.counts.window_reviews, 1)
                  : "—"}{" "}
                kept
              </span>
            </>
          }
          icon={<Icon name="query_stats" className="text-faint" />}
        />
        <KpiCard
          label="Average rating"
          value={<span className={data.mean_rating !== null && data.mean_rating < 3 ? "text-critical" : ""}>{formatRating(data.mean_rating)}</span>}
          hint="Clustered corpus, not Play listing average"
          footer={
            <>
              <span>Window</span>
              <span>
                {data.window.actual_start} → {data.window.actual_end}
              </span>
            </>
          }
        />
        <KpiCard
          label="Top theme share"
          value={
            rank1 && data.counts.clustered
              ? formatPct(rank1.size / data.counts.clustered)
              : "—"
          }
          hint={rank1 ? `${rank1.label} · ${formatNumber(rank1.size)} reviews` : "No themes"}
          footer={
            <>
              <span>Mean rating</span>
              <span className="text-critical">{rank1 ? formatRating(rank1.mean_rating) : "—"}</span>
            </>
          }
        />
        <KpiCard
          label="Editorial budget"
          value={
            <>
              {data.word_count} <span className="text-sm font-normal text-muted">/ {data.max_words} words</span>
            </>
          }
          hint={
            <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-nested">
              <div className="h-full bg-accent" style={{ width: `${Math.min(budget, 100)}%` }} />
            </div>
          }
          footer={
            <>
              <span>Synthesis</span>
              <span className="text-ink">
                {data.compose_model || data.compose_source || "heuristic"}
              </span>
            </>
          }
        />
      </section>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-12">
        <div className="space-y-6 xl:col-span-8">
          <Card>
            <CardHeader
              title="Top themes this week"
              icon={<Icon name="category" className="text-accent" />}
              action={<Chip>{data.top_themes.length} in note</Chip>}
            />
            <div className="divide-y divide-line">
              {data.top_themes.map((theme) => (
                <Link
                  key={theme.theme_id}
                  href={`/themes/${theme.theme_id}`}
                  className="flex flex-col gap-2 px-5 py-4 hover:bg-nested"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-xs text-accent">RANK {String(theme.rank).padStart(2, "0")}</span>
                    <h3 className="font-semibold text-ink">{theme.label}</h3>
                    {theme.emerging ? <Chip tone="warn">Emerging</Chip> : null}
                  </div>
                  <p className="text-sm text-muted">{theme.line || theme.summary}</p>
                  <div className="flex flex-wrap gap-3 font-mono text-xs text-faint">
                    <span>{formatNumber(theme.size)} reviews</span>
                    <span>{formatRating(theme.mean_rating)}</span>
                    <span>{formatPct(theme.neg_share)} negative</span>
                  </div>
                </Link>
              ))}
            </div>
          </Card>

          <Card>
            <CardHeader title="What users said" icon={<Icon name="format_quote" className="text-accent" />} />
            <div className="space-y-4 p-5">
              {data.quotes.map((quote) => {
                const theme = data.top_themes.find((item) => item.theme_id === quote.theme_id);
                return (
                  <QuoteCallout
                    key={quote.review_id}
                    meta={`Theme ${quote.theme_id} · ${theme?.label || ""} · ${quote.rating ?? "—"}★ · verbatim`}
                  >
                    “{quote.text}”
                  </QuoteCallout>
                );
              })}
            </div>
          </Card>

          <Card>
            <CardHeader title="Three things to do next" icon={<Icon name="task_alt" className="text-accent" />} />
            <ol className="space-y-3 p-5">
              {data.actions.map((action, index) => (
                <li key={`${action.text}-${index}`} className="flex gap-3 text-sm text-ink">
                  <span className="font-mono text-accent">{index + 1}.</span>
                  <span>
                    {action.text}
                    <span className="mt-1 block font-mono text-[11px] uppercase tracking-wider text-faint">
                      {action.theme_ids.join(", ")}
                    </span>
                  </span>
                </li>
              ))}
            </ol>
          </Card>
        </div>

        <div className="space-y-6 xl:col-span-4">
          <Card>
            <CardHeader
              title="Pulse health"
              icon={<Icon name="verified" className="text-accent" />}
              action={
                <Chip tone={data.all_gates_passed ? "accent" : "critical"}>
                  {data.gates_passed}/{data.gates_total} verified
                </Chip>
              }
            />
            <div className="p-5">
              <GateList gates={data.gates} passed={data.gates_passed} total={data.gates_total} />
              {data.rejected ? (
                <p className="mt-3 text-sm text-critical">
                  Gates failed — nothing published.{" "}
                  <a className="underline" href={api.noteUrl(data.run_id)}>
                    Open rejected note
                  </a>
                </p>
              ) : null}
            </div>
          </Card>

          <Card>
            <CardHeader
              title="Delivery & dispatch"
              icon={<Icon name="send" className="text-accent" />}
              action={<Chip tone={data.publish.mode === "dry-run" ? "warn" : "accent"}>{data.publish.mode}</Chip>}
            />
            <div className="space-y-3 p-5 text-sm">
              <div>
                <div className="font-mono text-[10px] uppercase text-faint">Target artifact</div>
                {data.publish.doc_url ? (
                  <a className="mt-1 flex items-center gap-2 text-ink hover:text-accent" href={data.publish.doc_url} target="_blank" rel="noreferrer">
                    <Icon name="description" size={16} className="text-accent" />
                    Groww Weekly Review Pulse [{data.publish.idempotency_key}]
                    <Icon name="open_in_new" size={14} />
                  </a>
                ) : (
                  <p className="mt-1 text-muted">Local dry-run — no Google Doc write.</p>
                )}
              </div>
              <div>
                <div className="font-mono text-[10px] uppercase text-faint">Gmail</div>
                <p className="mt-1 font-mono text-xs text-ink">{data.publish.recipient || "recipient unset"}</p>
              </div>
              <div className="grid grid-cols-3 gap-2 pt-2">
                <Link href={`/runs?run=${data.run_id}`} className="rounded-control border border-line px-2 py-1.5 text-center text-xs hover:bg-nested">
                  Open note
                </Link>
                {data.all_gates_passed ? (
                  <Link href="/publish" className="rounded-control bg-accent px-2 py-1.5 text-center text-xs font-semibold text-canvas">
                    Publish live
                  </Link>
                ) : (
                  <span className="cursor-not-allowed rounded-control border border-line px-2 py-1.5 text-center text-xs text-faint">
                    Publish live
                  </span>
                )}
                <Link href="/publish" className="rounded-control border border-line px-2 py-1.5 text-center text-xs hover:bg-nested">
                  Send email
                </Link>
              </div>
            </div>
          </Card>

          <Card>
            <CardHeader
              title="Pipeline telemetry"
              icon={<Icon name="account_tree" className="text-accent" />}
              action={<Chip>{data.stages.length} stages</Chip>}
            />
            <ol className="relative space-y-4 p-5 pl-8 before:absolute before:bottom-6 before:left-[26px] before:top-6 before:w-px before:bg-line">
              {data.stages.map((stage) => (
                <li key={stage.id} className="relative">
                  <span
                    className={`absolute -left-6 top-0.5 flex h-4 w-4 items-center justify-center rounded-full ${
                      stage.status === "ok" ? "bg-accent text-canvas" : stage.status === "failed" ? "bg-critical" : "bg-line"
                    }`}
                  >
                    <Icon name={stage.status === "ok" ? "check" : "circle"} size={12} />
                  </span>
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-medium text-ink">{stage.label}</span>
                    <span className="font-mono text-xs text-faint">{stage.status}</span>
                  </div>
                  <p className="font-mono text-xs text-muted">{stage.detail}</p>
                </li>
              ))}
            </ol>
          </Card>
        </div>
      </div>
    </div>
  );
}
