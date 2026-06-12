export function errorMessage(error: unknown, fallback: string): string {
  const direct = detailText(error);
  if (direct) return direct;

  if (error instanceof Error) {
    try {
      const parsed = JSON.parse(error.message) as unknown;
      const parsedDetail = detailText(parsed);
      if (parsedDetail) return parsedDetail;
    } catch {
      /* keep raw message */
    }
    return error.message || fallback;
  }

  return fallback;
}

function detailText(value: unknown): string {
  if (!value || typeof value !== "object") return "";
  const detail = (value as { detail?: unknown }).detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (typeof item === "string") return item;
        if (item && typeof item === "object") {
          const msg = (item as { msg?: unknown; message?: unknown }).msg;
          const message = (item as { msg?: unknown; message?: unknown }).message;
          return typeof msg === "string"
            ? msg
            : typeof message === "string"
              ? message
              : "";
        }
        return "";
      })
      .filter(Boolean);
    if (messages.length) return messages.join("；");
  }
  if (detail && typeof detail === "object") {
    const nested = detailText(detail);
    if (nested) return nested;
  }
  return "";
}
