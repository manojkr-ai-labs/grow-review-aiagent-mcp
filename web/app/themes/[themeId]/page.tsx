"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { formatNumber, formatPct, formatRating } from "@/lib/format";
import { useRunId } from "@/lib/useRunId";
import { useHeader } from "@/components/chrome/AppShell";
import { Card } from "@/components/ui/Card";
import { Chip } from "@/components/ui/Chip";
import { ErrorState } from "@/components/ui/EmptyState";
import { Icon } from "@/components/icons/Icon";
import { KpiCard } from "@/components/ui/KpiCard";
import { QuoteCallout } from "@/components/ui/QuoteCallout";
import { StarRating } from "@/components/ui/StarRating";

export default function ThemeDetailPage() {
  const params = useParams<{ themeId: string }>();
  const themeId = params.themeId;
  const runId = useRunId();
  const detail = useQuery({
    queryKey: ["theme", themeId, runId],
    queryFn: () => api.theme(themeId, runId),
  });
  const reviews = useQuery({
    queryKey: ["theme-reviews", themeId, runId],
    queryFn: () => api.reviews({ theme_id: themeId, limit: 50 }, runId),
  });
  const pulse = useQuery({ queryKey: ["pulse", runId], queryFn: () => api.pulse(runId) });

  useHeader({
    exportLabel: "Export Theme CSV",
    onExport: () => {
      if (!reviews.data) return;
      const header = "review_id,date,rating,text_clean,scrub_flags\n";
      const rows = reviews.data.items
        .map(
          (r) =>
            `${r.review_id},${r.date},${r.rating ?? ""},"${r.text_clean.replaceAll('"', '""')}",${r.scrub_flags.join("|")}`,
        )
        .join("\n");
      const blob = new Blob([header + rows], { type: "text/csv" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${themeId}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    },
  });

  if (detail.isError) return <ErrorState message="Theme not found on this run." />;
  if (!detail.data) return <div className="text-sm text-muted">Loading theme…</div>;

  const theme = detail.data.theme;
  const quote = pulse.data?.quotes.find((item) => item.theme_id === themeId);
  const hist = detail.data.rating_histogram;
  const maxBar = Math.max(...Object.values(hist), 1);

  return (
    <div className="mx-auto max-w-[1520px] space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Link href="/themes" className="inline-flex items-center gap-1.5 text-sm text-muted hover:text-accent">
          <Icon name="arrow_back" size={16} />
          Back to Themes
        </Link>
        <div className="flex flex-wrap gap-2">
          <Chip tone={theme.rank === 1 ? "critical" : "neutral"}>
            Rank {String(theme.rank).padStart(2, "0")}
          </Chip>
          {detail.data.in_note ? <Chip tone="accent">In weekly note</Chip> : null}
          {theme.emerging ? <Chip tone="warn">Emerging</Chip> : <Chip>Persistent</Chip>}
        </div>
      </div>

      <Card className="space-y-5 p-6">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">{theme.label}</h1>
          <p className="mt-2 max-w-4xl text-base text-muted">{theme.summary}</p>
        </div>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3 lg:grid-cols-5">
          <KpiCard label="Review volume" value={formatNumber(theme.size)} />
          <KpiCard label="Mean rating" value={formatRating(theme.mean_rating)} />
          <KpiCard label="Negative share" value={formatPct(theme.neg_share)} />
          <KpiCard label="Priority" value={theme.priority.toFixed(0)} />
          <KpiCard label="Trend (late/early)" value={theme.trend === null ? "—" : theme.trend.toFixed(2)} />
        </div>
      </Card>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-12">
        <Card className="p-5 xl:col-span-5">
          <h2 className="mb-4 text-sm font-semibold">Rating distribution</h2>
          <div className="space-y-2">
            {[5, 4, 3, 2, 1].map((star) => (
              <div key={star} className="flex items-center gap-3">
                <span className="w-6 font-mono text-xs">{star}★</span>
                <div className="h-2 flex-1 overflow-hidden rounded-full bg-nested">
                  <div
                    className={`h-full ${star <= 2 ? "bg-critical" : star === 3 ? "bg-warn" : "bg-accent"}`}
                    style={{ width: `${((hist[star] || hist[String(star)] || 0) / maxBar) * 100}%` }}
                  />
                </div>
                <span className="w-10 text-right font-mono text-xs nums">
                  {hist[star] || hist[String(star)] || 0}
                </span>
              </div>
            ))}
          </div>
        </Card>
        <Card className="p-5 xl:col-span-7">
          <h2 className="mb-4 text-sm font-semibold">Salient keywords</h2>
          <div className="flex flex-wrap gap-2">
            {(theme.top_terms.length ? theme.top_terms : theme.keywords).map((term) => (
              <Chip key={term}>{term}</Chip>
            ))}
          </div>
          {quote ? (
            <div className="mt-6">
              <QuoteCallout meta={`${quote.rating ?? "—"}★ · verbatim`}>“{quote.text}”</QuoteCallout>
            </div>
          ) : null}
        </Card>
      </div>

      <Card className="overflow-hidden">
        <div className="border-b border-line px-5 py-3.5">
          <h2 className="text-base font-semibold">Member reviews</h2>
          <p className="text-sm text-muted">Scrubbed text only · {formatNumber(reviews.data?.total ?? theme.size)} in cluster</p>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-line bg-rail font-mono text-[11px] uppercase text-faint">
                <th className="px-4 py-2.5">Date</th>
                <th className="px-4 py-2.5">Rating</th>
                <th className="px-4 py-2.5">Text</th>
                <th className="px-4 py-2.5">Flags</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {(reviews.data?.items || []).map((review) => (
                <tr key={review.review_id} className="hover:bg-nested">
                  <td className="whitespace-nowrap px-4 py-3 font-mono text-xs nums">{review.date.slice(0, 10)}</td>
                  <td className="px-4 py-3">
                    <StarRating value={review.rating} />
                  </td>
                  <td className="max-w-xl px-4 py-3 text-muted">{review.text_clean}</td>
                  <td className="px-4 py-3 font-mono text-xs text-faint">
                    {review.scrub_flags.length ? review.scrub_flags.join(", ") : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
