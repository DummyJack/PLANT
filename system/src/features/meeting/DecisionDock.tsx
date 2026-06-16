import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Edit3, Loader2, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import type { DragEvent } from "react";
import { submitDecision } from "@/api/runs";
import { ReferenceFileIcon, referenceLabel } from "@/features/documents/ReferenceFileIcon";
import { useUiStore } from "@/stores/uiStore";
import type { RunState } from "@/types/api";
import { cn } from "@/utils/cn";

interface DecisionDockProps {
  run: RunState;
  reviewSuggestions?: ReviewSuggestion[];
  onClearReviewSuggestions?: () => void;
  onEditReviewSuggestion?: (index: number) => void;
  onRemoveReviewSuggestion?: (index: number) => void;
  customStakeholders?: CustomStakeholder[];
  onClearCustomStakeholders?: () => void;
  onUpdateCustomStakeholder?: (id: string, patch: Partial<CustomStakeholder>) => void;
  onRemoveCustomStakeholder?: (id: string) => void;
  customDecisionText?: string;
  onClearCustomDecisionText?: () => void;
  onRegisterHumanDecisionConfirm?: (handler: (() => void) | null) => void;
  onReviewDragOver?: (event: DragEvent<HTMLDivElement>) => void;
  onReviewDragLeave?: (event: DragEvent<HTMLDivElement>) => void;
  onReviewDrop?: (event: DragEvent<HTMLDivElement>) => void;
}

const STAKEHOLDER_TYPES = [
  { value: "primary_user", label: "核心使用者" },
  { value: "system_owner", label: "系統所有者與管理者" },
  { value: "external_party", label: "外部相關單位" },
];
const OPTION_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("");

function optionDisplayLabel(value: string, index: number) {
  const raw = value.trim().toUpperCase();
  const letter = /^\d+$/.test(raw)
    ? OPTION_LETTERS[Math.max(0, Number(raw) - 1)]
    : raw || OPTION_LETTERS[index] || String(index + 1);
  return `選項 ${letter}`;
}

interface CustomStakeholder {
  id: string;
  name: string;
  type: string;
  reason: string;
}

export interface ReviewReference {
  name: string;
  size?: number;
}

export interface ReviewSuggestion {
  text: string;
  references?: ReviewReference[];
  target_ids?: string[];
}

