import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";
import { createProject, uploadReference } from "@/api/projects";
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
import { ChatFeed } from "./ChatFeed";
import { DecisionDock } from "./DecisionDock";
import { MeetingComposer } from "./MeetingComposer";
import { ProjectHeaderActions } from "./ProjectHeaderActions";
import { StatusBar } from "./StatusBar";
import { WorkspaceFlowIndex } from "./WorkspaceFlowIndex";

interface MeetingPanelProps {
  projectId: string | null;
}

export function MeetingPanel({ projectId }: MeetingPanelProps) {
  const queryClient = useQueryClient();
  const { project, references, artifacts } = useProjectData(projectId);
  const { activeRun } = useActiveRun(projectId);
  const clearMessages = useChatStore((s) => s.clearMessages);
  const pushNotice = useNoticeStore((s) => s.pushNotice);
  const meetingRounds = useUiStore((s) => s.meetingRounds);
  const enabledAgents = useUiStore((s) => s.enabledAgents);
  const attachedDocIds = useUiStore((s) => s.attachedDocIds);
  const clearAttachedDocs = useUiStore((s) => s.clearAttachedDocs);
  const setActiveProjectId = useUiStore((s) => s.setActiveProjectId);
  const stagedReferenceFiles = useUiStore((s) => s.stagedReferenceFiles);
  const clearStagedReferenceFiles = useUiStore((s) => s.clearStagedReferenceFiles);

  const roughIdea =
    (project.data?.project?.rough_idea as string | undefined) ?? "";
  const [input, setInput] = useState("");
  const [lastLog, setLastLog] = useState("");

  useEffect(() => {
    setInput("");
  }, [projectId]);

  const referenceRows = projectId
    ? buildReferenceRows(references.data?.references ?? [])
    : buildReferenceRows(stagedReferenceFiles.map((file) => ({ name: file.name })));

  const artifactItems = artifacts.data?.items;
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

  const { events } = useRunEvents(activeRun, roughIdea, onComplete);

  useEffect(() => {
    const logs = events.filter((e) => e.type === "log");
    const last = logs[logs.length - 1];
    if (last?.message) setLastLog(last.message);
  }, [events]);

  const runActive =
    !!activeRun &&
    ["queued", "running", "waiting_for_human", "cancelling"].includes(
      activeRun.status,
    );

  const startMut = useMutation({
    mutationFn: async () => {
      clearMessages();
      const trimmed = input.trim() || roughIdea;
      if (!trimmed) throw new Error("請先輸入初步想法");
      const targetProjectId = projectId ?? (await createProject(trimmed)).project_id;
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
      return createRun({
        project_id: targetProjectId,
        mode: projectId ? "continue" : "new",
        rounds: meetingRounds,
        rough_idea: trimmed,
        attached_reference_paths: [...attachedPaths, ...stagedPaths].length
          ? [...attachedPaths, ...stagedPaths]
          : undefined,
        enable_agents: enabledAgents,
      });
    },
    onSuccess: (run) => {
      setInput("");
      setActiveProjectId(run.project_id);
      clearAttachedDocs();
      clearStagedReferenceFiles();
      queryClient.invalidateQueries({ queryKey: ["runs", run.project_id] });
      queryClient.invalidateQueries({ queryKey: ["project", run.project_id] });
      queryClient.invalidateQueries({ queryKey: ["references", run.project_id] });
      queryClient.invalidateQueries({ queryKey: ["bootstrap"] });
    },
    onError: (e: Error) => {
      if (e.message !== "cancelled") {
        pushNotice({
          tone: "error",
          title: "啟動失敗",
          message: e.message || "無法啟動工作坊",
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
        message: e.message || "無法停止工作坊",
      });
    },
  });

  const stopping = activeRun?.status === "cancelling" || cancelMut.isPending;

  return (
    <PanelChrome
      title="工作區"
      actions={<WorkspaceFlowIndex />}
      trailing={<ProjectHeaderActions />}
      subheader={
        <StatusBar
          run={activeRun}
          lastLogMessage={lastLog}
          historyLoading={historyLoading}
        />
      }
      bodyClassName="flex flex-col"
    >
      <div className="relative min-h-0 flex-1 flex flex-col bg-slate-50/50">
        <div className="min-h-0 flex-1">
          <ChatFeed
            historyLoading={historyLoading}
          />
        </div>
        {activeRun?.status === "waiting_for_human" && activeRun.pending_decision && (
          <DecisionDock run={activeRun} />
        )}
      </div>
      {(!projectId || runActive) && (
        <MeetingComposer
          value={input}
          onChange={setInput}
          disabled={runActive}
          noProject={!projectId}
          loading={startMut.isPending || cancelMut.isPending}
          running={runActive}
          stopping={stopping}
          onSubmit={() => startMut.mutate()}
          onStop={() => cancelMut.mutate()}
        />
      )}
    </PanelChrome>
  );
}
