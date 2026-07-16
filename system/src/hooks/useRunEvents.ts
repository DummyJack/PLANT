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
  const [connected, setConnected] = useState(false);
  const [connectionError, setConnectionError] = useState(false);
  const sinceRef = useRef(0);
  const esRef = useRef<EventSource | null>(null);
  const runIdRef = useRef<string | null>(null);
  const trimmedCheckpointStageRef = useRef<string | null>(null);
  const sseFailedRef = useRef(false);
  const pollingFailureCountRef = useRef(0);
  const activeRunIdRef = useRef<string | null>(run?.run_id ?? null);
  const processedEventKeysRef = useRef<Set<string>>(new Set());
  activeRunIdRef.current = run?.run_id ?? null;
  const roughIdeaRef = useRef(roughIdea);
  roughIdeaRef.current = roughIdea;
  const appendMessage = useChatStore((s) => s.appendMessage);
  const setMessages = useChatStore((s) => s.setMessages);
  const resolveHumanInterventionProgress = useChatStore((s) => s.resolveHumanInterventionProgress);
  const resolveStageProgress = useChatStore((s) => s.resolveStageProgress);
  const resolveHeartbeatProgress = useChatStore((s) => s.resolveHeartbeatProgress);
  const resolveStepProgress = useChatStore((s) => s.resolveStepProgress);
  const continueReplacementStage = useChatStore((s) => s.continueReplacementStage);
  const setContinueReplacementStage = useChatStore((s) => s.setContinueReplacementStage);
  const trimRunStatusMessagesForContinue = useChatStore((s) => s.trimRunStatusMessagesForContinue);
  const setAutoOutputPath = useUiStore((s) => s.setAutoOutputPath);
  const queryClient = useQueryClient();

  const resolveDisconnectedProgress = useCallback(() => {
    resolveHeartbeatProgress();
    const runningStages = useChatStore
      .getState()
      .messages.filter(
        (message) =>
          message.role === "system" &&
          message.kind === "stage" &&
          message.status === "running",
      )
      .map((message) => String(message.stage ?? "").trim())
      .filter(Boolean);
    runningStages.forEach((stage) => resolveStageProgress(stage));
  }, [resolveHeartbeatProgress, resolveStageProgress]);

  const processEvent = useCallback(
    (event: RunEvent) => {
      const capturedRunId = run?.run_id ?? null;
      if (!capturedRunId || activeRunIdRef.current !== capturedRunId) return;
      const eventKey = `${capturedRunId}:${event.id}`;
      if (processedEventKeysRef.current.has(eventKey)) return;
      processedEventKeysRef.current.add(eventKey);
      if (event.type !== "heartbeat") {
        resolveHeartbeatProgress();
      }
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
      const shouldTrimContinueDocumentGeneration =
        event.type === "stage_started" &&
        run?.mode === "continue" &&
        eventStage === "document_generation" &&
        trimmedCheckpointStageRef.current !== `${run?.run_id || ""}:document_generation`;
      if (
        shouldTrimContinueDocumentGeneration ||
        (
          event.type === "stage_started" &&
          checkpointStage &&
          eventStage === checkpointStage &&
          (
            checkpointStage !== "formal_meeting" ||
            checkpointRound <= 0 ||
            new RegExp(`第\\s*${checkpointRound}\\s*輪正式會議開始`, "u").test(eventText)
          ) &&
          trimmedCheckpointStageRef.current !== trimKey
        )
      ) {
        trimRunStatusMessagesForContinue(
          shouldTrimContinueDocumentGeneration ? "document_generation" : checkpointTarget,
        );
        trimmedCheckpointStageRef.current = shouldTrimContinueDocumentGeneration
          ? `${run?.run_id || ""}:document_generation`
          : trimKey;
      }
      const chats = logEventToChats(event);
      if (event.type === "stage_completed") {
        resolveStageProgress(event.stage_id);
      }
      if (event.type === "step_completed") {
        resolveStepProgress(event.stage_id, event.step_id ?? event.action);
        if (event.output_path) {
          queryClient.invalidateQueries({ queryKey: ["chat-preview"] });
        }
      }
      if (
        event.type === "human_decision_submitted" ||
        event.type === "human_decision_auto_skipped"
      ) {
        resolveHumanInterventionProgress(event.decision);
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
        setConnectionError(false);
        setAutoOutputPath(null);
        if (run?.project_id) {
          queryClient.invalidateQueries({ queryKey: ["artifacts", run.project_id] });
          queryClient.invalidateQueries({ queryKey: ["project", run.project_id] });
          queryClient.invalidateQueries({ queryKey: ["runs", run.project_id] });
          queryClient.invalidateQueries({ queryKey: ["cost-summary", run.project_id] });
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
      run?.mode,
      run?.run_checkpoint?.stage_id,
      run?.run_checkpoint?.round,
      run?.run_id,
      continueReplacementStage,
      resolveHumanInterventionProgress,
      resolveStageProgress,
      resolveHeartbeatProgress,
      resolveStepProgress,
      setAutoOutputPath,
      setContinueReplacementStage,
      trimRunStatusMessagesForContinue,
    ],
  );

  // Reset event cursor when run changes or disconnects
  useEffect(() => {
    if (!run?.run_id) {
      sinceRef.current = 0;
      runIdRef.current = null;
      processedEventKeysRef.current.clear();
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
      runIdRef.current = run.run_id;
      processedEventKeysRef.current.clear();
      trimmedCheckpointStageRef.current = null;
    }

    const idea = roughIdeaRef.current?.trim();
    if (idea) {
      const currentMessages = useChatStore.getState().messages;
      if (currentMessages.length === 0) {
        setMessages(mergeChatMessages([buildInitialUserMessage(idea)]));
      } else if (!currentMessages.some((msg) => msg.id === "rough-idea")) {
        setMessages(mergeChatMessages([buildInitialUserMessage(idea), ...currentMessages]));
      }
    }

    let cancelled = false;
    const hydrateController = new AbortController();

    const hydrateActiveRunEvents = async () => {
      if (!run?.run_id || sinceRef.current > 0) return;
      try {
        const res = await fetch(runEventsUrl(run.run_id, 0), {
          headers: { Accept: "application/json" },
          signal: hydrateController.signal,
        });
        if (!res.ok || cancelled) return;
        const body = (await res.json()) as { events?: RunEvent[] };
        if (cancelled || activeRunIdRef.current !== run.run_id) return;
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
      es.onopen = () => {
        if (cancelled || activeRunIdRef.current !== run.run_id) {
          es.close();
          return;
        }
        sseFailedRef.current = false;
        pollingFailureCountRef.current = 0;
        setConnected(true);
        setConnectionError(false);
      };

      es.onmessage = (ev) => {
        if (cancelled || activeRunIdRef.current !== run.run_id) return;
        try {
          const data = JSON.parse(ev.data) as RunEvent;
          sinceRef.current = Math.max(sinceRef.current, Number(data.id) + 1);
          processEvent(data);
        } catch {
          /* ignore parse errors */
        }
      };

      es.addEventListener("done", () => {
        if (cancelled || activeRunIdRef.current !== run.run_id) return;
        es.close();
        esRef.current = null;
        setConnected(false);
        resolveDisconnectedProgress();
        setAutoOutputPath(null);
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
        if (cancelled || activeRunIdRef.current !== run.run_id) return;
        es.close();
        esRef.current = null;
        sseFailedRef.current = true;
        setConnected(false);
      };
    };

    void hydrateActiveRunEvents().finally(openEventSource);

    return () => {
      cancelled = true;
      hydrateController.abort();
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
    resolveDisconnectedProgress,
    queryClient,
    onComplete,
    setAutoOutputPath,
  ]);

  useEffect(() => {
    if (!run?.run_id) return;
    if (!["queued", "running", "waiting_for_human", "cancelling"].includes(run.status)) {
      return;
    }
    let cancelled = false;
    let pollController: AbortController | null = null;
    let pollInFlight = false;
    const poll = async () => {
      if (connected || cancelled || pollInFlight) return;
      pollInFlight = true;
      try {
        pollController = new AbortController();
        const res = await fetch(runEventsUrl(run.run_id, sinceRef.current), {
          headers: { Accept: "application/json" },
          signal: pollController.signal,
        });
        if (!res.ok) {
          pollingFailureCountRef.current += 1;
          if (sseFailedRef.current && pollingFailureCountRef.current >= 2) {
            resolveDisconnectedProgress();
            setConnectionError(true);
          }
          return;
        }
        const body = (await res.json()) as { events?: RunEvent[] };
        if (cancelled || activeRunIdRef.current !== run.run_id) return;
        pollingFailureCountRef.current = 0;
        setConnectionError(false);
        for (const event of body.events ?? []) {
          sinceRef.current = Math.max(sinceRef.current, Number(event.id) + 1);
          processEvent(event);
        }
      } catch {
        if (cancelled) return;
        pollingFailureCountRef.current += 1;
        if (sseFailedRef.current && pollingFailureCountRef.current >= 2) {
          resolveDisconnectedProgress();
          setConnectionError(true);
        }
      } finally {
        pollInFlight = false;
      }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 2000);
    return () => {
      cancelled = true;
      pollController?.abort();
      window.clearInterval(timer);
    };
  }, [run?.run_id, run?.status, connected, processEvent, resolveDisconnectedProgress]);

  return { connectionError };
}
