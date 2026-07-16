import { create } from "zustand";
import type { ChatMessage, RunCheckpoint } from "@/types/api";
import { completeStageProgress, completeStepProgress } from "@/utils/chatProgress";

type ContinueTrimTarget =
  | string
  | Pick<RunCheckpoint, "stage_id" | "step_id" | "round" | "last_round">
  | null
  | undefined;

interface ChatState {
  messages: ChatMessage[];
  continueReplacementStage: ContinueTrimTarget;
  appendMessage: (msg: ChatMessage) => void;
  setMessages: (msgs: ChatMessage[]) => void;
  resolveHumanInterventionProgress: (
    decision?: ChatMessage["decision"] | null,
  ) => void;
  resolveStageProgress: (stage?: string) => void;
  resolveHeartbeatProgress: () => void;
  resolveStepProgress: (stage?: string, action?: string) => void;
  setContinueReplacementStage: (target?: ContinueTrimTarget) => void;
  trimRunStatusMessagesForContinue: (target?: ContinueTrimTarget) => void;
  clearMessages: () => void;
}

function isTrailingRunStatusMessage(message: ChatMessage) {
  if (message.status === "failed") return true;
  if (message.role === "system" && message.kind === "stage") return true;
  return message.kind === "decision";
}

function isGeneratedDocumentPath(path?: string) {
  return /^(?:results|output)\/(?:srs|design_rationale)\.(?:html|md)$/i.test(path ?? "");
}

function isTrailingGeneratedDocumentMessage(message: ChatMessage) {
  if (isGeneratedDocumentPath(message.outputPath)) return true;
  return (
    message.stage === "document_generation" &&
    (message.speaker === "documentor" || message.kind === "stage" || message.kind === "action")
  );
}

function isGeneratedDocumentDisplayMessage(message: ChatMessage) {
  return isGeneratedDocumentPath(message.outputPath) || message.stage === "document_generation";
}

function messageTime(message: ChatMessage) {
  const value = message.timestamp ? new Date(message.timestamp).getTime() : NaN;
  return Number.isFinite(value) ? value : null;
}

function trimDocumentGenerationMessagesForContinue(messages: ChatMessage[]) {
  let latestActiveDocumentStage = -1;
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (
      message.role === "system" &&
      message.kind === "stage" &&
      message.stage === "document_generation" &&
      message.status === "running"
    ) {
      latestActiveDocumentStage = index;
      break;
    }
  }

  if (latestActiveDocumentStage < 0) {
    return messages.filter((message) => !isGeneratedDocumentDisplayMessage(message));
  }

  const activeStageTime = messageTime(messages[latestActiveDocumentStage]);
  return messages.filter((message, index) => {
    if (!isGeneratedDocumentDisplayMessage(message)) return true;
    if (index < latestActiveDocumentStage) return false;
    if (index === latestActiveDocumentStage) return true;
    if (activeStageTime === null) return true;
    const currentTime = messageTime(message);
    return currentTime === null || currentTime >= activeStageTime;
  });
}

function isDuplicateStagePill(a: ChatMessage, b: ChatMessage) {
  return (
    a.role === "system" &&
    b.role === "system" &&
    a.kind === "stage" &&
    b.kind === "stage" &&
    a.status === "running" &&
    b.status === "running" &&
    a.stage === b.stage &&
    a.text.trim() === b.text.trim()
  );
}

function isReviewOutputMessage(message: ChatMessage) {
  const action = String(message.action || "").trim();
  return (
    action === "stakeholder_statement_revision" ||
    action === "init.analyze_requirements_review" ||
    action === "init.generate_scope_review" ||
    action === "elicitation.update_feedback" ||
    action === "research_domain.update_feedback"
  );
}

function messageSemanticKey(message: ChatMessage) {
  if (message.outputPath) {
    if (isReviewOutputMessage(message)) {
      return `output-review:${message.outputPath}:${message.action || ""}:${message.text.trim()}`;
    }
    return `output:${message.outputPath}`;
  }
  if (message.role === "system" && message.kind === "stage") {
    return `stage:${message.stage || ""}:${message.text.trim()}`;
  }
  if (message.kind === "decision" && message.decision?.id) {
    return `decision:${message.decision.id}:${message.role}:${message.status}:${message.action || ""}`;
  }
  if (message.kind === "action" || message.kind === "output") {
    const action = String(message.action || "").trim();
    if (action) {
      return `action:${message.stage || ""}:${action}:${message.text.trim()}`;
    }
  }
  return "";
}

