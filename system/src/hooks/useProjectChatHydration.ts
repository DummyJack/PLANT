import { useEffect, useRef, useState } from "react";
import { fetchRuns } from "@/api/runs";
import { useChatStore } from "@/stores/chatStore";
import type { ChatMessage, RunState } from "@/types/api";
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

function attachMomLinks(messages: ChatMessage[]): ChatMessage[] {
  let currentRound = 0;
  return messages.map((message) => {
    const round =
      /^Round\s+(\d+)\s*:\s*開會/i.exec(message.text) ??
      /^第\s*(\d+)\s*輪/.exec(message.text);
    if (round) {
      currentRound = Number(round[1]);
      return message;
    }

    const task =
      /^\s*(?:Mediator\s*[:：]\s*)?(?:M|T)-(\d+)\s*[｜|]/.exec(message.text) ??
      /^\s*\[(?:M|T)-(\d+)\]\s*開始/.exec(message.text);
    if (task && currentRound > 0) {
      return {
        ...message,
        outputPath: `artifact/meeting/formal_meeting_r${currentRound}.json`,
      };
    }
    return {
      ...message,
    };
  });
}

function uniqueChatMessages(messages: ChatMessage[]): ChatMessage[] {
  const seen = new Set<string>();
  return messages.filter((message) => {
    if (seen.has(message.id)) return false;
    seen.add(message.id);
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
  return attachMomLinks(events.flatMap((event) => {
    const row = event as Parameters<typeof logEventToChat>[0];
    return historicalEventMessages(row);
  }));
}

async function loadRunLogMessages(projectId: string): Promise<ChatMessage[]> {
  try {
    const { runs } = await fetchRuns(projectId);
    const last = runs
      .filter((r) =>
        ["completed", "failed", "cancelled", "interrupted"].includes(r.status),
      )
      .sort(
        (a, b) =>
          new Date(b.finished_at ?? b.started_at).getTime() -
          new Date(a.finished_at ?? a.started_at).getTime(),
      )[0];
    if (!last) return [];

    const res = await fetch(
      `/api/runs/${last.run_id}/events?since=0`,
      { headers: { Accept: "application/json" } },
    );
    if (!res.ok) return [];

    const contentType = res.headers.get("content-type") ?? "";
    if (contentType.includes("application/json")) {
      const body = (await res.json()) as { events?: unknown[] } | unknown[];
      const rows = Array.isArray(body)
        ? body
        : Array.isArray(body.events)
          ? body.events
          : [];
      return historicalLogMessages(rows);
    }

    const text = await res.text();
    const messages = [];
    for (const line of text.split("\n")) {
      const trimmed = line.trim();
      if (!trimmed.startsWith("data:")) continue;
      try {
        const event = JSON.parse(trimmed.slice(5).trim());
        messages.push(...historicalEventMessages(event));
      } catch {
        /* skip malformed SSE chunks */
      }
    }
    return attachMomLinks(messages);
  } catch {
    return [];
  }
}

export function useProjectChatHydration(
  projectId: string | null,
  _artifactItems: unknown,
  roughIdea: string,
  activeRun: RunState | null,
  artifactsReady: boolean,
) {
  const setMessages = useChatStore((s) => s.setMessages);
  const hydratedKeyRef = useRef<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [hasHistory, setHasHistory] = useState(false);

  useEffect(() => {
    hydratedKeyRef.current = null;
    setMessages([]);
    setHasHistory(false);
    setLoading(!!projectId);
  }, [projectId, setMessages]);

  useEffect(() => {
    if (!projectId) {
      setLoading(false);
      setHasHistory(false);
      return;
    }

    const active = !!activeRun && ACTIVE.has(activeRun.status);
    const hydrationKey = `${projectId}:${active ? activeRun?.run_id : "history"}`;
    if (active && hydratedKeyRef.current === hydrationKey) {
      setLoading(false);
      setHasHistory(true);
      return;
    }

    if (!artifactsReady) {
      setLoading(true);
      return;
    }

    let cancelled = false;
    setLoading(true);

    const hydrate = async () => {
      const logMsgs = await loadRunLogMessages(projectId);

      if (cancelled) return;

      const seed = roughIdea.trim()
        ? [buildInitialUserMessage(roughIdea.trim())]
        : [];

      const currentMessages = useChatStore.getState().messages;

      if (!logMsgs.length) {
        if (seed.length) {
          setMessages(
            mergeChatMessages(
              uniqueChatMessages(
                active && currentMessages.length
                  ? [...seed, ...currentMessages]
                  : seed,
              ),
            ),
          );
          setHasHistory(true);
          hydratedKeyRef.current = hydrationKey;
          setLoading(false);
          return;
        }
        setHasHistory(false);
        hydratedKeyRef.current = hydrationKey;
        setLoading(false);
        return;
      }

      const historyMessages = mergeChatMessages([...seed, ...logMsgs]);
      setMessages(
        mergeChatMessages(
          uniqueChatMessages(
            active && currentMessages.length
              ? [...historyMessages, ...currentMessages]
              : historyMessages,
          ),
        ),
      );
      setHasHistory(true);
      hydratedKeyRef.current = hydrationKey;
      setLoading(false);
    };

    void hydrate();
    return () => {
      cancelled = true;
    };
  }, [
    projectId,
    roughIdea,
    activeRun?.run_id,
    activeRun?.status,
    artifactsReady,
    setMessages,
  ]);

  return { loading, hasHistory };
}
