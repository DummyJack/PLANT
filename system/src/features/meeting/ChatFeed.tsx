import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircle,
  ArrowDown,
  Bot,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock3,
  User,
  UsersRound,
  X,
} from "lucide-react";
import { fetchFile } from "@/api/projects";
import { agentLabel } from "@/constants/agents";
import { UI_TEXT, useI18n } from "@/i18n";
import { useChatStore } from "@/stores/chatStore";
import { useUiStore } from "@/stores/uiStore";
import type { ChatMessage, FileTreeNode, RunState } from "@/types/api";
import { buildOutputFiles, findModelPair, resolvePreferredOutputPath, type OutputFile } from "@/utils/buildOutputFiles";
import { cn } from "@/utils/cn";
import { sortStakeholdersByType } from "@/utils/stakeholders";

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

function tx() {
  return UI_TEXT[useUiStore.getState().language];
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
  if (!isDesignRationalePreview(outputPath)) return false;
  return /^(?:Topology|Requirements Traceability Map)$/i.test(heading.trim());
}

function isDesignRationalePreview(outputPath?: string) {
  return /^(?:output|results)\/design_rationale\.(?:md|html)$/i.test(outputPath ?? "");
}

function shouldSkipDocumentPreviewLine(line: string, outputPath?: string) {
  if (!isDesignRationalePreview(outputPath)) return false;
  const text = previewHeadingText(line).replace(/:$/, "").trim();
  return /^Acceptance Criteria$/i.test(text);
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
  let skippingBodyUntilHeading = false;

  for (let i = 0; i < lines.length && sectionCount < DOCUMENT_PREVIEW_SECTIONS; i += 1) {
    const line = lines[i].trim();
    if (!line) continue;

    const heading = /^(#{1,6})\s+(.+)$/.exec(line);
    if (heading) {
      skippingBodyUntilHeading = false;
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

    if (shouldSkipDocumentPreviewLine(line, outputPath)) {
      skippingBodyUntilHeading = true;
      continue;
    }

    if (
      skippingSection ||
      skippingBodyUntilHeading ||
      !currentHeading ||
      bodyCount >= DOCUMENT_PREVIEW_BODY_PER_SECTION
    ) continue;

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
  if (msg.action === "init.generate_scope_review") return "需求範圍修正";
  return (
    msg.text
      .replace(/^已(整理|產生|生成|完成)\s*/g, "")
      .replace(/完成。?$/g, "")
      .trim() || "產出內容"
  );
}

function titleFromFileContent(
  content: string,
  type?: string,
  outputPath?: string,
  labels?: { designRationale: string; specification: string },
) {
  if (/^(output\/srs\.md|results\/srs\.html)$/i.test(outputPath ?? "")) {
    return labels?.specification ?? "規格化";
  }
  if (/^(output\/design_rationale\.md|results\/design_rationale\.html)$/i.test(outputPath ?? "")) {
    return labels?.designRationale ?? "設計緣由";
  }
  if (isMarkdownPreview(type, outputPath)) return firstMarkdownHeading(content);
  if (type === "html") return firstHtmlHeading(content);
  return "";
}

function markdownSectionText(content: string, heading: string) {
  const lines = cleanMarkdownForPreview(content).split(/\r?\n/);
  const headingPattern = new RegExp(`^\\s*#{1,6}\\s+${heading}\\s*$`);
  const nextHeadingPattern = /^\s*#{1,6}\s+\S+/;
  const start = lines.findIndex((line) => headingPattern.test(line.trim()));
  if (start < 0) return "";
  const section: string[] = [];
  for (let i = start + 1; i < lines.length; i += 1) {
    const line = lines[i].trim();
    if (nextHeadingPattern.test(line)) break;
    if (line) section.push(line.replace(/^\s*[-*+]\s+/, ""));
  }
  return compactPreview(section.join("\n"));
}

function htmlSectionText(content: string, heading: string) {
  if (typeof DOMParser === "undefined") return "";
  const doc = new DOMParser().parseFromString(cleanHtmlForPreview(content), "text/html");
  doc.querySelectorAll("script, style, .dr-trace-modal").forEach((node) => node.remove());
  const headings = Array.from(doc.querySelectorAll("h1,h2,h3,h4,h5,h6"));
  const target = headings.find((node) => compactPreview(node.textContent ?? "") === heading);
  if (!target) return "";
  const section: string[] = [];
  let node = target.nextElementSibling;
  while (node) {
    if (/^H[1-6]$/.test(node.tagName)) break;
    const text = compactPreview(node.textContent ?? "");
    if (text) section.push(text);
    node = node.nextElementSibling;
  }
  return compactPreview(section.join("\n"));
}

function momPreviewMeta(content: string, type?: string, outputPath?: string) {
  const markdown = isMarkdownPreview(type, outputPath);
  return {
    title: titleFromFileContent(content, type, outputPath),
    summary: markdown ? markdownSectionText(content, "摘要") : htmlSectionText(content, "摘要"),
    decision: markdown ? markdownSectionText(content, "決議") : htmlSectionText(content, "決議"),
  };
}

function isModelImagePath(path?: string) {
  return !!path && /^artifact\/models\/.+\.(png|svg)$/i.test(path);
}

function isSystemModelsPath(path?: string) {
  return !!path && /^artifact\/system_models\.json$/i.test(path);
}

function normalizeModelName(value: string) {
  return value
    .replace(/\.(?:png|svg|plantuml)$/i, "")
    .replace(/^artifact\/models\//i, "")
    .replace(/\s+/g, "")
    .trim()
    .toLowerCase();
}

function modelNamesFromMessage(text: string) {
  return text
    .split(/[、,，\n]/)
    .map((item) => normalizeModelName(item))
    .filter(Boolean)
    .filter((item) => !/^(?:系統模型|系統模型完成|系統模型已更新|完成|生成中|載入中)$/.test(item));
}

function modelImagesForMessage(msg: ChatMessage, modelImages: OutputFile[]) {
  if (!isSystemModelsPath(msg.outputPath)) return modelImages;
  const names = modelNamesFromMessage(msg.text);
  if (!names.length) return modelImages;
  const filtered = modelImages.filter((file) => {
    const label = normalizeModelName(file.label);
    const path = normalizeModelName(file.path.split("/").pop() ?? file.path);
    return names.some((name) => label.includes(name) || path.includes(name) || name.includes(label));
  });
  return filtered.length ? filtered : modelImages;
}

function isMomPath(path?: string) {
  return !!path && /^(?:results\/MoM\/R\d+-M\d+\.html|artifact\/MoM\/R\d+-M\d+\.md)$/i.test(path);
}

function momRoundFromPath(path?: string) {
  return /(?:results\/MoM\/|artifact\/MoM\/)(R\d+)-M\d+\.(?:html|md)$/i.exec(path ?? "")?.[1]?.toUpperCase() ?? null;
}

function momMeetingIdFromPath(path?: string) {
  return /(?:results\/MoM\/|artifact\/MoM\/)(R\d+-M\d+)\.(?:html|md)$/i.exec(path ?? "")?.[1]?.toUpperCase() ?? null;
}

function roundNumberFromId(round?: string | null) {
  const value = /^R(\d+)$/i.exec(String(round ?? "").trim())?.[1];
  return value ? Number(value) : null;
}

function momFilesForMessage(msg: ChatMessage, momFiles: OutputFile[]) {
  const meetingId = momMeetingIdFromPath(msg.outputPath);
  if (meetingId) {
    return momFiles.filter((file) => momMeetingIdFromPath(file.path) === meetingId);
  }
  const round = momRoundFromPath(msg.outputPath);
  if (!round) return [];
  return momFiles.filter((file) => momRoundFromPath(file.path) === round);
}

function formalMeetingRoundFromStage(msg?: ChatMessage) {
  if (!msg || msg.role !== "system" || msg.kind !== "stage" || msg.stage !== "formal_meeting") return null;
  const round = /^第\s*(\d+)\s*輪會議/u.exec(msg.text.trim())?.[1];
  return round ? `R${round}` : null;
}

function meetingNumberFromId(id?: string | null) {
  const number = /^M-(\d+)$/i.exec(String(id ?? "").trim())?.[1];
  return number ? Number(number) : null;
}

function taskNumberFromMeetingPath(path?: string) {
  const number = /(?:results\/MoM\/|artifact\/MoM\/)R\d+-M(\d+)\.(?:html|md)$/i.exec(path ?? "")?.[1];
  return number ? Number(number) : null;
}

function taskNumberFromDecision(msg: ChatMessage) {
  const values = [
    msg.decision?.issue?.meeting_id,
    msg.decision?.issue?.id,
    (msg.decision?.options as Record<string, unknown> | undefined)?.meeting_id,
    (msg.decision?.options as Record<string, unknown> | undefined)?.issue_id,
  ];
  for (const value of values) {
    const number = /R\d+-M(\d+)/i.exec(String(value ?? ""))?.[1];
    if (number) return Number(number);
  }
  return null;
}

function fallbackTaskNumberFromPosition(
  messageIndex: number,
  firstPlanIndex: number,
  momEntries: Array<{ message: ChatMessage; index: number }>,
) {
  if (messageIndex < firstPlanIndex) return null;
  const nextMom = momEntries
    .filter((entry) => entry.index > messageIndex)
    .sort((a, b) => a.index - b.index)[0];
  return nextMom ? taskNumberFromMeetingPath(nextMom.message.outputPath) : null;
}

function isFormalMeetingPlanMessage(msg: ChatMessage) {
  if (msg.stage !== "formal_meeting") return false;
  const task = parseMeetingTask(msg.text);
  return !!task && /^M-\d+$/i.test(task.id);
}

function isFormalMeetingMomMessage(msg: ChatMessage) {
  return msg.stage === "formal_meeting" && isMomPath(msg.outputPath);
}

function isFormalMeetingArtifactPath(path?: string) {
  return !!path && /^artifact\/meeting\/formal_meeting_r\d+\.json$/i.test(path);
}

function isFormalMeetingDisplayMessage(msg: ChatMessage) {
  return msg.stage === "formal_meeting" || isMomPath(msg.outputPath) || isFormalMeetingArtifactPath(msg.outputPath);
}

function isDocumentGenerationDisplayMessage(msg: ChatMessage) {
  return (
    (msg.role === "system" && msg.kind === "stage" && msg.stage === "document_generation") ||
    isSrsOrDesignRationalePath(msg.outputPath)
  );
}

function moveFormalMeetingBlocksBeforeDocumentGeneration(messages: ChatMessage[]) {
  const documentGenerationIndex = messages.findIndex(isDocumentGenerationDisplayMessage);
  if (documentGenerationIndex < 0) return messages;

  const beforeDocumentGeneration = messages.slice(0, documentGenerationIndex);
  const afterDocumentGeneration = messages.slice(documentGenerationIndex);
  const delayedMeetingMessages: ChatMessage[] = [];
  const remainingAfterDocumentGeneration: ChatMessage[] = [];

  for (let index = 0; index < afterDocumentGeneration.length; index += 1) {
    const message = afterDocumentGeneration[index];
    if (!isFormalMeetingDisplayMessage(message)) {
      remainingAfterDocumentGeneration.push(message);
      continue;
    }

    delayedMeetingMessages.push(message);
    let cursor = index + 1;
    while (cursor < afterDocumentGeneration.length) {
      const next = afterDocumentGeneration[cursor];
      if (next.role === "system" && next.kind === "stage") break;
      delayedMeetingMessages.push(next);
      cursor += 1;
    }
    index = cursor - 1;
  }

  if (delayedMeetingMessages.length === 0) return messages;
  return [
    ...beforeDocumentGeneration,
    ...delayedMeetingMessages,
    ...remainingAfterDocumentGeneration,
  ];
}

function arrangeMeetingPlanMomSegment(segment: ChatMessage[]) {
  const round = formalMeetingRoundFromStage(segment[0]);
  if (!round) return segment;
  const rest = segment.slice(1);
  const planEntries = rest
    .map((message, index) => ({ message, index, task: parseMeetingTask(message.text) }))
    .filter((entry): entry is { message: ChatMessage; index: number; task: NonNullable<ReturnType<typeof parseMeetingTask>> } =>
      isFormalMeetingPlanMessage(entry.message),
    );
  if (planEntries.length === 0) return segment;

  const matchingMomEntries = rest
    .map((message, index) => ({ message, index }))
    .filter((entry) => isFormalMeetingMomMessage(entry.message) && momRoundFromPath(entry.message.outputPath) === round);
  const roundNumber = roundNumberFromId(round);
  const matchingDraftEntries = rest
    .map((message, index) => ({ message, index }))
    .filter((entry) => isDraftPath(entry.message.outputPath) && draftVersionFromPath(entry.message.outputPath) === roundNumber);
  if (matchingMomEntries.length === 0 && matchingDraftEntries.length === 0) return segment;

  const consumed = new Set<string>();
  const arranged: ChatMessage[] = [segment[0]];
  const firstPlanIndex = Math.min(...planEntries.map((entry) => entry.index));

  rest.slice(0, firstPlanIndex).forEach((message) => {
    arranged.push(message);
    consumed.add(message.id);
  });

  for (const entry of planEntries) {
    const taskNumber = meetingNumberFromId(entry.task.id);
    if (!consumed.has(entry.message.id)) {
      arranged.push(entry.message);
      consumed.add(entry.message.id);
    }

    rest.forEach((message) => {
      if (consumed.has(message.id)) return;
      if (message.kind !== "decision") return;
      const explicitTaskNumber = taskNumberFromDecision(message);
      const fallbackTaskNumber = explicitTaskNumber ?? fallbackTaskNumberFromPosition(
        rest.findIndex((item) => item.id === message.id),
        firstPlanIndex,
        matchingMomEntries,
      );
      if (fallbackTaskNumber !== taskNumber) return;
      arranged.push(message);
      consumed.add(message.id);
    });

    matchingMomEntries.forEach(({ message }) => {
      if (consumed.has(message.id)) return;
      if (taskNumberFromMeetingPath(message.outputPath) !== taskNumber) return;
      arranged.push(message);
      consumed.add(message.id);
    });
  }

  matchingDraftEntries
    .sort((a, b) => a.index - b.index)
    .forEach(({ message }) => {
      if (consumed.has(message.id)) return;
      arranged.push(message);
      consumed.add(message.id);
    });

  rest.forEach((message) => {
    if (consumed.has(message.id)) return;
    arranged.push(message);
  });
  return arranged;
}

function arrangeMeetingPlanMomMessages(messages: ChatMessage[]) {
  const arranged: ChatMessage[] = [];
  for (let index = 0; index < messages.length; index += 1) {
    const message = messages[index];
    if (!formalMeetingRoundFromStage(message)) {
      arranged.push(message);
      continue;
    }

    const segment: ChatMessage[] = [message];
    let cursor = index + 1;
    while (
      cursor < messages.length &&
      !formalMeetingRoundFromStage(messages[cursor]) &&
      !(messages[cursor].role === "system" && messages[cursor].kind === "stage")
    ) {
      segment.push(messages[cursor]);
      cursor += 1;
    }
    if (segment.length === 1 && cursor < messages.length) {
      index = cursor - 1;
      continue;
    }
    arranged.push(...arrangeMeetingPlanMomSegment(segment));
    index = cursor - 1;
  }
  return arranged;
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

function draftVersionFromPath(path?: string) {
  return Number(/draft_v(\d+)/i.exec(path ?? "")?.[1] ?? 0);
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

function optionLetter(index: number) {
  return String.fromCharCode(65 + index);
}

function decisionKindLabel(kind?: string) {
  const t = tx();
  switch (kind) {
    case "stakeholder_selection":
      return t.selectStakeholders;
    case "requirements_review":
      return t.initialRequirementAnalysis;
    case "domain_research_review":
      return t.domainResearch;
    case "scope_review":
      return t.requirementScope;
    case "meeting_issue_proposal_review":
      return t.agentIssues;
    case "stakeholder_statement_review":
      return t.stakeholderStatements;
    case "human_decision":
      return t.humanDecision;
    default:
      return t.userIntervention;
  }
}

function decisionViewLabel() {
  return tx().viewContent;
}

function humanInterventionBadge(kind?: string) {
  const t = tx();
  if (kind === "human_decision") return t.humanDecision;
  if (kind === "stakeholder_selection") return t.humanSelection;
  return t.humanSuggestion;
}

function humanInterventionStatus(kind?: string, completed = false) {
  const t = tx();
  if (!completed) return t.waiting;
  switch (kind) {
    case "stakeholder_selection":
      return t.selectionComplete;
    case "requirements_review":
      return t.analysisComplete;
    case "domain_research_review":
      return t.revisionComplete;
    case "scope_review":
      return t.revisionComplete;
    case "meeting_issue_proposal_review":
      return t.selectionComplete;
    case "stakeholder_statement_review":
      return t.statementComplete;
    case "human_decision":
      return t.decisionComplete;
    default:
      return t.suggestionComplete;
  }
}

function decisionOptionRows(decision: ChatMessage["decision"], payload: Record<string, unknown>) {
  const options = decision?.options && typeof decision.options === "object"
    ? decision.options
    : {};
  const bestOptions = jsonList((options as Record<string, unknown>).best_options)
    .map((row, index) => {
      const item = jsonRecord(row);
      const id = jsonText(item.option_id) || optionLetter(index);
      return {
        id,
        label: tx().optionLabel(id || optionLetter(index)),
        title: jsonText(item.title),
      };
    });
  const byId = new Map(bestOptions.map((row) => [row.id, row]));

  const chosenOptions = jsonList(payload.chosen_options)
    .map((row, index) => {
      const item = jsonRecord(row);
      const id = jsonText(item.option_id) || optionLetter(index);
      const matched = byId.get(id);
      const title = jsonText(item.title) || matched?.title || "";
      return `${matched?.label || tx().optionLabel(id)}: ${title}`.replace(/:\s*$/, "");
    })
    .filter(Boolean);
  if (chosenOptions.length) return chosenOptions;

  const choices = jsonList(payload.choices)
    .map((choice, index) => {
      const id = jsonText(choice) || optionLetter(index);
      const matched = byId.get(id);
      return `${matched?.label || tx().optionLabel(id)}: ${matched?.title || ""}`.replace(/:\s*$/, "");
    })
    .filter(Boolean);
  if (choices.length) return choices;

  const decisionText = jsonText(payload.decision) || jsonText(payload.custom_decision);
  if (decisionText) return decisionText.split("\n").map((line) => line.trim()).filter(Boolean);
  return [];
}

function payloadRows(payload?: Record<string, unknown>, decision?: ChatMessage["decision"]) {
  const t = tx();
  if (!payload) return [];
  const stakeholders = sortStakeholdersByType(
    jsonList(payload.stakeholders),
    (row) => jsonRecord(row).type,
  )
    .map((row) => jsonRecord(row).name)
    .map((value) => jsonText(value))
    .filter(Boolean)
    .map((value) => `${t.humanSelection}: ${value}`);
  if (stakeholders.length) return stakeholders;

  const suggestions = jsonList(payload.suggestions)
    .map((row, index) => {
      const item = jsonRecord(row);
      const text = jsonText(item.text);
      const refs = jsonList(item.references)
        .map((ref) => jsonText(jsonRecord(ref).name))
        .filter(Boolean)
        .map((name) => `@${name}`)
        .join(" ");
      return [`${t.suggestions} ${index + 1}:`, refs, text].filter(Boolean).join(" ");
    })
    .filter(Boolean);
  if (suggestions.length) return suggestions;

  const customIssues = jsonList(payload.custom_issues)
    .map((row, index) => {
      const title = jsonText(jsonRecord(row).title);
      return `${t.issues} ${index + 1}: ${title}`;
    })
    .filter((row) => !/：\s*$/.test(row));
  if (customIssues.length) return customIssues;

  const decisionRows = decisionOptionRows(decision, payload);
  if (decisionRows.length) return decisionRows;
  const humanDecision = jsonText(payload.human_decision);
  if (humanDecision) return humanDecision.split("\n").map((line) => line.trim()).filter(Boolean);
  if (payload.skip_all_human_interventions === true) return [t.autoSkipFutureDecisions];
  if (payload.skipped === true) return [t.skippedThisDecision];
  if (payload.action === "approve") return [t.noAdditionalSuggestions];
  return [];
}

function isSkipAllHumanInterventionsPayload(payload?: Record<string, unknown>) {
  return payload?.skip_all_human_interventions === true;
}

function mentionTokensFromRows(rows: string[]) {
  return Array.from(
    new Set(
      rows.flatMap((row) =>
        Array.from(row.matchAll(/@([A-Za-z0-9_-]+)/g)).map((match) => match[1].trim()),
      ),
    ),
  ).filter(Boolean);
}

function stakeholderStatementReferences(decision?: ChatMessage["decision"]) {
  const options = decision?.options && typeof decision.options === "object"
    ? decision.options
    : {};
  return sortStakeholdersByType(
    jsonList(options.stakeholders),
    (row) => jsonRecord(row).type,
  ).flatMap((row, stakeholderIndex) => {
    const item = jsonRecord(row);
    const name = jsonText(item.name) || tx().stakeholderFallback(stakeholderIndex + 1);
    const lines = Array.isArray(item.text)
      ? item.text
      : jsonText(item.text)
        ? [item.text]
        : [];
    return lines.map((line, lineIndex) => {
      const lineRecord = jsonRecord(line);
      const id = jsonText(lineRecord.id) || `ST-${stakeholderIndex + 1}-${lineIndex + 1}`;
      const text = jsonText(lineRecord.text) || jsonText(line);
      return {
        id,
        title: name,
        text,
      };
    });
  });
}

function requirementReferences(decision?: ChatMessage["decision"]) {
  const options = decision?.options && typeof decision.options === "object"
    ? decision.options
    : {};
  return jsonList(options.requirements).map((row, index) => {
    const item = jsonRecord(row);
    return {
      id: jsonText(item.id) || `URL-${index + 1}`,
      title: jsonText(item.source_id) || jsonText(item.source),
      text: jsonText(item.text) || jsonText(item.description),
    };
  });
}

function domainResearchReferences(decision?: ChatMessage["decision"]) {
  const options = decision?.options && typeof decision.options === "object"
    ? decision.options
    : {};
  return jsonList(options.references).map((row, index) => {
    const item = jsonRecord(row);
    const name = jsonText(item.name) || `reference-${index + 1}`;
    return {
      id: name,
      title: "參考文件",
      text: "",
    };
  });
}

function suggestionMentionTokenSets(payload: Record<string, unknown> | undefined, rows: string[]) {
  const suggestions = jsonList(payload?.suggestions);
  if (suggestions.length) {
    return suggestions.map((row, index) => {
      const item = jsonRecord(row);
      const textTokens = mentionTokensFromRows([jsonText(item.text)]);
      const referenceTokens = jsonList(item.references)
        .map((ref) => jsonText(jsonRecord(ref).name))
        .filter(Boolean);
      return {
        index: index + 1,
        tokens: Array.from(new Set([...textTokens, ...referenceTokens])),
      };
    });
  }
  return rows.map((row, index) => ({
    index: index + 1,
    tokens: mentionTokensFromRows([row]),
  }));
}

function referencedMentionRows(
  decision: ChatMessage["decision"],
  rows: string[],
  payload?: Record<string, unknown>,
) {
  const tokens = mentionTokensFromRows(rows);
  if (!tokens.length) return [];
  const references = [
    ...stakeholderStatementReferences(decision),
    ...requirementReferences(decision),
    ...domainResearchReferences(decision),
  ];
  const uniqueReferences = Array.from(
    references.reduce((items, item) => {
      if (item.id && !items.has(item.id)) items.set(item.id, item);
      return items;
    }, new Map<string, { id: string; title: string; text: string }>()),
  ).map(([, item]) => item);
  const usage = new Map<string, number[]>();
  const suggestionTokenSets = suggestionMentionTokenSets(payload, rows);
  suggestionTokenSets.forEach(({ index, tokens: rowTokens }) => {
    const usesAll = rowTokens.some((token) => token.toLowerCase() === "all");
    const usedIds = usesAll ? uniqueReferences.map((item) => item.id) : rowTokens;
    usedIds.forEach((id) => {
      const current = usage.get(id) ?? [];
      if (!current.includes(index)) usage.set(id, [...current, index]);
    });
  });
  if (tokens.some((token) => token.toLowerCase() === "all")) {
    return uniqueReferences.map((item) => ({
      ...item,
      usedIn: usage.get(item.id) ?? [],
    }));
  }
  return tokens.map((token) => {
    const found = uniqueReferences.find((item) => item.id === token);
    return {
      id: token,
      title: found?.title ?? "",
      text: found?.text ?? "",
      usedIn: usage.get(token) ?? [],
    };
  });
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
    text: jsonText(item.text),
  };
}

function ProjectCompactPreview({ data }: { data: Record<string, unknown> }) {
  const scenario = jsonText(data.scenario) || jsonText(data.rough_idea);
  const stakeholders = sortStakeholdersByType(
    jsonList(data.stakeholders),
    (row) => jsonRecord(row).type,
  ).slice(0, 4);
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
  const stakeholders = sortStakeholdersByType(
    jsonList(data.stakeholders),
    (row) => jsonRecord(row).type,
  ).slice(0, 6);
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
    /conflict/i.test(jsonText(pair.final_label)),
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
            const label = jsonText(pair.final_label) || "未標記";
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

function MomFileTile({ projectId, file }: { projectId: string | null; file: OutputFile }) {
  const mom = useQuery({
    queryKey: ["chat-mom-preview", projectId, file.path],
    queryFn: () => fetchFile(projectId!, file.path),
    enabled: !!projectId,
    retry: false,
  });

  const meta = mom.data
    ? momPreviewMeta(mom.data.content, mom.data.type, file.path)
    : { title: "", summary: "", decision: "" };

  return (
    <div className="w-full min-w-0 max-w-xl space-y-3 text-left" title={file.label}>
      <div className="text-lg font-bold leading-tight text-slate-900">
        {file.label}
      </div>
      <div className="space-y-1.5">
        <div className="text-xs font-semibold text-slate-500">摘要</div>
        <div className="whitespace-pre-wrap text-sm leading-relaxed text-slate-700">
          {meta.summary || (mom.isLoading ? "載入中..." : "")}
        </div>
      </div>
      <div className="space-y-1.5">
        <div className="text-xs font-semibold text-emerald-700">決議</div>
        <div className="whitespace-pre-wrap text-sm leading-relaxed text-slate-700">
          {meta.decision || (mom.isLoading ? "載入中..." : "")}
        </div>
      </div>
      <div className="text-xs font-semibold text-slate-500">查看完整內容</div>
    </div>
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
      <div className={cn("inline-grid gap-2", visibleMomFiles.length > 1 && "grid-cols-2")}>
        {visibleMomFiles.map((file) => (
          <MomFileTile key={file.path} projectId={projectId} file={file} />
        ))}
      </div>
    </div>
  );
}

type DraftUpdateLink = {
  speaker: string;
  label: string;
  path: string;
  anchor: string | null;
};

function DraftUpdateBubbleContent({
  projectId,
  item,
  modelImages,
  outputFiles,
}: {
  projectId: string | null;
  item: DraftUpdateLink;
  modelImages: OutputFile[];
  outputFiles: OutputFile[];
}) {
  const file = useQuery({
    queryKey: ["draft-update-preview", projectId, item.path],
    queryFn: () => fetchFile(projectId!, item.path),
    enabled: !!projectId && item.path !== "artifact/system_models.json",
    retry: false,
  });
  const data = useMemo(() => {
    if (file.isLoading || file.isError) return null;
    return parseJsonRecord(file.data?.content ?? "");
  }, [file.data?.content, file.isError, file.isLoading]);

  if (item.path === "artifact/system_models.json" && projectId && modelImages.length > 0) {
    return (
      <ModelImagesPreview
        projectId={projectId}
        modelImages={modelImages}
        outputFiles={outputFiles}
        title={item.label}
      />
    );
  }

  return (
    <div className="space-y-2">
      <div className="text-sm font-semibold text-slate-800">{item.label}</div>
      {data ? (
        item.path === "artifact/feedback.json" ? (
          <FeedbackCompactPreview data={data} />
        ) : (
          <RequirementsCompactPreview data={data} sectionTitle="正式需求" />
        )
      ) : (
        <div className="text-sm text-slate-500">{file.isLoading ? "載入內容預覽..." : "無法預覽"}</div>
      )}
      <div className="text-xs font-medium text-slate-500 underline decoration-dotted underline-offset-2">
        查看完整內容
      </div>
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

function updateFlagsFromMeetingRecords(records: Record<string, unknown>[]) {
  const flags = {
    requirements: false,
    feedback: false,
    models: false,
  };

  for (const record of records) {
    const resolution = jsonRecord(record.resolution);
    const artifactUpdates = jsonRecord(resolution.artifact_updates);
    if (Object.keys(jsonRecord(artifactUpdates.REQ)).length || Object.keys(jsonRecord(artifactUpdates.URL)).length) {
      flags.requirements = true;
    }
    if (Object.keys(jsonRecord(artifactUpdates.feedback)).length) {
      flags.feedback = true;
    }
    if (Object.keys(jsonRecord(artifactUpdates.system_models)).length) {
      flags.models = true;
    }

    for (const entry of jsonList(record.conversation).map(jsonRecord)) {
      const actions = jsonList(entry.actions).map((item) => String(item));
      const results = jsonList(jsonRecord(entry.response).issue_action_results).map(jsonRecord);
      for (const action of actions) {
        if (["update_requirement", "refine_requirement", "analyze_requirements"].includes(action)) {
          flags.requirements = true;
        }
        if (["research_domain", "update_feedback"].includes(action)) {
          flags.feedback = true;
        }
        if (["system_modeling", "create_model", "update_model"].includes(action)) {
          flags.models = true;
        }
      }
      for (const result of results) {
        const action = jsonText(result.action);
        if (["update_requirement", "refine_requirement", "analyze_requirements"].includes(action) || jsonList(result.REQ).length > 0) {
          flags.requirements = true;
        }
        if (["research_domain", "update_feedback"].includes(action) || Object.keys(jsonRecord(result.feedback)).length > 0) {
          flags.feedback = true;
        }
        if (["system_modeling", "create_model", "update_model"].includes(action) || jsonList(result.system_models).length > 0) {
          flags.models = true;
        }
      }
    }
  }
  return flags;
}

function DraftUpdateBubbles({
  projectId,
  path,
  modelImages,
  outputFiles,
}: {
  projectId: string | null;
  path?: string;
  modelImages: OutputFile[];
  outputFiles: OutputFile[];
}) {
  const setSelectedOutputPath = useUiStore((s) => s.setSelectedOutputPath);
  const draftVersion = draftVersionFromPath(path);
  const meetingPath = draftVersion > 0 ? `artifact/meeting/formal_meeting_r${draftVersion}.json` : "";
  const meeting = useQuery({
    queryKey: ["draft-update-meeting", projectId, meetingPath],
    queryFn: () => fetchFile(projectId!, meetingPath),
    enabled: !!projectId && !!meetingPath,
    retry: false,
  });
  const links = useMemo(() => {
    if (!meeting.data?.content) return [];
    const records = parseMeetingRecords(meeting.data.content);
    const flags = updateFlagsFromMeetingRecords(records);
    const items: DraftUpdateLink[] = [];
    if (flags.requirements) {
      items.push({
        speaker: "analyst",
        label: "需求更新",
        path: "artifact/requirements.json",
        anchor: "requirements-req",
      });
    }
    if (flags.feedback) {
      items.push({
        speaker: "expert",
        label: "領域研究更新",
        path: "artifact/feedback.json",
        anchor: "feedback-top",
      });
    }
    if (flags.models) {
      items.push({
        speaker: "modeler",
        label: "系統模型更新",
        path: "artifact/system_models.json",
        anchor: null,
      });
    }
    return items;
  }, [meeting.data?.content]);
  if (!links.length) return null;

  return (
    <>
      {links.map((item) => (
        <div key={item.label} className="mb-4 flex w-full min-w-0 gap-2.5 justify-start">
          <div className="flex w-14 shrink-0 flex-col items-center gap-1 sm:w-20">
            <div className="w-full whitespace-nowrap text-center text-xs font-semibold leading-tight text-slate-600">
              {agentLabel(item.speaker)}
            </div>
            <div className={cn("flex h-9 w-9 items-center justify-center rounded-full", ROLE_STYLES.agent.avatar)}>
              <Bot className="h-4.5 w-4.5" />
            </div>
          </div>
          <div className="min-w-0 max-w-[calc(100%-4.125rem)] pt-6 sm:max-w-[85%]">
            <button
              type="button"
              className={cn(
                "block rounded-control border px-3.5 py-2.5 text-left text-sm leading-relaxed",
                ROLE_STYLES.agent.bubble,
                "cursor-pointer hover:border-slate-300 hover:shadow",
              )}
              onClick={() => setSelectedOutputPath(item.path, "manual", item.anchor)}
            >
              <DraftUpdateBubbleContent
                projectId={projectId}
                item={item}
                modelImages={modelImages}
                outputFiles={outputFiles}
              />
            </button>
          </div>
        </div>
      ))}
    </>
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
  const { t } = useI18n();
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
    if (msg.action === "init.generate_scope_review") return "需求範圍修正";
    if (stakeholderStatementCard) return msg.text;
    if (/^artifact\/meeting\/elicitation_meeting\.json$/i.test(previewPath ?? "")) {
      return msg.action === "elicit_end" ? "需求擷取會議結束" : "需求擷取會議";
    }
    if (isMomPath(previewPath)) return "MoM";
    if (/^artifact\/system_models\.json$/i.test(previewPath ?? "")) return "系統模型產生";
    const draftVersion = /draft_v(\d+)/i.exec(previewPath ?? "")?.[1];
    if (draftVersion) return `Draft v${draftVersion}`;
    const conflictReportVersion = /conflict_report_v(\d+)/i.exec(previewPath ?? "")?.[1];
    if (conflictReportVersion) return `Report v${conflictReportVersion}`;
    if (file.isLoading || file.isError) return titleFromMessage(msg);
    const fileTitle = titleFromFileContent(
      file.data?.content ?? "",
      file.data?.type,
      previewPath,
      { designRationale: t.stageLabels.DR, specification: t.stageLabels.SRS },
    );
    return fileTitle || titleFromMessage(msg);
  }, [file.data?.content, file.data?.type, file.isError, file.isLoading, msg, previewPath, stakeholderStatementCard, t.stageLabels.DR, t.stageLabels.SRS]);
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
    if (/^(?:results\/report\/conflict_report_v\d+\.html|artifact\/report\/conflict_report_v\d+\.md)$/i.test(previewPath ?? "")) {
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
    return (
      <ModelImagesPreview
        projectId={projectId}
        modelImages={modelImagesForMessage(msg, modelImages)}
        outputFiles={outputFiles}
      />
    );
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
  const taskIdPattern = "((?:R\\d+-)?[MT]-?\\d+)";
  const participantSplitter = /[、,，`｀]+/;
  const schedule = new RegExp(
    `^\\s*${taskIdPattern}\\s*[｜|]\\s*([^｜|]+)\\s*[｜|]\\s*([^｜|]+)\\s*[｜|]\\s*([^，｜|]+)，(\\d+)\\s*輪\\s*[｜|]\\s*(.+)$`,
    "i",
  ).exec(cleaned);
  if (schedule) {
    return {
      id: schedule[1],
      title: schedule[2].trim(),
      action: schedule[3].trim(),
      mode: schedule[4].trim(),
      rounds: schedule[5].trim(),
      participants: schedule[6].split(participantSplitter).map((item) => item.trim()).filter(Boolean),
    };
  }
  const start = new RegExp(
    `^\\s*\\[${taskIdPattern}\\]\\s*開始[:：]\\s*([^（]+)（([^，）]+)，([^，）]+)，預計\\s*(\\d+)\\s*輪；參與[:：]\\s*([^）]+)）`,
    "i",
  ).exec(cleaned);
  if (!start) return null;
  return {
    id: start[1],
    title: start[2].trim(),
    action: start[3].trim(),
    mode: start[4].trim(),
    rounds: start[5].trim(),
    participants: start[6].split(participantSplitter).map((item) => item.trim()).filter(Boolean),
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
    /^elicit\s*plan\s*[:：]\s*(?:mode\s*[=:：]\s*[^|]+\|\s*)?participants\s*[=:：]\s*([^|]+)\|\s*participants[_\s]+order\s*[=:：]\s*([^|]+)\|\s*goal\s*[=:：]\s*([\s\S]+)$/i.exec(
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
    /^需求衝突再審查\s*[:：]\s*mode\s*[=:：]\s*([^|]+)\|\s*participants\s*[=:：]\s*([^|]+)\|\s*participants[_\s]+order\s*[=:：]\s*([\s\S]+)$/i.exec(
      text.trim(),
    );
  if (!match) return null;
  return {
    mode: match[1].trim(),
    participants: match[2].split(/[,，、]/).map((item) => item.trim()).filter(Boolean),
    order: match[3].split(/[;；]/).map((item) => item.trim()).filter(Boolean),
  };
}

function formatParticipantOrder(item: string) {
  return item
    .split(/\s*(?:→|->)\s*/)
    .map((part) => agentLabel(part.trim()))
    .join(" → ");
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
                {formatParticipantOrder(item)}
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

function HumanInterventionReplayModal({
  message,
  payload,
  onClose,
}: {
  message: ChatMessage;
  payload?: Record<string, unknown>;
  onClose: () => void;
}) {
  const decision = message.decision;
  const options = decision?.options && typeof decision.options === "object"
    ? decision.options
    : {};
  const bestOptions = jsonList(options.best_options);
  const proposals = jsonList(options.proposals);
  const submittedScope = jsonRecord((payload ?? message.decisionPayload)?.scope);
  const originalScope = jsonRecord(options.scope);
  const scopeReviewScope = decision?.kind === "scope_review"
    ? Object.keys(submittedScope).length
      ? submittedScope
      : originalScope
    : {};
  const scopeSections = ([
    ["範圍內", jsonList(scopeReviewScope.in_scope)],
    ["範圍外", jsonList(scopeReviewScope.out_of_scope)],
  ] as Array<[string, unknown[]]>);
  const responseRows = payloadRows(payload ?? message.decisionPayload, decision);
  const referencedMentions = referencedMentionRows(decision, responseRows, payload ?? message.decisionPayload);
  const completed = responseRows.length > 0;
  const title = decision?.title || parseHumanDecisionRequest(message.text)?.title || decisionKindLabel(decision?.kind);
  const description =
    decision?.kind === "stakeholder_statement_review"
      ? "右側可查看利害關係人發言，支援拖移引用與編輯，按確定送出"
      : decision?.kind === "scope_review"
        ? "右側可逐條編輯需求範圍；下方可加入建議，按確定送出"
      : decision?.description || "";
  const badgeLabel = humanInterventionBadge(decision?.kind);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/30 px-4 py-6"
      onClick={onClose}
    >
      <div
        className="flex max-h-full w-full max-w-3xl flex-col overflow-hidden rounded-card border border-gray-200 bg-white shadow-xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4 border-b border-gray-100 px-5 py-4">
          <div className="min-w-0">
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <span className="inline-flex rounded-md bg-amber-50 px-2 py-0.5 text-[11px] font-semibold text-amber-700">
                {badgeLabel}
              </span>
              <span className={cn(
                "inline-flex rounded-md px-2 py-0.5 text-[11px] font-semibold",
                completed
                  ? "bg-emerald-50 text-emerald-700"
                  : "bg-slate-100 text-slate-500",
              )}>
                {humanInterventionStatus(decision?.kind, completed)}
              </span>
            </div>
            <h2 className="text-lg font-semibold leading-snug text-slate-950">{title}</h2>
            {description && (
              <p className="mt-1 text-sm leading-relaxed text-slate-500">{description}</p>
            )}
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <button
              type="button"
              className="inline-flex h-8 w-8 items-center justify-center rounded-control text-slate-400 hover:bg-slate-50 hover:text-slate-700"
              onClick={onClose}
              aria-label="關閉"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>
        <div className="min-h-0 overflow-y-auto px-5 py-4">
          {decision?.kind === "stakeholder_selection" && decision.proposed?.length ? (
            <section className="mb-4">
              <h3 className="mb-2 text-xs font-semibold text-slate-500">候選利害關係人</h3>
              <div className="grid gap-2 sm:grid-cols-2">
                {sortStakeholdersByType(decision.proposed, (row) => row.type).map((row, index) => (
                  <div key={`${row.name}-${index}`} className="rounded-control border border-gray-200 bg-slate-50 px-3 py-2">
                    <div className="text-sm font-semibold text-slate-900">{row.name}</div>
                    <div className="mt-1 text-xs leading-relaxed text-slate-500">{row.reason}</div>
                  </div>
                ))}
              </div>
            </section>
          ) : null}

          {decision?.kind === "scope_review" ? (
            <section className="mb-4">
              <div className="grid gap-3 sm:grid-cols-2">
                {scopeSections.map(([sectionTitle, rows]) => (
                  <div key={sectionTitle} className="rounded-control border border-gray-200 bg-white px-3 py-2">
                    <div className="mb-2 text-xs font-semibold text-slate-500">{sectionTitle}</div>
                    {rows.length ? (
                      <div className="space-y-1.5">
                        {rows.map((row, index) => (
                          <div key={index} className="rounded-control bg-slate-50 px-2.5 py-2 text-sm leading-relaxed text-slate-700">
                            {String(row)}
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="rounded-control bg-slate-50 px-2.5 py-2 text-sm text-slate-400">
                        尚無項目
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </section>
          ) : null}

          {bestOptions.length ? (
            <section className="mb-4">
              <h3 className="mb-2 text-xs font-semibold text-slate-500">決策選項</h3>
              <div className="grid gap-2">
                {bestOptions.map((row, index) => {
                  const item = jsonRecord(row);
                  const recommended = item.recommendation === true;
                  const optionTitle = jsonText(item.title) || jsonText(item.summary) || `選項 ${optionLetter(index)}`;
                  const optionDescription = jsonText(item.description);
                  return (
                    <div key={index} className="rounded-control border border-gray-200 bg-white px-3 py-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="rounded-md bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-600">
                          選項 {optionLetter(index)}
                        </span>
                        {recommended && (
                          <span className="rounded-md bg-emerald-50 px-2 py-0.5 text-xs font-semibold text-emerald-700">
                            推薦
                          </span>
                        )}
                      </div>
                      <div className="mt-2 text-sm font-semibold leading-relaxed text-slate-900">{optionTitle}</div>
                      {optionDescription && (
                        <div className="mt-1 text-sm leading-relaxed text-slate-600">{optionDescription}</div>
                      )}
                    </div>
                  );
                })}
              </div>
            </section>
          ) : null}

          {proposals.length ? (
            <section className="mb-4">
              <h3 className="mb-2 text-xs font-semibold text-slate-500">候選議題</h3>
              <div className="grid gap-2">
                {proposals.map((row, index) => {
                  const item = jsonRecord(row);
                  const proposalTitle = jsonText(item.title) || jsonText(item.summary) || `議題 ${index + 1}`;
                  return (
                    <div key={index} className="rounded-control border border-gray-200 bg-white px-3 py-2 text-sm font-semibold text-slate-900">
                      {proposalTitle}
                    </div>
                  );
                })}
              </div>
            </section>
          ) : null}

          {referencedMentions.length ? (
            <section className="mb-4">
              <h3 className="mb-2 text-xs font-semibold text-slate-500">引用資訊</h3>
              <div className="grid gap-2">
                {referencedMentions.map((reference) => (
                  <div key={reference.id} className="rounded-control border border-gray-200 bg-white px-3 py-2">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex min-w-0 flex-wrap items-center gap-2">
                        <span className="rounded-md bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-700">
                          @{reference.id}
                        </span>
                        {reference.title && (
                          <span className="text-xs font-semibold text-slate-500">{reference.title}</span>
                        )}
                      </div>
                      {reference.usedIn?.length ? (
                        <div className="flex shrink-0 flex-wrap justify-end gap-1">
                          {reference.usedIn.map((index) => (
                            <span
                              key={index}
                              className="rounded-md bg-amber-50 px-2 py-0.5 text-xs font-semibold text-amber-700"
                            >
                              建議 {index}
                            </span>
                          ))}
                        </div>
                      ) : null}
                    </div>
                    {reference.text && (
                      <div className="mt-1 text-sm leading-relaxed text-slate-700">
                        {reference.text}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </section>
          ) : null}

          <section>
            <h3 className="mb-2 text-xs font-semibold text-slate-500">送出內容</h3>
            <div className="rounded-control border border-gray-200 bg-slate-50 px-3 py-2">
              {responseRows.length ? (
                <div className="space-y-1 text-sm leading-relaxed text-slate-800">
                  {responseRows.map((row, index) => (
                    <div key={`${row}-${index}`} className="whitespace-pre-wrap break-words">
                      {row}
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-sm text-slate-400">尚未送出</div>
              )}
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}

function shouldHideChatMessage(msg: ChatMessage) {
  if (
    msg.kind === "decision" &&
    msg.role === "user" &&
    isSkipAllHumanInterventionsPayload(msg.decisionPayload)
  ) {
    return true;
  }
  if (isModelNoChangeMessage(msg)) return true;
  return /^已提出\s*\d+\s*筆候選議題\s*$/u.test(msg.text.trim());
}

function isModelNoChangeMessage(msg: ChatMessage) {
  return (
    msg.role === "agent" &&
    (msg.speaker ?? "").toLowerCase() === "modeler" &&
    /^\s*系統模型無需改動\s*$/u.test(msg.text.trim())
  );
}

function isStagePillMessage(msg: ChatMessage) {
  return msg.role === "system" && msg.kind === "stage";
}

function isElicitationDisplayMessage(msg: ChatMessage) {
  return (
    msg.stage === "elicitation" ||
    /^artifact\/meeting\/elicitation_meeting\.json$/i.test(msg.outputPath ?? "")
  );
}

function applyCollapsedStagePills(
  messages: ChatMessage[],
  collapsedIds: Set<string>,
) {
  const visible: ChatMessage[] = [];
  const hiddenCounts = new Map<string, number>();
  let activeCollapsedId: string | null = null;

  for (const message of messages) {
    if (isStagePillMessage(message)) {
      activeCollapsedId = collapsedIds.has(message.id) ? message.id : null;
      visible.push(message);
      continue;
    }
    if (activeCollapsedId) {
      hiddenCounts.set(activeCollapsedId, (hiddenCounts.get(activeCollapsedId) ?? 0) + 1);
      continue;
    }
    visible.push(message);
  }

  return { visible, hiddenCounts };
}

function Bubble({
  msg,
  projectId,
  outputFiles,
  modelImages,
  momFiles,
  submittedDecisionPayload,
  collapsed = false,
  collapsedCount = 0,
  onToggleCollapse,
}: {
  msg: ChatMessage;
  projectId: string | null;
  outputFiles: OutputFile[];
  modelImages: OutputFile[];
  momFiles: OutputFile[];
  submittedDecisionPayload?: Record<string, unknown>;
  collapsed?: boolean;
  collapsedCount?: number;
  onToggleCollapse?: () => void;
}) {
  const setSelectedOutputPath = useUiStore((s) => s.setSelectedOutputPath);
  const [replayOpen, setReplayOpen] = useState(false);
  const openOutput = () => {
    if (!msg.outputPath) return;
    setSelectedOutputPath(resolvePreferredOutputPath(msg.outputPath, outputFiles) ?? msg.outputPath);
  };

  if (msg.role === "system") {
    const failed = msg.status === "failed";
    const waiting = msg.status === "waiting";
    const running = msg.status === "running";
    const collapsible = isStagePillMessage(msg);
    return (
      <div className="my-4 flex items-center gap-2 text-xs text-slate-500">
        <div className="h-px flex-1 bg-gray-100" />
        <button
          type="button"
          disabled={!collapsible && !msg.outputPath}
          title={collapsible ? (collapsed ? "展開此段內容" : "收起此段內容") : undefined}
          aria-expanded={collapsible ? !collapsed : undefined}
          className={cn(
            "inline-flex max-w-full items-center gap-1.5 rounded-full border bg-white px-2.5 py-1",
            (collapsible || msg.outputPath) && "cursor-pointer hover:border-slate-300 hover:text-slate-700",
            failed
              ? "border-red-200 text-red-700"
              : waiting
                ? "border-amber-200 text-amber-800"
                : running
                  ? "border-emerald-200 text-emerald-800"
                : "border-gray-200 text-slate-500",
          )}
          onClick={collapsible ? onToggleCollapse : openOutput}
        >
          {collapsible && (
            collapsed ? (
              <ChevronRight className="h-3.5 w-3.5 text-slate-400" />
            ) : (
              <ChevronDown className="h-3.5 w-3.5 text-slate-400" />
            )
          )}
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
          {collapsible && collapsed && collapsedCount > 0 && (
            <span className="ml-0.5 rounded-full bg-slate-100 px-1.5 py-0.5 text-[10px] font-semibold text-slate-500">
              {collapsedCount}
            </span>
          )}
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
  const label = isHumanUser
    ? "您"
    : msg.action === "init.generate_scope_review"
      ? agentLabel("analyst")
      : (msg.label ?? agentLabel("analyst"));
  const action =
    msg.action === "human_decision_request" || msg.action === "stakeholder_selection_request"
      ? ""
      : msg.action ?? (isAction ? msg.text.trim() : "");
  const modelPreviewGrid =
    !!projectId &&
    (isModelImagePath(msg.outputPath) || isSystemModelsPath(msg.outputPath)) &&
    modelImagesForMessage(msg, modelImages).length > 0;
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
    const viewLabel = decisionViewLabel();
    const badgeLabel = humanInterventionBadge(msg.decision?.kind);
    if (isSkipAllHumanInterventionsPayload(submittedDecisionPayload)) return null;
    const replayAvailable = !!submittedDecisionPayload;
    return (
      <div className="mb-5 mt-8 flex w-full justify-center">
        <button
          type="button"
          className={cn(
            "w-full max-w-xs rounded-control border border-gray-200 bg-white px-4 py-3 text-left shadow-sm",
            replayAvailable && "transition hover:border-slate-300 hover:shadow",
            !replayAvailable && "cursor-default",
          )}
          disabled={!replayAvailable}
          onClick={() => {
            if (replayAvailable) setReplayOpen(true);
          }}
        >
          <div className="mb-2 flex items-start justify-between gap-3">
            <div className="inline-flex rounded-md bg-amber-50 px-2 py-0.5 text-[11px] font-semibold text-amber-700">
              {badgeLabel}
            </div>
            {replayAvailable && (
              <div className="shrink-0 text-[11px] font-semibold text-slate-400">
                {viewLabel}
              </div>
            )}
          </div>
          <div className="text-sm font-semibold leading-snug text-slate-900">
            {humanDecisionRequest.title}
          </div>
          {replayAvailable && (
            <div className="mt-2 text-xs font-medium text-emerald-600">
              {humanInterventionStatus(msg.decision?.kind, true)}
            </div>
          )}
        </button>
        {replayOpen && replayAvailable && (
          <HumanInterventionReplayModal
            message={msg}
            payload={submittedDecisionPayload}
            onClose={() => setReplayOpen(false)}
          />
        )}
      </div>
    );
  }
  const momPreviewGrid =
    isMomPath(msg.outputPath) &&
    momFilesForMessage(msg, momFiles).length > 0 &&
    !meetingTask &&
    !meetingResult;
  const bubbleSelectable = !!msg.outputPath && !modelPreviewGrid;
  const bubbleContent = submittedDecision ? (
    <div className="text-sm font-semibold leading-relaxed text-white">
      {submittedDecision}
    </div>
  ) : elicitPlan ? (
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
        "mb-4 flex w-full min-w-0 gap-2.5",
        isHumanUser ? "flex-row-reverse justify-start" : "justify-start",
      )}
    >
      <div className="flex w-14 shrink-0 flex-col items-center gap-1 sm:w-20">
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
      <div className={cn("min-w-0 max-w-[calc(100%-4.125rem)] pt-6 sm:max-w-[85%]", momPreviewGrid && "w-full sm:w-fit", isHumanUser && "items-end")}>
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
  hideElicitationMessages?: boolean;
}

export function ChatFeed({
  projectId,
  artifactItems = [],
  historyLoading = false,
  activeRun = null,
  hideElicitationMessages = false,
}: ChatFeedProps) {
  const { language } = useI18n();
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
  const forcedStagePillScrollMessageIdRef = useRef<string | null>(null);
  const scrollStorageKeyRef = useRef(chatScrollKey(projectId));
  const latestHydrationStateRef = useRef({
    historyLoading,
    messageCount: messages.length,
    projectId,
  });
  const [isNearBottom, setIsNearBottom] = useState(true);
  const [hasNewBelow, setHasNewBelow] = useState(false);
  const [collapsedStagePills, setCollapsedStagePills] = useState<Set<string>>(() => new Set());
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
    forcedStagePillScrollMessageIdRef.current = null;
    setCollapsedStagePills(new Set());
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

  const arrangedMessages = useMemo(
    () => arrangeMeetingPlanMomMessages(
      moveFormalMeetingBlocksBeforeDocumentGeneration(messages.filter((message) => {
        if (hideElicitationMessages && isElicitationDisplayMessage(message)) return false;
        return !shouldHideChatMessage(message);
      })),
    ),
    [hideElicitationMessages, language, messages],
  );
  const collapsedView = useMemo(
    () => applyCollapsedStagePills(arrangedMessages, collapsedStagePills),
    [arrangedMessages, collapsedStagePills],
  );
  const visibleMessages = collapsedView.visible;
  const collapsedHiddenCounts = collapsedView.hiddenCounts;

  useEffect(() => {
    if (!didRestoreScrollRef.current) return;
    const latestStagePill = [...visibleMessages].reverse().find(isStagePillMessage);
    if (!latestStagePill || forcedStagePillScrollMessageIdRef.current === latestStagePill.id) return;
    forcedStagePillScrollMessageIdRef.current = latestStagePill.id;
    requestAnimationFrame(() => {
      scrollToLatest(didInitialScrollRef.current ? "smooth" : "auto");
      didInitialScrollRef.current = true;
    });
  }, [scrollToLatest, visibleMessages]);

  const toggleStagePillCollapse = useCallback((id: string) => {
    setCollapsedStagePills((current) => {
      const next = new Set(current);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }, []);
  const submittedDecisionPayloads = useMemo(() => {
    const rows = new Map<string, Record<string, unknown>>();
    messages.forEach((message) => {
      if (
        message.kind === "decision" &&
        message.role === "user" &&
        message.decisionId &&
        message.decisionPayload
      ) {
        rows.set(message.decisionId, message.decisionPayload);
      }
    });
    return rows;
  }, [language, messages]);

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
      className={cn("chat-scroll h-full overflow-y-auto overflow-x-hidden px-2 py-3 sm:px-4", runActive && "pb-5")}
    >
      <div className={cn(
        "mx-auto w-full min-w-0 max-w-[720px]",
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
                : language === "en"
                  ? "Enter an initial idea below and press Run. The Agent team will help you produce the Specification."
                  : "請在下方輸入初步想法並按「執行」，Agent 團隊將協助您進行規格化"}
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
            <DraftUpdateBubbles
              projectId={projectId}
              path={m.outputPath}
              modelImages={modelImages}
              outputFiles={outputFiles}
            />
            <Bubble
              msg={m}
              projectId={projectId}
              outputFiles={outputFiles}
              modelImages={modelImages}
              momFiles={momFiles}
              submittedDecisionPayload={
                m.decisionId ? submittedDecisionPayloads.get(m.decisionId) : undefined
              }
              collapsed={collapsedStagePills.has(m.id)}
              collapsedCount={collapsedHiddenCounts.get(m.id) ?? 0}
              onToggleCollapse={
                isStagePillMessage(m) ? () => toggleStagePillCollapse(m.id) : undefined
              }
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
