import type { HTMLAttributes, ReactNode } from "react";

export function Card({
  className = "",
  children,
  ...props
}: HTMLAttributes<HTMLDivElement> & { children: ReactNode }) {
  return (
    <div
      className={`rounded-card border border-line bg-card ${className}`}
      {...props}
    >
      {children}
    </div>
  );
}

export function CardHeader({
  title,
  icon,
  action,
}: {
  title: string;
  icon?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-line bg-rail/60 px-5 py-3.5">
      <div className="flex items-center gap-2">
        {icon}
        <h2 className="font-sans text-base font-semibold tracking-tight text-ink">{title}</h2>
      </div>
      {action}
    </div>
  );
}
