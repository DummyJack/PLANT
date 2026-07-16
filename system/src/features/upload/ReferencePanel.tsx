import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Download, ExternalLink, FileUp, Loader2, MoreHorizontal, Search, Trash2, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { DragEvent } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  deleteReference,
  referenceDownloadUrl,
  referencePreviewPageUrl,
  referencePreviewUrl,
  uploadReference,
} from "@/api/projects";
import { responseErrorMessage } from "@/api/client";
import { PanelChrome } from "@/components/PanelChrome";
import { buildReferenceRows, ReferenceFileIcon, referenceExt, referenceIconMeta } from "@/features/documents/referenceFiles";
import { useI18n } from "@/i18n";
import { useActiveRun, useProjectData } from "@/hooks/useProjectQueries";
import { useUiStore } from "@/stores/uiStore";
import { cn } from "@/utils/cn";
import { errorMessage } from "@/utils/errorMessage";
import { makeZip } from "@/utils/zip";

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

interface FileSystemEntry {
  isFile: boolean;
  isDirectory: boolean;
  name: string;
  fullPath: string;
}

interface FileSystemFileEntry extends FileSystemEntry {
  file: (successCallback: (file: File) => void, errorCallback?: (error: DOMException) => void) => void;
}

interface FileSystemDirectoryEntry extends FileSystemEntry {
  createReader: () => FileSystemDirectoryReader;
}

interface FileSystemDirectoryReader {
  readEntries: (
    successCallback: (entries: FileSystemEntry[]) => void,
    errorCallback?: (error: DOMException) => void,
  ) => void;
}

type DataTransferItemWithEntry = DataTransferItem & {
  webkitGetAsEntry?: () => FileSystemEntry | null;
};

