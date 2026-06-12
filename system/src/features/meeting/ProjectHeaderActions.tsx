import { useQuery } from "@tanstack/react-query";
import { BookOpen, Check, ChevronDown, MoreHorizontal, Plus, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { fetchArtifacts, manualIndexUrl } from "@/api/projects";
import { useBootstrap } from "@/hooks/useBootstrap";
import { useActiveRun } from "@/hooks/useActiveRun";
import { useUiStore } from "@/stores/uiStore";

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

interface ProjectHeaderActionsProps {
  onRequestDeleteProject?: () => void;
  deletingProject?: boolean;
}

export function ProjectHeaderActions({
  onRequestDeleteProject,
  deletingProject = false,
}: ProjectHeaderActionsProps) {
  const bootstrap = useBootstrap();
  const projectId = useUiStore((s) => s.activeProjectId);
  const setActiveProjectId = useUiStore((s) => s.setActiveProjectId);
  const canWrite = useUiStore((s) => s.canWrite);
  const { activeRun } = useActiveRun(projectId);
  const [projectMenuOpen, setProjectMenuOpen] = useState(false);
  const [actionMenuOpen, setActionMenuOpen] = useState(false);
  const projectMenuRef = useRef<HTMLDivElement>(null);
  const actionMenuRef = useRef<HTMLDivElement>(null);

  const runActive =
    !!activeRun &&
    ["queued", "running", "waiting_for_human", "cancelling"].includes(
      activeRun.status,
    );

  const projects = bootstrap.data?.projects ?? [];
  const hasProjects = projects.length > 0;
  const current = projects.find((p) => p.project_id === projectId);
  const artifactsQuery = useQuery({
    queryKey: ["artifacts", projectId],
    queryFn: () => fetchArtifacts(projectId!),
    enabled: !!projectId,
  });
  const hasManual = (artifactsQuery.data?.items ?? []).some(
    (item) => item.kind === "file" && item.path === "manual/index.html",
  );

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

  return (
    <div className="relative flex min-w-0 items-center gap-1.5">
      {projectId && hasManual && (
        <button
          type="button"
          className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-control border border-gray-200 bg-white text-slate-700 hover:border-gray-300 hover:bg-gray-50 focus:border-slate-400 focus:outline-none"
          aria-label="說明文件"
          title="說明文件"
          onClick={() => {
            window.open(manualIndexUrl(projectId), "_blank", "noopener,noreferrer");
          }}
        >
          <BookOpen className="h-3.5 w-3.5" />
        </button>
      )}

      <div ref={projectMenuRef} className="relative w-44 shrink-0">
        <button
          type="button"
          disabled={runActive || !hasProjects}
          className="flex h-8 w-full items-center justify-between rounded-control border border-gray-200 bg-white px-2 text-left text-xs text-slate-700 hover:border-gray-300 focus:border-slate-400 focus:outline-none disabled:cursor-not-allowed disabled:opacity-50"
          aria-label="選擇專案"
          title={
            current
              ? `${current.project_id} — ${current.scenario ?? current.rough_idea ?? ""}`
              : projectId
                ? projectId
              : hasProjects
                ? "選擇專案"
                : "目前沒有可選擇的專案"
          }
          onClick={() => {
            if (!runActive && hasProjects) setProjectMenuOpen((open) => !open);
          }}
        >
          <span className={projectId ? "min-w-0 truncate text-slate-700" : "text-slate-400"}>
            {current ? projectOptionLabel(current, true) : projectId ?? "選擇專案"}
          </span>
          <ChevronDown className="h-3.5 w-3.5 shrink-0 text-slate-400" />
        </button>
        {projectMenuOpen && (
          <div className="absolute left-0 right-0 top-full z-40 mt-1 max-h-52 overflow-y-auto rounded-control border border-gray-200 bg-white py-1 shadow-lg">
            {projects.map((p) => (
              <button
                key={p.project_id}
                type="button"
                className={`flex w-full items-center justify-between gap-2 px-2 py-1.5 text-left text-xs hover:bg-gray-50 ${
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

      {projectId && (
        <div ref={actionMenuRef} className="relative shrink-0">
          <button
            type="button"
            className="inline-flex shrink-0 items-center rounded p-1 text-slate-400 hover:bg-gray-50 hover:text-slate-700"
            aria-label="專案操作"
            title="專案操作"
            onClick={() => setActionMenuOpen((open) => !open)}
          >
            <MoreHorizontal className="h-3.5 w-3.5" />
          </button>
          {actionMenuOpen && (
            <div className="absolute right-0 top-full z-40 mt-3 w-28 rounded-control border border-gray-200 bg-white py-1 shadow-lg">
              <button
                type="button"
                disabled={runActive || !canWrite}
                className="flex w-full items-center gap-2 px-2 py-1.5 text-left text-xs text-slate-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-40"
                onClick={() => {
                  setActionMenuOpen(false);
                  setActiveProjectId(null);
                }}
              >
                <Plus className="h-3.5 w-3.5" />
                新增專案
              </button>
              <button
                type="button"
                disabled={deletingProject || runActive || !canWrite}
                className="flex w-full items-center gap-2 px-2 py-1.5 text-left text-xs text-red-600 hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-40"
                onClick={() => {
                  setActionMenuOpen(false);
                  onRequestDeleteProject?.();
                }}
              >
                <Trash2 className="h-3.5 w-3.5" />
                刪除專案
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
