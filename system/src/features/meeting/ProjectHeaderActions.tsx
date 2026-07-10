import { useQuery } from "@tanstack/react-query";
import { BookOpen, Check, ChevronDown, Coins, MoreHorizontal, Plus, Trash2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { ApiError } from "@/api/client";
import { fetchArtifacts, fetchCostSummary, manualIndexUrl } from "@/api/projects";
import { useBootstrap } from "@/hooks/useBootstrap";
import { useActiveRun } from "@/hooks/useActiveRun";
import { useI18n } from "@/i18n";
import { useUiStore } from "@/stores/uiStore";
import { errorMessage } from "@/utils/errorMessage";
import { CostSummaryModal } from "./CostSummaryModal";

const ACTIVE_PROJECT_STATUSES = new Set([
  "queued",
  "running",
  "waiting_for_human",
  "cancelling",
]);
const PUBLIC_READABLE_RESULT_STATUSES = new Set(["completed", "idle"]);

function projectOptionLabel(project: {
  project_id: string;
  rough_idea?: string;
  scenario?: string;
}, selected = false): string {
  const scenario = String(project.scenario ?? "").trim();
  const fallback = String(project.rough_idea ?? "").trim();
  const label = scenario || fallback || project.project_id;
  const max = selected ? 18 : 28;
  const snippet =
    label.length > max ? `${label.slice(0, max)}…` : label;
  return snippet;
}

function isVisibleProject(project: {
  project_id: string;
  rough_idea?: string;
  scenario?: string;
  has_results?: boolean;
  active_run?: unknown;
  status_hint?: string;
}) {
  if (String(project.scenario ?? project.rough_idea ?? "").trim()) return true;
  if (project.has_results) return true;
  if (project.active_run) return true;
  const status = String(project.status_hint ?? "").trim();
  return !!status && status !== "idle";
}

function isPublicReadableProject(project: {
  has_results?: boolean;
  active_run?: unknown;
  status_hint?: string;
}) {
  const status = String(project.status_hint ?? "").trim();
  return (
    !!project.has_results &&
    !project.active_run &&
    !ACTIVE_PROJECT_STATUSES.has(status) &&
    PUBLIC_READABLE_RESULT_STATUSES.has(status || "idle")
  );
}

function uniqueProjectsById<T extends { project_id: string }>(projects: T[]): T[] {
  const seen = new Set<string>();
  return projects.filter((project) => {
    if (seen.has(project.project_id)) return false;
    seen.add(project.project_id);
    return true;
  });
}

function costSummaryErrorMessage(
  error: unknown,
  t: ReturnType<typeof useI18n>["t"],
): string | null {
  if (!error) return null;
  if (error instanceof ApiError && error.status === 404) {
    return t.costSummaryMissing;
  }
  return errorMessage(error, t.costSummaryReadFailed);
}

interface ProjectHeaderActionsProps {
  onRequestDeleteProject?: () => void;
  deletingProject?: boolean;
  compact?: boolean;
}

export function ProjectHeaderActions({
  onRequestDeleteProject,
  deletingProject = false,
  compact = false,
}: ProjectHeaderActionsProps) {
  const { t } = useI18n();
  const bootstrap = useBootstrap();
  const projectId = useUiStore((s) => s.activeProjectId);
  const setActiveProjectId = useUiStore((s) => s.setActiveProjectId);
  const canWrite = useUiStore((s) => s.canWrite);
  const [projectMenuOpen, setProjectMenuOpen] = useState(false);
  const [actionMenuOpen, setActionMenuOpen] = useState(false);
  const [costModalOpen, setCostModalOpen] = useState(false);
  const projectMenuRef = useRef<HTMLDivElement>(null);
  const actionMenuRef = useRef<HTMLDivElement>(null);

  const projects = useMemo(
    () => uniqueProjectsById(bootstrap.data?.projects ?? []),
    [bootstrap.data?.projects],
  );
  const hasWriteAccess = canWrite || bootstrap.data?.activated === true;
  const visibleProjects = useMemo(
    () =>
      projects.filter((project) => {
        if (!hasWriteAccess && !isPublicReadableProject(project)) return false;
        return project.project_id === projectId || isVisibleProject(project);
      }),
    [hasWriteAccess, projectId, projects],
  );
  const hasProjects = visibleProjects.length > 0;
  const current = projects.find(
    (p) =>
      p.project_id === projectId &&
      (hasWriteAccess || isPublicReadableProject(p)),
  );
  const readableProjectId = projectId && (hasWriteAccess || current) ? projectId : null;
  const { activeRun } = useActiveRun(readableProjectId);
  const runActive =
    !!activeRun &&
    ["queued", "running", "waiting_for_human", "cancelling"].includes(
      activeRun.status,
    );
  const artifactsQuery = useQuery({
    queryKey: ["artifacts", readableProjectId],
    queryFn: () => fetchArtifacts(readableProjectId!),
    enabled: !!readableProjectId,
  });
  const hasManual = (artifactsQuery.data?.items ?? []).some(
    (item) => item.kind === "file" && item.path === "manual/index.html",
  );
  const hasCostSummary = !!current?.has_cost_summary;
  const costQuery = useQuery({
    queryKey: ["cost-summary", readableProjectId],
    queryFn: () => fetchCostSummary(readableProjectId!),
    enabled: !!readableProjectId && hasCostSummary && costModalOpen,
  });

  useEffect(() => {
    const onPointerDown = (event: PointerEvent) => {
      if (!projectMenuRef.current?.contains(event.target as Node)) {
        setProjectMenuOpen(false);
      }
      if (!actionMenuRef.current?.contains(event.target as Node)) {
        setActionMenuOpen(false);
      }
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, []);

  useEffect(() => {
    if (!runActive) return;
    setProjectMenuOpen(false);
    setActionMenuOpen(false);
  }, [runActive]);

  useEffect(() => {
    if (hasProjects) return;
    setProjectMenuOpen(false);
  }, [hasProjects]);

  useEffect(() => {
    setCostModalOpen(false);
  }, [projectId]);

  return (
    <div className="relative flex min-w-0 items-center gap-1.5">
      {readableProjectId && hasCostSummary && !compact && (
        <button
          type="button"
          className="inline-flex h-7 shrink-0 items-center gap-1.5 rounded-control border border-gray-200 bg-white px-2.5 text-xs font-medium text-slate-700 hover:border-gray-300 hover:bg-gray-50 focus:border-slate-400 focus:outline-none"
          aria-label={t.cost}
          title={t.cost}
          onClick={() => setCostModalOpen(true)}
        >
          <Coins className="h-3.5 w-3.5" />
          <span>{t.cost}</span>
        </button>
      )}

      {readableProjectId && hasManual && !compact && (
        <button
          type="button"
          className="inline-flex h-7 shrink-0 items-center gap-1.5 rounded-control border border-gray-200 bg-white px-2.5 text-xs font-medium text-slate-700 hover:border-gray-300 hover:bg-gray-50 focus:border-slate-400 focus:outline-none"
          aria-label={t.manual}
          title={t.manual}
          onClick={() => {
            window.open(manualIndexUrl(readableProjectId), "_blank", "noopener");
          }}
        >
          <BookOpen className="h-3.5 w-3.5" />
          <span>{t.manual}</span>
        </button>
      )}

      <div ref={projectMenuRef} className="relative w-44 shrink-0">
        <button
          type="button"
          disabled={runActive || !hasProjects}
          className="flex h-8 w-full items-center justify-between rounded-control border border-gray-200 bg-white px-2 text-left text-xs text-slate-700 hover:border-gray-300 focus:border-slate-400 focus:outline-none disabled:cursor-not-allowed disabled:opacity-50"
          aria-label={t.selectProject}
          title={
            current
              ? `${current.project_id} — ${current.scenario ?? current.rough_idea ?? ""}`
              : readableProjectId
                ? readableProjectId
              : hasProjects
                ? t.selectProject
                : t.noProjects
          }
          onClick={() => {
            if (!runActive && hasProjects) setProjectMenuOpen((open) => !open);
          }}
        >
          <span className={readableProjectId ? "min-w-0 truncate text-slate-700" : "text-slate-400"}>
            {current ? projectOptionLabel(current, true) : readableProjectId ?? t.selectProject}
          </span>
          <ChevronDown className="h-3.5 w-3.5 shrink-0 text-slate-400" />
        </button>
        {projectMenuOpen && (
          <div className="absolute left-0 right-0 top-full z-40 mt-1 max-h-52 overflow-y-auto rounded-control border border-gray-200 bg-white py-1 shadow-lg">
            {visibleProjects.map((p) => (
              <button
                key={p.project_id}
                type="button"
                className={`flex w-full items-center justify-between gap-2 px-2 py-2 text-left text-xs hover:bg-gray-50 ${
                  p.project_id === projectId
                    ? "bg-slate-50 font-semibold text-slate-900"
                    : "text-slate-700"
                }`}
                title={`${p.project_id} — ${p.scenario ?? p.rough_idea ?? ""}`}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => {
                  setActiveProjectId(p.project_id);
                  setProjectMenuOpen(false);
                }}
              >
                <span className="min-w-0 truncate">
                  {projectOptionLabel(p, p.project_id === projectId)}
                </span>
                {p.project_id === projectId && (
                  <Check className="h-3.5 w-3.5 shrink-0 text-slate-700" />
                )}
              </button>
            ))}
          </div>
        )}
      </div>

      {readableProjectId && (
        <div ref={actionMenuRef} className="relative shrink-0">
          <button
            type="button"
            className="inline-flex shrink-0 items-center rounded p-1 text-slate-400 hover:bg-gray-50 hover:text-slate-700"
            aria-label={t.projectActions}
            title={t.projectActions}
            onClick={() => setActionMenuOpen((open) => !open)}
          >
            <MoreHorizontal className="h-3.5 w-3.5" />
          </button>
          {actionMenuOpen && (
            <div className="absolute right-0 top-full z-40 mt-3 w-32 rounded-control border border-gray-200 bg-white py-1 shadow-lg">
              {readableProjectId && hasCostSummary && compact && (
                <button
                  type="button"
                  className="flex w-full items-center gap-2 px-2 py-1.5 text-left text-xs text-slate-700 hover:bg-gray-50"
                  onClick={() => {
                    setActionMenuOpen(false);
                    setCostModalOpen(true);
                  }}
                >
                  <Coins className="h-3.5 w-3.5" />
                  {t.cost}
                </button>
              )}
              {hasManual && compact && (
                <button
                  type="button"
                  className="flex w-full items-center gap-2 px-2 py-1.5 text-left text-xs text-slate-700 hover:bg-gray-50"
                  onClick={() => {
                    setActionMenuOpen(false);
                    window.open(manualIndexUrl(readableProjectId), "_blank", "noopener");
                  }}
                >
                  <BookOpen className="h-3.5 w-3.5" />
                  {t.manual}
                </button>
              )}
              <button
                type="button"
                disabled={runActive || !hasWriteAccess}
                className="flex w-full items-center gap-2 px-2 py-1.5 text-left text-xs text-slate-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-40"
                onClick={() => {
                  setActionMenuOpen(false);
                  setActiveProjectId(null);
                }}
              >
                <Plus className="h-3.5 w-3.5" />
                {t.newProject}
              </button>
              <button
                type="button"
                disabled={deletingProject || runActive || !hasWriteAccess}
                className="flex w-full items-center gap-2 px-2 py-1.5 text-left text-xs text-red-600 hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-40"
                onClick={() => {
                  setActionMenuOpen(false);
                  onRequestDeleteProject?.();
                }}
              >
                <Trash2 className="h-3.5 w-3.5" />
                {t.deleteProject}
              </button>
            </div>
          )}
        </div>
      )}
      {costModalOpen && hasCostSummary && (
        <CostSummaryModal
          summary={costQuery.data?.cost_summary}
          loading={costQuery.isLoading || costQuery.isFetching}
          error={costSummaryErrorMessage(costQuery.error, t)}
          onClose={() => setCostModalOpen(false)}
        />
      )}
    </div>
  );
}
