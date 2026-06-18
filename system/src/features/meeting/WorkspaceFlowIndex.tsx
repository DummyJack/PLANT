import { useEffect, useMemo, useRef, useState } from "react";
import { ListTree } from "lucide-react";
import { useChatStore } from "@/stores/chatStore";
import { useUiStore } from "@/stores/uiStore";
import type { ChatMessage, FileTreeNode, RunCheckpoint } from "@/types/api";
import { cn } from "@/utils/cn";
import { checkpointCleanupLabel, checkpointStageLabel } from "./RunCheckpointNotice";

interface FlowItem {
  id: string;
  title: string;
  detail: string;
  dedupeKey: string;
  orderHint?: number;
  outputPath?: string;
  scrollTargetId?: string;
  rawTitle?: string;
  tone: "user" | "action" | "decision" | "output" | "designRationale" | "srs" | "status";
}

function snippet(text: string, fallback: string) {
  const compact = text.replace(/\s+/g, " ").trim();
  if (!compact) return fallback;
  return compact.length > 48 ? `${compact.slice(0, 48)}...` : compact;
}

function statusText(status?: ChatMessage["status"]) {
  if (status === "done") return "完成";
  if (status === "failed") return "失敗";
  if (status === "waiting") return "等待你決議";
  return "執行中";
}

function actionKey(value: string) {
  return value.replace(/^(?:[a-z_]+(?:\.\w+_\d+)?\.)+/i, "");
}

function stageTitle(stage?: string) {
  if (!stage) return "";
  const value = stage.toLowerCase();
  if (value === "init") return "初始分析";
  if (value === "elicitation") return "需求擷取會議";
  if (value === "conflict_review") return "衝突辨識";
  if (value === "research_domain") return "領域研究";
  if (value === "system_model") return "系統模型生成";
  if (value === "draft") return "草稿建立";
  if (value === "formal_meeting") return "正式會議";
  if (value === "document_generation") return "規格化";
  if (value === "export") return "輸出整理";
  return "";
}

function actionDisplay(msg: ChatMessage): { title: string; detail: string } {
  const raw = msg.action ?? msg.text;
  const key = actionKey(raw);
  const running = statusText(msg.status);
  const round = /formal_meeting\.round_(\d+)\.run_meeting/i.exec(raw)?.[1];

  const table: Record<string, { title: string; running: string; done: string }> = {
    suggest_stakeholders: {
      title: "選擇利害關係人",
      running: "正在產生候選利害關係人",
      done: "已產生候選利害關係人",
    },
    write_stakeholder_text: {
      title: "利害關係人發言",
      running: "正在整理利害關係人需求",
      done: "已整理利害關係人需求",
    },
    analyze_scenario: {
      title: "分析初始想法",
      running: "正在整理情境與範圍",
      done: "已整理情境與範圍",
    },
    analyze_requirements: {
      title: "初步需求分析",
      running: "正在整理需求候選",
      done: "已整理需求候選",
    },
    generate_scope: {
      title: "定義系統範圍",
      running: "正在整理系統範圍",
      done: "已更新 Scope",
    },
    extract_requirements: {
      title: "需求擷取會議",
      running: "正在擷取使用者需求",
      done: "已擷取使用者需求",
    },
    merge_requirements: {
      title: "整併需求",
      running: "正在整併需求",
      done: "已更新 Requirements",
    },
    run_review: {
      title: "衝突辨識",
      running: "正在辨識需求衝突",
      done: "已辨識需求衝突",
    },
    research_domain: {
      title: "領域研究",
      running: "正在整理領域研究",
      done: "已更新領域研究",
    },
    read_reference_docs: {
      title: "領域研究",
      running: "正在讀取參考文件",
      done: "已讀取參考文件",
    },
    research_issue: {
      title: "領域研究",
      running: "正在研究外部限制與依據",
      done: "已整理研究依據",
    },
    update_feedback: {
      title: "領域研究",
      running: "正在更新領域研究",
      done: "已更新領域研究",
    },
    system_modeling: {
      title: "系統模型生成",
      running: "正在產生系統模型",
      done: "已更新 System Models",
    },
    create_model: {
      title: "系統模型生成",
      running: "正在產生系統模型",
      done: "已更新 System Models",
    },
    update_model: {
      title: "系統模型生成",
      running: "正在更新系統模型",
      done: "已更新 System Models",
    },
    default_update_draft: {
      title: "草稿建立",
      running: "正在更新 Draft",
      done: "已更新 Draft",
    },
    general_update_draft: {
      title: "草稿建立",
      running: "正在依會議結果更新 Draft",
      done: "已更新 Draft",
    },
    generate_dr: {
      title: "Design Rationale",
      running: "正在產生設計緣由",
      done: "已更新 Design Rationale",
    },
    generate_srs: {
      title: "SRS",
      running: "正在產生規格文件",
      done: "已更新 SRS",
    },
  };

  if (round) {
    return {
      title: `第 ${round} 輪會議`,
      detail: `${running}：討論中`,
    };
  }

  const matched = table[key];
  if (matched) {
    return {
      title: matched.title,
      detail: `${running}：${msg.status === "done" ? matched.done : matched.running}`,
    };
  }

  const fallbackTitle = stageTitle(msg.stage) || msg.label || msg.speaker || "Agent 執行";
  return {
    title: fallbackTitle,
    detail: `${running}：${snippet(msg.text, key || "正在處理")}`,
  };
}

