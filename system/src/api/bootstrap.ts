import type { BootstrapResponse } from "@/types/api";
import { apiFetch } from "./client";

export function fetchBootstrap() {
  return apiFetch<BootstrapResponse>("/api/bootstrap");
}
