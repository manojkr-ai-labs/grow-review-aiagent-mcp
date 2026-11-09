"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { AGENT_ORDER, agentStates, workingAgent, type AgentId, type AgentState } from "@/lib/agentFlow";
import { relativeTime } from "@/lib/format";
import { useRunId } from "@/lib/useRunId";
import { useStatus } from "@/components/chrome/AppShell";
import { Card } from "@/components/ui/Card";
import { Chip } from "@/components/ui/Chip";
import { Icon } from "@/components/icons/Icon";

const COPY: Record<AgentId, { name: string; does: string; fallbackWith: string }> = {
  fetch: {
    name: "Play fetch",
    does: "Downloads public Groww reviews",
    fallbackWith: "google-play-scraper",
  },
  ingest: {
    name: "Scrubber",
    does: "Drops names, short text, and non-English",
    fallbackWith: "Rules, then SQLite",
  },
  label: {
    name: "Theme labeler",
    does: "Names at most five clusters",
    fallbackWith: "Groq",
  },
  compose: {
    name: "Pulse composer",
    does: "Writes the note around three quotes",
    fallbackWith: "Gemini",
  },
  validate: {
    name: "Gatekeeper",
    does: "Checks quotes, length, actions, and PII",
    fallbackWith: "Seven local gates",
  },
  publish: {
    name: "Publisher",
    does: "Appends the Doc and drafts Gmail",
    fallbackWith: "MCP",
  },
};

export default function AgentsPage() {
  const runId = useRunId();
  const status = useStatus();
  const pulse = useQuery({ queryKey: ["pulse", runId], queryFn: () => api.pulse(runId) });
  const settings = useQuery({ queryKey: ["settings"], queryFn: api.settings });
  const job = status.data?.pipeline;
  const running = job?.status === "queued" || job?.status === "running";
  const [lines, setLines] = useState<string[]>([]);

  useEffect(() => {
    if (!job?.job_id || !running) {
      setLines([]);
      return;
    }
    const source = new EventSource(api.jobLogUrl(job.job_id));
    source.onmessage = (event) => {
      try {
        setLines((prev) => [...prev, String(JSON.parse(event.data))]);
      } catch {
        setLines((prev) => [...prev, event.data]);
      }
    };
    source.addEventListener("done", () => source.close());
    return () => source.close();
  }, [job?.job_id, running]);

  const active = workingAgent(lines, running);
  const states = agentStates(pulse.data?.stages ?? [], active);
  const activeName = active ? COPY[active].name : null;
  const withFor = (id: AgentId): string => {
    const s = settings.data;
    if (id === "label" && s?.groq_model) return `Groq · ${s.groq_model}`;
    if (id === "compose" && s?.gemini_model) return `Gemini · ${s.gemini_model}`;
    if (id === "publish" && s?.mcp_configured) return "MCP · Docs and Gmail";
    if (id === "fetch" && s?.package_id) return s.package_id;
    return COPY[id].fallbackWith;
  };

  return (
    <div className="mx-auto max-w-[1520px] space-y-6">
      <Card className="flex flex-wrap items-center justify-between gap-4 p-4">
        <div>
          <div className="font-mono text-[11px] uppercase tracking-wider text-faint">Who is working</div>
          <h2 className="mt-1 text-lg font-semibold">
            {activeName ? activeName : "No agent is working"}
          </h2>
          <p className="mt-1 max-w-2xl text-sm text-muted">
            {activeName
              ? "The orchestrator runs one worker at a time. The highlighted step is the one in progress."
              : `Last run ${status.data?.iso_week || "—"} finished ${relativeTime(status.data?.last_run_at)}. Start Run Pipeline to watch the highlight move.`}
          </p>
        </div>
        <Chip tone={active ? "warn" : "accent"}>{active ? "Working" : "Idle"}</Chip>
      </Card>

      <section aria-label="Agent flow" className="space-y-3">
        <div className="flex items-center gap-2">
          <Icon name="account_tree" className="text-accent" />
          <h2 className="text-base font-semibold">How the workers connect</h2>
        </div>
        <Card className="overflow-x-auto p-4 md:p-6">
          <div className="mb-5 flex items-center justify-between gap-3 rounded-control border border-line bg-nested px-4 py-3">
            <div className="flex items-center gap-3">
              <span
                className={`flex h-9 w-9 items-center justify-center rounded-full border ${
                  active ? "border-warn bg-warn/15 text-warn" : "border-line text-faint"
                }`}
              >
                <Icon name="smart_toy" size={18} />
              </span>
              <div>
                <div className="text-sm font-semibold">ReviewPulse orchestrator</div>
                <div className="font-mono text-[11px] text-faint">One pipeline · workers run in order</div>
              </div>
            </div>
            <Chip tone={active ? "warn" : "neutral"}>{active ? "Dispatching" : "Standing by"}</Chip>
          </div>
          <ol className="flex flex-col gap-3 lg:flex-row lg:items-stretch">
            {AGENT_ORDER.map((id, index) => (
              <li key={id} className="flex min-w-0 flex-1 flex-col gap-3 lg:flex-row lg:items-stretch">
                <AgentNode
                  name={COPY[id].name}
                  does={COPY[id].does}
                  withTool={withFor(id)}
                  state={states[id]}
                />
                {index < AGENT_ORDER.length - 1 ? (
                  <div className="flex items-center justify-center text-faint lg:px-1" aria-hidden>
                    <Icon name="arrow_downward" className="lg:hidden" size={16} />
                    <Icon name="arrow_forward" className="hidden lg:inline" size={16} />
                  </div>
                ) : null}
              </li>
            ))}
          </ol>
        </Card>
      </section>
    </div>
  );
}

function AgentNode({
  name,
  does,
  withTool,
  state,
}: {
  name: string;
  does: string;
  withTool: string;
  state: AgentState;
}) {
  const ring =
    state === "working"
      ? "border-warn bg-warn/10"
      : state === "finished"
        ? "border-accent/50 bg-accent/5"
        : state === "failed"
          ? "border-critical/50 bg-critical/10"
          : "border-line bg-canvas";
  const label = state === "working" ? "Working" : state === "finished" ? "Finished" : state === "failed" ? "Failed" : "Waiting";
  const tone = state === "working" ? "warn" : state === "finished" ? "accent" : state === "failed" ? "critical" : "neutral";
  return (
    <article className={`flex min-w-[160px] flex-1 flex-col rounded-card border p-3 ${ring}`} aria-label={`${name} ${label}`}>
      <div className="flex items-start justify-between gap-2">
        <h3 className="text-sm font-semibold">{name}</h3>
        {state === "working" ? <span className="mt-1 h-2 w-2 shrink-0 animate-pulse rounded-full bg-warn" /> : null}
      </div>
      <p className="mt-2 text-xs text-muted">{does}</p>
      <p className="mt-2 font-mono text-[10px] uppercase tracking-wider text-faint">{withTool}</p>
      <div className="mt-3">
        <Chip tone={tone}>{label}</Chip>
      </div>
    </article>
  );
}
