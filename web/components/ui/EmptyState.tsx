import { Icon } from "../icons/Icon";
import { Button } from "./Button";

export function EmptyState({
  title,
  body,
  cta,
  onCta,
}: {
  title: string;
  body: string;
  cta?: string;
  onCta?: () => void;
}) {
  return (
    <div className="flex flex-col items-start gap-3 rounded-card border border-line bg-card p-8">
      <Icon name="inbox" className="text-faint" size={22} />
      <h2 className="text-lg font-semibold text-ink">{title}</h2>
      <p className="max-w-xl text-sm text-muted">{body}</p>
      {cta && onCta ? (
        <Button variant="primary" onClick={onCta}>
          {cta}
        </Button>
      ) : null}
    </div>
  );
}

export function ErrorState({ message }: { message: string }) {
  return (
    <div className="rounded-card border border-critical/40 bg-critical/10 p-4 text-sm text-critical" role="alert">
      {message}
    </div>
  );
}
