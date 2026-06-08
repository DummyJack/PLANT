import type { FileTreeNode, LibraryRow } from "@/types/api";

function sourceForPath(path: string): LibraryRow["source"] | null {
  if (/^artifact\/drafts\/draft_v\d+\.md$/i.test(path)) return "Analyst";
  if (/^output\/srs\.md$/i.test(path)) return "Documenter";
  if (/^output\/design_rationale\.md$/i.test(path)) return "Documenter";
  if (/^artifact\/MoM\//i.test(path)) return "Meeting";
  if (/^artifact\/models\//i.test(path) && path.endsWith(".plantuml"))
    return "Modeler";
  return null;
}

export function buildArtifactRows(items: FileTreeNode[]): LibraryRow[] {
  const rows: LibraryRow[] = [];
  for (const item of items) {
    if (item.kind !== "file") continue;
    const source = sourceForPath(item.path);
    if (!source) continue;
    rows.push({
      id: `art-${item.path}`,
      name: item.name,
      source,
      path: item.path,
      editable: item.editable,
      deletable: false,
    });
  }
  return rows;
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

export function mergeLibraryRows(
  references: Array<{ name: string }>,
  artifacts: FileTreeNode[],
): LibraryRow[] {
  const artifactRows = buildArtifactRows(artifacts);
  const refRows = buildReferenceRows(references);
  const byName = new Map<string, LibraryRow>();
  for (const row of [...refRows, ...artifactRows]) {
    byName.set(`${row.source}:${row.name}`, row);
  }
  return Array.from(byName.values()).sort((a, b) =>
    a.name.localeCompare(b.name, "zh-Hant"),
  );
}

export function listDraftVersions(items: FileTreeNode[]): string[] {
  return items
    .filter((i) => /^artifact\/drafts\/draft_v(\d+)\.md$/i.test(i.path))
    .map((i) => {
      const m = /draft_v(\d+)\.md$/i.exec(i.path);
      return m ? `draft_v${m[1]}` : i.name;
    })
    .sort((a, b) => {
      const na = parseInt(/v(\d+)/.exec(a)?.[1] ?? "0", 10);
      const nb = parseInt(/v(\d+)/.exec(b)?.[1] ?? "0", 10);
      return na - nb;
    });
}

export function listMeetingRounds(items: FileTreeNode[]): string[] {
  const rounds = new Set<string>();
  for (const item of items) {
    const m = /formal_meeting_r(\d+)\.json$/i.exec(item.path);
    if (m) rounds.add(`R${m[1]}`);
    const mom = /MoM\/R(\d+)-/i.exec(item.path);
    if (mom) rounds.add(`R${mom[1]}`);
  }
  return Array.from(rounds).sort();
}
