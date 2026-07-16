import { useIsMutating, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Download, Edit3, Loader2, Minus, MoreHorizontal, Plus, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { DragEvent, RefObject } from "react";
import { createPortal } from "react-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { fetchFile, manualFileUrl } from "@/api/projects";
import { decisionMutationKey, submitDecision } from "@/api/runs";
import { PanelChrome } from "@/components/PanelChrome";
import { agentLabel } from "@/constants/agents";
import { JsonArtifactView } from "@/features/output/JsonArtifactView";
import { OutputFilePicker } from "@/features/output/OutputFilePicker";
import { useActiveRun } from "@/hooks/useProjectQueries";
import { useI18n } from "@/i18n";
import { useChatStore } from "@/stores/chatStore";
import { useNoticeStore } from "@/stores/noticeStore";
import { useUiStore } from "@/stores/uiStore";
import type { ScopeReviewDraft } from "@/stores/uiStore";
import {
  buildOutputFiles,
  filenameFromPath,
  findModelPair,
  resolvePreferredOutputPath,
} from "@/utils/buildOutputFiles";
import type { FileContent, FileTreeNode } from "@/types/api";
import { cn } from "@/utils/cn";
import { errorMessage } from "@/utils/errorMessage";
import { makeZip } from "@/utils/zip";
import { sortStakeholdersByType, stakeholderTypeLabel } from "@/utils/stakeholders";

interface ResultPreviewProps {
  projectId: string | null;
  items: FileTreeNode[];
}

interface TocItem {
  id: string;
  text: string;
  level: number;
}

interface TraceDetail {
  title: string;
  html: string;
}

interface StakeholderStatementLine {
  id: string;
  text: string;
}

interface StakeholderStatementDraft {
  name: string;
  type: string;
  text: StakeholderStatementLine[];
}

interface RequirementReviewRow {
  id: string;
  text: string;
  sourceId: string;
  raw: Record<string, unknown>;
}

interface AgentIssueProposalRow {
  id: string;
  agent: string;
  title: string;
  detail: string;
}

type UiTexts = ReturnType<typeof useI18n>["t"];

const emptyScopeDraft: ScopeReviewDraft = {
  in_scope: [],
  out_of_scope: [],
};

const REVIEW_MENTION_DRAG_MIME = "application/x-plant-review-mention";

const TRACE_ALLOWED_TAGS = new Set([
  "a", "blockquote", "br", "code", "div", "em", "h2", "h3", "h4", "h5",
  "img", "li", "ol", "p", "pre", "span", "strong", "table", "tbody", "td",
  "th", "thead", "tr", "ul",
]);

function decodeTraceContent(encoded: string, fallback = ""): string {
  if (!encoded) return fallback;
  try {
    const bytes = Uint8Array.from(atob(encoded), (char) => char.charCodeAt(0));
    return new TextDecoder().decode(bytes);
  } catch {
    return fallback;
  }
}

function encodeTraceContent(content: string): string {
  const bytes = new TextEncoder().encode(content);
  let binary = "";
  bytes.forEach((byte) => {
    binary += String.fromCharCode(byte);
  });
  return btoa(binary);
}

function escapeTraceText(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function sanitizeTraceHtml(source: string, baseUrl: string): string {
  const parsed = new DOMParser().parseFromString(source, "text/html");
  const blockedTags = new Set(["iframe", "object", "script", "style", "template"]);

  const cleanNode = (node: Node) => {
    for (const child of Array.from(node.childNodes)) {
      if (!(child instanceof Element)) continue;
      const tag = child.tagName.toLowerCase();
      if (blockedTags.has(tag)) {
        child.remove();
        continue;
      }
      if (!TRACE_ALLOWED_TAGS.has(tag)) {
        cleanNode(child);
        child.replaceWith(...Array.from(child.childNodes));
        continue;
      }

      for (const attribute of Array.from(child.attributes)) {
        const name = attribute.name.toLowerCase();
        const allowed =
          name === "class" ||
          (tag === "a" && ["href", "title"].includes(name)) ||
          (tag === "img" && ["src", "alt", "title"].includes(name)) ||
          (["td", "th"].includes(tag) && ["colspan", "rowspan"].includes(name));
        if (!allowed) child.removeAttribute(attribute.name);
      }

      if (tag === "a" && child.hasAttribute("href")) {
        const rawHref = child.getAttribute("href") ?? "";
        try {
          const url = new URL(rawHref, baseUrl);
          if (!["http:", "https:", "mailto:"].includes(url.protocol)) throw new Error();
          child.setAttribute("href", url.href);
          child.setAttribute("target", "_blank");
          child.setAttribute("rel", "noopener noreferrer");
        } catch {
          child.removeAttribute("href");
        }
      }

      if (tag === "img" && child.hasAttribute("src")) {
        const rawSrc = child.getAttribute("src") ?? "";
        try {
          const url = new URL(rawSrc, baseUrl);
          const safeDataImage = url.protocol === "data:" && /^data:image\//i.test(rawSrc);
          const safeSameOriginImage =
            ["http:", "https:"].includes(url.protocol) && url.origin === window.location.origin;
          if (!safeDataImage && !safeSameOriginImage) throw new Error();
          child.setAttribute("src", url.href);
        } catch {
          child.remove();
          continue;
        }
      }
      cleanNode(child);
    }
  };

  cleanNode(parsed.body);
  return parsed.body.innerHTML;
}

function createMentionDragLabel(id: string): HTMLDivElement {
  const label = document.createElement("div");
  label.textContent = `@${id}`;
  label.style.position = "fixed";
  label.style.top = "-1000px";
  label.style.left = "-1000px";
  label.style.border = "1px solid rgb(203 213 225)";
  label.style.borderRadius = "8px";
  label.style.background = "white";
  label.style.padding = "6px 10px";
  label.style.fontSize = "12px";
  label.style.fontWeight = "700";
  label.style.color = "rgb(51 65 85)";
  label.style.boxShadow = "0 8px 18px rgb(15 23 42 / 0.12)";
  return label;
}

function handleMentionDragStart(
  event: DragEvent<HTMLElement>,
  target: "stakeholders" | "requirements",
  id: string,
) {
  const normalizedId = id.trim();
  if (!normalizedId) {
    event.preventDefault();
    return;
  }
  const dragLabel = createMentionDragLabel(normalizedId);
  document.body.appendChild(dragLabel);
  event.dataTransfer.setDragImage(dragLabel, 12, 12);
  window.setTimeout(() => dragLabel.remove(), 0);
  event.dataTransfer.effectAllowed = "copy";
  event.dataTransfer.setData(
    REVIEW_MENTION_DRAG_MIME,
    JSON.stringify({ type: "review_mention", target, id: normalizedId }),
  );
  event.dataTransfer.setData("text/plain", `@${normalizedId}`);
}

function pathFromManualPreviewUrl(pathname: string, projectId: string): string | null {
  const prefix = `/${encodeURIComponent(projectId)}/manual/`;
  if (!pathname.startsWith(prefix)) return null;
  const value = decodeURIComponent(pathname.slice(prefix.length));
  if (value === "srs") return "results/srs.html";
  if (value === "dr") return "results/design_rationale.html";
  if (/^(results|artifact|output)\//i.test(value)) return value;
  return null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

function textValue(value: unknown): string {
  return typeof value === "string" ? value.trim() : String(value ?? "").trim();
}

function statementText(value: unknown): string {
  if (typeof value === "string") return value.trim();
  if (!isRecord(value)) return String(value ?? "").trim();
  return textValue(value.text);
}

function statementId(value: unknown, stakeholderIndex: number, lineIndex: number) {
  if (isRecord(value)) {
    const id = textValue(value.id);
    if (id) return id;
  }
  return `ST-${stakeholderIndex + 1}-${lineIndex + 1}`;
}

function stakeholderStatementDrafts(
  decision: NonNullable<ReturnType<typeof useActiveRun>["activeRun"]>["pending_decision"],
  t: UiTexts,
) {
  if (decision?.kind !== "stakeholder_statement_review") return [];
  const options = isRecord(decision.options) ? decision.options : {};
  const rows = Array.isArray(options.stakeholders) ? options.stakeholders : [];
  return sortStakeholdersByType(rows, (row) => (isRecord(row) ? row.type : "")).map((row, stakeholderIndex) => {
    const item = isRecord(row) ? row : {};
    const rawLines = Array.isArray(item.text)
      ? item.text
      : textValue(item.text)
        ? [item.text]
        : [];
    return {
      name: textValue(item.name) || t.stakeholderFallback(stakeholderIndex + 1),
      type: textValue(item.type),
      text: rawLines.map((line, lineIndex) => ({
        id: statementId(line, stakeholderIndex, lineIndex),
        text: statementText(line),
      })),
    };
  });
}

function requirementReviewRows(
  decision: NonNullable<ReturnType<typeof useActiveRun>["activeRun"]>["pending_decision"],
) {
  if (decision?.kind !== "requirements_review") return [];
  const options = isRecord(decision.options) ? decision.options : {};
  const rows = Array.isArray(options.requirements) ? options.requirements : [];
  return rows
    .map((row, index): RequirementReviewRow => {
      const item = isRecord(row) ? row : {};
      return {
        id: textValue(item.id) || `URL-${index + 1}`,
        text: textValue(item.text),
        sourceId: textValue(item.source_id),
        raw: item,
      };
    })
    .filter((row) => row.text);
}

function parseMeetingIssueProposalRows(
  decision: NonNullable<ReturnType<typeof useActiveRun>["activeRun"]>["pending_decision"],
  t: UiTexts,
) {
  if (decision?.kind !== "meeting_issue_proposal_review") return [];
  const options = isRecord(decision.options) ? decision.options : {};
  const rows = Array.isArray(options.proposals) ? options.proposals : [];
  return rows
    .map((row, index): AgentIssueProposalRow => {
      const item = isRecord(row) ? row : {};
      const rawAgent = textValue(item.proposed_by) || "Agent";
      const agent = agentLabel(rawAgent);
      const title = textValue(item.title) || t.issueFallback(index + 1);
      const detail =
        textValue(item.reason) ||
        textValue(item.expect_outcome) ||
        textValue(item.issue_focus);
      return {
        id: textValue(item.id) || `ISSUE-${index + 1}`,
        agent,
        title,
        detail,
      };
    })
    .filter((row) => row.title);
}

function cleanScopeList(value: unknown) {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => String(item ?? "").trim())
    .filter(Boolean);
}

function scopeReviewDraftFromDecision(
  decision: NonNullable<ReturnType<typeof useActiveRun>["activeRun"]>["pending_decision"],
): ScopeReviewDraft {
  if (decision?.kind !== "scope_review") return emptyScopeDraft;
  const options = isRecord(decision.options) ? decision.options : {};
  const rawScope = isRecord(options.scope) ? options.scope : {};
  return {
    in_scope: cleanScopeList(rawScope.in_scope),
    out_of_scope: cleanScopeList(rawScope.out_of_scope),
  };
}

function downloadBlob(content: FileContent, filename: string) {
  let blob: Blob;
  if (content.encoding === "base64") {
    const binary = window.atob(content.content);
    const bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0));
    blob = new Blob([bytes], { type: content.mime || "application/octet-stream" });
  } else {
    blob = new Blob([content.content], { type: content.mime || "text/plain;charset=utf-8" });
  }
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function triggerDownload(url: string, filename: string) {
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
}

function downloadSourcePathForPreview(path: string, availablePaths: Set<string>) {
  const srs = /^results\/srs\.html$/i.exec(path);
  if (srs && availablePaths.has("output/srs.md")) return "output/srs.md";

  const dr = /^results\/design_rationale\.html$/i.exec(path);
  if (dr && availablePaths.has("output/design_rationale.md")) {
    return "output/design_rationale.md";
  }

  const draft = /^results\/drafts\/(draft_v\d+)\.html$/i.exec(path);
  if (draft) {
    const source = `artifact/drafts/${draft[1]}.md`;
    if (availablePaths.has(source)) return source;
  }

  const mom = /^results\/MoM\/(R\d+-M\d+)\.html$/i.exec(path);
  if (mom) {
    const source = `artifact/MoM/${mom[1]}.md`;
    if (availablePaths.has(source)) return source;
  }

  const report = /^results\/report\/(conflict_report_v\d+)\.html$/i.exec(path);
  if (report) {
    const markdown = `artifact/report/${report[1]}.md`;
    if (availablePaths.has(markdown)) return markdown;
    const json = `artifact/report/${report[1]}.json`;
    if (availablePaths.has(json)) return json;
  }

  return path;
}

function downloadHtmlPathForPreview(path: string, availablePaths: Set<string>) {
  if (/\.html$/i.test(path)) return path;

  if (/^output\/srs\.md$/i.test(path) && availablePaths.has("results/srs.html")) {
    return "results/srs.html";
  }

  if (
    /^output\/design_rationale\.md$/i.test(path) &&
    availablePaths.has("results/design_rationale.html")
  ) {
    return "results/design_rationale.html";
  }

  const draft = /^artifact\/drafts\/(draft_v\d+)\.md$/i.exec(path);
  if (draft) {
    const html = `results/drafts/${draft[1]}.html`;
    if (availablePaths.has(html)) return html;
  }

  const mom = /^artifact\/MoM\/(R\d+-M\d+)\.md$/i.exec(path);
  if (mom) {
    const html = `results/MoM/${mom[1]}.html`;
    if (availablePaths.has(html)) return html;
  }

  const report = /^artifact\/report\/(conflict_report_v\d+)\.(?:md|json)$/i.exec(path);
  if (report) {
    const html = `results/report/${report[1]}.html`;
    if (availablePaths.has(html)) return html;
  }

  return path;
}

type DownloadFormat = "markdown" | "html";

function downloadPathForFormat(path: string, availablePaths: Set<string>, format: DownloadFormat) {
  return format === "html"
    ? downloadHtmlPathForPreview(path, availablePaths)
    : downloadSourcePathForPreview(path, availablePaths);
}

function modelImageDownloadPath(rawPath: string) {
  const trimmed = rawPath.trim().replace(/^<(.+)>$/, "$1");
  if (!trimmed || /^(?:[a-z][a-z0-9+.-]*:|\/\/|#)/i.test(trimmed)) return null;

  const hashIndex = trimmed.indexOf("#");
  const beforeHash = hashIndex >= 0 ? trimmed.slice(0, hashIndex) : trimmed;
  const hash = hashIndex >= 0 ? trimmed.slice(hashIndex) : "";
  const queryIndex = beforeHash.indexOf("?");
  const pathOnly = queryIndex >= 0 ? beforeHash.slice(0, queryIndex) : beforeHash;
  const query = queryIndex >= 0 ? beforeHash.slice(queryIndex) : "";
  const fileName = pathOnly.split("/").filter(Boolean).at(-1);
  if (!fileName || !/\.(?:png|jpe?g|gif|webp|svg)$/i.test(fileName)) return null;

  const pointsToModels = /(?:^|\/)models\//i.test(pathOnly) || !pathOnly.includes("/");
  if (!pointsToModels) return null;

  return `./models/${fileName}${query}${hash}`;
}

function rewriteMarkdownModelImagePaths(content: string) {
  const withMarkdownImages = content.replace(
    /(!\[[^\]]*]\()([^)\n]+)(\))/g,
    (match, prefix: string, target: string, suffix: string) => {
      const parts = /^(\S+)(\s+["'][^"']*["'])$/.exec(target.trim());
      const rawPath = parts?.[1] ?? target.trim();
      const title = parts?.[2] ?? "";
      const rewritten = modelImageDownloadPath(rawPath);
      return rewritten ? `${prefix}${rewritten}${title}${suffix}` : match;
    },
  );

  const withReferenceImages = withMarkdownImages.replace(
    /^(\[[^\]]+]:\s*)(\S+)(.*)$/gm,
    (match, prefix: string, rawPath: string, suffix: string) => {
      const rewritten = modelImageDownloadPath(rawPath);
      return rewritten ? `${prefix}${rewritten}${suffix}` : match;
    },
  );

  return withReferenceImages.replace(
    /(<img\b[^>]*\bsrc=["'])([^"']+)(["'][^>]*>)/gi,
    (match, prefix: string, rawPath: string, suffix: string) => {
      const rewritten = modelImageDownloadPath(rawPath);
      return rewritten ? `${prefix}${rewritten}${suffix}` : match;
    },
  );
}

function rewriteSrsDesignRationaleLinks(content: string) {
  const rewriteTarget = (rawPath: string) => {
    const trimmed = rawPath.trim().replace(/^<(.+)>$/, "$1");
    if (!trimmed || /^(?:[a-z][a-z0-9+.-]*:|\/\/|#)/i.test(trimmed)) return null;

    const hashIndex = trimmed.indexOf("#");
    const pathOnly = hashIndex >= 0 ? trimmed.slice(0, hashIndex) : trimmed;
    const hash = hashIndex >= 0 ? trimmed.slice(hashIndex) : "";
    if (!hash) return null;

    if (
      /^(?:\.\/)?dr$/i.test(pathOnly) ||
      /^(?:\.\/)?design_rationale\.html$/i.test(pathOnly) ||
      /^(?:\.\/)?design_rationale\.md$/i.test(pathOnly) ||
      /^results\/design_rationale\.html$/i.test(pathOnly) ||
      /^output\/design_rationale\.md$/i.test(pathOnly)
    ) {
      return `./design_rationale.md${hash}`;
    }

    return null;
  };

  const withMarkdownLinks = content.replace(
    /(\[[^\]]+]\()([^)\n]+)(\))/g,
    (match, prefix: string, target: string, suffix: string) => {
      const parts = /^(\S+)(\s+["'][^"']*["'])$/.exec(target.trim());
      const rawPath = parts?.[1] ?? target.trim();
      const title = parts?.[2] ?? "";
      const rewritten = rewriteTarget(rawPath);
      return rewritten ? `${prefix}${rewritten}${title}${suffix}` : match;
    },
  );

  const withReferenceLinks = withMarkdownLinks.replace(
    /^(\[[^\]]+]:\s*)(\S+)(.*)$/gm,
    (match, prefix: string, rawPath: string, suffix: string) => {
      const rewritten = rewriteTarget(rawPath);
      return rewritten ? `${prefix}${rewritten}${suffix}` : match;
    },
  );

  return withReferenceLinks.replace(
    /(<a\b[^>]*\bhref=["'])([^"']+)(["'][^>]*>)/gi,
    (match, prefix: string, rawPath: string, suffix: string) => {
      const rewritten = rewriteTarget(rawPath);
      return rewritten ? `${prefix}${rewritten}${suffix}` : match;
    },
  );
}

