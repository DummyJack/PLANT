import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchConfig } from "@/api/config";
import { HeaderBar } from "@/features/header/HeaderBar";
import {
  WorkspaceLayout,
  type LayoutMode,
} from "@/features/layout/WorkspaceLayout";
import { NoticeStack } from "@/components/NoticeStack";
import { useBootstrap, useProjectData } from "@/hooks/useProjectQueries";
import { useI18n } from "@/i18n";
import { useChatStore } from "@/stores/chatStore";
import { useUiStore } from "@/stores/uiStore";
import { cn } from "@/utils/cn";
import type { FileTreeNode, ProjectSummary } from "@/types/api";

const EMPTY_ITEMS: FileTreeNode[] = [];
const ACTIVE_PROJECT_STATUSES = new Set([
  "queued",
  "running",
  "waiting_for_human",
  "cancelling",
]);
const PUBLIC_READABLE_RESULT_STATUSES = new Set(["completed", "idle"]);

function positiveConfigNumber(value: unknown): number | null {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? Math.floor(parsed) : null;
}

function currentLayoutMode(): LayoutMode {
  if (typeof window === "undefined") return "desktop";
  if (window.innerWidth < 768) return "mobile";
  if (window.innerWidth < 1200) return "tablet";
  return "desktop";
}

function useLayoutMode() {
  const [mode, setMode] = useState<LayoutMode>(() => currentLayoutMode());

  useEffect(() => {
    const update = () => setMode(currentLayoutMode());
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);

  return mode;
}

function isPublicReadableProject(project: ProjectSummary | undefined) {
  if (!project) return false;
  const status = String(project.status_hint ?? "").trim();
  return (
    !!project.has_results &&
    !project.active_run &&
    !ACTIVE_PROJECT_STATUSES.has(status) &&
    PUBLIC_READABLE_RESULT_STATUSES.has(status || "idle")
  );
}

export default function App() {
  const projectId = useUiStore((s) => s.activeProjectId);
  const setActiveProjectId = useUiStore((s) => s.setActiveProjectId);
  const canWrite = useUiStore((s) => s.canWrite);
  const clearMessages = useChatStore((s) => s.clearMessages);
  const clearAttachedDocs = useUiStore((s) => s.clearAttachedDocs);
  const setEnabledAgents = useUiStore((s) => s.setEnabledAgents);
  const setMeetingDefaults = useUiStore((s) => s.setMeetingDefaults);
  const visiblePanels = useUiStore((s) => s.visiblePanels);
  const darkMode = useUiStore((s) => s.darkMode);
  const { t } = useI18n();
  const layoutMode = useLayoutMode();
  const bootstrap = useBootstrap(true);
  const configQuery = useQuery({
    queryKey: ["config"],
    queryFn: async () => (await fetchConfig()).config,
    refetchInterval: 3000,
  });
  const currentProject = useMemo(
    () => bootstrap.data?.projects.find((project) => project.project_id === projectId),
    [bootstrap.data?.projects, projectId],
  );
  const hasActiveRun = !!(projectId && bootstrap.data?.active_runs?.[projectId]);
  const hasWriteAccess = canWrite || bootstrap.data?.activated === true;
  const readableProjectId = useMemo(() => {
    if (!projectId || !bootstrap.data) return null;
    if (!currentProject && !hasActiveRun) return null;
    if (hasWriteAccess) return projectId;
    return isPublicReadableProject(currentProject) ? projectId : null;
  }, [bootstrap.data, currentProject, hasActiveRun, hasWriteAccess, projectId]);
  const { artifacts } = useProjectData(readableProjectId);

  useEffect(() => {
    const config = configQuery.data;
    if (!config) return;
    if (config.enable_agents) {
      setEnabledAgents({
        ...useUiStore.getState().enabledAgents,
        ...config.enable_agents,
      });
    }
    const rounds = positiveConfigNumber(config.rounds);
    const maxIssues = positiveConfigNumber(config.max_issues);
    setMeetingDefaults(rounds, maxIssues);
  }, [configQuery.data, setEnabledAgents, setMeetingDefaults]);

  useEffect(() => {
    clearMessages();
    clearAttachedDocs();
  }, [readableProjectId, clearMessages, clearAttachedDocs]);

  useEffect(() => {
    if (!projectId || !bootstrap.data) return;
    if (bootstrap.isFetching) return;
    const project = bootstrap.data.projects.find((row) => row.project_id === projectId);
    const exists = !!project;
    const hasActiveRun = !!bootstrap.data.active_runs?.[projectId];
    if (hasWriteAccess && hasActiveRun) return;
    if (!hasWriteAccess && !isPublicReadableProject(project)) {
      setActiveProjectId(null);
      return;
    }
    if (!exists) setActiveProjectId(null);
  }, [bootstrap.data, bootstrap.isFetching, hasWriteAccess, projectId, setActiveProjectId]);

  const items = artifacts.data?.items ?? EMPTY_ITEMS;
  return (
    <div className={cn("flex h-full min-w-0 flex-col overflow-hidden bg-slate-50", darkMode && "theme-dark")}>
      <HeaderBar />
      <NoticeStack />
      <div className="min-h-0 min-w-0 flex-1 overflow-hidden p-1">
        <WorkspaceLayout
          emptyLabel={t.noPanelOpen}
          items={items}
          layoutMode={layoutMode}
          projectId={readableProjectId}
          visiblePanels={visiblePanels}
        />
      </div>
    </div>
  );
}
