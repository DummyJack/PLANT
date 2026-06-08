import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileUp, Trash2 } from "lucide-react";
import { useRef, useState } from "react";
import { deleteReference, uploadReference } from "@/api/projects";
import { fetchRuns } from "@/api/runs";
import { PanelChrome } from "@/components/PanelChrome";
import { buildReferenceRows } from "@/features/documents/buildLibraryRows";
import { useProjectData } from "@/hooks/useProjectData";
import { useActiveRun } from "@/hooks/useActiveRun";
import { useUiStore } from "@/stores/uiStore";
import { cn } from "@/utils/cn";

interface ReferencePanelProps {
  projectId: string | null;
}

const SUPPORTED_REFERENCE_EXTS = [".pdf", ".docx", ".txt", ".md", ".json", ".csv"];
const REFERENCE_ACCEPT = SUPPORTED_REFERENCE_EXTS.join(",");
const REFERENCE_EXTS_LABEL = SUPPORTED_REFERENCE_EXTS.join(", ");

export function ReferencePanel({ projectId }: ReferencePanelProps) {
  const fileRef = useRef<HTMLInputElement>(null);
  const queryClient = useQueryClient();
  const { project, references } = useProjectData(projectId);
  const runs = useQuery({
    queryKey: ["runs", projectId],
    queryFn: () => fetchRuns(projectId!),
    enabled: !!projectId,
  });
  const { activeRun } = useActiveRun(projectId);
  const [dragOver, setDragOver] = useState(false);
  const [pendingDeleteName, setPendingDeleteName] = useState<string | null>(null);
  const [formatError, setFormatError] = useState<string | null>(null);
  const stagedReferenceFiles = useUiStore((s) => s.stagedReferenceFiles);
  const addStagedReferenceFile = useUiStore((s) => s.addStagedReferenceFile);
  const removeStagedReferenceFile = useUiStore((s) => s.removeStagedReferenceFile);

  const rows = projectId
    ? buildReferenceRows(references.data?.references ?? [])
    : buildReferenceRows(stagedReferenceFiles.map((file) => ({ name: file.name })));
  const latestRun = runs.data?.runs?.[0];
  const projectMeta =
    project.data?.project?.meta && typeof project.data.project.meta === "object"
      ? (project.data.project.meta as { attached_references?: string[] })
      : {};
  const metaAttached = Array.isArray(projectMeta.attached_references)
    ? projectMeta.attached_references
    : [];
  const attachedPaths = new Set(
    [...(latestRun?.attached_reference_paths ?? []), ...metaAttached].map(
      (path) => path.split("/").pop() ?? path,
    ),
  );
  const usedReferenceNames = projectId
    ? attachedPaths
    : new Set(stagedReferenceFiles.map((file) => file.name));
  const runActive = !!activeRun;
  const uploadDisabled = !!projectId || runActive;

  const uploadMut = useMutation({
    mutationFn: (file: File) => uploadReference(projectId!, file),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["references", projectId] });
    },
    onError: (e: Error) => {
      setFormatError(e.message || `文件庫僅支援：${REFERENCE_EXTS_LABEL}`);
    },
  });

  const deleteMut = useMutation({
    mutationFn: (name: string) => deleteReference(projectId!, name),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["references", projectId] });
    },
  });

  const handleFiles = (fileList: FileList | null) => {
    const file = fileList?.[0];
    if (!file) return;
    const lowerName = file.name.toLowerCase();
    if (!SUPPORTED_REFERENCE_EXTS.some((ext) => lowerName.endsWith(ext))) {
      setFormatError(`文件庫僅支援：${REFERENCE_EXTS_LABEL}`);
      return;
    }
    if (projectId) {
      uploadMut.mutate(file);
    } else {
      addStagedReferenceFile(file);
    }
  };

  const confirmDelete = () => {
    if (!pendingDeleteName) return;
    if (projectId) {
      deleteMut.mutate(pendingDeleteName);
    } else {
      removeStagedReferenceFile(pendingDeleteName);
    }
    setPendingDeleteName(null);
  };

  return (
    <PanelChrome
      title="文件庫"
      bodyClassName="flex flex-col"
      trailing={
        <>
          <input
            ref={fileRef}
            type="file"
            className="hidden"
            accept={REFERENCE_ACCEPT}
            disabled={uploadDisabled}
            onChange={(e) => {
              handleFiles(e.target.files);
              e.target.value = "";
            }}
          />
          <button
            type="button"
            disabled={uploadDisabled}
            title={`上傳文件：${REFERENCE_EXTS_LABEL}`}
            className="inline-flex items-center gap-1 rounded-control border border-gray-200 bg-white px-2 py-1 text-xs font-medium text-slate-700 hover:bg-gray-50 disabled:opacity-40"
            onClick={() => fileRef.current?.click()}
          >
            <FileUp className="h-3.5 w-3.5" />
            上傳
          </button>
        </>
      }
    >
      <div
        className={cn(
          "relative flex min-h-0 flex-1 flex-col transition-colors",
          dragOver && !uploadDisabled && "bg-slate-50",
          uploadDisabled && "pointer-events-none opacity-50",
        )}
        onDragOver={(e) => {
          if (uploadDisabled) return;
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          if (uploadDisabled) return;
          e.preventDefault();
          setDragOver(false);
          handleFiles(e.dataTransfer.files);
        }}
      >
        <div className="flex min-h-0 flex-1 overflow-y-auto px-2 py-2">
          {rows.length === 0 ? (
            <p className="m-auto px-4 text-center text-xs text-slate-500">
              {dragOver ? (
                "放開以上傳"
              ) : (
                <>
                  拖曳檔案至此區域上傳
                  <br />
                  （可支援檔案：{REFERENCE_EXTS_LABEL}）
                </>
              )}
            </p>
          ) : (
            <ul className="w-full">
              {rows.map((row) => (
                <li
                  key={row.id}
                  className={cn(
                    "group flex items-center justify-between rounded-control px-2 py-1.5 text-xs",
                    !uploadDisabled && "hover:bg-gray-50",
                  )}
                >
                  <span
                    className="min-w-0 truncate text-slate-700"
                    title={row.name}
                  >
                    {row.name}
                  </span>
                  <span
                    className={cn(
                      "ml-2 shrink-0 rounded-full px-1.5 py-0.5 text-[10px] font-medium",
                      usedReferenceNames.has(row.name)
                        ? "bg-emerald-50 text-emerald-700"
                        : "bg-slate-100 text-slate-500",
                    )}
                  >
                    {usedReferenceNames.has(row.name) ? "本次使用" : "已上傳"}
                  </span>
                  <button
                    type="button"
                    title="刪除"
                    disabled={uploadDisabled}
                    className="ml-2 shrink-0 rounded p-1 text-slate-400 opacity-0 transition-opacity hover:bg-red-50 hover:text-red-600 group-hover:opacity-100 disabled:opacity-40"
                    onClick={() => {
                      if (!uploadDisabled) setPendingDeleteName(row.name);
                    }}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
        {pendingDeleteName && (
          <div className="absolute inset-0 z-20 flex items-center justify-center bg-white/80 px-4 backdrop-blur-sm">
            <div className="w-full max-w-[260px] rounded-card border border-gray-200 bg-white p-4 shadow-lg">
              <div className="mb-3">
                <p className="text-sm font-semibold text-slate-900">刪除文件？</p>
                <p
                  className="mt-1 truncate text-xs text-slate-500"
                  title={pendingDeleteName}
                >
                  {pendingDeleteName}
                </p>
              </div>
              <div className="flex justify-end gap-2">
                <button
                  type="button"
                  className="rounded-control border border-gray-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-gray-50"
                  onClick={() => setPendingDeleteName(null)}
                >
                  取消
                </button>
                <button
                  type="button"
                  className="rounded-control bg-slate-950 px-3 py-1.5 text-xs font-semibold text-white hover:bg-slate-800"
                  onClick={confirmDelete}
                >
                  刪除
                </button>
              </div>
            </div>
          </div>
        )}
        {formatError && (
          <div className="absolute inset-0 z-20 flex items-center justify-center bg-white/80 px-4 backdrop-blur-sm">
            <div className="w-full max-w-[280px] rounded-card border border-gray-200 bg-white p-4 shadow-lg">
              <div className="mb-3">
                <p className="text-sm font-semibold text-slate-900">無法上傳文件</p>
                <p className="mt-1 text-xs leading-5 text-slate-500">{formatError}</p>
              </div>
              <div className="flex justify-end">
                <button
                  type="button"
                  className="rounded-control bg-slate-950 px-3 py-1.5 text-xs font-semibold text-white hover:bg-slate-800"
                  onClick={() => setFormatError(null)}
                >
                  確定
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </PanelChrome>
  );
}
