import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Edit3, Loader2, Minus, MoreHorizontal, Plus } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { DragEvent, RefObject } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { apiUrl } from "@/api/client";
import { fetchFile } from "@/api/projects";
import { submitDecision } from "@/api/runs";
import { PanelChrome } from "@/components/PanelChrome";
import { agentLabel } from "@/constants/agents";
import { JsonArtifactView } from "@/features/output/JsonArtifactView";
import { OutputFilePicker } from "@/features/output/OutputFilePicker";
import { useActiveRun } from "@/hooks/useActiveRun";
import { useChatStore } from "@/stores/chatStore";
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

interface ResultPreviewProps {
  projectId: string | null;
  items: FileTreeNode[];
}

interface TocItem {
  id: string;
  text: string;
  level: number;
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
}

interface AgentIssueProposalRow {
  id: string;
  agent: string;
  title: string;
  detail: string;
}

const emptyScopeDraft: ScopeReviewDraft = {
  in_scope: [],
  out_of_scope: [],
};

const REVIEW_MENTION_DRAG_MIME = "application/x-plant-review-mention";

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

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

function textValue(value: unknown): string {
  return typeof value === "string" ? value.trim() : String(value ?? "").trim();
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

function statementText(value: unknown): string {
  if (typeof value === "string") return value.trim();
  if (!isRecord(value)) return String(value ?? "").trim();
  return (
    textValue(value.text) ||
    textValue(value.statement) ||
    textValue(value.content) ||
    textValue(value.description)
  );
}

function statementId(value: unknown, stakeholderIndex: number, lineIndex: number) {
  if (isRecord(value)) {
    const id =
      textValue(value.id) ||
      textValue(value.statement_id) ||
      textValue(value.source_id);
    if (id) return id;
  }
  return `ST-${stakeholderIndex + 1}-${lineIndex + 1}`;
}

function stakeholderStatementDrafts(decision: NonNullable<ReturnType<typeof useActiveRun>["activeRun"]>["pending_decision"]) {
  if (decision?.kind !== "stakeholder_statement_review") return [];
  const options = isRecord(decision.options) ? decision.options : {};
  const rows = Array.isArray(options.stakeholders) ? options.stakeholders : [];
  return rows.map((row, stakeholderIndex) => {
    const item = isRecord(row) ? row : {};
    const rawLines = Array.isArray(item.text)
      ? item.text
      : textValue(item.text)
        ? [item.text]
        : [];
    return {
      name: textValue(item.name) || `利害關係人 ${stakeholderIndex + 1}`,
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
        text: textValue(item.text) || textValue(item.description),
        sourceId: textValue(item.source_id) || textValue(item.source),
      };
    })
    .filter((row) => row.text);
}

function parseMeetingIssueProposalRows(
  decision: NonNullable<ReturnType<typeof useActiveRun>["activeRun"]>["pending_decision"],
) {
  if (decision?.kind !== "meeting_issue_proposal_review") return [];
  const options = isRecord(decision.options) ? decision.options : {};
  const rows = Array.isArray(options.proposals) ? options.proposals : [];
  return rows
    .map((row, index): AgentIssueProposalRow => {
      const item = isRecord(row) ? row : {};
      const rawAgent =
        textValue(item.proposed_by) ||
        textValue(item.agent) ||
        textValue(item.proposer) ||
        textValue(item.role) ||
        textValue(item.speaker) ||
        "Agent";
      const agent = agentLabel(rawAgent);
      const title =
        textValue(item.issue_title) ||
        textValue(item.title) ||
        textValue(item.issue) ||
        textValue(item.summary) ||
        `議題 ${index + 1}`;
      const detail =
        textValue(item.description) ||
        textValue(item.reason) ||
        textValue(item.rationale) ||
        textValue(item.expect_outcome) ||
        textValue(item.detail);
      return {
        id: textValue(item.issue_id) || textValue(item.id) || `ISSUE-${index + 1}`,
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

function crc32(bytes: Uint8Array) {
  let crc = 0xffffffff;
  for (const byte of bytes) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit += 1) {
      crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1));
    }
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function writeUint16(bytes: number[], value: number) {
  bytes.push(value & 0xff, (value >>> 8) & 0xff);
}

function writeUint32(bytes: number[], value: number) {
  bytes.push(value & 0xff, (value >>> 8) & 0xff, (value >>> 16) & 0xff, (value >>> 24) & 0xff);
}

function appendBytes(target: number[], bytes: Uint8Array) {
  for (const byte of bytes) target.push(byte);
}

function makeZip(entries: Array<{ path: string; bytes: Uint8Array }>) {
  const encoder = new TextEncoder();
  const output: number[] = [];
  const centralDirectory: number[] = [];
  for (const entry of entries) {
    const nameBytes = encoder.encode(entry.path);
    const offset = output.length;
    const crc = crc32(entry.bytes);
    writeUint32(output, 0x04034b50);
    writeUint16(output, 20);
    writeUint16(output, 0);
    writeUint16(output, 0);
    writeUint16(output, 0);
    writeUint16(output, 0);
    writeUint32(output, crc);
    writeUint32(output, entry.bytes.length);
    writeUint32(output, entry.bytes.length);
    writeUint16(output, nameBytes.length);
    writeUint16(output, 0);
    appendBytes(output, nameBytes);
    appendBytes(output, entry.bytes);

    writeUint32(centralDirectory, 0x02014b50);
    writeUint16(centralDirectory, 20);
    writeUint16(centralDirectory, 20);
    writeUint16(centralDirectory, 0);
    writeUint16(centralDirectory, 0);
    writeUint16(centralDirectory, 0);
    writeUint16(centralDirectory, 0);
    writeUint32(centralDirectory, crc);
    writeUint32(centralDirectory, entry.bytes.length);
    writeUint32(centralDirectory, entry.bytes.length);
    writeUint16(centralDirectory, nameBytes.length);
    writeUint16(centralDirectory, 0);
    writeUint16(centralDirectory, 0);
    writeUint16(centralDirectory, 0);
    writeUint16(centralDirectory, 0);
    writeUint32(centralDirectory, 0);
    writeUint32(centralDirectory, offset);
    appendBytes(centralDirectory, nameBytes);
  }
  const centralDirectoryOffset = output.length;
  output.push(...centralDirectory);
  writeUint32(output, 0x06054b50);
  writeUint16(output, 0);
  writeUint16(output, 0);
  writeUint16(output, entries.length);
  writeUint16(output, entries.length);
  writeUint32(output, centralDirectory.length);
  writeUint32(output, centralDirectoryOffset);
  writeUint16(output, 0);
  return new Blob([new Uint8Array(output)], { type: "application/zip" });
}

function bytesFromFileContent(content: FileContent) {
  if (content.encoding === "base64") {
    const binary = window.atob(content.content);
    return Uint8Array.from(binary, (char) => char.charCodeAt(0));
  }
  return new TextEncoder().encode(content.content);
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
          尚無可編輯發言
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
                          "min-h-20 w-full resize-y rounded-control border bg-white px-2.5 py-2 text-sm leading-relaxed text-slate-800 focus:outline-none focus:ring-2",
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
                          不可為空
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
  return (
    <div className="min-h-0 flex-1 overflow-y-auto p-3">
      {drafts.length === 0 ? (
        <div className="flex min-h-0 flex-1 items-center justify-center p-4 text-sm text-slate-500">
          尚無利害關係人發言
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
                    title={`拖曳引用 @${line.id}`}
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
  const [editingItems, setEditingItems] = useState<Record<string, boolean>>({});
  const itemKey = (key: keyof ScopeReviewDraft, index: number) => `${key}-${index}`;
  const updateItem = (key: keyof ScopeReviewDraft, index: number, value: string) => {
    onChange({
      ...draft,
      [key]: draft[key].map((item, currentIndex) =>
        currentIndex === index ? value : item,
      ),
    });
  };
  const addItem = (key: keyof ScopeReviewDraft) => {
    if (draft[key].some((item) => !item.trim())) return;
    const nextIndex = draft[key].length;
    onChange({
      ...draft,
      [key]: [...draft[key], ""],
    });
    setEditingItems((current) => ({ ...current, [itemKey(key, nextIndex)]: true }));
  };
  const removeItem = (key: keyof ScopeReviewDraft, index: number) => {
    onChange({
      ...draft,
      [key]: draft[key].filter((_, currentIndex) => currentIndex !== index),
    });
    setEditingItems((current) => {
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
        ? "輸入需求範圍內"
        : "輸入需求範圍外";
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
          aria-label={`新增${title}`}
          title={canAdd ? "新增" : "請先填寫新增項目"}
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
          draft[key].map((item, index) => (
            <div
              key={`${key}-${index}`}
              className="rounded-control border border-gray-200 bg-white p-2"
            >
              <div className="flex min-h-14 items-center gap-2 rounded-control bg-slate-50 px-3 py-2">
                {editingItems[itemKey(key, index)] ? (
                  <textarea
                    className="min-h-10 flex-1 resize-none border-0 bg-transparent px-0 py-1 text-sm leading-relaxed text-slate-800 outline-none placeholder:text-slate-400 focus:ring-0"
                    value={item}
                    placeholder={placeholder}
                    autoFocus
                    onBlur={() =>
                      setEditingItems((current) => ({
                        ...current,
                        [itemKey(key, index)]: false,
                      }))
                    }
                    onChange={(event) => updateItem(key, index, event.target.value)}
                  />
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
                  onClick={() =>
                    setEditingItems((current) => ({
                      ...current,
                      [itemKey(key, index)]: true,
                    }))
                  }
                  aria-label="編輯此項"
                  title="編輯"
                >
                  <Edit3 className="h-3.5 w-3.5" />
                </button>
                <button
                  type="button"
                  className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-control border border-red-100 bg-white text-red-500 hover:bg-red-50 hover:text-red-600"
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={() => removeItem(key, index)}
                  aria-label="移除此項"
                  title="移除"
                >
                  <Minus className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
          ))
        )}
      </div>
    </section>
    );
  };

  return (
    <div className="min-h-0 flex-1 overflow-y-auto p-3">
      <div className="space-y-3">
        {renderSection("in_scope", "範圍內", "尚無範圍內項目")}
        {renderSection("out_of_scope", "範圍外", "尚無範圍外項目")}
      </div>
    </div>
  );
}

function RequirementReviewPreview({ rows }: { rows: RequirementReviewRow[] }) {
  return (
    <div className="min-h-0 flex-1 overflow-y-auto p-3">
      {rows.length === 0 ? (
        <div className="flex min-h-0 flex-1 items-center justify-center p-4 text-sm text-slate-500">
          尚無使用者需求
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
              title={`拖曳引用 @${row.id}`}
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

function AgentIssueProposalPreview({ rows }: { rows: AgentIssueProposalRow[] }) {
  return (
    <div className="min-h-0 flex-1 overflow-y-auto p-3">
      {rows.length === 0 ? (
        <div className="flex min-h-0 flex-1 items-center justify-center p-4 text-sm text-slate-500">
          尚無 Agent 議題
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
                  提出者：{row.agent}
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
}: {
  projectId: string;
  sourcePath?: string;
  imagePath?: string;
  title: string;
}) {
  const [tab, setTab] = useState<"diagram" | "source">(
    imagePath ? "diagram" : "source",
  );

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
          onClick={() => setTab("diagram")}
        >
          圖表
        </button>
        <button
          type="button"
          className={cn(
            "rounded-control px-2.5 py-1 text-xs font-medium",
            tab === "source"
              ? "bg-slate-900 text-white"
              : "text-slate-600 hover:bg-gray-100",
          )}
          onClick={() => setTab("source")}
        >
          PlantUML
        </button>
      </div>

      {tab === "diagram" ? (
        <div className="flex flex-1 items-center justify-center overflow-auto p-4">
          {!imagePath ? (
            <p className="text-sm text-slate-500">圖形尚無法預覽</p>
          ) : image.isLoading ? (
            <p className="text-sm text-slate-500">載入圖表中…</p>
          ) : image.data?.content ? (
            <img
              src={`data:${image.data.mime ?? "image/png"};base64,${image.data.content}`}
              alt={title}
              className="max-h-full max-w-full rounded-control object-contain"
            />
          ) : (
            <p className="text-sm text-slate-500">圖形尚無法預覽</p>
          )}
        </div>
      ) : (
        <pre className="min-h-0 flex-1 overflow-auto p-4 font-mono text-xs leading-relaxed text-slate-700">
          {!sourcePath
            ? "無 PlantUML"
            : source.isLoading
              ? "載入中…"
              : (source.data?.content ?? "無法載入 PlantUML")}
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
        載入圖片中...
      </div>
    );
  }

  if (!image.data?.content || image.data.type !== "image") {
    return (
      <div className="my-3 rounded-control border border-gray-200 bg-slate-50 px-3 py-6 text-center text-sm text-slate-500">
        圖片無法載入：{alt || src}
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
  const { activeRun } = useActiveRun(projectId);
  const headerActionsRef = useRef<HTMLDivElement>(null);
  const headerPickerRef = useRef<HTMLDivElement>(null);
  const actionMenuRef = useRef<HTMLDivElement>(null);
  const panelMeasureRef = useRef<HTMLDivElement>(null);
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const markdownContentRef = useRef<HTMLDivElement>(null);
  const domainAutoFollowDecisionRef = useRef<string | null>(null);
  const [controlsStacked, setControlsStacked] = useState(false);
  const [controlsNarrow, setControlsNarrow] = useState(false);
  const [tocOpen, setTocOpen] = useState(false);
  const [actionMenuOpen, setActionMenuOpen] = useState(false);
  const [downloadError, setDownloadError] = useState("");
  const [tocItems, setTocItems] = useState<TocItem[]>([]);
  const [pendingHtmlHash, setPendingHtmlHash] = useState<string | null>(null);
  const [statementDrafts, setStatementDrafts] = useState<StakeholderStatementDraft[]>([]);
  const [statementEditing, setStatementEditing] = useState(false);
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
    () => parseMeetingIssueProposalRows(meetingIssueProposalDecision),
    [meetingIssueProposalDecision],
  );

  const files = useMemo(() => buildOutputFiles(items), [items]);
  const fileMeta = files.find((f) => f.path === selectedOutputPath);
  const title = fileMeta?.label ?? "";
  const modelPair = fileMeta ? findModelPair(files, fileMeta) : {};
  const isModelArtifact =
    fileMeta?.modelBase &&
    (fileMeta.kind === "plantuml" || fileMeta.kind === "image");
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
  const statementEditMut = useMutation({
    mutationFn: (stakeholders: StakeholderStatementDraft[]) => {
      if (!activeRun?.pending_decision) throw new Error("沒有可編輯的使用者介入");
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
  });

  const fileData = file.data?.path === selectedOutputPath ? file.data : undefined;
  const content = fileData?.content ?? "";
  const fileLoading = !isHtmlArtifact && !isModelArtifact && !fileData && file.isFetching;
  const htmlPreviewUrl =
    projectId && selectedOutputPath?.startsWith("results/")
      ? apiUrl(
          `/api/projects/${encodeURIComponent(projectId)}/results/${selectedOutputPath
            .slice("results/".length)
            .split("/")
            .map(encodeURIComponent)
            .join("/")}`,
        )
      : null;
  const fileDownloadUrl = (path: string) =>
    projectId && path.startsWith("results/")
      ? apiUrl(
          `/api/projects/${encodeURIComponent(projectId)}/results/${path
            .slice("results/".length)
            .split("/")
            .map(encodeURIComponent)
            .join("/")}`,
        )
      : null;
  const downloadArtifactPath = async (path: string) => {
    if (!projectId) return;
    const htmlUrl = fileDownloadUrl(path);
    if (htmlUrl) {
      triggerDownload(htmlUrl, filenameFromPath(path));
      return;
    }
    const data = await fetchFile(projectId, path);
    downloadBlob(data, filenameFromPath(path));
  };
  const zipEntryForPath = async (path: string) => {
    if (!projectId) return null;
    const data = await fetchFile(projectId, path);
    const modelMatch = /^artifact\/models\/(.+\.png)$/i.exec(path);
    return {
      path: modelMatch ? `models/${modelMatch[1]}` : filenameFromPath(path),
      bytes: bytesFromFileContent(data),
    };
  };
  const downloadTargets = useMemo(() => {
    if (!selectedOutputPath) return [];
    if (isModelArtifact) {
      return [modelPair.image?.path ?? selectedOutputPath];
    }
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
  }, [files, isModelArtifact, modelPair.image?.path, selectedOutputPath]);
  const runInProgress =
    !!activeRun &&
    ["queued", "running", "cancelling"].includes(activeRun.status);
  const canDownloadOutput =
    !!projectId &&
    !runInProgress &&
    !meetingIssueProposalDecision &&
    downloadTargets.length > 0;
  const downloadSelectedOutput = async () => {
    if (!canDownloadOutput) return;
    setDownloadError("");
    try {
      const selectedIsSrs =
        !!selectedOutputPath && /(?:^results\/srs\.html$|^output\/srs\.md$)/i.test(selectedOutputPath);
      const selectedIsDraft =
        !!selectedOutputPath && /(?:^results\/drafts\/draft_v\d+\.html$|^artifact\/drafts\/draft_v\d+\.md$)/i.test(selectedOutputPath);
      if (selectedIsSrs || selectedIsDraft) {
        const entries = (await Promise.all(downloadTargets.map(zipEntryForPath))).filter(
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
      for (const path of downloadTargets) {
        await downloadArtifactPath(path);
      }
    } catch (error) {
      setDownloadError(error instanceof Error ? error.message : "下載失敗");
      console.error(error);
    }
  };

  useEffect(() => {
    setTocOpen(false);
    setActionMenuOpen(false);
    setDownloadError("");
    setTocItems([]);
  }, [selectedOutputPath]);

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
    setStatementDrafts(stakeholderStatementDrafts(stakeholderReviewDecision));
    setStatementEditing(false);
  }, [stakeholderReviewDecision?.id]);

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
    const prefix = projectId
      ? new URL(
          apiUrl(`/api/projects/${encodeURIComponent(projectId)}/results/`),
          window.location.origin,
        )
      : null;
    let targetPath = "";
    if (
      prefix &&
      url.origin === prefix.origin &&
      url.pathname.startsWith(prefix.pathname)
    ) {
      targetPath = `results/${decodeURIComponent(url.pathname.slice(prefix.pathname.length))}`;
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

  const collectHtmlToc = () => {
    const doc = iframeRef.current?.contentDocument;
    if (!doc) return;
    if (!doc.getElementById("plant-artifact-preview-background")) {
      const style = doc.createElement("style");
      style.id = "plant-artifact-preview-background";
      style.textContent = "html, body { background: #f8fafc !important; }";
      doc.head.appendChild(style);
    }
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

  const actionControls = (
    <div
      ref={headerActionsRef}
      className={cn(
        "flex min-w-0 flex-wrap items-center gap-2",
        controlsNarrow && "w-full",
      )}
    >
      {manualOutputLock && currentAutoOutputPath && (
        <button
          type="button"
          className="rounded-control border border-amber-200 bg-amber-50 px-2.5 py-1 text-xs font-medium text-amber-700 hover:bg-amber-100"
          onClick={resumeOutputAutoFollow}
          title="恢復跟隨流程進度產出物"
        >
          跟隨進度
        </button>
      )}
      {!manualOutputLock && autoFollowOutput && currentAutoOutputPath && (
        <span className="rounded-control border border-emerald-100 bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700">
          跟隨中
        </span>
      )}
      {relatedMessageId && (
        <button
          type="button"
          className="rounded-control border border-gray-200 bg-white px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-gray-50"
          onClick={() => setScrollTargetMessageId(relatedMessageId)}
        >
          回到對話
        </button>
      )}
      {showToc && (
        <div className="relative">
          <button
            type="button"
            className="rounded-control border border-gray-200 bg-white px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-gray-50"
            onClick={() => setTocOpen((open) => !open)}
          >
            目錄
          </button>
          {tocOpen && (
            <div className="absolute left-0 top-full z-30 mt-2 max-h-80 w-64 overflow-y-auto rounded-card border border-gray-200 bg-white p-2 shadow-lg">
              {isMarkdownArtifact && file.isLoading ? (
                <p className="px-2 py-3 text-xs text-slate-500">目錄載入中...</p>
              ) : tocItems.length === 0 ? (
                <p className="px-2 py-3 text-xs text-slate-500">尚無目錄</p>
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
  const downloadButton = (
    <button
      type="button"
      disabled={!canDownloadOutput}
      className="inline-flex shrink-0 items-center rounded p-1 text-slate-400 hover:bg-gray-50 hover:text-slate-700 disabled:cursor-not-allowed disabled:opacity-40"
      aria-label="下載結果"
      title="下載結果"
      onClick={() => void downloadSelectedOutput()}
    >
      <Download className="h-3.5 w-3.5" />
    </button>
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
    canDownloadOutput || !!relatedMessageId || (manualOutputLock && currentAutoOutputPath) || showToc;
  const actionMenu = hasActionMenu ? (
    <div ref={actionMenuRef} className="relative">
      <button
        type="button"
        className="inline-flex shrink-0 items-center rounded p-1 text-slate-400 hover:bg-gray-50 hover:text-slate-700"
        aria-label="更多產出物操作"
        title="更多"
        onClick={() => setActionMenuOpen((open) => !open)}
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
              跟隨進度
            </button>
          )}
          {canDownloadOutput && (
            <button
              type="button"
              className="flex w-full items-center gap-2 rounded-control px-2 py-2 text-left text-xs font-medium text-slate-700 hover:bg-gray-50"
              onClick={() => {
                setActionMenuOpen(false);
                void downloadSelectedOutput();
              }}
            >
              <Download className="h-3.5 w-3.5" />
              下載
            </button>
          )}
          {relatedMessageId && (
            <button
              type="button"
              className="block w-full rounded-control px-2 py-2 text-left text-xs font-medium text-slate-700 hover:bg-gray-50"
              onClick={() => {
                setScrollTargetMessageId(relatedMessageId);
                setActionMenuOpen(false);
              }}
            >
              回到對話
            </button>
          )}
          {showToc && (
            <div className="border-t border-gray-100 first:border-t-0">
              <div className="px-2 py-2 text-xs font-medium text-slate-700">
                目錄
              </div>
              <div className="max-h-64 overflow-y-auto">
                {isMarkdownArtifact && file.isLoading ? (
                  <p className="px-2 py-3 text-xs text-slate-500">目錄載入中...</p>
                ) : tocItems.length === 0 ? (
                  <p className="px-2 py-3 text-xs text-slate-500">尚無目錄</p>
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
                        onClick={() => {
                          scrollToTocItem(item.id);
                          setActionMenuOpen(false);
                        }}
                      >
                        {item.text}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
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
      setStatementDrafts(stakeholderStatementDrafts(stakeholderReviewDecision));
      setStatementEditing(false);
    };
    return (
      <PanelChrome
        title={statementEditing ? "編輯中" : "利害關係人發言"}
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
                    statementEditMut.isPending ||
                    statementDrafts.length === 0 ||
                    hasEmptyStatement
                  }
                  onClick={() => statementEditMut.mutate(statementDrafts)}
                >
                  {statementEditMut.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                  儲存
                </button>
                <button
                  type="button"
                  className="h-8 rounded-control border border-gray-200 bg-white px-3 text-xs font-medium text-slate-600 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
                  disabled={statementEditMut.isPending}
                  onClick={resetDrafts}
                >
                  取消
                </button>
              </>
            ) : (
              <button
                type="button"
                className="inline-flex h-8 items-center gap-1.5 rounded-control border border-gray-200 bg-white px-3 text-xs font-medium text-slate-700 hover:bg-gray-50"
                onClick={() => setStatementEditing(true)}
              >
                <Edit3 className="h-3.5 w-3.5" />
                編輯
              </button>
            )}
          </div>
        }
        bodyClassName="flex min-h-0 flex-col"
      >
        {statementEditing ? (
          <StakeholderStatementEditor
            drafts={statementDrafts}
            saving={statementEditMut.isPending}
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
        title="需求範圍"
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
    return (
      <PanelChrome
        title="使用者需求"
        centerTitle
        headerClassName="min-h-10 py-2"
        titleClassName="text-base"
        bodyClassName="flex min-h-0 flex-col"
      >
        <RequirementReviewPreview rows={requirementRows} />
      </PanelChrome>
    );
  }

  if (meetingIssueProposalDecision) {
    return (
      <PanelChrome
        title="Agent 議題"
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
    <PanelChrome
      title="產出物"
      centerTitle
      headerClassName={cn("min-h-10 py-2", controlsStacked && "border-b-0")}
      titleClassName="text-base"
      actions={!controlsStacked && actionControls}
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
      bodyClassName="flex min-h-0 flex-col bg-slate-50/50"
    >
      {downloadError && (
        <div className="shrink-0 border-b border-red-100 bg-red-50 px-4 py-2 text-xs text-red-700">
          {downloadError}
        </div>
      )}
      {!projectId ? (
        <div className="grid min-h-0 flex-1 place-items-center p-4 text-center text-sm text-slate-500">
          未選擇任何檔案
        </div>
      ) : !selectedOutputPath ? (
        <div className="grid min-h-0 flex-1 place-items-center p-4 text-center text-sm text-slate-500">
          未選擇任何檔案
        </div>
      ) : isModelArtifact ? (
        <ModelDualView
          projectId={projectId}
          title={title}
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
          載入中…
        </div>
      ) : !fileData && file.isError ? (
        <p className="p-4 text-sm text-slate-500">無法載入檔案</p>
      ) : isHtmlArtifact || fileData?.type === "html" ? (
        <iframe
          ref={iframeRef}
          title={title || "產出物"}
          src={htmlPreviewUrl ?? undefined}
          sandbox="allow-same-origin"
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
            <p className="text-sm text-slate-500">圖形尚無法預覽</p>
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
  );
}