function outputLabel(path?: string, text?: string) {
  if (!path) return snippet(text ?? "", "產出物");
  if (/project\.json$/i.test(path)) return "Project";
  if (/scope\.json$/i.test(path)) return "Scope";
  if (/meeting\/elicitation_meeting\.json$/i.test(path)) return "需求擷取會議";
  if (/requirements\.json$/i.test(path)) return "Requirements";
  if (/feedback\.json$/i.test(path)) return "領域研究";
  if (/system_models\.json$/i.test(path)) return "系統模型生成";
  if (/result\.json$/i.test(path)) return "Conflict";
  const draft = /draft_v(\d+)/i.exec(path)?.[1];
  if (draft) return `Draft v${draft}`;
  if (/srs\.(html|md)$/i.test(path)) return "SRS";
  if (/design_rationale\.(html|md)$/i.test(path)) return "Design Rationale";
  if (/models\/.+\.(png|svg|plantuml|puml)$/i.test(path)) return "系統模型生成";
  return snippet(text ?? path, path);
}

function outputTone(label: string): FlowItem["tone"] {
  if (label === "Design Rationale") return "designRationale";
  if (label === "SRS") return "srs";
  return "output";
}

function isPrimaryOutput(path?: string) {
  if (!path) return false;
  return (
    /scope\.json$/i.test(path) ||
    /meeting\/elicitation_meeting\.json$/i.test(path) ||
    /feedback\.json$/i.test(path) ||
    /system_models\.json$/i.test(path) ||
    /draft_v\d+\.(?:md|html)$/i.test(path) ||
    /srs\.(?:html|md)$/i.test(path) ||
    /design_rationale\.(?:html|md)$/i.test(path) ||
    /models\/.+\.(?:png|svg|plantuml|puml)$/i.test(path)
  );
}

function isPrimaryAction(msg: ChatMessage) {
  const raw = msg.action ?? msg.text;
  const key = actionKey(raw);
  return (
    key === "suggest_stakeholders" ||
    key === "write_stakeholder_text" ||
    key === "analyze_requirements" ||
    key === "generate_scope" ||
    key === "extract_requirements" ||
    key === "run_review" ||
    key === "research_domain" ||
    key === "read_reference_docs" ||
    key === "research_issue" ||
    key === "update_feedback" ||
    key === "system_modeling" ||
    key === "create_model" ||
    key === "update_model" ||
    key === "default_update_draft" ||
    key === "general_update_draft" ||
    key === "generate_dr" ||
    key === "generate_srs" ||
    /^formal_meeting\.round_\d+\.run_meeting$/i.test(raw)
  );
}

