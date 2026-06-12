import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Download, FileUp, MoreHorizontal, Search, Trash2, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  deleteReference,
  referenceDownloadUrl,
  referencePreviewUrl,
  uploadReference,
} from "@/api/projects";
import { PanelChrome } from "@/components/PanelChrome";
import { buildReferenceRows } from "@/features/documents/buildLibraryRows";
import { useProjectData } from "@/hooks/useProjectData";
import { useActiveRun } from "@/hooks/useActiveRun";
import { useUiStore } from "@/stores/uiStore";
import { cn } from "@/utils/cn";
import { errorMessage } from "@/utils/errorMessage";

interface ReferencePanelProps {
  projectId: string | null;
}

type DeleteTarget =
  | { kind: "single"; names: string[] }
  | { kind: "multiple"; names: string[] };

type ReferencePreview = {
  name: string;
  loading: boolean;
  content?: string;
  url?: string;
  kind: "text" | "pdf" | "unsupported";
  error?: string;
};

const SUPPORTED_REFERENCE_EXTS = [
  ".pdf",
  ".docx",
  ".xlsx",
  ".pptx",
  ".txt",
  ".md",
  ".json",
  ".csv",
];
const REFERENCE_ACCEPT = SUPPORTED_REFERENCE_EXTS.join(",");
const REFERENCE_EXTS_LABEL = SUPPORTED_REFERENCE_EXTS.join(", ");

function extensionLabel(name: string): string {
  const ext = name.split(".").pop()?.trim();
  return ext ? ext.toUpperCase() : "FILE";
}

function basename(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot > 0 ? name.slice(0, dot) : name;
}

function referenceExt(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot >= 0 ? name.slice(dot).toLowerCase() : "";
}

function isTextReference(name: string): boolean {
  return [".txt", ".md", ".json", ".csv"].includes(referenceExt(name));
}

function isPdfReference(name: string): boolean {
  return referenceExt(name) === ".pdf";
}

function triggerDownload(url: string, filename: string) {
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
}

