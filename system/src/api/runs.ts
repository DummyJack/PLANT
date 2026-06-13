import type { RunEvent, RunState } from "@/types/api";
import { apiFetch } from "./client";

export function fetchRuns(projectId?: string) {
  const q = projectId ? `?project_id=${encodeURIComponent(projectId)}` : "";
  return apiFetch<{ runs: RunState[] }>(`/api/runs${q}`);
}

export function createRun(body: {
  project_id: string;
  mode?: "new" | "continue";
  rounds?: number | null;
  max_issues?: number | null;
  rough_idea?: string | null;
  attached_reference_paths?: string[] | null;
  enable_agents?: Record<string, boolean>;
  stage_overrides?: Record<string, boolean>;
}) {
  return apiFetch<RunState>("/api/runs", {
    method: "POST",
    body: JSON.stringify({
      mode: "continue",
      ...body,
    }),
  });
}

export function fetchRun(runId: string) {
  return apiFetch<RunState>(`/api/runs/${runId}`);
}

export function cancelRun(runId: string) {
  return apiFetch<RunState>(`/api/runs/${runId}/cancel`, { method: "POST" });
}

export function submitDecision(
  runId: string,
  decisionId: string,
  payload: Record<string, unknown>,
) {
  return apiFetch<RunState>(`/api/runs/${runId}/decisions/${decisionId}`, {
    method: "POST",
    body: JSON.stringify({ payload }),
  });
}

export function runEventsUrl(runId: string, since = 0) {
  return `/api/runs/${runId}/events?since=${since}`;
}

export type { RunEvent };
