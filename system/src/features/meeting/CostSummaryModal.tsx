import { X } from "lucide-react";
import type { CostAgentSummary, CostSummary } from "@/types/api";

const AGENT_LABELS: Record<string, string> = {
  user: "User",
  analyst: "Analyst",
  expert: "Expert",
  mediator: "Mediator",
  modeler: "Modeler",
  documentor: "Documentor",
};

function numberValue(value: unknown): number | null {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function formatInteger(value: unknown): string {
  const parsed = numberValue(value);
  return parsed == null ? "-" : Math.round(parsed).toLocaleString("en-US");
}

function formatSeconds(value: unknown): string {
  const parsed = numberValue(value);
  if (parsed == null) return "-";
  return Math.round(parsed).toLocaleString("en-US");
}

function costValue(row: CostAgentSummary | undefined): number | null {
  return numberValue(row?.["estimated_cost(USD)"] ?? row?.estimated_cost);
}

function formatCost(value: unknown): string {
  const parsed = numberValue(value);
  if (parsed == null) return "-";
  return `$${parsed.toLocaleString("en-US", {
    minimumFractionDigits: 4,
    maximumFractionDigits: 4,
  })}`;
}

function agentLabel(agent: string): string {
  return AGENT_LABELS[agent] ?? agent;
}

function sortAgentRows(entries: Array<[string, CostAgentSummary]>) {
  const order = Object.keys(AGENT_LABELS);
  return [...entries].sort(([a], [b]) => {
    const ai = order.indexOf(a);
    const bi = order.indexOf(b);
    if (ai >= 0 && bi >= 0) return ai - bi;
    if (ai >= 0) return -1;
    if (bi >= 0) return 1;
    return a.localeCompare(b);
  });
}

function Metric({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="min-w-0">
      <div className="text-[11px] font-semibold tracking-normal text-slate-400">
        {label}
      </div>
      <div className="mt-0.5 truncate text-sm font-semibold tabular-nums text-slate-800" title={value}>
        {value}
      </div>
    </div>
  );
}

function AgentCostCard({
  agent,
  row,
}: {
  agent: string;
  row: CostAgentSummary;
}) {
  return (
    <article className="rounded-card border border-gray-200 bg-white p-3 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="truncate text-sm font-semibold text-slate-950">
            {agentLabel(agent)}
          </h3>
          <p className="mt-0.5 truncate text-xs text-slate-500" title={String(row.model ?? "-")}>
            {String(row.model ?? "-")}
          </p>
        </div>
        <div className="shrink-0 rounded-control bg-slate-50 px-2.5 py-1 text-sm font-semibold tabular-nums text-slate-950">
          {formatCost(costValue(row))}
        </div>
      </div>
      <div className="mt-3 grid grid-cols-3 gap-3">
        <Metric label="I-Tokens" value={formatInteger(row.input_tokens)} />
        <Metric label="O-Tokens" value={formatInteger(row.output_tokens)} />
        <Metric label="Runtime(s)" value={formatSeconds(row["run_time(s)"])} />
      </div>
    </article>
  );
}

function TotalCostCard({ totals }: { totals: CostAgentSummary | undefined }) {
  return (
    <section className="rounded-card border border-slate-200 bg-slate-950 p-4 text-white shadow-sm md:col-span-2">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <div className="text-sm font-semibold tracking-normal text-slate-400">
            Total
          </div>
          <div className="mt-0.5 text-3xl font-semibold tabular-nums">
            {formatCost(costValue(totals))}
          </div>
        </div>
        <div className="grid grid-cols-3 gap-4 sm:min-w-[420px]">
          <div>
            <div className="text-[11px] font-semibold tracking-normal text-slate-400">
              I-Tokens
            </div>
            <div className="mt-0.5 text-sm font-semibold tabular-nums text-white">
              {formatInteger(totals?.input_tokens)}
            </div>
          </div>
          <div>
            <div className="text-[11px] font-semibold tracking-normal text-slate-400">
              O-Tokens
            </div>
            <div className="mt-0.5 text-sm font-semibold tabular-nums text-white">
              {formatInteger(totals?.output_tokens)}
            </div>
          </div>
          <div>
            <div className="text-[11px] font-semibold tracking-normal text-slate-400">
              Runtime(s)
            </div>
            <div className="mt-0.5 text-sm font-semibold tabular-nums text-white">
              {formatSeconds(totals?.["run_time(s)"])}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

export function CostSummaryModal({
  summary,
  loading,
  error,
  onClose,
}: {
  summary?: CostSummary;
  loading?: boolean;
  error?: string | null;
  onClose: () => void;
}) {
  const agentRows = sortAgentRows(
    Object.entries(summary?.agents ?? {}).filter(
      (entry): entry is [string, CostAgentSummary] =>
        !!entry[1] && typeof entry[1] === "object",
    ),
  );
  const totals = summary?.totals;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/30 px-4 py-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="cost-summary-title"
      onClick={onClose}
    >
      <div
        className="flex max-h-[calc(100vh-2rem)] w-full max-w-4xl flex-col overflow-hidden rounded-card border border-gray-200 bg-white shadow-xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center justify-between gap-4 border-b border-gray-100 px-4 py-2.5">
          <div className="min-w-0">
            <h2 id="cost-summary-title" className="text-lg font-semibold leading-snug text-slate-950">
              開發成本
            </h2>
          </div>
          <button
            type="button"
            className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-control text-slate-400 hover:bg-slate-50 hover:text-slate-700"
            aria-label="關閉"
            onClick={onClose}
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="min-h-0 px-4 py-3">
          {loading ? (
            <div className="flex h-40 items-center justify-center text-sm text-slate-500">
              讀取成本摘要中...
            </div>
          ) : error ? (
            <div className="rounded-control border border-red-100 bg-red-50 px-3 py-2 text-sm text-red-700">
              {error}
            </div>
          ) : (
            <div className="grid gap-2.5 md:grid-cols-2">
              {agentRows.length === 0 ? (
                <div className="rounded-control border border-gray-200 px-3 py-8 text-center text-sm text-slate-400 md:col-span-2">
                  沒有 agent 成本資料
                </div>
              ) : (
                agentRows.map(([agent, row]) => (
                  <AgentCostCard key={agent} agent={agent} row={row} />
                ))
              )}
              <TotalCostCard totals={totals} />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