export function ReferencePanel({ projectId }: ReferencePanelProps) {
  const fileRef = useRef<HTMLInputElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const toolbarRef = useRef<HTMLDivElement>(null);
  const queryClient = useQueryClient();
  const { references } = useProjectData(projectId);
  const { activeRun } = useActiveRun(projectId);
  const [dragOver, setDragOver] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<DeleteTarget | null>(null);
  const [formatError, setFormatError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [selectedNames, setSelectedNames] = useState<Set<string>>(new Set());
  const [menuName, setMenuName] = useState<string | null>(null);
  const [preview, setPreview] = useState<ReferencePreview | null>(null);
  const [compactUpload, setCompactUpload] = useState(false);
  const [toolbarWrapped, setToolbarWrapped] = useState(false);
  const stagedReferenceFiles = useUiStore((s) => s.stagedReferenceFiles);
  const addStagedReferenceFile = useUiStore((s) => s.addStagedReferenceFile);
  const removeStagedReferenceFile = useUiStore((s) => s.removeStagedReferenceFile);
  const canWrite = useUiStore((s) => s.canWrite);

  const rows = projectId
    ? buildReferenceRows(references.data?.references ?? [])
    : buildReferenceRows(stagedReferenceFiles.map((file) => ({ name: file.name })));
  const filteredRows = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    if (!keyword) return rows;
    return rows.filter((row) => row.name.toLowerCase().includes(keyword));
  }, [query, rows]);
  const selectedVisibleNames = filteredRows
    .map((row) => row.name)
    .filter((name) => selectedNames.has(name));
  const allVisibleSelected =
    filteredRows.length > 0 && selectedVisibleNames.length === filteredRows.length;
  const someVisibleSelected = selectedVisibleNames.length > 0;
  const runActive = !!activeRun;
  const uploadDisabled = runActive || !canWrite;
  const writeDisabled = runActive || !canWrite;

  useEffect(() => {
    const onPointerDown = (event: PointerEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) {
        setMenuName(null);
      }
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, []);

  useEffect(() => {
    const toolbar = toolbarRef.current;
    const header = toolbar?.parentElement?.parentElement;
    const titleGroup = header?.firstElementChild as HTMLElement | null;
    if (!toolbar || !header || !titleGroup) return;

    const updateCompactState = () => {
      const previousHeaderJustify = header.style.justifyContent;
      const previousTitleBasis = titleGroup.style.flexBasis;
      const previousTitleJustify = titleGroup.style.justifyContent;

      header.style.justifyContent = "";
      titleGroup.style.flexBasis = "6rem";
      titleGroup.style.justifyContent = "";

      const toolbarTop = toolbar.getBoundingClientRect().top;
      const titleTop = titleGroup.getBoundingClientRect().top;
      const wrappedToNextLine = toolbarTop > titleTop + 4;
      const overflowing = toolbar.scrollWidth > toolbar.clientWidth + 1;

      header.style.justifyContent = previousHeaderJustify;
      titleGroup.style.flexBasis = previousTitleBasis;
      titleGroup.style.justifyContent = previousTitleJustify;

      setToolbarWrapped(wrappedToNextLine);
      setCompactUpload(wrappedToNextLine || overflowing);
    };

    const observer = new ResizeObserver(() => {
      window.requestAnimationFrame(updateCompactState);
    });
    observer.observe(header);
    observer.observe(toolbar);
    updateCompactState();
    return () => observer.disconnect();
  }, []);

  const uploadMut = useMutation({
    mutationFn: async (files: File[]) => {
      for (const file of files) {
        await uploadReference(projectId!, file);
      }
      return files;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["references", projectId] });
    },
    onError: (e: Error) => {
      setFormatError(errorMessage(e, `文件庫僅支援：${REFERENCE_EXTS_LABEL}`));
    },
  });

  const deleteMut = useMutation({
    mutationFn: async (names: string[]) => {
      if (projectId) {
        for (const name of names) {
          await deleteReference(projectId, name);
        }
      } else {
        names.forEach(removeStagedReferenceFile);
      }
      return names;
    },
    onSuccess: (names) => {
      setSelectedNames((current) => {
        const next = new Set(current);
        names.forEach((name) => next.delete(name));
        return next;
      });
      queryClient.invalidateQueries({ queryKey: ["references", projectId] });
    },
    onError: (e: Error) => {
      setFormatError(errorMessage(e, "刪除失敗"));
    },
  });

  const handleFiles = (fileList: FileList | null) => {
    const files = Array.from(fileList ?? []);
    if (!files.length) return;
    const invalidFiles = files.filter((file) => {
      const lowerName = file.name.toLowerCase();
      return !SUPPORTED_REFERENCE_EXTS.some((ext) => lowerName.endsWith(ext));
    });
    if (invalidFiles.length) {
      setFormatError(
        `文件庫僅支援：${REFERENCE_EXTS_LABEL}。不支援：${invalidFiles
          .map((file) => file.name)
          .join("、")}`,
      );
      return;
    }
    if (projectId) {
      uploadMut.mutate(files);
    } else {
      files.forEach(addStagedReferenceFile);
    }
  };

  const downloadNames = (names: string[]) => {
    names.forEach((name) => {
      if (projectId) {
        triggerDownload(referenceDownloadUrl(projectId, name), name);
        return;
      }
      const file = stagedReferenceFiles.find((item) => item.name === name);
      if (!file) return;
      const url = URL.createObjectURL(file);
      triggerDownload(url, name);
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    });
    setMenuName(null);
  };

  const confirmDelete = () => {
    if (!deleteTarget?.names.length) return;
    deleteMut.mutate(deleteTarget.names);
    setDeleteTarget(null);
    setMenuName(null);
  };

  useEffect(() => {
    return () => {
      if (preview?.url) URL.revokeObjectURL(preview.url);
    };
  }, [preview?.url]);

  const closePreview = () => {
    if (preview?.url) URL.revokeObjectURL(preview.url);
    setPreview(null);
  };

  const openReferencePreview = async (name: string) => {
    if (preview?.url) URL.revokeObjectURL(preview.url);
    const kind = isTextReference(name) ? "text" : isPdfReference(name) ? "pdf" : "unsupported";
    setPreview({ name, kind, loading: true });
    try {
      if (projectId) {
        const url = referencePreviewUrl(projectId, name);
        if (kind === "text") {
          const response = await fetch(url);
          if (!response.ok) throw new Error("讀取文件失敗");
          setPreview({ name, kind, loading: false, content: await response.text() });
          return;
        }
        if (kind === "pdf") {
          setPreview({ name, kind, loading: false, url });
          return;
        }
      } else {
        const file = stagedReferenceFiles.find((item) => item.name === name);
        if (!file) throw new Error("找不到文件");
        if (kind === "text") {
          setPreview({ name, kind, loading: false, content: await file.text() });
          return;
        }
        if (kind === "pdf") {
          setPreview({
            name,
            kind,
            loading: false,
            url: URL.createObjectURL(file),
          });
          return;
        }
      }
      setPreview({
        name,
        kind,
        loading: false,
        error: "此檔案格式目前無法直接預覽，請下載後查看。",
      });
    } catch (error) {
      setPreview({
        name,
        kind,
        loading: false,
        error: errorMessage(error, "讀取文件失敗"),
      });
    }
  };

  return (
    <PanelChrome
      title="文件庫"
      bodyClassName="flex flex-col"
      headerClassName={cn(toolbarWrapped && "justify-center")}
      titleGroupClassName={cn(toolbarWrapped && "basis-full justify-center")}
      trailing={
        <div
          ref={toolbarRef}
          className="flex min-w-0 items-center justify-center gap-1.5 max-[520px]:w-full"
        >
          <label className="flex h-8 min-w-0 flex-1 items-center gap-1.5 rounded-control border border-gray-200 bg-white px-2 text-xs text-slate-500 focus-within:border-slate-400 focus-within:ring-2 focus-within:ring-slate-100">
            <Search className="h-3.5 w-3.5 shrink-0" />
            <input
              className="min-w-0 flex-1 bg-transparent text-xs text-slate-700 placeholder:text-slate-400 focus:outline-none"
              placeholder="搜尋"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </label>
          <input
            ref={fileRef}
            type="file"
            className="hidden"
            accept={REFERENCE_ACCEPT}
            multiple
            disabled={uploadDisabled}
            onChange={(e) => {
              handleFiles(e.target.files);
              e.target.value = "";
            }}
          />
          <button
            type="button"
            disabled={uploadDisabled}
            title="上傳文件"
            className={cn(
              "inline-flex h-8 shrink-0 items-center gap-1 rounded-control border border-gray-200 bg-white px-2 text-xs font-medium text-slate-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-40",
              compactUpload && "w-8 justify-center px-0",
            )}
            onClick={() => fileRef.current?.click()}
          >
            <FileUp className="h-3.5 w-3.5" />
            <span className={cn(compactUpload && "sr-only")}>上傳</span>
          </button>
        </div>
      }
    >
      <div
        className={cn(
          "relative flex min-h-0 flex-1 flex-col transition-colors",
          dragOver && !uploadDisabled && "bg-slate-50",
          uploadDisabled && "opacity-50",
        )}
        onDragOver={(e) => {
          if (uploadDisabled) return;
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={(e) => {
          if (!e.currentTarget.contains(e.relatedTarget as Node | null)) {
            setDragOver(false);
          }
        }}
        onDrop={(e) => {
          if (uploadDisabled) return;
          e.preventDefault();
          setDragOver(false);
          handleFiles(e.dataTransfer.files);
        }}
      >
        <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3">
          {rows.length === 0 ? (
            <div
              className={cn(
                "flex min-h-full w-full flex-col items-center justify-center px-3 py-8 text-center transition-colors",
                dragOver && !uploadDisabled && "bg-slate-50",
              )}
            >
              <FileUp className="mb-3 h-6 w-6 text-slate-400" />
              <p className="text-sm font-semibold text-slate-600">
                {!canWrite
                  ? "請先啟動後上傳"
                  : dragOver
                    ? "放開以上傳"
                    : "拖曳檔案至此區域上傳"}
              </p>
            </div>
          ) : (
            <div ref={menuRef} className="w-full min-w-0">
              <div className="grid grid-cols-[24px_minmax(0,1fr)_64px_28px] items-center gap-2 border-b border-gray-100 px-1 pb-2 text-[11px] font-medium text-slate-400">
                <input
                  type="checkbox"
                  aria-label="選取全部文件"
                  className={cn(
                    "h-4 w-4 rounded border-gray-300 text-slate-900 focus:ring-slate-300",
                    !someVisibleSelected && "opacity-0 hover:opacity-100",
                  )}
                  checked={allVisibleSelected}
                  ref={(node) => {
                    if (node) node.indeterminate = someVisibleSelected && !allVisibleSelected;
                  }}
                  onChange={(event) => {
                    setSelectedNames((current) => {
                      const next = new Set(current);
                      filteredRows.forEach((row) => {
                        if (event.target.checked) next.add(row.name);
                        else next.delete(row.name);
                      });
                      return next;
                    });
                  }}
                />
                <span>名稱</span>
                <span>種類</span>
                <div className="relative flex justify-end">
                  {someVisibleSelected && (
                    <div className="absolute right-0 top-1/2 flex -translate-y-1/2 items-center gap-1 rounded-control bg-white">
                      <button
                        type="button"
                        title="下載選取文件"
                        className="rounded p-1 text-slate-500 hover:bg-gray-50 hover:text-slate-900"
                        onClick={() => downloadNames(selectedVisibleNames)}
                      >
                        <Download className="h-3.5 w-3.5" />
                      </button>
                      <button
                        type="button"
                        title="刪除選取文件"
                        disabled={writeDisabled}
                        className="rounded p-1 text-red-500 hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-40"
                        onClick={() =>
                          setDeleteTarget({ kind: "multiple", names: selectedVisibleNames })
                        }
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  )}
                </div>
              </div>
              {filteredRows.length === 0 ? (
                <p className="px-1 py-4 text-center text-xs text-slate-400">
                  找不到符合的文件
                </p>
              ) : (
                <ul>
                  {filteredRows.map((row) => {
                    const selected = selectedNames.has(row.name);
                    const menuOpen = menuName === row.name;
                    return (
                      <li
                        key={row.id}
                        className="group grid grid-cols-[24px_minmax(0,1fr)_64px_28px] items-center gap-2 border-b border-gray-100 px-1 py-2 text-xs hover:bg-gray-50"
                      >
                        <input
                          type="checkbox"
                          aria-label={`選取 ${row.name}`}
                          className={cn(
                            "h-4 w-4 rounded border-gray-300 text-slate-900 focus:ring-slate-300",
                            !selected && "opacity-0 group-hover:opacity-100",
                          )}
                          checked={selected}
                          onChange={(event) => {
                            setSelectedNames((current) => {
                              const next = new Set(current);
                              if (event.target.checked) next.add(row.name);
                              else next.delete(row.name);
                              return next;
                            });
                          }}
                        />
                        <button
                          type="button"
                          className="min-w-0 truncate text-left font-medium text-slate-700 hover:text-slate-950 hover:underline"
                          title={row.name}
                          onClick={() => void openReferencePreview(row.name)}
                        >
                          {basename(row.name)}
                        </button>
                        <span className="truncate text-[11px] text-slate-400">
                          {extensionLabel(row.name)}
                        </span>
                        <div className="relative flex justify-end">
                          <button
                            type="button"
                            aria-label={`${row.name} 更多操作`}
                            className={cn(
                              "rounded p-1 text-slate-400 opacity-0 hover:bg-white hover:text-slate-700 group-hover:opacity-100",
                              menuOpen && "bg-white opacity-100",
                            )}
                            onClick={() =>
                              setMenuName((current) => (current === row.name ? null : row.name))
                            }
                          >
                            <MoreHorizontal className="h-4 w-4" />
                          </button>
                          {menuOpen && (
                            <div className="absolute right-0 top-full z-20 mt-1 w-24 rounded-control border border-gray-200 bg-white py-1 shadow-lg">
                              <button
                                type="button"
                                className="flex w-full items-center gap-2 px-2 py-1.5 text-left text-xs text-slate-700 hover:bg-gray-50"
                                onClick={() => downloadNames([row.name])}
                              >
                                <Download className="h-3.5 w-3.5" />
                                下載
                              </button>
                              <button
                                type="button"
                                disabled={writeDisabled}
                                className="flex w-full items-center gap-2 px-2 py-1.5 text-left text-xs text-red-600 hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-40"
                                onClick={() =>
                                  setDeleteTarget({ kind: "single", names: [row.name] })
                                }
                              >
                                <Trash2 className="h-3.5 w-3.5" />
                                刪除
                              </button>
                            </div>
                          )}
                        </div>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          )}
        </div>
        <div
          className="shrink-0 cursor-default border-t border-gray-100 px-4 py-3 text-center"
          onDragOver={(event) => {
            event.stopPropagation();
            setDragOver(false);
          }}
          onDrop={(event) => {
            event.stopPropagation();
            setDragOver(false);
          }}
        >
          <p className="overflow-x-auto whitespace-nowrap text-[11px] leading-4 text-slate-400">
            <span className="font-medium">可支援檔案：</span>
            {REFERENCE_EXTS_LABEL}
          </p>
        </div>
        {deleteTarget && (
          <div
            className="absolute inset-0 z-30 flex items-center justify-center bg-white/80 px-4 backdrop-blur-sm"
            onClick={() => setDeleteTarget(null)}
          >
            <div
              className="w-full max-w-[280px] rounded-card border border-gray-200 bg-white p-4 shadow-lg"
              onClick={(event) => event.stopPropagation()}
            >
              <div className="mb-3">
                <p className="text-[15px] font-semibold text-slate-900">
                  {deleteTarget.kind === "multiple" ? "刪除這些文件？" : "刪除文件？"}
                </p>
                {deleteTarget.kind === "single" && (
                  <p className="mt-1 break-words text-xs leading-5 text-slate-500">
                    {deleteTarget.names[0]}
                  </p>
                )}
                <p className="mt-0.5 text-xs leading-5 text-slate-500">
                  {deleteTarget.kind === "multiple"
                    ? `將刪除 ${deleteTarget.names.length} 個文件，此動作無法復原。`
                    : "動作無法復原。"}
                </p>
              </div>
              <div className="flex justify-center gap-2">
                <button
                  type="button"
                  className="rounded-control border border-gray-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-gray-50"
                  onClick={() => setDeleteTarget(null)}
                >
                  取消
                </button>
                <button
                  type="button"
                  disabled={deleteMut.isPending}
                  className="rounded-control bg-red-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-50"
                  onClick={confirmDelete}
                >
                  刪除
                </button>
              </div>
            </div>
          </div>
        )}
        {preview && (
          <div className="absolute inset-0 z-40 flex items-center justify-center bg-white/80 px-4 backdrop-blur-sm">
            <div className="flex max-h-[82%] w-full max-w-[720px] flex-col rounded-card border border-gray-200 bg-white shadow-lg">
              <div className="flex shrink-0 items-center gap-3 border-b border-gray-100 px-4 py-3">
                <h3 className="min-w-0 flex-1 truncate text-sm font-semibold text-slate-900">
                  {preview.name}
                </h3>
                <button
                  type="button"
                  className="inline-flex h-7 w-7 items-center justify-center rounded-control text-slate-500 hover:bg-gray-50 hover:text-slate-900"
                  aria-label="關閉"
                  onClick={closePreview}
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
              <div className="min-h-0 flex-1 overflow-auto p-4">
                {preview.loading ? (
                  <p className="text-sm text-slate-500">讀取文件中...</p>
                ) : preview.error ? (
                  <div className="space-y-3">
                    <p className="text-sm leading-6 text-slate-500">{preview.error}</p>
                    <button
                      type="button"
                      className="inline-flex items-center gap-1 rounded-control border border-gray-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-gray-50"
                      onClick={() => downloadNames([preview.name])}
                    >
                      <Download className="h-3.5 w-3.5" />
                      下載
                    </button>
                  </div>
                ) : preview.kind === "pdf" && preview.url ? (
                  <iframe
                    title={preview.name}
                    src={preview.url}
                    sandbox=""
                    className="h-[60vh] w-full rounded-control border border-gray-200"
                  />
                ) : (
                  <pre className="whitespace-pre-wrap break-words rounded-control bg-slate-50 p-3 text-xs leading-5 text-slate-700">
                    {preview.content || "無內容"}
                  </pre>
                )}
              </div>
            </div>
          </div>
        )}
        {formatError && (
          <div className="absolute inset-0 z-30 flex items-center justify-center bg-white/80 px-4 backdrop-blur-sm">
            <div className="w-full max-w-[280px] rounded-card border border-gray-200 bg-white p-4 shadow-lg">
              <div className="mb-3">
                <p className="text-sm font-semibold text-slate-900">無法處理文件</p>
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