function hasDuplicateMessage(messages: ChatMessage[], msg: ChatMessage) {
  if (messages.some((m) => m.id === msg.id)) return true;
  if (messages.some((m) => isDuplicateStagePill(m, msg))) return true;
  const key = messageSemanticKey(msg);
  if (!key) return false;
  return messages.some((message) => messageSemanticKey(message) === key);
}

function isProgressForDecision(message: ChatMessage, decision?: ChatMessage["decision"] | null) {
  if (message.status !== "running" || message.kind !== "action") return false;
  const kind = decision?.kind;
  const options = decision?.options && typeof decision.options === "object"
    ? decision.options as Record<string, unknown>
    : {};
  const stageId = String(options.stage_id ?? "").trim();
  const action = String(message.action ?? "").trim();
  if (kind === "meeting_issue_proposal_review") {
    return (
      /^formal_meeting\.round_\d+\.propose_issues$/i.test(action) ||
      /候選議題/.test(message.text)
    );
  }
  if (stageId && (message.stage === stageId || action.includes(stageId))) return true;
  return false;
}

export function trimTrailingRunDisplayMessages(messages: ChatMessage[]) {
  let end = messages.length;
  while (
    end > 0 &&
    (
      isTrailingRunStatusMessage(messages[end - 1]) ||
      isTrailingGeneratedDocumentMessage(messages[end - 1])
    )
  ) {
    end -= 1;
  }
  return end === messages.length ? messages : messages.slice(0, end);
}

export function trimTrailingGeneratedDocumentMessages(messages: ChatMessage[]) {
  let end = messages.length;
  while (end > 0 && isTrailingGeneratedDocumentMessage(messages[end - 1])) {
    end -= 1;
  }
  return end === messages.length ? messages : messages.slice(0, end);
}

export function trimRunDisplayMessagesFromStage(
  messages: ChatMessage[],
  target?: ContinueTrimTarget,
) {
  const stage = typeof target === "string"
    ? target.trim()
    : String(target?.stage_id ?? "").trim();
  if (!stage) return trimTrailingRunDisplayMessages(messages);
  const round = typeof target === "object" && target
    ? Number(target.round || target.last_round || 0)
    : 0;

  if (stage === "document_generation") {
    return trimDocumentGenerationMessagesForContinue(messages);
  }

  let start = -1;
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (
      message.role === "system" &&
      message.kind === "stage" &&
      message.stage === stage &&
      (
        stage !== "formal_meeting" ||
        round <= 0 ||
        new RegExp(`^第\\s*${round}\\s*輪會議$`, "u").test(message.text.trim())
      )
    ) {
      start = index;
      break;
    }
  }
  if (start < 0) return trimTrailingRunDisplayMessages(messages);
  return messages.slice(0, start + 1);
}

export const useChatStore = create<ChatState>((set) => ({
  messages: [],
  continueReplacementStage: null,
  appendMessage: (msg) =>
    set((s) => {
      if (hasDuplicateMessage(s.messages, msg)) return s;
      return { messages: [...s.messages, msg] };
    }),
  setMessages: (messages) => set({ messages }),
  resolveHumanInterventionProgress: (decision) =>
    set((s) => {
      let changed = false;
      const next = [...s.messages];
      for (let index = next.length - 1; index >= 0; index -= 1) {
        const message = next[index];
        if (!isProgressForDecision(message, decision)) continue;
        next.splice(index, 1);
        changed = true;
        break;
      }
      return changed ? { messages: next } : s;
    }),
  resolveStageProgress: (stage) =>
    set((s) => {
      const messages = completeStageProgress(s.messages, stage);
      return messages === s.messages ? s : { messages };
    }),
  resolveHeartbeatProgress: () =>
    set((s) => {
      const messages = s.messages.filter((message) => !message.id.startsWith("heartbeat-"));
      return messages.length === s.messages.length ? s : { messages };
    }),
  resolveStepProgress: (stage, action) =>
    set((s) => {
      const messages = completeStepProgress(s.messages, stage, action);
      return messages === s.messages ? s : { messages };
    }),
  setContinueReplacementStage: (stageId) =>
    set({
      continueReplacementStage: typeof stageId === "string"
        ? String(stageId ?? "").trim() || null
        : stageId ?? null,
    }),
  trimRunStatusMessagesForContinue: (stageId) =>
    set((s) => {
      const messages = trimRunDisplayMessagesFromStage(s.messages, stageId);
      if (messages === s.messages) return s;
      return { messages };
    }),
  clearMessages: () => set({ messages: [] }),
}));
