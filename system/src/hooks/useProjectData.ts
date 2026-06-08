import { useQuery } from "@tanstack/react-query";
import {
  fetchArtifacts,
  fetchProject,
  fetchReferences,
} from "@/api/projects";

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
