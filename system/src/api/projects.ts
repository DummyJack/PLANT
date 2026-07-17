import type { BootstrapResponse, CostSummary, FileContent, FileTreeNode } from "@/types/api";
import { apiFetch, apiUrl, responseErrorMessage } from "./client";

export function fetchBootstrap() {
  return apiFetch<BootstrapResponse>("/api/bootstrap");
}

export function createProject(rough_idea: string, creation_id?: string) {
  return apiFetch<{ project_id: string; rough_idea: string }>(
    "/api/projects",
    {
      method: "POST",
      body: JSON.stringify({ rough_idea, creation_id }),
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

export async function fetchPdfExport(projectId: string, path: string) {
  const url = apiUrl(
    `/api/projects/${encodeURIComponent(projectId)}/exports/pdf?path=${encodeURIComponent(path)}`,
  );
  const response = await fetch(url, {
    credentials: "include",
    headers: { Accept: "application/pdf" },
  });
  if (!response.ok) {
    throw new Error(await responseErrorMessage(response, "PDF export failed"));
  }
  return response.blob();
}
