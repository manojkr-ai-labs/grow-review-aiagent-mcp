"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode, Suspense } from "react";
import { api } from "@/lib/api";
import { formatWindow, relativeTime, storeRun } from "@/lib/format";
import { Icon } from "@/components/icons/Icon";
import { Button } from "@/components/ui/Button";
import { Chip } from "@/components/ui/Chip";

const NAV = [
  { href: "/", label: "Weekly Pulse", icon: "monitoring", mobile: true },
  { href: "/themes", label: "Themes", icon: "category", mobile: true },
  { href: "/reviews", label: "Reviews", icon: "rate_review", mobile: true },
  { href: "/pipeline", label: "Pipeline", icon: "account_tree", mobile: true },
  { href: "/runs", label: "Runs", icon: "history", mobile: true },
  { href: "/publish", label: "Publish", icon: "publish", mobile: false },
  { href: "/settings", label: "Settings", icon: "settings", mobile: false },
] as const;

const TITLES: Record<string, string> = {
  "/": "Weekly Review Pulse",
  "/themes": "Themes & Issue Clusters",
  "/reviews": "Reviews",
  "/pipeline": "Pipeline",
  "/runs": "Runs / Job Execution History",
  "/publish": "Publish",
  "/settings": "Settings & Runtime Configuration",
};

type HeaderState = {
  exportLabel?: string;
  onExport?: () => void;
  subtitle?: string;
};

const HeaderCtx = createContext<{
  setHeader: (state: HeaderState) => void;
}>({ setHeader: () => undefined });