function decisionDetail(msg: ChatMessage) {
  if (msg.status === "waiting") {
    if (msg.action === "stakeholder_selection_request") return "等待你決議：請選擇利害關係人";
    if (/候選議題|議題/i.test(msg.text)) return "等待你決議：請選擇正式會議議題";
    return `等待你決議：${snippet(msg.text, "請確認下一步")}`;
  }
  if (/後續人類介入將自動跳過/.test(msg.text)) return "後續決議將自動跳過";
  if (/已略過/.test(msg.text)) return "已略過本次決議";
  const selected = msg.text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .filter((line) => !/^(已提交決策|選擇[:：]?|建議[:：]?|議題[:：]?)$/.test(line));
  if (selected.length) {
    return `${selected.slice(0, 2).join("、")}${selected.length > 2 ? "..." : ""}`;
  }
  return "完成";
}

function decisionTitle(msg: ChatMessage) {
  if (msg.action === "human_decision_request" || msg.decision?.kind === "human_decision") return "人類決策";
  if (/建議|候選議題|議題/i.test(msg.text)) return "人類介入";
  return "人類選擇";
}

function decisionDedupeKey(msg: ChatMessage) {
  if (msg.decisionId) return `decision:${msg.decisionId}`;
  if (msg.action === "stakeholder_selection_request") return "decision:stakeholder_selection";
  if (/@資料來源|資料來源_|\.pdf|法令|法規/i.test(msg.text)) return "decision:feedback";
  if (/利害關係人/.test(msg.text)) return "decision:stakeholder_selection";
  if (/候選議題|議題/.test(msg.text)) return "decision:meeting_issues";
  if (/需求|Requirements?|URL|REQ/i.test(msg.text)) return "decision:requirements";
  if (/領域|研究|Feedback/i.test(msg.text)) return "decision:feedback";
  if (/衝突|Conflict|CR-/i.test(msg.text)) return "decision:conflict";
  return "decision:general";
}

function decisionRound(msg: ChatMessage) {
  const rawRound = msg.decision?.issue?.round;
  if (typeof rawRound === "number" && Number.isFinite(rawRound)) return rawRound;
  if (typeof rawRound === "string") {
    const parsed = Number(rawRound);
    if (Number.isFinite(parsed)) return parsed;
  }
  return undefined;
}

function decisionOrderHint(msg: ChatMessage) {
  const round = decisionRound(msg);
  if (!round) return undefined;
  return 70 + (round - 1) * 2 + 0.5;
}

function actionDedupeKey(msg: ChatMessage) {
  const raw = msg.action ?? msg.text;
  const round = /formal_meeting\.round_(\d+)\.run_meeting/i.exec(raw)?.[1];
  if (round) return `action:formal_meeting:R${round}`;
  return `action:${actionDisplay(msg).title}`;
}

function actionTone(title: string): FlowItem["tone"] {
  if (title === "Design Rationale") return "designRationale";
  if (title === "SRS") return "srs";
  return "action";
}

