import type { CostSummary, FileContent, FileTreeNode } from "@/types/api";
import { apiFetch, apiUrl } from "./client";

export function fetchProjects() {
  return apiFetch<{ projects: import("@/types/api").ProjectSummary[] }>(
    "/api/projects",
  );
}

export function createProject(rough_idea: string) {
  return apiFetch<{ project_id: string; rough_idea: string }>(
    "/api/projects",
    {
      method: "POST",
      body: JSON.stringify({ rough_idea }),
    },
  );
}

export function fetchProject(projectId: string) {
  return apiFetch<{
    project_id: string;
    project: Record<string, unknown>;
    path: string;
  }>(`/api/projects/${projectId}`);
}

export function updateProject(
  projectId: string,
  body: { rough_idea?: string; meta?: Record<string, unknown> },
) {
  return apiFetch(`/api/projects/${projectId}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export function deleteProject(projectId: string) {
  return apiFetch(`/api/projects/${projectId}`, { method: "DELETE" });
}

export function fetchReferences(projectId: string) {
  return apiFetch<{
    project_id: string;
    references: Array<{ name: string; size: number }>;
  }>(`/api/projects/${projectId}/references`);
}

export function uploadReference(projectId: string, file: File) {
  const form = new FormData();
  form.append("file", file);
  return apiFetch(`/api/projects/${projectId}/references`, {
    method: "POST",
    body: form,
  });
}

export function deleteReference(projectId: string, name: string) {
  return apiFetch(`/api/projects/${projectId}/references/${encodeURIComponent(name)}`, {
    method: "DELETE",
  });
}

export function referenceDownloadUrl(projectId: string, name: string) {
  return apiUrl(`/api/projects/${projectId}/references/${encodeURIComponent(name)}`);
}

export function referencePreviewUrl(projectId: string, name: string) {
  return apiUrl(`/${encodeURIComponent(projectId)}/references/${encodeURIComponent(name)}?inline=true`);
}

export function referencePreviewPageUrl(projectId: string, name: string) {
  return apiUrl(`/${encodeURIComponent(projectId)}/references/${encodeURIComponent(name)}/preview`);
}

export function manualIndexUrl(projectId: string) {
  return apiUrl(`/${encodeURIComponent(projectId)}/manual`);
}

function encodePathSegments(path: string) {
  return path
    .split("/")
    .filter(Boolean)
    .map(encodeURIComponent)
    .join("/");
}

export function manualFileUrl(projectId: string, path: string) {
  if (/^results\/srs\.html$/i.test(path)) {
    return apiUrl(`/${encodeURIComponent(projectId)}/manual/srs`);
  }
  if (/^results\/design_rationale\.html$/i.test(path)) {
    return apiUrl(`/${encodeURIComponent(projectId)}/manual/dr`);
  }
  return apiUrl(`/${encodeURIComponent(projectId)}/manual/${encodePathSegments(path)}`);
}

export function fetchCostSummary(projectId: string) {
  return apiFetch<{ project_id: string; cost_summary: CostSummary }>(
    `/api/projects/${projectId}/cost-summary`,
  );
}

export function fetchArtifacts(projectId: string) {
  return apiFetch<{ items: FileTreeNode[] }>(
    `/api/projects/${projectId}/artifacts`,
  );
}

export function fetchFile(projectId: string, path: string) {
  return apiFetch<FileContent>(
    `/api/projects/${projectId}/files?path=${encodeURIComponent(path)}`,
  );
}

export function writeFile(projectId: string, path: string, content: string) {
  return apiFetch(`/api/projects/${projectId}/files?path=${encodeURIComponent(path)}`, {
    method: "PUT",
    body: JSON.stringify({ content }),
  });
}

export function exportProject(
  projectId: string,
  opts: { html?: boolean; cost?: boolean; manual?: boolean } = {},
) {
  return apiFetch(`/api/projects/${projectId}/export`, {
    method: "POST",
    body: JSON.stringify({ html: true, cost: false, manual: true, ...opts }),
  });
}
