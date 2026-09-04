"use client";

import type { ReactNode } from "react";
import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, api } from "@/lib/api";
import { useRunId } from "@/lib/useRunId";
import { useStatus } from "@/components/chrome/AppShell";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Chip } from "@/components/ui/Chip";
import { ConfirmModal } from "@/components/ui/ConfirmModal";
import { EmptyState, ErrorState } from "@/components/ui/EmptyState";
import { Icon } from "@/components/icons/Icon";

export default function PublishPage() {
  const runId = useRunId();
  const status = useStatus();
  const queryClient = useQueryClient();
  const [confirmSend, setConfirmSend] = useState(false);
  const [flash, setFlash] = useState<string | null>(null);
  const pulse = useQuery({ queryKey: ["pulse", runId], queryFn: () => api.pulse(runId) });
  const publish = useQuery({ queryKey: ["publish", runId], queryFn: () => api.publish(runId) });
  const settings = useQuery({ queryKey: ["settings"], queryFn: api.settings });

  const mcpOk = status.data?.mcp.ok ?? false;
  const gatesOk = pulse.data?.all_gates_passed ?? false;
  const rejected = pulse.data?.rejected ?? false;
  const dry = pulse.data?.publish.mode === "dry-run" || publish.data?.mode === "dry-run";
  const blocked = !mcpOk || !gatesOk || rejected;

  const action = useMutation({
    mutationFn: (kind: "append" | "draft" | "send") => {
      if (kind === "append") return api.append(runId);
      if (kind === "draft") return api.draft(runId);
      return api.send(runId);
    },
    onSuccess: (result) => {
      setFlash(result.skipped ? `${result.detail}` : result.detail);
      queryClient.invalidateQueries({ queryKey: ["publish"] });
      queryClient.invalidateQueries({ queryKey: ["pulse"] });
      queryClient.invalidateQueries({ queryKey: ["status"] });
    },
  });

  if (pulse.isError && String(pulse.error).includes("no runs")) {
    return (
      <EmptyState
        title="Nothing to publish"
        body="Produce a gated note first (dry-run pipeline), then append or send from this page."
      />
    );
  }
  if (publish.isError) return <ErrorState message="Could not load publish state." />;
  if (!publish.data || !pulse.data) return <div className="text-sm text-muted">Loading publish state…</div>;

  const data = publish.data;
  const error =
    action.error instanceof ApiError
      ? action.error.detail
      : action.error instanceof Error
        ? action.error.message
        : null;

  return (
    <div className="mx-auto max-w-[1200px] space-y-6">
      <div className="rounded-r border border-line border-l-2 border-l-warn bg-nested px-4 py-3">
        <p className="text-sm font-medium text-ink">
          Same-week retries skip a second Doc append (F14) and a second send if a message_id is stored (F19).
        </p>
        <p className="mt-1 text-sm text-muted">
          Publishing talks to Google only through MCP. This console never calls the Docs or Gmail REST APIs.
        </p>
      </div>

      {!mcpOk ? (
        <ErrorState message="MCP unreachable — append, draft, and send are disabled until Test MCP succeeds." />
      ) : null}
      {rejected || !gatesOk ? (
        <ErrorState message="Gates failed on this run. Open the rejected note from Weekly Pulse; publish stays locked." />
      ) : null}
      {dry && gatesOk ? (
        <Chip tone="warn">Last run was dry-run — artifacts are local until you append or send here.</Chip>
      ) : null}
      {flash ? <Chip tone="accent">{flash}</Chip> : null}
      {error ? <ErrorState message={error} /> : null}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card className="flex flex-col gap-4 p-5">
          <div className="flex items-start gap-3 border-b border-line pb-4">
            <span className="flex h-10 w-10 items-center justify-center rounded-control border border-line text-accent">
              <Icon name="description" size={22} />
            </span>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-base font-semibold">Google Doc notebook</h2>
                {data.skipped_append ? <Chip tone="warn">Append skipped (same week)</Chip> : null}
              </div>
              <p className="text-sm text-muted">Rolling chronicle — one headed section per ISO week.</p>
            </div>
          </div>
          <Row label="Document id" value={data.doc_id || settings.data?.document_id || "unset"} />
          <Row
            label="Idempotency key"
            value={data.idempotency_key || pulse.data.iso_week || "—"}
          />
          <Row
            label="Notebook URL"
            value={
              data.doc_url ? (
                <a href={data.doc_url} target="_blank" rel="noreferrer" className="text-accent hover:underline">
                  Open Doc
                </a>
              ) : (
                "none (dry-run or unset)"
              )
            }
          />
          <div className="mt-auto flex flex-wrap gap-2 pt-2">
            <Button variant="primary" disabled={blocked || action.isPending} onClick={() => action.mutate("append")}>
              Append to notebook
            </Button>
            <Link href="/" className="inline-flex h-[38px] items-center rounded-control border border-line px-3 text-sm hover:bg-nested">
              Review pulse first
            </Link>
          </div>
        </Card>

        <Card className="flex flex-col gap-4 p-5">
          <div className="flex items-start gap-3 border-b border-line pb-4">
            <span className="flex h-10 w-10 items-center justify-center rounded-control border border-line text-accent">
              <Icon name="mail" size={22} />
            </span>
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-base font-semibold">Gmail dispatch</h2>
                {data.message_id ? <Chip tone="accent">Sent</Chip> : data.draft_id ? <Chip>Draft</Chip> : <Chip tone="warn">Not sent</Chip>}
                {data.skipped_send ? <Chip tone="warn">Send skipped</Chip> : null}
              </div>
              <p className="text-sm text-muted">draft_email by default; send_email only after confirm.</p>
            </div>
          </div>
          <Row label="Recipient" value={data.recipient || settings.data?.recipient_alias || "unset"} />
          <Row label="Subject" value={data.subject || (data.idempotency_key ? `groww pulse ${data.idempotency_key}` : "—")} />
          <Row label="Draft id" value={data.draft_id || "—"} />
          <Row label="Message id" value={data.message_id || "—"} />
          <div className="mt-auto flex flex-wrap gap-2 pt-2">
            <Button disabled={blocked || action.isPending} onClick={() => action.mutate("draft")}>
              Create draft
            </Button>
            <Button variant="danger" disabled={blocked || action.isPending} onClick={() => setConfirmSend(true)}>
              Send now
            </Button>
          </div>
        </Card>
      </div>

      <ConfirmModal
        open={confirmSend}
        title="Send the weekly pulse?"
        body="This calls MCP send_email. A same-week retry is skipped if a message_id is already stored. There is no undo from this console."
        confirmLabel="Confirm send"
        danger
        onCancel={() => setConfirmSend(false)}
        onConfirm={() => {
          setConfirmSend(false);
          action.mutate("send");
        }}
      />
    </div>
  );
}

function Row({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex flex-col gap-1 border-t border-line/60 pt-2.5 text-sm sm:flex-row sm:items-center sm:justify-between">
      <span className="text-muted">{label}</span>
      <span className="max-w-md truncate font-mono text-xs text-ink">{value}</span>
    </div>
  );
}