function messageToFlowItem(msg: ChatMessage): FlowItem | null {
  if (msg.role === "user") {
    if (msg.kind === "decision") {
      return {
        id: msg.id,
        title: decisionTitle(msg),
        detail: decisionDetail(msg),
        dedupeKey: decisionDedupeKey(msg),
        orderHint: decisionOrderHint(msg),
        rawTitle: msg.action,
        tone: "decision",
      };
    }
    return {
      id: msg.id,
      title: "人類輸入",
      detail: snippet(msg.text, "人類輸入"),
      dedupeKey: `message:${msg.id}`,
      tone: "decision",
    };
  }

  if (msg.kind === "action") {
    if (!isPrimaryAction(msg)) return null;
    const agent = msg.label ?? msg.speaker ?? "Agent";
    const display = actionDisplay(msg);
    return {
      id: msg.id,
      title: display.title,
      detail: display.detail,
      dedupeKey: actionDedupeKey(msg),
      rawTitle: `${agent}: ${msg.action ?? msg.text}`,
      tone: actionTone(display.title),
    };
  }

  if (msg.kind === "decision") {
    return {
      id: msg.id,
      title: decisionTitle(msg),
      detail: decisionDetail(msg),
      dedupeKey: decisionDedupeKey(msg),
      orderHint: decisionOrderHint(msg),
      rawTitle: msg.action,
      tone: "decision",
    };
  }

  if (msg.kind === "output" || msg.outputPath) {
    if (!isPrimaryOutput(msg.outputPath)) return null;
    const label = outputLabel(msg.outputPath, msg.text);
    if (label === "領域研究" || label === "系統模型生成") {
      return {
        id: msg.id,
        title: label,
        detail: "已更新",
        dedupeKey: `output:${label}`,
        outputPath: msg.outputPath,
        rawTitle: msg.action,
        tone: "action",
      };
    }
    if (label === "Scope" || label === "需求擷取會議" || /^Draft v\d+$/i.test(label) || label === "Design Rationale" || label === "SRS") {
      return {
        id: msg.id,
        title: label,
        detail: "已更新",
        dedupeKey: msg.outputPath ? `output:${msg.outputPath}` : `message:${msg.id}`,
        outputPath: msg.outputPath,
        rawTitle: msg.action,
        tone: outputTone(label),
      };
    }
    return null;
  }

  if (msg.status === "waiting" || msg.status === "failed") {
    return {
      id: msg.id,
      title: msg.status === "failed" ? "錯誤" : "等待中",
      detail: snippet(msg.text, msg.status === "failed" ? "執行錯誤" : "等待中"),
      dedupeKey: `message:${msg.id}`,
      tone: "status",
    };
  }

  return null;
}

function findFlowTargetMessageId(messages: ChatMessage[], title: string, outputPath: string) {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (!message) continue;
    if (message.outputPath === outputPath) return message.id;
    if (message.outputPath && outputLabel(message.outputPath, message.text) === title) return message.id;
    if (message.kind === "action" && isPrimaryAction(message) && actionDisplay(message).title === title) {
      return message.id;
    }
  }
  return undefined;
}

function artifactFlowItems(items: FileTreeNode[], messages: ChatMessage[]): FlowItem[] {
  const paths = new Set(
    items
      .filter((item) => item.kind === "file")
      .map((item) => item.path),
  );
  const hasModel =
    paths.has("artifact/system_models.json") ||
    Array.from(paths).some((path) => /^artifact\/models\/.+/i.test(path));
  const draftPath = Array.from(paths)
    .filter((path) => /^artifact\/drafts\/draft_v\d+\.md$/i.test(path) || /^results\/drafts\/draft_v\d+\.html$/i.test(path))
    .sort((a, b) => {
      const aVersion = Number(/draft_v(\d+)/i.exec(a)?.[1] ?? 0);
      const bVersion = Number(/draft_v(\d+)/i.exec(b)?.[1] ?? 0);
      return bVersion - aVersion;
    })[0];
  const flowItems: FlowItem[] = [];

  if (paths.has("artifact/feedback.json")) {
    flowItems.push({
      id: "artifact-flow-feedback",
      title: "領域研究",
      detail: "已更新",
      dedupeKey: "output:領域研究",
      outputPath: "artifact/feedback.json",
      scrollTargetId: findFlowTargetMessageId(messages, "領域研究", "artifact/feedback.json"),
      tone: "action",
    });
  }
  if (hasModel) {
    flowItems.push({
      id: "artifact-flow-system-models",
      title: "系統模型生成",
      detail: "已更新",
      dedupeKey: "output:系統模型生成",
      outputPath: "artifact/system_models.json",
      scrollTargetId: findFlowTargetMessageId(messages, "系統模型生成", "artifact/system_models.json"),
      tone: "action",
    });
  }
  if (draftPath) {
    flowItems.push({
      id: "artifact-flow-draft",
      title: "草稿建立",
      detail: "已更新",
      dedupeKey: "output:草稿建立",
      outputPath: draftPath,
      scrollTargetId: findFlowTargetMessageId(messages, "草稿建立", draftPath),
      tone: "action",
    });
  }
  return flowItems;
}

