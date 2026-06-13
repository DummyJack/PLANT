import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  AlertCircle,
  ArrowDown,
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
import { buildOutputFiles, findModelPair, resolvePreferredOutputPath, type OutputFile } from "@/utils/buildOutputFiles";
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
const DOCUMENT_PREVIEW_SECTIONS = 6;
const DOCUMENT_PREVIEW_BODY_PER_SECTION = 2;
const DOCUMENT_PREVIEW_BODY_LIMIT = 120;
const CHAT_SCROLL_KEY_PREFIX = "plant:chat-scroll:v2";

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
  if (run.status === "queued") return "Waiting";
  if (run.status === "cancelling") return "Stopping";
  if (run.status === "waiting_for_human") return "Waiting";
  const stage = String(run.current_stage || "").trim();
  if (/meeting|elicitation|會議|開會/i.test(stage)) return "Meeting";
  if (/draft|system_model|document|document_generation|SRS|software.requirements|DR|design.rationale|design_rationale|規格|草稿|模型|設計緣由/i.test(stage)) {
    return "Generating";
  }
  return "Running";
}

function chatScrollKey(projectId: string | null) {
  return `${CHAT_SCROLL_KEY_PREFIX}:${projectId || "new"}`;
}

function readSavedScrollTop(key: string): number | null {
  if (typeof window === "undefined") return null;
  const value = Number(window.sessionStorage.getItem(key));
  return Number.isFinite(value) && value >= 0 ? value : null;
}

function saveScrollTop(key: string, value: number) {
  if (typeof window === "undefined") return;
  window.sessionStorage.setItem(key, String(Math.max(0, Math.round(value))));
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

function stripMarkdownHtmlTags(value: string) {
  return value
    .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, " ")
    .replace(/<style\b[^>]*>[\s\S]*?<\/style>/gi, " ")
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<\/(h[1-6]|p|div|section|article|header|footer|blockquote|li|ul|ol|tr|table)>/gi, "\n")
    .replace(/<hr\b[^>]*>/gi, "\n---\n")
    .replace(/<li\b[^>]*>/gi, "- ")
    .replace(/<t[dh]\b[^>]*>/gi, " ")
    .replace(/<\/t[dh]>/gi, " | ")
    .replace(/<[^>\n]+>/g, "")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&#39;/g, "'")
    .replace(/&quot;/g, '"');
}

