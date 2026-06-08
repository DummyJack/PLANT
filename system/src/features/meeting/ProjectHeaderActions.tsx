import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { fetchBootstrap } from "@/api/bootstrap";
import { deleteProject } from "@/api/projects";
import { SelectControl } from "@/components/SelectControl";
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

export function ProjectHeaderActions() {
  const queryClient = useQueryClient();
  const bootstrap = useBootstrap();
  const projectId = useUiStore((s) => s.activeProjectId);
  const setActiveProjectId = useUiStore((s) => s.setActiveProjectId);
  const { activeRun } = useActiveRun(projectId);
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const runActive =
    !!activeRun &&
    ["queued", "running", "waiting_for_human", "cancelling"].includes(
      activeRun.status,
    );

  const deleteMut = useMutation({
    mutationFn: () => deleteProject(projectId!),
    onSuccess: async () => {
      setActiveProjectId(null);
      await queryClient.fetchQuery({
        queryKey: ["bootstrap"],
        queryFn: fetchBootstrap,
      });
    },
    onError: (e: Error) => {
      setDeleteError(e.message || "刪除失敗");
    },
  });

  const projects = bootstrap.data?.projects ?? [];
  const current = projects.find((p) => p.project_id === projectId);

  const handleDelete = () => {
    if (!projectId) return;
    setConfirmDeleteOpen(true);
  };

  const confirmDelete = () => {
    if (!projectId) return;
    setConfirmDeleteOpen(false);
    deleteMut.mutate();
  };

  return (
    <div className="relative flex min-w-0 items-center gap-1.5">
      <SelectControl
        wrapperClassName="w-44 shrink-0"
        className={projectId ? "w-full truncate text-slate-700" : "w-full text-slate-400"}
        value={projectId ?? ""}
        onChange={(e) => setActiveProjectId(e.target.value || null)}
        aria-label="選擇專案"
        title={
          current
            ? `${current.project_id} — ${current.scenario ?? current.rough_idea ?? ""}`
            : undefined
        }
      >
        <option value="">選擇專案</option>
        {projects.map((p) => (
          <option
            key={p.project_id}
            value={p.project_id}
            title={`${p.project_id} — ${p.scenario ?? p.rough_idea ?? ""}`}
          >
            {projectOptionLabel(p, p.project_id === projectId)}
          </option>
        ))}
      </SelectControl>

      {projectId && (
        <>
          <span className="group relative inline-flex shrink-0">
            <button
              type="button"
              className="inline-flex shrink-0 items-center rounded-control border border-red-200 bg-white p-1 text-red-600 hover:bg-red-50 disabled:opacity-40"
              onClick={handleDelete}
              disabled={deleteMut.isPending || runActive}
              aria-label="刪除專案"
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
            <span className="pointer-events-none absolute right-0 top-full z-40 mt-2 whitespace-nowrap rounded-control border border-gray-200 bg-white px-2 py-1 text-xs font-medium text-slate-700 opacity-0 shadow-md transition-opacity delay-500 duration-150 group-hover:opacity-100">
              刪除專案
            </span>
          </span>
          <span className="group relative inline-flex shrink-0">
            <button
              type="button"
              className="inline-flex shrink-0 items-center rounded-control border border-gray-200 bg-white p-1 text-slate-700 hover:bg-gray-50 disabled:opacity-40"
              onClick={() => setActiveProjectId(null)}
              disabled={runActive}
              aria-label="新增專案"
            >
              <Plus className="h-3.5 w-3.5" />
            </button>
            <span className="pointer-events-none absolute right-0 top-full z-40 mt-2 whitespace-nowrap rounded-control border border-gray-200 bg-white px-2 py-1 text-xs font-medium text-slate-700 opacity-0 shadow-md transition-opacity delay-500 duration-150 group-hover:opacity-100">
              新增專案
            </span>
          </span>
        </>
      )}
      {confirmDeleteOpen && (
        <div className="absolute right-0 top-full z-30 mt-2 w-[300px] rounded-card border border-gray-200 bg-white p-4 shadow-lg">
          <div className="mb-3">
            <p className="text-sm font-semibold text-slate-900">刪除專案？</p>
            <p className="mt-2 text-xs leading-5 text-slate-500">
              此動作無法復原，且專案不可有執行中的任務。
            </p>
          </div>
          <div className="flex justify-end gap-2">
            <button
              type="button"
              className="rounded-control border border-gray-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-gray-50"
              onClick={() => setConfirmDeleteOpen(false)}
            >
              取消
            </button>
            <button
              type="button"
              className="rounded-control bg-slate-950 px-3 py-1.5 text-xs font-semibold text-white hover:bg-slate-800 disabled:opacity-50"
              disabled={deleteMut.isPending}
              onClick={confirmDelete}
            >
              刪除
            </button>
          </div>
        </div>
      )}
      {deleteError && (
        <div className="absolute right-0 top-full z-30 mt-2 w-[300px] rounded-card border border-gray-200 bg-white p-4 shadow-lg">
          <div className="mb-3">
            <p className="text-sm font-semibold text-slate-900">刪除失敗</p>
            <p className="mt-1 text-xs leading-5 text-slate-500">{deleteError}</p>
          </div>
          <div className="flex justify-end">
            <button
              type="button"
              className="rounded-control bg-slate-950 px-3 py-1.5 text-xs font-semibold text-white hover:bg-slate-800"
              onClick={() => setDeleteError(null)}
            >
              確定
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