export function useHeader(state: HeaderState) {
  const ctx = useContext(HeaderCtx);
  const onExportRef = useRef(state.onExport);
  onExportRef.current = state.onExport;
  const hasExport = Boolean(state.onExport);
  useEffect(() => {
    ctx.setHeader({
      exportLabel: state.exportLabel,
      subtitle: state.subtitle,
      onExport: hasExport ? () => onExportRef.current?.() : undefined,
    });
    return () => ctx.setHeader({});
  }, [ctx, state.exportLabel, state.subtitle, hasExport]);
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [header, setHeader] = useState<HeaderState>({});
  const [more, setMore] = useState(false);
  const status = useQuery({ queryKey: ["status"], queryFn: api.status, refetchInterval: 8000 });
  const run = useMutation({
    mutationFn: () => api.runPipeline({ dry_run: true, send: false }),
    onSuccess: (job) => {
      storeRun(null);
      queryClient.invalidateQueries();
      router.push(`/pipeline?job=${job.job_id}`);
    },
  });

  const data = status.data;
  const mcpOk = data?.mcp.ok ?? false;
  const running = data?.pipeline?.status === "running" || data?.pipeline?.status === "queued" || run.isPending;
  const title =
    TITLES[pathname] ||
    (pathname.startsWith("/themes/") ? "Theme detail" : "ReviewPulse");
  const headerApi = useMemo(() => ({ setHeader }), []);

  return (
    <HeaderCtx.Provider value={headerApi}>
      <div className="min-h-screen bg-canvas text-ink">
        <aside className="fixed inset-y-0 left-0 z-40 hidden w-60 flex-col justify-between border-r border-line bg-rail p-4 md:flex">
          <div className="space-y-6">
            <div className="flex items-center justify-between border-b border-line pb-4">
              <div className="flex items-center gap-2.5">
                <span className="relative flex h-2.5 w-2.5">
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-accent opacity-60" />
                  <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-accent" />
                </span>
                <div>
                  <div className="text-sm font-bold tracking-tight">ReviewPulse</div>
                  <div className="font-mono text-[10px] uppercase tracking-wider text-faint">Groww · Play Store</div>
                </div>
              </div>
              <Chip tone="accent">LIVE</Chip>
            </div>
            <nav aria-label="Console" className="space-y-1">
              {NAV.map((item) => {
                const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={`flex items-center gap-3 rounded-r px-3 py-2 text-sm transition-colors duration-150 ${
                      active
                        ? "border-l-2 border-accent bg-nested text-accent"
                        : "text-muted hover:bg-nested hover:text-ink"
                    }`}
                  >
                    <Icon name={item.icon} filled={active} className={active ? "text-accent" : "text-faint"} />
                    <span className={active ? "font-semibold text-ink" : ""}>{item.label}</span>
                  </Link>
                );
              })}
            </nav>
          </div>
          <div className="space-y-2 border-t border-line pt-4 font-mono text-[11px] uppercase tracking-wider text-faint">
            <div className="flex items-center justify-between px-1">
              <span className="flex items-center gap-1.5">
                <Icon name="calendar_today" size={14} />
                {data?.iso_week || "ISO —"}
              </span>
              <Chip tone={mcpOk ? "accent" : "critical"}>{mcpOk ? "STABLE" : "MCP DOWN"}</Chip>
            </div>
            <div className="flex items-center gap-1.5 px-1">
              <Icon name="schedule" size={14} />
              Last run: {relativeTime(data?.last_run_at)}
            </div>
          </div>
        </aside>

        <header className="sticky top-0 z-30 flex items-center justify-between gap-3 border-b border-line bg-rail/95 px-4 py-3 backdrop-blur md:ml-60 md:px-6">
          <div className="min-w-0">
            <h1 className="truncate text-lg font-semibold tracking-tight">{title}</h1>
            <div className="mt-1 hidden flex-wrap items-center gap-2 sm:flex">
              {data?.window ? (
                <Chip>
                  <Icon name="date_range" size={12} />
                  {formatWindow(data.window.weeks, data.window.actual_start, data.window.actual_end)}
                </Chip>
              ) : null}
              <Chip tone={mcpOk ? "accent" : "critical"}>
                <span className={`h-1.5 w-1.5 rounded-full ${mcpOk ? "bg-accent animate-pulse" : "bg-critical"}`} />
                MCP: {data?.mcp.label || "UNKNOWN"}
              </Chip>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {header.onExport ? (
              <Button variant="secondary" className="hidden sm:inline-flex" onClick={header.onExport}>
                <Icon name="download" size={16} />
                {header.exportLabel || "Export"}
              </Button>
            ) : null}
            <Button variant="primary" disabled={running} onClick={() => run.mutate()} aria-label="Run pipeline dry-run">
              <Icon name={running ? "progress_activity" : "play_arrow"} size={16} />
              {running ? "Running…" : "Run Pipeline"}
            </Button>
            <div
              className="hidden h-8 w-8 items-center justify-center rounded-control border border-line bg-nested font-mono text-xs font-bold text-accent sm:flex"
              title="Operator"
            >
              {data?.operator_initials || "MK"}
            </div>
          </div>
        </header>

        <main className="bg-grid-subtle min-h-[calc(100vh-57px)] px-4 py-6 pb-24 md:ml-60 md:px-6 md:pb-6">
          {status.isError ? (
            <div className="mb-4 rounded-card border border-warn/40 bg-warn/10 p-3 text-sm text-warn">
              Console API unreachable. Start `reviewpulse serve` on port 8000.
            </div>
          ) : null}
          <Suspense fallback={<div className="text-sm text-muted">Loading…</div>}>{children}</Suspense>
        </main>

        <nav
          aria-label="Mobile"
          className="fixed inset-x-0 bottom-0 z-40 flex border-t border-line bg-rail md:hidden"
        >
          {NAV.filter((item) => item.mobile).map((item) => {
            const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`flex min-h-[44px] min-w-[54px] flex-1 flex-col items-center justify-center py-1 text-[10px] uppercase tracking-wider ${
                  active ? "border-t-2 border-accent text-accent" : "text-muted"
                }`}
              >
                <Icon name={item.icon} filled={active} size={18} />
                {item.label.replace("Weekly ", "")}
              </Link>
            );
          })}
          <button
            type="button"
            className="flex min-w-[54px] flex-col items-center justify-center text-[10px] uppercase tracking-wider text-muted"
            onClick={() => setMore((v) => !v)}
            aria-label="More"
          >
            <Icon name="more_horiz" />
            More
          </button>
        </nav>
        {more ? (
          <div className="fixed inset-x-0 bottom-14 z-40 border-t border-line bg-card p-3 md:hidden">
            <Link href="/publish" className="block px-3 py-2 text-sm text-ink" onClick={() => setMore(false)}>
              Publish
            </Link>
            <Link href="/settings" className="block px-3 py-2 text-sm text-ink" onClick={() => setMore(false)}>
              Settings
            </Link>
          </div>
        ) : null}
      </div>
    </HeaderCtx.Provider>
  );
}

export function useStatus() {
  return useQuery({ queryKey: ["status"], queryFn: api.status, refetchInterval: 8000 });
}