function cleanMarkdownForPreview(content: string, outputPath?: string) {
  return stripMarkdownHtmlTags(stripMarkdownDocumentHeading(content, outputPath))
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

function previewHeadingText(value: string) {
  return compactPreview(
    decodeHtmlEntities(value)
      .replace(/<span\b[^>]*id=["'][^"']+["'][^>]*>\s*<\/span>/gi, " ")
      .replace(/<[^>]+>/g, " ")
      .replace(/\*\*(.*?)\*\*/g, "$1")
      .replace(/`([^`]+)`/g, "$1"),
  );
}

function clipDocumentPreviewText(value: string) {
  const text = previewHeadingText(value.replace(/^\s*[-*+]\s+/, ""));
  if (text.length <= DOCUMENT_PREVIEW_BODY_LIMIT) return text;
  return `${text.slice(0, DOCUMENT_PREVIEW_BODY_LIMIT)}...`;
}

function markdownTablePreviewLines(lines: string[]) {
  return markdownTableRows(lines)
    .slice(1, 3)
    .map((row) => row.filter(Boolean).join(" / "))
    .filter(Boolean);
}

function shouldSkipDocumentPreviewHeading(heading: string, outputPath?: string) {
  return /^output\/design_rationale\.md$/i.test(outputPath ?? "") ||
    /^results\/design_rationale\.html$/i.test(outputPath ?? "")
    ? /^Topology$/i.test(heading.trim())
    : false;
}

function documentPreviewBlocksFromMarkdownLines(
  lines: string[],
  outputPath?: string,
): HtmlPreviewBlock[] {
  const blocks: HtmlPreviewBlock[] = [];
  let sectionCount = 0;
  let bodyCount = 0;
  let currentHeading = "";
  let skippingSection = false;

  for (let i = 0; i < lines.length && sectionCount < DOCUMENT_PREVIEW_SECTIONS; i += 1) {
    const line = lines[i].trim();
    if (!line) continue;

    const heading = /^(#{1,6})\s+(.+)$/.exec(line);
    if (heading) {
      currentHeading = previewHeadingText(heading[2]);
      if (!currentHeading) continue;
      skippingSection = shouldSkipDocumentPreviewHeading(currentHeading, outputPath);
      if (skippingSection) {
        bodyCount = 0;
        continue;
      }
      blocks.push({ type: "text", text: currentHeading, weight: "heading" });
      sectionCount += 1;
      bodyCount = 0;
      continue;
    }

    if (skippingSection || !currentHeading || bodyCount >= DOCUMENT_PREVIEW_BODY_PER_SECTION) continue;

    if (line.includes("|")) {
      const tableLines = [];
      let j = i;
      while (j < lines.length && lines[j].includes("|") && lines[j].trim()) {
        tableLines.push(lines[j]);
        j += 1;
      }
      if (tableLines.length >= 2) {
        for (const tableLine of markdownTablePreviewLines(tableLines)) {
          if (bodyCount >= DOCUMENT_PREVIEW_BODY_PER_SECTION) break;
          blocks.push({ type: "text", text: clipDocumentPreviewText(tableLine), weight: "body" });
          bodyCount += 1;
        }
        i = j - 1;
      }
      continue;
    }

    const text = clipDocumentPreviewText(line);
    if (!text || /^-{3,}$/.test(text)) continue;
    blocks.push({ type: "text", text, weight: "body" });
    bodyCount += 1;
  }

  return blocks;
}

function markdownDocumentPreviewBlocks(content: string, outputPath?: string) {
  return documentPreviewBlocksFromMarkdownLines(
    cleanMarkdownForPreview(content, outputPath).split(/\r?\n/),
    outputPath,
  );
}

function htmlDocumentPreviewBlocks(content: string, outputPath?: string): HtmlPreviewBlock[] {
  const cleaned = cleanHtmlForPreview(content, outputPath);
  if (typeof DOMParser === "undefined") {
    return documentPreviewBlocksFromMarkdownLines(
      htmlPreviewText(cleaned)
        .split(/\r?\n/)
        .map((line) => {
          const heading = /^(.+)$/.exec(line.trim());
          return heading ? line : line;
        }),
      outputPath,
    );
  }

  const doc = new DOMParser().parseFromString(cleaned, "text/html");
  doc.querySelectorAll("script, style, .dr-trace-modal").forEach((node) => node.remove());
  const root = doc.querySelector(".md-body") ?? doc.body;
  const lines: string[] = [];

  for (const child of Array.from(root.children)) {
    const tag = child.tagName.toLowerCase();
    if (/^h[1-6]$/.test(tag)) {
      lines.push(`# ${previewHeadingText(child.textContent ?? "")}`);
      continue;
    }
    const table = tag === "table" ? child : child.querySelector("table");
    if (table) {
      for (const row of tableRowsForPreview(table)) {
        lines.push(`| ${row.join(" | ")} |`);
      }
      continue;
    }
    const text = compactPreview(child.textContent ?? "");
    if (text) lines.push(text);
  }

  return documentPreviewBlocksFromMarkdownLines(lines, outputPath);
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
  return !!path && /^(?:results\/MoM\/.+\.html|artifact\/MoM\/R\d+-M\d+\.md)$/i.test(path);
}

function momRoundFromPath(path?: string) {
  return /(?:results\/MoM\/|artifact\/MoM\/)(R\d+)-M\d+\.(?:html|md)$/i.exec(path ?? "")?.[1]?.toUpperCase() ?? null;
}

function momMeetingIdFromPath(path?: string) {
  return /(?:results\/MoM\/|artifact\/MoM\/)(R\d+-M\d+)\.(?:html|md)$/i.exec(path ?? "")?.[1]?.toUpperCase() ?? null;
}

function momFilesForMessage(msg: ChatMessage, momFiles: OutputFile[]) {
  const round = momRoundFromPath(msg.outputPath);
  if (!round) return [];
  return momFiles.filter((file) => momRoundFromPath(file.path) === round);
}

