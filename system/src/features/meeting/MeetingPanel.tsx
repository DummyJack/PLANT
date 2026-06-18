import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { DragEvent } from "react";
import { createProject, deleteProject, uploadReference } from "@/api/projects";
import { fetchBootstrap } from "@/api/bootstrap";
import { fetchConfig } from "@/api/config";
import { cancelRun, createRun, submitDecision } from "@/api/runs";
import { PanelChrome } from "@/components/PanelChrome";
import { buildReferenceRows } from "@/features/documents/buildLibraryRows";
import { useProjectData } from "@/hooks/useProjectData";
import { useActiveRun } from "@/hooks/useActiveRun";
import { useProjectChatHydration } from "@/hooks/useProjectChatHydration";
import { useRunEvents } from "@/hooks/useRunEvents";
import { useChatStore } from "@/stores/chatStore";
import { useNoticeStore } from "@/stores/noticeStore";
import { useUiStore } from "@/stores/uiStore";
import { errorMessage } from "@/utils/errorMessage";
import { buildInitialUserMessage, mergeChatMessages } from "@/utils/logParser";
import type { RunCheckpoint } from "@/types/api";
import { ChatFeed } from "./ChatFeed";
import { DecisionDock, type ReviewReference, type ReviewSuggestion } from "./DecisionDock";
import { MeetingComposer } from "./MeetingComposer";
import { ProjectHeaderActions } from "./ProjectHeaderActions";
import { StageToggleMenu } from "./StageToggleMenu";
import { WorkspaceFlowIndex } from "./WorkspaceFlowIndex";

interface MeetingPanelProps {
  projectId: string | null;
}

const STAKEHOLDER_TYPES = [
  { value: "primary_user", label: "核心使用者" },
  { value: "system_owner", label: "系統所有者與管理者" },
  { value: "external_party", label: "外部相關單位" },
];
const REFERENCE_DRAG_MIME = "application/x-plant-reference";
const REVIEW_MENTION_DRAG_MIME = "application/x-plant-review-mention";

interface CustomStakeholder {
  id: string;
  name: string;
  type: string;
  reason: string;
}

const INITIAL_AGENT_STAGE_OVERRIDES: Record<string, boolean> = {
  init: true,
  elicitation: false,
  conflict_detection: false,
  research_domain: false,
  system_model: false,
  draft: false,
  default_formal_meeting: false,
  general_formal_meeting: false,
  DR: false,
  SRS: false,
};

const COMPLETED_ALLOWED_STAGE_KEYS = new Set([
  "general_formal_meeting",
  "general_update_draft",
  "DR",
  "SRS",
]);

const KNOWN_STAGE_KEYS = [
  "init",
  "elicitation",
  "conflict_detection",
  "research_domain",
  "system_model",
  "draft",
  "default_formal_meeting",
  "default_update_draft",
  "general_formal_meeting",
  "general_update_draft",
  "DR",
  "SRS",
];

function restrictCompletedStageOverrides(
  overrides: Record<string, boolean> | undefined,
  docsComplete: boolean,
) {
  if (!docsComplete) return overrides;
  const next: Record<string, boolean> = {};
  KNOWN_STAGE_KEYS.forEach((key) => {
    next[key] = COMPLETED_ALLOWED_STAGE_KEYS.has(key)
      ? (overrides?.[key] ?? false)
      : false;
  });
  return next;
}

