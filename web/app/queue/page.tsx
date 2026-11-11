"use client";

import Link from "next/link";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, api, type DeskQueueRow } from "@/lib/api";
import { useHeader } from "@/components/chrome/AppShell";
import { Button } from "@/components/ui/Button";
import { Card, CardHeader } from "@/components/ui/Card";
import { Chip } from "@/components/ui/Chip";
import { EmptyState, ErrorState } from "@/components/ui/EmptyState";

const CHIP_ORDER = ["Personal data", "Advice", "Complaint", "Fact", "Not covered"] as const;

export function queueChips(row: DeskQueueRow): Array<(typeof CHIP_ORDER)[number]> {
  const present = new Set<string>();
  if (row.pii_redacted || row.redaction_blocked) present.add("Personal data");
  if (row.compliance_decision === "refuse") present.add("Advice");
  if ((row.pattern_signal === "recurring" || row.pattern_signal === "rising") && row.theme_id) {
    present.add("Complaint");
  }
  if (row.coverage === "covered") present.add("Fact");
  if (row.not_covered || row.coverage === "not_covered") present.add("Not covered");
  return CHIP_ORDER.filter((chip) => present.has(chip));
}

function windowLabel(row: DeskQueueRow): string {
  if (row.window_start && row.window_end) return `${row.window_start} → ${row.window_end}`;
  return row.window_start || row.window_end || "window unavailable";
}

function queueAction(row: DeskQueueRow): { href: string; label: string } | null {
  if (row.state === "blocked") return null;
  if (row.state === "pending_approval") return { href: `/queue/${row.case_id}/approve`, label: "Approve" };
  if (row.state === "approved") return { href: `/queue/${row.case_id}/approve`, label: "Publish" };
  return { href: `/queue/${row.case_id}`, label: "Open" };
}

export default function QueuePage() {
  const client = useQueryClient();
  const queue = useQuery({ queryKey: ["desk-queue"], queryFn: () => api.deskQueue() });
  useHeader({ subtitle: "Sanitized questions. Chips come from the stored case." });

  return (
    <div className="mx-auto max-w-[1440px] space-y-4">
      <AskForm
        onSubmitted={async () => {
          await client.invalidateQueries({ queryKey: ["desk-queue"] });
        }}
      />
      <QueueList queue={queue} />
    </div>
  );
}

function AskForm({ onSubmitted }: { onSubmitted: () => Promise<void> }) {
  const [text, setText] = useState("");
  const ask = useMutation({
    mutationFn: () => api.deskQuestion(text.trim()),
    onSuccess: async () => {
      setText("");
      await onSubmitted();
    },
  });
  const failure = ask.error instanceof ApiError ? ask.error.detail : ask.error instanceof Error ? ask.error.message : null;

  return (
    <Card>
      <CardHeader title="New question" />
      <form
        className="space-y-3 p-5"
        onSubmit={(event) => {
          event.preventDefault();
          if (!text.trim() || ask.isPending) return;
          ask.mutate();
        }}
      >
        <label className="block text-sm text-muted" htmlFor="desk-question">
          The desk sanitizes this message, then drafts a reply or says it is not covered.
        </label>
        <textarea
          id="desk-question"
          value={text}
          onChange={(event) => setText(event.target.value)}
          rows={3}
          className="w-full rounded-control border border-line bg-canvas px-3 py-2 text-sm text-ink"
          placeholder="What is the expense ratio of HDFC Large Cap Fund Direct Growth?"
        />
        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" variant="primary" disabled={ask.isPending || !text.trim()}>
            {ask.isPending ? "Reviewing…" : "Ask the desk"}
          </Button>
          <p className="text-xs text-muted">A citation or a count typed here is ignored. The reply uses stored retrieval only.</p>
        </div>
        {failure ? <p className="text-sm text-critical">{failure}</p> : null}
      </form>
    </Card>
  );
}

function QueueList({
  queue,
}: {
  queue: { isError: boolean; error: unknown; data?: DeskQueueRow[] };
}) {
  if (queue.isError) {
    const message = queue.error instanceof Error ? queue.error.message : "Failed to load the queue";
    return <ErrorState message={message} />;
  }
  if (!queue.data) {
    return <div className="text-sm text-muted">Loading queue…</div>;
  }
  if (queue.data.length === 0) {
    return (
      <EmptyState
        title="Queue is empty"
        body="Submitted questions appear here after they are sanitized and reviewed."
      />
    );
  }
  return (
    <div className="space-y-4">
      {queue.data.map((row) => (
        <QueueRow key={row.case_id} row={row} />
      ))}
    </div>
  );
}

function QueueRow({ row }: { row: DeskQueueRow }) {
  const chips = queueChips(row);
  const action = queueAction(row);
  const sources = row.citation.length ? row.citation.join(" · ") : "No source stored";
  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-2">
          <Link href={`/queue/${row.case_id}`} className="text-base font-semibold text-ink hover:text-accent">
            {row.sanitized_text}
          </Link>
          <p className="text-sm text-muted">{row.not_covered || !row.draft ? "Not covered" : row.draft}</p>
          {row.not_covered ? <Chip tone="warn">Not covered</Chip> : null}
          <p className="break-all font-mono text-xs text-faint">source · {sources}</p>
          <p className="font-mono text-xs text-faint">
            {row.theme_id ? `theme ${row.theme_id}` : "no theme"}
            {" · "}
            pattern · {row.pattern_signal || "no signal"} · count {row.matching_count ?? "unavailable"}
            {" · "}
            {windowLabel(row)}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Chip tone="neutral">{row.reviewer_flag || "unreviewed"}</Chip>
          <Chip tone="accent">{row.state}</Chip>
          {row.state === "blocked" ? <Chip tone="critical">Not approvable</Chip> : null}
          {action ? (
            <Link
              href={action.href}
              className="inline-flex h-[38px] items-center rounded-control bg-accent px-3.5 text-sm font-semibold text-canvas"
            >
              {action.label}
            </Link>
          ) : null}
        </div>
      </div>
      {chips.length > 0 ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {chips.map((chip) => (
            <Chip key={chip} tone={chip === "Not covered" || chip === "Advice" ? "warn" : "neutral"}>
              {chip}
            </Chip>
          ))}
        </div>
      ) : null}
    </Card>
  );
}
