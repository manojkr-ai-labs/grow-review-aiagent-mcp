"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { formatNumber, formatPct, shortId } from "@/lib/format";
import { useRunId } from "@/lib/useRunId";
import { useHeader } from "@/components/chrome/AppShell";
import { Card } from "@/components/ui/Card";
import { Chip } from "@/components/ui/Chip";
import { EmptyState, ErrorState } from "@/components/ui/EmptyState";
import { Icon } from "@/components/icons/Icon";
import { KpiCard } from "@/components/ui/KpiCard";
import { StarRating } from "@/components/ui/StarRating";
import type { ReviewDTO } from "@/lib/types";

export default function ReviewsPage() {
  const runId = useRunId();
  const [q, setQ] = useState("");
  const [rating, setRating] = useState<string>("all");
  const [themeId, setThemeId] = useState<string>("all");
  const [scrubbed, setScrubbed] = useState<string>("all");
  const [cursor, setCursor] = useState<string | null>(null);
  const [selected, setSelected] = useState<ReviewDTO | null>(null);

  const themes = useQuery({ queryKey: ["themes", runId], queryFn: () => api.themes(runId) });
  const reviews = useQuery({
    queryKey: ["reviews", runId, q, rating, themeId, scrubbed, cursor],
    queryFn: () =>
      api.reviews(
        {
          q: q || undefined,
          rating: rating === "all" ? undefined : Number(rating),
          theme_id: themeId === "all" ? undefined : themeId,
          scrubbed: scrubbed === "all" ? undefined : scrubbed === "yes",
          cursor: cursor || undefined,
          limit: 50,
        },
        runId,
      ),
  });

  useHeader({
    exportLabel: "Export CSV",
    onExport: () => {
      if (!reviews.data) return;
      const header = "review_id,date,rating,theme_id,text_clean,scrub_flags\n";
      const rows = reviews.data.items
        .map(
          (r) =>
            `${r.review_id},${r.date},${r.rating ?? ""},${r.theme_id ?? ""},"${r.text_clean.replaceAll('"', '""')}",${r.scrub_flags.join("|")}`,
        )
        .join("\n");
      const blob = new Blob([header + rows], { type: "text/csv" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "reviews.csv";
      a.click();
      URL.revokeObjectURL(url);
    },
  });

  const keptPct = useMemo(() => {
    const total = reviews.data?.window_reviews || 0;
    const clustered = reviews.data?.clustered || 0;
    return total ? clustered / total : 0;
  }, [reviews.data]);

  if (reviews.isPending) return <div className="text-sm text-muted">Loading reviews…</div>;
  if (reviews.isError) {
    const message = reviews.error instanceof Error ? reviews.error.message : "Failed to load reviews";
    if (message.toLowerCase().includes("unable") || message.includes("no such table")) {
      return <EmptyState title="Store empty" body="Ingest Play reviews first: reviewpulse ingest --window-weeks 12" />;
    }
    return <ErrorState message={message} />;
  }

  const data = reviews.data;

  return (
    <div className="mx-auto max-w-[1440px] space-y-6">
      <section className="grid grid-cols-1 gap-4 md:grid-cols-4">
        <KpiCard label="Total in window" value={formatNumber(data?.window_reviews)} hint="Scrubbed SQLite rows" />
        <KpiCard
          label="Clustered / kept"
          value={formatNumber(data?.clustered)}
          hint={`${formatPct(keptPct, 1)} of window`}
        />
        <KpiCard label="Dropped praise" value={formatNumber(data?.dropped_low_signal)} hint="Low-signal filter" />
        <KpiCard
          label="Compliance shield"
          value="PII scrubbed"
          hint="No names, emails, or phones stored"
          footer={
            <>
              <span>Flags</span>
              <span>
                {Object.entries(data?.scrub_flag_counts || {})
                  .map(([k, v]) => `${k}:${v}`)
                  .join(" · ") || "none"}
              </span>
            </>
          }
        />
      </section>

      <Card className="flex flex-wrap items-center gap-3 p-3">
        <div className="relative min-w-[280px] flex-1">
          <Icon name="search" className="absolute left-3 top-1/2 -translate-y-1/2 text-faint" size={16} />
          <input
            className="w-full rounded-control border border-line bg-canvas py-1.5 pl-9 pr-3 text-sm text-ink placeholder:text-faint focus:border-accent"
            placeholder="Search review text or review_id…"
            value={q}
            onChange={(e) => {
              setCursor(null);
              setQ(e.target.value);
            }}
          />
        </div>
        <select className="rounded-control border border-line bg-card px-2 py-1.5 text-xs" value={rating} onChange={(e) => { setCursor(null); setRating(e.target.value); }} aria-label="Filter rating">
          <option value="all">All ratings</option>
          {[1, 2, 3, 4, 5].map((n) => (
            <option key={n} value={n}>{n}★</option>
          ))}
        </select>
        <select className="rounded-control border border-line bg-card px-2 py-1.5 text-xs" value={themeId} onChange={(e) => { setCursor(null); setThemeId(e.target.value); }} aria-label="Filter theme">
          <option value="all">All themes</option>
          {(themes.data || []).map((t) => (
            <option key={t.theme_id} value={t.theme_id}>{t.label}</option>
          ))}
        </select>
        <select className="rounded-control border border-line bg-card px-2 py-1.5 text-xs" value={scrubbed} onChange={(e) => { setCursor(null); setScrubbed(e.target.value); }} aria-label="Filter scrubbed">
          <option value="all">All rows</option>
          <option value="yes">Scrubbed only</option>
          <option value="no">No flags</option>
        </select>
      </Card>

      <Card className="overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-line bg-rail font-mono text-[11px] uppercase text-faint">
                <th className="px-4 py-2.5">ID</th>
                <th className="px-4 py-2.5">Date</th>
                <th className="px-4 py-2.5">Rating</th>
                <th className="px-4 py-2.5">Theme</th>
                <th className="px-4 py-2.5">Text</th>
                <th className="px-4 py-2.5">Flags</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {(data?.items || []).map((review) => (
                <tr
                  key={review.review_id}
                  className="h-12 cursor-pointer hover:bg-nested"
                  onClick={() => setSelected(review)}
                >
                  <td className="px-4 font-mono text-xs text-accent">{shortId(review.review_id)}</td>
                  <td className="whitespace-nowrap px-4 font-mono text-xs nums">{review.date.slice(0, 10)}</td>
                  <td className="px-4"><StarRating value={review.rating} /></td>
                  <td className="max-w-[12rem] truncate px-4 text-muted">{review.theme_label || "—"}</td>
                  <td className="max-w-xl truncate px-4 text-ink">{review.text_clean}</td>
                  <td className="px-4 font-mono text-xs text-faint">{review.scrub_flags.join(", ") || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="flex items-center justify-between border-t border-line px-4 py-3 text-sm text-muted">
          <span>{formatNumber(data?.total)} matching · page of 50</span>
          <button
            type="button"
            className="rounded-control border border-line px-3 py-1 disabled:opacity-40"
            disabled={!data?.next_cursor}
            onClick={() => setCursor(data?.next_cursor ?? null)}
          >
            Next page
          </button>
        </div>
      </Card>

      {selected ? (
        <div className="fixed inset-y-0 right-0 z-40 w-full max-w-md overflow-y-auto border-l border-line bg-card p-5 shadow-[0_8px_24px_-4px_rgba(0,0,0,0.85)]">
          <div className="flex items-center justify-between">
            <h2 className="text-base font-semibold">Review</h2>
            <button type="button" onClick={() => setSelected(null)} aria-label="Close" className="text-muted hover:text-ink">
              <Icon name="close" />
            </button>
          </div>
          <p className="mt-2 font-mono text-xs text-accent break-all">{selected.review_id}</p>
          <div className="mt-4 flex gap-2">
            <StarRating value={selected.rating} />
            <Chip>{selected.date.slice(0, 10)}</Chip>
            {selected.theme_label ? <Chip tone="accent">{selected.theme_label}</Chip> : null}
          </div>
          <p className="mt-4 text-sm leading-relaxed text-ink">{selected.text_clean}</p>
          <p className="mt-4 font-mono text-xs text-faint">
            Flags: {selected.scrub_flags.length ? selected.scrub_flags.join(", ") : "none"} · author never stored
          </p>
        </div>
      ) : null}
    </div>
  );
}
