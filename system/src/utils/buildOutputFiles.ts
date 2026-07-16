import type { FileTreeNode } from "@/types/api";

export interface OutputFile {
  path: string;
  label: string;
  kind: "html" | "image" | "plantuml" | "json" | "markdown";
  /** Base name under artifact/models/ for pairing .png with source */
  modelBase?: string;
}

interface DocumentLabels {
  designRationale?: string;
  specification?: string;
}

function outputLabels(labels?: DocumentLabels): Record<string, string> {
  return {
    "results/srs.html": labels?.specification ?? "SRS",
    "results/design_rationale.html": labels?.designRationale ?? "Design Rationale",
    "artifact/meeting/elicitation_meeting.json": "Elicitation Meeting",
    "artifact/meeting/issues.json": "Issues",
    "artifact/requirements.json": "Requirements",
    "artifact/feedback.json": "Feedback",
    "artifact/project.json": "Project",
    "artifact/scope.json": "Scope",
    "artifact/system_models.json": "System Models",
    "artifact/result.json": "Conflict",
  };
}

function reportLabel(name: string) {
  const version = /^conflict_report_v(\d+)\.(?:html|md|json)$/i.exec(name)?.[1];
  return version ? `Report v${Number(version)}` : name.replace(/\.(?:html|md|json)$/i, "");
}

