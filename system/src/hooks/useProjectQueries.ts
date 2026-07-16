import { useQuery } from "@tanstack/react-query";
import {
  fetchArtifacts,
  fetchBootstrap,
  fetchProject,
  fetchReferences,
} from "@/api/projects";
import { fetchRuns } from "@/api/runs";

const ACTIVE_RUN_STATUSES = new Set([
  "queued",
  "running",
  "waiting_for_human",
  "cancelling",
]);

export function useBootstrap(enabled = true) {
  return useQuery({
    queryKey: ["bootstrap"],
    queryFn: fetchBootstrap,
    enabled,
    refetchInterval: 30_000,
  });
}

export function useProjectData(projectId: string | null) {
  const project = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => fetchProject(projectId!),
    enabled: !!projectId,
  });
  const references = useQuery({
    queryKey: ["references", projectId],
    queryFn: () => fetchReferences(projectId!),
    enabled: !!projectId,
  });
  const artifacts = useQuery({
    queryKey: ["artifacts", projectId],
    queryFn: () => fetchArtifacts(projectId!),
    enabled: !!projectId,
  });
  return { project, references, artifacts };
}

function useRuns(projectId: string | null) {
  return useQuery({
    queryKey: ["runs", projectId],
    queryFn: () => fetchRuns(projectId ?? undefined),
    enabled: !!projectId,
    refetchInterval: 5000,
  });
}

export function useActiveRun(projectId: string | null) {
  const runs = useRuns(projectId);
  const activeRun =
    runs.data?.runs.find((run) => ACTIVE_RUN_STATUSES.has(run.status)) ?? null;
  return { ...runs, activeRun };
}
