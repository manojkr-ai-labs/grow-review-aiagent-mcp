const IST = "Asia/Kolkata";

export function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat("en-IN").format(value);
}

export function formatRating(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${value.toFixed(2)}★`;
}

export function formatPct(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${(value * 100).toFixed(digits)}%`;
}

export function formatWindow(weeks: number, start?: string | null, end?: string | null): string {
  if (start && end) {
    return `${weeks} weeks · ${formatDay(start)} → ${formatDay(end)}`;
  }
  return `${weeks} weeks`;
}

export function formatDay(iso: string): string {
  const date = new Date(`${iso.slice(0, 10)}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return iso;
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  }).format(date);
}

export function formatIst(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: IST,
  }).format(date) + " IST";
}

export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return "never";
  const date = new Date(iso);
  const delta = Date.now() - date.getTime();
  if (Number.isNaN(delta)) return "—";
  const minutes = Math.round(delta / 60000);
  if (minutes < 1) return "Just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return `${days}d ago`;
}

export function shortId(id: string, keep = 8): string {
  if (id.length <= keep + 6) return id;
  return `${id.slice(0, keep)}…${id.slice(-4)}`;
}

const RUN_KEY = "reviewpulse.run_id";

export function readStoredRun(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(RUN_KEY);
}

export function storeRun(runId: string | null): void {
  if (typeof window === "undefined") return;
  if (!runId) window.localStorage.removeItem(RUN_KEY);
  else window.localStorage.setItem(RUN_KEY, runId);
}
