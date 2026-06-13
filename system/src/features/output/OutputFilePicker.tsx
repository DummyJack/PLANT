import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";
import { useUiStore } from "@/stores/uiStore";
import type { FileTreeNode } from "@/types/api";
import {
  buildOutputFiles,
  resolvePreferredOutputPath,
  type OutputFile,
} from "@/utils/buildOutputFiles";
import { cn } from "@/utils/cn";

interface OutputFilePickerProps {
  projectId: string | null;
  items: FileTreeNode[];
  compact?: boolean;
}

const GROUPS = [
  { id: "documents", label: "Output" },
  { id: "drafts", label: "Drafts" },
  { id: "meetingData", label: "Meeting" },
  { id: "meetings", label: "MoM" },
  { id: "reports", label: "Conflict" },
  { id: "models", label: "Models" },
  { id: "artifacts", label: "Artifact" },
] as const;

function groupForFile(file: OutputFile): (typeof GROUPS)[number]["id"] {
  if (file.path.startsWith("results/MoM/")) return "meetings";
  if (file.path.startsWith("artifact/MoM/")) return "meetings";
  if (file.path.includes("/meeting/")) return "meetingData";
  if (
    file.path.startsWith("results/report/") ||
    file.path.startsWith("artifact/report/")
  ) return "reports";
  if (file.kind === "image" || file.kind === "plantuml") return "models";
  if (file.path.startsWith("output/")) return "documents";
  if (file.path.startsWith("results/") && !file.path.includes("/drafts/")) return "documents";
  if (file.path.includes("/drafts/")) return "drafts";
  return "artifacts";
}

