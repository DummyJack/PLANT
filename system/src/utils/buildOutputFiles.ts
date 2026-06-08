import type { FileTreeNode } from "@/types/api";

export interface OutputFile {
  path: string;
  label: string;
  kind: "html" | "image" | "plantuml" | "json";
  /** Base name under artifact/models/ for pairing .png with source */
  modelBase?: string;
}

const OUTPUT_LABELS: Record<string, string> = {
  "results/srs.html": "SRS",
  "results/design_rationale.html": "Design Rationale",
  "artifact/meeting/elicitation_meeting.json": "需求擷取會議",
  "artifact/meeting/issues.json": "會議議題",
  "artifact/requirements.json": "需求資料",
  "artifact/feedback.json": "領域回饋",
};

const OUTPUT_PATTERNS: Array<{
  test: RegExp;
  kind: OutputFile["kind"];
  label?: (path: string, name: string) => string;
  modelBase?: (path: string, name: string) => string | undefined;
}> = [
  {
    test: /^results\/[^/]+\.html$/i,
    kind: "html",
    label: (path, name) => OUTPUT_LABELS[path] ?? name.replace(/\.html$/i, ""),
  },
  {
    test: /^results\/drafts\/draft_v\d+\.html$/i,
    kind: "html",
    label: (_p, name) => `v${name.replace(/^draft_v|\.html$/gi, "")}`,
  },
  {
    test: /^results\/(MoM|report)\/[^/]+\.html$/i,
    kind: "html",
    label: (path, name) => {
      if (path.startsWith("results/MoM/")) {
        return name.replace(/\.html$/i, "");
      }
      if (name === "conflict_report.html") return "需求衝突報告";
      return name.replace(/\.html$/i, "");
    },
  },
  {
    test: /^results\/[^/]+\/[^/]+\.html$/i,
    kind: "html",
    label: (_p, name) => name.replace(/\.html$/i, ""),
  },
  {
    test: /^artifact\/meeting\/formal_meeting_r\d+\.json$/i,
    kind: "json",
    label: (_p, name) => `正式會議 ${name.replace(/^formal_meeting_r|\.json$/gi, "R")}`,
  },
  {
    test: /^artifact\/meeting\/(elicitation_meeting|issues)\.json$/i,
    kind: "json",
    label: (path, name) => OUTPUT_LABELS[path] ?? name.replace(/\.json$/i, ""),
  },
  {
    test: /^artifact\/(requirements|feedback)\.json$/i,
    kind: "json",
    label: (path, name) => OUTPUT_LABELS[path] ?? name.replace(/\.json$/i, ""),
  },
  {
    test: /^artifact\/models\/.+\.(png|svg)$/i,
    kind: "image",
    label: (_p, name) => name.replace(/\.(png|svg)$/i, ""),
    modelBase: (_p, name) => name.replace(/\.(png|svg)$/i, ""),
  },
  {
    test: /^artifact\/models\/.+\.(plantuml|puml)$/i,
    kind: "plantuml",
    label: (_p, name) => name.replace(/\.(plantuml|puml)$/i, ""),
    modelBase: (_p, name) => name.replace(/\.(plantuml|puml)$/i, ""),
  },
];

export function buildOutputFiles(items: FileTreeNode[]): OutputFile[] {
  const files: OutputFile[] = [];
  const seen = new Set<string>();

  for (const item of items) {
    if (item.kind !== "file") continue;
    for (const pattern of OUTPUT_PATTERNS) {
      if (!pattern.test.test(item.path)) continue;
      if (seen.has(item.path)) break;
      seen.add(item.path);
      files.push({
        path: item.path,
        kind: pattern.kind,
        label: pattern.label?.(item.path, item.name) ?? item.name,
        modelBase: pattern.modelBase?.(item.path, item.name),
      });
      break;
    }
  }

  return files.sort((a, b) => {
    const order = (p: string) => {
      if (p === "results/srs.html" || p === "results/design_rationale.html") return 0;
      if (p.includes("/drafts/")) return 1;
      if (p.includes("/meeting/")) return 2;
      if (p.endsWith("requirements.json") || p.endsWith("feedback.json")) return 3;
      if (p.endsWith(".png") || p.endsWith(".svg")) return 4;
      return 5;
    };
    const d = order(a.path) - order(b.path);
    return d !== 0 ? d : a.label.localeCompare(b.label, "zh-Hant");
  });
}

export function findModelPair(
  files: OutputFile[],
  selected: OutputFile,
): { source?: OutputFile; image?: OutputFile } {
  if (!selected.modelBase) return {};
  const siblings = files.filter((f) => f.modelBase === selected.modelBase);
  return {
    source: siblings.find((f) => f.kind === "plantuml"),
    image: siblings.find((f) => f.kind === "image"),
  };
}

export function filenameFromPath(path: string | null): string {
  if (!path) return "尚未選擇";
  return path.split("/").pop() ?? path;
}
