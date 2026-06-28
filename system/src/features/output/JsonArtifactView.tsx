import { useQuery } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";
import { fetchFile } from "@/api/projects";
import { agentLabel } from "@/constants/agents";
import { useI18n } from "@/i18n";
import { sortStakeholdersByType } from "@/utils/stakeholders";
import { useEffect } from "react";
import type { ReactNode } from "react";

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

function text(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function fileName(value: string) {
  return value.split(/[\\/]/).filter(Boolean).pop() || value;
}

function sourceDisplayName(item: Record<string, unknown>, fallback: unknown) {
  return text(item.title) || text(item.name) || fileName(text(item.path) || text(item.url)) || String(fallback);
}

function sourceDedupeKey(item: Record<string, unknown>, fallback: unknown) {
  const title = sourceDisplayName(item, fallback);
  const path = text(item.path) || text(item.url);
  const name = fileName(path || title).toLowerCase();
  if (name.endsWith(".pdf")) return `pdf:${name}`;
  return (path || title || String(fallback)).toLowerCase();
}

function isPdfSource(item: Record<string, unknown>, title: string) {
  const value = `${title} ${text(item.path)} ${text(item.url)}`.toLowerCase();
  return value.includes(".pdf");
}

function decodeHtmlEntities(value: string) {
  return value
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&#39;/g, "'")
    .replace(/&quot;/g, '"');
}

function firstHtmlHeading(value: string) {
  const match = /<h1\b[^>]*>([\s\S]*?)<\/h1>/i.exec(value);
  if (!match) return "";
  return decodeHtmlEntities(match[1].replace(/<[^>]+>/g, " "))
    .replace(/\s+/g, " ")
    .trim();
}

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function htmlSectionText(value: string, heading: string) {
  const pattern = new RegExp(
    `<h[1-6]\\b[^>]*>\\s*${escapeRegExp(heading)}\\s*<\\/h[1-6]>([\\s\\S]*?)(?=<h[1-6]\\b|$)`,
    "i",
  );
  const match = pattern.exec(value);
  if (!match) return "";
  return decodeHtmlEntities(match[1].replace(/<[^>]+>/g, " "))
    .replace(/\s+/g, " ")
    .trim();
}

function firstMarkdownHeading(value: string) {
  const match = /^#\s+(.+)$/m.exec(value);
  return match?.[1]?.trim() ?? "";
}

function markdownSectionText(value: string, heading: string) {
  const pattern = new RegExp(
    `^##\\s+${escapeRegExp(heading)}\\s*$([\\s\\S]*?)(?=^##\\s+|\\s*$)`,
    "m",
  );
  const match = pattern.exec(value);
  if (!match) return "";
  return match[1]
    .replace(/^\s*[-*]\s+/gm, "")
    .replace(/\*\*(.*?)\*\*/g, "$1")
    .trim();
}

type UiTexts = ReturnType<typeof useI18n>["t"];

function stopReasonLabel(reason: string, t: UiTexts): string {
  switch (reason) {
    case "judge_finish":
      return t.stopReasonJudgeFinish;
    case "no_new_info":
      return t.stopReasonNoNewInfo;
    case "max_turn":
    case "max_turns_reached":
      return t.stopReasonMaxTurn;
    case "":
      return t.stopReasonMissing;
    default:
      return reason;
  }
}

function JsonBlock({ data }: { data: unknown }) {
  return (
    <pre className="overflow-auto rounded-control bg-slate-950 p-3 font-mono text-xs leading-relaxed text-slate-100">
      {JSON.stringify(data, null, 2)}
    </pre>
  );
}

function Section({
  title,
  children,
  titleAlign = "left",
  titleSize = "xs",
}: {
  title: string;
  children: ReactNode;
  titleAlign?: "left" | "center";
  titleSize?: "xs" | "sm";
}) {
  return (
    <section className="border-b border-gray-100 px-4 py-3 last:border-0">
      <h3
        className={`mb-2 font-semibold uppercase tracking-wide text-slate-500 ${
          titleSize === "sm" ? "text-sm" : "text-xs"
        } ${
          titleAlign === "center" ? "text-center" : ""
        }`}
      >
        {title}
      </h3>
      {children}
    </section>
  );
}

function ArtifactHeading({
  children,
  border = true,
}: {
  children: ReactNode;
  border?: boolean;
}) {
  return (
    <div className={`${border ? "border-b border-gray-100" : ""} px-4 py-3`}>
      <h3 className="text-center text-sm font-semibold tracking-wide text-slate-600">
        {children}
      </h3>
    </div>
  );
}

function Chip({ children }: { children: ReactNode }) {
  return (
    <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600">
      {children}
    </span>
  );
}

function Card({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-control border border-gray-200 bg-white p-3">
      {children}
    </div>
  );
}

function list(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function idList(value: unknown): string {
  if (Array.isArray(value)) return value.map(String).filter(Boolean).join(", ");
  return text(value);
}

function sourceLabel(item: Record<string, unknown>) {
  const source = text(item.source);
  const sourceIds = idList(item.source_ids);
  if (sourceIds) return sourceIds;
  return source;
}

function stakeholderStatementText(value: unknown): string {
  if (typeof value === "string") return value.trim();
  if (!isRecord(value)) return String(value ?? "").trim();
  return text(value.text);
}

function stakeholderStatementId(value: unknown): string {
  if (!isRecord(value)) return "";
  return text(value.id);
}

function titleCaseLabel(value: string) {
  return value
    .split(/[_\s-]+/)
    .filter(Boolean)
    .map((part) => `${part.charAt(0).toUpperCase()}${part.slice(1).toLowerCase()}`)
    .join(" ");
}

function requirementTypeAbbrev(value: string) {
  const normalized = value.trim().toLowerCase().replace(/_/g, "-");
  if (normalized === "functional") return "FR";
  if (normalized === "non-functional") return "NFR";
  if (normalized === "constraint") return "CON";
  return value;
}

function optionLabel(value: string, index: number) {
  const raw = value.trim().toUpperCase();
  if (/^\d+$/.test(raw)) return String.fromCharCode(64 + Math.max(1, Number(raw)));
  return raw || String.fromCharCode(65 + index);
}

function modelDescriptionText(value: string) {
  const purpose = /\*\*用途\*\*\s*[：:]\s*([\s\S]*?)(?=\n?\s*\*\*反映需求\*\*\s*[：:]|$)/.exec(value);
  if (purpose) return purpose[1].trim();
  return value;
}

function RequirementsView({ data, anchor }: { data: Record<string, unknown>; anchor?: string | null }) {
  const { t } = useI18n();
  const urls = list(data.URL);
  const reqs = list(data.REQ);
  useEffect(() => {
    if (anchor !== "requirements-req") return;
    window.requestAnimationFrame(() => {
      document.getElementById("requirements-req")?.scrollIntoView({
        behavior: "smooth",
        block: "start",
      });
    });
  }, [anchor]);
  const renderRows = (rows: unknown[], kind: "URL" | "REQ") => {
    if (rows.length === 0) {
      return <p className="text-sm text-slate-500">{t.noContent}</p>;
    }
    const records = rows.map((row) => (isRecord(row) ? row : {}));
    return (
      <div>
        <div className="hidden overflow-x-auto rounded-control border border-gray-200 bg-white md:block">
          <table className="w-full table-fixed border-collapse text-sm">
            <colgroup>
              <col className="w-20" />
              {kind === "REQ" && <col className="w-24" />}
              <col />
              {kind === "URL" && <col className="w-36" />}
            </colgroup>
          <thead className="bg-slate-50 text-xs text-slate-500">
            <tr>
              <th className="border-b px-3 py-2 text-left">ID</th>
              {kind === "REQ" && <th className="border-b px-3 py-2 text-left">{t.type}</th>}
              <th className="border-b px-3 py-2 text-left">{t.description}</th>
              {kind === "URL" && <th className="border-b px-3 py-2 text-left">{t.source}</th>}
            </tr>
          </thead>
          <tbody>
            {records.map((item, index) => (
                <tr key={index} className="align-top">
                  <td className="break-words border-b px-3 py-2 font-semibold text-slate-700">{text(item.id)}</td>
                  {kind === "REQ" && (
                    <td className="break-words border-b px-3 py-2 text-slate-600">
                      {requirementTypeAbbrev(text(item.type))}
                    </td>
                  )}
                  <td className="border-b px-3 py-2 leading-relaxed text-slate-800">
                    {text(item.text) || text(item.description)}
                  </td>
                  {kind === "URL" && (
                    <td className="break-words border-b px-3 py-2 text-xs text-slate-500">
                      {sourceLabel(item)}
                    </td>
                  )}
                </tr>
            ))}
          </tbody>
        </table>
        </div>
        <div className="space-y-2 md:hidden">
          {records.map((item, index) => (
            <Card key={index}>
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-semibold text-slate-800">
                  {text(item.id) || `#${index + 1}`}
                </span>
                {kind === "REQ" && text(item.type) && <Chip>{requirementTypeAbbrev(text(item.type))}</Chip>}
              </div>
              <p className="mt-2 text-sm leading-relaxed text-slate-800">
                {text(item.text) || text(item.description)}
              </p>
              {kind === "URL" && sourceLabel(item) && (
                <div className="mt-2 text-xs leading-relaxed text-slate-500">
                  {sourceLabel(item)}
                </div>
              )}
            </Card>
          ))}
        </div>
      </div>
    );
  };

  return (
    <div className="min-h-0 overflow-y-auto">
      <Section title={t.userRequirements} titleAlign="center" titleSize="sm">{renderRows(urls, "URL")}</Section>
      <div id="requirements-req">
        <Section title={t.formalRequirements} titleAlign="center" titleSize="sm">{renderRows(reqs, "REQ")}</Section>
      </div>
    </div>
  );
}

function externalDocumentSources(projectData: Record<string, unknown>): Array<Record<string, unknown>> {
  const meta = isRecord(projectData.meta) ? projectData.meta : {};
  const review = isRecord(projectData.domain_research_review)
    ? projectData.domain_research_review
    : {};
  const referencedFiles = [
    ...list(meta.domain_research_referenced_files),
    ...list(meta.attached_references),
    ...list(review.referenced_files),
  ];
  const seen = new Set<string>();
  return referencedFiles
    .map((row) => {
      if (isRecord(row)) {
        const name = text(row.name) || text(row.path);
        const path = text(row.path);
        return {
          title: name || path,
          path,
          type: text(row.type),
        };
      }
      const value = String(row ?? "").trim();
      return {
        title: value.split("/").pop() || value,
        path: value,
      };
    })
    .filter((row) => {
      const key = `${text(row.title)}|${text(row.path)}`;
      if (!text(row.title) || seen.has(key)) return false;
      seen.add(key);
      return true;
    });
}

function FeedbackView({ projectId, data }: { projectId: string | null; data: Record<string, unknown> }) {
  const { t } = useI18n();
  const sections: Array<[string, unknown[]]> = [
    [t.findings, list(data.findings)],
    [t.constraints, list(data.constraints)],
    [t.risks, list(data.risks)],
    [t.suggestions, list(data.recommendations)],
  ];
  const project = useQuery({
    queryKey: ["file", projectId, "artifact/project.json"],
    queryFn: () => fetchFile(projectId!, "artifact/project.json"),
    enabled: !!projectId,
    retry: false,
  });
  let projectData: Record<string, unknown> = {};
  try {
    const parsed = project.data?.content ? JSON.parse(project.data.content) : {};
    projectData = isRecord(parsed) ? parsed : {};
  } catch {
    projectData = {};
  }
  const sources = [...list(data.sources), ...externalDocumentSources(projectData)];
  const seenSources = new Set<string>();
  const uniqueSources = sources.filter((row) => {
    const item = isRecord(row) ? row : {};
    const key = sourceDedupeKey(item, row);
    if (!key || seenSources.has(key)) return false;
    seenSources.add(key);
    return true;
  });
  return (
    <div className="min-h-0 overflow-y-auto">
      <ArtifactHeading border={false}>{t.domainResearch}</ArtifactHeading>
      {sections.map(([title, rows]) => (
        <Section key={title} title={title}>
          {rows.length === 0 ? (
            <p className="text-sm text-slate-500">{t.noContent}</p>
          ) : (
            <div className="space-y-2">
              {rows.map((row, index) => {
                const item = isRecord(row) ? row : {};
                return (
                  <Card key={index}>
                    <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-800">
                      {text(item.text) || String(row)}
                    </p>
                    {list(item.related_requirement_ids).length > 0 && (
                      <div className="mt-4">
                        <div className="mb-2 text-xs font-semibold text-slate-500">
                          {t.relatedRequirements}
                        </div>
                        <div className="flex flex-wrap gap-1">
                        {list(item.related_requirement_ids).map((id) => (
                          <Chip key={String(id)}>{String(id)}</Chip>
                        ))}
                        </div>
                      </div>
                    )}
                  </Card>
                );
              })}
            </div>
          )}
        </Section>
      ))}
      <Section title={t.source}>
        {uniqueSources.length === 0 ? (
          <p className="text-sm text-slate-500">{t.noSources}</p>
        ) : (
          <div className="space-y-2">
            {uniqueSources.map((row, index) => {
              const item = isRecord(row) ? row : {};
              const title = sourceDisplayName(item, row);
              const url = text(item.url);
              const isPdf = isPdfSource(item, title);
              return (
                <Card key={index}>
                  {url && !isPdf ? (
                    <a
                      href={url}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex max-w-full items-center gap-1.5 text-sm font-medium text-blue-700 hover:text-blue-900 hover:underline"
                    >
                      <span className="min-w-0 truncate">{title}</span>
                      <ExternalLink className="h-3.5 w-3.5 shrink-0" />
                    </a>
                  ) : (
                    <p className="text-sm font-medium text-slate-800">{title}</p>
                  )}
                </Card>
              );
            })}
          </div>
        )}
      </Section>
    </div>
  );
}

function ScopeView({ data }: { data: Record<string, unknown> }) {
  const { t } = useI18n();
  const render = (rows: unknown[]) => (
    <div className="space-y-2">
      {rows.map((row, index) => (
        <Card key={index}>
          <p className="text-sm leading-relaxed text-slate-800">{String(row)}</p>
        </Card>
      ))}
    </div>
  );
  return (
    <div className="min-h-0 overflow-y-auto">
      <ArtifactHeading border={false}>{t.requirementScope}</ArtifactHeading>
      <Section title={t.inScope}>{render(list(data.in_scope))}</Section>
      <Section title={t.outOfScope}>{render(list(data.out_of_scope))}</Section>
    </div>
  );
}

function ProjectView({ data }: { data: Record<string, unknown> }) {
  const { t } = useI18n();
  return (
    <div className="min-h-0 overflow-y-auto">
      <section className="border-b border-gray-100 px-4 py-3">
        <Card>
          <div className="text-xs font-semibold text-slate-500">{t.initialThought}</div>
          <p className="mt-1 text-sm text-slate-800">{text(data.rough_idea)}</p>
          <div className="mt-3 text-xs font-semibold text-slate-500">{t.scenario}</div>
          <p className="mt-1 text-sm text-slate-800">{text(data.scenario)}</p>
        </Card>
      </section>
      <Section title={t.stakeholders} titleSize="sm">
        <div className="space-y-2">
          {sortStakeholdersByType(list(data.stakeholders), (row) =>
            isRecord(row) ? row.type : "",
          ).map((row, index) => {
            const item = isRecord(row) ? row : {};
            const type = text(item.type);
            return (
              <Card key={index}>
                <div className="flex items-start justify-between gap-3">
                  <span className="text-sm font-semibold text-slate-800">{text(item.name)}</span>
                  {type && <Chip>{(t.stakeholderTypeLabels as Record<string, string>)[type] ?? type}</Chip>}
                </div>
                <div className="mt-3 space-y-2">
                  {list(item.text).map((line, i) => {
                    const statement = stakeholderStatementText(line);
                    const statementId = stakeholderStatementId(line);
                    if (!statement) return null;
                    return (
                      <div key={i} className="rounded-control bg-slate-50 px-3 py-2">
                        {statementId && (
                          <div className="mb-1 text-[11px] font-semibold text-slate-400">
                            {statementId}
                          </div>
                        )}
                        <p className="text-sm leading-relaxed text-slate-700">{statement}</p>
                      </div>
                    );
                  })}
                </div>
              </Card>
            );
          })}
        </div>
      </Section>
    </div>
  );
}

function SystemModelsView({ data }: { data: unknown[] }) {
  const { t } = useI18n();
  return (
    <div className="min-h-0 overflow-y-auto">
      <Section title={t.systemModelGeneration} titleAlign="center" titleSize="sm">
        <div className="space-y-2">
          {data.map((row, index) => {
            const item = isRecord(row) ? row : {};
            const type = text(item.type);
            const description = modelDescriptionText(text(item.description));
            return (
              <Card key={index}>
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-semibold text-slate-800">{text(item.id)}</span>
                      <span className="text-sm font-semibold text-slate-800">{text(item.name)}</span>
                    </div>
                  </div>
                  {type && <Chip>{titleCaseLabel(type)}</Chip>}
                </div>
                <p className="mt-2 text-sm leading-relaxed text-slate-700">{description}</p>
                {list(item.related_requirement_ids).length > 0 && (
                  <div className="mt-4">
                    <div className="mb-2 text-xs font-semibold text-slate-500">
                      {t.relatedRequirements}
                    </div>
                    <div className="flex flex-wrap gap-1">
                      {list(item.related_requirement_ids).map((id) => (
                        <Chip key={String(id)}>{String(id)}</Chip>
                      ))}
                    </div>
                  </div>
                )}
              </Card>
            );
          })}
        </div>
      </Section>
    </div>
  );
}

function ConflictPairsView({ data }: { data: Record<string, unknown> }) {
  const { t } = useI18n();
  const versions = Object.entries(data)
    .filter(([key, value]) => /^v\d+$/i.test(key) && isRecord(value))
    .sort(([a], [b]) => Number(a.slice(1)) - Number(b.slice(1)));
  const sections = versions.length ? versions : [["", data] as [string, unknown]];
  const isConflict = (item: Record<string, unknown>) =>
    /conflict/i.test(text(item.final_label));

  return (
    <div className="min-h-0 overflow-y-auto">
      <Section title={t.conflictResults} titleAlign="center" titleSize="sm">
        <div className="space-y-4">
          {sections.map(([version, payload]) => {
            const versionData = isRecord(payload) ? payload : {};
            const pairs = list(versionData.pairs).map((row) => (isRecord(row) ? row : {}));
            const multiples = list(versionData.multiple).map((row) =>
              isRecord(row) ? row : {},
            );
            const rows = [...pairs, ...multiples];
            const multipleCount = multiples.length;
            const conflictCount = rows.filter(isConflict).length;
            const nonConflictCount = rows.length - conflictCount;
            return (
              <div key={version || "current"}>
                {version && (
                  <div className="mb-2 text-xs font-semibold uppercase text-slate-500">
                    {version}
                  </div>
                )}
                <div className="mb-3 grid grid-cols-4 gap-px overflow-hidden rounded-control border border-slate-200 bg-slate-100 text-center text-xs">
                  {[
                    [t.pairwiseComparison, pairs.length],
                    [t.multiPartyComparison, multipleCount],
                    [t.conflict, conflictCount],
                    [t.nonConflict, nonConflictCount],
                  ].map(([label, value]) => (
                    <div key={label} className="bg-white px-2 py-2">
                      <div className="font-semibold text-slate-800">{value}</div>
                      <div className="mt-0.5 text-slate-500">{label}</div>
                    </div>
                  ))}
                </div>
                <div className="space-y-2">
                  {rows.map((item, index) => {
                    const requirements = list(item.requirements).map((req) =>
                      isRecord(req) ? req : {},
                    );
                    const conflict = isConflict(item);
                    const label = conflict ? t.conflict : t.nonConflict;
                    const reason =
                      text(item.initial_reason) ||
                      text(item.description) ||
                      text(item.final_reason);
                    return (
                      <Card key={index}>
                        <div className="flex items-start justify-between gap-3">
                          <span className="text-sm font-semibold text-slate-900">
                            {text(item.id) || `PAIR-${index + 1}`}
                          </span>
                          <span
                            className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-semibold ${
                              conflict
                                ? "bg-red-50 text-red-700"
                                : "bg-slate-100 text-slate-600"
                            }`}
                          >
                            {label}
                          </span>
                        </div>
                        <div className="mt-3 space-y-2">
                          {requirements.map((req, i) => (
                            <div key={i}>
                              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                                {text(req.id) || `REQ-${i + 1}`}
                              </div>
                              <p className="mt-0.5 text-sm leading-relaxed text-slate-700">
                                {text(req.text) || text(req.description)}
                              </p>
                            </div>
                          ))}
                        </div>
                        {reason && (
                          <div className="mt-3">
                            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                              {t.rationale}
                            </div>
                            <p className="mt-0.5 text-sm leading-relaxed text-slate-700">
                              {reason}
                            </p>
                          </div>
                        )}
                      </Card>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      </Section>
    </div>
  );
}

function ConflictReportView({ data }: { data: unknown[] }) {
  const { t } = useI18n();
  return (
    <div className="min-h-0 overflow-y-auto">
      <Section title="Conflict Report">
        <div className="space-y-2">
          {data.map((row, index) => {
            const item = isRecord(row) ? row : {};
            return (
              <Card key={index}>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-semibold text-slate-800">{text(item.id)}</span>
                  {text(item.status) && <Chip>{text(item.status)}</Chip>}
                  {text(item.meeting_id) && <Chip>{text(item.meeting_id)}</Chip>}
                </div>
                <p className="mt-2 text-sm leading-relaxed text-slate-700">{text(item.description)}</p>
                {text(item.recommended_resolution) && (
                  <p className="mt-2 rounded-control bg-emerald-50 p-2 text-sm leading-relaxed text-emerald-900">
                    {text(item.recommended_resolution)}
                  </p>
                )}
                {text(item.decision) && (
                  <p className="mt-2 text-sm leading-relaxed text-slate-800">{text(item.decision)}</p>
                )}
                {list(item.requirements).length > 0 && (
                  <div className="mt-2 space-y-1">
                    {list(item.requirements).map((req, i) => {
                      const r = isRecord(req) ? req : {};
                      return (
                        <p key={i} className="text-xs leading-relaxed text-slate-600">
                          <b>{text(r.id)}</b> {text(r.text)}
                        </p>
                      );
                    })}
                  </div>
                )}
                {list(item.resolution_options).length > 0 && (
                  <div className="mt-2 space-y-2">
                    {list(item.resolution_options).map((option, optionIndex) => {
                      const opt = isRecord(option) ? option : {};
                      return (
                        <div key={optionIndex} className="rounded-control bg-slate-50 p-2">
                          <div className="flex flex-wrap gap-1">
                            <Chip>{t.optionLabel(optionLabel(text(opt.option), optionIndex))}</Chip>
                            {opt.recommendation === true && <Chip>{t.suggestions}</Chip>}
                          </div>
                          <p className="mt-1 text-xs leading-relaxed text-slate-700">
                            {text(opt.description)}
                          </p>
                        </div>
                      );
                    })}
                  </div>
                )}
              </Card>
            );
          })}
        </div>
      </Section>
    </div>
  );
}

function IssuesView({ data }: { data: Record<string, unknown> }) {
  const { t } = useI18n();
  const groups = isRecord(data.meeting_issues) ? data.meeting_issues : data;
  return (
    <div className="min-h-0 overflow-y-auto">
      <Section title={t.issues} titleAlign="center" titleSize="sm">
        <div className="space-y-3">
          {Object.entries(groups).filter(([, value]) => Array.isArray(value)).map(([round, rows]) => (
            <div key={round}>
              <div className="mb-1 text-xs font-semibold uppercase text-slate-500">{round.toUpperCase()}</div>
              <div className="space-y-2">
                {list(rows).map((row, index) => {
                  const item = isRecord(row) ? row : {};
                  const participants = valueList(item.participants);
                  return (
                    <Card key={index}>
                      <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5">
                        <span className="text-sm font-semibold text-slate-800">
                          {[text(item.issue_id) || text(item.id), text(item.title)].filter(Boolean).join(" ")}
                        </span>
                        {text(item.proposed_by) && <Chip>{t.proposedBy}: {agentLabel(text(item.proposed_by))}</Chip>}
                        {text(item.category) && <Chip>{t.category}: {text(item.category)}</Chip>}
                        {text(item.discussion_mode) && <Chip>{t.mode}: {text(item.discussion_mode)}</Chip>}
                        {participants.length > 0 && (
                          <Chip>{t.participants}: {participants.map(agentLabel).join(", ")}</Chip>
                        )}
                      </div>
                    </Card>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      </Section>
    </div>
  );
}

function ElicitationView({ data }: { data: Record<string, unknown> }) {
  const { t } = useI18n();
  const plan = isRecord(data.plan) ? data.plan : {};
  const meeting = isRecord(data.meeting) ? data.meeting : {};
  const elicited = Array.isArray(data.elicited_reqts) ? data.elicited_reqts : [];
  const stopReason = text(data.elicitation_stop_reason);

  return (
    <div className="min-h-0 overflow-y-auto">
      <Section title={t.elicitationStatus}>
        <div className="flex flex-wrap gap-2 text-xs text-slate-600">
          <span className="rounded-full border border-gray-200 bg-white px-2 py-1">
            {t.roundLimit}: {String(plan.round_limit ?? t.notConfigured)}
          </span>
          <span className="rounded-full border border-gray-200 bg-white px-2 py-1">
            {t.mode}: {text(plan.mode) || t.notRecorded}
          </span>
          <span className="rounded-full border border-emerald-200 bg-emerald-50 px-2 py-1 text-emerald-800">
            {t.finish}: {stopReasonLabel(stopReason, t)}
          </span>
        </div>
      </Section>

      <Section title={t.elicitationRecords}>
        {Object.keys(meeting).length === 0 ? (
          <p className="text-sm text-slate-500">{t.noElicitationRecords}</p>
        ) : (
          <div className="space-y-3">
            {Object.entries(meeting).map(([roundKey, rows]) => (
              <div key={roundKey}>
                <div className="mb-1 text-xs font-medium text-slate-500">
                  {roundKey.toUpperCase()}
                </div>
                <div className="space-y-2">
                  {(Array.isArray(rows) ? rows : []).map((row, index) => (
                    <div
                      key={`${roundKey}-${index}`}
                      className="rounded-control border border-gray-200 bg-white p-3"
                    >
                      {isRecord(row) &&
                        Object.entries(row)
                          .filter(([key]) => key !== "id")
                          .map(([speaker, value]) => (
                            <div key={speaker} className="mb-2 last:mb-0">
                              <div className="text-xs font-semibold text-slate-500">
                                {agentLabel(speaker)}
                              </div>
                              <div className="mt-0.5 whitespace-pre-wrap text-sm leading-relaxed text-slate-800">
                                {String(value ?? "")}
                              </div>
                            </div>
                          ))}
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </Section>

      <Section title={t.candidateRequirements}>
        {elicited.length === 0 ? (
          <p className="text-sm text-slate-500">{t.noCandidateRequirements}</p>
        ) : (
          <div className="space-y-2">
            {elicited.map((row, index) => (
              <div
                key={index}
                className="rounded-control border border-gray-200 bg-white p-3 text-sm text-slate-800"
              >
                {isRecord(row) ? text(row.text) || JSON.stringify(row) : String(row)}
              </div>
            ))}
          </div>
        )}
      </Section>
    </div>
  );
}

function valueList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.map((item) => String(item)).filter(Boolean)
    : [];
}

async function fetchMeetingMomMeta(projectId: string, meetingId: string) {
  const paths = [
    `artifact/MoM/${meetingId}.md`,
    `results/MoM/${meetingId}.md`,
    `results/MoM/${meetingId}.html`,
    `artifact/MoM/${meetingId}.html`,
  ];
  for (const path of paths) {
    try {
      const file = await fetchFile(projectId, path);
      if (file.type === "html") {
        return {
          title: firstHtmlHeading(file.content),
          summary: htmlSectionText(file.content, "摘要"),
          decision: htmlSectionText(file.content, "決議"),
        };
      }
      return {
        title: firstMarkdownHeading(file.content),
        summary: markdownSectionText(file.content, "摘要"),
        decision: markdownSectionText(file.content, "決議"),
      };
    } catch {
      continue;
    }
  }
  return { title: "", summary: "" };
}

function useMeetingMomMeta(projectId: string | null, meetingId: string) {
  return useQuery({
    queryKey: ["formal-meeting-mom-meta", projectId, meetingId],
    queryFn: () => fetchMeetingMomMeta(projectId!, meetingId),
    enabled: !!projectId && !!meetingId,
    retry: false,
  });
}

function MeetingHeading({
  meetingId,
  title,
}: {
  meetingId: string;
  title: string;
}) {

  return (
    <>
      {meetingId}
      {title ? `：${title}` : ""}
    </>
  );
}

function MeetingSummarySection({ children }: { children: ReactNode }) {
  const { t } = useI18n();
  return (
    <div className="rounded-control border border-gray-200 bg-white px-3 py-2">
      <div className="text-xs font-semibold text-slate-500">{t.summary}</div>
      <div className="mt-1 whitespace-pre-wrap text-sm leading-relaxed text-slate-800">
        {children}
      </div>
    </div>
  );
}

function FormalMeetingIssueCard({
  projectId,
  issue,
  index,
}: {
  projectId: string | null;
  issue: Record<string, unknown>;
  index: number;
}) {
  const { t } = useI18n();
  const participants = valueList(issue.participants);
  const meetingId = text(issue.meeting_id) || `Meeting ${index + 1}`;
  const momMeta = useMeetingMomMeta(projectId, meetingId);
  const title =
    text(issue.title) ||
    text(issue.issue_title) ||
    text(issue.topic) ||
    momMeta.data?.title ||
    "";
  const summary =
    momMeta.data?.summary ||
    (isRecord(issue.resolution) ? text(issue.resolution.summary) : "") ||
    "";
  const resolutionText = isRecord(issue.resolution)
    ? momMeta.data?.decision ||
      text(issue.resolution.decision) ||
      text(issue.resolution.result) ||
      text(issue.resolution.summary) ||
      JSON.stringify(issue.resolution, null, 2)
    : "";

  return (
    <article className="rounded-control border border-gray-200 bg-white">
      <div className="border-b border-gray-100 px-3 py-2">
        <div className="text-sm font-semibold text-slate-800">
          <MeetingHeading meetingId={meetingId} title={title} />
        </div>
        <div className="mt-2 flex flex-wrap gap-1.5 text-[11px] text-slate-500">
          {text(issue.category) && (
            <span className="rounded-full bg-slate-100 px-2 py-0.5">
              {text(issue.category)}
            </span>
          )}
          {text(issue.discussion_mode) && (
            <span className="rounded-full bg-slate-100 px-2 py-0.5">
              {text(issue.discussion_mode)}
            </span>
          )}
          {text(issue.proposed_by) && (
            <span className="rounded-full bg-slate-100 px-2 py-0.5">
              {t.proposedBy}: {agentLabel(text(issue.proposed_by))}
            </span>
          )}
          {participants.length > 0 && (
            <span className="rounded-full bg-slate-100 px-2 py-0.5">
              {t.participants}: {participants.map(agentLabel).join(", ")}
            </span>
          )}
        </div>
      </div>
      <div className="space-y-2 px-3 py-3">
        {summary && <MeetingSummarySection>{summary}</MeetingSummarySection>}
        {isRecord(issue.resolution) && (
          <div className="rounded-control border border-emerald-100 bg-emerald-50 px-3 py-2">
            <div className="text-xs font-semibold text-emerald-800">{t.resolution}</div>
            <div className="mt-1 whitespace-pre-wrap text-sm leading-relaxed text-emerald-900">
              {resolutionText}
            </div>
          </div>
        )}
        {!isRecord(issue.resolution) && (
          <p className="text-sm text-slate-500">{t.noResolutionSummary}</p>
        )}
      </div>
    </article>
  );
}

function FormalMeetingView({
  projectId,
  data,
}: {
  projectId: string | null;
  data: unknown;
}) {
  const { t } = useI18n();
  const issues = Array.isArray(data)
    ? data
    : isRecord(data) && Array.isArray(data.issues)
      ? data.issues
      : [];

  return (
    <div className="min-h-0 overflow-y-auto">
      <div className="px-4 py-2">
        {issues.length === 0 ? (
          <p className="text-sm text-slate-500">{t.noFormalMeetingIssues}</p>
        ) : (
          <div className="space-y-3">
            {issues.map((issue, index) => {
              if (!isRecord(issue)) return null;
              return (
                <FormalMeetingIssueCard
                  key={index}
                  projectId={projectId}
                  issue={issue}
                  index={index}
                />
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

export function JsonArtifactView({
  projectId,
  path,
  content,
  anchor,
}: {
  projectId: string | null;
  path: string;
  content: string;
  anchor?: string | null;
}) {
  let data: unknown;
  try {
    data = JSON.parse(content);
  } catch {
    return <JsonBlock data={content} />;
  }

  if (isRecord(data) && /elicitation_meeting\.json$/i.test(path)) {
    return <ElicitationView data={data} />;
  }
  if (
    /formal_meeting_r\d+\.json$/i.test(path) &&
    (isRecord(data) || Array.isArray(data))
  ) {
    return <FormalMeetingView projectId={projectId} data={data} />;
  }
  if (isRecord(data) && /requirements\.json$/i.test(path)) {
    return <RequirementsView data={data} anchor={anchor} />;
  }
  if (isRecord(data) && /feedback\.json$/i.test(path)) {
    return <FeedbackView projectId={projectId} data={data} />;
  }
  if (isRecord(data) && /scope\.json$/i.test(path)) {
    return <ScopeView data={data} />;
  }
  if (isRecord(data) && /project\.json$/i.test(path)) {
    return <ProjectView data={data} />;
  }
  if (Array.isArray(data) && /system_models\.json$/i.test(path)) {
    return <SystemModelsView data={data} />;
  }
  if (isRecord(data) && /result\.json$/i.test(path)) {
    return <ConflictPairsView data={data} />;
  }
  if (Array.isArray(data) && /conflict_report_v\d+\.json$/i.test(path)) {
    return <ConflictReportView data={data} />;
  }
  if (isRecord(data) && /issues\.json$/i.test(path)) {
    return <IssuesView data={data} />;
  }
  return (
    <div className="min-h-0 flex-1 overflow-auto p-4">
      <JsonBlock data={data} />
    </div>
  );
}