function isSelectableOutputFile(file: OutputFile, files: OutputFile[]) {
  if (
    file.kind !== "html" &&
    file.kind !== "json" &&
    file.kind !== "image" &&
    file.kind !== "markdown" &&
    file.kind !== "plantuml"
  ) {
    return false;
  }
  if (file.kind === "image") {
    const imageBase =
      file.modelBase ??
      file.label.replace(/\.(?:png|svg)$/i, "") ??
      file.path.replace(/^.*\//, "").replace(/\.(?:png|svg)$/i, "");
    return !files.some(
      (candidate) =>
        candidate.kind === "plantuml" &&
        (
          candidate.modelBase === imageBase ||
          candidate.label.replace(/\.(?:plantuml|puml)$/i, "") === imageBase
        ),
    );
  }
  return true;
}

export function OutputFilePicker({ projectId, items, compact }: OutputFilePickerProps) {
  const rootRef = useRef<HTMLDivElement>(null);
  const [compactMenu, setCompactMenu] = useState(false);
  const [menuWidth, setMenuWidth] = useState<number | undefined>(undefined);
  const [open, setOpen] = useState(false);
  const selectedOutputPath = useUiStore((s) => s.selectedOutputPath);
  const setSelectedOutputPath = useUiStore((s) => s.setSelectedOutputPath);

  const files = useMemo(() => buildOutputFiles(items), [items]);
  const selectableFiles = useMemo(
    () => files.filter((file) => isSelectableOutputFile(file, files)),
    [files],
  );
  const grouped = useMemo(
    () =>
      GROUPS.map((group) => ({
        ...group,
        files: selectableFiles.filter((file) => groupForFile(file) === group.id),
      })).filter((group) => group.files.length > 0),
    [selectableFiles],
  );
  const filePaths = useMemo(() => selectableFiles.map((f) => f.path).join("|"), [selectableFiles]);
  const selectedFile = selectableFiles.find((f) => f.path === selectedOutputPath);
  const selectedGroupId = selectedFile ? groupForFile(selectedFile) : grouped[0]?.id;
  const [activeGroupId, setActiveGroupId] = useState<string | undefined>(selectedGroupId);
  const activeGroup =
    grouped.find((group) => group.id === activeGroupId) ?? grouped[0];

  useEffect(() => {
    if (!open) return;
    const handler = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  useEffect(() => {
    if (selectedGroupId) {
      setActiveGroupId((current) => (current === selectedGroupId ? current : selectedGroupId));
    }
  }, [selectedGroupId]);

  useEffect(() => {
    const root = rootRef.current;
    const panel = root?.closest(".card");
    if (!root || !panel) return;

    const update = () => {
      const panelWidth = panel.getBoundingClientRect().width;
      const rootWidth = root.getBoundingClientRect().width;
      const nextCompact = compact ?? panelWidth < 420;
      const nextWidth = Math.max(160, Math.min(360, panelWidth - 24, rootWidth));
      setCompactMenu((current) => (current === nextCompact ? current : nextCompact));
      setMenuWidth((current) => (current === nextWidth ? current : nextWidth));
    };
    const observer = new ResizeObserver(() => {
      window.requestAnimationFrame(update);
    });
    observer.observe(panel);
    update();
    return () => observer.disconnect();
  }, [compact]);

  useEffect(() => {
    if (!projectId) {
      if (selectedOutputPath !== null) setSelectedOutputPath(null, "system");
      return;
    }
    if (selectableFiles.length === 0) {
      if (selectedOutputPath !== null) setSelectedOutputPath(null, "system");
      return;
    }
    const preferred = resolvePreferredOutputPath(selectedOutputPath, selectableFiles);
    if (preferred && preferred !== selectedOutputPath) {
      setSelectedOutputPath(preferred, "system");
      return;
    }
    if (!selectedOutputPath || !selectableFiles.some((f) => f.path === selectedOutputPath)) {
      if (preferred) {
        setSelectedOutputPath(preferred, "system");
        return;
      }
      const srs =
        selectableFiles.find((f) => f.path === "results/srs.html") ??
        selectableFiles.find((f) => f.path === "output/srs.md");
      const html = selectableFiles.find((f) => f.kind === "html");
      setSelectedOutputPath(
        srs?.path ?? html?.path ?? selectableFiles[selectableFiles.length - 1].path,
        "system",
      );
    }
  }, [projectId, filePaths, selectedOutputPath, setSelectedOutputPath]);

  const disabled = !projectId || selectableFiles.length === 0;

  return (
    <div ref={rootRef} className="relative w-full min-w-0 max-w-full shrink sm:w-40">
      <button
        type="button"
        disabled={disabled}
        className={cn(
          "flex h-8 w-full items-center justify-between gap-2 rounded-control border border-gray-200 bg-white py-1 pl-2.5 pr-2 text-left text-sm text-slate-700 hover:border-gray-300 focus:border-slate-400 focus:outline-none focus:ring-2 focus:ring-slate-200 disabled:cursor-not-allowed disabled:opacity-50",
        )}
        onClick={() => setOpen((v) => !v)}
        title={selectedFile?.label ?? "選擇檔案"}
      >
        <span className="min-w-0 flex-1 truncate">
          {selectedFile?.label ?? "選擇檔案"}
        </span>
        <ChevronDown className="h-3.5 w-3.5 shrink-0 text-slate-400" />
      </button>

      {open && (
        <div
          className={cn(
            "absolute top-full z-40 mt-2 max-h-80 overflow-hidden rounded-card border border-gray-200 bg-white shadow-lg",
            compactMenu
              ? "left-0 flex min-w-0 flex-col"
              : "right-0 grid w-[min(360px,calc(100vw-2rem))] grid-cols-[minmax(88px,120px)_minmax(0,1fr)]",
          )}
          style={{ width: compactMenu ? menuWidth : undefined }}
        >
          {grouped.length === 0 ? (
            <div className="col-span-2 px-3 py-4 text-xs text-slate-500">
              無任何內容
            </div>
          ) : compactMenu ? (
            <div className="max-h-72 overflow-y-auto p-1">
              {grouped.map((group) => (
                <div key={group.id} className="py-1 first:pt-0">
                  <div className="px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                    {group.label}
                  </div>
                  <div className="space-y-0.5">
                    {group.files.map((file) => (
                    <button
                      key={file.path}
                      type="button"
                      className={cn(
                        "block w-full rounded-control px-2 py-2 text-left text-xs",
                        selectedOutputPath === file.path
                          ? "bg-slate-900 text-white"
                          : "text-slate-700 hover:bg-slate-50",
                      )}
                      title={file.label}
                      onClick={() => {
                        setSelectedOutputPath(file.path);
                        setOpen(false);
                      }}
                    >
                      <span className="block whitespace-normal break-words leading-snug">
                        {file.label}
                      </span>
                    </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <>
              <div className="border-r border-gray-100 bg-slate-50 p-1">
                {grouped.map((group) => (
                  <button
                    key={group.id}
                    type="button"
                    className={cn(
                      "block w-full rounded-control px-2 py-2 text-left text-xs font-medium break-words",
                      activeGroup?.id === group.id
                        ? "bg-white text-slate-900 shadow-sm"
                        : "text-slate-500 hover:bg-white/70 hover:text-slate-800",
                    )}
                    onClick={() => setActiveGroupId(group.id)}
                  >
                    {group.label}
                  </button>
                ))}
              </div>
              <div className="max-h-80 overflow-y-auto p-1">
                {activeGroup?.files.length ? (
                  activeGroup.files.map((file) => (
                    <button
                      key={file.path}
                      type="button"
                      className={cn(
                        "block w-full rounded-control px-2 py-2 text-left text-xs",
                        selectedOutputPath === file.path
                          ? "bg-slate-900 text-white"
                          : "text-slate-700 hover:bg-slate-50",
                      )}
                      title={file.label}
                      onClick={() => {
                        setSelectedOutputPath(file.path);
                        setOpen(false);
                      }}
                    >
                      <span className="block whitespace-normal break-words leading-snug">
                        {file.label}
                      </span>
                    </button>
                  ))
                ) : (
                  <p className="px-2 py-3 text-xs text-slate-500">無任何內容</p>
                )}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
