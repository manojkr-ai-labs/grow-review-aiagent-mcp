export const AGENT_ORDER = ["fetch", "ingest", "label", "compose", "validate", "publish"] as const;

export type AgentId = (typeof AGENT_ORDER)[number];
export type AgentState = "working" | "finished" | "waiting" | "failed";

const STAGE_TO_AGENT: Record<string, AgentId> = {
  fetch: "fetch",
  ingest: "ingest",
  cluster: "label",
  pulse: "compose",
  validate: "validate",
  publish: "publish",
};

/** Latest log line decides the single worker that is active. Earlier workers are finished. */
export function workingAgent(lines: string[], running: boolean): AgentId | null {
  if (!running) return null;
  const text = lines.join("\n");
  if (/Dry-run publish|Doc URL|append_to_google_doc|draft_email|send_email/i.test(text)) return "publish";
  if (/Composed a /.test(text)) return "validate";
  if (/Clustered /.test(text)) return "compose";
  if (/Stored /.test(text)) return "label";
  if (/Downloaded /.test(text)) return "ingest";
  return "fetch";
}

export function agentStates(
  stages: { id: string; status: string }[],
  active: AgentId | null,
): Record<AgentId, AgentState> {
  const fromRun = {} as Record<AgentId, AgentState>;
  for (const id of AGENT_ORDER) fromRun[id] = "waiting";
  for (const stage of stages) {
    const id = STAGE_TO_AGENT[stage.id];
    if (!id) continue;
    if (stage.status === "failed") fromRun[id] = "failed";
    else if (stage.status === "ok") fromRun[id] = "finished";
  }
  if (!active) return fromRun;
  const index = AGENT_ORDER.indexOf(active);
  const next = {} as Record<AgentId, AgentState>;
  AGENT_ORDER.forEach((id, i) => {
    if (i < index) next[id] = "finished";
    else if (i === index) next[id] = "working";
    else next[id] = "waiting";
  });
  return next;
}
