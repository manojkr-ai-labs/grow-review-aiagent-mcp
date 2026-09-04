"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { formatNumber, formatPct, formatRating } from "@/lib/format";
import { useRunId } from "@/lib/useRunId";
import { useHeader } from "@/components/chrome/AppShell";
import { Card, CardHeader } from "@/components/ui/Card";
import { Chip } from "@/components/ui/Chip";
import { EmptyState, ErrorState } from "@/components/ui/EmptyState";
import { Icon } from "@/components/icons/Icon";
import type { ThemeDTO } from "@/lib/types";

type Filter = "all" | "negative" | "emerging" | "note";

export default function ThemesPage() {
  const runId = useRunId();
  const pulse = useQuery({ queryKey: ["pulse", runId], queryFn: () => api.pulse(runId) });
  const themes = useQuery({ queryKey: ["themes", runId], queryFn: () => api.themes(runId) });
  const [filter, setFilter] = useState<Filter>("all");
  const [sort, setSort] = useState<"priority" | "size" | "rating" | "trend">("priority");
  const [q, setQ] = useState("");

  useHeader({
    exportLabel: "Export Themes CSV",
    onExport: () => {
      if (!themes.data) return;
      const header = "rank,theme_id,label,size,mean_rating,neg_share,priority,trend,emerging\n";
      const rows = themes.data
        .map(
          (t) =>
            `${t.rank},${t.theme_id},"${t.label.replaceAll('"', '""')}",${t.size},${t.mean_rating ?? ""},${t.neg_share},${t.priority},${t.trend ?? ""},${t.emerging}`,
        )
        .join("\n");
      const blob = new Blob([header + rows], { type: "text/csv" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "themes.csv";
      a.click();
      URL.revokeObjectURL(url);
    },
  });

  const filtered = useMemo(() => {
    let list = themes.data ?? [];
    if (filter === "negative") list = list.filter((t) => t.neg_share >= 0.6);
    if (filter === "emerging") list = list.filter((t) => t.emerging);
    if (filter === "note") list = list.filter((t) => t.in_note || t.rank <= 3);
    if (q.trim()) {
      const needle = q.toLowerCase();
      list = list.filter((t) => t.label.toLowerCase().includes(needle) || t.keywords.join(" ").includes(needle));
    }
    const copy = [...list];
    copy.sort((a, b) => {
      if (sort === "size") return b.size - a.size;
      if (sort === "rating") return (a.mean_rating ?? 99) - (b.mean_rating ?? 99);
      if (sort === "trend") return (b.trend ?? 0) - (a.trend ?? 0);
      return b.priority - a.priority;
    });
    return copy;
  }, [themes.data, filter, sort, q]);

  if (themes.isError) return <ErrorState message="Could not load themes. Run a pulse first." />;
  if (!themes.data) return <div className="text-sm text-muted">Loading themes…</div>;
  if (themes.data.length === 0) {
    return <EmptyState title="No themes" body="Cluster a window of reviews to produce at most five themes." />;
  }

  const counts = pulse.data?.counts;
  const maxPriority = Math.max(...themes.data.map((t) => t.priority), 1);

  return (
    <div className="mx-auto max-w-[1440px] space-y-5">
      <Card className="flex flex-wrap items-center justify-between gap-4 p-4">
        <div className="flex flex-wrap gap-6">
          <Stat n={themes.data.length} label="Total clusters" />
          <Stat n={counts?.clustered ?? 0} label="Reviews analysed" />
          <Stat n={counts?.negative ?? 0} label="Negative friction" critical />
        </div>
        <span className="font-mono text-[11px] uppercase text-faint">
          Labels: Groq · Composition: Gemini · Clustering: MiniLM + ward
        </span>
      </Card>

      <div className="flex flex-col justify-between gap-3 lg:flex-row lg:items-center">
        <div className="flex flex-wrap gap-2">
          <FilterChip active={filter === "all"} onClick={() => setFilter("all")} label={`All (${themes.data.length})`} />
          <FilterChip
            active={filter === "negative"}
            onClick={() => setFilter("negative")}
            label={`High negative (${themes.data.filter((t) => t.neg_share >= 0.6).length})`}
          />
          <FilterChip
            active={filter === "emerging"}
            onClick={() => setFilter("emerging")}
            label={`Emerging (${themes.data.filter((t) => t.emerging).length})`}
          />
          <FilterChip
            active={filter === "note"}
            onClick={() => setFilter("note")}
            label={`Ranked in note (${themes.data.filter((t) => t.in_note || t.rank <= 3).length})`}
          />
        </div>
        <div className="flex gap-3">
          <select
            className="rounded-control border border-line bg-card px-3 py-1.5 text-xs text-ink focus:border-accent"
            value={sort}
            onChange={(e) => setSort(e.target.value as typeof sort)}
            aria-label="Sort themes"
          >
            <option value="priority">Sorted by: Impact (size × negative %)</option>
            <option value="size">Sorted by: Highest review volume</option>
            <option value="rating">Sorted by: Lowest average rating</option>
            <option value="trend">Sorted by: Emerging velocity</option>
          </select>
          <input
            className="w-64 rounded-control border border-line bg-canvas px-3 py-1.5 text-xs text-ink placeholder:text-faint focus:border-accent"
            placeholder="Search themes or cluster tags..."
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </div>
      </div>

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-12">
        <Card className="p-5 xl:col-span-4">
          <CardHeader title="Theme priority & impact ranking" />
          <p className="-mt-2 mb-4 px-0 text-sm text-muted">
            Priority index = volume × negative sentiment share. Rank 1 visually dominates.
          </p>
          <div className="space-y-3">
            {filtered.map((theme) => (
              <div key={theme.theme_id}>
                <div className="mb-1 flex justify-between font-mono text-xs">
                  <span className="text-ink">
                    {theme.rank}. {theme.label}
                  </span>
                  <span className="text-faint">{theme.priority.toFixed(0)}</span>
                </div>
                <div className="h-1.5 overflow-hidden rounded-full bg-nested">
                  <div
                    className="h-full bg-accent"
                    style={{ width: `${Math.max(8, (theme.priority / maxPriority) * 100)}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
        </Card>
        <div className="space-y-4 xl:col-span-8">
          {filtered.map((theme) => (
            <ThemeCard key={theme.theme_id} theme={theme} />
          ))}
        </div>
      </div>
    </div>
  );
}

function Stat({ n, label, critical }: { n: number; label: string; critical?: boolean }) {
  return (
    <div className="flex items-baseline gap-2">
      <span className={`font-mono text-xl font-bold nums ${critical ? "text-critical" : "text-ink"}`}>
        {formatNumber(n)}
      </span>
      <span className="font-mono text-[11px] uppercase text-faint">{label}</span>
    </div>
  );
}

function FilterChip({ active, label, onClick }: { active: boolean; label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-lg border px-3 py-1.5 font-mono text-xs uppercase ${
        active ? "border-accent bg-nested text-accent" : "border-line bg-card text-muted hover:text-ink"
      }`}
    >
      {label}
    </button>
  );
}

function ThemeCard({ theme }: { theme: ThemeDTO }) {
  return (
    <Link href={`/themes/${theme.theme_id}`} className="block">
      <Card className="p-5 hover:border-muted">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-xs text-accent">RANK {String(theme.rank).padStart(2, "0")}</span>
              <h3 className="text-base font-semibold">{theme.label}</h3>
              {theme.in_note || theme.rank <= 3 ? <Chip tone="accent">In weekly note</Chip> : null}
              {theme.emerging ? <Chip tone="warn">Emerging</Chip> : null}
            </div>
            <p className="mt-2 max-w-3xl font-serif text-sm leading-relaxed text-muted">{theme.summary}</p>
          </div>
          <Icon name="chevron_right" className="text-faint" />
        </div>
        <div className="mt-4 grid grid-cols-2 gap-3 text-sm md:grid-cols-5">
          <Meta label="Size" value={formatNumber(theme.size)} />
          <Meta label="Mean rating" value={formatRating(theme.mean_rating)} />
          <Meta label="Negative" value={formatPct(theme.neg_share)} />
          <Meta label="Priority" value={theme.priority.toFixed(0)} />
          <Meta label="Trend" value={theme.trend === null ? "—" : theme.trend.toFixed(2)} />
        </div>
      </Card>
    </Link>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="font-mono text-[10px] uppercase text-faint">{label}</div>
      <div className="font-mono text-sm nums text-ink">{value}</div>
    </div>
  );
}
