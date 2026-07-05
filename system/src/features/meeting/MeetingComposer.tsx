import { Bot, Plus, Send, Square } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { DragEvent } from "react";
import { fetchConfig, updateConfig } from "@/api/config";
import { fetchModelApiKeys } from "@/api/secrets";
import { AGENT_LABELS, HEADER_AGENT_ORDER } from "@/constants/agents";
import { ReferenceFileIcon, referenceLabel } from "@/features/documents/ReferenceFileIcon";
import { useI18n } from "@/i18n";
import { useUiStore } from "@/stores/uiStore";
import { useNoticeStore } from "@/stores/noticeStore";
import type { RunCheckpoint } from "@/types/api";
import { cn } from "@/utils/cn";
import { errorMessage } from "@/utils/errorMessage";
import { RunCheckpointNotice } from "./RunCheckpointNotice";

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
  reviewTarget?: "stakeholders" | "requirements" | "domain" | "scope" | "meeting_issues";
  onAddReviewSuggestion?: (suggestion?: { text: string; references?: ReferenceMention[] }) => void;
  onConfirmHumanDecision?: () => void;
  onSkipAllHumanInterventions?: () => void;
  skipAllHumanInterventionsLoading?: boolean;
  reviewDragOver?: boolean;
  reviewReferences?: ReferenceMention[];
  onReviewReferencesChange?: (references: ReferenceMention[]) => void;
  mentionOptions?: string[];
  referenceMentionOptions?: ReferenceMention[];
  stakeholderSelectionMode?: boolean;
  customStakeholderDraft?: {
    name: string;
    type: string;
    reason: string;
  };
  stakeholderTypeOptions?: Array<{ value: string; label: string }>;
  onCustomStakeholderDraftChange?: (patch: Partial<{ name: string; type: string; reason: string }>) => void;
  onAddCustomStakeholder?: () => void;
  runCheckpoint?: RunCheckpoint | null;
  stageOverrides?: Record<string, boolean>;
  onDismissRunCheckpoint?: () => void;
}

interface ReferenceMention {
  name: string;
  size?: number;
}

const REFERENCE_DRAG_MIME = "application/x-plant-reference";
const REVIEW_MENTION_DRAG_MIME = "application/x-plant-review-mention";

const AGENT_OPTION_LABELS: Record<string, string> = {
  user: "User",
  analyst: "Analyst",
  expert: "Expert",
  modeler: "Modeler",
  mediator: "Mediator",
  documentor: "Documentor",
};

function normalizeMentionTokens(tokens: string[]): string[] {
  const unique = Array.from(new Set(tokens));
  return unique.includes("@All") ? ["@All"] : unique;
}

function stageEnabled(
  config: Awaited<ReturnType<typeof fetchConfig>>["config"] | undefined,
  stageOverrides: Record<string, boolean> | undefined,
  key: string,
  fallback = true,
): boolean {
  const stage = config?.stage ?? {};
  return stageOverrides?.[key] ?? stage[key] ?? fallback;
}

function requiredAgentReasons(
  config: Awaited<ReturnType<typeof fetchConfig>>["config"] | undefined,
  t: ReturnType<typeof useI18n>["t"],
  stageOverrides?: Record<string, boolean>,
): Record<string, string[]> {
  const reasons: Record<string, string[]> = {};
  const add = (agent: string, reason: string) => {
    reasons[agent] = [...(reasons[agent] ?? []), reason];
  };
  if (stageEnabled(config, stageOverrides, "init")) add("user", t.stageLabels.init);
  if (stageEnabled(config, stageOverrides, "elicitation")) {
    add("user", t.stageLabels.elicitation);
    add("analyst", t.stageLabels.elicitation);
    add("mediator", t.stageLabels.elicitation);
  }
  if (stageEnabled(config, stageOverrides, "conflict_detection")) {
    add("analyst", t.stageLabels.conflict_detection);
    add("mediator", t.stageLabels.conflict_detection);
  }
  if (stageEnabled(config, stageOverrides, "research_domain")) {
    add("expert", t.stageLabels.research_domain);
  }
  if (stageEnabled(config, stageOverrides, "system_model")) {
    add("modeler", t.stageLabels.system_model);
  }
  if (stageEnabled(config, stageOverrides, "draft")) {
    add("analyst", t.stageLabels.draft);
  }
  if (
    stageEnabled(config, stageOverrides, "default_formal_meeting") ||
    stageEnabled(config, stageOverrides, "general_formal_meeting")
  ) {
    add("user", t.stageLabels.general_meeting);
    add("analyst", t.stageLabels.general_meeting);
    add("expert", t.stageLabels.general_meeting);
    add("modeler", t.stageLabels.general_meeting);
    add("mediator", t.stageLabels.general_meeting);
  }
  if (stageEnabled(config, stageOverrides, "DR") || stageEnabled(config, stageOverrides, "SRS")) {
    add("documentor", "SRS / DR");
  }
  return reasons;
}

