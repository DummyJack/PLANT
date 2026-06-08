import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, Plus, X } from "lucide-react";
import { useEffect, useState } from "react";
import { submitDecision } from "@/api/runs";
import type { RunState } from "@/types/api";
import { cn } from "@/utils/cn";

interface DecisionDockProps {
  run: RunState;
}

const STAKEHOLDER_TYPES = [
  { value: "primary_user", label: "核心使用者" },
  { value: "system_owner", label: "系統所有者與管理者" },
  { value: "external_party", label: "外部相關單位" },
];
const OPTION_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("");

interface CustomStakeholder {
  id: string;
  name: string;
  type: string;
  reason: string;
}

export function DecisionDock({ run }: DecisionDockProps) {
  const decision = run.pending_decision;
  const queryClient = useQueryClient();
  const [customText, setCustomText] = useState("");
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [stakeholders, setStakeholders] = useState<
    Record<string, boolean>
  >(() => {
    const init: Record<string, boolean> = {};
    decision?.proposed?.forEach((_row, i) => {
      init[String(i)] = i < 2;
    });
    return init;
  });
  const [customStakeholders, setCustomStakeholders] = useState<CustomStakeholder[]>([
    { id: "custom-1", name: "", type: "", reason: "" },
  ]);
  const [stakeholderError, setStakeholderError] = useState("");

  useEffect(() => {
    if (decision?.kind !== "stakeholder_selection") return;
    const init: Record<string, boolean> = {};
    decision.proposed?.forEach((_row, i) => {
      init[String(i)] = i < 2;
    });
    setStakeholders(init);
    setCustomStakeholders([{ id: "custom-1", name: "", type: "", reason: "" }]);
    setStakeholderError("");
  }, [decision?.id, decision?.kind, decision?.proposed]);

  const submitMut = useMutation({
    mutationFn: (payload: Record<string, unknown>) =>
      submitDecision(run.run_id, decision!.id, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["runs"] });
      queryClient.invalidateQueries({ queryKey: ["run"] });
    },
  });

  if (!decision || run.status !== "waiting_for_human") return null;
  const waitingForResume = submitMut.isPending;

  if (decision.kind === "stakeholder_selection") {
    const proposed = decision.proposed ?? [];
    const updateCustomStakeholder = (
      id: string,
      patch: Partial<CustomStakeholder>,
    ) => {
      setCustomStakeholders((rows) =>
        rows.map((row) => (row.id === id ? { ...row, ...patch } : row)),
      );
      setStakeholderError("");
    };
    const addCustomStakeholder = () => {
      setCustomStakeholders((rows) => [
        ...rows,
        { id: `custom-${Date.now()}`, name: "", type: "", reason: "" },
      ]);
    };
    const removeCustomStakeholder = (id: string) => {
      setCustomStakeholders((rows) =>
        rows.length <= 1
          ? [{ id: "custom-1", name: "", type: "", reason: "" }]
          : rows.filter((row) => row.id !== id),
      );
    };
    const submitStakeholders = () => {
      const selectedProposed = Object.entries(stakeholders)
        .filter(([, v]) => v)
        .map(([i]) => proposed[Number(i)])
        .filter(Boolean)
        .map((row) => ({
          name: row.name,
          type: row.type,
          reason: row.reason,
        }));
      const customRows = customStakeholders
        .map((row) => ({
          name: row.name.trim(),
          type: row.type.trim(),
          reason: row.reason.trim() || "使用者自訂",
        }))
        .filter((row) => row.name || row.type || row.reason !== "使用者自訂");
      const invalidCustom = customRows.find((row) => !row.name || !row.type);
      if (invalidCustom) {
        setStakeholderError("自訂利害關係人需要填寫名稱並選擇類別");
        return;
      }
      const payloadRows = [...selectedProposed, ...customRows];
      const maxSelect = decision.max_select ?? 5;
      if (!payloadRows.length) {
        setStakeholderError("請至少選擇或新增一位利害關係人");
        return;
      }
      if (payloadRows.length > maxSelect) {
        setStakeholderError(`最多只能選擇 ${maxSelect} 位利害關係人`);
        return;
      }
      submitMut.mutate({ stakeholders: payloadRows });
    };

    return (
      <div className="shrink-0 border-t border-gray-100 bg-white p-4">
        <div className="rounded-card border border-gray-200 bg-white p-4 shadow-sm">
          <div className="mb-4">
            <div className="text-sm font-semibold text-slate-900">
              {decision.title}
            </div>
            <p className="mt-1 text-xs leading-relaxed text-slate-500">
              {decision.description}
            </p>
          </div>

        <div className="max-h-48 space-y-2 overflow-y-auto">
          {proposed.map((p, i) => (
            <button
              key={p.name}
              type="button"
              className={cn(
                "flex w-full items-start gap-3 rounded-control border px-3 py-2.5 text-left transition",
                stakeholders[String(i)]
                  ? "border-slate-800 bg-slate-900 text-white"
                  : "border-gray-200 bg-white text-slate-700 hover:border-slate-300 hover:bg-slate-50",
              )}
              onClick={() =>
                setStakeholders((s) => ({
                  ...s,
                  [String(i)]: !(s[String(i)] ?? false),
                }))
              }
            >
              <span
                className={cn(
                  "flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-xs font-semibold",
                  stakeholders[String(i)]
                    ? "bg-white/15 text-white"
                    : "bg-slate-100 text-slate-500",
                )}
              >
                {OPTION_LETTERS[i] ?? i + 1}
              </span>
              <span className="min-w-0 flex-1">
                <span className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-semibold">{p.name}</span>
                  <span
                    className={cn(
                      "rounded-full px-2 py-0.5 text-[11px]",
                      stakeholders[String(i)]
                        ? "bg-white/15 text-white/80"
                        : "bg-slate-100 text-slate-500",
                    )}
                  >
                    {STAKEHOLDER_TYPES.find((type) => type.value === p.type)?.label ?? p.type}
                  </span>
                </span>
                {p.reason && (
                  <span
                    className={cn(
                      "mt-1 block text-xs leading-relaxed",
                      stakeholders[String(i)] ? "text-white/75" : "text-slate-500",
                    )}
                  >
                    {p.reason}
                  </span>
                )}
              </span>
            </button>
          ))}
        </div>

          <div className="mt-3 rounded-control border border-gray-200 bg-slate-50 p-3">
              <div className="mb-2 flex items-center justify-between">
                <span className="text-xs font-semibold text-slate-700">
                  自訂利害關係人
                </span>
                <button
                  type="button"
                  className="inline-flex items-center gap-1 rounded-lg border border-gray-200 bg-white px-2 py-1 text-xs text-slate-600 hover:bg-gray-50"
                  onClick={addCustomStakeholder}
                >
                  <Plus className="h-3 w-3" />
                  新增
                </button>
              </div>
              <div className="space-y-2">
                {customStakeholders.map((row) => (
                  <div key={row.id} className="grid grid-cols-[1fr_150px_1fr_auto] gap-2">
                <input
                  className="min-w-0 rounded-lg border border-gray-200 px-2 py-1.5 text-xs focus:border-slate-400 focus:outline-none focus:ring-2 focus:ring-slate-200"
                  placeholder="名稱"
                  value={row.name}
                  onChange={(e) =>
                    updateCustomStakeholder(row.id, { name: e.target.value })
                  }
                />
                <select
                  className="min-w-0 rounded-lg border border-gray-200 bg-white px-2 py-1.5 text-xs text-slate-700 focus:border-slate-400 focus:outline-none focus:ring-2 focus:ring-slate-200"
                  value={row.type}
                  onChange={(e) =>
                    updateCustomStakeholder(row.id, { type: e.target.value })
                  }
                >
                  <option value="">選擇類別</option>
                  {STAKEHOLDER_TYPES.map((type) => (
                    <option key={type.value} value={type.value}>
                      {type.label}
                    </option>
                  ))}
                </select>
                <input
                  className="min-w-0 rounded-lg border border-gray-200 px-2 py-1.5 text-xs focus:border-slate-400 focus:outline-none focus:ring-2 focus:ring-slate-200"
                  placeholder="理由，可留空"
                  value={row.reason}
                  onChange={(e) =>
                    updateCustomStakeholder(row.id, { reason: e.target.value })
                  }
                />
                <button
                  type="button"
                  className="inline-flex items-center justify-center rounded-lg border border-gray-200 bg-white px-2 py-1.5 text-xs text-slate-500 hover:bg-gray-50"
                  onClick={() => removeCustomStakeholder(row.id)}
                  aria-label="移除自訂利害關係人"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
                ))}
              </div>
            </div>
          {stakeholderError && (
            <p className="mt-3 text-xs font-medium text-red-600">
              {stakeholderError}
            </p>
          )}

        <div className="mt-4 flex items-center justify-between gap-3">
          <div className="min-w-0 text-xs text-slate-500">
            {waitingForResume && (
              <span className="inline-flex items-center gap-1.5">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                已送出，等待 Agent 團隊繼續生成...
              </span>
            )}
          </div>
          <button
            type="button"
            className="inline-flex items-center gap-1.5 rounded-lg bg-slate-900 px-4 py-1.5 text-xs font-medium text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-400"
            disabled={waitingForResume}
            onClick={submitStakeholders}
          >
            {waitingForResume && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
            確認
          </button>
        </div>
        </div>
      </div>
    );
  }

  const options = decision.options as {
    best_options?: Array<{ id?: number; title?: string; description?: string }>;
  } | undefined;
  const best = options?.best_options ?? [];

  return (
    <div className="shrink-0 border-t border-amber-200 bg-amber-50/80 p-4">
      <div className="mb-2 text-sm font-semibold text-amber-900">
        {decision.title}
      </div>
      <p className="mb-3 text-xs text-amber-800/80">{decision.description}</p>
      <div className="flex flex-wrap gap-2">
        {best.map((opt, i) => (
          <button
            key={i}
            type="button"
            className={cn(
              "max-w-[220px] rounded-xl border px-3 py-2 text-left text-xs transition-colors",
              selected.has(i + 1)
                ? "border-slate-800 bg-slate-800 text-white"
                : "border-gray-200 bg-white text-slate-700 hover:border-gray-300",
            )}
            onClick={() => {
              const next = new Set<number>();
              next.add(i + 1);
              setSelected(next);
            }}
          >
            <div className="font-medium">{opt.title ?? `方案 ${i + 1}`}</div>
            {opt.description && (
              <div className="mt-0.5 opacity-80">{opt.description}</div>
            )}
          </button>
        ))}
      </div>
      <input
        className="mt-3 w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-xs focus:border-slate-400 focus:outline-none focus:ring-2 focus:ring-slate-200"
        placeholder="自訂決策…"
        value={customText}
        onChange={(e) => setCustomText(e.target.value)}
      />
      <div className="mt-3 flex items-center justify-between gap-3">
        <div className="min-w-0 text-xs text-slate-500">
          {waitingForResume && (
            <span className="inline-flex items-center gap-1.5">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              已送出，等待 Agent 團隊繼續生成...
            </span>
          )}
        </div>
        <div className="flex justify-end gap-2">
        <button
          type="button"
          className="rounded-lg border border-gray-200 bg-white px-4 py-1.5 text-xs text-slate-600 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
          disabled={waitingForResume}
          onClick={() => submitMut.mutate({ skipped: true })}
        >
          略過
        </button>
        <button
          type="button"
          className="inline-flex items-center gap-1.5 rounded-lg bg-slate-900 px-4 py-1.5 text-xs font-medium text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-400"
          disabled={waitingForResume}
          onClick={() => {
            if (customText.trim()) {
              submitMut.mutate({
                choices: [0],
                custom_decision: customText.trim(),
              });
            } else if (selected.size) {
              submitMut.mutate({ choices: Array.from(selected) });
            }
          }}
        >
          {waitingForResume && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
          確認選擇
        </button>
        </div>
      </div>
    </div>
  );
}
