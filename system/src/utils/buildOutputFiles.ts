import type { FileTreeNode } from "@/types/api";

export interface OutputFile {
  path: string;
  label: string;
  kind: "html" | "image" | "plantuml" | "json" | "markdown";
  /** Base name under artifact/models/ for pairing .png with source */
  modelBase?: string;
}

const OUTPUT_LABELS: Record<string, string> = {
  "results/srs.html": "SRS",
  "results/design_rationale.html": "Design Rationale",
  "artifact/meeting/elicitation_meeting.json": "Elicitation Meeting",
  "artifact/meeting/issues.json": "Issues",
  "artifact/requirements.json": "Requirements",
  "artifact/feedback.json": "Feedback",
  "artifact/project.json": "Project",
  "artifact/scope.json": "Scope",
  "artifact/system_models.json": "System Models",
  "artifact/result.json": "Conflict",
};

function reportLabel(name: string) {
  const version = /^conflict_report_v(\d+)\.(?:html|md|json)$/i.exec(name)?.[1];
  return version ? `衝突報告 v${Number(version)}` : name.replace(/\.(?:html|md|json)$/i, "");
}

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
    test: /^artifact\/drafts\/draft_v\d+\.md$/i,
    kind: "markdown",
    label: (_p, name) => `v${name.replace(/^draft_v|\.md$/gi, "")}`,
  },
  {
    test: /^output\/(srs|design_rationale)\.md$/i,
    kind: "markdown",
    label: (path, name) => {
      if (path === "output/srs.md") return "SRS";
      if (path === "output/design_rationale.md") return "Design Rationale";
      return name.replace(/\.md$/i, "");
    },
  },
  {
    test: /^results\/(MoM|report)\/[^/]+\.html$/i,
    kind: "html",
    label: (path, name) => {
      if (path.startsWith("results/MoM/")) {
        return name.replace(/\.html$/i, "");
      }
      return reportLabel(name);
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
    label: (_p, name) =>
      `Formal Meeting ${name.replace(/^formal_meeting_r/i, "R").replace(/\.json$/i, "")}`,
  },
  {
    test: /^artifact\/meeting\/(elicitation_meeting|issues)\.json$/i,
    kind: "json",
    label: (path, name) => OUTPUT_LABELS[path] ?? name.replace(/\.json$/i, ""),
  },
  {
    test: /^artifact\/(project|scope|system_models|requirements|feedback|result)\.json$/i,
    kind: "json",
    label: (path, name) => OUTPUT_LABELS[path] ?? name.replace(/\.json$/i, ""),
  },
  {
    test: /^artifact\/report\/conflict_report_v\d+\.json$/i,
    kind: "json",
    label: (_p, name) => reportLabel(name),
  },
  {
    test: /^artifact\/report\/conflict_report_v\d+\.md$/i,
    kind: "markdown",
    label: (_p, name) => reportLabel(name),
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

function outputKind(path: string): OutputFile["kind"] | null {
  if (/\.html$/i.test(path)) return "html";
  if (/\.json$/i.test(path)) return "json";
  if (/\.md$/i.test(path)) return "markdown";
  if (/\.(png|svg)$/i.test(path)) return "image";
  if (/\.(plantuml|puml)$/i.test(path)) return "plantuml";
  return null;
}

function isOutputRoot(path: string): boolean {
  return /^(artifact|results|output|manual)\//i.test(path);
}

function defaultOutputLabel(path: string, name: string): string {
  if (OUTPUT_LABELS[path]) return OUTPUT_LABELS[path];
  return name.replace(/\.(html|json|md|png|svg|plantuml|puml)$/i, "");
}

function modelBaseForPath(path: string, name: string): string | undefined {
  if (!/^artifact\/models\//i.test(path)) return undefined;
  if (!/\.(png|svg|plantuml|puml)$/i.test(name)) return undefined;
  return name.replace(/\.(png|svg|plantuml|puml)$/i, "");
}

export function buildOutputFiles(items: FileTreeNode[]): OutputFile[] {
  const files: OutputFile[] = [];
  const seen = new Set<string>();

  for (const item of items) {
    if (item.kind !== "file") continue;
    if (/^results\/report\/conflict_report\.html$/i.test(item.path)) continue;
    if (seen.has(item.path)) continue;
    let matched = false;
    for (const pattern of OUTPUT_PATTERNS) {
      if (!pattern.test.test(item.path)) continue;
      seen.add(item.path);
      files.push({
        path: item.path,
        kind: pattern.kind,
        label: pattern.label?.(item.path, item.name) ?? item.name,
        modelBase: pattern.modelBase?.(item.path, item.name),
      });
      matched = true;
      break;
    }
    if (matched || !isOutputRoot(item.path)) continue;
    const kind = outputKind(item.path);
    if (!kind) continue;
    seen.add(item.path);
    files.push({
      path: item.path,
      kind,
      label: defaultOutputLabel(item.path, item.name),
      modelBase: modelBaseForPath(item.path, item.name),
    });
  }

  return files.sort((a, b) => {
    const order = (p: string) => {
      if (p === "results/srs.html" || p === "results/design_rationale.html") return 0;
      if (p.includes("/drafts/")) return 1;
      if (p.includes("/meeting/")) return 2;
      if (p.endsWith("requirements.json") || p.endsWith("feedback.json")) return 3;
      if (p.startsWith("artifact/")) return 4;
      if (p.endsWith(".png") || p.endsWith(".svg")) return 5;
      return 5;
    };
    const d = order(a.path) - order(b.path);
    return d !== 0 ? d : a.label.localeCompare(b.label, "zh-Hant");
  });
}

export function resolvePreferredOutputPath(
  path: string | null | undefined,
  files: OutputFile[],
): string | null {
  if (!path) return null;

  const candidates: string[] = [];
  const draft = /^artifact\/drafts\/draft_v(\d+)\.md$/i.exec(path);
  if (draft) candidates.push(`results/drafts/draft_v${draft[1]}.html`);
  const draftHtml = /^results\/drafts\/draft_v(\d+)\.html$/i.exec(path);
  if (draftHtml) candidates.push(path);

  const report = /^artifact\/report\/conflict_report_v(\d+)\.(?:md|json)$/i.exec(path);
  if (report) candidates.push(`results/report/conflict_report_v${report[1]}.html`);
  const reportHtml = /^results\/report\/conflict_report_v(\d+)\.html$/i.exec(path);
  if (reportHtml) candidates.push(path);

  if (/^output\/srs\.md$/i.test(path)) candidates.push("results/srs.html");
  if (/^results\/srs\.html$/i.test(path)) candidates.push(path);
  if (/^output\/design_rationale\.md$/i.test(path)) {
    candidates.push("results/design_rationale.html");
  }
  if (/^results\/design_rationale\.html$/i.test(path)) {
    candidates.push(path);
  }

  candidates.push(path);
  return candidates.find((candidate) => files.some((file) => file.path === candidate)) ?? null;
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
