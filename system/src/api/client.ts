export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, detail: unknown) {
    super(apiErrorMessage(detail));
    this.status = status;
    this.detail = detail;
  }
}

const LOCAL_API_BASE_URL = "http://127.0.0.1:8000/api";
const PUBLIC_API_BASE_URL = "https://plant.dummyjack.com/api";

function useLocalhost(value: string | undefined, fallback: boolean): boolean {
  if (value == null || value.trim() === "") return fallback;
  return ["1", "true", "yes", "on"].includes(value.trim().toLowerCase());
}

const API_BASE_URL = (
  useLocalhost(import.meta.env.develop_backend, true)
    ? LOCAL_API_BASE_URL
    : PUBLIC_API_BASE_URL
).replace(/\/+$/, "");

export function apiUrl(path: string): string {
  if (/^https?:\/\//i.test(path)) return path;
  if (!API_BASE_URL) return path;
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  if (API_BASE_URL.endsWith("/api") && normalizedPath === "/api") {
    return API_BASE_URL;
  }
  if (API_BASE_URL.endsWith("/api") && normalizedPath.startsWith("/api/")) {
    return `${API_BASE_URL}${normalizedPath.slice("/api".length)}`;
  }
  return `${API_BASE_URL}${normalizedPath}`;
}

function apiErrorMessage(detail: unknown): string {
  if (typeof detail === "string") return detail;
  const fromDetail = detailText(detail);
  if (fromDetail) return fromDetail;
  try {
    return JSON.stringify(detail);
  } catch {
    return "Request failed";
  }
}

function detailText(value: unknown): string {
  if (!value || typeof value !== "object") return "";
  const body = value as { detail?: unknown; message?: unknown };
  if (typeof body.detail === "string") return body.detail;
  if (typeof body.message === "string") return body.message;
  if (Array.isArray(body.detail)) {
    const messages = body.detail
      .map((item) => {
        if (typeof item === "string") return item;
        if (!item || typeof item !== "object") return "";
        const row = item as { msg?: unknown; message?: unknown };
        return typeof row.msg === "string"
          ? row.msg
          : typeof row.message === "string"
            ? row.message
            : "";
      })
      .filter(Boolean);
    if (messages.length) return messages.join("；");
  }
  if (body.detail && typeof body.detail === "object") {
    return detailText(body.detail);
  }
  return "";
}

export async function apiFetch<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const res = await fetch(apiUrl(path), {
    ...init,
    headers: {
      ...(init?.body instanceof FormData
        ? {}
        : { "Content-Type": "application/json" }),
      ...init?.headers,
    },
  });
  if (!res.ok) {
    let detail: unknown = res.statusText;
    try {
      detail = await res.json();
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}