function completedStageOverrides(
  projectId: string | null,
  items: Array<{ path: string; kind: string }> | undefined,
  artifact: Record<string, unknown> | undefined,
): Record<string, boolean> | undefined {
  if (!projectId || !items) return undefined;
  const paths = new Set(
    items
      .filter((item) => item.kind === "file")
      .map((item) => item.path),
  );
  const has = (pattern: RegExp) => [...paths].some((path) => pattern.test(path));
  const overrides: Record<string, boolean> = {};
  const close = (keys: string[]) => {
    keys.forEach((key) => {
      overrides[key] = false;
    });
  };
  const open = (keys: string[]) => {
    keys.forEach((key) => {
      overrides[key] = true;
    });
  };
  const docsComplete =
    paths.has("results/design_rationale.html") &&
    paths.has("results/srs.html");
  const initComplete =
    !!String(artifact?.scenario ?? "").trim() &&
    Array.isArray(artifact?.stakeholders) &&
    artifact.stakeholders.length > 0 &&
    !!artifact?.scope &&
    typeof artifact.scope === "object" &&
    Array.isArray(artifact?.URL) &&
    artifact.URL.length > 0;

  if (initComplete) close(["init"]);
  if (paths.has("artifact/meeting/elicitation_meeting.json")) close(["elicitation"]);
  if (
    paths.has("artifact/result.json") ||
    has(/^artifact\/report\/conflict_report_v\d+\.(?:json|md)$/i) ||
    has(/^results\/report\/conflict_report_v\d+\.html$/i)
  ) {
    close(["conflict_detection"]);
  }
  if (paths.has("artifact/feedback.json")) {
    close(["research_domain"]);
  }
  if (paths.has("artifact/system_models.json") || has(/^artifact\/models\/.+/i)) {
    close(["system_model"]);
  }
  if (has(/^artifact\/drafts\/draft_v\d+\.md$/i) || has(/^results\/drafts\/draft_v\d+\.html$/i)) {
    close(["draft"]);
  }
  if (
    has(/^artifact\/meeting\/formal_meeting_r1\.json$/i) ||
    has(/^results\/MoM\/R1-M\d+\.html$/i)
  ) {
    close(["default_formal_meeting", "default_update_draft"]);
  }
  const generalMeetingComplete =
    has(/^artifact\/meeting\/formal_meeting_r(?:[2-9]|\d{2,})\.json$/i) ||
    has(/^results\/MoM\/R(?:[2-9]|\d{2,})-M\d+\.html$/i);
  if (generalMeetingComplete) {
    close(["general_formal_meeting", "general_update_draft"]);
  }
  if (docsComplete) {
    close([
      "init",
      "elicitation",
      "conflict_detection",
      "research_domain",
      "system_model",
      "draft",
      "default_formal_meeting",
      "default_update_draft",
    ]);
    open(["general_formal_meeting", "general_update_draft", "DR", "SRS"]);
  }
  return Object.keys(overrides).length ? overrides : undefined;
}

function stakeholderStatementMentionIds(
  decision: NonNullable<ReturnType<typeof useActiveRun>["activeRun"]>["pending_decision"],
) {
  if (decision?.kind !== "stakeholder_statement_review") return [];
  const options = decision.options as
    | { stakeholders?: Array<{ text?: Array<{ id?: string } | string> | string }> }
    | undefined;
  const ids: string[] = [];
  options?.stakeholders?.forEach((stakeholder) => {
    const lines = stakeholder.text;
    if (Array.isArray(lines)) {
      lines.forEach((line) => {
        if (typeof line === "object" && line?.id) ids.push(String(line.id));
      });
    }
  });
  return Array.from(new Set(ids.filter(Boolean)));
}

function requirementMentionIds(
  decision: NonNullable<ReturnType<typeof useActiveRun>["activeRun"]>["pending_decision"],
) {
  if (decision?.kind !== "requirements_review") return [];
  const options = decision.options as
    | { requirements?: Array<{ id?: string }> }
    | undefined;
  return Array.from(
    new Set(
      (options?.requirements ?? [])
        .map((row) => String(row?.id ?? "").trim())
        .filter(Boolean),
    ),
  );
}

function runCheckpointKey(checkpoint?: RunCheckpoint | null) {
  if (!checkpoint) return "";
  return [
    checkpoint.run_id || "",
    checkpoint.stage_id || "",
    checkpoint.step_id || "",
    checkpoint.created_at || "",
  ].join(":");
}

function stageOverridesForCheckpoint(
  overrides: Record<string, boolean> | undefined,
  checkpoint?: RunCheckpoint | null,
) {
  if (!checkpoint?.stage_id) return overrides;
  const next = { ...(overrides ?? {}) };
  const stage = checkpoint.stage_id;
  next[stage] = true;
  if (stage === "research_domain") {
    next.system_model = true;
    next.draft = true;
  }
  if (stage === "system_model") {
    next.draft = true;
  }
  return next;
}

function forceRegenerateFlags(config: Record<string, unknown> | undefined) {
  const raw = config?.force_regenerate_outputs;
  return raw && typeof raw === "object" && !Array.isArray(raw)
    ? (raw as Record<string, boolean>)
    : {};
}

