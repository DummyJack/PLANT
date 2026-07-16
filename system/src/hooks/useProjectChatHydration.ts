import { useEffect, useRef, useState } from "react";
import { fetchRuns, runEventsUrl } from "@/api/runs";
import {
  trimRunDisplayMessagesFromStage,
  trimTrailingGeneratedDocumentMessages,
  trimTrailingRunDisplayMessages,
  useChatStore,
} from "@/stores/chatStore";
import type { ChatMessage, FileTreeNode, RunCheckpoint, RunState } from "@/types/api";
import {
  buildInitialUserMessage,
  logEventToChat,
  logEventToChats,
  mergeChatMessages,
} from "@/utils/logParser";

const ACTIVE = new Set([
  "queued",
  "running",
  "waiting_for_human",
  "cancelling",
]);

function uniqueChatMessages(messages: ChatMessage[]): ChatMessage[] {
  const seen = new Set<string>();
  return messages.filter((message) => {
    const action = String(message.action || "").trim();
    const isReviewOutput =
      action === "stakeholder_statement_revision" ||
      action === "init.analyze_requirements_review" ||
      action === "init.generate_scope_review" ||
      action === "elicitation.update_feedback" ||
      action === "research_domain.update_feedback";
    const semanticKey = message.outputPath
      ? isReviewOutput
        ? `output-review:${message.outputPath}:${action}:${message.text.trim()}`
        : `output:${message.outputPath}`
      : message.role === "system" && message.kind === "stage"
        ? `stage:${message.stage || ""}:${message.text.trim()}`
        : message.kind === "decision" && message.decision?.id
          ? `decision:${message.decision.id}:${message.role}:${message.status}:${message.action || ""}`
          : (message.kind === "action" || message.kind === "output") && message.action
            ? `action:${message.stage || ""}:${message.action}:${message.text.trim()}`
            : "";
    const key = semanticKey || message.id;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function isHistoricalTransientEvent(event: Parameters<typeof logEventToChat>[0]) {
  return (
    event.type === "heartbeat" ||
    event.type === "cancel_requested" ||
    event.type === "run_completed" ||
    event.type === "run_failed" ||
    event.type === "run_cancelled"
  );
}

function historicalEventMessages(event: Parameters<typeof logEventToChat>[0]): ChatMessage[] {
  if (isHistoricalTransientEvent(event)) return [];
  const messages = logEventToChats(event);
  if (event.type !== "stage_started") return messages;
  return messages.map((message) =>
    message.role === "system" && message.kind === "stage" && message.status === "running"
      ? { ...message, status: "done" }
      : message,
  );
}

function historicalLogMessages(events: unknown[]): ChatMessage[] {
  return events.flatMap((event) => {
    const row = event as Parameters<typeof logEventToChat>[0];
    return historicalEventMessages(row);
  });
}

function checkpointFromEvents(events: unknown[]): Pick<RunCheckpoint, "stage_id" | "step_id" | "round"> | null {
  for (const event of [...events].reverse()) {
    const row = event as {
      type?: string;
      checkpoint?: Pick<RunCheckpoint, "stage_id" | "step_id" | "round">;
      stage_id?: string;
      step_id?: string;
      round?: number;
    };
    if (row.type !== "run_checkpoint_recorded") continue;
    const stageId = String(row.checkpoint?.stage_id || row.stage_id || "").trim();
    if (!stageId) return null;
    return {
      stage_id: stageId,
      step_id: String(row.checkpoint?.step_id || row.step_id || "").trim() || undefined,
      round: Number(row.checkpoint?.round ?? row.round ?? 0) || undefined,
    };
  }
  return null;
}

function trimEventsFromCheckpoint(
  events: unknown[],
  checkpoint?: Pick<RunCheckpoint, "stage_id" | "step_id" | "round"> | null,
): unknown[] {
  const stage = String(checkpoint?.stage_id ?? "").trim();
  if (!stage) return events;
  const round = Number(checkpoint?.round ?? 0);
  const index = events.findIndex((event) => {
    const row = event as { stage_id?: string; step_id?: string; message?: string; title?: string };
    if (String(row.stage_id || "").trim() !== stage) return false;
    if (stage !== "formal_meeting" || round <= 0) return true;
    const text = String(row.message || row.title || "").trim();
    return (
      new RegExp(`第\\s*${round}\\s*輪正式會議開始`, "u").test(text) ||
      String(row.step_id || "").startsWith(`formal_meeting.round_${round}.`)
    );
  });
  return index < 0 ? events : events.slice(0, index);
}

function historicalRunEvents(run: RunState, events: unknown[]): unknown[] {
  if (!["failed", "cancelled", "interrupted"].includes(run.status)) {
    return events;
  }
  const checkpoint = run.run_checkpoint || checkpointFromEvents(events);
  return checkpoint ? trimEventsFromCheckpoint(events, checkpoint) : events;
}

function historicalRunMessages(run: RunState, events: unknown[]): ChatMessage[] {
  const messages = historicalLogMessages(historicalRunEvents(run, events));
  if (run.mode === "continue" && ACTIVE.has(run.status)) {
    return trimTrailingGeneratedDocumentMessages(messages);
  }
  return messages;
}

function trimCurrentMessagesForCheckpoint(
  messages: ChatMessage[],
  checkpoint?: Parameters<typeof trimRunDisplayMessagesFromStage>[1],
  removeDocumentGeneration = false,
) {
  const baseMessages = removeDocumentGeneration
    ? trimRunDisplayMessagesFromStage(messages, "document_generation")
    : messages;
  const stage = typeof checkpoint === "string"
    ? checkpoint.trim()
    : String(checkpoint?.stage_id ?? "").trim();
  if (stage !== "document_generation") {
    return trimRunDisplayMessagesFromStage(
      trimTrailingRunDisplayMessages(baseMessages),
      checkpoint,
    );
  }

  return trimRunDisplayMessagesFromStage(baseMessages, checkpoint);
}

async function loadRunEvents(runId: string): Promise<unknown[]> {
  const res = await fetch(
    runEventsUrl(runId, 0),
    { headers: { Accept: "application/json" } },
  );
  if (!res.ok) return [];

  const contentType = res.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    const body = (await res.json()) as { events?: unknown[] } | unknown[];
    return Array.isArray(body)
      ? body
      : Array.isArray(body.events)
        ? body.events
        : [];
  }

  const rows: unknown[] = [];
  const text = await res.text();
  for (const line of text.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed.startsWith("data:")) continue;
    try {
      rows.push(JSON.parse(trimmed.slice(5).trim()));
    } catch {
      /* skip malformed SSE chunks */
    }
  }
  return rows;
}

async function loadRunLogMessages(projectId: string, activeRunId?: string | null): Promise<ChatMessage[]> {
    const { runs } = await fetchRuns(projectId);
    const historyRuns = runs
      .filter((r) =>
        ["completed", "failed", "cancelled", "interrupted"].includes(r.status),
      )
      .sort(
        (a, b) =>
          new Date(a.started_at).getTime() -
          new Date(b.started_at).getTime(),
      );
    const rows: ChatMessage[] = [];
    for (const run of historyRuns) {
      const events = await loadRunEvents(run.run_id);
      rows.push(...historicalRunMessages(run, events));
    }
    if (activeRunId && !historyRuns.some((run) => run.run_id === activeRunId)) {
      rows.push(...historicalLogMessages(await loadRunEvents(activeRunId)));
    }
    if (!rows.length) return [];
    return rows;
}

function systemModelArtifactFallback(
  artifactItems: FileTreeNode[] | undefined,
  messages: ChatMessage[],
): ChatMessage[] {
  const hasSystemModels = (artifactItems ?? []).some(
    (item) => item.kind === "file" && item.path === "artifact/system_models.json",
  );
  const hasSystemModelMessage = messages.some(
    (message) => message.outputPath === "artifact/system_models.json",
  );
  if (!hasSystemModels || hasSystemModelMessage) return [];
  return [
    {
      id: "artifact-fallback-system-models",
      role: "agent",
      kind: "output",
      speaker: "modeler",
      label: "Modeler",
      action: "system_model.modeling",
      stage: "system_model",
      status: "done",
      text: "系統模型產生",
      outputPath: "artifact/system_models.json",
    },
  ];
}

function insertArtifactFallbackMessages(
  messages: ChatMessage[],
  fallbackMessages: ChatMessage[],
): ChatMessage[] {
  if (!fallbackMessages.length) return messages;
  const next = [...messages];
  for (const fallback of fallbackMessages) {
    const insertAt = next.findIndex((message) =>
      ["draft", "formal_meeting", "document_generation"].includes(
        String(message.stage ?? "").trim(),
      ),
    );
    next.splice(insertAt < 0 ? next.length : insertAt, 0, fallback);
  }
  return next;
}

export function useProjectChatHydration(
  projectId: string | null,
  artifactItems: FileTreeNode[] | undefined,
  roughIdea: string,
  activeRun: RunState | null,
  artifactsReady: boolean,
) {
  const setMessages = useChatStore((s) => s.setMessages);
  const continueReplacementStage = useChatStore((s) => s.continueReplacementStage);
  const hydratedKeyRef = useRef<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    hydratedKeyRef.current = null;
    setMessages([]);
    setError(null);
    setLoading(!!projectId);
  }, [projectId, setMessages]);

  useEffect(() => {
    if (!projectId) {
      setLoading(false);
      setError(null);
      return;
    }

    const active = !!activeRun && ACTIVE.has(activeRun.status);
    const hydrationKey = `${projectId}:${active ? activeRun?.run_id : "history"}`;
    if (active && hydratedKeyRef.current === hydrationKey) {
      setLoading(false);
      return;
    }

    if (!artifactsReady) {
      setLoading(true);
      return;
    }

    let cancelled = false;
    setLoading(true);
    setError(null);

    const hydrate = async () => {
      const logMsgs = await loadRunLogMessages(projectId, active ? activeRun?.run_id : null);

      if (cancelled) return;

      const seed = roughIdea.trim()
        ? [buildInitialUserMessage(roughIdea.trim())]
        : [];
      const fallbackMessages = systemModelArtifactFallback(artifactItems, logMsgs);
      const restoredLogMessages = insertArtifactFallbackMessages(logMsgs, fallbackMessages);

      const currentMessages = useChatStore.getState().messages;

      if (!logMsgs.length) {
        if (seed.length || fallbackMessages.length) {
          setMessages(
            mergeChatMessages(
              uniqueChatMessages(
                active && currentMessages.length
                  ? [...seed, ...fallbackMessages, ...currentMessages]
                  : [...seed, ...fallbackMessages],
              ),
            ),
          );
          hydratedKeyRef.current = hydrationKey;
          setLoading(false);
          return;
        }
        hydratedKeyRef.current = hydrationKey;
        setLoading(false);
        return;
      }

      const mergedHistoryMessages = mergeChatMessages([
        ...seed,
        ...restoredLogMessages,
      ]);
      const removeDocumentGeneration = active && activeRun?.mode === "continue";
      const trimStage = removeDocumentGeneration
        ? "document_generation"
        : continueReplacementStage || activeRun?.run_checkpoint || null;
      const currentMessagesForMerge = active && (trimStage || removeDocumentGeneration)
        ? trimCurrentMessagesForCheckpoint(currentMessages, trimStage, removeDocumentGeneration)
        : currentMessages;
      const historyMessages = active && (trimStage || removeDocumentGeneration)
        ? trimCurrentMessagesForCheckpoint(mergedHistoryMessages, trimStage, removeDocumentGeneration)
        : mergedHistoryMessages;
      setMessages(
        mergeChatMessages(
          uniqueChatMessages(
            active && currentMessagesForMerge.length
              ? [...historyMessages, ...currentMessagesForMerge]
              : historyMessages,
          ),
        ),
      );
      hydratedKeyRef.current = hydrationKey;
      setLoading(false);
    };

    void hydrate().catch((reason) => {
      if (cancelled) return;
      setError(reason instanceof Error ? reason.message : "Unable to load chat history");
      setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [
    projectId,
    roughIdea,
    activeRun?.run_id,
    activeRun?.status,
    artifactItems,
    continueReplacementStage,
    artifactsReady,
    setMessages,
  ]);

  return { loading, error };
}
