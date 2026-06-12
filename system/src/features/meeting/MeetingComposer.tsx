import { Bot, Plus, Send, Square } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { fetchConfig, updateConfig } from "@/api/config";
import { fetchModelApiKeys } from "@/api/secrets";
import { AGENT_LABELS, HEADER_AGENT_ORDER } from "@/constants/agents";
import { useUiStore } from "@/stores/uiStore";
import { useNoticeStore } from "@/stores/noticeStore";
import { cn } from "@/utils/cn";
import { errorMessage } from "@/utils/errorMessage";

interface MeetingComposerProps {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  onStop?: () => void;
  disabled?: boolean;
  noProject?: boolean;
  loading?: boolean;
  running?: boolean;
  stopping?: boolean;
  readonlyAgentSettings?: boolean;
  canWrite?: boolean;
  submitLabel?: string;
  submitDisabled?: boolean;
  reviewMode?: boolean;
  humanDecisionMode?: boolean;
  reviewTarget?: "stakeholders" | "requirements";
  onAddReviewSuggestion?: () => void;
  onConfirmHumanDecision?: () => void;
  mentionOptions?: string[];
  stakeholderSelectionMode?: boolean;
  customStakeholderDraft?: {
    name: string;
    type: string;
    reason: string;
  };
  stakeholderTypeOptions?: Array<{ value: string; label: string }>;
  onCustomStakeholderDraftChange?: (patch: Partial<{ name: string; type: string; reason: string }>) => void;
  onAddCustomStakeholder?: () => void;
}

const AGENT_OPTION_LABELS: Record<string, string> = {
  user: "User",
  analyst: "Analyst",
  expert: "Expert",
  modeler: "Modeler",
  mediator: "Mediator",
  documentor: "Documentor",
};

const LOCKED_AGENTS = new Set<string>();

function normalizeMentionTokens(tokens: string[]): string[] {
  const unique = Array.from(new Set(tokens));
  return unique.includes("@All") ? ["@All"] : unique;
}

function apiKeyConfiguredMap(
  providers?: Array<{ provider: string; configured: boolean }>,
): Record<string, boolean> {
  return Object.fromEntries(
    (providers ?? []).map((row) => [row.provider.toLowerCase(), row.configured]),
  );
}

function agentReady(
  config: Awaited<ReturnType<typeof fetchConfig>>["config"] | undefined,
  agentId: string,
  configuredProviders: Record<string, boolean>,
): boolean {
  const modelConfig = config?.agent_models?.[agentId];
  const provider = String(modelConfig?.provider ?? "").trim().toLowerCase();
  const model = String(modelConfig?.model ?? "").trim();
  return !!provider && !!model && configuredProviders[provider] === true;
}

