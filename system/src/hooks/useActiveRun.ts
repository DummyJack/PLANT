import { useQuery } from "@tanstack/react-query";
import { fetchRuns } from "@/api/runs";

const ACTIVE = new Set([
  "queued",
  "running",
  "waiting_for_human",
  "cancelling",
]);

export function useRuns(projectId: string | null) {
  return useQuery({
    queryKey: ["runs", projectId],
    queryFn: () => fetchRuns(projectId ?? undefined),
    enabled: !!projectId,
    refetchInterval: 5000,
  });
}

export function useActiveRun(projectId: string | null) {
  const runs = useRuns(projectId);
  const active =
    runs.data?.runs.find((r) => ACTIVE.has(r.status)) ?? null;
  return { ...runs, activeRun: active };
}
