import type { ChatMessage } from "@/types/api";

function findLastMessageIndex(
  messages: ChatMessage[],
  predicate: (message: ChatMessage) => boolean,
) {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    if (predicate(messages[index])) return index;
  }
  return -1;
}

export function completeStageProgress(
  messages: ChatMessage[],
  stage?: string,
): ChatMessage[] {
  const normalizedStage = String(stage ?? "").trim();
  if (!normalizedStage) return messages;
  const index = findLastMessageIndex(messages, (message) =>
    message.role === "system" &&
    message.kind === "stage" &&
    message.status === "running" &&
    String(message.stage ?? "").trim() === normalizedStage &&
    !message.id.startsWith("heartbeat-")
  );
  if (index < 0) return messages;
  const next = [...messages];
  next[index] = { ...next[index], status: "done" };
  return next;
}

export function completeStepProgress(
  messages: ChatMessage[],
  stage?: string,
  action?: string,
): ChatMessage[] {
  const normalizedStage = String(stage ?? "").trim();
  const normalizedAction = String(action ?? "").trim();
  if (!normalizedAction) return messages;
  const index = findLastMessageIndex(messages, (message) =>
    message.kind === "action" &&
    message.status === "running" &&
    String(message.action ?? "").trim() === normalizedAction &&
    (!normalizedStage || String(message.stage ?? "").trim() === normalizedStage)
  );
  return index < 0
    ? messages
    : messages.filter((_, messageIndex) => messageIndex !== index);
}
