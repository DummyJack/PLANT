import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { runEventsUrl, type RunEvent } from "@/api/runs";
import { useChatStore } from "@/stores/chatStore";
import { useUiStore } from "@/stores/uiStore";
import {
  buildInitialUserMessage,
  logEventToChats,
  mergeChatMessages,
} from "@/utils/logParser";
import { outputPathFromRunEvent } from "@/utils/outputFollow";
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
  const trimmedCheckpointStageRef = useRef<string | null>(null);
  const roughIdeaRef = useRef(roughIdea);
  roughIdeaRef.current = roughIdea;
  const appendMessage = useChatStore((s) => s.appendMessage);
  const setMessages = useChatStore((s) => s.setMessages);
  const resolveHumanInterventionProgress = useChatStore((s) => s.resolveHumanInterventionProgress);
  const continueReplacementStage = useChatStore((s) => s.continueReplacementStage);
  const setContinueReplacementStage = useChatStore((s) => s.setContinueReplacementStage);
  const trimRunStatusMessagesForContinue = useChatStore((s) => s.trimRunStatusMessagesForContinue);
  const setAutoOutputPath = useUiStore((s) => s.setAutoOutputPath);
  const queryClient = useQueryClient();

  const processEvent = useCallback(
    (event: RunEvent) => {
      setEvents((prev) => {
        if (prev.some((e) => e.id === event.id)) return prev;
        return [...prev, event];
      });
      const followPath = outputPathFromRunEvent(event);
      if (followPath) {
        setAutoOutputPath(followPath);
        if (run?.project_id) {
          queryClient.invalidateQueries({ queryKey: ["artifacts", run.project_id] });
        } else {
          queryClient.invalidateQueries({ queryKey: ["artifacts"] });
        }
      }
      const checkpointTarget = run?.run_checkpoint || continueReplacementStage;
      const checkpointStage = typeof checkpointTarget === "string"
        ? checkpointTarget.trim()
        : String(checkpointTarget?.stage_id || "").trim();
      const checkpointRound = typeof checkpointTarget === "object" && checkpointTarget
        ? Number(checkpointTarget.round ?? 0)
        : 0;
      const eventStage = String(event.stage_id || "").trim();
      const eventText = String(event.message || event.title || "").trim();
      const trimKey = `${run?.run_id || ""}:${checkpointStage}:${checkpointRound || ""}`;
      if (
        event.type === "stage_started" &&
        checkpointStage &&
        eventStage === checkpointStage &&
        (
          checkpointStage !== "formal_meeting" ||
          checkpointRound <= 0 ||
          new RegExp(`第\\s*${checkpointRound}\\s*輪正式會議開始`, "u").test(eventText)
        ) &&
        trimmedCheckpointStageRef.current !== trimKey
      ) {
        trimRunStatusMessagesForContinue(checkpointTarget);
        trimmedCheckpointStageRef.current = trimKey;
      }
      const chats = logEventToChats(event);
      if (
        event.type === "human_decision_submitted" ||
        event.type === "human_decision_auto_skipped"
      ) {
        resolveHumanInterventionProgress(event.decision, event.payload ?? null);
      }
      for (const chat of chats) {
        appendMessage(chat);
        if (chat.outputPath) {
          if (run?.project_id) {
            queryClient.invalidateQueries({ queryKey: ["artifacts", run.project_id] });
            queryClient.invalidateQueries({ queryKey: ["file", run.project_id, chat.outputPath] });
          } else {
            queryClient.invalidateQueries({ queryKey: ["artifacts"] });
            queryClient.invalidateQueries({ queryKey: ["file"] });
          }
          queryClient.invalidateQueries({ queryKey: ["chat-preview"] });
        }
      }

      if (
        event.type === "run_completed" ||
        event.type === "run_failed" ||
        event.type === "run_cancelled"
      ) {
        if (run?.project_id) {
          queryClient.invalidateQueries({ queryKey: ["artifacts", run.project_id] });
          queryClient.invalidateQueries({ queryKey: ["project", run.project_id] });
          queryClient.invalidateQueries({ queryKey: ["runs", run.project_id] });
        } else {
          queryClient.invalidateQueries({ queryKey: ["artifacts"] });
        }
        queryClient.invalidateQueries({ queryKey: ["runs"] });
        queryClient.invalidateQueries({ queryKey: ["project"] });
        onComplete?.();
        setContinueReplacementStage(null);
      }
    },
    [
      appendMessage,
      onComplete,
      queryClient,
      run?.project_id,
      run?.run_checkpoint?.stage_id,
      run?.run_id,
      continueReplacementStage,
      resolveHumanInterventionProgress,
      setAutoOutputPath,
      setContinueReplacementStage,
      trimRunStatusMessagesForContinue,
    ],
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
      trimmedCheckpointStageRef.current = null;
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

    let cancelled = false;

    const hydrateActiveRunEvents = async () => {
      if (!run?.run_id || sinceRef.current > 0) return;
      try {
        const res = await fetch(runEventsUrl(run.run_id, 0), {
          headers: { Accept: "application/json" },
        });
        if (!res.ok || cancelled) return;
        const body = (await res.json()) as { events?: RunEvent[] };
        const historicalEvents = body.events ?? [];
        for (const event of historicalEvents) {
          sinceRef.current = Math.max(sinceRef.current, Number(event.id) + 1);
          processEvent(event);
        }
      } catch {
        /* SSE/polling below will keep trying */
      }
    };

    const openEventSource = () => {
      if (cancelled || !run?.run_id) return;
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
        if (run?.project_id) {
          queryClient.invalidateQueries({ queryKey: ["artifacts", run.project_id] });
          queryClient.invalidateQueries({ queryKey: ["project", run.project_id] });
          queryClient.invalidateQueries({ queryKey: ["runs", run.project_id] });
        } else {
          queryClient.invalidateQueries({ queryKey: ["artifacts"] });
        }
        onComplete?.();
      });

      es.onerror = () => {
        setConnected(false);
      };
    };

    void hydrateActiveRunEvents().finally(openEventSource);

    return () => {
      cancelled = true;
      esRef.current?.close();
      esRef.current = null;
      setConnected(false);
    };
  }, [
    run?.run_id,
    run?.status,
    roughIdea,
    processEvent,
    setMessages,
    appendMessage,
    queryClient,
    onComplete,
  ]);

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
