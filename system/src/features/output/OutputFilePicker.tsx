import { useEffect, useMemo } from "react";
import { SelectControl } from "@/components/SelectControl";
import { useUiStore } from "@/stores/uiStore";
import type { FileTreeNode } from "@/types/api";
import { buildOutputFiles, type OutputFile } from "@/utils/buildOutputFiles";

interface OutputFilePickerProps {
  projectId: string | null;
  items: FileTreeNode[];
}

const GROUPS = [
  { id: "documents", label: "Output" },
  { id: "drafts", label: "Draft" },
  { id: "meetings", label: "MoM" },
  { id: "reports", label: "Conflict" },
  { id: "models", label: "Model" },
] as const;

function groupForFile(file: OutputFile): (typeof GROUPS)[number]["id"] {
  if (file.path.startsWith("results/MoM/") || file.path.includes("/meeting/")) return "meetings";
  if (file.path.startsWith("results/report/")) return "reports";
  if (file.path.startsWith("results/") && !file.path.includes("/drafts/")) return "documents";
  if (file.path.includes("/drafts/")) return "drafts";
  return "models";
}

export function OutputFilePicker({ projectId, items }: OutputFilePickerProps) {
  const selectedOutputPath = useUiStore((s) => s.selectedOutputPath);
  const setSelectedOutputPath = useUiStore((s) => s.setSelectedOutputPath);

  const files = useMemo(() => buildOutputFiles(items), [items]);
  const selectableFiles = useMemo(
    () => files.filter((file) => file.kind === "html" || file.kind === "image"),
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

  useEffect(() => {
    if (!projectId) {
      if (selectedOutputPath !== null) setSelectedOutputPath(null);
      return;
    }
    if (selectableFiles.length === 0) {
      if (selectedOutputPath !== null) setSelectedOutputPath(null);
      return;
    }
    if (!selectedOutputPath || !selectableFiles.some((f) => f.path === selectedOutputPath)) {
      const srs = selectableFiles.find((f) => f.path === "results/srs.html");
      setSelectedOutputPath(srs?.path ?? selectableFiles[selectableFiles.length - 1].path);
    }
  }, [projectId, filePaths, selectableFiles, selectedOutputPath, setSelectedOutputPath]);

  return (
    <SelectControl
      disabled={!projectId || selectableFiles.length === 0}
      value={selectedOutputPath ?? ""}
      wrapperClassName="w-40 shrink-0"
      className="w-full truncate text-sm"
      onChange={(e) => setSelectedOutputPath(e.target.value || null)}
    >
      <option value="" disabled>
        選擇檔案
      </option>
      {selectableFiles.length === 0 ? (
        <option value="" disabled>
          尚無產出物
        </option>
      ) : (
        grouped.map((group) => (
          <optgroup key={group.id} label={group.label}>
            {group.files.map((f) => (
              <option key={f.path} value={f.path}>
                {f.label}
              </option>
            ))}
          </optgroup>
        ))
      )}
    </SelectControl>
  );
}
