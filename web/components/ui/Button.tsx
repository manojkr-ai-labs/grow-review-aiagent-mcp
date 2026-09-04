import type { ButtonHTMLAttributes, ReactNode } from "react";

type Variant = "primary" | "secondary" | "danger" | "ghost" | "icon";

const styles: Record<Variant, string> = {
  primary:
    "h-[38px] px-3.5 bg-accent text-canvas font-semibold hover:bg-accent-hover active:scale-[0.98] disabled:opacity-50",
  secondary:
    "h-[38px] px-3 bg-card text-ink border border-line hover:bg-nested hover:border-muted disabled:opacity-50",
  danger:
    "h-[38px] px-3 bg-transparent text-critical border border-critical hover:bg-critical/10 disabled:opacity-50",
  ghost:
    "h-8 px-2.5 bg-nested text-ink border border-line hover:border-muted text-xs disabled:opacity-50",
  icon: "h-8 w-8 p-0 bg-card text-muted border border-line hover:text-ink hover:border-muted disabled:opacity-50",
};

export function Button({
  variant = "secondary",
  className = "",
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; children: ReactNode }) {
  return (
    <button
      className={`inline-flex items-center justify-center gap-1.5 rounded-control text-sm transition-colors duration-150 ${styles[variant]} ${className}`}
      {...props}
    >
      {children}
    </button>
  );
}