function addDesignRationaleMarkdownAnchors(content: string) {
  const newline = content.includes("\r\n") ? "\r\n" : "\n";
  const lines = content.split(/\r?\n/);
  const output: string[] = [];
  for (const line of lines) {
    const heading = /^(#{1,6})\s+((?:CON|FR|NFR)-\d+)\b/i.exec(line.trim());
    if (heading) {
      const id = heading[2].toLowerCase();
      const previous = output.at(-1)?.trim() ?? "";
      if (!new RegExp(`<a\\s+(?:id|name)=["']${id}["']\\s*><\\/a>`, "i").test(previous)) {
        output.push(`<a id="${id}"></a>`);
      }
    }
    output.push(line);
  }
  return output.join(newline);
}

function fileContentForDownload(content: FileContent, path: string): FileContent {
  if (content.encoding !== "base64" && /\.md$/i.test(path)) {
    const normalized = /^output\/srs\.md$/i.test(path)
      ? rewriteSrsDesignRationaleLinks(rewriteMarkdownModelImagePaths(content.content))
      : /^output\/design_rationale\.md$/i.test(path)
        ? addDesignRationaleMarkdownAnchors(rewriteMarkdownModelImagePaths(content.content))
        : rewriteMarkdownModelImagePaths(content.content);
    return {
      ...content,
      content: normalized,
      mime: content.mime || "text/markdown;charset=utf-8",
    };
  }
  return content;
}

function bytesFromFileContent(content: FileContent) {
  if (content.encoding === "base64") {
    const binary = window.atob(content.content);
    return Uint8Array.from(binary, (char) => char.charCodeAt(0));
  }
  return new TextEncoder().encode(content.content);
}

function bytesFromFileContentForDownload(content: FileContent, path: string) {
  return bytesFromFileContent(fileContentForDownload(content, path));
}

function StakeholderStatementEditor({
  drafts,
  saving,
  showValidation,
  onChange,
}: {
  drafts: StakeholderStatementDraft[];
  saving?: boolean;
  showValidation?: boolean;
  onChange: (drafts: StakeholderStatementDraft[]) => void;
}) {
  const { t } = useI18n();
  const updateLine = (stakeholderIndex: number, lineIndex: number, value: string) => {
    onChange(
      drafts.map((stakeholder, currentStakeholderIndex) =>
        currentStakeholderIndex !== stakeholderIndex
          ? stakeholder
          : {
              ...stakeholder,
              text: stakeholder.text.map((line, currentLineIndex) =>
                currentLineIndex === lineIndex ? { ...line, text: value } : line,
              ),
            },
      ),
    );
  };

  return (
    <div className="min-h-0 flex-1 overflow-y-auto p-3">
      {drafts.length === 0 ? (
        <div className="flex min-h-0 flex-1 items-center justify-center p-4 text-sm text-slate-500">
          {t.noEditableStatements}
        </div>
      ) : (
        <div className="space-y-3">
          {drafts.map((stakeholder, stakeholderIndex) => (
            <section
              key={`${stakeholder.name}-${stakeholderIndex}`}
              className="rounded-control border border-gray-200 bg-white p-3"
            >
              <div className="mb-3 flex items-center justify-between gap-3">
                <h3 className="text-sm font-semibold text-slate-900">
                  {stakeholder.name}
                </h3>
                {stakeholder.type && (
                  <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600">
                    {stakeholderTypeLabel(stakeholder.type)}
                  </span>
                )}
              </div>
              <div className="space-y-2">
                {stakeholder.text.map((line, lineIndex) => {
                  const empty = !line.text.trim();
                  return (
                    <label
                      key={line.id}
                      className="block rounded-control bg-slate-50 px-3 py-2"
                    >
                      <span className="mb-1 block text-xs font-semibold text-slate-400">
                        {line.id}
                      </span>
                      <textarea
                        className={cn(
                          "min-h-20 w-full resize-none rounded-control border bg-white px-2.5 py-2 text-sm leading-relaxed text-slate-800 focus:outline-none focus:ring-2",
                          showValidation && empty
                            ? "border-red-300 focus:border-red-400 focus:ring-red-100"
                            : "border-gray-200 focus:border-slate-400 focus:ring-slate-200",
                        )}
                        disabled={saving}
                        value={line.text}
                        onChange={(event) =>
                          updateLine(stakeholderIndex, lineIndex, event.target.value)
                        }
                      />
                      {showValidation && empty && (
                        <span className="mt-1 block text-xs font-medium text-red-600">
                          {t.requiredField}
                        </span>
                      )}
                    </label>
                  );
                })}
              </div>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}

function StakeholderStatementPreview({
  drafts,
}: {
  drafts: StakeholderStatementDraft[];
}) {
  const { t } = useI18n();
  return (
    <div className="min-h-0 flex-1 overflow-y-auto p-3">
      {drafts.length === 0 ? (
        <div className="flex min-h-0 flex-1 items-center justify-center p-4 text-sm text-slate-500">
          {t.noStakeholderStatements}
        </div>
      ) : (
        <div className="space-y-3">
          {drafts.map((stakeholder, stakeholderIndex) => (
            <section
              key={`${stakeholder.name}-${stakeholderIndex}`}
              className="rounded-control border border-gray-200 bg-white p-3"
            >
              <div className="mb-3 flex items-center justify-between gap-3">
                <h3 className="text-sm font-semibold text-slate-900">
                  {stakeholder.name}
                </h3>
                {stakeholder.type && (
                  <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600">
                    {stakeholderTypeLabel(stakeholder.type)}
                  </span>
                )}
              </div>
              <div className="space-y-2">
                {stakeholder.text.map((line) => (
                  <div
                    key={line.id}
                    draggable
                    className="rounded-control bg-slate-50 px-3 py-2 cursor-grab active:cursor-grabbing"
                    onDragStart={(event) =>
                      handleMentionDragStart(event, "stakeholders", line.id)
                    }
                    title={t.dragReferenceTitle(line.id)}
                  >
                    <div className="mb-1 text-xs font-semibold text-slate-400">
                      {line.id}
                    </div>
                    <p className="text-sm leading-relaxed text-slate-800">
                      {line.text}
                    </p>
                  </div>
                ))}
              </div>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}

function ScopeReviewEditor({
  draft,
  onChange,
}: {
  draft: ScopeReviewDraft;
  onChange: (draft: ScopeReviewDraft) => void;
}) {
  const { t } = useI18n();
  const [editingItems, setEditingItems] = useState<Record<string, boolean>>({});
  const [invalidItems, setInvalidItems] = useState<Record<string, boolean>>({});
  const [removeTarget, setRemoveTarget] = useState<{
    key: keyof ScopeReviewDraft;
    index: number;
  } | null>(null);
  const itemKey = (key: keyof ScopeReviewDraft, index: number) => `${key}-${index}`;
  const updateItem = (key: keyof ScopeReviewDraft, index: number, value: string) => {
    onChange({
      ...draft,
      [key]: draft[key].map((item, currentIndex) =>
        currentIndex === index ? value : item,
      ),
    });
    if (value.trim()) {
      const currentKey = itemKey(key, index);
      setInvalidItems((current) => {
        if (!current[currentKey]) return current;
        const next = { ...current };
        delete next[currentKey];
        return next;
      });
    }
  };
  const addItem = (key: keyof ScopeReviewDraft) => {
    if (draft[key].some((item) => !item.trim())) return;
    const nextIndex = draft[key].length;
    setRemoveTarget(null);
    onChange({
      ...draft,
      [key]: [...draft[key], ""],
    });
    setEditingItems((current) => ({ ...current, [itemKey(key, nextIndex)]: true }));
  };
  const finishItemEditing = (key: keyof ScopeReviewDraft, index: number) => {
    const currentKey = itemKey(key, index);
    if (!draft[key][index]?.trim()) {
      setInvalidItems((current) => ({ ...current, [currentKey]: true }));
      setEditingItems((current) => ({ ...current, [currentKey]: true }));
      return;
    }
    setInvalidItems((current) => {
      if (!current[currentKey]) return current;
      const next = { ...current };
      delete next[currentKey];
      return next;
    });
    setEditingItems((current) => ({
      ...current,
      [currentKey]: false,
    }));
  };
  const removeItem = (key: keyof ScopeReviewDraft, index: number) => {
    onChange({
      ...draft,
      [key]: draft[key].filter((_, currentIndex) => currentIndex !== index),
    });
    setRemoveTarget(null);
    setEditingItems((current) => {
      const next = { ...current };
      delete next[itemKey(key, index)];
      return next;
    });
    setInvalidItems((current) => {
      const next = { ...current };
      delete next[itemKey(key, index)];
      return next;
    });
  };
  const renderSection = (
    key: keyof ScopeReviewDraft,
    title: string,
    emptyText: string,
  ) => {
    const canAdd = !draft[key].some((item) => !item.trim());
    const placeholder =
      key === "in_scope"
        ? t.inputInScope
        : t.inputOutOfScope;
    return (
      <section className="rounded-control border border-gray-200 bg-white p-3">
      <div className="relative mb-3 flex items-center justify-end gap-3">
        <h3 className="absolute left-1/2 -translate-x-1/2 text-sm font-semibold text-slate-900">
          {title}
        </h3>
        <button
          type="button"
          className={cn(
            "inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-control border",
            canAdd
              ? "border-emerald-200 bg-emerald-50 text-emerald-700 hover:bg-emerald-100"
              : "cursor-not-allowed border-gray-200 bg-slate-50 text-slate-300",
          )}
          disabled={!canAdd}
          onClick={() => addItem(key)}
          aria-label={t.addSectionItem(title)}
          title={canAdd ? t.addItem : t.fillNewItemFirst}
        >
          <Plus className="h-3.5 w-3.5" />
        </button>
      </div>
      <div className="space-y-2">
        {draft[key].length === 0 ? (
          <div className="rounded-control border border-dashed border-gray-200 bg-slate-50 px-3 py-4 text-sm text-slate-500">
            {emptyText}
          </div>
        ) : (
          draft[key].map((item, index) => {
            const currentKey = itemKey(key, index);
            const editing = editingItems[currentKey];
            const confirmRemove = removeTarget?.key === key && removeTarget.index === index;
            return (
              <div
                key={`${key}-${index}`}
                className="rounded-control border border-gray-200 bg-white p-2"
              >
                <div className="flex min-h-14 items-center gap-2 rounded-control bg-slate-50 px-3 py-2">
                  {editing ? (
                    <div className="min-w-0 flex-1">
                      <textarea
                        className={cn(
                          "min-h-10 w-full resize-none border-0 bg-transparent px-0 py-1 text-sm leading-relaxed text-slate-800 outline-none placeholder:text-slate-400 focus:ring-0",
                          invalidItems[currentKey] && "text-red-700 placeholder:text-red-300",
                        )}
                        value={item}
                        placeholder={placeholder}
                        autoFocus
                        onBlur={() => finishItemEditing(key, index)}
                        onChange={(event) => updateItem(key, index, event.target.value)}
                      />
                      {invalidItems[currentKey] && (
                        <span className="mt-1 block text-xs font-medium text-red-600">
                          {t.requiredField}
                        </span>
                      )}
                    </div>
                  ) : (
                    <div className="min-w-0 flex-1 text-left text-sm leading-relaxed text-slate-700">
                      {item.trim() || (
                        <span className="text-slate-400">{placeholder}</span>
                      )}
                    </div>
                  )}
                  <button
                    type="button"
                    className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-control text-slate-500 hover:bg-white hover:text-slate-700"
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={() => {
                      setRemoveTarget(null);
                      if (editing) {
                        finishItemEditing(key, index);
                        return;
                      }
                      setEditingItems((current) => ({
                        ...current,
                        [currentKey]: true,
                      }));
                    }}
                    aria-label={editing ? t.confirm : t.editItem}
                    title={editing ? t.confirm : t.edit}
                  >
                    {editing ? (
                      <Check className="h-3.5 w-3.5" />
                    ) : (
                      <Edit3 className="h-3.5 w-3.5" />
                    )}
                  </button>
                  <button
                    type="button"
                    className={cn(
                      "inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-control border border-red-100 bg-white text-red-500 hover:bg-red-50 hover:text-red-600",
                      confirmRemove && "border-red-200 bg-red-50 text-red-600",
                    )}
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={() => setRemoveTarget({ key, index })}
                    aria-label={t.removeItem}
                    title={t.remove}
                  >
                    <Minus className="h-3.5 w-3.5" />
                  </button>
                </div>
                {confirmRemove && (
                  <div className="mt-2 rounded-control border border-red-100 bg-red-50 px-3 py-2">
                    <div className="text-xs font-semibold text-red-700">
                      {t.removeItem}
                    </div>
                    <p className="mt-1 text-xs leading-5 text-red-500">
                      {t.irreversibleAction}
                    </p>
                    <div className="mt-2 flex justify-end gap-2">
                      <button
                        type="button"
                        className="rounded-control border border-red-100 bg-white px-2.5 py-1 text-xs font-medium text-slate-600 hover:bg-red-50"
                        onClick={() => setRemoveTarget(null)}
                      >
                        {t.cancel}
                      </button>
                      <button
                        type="button"
                        className="rounded-control bg-red-600 px-2.5 py-1 text-xs font-semibold text-white hover:bg-red-700"
                        onClick={() => removeItem(key, index)}
                      >
                        {t.remove}
                      </button>
                    </div>
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>
    </section>
    );
  };

  return (
    <div className="min-h-0 flex-1 overflow-y-auto p-3">
      <div className="space-y-3">
        {renderSection("in_scope", t.inScope, t.noInScopeItems)}
        {renderSection("out_of_scope", t.outOfScope, t.noOutOfScopeItems)}
      </div>
    </div>
  );
}

function RequirementReviewPreview({ rows }: { rows: RequirementReviewRow[] }) {
  const { t } = useI18n();
  return (
    <div className="min-h-0 flex-1 overflow-y-auto p-3">
      {rows.length === 0 ? (
        <div className="flex min-h-0 flex-1 items-center justify-center p-4 text-sm text-slate-500">
          {t.noUserRequirements}
        </div>
      ) : (
        <div className="space-y-2">
          {rows.map((row) => (
            <div
              key={row.id}
              draggable
              className="rounded-control border border-gray-200 bg-white p-3 cursor-grab active:cursor-grabbing"
              onDragStart={(event) =>
                handleMentionDragStart(event, "requirements", row.id)
              }
              title={t.dragReferenceTitle(row.id)}
            >
              <div className="mb-2 flex items-center justify-between gap-3">
                <div className="text-xs font-semibold text-slate-400">
                  {row.id}
                </div>
                {row.sourceId && (
                  <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-500">
                    {row.sourceId}
                  </span>
                )}
              </div>
              <p className="text-sm leading-relaxed text-slate-800">
                {row.text}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function RequirementReviewEditor({
  rows,
  saving,
  showValidation,
  onChange,
}: {
  rows: RequirementReviewRow[];
  saving?: boolean;
  showValidation?: boolean;
  onChange: (rows: RequirementReviewRow[]) => void;
}) {
  const { t } = useI18n();
  const updateText = (index: number, value: string) => {
    onChange(
      rows.map((row, currentIndex) =>
        currentIndex === index ? { ...row, text: value } : row,
      ),
    );
  };

  return (
    <div className="min-h-0 flex-1 overflow-y-auto p-3">
      {rows.length === 0 ? (
        <div className="flex min-h-0 flex-1 items-center justify-center p-4 text-sm text-slate-500">
          {t.noEditableRequirements}
        </div>
      ) : (
        <div className="space-y-2">
          {rows.map((row, index) => {
            const empty = !row.text.trim();
            return (
              <label
                key={row.id}
                className="block rounded-control border border-gray-200 bg-white p-3"
              >
                <div className="mb-2 flex items-center justify-between gap-3">
                  <div className="text-xs font-semibold text-slate-400">
                    {row.id}
                  </div>
                  {row.sourceId && (
                    <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-500">
                      {row.sourceId}
                    </span>
                  )}
                </div>
                <textarea
                  className={cn(
                    "min-h-24 w-full resize-none rounded-control border bg-white px-2.5 py-2 text-sm leading-relaxed text-slate-800 focus:outline-none focus:ring-2",
                    showValidation && empty
                      ? "border-red-300 focus:border-red-400 focus:ring-red-100"
                      : "border-gray-200 focus:border-slate-400 focus:ring-slate-200",
                  )}
                  disabled={saving}
                  value={row.text}
                  onChange={(event) => updateText(index, event.target.value)}
                />
                {showValidation && empty && (
                  <span className="mt-1 block text-xs font-medium text-red-600">
                    {t.requiredField}
                  </span>
                )}
              </label>
            );
          })}
        </div>
      )}
    </div>
  );
}

function AgentIssueProposalPreview({ rows }: { rows: AgentIssueProposalRow[] }) {
  const { t } = useI18n();
  return (
    <div className="min-h-0 flex-1 overflow-y-auto p-3">
      {rows.length === 0 ? (
        <div className="flex min-h-0 flex-1 items-center justify-center p-4 text-sm text-slate-500">
          {t.noAgentIssues}
        </div>
      ) : (
        <div className="space-y-2">
          {rows.map((row) => (
            <div
              key={row.id}
              className="rounded-control border border-gray-200 bg-white p-3"
            >
              <div className="mb-2 flex min-w-0 flex-wrap items-center gap-2">
                <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-semibold text-slate-500">
                  {t.proposedBy}: {row.agent}
                </span>
                {row.id && (
                  <span className="text-[11px] font-medium text-slate-400">
                    {row.id}
                  </span>
                )}
              </div>
              <div className="text-sm font-semibold leading-relaxed text-slate-900">
                {row.title}
              </div>
              {row.detail && (
                <p className="mt-2 text-sm leading-relaxed text-slate-600">
                  {row.detail}
                </p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ModelDualView({
  projectId,
  sourcePath,
  imagePath,
  title,
  tab,
  onTabChange,
}: {
  projectId: string;
  sourcePath?: string;
  imagePath?: string;
  title: string;
  tab: "diagram" | "source";
  onTabChange: (tab: "diagram" | "source") => void;
}) {
  const { t } = useI18n();

  const source = useQuery({
    queryKey: ["file", projectId, sourcePath],
    queryFn: () => fetchFile(projectId, sourcePath!),
    enabled: !!sourcePath,
    retry: false,
  });

  const image = useQuery({
    queryKey: ["file", projectId, imagePath],
    queryFn: () => fetchFile(projectId, imagePath!),
    enabled: !!imagePath,
    retry: false,
  });

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex shrink-0 gap-1 border-b border-gray-100 px-3 py-2">
        <button
          type="button"
          className={cn(
            "rounded-control px-2.5 py-1 text-xs font-medium",
            tab === "diagram"
              ? "bg-slate-900 text-white"
              : "text-slate-600 hover:bg-gray-100",
          )}
          onClick={() => onTabChange("diagram")}
        >
          {t.model}
        </button>
        <button
          type="button"
          className={cn(
            "rounded-control px-2.5 py-1 text-xs font-medium",
            tab === "source"
              ? "bg-slate-900 text-white"
              : "text-slate-600 hover:bg-gray-100",
          )}
          onClick={() => onTabChange("source")}
        >
          PlantUML
        </button>
      </div>

      {tab === "diagram" ? (
        <div className="flex flex-1 items-center justify-center overflow-auto p-4">
          {!imagePath ? (
            <p className="text-sm text-slate-500">{t.graphPreviewUnavailable}</p>
          ) : image.isLoading ? (
            <p className="text-sm text-slate-500">{t.loadingModel}</p>
          ) : image.data?.content ? (
            <img
              src={`data:${image.data.mime ?? "image/png"};base64,${image.data.content}`}
              alt={title}
              className="max-h-full max-w-full rounded-control object-contain"
            />
          ) : (
            <p className="text-sm text-slate-500">{t.graphPreviewUnavailable}</p>
          )}
        </div>
      ) : (
        <pre className="min-h-0 flex-1 overflow-auto p-4 font-mono text-xs leading-relaxed text-slate-700">
          {!sourcePath
            ? t.noPlantUml
            : source.isLoading
              ? t.loading
              : (source.data?.content ?? t.unableLoadPlantUml)}
        </pre>
      )}
    </div>
  );
}

function stripMarkdownAnchors(value: string) {
  return value.replace(/<span\b[^>]*id=["'][^"']+["'][^>]*>\s*<\/span>/gi, "");
}

function stripMarkdownHtmlArtifacts(value: string) {
  return value
    .replace(/<!-- plant-toc:start -->[\s\S]*?<!-- plant-toc:end -->/gi, " ")
    .replace(/<!--[\s\S]*?-->/g, " ")
    .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, " ")
    .replace(/<style\b[^>]*>[\s\S]*?<\/style>/gi, " ")
    .replace(/<div\b[^>]*class=["'][^"']*\bdr-trace-modal\b[^"']*["'][^>]*>[\s\S]*?<\/div>\s*<\/div>/gi, " ")
    .replace(/<div\b[^>]*class=["'][^"']*\bdr-trace-topology\b[^"']*["'][^>]*>[\s\S]*?<\/svg>\s*<\/div>\s*<\/div>/gi, " ");
}

function stripMarkdownHtmlTags(value: string) {
  return value
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

function stripMarkdownInlineToc(value: string) {
  const lines = value.split(/\r?\n/);
  const out: string[] = [];
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    const heading = /^(#{1,6})\s+(目錄|Table of Contents)\s*$/i.exec(line.trim());
    if (!heading) {
      out.push(line);
      continue;
    }

    index += 1;
    while (index < lines.length) {
      const current = lines[index];
      const trimmed = current.trim();
      if (/^#{1,6}\s+/.test(trimmed)) {
        index -= 1;
        break;
      }
      if (
        trimmed &&
        !/^[-*+]\s+/.test(trimmed) &&
        !/^\d+[.)]\s+/.test(trimmed) &&
        !/^\[[^\]]+\]\([^)]+\)/.test(trimmed)
      ) {
        index -= 1;
        break;
      }
      index += 1;
    }
  }
  return out.join("\n");
}

function cleanMarkdownForPreview(value: string) {
  return stripMarkdownInlineToc(stripMarkdownHtmlTags(stripMarkdownAnchors(stripMarkdownHtmlArtifacts(value))))
    .replace(/^#{4}\s+Topology\s*\n+(?=^#{1,6}\s+|^---\s*$|\s*$)/gm, "")
    .replace(/\n{4,}/g, "\n\n\n")
    .trim();
}

function markdownHeadingItems(value: string): TocItem[] {
  return cleanMarkdownForPreview(value)
    .split(/\r?\n/)
    .map((line, index) => {
      const match = /^(#{1,4})\s+(.+?)\s*$/.exec(line.trim());
      if (!match) return null;
      return {
        id: `markdown-heading-${index + 1}`,
        text: match[2]
          .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
          .replace(/\*\*(.*?)\*\*/g, "$1")
          .replace(/`([^`]+)`/g, "$1")
          .trim(),
        level: match[1].length,
      };
    })
    .filter((item): item is TocItem => !!item && !!item.text);
}

function MarkdownPreview({
  projectId,
  selectedPath,
  content,
  onHeadings,
  contentRef,
}: {
  projectId: string;
  selectedPath: string;
  content: string;
  onHeadings: (items: TocItem[]) => void;
  contentRef: RefObject<HTMLDivElement>;
}) {
  const headings = useMemo(() => markdownHeadingItems(content), [content]);

  useEffect(() => {
    onHeadings(headings.filter((item) => item.level > 1));
  }, [headings, onHeadings]);

  let headingIndex = 0;
  const safeHref = (href?: string) => {
    const value = String(href ?? "").trim();
    if (!value) return undefined;
    if (/^(https?:|mailto:|#|\/)/i.test(value)) return value;
    if (/^[A-Za-z0-9._~!$&'()*+,;=:@/%-]+$/i.test(value) && !/^\w+:/i.test(value)) {
      return value;
    }
    return undefined;
  };

  return (
    <div ref={contentRef} className="min-h-0 flex-1 overflow-y-auto bg-slate-50/50 p-5">
      <div className="markdown-body max-w-none text-slate-800">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            h1: ({ children }) => {
              const item = headings[headingIndex++];
              return <h1 id={item?.id}>{children}</h1>;
            },
            h2: ({ children }) => {
              const item = headings[headingIndex++];
              return <h2 id={item?.id}>{children}</h2>;
            },
            h3: ({ children }) => {
              const item = headings[headingIndex++];
              return <h3 id={item?.id}>{children}</h3>;
            },
            h4: ({ children }) => {
              const item = headings[headingIndex++];
              return <h4 id={item?.id}>{children}</h4>;
            },
            h5: ({ children }) => <h5>{children}</h5>,
            h6: ({ children }) => <h6>{children}</h6>,
            a: ({ href, children }) => (
              <a href={safeHref(href)} target="_blank" rel="noopener noreferrer">
                {children}
              </a>
            ),
            blockquote: ({ children }) => <blockquote>{children}</blockquote>,
            pre: ({ children }) => <pre>{children}</pre>,
            code: ({ children, className }) => {
              const inline = !className;
              return inline ? <code>{children}</code> : <code className={className}>{children}</code>;
            },
            ul: ({ children }) => <ul>{children}</ul>,
            ol: ({ children }) => <ol>{children}</ol>,
            li: ({ children }) => <li>{children}</li>,
            table: ({ children }) => (
              <div className="my-3 overflow-x-auto rounded-control border border-gray-200">
                <table className="min-w-full border-collapse text-sm">
                  {children}
                </table>
              </div>
            ),
            th: ({ children }) => (
              <th className="border-b border-r border-gray-200 bg-slate-50 px-3 py-2 text-left font-semibold text-slate-700 last:border-r-0">
                {children}
              </th>
            ),
            td: ({ children }) => (
              <td className="break-words border-b border-r border-gray-100 px-3 py-2 align-top leading-relaxed last:border-r-0">
                {children}
              </td>
            ),
            img: ({ src, alt }) => (
              <MarkdownImage
                projectId={projectId}
                selectedPath={selectedPath}
                src={src}
                alt={alt}
              />
            ),
          }}
        >
          {cleanMarkdownForPreview(content)}
        </ReactMarkdown>
      </div>
    </div>
  );
}

function normalizeMarkdownImagePath(selectedPath: string, src?: string) {
  const raw = String(src ?? "").trim();
  if (!raw || /^(https?:|data:|blob:|javascript:)/i.test(raw)) return "";
  const cleaned = raw.split("#")[0].split("?")[0];
  const fileName = decodeURIComponent(cleaned.split("/").pop() ?? cleaned);
  if (!fileName) return raw;
  if (/\.(png|jpe?g|gif|webp|svg)$/i.test(fileName)) {
    return `artifact/models/${fileName}`;
  }
  const baseDir = selectedPath.split("/").slice(0, -1).join("/");
  return `${baseDir}/${cleaned}`.replace(/\/\.\//g, "/");
}

function MarkdownImage({
  projectId,
  selectedPath,
  src,
  alt,
}: {
  projectId: string;
  selectedPath: string;
  src?: string;
  alt?: string;
}) {
  const { t } = useI18n();
  const resolvedPath = normalizeMarkdownImagePath(selectedPath, src);
  const image = useQuery({
    queryKey: ["markdown-image", projectId, selectedPath, src],
    queryFn: () => fetchFile(projectId, resolvedPath),
    enabled: !!projectId && !!resolvedPath,
    retry: false,
  });

  if (image.isLoading) {
    return (
      <div className="my-3 rounded-control border border-gray-200 bg-slate-50 px-3 py-6 text-center text-sm text-slate-500">
        {t.loadingImage}
      </div>
    );
  }

  if (!image.data?.content || image.data.type !== "image") {
    return (
      <div className="my-3 rounded-control border border-gray-200 bg-slate-50 px-3 py-6 text-center text-sm text-slate-500">
        {t.unableLoadImage(alt || src || "")}
      </div>
    );
  }

  return (
    <figure className="my-4 rounded-control border border-gray-200 bg-white p-3">
      <img
        src={`data:${image.data.mime ?? "image/png"};base64,${image.data.content}`}
        alt={alt ?? ""}
        className="mx-auto max-h-[560px] max-w-full object-contain"
      />
      {alt && (
        <figcaption className="mt-2 text-center text-xs text-slate-500">{alt}</figcaption>
      )}
    </figure>
  );
}

export function ResultPreview({ projectId, items }: ResultPreviewProps) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const selectedOutputPath = useUiStore((s) => s.selectedOutputPath);
  const selectedOutputAnchor = useUiStore((s) => s.selectedOutputAnchor);
  const setSelectedOutputPath = useUiStore((s) => s.setSelectedOutputPath);
  const scopeReviewDrafts = useUiStore((s) => s.scopeReviewDrafts);
  const setScopeReviewDraft = useUiStore((s) => s.setScopeReviewDraft);
  const clearScopeReviewDraft = useUiStore((s) => s.clearScopeReviewDraft);
  const autoFollowOutput = useUiStore((s) => s.autoFollowOutput);
  const manualOutputLock = useUiStore((s) => s.manualOutputLock);
  const currentAutoOutputPath = useUiStore((s) => s.currentAutoOutputPath);
  const resumeOutputAutoFollow = useUiStore((s) => s.resumeOutputAutoFollow);
  const setScrollTargetMessageId = useUiStore((s) => s.setScrollTargetMessageId);
  const messages = useChatStore((s) => s.messages);
  const pushNotice = useNoticeStore((s) => s.pushNotice);
  const { activeRun } = useActiveRun(projectId);
  const headerActionsRef = useRef<HTMLDivElement>(null);
  const headerPickerRef = useRef<HTMLDivElement>(null);
  const tocMenuRef = useRef<HTMLDivElement>(null);
  const downloadMenuRef = useRef<HTMLDivElement>(null);
  const actionMenuRef = useRef<HTMLDivElement>(null);
  const panelMeasureRef = useRef<HTMLDivElement>(null);
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const markdownContentRef = useRef<HTMLDivElement>(null);
  const domainAutoFollowDecisionRef = useRef<string | null>(null);
  const [controlsStacked, setControlsStacked] = useState(false);
  const [controlsNarrow, setControlsNarrow] = useState(false);
  const [tocOpen, setTocOpen] = useState(false);
  const [traceDetail, setTraceDetail] = useState<TraceDetail | null>(null);
  const traceDetailHasFeedbackTable = Boolean(
    traceDetail?.html.includes("dr-trace-feedback-table"),
  );
  const [downloadMenuOpen, setDownloadMenuOpen] = useState(false);
  const [actionMenuOpen, setActionMenuOpen] = useState(false);
  const [downloadError, setDownloadError] = useState("");
  const [downloadPending, setDownloadPending] = useState(false);
  const [modelViewTab, setModelViewTab] = useState<"diagram" | "source">("diagram");
  const [tocItems, setTocItems] = useState<TocItem[]>([]);
  const [pendingHtmlHash, setPendingHtmlHash] = useState<string | null>(null);
  const [statementDrafts, setStatementDrafts] = useState<StakeholderStatementDraft[]>([]);
  const [statementEditing, setStatementEditing] = useState(false);
  const [requirementDrafts, setRequirementDrafts] = useState<RequirementReviewRow[]>([]);
  const [requirementEditing, setRequirementEditing] = useState(false);
  const stakeholderReviewDecision =
    activeRun?.status === "waiting_for_human" &&
    activeRun.pending_decision?.kind === "stakeholder_statement_review"
      ? activeRun.pending_decision
      : null;
  const requirementsReviewDecision =
    activeRun?.status === "waiting_for_human" &&
    activeRun.pending_decision?.kind === "requirements_review"
      ? activeRun.pending_decision
      : null;
  const domainResearchReviewDecision =
    activeRun?.status === "waiting_for_human" &&
    activeRun.pending_decision?.kind === "domain_research_review"
      ? activeRun.pending_decision
      : null;
  const meetingIssueProposalDecision =
    activeRun?.status === "waiting_for_human" &&
    activeRun.pending_decision?.kind === "meeting_issue_proposal_review"
      ? activeRun.pending_decision
      : null;
  const scopeReviewDecision =
    activeRun?.status === "waiting_for_human" &&
    activeRun.pending_decision?.kind === "scope_review"
      ? activeRun.pending_decision
      : null;
  const originalScopeDraft = useMemo(
    () => scopeReviewDraftFromDecision(scopeReviewDecision),
    [scopeReviewDecision],
  );
  const scopeDraft =
    scopeReviewDecision
      ? scopeReviewDrafts[scopeReviewDecision.id] ?? originalScopeDraft
      : emptyScopeDraft;
  const requirementRows = useMemo(
    () => requirementReviewRows(requirementsReviewDecision),
    [requirementsReviewDecision],
  );
  const meetingIssueProposalRows = useMemo(
    () => parseMeetingIssueProposalRows(meetingIssueProposalDecision, t),
    [meetingIssueProposalDecision, t],
  );

  const files = useMemo(() => buildOutputFiles(items), [items]);
  const availablePaths = useMemo(
    () => new Set(items.filter((item) => item.kind === "file").map((item) => item.path)),
    [items],
  );
  const fileMeta = files.find((f) => f.path === selectedOutputPath);
  const title = fileMeta?.label ?? "";
  const modelPair = fileMeta ? findModelPair(files, fileMeta) : {};
  const isModelArtifact =
    fileMeta?.modelBase &&
    (fileMeta.kind === "plantuml" || fileMeta.kind === "image");
  useEffect(() => {
    if (!isModelArtifact) return;
    setModelViewTab(modelPair.image ? "diagram" : "source");
  }, [isModelArtifact, modelPair.image, selectedOutputPath]);
  const isHtmlArtifact = fileMeta?.kind === "html";
  const isMarkdownArtifact = fileMeta?.kind === "markdown";
  const isGeneratedDocumentArtifact =
    !!selectedOutputPath &&
    /^results\/(srs|design_rationale)\.html$/i.test(selectedOutputPath);
  const showToc =
    !!selectedOutputPath &&
    ((isHtmlArtifact &&
      (/^results\/(srs|design_rationale)\.html$/i.test(selectedOutputPath) ||
        /^results\/drafts\/draft_v\d+\.html$/i.test(selectedOutputPath))) ||
      (isMarkdownArtifact &&
        (/^output\/(srs|design_rationale)\.md$/i.test(selectedOutputPath) ||
          /^artifact\/drafts\/draft_v\d+\.md$/i.test(selectedOutputPath))));
  const relatedMessageId = useMemo(() => {
    if (!selectedOutputPath) return null;
    const direct = messages.find((msg) => msg.outputPath === selectedOutputPath);
    if (direct) return direct.id;
    const selectedFile = files.find((file) => file.path === selectedOutputPath);
    if (selectedFile) {
      const related = messages.find((msg) => {
        if (!msg.outputPath) return false;
        return resolvePreferredOutputPath(msg.outputPath, files) === selectedFile.path;
      });
      if (related) return related.id;
    }
    if (/^artifact\/models\/.+\.(png|svg)$/i.test(selectedOutputPath)) {
      return (
        messages.find((msg) => /^artifact\/models\/.+\.(png|svg)$/i.test(msg.outputPath ?? ""))
          ?.id ?? null
      );
    }
    if (/^results\/MoM\/.+\.html$/i.test(selectedOutputPath)) {
      return messages.find((msg) => /^results\/MoM\/.+\.html$/i.test(msg.outputPath ?? ""))?.id ?? null;
    }
    return null;
  }, [files, messages, selectedOutputPath]);

  const file = useQuery({
    queryKey: ["file", projectId, selectedOutputPath],
    queryFn: () => fetchFile(projectId!, selectedOutputPath!),
    enabled:
      !!projectId && !!selectedOutputPath && !!fileMeta && !isModelArtifact && !isHtmlArtifact,
    placeholderData: (previous) => previous,
    retry: false,
  });
  const sharedDecisionMutationKey = decisionMutationKey(
    activeRun?.run_id,
    activeRun?.pending_decision?.id,
  );
  const decisionSubmissionsPending = useIsMutating({ mutationKey: sharedDecisionMutationKey });
  const statementEditMut = useMutation({
    mutationKey: sharedDecisionMutationKey,
    mutationFn: (stakeholders: StakeholderStatementDraft[]) => {
      if (!activeRun?.pending_decision) throw new Error(t.noEditableHumanIntervention);
      return submitDecision(activeRun.run_id, activeRun.pending_decision.id, {
        action: "direct_edit",
        stakeholders: stakeholders.map((row) => ({
          name: row.name,
          type: row.type,
          text: row.text
            .map((line) => ({
              id: line.id,
              text: line.text.trim(),
            }))
            .filter((line) => line.text),
        })),
      });
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["runs"] });
      await queryClient.invalidateQueries({ queryKey: ["run"] });
      await queryClient.invalidateQueries({ queryKey: ["artifacts", projectId] });
      await queryClient.invalidateQueries({ queryKey: ["file", projectId, "artifact/project.json"] });
    },
    onError: (error) => {
      pushNotice({
        tone: "error",
        title: t.directEditFailed,
        message: errorMessage(error, t.directEditFailed),
      });
    },
  });
  const requirementEditMut = useMutation({
    mutationKey: sharedDecisionMutationKey,
    mutationFn: (rows: RequirementReviewRow[]) => {
      if (!activeRun?.pending_decision) throw new Error(t.noEditableHumanIntervention);
      return submitDecision(activeRun.run_id, activeRun.pending_decision.id, {
        action: "direct_edit",
        requirements: rows
          .map((row) => ({
            ...row.raw,
            id: row.id,
            text: row.text.trim(),
          }))
          .filter((row) => row.text),
      });
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["runs"] });
      await queryClient.invalidateQueries({ queryKey: ["run"] });
      await queryClient.invalidateQueries({ queryKey: ["artifacts", projectId] });
      await queryClient.invalidateQueries({ queryKey: ["file", projectId, "artifact/project.json"] });
      await queryClient.invalidateQueries({ queryKey: ["file", projectId, "artifact/requirements.json"] });
    },
    onError: (error) => {
      pushNotice({
        tone: "error",
        title: t.directEditFailed,
        message: errorMessage(error, t.directEditFailed),
      });
    },
  });

  const fileData = file.data?.path === selectedOutputPath ? file.data : undefined;
  const content = fileData?.content ?? "";
  const fileLoading = !isHtmlArtifact && !isModelArtifact && !fileData && file.isFetching;
  const htmlPreviewUrl =
    projectId && selectedOutputPath?.startsWith("results/")
      ? manualFileUrl(projectId, selectedOutputPath)
      : null;
  const normalizeModelImagePathsForDownload = (html: string) => {
    const imageFiles = files.filter(
      (item) => item.kind === "image" && /(?:^|\/)models\//i.test(item.path),
    );
    if (imageFiles.length === 0) return html;

    const replacements = new Map<string, string>();
    imageFiles.forEach((item) => {
      const fileName = filenameFromPath(item.path);
      replacements.set(fileName, `./models/${fileName}`);
    });

    const inlineReferences = (source: string) => {
      const reference = /(?:https?:\/\/[^"'<>\s]+)?(?:[\\/][^"'<>\s]*)?[\\/]models[\\/]([^"'<>?\\/\s]+)(?:\?[^"'<>\s]*)?|(?:\.\.[\\/]|\.[\\/])?models[\\/]([^"'<>?\\/\s]+)(?:\?[^"'<>\s]*)?/g;
      return source.replace(reference, (original, absoluteName: string, relativeName: string) => {
        const encodedName = absoluteName || relativeName || "";
        let fileName = encodedName;
        try {
          fileName = decodeURIComponent(encodedName);
        } catch {
          // Keep the raw filename when it is not valid URL encoding.
        }
        return replacements.get(fileName) ?? original;
      });
    };

    let standalone = inlineReferences(html);
    standalone = standalone.replace(
      /data-trace-content-b64="([^"]*)"/g,
      (attribute, encoded: string) => {
        const decoded = decodeTraceContent(encoded);
        if (!decoded) return attribute;
        const inlined = inlineReferences(decoded);
        return `data-trace-content-b64="${encodeTraceContent(inlined)}"`;
      },
    );
    standalone = standalone
      .replaceAll(`/${projectId}/manual/srs`, "srs.html")
      .replaceAll(`/${projectId}/manual/dr`, "design_rationale.html");
    return standalone;
  };
  const downloadArtifactPath = async (path: string, format: DownloadFormat) => {
    if (!projectId) return;
    const sourcePath = downloadPathForFormat(path, availablePaths, format);
    const data = await fetchFile(projectId, sourcePath);
    if (format === "html" && data.encoding !== "base64" && /\.html$/i.test(sourcePath)) {
      const offlineHtml = normalizeModelImagePathsForDownload(data.content);
      downloadBlob({ ...data, content: offlineHtml }, filenameFromPath(sourcePath));
      return;
    }
    downloadBlob(fileContentForDownload(data, sourcePath), filenameFromPath(sourcePath));
  };
  const zipEntryForPath = async (path: string, format: DownloadFormat) => {
    if (!projectId) return null;
    const sourcePath = downloadPathForFormat(path, availablePaths, format);
    const data = await fetchFile(projectId, sourcePath);
    const modelMatch = /^artifact\/models\/(.+\.png)$/i.exec(sourcePath);
    return {
      path: modelMatch ? `models/${modelMatch[1]}` : filenameFromPath(sourcePath),
      bytes: bytesFromFileContentForDownload(data, sourcePath),
    };
  };
  const standaloneHtmlZipEntry = async (path: string) => {
    if (!projectId) return null;
    const sourcePath = downloadHtmlPathForPreview(path, availablePaths);
    if (!/\.html$/i.test(sourcePath)) return null;
    const data = await fetchFile(projectId, sourcePath);
    if (data.encoding === "base64") return null;
    const standaloneHtml = normalizeModelImagePathsForDownload(data.content);
    return {
      path: filenameFromPath(sourcePath),
      bytes: new TextEncoder().encode(standaloneHtml),
    };
  };
  const modelImageZipEntry = async (path: string) => {
    if (!projectId) return null;
    const data = await fetchFile(projectId, path);
    return {
      path: `models/${filenameFromPath(path)}`,
      bytes: bytesFromFileContent(data),
    };
  };
  const downloadTargets = useMemo(() => {
    if (!selectedOutputPath || isModelArtifact) return [];
    const targets = [selectedOutputPath];
    const selectedIsSrs = /(?:^results\/srs\.html$|^output\/srs\.md$)/i.test(selectedOutputPath);
    const selectedIsDraft = /(?:^results\/drafts\/draft_v\d+\.html$|^artifact\/drafts\/draft_v\d+\.md$)/i.test(selectedOutputPath);
    if (selectedIsSrs) {
      const dr =
        files.find((item) => item.path === "results/design_rationale.html") ??
        files.find((item) => item.path === "output/design_rationale.md");
      if (dr && !targets.includes(dr.path)) targets.push(dr.path);
    }
    if (selectedIsSrs || selectedIsDraft) {
      files
        .filter((item) => /^artifact\/models\/.+\.png$/i.test(item.path))
        .forEach((item) => {
          if (!targets.includes(item.path)) targets.push(item.path);
        });
    }
    return targets;
  }, [files, isModelArtifact, selectedOutputPath]);
  const markdownDownloadPath = selectedOutputPath
    ? downloadSourcePathForPreview(selectedOutputPath, availablePaths)
    : "";
  const htmlDownloadPath = selectedOutputPath
    ? downloadHtmlPathForPreview(selectedOutputPath, availablePaths)
    : "";
  const hasMarkdownDownload = !!markdownDownloadPath && /\.md$/i.test(markdownDownloadPath);
  const hasHtmlDownload = !!htmlDownloadPath && /\.html$/i.test(htmlDownloadPath);
  const canChooseDownloadFormat =
    !isModelArtifact &&
    hasMarkdownDownload &&
    hasHtmlDownload &&
    markdownDownloadPath !== htmlDownloadPath;
  const hasDownloadChoices = canChooseDownloadFormat || !!isModelArtifact;
  const defaultDownloadFormat: DownloadFormat = "markdown";
  const downloadTargetsForFormat = (format: DownloadFormat) => {
    if (format === "html" && selectedOutputPath) {
      const htmlPath = downloadHtmlPathForPreview(selectedOutputPath, availablePaths);
      if (/\.html$/i.test(htmlPath)) {
        if (/^results\/srs\.html$/i.test(htmlPath)) {
          const drPath = "results/design_rationale.html";
          return availablePaths.has(drPath) ? [htmlPath, drPath] : [htmlPath];
        }
        return [htmlPath];
      }
    }
    return downloadTargets;
  };
  const runInProgress =
    !!activeRun &&
    ["queued", "running", "cancelling"].includes(activeRun.status);
  const canDownloadOutput =
    !!projectId &&
    !runInProgress &&
    !meetingIssueProposalDecision &&
    (isModelArtifact
      ? !!(modelPair.image?.path || modelPair.source?.path)
      : downloadTargets.length > 0);
  const downloadSelectedOutput = async (format: DownloadFormat = defaultDownloadFormat) => {
    if (!canDownloadOutput || downloadPending) return;
    setDownloadError("");
    setDownloadPending(true);
    try {
      const targets = downloadTargetsForFormat(format);
      const selectedIsSrs =
        !!selectedOutputPath && /(?:^results\/srs\.html$|^output\/srs\.md$)/i.test(selectedOutputPath);
      const selectedIsDraft =
        !!selectedOutputPath && /(?:^results\/drafts\/draft_v\d+\.html$|^artifact\/drafts\/draft_v\d+\.md$)/i.test(selectedOutputPath);
      const selectedIsDr =
        !!selectedOutputPath && /(?:^results\/design_rationale\.html$|^output\/design_rationale\.md$)/i.test(selectedOutputPath);
      if (format === "markdown" && (selectedIsSrs || selectedIsDraft)) {
        const entries = (await Promise.all(targets.map((path) => zipEntryForPath(path, format)))).filter(
          (entry): entry is { path: string; bytes: Uint8Array } => entry !== null,
        );
        const blob = makeZip(entries);
        const url = URL.createObjectURL(blob);
        const draftVersion = /^results\/drafts\/(draft_v\d+)\.html$/i.exec(selectedOutputPath ?? "")?.[1] ??
          /^artifact\/drafts\/(draft_v\d+)\.md$/i.exec(selectedOutputPath ?? "")?.[1] ??
          "draft";
        triggerDownload(url, selectedIsSrs ? "srs.zip" : `${draftVersion}.zip`);
        window.setTimeout(() => URL.revokeObjectURL(url), 1000);
        return;
      }
      if (format === "html" && (selectedIsSrs || selectedIsDraft || selectedIsDr)) {
        const htmlEntries = (await Promise.all(targets.map(standaloneHtmlZipEntry))).filter(
          (entry): entry is { path: string; bytes: Uint8Array } => entry !== null,
        );
        const modelPaths = files
          .filter((item) => item.kind === "image" && /(?:^|\/)models\//i.test(item.path))
          .map((item) => item.path);
        const imageEntries = (await Promise.all(modelPaths.map(modelImageZipEntry))).filter(
          (entry): entry is { path: string; bytes: Uint8Array } => entry !== null,
        );
        const entries = [...htmlEntries, ...imageEntries];
        if (entries.length > 0) {
          const blob = makeZip(entries);
          const url = URL.createObjectURL(blob);
          const draftVersion = /^results\/drafts\/(draft_v\d+)\.html$/i.exec(selectedOutputPath ?? "")?.[1] ??
            /^artifact\/drafts\/(draft_v\d+)\.md$/i.exec(selectedOutputPath ?? "")?.[1] ??
            "draft";
          triggerDownload(
            url,
            selectedIsSrs
              ? "srs-html.zip"
              : selectedIsDr
                ? "design-rationale-html.zip"
                : `${draftVersion}-html.zip`,
          );
          window.setTimeout(() => URL.revokeObjectURL(url), 1000);
          return;
        }
      }
      for (const path of targets) {
        await downloadArtifactPath(path, format);
      }
    } catch (error) {
      setDownloadError(error instanceof Error ? error.message : t.downloadFailed);
      console.error(error);
    } finally {
      setDownloadPending(false);
    }
  };
  const downloadModelOutput = async (kind: "image" | "source") => {
    const path = kind === "image" ? modelPair.image?.path : modelPair.source?.path;
    if (!projectId || !path || runInProgress || downloadPending) return;
    setDownloadError("");
    setDownloadPending(true);
    try {
      const data = await fetchFile(projectId, path);
      downloadBlob(fileContentForDownload(data, path), filenameFromPath(path));
    } catch (error) {
      setDownloadError(errorMessage(error, t.downloadFailed));
    } finally {
      setDownloadPending(false);
    }
  };

  useEffect(() => {
    setTocOpen(false);
    setDownloadMenuOpen(false);
    setActionMenuOpen(false);
    setDownloadError("");
    setTocItems([]);
    setTraceDetail(null);
  }, [selectedOutputPath]);

  useEffect(() => {
    if (!traceDetail) return;
    const handler = (event: KeyboardEvent) => {
      if (event.key === "Escape") setTraceDetail(null);
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [traceDetail]);

  useEffect(() => {
    if (!tocOpen) return;
    const handler = (event: PointerEvent) => {
      if (!tocMenuRef.current?.contains(event.target as Node)) {
        setTocOpen(false);
      }
    };
    document.addEventListener("pointerdown", handler);
    return () => document.removeEventListener("pointerdown", handler);
  }, [tocOpen]);

  useEffect(() => {
    if (!downloadMenuOpen) return;
    const handler = (event: MouseEvent) => {
      if (!downloadMenuRef.current?.contains(event.target as Node)) {
        setDownloadMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [downloadMenuOpen]);

  useEffect(() => {
    if (!actionMenuOpen) return;
    const handler = (event: MouseEvent) => {
      if (!actionMenuRef.current?.contains(event.target as Node)) {
        setActionMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [actionMenuOpen]);

  useEffect(() => {
    setStatementDrafts(stakeholderStatementDrafts(stakeholderReviewDecision, t));
    setStatementEditing(false);
  }, [stakeholderReviewDecision?.id, t]);

  useEffect(() => {
    setRequirementDrafts(requirementRows);
    setRequirementEditing(false);
  }, [requirementsReviewDecision?.id, requirementRows]);

  useEffect(() => {
    if (!scopeReviewDecision) return;
    if (!scopeReviewDrafts[scopeReviewDecision.id]) {
      setScopeReviewDraft(scopeReviewDecision.id, originalScopeDraft);
    }
  }, [
    originalScopeDraft,
    scopeReviewDecision,
    scopeReviewDrafts,
    setScopeReviewDraft,
  ]);

  useEffect(() => {
    return () => {
      if (scopeReviewDecision?.id) {
        clearScopeReviewDraft(scopeReviewDecision.id);
      }
    };
  }, [clearScopeReviewDraft, scopeReviewDecision?.id]);

  useEffect(() => {
    setPendingHtmlHash(null);
  }, [projectId]);

  useEffect(() => {
    if (!selectedOutputPath) return;
    const preferred = resolvePreferredOutputPath(selectedOutputPath, files);
    if (preferred && preferred !== selectedOutputPath) {
      setSelectedOutputPath(preferred, "system");
    }
  }, [files, selectedOutputPath, setSelectedOutputPath]);

  useEffect(() => {
    if (!projectId || !selectedOutputPath || files.length === 0) return;
    if (files.some((file) => file.path === selectedOutputPath)) return;
    const preferred = resolvePreferredOutputPath(selectedOutputPath, files);
    setSelectedOutputPath(preferred ?? files[0].path, "system");
  }, [files, projectId, selectedOutputPath, setSelectedOutputPath]);

  useEffect(() => {
    if (!autoFollowOutput || manualOutputLock || !currentAutoOutputPath) return;
    const preferred = resolvePreferredOutputPath(currentAutoOutputPath, files);
    if (preferred && preferred !== selectedOutputPath) {
      setSelectedOutputPath(preferred, "auto");
    }
  }, [
    autoFollowOutput,
    currentAutoOutputPath,
    files,
    manualOutputLock,
    selectedOutputPath,
    setSelectedOutputPath,
  ]);

  useEffect(() => {
    if (!domainResearchReviewDecision || !autoFollowOutput || manualOutputLock) return;
    const decisionId = domainResearchReviewDecision.id || "";
    if (decisionId && domainAutoFollowDecisionRef.current === decisionId) return;
    const contextPath =
      files.find((file) => file.path === "artifact/requirements.json")?.path ??
      files.find((file) => file.path === "artifact/project.json")?.path;
    if (!contextPath) return;
    domainAutoFollowDecisionRef.current = decisionId;
    if (contextPath !== selectedOutputPath) {
      setSelectedOutputPath(contextPath, "auto");
    }
  }, [
    autoFollowOutput,
    domainResearchReviewDecision,
    files,
    manualOutputLock,
    selectedOutputPath,
    setSelectedOutputPath,
  ]);

  useEffect(() => {
    const measure = panelMeasureRef.current;
    const panel = measure?.closest(".card");
    if (!measure || !panel) return;

    const updateStackedState = () => {
      const panelWidth = panel.getBoundingClientRect().width;
      const nextNarrow = panelWidth < 360;
      setControlsNarrow((current) => (current === nextNarrow ? current : nextNarrow));
      const actionsWidth = headerActionsRef.current?.scrollWidth ?? 0;
      const pickerWidth = headerPickerRef.current?.scrollWidth ?? 0;
      const titleWidth = 72;
      const horizontalPadding = 32;
      const titleGap = 16;
      const titleLeft = panelWidth / 2 - titleWidth / 2;
      const titleRight = panelWidth / 2 + titleWidth / 2;
      const actionsRight = horizontalPadding / 2 + actionsWidth;
      const pickerLeft = panelWidth - horizontalPadding / 2 - pickerWidth;
      const controlsCollideWithTitle =
        (actionsWidth > 0 && actionsRight + titleGap > titleLeft) ||
        (pickerWidth > 0 && pickerLeft - titleGap < titleRight);
      const controlsOverflow =
        actionsWidth + pickerWidth + titleWidth + horizontalPadding + titleGap * 2 >
        panelWidth;
      const nextStacked = controlsCollideWithTitle || controlsOverflow;
      setControlsStacked((current) => (current === nextStacked ? current : nextStacked));
    };

    const observer = new ResizeObserver(() => {
      window.requestAnimationFrame(updateStackedState);
    });
    observer.observe(panel);
    observer.observe(measure);
    updateStackedState();
    return () => observer.disconnect();
  }, [relatedMessageId, showToc, items]);

  const htmlLinkTarget = (href: string) => {
    if (!selectedOutputPath || !href) return null;
    let url: URL;
    try {
      url = new URL(href, window.location.origin);
    } catch {
      return null;
    }
    let targetPath = "";
    const manualPath = projectId ? pathFromManualPreviewUrl(url.pathname, projectId) : null;
    if (url.origin === window.location.origin && manualPath) {
      targetPath = manualPath;
    } else if (url.origin !== window.location.origin) {
      return null;
    } else if (!url.pathname || url.pathname === window.location.pathname) {
      targetPath = selectedOutputPath;
    } else {
      const fileName = decodeURIComponent(url.pathname.split("/").pop() ?? "");
      if (!fileName) return null;
      const baseDir = selectedOutputPath.split("/").slice(0, -1).join("/");
      targetPath = `${baseDir}/${fileName}`.replace(/\/+/g, "/");
    }
    if (!/^results\/.+\.html$/i.test(targetPath)) return null;
    if (!files.some((file) => file.path === targetPath)) return null;
    return {
      path: targetPath,
      hash: url.hash ? decodeURIComponent(url.hash.slice(1)) : "",
    };
  };

  const scrollHtmlToHash = (hash: string | null) => {
    if (!hash) return;
    const doc = iframeRef.current?.contentDocument;
    const target = doc?.getElementById(hash);
    target?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const wireHtmlDocumentLinks = () => {
    const doc = iframeRef.current?.contentDocument;
    if (!doc) return;
    doc.querySelectorAll<HTMLAnchorElement>("a[href]").forEach((link) => {
      link.addEventListener("click", (event) => {
        const target = htmlLinkTarget(link.href);
        if (!target) return;
        event.preventDefault();
        setTocOpen(false);
        if (target.path === selectedOutputPath) {
          scrollHtmlToHash(target.hash);
          return;
        }
        setPendingHtmlHash(target.hash || null);
        setSelectedOutputPath(target.path);
      });
    });
  };

  const blockHtmlDocumentFileDrops = () => {
    const doc = iframeRef.current?.contentDocument;
    if (!doc || doc.documentElement.dataset.fileDropBlocked === "true") return;

    const blockFileDrop = (event: globalThis.DragEvent) => {
      if (!Array.from(event.dataTransfer?.types ?? []).includes("Files")) return;
      event.preventDefault();
      event.stopPropagation();
      if (event.dataTransfer) event.dataTransfer.dropEffect = "none";
    };

    doc.documentElement.dataset.fileDropBlocked = "true";
    doc.addEventListener("dragover", blockFileDrop, true);
    doc.addEventListener("drop", blockFileDrop, true);
  };

  const collectHtmlToc = () => {
    const doc = iframeRef.current?.contentDocument;
    if (!doc) return;
    if (!doc.getElementById("plant-scrollbar-style")) {
      const style = doc.createElement("style");
      style.id = "plant-scrollbar-style";
      style.textContent = `
        * { scrollbar-width: thin; scrollbar-color: transparent transparent; }
        *::-webkit-scrollbar { width: 6px; height: 6px; }
        *::-webkit-scrollbar-track { background: transparent; }
        *::-webkit-scrollbar-thumb { border-radius: 999px; background: transparent; }
        *:hover { scrollbar-color: #cbd5e1 transparent; }
        *:hover::-webkit-scrollbar-thumb { background: #cbd5e1; }
        *::-webkit-scrollbar-thumb:hover { background: #94a3b8; }
      `;
      doc.head.appendChild(style);
    }
    if (doc.documentElement.dataset.parentOutsideClickWired !== "true") {
      doc.documentElement.dataset.parentOutsideClickWired = "true";
      doc.addEventListener("pointerdown", () => {
        document.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
        document.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
        setTocOpen(false);
        setDownloadMenuOpen(false);
        setActionMenuOpen(false);
      });
    }
    if (doc.documentElement.dataset.parentTraceInteractionWired !== "true") {
      doc.documentElement.dataset.parentTraceInteractionWired = "true";
      const openTraceNode = (node: Element) => {
        if ((node.getAttribute("data-trace-type") ?? "") === "Requirement") return;
        const encoded = node.getAttribute("data-trace-content-b64") ?? "";
        const fallback = node.getAttribute("data-trace-content") ?? "";
        const content = decodeTraceContent(encoded, fallback);
        const format = node.getAttribute("data-trace-format") ?? "text";
        const safeSource = format === "html" ? content : `<pre>${escapeTraceText(content)}</pre>`;
        setTraceDetail({
          title:
            node.getAttribute("data-trace-title") ??
            node.getAttribute("data-trace-id") ??
            "",
          html: sanitizeTraceHtml(safeSource, doc.baseURI),
        });
      };
      doc.addEventListener("click", (event) => {
        const target = event.target;
        const node =
          target && typeof (target as Element).closest === "function"
            ? (target as Element).closest(".dr-trace-node")
            : null;
        if (!node) return;
        event.preventDefault();
        openTraceNode(node);
      });
      doc.addEventListener("keydown", (event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        const target = event.target;
        const node =
          target && typeof (target as Element).closest === "function"
            ? (target as Element).closest(".dr-trace-node")
            : null;
        if (!node) return;
        event.preventDefault();
        openTraceNode(node);
      });
    }
    if (!doc.getElementById("plant-artifact-preview-background")) {
      const style = doc.createElement("style");
      style.id = "plant-artifact-preview-background";
      style.textContent = `
        html, body { background: #f8fafc !important; }
        .plant-floating-toc { display: none !important; }
        body.has-floating-toc {
          margin: 24px !important;
          padding-bottom: 0 !important;
        }
        @media (max-width: 1024px) {
          body.has-floating-toc { margin: 16px !important; }
        }
      `;
      doc.head.appendChild(style);
    }
    blockHtmlDocumentFileDrops();
    wireHtmlDocumentLinks();
    if (isGeneratedDocumentArtifact) {
      doc.querySelectorAll("h2").forEach((heading) => {
        if (heading.textContent?.trim() !== "目錄") return;
        heading.hidden = true;
        const tocList = heading.nextElementSibling;
        if (tocList?.tagName.toLowerCase() === "ul") {
          (tocList as HTMLElement).hidden = true;
        }
      });
    }
    const headings = Array.from(doc.querySelectorAll("h2, h3"));
    const items = headings
      .map((heading, index) => {
        const text = heading.textContent?.trim() ?? "";
        if (!text || text === "目錄") return null;
        let id = heading.id;
        if (!id) {
          id = `artifact-heading-${index + 1}`;
          heading.id = id;
        }
        return {
          id,
          text,
          level: Number(heading.tagName.slice(1)),
        };
      })
      .filter((item): item is TocItem => item !== null);
    setTocItems(items);
    scrollHtmlToHash(pendingHtmlHash);
    setPendingHtmlHash(null);
  };

  const scrollToTocItem = (id: string) => {
    if (isMarkdownArtifact) {
      markdownContentRef.current
        ?.querySelector<HTMLElement>(`#${id}`)
        ?.scrollIntoView({ behavior: "smooth", block: "start" });
      setTocOpen(false);
      return;
    }
    const doc = iframeRef.current?.contentDocument;
    const target = doc?.getElementById(id);
    target?.scrollIntoView({ behavior: "smooth", block: "start" });
    setTocOpen(false);
  };

  const tocControl = showToc ? (
    <div ref={tocMenuRef} className="relative">
      <button
        type="button"
        className="rounded-control border border-gray-200 bg-white px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-gray-50"
        onClick={() => {
          setActionMenuOpen(false);
          setDownloadMenuOpen(false);
          setTocOpen((open) => !open);
        }}
      >
        {t.tableOfContents}
      </button>
      {tocOpen && (
        <div className="absolute left-0 top-full z-30 mt-2 max-h-80 w-64 overflow-y-auto rounded-card border border-gray-200 bg-white p-2 shadow-lg">
          {isMarkdownArtifact && file.isLoading ? (
            <p className="px-2 py-3 text-xs text-slate-500">{t.tocLoading}</p>
          ) : tocItems.length === 0 ? (
            <p className="px-2 py-3 text-xs text-slate-500">{t.noToc}</p>
          ) : (
            <div className="space-y-0.5">
              {tocItems.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className={cn(
                    "block w-full rounded-control px-2 py-1.5 text-left text-xs text-slate-700 hover:bg-gray-50",
                    item.level === 2 && "pl-4",
                    item.level === 3 && "pl-6 text-slate-500",
                  )}
                  onClick={() => scrollToTocItem(item.id)}
                >
                  {item.text}
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  ) : null;

  const actionControls = (
    <div
      ref={headerActionsRef}
      className={cn(
        "flex min-w-0 flex-wrap items-center gap-2",
        controlsNarrow && "w-full",
      )}
    >
      {tocControl}
      {manualOutputLock && currentAutoOutputPath && (
        <button
          type="button"
          className="rounded-control border border-amber-200 bg-amber-50 px-2.5 py-1 text-xs font-medium text-amber-700 hover:bg-amber-100"
          onClick={resumeOutputAutoFollow}
          title={t.resumeFollowProgressTitle}
        >
          {t.followProgress}
        </button>
      )}
      {!manualOutputLock && autoFollowOutput && currentAutoOutputPath && (
        <span className="rounded-control border border-emerald-100 bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700">
          {t.following}
        </span>
      )}
      {relatedMessageId && (
        <button
          type="button"
          className="rounded-control border border-gray-200 bg-white px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-gray-50"
          onClick={() => setScrollTargetMessageId(relatedMessageId)}
        >
          {t.backToChat}
        </button>
      )}
    </div>
  );

  const filePicker = (
    <div
      className={cn(
        controlsStacked
          ? "mx-auto w-full max-w-44"
          : controlsNarrow && "w-full",
      )}
    >
      <OutputFilePicker
        projectId={projectId}
        items={items}
        compact={controlsStacked}
      />
    </div>
  );
  const renderDownloadActions = (closeMenu: () => void) => (
    <>
      {isModelArtifact ? (
        <>
          <button
            type="button"
            disabled={!modelPair.image || downloadPending}
            className="flex w-full items-center gap-2 rounded-control px-2 py-2 text-left text-xs font-medium text-slate-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-40"
            onClick={() => {
              closeMenu();
              void downloadModelOutput("image");
            }}
          >
            <Download className="h-3.5 w-3.5" />
            {t.downloadImage}
          </button>
          <button
            type="button"
            disabled={!modelPair.source || downloadPending}
            className="flex w-full items-center gap-2 rounded-control px-2 py-2 text-left text-xs font-medium text-slate-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-40"
            onClick={() => {
              closeMenu();
              void downloadModelOutput("source");
            }}
          >
            <Download className="h-3.5 w-3.5" />
            {t.downloadPlantUml}
          </button>
        </>
      ) : canChooseDownloadFormat ? (
        <>
          <button
            type="button"
            disabled={downloadPending}
            className="flex w-full items-center gap-2 rounded-control px-2 py-2 text-left text-xs font-medium text-slate-700 hover:bg-gray-50"
            onClick={() => {
              closeMenu();
              void downloadSelectedOutput("markdown");
            }}
          >
            <Download className="h-3.5 w-3.5" />
            {t.downloadMarkdown}
          </button>
          <button
            type="button"
            disabled={downloadPending}
            className="flex w-full items-center gap-2 rounded-control px-2 py-2 text-left text-xs font-medium text-slate-700 hover:bg-gray-50"
            onClick={() => {
              closeMenu();
              void downloadSelectedOutput("html");
            }}
          >
            <Download className="h-3.5 w-3.5" />
            {t.downloadHtml}
          </button>
        </>
      ) : (
        <button
          type="button"
          disabled={downloadPending}
          className="flex w-full items-center gap-2 rounded-control px-2 py-2 text-left text-xs font-medium text-slate-700 hover:bg-gray-50"
          onClick={() => {
            closeMenu();
            void downloadSelectedOutput();
          }}
        >
          <Download className="h-3.5 w-3.5" />
          {t.download}
        </button>
      )}
    </>
  );
  const downloadButton = (
    <div ref={downloadMenuRef} className="relative shrink-0">
      <button
        type="button"
        disabled={!canDownloadOutput || downloadPending}
        aria-busy={downloadPending}
        className="inline-flex shrink-0 items-center rounded p-1 text-slate-400 hover:bg-gray-50 hover:text-slate-700 disabled:cursor-not-allowed disabled:opacity-40"
        aria-label={t.downloadResult}
        title={t.downloadResult}
        onClick={() => {
          if (hasDownloadChoices) {
            setTocOpen(false);
            setActionMenuOpen(false);
            setDownloadMenuOpen((open) => !open);
            return;
          }
          void downloadSelectedOutput();
        }}
      >
        <Download className="h-3.5 w-3.5" />
      </button>
      {downloadMenuOpen && canDownloadOutput && hasDownloadChoices && (
        <div className="absolute left-0 top-full z-40 mt-2 w-44 rounded-card border border-gray-200 bg-white p-1 shadow-lg">
          {renderDownloadActions(() => setDownloadMenuOpen(false))}
        </div>
      )}
    </div>
  );
  const filePickerControls = (
    <div
      ref={headerPickerRef}
      className={cn("flex min-w-0 items-center gap-2", controlsStacked && "mx-auto")}
    >
      {!controlsStacked && canDownloadOutput && downloadButton}
      {filePicker}
    </div>
  );
  const hasActionMenu =
    canDownloadOutput ||
    !!relatedMessageId ||
    (manualOutputLock && currentAutoOutputPath);
  const actionMenu = hasActionMenu ? (
    <div ref={actionMenuRef} className="relative">
      <button
        type="button"
        className="inline-flex shrink-0 items-center rounded p-1 text-slate-400 hover:bg-gray-50 hover:text-slate-700"
        aria-label={t.moreOutputActions}
        title={t.more}
        onClick={() => {
          setTocOpen(false);
          setDownloadMenuOpen(false);
          setActionMenuOpen((open) => !open);
        }}
      >
        <MoreHorizontal className="h-3.5 w-3.5" />
      </button>
      {actionMenuOpen && (
        <div className="absolute right-0 top-full z-40 mt-2 w-48 rounded-card border border-gray-200 bg-white p-1 shadow-lg">
          {manualOutputLock && currentAutoOutputPath && (
            <button
              type="button"
              className="block w-full rounded-control px-2 py-2 text-left text-xs font-medium text-amber-700 hover:bg-amber-50"
              onClick={() => {
                resumeOutputAutoFollow();
                setActionMenuOpen(false);
              }}
            >
              {t.followProgress}
            </button>
          )}
          {canDownloadOutput && renderDownloadActions(() => setActionMenuOpen(false))}
          {relatedMessageId && (
            <button
              type="button"
              className="block w-full rounded-control px-2 py-2 text-left text-xs font-medium text-slate-700 hover:bg-gray-50"
              onClick={() => {
                setScrollTargetMessageId(relatedMessageId);
                setActionMenuOpen(false);
              }}
            >
              {t.backToChat}
            </button>
          )}
        </div>
      )}
    </div>
  ) : null;

  if (stakeholderReviewDecision) {
    const hasEmptyStatement = statementDrafts.some((stakeholder) =>
      stakeholder.text.some((line) => !line.text.trim()),
    );
    const resetDrafts = () => {
      setStatementDrafts(stakeholderStatementDrafts(stakeholderReviewDecision, t));
      setStatementEditing(false);
    };
    return (
      <PanelChrome
        title={statementEditing ? t.editing : t.stakeholderStatements}
        centerTitle
        headerClassName="min-h-10 py-2"
        titleClassName="text-base"
        trailing={
          <div className="flex items-center gap-1.5">
            {statementEditing ? (
              <>
                <button
                  type="button"
                  className="inline-flex h-8 items-center gap-1.5 rounded-control bg-slate-900 px-3 text-xs font-medium text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-400"
                  disabled={
                    decisionSubmissionsPending > 0 ||
                    statementDrafts.length === 0 ||
                    hasEmptyStatement
                  }
                  onClick={() => statementEditMut.mutate(statementDrafts)}
                >
                  {decisionSubmissionsPending > 0 && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                  {t.save}
                </button>
                <button
                  type="button"
                  className="h-8 rounded-control border border-gray-200 bg-white px-3 text-xs font-medium text-slate-600 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
                  disabled={decisionSubmissionsPending > 0}
                  onClick={resetDrafts}
                >
                  {t.cancel}
                </button>
              </>
            ) : (
              <button
                type="button"
                className="inline-flex h-8 items-center gap-1.5 rounded-control border border-gray-200 bg-white px-3 text-xs font-medium text-slate-700 hover:bg-gray-50"
                onClick={() => setStatementEditing(true)}
              >
                <Edit3 className="h-3.5 w-3.5" />
                {t.edit}
              </button>
            )}
          </div>
        }
        bodyClassName="flex min-h-0 flex-col"
      >
        {statementEditing ? (
          <StakeholderStatementEditor
            drafts={statementDrafts}
            saving={decisionSubmissionsPending > 0}
            showValidation={hasEmptyStatement}
            onChange={setStatementDrafts}
          />
        ) : (
          <StakeholderStatementPreview drafts={statementDrafts} />
        )}
      </PanelChrome>
    );
  }

  if (scopeReviewDecision) {
    return (
      <PanelChrome
        title={t.requirementScope}
        centerTitle
        headerClassName="min-h-10 py-2"
        titleClassName="text-base"
        bodyClassName="flex min-h-0 flex-col"
      >
        <ScopeReviewEditor
          draft={scopeDraft}
          onChange={(nextDraft) =>
            setScopeReviewDraft(scopeReviewDecision.id, nextDraft)
          }
        />
      </PanelChrome>
    );
  }

  if (requirementsReviewDecision) {
    const hasEmptyRequirement = requirementDrafts.some((row) => !row.text.trim());
    const resetRequirementDrafts = () => {
      setRequirementDrafts(requirementReviewRows(requirementsReviewDecision));
      setRequirementEditing(false);
    };
    return (
      <PanelChrome
        title={requirementEditing ? t.editing : t.userRequirements}
        centerTitle
        headerClassName="min-h-10 py-2"
        titleClassName="text-base"
        trailing={
          <div className="flex items-center gap-1.5">
            {requirementEditing ? (
              <>
                <button
                  type="button"
                  className="inline-flex h-8 items-center gap-1.5 rounded-control bg-slate-900 px-3 text-xs font-medium text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-400"
                  disabled={
                    decisionSubmissionsPending > 0 ||
                    requirementDrafts.length === 0 ||
                    hasEmptyRequirement
                  }
                  onClick={() => requirementEditMut.mutate(requirementDrafts)}
                >
                  {decisionSubmissionsPending > 0 && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                  {t.save}
                </button>
                <button
                  type="button"
                  className="h-8 rounded-control border border-gray-200 bg-white px-3 text-xs font-medium text-slate-600 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
                  disabled={decisionSubmissionsPending > 0}
                  onClick={resetRequirementDrafts}
                >
                  {t.cancel}
                </button>
              </>
            ) : (
              <button
                type="button"
                className="inline-flex h-8 items-center gap-1.5 rounded-control border border-gray-200 bg-white px-3 text-xs font-medium text-slate-700 hover:bg-gray-50"
                onClick={() => setRequirementEditing(true)}
              >
                <Edit3 className="h-3.5 w-3.5" />
                {t.edit}
              </button>
            )}
          </div>
        }
        bodyClassName="flex min-h-0 flex-col"
      >
        {requirementEditing ? (
          <RequirementReviewEditor
            rows={requirementDrafts}
            saving={decisionSubmissionsPending > 0}
            showValidation={hasEmptyRequirement}
            onChange={setRequirementDrafts}
          />
        ) : (
          <RequirementReviewPreview rows={requirementDrafts} />
        )}
      </PanelChrome>
    );
  }

  if (meetingIssueProposalDecision) {
    return (
      <PanelChrome
        title={t.agentIssues}
        centerTitle
        headerClassName="min-h-10 py-2"
        titleClassName="text-base"
        bodyClassName="flex min-h-0 flex-col"
      >
        <AgentIssueProposalPreview rows={meetingIssueProposalRows} />
      </PanelChrome>
    );
  }

  return (
    <>
    <PanelChrome
      title={t.output}
      centerTitle
      headerClassName={cn("min-h-10 py-2", controlsStacked && "border-b-0")}
      titleClassName="text-base"
      actions={controlsStacked ? tocControl : actionControls}
      trailing={controlsStacked ? actionMenu : filePickerControls}
      subheader={
        <>
          <div ref={panelMeasureRef} className="pointer-events-none absolute inset-x-0 top-0 h-0 overflow-hidden opacity-0" />
          {controlsStacked && (
            <div
              className="flex shrink-0 justify-center border-b border-gray-100 px-4 py-2"
            >
              {filePickerControls}
            </div>
          )}
        </>
      }
      bodyClassName="relative flex min-h-0 flex-col bg-slate-50/50"
    >
      {downloadPending && (
        <div
          className="absolute inset-0 z-50 flex items-center justify-center bg-white/75 backdrop-blur-[1px]"
          role="status"
          aria-live="polite"
        >
          <div className="flex items-center gap-2 rounded-control border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-700 shadow-sm">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            <span>{t.downloading}</span>
          </div>
        </div>
      )}
      {downloadError && (
        <div className="shrink-0 border-b border-red-100 bg-red-50 px-4 py-2 text-xs text-red-700">
          {downloadError}
        </div>
      )}
      {!projectId ? (
        <div className="grid min-h-0 flex-1 place-items-center p-4 text-center text-sm text-slate-500">
          {t.noSelectedFile}
        </div>
      ) : !selectedOutputPath ? (
        <div className="grid min-h-0 flex-1 place-items-center p-4 text-center text-sm text-slate-500">
          {t.noSelectedFile}
        </div>
      ) : isModelArtifact ? (
        <ModelDualView
          projectId={projectId}
          title={title}
          tab={modelViewTab}
          onTabChange={setModelViewTab}
          sourcePath={
            modelPair.source?.path ??
            (fileMeta?.kind === "plantuml" ? fileMeta.path : undefined)
          }
          imagePath={
            modelPair.image?.path ??
            (fileMeta?.kind === "image" ? fileMeta.path : undefined)
          }
        />
      ) : fileLoading ? (
        <div className="grid min-h-0 flex-1 place-items-center p-4 text-center text-sm text-slate-500">
          {t.loading}
        </div>
      ) : !fileData && file.isError ? (
        <p className="p-4 text-sm text-slate-500">{t.unableLoadFile}</p>
      ) : isHtmlArtifact || fileData?.type === "html" ? (
        <iframe
          ref={iframeRef}
          title={title || t.artifact}
          src={htmlPreviewUrl ?? undefined}
          sandbox="allow-same-origin allow-downloads"
          onLoad={collectHtmlToc}
          className="min-h-0 flex-1 border-0 bg-slate-50/50"
        />
      ) : fileMeta?.kind === "json" || fileData?.type === "json" ? (
        <JsonArtifactView
          projectId={projectId}
          path={selectedOutputPath ?? ""}
          content={content}
          anchor={selectedOutputAnchor}
        />
      ) : fileMeta?.kind === "image" || fileData?.type === "image" ? (
        <div className="flex flex-1 items-center justify-center overflow-auto p-4">
          {fileData?.content ? (
            <img
              src={`data:${fileData.mime ?? "image/png"};base64,${fileData.content}`}
              alt={title}
              className="max-h-full max-w-full rounded-control object-contain"
            />
          ) : (
            <p className="text-sm text-slate-500">{t.graphPreviewUnavailable}</p>
          )}
        </div>
      ) : isMarkdownArtifact || fileData?.type === "md" ? (
        <MarkdownPreview
          projectId={projectId}
          selectedPath={selectedOutputPath}
          content={content}
          onHeadings={setTocItems}
          contentRef={markdownContentRef}
        />
      ) : (
        <div className="min-h-0 flex-1 overflow-y-auto bg-slate-50/50 p-4">
          <pre className="whitespace-pre-wrap font-mono text-xs leading-relaxed text-slate-700">
            {content}
          </pre>
        </div>
      )}
    </PanelChrome>
    {traceDetail && createPortal(
      <div
        className="fixed inset-0 z-[100] grid place-items-center bg-slate-950/40 p-4"
        role="presentation"
        onMouseDown={(event) => {
          if (event.target === event.currentTarget) setTraceDetail(null);
        }}
      >
        <section
          role="dialog"
          aria-modal="true"
          aria-label={traceDetail.title || t.artifact}
          className={`flex max-h-[min(720px,calc(100vh-32px))] w-full flex-col overflow-hidden rounded-card border border-gray-200 bg-white shadow-2xl ${
            traceDetailHasFeedbackTable ? "max-w-5xl" : "max-w-3xl"
          }`}
        >
          <header className="flex shrink-0 items-start justify-between gap-4 border-b border-gray-100 px-5 py-4">
            <h2 className="text-base font-semibold text-slate-900">{traceDetail.title}</h2>
            <button
              type="button"
              className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-control text-slate-500 hover:bg-gray-100 hover:text-slate-900"
              aria-label={t.close}
              title={t.close}
              onClick={() => setTraceDetail(null)}
            >
              <X className="h-4 w-4" />
            </button>
          </header>
          <div
            className="trace-detail-content prose prose-slate min-h-0 max-w-none flex-1 overflow-auto p-5 text-sm leading-relaxed prose-img:mx-auto prose-img:max-h-[420px] prose-img:rounded-control prose-table:text-xs"
            dangerouslySetInnerHTML={{ __html: traceDetail.html }}
          />
        </section>
      </div>
    , document.body)}
    </>
  );
}