function stageOverridesWithForce(
  overrides: Record<string, boolean> | undefined,
  config: Record<string, unknown> | undefined,
) {
  const flags = forceRegenerateFlags(config);
  const next = { ...(overrides ?? {}) };
  Object.entries(flags).forEach(([key, enabled]) => {
    if (enabled === true) next[key] = true;
  });
  return Object.keys(next).length ? next : undefined;
}

export function MeetingPanel({ projectId }: MeetingPanelProps) {
  const queryClient = useQueryClient();
  const configQuery = useQuery({
    queryKey: ["config"],
    queryFn: async () => (await fetchConfig()).config,
    enabled: !!projectId,
  });
  const { project, references, artifacts } = useProjectData(projectId);
  const { activeRun, data: runsData } = useActiveRun(projectId);
  const clearMessages = useChatStore((s) => s.clearMessages);
  const setMessages = useChatStore((s) => s.setMessages);
  const setContinueReplacementStage = useChatStore((s) => s.setContinueReplacementStage);
  const trimRunStatusMessagesForContinue = useChatStore((s) => s.trimRunStatusMessagesForContinue);
  const pushNotice = useNoticeStore((s) => s.pushNotice);
  const meetingRounds = useUiStore((s) => s.meetingRounds);
  const meetingMaxIssues = useUiStore((s) => s.meetingMaxIssues);
  const meetingRoundsOverridden = useUiStore((s) => s.meetingRoundsOverridden);
  const meetingMaxIssuesOverridden = useUiStore((s) => s.meetingMaxIssuesOverridden);
  const enabledAgents = useUiStore((s) => s.enabledAgents);
  const attachedDocIds = useUiStore((s) => s.attachedDocIds);
  const clearAttachedDocs = useUiStore((s) => s.clearAttachedDocs);
  const setActiveProjectId = useUiStore((s) => s.setActiveProjectId);
  const stagedReferenceFiles = useUiStore((s) => s.stagedReferenceFiles);
  const clearStagedReferenceFiles = useUiStore((s) => s.clearStagedReferenceFiles);
  const canWrite = useUiStore((s) => s.canWrite);
  const dismissedRunCheckpointKeys = useUiStore((s) => s.dismissedRunCheckpointKeys);
  const dismissRunCheckpoint = useUiStore((s) => s.dismissRunCheckpoint);
  const humanDecisionConfirmRef = useRef<(() => void) | null>(null);
  const panelMeasureRef = useRef<HTMLDivElement>(null);
  const [headerCompact, setHeaderCompact] = useState(false);

  const roughIdea =
    (project.data?.project?.rough_idea as string | undefined) ?? "";
  const [input, setInput] = useState("");
  const [reviewSuggestions, setReviewSuggestions] = useState<ReviewSuggestion[]>([]);
  const [pendingReviewReferences, setPendingReviewReferences] = useState<ReviewReference[]>([]);
  const [reviewDockDragOver, setReviewDockDragOver] = useState(false);
  const [customStakeholderDraft, setCustomStakeholderDraft] = useState({
    name: "",
    type: "",
    reason: "",
  });
  const [customStakeholders, setCustomStakeholders] = useState<CustomStakeholder[]>([]);
  const [confirmDeleteProjectOpen, setConfirmDeleteProjectOpen] = useState(false);

  useEffect(() => {
    setInput("");
    setReviewSuggestions([]);
    setPendingReviewReferences([]);
    setCustomStakeholderDraft({ name: "", type: "", reason: "" });
    setCustomStakeholders([]);
  }, [projectId]);

  useEffect(() => {
    const measure = panelMeasureRef.current;
    const panel = measure?.closest(".card");
    if (!measure || !panel) return;

    const updateHeaderLayout = () => {
      const panelWidth = panel.getBoundingClientRect().width;
      const nextCompact = panelWidth < 550;
      setHeaderCompact((current) => (current === nextCompact ? current : nextCompact));
    };

    const observer = new ResizeObserver(updateHeaderLayout);
    observer.observe(panel);
    updateHeaderLayout();
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (
      activeRun?.pending_decision?.kind !== "stakeholder_statement_review" &&
      activeRun?.pending_decision?.kind !== "requirements_review" &&
      activeRun?.pending_decision?.kind !== "domain_research_review" &&
      activeRun?.pending_decision?.kind !== "scope_review" &&
      activeRun?.pending_decision?.kind !== "meeting_issue_proposal_review"
    ) {
      setReviewSuggestions([]);
      setPendingReviewReferences([]);
    }
    if (activeRun?.pending_decision?.kind !== "stakeholder_selection") {
      setCustomStakeholderDraft({ name: "", type: "", reason: "" });
      setCustomStakeholders([]);
    }
  }, [
    activeRun?.pending_decision?.id,
    activeRun?.pending_decision?.kind,
  ]);

  const stagedReferenceRows = useMemo(
    () => stagedReferenceFiles.map((file) => ({ name: file.name })),
    [stagedReferenceFiles],
  );
  const referenceRows = useMemo(
    () =>
      projectId
        ? buildReferenceRows(references.data?.references ?? [])
        : buildReferenceRows(stagedReferenceRows),
    [projectId, references.data?.references, stagedReferenceRows],
  );
  const referenceMentionOptions = useMemo(
    () => referenceRows.map((row) => ({ name: row.name })),
    [referenceRows],
  );
  const mentionOptions = useMemo(
    () =>
      Array.from(
        new Set([
          "All",
          ...stakeholderStatementMentionIds(activeRun?.pending_decision ?? null),
          ...requirementMentionIds(activeRun?.pending_decision ?? null),
        ]),
      ),
    [activeRun?.pending_decision],
  );
  const reviewMode =
    activeRun?.pending_decision?.kind === "stakeholder_statement_review" ||
    activeRun?.pending_decision?.kind === "requirements_review" ||
    activeRun?.pending_decision?.kind === "domain_research_review" ||
    activeRun?.pending_decision?.kind === "scope_review" ||
    activeRun?.pending_decision?.kind === "meeting_issue_proposal_review";
  const reviewTarget =
    activeRun?.pending_decision?.kind === "requirements_review"
      ? "requirements"
      : activeRun?.pending_decision?.kind === "domain_research_review"
        ? "domain"
        : activeRun?.pending_decision?.kind === "scope_review"
          ? "scope"
          : activeRun?.pending_decision?.kind === "meeting_issue_proposal_review"
            ? "meeting_issues"
            : "stakeholders";
  const referenceFromDrop = useCallback((dataTransfer: DataTransfer) => {
    const raw = dataTransfer.getData(REFERENCE_DRAG_MIME);
    if (raw) {
      try {
        const parsed = JSON.parse(raw) as { type?: string; name?: string; size?: number };
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
  }, [referenceMentionOptions]);
  const mentionFromDrop = useCallback((dataTransfer: DataTransfer) => {
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
  }, [reviewTarget]);
  const canAcceptReviewDockDrop = useCallback((dataTransfer: DataTransfer) => {
    if (!reviewMode || !canWrite) return false;
    const types = Array.from(dataTransfer.types);
    if (reviewTarget === "domain") {
      return types.includes(REFERENCE_DRAG_MIME);
    }
    if (reviewTarget === "stakeholders" || reviewTarget === "requirements") {
      return types.includes(REVIEW_MENTION_DRAG_MIME);
    }
    return false;
  }, [canWrite, reviewMode, reviewTarget]);
  const handleReviewDockDragOver = useCallback((event: DragEvent<HTMLDivElement>) => {
    if (!canAcceptReviewDockDrop(event.dataTransfer)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    setReviewDockDragOver(true);
  }, [canAcceptReviewDockDrop]);
  const handleReviewDockDragLeave = useCallback((event: DragEvent<HTMLDivElement>) => {
    const nextTarget = event.relatedTarget as Node | null;
    if (!nextTarget || !event.currentTarget.contains(nextTarget)) {
      setReviewDockDragOver(false);
    }
  }, []);
  const handleReviewDockDrop = useCallback((event: DragEvent<HTMLDivElement>) => {
    if (!canAcceptReviewDockDrop(event.dataTransfer)) return;
    event.preventDefault();
    setReviewDockDragOver(false);
    if (reviewTarget === "domain") {
      const reference = referenceFromDrop(event.dataTransfer);
      if (!reference) return;
      setPendingReviewReferences((items = []) =>
        items.some((item) => item.name === reference.name)
          ? items
          : [...items, reference],
      );
      return;
    }
    const id = mentionFromDrop(event.dataTransfer);
    if (!id) return;
    const token = `@${id}`;
    setInput((current) => {
      const tokens = Array.from(new Set(current.match(/@[A-Za-z0-9_-]+/g) ?? []));
      const nextTokens =
        token === "@All"
          ? ["@All"]
          : [...tokens.filter((item) => item !== "@All" && item !== token), token];
      const body = current
        .replace(/(^|\s)@[A-Za-z0-9_-]+/g, " ")
        .replace(/\s{2,}/g, " ")
        .trimStart();
      return [nextTokens.join(" "), body].filter(Boolean).join(" ");
    });
  }, [canAcceptReviewDockDrop, mentionFromDrop, referenceFromDrop, reviewTarget]);
  const addCustomStakeholder = useCallback(() => {
    const name = customStakeholderDraft.name.trim();
    const type = customStakeholderDraft.type.trim();
    const reason = customStakeholderDraft.reason.trim();
    if (!name || !type) return;
    setCustomStakeholders((items) => [
      ...items,
      {
        id: `custom-${Date.now()}-${items.length}`,
        name,
        type,
        reason,
      },
    ]);
    setCustomStakeholderDraft({ name: "", type: "", reason: "" });
  }, [customStakeholderDraft]);

  const artifactItems = artifacts.data?.items;
  const hasArtifactPath = useCallback(
    (path: string) =>
      (artifactItems ?? []).some((item) => item.kind === "file" && item.path === path),
    [artifactItems],
  );
  const docsComplete =
    !!projectId &&
    hasArtifactPath("results/design_rationale.html") &&
    hasArtifactPath("results/srs.html");
  const existingStageOutputs = useMemo(
    () => ({
      elicitation: hasArtifactPath("artifact/meeting/elicitation_meeting.json"),
      conflict_detection:
        hasArtifactPath("artifact/result.json") ||
        (artifactItems ?? []).some(
          (item) =>
            item.kind === "file" &&
            (/^artifact\/report\/conflict_report_v\d+\.(?:json|md)$/i.test(item.path) ||
              /^results\/report\/conflict_report_v\d+\.html$/i.test(item.path)),
        ),
      research_domain: hasArtifactPath("artifact/feedback.json"),
      system_model:
        hasArtifactPath("artifact/system_models.json") ||
        (artifactItems ?? []).some((item) => item.kind === "file" && /^artifact\/models\/.+/i.test(item.path)),
      draft: (artifactItems ?? []).some(
        (item) =>
          item.kind === "file" &&
          (/^artifact\/drafts\/draft_v\d+\.md$/i.test(item.path) ||
            /^results\/drafts\/draft_v\d+\.html$/i.test(item.path)),
      ),
      default_formal_meeting:
        hasArtifactPath("artifact/meeting/formal_meeting_r1.json") ||
        (artifactItems ?? []).some((item) => item.kind === "file" && /^results\/MoM\/R1-M\d+\.html$/i.test(item.path)),
      general_formal_meeting: (artifactItems ?? []).some(
        (item) =>
          item.kind === "file" &&
          (/^artifact\/meeting\/formal_meeting_r(?:[2-9]|\d{2,})\.json$/i.test(item.path) ||
            /^results\/MoM\/R(?:[2-9]|\d{2,})-M\d+\.html$/i.test(item.path)),
      ),
      general_update_draft: (artifactItems ?? []).some(
        (item) =>
          item.kind === "file" &&
          (/^artifact\/meeting\/formal_meeting_r(?:[2-9]|\d{2,})\.json$/i.test(item.path) ||
            /^results\/MoM\/R(?:[2-9]|\d{2,})-M\d+\.html$/i.test(item.path)),
      ),
      DR:
        hasArtifactPath("output/design_rationale.md") ||
        hasArtifactPath("results/design_rationale.html"),
      SRS:
        hasArtifactPath("output/srs.md") ||
        hasArtifactPath("results/srs.html"),
    }),
    [artifactItems, hasArtifactPath],
  );
  const stageOverrides = useMemo(
    () => completedStageOverrides(projectId, artifactItems, project.data?.project),
    [projectId, artifactItems, project.data?.project],
  );
  const effectiveStageOverrides = useMemo(
    () => restrictCompletedStageOverrides(
      stageOverridesWithForce(stageOverrides, configQuery.data),
      docsComplete,
    ),
    [configQuery.data, docsComplete, stageOverrides],
  );
  const agentStageOverrides = projectId ? effectiveStageOverrides : INITIAL_AGENT_STAGE_OVERRIDES;
  const { loading: historyLoading } = useProjectChatHydration(
    projectId,
    artifactItems,
    roughIdea,
    activeRun,
    !projectId || artifacts.isSuccess || artifacts.isError,
  );

  const onComplete = useCallback(() => {
    if (!projectId) return;
    queryClient.invalidateQueries({ queryKey: ["artifacts", projectId] });
  }, [projectId, queryClient]);

  useRunEvents(activeRun, roughIdea, onComplete);

  const runActive =
    !!activeRun &&
    ["queued", "running", "waiting_for_human", "cancelling"].includes(
      activeRun.status,
    );
  const rawRunCheckpoint = activeRun?.run_checkpoint ??
    runsData?.runs.find((run) => !!run.run_checkpoint)?.run_checkpoint ??
    null;
  const rawRunCheckpointKey = runCheckpointKey(rawRunCheckpoint);
  const dismissedRunCheckpointKey = projectId ? dismissedRunCheckpointKeys[projectId] ?? "" : "";
  const runCheckpoint =
    rawRunCheckpoint && !runActive && rawRunCheckpointKey !== dismissedRunCheckpointKey
      ? rawRunCheckpoint
      : null;
  const startMut = useMutation({
    mutationFn: async () => {
      const replacementStage = projectId ? rawRunCheckpoint : null;
      setContinueReplacementStage(replacementStage);
      if (projectId) trimRunStatusMessagesForContinue(replacementStage);
      else clearMessages();
      const trimmed = projectId ? "" : input.trim();
      const runIdea = projectId ? "" : (trimmed || roughIdea);
      if (!canWrite) throw new Error("需要啟動碼才能執行此操作");
      if (!projectId && !runIdea) throw new Error("請先輸入初步想法");
      const runConfig = projectId
        ? (await queryClient.fetchQuery({
            queryKey: ["config"],
            queryFn: async () => (await fetchConfig()).config,
          }))
        : undefined;
      const stageOverridesForRun = projectId
        ? restrictCompletedStageOverrides(
            stageOverridesForCheckpoint(
              stageOverridesWithForce(stageOverrides, runConfig),
              rawRunCheckpoint,
            ),
            docsComplete,
          )
        : undefined;
      const targetProjectId = projectId ?? (await createProject(runIdea)).project_id;
      if (!projectId && stagedReferenceFiles.length) {
        for (const file of stagedReferenceFiles) {
          await uploadReference(targetProjectId, file);
        }
      }
      const attachedPaths = referenceRows
        .filter((r) => attachedDocIds.includes(r.id))
        .map((r) => `${targetProjectId}/${r.name}`);
      const stagedPaths = !projectId
        ? stagedReferenceFiles.map((file) => `${targetProjectId}/${file.name}`)
        : [];
      const run = await createRun({
        project_id: targetProjectId,
        mode: projectId ? "continue" : "new",
        rounds: projectId || meetingRoundsOverridden ? meetingRounds : undefined,
        max_issues: meetingMaxIssuesOverridden ? meetingMaxIssues : undefined,
        rough_idea: runIdea || undefined,
        attached_reference_paths: [...attachedPaths, ...stagedPaths].length
          ? [...attachedPaths, ...stagedPaths]
          : undefined,
        enable_agents: enabledAgents,
        stage_overrides: stageOverridesForRun,
      });
      return { run, initialIdea: runIdea };
    },
    onSuccess: async ({ run, initialIdea }) => {
      setInput("");
      if (initialIdea) {
        setMessages(mergeChatMessages([buildInitialUserMessage(initialIdea)]));
      }
      clearAttachedDocs();
      clearStagedReferenceFiles();
      setActiveProjectId(run.project_id);
      await queryClient.fetchQuery({
        queryKey: ["bootstrap"],
        queryFn: fetchBootstrap,
      });
      queryClient.invalidateQueries({ queryKey: ["runs", run.project_id] });
      queryClient.invalidateQueries({ queryKey: ["project", run.project_id] });
      queryClient.invalidateQueries({ queryKey: ["references", run.project_id] });
    },
    onError: (e: Error) => {
      if (e.message !== "cancelled") {
        pushNotice({
          tone: "error",
          title: "啟動失敗",
          message: errorMessage(e, "無法啟動 Agent 執行"),
        });
      }
    },
  });

  const cancelMut = useMutation({
    mutationFn: () => cancelRun(activeRun!.run_id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["runs"] });
      if (projectId) {
        queryClient.invalidateQueries({ queryKey: ["runs", projectId] });
        queryClient.invalidateQueries({ queryKey: ["project", projectId] });
      }
    },
    onError: (e: Error) => {
      pushNotice({
        tone: "error",
        title: "停止失敗",
        message: errorMessage(e, "無法停止 Agent 執行"),
      });
    },
  });

  const skipAllHumanInterventionsMut = useMutation({
    mutationFn: () => {
      if (!activeRun?.pending_decision) throw new Error("目前沒有可跳過的人類介入");
      return submitDecision(activeRun.run_id, activeRun.pending_decision.id, {
        skip_all_human_interventions: true,
      });
    },
    onSuccess: () => {
      setInput("");
      setReviewSuggestions([]);
      queryClient.invalidateQueries({ queryKey: ["runs"] });
      if (projectId) {
        queryClient.invalidateQueries({ queryKey: ["runs", projectId] });
      }
    },
    onError: (e: Error) => {
      pushNotice({
        tone: "error",
        title: "跳過失敗",
        message: errorMessage(e, "無法跳過後續人類介入"),
      });
    },
  });

  const deleteProjectMut = useMutation({
    mutationFn: async () => {
      if (!projectId) throw new Error("未選擇專案");
      return deleteProject(projectId);
    },
    onSuccess: async () => {
      setConfirmDeleteProjectOpen(false);
      setActiveProjectId(null);
      await queryClient.fetchQuery({
        queryKey: ["bootstrap"],
        queryFn: fetchBootstrap,
      });
    },
    onError: (e: Error) => {
      pushNotice({
        tone: "error",
        title: "刪除失敗",
        message: errorMessage(e, "刪除失敗"),
      });
    },
  });

  const stopping = activeRun?.status === "cancelling" || cancelMut.isPending;
  const continueStageSyncPending = !!projectId && !artifacts.isSuccess;
  const stageDisabled = runActive || !canWrite || continueStageSyncPending;
  const stageDisabledReason = !canWrite
    ? "需要啟動碼才能調整階段"
    : continueStageSyncPending
      ? "讀取專案階段中"
      : undefined;

  return (
    <PanelChrome
      title="工作區"
      actions={
        <>
          <WorkspaceFlowIndex
            compact={headerCompact}
            runCheckpoint={runCheckpoint}
            artifactItems={artifactItems ?? []}
            completedDisplayOnly={docsComplete}
          />
          <StageToggleMenu
            disabled={stageDisabled}
            disabledReason={stageDisabledReason}
            stageOverrides={stageOverrides}
            existingOutputs={existingStageOutputs}
            compact={headerCompact}
            enabledRowIds={docsComplete ? ["general_meeting", "DR", "SRS"] : undefined}
          />
        </>
      }
      trailing={
        <ProjectHeaderActions
          compact={headerCompact}
          deletingProject={deleteProjectMut.isPending}
          onRequestDeleteProject={() => {
            if (projectId) setConfirmDeleteProjectOpen(true);
          }}
        />
      }
      bodyClassName="flex flex-col"
    >
      <div ref={panelMeasureRef} className="pointer-events-none absolute inset-x-0 top-0 h-0 overflow-hidden opacity-0" />
      <div
        className="relative flex min-h-0 flex-1 flex-col"
        onDragOver={handleReviewDockDragOver}
        onDragLeave={handleReviewDockDragLeave}
        onDrop={handleReviewDockDrop}
      >
        <div className="relative min-h-0 flex-1 flex flex-col bg-slate-50/50">
          <div className="min-h-0 flex-1">
            <ChatFeed
              key={projectId || "new-project"}
              projectId={projectId}
              artifactItems={artifactItems ?? []}
              historyLoading={historyLoading}
              activeRun={activeRun}
            />
          </div>
          {activeRun?.status === "waiting_for_human" && activeRun.pending_decision && (
            <DecisionDock
              run={activeRun}
              reviewSuggestions={reviewSuggestions}
              onClearReviewSuggestions={() => setReviewSuggestions([])}
              onEditReviewSuggestion={(index) => {
                const value = reviewSuggestions[index];
                if (!value) return;
                setInput(value.text);
                setPendingReviewReferences(value.references ?? []);
                setReviewSuggestions((items) => items.filter((_, i) => i !== index));
              }}
              onRemoveReviewSuggestion={(index) => {
                setReviewSuggestions((items) => items.filter((_, i) => i !== index));
              }}
              customStakeholders={customStakeholders}
              onClearCustomStakeholders={() => setCustomStakeholders([])}
              onUpdateCustomStakeholder={(id, patch) => {
                setCustomStakeholders((items) =>
                  items.map((item) => (item.id === id ? { ...item, ...patch } : item)),
                );
              }}
              onRemoveCustomStakeholder={(id) => {
                setCustomStakeholders((items) => items.filter((item) => item.id !== id));
              }}
              customDecisionText={input}
              onClearCustomDecisionText={() => setInput("")}
              onRegisterHumanDecisionConfirm={(handler) => {
                humanDecisionConfirmRef.current = handler;
              }}
              onReviewDragOver={handleReviewDockDragOver}
              onReviewDragLeave={handleReviewDockDragLeave}
              onReviewDrop={handleReviewDockDrop}
            />
          )}
        </div>
        <MeetingComposer
          value={input}
          onChange={setInput}
          disabled={runActive || !canWrite || continueStageSyncPending}
          noProject={!projectId}
          loading={startMut.isPending || cancelMut.isPending}
          running={runActive}
          stopping={stopping}
          readonlyAgentSettings={false}
          canWrite={canWrite}
          runCheckpoint={runCheckpoint}
          stageOverrides={agentStageOverrides}
          reviewDragOver={reviewDockDragOver}
          onDismissRunCheckpoint={() => {
            if (projectId && rawRunCheckpointKey) {
              dismissRunCheckpoint(projectId, rawRunCheckpointKey);
            }
          }}
          submitLabel={projectId && docsComplete ? "執行" : undefined}
          submitDisabled={false}
          reviewMode={reviewMode}
          humanDecisionMode={activeRun?.pending_decision?.kind === "human_decision"}
          reviewTarget={reviewTarget}
          reviewReferences={pendingReviewReferences ?? []}
          onReviewReferencesChange={setPendingReviewReferences}
          mentionOptions={mentionOptions}
          referenceMentionOptions={referenceMentionOptions}
          stakeholderSelectionMode={activeRun?.pending_decision?.kind === "stakeholder_selection"}
          stakeholderTypeOptions={STAKEHOLDER_TYPES}
          customStakeholderDraft={customStakeholderDraft}
          onCustomStakeholderDraftChange={(patch) => {
            setCustomStakeholderDraft((draft) => ({ ...draft, ...patch }));
          }}
          onAddCustomStakeholder={addCustomStakeholder}
          onAddReviewSuggestion={(suggestion) => {
            const text = (suggestion?.text ?? input).trim();
            const references = suggestion?.references ?? [];
            if (!text && !references.length) return;
            setReviewSuggestions((items) => [...items, { text, references }]);
            setInput("");
            setPendingReviewReferences([]);
          }}
          onConfirmHumanDecision={() => humanDecisionConfirmRef.current?.()}
          onSkipAllHumanInterventions={() => skipAllHumanInterventionsMut.mutate()}
          skipAllHumanInterventionsLoading={skipAllHumanInterventionsMut.isPending}
          onSubmit={() => startMut.mutate()}
          onStop={() => cancelMut.mutate()}
        />
        {confirmDeleteProjectOpen && (
          <div
            className="absolute inset-0 z-30 flex items-center justify-center bg-white/80 px-4 backdrop-blur-sm"
            onClick={() => setConfirmDeleteProjectOpen(false)}
          >
            <div
              className="w-full max-w-[300px] rounded-card border border-gray-200 bg-white p-4 shadow-lg"
              onClick={(event) => event.stopPropagation()}
            >
              <div className="mb-3">
                <p className="text-[15px] font-semibold text-slate-900">刪除專案？</p>
                <p className="mt-1 text-xs leading-5 text-slate-500">
                  此動作無法復原。
                </p>
              </div>
              <div className="flex justify-center gap-2">
                <button
                  type="button"
                  className="rounded-control border border-gray-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-gray-50"
                  onClick={() => setConfirmDeleteProjectOpen(false)}
                >
                  取消
                </button>
                <button
                  type="button"
                  className="rounded-control bg-red-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-50"
                  disabled={deleteProjectMut.isPending || !canWrite}
                  onClick={() => deleteProjectMut.mutate()}
                >
                  刪除
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </PanelChrome>
  );
}
