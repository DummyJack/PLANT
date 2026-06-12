import { useQuery } from "@tanstack/react-query";
import { fetchFile } from "@/api/projects";
import { agentLabel } from "@/constants/agents";
import type { ReactNode } from "react";

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

function text(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
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

function stopReasonLabel(reason: string): string {
  switch (reason) {
    case "judge_finish":
      return "收束投票通過";
    case "no_new_info":
      return "連續未產生新候選需求";
    case "max_turn":
    case "max_turns_reached":
      return "達到最大訪談輪次";
    case "":
      return "尚未記錄結束原因";
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
  const sourceIds = idList(item.source_ids ?? item.source_id ?? item.related_requirement_ids);
  if (sourceIds) return sourceIds;
  return source;
}

function stakeholderTypeLabel(value: string) {
  switch (value) {
    case "primary_user":
      return "核心使用者";
    case "system_owner":
      return "系統所有者與管理者";
    case "external_party":
      return "外部相關單位";
    default:
      return value;
  }
}

function stakeholderStatementText(value: unknown): string {
  if (typeof value === "string") return value.trim();
  if (!isRecord(value)) return String(value ?? "").trim();
  return (
    text(value.text) ||
    text(value.statement) ||
    text(value.content) ||
    text(value.description) ||
    text(value.requirement)
  );
}

function stakeholderStatementId(value: unknown): string {
  if (!isRecord(value)) return "";
  return text(value.id) || text(value.statement_id) || text(value.source_id);
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

function modelDescriptionText(value: string) {
  const purpose = /\*\*用途\*\*\s*[：:]\s*([\s\S]*?)(?=\n?\s*\*\*反映需求\*\*\s*[：:]|$)/.exec(value);
  if (purpose) return purpose[1].trim();
  return value;
}

function RequirementsView({ data }: { data: Record<string, unknown> }) {
  const urls = list(data.URL);
  const reqs = list(data.REQ);
  const renderRows = (rows: unknown[], kind: "URL" | "REQ") => {
    if (rows.length === 0) {
      return <p className="text-sm text-slate-500">無任何內容</p>;
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
              {kind === "REQ" && <th className="border-b px-3 py-2 text-left">Type</th>}
              <th className="border-b px-3 py-2 text-left">Description</th>
              {kind === "URL" && <th className="border-b px-3 py-2 text-left">Source</th>}
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
      <Section title="使用者需求" titleAlign="center" titleSize="sm">{renderRows(urls, "URL")}</Section>
      <Section title="正式需求" titleAlign="center" titleSize="sm">{renderRows(reqs, "REQ")}</Section>
    </div>
  );
}

function FeedbackView({ data }: { data: Record<string, unknown> }) {
  const sections: Array<[string, unknown[]]> = [
    ["Findings", list(data.findings)],
    ["Constraints", list(data.constraints)],
    ["Risks", list(data.risks)],
    ["Recommendations", list(data.recommendations)],
  ];
  return (
    <div className="min-h-0 overflow-y-auto">
      <ArtifactHeading border={false}>領域研究</ArtifactHeading>
      {sections.map(([title, rows]) => (
        <Section key={title} title={title}>
          {rows.length === 0 ? (
            <p className="text-sm text-slate-500">無任何內容</p>
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
                          相關需求
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
    </div>
  );
}

function ScopeView({ data }: { data: Record<string, unknown> }) {
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
      <ArtifactHeading border={false}>需求範圍</ArtifactHeading>
      <Section title="In Scope">{render(list(data.in_scope))}</Section>
      <Section title="Out of Scope">{render(list(data.out_of_scope))}</Section>
    </div>
  );
}

function ProjectView({ data }: { data: Record<string, unknown> }) {
  return (
    <div className="min-h-0 overflow-y-auto">
      <section className="border-b border-gray-100 px-4 py-3">
        <Card>
          <div className="text-xs font-semibold text-slate-500">Rough Idea</div>
          <p className="mt-1 text-sm text-slate-800">{text(data.rough_idea)}</p>
          <div className="mt-3 text-xs font-semibold text-slate-500">Scenario</div>
          <p className="mt-1 text-sm text-slate-800">{text(data.scenario)}</p>
        </Card>
      </section>
      <Section title="利害關係人" titleSize="sm">
        <div className="space-y-2">
          {list(data.stakeholders).map((row, index) => {
            const item = isRecord(row) ? row : {};
            const type = text(item.type);
            return (
              <Card key={index}>
                <div className="flex items-start justify-between gap-3">
                  <span className="text-sm font-semibold text-slate-800">{text(item.name)}</span>
                  {type && <Chip>{stakeholderTypeLabel(type)}</Chip>}
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
  return (
    <div className="min-h-0 overflow-y-auto">
      <Section title="系統模型" titleAlign="center" titleSize="sm">
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
                      相關需求
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
  const versions = Object.entries(data)
    .filter(([key, value]) => /^v\d+$/i.test(key) && isRecord(value))
    .sort(([a], [b]) => Number(a.slice(1)) - Number(b.slice(1)));
  const sections = versions.length ? versions : [["", data] as [string, unknown]];
  const isConflict = (item: Record<string, unknown>) =>
    /conflict/i.test(text(item.final_label) || text(item.initial_label));

  return (
    <div className="min-h-0 overflow-y-auto">
      <Section title="衝突辨識結果" titleAlign="center" titleSize="sm">
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
                    ["Pair", pairs.length],
                    ["Multiple", multipleCount],
                    ["衝突", conflictCount],
                    ["非衝突", nonConflictCount],
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
                    const label = conflict ? "衝突" : "非衝突";
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
                              判斷理由
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
                            {text(opt.option) && <Chip>Option {text(opt.option)}</Chip>}
                            {text(opt.strategy) && <Chip>{text(opt.strategy)}</Chip>}
                            {opt.recommendation === true && <Chip>recommended</Chip>}
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
  const groups = isRecord(data.meeting_issues) ? data.meeting_issues : data;
  return (
    <div className="min-h-0 overflow-y-auto">
      <Section title="Issues">
        <div className="space-y-3">
          {Object.entries(groups).filter(([, value]) => Array.isArray(value)).map(([round, rows]) => (
            <div key={round}>
              <div className="mb-1 text-xs font-semibold uppercase text-slate-500">{round}</div>
              <div className="space-y-2">
                {list(rows).map((row, index) => {
                  const item = isRecord(row) ? row : {};
                  return (
                    <Card key={index}>
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-sm font-semibold text-slate-800">{text(item.issue_id)}</span>
                        {text(item.importance) && <Chip>{text(item.importance)}</Chip>}
                        {text(item.proposed_by) && <Chip>proposed by {agentLabel(text(item.proposed_by))}</Chip>}
                      </div>
                      <p className="mt-1 text-sm font-medium text-slate-800">{text(item.title)}</p>
                      <p className="mt-2 text-sm leading-relaxed text-slate-700">{text(item.expect_outcome) || text(item.reason)}</p>
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
  const plan = isRecord(data.plan) ? data.plan : {};
  const meeting = isRecord(data.meeting) ? data.meeting : {};
  const elicited = Array.isArray(data.elicited_reqts) ? data.elicited_reqts : [];
  const stopReason = text(data.elicitation_stop_reason);

  return (
    <div className="min-h-0 overflow-y-auto">
      <Section title="訪談狀態">
        <div className="flex flex-wrap gap-2 text-xs text-slate-600">
          <span className="rounded-full border border-gray-200 bg-white px-2 py-1">
            輪次上限：{String(plan.round_limit ?? "未設定")}
          </span>
          <span className="rounded-full border border-gray-200 bg-white px-2 py-1">
            模式：{text(plan.mode) || "未記錄"}
          </span>
          <span className="rounded-full border border-emerald-200 bg-emerald-50 px-2 py-1 text-emerald-800">
            結束：{stopReasonLabel(stopReason)}
          </span>
        </div>
      </Section>

      <Section title="訪談紀錄">
        {Object.keys(meeting).length === 0 ? (
          <p className="text-sm text-slate-500">尚無訪談問答紀錄</p>
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

      <Section title="候選需求">
        {elicited.length === 0 ? (
          <p className="text-sm text-slate-500">尚無擷取候選需求</p>
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

function MeetingHeading({
  projectId,
  meetingId,
}: {
  projectId: string | null;
  meetingId: string;
}) {
  const mom = useQuery({
    queryKey: ["formal-meeting-title", projectId, meetingId],
    queryFn: () => fetchFile(projectId!, `results/MoM/${meetingId}.html`),
    enabled: !!projectId && !!meetingId,
    retry: false,
  });
  const title =
    mom.data?.type === "html" ? firstHtmlHeading(mom.data.content) : "";

  return (
    <>
      {meetingId}
      {title ? `：${title}` : ""}
    </>
  );
}

function FormalMeetingView({
  projectId,
  data,
}: {
  projectId: string | null;
  data: unknown;
}) {
  const issues = Array.isArray(data)
    ? data
    : isRecord(data) && Array.isArray(data.issues)
      ? data.issues
      : [];

  return (
    <div className="min-h-0 overflow-y-auto">
      <Section title="會議紀錄">
        {issues.length === 0 ? (
          <p className="text-sm text-slate-500">尚無正式會議議題</p>
        ) : (
          <div className="space-y-3">
            {issues.map((issue, index) => {
              if (!isRecord(issue)) return null;
              const participants = valueList(issue.participants);
              const meetingId = text(issue.meeting_id) || `Meeting ${index + 1}`;
              return (
                <article
                  key={index}
                  className="rounded-control border border-gray-200 bg-white"
                >
                  <div className="border-b border-gray-100 px-3 py-2">
                    <div className="text-sm font-semibold text-slate-800">
                      <MeetingHeading projectId={projectId} meetingId={meetingId} />
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
                          proposed by {agentLabel(text(issue.proposed_by))}
                        </span>
                      )}
                      {participants.length > 0 && (
                        <span className="rounded-full bg-slate-100 px-2 py-0.5">
                          Participants: {participants.map(agentLabel).join(", ")}
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="space-y-2 px-3 py-3">
                    {isRecord(issue.resolution) && (
                      <div className="rounded-control border border-emerald-100 bg-emerald-50 px-3 py-2">
                        <div className="text-xs font-semibold text-emerald-800">Resolution</div>
                        <div className="mt-1 whitespace-pre-wrap text-sm leading-relaxed text-emerald-900">
                          {text(issue.resolution.summary) ||
                            text(issue.resolution.decision) ||
                            JSON.stringify(issue.resolution, null, 2)}
                        </div>
                      </div>
                    )}
                    {!isRecord(issue.resolution) && (
                      <p className="text-sm text-slate-500">尚無決議摘要</p>
                    )}
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </Section>
    </div>
  );
}

export function JsonArtifactView({
  projectId,
  path,
  content,
}: {
  projectId: string | null;
  path: string;
  content: string;
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
    return <RequirementsView data={data} />;
  }
  if (isRecord(data) && /feedback\.json$/i.test(path)) {
    return <FeedbackView data={data} />;
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
