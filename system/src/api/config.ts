import type { PlantConfig } from "@/types/api";
import { apiFetch } from "./client";

export function fetchConfig() {
  return apiFetch<{ config: PlantConfig }>("/api/config");
}

export function patchConfig(patch: Partial<PlantConfig>) {
  return apiFetch<{ saved: boolean; config: PlantConfig }>("/api/config", {
    method: "PATCH",
    body: JSON.stringify({ patch }),
  });
}
