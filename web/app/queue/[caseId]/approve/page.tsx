"use client";

import Link from "next/link";
import { useState } from "react";
import { useParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, api, type DeskClaim } from "@/lib/api";
import { claimIsVerified, lastCheckedLabel } from "@/lib/deskView";
import { useHeader } from "@/components/chrome/AppShell";
import { Button } from "@/components/ui/Button";
import { Card, CardHeader } from "@/components/ui/Card";
import { Chip } from "@/components/ui/Chip";
import { ErrorState } from "@/components/ui/EmptyState";

const APPROVER_REF = "operator.1";
const EDIT_INSTRUCTION = "operator edit";

export default function ApprovalPage() {
  const params = useParams<{ caseId: string }>();
  const caseId = Array.isArray(params.caseId) ? params.caseId[0] : params.caseId;
  const client = useQueryClient();
  const loaded = useQuery({
    queryKey: ["desk-case", caseId],
    queryFn: () => api.deskCase(caseId),
    enabled: Boolean(caseId),
  });
  useHeader({ subtitle: "Gmail send will not be called." });

  const decision = useMutation({
    mutationFn: (choice: "approve" | "reject") =>
      api.deskDecision(caseId, { decision: choice, approver_ref: APPROVER_REF }),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["desk-case", caseId] });
      await client.invalidateQueries({ queryKey: ["desk-queue"] });
    },
  });
  const publish = useMutation({
    mutationFn: () => api.deskPublish(caseId),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["desk-case", caseId] });
    },
  });

  if (loaded.isError) {
    const message = loaded.error instanceof Error ? loaded.error.message : "Failed to load the case";
    return <ErrorState message={message} />;
  }
  if (!loaded.data) {
    return <div className="text-sm text-muted">Loading approval…</div>;
  }

  const detail = loaded.data;
  const note = detail.routing_note;
  const hash = detail.content_hash || "";
  const state = detail.state || "";
  const pending = state === "pending_approval";
  const approved = state === "approved";
  const blocked = state === "blocked";
  const canEdit = pending || approved;
  const busy = decision.isPending || publish.isPending;
  const failure = decision.error || publish.error;
  const verified = detail.claims.filter(claimIsVerified);
  const canonical = verified[0]?.claim || "";

  return (
    <div className="mx-auto max-w-[1440px] space-y-4">
      <Link href={`/queue/${caseId}`} className="text-sm text-accent">
        Back to case
      </Link>
      <Card>
        <CardHeader title="Reply" />
        <p className="whitespace-pre-wrap px-5 py-4 text-sm text-ink">{detail.draft?.text || "No reply stored."}</p>
      </Card>
      <Card>
        <CardHeader title="Facts on this draft" />
        <div className="space-y-4 px-5 py-4 text-sm">
          <p className="text-ink">
            {canonical
              ? `Canonical fact: ${canonical}`
              : "No verified fact is stored for this draft."}
          </p>
          {detail.claims.length === 0 ? (
            <p className="text-muted">Not verified. The corpus did not return a claim.</p>
          ) : (
            <ul className="space-y-3">
              {detail.claims.map((claim) => (
                <li key={`${claim.source_url}-${claim.claim}`}>
                  <FactRow claim={claim} />
                </li>
              ))}
            </ul>
          )}
          {detail.searched_urls.length > 0 && verified.length === 0 ? (
            <div>
              <p className="text-muted">Pages searched</p>
              <ul className="mt-2 space-y-1">
                {detail.searched_urls.map((url) => (
                  <li key={url} className="break-all font-mono text-xs text-ink">
                    {url}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      </Card>
      <Card>
        <CardHeader title="Routing note" />
        <pre className="overflow-x-auto px-5 py-4 font-mono text-xs text-ink">
          {note ? JSON.stringify(note, null, 2) : "No routing note stored."}
        </pre>
      </Card>
      {canEdit && detail.draft?.text ? (
        <EditDraft caseId={caseId} current={detail.draft.text} busy={busy} />
      ) : null}
      <Card>
        <CardHeader title="Publish destination" />
        <dl className="grid gap-3 px-5 py-4 text-sm sm:grid-cols-2">
          <div>
            <dt className="text-xs uppercase tracking-wider text-faint">Doc id</dt>
            <dd className="font-mono text-ink">{detail.document_id || "Not configured"}</dd>
          </div>
          <div>
            <dt className="text-xs uppercase tracking-wider text-faint">Draft recipient</dt>
            <dd className="font-mono text-ink">{detail.recipient || "Not configured"}</dd>
          </div>
          <div className="sm:col-span-2">
            <dt className="text-xs uppercase tracking-wider text-faint">Content hash</dt>
            <dd className="break-all font-mono text-xs text-ink">{hash || "No hash stored."}</dd>
          </div>
        </dl>
        <p className="px-5 pb-4 text-sm text-ink">
          Gmail send will not be called. A timeout stays uncertain and is not retried. A failed draft retry can
          create a second draft, because the hosted server is not exactly-once.
        </p>
      </Card>
      {blocked ? (
        <p className="text-sm text-critical">This case is blocked. It cannot be approved and it will not call Docs or Gmail.</p>
      ) : null}
      {detail.reviewer_findings.length > 0 ? (
        <Card>
          <CardHeader title="Reviewer" />
          <ul className="space-y-2 px-5 py-4 text-sm text-ink">
            {detail.reviewer_findings.map((finding, index) => (
              <li key={`${finding.code || "finding"}-${index}`}>
                {finding.code ? `${finding.code}: ` : ""}
                {finding.message || "Finding stored."}
              </li>
            ))}
          </ul>
        </Card>
      ) : null}
      <div className="flex flex-wrap gap-2">
        <Button variant="primary" disabled={busy || !hash || !pending} onClick={() => decision.mutate("approve")}>
          Approve
        </Button>
        <Button variant="danger" disabled={busy || !pending} onClick={() => decision.mutate("reject")}>
          Reject
        </Button>
        <Button variant="secondary" disabled={busy || !approved || !hash} onClick={() => publish.mutate()}>
          Publish
        </Button>
      </div>
      <p className="text-xs text-muted">Approver reference {APPROVER_REF}. Publish sends the hash on this screen and no send flag.</p>
      {failure ? (
        <p className="text-sm text-critical">{failure instanceof Error ? failure.message : "The desk refused the action."}</p>
      ) : null}
    </div>
  );
}

function FactRow({ claim }: { claim: DeskClaim }) {
  const verified = claimIsVerified(claim);
  return (
    <div className="space-y-1">
      <Chip tone={verified ? "accent" : "warn"}>{verified ? "Verified" : "Not verified"}</Chip>
      <p className="text-ink">{claim.claim}</p>
      <p className="break-all font-mono text-xs text-muted">{claim.source_url}</p>
      <p className="text-xs text-muted">Last checked {lastCheckedLabel(claim.last_checked)}</p>
    </div>
  );
}

function EditDraft({ caseId, current, busy }: { caseId: string; current: string; busy: boolean }) {
  const client = useQueryClient();
  const [reply, setReply] = useState(current);
  const [notice, setNotice] = useState<string | null>(null);
  const edit = useMutation({
    mutationFn: () => api.deskRefine(caseId, { instruction: EDIT_INSTRUCTION, reply: reply.trim() }),
    onSuccess: async (result) => {
      const accepted = result.refinements?.at(-1)?.accepted !== false;
      setNotice(
        accepted
          ? "Saved. Approval was cleared. Approve the hash now on screen before publish."
          : "The reviewer kept the previous reply. Stay inside the retrieved passage, keep the Groww link, and use at most three sentences.",
      );
      await client.invalidateQueries({ queryKey: ["desk-case", caseId] });
      await client.invalidateQueries({ queryKey: ["desk-queue"] });
    },
  });
  const failure = edit.error instanceof ApiError ? edit.error.detail : edit.error instanceof Error ? edit.error.message : null;
  const changed = reply.trim() !== current.trim();

  return (
    <Card>
      <CardHeader title="Edit this draft" />
      <form
        className="space-y-3 p-5"
        onSubmit={(event) => {
          event.preventDefault();
          if (!changed || edit.isPending || busy) return;
          setNotice(null);
          edit.mutate();
        }}
      >
        <p className="text-sm text-muted">
          Before: the reply above. After: the text in this box. Saving replaces that version and clears approval.
        </p>
        <textarea
          value={reply}
          onChange={(event) => setReply(event.target.value)}
          rows={5}
          aria-label="Replacement reply"
          className="w-full rounded-control border border-line bg-canvas px-3 py-2 text-sm text-ink"
        />
        <Button type="submit" variant="secondary" disabled={busy || edit.isPending || !changed || !reply.trim()}>
          {edit.isPending ? "Saving…" : "Save edit"}
        </Button>
        {notice ? <p className="text-sm text-ink">{notice}</p> : null}
        {failure ? <p className="text-sm text-critical">{failure}</p> : null}
      </form>
    </Card>
  );
}