function flowItemOrder(item: FlowItem) {
  if (item.orderHint !== undefined) return item.orderHint;
  const value = `${item.title} ${item.detail}`;
  const isHumanDecision = item.title === "人類選擇" || item.title === "人類介入" || item.title === "人類決策";
  const meetingRound = /第\s*(\d+)\s*輪會議/.exec(item.title)?.[1];
  if (meetingRound) return 70 + (Number(meetingRound) - 1) * 2;
  if (item.title === "人類輸入") return 0;
  if (item.dedupeKey === "decision:feedback") return 46;
  if (item.dedupeKey === "decision:conflict" || item.dedupeKey === "decision:requirements") return 21;
  if (item.dedupeKey === "decision:meeting_issues") return 71;
  if (item.dedupeKey === "decision:stakeholder_selection") return 11;
  if (/選擇利害關係人/.test(value)) return 10;
  if (isHumanDecision && /消費者|外送員|利害關係人/.test(value)) return 11;
  if (/利害關係人發言/.test(value)) return 12;
  if (/需求分析|需求候選/.test(value)) return 20;
  if (isHumanDecision && /議題/.test(value)) return 71;
  if (isHumanDecision && /@資料來源|資料來源_|\.pdf|法令|法規|領域|研究/.test(value)) return 46;
  if (isHumanDecision && /衝突|Conflict|CR-/.test(value)) return 21;
  if (isHumanDecision) return 21;
  if (/範圍|Scope/.test(value)) return 25;
  if (/需求擷取會議/.test(value)) return 30;
  if (/衝突辨識|衝突解決/.test(value)) return 45;
  if (/領域研究|Feedback/.test(value)) return 47;
  if (/系統模型生成|模型生成|系統模型|System Models/.test(value)) return 50;
  if (/Draft|草稿/.test(value)) return 60;
  if (/正式會議/.test(value)) return 70;
  if (/Design Rationale/.test(value)) return 80;
  if (/\bSRS\b/.test(value)) return 85;
  return 100;
}

const toneClass: Record<FlowItem["tone"], string> = {
  user: "bg-slate-900",
  action: "bg-violet-500",
  decision: "bg-amber-500",
  output: "bg-emerald-500",
  designRationale: "bg-emerald-500",
  srs: "bg-emerald-500",
  status: "bg-slate-400",
};

function latestVersionedPath(paths: Set<string>, pattern: RegExp) {
  return Array.from(paths)
    .map((path) => ({ path, version: Number(pattern.exec(path)?.[1] ?? -1) }))
    .filter((item) => item.version >= 0)
    .sort((a, b) => b.version - a.version)[0]?.path;
}

function firstExistingPath(paths: Set<string>, candidates: string[]) {
  return candidates.find((path) => paths.has(path));
}

function outputPathForFlowItem(item: FlowItem, paths: Set<string>) {
  if (item.outputPath && paths.has(item.outputPath)) return item.outputPath;
  const value = `${item.title} ${item.detail} ${item.dedupeKey}`;
  const meetingRound = /第\s*(\d+)\s*輪會議/.exec(item.title)?.[1];

  if (/人類輸入|選擇利害關係人|利害關係人發言/.test(value)) {
    return firstExistingPath(paths, ["artifact/project.json"]);
  }
  if (/需求分析|需求候選|decision:requirements/.test(value)) {
    return firstExistingPath(paths, ["artifact/requirements.json"]);
  }
  if (/範圍|Scope/.test(value)) {
    return firstExistingPath(paths, ["artifact/scope.json"]);
  }
  if (/需求擷取會議/.test(value)) {
    return firstExistingPath(paths, ["artifact/meeting/elicitation_meeting.json"]);
  }
  if (/衝突報告|衝突辨識|衝突解決|Conflict|CR-|decision:conflict/.test(value)) {
    return firstExistingPath(paths, ["artifact/result.json"]) ??
      latestVersionedPath(paths, /conflict_report_v(\d+)\.(?:html|md|json)$/i);
  }
  if (/領域研究|Feedback|decision:feedback/.test(value)) {
    return firstExistingPath(paths, ["artifact/feedback.json"]);
  }
  if (/系統模型生成|模型生成|系統模型|System Models/.test(value)) {
    return firstExistingPath(paths, ["artifact/system_models.json"]);
  }
  if (/Draft|草稿/.test(value)) {
    return latestVersionedPath(paths, /draft_v(\d+)\.(?:html|md)$/i);
  }
  if (meetingRound) {
    return firstExistingPath(paths, [
      `artifact/meeting/formal_meeting_r${meetingRound}.json`,
      `results/MoM/R${meetingRound}-M1.html`,
      `artifact/MoM/R${meetingRound}-M1.md`,
    ]) ?? latestVersionedPath(paths, new RegExp(`R${meetingRound}-M(\\d+)\\.(?:html|md)$`, "i"));
  }
  if (/Design Rationale/.test(value)) {
    return firstExistingPath(paths, ["results/design_rationale.html", "output/design_rationale.md"]);
  }
  if (/\bSRS\b/.test(value)) {
    return firstExistingPath(paths, ["results/srs.html", "output/srs.md"]);
  }
  return undefined;
}

