import type { PlantConfig } from "@/types/api";
import { apiFetch } from "./client";

export function fetchConfig() {
  return apiFetch<{ config: PlantConfig }>("/api/config");
}

export function updateConfig(config: PlantConfig) {
  return apiFetch<{ saved: boolean; config: PlantConfig }>("/api/config", {
    method: "PUT",
    body: JSON.stringify({ config }),
  });
}

export function validateConfig(config: PlantConfig) {
  return apiFetch<{ valid: boolean; errors: string[] }>(
    "/api/config/validate",
    {
      method: "POST",
      body: JSON.stringify({ config }),
    },
  );
}
