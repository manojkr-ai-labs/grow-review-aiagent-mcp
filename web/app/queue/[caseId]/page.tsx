"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { api, type DeskCaseDetail, type DeskClaim } from "@/lib/api";
import { allowListedUrl, claimIsVerified, lastCheckedLabel } from "@/lib/deskView";
import { useHeader } from "@/components/chrome/AppShell";
import { Card, CardHeader } from "@/components/ui/Card";
import { Chip } from "@/components/ui/Chip";
import { ErrorState } from "@/components/ui/EmptyState";

export default function CasePage() {
  const params = useParams<{ caseId: string }>();
  const caseId = Array.isArray(params.caseId) ? params.caseId[0] : params.caseId;
  const loaded = useQuery({
    queryKey: ["desk-case", caseId],
    queryFn: () => api.deskCase(caseId),
    enabled: Boolean(caseId),
  });
  useHeader({ subtitle: caseId ? `Case ${caseId}` : "Case" });

  if (loaded.isError) {
    const message = loaded.error instanceof Error ? loaded.error.message : "Failed to load the case";
    return <ErrorState message={message} />;
  }
  if (!loaded.data) {
    return <div className="text-sm text-muted">Loading case…</div>;
  }

  const detail = loaded.data;
  const note = detail.routing_note;
  const notCovered = note ? note.facts_coverage === "not_covered" : detail.claims.length === 0;

  return (
    <div className="mx-auto max-w-[1440px] space-y-4">
      <Link href="/queue" className="text-sm text-accent">
        Back to queue
      </Link>
      <Link href={`/queue/${caseId}/approve`} className="text-sm text-accent">
        Approve, edit, or reject
      </Link>
      <Card>
        <CardHeader title="Reply" />
        <p className="px-5 py-4 text-sm text-ink">{detail.draft?.text || "No reply stored."}</p>
      </Card>
      <Card>
        <CardHeader title="Routing note" />
        {note ? <RoutingNoteView note={note} /> : <p className="px-5 py-4 text-sm text-muted">No routing note stored.</p>}
      </Card>
      <Card>
        <CardHeader title="Source panel" />
        <SourcePanel detail={detail} notCovered={notCovered} />
      </Card>
      <Card>
        <CardHeader title="Agent times" />
        <ul className="divide-y divide-line">
          {detail.agent_timings.length === 0 ? (
            <li className="px-5 py-4 text-sm text-muted">No agent times stored.</li>
          ) : (
            detail.agent_timings.map((item) => (
              <li key={`${item.agent}-${item.started_at}`} className="px-5 py-3 text-sm">
                <span className="font-semibold text-ink">{item.agent}</span>
                <span className="mt-1 block font-mono text-xs text-muted">
                  start {item.started_at || "not recorded"} · end {item.ended_at || "not recorded"}
                </span>
              </li>
            ))
          )}
        </ul>
      </Card>
    </div>
  );
}

function RoutingNoteView({ note }: { note: NonNullable<DeskCaseDetail["routing_note"]> }) {
  return (
    <dl className="grid gap-3 px-5 py-4 text-sm sm:grid-cols-2">
      <Field label="Team" value={note.team} />
      <Field label="Priority" value={note.priority} />
      <Field label="Coverage" value={note.facts_coverage} />
      <Field label="Pattern" value={`${note.pattern_signal} · count ${note.matching_count}`} />
      <Field label="Window" value={windowText(note.analysis_window)} />
      <Field label="Reason" value={note.reason} />
      <Field label="Next action" value={note.next_action} />
      {note.disagreement ? <Field label="Disagreement" value={note.disagreement} /> : null}
    </dl>
  );
}

function SourcePanel({ detail, notCovered }: { detail: DeskCaseDetail; notCovered: boolean }) {
  if (!notCovered) {
    return (
      <ul className="space-y-4 px-5 py-4">
        {detail.claims.map((claim) => (
          <li key={`${claim.source_url}-${claim.claim}`}>
            <ClaimView claim={claim} />
          </li>
        ))}
      </ul>
    );
  }
  return (
    <div className="px-5 py-4 text-sm">
      <p className="text-muted">Not verified. Pages searched</p>
      {detail.searched_urls.length === 0 ? (
        <p className="mt-2 text-ink">No pages stored.</p>
      ) : (
        <ul className="mt-2 space-y-1">
          {detail.searched_urls.map((url) => (
            <li key={url} className="break-all font-mono text-xs text-ink">
              {url}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ClaimView({ claim }: { claim: DeskClaim }) {
  const verified = claimIsVerified(claim);
  return (
    <div className="space-y-1 text-sm">
      <Chip tone={verified ? "accent" : "warn"}>{verified ? "Verified" : "Not verified"}</Chip>
      <p className="text-ink">{claim.claim}</p>
      {verified ? (
        <a href={claim.source_url} className="break-all font-mono text-xs text-accent">
          {claim.source_url}
        </a>
      ) : (
        <p className="font-mono text-xs text-muted">
          {allowListedUrl(claim.source_url) ? claim.source_url : "Link is not on the Groww allow list."}
        </p>
      )}
      <p className="text-xs text-muted">Last checked {lastCheckedLabel(claim.last_checked)}</p>
    </div>
  );
}

function windowText(window: { start: string | null; end: string | null } | null | undefined): string {
  if (!window) return "window unavailable";
  if (window.start && window.end) return `${window.start} → ${window.end}`;
  return window.start || window.end || "window unavailable";
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wider text-faint">{label}</dt>
      <dd className="text-ink">{value}</dd>
    </div>
  );
}