export function WorkspaceFlowIndex({
  compact = false,
  runCheckpoint = null,
  artifactItems = [],
  completedDisplayOnly = false,
}: {
  compact?: boolean;
  runCheckpoint?: RunCheckpoint | null;
  artifactItems?: FileTreeNode[];
  completedDisplayOnly?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const itemRefs = useRef<Record<string, HTMLButtonElement | null>>({});
  const messages = useChatStore((s) => s.messages);
  const activeFlowMessageId = useUiStore((s) => s.activeFlowMessageId);
  const setScrollTargetMessageId = useUiStore((s) => s.setScrollTargetMessageId);
  const setSelectedOutputPath = useUiStore((s) => s.setSelectedOutputPath);

  const items = useMemo(() => {
    const availablePaths = new Set(
      artifactItems
        .filter((item) => item.kind === "file")
        .map((item) => item.path),
    );
    const byKey = new Map<string, FlowItem>();
    messages.forEach((message) => {
      const item = messageToFlowItem(message);
      if (!item) return;
      byKey.set(item.dedupeKey, item);
    });
    artifactFlowItems(artifactItems, messages).forEach((item) => {
      if (!byKey.has(item.dedupeKey)) byKey.set(item.dedupeKey, item);
    });
    return Array.from(byKey.values())
      .filter((item) => {
        if (!completedDisplayOnly) return true;
        if (/第\s*\d+\s*輪會議/.test(item.title)) return true;
        return item.title === "Design Rationale" ||
          item.title === "SRS" ||
          item.dedupeKey === "decision:meeting_issues" ||
          item.dedupeKey === "decision:conflict";
      })
      .map((item, index) => ({ item, index }))
      .sort((a, b) => {
        const orderDiff = flowItemOrder(a.item) - flowItemOrder(b.item);
        return orderDiff || a.index - b.index;
      })
      .map(({ item }) => ({
        ...item,
        outputPath: outputPathForFlowItem(item, availablePaths),
      }));
  }, [artifactItems, completedDisplayOnly, messages]);
  const activeItemId = useMemo(() => {
    if (!activeFlowMessageId) return items[0]?.id ?? null;
    const itemIds = new Set(items.map((item) => item.id));
    if (itemIds.has(activeFlowMessageId)) return activeFlowMessageId;
    const itemByScrollTarget = items.find((item) => item.scrollTargetId === activeFlowMessageId);
    if (itemByScrollTarget) return itemByScrollTarget.id;
    const activeIndex = messages.findIndex((message) => message.id === activeFlowMessageId);
    if (activeIndex < 0) return items[0]?.id ?? null;
    for (let index = activeIndex; index >= 0; index -= 1) {
      const id = messages[index]?.id;
      if (id && itemIds.has(id)) return id;
      const item = items.find((candidate) => candidate.scrollTargetId === id);
      if (item) return item.id;
    }
    return items[0]?.id ?? null;
  }, [activeFlowMessageId, items, messages]);

  useEffect(() => {
    if (!open) return;
    const handler = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  useEffect(() => {
    if (!open || !activeItemId) return;
    itemRefs.current[activeItemId]?.scrollIntoView({
      block: "nearest",
      behavior: "smooth",
    });
  }, [activeItemId, open]);

  const jumpTo = (item: FlowItem) => {
    setScrollTargetMessageId(item.scrollTargetId ?? item.id);
    if (item.outputPath) setSelectedOutputPath(item.outputPath);
    setOpen(false);
  };

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        className={cn(
          "inline-flex h-7 items-center gap-1.5 rounded-control border text-xs font-medium transition",
          compact ? "w-7 justify-center px-0" : "px-2.5",
          open
            ? "border-slate-300 bg-slate-50 text-slate-800"
            : "border-gray-200 bg-white text-slate-600 hover:border-slate-300 hover:text-slate-800",
        )}
        aria-label="流程"
        title="流程"
        onClick={() => setOpen((v) => !v)}
      >
        <ListTree className="h-3.5 w-3.5" />
        <span className={cn(compact && "sr-only")}>流程</span>
      </button>

      {open && (
        <div className="absolute left-0 top-full z-30 mt-2 max-h-80 w-72 overflow-y-auto rounded-card border border-gray-200 bg-white p-2 shadow-lg">
          {items.length === 0 ? (
            runCheckpoint ? (
              <button
                type="button"
                className="flex w-full items-start gap-2 rounded-control bg-amber-50 px-2 py-2 text-left"
                disabled
                title={checkpointCleanupLabel(runCheckpoint)}
              >
                <span className="mt-1 h-2 w-2 shrink-0 rounded-full bg-amber-500" />
                <span className="min-w-0">
                  <span className="block truncate text-xs font-semibold text-amber-950">
                    繼續時重跑：{checkpointStageLabel(runCheckpoint)}
                  </span>
                  <span className="block truncate text-[11px] text-amber-800">
                    {checkpointCleanupLabel(runCheckpoint)}
                  </span>
                </span>
              </button>
            ) : (
              <p className="px-2 py-3 text-xs text-slate-500">無任何內容</p>
            )
          ) : (
            <div className="space-y-1">
              {runCheckpoint && (
                <button
                  type="button"
                  className="flex w-full items-start gap-2 rounded-control bg-amber-50 px-2 py-2 text-left"
                  disabled
                  title={checkpointCleanupLabel(runCheckpoint)}
                >
                  <span className="mt-1 h-2 w-2 shrink-0 rounded-full bg-amber-500" />
                  <span className="min-w-0">
                    <span className="block truncate text-xs font-semibold text-amber-950">
                      繼續時重跑：{checkpointStageLabel(runCheckpoint)}
                    </span>
                    <span className="block truncate text-[11px] text-amber-800">
                      {checkpointCleanupLabel(runCheckpoint)}
                    </span>
                  </span>
                </button>
              )}
              {items.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  ref={(node) => {
                    itemRefs.current[item.id] = node;
                  }}
                  aria-current={item.id === activeItemId ? "true" : undefined}
                  title={item.rawTitle || `${item.title}：${item.detail}`}
                  className={cn(
                    "flex w-full items-start gap-2 rounded-control px-2 py-2 text-left transition-colors hover:bg-slate-50",
                    item.id === activeItemId && "bg-slate-50",
                  )}
                  onClick={() => jumpTo(item)}
                >
                  <span
                    className={cn(
                      "mt-1 h-2 w-2 shrink-0 rounded-full transition",
                      toneClass[item.tone],
                      item.id === activeItemId && "ring-2 ring-slate-200 ring-offset-1",
                    )}
                  />
                  <span className="min-w-0">
                    <span className={cn(
                      "block truncate text-xs font-semibold",
                      item.id === activeItemId ? "text-slate-900" : "text-slate-700",
                    )}>
                      {item.title}
                    </span>
                    {!["action", "designRationale", "srs"].includes(item.tone) && (
                      <span className="block truncate text-[11px] text-slate-500">
                        {item.detail}
                      </span>
                    )}
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
