export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, detail: unknown) {
    super(apiErrorMessage(detail));
    this.status = status;
    this.detail = detail;
  }
}

export function apiUrl(path: string): string {
  if (/^https?:\/\//i.test(path)) return path;
  return path.startsWith("/") ? path : `/${path}`;
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
    credentials: "include",
    headers: {
      Accept: "application/json",
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
