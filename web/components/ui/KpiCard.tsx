import type { ReactNode } from "react";
import { Card } from "./Card";

export function KpiCard({
  label,
  value,
  hint,
  footer,
  icon,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  footer?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <Card className="flex flex-col justify-between p-5">
      <div className="flex items-center justify-between">
        <span className="font-mono text-[11px] font-semibold uppercase tracking-wider text-faint">
          {label}
        </span>
        {icon}
      </div>
      <div className="mt-3">
        <div className="font-mono text-[1.25rem] font-medium tracking-tight text-ink nums">{value}</div>
        {hint ? <div className="mt-1 text-sm text-muted">{hint}</div> : null}
      </div>
      {footer ? (
        <div className="mt-3 flex items-center justify-between border-t border-line pt-2.5 font-mono text-xs text-faint">
          {footer}
        </div>
      ) : null}
    </Card>
  );
}
