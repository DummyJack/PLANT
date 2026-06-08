import { useEffect, useState } from "react";
import { fetchRuns } from "@/api/runs";
import { useChatStore } from "@/stores/chatStore";
import type { ChatMessage, FileTreeNode, RunState } from "@/types/api";
import {
  buildInitialUserMessage,
  logEventToChat,
  mergeChatMessages,
} from "@/utils/logParser";

const ACTIVE = new Set([
  "queued",
  "running",
  "waiting_for_human",
  "cancelling",
]);

async function loadRunLogMessages(projectId: string): Promise<ChatMessage[]> {
  try {
    const { runs } = await fetchRuns(projectId);
    const last = runs
      .filter((r) => r.status === "completed" || r.status === "failed")
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
      return rows
        .map((e) => logEventToChat(e as Parameters<typeof logEventToChat>[0]))
        .filter((m): m is NonNullable<typeof m> => !!m);
    }

    const text = await res.text();
    const messages = [];
    for (const line of text.split("\n")) {
      const trimmed = line.trim();
      if (!trimmed.startsWith("data:")) continue;
      try {
        const event = JSON.parse(trimmed.slice(5).trim());
        const chat = logEventToChat(event);
        if (chat) messages.push(chat);
      } catch {
        /* skip malformed SSE chunks */
      }
    }
    return messages;
  } catch {
    return [];
  }
}

function buildArtifactExecutionMessages(items: FileTreeNode[]): ChatMessage[] {
  const paths = new Set(
    items.filter((item) => item.kind === "file").map((item) => item.path),
  );
  const messages: ChatMessage[] = [];
  const add = (
    id: string,
    speaker: string,
    action: string,
    text: string,
    outputPath?: string,
  ) => {
    messages.push({
      id,
      role: "agent",
      kind: "action",
      speaker,
      label:
        speaker === "analyst"
          ? "Analyst"
          : speaker === "expert"
            ? "Expert"
            : speaker === "modeler"
              ? "Modeler"
              : speaker === "documentor"
                ? "Documentor"
                : speaker,
      action,
      status: "done",
      text,
      outputPath,
    });
  };
  const output = (id: string, text: string, outputPath?: string) => {
    messages.push({
      id,
      role: "system",
      kind: "output",
      status: "done",
      text,
      outputPath,
    });
  };

  const draftVersions = items
    .filter((item) => /^results\/drafts\/draft_v\d+\.html$/i.test(item.path))
    .map((item) => Number(/draft_v(\d+)/i.exec(item.path)?.[1] ?? -1))
    .filter((version) => version >= 0)
    .sort((a, b) => a - b);
  const modelCount = items.filter(
    (item) => item.kind === "file" && /^results\/models\/.+\.(png|svg)$/i.test(item.path),
  ).length;
  const momCount = items.filter(
    (item) => item.kind === "file" && /^results\/MoM\/.+\.html$/i.test(item.path),
  ).length;

  if (draftVersions.length) {
    const version = draftVersions[draftVersions.length - 1];
    add(
      "artifact-summary-draft",
      "analyst",
      "generate_draft",
      `已整理 Draft v${version}`,
      `results/drafts/draft_v${version}.html`,
    );
  }
  if (paths.has("results/report/conflict_report.html")) {
    add(
      "artifact-summary-conflict",
      "analyst",
      "detect_conflicts",
      "已產生需求衝突報告",
      "results/report/conflict_report.html",
    );
  }
  if (paths.has("artifact/feedback.json")) {
    add("artifact-summary-feedback", "expert", "update_feedback", "已整理領域回饋");
  }
  if (modelCount) {
    const firstModel = items.find(
      (item) => item.kind === "file" && /^results\/models\/.+\.(png|svg)$/i.test(item.path),
    );
    add(
      "artifact-summary-models",
      "modeler",
      "generate_system_models",
      `已產生 ${modelCount} 個系統模型`,
      firstModel?.path,
    );
  }
  if (momCount) {
    const latestMom = items
      .filter((item) => item.kind === "file" && /^results\/MoM\/.+\.html$/i.test(item.path))
      .sort((a, b) => a.path.localeCompare(b.path))
      .at(-1);
    output("artifact-summary-mom", `已產生 ${momCount} 份 MoM`, latestMom?.path);
  }
  if (paths.has("results/design_rationale.html")) {
    add(
      "artifact-summary-dr",
      "documentor",
      "generate_design_rationale",
      "已產生 Design Rationale",
      "results/design_rationale.html",
    );
  }
  if (paths.has("results/srs.html")) {
    add("artifact-summary-srs", "documentor", "generate_srs", "已產生 SRS", "results/srs.html");
  }
  if (messages.length) {
    output("artifact-summary-html", "已完成 HTML Artifact 匯出");
  }
  return messages;
}

export function useProjectChatHydration(
  projectId: string | null,
  artifactItems: FileTreeNode[] | undefined,
  roughIdea: string,
  activeRun: RunState | null,
  artifactsReady: boolean,
) {
  const setMessages = useChatStore((s) => s.setMessages);
  const [loading, setLoading] = useState(false);
  const [hasHistory, setHasHistory] = useState(false);

  useEffect(() => {
    if (!projectId) {
      setLoading(false);
      setHasHistory(false);
      return;
    }

    if (activeRun && ACTIVE.has(activeRun.status)) {
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
      const fallbackMsgs = logMsgs.length
        ? []
        : buildArtifactExecutionMessages(artifactItems ?? []);

      if (cancelled) return;

      if (!logMsgs.length && !fallbackMsgs.length) {
        setHasHistory(false);
        setLoading(false);
        return;
      }

      const seed = roughIdea.trim()
        ? [buildInitialUserMessage(roughIdea.trim())]
        : [];
      setMessages(mergeChatMessages([...seed, ...(logMsgs.length ? logMsgs : fallbackMsgs)]));
      setHasHistory(true);
      setLoading(false);
    };

    void hydrate();
    return () => {
      cancelled = true;
    };
  }, [
    projectId,
    artifactItems,
    roughIdea,
    activeRun?.run_id,
    activeRun?.status,
    artifactsReady,
    setMessages,
  ]);

  return { loading, hasHistory };
}
