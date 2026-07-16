import type { LibraryRow } from "@/types/api";

export function referenceExt(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot >= 0 ? name.slice(dot).toLowerCase() : "";
}

export function referenceLabel(name: string): string {
  const ext = referenceExt(name).slice(1).toUpperCase();
  return ext || "FILE";
}

export function referenceIconMeta(name: string): {
  label: string;
  fill: string;
  fold: string;
} {
  const ext = referenceExt(name);
  if (ext === ".pdf") return { label: "PDF", fill: "#ef4444", fold: "#fecaca" };
  if (ext === ".pptx") return { label: "PPT", fill: "#f97316", fold: "#fed7aa" };
  if (ext === ".xlsx" || ext === ".csv") {
    return { label: ext === ".csv" ? "CSV" : "XLS", fill: "#16a34a", fold: "#bbf7d0" };
  }
  if (ext === ".doc" || ext === ".docx") return { label: "DOC", fill: "#2563eb", fold: "#bfdbfe" };
  if (ext === ".md") return { label: "MD", fill: "#475569", fold: "#cbd5e1" };
  if (ext === ".txt") return { label: "TXT", fill: "#64748b", fold: "#cbd5e1" };
  if (ext === ".json") return { label: "JSN", fill: "#7c3aed", fold: "#ddd6fe" };
  return { label: "FILE", fill: "#64748b", fold: "#cbd5e1" };
}

export function buildReferenceRows(
  references: Array<{ name: string }>,
): LibraryRow[] {
  return references.map((ref) => ({
    id: `ref-${ref.name}`,
    name: ref.name,
    source: "外部上傳" as const,
    path: `doc/${ref.name}`,
    editable: /\.(md|json|plantuml)$/i.test(ref.name),
    deletable: true,
  }));
}

export function ReferenceFileIcon({
  name,
  className = "h-6 w-5",
}: {
  name: string;
  className?: string;
}) {
  const meta = referenceIconMeta(name);

  return (
    <svg
      viewBox="0 0 28 32"
      aria-hidden="true"
      className={className}
      role="img"
    >
      <path d="M4 1.5h13.5L24 8v22.5H4z" fill={meta.fill} />
      <path d="M17.5 1.5V8H24z" fill={meta.fold} />
      <path d="M17.5 1.5V8H24" fill="none" stroke="rgba(15,23,42,.22)" strokeWidth="1" />
      <text
        x="14"
        y="22"
        textAnchor="middle"
        fontSize={meta.label.length > 3 ? 5.2 : 6.2}
        fontWeight="700"
        fill="white"
        fontFamily="ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
      >
        {meta.label}
      </text>
    </svg>
  );
}
