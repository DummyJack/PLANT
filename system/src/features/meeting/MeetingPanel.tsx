import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createProject, deleteProject, uploadReference } from "@/api/projects";
import { fetchBootstrap } from "@/api/bootstrap";
import { cancelRun, createRun } from "@/api/runs";
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
import { ChatFeed } from "./ChatFeed";
import { DecisionDock } from "./DecisionDock";
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

interface CustomStakeholder {
  id: string;
  name: string;
  type: string;
  reason: string;
}

function completedStageOverrides(
  projectId: string | null,
  items: Array<{ path: string; kind: string }> | undefined,
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

  close(["init"]);
  if (paths.has("artifact/meeting/elicitation_meeting.json")) close(["elicitation"]);
  if (
    paths.has("artifact/result.json") ||
    has(/^artifact\/report\/conflict_report_v\d+\.(?:json|md)$/i) ||
    has(/^results\/report\/conflict_report_v\d+\.html$/i)
  ) {
    close(["conflict_detection"]);
  }
  if (paths.has("artifact/feedback.json")) close(["research_domain"]);
  if (paths.has("artifact/system_models.json") || has(/^artifact\/models\/.+/i)) {
    close(["system_model"]);
  }
  if (has(/^artifact\/drafts\/draft_v\d+\.md$/i) || has(/^results\/drafts\/draft_v\d+\.html$/i)) {
    close(["default_update_draft", "general_update_draft"]);
  }
  if (
    has(/^artifact\/meeting\/formal_meeting_r1\.json$/i) ||
    has(/^results\/MoM\/R1-M\d+\.html$/i)
  ) {
    close(["default_formal_meeting", "default_update_draft"]);
  }
  if (
    has(/^artifact\/meeting\/formal_meeting_r(?:[2-9]|\d{2,})\.json$/i) ||
    has(/^results\/MoM\/R(?:[2-9]|\d{2,})-M\d+\.html$/i)
  ) {
    close(["general_formal_meeting", "general_update_draft"]);
  }
  if (paths.has("output/design_rationale.md") || paths.has("results/design_rationale.html")) {
    close(["DR"]);
  }
  if (paths.has("output/srs.md") || paths.has("results/srs.html")) {
    close(["SRS"]);
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

export function MeetingPanel({ projectId }: MeetingPanelProps) {
  const queryClient = useQueryClient();
  const { project, references, artifacts } = useProjectData(projectId);
  const { activeRun } = useActiveRun(projectId);
  const clearMessages = useChatStore((s) => s.clearMessages);
  const setMessages = useChatStore((s) => s.setMessages);
  const pushNotice = useNoticeStore((s) => s.pushNotice);
  const meetingRounds = useUiStore((s) => s.meetingRounds);
  const enabledAgents = useUiStore((s) => s.enabledAgents);
  const attachedDocIds = useUiStore((s) => s.attachedDocIds);
  const clearAttachedDocs = useUiStore((s) => s.clearAttachedDocs);
  const setActiveProjectId = useUiStore((s) => s.setActiveProjectId);
  const stagedReferenceFiles = useUiStore((s) => s.stagedReferenceFiles);
  const clearStagedReferenceFiles = useUiStore((s) => s.clearStagedReferenceFiles);
  const canWrite = useUiStore((s) => s.canWrite);
  const humanDecisionConfirmRef = useRef<(() => void) | null>(null);

  const roughIdea =
    (project.data?.project?.rough_idea as string | undefined) ?? "";
  const [input, setInput] = useState("");
  const [reviewSuggestions, setReviewSuggestions] = useState<string[]>([]);
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
    setCustomStakeholderDraft({ name: "", type: "", reason: "" });
    setCustomStakeholders([]);
  }, [projectId]);

  useEffect(() => {
    if (
      activeRun?.pending_decision?.kind !== "stakeholder_statement_review" &&
      activeRun?.pending_decision?.kind !== "requirements_review"
    ) {
      setReviewSuggestions([]);
    }
    if (activeRun?.pending_decision?.kind !== "stakeholder_selection") {
      setCustomStakeholderDraft({ name: "", type: "", reason: "" });
      setCustomStakeholders([]);
    }
  }, [
    activeRun?.pending_decision?.id,
    activeRun?.pending_decision?.kind,
  ]);

  const referenceRows = projectId
    ? buildReferenceRows(references.data?.references ?? [])
    : buildReferenceRows(stagedReferenceFiles.map((file) => ({ name: file.name })));
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
    (hasArtifactPath("output/design_rationale.md") ||
      hasArtifactPath("results/design_rationale.html")) &&
    (hasArtifactPath("output/srs.md") || hasArtifactPath("results/srs.html"));
  const stageOverrides = useMemo(
    () => completedStageOverrides(projectId, artifactItems),
    [projectId, artifactItems],
  );
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

  const startMut = useMutation({
    mutationFn: async () => {
      if (!projectId) clearMessages();
      const trimmed = projectId ? "" : input.trim();
      const runIdea = projectId ? "" : (trimmed || roughIdea);
      if (!canWrite) throw new Error("需要啟動碼才能執行此操作");
      if (!projectId && !runIdea) throw new Error("請先輸入初步想法");
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
        rounds: meetingRounds,
        rough_idea: runIdea || undefined,
        attached_reference_paths: [...attachedPaths, ...stagedPaths].length
          ? [...attachedPaths, ...stagedPaths]
          : undefined,
        enable_agents: enabledAgents,
        stage_overrides: projectId ? stageOverrides : undefined,
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
      await queryClient.fetchQuery({
        queryKey: ["bootstrap"],
        queryFn: fetchBootstrap,
      });
      setActiveProjectId(run.project_id);
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
    },
    onError: (e: Error) => {
      pushNotice({
        tone: "error",
        title: "停止失敗",
        message: errorMessage(e, "無法停止 Agent 執行"),
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
          <WorkspaceFlowIndex />
          <StageToggleMenu
            disabled={stageDisabled}
            disabledReason={stageDisabledReason}
            stageOverrides={stageOverrides}
          />
        </>
      }
      trailing={
        <ProjectHeaderActions
          deletingProject={deleteProjectMut.isPending}
          onRequestDeleteProject={() => {
            if (projectId) setConfirmDeleteProjectOpen(true);
          }}
        />
      }
      bodyClassName="flex flex-col"
    >
      <div className="relative flex min-h-0 flex-1 flex-col">
        <div className="relative min-h-0 flex-1 flex flex-col bg-slate-50/50">
          <div className="min-h-0 flex-1">
            <ChatFeed
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
                setInput(value);
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
          readonlyAgentSettings={!!projectId && !runActive}
          canWrite={canWrite}
          submitLabel={projectId && docsComplete ? "執行" : undefined}
          submitDisabled={!!projectId && docsComplete}
          reviewMode={
            activeRun?.pending_decision?.kind === "stakeholder_statement_review" ||
            activeRun?.pending_decision?.kind === "requirements_review"
          }
          humanDecisionMode={activeRun?.pending_decision?.kind === "human_decision"}
          reviewTarget={
            activeRun?.pending_decision?.kind === "requirements_review"
              ? "requirements"
              : "stakeholders"
          }
          mentionOptions={mentionOptions}
          stakeholderSelectionMode={activeRun?.pending_decision?.kind === "stakeholder_selection"}
          stakeholderTypeOptions={STAKEHOLDER_TYPES}
          customStakeholderDraft={customStakeholderDraft}
          onCustomStakeholderDraftChange={(patch) => {
            setCustomStakeholderDraft((draft) => ({ ...draft, ...patch }));
          }}
          onAddCustomStakeholder={addCustomStakeholder}
          onAddReviewSuggestion={() => {
            const text = input.trim();
            if (!text) return;
            setReviewSuggestions((items) => [...items, text]);
            setInput("");
          }}
          onConfirmHumanDecision={() => humanDecisionConfirmRef.current?.()}
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