const OUTPUT_PATTERNS: Array<{
  test: RegExp;
  kind: OutputFile["kind"];
  label?: (path: string, name: string, labels?: DocumentLabels) => string;
  modelBase?: (path: string, name: string) => string | undefined;
}> = [
  {
    test: /^results\/[^/]+\.html$/i,
    kind: "html",
    label: (path, name, labels) => outputLabels(labels)[path] ?? name.replace(/\.html$/i, ""),
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
    label: (path, name, labels) => {
      if (path === "output/srs.md") return labels?.specification ?? "SRS";
      if (path === "output/design_rationale.md") return labels?.designRationale ?? "Design Rationale";
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
    test: /^artifact\/MoM\/R\d+-M\d+\.md$/i,
    kind: "markdown",
    label: (_p, name) => name.replace(/\.md$/i, ""),
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
    label: (path, name, labels) => outputLabels(labels)[path] ?? name.replace(/\.json$/i, ""),
  },
  {
    test: /^artifact\/(project|scope|system_models|requirements|feedback|result)\.json$/i,
    kind: "json",
    label: (path, name, labels) => outputLabels(labels)[path] ?? name.replace(/\.json$/i, ""),
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
  return /^(artifact|results|output)\//i.test(path);
}

function defaultOutputLabel(path: string, name: string, labels?: DocumentLabels): string {
  const label = outputLabels(labels)[path];
  if (label) return label;
  return name.replace(/\.(html|json|md|png|svg|plantuml|puml)$/i, "");
}

function modelBaseForPath(path: string, name: string): string | undefined {
  if (!/^artifact\/models\//i.test(path)) return undefined;
  if (!/\.(png|svg|plantuml|puml)$/i.test(name)) return undefined;
  return name.replace(/\.(png|svg|plantuml|puml)$/i, "");
}

export function buildOutputFiles(items: FileTreeNode[], labels?: DocumentLabels): OutputFile[] {
  const files: OutputFile[] = [];
  const seen = new Set<string>();
  const availablePaths = new Set(
    items.filter((item) => item.kind === "file").map((item) => item.path),
  );

  for (const item of items) {
    if (item.kind !== "file") continue;
    if (/^manual\//i.test(item.path)) continue;
    if (/^artifact\/workflow_state\.json$/i.test(item.path)) continue;
    if (/^artifact\/meeting\/issues\.json$/i.test(item.path)) continue;
    if (/^results\/report\/conflict_report\.html$/i.test(item.path)) continue;
    if (/^artifact\/report\/conflict_report_v\d+\.json$/i.test(item.path)) continue;
    const momMd = /^artifact\/MoM\/(R\d+-M\d+)\.md$/i.exec(item.path);
    if (momMd && availablePaths.has(`results/MoM/${momMd[1]}.html`)) {
      continue;
    }
    const modelAsset = /^artifact\/models\/(.+)\.(png|svg|plantuml|puml)$/i.exec(item.path);
    if (modelAsset) {
      const [, base, ext] = modelAsset;
      const pngPath = `artifact/models/${base}.png`;
      if (/^svg$/i.test(ext) && availablePaths.has(pngPath)) {
        continue;
      }
    }
    const resultModelImage = /^results\/models\/(.+)\.(png|svg)$/i.exec(item.path);
    if (resultModelImage) {
      const [, base] = resultModelImage;
      if (
        availablePaths.has(`artifact/models/${base}.png`) ||
        availablePaths.has(`artifact/models/${base}.svg`)
      ) {
        continue;
      }
    }
    const draftMd = /^artifact\/drafts\/draft_v(\d+)\.md$/i.exec(item.path);
    if (draftMd && availablePaths.has(`results/drafts/draft_v${draftMd[1]}.html`)) {
      continue;
    }
    if (
      /^output\/srs\.md$/i.test(item.path) &&
      availablePaths.has("results/srs.html")
    ) {
      continue;
    }
    if (
      /^output\/design_rationale\.md$/i.test(item.path) &&
      availablePaths.has("results/design_rationale.html")
    ) {
      continue;
    }
    const reportRaw = /^artifact\/report\/conflict_report_v(\d+)\.(?:md|json)$/i.exec(item.path);
    if (reportRaw && availablePaths.has(`results/report/conflict_report_v${reportRaw[1]}.html`)) {
      continue;
    }
    if (seen.has(item.path)) continue;
    let matched = false;
    for (const pattern of OUTPUT_PATTERNS) {
      if (!pattern.test.test(item.path)) continue;
      seen.add(item.path);
      files.push({
        path: item.path,
        kind: pattern.kind,
        label: pattern.label?.(item.path, item.name, labels) ?? item.name,
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
      label: defaultOutputLabel(item.path, item.name, labels),
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
    if (d !== 0) return d;
    const momA = /^R(\d+)-M(\d+)$/i.exec(a.label);
    const momB = /^R(\d+)-M(\d+)$/i.exec(b.label);
    if (momA && momB) {
      const roundDiff = Number(momA[1]) - Number(momB[1]);
      if (roundDiff !== 0) return roundDiff;
      return Number(momA[2]) - Number(momB[2]);
    }
    return a.label.localeCompare(b.label, "zh-Hant");
  });
}

export function resolvePreferredOutputPath(
  path: string | null | undefined,
  files: OutputFile[],
): string | null {
  if (!path) return null;

  const candidates: string[] = [];
  const draft = /^artifact\/drafts\/draft_v(\d+)\.md$/i.exec(path);
  if (draft) candidates.push(`results/drafts/draft_v${draft[1]}.html`, path);
  const draftHtml = /^results\/drafts\/draft_v(\d+)\.html$/i.exec(path);
  if (draftHtml) candidates.push(path, `artifact/drafts/draft_v${draftHtml[1]}.md`);

  const report = /^artifact\/report\/conflict_report_v(\d+)\.(?:md|json)$/i.exec(path);
  if (report) candidates.push(`results/report/conflict_report_v${report[1]}.html`, path);
  const reportHtml = /^results\/report\/conflict_report_v(\d+)\.html$/i.exec(path);
  if (reportHtml) candidates.push(path, `artifact/report/conflict_report_v${reportHtml[1]}.md`);

  const mom = /^artifact\/MoM\/(R\d+-M\d+)\.md$/i.exec(path);
  if (mom) candidates.push(`results/MoM/${mom[1]}.html`, path);
  const momHtml = /^results\/MoM\/(R\d+-M\d+)\.html$/i.exec(path);
  if (momHtml) candidates.push(path, `artifact/MoM/${momHtml[1]}.md`);

  if (/^output\/srs\.md$/i.test(path)) candidates.push("results/srs.html", path);
  if (/^results\/srs\.html$/i.test(path)) candidates.push(path, "output/srs.md");
  if (/^output\/design_rationale\.md$/i.test(path)) {
    candidates.push("results/design_rationale.html", path);
  }
  if (/^results\/design_rationale\.html$/i.test(path)) {
    candidates.push(path, "output/design_rationale.md");
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