function apiKeyUsableMap(
  providers?: Array<{ provider: string; configured: boolean; status?: string; valid?: boolean }>,
): Record<string, boolean> {
  return Object.fromEntries(
    (providers ?? []).map((row) => [
      row.provider.toLowerCase(),
      row.configured && (row.valid === true || row.status === "valid"),
    ]),
  );
}

function agentReady(
  config: Awaited<ReturnType<typeof fetchConfig>>["config"] | undefined,
  agentId: string,
  configuredProviders: Record<string, boolean>,
): boolean {
  void config;
  void agentId;
  return Object.values(configuredProviders).some(Boolean);
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
  onSkipAllHumanInterventions,
  skipAllHumanInterventionsLoading = false,
  reviewDragOver = false,
  reviewReferences,
  onReviewReferencesChange,
  mentionOptions = [],
  referenceMentionOptions = [],
  stakeholderSelectionMode = false,
  customStakeholderDraft,
  stakeholderTypeOptions = [],
  onCustomStakeholderDraftChange,
  onAddCustomStakeholder,
  runCheckpoint,
  stageOverrides,
  onDismissRunCheckpoint,
}: MeetingComposerProps) {
  const { t } = useI18n();
  const meetingRounds = useUiStore((s) => s.meetingRounds);
  const setMeetingRounds = useUiStore((s) => s.setMeetingRounds);
  const meetingMaxIssues = useUiStore((s) => s.meetingMaxIssues);
  const setMeetingMaxIssues = useUiStore((s) => s.setMeetingMaxIssues);
  const enabledAgents = useUiStore((s) => s.enabledAgents);
  const toggleAgent = useUiStore((s) => s.toggleAgent);
  const pushNotice = useNoticeStore((s) => s.pushNotice);

  const [showAgentPopover, setShowAgentPopover] = useState(false);
  const [mentionOpen, setMentionOpen] = useState(false);
  const [mentionActiveIndex, setMentionActiveIndex] = useState(0);
  const [internalSelectedReferences, setInternalSelectedReferences] = useState<ReferenceMention[]>([]);
  const selectedReferences = reviewReferences ?? internalSelectedReferences;
  const setSelectedReferences = onReviewReferencesChange ?? setInternalSelectedReferences;
  const [referenceDragOver, setReferenceDragOver] = useState(false);
  const [compactButtons, setCompactButtons] = useState(false);
  const [agentPopoverLeft, setAgentPopoverLeft] = useState(8);
  const [agentPopoverBottom, setAgentPopoverBottom] = useState(8);
  const composerRef = useRef<HTMLDivElement>(null);
  const agentRef = useRef<HTMLDivElement>(null);
  const agentPopoverRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const configQuery = useQuery({
    queryKey: ["config"],
    queryFn: async () => (await fetchConfig()).config,
    enabled: true,
    refetchInterval: showAgentPopover ? 3000 : false,
  });
  const keyQuery = useQuery({
    queryKey: ["model-api-keys"],
    queryFn: fetchModelApiKeys,
    enabled: true,
    refetchInterval: showAgentPopover ? 3000 : false,
  });

  const displayAgents = HEADER_AGENT_ORDER;
  const configuredProviders = apiKeyUsableMap(keyQuery.data?.providers);
  const hasUsableProvider = Object.values(configuredProviders).some(Boolean);
  const lockedAgentReasons = requiredAgentReasons(configQuery.data, t, stageOverrides);
  const requiredAgentsReady =
    configQuery.isSuccess &&
    keyQuery.isSuccess &&
    hasUsableProvider;
  const agentButtonDisabled = !requiredAgentsReady;
  const runSubmitDisabled = submitDisabled || !requiredAgentsReady;
  const idleSubmitLabel = submitLabel ?? (noProject ? t.execute : t.continue);
  const readyToRecover = !!runCheckpoint && !running && !stopping;
  const submitTitle = readyToRecover
    ? t.cleanupBeforeContinue
    : !requiredAgentsReady
      ? t.agentApiKeyRequired("Agent")
    : idleSubmitLabel;
  const continueMode = !noProject && !running && !stopping;
  const inputDisabled =
    reviewMode || stakeholderSelectionMode || humanDecisionMode
      ? !canWrite
      : !!disabled || continueMode;
  const mentionTokens = normalizeMentionTokens(value.match(/@[A-Za-z0-9_-]+/g) ?? []);
  const isDomainReview = reviewMode && reviewTarget === "domain";
  const isScopeReview = reviewMode && reviewTarget === "scope";
  const isMeetingIssueReview = reviewMode && reviewTarget === "meeting_issues";
  const reviewUsesMention = reviewMode && !isMeetingIssueReview && !isScopeReview;
  const canDropReference = isDomainReview && canWrite && !inputDisabled;
  const canDropReviewMention =
    reviewMode &&
    (reviewTarget === "stakeholders" || reviewTarget === "requirements") &&
    canWrite &&
    !inputDisabled;
  const visibleInputValue = reviewMode && !isMeetingIssueReview
    ? value
        .replace(/(^|\s)@[A-Za-z0-9_-]+/g, " ")
        .replace(/\s{2,}/g, " ")
        .trimStart()
    : value;
  const mentionPattern = isDomainReview ? /@([^\s]*)$/ : /@([A-Za-z0-9_-]*)$/;
  const mentionMatch = reviewMode && !isMeetingIssueReview ? mentionPattern.exec(visibleInputValue) : null;
  const mentionQuery = mentionMatch?.[1] ?? "";
  const mentionItems = (isDomainReview ? referenceMentionOptions.map((item) => item.name) : mentionOptions)
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
      if (
        showAgentPopover &&
        agentRef.current &&
        !agentRef.current.contains(target) &&
        !agentPopoverRef.current?.contains(target)
      ) {
        setShowAgentPopover(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [showAgentPopover]);

  useEffect(() => {
    if (!showAgentPopover) return;
    const updatePosition = () => {
      const rect = agentRef.current?.getBoundingClientRect();
      if (!rect) return;
      const width = 256;
      const padding = 8;
      setAgentPopoverLeft(Math.min(Math.max(padding, rect.left), window.innerWidth - width - padding));
      setAgentPopoverBottom(Math.max(padding, window.innerHeight - rect.top + padding));
    };
    updatePosition();
    window.addEventListener("resize", updatePosition);
    window.addEventListener("scroll", updatePosition, true);
    return () => {
      window.removeEventListener("resize", updatePosition);
      window.removeEventListener("scroll", updatePosition, true);
    };
  }, [showAgentPopover]);

  useEffect(() => {
    const root = composerRef.current;
    if (!root) return;

    const updateLayout = () => {
      const nextCompact = root.getBoundingClientRect().width < 430;
      setCompactButtons((current) => (current === nextCompact ? current : nextCompact));
    };

    const observer = new ResizeObserver(updateLayout);
    observer.observe(root);
    updateLayout();
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    setMentionActiveIndex(0);
  }, [mentionQuery, mentionItems.length]);

  useEffect(() => {
    if (!isDomainReview) setSelectedReferences([]);
  }, [isDomainReview]);

  const saveAgentDefaults = async (nextAgents = enabledAgents) => {
    try {
      const { config } = await fetchConfig();
      await updateConfig({
        ...config,
        enable_agents: { ...nextAgents },
      });
      pushNotice({
        tone: "success",
        title: t.saved,
        message: t.agentSettingsUpdated,
      });
    } catch (e) {
      pushNotice({
        tone: "error",
        title: t.saveFailed,
        message: errorMessage(e, t.unableSaveAgentSettings),
      });
    }
  };

  const saveMeetingDefaults = async (patch: { rounds?: number; max_issues?: number }) => {
    try {
      const { config } = await fetchConfig();
      await updateConfig({
        ...config,
        ...patch,
      });
      pushNotice({
        tone: "success",
        title: t.saved,
        message: t.meetingSettingsUpdated,
      });
    } catch (e) {
      pushNotice({
        tone: "error",
        title: t.saveFailed,
        message: errorMessage(e, t.unableSaveMeetingSettings),
      });
    }
  };

  const addSelectedReference = (reference: ReferenceMention) => {
    if (selectedReferences.some((item) => item.name === reference.name)) return;
    setSelectedReferences([...selectedReferences, reference]);
  };

  const referenceFromDrop = (dataTransfer: DataTransfer): ReferenceMention | null => {
    const raw = dataTransfer.getData(REFERENCE_DRAG_MIME);
    if (raw) {
      try {
        const parsed = JSON.parse(raw) as Partial<ReferenceMention> & { type?: string };
        if (parsed.type === "reference_file" && parsed.name) {
          return { name: parsed.name, size: parsed.size };
        }
      } catch {
        return null;
      }
    }
    const plainName = dataTransfer.getData("text/plain").trim();
    if (!plainName) return null;
    return referenceMentionOptions.find((item) => item.name === plainName) ?? { name: plainName };
  };

  const handleReferenceDragOver = (event: DragEvent<HTMLDivElement>) => {
    if (!canDropReference) return;
    const types = Array.from(event.dataTransfer.types);
    if (!types.includes(REFERENCE_DRAG_MIME)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    setReferenceDragOver(true);
  };

  const handleReferenceDragLeave = (event: DragEvent<HTMLDivElement>) => {
    const nextTarget = event.relatedTarget as Node | null;
    if (!nextTarget || !event.currentTarget.contains(nextTarget)) {
      setReferenceDragOver(false);
    }
  };

  const handleReferenceDrop = (event: DragEvent<HTMLDivElement>) => {
    if (!canDropReference) return;
    const reference = referenceFromDrop(event.dataTransfer);
    if (!reference) return;
    event.preventDefault();
    setReferenceDragOver(false);
    addSelectedReference(reference);
    window.requestAnimationFrame(() => textareaRef.current?.focus());
  };

  const mentionFromDrop = (dataTransfer: DataTransfer): string | null => {
    const raw = dataTransfer.getData(REVIEW_MENTION_DRAG_MIME);
    if (!raw) return null;
    try {
      const parsed = JSON.parse(raw) as {
        type?: string;
        target?: "stakeholders" | "requirements";
        id?: string;
      };
      if (parsed.type !== "review_mention" || parsed.target !== reviewTarget) return null;
      const id = String(parsed.id ?? "").trim().replace(/^@+/, "");
      return id || null;
    } catch {
      return null;
    }
  };

  const handleReviewMentionDragOver = (event: DragEvent<HTMLDivElement>) => {
    if (!canDropReviewMention) return;
    if (!Array.from(event.dataTransfer.types).includes(REVIEW_MENTION_DRAG_MIME)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    setReferenceDragOver(true);
  };

  const handleReviewMentionDrop = (event: DragEvent<HTMLDivElement>) => {
    if (!canDropReviewMention) return;
    const id = mentionFromDrop(event.dataTransfer);
    if (!id) return;
    event.preventDefault();
    setReferenceDragOver(false);
    const token = `@${id}`;
    const nextTokens =
      token === "@All"
        ? ["@All"]
        : [...mentionTokens.filter((item) => item !== "@All" && item !== token), token];
    onChange(composeReviewValue(visibleInputValue, nextTokens));
    window.requestAnimationFrame(() => textareaRef.current?.focus());
  };

  const handleComposerDragOver = (event: DragEvent<HTMLDivElement>) => {
    handleReferenceDragOver(event);
    handleReviewMentionDragOver(event);
  };

  const handleComposerDrop = (event: DragEvent<HTMLDivElement>) => {
    handleReferenceDrop(event);
    handleReviewMentionDrop(event);
  };

  const insertMention = (id: string) => {
    const target = textareaRef.current;
    const raw = visibleInputValue;
    const cursor = target?.selectionStart ?? raw.length;
    const before = raw
      .slice(0, cursor)
      .replace(isDomainReview ? /@([^\s]*)$/ : /@([A-Za-z0-9_-]*)$/, "");
    const after = raw.slice(cursor);
    if (isDomainReview) {
      const reference = referenceMentionOptions.find((item) => item.name === id);
      if (reference) {
        addSelectedReference(reference);
      }
      onChange(`${before}${after}`.trimStart());
      setMentionOpen(false);
      window.requestAnimationFrame(() => {
        target?.focus();
        target?.setSelectionRange(before.length, before.length);
      });
      return;
    }
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
    if (mentionOpen) {
      const nextBefore = before.replace(isDomainReview ? /@([^\s]*)$/ : /@([A-Za-z0-9_-]*)$/, "");
      onChange(isDomainReview ? `${nextBefore}${after}` : composeReviewValue(`${nextBefore}${after}`));
      setMentionOpen(false);
      window.requestAnimationFrame(() => {
        target?.focus();
        target?.setSelectionRange(nextBefore.length, nextBefore.length);
      });
      return;
    }
    const needsPrefix = before.endsWith("@") ? "" : before && !/\s$/.test(before) ? " @" : "@";
    const nextBefore = `${before}${needsPrefix}`;
    onChange(isDomainReview ? `${nextBefore}${after}` : composeReviewValue(`${nextBefore}${after}`));
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

  const addReviewSuggestion = () => {
    if (isMeetingIssueReview) {
      if (!value.trim()) return;
      onAddReviewSuggestion?.();
      return;
    }
    if (!isDomainReview) {
      onAddReviewSuggestion?.();
      return;
    }
    onAddReviewSuggestion?.({
      text: value.trim(),
      references: selectedReferences,
    });
    setSelectedReferences([]);
  };

  return (
    <div
      ref={composerRef}
      className="min-w-0 shrink-0 overflow-x-hidden px-2 pb-4 pt-3 sm:px-3"
      onDragOver={handleComposerDragOver}
      onDragLeave={handleReferenceDragLeave}
      onDrop={handleComposerDrop}
    >
      <RunCheckpointNotice
        checkpoint={runCheckpoint}
        compact={compactButtons}
        onDismiss={onDismissRunCheckpoint}
      />
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <div className="relative" ref={agentRef}>
          <button
            type="button"
            title={t.agentSettings}
            className={cn(
              "relative inline-flex h-[54px] shrink-0 items-center justify-center gap-1.5 rounded-bubble border text-sm font-medium transition-colors disabled:opacity-40",
              compactButtons ? "w-[54px] px-0" : "px-3",
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
            <span className={cn(compactButtons && "sr-only")}>Agent</span>
          </button>

          {showAgentPopover && createPortal(
            <div
              ref={agentPopoverRef}
              className="fixed z-[100] w-64 rounded-control border border-gray-200 bg-white shadow-lg"
              style={{ left: agentPopoverLeft, bottom: agentPopoverBottom }}
            >
              <div className="border-b border-gray-100 px-3 py-2">
                <p className="text-center text-xs font-semibold text-slate-800">{t.agentSettings}</p>
              </div>
              <div className="border-b border-gray-100 px-3 py-2.5">
                <div className="grid grid-cols-2 gap-2 text-xs text-slate-600">
                  <div className="flex items-center gap-2">
                    <label htmlFor="meeting-rounds" className="shrink-0 font-medium text-slate-700">
                      {t.rounds}
                    </label>
                    <input
                      id="meeting-rounds"
                      type="number"
                      min={1}
                      max={99}
                      step={1}
                      className="h-7 w-12 rounded-control border border-gray-200 bg-gray-50 px-2 text-center text-xs font-medium text-slate-700 focus:border-slate-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-slate-200 disabled:opacity-50"
                      disabled={disabled || readonlyAgentSettings}
                      value={meetingRounds}
                      onChange={(e) => {
                        const next = Math.max(1, Number(e.target.value || 1));
                        setMeetingRounds(next);
                        void saveMeetingDefaults({ rounds: next });
                      }}
                    />
                  </div>
                  <div className="flex items-center gap-2" title={t.maxIssuesPerRound}>
                    <label htmlFor="meeting-max-issues" className="shrink-0 font-medium text-slate-700">
                      {t.issues}
                    </label>
                    <input
                      id="meeting-max-issues"
                      type="number"
                      min={1}
                      max={20}
                      step={1}
                      className="h-7 w-12 rounded-control border border-gray-200 bg-gray-50 px-2 text-center text-xs font-medium text-slate-700 focus:border-slate-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-slate-200 disabled:opacity-50"
                      disabled={disabled || readonlyAgentSettings}
                      value={meetingMaxIssues}
                      onChange={(e) => {
                        const next = Math.max(1, Number(e.target.value || 1));
                        setMeetingMaxIssues(next);
                        void saveMeetingDefaults({ max_issues: next });
                      }}
                    />
                  </div>
                </div>
              </div>
              <div className="py-1">
                {displayAgents.map((id) => {
                  const lockReasons = lockedAgentReasons[id] ?? [];
                  const locked = lockReasons.length > 0;
                  const on = locked || enabledAgents[id] !== false;
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
                      title={
                        locked
                          ? t.requiredAgentReason(lockReasons.join(" / "))
                          : undefined
                      }
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
                          void saveAgentDefaults(nextAgents);
                        }}
                      />
                      <span className={cn((!on || unavailable) && !locked && "text-slate-400")}>
                        {AGENT_OPTION_LABELS[id] ?? AGENT_LABELS[id]}
                      </span>
                    </label>
                  );
                })}
              </div>
            </div>,
            document.body,
          )}
        </div>

        <div
          className={cn(
            "relative flex min-h-[54px] min-w-[240px] flex-1 items-start gap-2 rounded-bubble border border-gray-100 bg-transparent p-2 transition-colors max-[360px]:min-w-0",
            (referenceDragOver || reviewDragOver) && "border-slate-300 bg-slate-50",
          )}
        >
          <div
            className={cn(
              "flex min-w-0 flex-1 gap-2",
              reviewUsesMention ? "flex-col items-stretch" : "flex-wrap items-center",
            )}
          >
            {reviewUsesMention && (
              <div className="flex min-w-0 flex-wrap items-center gap-2">
                <button
                  type="button"
                  className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-sm font-semibold text-slate-400 hover:bg-white hover:text-slate-600 disabled:cursor-not-allowed disabled:opacity-30"
                  disabled={
                    !canWrite ||
                    (isDomainReview ? referenceMentionOptions.length === 0 : mentionOptions.length === 0)
                  }
                  onClick={openMentionPicker}
                  title={
                    isDomainReview
                      ? t.quoteFiles
                      : reviewTarget === "requirements"
                        ? t.quoteRequirementId
                        : reviewTarget === "scope"
                          ? t.quoteScope
                        : t.quoteStakeholderId
                  }
                >
                  @
                </button>
                {isDomainReview
                  ? selectedReferences.map((reference) => (
                    <span
                      key={reference.name}
                      className="inline-flex max-w-[220px] items-center gap-2 rounded-lg border border-slate-200 bg-white px-2 py-1 text-slate-700"
                    >
                      <span className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-slate-100 text-slate-500">
                        <ReferenceFileIcon name={reference.name} />
                      </span>
                      <span className="min-w-0">
                        <span className="block truncate text-[11px] font-semibold leading-4">
                          {reference.name}
                        </span>
                        <span className="block text-[10px] font-medium leading-3 text-slate-400">
                          {referenceLabel(reference.name)}
                        </span>
                      </span>
                      <button
                        type="button"
                        className="inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-slate-900 text-[11px] leading-none text-white hover:bg-slate-700"
                        onClick={() =>
                          setSelectedReferences(
                            selectedReferences.filter((item) => item.name !== reference.name),
                          )
                        }
                        aria-label={`${t.removeQuote} ${reference.name}`}
                        title={t.removeQuote}
                      >
                        ×
                      </button>
                    </span>
                  ))
                  : mentionTokens.map((token) => (
                    <span
                      key={token}
                      className="inline-flex max-w-full items-center gap-1 rounded-md border border-slate-200 bg-white px-1.5 py-0.5 text-[11px] font-medium text-slate-600"
                    >
                      <span className="truncate">{token}</span>
                      <button
                        type="button"
                        className="inline-flex h-3.5 w-3.5 items-center justify-center rounded-sm text-slate-400 hover:bg-slate-100 hover:text-slate-700"
                        onClick={() => removeMentionToken(token)}
                        aria-label={`${t.removeQuote} ${token}`}
                        title={t.removeQuote}
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
                reviewUsesMention && "w-full flex-none",
              )}
              placeholder={
                !canWrite
                  ? t.enterActivationFirst
                  : noProject
                  ? t.initialIdea
                  : stopping
                    ? t.stoppingAgent
                  : reviewMode
                  ? reviewTarget === "requirements"
                    ? t.suggestionWithRequirements
                    : isScopeReview
                      ? t.scopeSuggestion
                    : isDomainReview
                      ? t.suggestionWithFiles
                    : isMeetingIssueReview
                      ? t.customIssue
                      : t.suggestionWithStakeholders
                  : humanDecisionMode
                  ? t.customDecision
                  : stakeholderSelectionMode
                  ? t.customStakeholder
                  : running
                    ? t.runningWait
                  : !noProject
                    ? readyToRecover
                      ? t.recoverHint
                      : t.selectedProjectHint
                    : disabled
                    ? t.selectedProjectHint
                    : t.initialIdea
              }
              disabled={inputDisabled}
              onChange={(e) => {
                if (stakeholderSelectionMode) {
                  onCustomStakeholderDraftChange?.({ name: e.target.value });
                  return;
                }
                const inlineTokens =
                  isDomainReview || isMeetingIssueReview || isScopeReview
                    ? null
                    : e.target.value.match(/@[A-Za-z0-9_-]+/g);
                const inlineText = isDomainReview || isMeetingIssueReview || isScopeReview
                  ? e.target.value
                  : e.target.value
                      .replace(/(^|\s)@[A-Za-z0-9_-]+/g, " ")
                      .replace(/\s{2,}/g, " ")
                      .trimStart();
                const next = reviewMode
                  ? isDomainReview || isMeetingIssueReview || isScopeReview
                    ? inlineText
                    : composeReviewValue(inlineText, inlineTokens ?? mentionTokens)
                  : e.target.value;
                onChange(next);
                if (reviewMode && !isMeetingIssueReview) {
                  setMentionOpen(mentionPattern.test(e.target.value));
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
                if (e.key === "Enter" && !e.shiftKey && !inputDisabled && !runSubmitDisabled) {
                  e.preventDefault();
                  if (stakeholderSelectionMode) {
                    onAddCustomStakeholder?.();
                  } else if (value.trim() || (reviewMode && isDomainReview && selectedReferences.length)) {
                    if (reviewMode) addReviewSuggestion();
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
                  {t.selectCategory}
                </option>
                {stakeholderTypeOptions.map((type) => (
                  <option key={type.value} value={type.value}>
                    {type.label}
                  </option>
                ))}
              </select>
              <input
                className="h-9 min-w-0 flex-[0.95] rounded-lg border border-gray-200 bg-white px-2.5 text-xs text-slate-800 placeholder:text-slate-400 focus:border-slate-400 focus:outline-none focus:ring-2 focus:ring-slate-200 disabled:cursor-not-allowed disabled:opacity-40"
                placeholder={t.reasonOptional}
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
            <div
              className={cn(
                "absolute bottom-full left-2 z-30 mb-2 overflow-hidden rounded-control border border-gray-200 bg-white shadow-lg",
                isDomainReview ? "w-72" : "w-52",
              )}
            >
              <div className="border-b border-gray-100 px-2 py-1.5 text-[10px] font-semibold text-slate-400">
                {t.quote}
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
                    {isDomainReview ? (
                      <span className="flex min-w-0 items-center gap-2">
                        <span
                          className={cn(
                            "inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md",
                            index === mentionActiveIndex
                              ? "bg-white/15 text-white"
                              : "bg-slate-100 text-slate-500",
                          )}
                        >
                          <ReferenceFileIcon name={id} />
                        </span>
                        <span className="min-w-0">
                          <span className="block truncate">{id}</span>
                          <span
                            className={cn(
                              "block text-[10px]",
                              index === mentionActiveIndex ? "text-white/70" : "text-slate-400",
                            )}
                          >
                            {referenceLabel(id)}
                          </span>
                        </span>
                      </span>
                    ) : (
                      id
                    )}
                  </button>
                ))}
              </div>
            </div>
          )}

          <div
            className={cn(
              "flex shrink-0 items-center gap-2",
              reviewUsesMention ? "mt-10 self-start" : "self-center",
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
                aria-label={t.addCustomStakeholder}
                title={t.add}
              >
                <Plus className="h-4 w-4" />
              </button>
            )}

            {reviewMode && (
              <button
                type="button"
                className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-emerald-200 bg-emerald-50 text-emerald-700 hover:bg-emerald-100 disabled:cursor-not-allowed disabled:opacity-40"
                disabled={!canWrite || (!value.trim() && (!isDomainReview || !selectedReferences.length))}
                onClick={addReviewSuggestion}
                aria-label={t.addSuggestion}
                title={t.add}
              >
                <Plus className="h-4 w-4" />
              </button>
            )}

            {(reviewMode || humanDecisionMode) && onSkipAllHumanInterventions ? (
              <button
                type="button"
                className="inline-flex shrink-0 items-center gap-1.5 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-sm font-medium text-amber-700 hover:bg-amber-100 disabled:cursor-not-allowed disabled:opacity-50"
                disabled={!canWrite || skipAllHumanInterventionsLoading}
                onClick={onSkipAllHumanInterventions}
              >
                {t.skipAll}
              </button>
            ) : (!humanDecisionMode || running) && (
              <button
                type="button"
                className={cn(
                  "inline-flex h-10 shrink-0 items-center justify-center gap-1.5 rounded-xl text-sm font-medium text-white disabled:opacity-40",
                  compactButtons ? "w-10 px-0" : "px-4",
                  running ? "bg-red-600 hover:bg-red-700" : "bg-slate-900 hover:bg-slate-800",
                  stopping && "bg-red-400 hover:bg-red-400",
                )}
                disabled={
                  reviewMode || stakeholderSelectionMode
                    ? true
                    : running
                      ? loading || stopping
                      : disabled || runSubmitDisabled || loading || (noProject && !value.trim())
                }
                onClick={running ? onStop : onSubmit}
                aria-label={stopping ? t.stopping : running ? t.stop : idleSubmitLabel}
                title={stopping ? t.stopping : running ? t.stop : submitTitle}
              >
                {running ? <Square className="h-4 w-4" /> : <Send className="h-4 w-4" />}
                <span className={cn(compactButtons && "sr-only")}>
                  {stopping ? `${t.stopping}...` : running ? t.stop : idleSubmitLabel}
                </span>
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
