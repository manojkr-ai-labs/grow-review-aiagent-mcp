import { Icon } from "../icons/Icon";
import type { GateDTO } from "@/lib/types";

export function GateList({ gates, passed, total }: { gates: GateDTO[]; passed: number; total: number }) {
  const all = passed === total && gates.every((g) => g.passed);
  return (
    <div className="space-y-2.5">
      {gates.map((gate) => (
        <div key={gate.gate} className="flex items-center justify-between font-mono text-sm">
          <span className="text-muted">
            {gate.gate}
            {gate.detail ? <span className="text-faint"> · {gate.detail}</span> : null}
          </span>
          <span className={`flex items-center gap-1.5 ${gate.passed ? "text-accent" : "text-critical"}`}>
            <Icon name={gate.passed ? "check_circle" : "cancel"} size={16} />
            {gate.passed ? "VERIFIED" : "FAILED"}
          </span>
        </div>
      ))}
      <div className="mt-4 flex items-center gap-2 border-t border-line pt-3 text-sm">
        <span className={`h-2 w-2 rounded-full ${all ? "bg-accent animate-pulse" : "bg-critical"}`} />
        <span className="text-ink">
          {all ? `Strict gate: all ${total} criteria verified.` : `${passed}/${total} gates passed.`}
        </span>
      </div>
    </div>
  );
}
