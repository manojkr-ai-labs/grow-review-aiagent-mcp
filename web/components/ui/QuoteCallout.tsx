import type { ReactNode } from "react";

export function QuoteCallout({
  children,
  meta,
}: {
  children: ReactNode;
  meta?: ReactNode;
}) {
  return (
    <figure className="rounded-r border border-line border-l-2 border-l-accent bg-nested/80 py-3 pl-4 pr-4">
      <blockquote className="font-serif text-lg italic leading-relaxed text-ink">{children}</blockquote>
      {meta ? <figcaption className="mt-2 font-mono text-[11px] uppercase tracking-wider text-faint">{meta}</figcaption> : null}
    </figure>
  );
}
