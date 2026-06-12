import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { runEventsUrl, type RunEvent } from "@/api/runs";
import { useChatStore } from "@/stores/chatStore";
import {
  buildInitialUserMessage,
  logEventToChats,
  mergeChatMessages,
} from "@/utils/logParser";
import type { RunState } from "@/types/api";

export function useRunEvents(
  run: RunState | null,
  roughIdea?: string,
  onComplete?: () => void,
) {
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const sinceRef = useRef(0);
  const esRef = useRef<EventSource | null>(null);
  const runIdRef = useRef<string | null>(null);
  const seededRunRef = useRef<string | null>(null);
  const roughIdeaRef = useRef(roughIdea);
  roughIdeaRef.current = roughIdea;
  const appendMessage = useChatStore((s) => s.appendMessage);
  const setMessages = useChatStore((s) => s.setMessages);
  const queryClient = useQueryClient();

  const processEvent = useCallback(
    (event: RunEvent) => {
      setEvents((prev) => {
        if (prev.some((e) => e.id === event.id)) return prev;
        return [...prev, event];
      });
      const chats = logEventToChats(event);
      for (const chat of chats) {
        appendMessage(chat);
        if (chat.outputPath) {
          queryClient.invalidateQueries({ queryKey: ["artifacts"] });
          queryClient.invalidateQueries({ queryKey: ["chat-preview"] });
          queryClient.invalidateQueries({ queryKey: ["file"] });
        }
      }

      if (
        event.type === "run_completed" ||
        event.type === "run_failed" ||
        event.type === "run_cancelled"
      ) {
        queryClient.invalidateQueries({ queryKey: ["artifacts"] });
        queryClient.invalidateQueries({ queryKey: ["runs"] });
        queryClient.invalidateQueries({ queryKey: ["project"] });
        onComplete?.();
      }
    },
    [appendMessage, onComplete, queryClient],
  );

  // Reset event buffer when run changes or disconnects
  useEffect(() => {
    if (!run?.run_id) {
      setEvents([]);
      sinceRef.current = 0;
      runIdRef.current = null;
    }
  }, [run?.run_id]);

  useEffect(() => {
    if (!run?.run_id) return;
    if (!["queued", "running", "waiting_for_human", "cancelling"].includes(run.status)) {
      return;
    }

    // Close any existing SSE before opening a new connection
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
    }

    if (runIdRef.current !== run.run_id) {
      sinceRef.current = 0;
      setEvents([]);
      runIdRef.current = run.run_id;
      seededRunRef.current = null;
    }

    const idea = roughIdeaRef.current?.trim();
    if (idea) {
      const currentMessages = useChatStore.getState().messages;
      if (currentMessages.length === 0) {
        setMessages(mergeChatMessages([buildInitialUserMessage(idea)]));
        seededRunRef.current = run.run_id;
      } else if (!currentMessages.some((msg) => msg.id === "rough-idea")) {
        setMessages(mergeChatMessages([buildInitialUserMessage(idea), ...currentMessages]));
        seededRunRef.current = run.run_id;
      }
    }

    const url = runEventsUrl(run.run_id, sinceRef.current);
    const es = new EventSource(url);
    esRef.current = es;
    setConnected(true);

    es.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data) as RunEvent;
        sinceRef.current = data.id + 1;
        processEvent(data);
      } catch {
        /* ignore parse errors */
      }
    };

    es.addEventListener("done", () => {
      es.close();
      esRef.current = null;
      setConnected(false);
      queryClient.invalidateQueries({ queryKey: ["runs"] });
      queryClient.invalidateQueries({ queryKey: ["artifacts"] });
      onComplete?.();
    });

    es.onerror = () => {
      setConnected(false);
    };

    return () => {
      es.close();
      esRef.current = null;
      setConnected(false);
    };
  }, [run?.run_id, run?.status, roughIdea, processEvent, setMessages, appendMessage, queryClient, onComplete]);

  useEffect(() => {
    if (!run?.run_id) return;
    if (!["queued", "running", "waiting_for_human", "cancelling"].includes(run.status)) {
      return;
    }
    let cancelled = false;
    const poll = async () => {
      if (connected || cancelled) return;
      try {
        const res = await fetch(runEventsUrl(run.run_id, sinceRef.current), {
          headers: { Accept: "application/json" },
        });
        if (!res.ok) return;
        const body = (await res.json()) as { events?: RunEvent[] };
        for (const event of body.events ?? []) {
          sinceRef.current = Math.max(sinceRef.current, Number(event.id) + 1);
          processEvent(event);
        }
      } catch {
        /* keep polling while the active run exists */
      }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 2000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [run?.run_id, run?.status, connected, processEvent]);

  return { events, connected };
}
