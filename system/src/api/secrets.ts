import { apiFetch } from "./client";

export interface ModelApiKeyStatus {
  provider: string;
  env_key: string;
  configured: boolean;
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
