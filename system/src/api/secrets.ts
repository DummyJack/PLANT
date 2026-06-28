import { apiFetch } from "./client";

export interface ModelApiKeyStatus {
  provider: string;
  env_key: string;
  configured: boolean;
  status?: "untested" | "valid" | "invalid";
  valid?: boolean;
  error?: string | null;
  tested_at?: string | null;
}

export interface ModelApiKeyTestResult extends ModelApiKeyStatus {
  valid: boolean;
  error?: string | null;
}

export function fetchModelApiKeys() {
  return apiFetch<{ providers: ModelApiKeyStatus[] }>("/api/secrets/model-api-keys");
}

export function updateModelApiKey(provider: string, api_key: string) {
  return apiFetch<{
    saved: boolean;
    provider: string;
    env_key: string;
    configured: boolean;
  }>("/api/secrets/model-api-keys", {
    method: "PUT",
    body: JSON.stringify({ provider, api_key }),
  });
}

export function testModelApiKey(provider: string) {
  return apiFetch<ModelApiKeyTestResult>("/api/secrets/model-api-keys/test", {
    method: "POST",
    body: JSON.stringify({ provider }),
  });
}

export function deleteModelApiKey(provider: string) {
  return apiFetch<{
    deleted: boolean;
    provider: string;
    env_key: string;
    configured: boolean;
    removed: boolean;
  }>(`/api/secrets/model-api-keys/${provider}`, {
    method: "DELETE",
  });
}

export function activateCode(code: string) {
  return apiFetch<{ activated: boolean }>("/api/secrets/activation-code", {
    method: "POST",
    body: JSON.stringify({ code }),
  });
}

export function fetchActivationStatus() {
  return apiFetch<{ activated: boolean }>("/api/secrets/activation-code");
}

export function deactivateCode() {
  return apiFetch<{ activated: boolean }>("/api/secrets/activation-code", {
    method: "DELETE",
  });
}
