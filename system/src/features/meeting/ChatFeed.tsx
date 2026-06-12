import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef } from "react";
import {
  AlertCircle,
  Bot,
  CheckCircle2,
  Clock3,
  User,
  UsersRound,
} from "lucide-react";
import { fetchFile } from "@/api/projects";
import { agentLabel } from "@/constants/agents";
import { useChatStore } from "@/stores/chatStore";
import { useUiStore } from "@/stores/uiStore";
import type { ChatMessage, FileTreeNode, RunState } from "@/types/api";
import { buildOutputFiles, resolvePreferredOutputPath, type OutputFile } from "@/utils/buildOutputFiles";
import { cn } from "@/utils/cn";

const ROLE_STYLES: Record<string, { bubble: string; avatar: string }> = {
  user: {
    bubble: "bg-slate-900 text-white",
    avatar: "bg-slate-800 text-white",
  },
  agent: {
    bubble: "bg-white border border-gray-200 text-slate-800 shadow-sm",
    avatar: "bg-violet-100 text-violet-700",
  },
  system: {
    bubble: "bg-slate-100 text-slate-600",
    avatar: "bg-slate-200 text-slate-600",
  },
};

const PREVIEW_LIMIT = 360;
const PREVIEW_TABLE_ROWS = 4;
const PREVIEW_TABLE_COLS = 4;

type HtmlPreviewBlock =
  | { type: "text"; text: string; weight: "heading" | "body" }
  | { type: "table"; rows: string[][]; truncated: boolean };