interface ScopeReviewDraft {
  in_scope: string[];
  out_of_scope: string[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

const TARGET_MENTION_RE = /(^|\s)@((?:URL|REQ|SM|CR|ST)-[A-Za-z0-9_.:-]+|R\d+-M\d+)/gi;

function reviewTargetIds(text: string) {
  const ids: string[] = [];
  String(text || "").replace(TARGET_MENTION_RE, (_match, _prefix, id) => {
    ids.push(String(id || "").trim().toUpperCase());
    return "";
  });
  return Array.from(new Set(ids.filter(Boolean)));
}

function stripTargetMentions(text: string) {
  return String(text || "")
    .replace(TARGET_MENTION_RE, " ")
    .replace(/\s{2,}/g, " ")
    .trim();
}

function suggestionPayload(suggestion: ReviewSuggestion) {
  const target_ids = Array.from(
    new Set([...(suggestion.target_ids ?? []), ...reviewTargetIds(suggestion.text)]),
  );
  return {
    text: stripTargetMentions(suggestion.text) || suggestion.text.trim(),
    target_ids,
    references: (suggestion.references ?? []).map((ref) => ({ name: ref.name })),
  };
}

function suggestionPayloads(suggestions: ReviewSuggestion[]) {
  return suggestions.map(suggestionPayload);
}

function cleanScopeList(value: unknown) {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => String(item ?? "").trim())
    .filter(Boolean);
}

function scopeDraftFromDecision(decision: RunState["pending_decision"]): ScopeReviewDraft {
  const options = isRecord(decision?.options) ? decision.options : {};
  const rawScope = isRecord(options.scope) ? options.scope : {};
  return {
    in_scope: cleanScopeList(rawScope.in_scope),
    out_of_scope: cleanScopeList(rawScope.out_of_scope),
  };
}

function normalizeScopeDraft(draft: ScopeReviewDraft): ScopeReviewDraft {
  return {
    in_scope: cleanScopeList(draft.in_scope),
    out_of_scope: cleanScopeList(draft.out_of_scope),
  };
}

function sameScopeDraft(a: ScopeReviewDraft, b: ScopeReviewDraft) {
  const left = normalizeScopeDraft(a);
  const right = normalizeScopeDraft(b);
  return (
    left.in_scope.length === right.in_scope.length &&
    left.out_of_scope.length === right.out_of_scope.length &&
    left.in_scope.every((item, index) => item === right.in_scope[index]) &&
    left.out_of_scope.every((item, index) => item === right.out_of_scope[index])
  );
}

function ReferenceChip({ reference }: { reference: ReviewReference }) {
  return (
    <span className="inline-flex max-w-[210px] items-center gap-2 rounded-lg border border-slate-200 bg-white px-2 py-1 text-slate-700">
      <span className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-slate-100 text-slate-500">
        <ReferenceFileIcon name={reference.name} />
      </span>
      <span className="min-w-0">
        <span className="block truncate text-[11px] font-semibold leading-4">{reference.name}</span>
        <span className="block text-[10px] font-medium leading-3 text-slate-400">
          {referenceLabel(reference.name)}
        </span>
      </span>
    </span>
  );
}

export function DecisionDock({
  run,
  reviewSuggestions = [],
  onClearReviewSuggestions,
  onEditReviewSuggestion,
  onRemoveReviewSuggestion,
  customStakeholders = [],
  onClearCustomStakeholders,
  onUpdateCustomStakeholder,
  onRemoveCustomStakeholder,
  customDecisionText = "",
  onClearCustomDecisionText,
  onRegisterHumanDecisionConfirm,
  onReviewDragOver,
  onReviewDragLeave,
  onReviewDrop,
}: DecisionDockProps) {
  const decision = run.pending_decision;
  const queryClient = useQueryClient();
  const canWrite = useUiStore((s) => s.canWrite);
  const scopeReviewDrafts = useUiStore((s) => s.scopeReviewDrafts);
  const clearScopeReviewDraft = useUiStore((s) => s.clearScopeReviewDraft);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [stakeholders, setStakeholders] = useState<
    Record<string, boolean>
  >(() => {
    const init: Record<string, boolean> = {};
    decision?.proposed?.forEach((_row, i) => {
      init[String(i)] = i < 2;
    });
    return init;
  });
  const [stakeholderError, setStakeholderError] = useState("");

  useEffect(() => {
    if (decision?.kind !== "stakeholder_selection") return;
    const init: Record<string, boolean> = {};
    decision.proposed?.forEach((_row, i) => {
      init[String(i)] = i < 2;
    });
    setStakeholders(init);
    setStakeholderError("");
  }, [decision?.id, decision?.kind, decision?.proposed]);

  useEffect(() => {
    if (decision?.kind !== "human_decision") return;
    setSelected(new Set());
  }, [decision?.id, decision?.kind]);

  const submitMut = useMutation({
    mutationFn: (payload: Record<string, unknown>) =>
      submitDecision(run.run_id, decision!.id, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["runs"] });
      queryClient.invalidateQueries({ queryKey: ["run"] });
      queryClient.invalidateQueries({ queryKey: ["artifacts", run.project_id] });
      queryClient.invalidateQueries({ queryKey: ["file", run.project_id, "artifact/project.json"] });
    },
  });

  if (!decision || run.status !== "waiting_for_human") return null;
  const waitingForResume = submitMut.isPending;
  const actionDisabled = waitingForResume || !canWrite;

  if (
    decision.kind === "stakeholder_statement_review" ||
    decision.kind === "requirements_review" ||
    decision.kind === "domain_research_review" ||
    decision.kind === "scope_review" ||
    decision.kind === "meeting_issue_proposal_review"
  ) {
    const isRequirementsReview = decision.kind === "requirements_review";
    const isDomainReview = decision.kind === "domain_research_review";
    const isScopeReview = decision.kind === "scope_review";
    const isMeetingIssueReview = decision.kind === "meeting_issue_proposal_review";
    const originalScopeDraft = scopeDraftFromDecision(decision);
    const editedScopeDraft = normalizeScopeDraft(
      scopeReviewDrafts[decision.id] ?? originalScopeDraft,
    );
    const scopeChanged = isScopeReview && !sameScopeDraft(originalScopeDraft, editedScopeDraft);
    const reviewHelpText = isDomainReview
      ? "右側可查看領域研究文件，支援拖移引用，按確定送出"
      : isRequirementsReview
        ? "右側可查看使用者需求，支援拖移引用，按確定送出"
        : isScopeReview
          ? "右側可逐條編輯需求範圍；下方可加入建議，按確定送出"
        : isMeetingIssueReview
          ? "右側可查看候選議題，按確定送出"
          : "右側可查看利害關係人發言，支援拖移引用與編輯，按確定送出";
    const renderSuggestion = (suggestion: ReviewSuggestion) => {
      const value = suggestion.text;
      const tokens = Array.from(new Set(value.match(/@[A-Za-z0-9_-]+/g) ?? []));
      const text = value
        .replace(/(^|\s)@[A-Za-z0-9_-]+/g, " ")
        .replace(/\s{2,}/g, " ")
        .trim();
      return (
        <div className="flex min-w-0 flex-col gap-1">
          {suggestion.references?.length ? (
            <div className="flex min-w-0 flex-wrap items-center gap-1.5">
              {suggestion.references.map((reference) => (
                <ReferenceChip key={reference.name} reference={reference} />
              ))}
            </div>
          ) : null}
          {tokens.length > 0 && (
            <div className="flex min-w-0 flex-wrap items-center gap-1.5">
              {tokens.map((token) => (
                <span
                  key={token}
                  className="inline-flex max-w-full items-center rounded-md border border-slate-200 bg-white px-1.5 py-0.5 font-medium text-slate-700"
                >
                  <span className="truncate">{token}</span>
                </span>
              ))}
            </div>
          )}
          {text && <div className="break-words">{text}</div>}
        </div>
      );
    };
    const submitReview = () => {
      const suggestions = reviewSuggestions
        .map((item) => ({ ...item, text: item.text.trim() }))
        .filter((item) => item.text || item.references?.length);
      if (isScopeReview) {
        const structuredSuggestions = suggestionPayloads(suggestions);
        if (scopeChanged) {
          submitMut.mutate({
            action: "direct_edit",
            scope: editedScopeDraft,
            ...(structuredSuggestions.length ? { suggestions: structuredSuggestions } : {}),
          });
          onClearReviewSuggestions?.();
          clearScopeReviewDraft(decision.id);
          return;
        }
        if (structuredSuggestions.length) {
          submitMut.mutate({
            action: "submit_suggestions",
            suggestions: structuredSuggestions,
          });
          onClearReviewSuggestions?.();
          clearScopeReviewDraft(decision.id);
          return;
        }
        submitMut.mutate({ action: "approve" });
        clearScopeReviewDraft(decision.id);
        return;
      }
      if (!suggestions.length) {
        submitMut.mutate({ action: "approve" });
        return;
      }
      if (isMeetingIssueReview) {
        submitMut.mutate({
          action: "human_issues",
          custom_issues: suggestions.map((item) => ({ title: item.text })),
        });
        onClearReviewSuggestions?.();
        return;
      }
      if (isDomainReview) {
        submitMut.mutate({
          action: "submit_suggestions",
          suggestions: suggestionPayloads(suggestions),
        });
        onClearReviewSuggestions?.();
        return;
      }
      submitMut.mutate({
        action: "submit_suggestions",
        suggestions: suggestionPayloads(suggestions),
      });
      onClearReviewSuggestions?.();
    };
    return (
      <div
        className="max-h-[46vh] shrink-0 overflow-y-auto border-t border-gray-100 bg-white px-3 py-2.5"
        onDragOver={onReviewDragOver}
        onDragLeave={onReviewDragLeave}
        onDrop={onReviewDrop}
      >
        <div className="mb-2 flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <div className="text-[13px] font-semibold text-slate-900">
                {isDomainReview
                  ? "建議（領域研究）"
                  : isRequirementsReview
                    ? "建議（使用者需求）"
                    : isScopeReview
                      ? "建議（需求範圍）"
                    : isMeetingIssueReview
                      ? "候選議題"
                    : "建議（利害關係人發言）"}
              </div>
              <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[10px] font-medium text-amber-700">
                使用者介入
              </span>
            </div>
            <p className="mt-0.5 text-[11px] leading-5 text-slate-500">
              {reviewHelpText}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-1.5">
            <button
              type="button"
              className="inline-flex h-7 shrink-0 items-center gap-1.5 rounded-lg bg-slate-900 px-3 text-xs font-medium text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-400"
              disabled={actionDisabled}
              onClick={submitReview}
            >
              {waitingForResume && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              確定
            </button>
          </div>
        </div>

        <div className="rounded-lg border border-gray-200 bg-white p-2">
          <div className="space-y-1">
            {reviewSuggestions.length ? (
              reviewSuggestions.map((suggestion, index) => (
                <div
                  key={`${suggestion.text}-${index}`}
                  className="flex items-start gap-2 rounded-md bg-slate-50 px-2 py-2 text-[11px] leading-5 text-slate-600"
                >
                  <div className="min-w-0 flex-1 break-words">
                    {renderSuggestion(suggestion)}
                  </div>
                  <div className="flex shrink-0 items-center gap-1">
                    <button
                      type="button"
                      className="inline-flex h-5 w-5 items-center justify-center rounded-md text-slate-500 hover:bg-white hover:text-slate-800 disabled:opacity-40"
                      disabled={actionDisabled}
                      onClick={() => onEditReviewSuggestion?.(index)}
                      aria-label="編輯建議"
                      title="編輯建議"
                    >
                      <Edit3 className="h-3 w-3" />
                    </button>
                    <button
                      type="button"
                      className="inline-flex h-5 w-5 items-center justify-center rounded-md border border-red-100 bg-white text-sm font-semibold leading-none text-red-600 hover:bg-red-50 disabled:opacity-40"
                      disabled={actionDisabled}
                      onClick={() => onRemoveReviewSuggestion?.(index)}
                      aria-label="移除建議"
                      title="移除建議"
                    >
                      -
                    </button>
                  </div>
                </div>
              ))
            ) : (
              <div className="rounded-md bg-slate-50 px-2 py-3 text-center text-[11px] leading-4 text-slate-400">
                {isMeetingIssueReview ? "在下方對話匡輸入自訂議題後按「+」。" : "在下方對話匡輸入建議後按「+」。"}
              </div>
            )}
          </div>
        </div>
      </div>
    );
  }

  if (decision.kind === "stakeholder_selection") {
    const proposed = decision.proposed ?? [];
    const maxSelect = decision.max_select ?? 5;
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
      if (!payloadRows.length) {
        setStakeholderError("請至少選擇或新增一位利害關係人");
        return;
      }
      if (payloadRows.length > maxSelect) {
        setStakeholderError(`最多只能選擇 ${maxSelect} 位利害關係人`);
        return;
      }
      submitMut.mutate({ stakeholders: payloadRows });
      onClearCustomStakeholders?.();
    };

    return (
      <div className="max-h-[46vh] shrink-0 overflow-y-auto border-t border-gray-100 bg-white px-2.5 py-2">
        <div className="bg-white">
          <div className="mb-2 flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="text-[13px] font-semibold text-slate-900">
                請選擇利害關係人（最多 {maxSelect} 位）
              </div>
              <p className="mt-0.5 text-[11px] leading-4 text-slate-500">
                按確定送出
              </p>
            </div>
            <button
              type="button"
              className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-400"
              disabled={actionDisabled}
              onClick={submitStakeholders}
            >
              {waitingForResume && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              確認
            </button>
          </div>

        <div className="grid max-h-40 grid-cols-1 gap-1 overflow-y-auto min-[640px]:grid-cols-2">
          {proposed.map((p, i) => (
            <button
              key={p.name}
              type="button"
              disabled={!canWrite}
              className={cn(
                "flex min-h-0 w-full items-start gap-2 rounded-control border px-2 py-1.5 text-left transition",
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
                  "flex h-5 w-5 shrink-0 items-center justify-center rounded-md text-[10px] font-semibold",
                  stakeholders[String(i)]
                    ? "bg-white/15 text-white"
                    : "bg-slate-100 text-slate-500",
                )}
              >
                {OPTION_LETTERS[i] ?? i + 1}
              </span>
              <span className="min-w-0 flex-1">
                <span className="flex flex-wrap items-center gap-2">
                  <span className="text-[12px] font-semibold leading-4">{p.name}</span>
                  <span
                    className={cn(
                      "rounded-full px-1.5 py-0.5 text-[10px] leading-4",
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
                      "mt-0.5 block line-clamp-2 text-[11px] leading-4",
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

        <div className="mt-1.5 space-y-1">
          {customStakeholders.length > 0 && (
            <div className="space-y-1">
              <div className="text-[10px] font-medium text-slate-500">
                利害關係人自訂 {customStakeholders.length} 位
              </div>
              {customStakeholders.map((row) => (
                <div key={row.id} className="grid grid-cols-1 gap-1 min-[640px]:grid-cols-[1fr_180px_1fr_auto]">
                  <input
                    className="h-8 min-w-0 rounded-lg border border-gray-200 bg-white px-2 text-xs font-medium text-slate-800 focus:border-slate-400 focus:outline-none focus:ring-2 focus:ring-slate-200"
                    disabled={!canWrite}
                    value={row.name}
                    onChange={(e) =>
                      onUpdateCustomStakeholder?.(row.id, { name: e.target.value })
                    }
                    onKeyDown={(e) => {
                      if (e.key === "Enter") e.currentTarget.blur();
                    }}
                    title="可直接編輯自訂利害關係人名稱，按 Enter 完成"
                  />
                  <select
                    className="h-8 min-w-0 rounded-lg border border-gray-200 bg-white px-2 text-xs text-slate-700 focus:border-slate-400 focus:outline-none focus:ring-2 focus:ring-slate-200"
                    disabled={!canWrite}
                    value={row.type}
                    onChange={(e) =>
                      onUpdateCustomStakeholder?.(row.id, { type: e.target.value })
                    }
                    title="可直接編輯類別"
                  >
                    {STAKEHOLDER_TYPES.map((type) => (
                      <option key={type.value} value={type.value}>
                        {type.label}
                      </option>
                    ))}
                  </select>
                  <input
                    className="h-8 min-w-0 rounded-lg border border-gray-200 bg-white px-2 text-xs text-slate-600 focus:border-slate-400 focus:outline-none focus:ring-2 focus:ring-slate-200"
                    disabled={!canWrite}
                    placeholder="省略"
                    value={row.reason}
                    onChange={(e) =>
                      onUpdateCustomStakeholder?.(row.id, { reason: e.target.value })
                    }
                    onKeyDown={(e) => {
                      if (e.key === "Enter") e.currentTarget.blur();
                    }}
                    title="可直接編輯理由，按 Enter 完成"
                  />
                  <button
                    type="button"
                    disabled={!canWrite}
                    className="inline-flex h-8 items-center justify-center rounded-lg border border-red-200 bg-red-50 px-2 text-[11px] text-red-600 hover:bg-red-100 disabled:cursor-not-allowed disabled:border-gray-200 disabled:bg-white disabled:text-slate-300"
                    onClick={() => onRemoveCustomStakeholder?.(row.id)}
                    aria-label="移除自訂利害關係人"
                    title="移除自訂利害關係人"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
          {stakeholderError && (
            <p className="mt-2 text-[11px] font-medium text-red-600">
              {stakeholderError}
            </p>
          )}

          {waitingForResume && (
            <div className="mt-1 text-[11px] text-slate-500">
              <span className="inline-flex items-center gap-1.5">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                已送出，等待 Agent 團隊繼續生成...
              </span>
            </div>
          )}
        </div>
      </div>
    );
  }

  const options = decision.options as {
    best_options?: Array<{
      id?: number | string;
      option_id?: number | string;
      index?: number;
      title?: string;
      description?: string;
      summary?: string;
      rationale?: string;
    }>;
    recommendation?: {
      option_id?: number | string;
      rationale?: string;
    };
  } | undefined;
  const best = options?.best_options ?? [];
  const recommendedId = String(options?.recommendation?.option_id ?? "").trim();
  const recommendationRationale = String(options?.recommendation?.rationale ?? "").trim();
  const submitHumanDecision = useCallback(() => {
    if (customDecisionText.trim()) {
      submitMut.mutate({
        choices: [0],
        custom_decision: customDecisionText.trim(),
      });
      onClearCustomDecisionText?.();
    } else if (selected.size) {
      submitMut.mutate({ choices: Array.from(selected) });
    }
  }, [customDecisionText, onClearCustomDecisionText, selected, submitMut]);

  useEffect(() => {
    onRegisterHumanDecisionConfirm?.(submitHumanDecision);
    return () => onRegisterHumanDecisionConfirm?.(null);
  }, [onRegisterHumanDecisionConfirm, submitHumanDecision]);

  return (
    <div className="max-h-[46vh] shrink-0 overflow-y-auto border-t border-gray-100 bg-white px-2.5 py-2">
      <div className="bg-white">
        <div className="mb-2 flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="text-[13px] font-semibold text-slate-900">
              {decision.title}
            </div>
            <p className="mt-0.5 text-[11px] leading-4 text-slate-500">
              {decision.description}
            </p>
          </div>
          <div className="flex shrink-0 justify-end gap-1.5">
            <button
              type="button"
              className="rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-xs text-slate-600 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
              disabled={actionDisabled}
              onClick={() => submitMut.mutate({ skipped: true })}
            >
              本次跳過
            </button>
            <button
              type="button"
              className="inline-flex items-center gap-1.5 rounded-lg bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-400"
              disabled={actionDisabled}
              onClick={submitHumanDecision}
            >
              {waitingForResume && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              確認
            </button>
          </div>
        </div>

        <div className="grid max-h-40 grid-cols-1 gap-1 overflow-y-auto min-[640px]:grid-cols-2">
          {best.map((opt, i) => {
            const optionValue = String(opt.option_id ?? opt.id ?? OPTION_LETTERS[i] ?? String(i + 1)).trim();
            const active = selected.has(optionValue);
            const recommended =
              !!recommendedId &&
              (recommendedId === optionValue ||
                recommendedId === String(i + 1) ||
                recommendedId.toUpperCase() === (OPTION_LETTERS[i] ?? "").toUpperCase());
            const optionLabel = optionDisplayLabel(optionValue, i);
            const title = opt.title || opt.summary || optionLabel;
            const rawDescription = opt.description || (opt.summary && opt.summary !== title ? opt.summary : "") || "";
            const description = rawDescription.trim() === title.trim() ? "" : rawDescription;
            return (
              <button
                key={opt.id ?? i}
                type="button"
                  disabled={!canWrite}
                  className={cn(
                  "flex min-h-0 w-full items-start gap-2 rounded-control border px-2 py-1.5 text-left transition",
                  active
                    ? "border-slate-800 bg-slate-900 text-white"
                    : recommended
                      ? "border-emerald-200 bg-emerald-50/60 text-slate-800 hover:border-emerald-300 hover:bg-emerald-50"
                    : "border-gray-200 bg-white text-slate-700 hover:border-slate-300 hover:bg-slate-50",
                )}
                onClick={() => {
                  setSelected(new Set([optionValue]));
                  onClearCustomDecisionText?.();
                }}
              >
                <span
                    className={cn(
                    "flex h-5 min-w-12 shrink-0 items-center justify-center rounded-md px-1.5 text-[10px] font-semibold",
                    active
                      ? "bg-white/15 text-white"
                      : "bg-slate-100 text-slate-500",
                  )}
                >
                  {optionLabel}
                </span>
                  <span className="min-w-0 flex-1">
                  <span className="flex min-w-0 flex-wrap items-center gap-2">
                    <span className="text-xs font-semibold">
                      {title}
                    </span>
                    {recommended && (
                      <span
                        className={cn(
                          "rounded-full px-1.5 py-0.5 text-[10px] font-semibold",
                          active
                            ? "bg-white/15 text-white"
                            : "bg-emerald-100 text-emerald-700",
                        )}
                      >
                        推薦
                      </span>
                    )}
                  </span>
                  {description && (
                    <span
                      className={cn(
                        "mt-0.5 block text-[11px] leading-5",
                        "line-clamp-2",
                        active ? "text-white/75" : "text-slate-500",
                      )}
                    >
                      {description}
                    </span>
                  )}
                  {recommended && recommendationRationale && (
                    <span
                      className={cn(
                        "mt-0.5 block text-[11px] leading-5",
                        "line-clamp-2",
                        active ? "text-white/70" : "text-emerald-700",
                      )}
                    >
                      建議理由：{recommendationRationale}
                    </span>
                  )}
                </span>
              </button>
            );
          })}
        </div>

        <div className="mt-2 min-h-4 text-[11px] text-slate-500">
            {waitingForResume && (
              <span className="inline-flex items-center gap-1.5">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                已送出，等待 Agent 團隊繼續生成...
              </span>
            )}
        </div>
      </div>
    </div>
  );
}