function formalMeetingPathForMom(path?: string) {
  const round = /^R(\d+)$/i.exec(momRoundFromPath(path) ?? "")?.[1];
  return round ? `artifact/meeting/formal_meeting_r${round}.json` : null;
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

function isDraftPath(path?: string) {
  return !!path && /^(?:artifact\/drafts\/draft_v\d+\.md|results\/drafts\/draft_v\d+\.html)$/i.test(path);
}

function isSrsOrDesignRationalePath(path?: string) {
  return !!path && /^(?:output\/(?:srs|design_rationale)\.md|results\/(?:srs|design_rationale)\.html)$/i.test(path);
}

function isDocumentPreviewPath(path?: string) {
  return isDraftPath(path) || isSrsOrDesignRationalePath(path);
}

function isElicitationMeetingPath(path?: string) {
  return !!path && /^artifact\/meeting\/elicitation_meeting\.json$/i.test(path);
}

function isConflictResultPath(path?: string) {
  return !!path && /^artifact\/result\.json$/i.test(path);
}

function isHumanDecisionRequestMessage(msg?: ChatMessage) {
  return (
    msg?.action === "human_decision_request" ||
    msg?.action === "stakeholder_selection_request"
  );
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

function stakeholderStatementPreviewLine(value: unknown) {
  if (typeof value === "string") {
    const statement = value.trim();
    const match = /^([A-Z]+-\d+-\d+)\s*[:：]?\s*([\s\S]+)$/i.exec(statement);
    return {
      id: match?.[1] ?? "",
      text: match?.[2]?.trim() || statement,
    };
  }
  const item = jsonRecord(value);
  return {
    id: jsonText(item.id),
    text:
      jsonText(item.text) ||
      jsonText(item.content) ||
      jsonText(item.body) ||
      jsonText(item.statement),
  };
}

function ProjectCompactPreview({ data }: { data: Record<string, unknown> }) {
  const scenario = jsonText(data.scenario) || jsonText(data.rough_idea);
  const stakeholders = jsonList(data.stakeholders).slice(0, 4);
  return (
    <div className="space-y-3">
      {scenario && (
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            情境
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

function StakeholderStatementCompactPreview({ data }: { data: Record<string, unknown> }) {
  const stakeholders = jsonList(data.stakeholders).slice(0, 6);
  if (!stakeholders.length) return <div className="text-sm text-slate-500">無任何內容</div>;
  return (
    <div className="space-y-2">
      {stakeholders.map((row, index) => {
        const item = jsonRecord(row);
        const statement = jsonList(item.text)
          .map(stakeholderStatementPreviewLine)
          .find((value) => value.id || value.text);
        const statementId = statement?.id || jsonText(item.id) || `ST-${index + 1}-1`;
        const statementText = statement?.text || "";
        return (
          <div key={jsonText(item.id) || index} className="rounded-control bg-slate-50 px-2.5 py-2">
            <div className="mb-1 flex min-w-0 flex-wrap items-center gap-2">
              <span className="text-sm font-semibold leading-relaxed text-slate-800">
                {stakeholderLabel(row)}
              </span>
              <span className="text-xs font-semibold leading-relaxed text-slate-400">
                {statementId}
              </span>
            </div>
            {statementText && (
              <p className="line-clamp-3 whitespace-pre-wrap text-sm leading-relaxed text-slate-700">
                {statementText}
              </p>
            )}
          </div>
        );
      })}
    </div>
  );
}

function RequirementsCompactPreview({
  data,
  sectionTitle,
}: {
  data: Record<string, unknown>;
  sectionTitle?: string;
}) {
  const urls = jsonList(data.URL).slice(0, 5);
  const reqs = jsonList(data.REQ).slice(0, 5);
  const rows = sectionTitle ? reqs.length ? reqs : urls : urls.length ? urls : reqs;
  if (!rows.length) return <div className="text-sm text-slate-500">無任何內容</div>;
  return (
    <div className="space-y-2">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
        {sectionTitle || (urls.length ? "使用者需求" : "正式需求")}
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
    ["範圍內", jsonList(data.in_scope).slice(0, 4)],
    ["範圍外", jsonList(data.out_of_scope).slice(0, 2)],
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
          <div className="mt-0.5 text-slate-500">兩兩比對</div>
        </div>
        <div className="bg-white px-2 py-2">
          <div className="font-semibold text-slate-800">{multipleCount}</div>
          <div className="mt-0.5 text-slate-500">多方比對</div>
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

function parseMeetingRecords(content?: string): Record<string, unknown>[] {
  if (!content) return [];
  try {
    const parsed = JSON.parse(content) as unknown;
    if (Array.isArray(parsed)) return parsed.map(jsonRecord).filter((item) => Object.keys(item).length > 0);
    const record = jsonRecord(parsed);
    const rows = jsonList(record.issues);
    if (rows.length) return rows.map(jsonRecord).filter((item) => Object.keys(item).length > 0);
  } catch {
    return [];
  }
  return [];
}

type MeetingArtifactUpdates = {
  requirements: boolean;
  models: boolean;
  feedback: boolean;
};

function updateFlagsFromMeetingRecords(records: Record<string, unknown>[]): MeetingArtifactUpdates {
  const flags: MeetingArtifactUpdates = {
    requirements: false,
    models: false,
    feedback: false,
  };

  for (const record of records) {
    const resolution = jsonRecord(record.resolution);
    const artifactUpdates = jsonRecord(resolution.artifact_updates);
    if (Object.keys(jsonRecord(artifactUpdates.REQ)).length || Object.keys(jsonRecord(artifactUpdates.URL)).length) {
      flags.requirements = true;
    }
    if (Object.keys(jsonRecord(artifactUpdates.system_models)).length) {
      flags.models = true;
    }
    if (Object.keys(jsonRecord(artifactUpdates.feedback)).length) {
      flags.feedback = true;
    }

    for (const entry of jsonList(record.conversation).map(jsonRecord)) {
      const actions = jsonList(entry.actions).map((item) => String(item));
      const results = jsonList(jsonRecord(entry.response).issue_action_results).map(jsonRecord);
      for (const action of actions) {
        if (["update_requirement", "refine_requirement", "analyze_requirements"].includes(action)) {
          flags.requirements = true;
        }
        if (["system_modeling", "create_model", "update_model"].includes(action)) {
          flags.models = true;
        }
        if (["research_domain", "update_feedback"].includes(action)) {
          flags.feedback = true;
        }
      }
      for (const result of results) {
        const action = jsonText(result.action);
        if (["update_requirement", "refine_requirement", "analyze_requirements"].includes(action) || jsonList(result.REQ).length > 0) {
          flags.requirements = true;
        }
        if (["system_modeling", "create_model", "update_model"].includes(action) || jsonList(result.system_models).length > 0) {
          flags.models = true;
        }
        if (["research_domain", "update_feedback"].includes(action) || Object.keys(jsonRecord(result.feedback)).length > 0) {
          flags.feedback = true;
        }
      }
    }
  }

  return flags;
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
    ["發現", jsonList(data.findings)],
    ["限制", jsonList(data.constraints)],
    ["風險", jsonList(data.risks)],
    ["建議", jsonList(data.recommendations)],
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
  outputFiles,
}: {
  projectId: string;
  file: OutputFile;
  outputFiles: OutputFile[];
}) {
  const setSelectedOutputPath = useUiStore((s) => s.setSelectedOutputPath);
  const pairedModelPath = findModelPair(outputFiles, file).source?.path ?? file.path;
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
        setSelectedOutputPath(pairedModelPath);
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
  outputFiles,
  title = "系統模型產生",
}: {
  projectId: string;
  modelImages: OutputFile[];
  outputFiles: OutputFile[];
  title?: string;
}) {
  return (
    <div className="space-y-2">
      <div className="text-sm font-semibold text-slate-800">{title}</div>
      <div className="grid grid-cols-2 gap-2">
        {modelImages.map((file) => (
          <ModelImageTile key={file.path} projectId={projectId} file={file} outputFiles={outputFiles} />
        ))}
      </div>
      <div className="text-xs font-medium text-slate-500">
        點選圖片查看完整內容
      </div>
    </div>
  );
}

function JsonUpdatePreview({
  projectId,
  path,
  title,
  anchor,
  children,
}: {
  projectId: string | null;
  path: string;
  title: string;
  anchor?: string;
  children: (data: Record<string, unknown>) => ReactNode;
}) {
  const setSelectedOutputPath = useUiStore((s) => s.setSelectedOutputPath);
  const file = useQuery({
    queryKey: ["chat-update-preview", projectId, path],
    queryFn: () => fetchFile(projectId!, path),
    enabled: !!projectId,
    retry: false,
  });
  const data = useMemo(() => {
    if (file.isLoading || file.isError) return null;
    return parseJsonRecord(file.data?.content ?? "");
  }, [file.data?.content, file.isError, file.isLoading]);

  return (
    <button
      type="button"
      className="block w-full rounded-control px-0 py-0 text-left hover:bg-slate-50"
      onClick={(event) => {
        event.stopPropagation();
        setSelectedOutputPath(path, "manual", anchor ?? null);
      }}
    >
      <div className="mb-2 text-sm font-semibold text-slate-800">{title}</div>
      {data ? (
        children(data)
      ) : (
        <div className="text-sm text-slate-500">{file.isLoading ? "載入內容預覽..." : "無法預覽"}</div>
      )}
      <div className="mt-2 text-xs font-medium text-slate-500 underline decoration-dotted underline-offset-2">
        查看完整內容
      </div>
    </button>
  );
}

function ArtifactUpdateBubble({
  speaker,
  children,
}: {
  speaker: "analyst" | "modeler" | "expert";
  children: ReactNode;
}) {
  return (
    <div className="mb-4 flex w-full gap-2.5 justify-start">
      <div className="flex w-20 shrink-0 flex-col items-center gap-1">
        <div className="w-full whitespace-nowrap text-center text-xs font-semibold leading-tight text-slate-600">
          {agentLabel(speaker)}
        </div>
        <div className={cn("flex h-9 w-9 items-center justify-center rounded-full", ROLE_STYLES.agent.avatar)}>
          <Bot className="h-4.5 w-4.5" />
        </div>
      </div>
      <div className="min-w-0 max-w-[85%] pt-6">
        <div className={cn("block rounded-control border px-3.5 py-2.5 text-left text-sm leading-relaxed", ROLE_STYLES.agent.bubble)}>
          {children}
        </div>
      </div>
    </div>
  );
}

function MeetingArtifactUpdateBubbles({
  projectId,
  msg,
  momFiles,
  modelImages,
  outputFiles,
}: {
  projectId: string | null;
  msg: ChatMessage;
  momFiles: OutputFile[];
  modelImages: OutputFile[];
  outputFiles: OutputFile[];
}) {
  const meetingPath = formalMeetingPathForMom(msg.outputPath);
  const visibleMeetingIds = useMemo(
    () =>
      new Set(
        momFilesForMessage(msg, momFiles)
          .map((file) => momMeetingIdFromPath(file.path))
          .filter((id): id is string => !!id),
      ),
    [momFiles, msg],
  );
  const meeting = useQuery({
    queryKey: ["chat-mom-updates", projectId, meetingPath],
    queryFn: () => fetchFile(projectId!, meetingPath!),
    enabled: !!projectId && !!meetingPath,
    retry: false,
  });
  const updates = useMemo(() => {
    const records = parseMeetingRecords(meeting.data?.content).filter((record) => {
      const id = jsonText(record.meeting_id).toUpperCase();
      return !visibleMeetingIds.size || visibleMeetingIds.has(id);
    });
    return updateFlagsFromMeetingRecords(records);
  }, [meeting.data?.content, visibleMeetingIds]);

  if (!isMomPath(msg.outputPath) || (!updates.requirements && !updates.models && !updates.feedback)) return null;

  return (
    <>
      {updates.requirements && (
        <ArtifactUpdateBubble speaker="analyst">
          <JsonUpdatePreview
            projectId={projectId}
            path="artifact/requirements.json"
            title="需求更新"
            anchor="requirements-req"
          >
            {(data) => <RequirementsCompactPreview data={data} sectionTitle="正式需求" />}
          </JsonUpdatePreview>
        </ArtifactUpdateBubble>
      )}
      {updates.models && projectId && modelImages.length > 0 && (
        <ArtifactUpdateBubble speaker="modeler">
          <ModelImagesPreview
            projectId={projectId}
            modelImages={modelImages}
            outputFiles={outputFiles}
            title="系統模型更新"
          />
        </ArtifactUpdateBubble>
      )}
      {updates.feedback && (
        <ArtifactUpdateBubble speaker="expert">
          <JsonUpdatePreview
            projectId={projectId}
            path="artifact/feedback.json"
            title="領域研究更新"
            anchor="feedback-top"
          >
            {(data) => <FeedbackCompactPreview data={data} />}
          </JsonUpdatePreview>
        </ArtifactUpdateBubble>
      )}
    </>
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
    mom.data?.type === "html"
      ? firstHtmlHeading(mom.data.content)
      : isMarkdownPreview(mom.data?.type, file.path)
        ? firstMarkdownHeading(mom.data?.content ?? "")
        : "";

  return (
    <button
      type="button"
      className="w-fit min-w-48 max-w-80 rounded-control border border-gray-200 bg-slate-50 px-3 py-2 text-left hover:border-slate-300 hover:bg-white"
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
  const visibleMomFiles = momFilesForMessage(msg, momFiles);

  return (
    <div className="space-y-2">
      <div className="text-sm font-semibold text-slate-800">{titleFromMessage(msg)}</div>
      <div className={cn("inline-grid gap-2", visibleMomFiles.length > 1 && "grid-cols-2")}>
        {visibleMomFiles.map((file) => (
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
  outputFiles,
  modelImages,
  momFiles,
}: {
  projectId: string | null;
  msg: ChatMessage;
  outputFiles: OutputFile[];
  modelImages: OutputFile[];
  momFiles: OutputFile[];
}) {
  const previewPath = resolvePreferredOutputPath(msg.outputPath, outputFiles) ?? msg.outputPath;
  const stakeholderStatementCard =
    msg.action === "stakeholder_statement" ||
    msg.action === "stakeholder_statement_revision";
  const file = useQuery({
    queryKey: ["chat-preview", projectId, previewPath],
    queryFn: () => fetchFile(projectId!, previewPath!),
    enabled: !!projectId && !!previewPath && !/\.(png|svg)$/i.test(previewPath),
    retry: false,
  });

  const preview = useMemo(() => {
    if (!previewPath) return msg.text;
    if (/\.(png|svg)$/i.test(previewPath)) return msg.text;
    if (file.isLoading) return "載入內容預覽...";
    if (file.isError) return msg.text;
    const content = file.data?.content ?? "";
    const source = previewSource(content, file.data?.type, previewPath);
    return truncatePreview(source) || msg.text;
  }, [file.data?.content, file.data?.type, file.isError, file.isLoading, msg, previewPath]);
  const cardTitle = useMemo(() => {
    if (stakeholderStatementCard) return msg.text;
    if (/^artifact\/meeting\/elicitation_meeting\.json$/i.test(previewPath ?? "")) {
      return msg.action === "elicit_end" ? "需求擷取會議結束" : "需求擷取會議";
    }
    if (isMomPath(previewPath)) return "MoM";
    if (/^artifact\/system_models\.json$/i.test(previewPath ?? "")) return "系統模型產生";
    const draftVersion = /draft_v(\d+)/i.exec(previewPath ?? "")?.[1];
    if (draftVersion) return `Draft v${draftVersion}`;
    const conflictReportVersion = /conflict_report_v(\d+)/i.exec(previewPath ?? "")?.[1];
    if (conflictReportVersion) return `Conflict Report v${conflictReportVersion}`;
    if (file.isLoading || file.isError) return titleFromMessage(msg);
    const fileTitle = titleFromFileContent(
      file.data?.content ?? "",
      file.data?.type,
      previewPath,
    );
    return fileTitle || titleFromMessage(msg);
  }, [file.data?.content, file.data?.type, file.isError, file.isLoading, msg, previewPath, stakeholderStatementCard]);
  const structuredBlocks = useMemo(() => {
    if (file.isLoading || file.isError) return [];
    if (isDocumentPreviewPath(previewPath)) {
      const documentBlocks = isMarkdownPreview(file.data?.type, previewPath)
        ? markdownDocumentPreviewBlocks(file.data?.content ?? "", previewPath)
        : file.data?.type === "html"
          ? htmlDocumentPreviewBlocks(file.data.content ?? "", previewPath)
          : [];
      if (documentBlocks.length) return documentBlocks;
    }
    const blocks = isMarkdownPreview(file.data?.type, previewPath)
      ? markdownPreviewBlocks(file.data?.content ?? "", previewPath)
      : file.data?.type === "html"
        ? htmlPreviewBlocks(file.data.content ?? "", previewPath)
        : [];
    if (/^results\/report\/conflict_report_v\d+\.html$/i.test(previewPath ?? "")) {
      return blocks.filter((block) => block.type !== "text" || block.text.trim() !== "完成");
    }
    return blocks;
  }, [file.data?.content, file.data?.type, file.isError, file.isLoading, previewPath]);
  const jsonData = useMemo(() => {
    if (!/\.json$/i.test(previewPath ?? "") || file.isLoading || file.isError) return null;
    return parseJsonRecord(file.data?.content ?? "");
  }, [file.data?.content, file.isError, file.isLoading, previewPath]);

  const stakeholderStatementPreview =
    stakeholderStatementCard && jsonData
      ? <StakeholderStatementCompactPreview data={jsonData} />
      : null;

  if (
    projectId &&
    (isModelImagePath(msg.outputPath) || isSystemModelsPath(msg.outputPath)) &&
    modelImages.length > 0
  ) {
    return <ModelImagesPreview projectId={projectId} modelImages={modelImages} outputFiles={outputFiles} />;
  }
  if (isMomPath(msg.outputPath) && momFilesForMessage(msg, momFiles).length > 0) {
    return (
      <MomFilesPreview
        projectId={projectId}
        msg={msg}
        momFiles={momFiles}
      />
    );
  }

  return (
      <div className="space-y-2">
        <div className="text-sm font-semibold text-slate-800">{cardTitle}</div>
      {stakeholderStatementPreview ? (
        stakeholderStatementPreview
      ) : jsonData ? (
        <ArtifactJsonCompactPreview path={previewPath} data={jsonData} />
      ) : structuredBlocks.length ? (
        <HtmlStructuredPreview blocks={structuredBlocks} />
      ) : (
        <div className="whitespace-pre-wrap text-sm leading-relaxed text-slate-700">
          {preview}
        </div>
      )}
      {previewPath && (
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
          查看完整內容
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
            <div className="mt-0.5 text-slate-500">待釐清</div>
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

function SubmittedDecisionCard({ msg }: { msg: ChatMessage }) {
  const [title = "", ...rawRows] = msg.text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
  const issueMode = rawRows.some((line) => /^議題[:：]$/.test(line));
  const suggestionMode = rawRows.some((line) => /^建議[:：]$/.test(line));
  const rows = rawRows
    .filter((line) => !/^(選擇|建議|議題)[:：]$/.test(line))
    .map((line, index) => {
      if (suggestionMode) {
        const numbered = /^建議\s*(\d+)\s*[:：]\s*(.+)$/.exec(line);
        if (numbered) return `建議 ${numbered[1]}：${numbered[2].trim()}`;
        return `建議 ${index + 1}：${line}`;
      }
      if (!issueMode) return line;
      const numbered = /^議題\s*(\d+)\s*[:：]\s*(.+)$/.exec(line);
      if (numbered) return `議題 ${numbered[1]}：${numbered[2].trim()}`;
      return `議題 ${index + 1}：${line}`;
    });
  if (title !== "已提交決策") return null;
  if (!rows.length) {
    return <div className="leading-relaxed text-white">{title}</div>;
  }
  return (
    <div className="space-y-2">
      <div className="space-y-1">
        {rows.map((row) => (
          <div key={row} className="leading-relaxed text-white">
            {row}
          </div>
        ))}
      </div>
    </div>
  );
}

function shouldHideChatMessage(msg: ChatMessage) {
  return /^已提出\s*\d+\s*筆候選議題\s*$/u.test(msg.text.trim());
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
  const isStakeholderAgent =
    msg.kind === "speech" &&
    (
      msg.stage === "elicitation" ||
      msg.speaker === "stakeholder" ||
      (msg.role === "user" && !!msg.label && !["你", "您", "User"].includes(msg.label))
    );
  const isHumanUser = isUser && !isStakeholderAgent;
  const isAction = msg.kind === "action";
  const isDecision = msg.kind === "decision";
  const styles = isStakeholderAgent ? ROLE_STYLES.agent : ROLE_STYLES[msg.role] ?? ROLE_STYLES.agent;
  const label = msg.label ?? (isHumanUser ? agentLabel("user") : agentLabel("analyst"));
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
  const humanDecision = !isHumanUser ? parseHumanDecision(msg.text) : null;
  const submittedDecision = isHumanUser && isDecision ? <SubmittedDecisionCard msg={msg} /> : null;
  if (isDecision && humanDecisionRequest) {
    return (
      <div className="mb-5 mt-8 flex w-full justify-center">
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
  const momPreviewGrid =
    isMomPath(msg.outputPath) &&
    momFilesForMessage(msg, momFiles).length > 0 &&
    !meetingTask &&
    !meetingResult;
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
  ) : submittedDecision ? (
    submittedDecision
  ) : msg.outputPath ? (
    <OutputPreview
      projectId={projectId}
      msg={msg}
      outputFiles={outputFiles}
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
        isHumanUser ? "flex-row-reverse justify-start" : "justify-start",
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
          {isHumanUser ? (
            <User className="h-4.5 w-4.5" />
          ) : (
            <Bot className="h-4.5 w-4.5" />
          )}
        </div>
      </div>
      <div className={cn("min-w-0 max-w-[85%] pt-6", momPreviewGrid && "w-fit", isHumanUser && "items-end")}>
        {!isHumanUser && !isAction && !msg.outputPath && !elicitPlan && !conflictPlan && (action || isDecision) && (
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
            momPreviewGrid && "w-fit max-w-full",
            isHumanUser && "border-slate-900",
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
  const didInitialScrollRef = useRef(false);
  const didRestoreScrollRef = useRef(false);
  const forcedDecisionScrollMessageIdRef = useRef<string | null>(null);
  const scrollStorageKeyRef = useRef(chatScrollKey(projectId));
  const latestHydrationStateRef = useRef({
    historyLoading,
    messageCount: messages.length,
    projectId,
  });
  const [isNearBottom, setIsNearBottom] = useState(true);
  const [hasNewBelow, setHasNewBelow] = useState(false);
  latestHydrationStateRef.current = {
    historyLoading,
    messageCount: messages.length,
    projectId,
  };

  const scrollToLatest = useCallback((behavior: ScrollBehavior = "smooth") => {
    bottomRef.current?.scrollIntoView({ behavior, block: "end" });
    setHasNewBelow(false);
    setIsNearBottom(true);
  }, []);

  const updateScrollPosition = useCallback(() => {
    const root = scrollRef.current;
    if (!root) return;
    if (messages.length > 0 && didRestoreScrollRef.current) {
      saveScrollTop(scrollStorageKeyRef.current, root.scrollTop);
    }
    const distanceFromBottom = root.scrollHeight - root.scrollTop - root.clientHeight;
    const near = distanceFromBottom < 96;
    setIsNearBottom(near);
    if (near) setHasNewBelow(false);
  }, [messages.length]);

  useEffect(() => {
    const key = chatScrollKey(projectId);
    const previousKey = scrollStorageKeyRef.current;
    const root = scrollRef.current;
    if (root && messages.length > 0 && didRestoreScrollRef.current) {
      saveScrollTop(previousKey, root.scrollTop);
    }
    scrollStorageKeyRef.current = key;
    didInitialScrollRef.current = false;
    didRestoreScrollRef.current = false;
    forcedDecisionScrollMessageIdRef.current = null;
    setHasNewBelow(false);
    setIsNearBottom(true);
    return () => {
      const node = scrollRef.current;
      if (node && messages.length > 0 && didRestoreScrollRef.current) {
        saveScrollTop(key, node.scrollTop);
      }
    };
  }, [projectId, messages.length]);

  useEffect(() => {
    if (didRestoreScrollRef.current) return;
    const timer = window.setTimeout(() => {
      requestAnimationFrame(() => {
        if (didRestoreScrollRef.current) return;
        const latest = latestHydrationStateRef.current;
        if (latest.projectId !== projectId) return;
        if (latest.historyLoading && latest.messageCount === 0) return;
        const root = scrollRef.current;
        if (!root) return;
        const savedTop = readSavedScrollTop(scrollStorageKeyRef.current);
        if (savedTop != null) {
          root.scrollTop = Math.min(savedTop, Math.max(0, root.scrollHeight - root.clientHeight));
          updateScrollPosition();
        } else if (latest.messageCount > 0) {
          scrollToLatest("auto");
        }
        didRestoreScrollRef.current = true;
        didInitialScrollRef.current = true;
      });
    }, 0);
    return () => window.clearTimeout(timer);
  }, [historyLoading, messages.length, projectId, scrollToLatest, updateScrollPosition]);

  useEffect(() => {
    const saveCurrentPosition = () => {
      const root = scrollRef.current;
      if (!root || messages.length === 0 || !didRestoreScrollRef.current) return;
      saveScrollTop(scrollStorageKeyRef.current, root.scrollTop);
    };
    window.addEventListener("pagehide", saveCurrentPosition);
    return () => {
      saveCurrentPosition();
      window.removeEventListener("pagehide", saveCurrentPosition);
    };
  }, [messages.length]);

  useEffect(() => {
    if (!didRestoreScrollRef.current) return;
    const latestMessage = messages[messages.length - 1];
    const shouldForceLatest =
      isHumanDecisionRequestMessage(latestMessage) &&
      forcedDecisionScrollMessageIdRef.current !== latestMessage?.id;
    if (isNearBottom || shouldForceLatest) {
      const behavior: ScrollBehavior = didInitialScrollRef.current ? "smooth" : "auto";
      requestAnimationFrame(() => {
        if (shouldForceLatest) {
          forcedDecisionScrollMessageIdRef.current = latestMessage?.id ?? null;
        }
        scrollToLatest(behavior);
        didInitialScrollRef.current = true;
      });
      return;
    }
    didInitialScrollRef.current = true;
    if (messages.length > 0) setHasNewBelow(true);
  }, [messages, isNearBottom, scrollToLatest]);

  useEffect(() => {
    if (!scrollTargetMessageId) return;
    const target = messageRefs.current[scrollTargetMessageId];
    if (!target) return;
    target.scrollIntoView({ behavior: "smooth", block: "center" });
    requestAnimationFrame(updateScrollPosition);
    setScrollTargetMessageId(null);
  }, [scrollTargetMessageId, setScrollTargetMessageId, updateScrollPosition]);

  const visibleMessages = useMemo(
    () => messages.filter((message) => !shouldHideChatMessage(message)),
    [messages],
  );

  useEffect(() => {
    const root = scrollRef.current;
    if (!root) return;
    const nodeToId = new Map<Element, string>();
    visibleMessages.forEach((message) => {
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
  }, [setActiveFlowMessageId, visibleMessages]);

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
        (file) => (file.kind === "html" || file.kind === "markdown") && isMomPath(file.path),
      ),
    [outputFiles],
  );

  const runActive =
    !!activeRun &&
    ["queued", "running", "waiting_for_human", "cancelling"].includes(
      activeRun.status,
    );

  return (
    <div
      ref={scrollRef}
      onScroll={updateScrollPosition}
      className={cn("chat-scroll h-full overflow-y-auto px-4 py-3", runActive && "pb-5")}
    >
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
                ? "已選擇此專案，按「執行」可以繼續討論"
                : "請在下方輸入初步想法並按「執行」，Agent 團隊將協助您生成 SRS"}
            </p>
          </div>
        )}
        {visibleMessages.map((m) => (
          <div
            key={m.id}
            ref={(node) => {
              messageRefs.current[m.id] = node;
            }}
          >
            <MeetingArtifactUpdateBubbles
              projectId={projectId}
              msg={m}
              momFiles={momFiles}
              modelImages={modelImages}
              outputFiles={outputFiles}
            />
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
      {messages.length > 0 && (!isNearBottom || hasNewBelow) && (
        <div className="sticky bottom-3 z-20 -mt-10 flex justify-center pointer-events-none">
          <button
            type="button"
            title="查看最新內容"
            aria-label="查看最新內容"
            onClick={() => scrollToLatest()}
            className="pointer-events-auto inline-flex h-9 w-9 items-center justify-center rounded-full border border-gray-200 bg-white text-slate-950 shadow-sm transition hover:-translate-y-0.5 hover:border-gray-300 hover:shadow-md focus:outline-none focus:ring-2 focus:ring-slate-300"
          >
            <ArrowDown className="h-4.5 w-4.5" strokeWidth={1.45} />
          </button>
        </div>
      )}
    </div>
  );
}