function stripHtml(value: string) {
  return value
    .replace(/<script[\s\S]*?<\/script>/gi, " ")
    .replace(/<style[\s\S]*?<\/style>/gi, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&#39;/g, "'")
    .replace(/&quot;/g, '"');
}

function displayText(value: string) {
  return value
    .replace(/^={0,}\s*Round\s+1\s*:\s*開會\s*={0,}$/i, "第一輪會議")
    .replace(/^={0,}\s*Round\s+2\s*:\s*開會\s*={0,}$/i, "第二輪會議");
}

function runActivityLabel(run: RunState | null) {
  if (!run) return "";
  if (run.status === "queued") return "Queued";
  if (run.status === "cancelling") return "Stopping";
  if (run.status === "waiting_for_human") return "Waiting";
  const stage = String(run.current_stage || "").trim();
  if (/meeting|會議|開會/i.test(stage)) return "Meeting";
  return "Running";
}

function RunActivityIndicator({ run }: { run: RunState | null }) {
  const active =
    !!run &&
    ["queued", "running", "waiting_for_human", "cancelling"].includes(run.status);
  if (!active) return null;
  const waiting = run.status === "waiting_for_human";
  const label = runActivityLabel(run);

  return (
    <div className="sticky bottom-2 z-10 mt-2 flex justify-center">
      <div
        className={cn(
          "activity-pill inline-flex max-w-full items-center rounded-full border bg-white/95 px-3 py-1.5 text-xs font-semibold shadow-sm backdrop-blur",
          waiting
            ? "border-amber-200 text-amber-800"
            : "border-emerald-200 text-emerald-800",
        )}
      >
        <span className="min-w-0 truncate">
          {label}
          <span className="activity-dots inline-flex w-5 justify-start">
            <span>.</span>
            <span>.</span>
            <span>.</span>
          </span>
        </span>
      </div>
    </div>
  );
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

function firstMarkdownHeading(value: string) {
  const match = /^\s*#\s+(.+?)\s*$/m.exec(value);
  if (!match) return "";
  return match[1]
    .replace(/<span\b[^>]*id=["'][^"']+["'][^>]*>\s*<\/span>/gi, " ")
    .replace(/\*\*(.*?)\*\*/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .trim();
}

function htmlPreviewText(value: string) {
  return stripHtml(
    value
      .replace(/<div\b[^>]*class=["'][^"']*\bdr-trace-modal\b[^"']*["'][^>]*>[\s\S]*?<\/div>\s*<\/div>/gi, " ")
      .replace(/<br\s*\/?>/gi, "\n")
      .replace(/<\/(h[1-6]|p|li|tr|table|ul|ol|blockquote|section|article|div)>/gi, "\n")
      .replace(/<hr\b[^>]*>/gi, "\n"),
  );
}

function stripHtmlHead(value: string) {
  return value.replace(/<head\b[^>]*>[\s\S]*?<\/head>/i, " ");
}

function stripHtmlAssets(value: string) {
  return value
    .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, " ")
    .replace(/<style\b[^>]*>[\s\S]*?<\/style>/gi, " ");
}

function stripDocumentHeading(value: string, outputPath?: string) {
  if (
    /^results\/(srs|design_rationale)\.html$/i.test(outputPath ?? "") ||
    /^results\/drafts\/draft_v\d+\.html$/i.test(outputPath ?? "") ||
    /^results\/MoM\/.+\.html$/i.test(outputPath ?? "") ||
    /^results\/report\/conflict_report(?:_v\d+)?\.html$/i.test(outputPath ?? "")
  ) {
    return value.replace(/<h1\b[^>]*>[\s\S]*?<\/h1>/i, " ");
  }
  return value;
}

function stripMarkdownDocumentHeading(value: string, outputPath?: string) {
  if (
    /^output\/(srs|design_rationale)\.md$/i.test(outputPath ?? "") ||
    /^artifact\/drafts\/draft_v\d+\.md$/i.test(outputPath ?? "")
  ) {
    return value.replace(/^\s*#\s+.+(?:\r?\n|$)/, "");
  }
  return value;
}

function cleanHtmlForPreview(content: string, outputPath?: string) {
  return stripDocumentHeading(stripHtmlAssets(stripHtmlHead(content)), outputPath);
}

function cleanMarkdownForPreview(content: string, outputPath?: string) {
  return stripMarkdownDocumentHeading(content, outputPath)
    .replace(/<span\b[^>]*id=["'][^"']+["'][^>]*>\s*<\/span>/gi, " ")
    .replace(/<!--[\s\S]*?-->/g, " ")
    .trim();
}

function isMarkdownPreview(type?: string, outputPath?: string) {
  return type === "md" || /\.md$/i.test(outputPath ?? "");
}

function previewSource(content: string, type?: string, outputPath?: string) {
  if (isMarkdownPreview(type, outputPath)) {
    return markdownPreviewText(cleanMarkdownForPreview(content, outputPath));
  }
  if (type !== "html") return content;
  return htmlPreviewText(cleanHtmlForPreview(content, outputPath));
}

function compactPreview(value: string) {
  return value
    .split(/\n+/)
    .map((line) => line.replace(/[ \t\r\f\v]+/g, " ").trim())
    .filter(Boolean)
    .join("\n")
    .trim();
}

function truncatePreview(value: string) {
  const text = compactPreview(value);
  if (text.length <= PREVIEW_LIMIT) return text;
  return `${text.slice(0, PREVIEW_LIMIT)}...`;
}

function tableRowsForPreview(table: Element): string[][] {
  return Array.from(table.querySelectorAll("tr"))
    .slice(0, PREVIEW_TABLE_ROWS)
    .map((row) =>
      Array.from(row.querySelectorAll("th,td"))
        .slice(0, PREVIEW_TABLE_COLS)
        .map((cell) => compactPreview(cell.textContent ?? "")),
    )
    .filter((row) => row.some(Boolean));
}

function htmlPreviewBlocks(content: string, outputPath?: string): HtmlPreviewBlock[] {
  if (typeof DOMParser === "undefined") return [];
  const doc = new DOMParser().parseFromString(
    cleanHtmlForPreview(content, outputPath),
    "text/html",
  );
  doc.querySelectorAll("script, style, .dr-trace-modal").forEach((node) => node.remove());
  const root = doc.querySelector(".md-body") ?? doc.body;
  const blocks: HtmlPreviewBlock[] = [];
  let textLength = 0;

  for (const child of Array.from(root.children)) {
    if (blocks.length >= 8 || textLength >= PREVIEW_LIMIT) break;
    const tag = child.tagName.toLowerCase();
    if (tag === "script" || tag === "style") continue;
    const table = tag === "table" ? child : child.querySelector("table");
    if (table) {
      const rows = tableRowsForPreview(table);
      if (rows.length) {
        blocks.push({
          type: "table",
          rows,
          truncated: table.querySelectorAll("tr").length > rows.length,
        });
      }
      continue;
    }

    const text = compactPreview(child.textContent ?? "");
    if (!text) continue;
    if (/^h[1-6]$/.test(tag)) {
      blocks.push({ type: "text", text, weight: "heading" });
      textLength += text.length;
      continue;
    }
    const remaining = PREVIEW_LIMIT - textLength;
    const clipped = text.length > remaining ? `${text.slice(0, Math.max(0, remaining))}...` : text;
    blocks.push({ type: "text", text: clipped, weight: "body" });
    textLength += clipped.length;
  }

  return blocks;
}

function markdownTableRows(lines: string[]): string[][] {
  return lines
    .filter((line) => !/^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line))
    .slice(0, PREVIEW_TABLE_ROWS)
    .map((line) =>
      line
        .trim()
        .replace(/^\|/, "")
        .replace(/\|$/, "")
        .split("|")
        .slice(0, PREVIEW_TABLE_COLS)
        .map((cell) => compactPreview(cell)),
    )
    .filter((row) => row.some(Boolean));
}

function markdownPreviewText(content: string) {
  return cleanMarkdownForPreview(content)
    .replace(/^\s*#{1,6}\s+/gm, "")
    .replace(/^\s*[-*+]\s+/gm, "")
    .replace(/\*\*(.*?)\*\*/g, "$1")
    .replace(/`([^`]+)`/g, "$1");
}

function markdownPreviewBlocks(content: string, outputPath?: string): HtmlPreviewBlock[] {
  const lines = cleanMarkdownForPreview(content, outputPath).split(/\r?\n/);
  const blocks: HtmlPreviewBlock[] = [];
  let textLength = 0;

  for (let i = 0; i < lines.length && blocks.length < 8 && textLength < PREVIEW_LIMIT; i += 1) {
    const line = lines[i].trim();
    if (!line) continue;

    if (line.includes("|")) {
      const tableLines = [];
      let j = i;
      while (j < lines.length && lines[j].includes("|") && lines[j].trim()) {
        tableLines.push(lines[j]);
        j += 1;
      }
      if (tableLines.length >= 2) {
        const rows = markdownTableRows(tableLines);
        if (rows.length) {
          blocks.push({ type: "table", rows, truncated: tableLines.length > rows.length });
          i = j - 1;
          continue;
        }
      }
    }

    const heading = /^(#{1,6})\s+(.+)$/.exec(line);
    const rawText = heading ? heading[2] : line.replace(/^\s*[-*+]\s+/, "");
    const text = compactPreview(
      rawText.replace(/\*\*(.*?)\*\*/g, "$1").replace(/`([^`]+)`/g, "$1"),
    );
    if (!text) continue;
    const remaining = PREVIEW_LIMIT - textLength;
    const clipped = text.length > remaining ? `${text.slice(0, Math.max(0, remaining))}...` : text;
    blocks.push({ type: "text", text: clipped, weight: heading ? "heading" : "body" });
    textLength += clipped.length;
  }

  return blocks;
}

function titleFromMessage(msg: ChatMessage) {
  return (
    msg.text
      .replace(/^已(整理|產生|生成|完成)\s*/g, "")
      .replace(/完成。?$/g, "")
      .trim() || "產出內容"
  );
}

function titleFromFileContent(content: string, type?: string, outputPath?: string) {
  if (/^(output\/srs\.md|results\/srs\.html)$/i.test(outputPath ?? "")) return "SRS";
  if (isMarkdownPreview(type, outputPath)) return firstMarkdownHeading(content);
  if (type === "html") return firstHtmlHeading(content);
  return "";
}

function isModelImagePath(path?: string) {
  return !!path && /^artifact\/models\/.+\.(png|svg)$/i.test(path);
}

function isSystemModelsPath(path?: string) {
  return !!path && /^artifact\/system_models\.json$/i.test(path);
}

function isMomPath(path?: string) {
  return !!path && /^results\/MoM\/.+\.html$/i.test(path);
}

function isSingleMomAction(msg: ChatMessage) {
  return msg.action === "generate_mom" && isMomPath(msg.outputPath);
}

function isFeedbackPath(path?: string) {
  return !!path && /^artifact\/feedback\.json$/i.test(path);
}

function isProjectPath(path?: string) {
  return !!path && /^artifact\/project\.json$/i.test(path);
}

function isRequirementsPath(path?: string) {
  return !!path && /^artifact\/requirements\.json$/i.test(path);
}

function isScopePath(path?: string) {
  return !!path && /^artifact\/scope\.json$/i.test(path);
}

function isElicitationMeetingPath(path?: string) {
  return !!path && /^artifact\/meeting\/elicitation_meeting\.json$/i.test(path);
}

function isConflictResultPath(path?: string) {
  return !!path && /^artifact\/result\.json$/i.test(path);
}

function parseJsonRecord(value: string): Record<string, unknown> | null {
  try {
    const parsed = JSON.parse(value) as unknown;
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      return parsed as Record<string, unknown>;
    }
  } catch {
    return null;
  }
  return null;
}

function jsonList(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function jsonRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function jsonText(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function stakeholderLabel(value: unknown): string {
  const item = jsonRecord(value);
  return jsonText(item.name) || String(value);
}

function ProjectCompactPreview({ data }: { data: Record<string, unknown> }) {
  const scenario = jsonText(data.scenario) || jsonText(data.rough_idea);
  const stakeholders = jsonList(data.stakeholders).slice(0, 4);
  return (
    <div className="space-y-3">
      {scenario && (
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Scenario
          </div>
          <p className="mt-1 text-sm font-semibold leading-relaxed text-slate-800">
            {scenario}
          </p>
        </div>
      )}
      {stakeholders.length > 0 && (
        <div className="space-y-1.5">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Stakeholders
          </div>
          <div className="grid grid-cols-2 gap-1.5">
            {stakeholders.map((row, index) => {
              const item = jsonRecord(row);
              const firstText = jsonList(item.text).map(String).find(Boolean);
              return (
                <div key={index} className="rounded-control border border-gray-200 bg-white px-2.5 py-2">
                  <div className="text-sm font-semibold text-slate-800">
                    {stakeholderLabel(row)}
                  </div>
                  {jsonText(item.type) && (
                    <div className="text-xs text-slate-500">{jsonText(item.type)}</div>
                  )}
                  {firstText && (
                    <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-slate-600">
                      {firstText}
                    </p>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

function RequirementsCompactPreview({ data }: { data: Record<string, unknown> }) {
  const urls = jsonList(data.URL).slice(0, 5);
  const reqs = jsonList(data.REQ).slice(0, 5);
  const rows = urls.length ? urls : reqs;
  if (!rows.length) return <div className="text-sm text-slate-500">無任何內容</div>;
  return (
    <div className="space-y-2">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
        {urls.length ? "User Requirements" : "Requirements"}
      </div>
      <div className="space-y-1.5">
        {rows.map((row, index) => {
          const item = jsonRecord(row);
          const stakeholder = jsonRecord(item.stakeholder);
          return (
            <div key={index} className="rounded-control border border-gray-200 bg-white px-2.5 py-2">
              <div className="mb-1 flex items-center gap-2">
                <span className="text-xs font-semibold text-slate-500">
                  {jsonText(item.id) || `#${index + 1}`}
                </span>
                {jsonText(stakeholder.name) && (
                  <span className="rounded-full bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-500">
                    {jsonText(stakeholder.name)}
                  </span>
                )}
              </div>
              <p className="line-clamp-3 text-sm leading-relaxed text-slate-700">
                {jsonText(item.text) || jsonText(item.description)}
              </p>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ScopeCompactPreview({ data }: { data: Record<string, unknown> }) {
  const sections = ([
    ["In Scope", jsonList(data.in_scope).slice(0, 4)],
    ["Out of Scope", jsonList(data.out_of_scope).slice(0, 2)],
  ] as Array<[string, unknown[]]>).filter(([, rows]) => rows.length > 0);
  if (!sections.length) return <div className="text-sm text-slate-500">無任何內容</div>;
  return (
    <div className="space-y-3">
      {sections.map(([title, rows]) => (
        <div key={title} className="space-y-1.5">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            {title}
          </div>
          {rows.map((row, index) => (
            <div key={index} className="rounded-control border border-gray-200 bg-white px-2.5 py-2">
              <p className="line-clamp-2 text-sm leading-relaxed text-slate-700">
                {String(row)}
              </p>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

function ArtifactJsonCompactPreview({
  path,
  data,
}: {
  path?: string;
  data: Record<string, unknown>;
}) {
  if (isElicitationMeetingPath(path)) return <ElicitationMeetingCompactPreview data={data} />;
  if (isConflictResultPath(path)) return <ConflictCompactPreview data={data} />;
  if (isFeedbackPath(path)) return <FeedbackCompactPreview data={data} />;
  if (isProjectPath(path)) return <ProjectCompactPreview data={data} />;
  if (isRequirementsPath(path)) return <RequirementsCompactPreview data={data} />;
  if (isScopePath(path)) return <ScopeCompactPreview data={data} />;
  return (
    <pre className="max-h-64 overflow-hidden whitespace-pre-wrap rounded-control bg-slate-50 p-2 text-xs leading-relaxed text-slate-600">
      {JSON.stringify(data, null, 2).slice(0, 800)}
    </pre>
  );
}

function ConflictCompactPreview({ data }: { data: Record<string, unknown> }) {
  const versions = Object.entries(data)
    .filter(([, value]) => jsonList(jsonRecord(value).pairs).length > 0)
    .sort(([a], [b]) => {
      const av = Number(/^v(\d+)$/i.exec(a)?.[1] ?? 0);
      const bv = Number(/^v(\d+)$/i.exec(b)?.[1] ?? 0);
      return av - bv;
    });
  const latest = versions.at(-1);
  const latestData = latest ? jsonRecord(latest[1]) : {};
  const latestPairs = jsonList(latestData.pairs).map(jsonRecord);
  const latestMultiples = jsonList(latestData.multiple).map(jsonRecord);
  const latestRows = [...latestPairs, ...latestMultiples];
  const totalPairs = latestPairs.length;
  const multipleCount = latestMultiples.length;
  const conflictCount = latestRows.filter((pair) =>
    /conflict/i.test(jsonText(pair.final_label) || jsonText(pair.initial_label)),
  ).length;
  const nonConflictCount = latestRows.length - conflictCount;

  return (
    <div className="overflow-hidden rounded-control border border-slate-200 bg-white">
      <div className="grid grid-cols-4 gap-px bg-slate-100 text-center text-xs">
        <div className="bg-white px-2 py-2">
          <div className="font-semibold text-slate-800">{totalPairs}</div>
          <div className="mt-0.5 text-slate-500">Pair</div>
        </div>
        <div className="bg-white px-2 py-2">
          <div className="font-semibold text-slate-800">{multipleCount}</div>
          <div className="mt-0.5 text-slate-500">Multiple</div>
        </div>
        <div className="bg-white px-2 py-2">
          <div className="font-semibold text-slate-800">{conflictCount}</div>
          <div className="mt-0.5 text-slate-500">衝突</div>
        </div>
        <div className="bg-white px-2 py-2">
          <div className="font-semibold text-slate-800">{nonConflictCount}</div>
          <div className="mt-0.5 text-slate-500">非衝突</div>
        </div>
      </div>
      {latestPairs.length > 0 && (
        <div className="space-y-1.5 px-3 py-2.5">
          {latestPairs.slice(0, 2).map((pair, index) => {
            const reqs = jsonList(pair.requirements).map(jsonRecord);
            const label = jsonText(pair.final_label) || jsonText(pair.initial_label) || "未標記";
            return (
              <div
                key={jsonText(pair.id) || index}
                className="rounded-control border border-slate-100 bg-slate-50 px-2.5 py-2"
              >
                <div className="mb-1 flex items-center justify-between gap-2">
                  <span className="text-xs font-semibold text-slate-700">
                    {jsonText(pair.id) || `PAIR-${index + 1}`}
                  </span>
                  <span className="rounded-full border border-slate-200 bg-white px-2 py-0.5 text-[11px] font-medium text-slate-600">
                    {label}
                  </span>
                </div>
                <p className="line-clamp-2 text-xs leading-relaxed text-slate-600">
                  {reqs.map((req) => jsonText(req.id)).filter(Boolean).join(" / ") || "需求配對"}
                </p>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function ElicitationMeetingCompactPreview({ data }: { data: Record<string, unknown> }) {
  const plan = jsonRecord(data.plan);
  const participants = jsonList(plan.participants).map((item) => agentLabel(String(item)));
  const mode = jsonText(plan.mode) || "未指定";
  const roundLimit = jsonText(plan.round_limit) || "1";
  const meeting = jsonRecord(data.meeting);
  const roundCount = Object.values(meeting).filter(Array.isArray).length;
  const requirementCount = jsonList(data.elicited_reqts).length;

  return (
    <div className="overflow-hidden rounded-control border border-slate-200 bg-white">
      <div className="grid grid-cols-3 gap-px bg-slate-100 text-center text-xs">
        <div className="bg-white px-2 py-2">
          <div className="font-semibold text-slate-800">{mode}</div>
          <div className="mt-0.5 text-slate-500">討論模式</div>
        </div>
        <div className="bg-white px-2 py-2">
          <div className="font-semibold text-slate-800">{roundCount || roundLimit}</div>
          <div className="mt-0.5 text-slate-500">回合</div>
        </div>
        <div className="bg-white px-2 py-2">
          <div className="font-semibold text-slate-800">{requirementCount}</div>
          <div className="mt-0.5 text-slate-500">擷取需求</div>
        </div>
      </div>
      {participants.length > 0 && (
        <div className="flex items-start gap-2 px-3 py-2.5">
          <UsersRound className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-400" />
          <div className="flex flex-wrap gap-1.5">
            {participants.map((name) => (
              <span
                key={name}
                className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-xs font-medium text-slate-600"
              >
                {name}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function FeedbackCompactPreview({ data }: { data: Record<string, unknown> }) {
  const sections: Array<[string, unknown[]]> = [
    ["Findings", jsonList(data.findings)],
    ["Constraints", jsonList(data.constraints)],
    ["Risks", jsonList(data.risks)],
    ["Recommendations", jsonList(data.recommendations)],
  ];
  const visibleSections = sections
    .map(([title, rows]) => [title, rows.slice(0, 2)] as const)
    .filter(([, rows]) => rows.length > 0)
    .slice(0, 3);

  if (!visibleSections.length) {
    return <div className="text-sm text-slate-500">無任何內容</div>;
  }

  return (
    <div className="space-y-3">
      {visibleSections.map(([title, rows]) => (
        <div key={title} className="space-y-1.5">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            {title}
          </div>
          {rows.map((row, index) => {
            const item = jsonRecord(row);
            const content = jsonText(item.text) || String(row);
            return (
              <div
                key={index}
                className="rounded-control border border-gray-200 bg-white px-2.5 py-2"
              >
                <p className="line-clamp-3 whitespace-pre-wrap text-sm leading-relaxed text-slate-700">
                  {content}
                </p>
              </div>
            );
          })}
        </div>
      ))}
    </div>
  );
}

function ModelImageTile({
  projectId,
  file,
}: {
  projectId: string;
  file: OutputFile;
}) {
  const setSelectedOutputPath = useUiStore((s) => s.setSelectedOutputPath);
  const image = useQuery({
    queryKey: ["chat-model-image", projectId, file.path],
    queryFn: () => fetchFile(projectId, file.path),
    enabled: !!projectId,
    retry: false,
  });

  const src =
    image.data?.content && image.data.type === "image"
      ? `data:${image.data.mime ?? "image/png"};base64,${image.data.content}`
      : null;

  return (
    <button
      type="button"
      className="min-w-0 overflow-hidden rounded-control border border-gray-200 bg-slate-50 text-left hover:border-slate-300 hover:bg-white"
      onClick={(event) => {
        event.stopPropagation();
        setSelectedOutputPath(file.path);
      }}
      title={file.label}
    >
      <div className="flex h-24 items-center justify-center bg-white">
        {src ? (
          <img
            src={src}
            alt={file.label}
            className="h-full w-full object-contain p-1.5"
          />
        ) : image.isLoading ? (
          <span className="text-xs text-slate-400">載入中...</span>
        ) : (
          <span className="px-2 text-center text-xs text-slate-400">無法預覽</span>
        )}
      </div>
      <div className="border-t border-gray-100 px-2 py-1.5 text-xs font-medium leading-snug text-slate-600">
        <span className="line-clamp-2 break-words">{file.label}</span>
      </div>
    </button>
  );
}

function ModelImagesPreview({
  projectId,
  modelImages,
}: {
  projectId: string;
  modelImages: OutputFile[];
}) {
  return (
    <div className="space-y-2">
      <div className="text-sm font-semibold text-slate-800">系統模型產生</div>
      <div className="grid grid-cols-2 gap-2">
        {modelImages.map((file) => (
          <ModelImageTile key={file.path} projectId={projectId} file={file} />
        ))}
      </div>
      <div className="text-xs font-medium text-slate-500">
        點選圖片查看完整內容
      </div>
    </div>
  );
}

function MomFileTile({ projectId, file }: { projectId: string | null; file: OutputFile }) {
  const setSelectedOutputPath = useUiStore((s) => s.setSelectedOutputPath);
  const mom = useQuery({
    queryKey: ["chat-mom-title", projectId, file.path],
    queryFn: () => fetchFile(projectId!, file.path),
    enabled: !!projectId,
    retry: false,
  });

  const title =
    mom.data?.type === "html" ? firstHtmlHeading(mom.data.content) : "";

  return (
    <button
      type="button"
      className="min-w-0 rounded-control border border-gray-200 bg-slate-50 px-3 py-2 text-left hover:border-slate-300 hover:bg-white"
      onClick={(event) => {
        event.stopPropagation();
        setSelectedOutputPath(file.path);
      }}
      title={file.label}
    >
      <span className="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-400">
        {file.label}
      </span>
      <span className="block whitespace-normal break-words text-sm font-semibold leading-snug text-slate-700">
        {title || (mom.isLoading ? "載入標題..." : "未命名會議")}
      </span>
    </button>
  );
}

function MomFilesPreview({
  projectId,
  msg,
  momFiles,
}: {
  projectId: string | null;
  msg: ChatMessage;
  momFiles: OutputFile[];
}) {
  return (
    <div className="space-y-2">
      <div className="text-sm font-semibold text-slate-800">{titleFromMessage(msg)}</div>
      <div className="grid grid-cols-2 gap-2">
        {momFiles.map((file) => (
          <MomFileTile key={file.path} projectId={projectId} file={file} />
        ))}
      </div>
      <div className="text-xs font-medium text-slate-500">
        點選 MoM 查看完整內容
      </div>
    </div>
  );
}

function HtmlStructuredPreview({ blocks }: { blocks: HtmlPreviewBlock[] }) {
  return (
    <div className="space-y-2 text-sm leading-relaxed text-slate-700">
      {blocks.map((block, index) => {
        if (block.type === "text") {
          return (
            <div
              key={index}
              className={cn(
                "whitespace-pre-wrap",
                block.weight === "heading" && "font-semibold text-slate-800",
              )}
            >
              {block.text}
            </div>
          );
        }
        return (
          <div
            key={index}
            className="overflow-hidden rounded-control border border-gray-200 bg-white"
          >
            <div className="max-w-full overflow-x-auto">
              <table className="w-full min-w-[360px] border-collapse text-xs">
                <tbody>
                  {block.rows.map((row, rowIndex) => (
                    <tr key={rowIndex} className={rowIndex === 0 ? "bg-slate-50" : undefined}>
                      {row.map((cell, cellIndex) => (
                        <td
                          key={cellIndex}
                          className={cn(
                            "border-b border-r border-gray-100 px-2 py-1.5 align-top leading-snug last:border-r-0",
                            rowIndex === 0 && "font-semibold text-slate-700",
                          )}
                        >
                          <span className="line-clamp-3 break-words">{cell}</span>
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {block.truncated && (
              <div className="border-t border-gray-100 px-2 py-1 text-xs text-slate-400">
                表格內容已截斷
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function OutputPreview({
  projectId,
  msg,
  modelImages,
  momFiles,
}: {
  projectId: string | null;
  msg: ChatMessage;
  modelImages: OutputFile[];
  momFiles: OutputFile[];
}) {
  const file = useQuery({
    queryKey: ["chat-preview", projectId, msg.outputPath],
    queryFn: () => fetchFile(projectId!, msg.outputPath!),
    enabled: !!projectId && !!msg.outputPath && !/\.(png|svg)$/i.test(msg.outputPath),
    retry: false,
  });

  const preview = useMemo(() => {
    if (!msg.outputPath) return msg.text;
    if (/\.(png|svg)$/i.test(msg.outputPath)) return msg.text;
    if (file.isLoading) return "載入內容預覽...";
    if (file.isError) return msg.text;
    const content = file.data?.content ?? "";
    const source = previewSource(content, file.data?.type, msg.outputPath);
    return truncatePreview(source) || msg.text;
  }, [file.data?.content, file.data?.type, file.isError, file.isLoading, msg]);
  const cardTitle = useMemo(() => {
    if (/^artifact\/meeting\/elicitation_meeting\.json$/i.test(msg.outputPath ?? "")) {
      return msg.action === "elicit_end" ? "需求擷取會議結束" : "需求擷取會議";
    }
    if (isMomPath(msg.outputPath)) return "MoM";
    if (/^artifact\/system_models\.json$/i.test(msg.outputPath ?? "")) return "系統模型產生";
    const draftVersion = /draft_v(\d+)/i.exec(msg.outputPath ?? "")?.[1];
    if (draftVersion) return `Draft v${draftVersion}`;
    const conflictReportVersion = /conflict_report_v(\d+)/i.exec(msg.outputPath ?? "")?.[1];
    if (conflictReportVersion) return `Conflict Report v${conflictReportVersion}`;
    if (file.isLoading || file.isError) return titleFromMessage(msg);
    const fileTitle = titleFromFileContent(
      file.data?.content ?? "",
      file.data?.type,
      msg.outputPath,
    );
    return fileTitle || titleFromMessage(msg);
  }, [file.data?.content, file.data?.type, file.isError, file.isLoading, msg]);
  const structuredBlocks = useMemo(() => {
    if (file.isLoading || file.isError) return [];
    const blocks = isMarkdownPreview(file.data?.type, msg.outputPath)
      ? markdownPreviewBlocks(file.data?.content ?? "", msg.outputPath)
      : file.data?.type === "html"
        ? htmlPreviewBlocks(file.data.content ?? "", msg.outputPath)
        : [];
    if (/^results\/report\/conflict_report_v\d+\.html$/i.test(msg.outputPath ?? "")) {
      return blocks.filter((block) => block.type !== "text" || block.text.trim() !== "完成");
    }
    return blocks;
  }, [file.data?.content, file.data?.type, file.isError, file.isLoading, msg.outputPath]);
  const jsonData = useMemo(() => {
    if (!/\.json$/i.test(msg.outputPath ?? "") || file.isLoading || file.isError) return null;
    return parseJsonRecord(file.data?.content ?? "");
  }, [file.data?.content, file.isError, file.isLoading, msg.outputPath]);

  if (
    projectId &&
    (isModelImagePath(msg.outputPath) || isSystemModelsPath(msg.outputPath)) &&
    modelImages.length > 0
  ) {
    return <ModelImagesPreview projectId={projectId} modelImages={modelImages} />;
  }
  if (isMomPath(msg.outputPath) && momFiles.length > 0) {
    return <MomFilesPreview projectId={projectId} msg={msg} momFiles={momFiles} />;
  }

  return (
    <div className="space-y-2">
      <div className="text-sm font-semibold text-slate-800">{cardTitle}</div>
      {jsonData ? (
        <ArtifactJsonCompactPreview path={msg.outputPath} data={jsonData} />
      ) : structuredBlocks.length ? (
        <HtmlStructuredPreview blocks={structuredBlocks} />
      ) : (
        <div className="whitespace-pre-wrap text-sm leading-relaxed text-slate-700">
          {preview}
        </div>
      )}
      {msg.outputPath && (
        <div className="text-xs font-medium text-slate-500 underline decoration-dotted underline-offset-2">
          查看完整內容
        </div>
      )}
    </div>
  );
}

function parseMeetingTask(text: string) {
  const cleaned = text.replace(/^Mediator\s*[:：]\s*/i, "").trim();
  const schedule = /^\s*((?:M|T)-\d+)\s*[｜|]\s*([^｜|]+)\s*[｜|]\s*([^｜|]+)\s*[｜|]\s*([^，｜|]+)，(\d+)\s*輪\s*[｜|]\s*(.+)$/.exec(cleaned);
  if (schedule) {
    return {
      id: schedule[1],
      title: schedule[2].trim(),
      action: schedule[3].trim(),
      mode: schedule[4].trim(),
      rounds: schedule[5].trim(),
      participants: schedule[6].split(/[、,，]/).map((item) => item.trim()).filter(Boolean),
    };
  }
  const start = /^\s*\[((?:M|T)-\d+)\]\s*開始[:：]\s*([^（]+)（([^，）]+)，([^，）]+)，預計\s*(\d+)\s*輪；參與[:：]\s*([^）]+)）/.exec(cleaned);
  if (!start) return null;
  return {
    id: start[1],
    title: start[2].trim(),
    action: start[3].trim(),
    mode: start[4].trim(),
    rounds: start[5].trim(),
    participants: start[6].split(/[、,，]/).map((item) => item.trim()).filter(Boolean),
  };
}

function parseMeetingResult(text: string) {
  const done = /^\s*討論完成[:：]\s*(\d+)\/(\d+)\s*輪，(\d+)\s*則發言，(\d+)\s*個\s*open question/i.exec(text);
  if (done) {
    return {
      kind: "done" as const,
      rounds: `${done[1]}/${done[2]}`,
      turns: done[3],
      openQuestions: done[4],
    };
  }
  const convergence = /^\s*收斂結果[:：]\s*([^｜|]+)[｜|](.+)$/.exec(text);
  if (!convergence) return null;
  return {
    kind: "convergence" as const,
    status: convergence[1].trim(),
    summary: convergence[2].trim(),
  };
}

function parseElicitPlan(text: string) {
  const mode = /(?:^|\|)\s*mode\s*[=:：]\s*([^|]+)/i.exec(text.trim())?.[1]?.trim();
  const match =
    /^elicit\s*plan\s*[:：]\s*(?:mode\s*[=:：]\s*[^|]+\|\s*)?participants\s*[:：]\s*([^|]+)\|\s*participants_order\s*[:：]\s*([^|]+)\|\s*goal\s*[:：]\s*([\s\S]+)$/i.exec(
      text.trim(),
    );
  if (!match) return null;
  return {
    participants: match[1].split(/[,，、]/).map((item) => item.trim()).filter(Boolean),
    order: match[2].split(/[;；]/).map((item) => item.trim()).filter(Boolean),
    goal: match[3].trim(),
    mode: mode || "simultaneous",
  };
}

function parseConflictPlan(text: string) {
  const match =
    /^需求衝突再審查\s*[:：]\s*mode\s*=\s*([^|]+)\|\s*participants\s*=\s*([^|]+)\|\s*participants_order\s*[:=]\s*([\s\S]+)$/i.exec(
      text.trim(),
    );
  if (!match) return null;
  return {
    mode: match[1].trim(),
    participants: match[2].split(/[,，、]/).map((item) => item.trim()).filter(Boolean),
    order: match[3].split(/[;；]/).map((item) => item.trim()).filter(Boolean),
  };
}

function PlanCard({
  title,
  subtitle,
  participants,
  order,
  goal,
  goalLabel = "目標",
  mode,
  plainOrder = false,
  goalFirst = false,
}: {
  title: string;
  subtitle?: string;
  participants: string[];
  order: string[];
  goal?: string;
  goalLabel?: string;
  mode?: string;
  plainOrder?: boolean;
  goalFirst?: boolean;
}) {
  const goalBlock = goal ? (
    <div>
      <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
        {goalLabel}
      </div>
      <p className="text-sm leading-relaxed text-slate-700">{goal}</p>
    </div>
  ) : null;

  return (
    <div className="space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-sm font-semibold text-slate-900">{title}</div>
          {subtitle && (
            <div className="mt-1 text-xs leading-relaxed text-slate-500">{subtitle}</div>
          )}
        </div>
        {mode && (
          <span className="shrink-0 rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-xs font-medium text-slate-600">
            {mode}
          </span>
        )}
      </div>
      <div className="space-y-2">
        {goalFirst && goalBlock}
        <div>
          <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
            參與者
          </div>
          <div className="flex flex-wrap gap-1.5">
            {participants.map((participant) => (
              <span
                key={participant}
                className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-xs font-medium text-slate-600"
              >
                {agentLabel(participant)}
              </span>
            ))}
          </div>
        </div>
        <div>
          <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
            發言順序
          </div>
          <div className="space-y-1">
            {order.map((item) => (
              <div key={item} className={cn(
                "text-xs font-medium text-slate-600",
                !plainOrder && "rounded-control border border-slate-100 bg-slate-50 px-2.5 py-1.5",
              )}>
                {item}
              </div>
            ))}
          </div>
        </div>
        {!goalFirst && goalBlock}
      </div>
    </div>
  );
}

function ElicitPlanCard({ msg }: { msg: ChatMessage }) {
  const plan = parseElicitPlan(msg.text);
  if (!plan) return null;
  return (
    <PlanCard
      title="Plan"
      participants={plan.participants}
      order={plan.order}
      goal={plan.goal}
      mode={plan.mode}
    />
  );
}

function ConflictPlanCard({ msg }: { msg: ChatMessage }) {
  const plan = parseConflictPlan(msg.text);
  if (!plan) return null;
  return (
    <PlanCard
      title="Plan"
      participants={plan.participants}
      order={plan.order}
      mode={plan.mode}
      plainOrder
    />
  );
}

function MeetingTaskCard({ msg }: { msg: ChatMessage }) {
  const task = parseMeetingTask(msg.text);
  if (!task) return null;
  const participantOrder = task.participants.map((participant) => agentLabel(participant)).join(" → ");
  return (
    <div className="space-y-3">
      <PlanCard
        title="Plan"
        participants={task.participants}
        order={participantOrder ? [participantOrder] : []}
        goal={task.title}
        goalLabel="議題"
        mode={task.mode}
        plainOrder
        goalFirst
      />
      <div className="flex flex-wrap gap-1.5">
        <span className="max-w-full break-all rounded-full border border-slate-200 bg-white px-2 py-0.5 text-xs text-slate-600">
          {task.action}
        </span>
        <span className="max-w-full break-words rounded-full border border-slate-200 bg-white px-2 py-0.5 text-xs text-slate-600">
          {task.rounds} 輪
        </span>
      </div>
      {msg.outputPath && (
        <div className="text-xs font-medium text-slate-500 underline decoration-dotted underline-offset-2">
          查看 Formal Meeting
        </div>
      )}
    </div>
  );
}

function MeetingResultCard({ msg }: { msg: ChatMessage }) {
  const result = parseMeetingResult(msg.text);
  if (!result) return null;
  return (
    <div className="space-y-2">
      {result.kind === "done" ? (
        <div className="grid grid-cols-3 gap-px overflow-hidden rounded-control border border-slate-200 bg-slate-100 text-center text-xs">
          <div className="bg-white px-2 py-2">
            <div className="font-semibold text-slate-800">{result.rounds}</div>
            <div className="mt-0.5 text-slate-500">討論輪次</div>
          </div>
          <div className="bg-white px-2 py-2">
            <div className="font-semibold text-slate-800">{result.turns}</div>
            <div className="mt-0.5 text-slate-500">發言</div>
          </div>
          <div className="bg-white px-2 py-2">
            <div className="font-semibold text-slate-800">{result.openQuestions}</div>
            <div className="mt-0.5 text-slate-500">Open question</div>
          </div>
        </div>
      ) : (
        <div className="rounded-control border border-slate-200 bg-white px-3 py-2.5">
          <div className="mb-1">
            <span className="rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-xs font-semibold text-emerald-800">
              {result.status}
            </span>
          </div>
          <p className="line-clamp-4 text-sm leading-relaxed text-slate-700">{result.summary}</p>
        </div>
      )}
      {msg.outputPath && (
        <div className="text-xs font-medium text-slate-500 underline decoration-dotted underline-offset-2">
          查看 MoM
        </div>
      )}
    </div>
  );
}

function parseHumanDecision(text: string) {
  const adopted = /^已採納方案[:：]\s*([\s\S]+)$/.exec(text.trim());
  if (adopted) {
    return {
      title: "人類裁決",
      label: "已採納方案",
      value: adopted[1].trim(),
    };
  }
  const custom = /^已提交裁決[:：]\s*([\s\S]+)$/.exec(text.trim());
  if (custom) {
    return {
      title: "人類裁決",
      label: "自訂決策",
      value: custom[1].trim(),
    };
  }
  if (/^已略過本次裁決/.test(text.trim())) {
    return {
      title: "人類裁決",
      label: "裁決結果",
      value: "略過",
    };
  }
  return null;
}

function parseHumanDecisionRequest(text: string) {
  const [title = "", description = "", optionBlock = ""] = text.split(/\n{2,}/);
  if (!title.trim()) return null;
  const options = optionBlock
    .replace(/^候選方案\s*/u, "")
    .split(/\n(?=[A-Z]\.\s)/)
    .map((item) => item.trim())
    .filter(Boolean)
    .map((item) => {
      const match = /^([A-Z])\.\s*([^\n]+)\n?([\s\S]*)$/.exec(item);
      return {
        letter: match?.[1] ?? "",
        title: match?.[2]?.trim() ?? item,
        description: match?.[3]?.trim() ?? "",
      };
    });
  return {
    title: title.trim(),
    description: description.trim(),
    options,
  };
}

function HumanDecisionRequestCard({ msg }: { msg: ChatMessage }) {
  const decision = parseHumanDecisionRequest(msg.text);
  if (!decision) return null;
  return (
    <div className="space-y-3">
      <div>
        <div className="text-sm font-semibold text-slate-900">{decision.title}</div>
        {decision.description && (
          <p className="mt-1 text-xs leading-relaxed text-slate-500">
            {decision.description}
          </p>
        )}
      </div>
      {decision.options.length > 0 && (
        <div className="space-y-2">
          {decision.options.map((option) => (
            <div
              key={`${option.letter}-${option.title}`}
              className="flex gap-2 rounded-control border border-slate-200 bg-slate-50 px-3 py-2.5"
            >
              {option.letter && (
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-white text-xs font-semibold text-slate-500">
                  {option.letter}
                </span>
              )}
              <div className="min-w-0">
                <div className="text-sm font-semibold leading-snug text-slate-800">
                  {option.title}
                </div>
                {option.description && (
                  <p className="mt-1 whitespace-pre-wrap text-xs leading-relaxed text-slate-500">
                    {option.description}
                  </p>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function HumanDecisionCard({ msg }: { msg: ChatMessage }) {
  const decision = parseHumanDecision(msg.text);
  if (!decision) return null;
  return (
    <div className="space-y-3">
      <div>
        <div className="text-sm font-semibold text-slate-900">{decision.title}</div>
        <div className="mt-1 text-xs leading-relaxed text-slate-500">
          {decision.label}
        </div>
      </div>
      <div className="rounded-control border border-slate-200 bg-slate-50 px-3 py-2.5">
        <p className="whitespace-pre-wrap text-sm font-semibold leading-relaxed text-slate-800">
          {decision.value}
        </p>
      </div>
    </div>
  );
}

function MomCard({ projectId, msg }: { projectId: string | null; msg: ChatMessage }) {
  const meetingId = /\/(R\d+-M\d+)\.html$/i.exec(msg.outputPath ?? "")?.[1] ?? "MoM";
  const mom = useQuery({
    queryKey: ["chat-single-mom-title", projectId, msg.outputPath],
    queryFn: () => fetchFile(projectId!, msg.outputPath!),
    enabled: !!projectId && !!msg.outputPath,
    retry: false,
  });
  const title =
    mom.data?.type === "html" ? firstHtmlHeading(mom.data.content) : "";
  return (
    <div className="space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-sm font-semibold text-slate-900">會議記錄</div>
          <div className="mt-1 text-xs leading-relaxed text-slate-500">
            {title || (mom.isLoading ? "載入標題..." : `${meetingId} 會議紀錄`)}
          </div>
        </div>
        <span className="shrink-0 rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-xs font-medium text-slate-600">
          {meetingId}
        </span>
      </div>
      <div className="text-xs font-medium text-slate-500 underline decoration-dotted underline-offset-2">
        查看 MoM
      </div>
    </div>
  );
}

function Bubble({
  msg,
  projectId,
  outputFiles,
  modelImages,
  momFiles,
}: {
  msg: ChatMessage;
  projectId: string | null;
  outputFiles: OutputFile[];
  modelImages: OutputFile[];
  momFiles: OutputFile[];
}) {
  const setSelectedOutputPath = useUiStore((s) => s.setSelectedOutputPath);
  const openOutput = () => {
    if (!msg.outputPath) return;
    setSelectedOutputPath(resolvePreferredOutputPath(msg.outputPath, outputFiles) ?? msg.outputPath);
  };

  if (msg.role === "system") {
    const failed = msg.status === "failed";
    const waiting = msg.status === "waiting";
    const running = msg.status === "running";
    return (
      <div className="my-4 flex items-center gap-2 text-xs text-slate-500">
        <div className="h-px flex-1 bg-gray-100" />
        <button
          type="button"
          disabled={!msg.outputPath}
          className={cn(
            "inline-flex max-w-full items-center gap-1.5 rounded-full border bg-white px-2.5 py-1",
            msg.outputPath && "cursor-pointer hover:border-slate-300 hover:text-slate-700",
            failed
              ? "border-red-200 text-red-700"
              : waiting
                ? "border-amber-200 text-amber-800"
                : running
                  ? "border-emerald-200 text-emerald-800"
                : "border-gray-200 text-slate-500",
          )}
          onClick={openOutput}
        >
          {failed ? (
            <AlertCircle className="h-3.5 w-3.5 text-red-500" />
          ) : waiting || running ? (
            <Clock3
              className={cn(
                "h-3.5 w-3.5",
                waiting ? "text-amber-500" : "text-emerald-500",
              )}
            />
          ) : (
            <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />
          )}
          <span className="whitespace-normal break-words text-center leading-snug">
            {displayText(msg.text)}
          </span>
        </button>
        <div className="h-px flex-1 bg-gray-100" />
      </div>
    );
  }

  const isUser = msg.role === "user";
  const isAction = msg.kind === "action";
  const isDecision = msg.kind === "decision";
  const styles = ROLE_STYLES[msg.role] ?? ROLE_STYLES.agent;
  const label = msg.label ?? (isUser ? agentLabel("user") : agentLabel("analyst"));
  const action =
    msg.action === "human_decision_request" || msg.action === "stakeholder_selection_request"
      ? ""
      : msg.action ?? (isAction ? msg.text.trim() : "");
  const modelPreviewGrid =
    !!projectId &&
    (isModelImagePath(msg.outputPath) || isSystemModelsPath(msg.outputPath)) &&
    modelImages.length > 0;
  const meetingTask = parseMeetingTask(msg.text);
  const meetingResult = parseMeetingResult(msg.text);
  const elicitPlan = parseElicitPlan(msg.text);
  const conflictPlan = parseConflictPlan(msg.text);
  const humanDecisionRequest = msg.action === "human_decision_request" || msg.action === "stakeholder_selection_request"
    ? parseHumanDecisionRequest(msg.text)
    : null;
  const humanDecision = !isUser ? parseHumanDecision(msg.text) : null;
  if (isDecision && humanDecisionRequest) {
    return (
      <div className="my-4 flex w-full justify-center">
        <div className="w-full max-w-xs rounded-control border border-gray-200 bg-white px-4 py-3 text-left shadow-sm">
          <div className="mb-2 inline-flex rounded-md bg-amber-50 px-2 py-0.5 text-[11px] font-semibold text-amber-700">
            您負責決議
          </div>
          <div className="text-sm font-semibold leading-snug text-slate-900">
            {humanDecisionRequest.title}
          </div>
        </div>
      </div>
    );
  }
  const singleMomAction = isSingleMomAction(msg);
  const momPreviewGrid = isMomPath(msg.outputPath) && momFiles.length > 0 && !meetingTask && !meetingResult && !singleMomAction;
  const bubbleSelectable = !!msg.outputPath && !modelPreviewGrid && !momPreviewGrid;
  const bubbleContent = elicitPlan ? (
    <ElicitPlanCard msg={msg} />
  ) : conflictPlan ? (
    <ConflictPlanCard msg={msg} />
  ) : meetingTask ? (
    <MeetingTaskCard msg={msg} />
  ) : meetingResult ? (
    <MeetingResultCard msg={msg} />
  ) : humanDecisionRequest ? (
    <HumanDecisionRequestCard msg={msg} />
  ) : humanDecision ? (
    <HumanDecisionCard msg={msg} />
  ) : singleMomAction ? (
    <MomCard projectId={projectId} msg={msg} />
  ) : msg.outputPath ? (
    <OutputPreview
      projectId={projectId}
      msg={msg}
      modelImages={modelImages}
      momFiles={momFiles}
    />
  ) : isAction && action ? (
    <div className="whitespace-pre-wrap">{msg.text}</div>
  ) : (
    <div className="whitespace-pre-wrap">{msg.text}</div>
  );

  return (
    <div
      className={cn(
        "mb-4 flex w-full gap-2.5",
        isUser ? "flex-row-reverse justify-start" : "justify-start",
      )}
    >
      <div className="flex w-20 shrink-0 flex-col items-center gap-1">
        <div className="w-full whitespace-nowrap text-center text-xs font-semibold leading-tight text-slate-600">
          {label}
        </div>
        <div
          className={cn(
            "flex h-9 w-9 items-center justify-center rounded-full",
            styles.avatar,
          )}
        >
          {isUser ? (
            <User className="h-4.5 w-4.5" />
          ) : (
            <Bot className="h-4.5 w-4.5" />
          )}
        </div>
      </div>
      <div className={cn("min-w-0 max-w-[85%] pt-6", isUser && "items-end")}>
        {!isUser && !isAction && !msg.outputPath && !elicitPlan && !conflictPlan && (action || isDecision) && (
          <div className="mb-1 flex flex-wrap items-center gap-1.5 text-xs text-slate-500">
            {action && (
              <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[10px] text-slate-500">
                {action}
              </span>
            )}
            {isDecision && (
              <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] text-amber-700">
                {msg.action === "stakeholder_selection_request"
                  ? "選擇利害關係人"
                  : msg.action === "human_decision_request"
                    ? "人類裁決"
                    : "decision"}
              </span>
            )}
          </div>
        )}
        <div
          className={cn(
            "block rounded-control border px-3.5 py-2.5 text-left text-sm leading-relaxed",
            styles.bubble,
            isUser && "border-slate-900",
            bubbleSelectable && "cursor-pointer hover:border-slate-300 hover:shadow",
          )}
          onClick={bubbleSelectable ? openOutput : undefined}
          role={bubbleSelectable ? "button" : undefined}
          tabIndex={bubbleSelectable ? 0 : undefined}
          onKeyDown={
            bubbleSelectable
              ? (event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    openOutput();
                  }
                }
              : undefined
          }
        >
          {bubbleContent}
        </div>
      </div>
    </div>
  );
}

interface ChatFeedProps {
  projectId: string | null;
  artifactItems?: FileTreeNode[];
  historyLoading?: boolean;
  activeRun?: RunState | null;
}

export function ChatFeed({
  projectId,
  artifactItems = [],
  historyLoading = false,
  activeRun = null,
}: ChatFeedProps) {
  const messages = useChatStore((s) => s.messages);
  const scrollTargetMessageId = useUiStore((s) => s.scrollTargetMessageId);
  const setScrollTargetMessageId = useUiStore((s) => s.setScrollTargetMessageId);
  const setActiveFlowMessageId = useUiStore((s) => s.setActiveFlowMessageId);
  const bottomRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const messageRefs = useRef<Record<string, HTMLDivElement | null>>({});

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length]);

  useEffect(() => {
    if (!scrollTargetMessageId) return;
    const target = messageRefs.current[scrollTargetMessageId];
    if (!target) return;
    target.scrollIntoView({ behavior: "smooth", block: "center" });
    setScrollTargetMessageId(null);
  }, [scrollTargetMessageId, setScrollTargetMessageId]);

  useEffect(() => {
    const root = scrollRef.current;
    if (!root) return;
    const nodeToId = new Map<Element, string>();
    messages.forEach((message) => {
      const node = messageRefs.current[message.id];
      if (node) nodeToId.set(node, message.id);
    });
    if (nodeToId.size === 0) return;

    const observer = new IntersectionObserver(
      (entries) => {
        const rootTop = root.getBoundingClientRect().top;
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .map((entry) => ({
            id: nodeToId.get(entry.target),
            distance: Math.abs(entry.boundingClientRect.top - rootTop - root.clientHeight * 0.28),
          }))
          .filter((entry): entry is { id: string; distance: number } => !!entry.id)
          .sort((a, b) => a.distance - b.distance);
        if (visible[0]) setActiveFlowMessageId(visible[0].id);
      },
      {
        root,
        rootMargin: "-18% 0px -58% 0px",
        threshold: [0, 0.15, 0.5, 1],
      },
    );

    nodeToId.forEach((_id, node) => observer.observe(node));
    return () => observer.disconnect();
  }, [messages, setActiveFlowMessageId]);

  const showEmpty = messages.length === 0 && !historyLoading;
  const outputFiles = useMemo(() => buildOutputFiles(artifactItems), [artifactItems]);
  const modelImages = useMemo(
    () =>
      outputFiles.filter(
        (file) => file.kind === "image" && isModelImagePath(file.path),
      ),
    [outputFiles],
  );
  const momFiles = useMemo(
    () =>
      outputFiles.filter(
        (file) => file.kind === "html" && isMomPath(file.path),
      ),
    [outputFiles],
  );

  const runActive =
    !!activeRun &&
    ["queued", "running", "waiting_for_human", "cancelling"].includes(
      activeRun.status,
    );

  return (
    <div ref={scrollRef} className={cn("chat-scroll h-full overflow-y-auto px-4 py-3", runActive && "pb-5")}>
      <div className={cn(
        "mx-auto w-full max-w-[720px]",
        (showEmpty || (historyLoading && messages.length === 0)) &&
          "flex h-full items-center justify-center",
      )}>
        {historyLoading && messages.length === 0 && (
          <div className="py-12 text-center text-lg font-semibold text-slate-400">
            載入討論紀錄…
          </div>
        )}
        {showEmpty && (
          <div className="text-center">
            <p className="text-sm font-medium text-slate-500">
              {projectId
                ? "已選擇既有專案，按下方「繼續」執行"
                : "請在下方輸入初步想法並按「執行」，Agent 團隊將協助您生成 SRS"}
            </p>
          </div>
        )}
        {messages.map((m) => (
          <div
            key={m.id}
            ref={(node) => {
              messageRefs.current[m.id] = node;
            }}
          >
            <Bubble
              msg={m}
              projectId={projectId}
              outputFiles={outputFiles}
              modelImages={modelImages}
              momFiles={momFiles}
            />
          </div>
        ))}
        <RunActivityIndicator run={activeRun} />
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