const SUPPORTED_REFERENCE_EXTS = [
  ".pdf",
  ".doc",
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
const REFERENCE_DRAG_MIME = "application/x-plant-reference";
const REVIEW_MENTION_DRAG_MIME = "application/x-plant-review-mention";

function extensionLabel(name: string): string {
  const ext = name.split(".").pop()?.trim();
  return ext ? ext.toUpperCase() : "FILE";
}

function basename(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot > 0 ? name.slice(0, dot) : name;
}

function createReferenceDragIcon(name: string): SVGSVGElement {
  const meta = referenceIconMeta(name);
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 28 32");
  svg.setAttribute("width", "18");
  svg.setAttribute("height", "21");

  const body = document.createElementNS(ns, "path");
  body.setAttribute("d", "M4 1.5h13.5L24 8v22.5H4z");
  body.setAttribute("fill", meta.fill);
  svg.appendChild(body);

  const fold = document.createElementNS(ns, "path");
  fold.setAttribute("d", "M17.5 1.5V8H24z");
  fold.setAttribute("fill", meta.fold);
  svg.appendChild(fold);

  const foldLine = document.createElementNS(ns, "path");
  foldLine.setAttribute("d", "M17.5 1.5V8H24");
  foldLine.setAttribute("fill", "none");
  foldLine.setAttribute("stroke", "rgba(15,23,42,.22)");
  foldLine.setAttribute("stroke-width", "1");
  svg.appendChild(foldLine);

  const text = document.createElementNS(ns, "text");
  text.setAttribute("x", "14");
  text.setAttribute("y", "22");
  text.setAttribute("text-anchor", "middle");
  text.setAttribute("font-size", meta.label.length > 3 ? "5.2" : "6.2");
  text.setAttribute("font-weight", "700");
  text.setAttribute("fill", "white");
  text.setAttribute(
    "font-family",
    "ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif",
  );
  text.textContent = meta.label;
  svg.appendChild(text);

  return svg;
}

function isTextReference(name: string): boolean {
  return [".txt", ".md", ".json", ".csv"].includes(referenceExt(name));
}

function isPdfReference(name: string): boolean {
  return referenceExt(name) === ".pdf";
}

function isSupportedReferenceName(name: string): boolean {
  const lowerName = name.toLowerCase();
  return SUPPORTED_REFERENCE_EXTS.some((ext) => lowerName.endsWith(ext));
}

function csvRows(content: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let quoted = false;
  for (let index = 0; index < content.length; index += 1) {
    const char = content[index];
    const next = content[index + 1];
    if (quoted) {
      if (char === '"' && next === '"') {
        cell += '"';
        index += 1;
      } else if (char === '"') {
        quoted = false;
      } else {
        cell += char;
      }
      continue;
    }
    if (char === '"') {
      quoted = true;
    } else if (char === ",") {
      row.push(cell);
      cell = "";
    } else if (char === "\n") {
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
    } else if (char !== "\r") {
      cell += char;
    }
  }
  row.push(cell);
  if (row.some((value) => value.trim())) rows.push(row);
  return rows;
}

function hasSupportedDragFile(items: DataTransferItemList): boolean {
  const fileItems = Array.from(items).filter((item) => item.kind === "file");
  if (!fileItems.length) return false;
  return fileItems.some((item) => {
    const entry = (item as DataTransferItemWithEntry).webkitGetAsEntry?.();
    if (entry?.isDirectory) return true;
    const name = item.getAsFile()?.name;
    return !name || isSupportedReferenceName(name);
  });
}

function isInternalAppDrag(dataTransfer: DataTransfer): boolean {
  const types = Array.from(dataTransfer.types);
  return types.includes(REFERENCE_DRAG_MIME) || types.includes(REVIEW_MENTION_DRAG_MIME);
}

function readFileEntry(entry: FileSystemFileEntry): Promise<File> {
  return new Promise((resolve, reject) => {
    entry.file(resolve, reject);
  });
}

function readDirectoryEntries(reader: FileSystemDirectoryReader): Promise<FileSystemEntry[]> {
  return new Promise((resolve, reject) => {
    reader.readEntries(resolve, reject);
  });
}

async function readAllDirectoryEntries(entry: FileSystemDirectoryEntry): Promise<FileSystemEntry[]> {
  const reader = entry.createReader();
  const entries: FileSystemEntry[] = [];
  while (true) {
    const batch = await readDirectoryEntries(reader);
    if (!batch.length) break;
    entries.push(...batch);
  }
  return entries;
}

async function filesFromEntry(entry: FileSystemEntry): Promise<File[]> {
  if (entry.isFile) return [await readFileEntry(entry as FileSystemFileEntry)];
  if (!entry.isDirectory) return [];
  const entries = await readAllDirectoryEntries(entry as FileSystemDirectoryEntry);
  const nested = await Promise.all(entries.map(filesFromEntry));
  return nested.flat();
}

async function filesFromDataTransfer(dataTransfer: DataTransfer): Promise<File[]> {
  const itemFiles = await Promise.all(
    Array.from(dataTransfer.items)
      .filter((item) => item.kind === "file")
      .map(async (item) => {
        const entry = (item as DataTransferItemWithEntry).webkitGetAsEntry?.();
        if (entry) return filesFromEntry(entry);
        const file = item.getAsFile();
        return file ? [file] : [];
      }),
  );
  const files = itemFiles.flat();
  return files.length ? files : Array.from(dataTransfer.files);
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
  const { t } = useI18n();
  const fileRef = useRef<HTMLInputElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const panelMeasureRef = useRef<HTMLDivElement>(null);
  const [downloadPending, setDownloadPending] = useState(false);
  const queryClient = useQueryClient();
  const { references } = useProjectData(projectId);
  const { activeRun } = useActiveRun(projectId);
  const [dragOver, setDragOver] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<DeleteTarget | null>(null);
  const [formatError, setFormatError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [selectedNames, setSelectedNames] = useState<Set<string>>(new Set());
  const selectionAnchorRef = useRef<string | null>(null);
  const [menuName, setMenuName] = useState<string | null>(null);
  const [preview, setPreview] = useState<ReferencePreview | null>(null);
  const [dragRejected, setDragRejected] = useState(false);
  const [controlsStacked, setControlsStacked] = useState(false);
  const [controlsNarrow, setControlsNarrow] = useState(false);
  const stagedReferenceFiles = useUiStore((s) => s.stagedReferenceFiles);
  const addStagedReferenceFile = useUiStore((s) => s.addStagedReferenceFile);
  const removeStagedReferenceFile = useUiStore((s) => s.removeStagedReferenceFile);
  const canWrite = useUiStore((s) => s.canWrite);

  const rows = projectId
    ? buildReferenceRows(references.data?.references ?? [])
    : buildReferenceRows(stagedReferenceFiles.map((file) => ({ name: file.name })));
  const canDragReferenceToReview =
    activeRun?.status === "waiting_for_human" &&
    activeRun.pending_decision?.kind === "domain_research_review";
  const filteredRows = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    if (!keyword) return rows;
    return rows.filter((row) => row.name.toLowerCase().includes(keyword));
  }, [query, rows]);
  const updateFileSelection = (name: string, checked: boolean, shiftKey: boolean) => {
    const anchorName = selectionAnchorRef.current;
    setSelectedNames((current) => {
      const next = new Set(current);
      const anchorIndex = anchorName
        ? filteredRows.findIndex((row) => row.name === anchorName)
        : -1;
      const targetIndex = filteredRows.findIndex((row) => row.name === name);
      if (shiftKey && anchorIndex >= 0 && targetIndex >= 0) {
        const start = Math.min(anchorIndex, targetIndex);
        const end = Math.max(anchorIndex, targetIndex);
        filteredRows.slice(start, end + 1).forEach((row) => {
          if (checked) next.add(row.name);
          else next.delete(row.name);
        });
      } else if (checked) {
        next.add(name);
      } else {
        next.delete(name);
      }
      return next;
    });
    selectionAnchorRef.current = name;
  };
  const selectedVisibleNames = filteredRows
    .map((row) => row.name)
    .filter((name) => selectedNames.has(name));
  const allVisibleSelected =
    filteredRows.length > 0 && selectedVisibleNames.length === filteredRows.length;
  const someVisibleSelected = selectedVisibleNames.length > 0;
  useEffect(() => {
    if (activeRun?.status !== "waiting_for_human") return;
    queryClient.invalidateQueries({ queryKey: ["references", projectId] });
  }, [activeRun?.status, projectId, queryClient]);

  useEffect(() => {
    const blockExternalFileDropOutsideLibrary = (event: globalThis.DragEvent) => {
      if (!Array.from(event.dataTransfer?.types ?? []).includes("Files")) return;

      const target = event.target instanceof Element ? event.target : null;
      const dropzone = target?.closest<HTMLElement>("[data-reference-dropzone]");
      if (dropzone?.dataset.referenceDropzone === "enabled") return;

      event.preventDefault();
      if (event.dataTransfer) event.dataTransfer.dropEffect = "none";
      if (event.type === "drop") event.stopPropagation();
    };

    window.addEventListener("dragover", blockExternalFileDropOutsideLibrary, true);
    window.addEventListener("drop", blockExternalFileDropOutsideLibrary, true);
    return () => {
      window.removeEventListener("dragover", blockExternalFileDropOutsideLibrary, true);
      window.removeEventListener("drop", blockExternalFileDropOutsideLibrary, true);
    };
  }, []);

  const handleReferenceDragStart = (event: DragEvent<HTMLElement>, row: { name: string }) => {
    if (uploadDisabled) {
      event.preventDefault();
      return;
    }
    const dragLabel = document.createElement("div");
    dragLabel.textContent = row.name;
    dragLabel.style.position = "fixed";
    dragLabel.style.top = "-1000px";
    dragLabel.style.left = "-1000px";
    dragLabel.style.display = "flex";
    dragLabel.style.alignItems = "center";
    dragLabel.style.gap = "8px";
    dragLabel.style.border = "1px solid rgb(203 213 225)";
    dragLabel.style.borderRadius = "8px";
    dragLabel.style.background = "white";
    dragLabel.style.padding = "6px 10px";
    dragLabel.style.fontSize = "12px";
    dragLabel.style.fontWeight = "600";
    dragLabel.style.color = "rgb(51 65 85)";
    dragLabel.style.boxShadow = "0 8px 18px rgb(15 23 42 / 0.12)";
    const iconWrap = document.createElement("span");
    iconWrap.style.display = "inline-flex";
    iconWrap.style.flexShrink = "0";
    iconWrap.appendChild(createReferenceDragIcon(row.name));
    const nameWrap = document.createElement("span");
    nameWrap.textContent = row.name;
    nameWrap.style.whiteSpace = "nowrap";
    dragLabel.textContent = "";
    dragLabel.append(iconWrap, nameWrap);
    document.body.appendChild(dragLabel);
    event.dataTransfer.setDragImage(dragLabel, 12, 12);
    window.setTimeout(() => dragLabel.remove(), 0);
    event.dataTransfer.effectAllowed = "copy";
    event.dataTransfer.setData(
      REFERENCE_DRAG_MIME,
      JSON.stringify({ type: "reference_file", name: row.name }),
    );
    event.dataTransfer.setData("text/plain", row.name);
  };

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
    const measure = panelMeasureRef.current;
    const panel = measure?.closest(".card");
    if (!measure || !panel) return;

    const updateControlsLayout = () => {
      const panelWidth = panel.getBoundingClientRect().width;
      const nextStacked = panelWidth < 390;
      const nextNarrow = panelWidth < 340;
      setControlsStacked((current) => (current === nextStacked ? current : nextStacked));
      setControlsNarrow((current) => (current === nextNarrow ? current : nextNarrow));
    };

    const observer = new ResizeObserver(updateControlsLayout);
    observer.observe(panel);
    updateControlsLayout();
    return () => observer.disconnect();
  }, []);

  const uploadMut = useMutation({
    mutationFn: async (files: File[]) => {
      for (const file of files) {
        await uploadReference(projectId!, file);
      }
      return files;
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["references", projectId] });
    },
    onError: (e: Error) => {
      setFormatError(errorMessage(e, t.referenceSupportedOnly(REFERENCE_EXTS_LABEL)));
    },
  });
  const uploadPending = uploadMut.isPending;
  const uploadDisabled = !canWrite || uploadPending;
  const writeDisabled = !canWrite || uploadPending;

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
    onSuccess: async (names) => {
      setSelectedNames((current) => {
        const next = new Set(current);
        names.forEach((name) => next.delete(name));
        return next;
      });
      await queryClient.invalidateQueries({ queryKey: ["references", projectId] });
    },
    onError: (e: Error) => {
      setFormatError(errorMessage(e, t.deleteFailed));
    },
  });

  const handleFiles = (files: File[]) => {
    if (!files.length) return;
    const invalidFiles = files.filter((file) => !isSupportedReferenceName(file.name));
    const validFiles = files.filter((file) => isSupportedReferenceName(file.name));
    if (invalidFiles.length) {
      setFormatError(
        `${t.referenceSupportedOnly(REFERENCE_EXTS_LABEL)}\n${t.unsupportedFiles(invalidFiles
          .map((file) => file.name)
          .join(", "))}`,
      );
    }
    if (!validFiles.length) return;
    if (projectId) {
      uploadMut.mutate(validFiles);
    } else {
      validFiles.forEach(addStagedReferenceFile);
    }
  };

  const updateDragState = (event: DragEvent<HTMLElement>) => {
    if (uploadDisabled) {
      if (!Array.from(event.dataTransfer.types).includes("Files")) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = "none";
      setDragOver(false);
      setDragRejected(true);
      return;
    }
    if (isInternalAppDrag(event.dataTransfer)) {
      setDragOver(false);
      setDragRejected(false);
      return;
    }
    event.preventDefault();
    const supported = hasSupportedDragFile(event.dataTransfer.items);
    event.dataTransfer.dropEffect = supported ? "copy" : "none";
    setDragOver(supported);
    setDragRejected(!supported);
  };

  const downloadNames = async (names: string[]) => {
    if (downloadPending || !names.length) return;
    setDownloadPending(true);
    setMenuName(null);
    try {
      if (names.length > 1) {
        const entries: Array<{ path: string; bytes: Uint8Array }> = [];
        for (const name of names) {
          if (projectId) {
            const response = await fetch(referenceDownloadUrl(projectId, name), {
              credentials: "include",
            });
            if (!response.ok) throw new Error(`${t.downloadFailed} (${response.status})`);
            entries.push({ path: name, bytes: new Uint8Array(await response.arrayBuffer()) });
            continue;
          }
          const file = stagedReferenceFiles.find((item) => item.name === name);
          if (file) {
            entries.push({ path: name, bytes: new Uint8Array(await file.arrayBuffer()) });
          }
        }
        if (!entries.length) throw new Error(t.downloadFailed);
        const url = URL.createObjectURL(makeZip(entries));
        triggerDownload(url, "reference.zip");
        window.setTimeout(() => URL.revokeObjectURL(url), 1000);
        return;
      }
      for (const name of names) {
        if (projectId) {
          const response = await fetch(referenceDownloadUrl(projectId, name), {
            credentials: "include",
          });
          if (!response.ok) throw new Error(`${t.downloadFailed} (${response.status})`);
          const url = URL.createObjectURL(await response.blob());
          triggerDownload(url, name);
          window.setTimeout(() => URL.revokeObjectURL(url), 1000);
          continue;
        }
        const file = stagedReferenceFiles.find((item) => item.name === name);
        if (!file) continue;
        const url = URL.createObjectURL(file);
        triggerDownload(url, name);
        window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      }
    } catch (error) {
      setFormatError(errorMessage(error as Error, t.downloadFailed));
    } finally {
      setDownloadPending(false);
    }
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

  const openPreviewInNewTab = () => {
    if (!preview || !projectId) return;
    window.open(referencePreviewPageUrl(projectId, preview.name), "_blank", "noopener,noreferrer");
  };

  const openReferencePreview = async (name: string) => {
    if (preview?.url) URL.revokeObjectURL(preview.url);
    const kind = isTextReference(name)
      ? "text"
      : isPdfReference(name)
        ? "pdf"
        : "unsupported";
    setPreview({ name, kind, loading: true });
    try {
      if (projectId) {
        const url = referencePreviewUrl(projectId, name);
        if (kind === "text") {
          const response = await fetch(url);
          if (!response.ok) throw new Error(await responseErrorMessage(response, t.readFileFailed));
          setPreview({ name, kind, loading: false, content: await response.text() });
          return;
        }
        if (kind === "pdf") {
          setPreview({ name, kind, loading: false, url });
          return;
        }
      } else {
        const file = stagedReferenceFiles.find((item) => item.name === name);
        if (!file) throw new Error(t.fileNotFound);
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
        error: t.unsupportedPreview,
      });
    } catch (error) {
      setPreview({
        name,
        kind,
        loading: false,
        error: errorMessage(error, t.readFileFailed),
      });
    }
  };

  const renderTextPreview = (item: ReferencePreview) => {
    const content = item.content || "";
    const ext = referenceExt(item.name);
    if (ext === ".md") {
      return (
        <div className="markdown-body max-w-none rounded-control border border-gray-100 bg-white p-4 text-sm text-slate-800">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {content || t.noContent}
          </ReactMarkdown>
        </div>
      );
    }
    if (ext === ".json") {
      let formatted = content;
      try {
        formatted = JSON.stringify(JSON.parse(content), null, 2);
      } catch {
        formatted = content;
      }
      return (
        <pre className="whitespace-pre-wrap break-words rounded-control bg-slate-950 p-3 font-mono text-xs leading-5 text-slate-50">
          {formatted || t.noContent}
        </pre>
      );
    }
    if (ext === ".csv") {
      const rows = csvRows(content);
      if (!rows.length) {
        return (
          <p className="rounded-control bg-slate-50 p-3 text-sm text-slate-500">
            {t.noContent}
          </p>
        );
      }
      const [headers, ...bodyRows] = rows;
      return (
        <div className="overflow-auto rounded-control border border-gray-200">
          <table className="min-w-full border-collapse text-left text-xs">
            <thead className="bg-slate-50 text-slate-600">
              <tr>
                {headers.map((cell, index) => (
                  <th key={index} className="border-b border-r border-gray-200 px-2 py-1.5 font-semibold last:border-r-0">
                    {cell}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {bodyRows.map((row, rowIndex) => (
                <tr key={rowIndex} className="odd:bg-white even:bg-slate-50/60">
                  {headers.map((_, cellIndex) => (
                    <td key={cellIndex} className="border-b border-r border-gray-100 px-2 py-1.5 align-top text-slate-700 last:border-r-0">
                      {row[cellIndex] ?? ""}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    }
    return (
      <pre className="whitespace-pre-wrap break-words rounded-control bg-slate-50 p-3 font-mono text-xs leading-5 text-slate-700">
        {content || t.noContent}
      </pre>
    );
  };

  const toolbar = (
    <div
      className={cn(
        "flex min-w-0 items-center justify-center gap-1.5",
        controlsStacked ? "mx-auto w-full max-w-[480px]" : "max-[520px]:w-full",
      )}
    >
      <label className="flex h-8 min-w-0 flex-1 items-center gap-1.5 rounded-control border border-gray-200 bg-white px-2 text-xs text-slate-500 focus-within:border-slate-400 focus-within:ring-2 focus-within:ring-slate-100">
        <Search className="h-3.5 w-3.5 shrink-0" />
        <input
          className="min-w-0 flex-1 bg-transparent text-xs text-slate-700 placeholder:text-slate-400 focus:outline-none"
          placeholder={t.search}
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
          handleFiles(Array.from(e.target.files ?? []));
          e.target.value = "";
        }}
      />
      <button
        type="button"
        disabled={uploadDisabled}
        title={t.uploadFile}
        className={cn(
          "inline-flex h-8 shrink-0 items-center gap-1 rounded-control border border-gray-200 bg-white px-2 text-xs font-medium text-slate-700 hover:bg-gray-50 disabled:cursor-not-allowed",
          controlsNarrow && "w-8 justify-center px-0",
        )}
        onClick={() => fileRef.current?.click()}
      >
        <FileUp className="h-3.5 w-3.5" />
        <span className={cn(controlsNarrow && "sr-only")}>{t.upload}</span>
      </button>
    </div>
  );

  return (
    <PanelChrome
      title={t.references}
      bodyClassName="flex flex-col bg-slate-50/50"
      centerTitle={controlsStacked}
      headerClassName={cn(controlsStacked && "min-h-10 border-b-0 py-2")}
      titleClassName={cn(controlsStacked && "text-base")}
      trailing={!controlsStacked && toolbar}
      subheader={
        <>
          <div ref={panelMeasureRef} className="pointer-events-none absolute inset-x-0 top-0 h-0 overflow-hidden opacity-0" />
          {controlsStacked && (
            <div className="flex shrink-0 border-b border-gray-100 px-4 py-2">
              {toolbar}
            </div>
          )}
        </>
      }
    >
      <div
        data-reference-dropzone={uploadDisabled ? "disabled" : "enabled"}
        className={cn(
          "relative flex min-h-0 flex-1 flex-col bg-slate-50/50 transition-colors",
          dragOver && !uploadDisabled && "bg-slate-50",
          dragRejected && "cursor-not-allowed",
        )}
        onDragEnter={updateDragState}
        onDragOver={(e) => {
          updateDragState(e);
        }}
        onDragLeave={(e) => {
          if (!e.currentTarget.contains(e.relatedTarget as Node | null)) {
            setDragOver(false);
            setDragRejected(false);
          }
        }}
        onDrop={async (e) => {
          e.preventDefault();
          if (uploadDisabled) return;
          if (isInternalAppDrag(e.dataTransfer)) {
            setDragOver(false);
            setDragRejected(false);
            return;
          }
          e.preventDefault();
          setDragOver(false);
          setDragRejected(false);
          handleFiles(await filesFromDataTransfer(e.dataTransfer));
        }}
      >
        {(uploadPending || deleteMut.isPending || downloadPending) && (
          <div
            className="absolute inset-0 z-20 flex items-center justify-center bg-white/75 backdrop-blur-[1px]"
            role="status"
            aria-live="polite"
          >
            <div className="flex items-center gap-2 rounded-control border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-700 shadow-sm">
              <span
                aria-hidden="true"
                className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-slate-700"
              />
              <span>
                {uploadPending
                  ? t.uploading
                  : deleteMut.isPending
                    ? t.deleting
                    : t.downloading}
              </span>
            </div>
          </div>
        )}
        <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3">
          {rows.length === 0 ? (
            <div
              className={cn(
                "flex min-h-full w-full flex-col items-center justify-center px-3 py-8 text-center transition-colors",
                dragOver && !uploadDisabled && "bg-slate-50",
                dragRejected && "cursor-not-allowed",
              )}
            >
              {!uploadPending && <FileUp className="mb-3 h-6 w-6 text-slate-400" />}
              {!uploadPending && (
                <p className="text-sm font-semibold text-slate-600">
                  {!canWrite
                    ? t.noReferenceFiles
                    : dragOver
                      ? t.releaseToUpload
                      : dragRejected
                        ? t.unsupportedFormat
                        : t.dragFilesToUpload}
                </p>
              )}
            </div>
          ) : (
            <div ref={menuRef} className="w-full min-w-0">
              <div
                className={cn(
                  "grid items-center gap-2 border-b border-gray-100 px-1 pb-2 text-[11px] font-medium text-slate-400",
                  controlsStacked
                    ? "grid-cols-[24px_minmax(0,1fr)_28px]"
                    : "grid-cols-[24px_minmax(0,1fr)_64px_28px]",
                )}
              >
                <input
                  type="checkbox"
                  aria-label={t.selectAllFiles}
                  className={cn(
                    "h-4 w-4 rounded border-gray-300 text-slate-900 focus:ring-slate-300",
                    !someVisibleSelected && "opacity-0 hover:opacity-100",
                  )}
                  checked={allVisibleSelected}
                  ref={(node) => {
                    if (node) node.indeterminate = someVisibleSelected && !allVisibleSelected;
                  }}
                  onChange={(event) => {
                    selectionAnchorRef.current = null;
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
                <span>{t.name}</span>
                {!controlsStacked && <span>{t.type}</span>}
                <div className="relative flex justify-end">
                  {someVisibleSelected && (
                    <div className="absolute right-0 top-1/2 flex -translate-y-1/2 items-center gap-1 rounded-control bg-white">
                      <button
                        type="button"
                        title={t.downloadSelectedFiles}
                        disabled={downloadPending || deleteMut.isPending}
                        className="rounded p-1 text-slate-500 hover:bg-gray-50 hover:text-slate-900"
                        onClick={() => downloadNames(selectedVisibleNames)}
                      >
                        <Download className="h-3.5 w-3.5" />
                      </button>
                      <button
                        type="button"
                        title={t.deleteSelectedFiles}
                        disabled={writeDisabled}
                        className="rounded p-1 text-red-500 hover:bg-red-50 disabled:cursor-not-allowed"
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
                  {t.noMatchingFiles}
                </p>
              ) : (
                <ul>
                  {filteredRows.map((row) => {
                    const selected = selectedNames.has(row.name);
                    const menuOpen = menuName === row.name;
                    return (
                      <li
                        key={row.id}
                        draggable={!uploadDisabled && canDragReferenceToReview}
                        onDragStart={(event) => handleReferenceDragStart(event, row)}
                        className={cn(
                          "group grid items-center gap-2 border-b border-gray-100 px-1 py-2 text-xs hover:bg-gray-50",
                          !uploadDisabled &&
                            canDragReferenceToReview &&
                            "cursor-grab active:cursor-grabbing",
                          controlsStacked
                            ? "grid-cols-[24px_minmax(0,1fr)_28px]"
                            : "grid-cols-[24px_minmax(0,1fr)_64px_28px]",
                        )}
                      >
                        <input
                          type="checkbox"
                          aria-label={t.selectFile(row.name)}
                          className={cn(
                            "h-4 w-4 rounded border-gray-300 text-slate-900 focus:ring-slate-300",
                            !selected && "opacity-0 group-hover:opacity-100",
                          )}
                          checked={selected}
                          onChange={(event) => {
                            updateFileSelection(
                              row.name,
                              event.target.checked,
                              (event.nativeEvent as MouseEvent).shiftKey,
                            );
                          }}
                        />
                        <button
                          type="button"
                          className="reference-file-name flex min-w-0 items-center gap-2 text-left font-medium text-slate-700 hover:text-slate-950 hover:underline"
                          title={row.name}
                          onClick={() => void openReferencePreview(row.name)}
                        >
                          <span className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-slate-100 text-slate-500">
                            <ReferenceFileIcon name={row.name} />
                          </span>
                          <span className="min-w-0 truncate">{basename(row.name)}</span>
                        </button>
                        {!controlsStacked && <span className="truncate text-[11px] text-slate-400">
                          {extensionLabel(row.name)}
                        </span>}
                        <div className="relative flex justify-end">
                          <button
                            type="button"
                            aria-label={t.moreActions(row.name)}
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
                                disabled={downloadPending || deleteMut.isPending}
                                className="flex w-full items-center gap-2 px-2 py-1.5 text-left text-xs text-slate-700 hover:bg-gray-50"
                                onClick={() => downloadNames([row.name])}
                              >
                                <Download className="h-3.5 w-3.5" />
                                {t.download}
                              </button>
                              <button
                                type="button"
                                disabled={writeDisabled}
                                className="flex w-full items-center gap-2 px-2 py-1.5 text-left text-xs text-red-600 hover:bg-red-50 disabled:cursor-not-allowed"
                                onClick={() =>
                                  setDeleteTarget({ kind: "single", names: [row.name] })
                                }
                              >
                                <Trash2 className="h-3.5 w-3.5" />
                                {t.remove}
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
          <p className="truncate whitespace-nowrap text-[11px] leading-4 text-slate-400">
            <span className="font-medium">{t.supportedFiles}</span>
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
                  {deleteTarget.kind === "multiple" ? t.deleteFilesTitle : t.deleteFileTitle}
                </p>
                {deleteTarget.kind === "single" && (
                  <p className="mt-1 break-words text-xs leading-5 text-slate-500">
                    {deleteTarget.names[0]}
                  </p>
                )}
                <p className="mt-0.5 text-xs leading-5 text-slate-500">
                  {deleteTarget.kind === "multiple"
                    ? t.deleteFilesDescription(deleteTarget.names.length)
                    : t.irreversibleAction}
                </p>
              </div>
              <div className="flex justify-center gap-2">
                <button
                  type="button"
                  className="rounded-control border border-gray-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-gray-50"
                  onClick={() => setDeleteTarget(null)}
                >
                  {t.cancel}
                </button>
                <button
                  type="button"
                  disabled={deleteMut.isPending}
                  className="rounded-control bg-red-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-50"
                  onClick={confirmDelete}
                >
                  {t.remove}
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
                {projectId && (preview.kind === "pdf" || preview.kind === "text") && !preview.loading && !preview.error && (
                  <button
                    type="button"
                    className="inline-flex h-7 w-7 items-center justify-center rounded-control text-slate-500 hover:bg-gray-50 hover:text-slate-900"
                    aria-label={t.openInNewTab}
                    title={t.openInNewTab}
                    onClick={openPreviewInNewTab}
                  >
                    <ExternalLink className="h-4 w-4" />
                  </button>
                )}
                <button
                  type="button"
                  className="inline-flex h-7 w-7 items-center justify-center rounded-control text-slate-500 hover:bg-gray-50 hover:text-slate-900"
                  aria-label={t.close}
                  onClick={closePreview}
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
              <div className="min-h-0 flex-1 overflow-auto p-4">
                {preview.loading ? (
                  <div className="flex min-h-[180px] flex-col items-center justify-center gap-3 text-center">
                    <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
                    <p className="text-sm text-slate-500">{t.readingFile}</p>
                  </div>
                ) : preview.error ? (
                  <div className="flex flex-col items-center gap-3 text-center">
                    <p className="text-sm leading-6 text-slate-500">{preview.error}</p>
                    <button
                      type="button"
                      disabled={downloadPending || deleteMut.isPending}
                      className="inline-flex items-center gap-1 rounded-control border border-gray-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-gray-50"
                      onClick={() => downloadNames([preview.name])}
                    >
                      <Download className="h-3.5 w-3.5" />
                      {t.download}
                    </button>
                  </div>
                ) : preview.kind === "pdf" && preview.url ? (
                  <iframe
                    title={preview.name}
                    src={preview.url}
                    className="h-[60vh] w-full rounded-control border border-gray-200"
                  />
                ) : (
                  renderTextPreview(preview)
                )}
              </div>
            </div>
          </div>
        )}
        {formatError && (
          <div className="absolute inset-0 z-30 flex items-center justify-center bg-white/80 px-4 backdrop-blur-sm">
            <div className="w-full max-w-[280px] rounded-card border border-gray-200 bg-white p-4 shadow-lg">
              <div className="mb-3">
                <p className="text-sm font-semibold text-slate-900">{t.unableProcessFile}</p>
                <div className="mt-2 space-y-2 text-xs leading-5 text-slate-500">
                  {formatError.split("\n").map((line) => (
                    <p key={line} className="break-words">
                      {line}
                    </p>
                  ))}
                </div>
              </div>
              <div className="flex justify-end">
                <button
                  type="button"
                  className="rounded-control bg-slate-950 px-3 py-1.5 text-xs font-semibold text-white hover:bg-slate-800"
                  onClick={() => setFormatError(null)}
                >
                  {t.confirm}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </PanelChrome>
  );
}