export function MeetingComposer({
  value,
  onChange,
  onSubmit,
  onStop,
  disabled,
  noProject,
  loading,
  running,
  stopping,
  readonlyAgentSettings,
  canWrite = true,
  submitLabel,
  submitDisabled = false,
  reviewMode = false,
  humanDecisionMode = false,
  reviewTarget = "stakeholders",
  onAddReviewSuggestion,
  onConfirmHumanDecision,
  mentionOptions = [],
  stakeholderSelectionMode = false,
  customStakeholderDraft,
  stakeholderTypeOptions = [],
  onCustomStakeholderDraftChange,
  onAddCustomStakeholder,
}: MeetingComposerProps) {
  const meetingRounds = useUiStore((s) => s.meetingRounds);
  const setMeetingRounds = useUiStore((s) => s.setMeetingRounds);
  const enabledAgents = useUiStore((s) => s.enabledAgents);
  const toggleAgent = useUiStore((s) => s.toggleAgent);
  const pushNotice = useNoticeStore((s) => s.pushNotice);

  const [showAgentPopover, setShowAgentPopover] = useState(false);
  const [mentionOpen, setMentionOpen] = useState(false);
  const [mentionActiveIndex, setMentionActiveIndex] = useState(0);
  const agentRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const configQuery = useQuery({
    queryKey: ["config"],
    queryFn: async () => (await fetchConfig()).config,
    enabled: showAgentPopover,
    refetchInterval: showAgentPopover ? 3000 : false,
  });
  const keyQuery = useQuery({
    queryKey: ["model-api-keys"],
    queryFn: fetchModelApiKeys,
    enabled: showAgentPopover,
    refetchInterval: showAgentPopover ? 3000 : false,
  });

  const displayAgents = HEADER_AGENT_ORDER;
  const agentButtonDisabled = !!disabled && !readonlyAgentSettings;
  const configuredProviders = apiKeyConfiguredMap(keyQuery.data?.providers);
  const idleSubmitLabel = submitLabel ?? (noProject ? "執行" : "繼續");
  const continueMode = !noProject && !running && !stopping;
  const inputDisabled =
    reviewMode || stakeholderSelectionMode || humanDecisionMode
      ? !canWrite
      : !!disabled || continueMode;
  const mentionTokens = normalizeMentionTokens(value.match(/@[A-Za-z0-9_-]+/g) ?? []);
  const visibleInputValue = reviewMode
    ? value
        .replace(/(^|\s)@[A-Za-z0-9_-]+/g, " ")
        .replace(/\s{2,}/g, " ")
        .trimStart()
    : value;
  const mentionMatch = reviewMode ? /@([A-Za-z0-9_-]*)$/.exec(visibleInputValue) : null;
  const mentionQuery = mentionMatch?.[1] ?? "";
  const mentionItems = mentionOptions
    .filter((id) => id.toLowerCase().includes(mentionQuery.toLowerCase()))
    .slice(0, 8);
  const showMentionPopover =
    reviewMode && mentionOpen && mentionMatch && mentionItems.length > 0;
  const composeReviewValue = (text: string, tokens = mentionTokens) =>
    [normalizeMentionTokens(tokens).join(" "), text.trimStart()].filter(Boolean).join(" ");

  useEffect(() => {
    if (!showAgentPopover) return;
    const handler = (e: MouseEvent) => {
      const target = e.target as Node;
      if (showAgentPopover && agentRef.current && !agentRef.current.contains(target)) {
        setShowAgentPopover(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [showAgentPopover]);

  useEffect(() => {
    setMentionActiveIndex(0);
  }, [mentionQuery, mentionItems.length]);

  const saveDefaults = async (
    nextAgents = enabledAgents,
    nextRounds = meetingRounds,
  ) => {
    try {
      const { config } = await fetchConfig();
      await updateConfig({
        ...config,
        rounds: nextRounds,
        enable_agents: { ...nextAgents, mediator: true },
      });
      pushNotice({
        tone: "success",
        title: "已儲存",
        message: "代理人設定已更新",
      });
    } catch (e) {
      pushNotice({
        tone: "error",
        title: "儲存失敗",
        message: errorMessage(e, "無法儲存代理人設定"),
      });
    }
  };

  const insertMention = (id: string) => {
    const target = textareaRef.current;
    const raw = visibleInputValue;
    const cursor = target?.selectionStart ?? raw.length;
    const before = raw.slice(0, cursor).replace(/@([A-Za-z0-9_-]*)$/, "");
    const after = raw.slice(cursor);
    const token = `@${id}`;
    const nextTokens =
      token === "@All"
        ? ["@All"]
        : [...mentionTokens.filter((item) => item !== "@All" && item !== token), token];
    onChange(composeReviewValue(`${before}${after}`, nextTokens));
    setMentionOpen(false);
    window.requestAnimationFrame(() => {
      target?.focus();
      target?.setSelectionRange(before.length, before.length);
    });
  };

  const openMentionPicker = () => {
    const target = textareaRef.current;
    const cursor = target?.selectionStart ?? visibleInputValue.length;
    const before = visibleInputValue.slice(0, cursor);
    const after = visibleInputValue.slice(cursor);
    const needsPrefix = before.endsWith("@") ? "" : before && !/\s$/.test(before) ? " @" : "@";
    const nextBefore = `${before}${needsPrefix}`;
    onChange(composeReviewValue(`${nextBefore}${after}`));
    setMentionOpen(true);
    window.requestAnimationFrame(() => {
      target?.focus();
      target?.setSelectionRange(nextBefore.length, nextBefore.length);
    });
  };

  const removeMentionToken = (token: string) => {
    const escaped = token.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const next = value
      .replace(new RegExp(`(^|\\s)${escaped}(?=\\s|$)`, "g"), " ")
      .replace(/\s{2,}/g, " ")
      .trimStart();
    onChange(next);
    window.requestAnimationFrame(() => textareaRef.current?.focus());
  };

  return (
    <div className="composer-shadow shrink-0 border-t border-gray-100 bg-white px-3 pb-4 pt-3">
      <div className="flex items-center gap-2">
        <div className="relative" ref={agentRef}>
          <button
            type="button"
            title="選擇啟用的代理（套用於下一次 Agent 執行）"
            className={cn(
              "relative inline-flex h-[54px] shrink-0 items-center gap-1.5 rounded-bubble border px-3 text-sm font-medium transition-colors disabled:opacity-40",
              showAgentPopover
                ? "border-slate-300 bg-white text-slate-800 shadow-sm"
                : "border-gray-200 bg-gray-50 text-slate-600 hover:bg-white hover:text-slate-800",
            )}
            disabled={agentButtonDisabled}
            onClick={() => {
              setShowAgentPopover((v) => !v);
            }}
          >
            <Bot className="h-4 w-4" />
            Agent
          </button>

          {showAgentPopover && (
            <div className="absolute bottom-full left-0 z-20 mb-2 w-64 rounded-control border border-gray-200 bg-white shadow-lg">
              <div className="border-b border-gray-100 px-3 py-2">
                <p className="text-center text-xs font-semibold text-slate-800">代理人設定</p>
              </div>
              <div className="border-b border-gray-100 px-3 py-2.5">
                <div className="flex items-center gap-3 text-xs text-slate-600">
                  <label htmlFor="meeting-rounds" className="shrink-0 font-medium text-slate-700">
                    回合數
                  </label>
                  <input
                    id="meeting-rounds"
                    type="number"
                    min={1}
                    max={99}
                    step={1}
                    className="h-7 w-14 rounded-control border border-gray-200 bg-gray-50 px-2 text-center text-xs font-medium text-slate-700 focus:border-slate-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-slate-200 disabled:opacity-50"
                    disabled={disabled || readonlyAgentSettings}
                    value={meetingRounds}
                    onChange={(e) => {
                      const next = Math.max(1, Number(e.target.value || 1));
                      setMeetingRounds(next);
                      void saveDefaults(enabledAgents, next);
                    }}
                  />
                </div>
              </div>
              <div className="py-1">
                {displayAgents.map((id) => {
                  const on = enabledAgents[id] !== false;
                  const locked = LOCKED_AGENTS.has(id);
                  const ready = agentReady(configQuery.data, id, configuredProviders);
                  const unavailable = !ready;
                  return (
                    <label
                      key={id}
                      className={cn(
                        "flex items-center gap-2.5 px-3 py-2 text-xs transition-colors",
                        locked || unavailable
                          ? "cursor-default text-slate-400"
                          : "cursor-pointer text-slate-700 hover:bg-gray-50",
                        unavailable && "text-slate-400",
                        (disabled || readonlyAgentSettings) && "opacity-50",
                        !readonlyAgentSettings && disabled && "pointer-events-none",
                      )}
                      title={locked ? "此代理固定啟用" : undefined}
                    >
                      <input
                        type="checkbox"
                        className={cn(
                          "rounded border-gray-300 text-slate-800 accent-blue-600 focus:ring-slate-300",
                          unavailable && "accent-gray-300 text-slate-300",
                        )}
                        style={unavailable ? { accentColor: "#d1d5db" } : undefined}
                        disabled={disabled || readonlyAgentSettings || locked || unavailable}
                        checked={on}
                        onChange={() => {
                          if (unavailable) return;
                          const nextAgents = {
                            ...enabledAgents,
                            [id]: !on,
                          };
                          toggleAgent(id);
                          void saveDefaults(nextAgents, meetingRounds);
                        }}
                      />
                      <span className={cn((!on || unavailable) && !locked && "text-slate-400")}>
                        {AGENT_OPTION_LABELS[id] ?? AGENT_LABELS[id]}
                      </span>
                    </label>
                  );
                })}
              </div>
            </div>
          )}
        </div>

        <div className="relative flex min-h-[54px] min-w-0 flex-1 items-start gap-2 rounded-bubble border border-gray-200 bg-gray-50 p-2">
          <div
            className={cn(
              "flex min-w-0 flex-1 gap-2",
              reviewMode ? "flex-col items-stretch" : "flex-wrap items-center",
            )}
          >
            {reviewMode && (
              <div className="flex min-w-0 flex-wrap items-center gap-2">
                <button
                  type="button"
                  className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-sm font-semibold text-slate-400 hover:bg-white hover:text-slate-600 disabled:cursor-not-allowed disabled:opacity-30"
                  disabled={!canWrite || mentionOptions.length === 0}
                  onClick={openMentionPicker}
                  title={reviewTarget === "requirements" ? "引用需求 ID" : "引用利害關係人發言 ID"}
                >
                  @
                </button>
                {mentionTokens.map((token) => (
                    <span
                      key={token}
                      className="inline-flex max-w-full items-center gap-1 rounded-md border border-slate-200 bg-white px-1.5 py-0.5 text-[11px] font-medium text-slate-600"
                    >
                      <span className="truncate">{token}</span>
                      <button
                        type="button"
                        className="inline-flex h-3.5 w-3.5 items-center justify-center rounded-sm text-slate-400 hover:bg-slate-100 hover:text-slate-700"
                        onClick={() => removeMentionToken(token)}
                        aria-label={`移除 ${token}`}
                        title="移除引用"
                      >
                        ×
                      </button>
                    </span>
                  ))}
              </div>
            )}

            <textarea
              ref={textareaRef}
              rows={1}
              className={cn(
                "min-h-[36px] min-w-0 resize-none bg-transparent px-1 py-2 text-sm text-slate-800 placeholder:text-slate-400 focus:outline-none",
                stakeholderSelectionMode ? "flex-[1.15]" : "flex-1",
                reviewMode && "w-full flex-none",
              )}
              placeholder={
                !canWrite
                  ? "請先到設定輸入啟動碼"
                  : noProject
                  ? "輸入初步想法"
                  : stopping
                    ? "正在停止 Agent 執行，請稍候..."
                  : reviewMode
                  ? reviewTarget === "requirements"
                    ? "輸入建議(@：可以引用需求)"
                    : "輸入建議(@：可以引用利害關係人發言)"
                  : humanDecisionMode
                  ? "輸入自訂決策"
                  : stakeholderSelectionMode
                  ? "自訂利害關係人"
                  : running
                    ? "執行中，請稍候…"
                    : !noProject
                    ? `已選擇既有專案，按「${idleSubmitLabel}」執行`
                    : disabled
                    ? `已選擇既有專案，按「${idleSubmitLabel}」執行`
                    : "輸入初步想法"
              }
              disabled={inputDisabled}
              onChange={(e) => {
                if (stakeholderSelectionMode) {
                  onCustomStakeholderDraftChange?.({ name: e.target.value });
                  return;
                }
              const inlineTokens = e.target.value.match(/@[A-Za-z0-9_-]+/g);
              const inlineText = e.target.value
                .replace(/(^|\s)@[A-Za-z0-9_-]+/g, " ")
                .replace(/\s{2,}/g, " ")
                .trimStart();
              const next = reviewMode
                ? composeReviewValue(inlineText, inlineTokens ?? mentionTokens)
                : e.target.value;
                onChange(next);
                if (reviewMode) {
                  setMentionOpen(/@([A-Za-z0-9_-]*)$/.test(e.target.value));
                }
              }}
              onKeyDown={(e) => {
                const composing =
                  e.nativeEvent.isComposing ||
                  (e.nativeEvent as KeyboardEvent).keyCode === 229;
                if (composing) return;
                if (showMentionPopover) {
                  if (e.key === "ArrowDown") {
                    e.preventDefault();
                    setMentionActiveIndex((index) => (index + 1) % mentionItems.length);
                    return;
                  }
                  if (e.key === "ArrowUp") {
                    e.preventDefault();
                    setMentionActiveIndex(
                      (index) => (index - 1 + mentionItems.length) % mentionItems.length,
                    );
                    return;
                  }
                  if (e.key === "Enter" || e.key === "Tab") {
                    e.preventDefault();
                    insertMention(mentionItems[mentionActiveIndex] ?? mentionItems[0]);
                    return;
                  }
                  if (e.key === "Escape") {
                    e.preventDefault();
                    setMentionOpen(false);
                    return;
                  }
                }
                if (e.key === "Enter" && !e.shiftKey && !inputDisabled) {
                  e.preventDefault();
                  if (stakeholderSelectionMode) {
                    onAddCustomStakeholder?.();
                  } else if (value.trim()) {
                    if (reviewMode) onAddReviewSuggestion?.();
                    else if (humanDecisionMode) onConfirmHumanDecision?.();
                    else onSubmit();
                  }
                }
              }}
              value={
                stakeholderSelectionMode
                  ? customStakeholderDraft?.name ?? ""
                  : visibleInputValue
              }
            />

          {stakeholderSelectionMode && (
            <>
              <select
                className="h-9 w-40 shrink-0 rounded-lg border border-gray-200 bg-white px-2 text-xs text-slate-700 focus:border-slate-400 focus:outline-none focus:ring-2 focus:ring-slate-200 disabled:cursor-not-allowed disabled:opacity-40"
                disabled={!canWrite}
                value={customStakeholderDraft?.type ?? ""}
                onChange={(event) =>
                  onCustomStakeholderDraftChange?.({ type: event.target.value })
                }
              >
                <option value="" disabled hidden>
                  選擇類別
                </option>
                {stakeholderTypeOptions.map((type) => (
                  <option key={type.value} value={type.value}>
                    {type.label}
                  </option>
                ))}
              </select>
              <input
                className="h-9 min-w-0 flex-[0.95] rounded-lg border border-gray-200 bg-white px-2.5 text-xs text-slate-800 placeholder:text-slate-400 focus:border-slate-400 focus:outline-none focus:ring-2 focus:ring-slate-200 disabled:cursor-not-allowed disabled:opacity-40"
                placeholder="理由，可留空"
                disabled={!canWrite}
                value={customStakeholderDraft?.reason ?? ""}
                onChange={(event) =>
                  onCustomStakeholderDraftChange?.({ reason: event.target.value })
                }
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey && canWrite) {
                    event.preventDefault();
                    onAddCustomStakeholder?.();
                  }
                }}
              />
            </>
          )}
          </div>

          {showMentionPopover && (
            <div className="absolute bottom-full left-2 z-30 mb-2 w-52 overflow-hidden rounded-control border border-gray-200 bg-white shadow-lg">
              <div className="border-b border-gray-100 px-2 py-1.5 text-[10px] font-semibold text-slate-400">
                引用
              </div>
              <div className="max-h-48 overflow-y-auto p-1">
                {mentionItems.map((id, index) => (
                  <button
                    key={id}
                    type="button"
                    className={cn(
                      "block w-full rounded-control px-2 py-1.5 text-left text-xs font-medium",
                      index === mentionActiveIndex
                        ? "bg-slate-900 text-white"
                        : "text-slate-700 hover:bg-slate-50",
                    )}
                    onMouseEnter={() => setMentionActiveIndex(index)}
                    onMouseDown={(event) => {
                      event.preventDefault();
                      insertMention(id);
                    }}
                  >
                    {id}
                  </button>
                ))}
              </div>
            </div>
          )}

          <div
            className={cn(
              "flex shrink-0 items-center gap-2",
              reviewMode ? "mt-10 self-start" : "self-center",
            )}
          >
            {stakeholderSelectionMode && (
              <button
                type="button"
                className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-emerald-200 bg-emerald-50 text-emerald-700 hover:bg-emerald-100 disabled:cursor-not-allowed disabled:opacity-40"
                disabled={
                  !canWrite ||
                  !customStakeholderDraft?.name.trim() ||
                  !customStakeholderDraft?.type.trim()
                }
                onClick={onAddCustomStakeholder}
                aria-label="加入自訂利害關係人"
                title="加入"
              >
                <Plus className="h-4 w-4" />
              </button>
            )}

            {reviewMode && (
              <button
                type="button"
                className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-emerald-200 bg-emerald-50 text-emerald-700 hover:bg-emerald-100 disabled:cursor-not-allowed disabled:opacity-40"
                disabled={!canWrite || !value.trim()}
                onClick={onAddReviewSuggestion}
                aria-label="加入建議"
                title="加入"
              >
                <Plus className="h-4 w-4" />
              </button>
            )}

            {(!humanDecisionMode || running) && (
              <button
                type="button"
                className={cn(
                  "inline-flex shrink-0 items-center gap-1.5 rounded-xl px-4 py-2 text-sm font-medium text-white disabled:opacity-40",
                  running ? "bg-red-600 hover:bg-red-700" : "bg-slate-900 hover:bg-slate-800",
                  stopping && "bg-red-400 hover:bg-red-400",
                )}
                disabled={
                  reviewMode || stakeholderSelectionMode
                    ? true
                    : running
                      ? loading || stopping
                      : disabled || submitDisabled || loading || (noProject && !value.trim())
                }
                onClick={running ? onStop : onSubmit}
              >
                {running ? <Square className="h-4 w-4" /> : <Send className="h-4 w-4" />}
                {stopping ? "停止中..." : running ? "停止" : idleSubmitLabel}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
