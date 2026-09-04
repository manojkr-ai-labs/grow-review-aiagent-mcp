import type { ReactNode } from "react";

type Tone = "accent" | "critical" | "warn" | "neutral" | "gold";

const tones: Record<Tone, string> = {
  accent: "bg-accent/10 border-accent/40 text-accent",
  critical: "bg-critical/10 border-critical/40 text-critical",
  warn: "bg-warn/10 border-warn/40 text-warn",
  neutral: "bg-nested border-line text-muted",
  gold: "bg-gold/10 border-gold/40 text-gold",
};

export function Chip({
  tone = "neutral",
  children,
  className = "",
}: {
  tone?: Tone;
  children: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-chip border px-2 py-0.5 font-mono text-[11px] font-semibold uppercase tracking-wider ${tones[tone]} ${className}`}
    >
      {children}
    </span>
  );
}
