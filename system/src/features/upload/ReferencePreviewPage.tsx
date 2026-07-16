import { Download, Loader2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { apiUrl, responseErrorMessage } from "@/api/client";
import { UI_TEXT } from "@/i18n";
import { useUiStore } from "@/stores/uiStore";

type PreviewState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; name: string; contentType: string; content?: string; url: string };

function csvRows(content: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let quoted = false;
  for (let index = 0; index < content.length; index += 1) {
    const char = content[index];
    const next = content[index + 1];
    if (quoted) {
      if (char === '"' && next === '"') {
        cell += '"';
        index += 1;
      } else if (char === '"') {
        quoted = false;
      } else {
        cell += char;
      }
      continue;
    }
    if (char === '"') quoted = true;
    else if (char === ",") {
      row.push(cell);
      cell = "";
    } else if (char === "\n") {
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
    } else if (char !== "\r") cell += char;
  }
  row.push(cell);
  if (row.some((value) => value.trim())) rows.push(row);
  return rows;
}

function filenameFromDisposition(value: string | null, fallback: string) {
  const match = /filename\*=UTF-8''([^;]+)|filename="?([^";]+)"?/i.exec(value ?? "");
  const raw = match?.[1] || match?.[2] || fallback;
  try {
    return decodeURIComponent(raw);
  } catch {
    return raw;
  }
}

function referencePreviewMatch() {
  const match = /^\/([^/]+)\/references\/([^/]+)\/preview\/?$/.exec(window.location.pathname);
  if (!match) return null;
  return {
    projectId: decodeURIComponent(match[1]),
    name: decodeURIComponent(match[2]),
  };
}

function extension(name: string) {
  const dot = name.lastIndexOf(".");
  return dot >= 0 ? name.slice(dot).toLowerCase() : "";
}

function isPdfPreview(name: string, contentType: string) {
  return contentType.includes("pdf") || extension(name) === ".pdf";
}

function isTextPreview(name: string, contentType: string) {
  const ext = extension(name);
  return [".txt", ".md", ".json", ".csv"].includes(ext)
    || contentType.includes("text/")
    || contentType.includes("json")
    || contentType.includes("csv")
    || contentType.includes("markdown");
}

function rawReferenceUrl(projectId: string, name: string) {
  return `/${encodeURIComponent(projectId)}/references/${encodeURIComponent(name)}?inline=true`;
}

function downloadReferenceUrl(projectId: string, name: string) {
  return apiUrl(`/api/projects/${encodeURIComponent(projectId)}/references/${encodeURIComponent(name)}`);
}

function renderContent(state: Extract<PreviewState, { status: "ready" }>, noContent: string) {
  const ext = extension(state.name);
  const content = state.content ?? "";
  if (isPdfPreview(state.name, state.contentType)) {
    return <iframe title={state.name} src={state.url} className="h-screen w-full border-0" />;
  }
  if (ext === ".md" || state.contentType.includes("markdown")) {
    return (
      <article className="markdown-body mx-auto max-w-5xl p-6 text-slate-800">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{content || noContent}</ReactMarkdown>
      </article>
    );
  }
  if (ext === ".json" || state.contentType.includes("json")) {
    let formatted = content;
    try {
      formatted = JSON.stringify(JSON.parse(content), null, 2);
    } catch {
      formatted = content;
    }
    return <pre className="m-6 whitespace-pre-wrap break-words rounded-control bg-slate-950 p-4 font-mono text-sm leading-6 text-slate-50">{formatted || noContent}</pre>;
  }
  if (ext === ".csv" || state.contentType.includes("csv")) {
    const rows = csvRows(content);
    const [headers, ...bodyRows] = rows;
    if (!headers) return <p className="p-6 text-sm text-slate-500">{noContent}</p>;
    return (
      <div className="p-6">
        <div className="overflow-auto rounded-control border border-gray-200 bg-white">
          <table className="min-w-full border-collapse text-left text-sm">
            <thead className="bg-slate-50 text-slate-600">
              <tr>{headers.map((cell, index) => <th key={index} className="border-b border-r border-gray-200 px-3 py-2 font-semibold last:border-r-0">{cell}</th>)}</tr>
            </thead>
            <tbody>
              {bodyRows.map((row, rowIndex) => (
                <tr key={rowIndex} className="odd:bg-white even:bg-slate-50/60">
                  {headers.map((_, cellIndex) => <td key={cellIndex} className="border-b border-r border-gray-100 px-3 py-2 align-top text-slate-700 last:border-r-0">{row[cellIndex] ?? ""}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    );
  }
  return <pre className="m-6 whitespace-pre-wrap break-words rounded-control bg-slate-50 p-4 font-mono text-sm leading-6 text-slate-700">{content || noContent}</pre>;
}

export function isReferencePreviewPath() {
  return referencePreviewMatch() !== null;
}

export function ReferencePreviewPage() {
  const t = UI_TEXT[useUiStore.getState().language];
  const target = useMemo(referencePreviewMatch, []);
  const [state, setState] = useState<PreviewState>({ status: "loading" });

  useEffect(() => {
    if (!target) return;
    const controller = new AbortController();
    const rawUrl = apiUrl(rawReferenceUrl(target.projectId, target.name));
    const load = async () => {
      const raw = await fetch(rawUrl, { credentials: "include", signal: controller.signal });
      if (!raw.ok) throw new Error(await responseErrorMessage(raw, t.readFileFailed));
      return { response: raw, url: rawUrl };
    };
    load()
      .then(async (response) => {
        const contentType = response.response.headers.get("content-type") ?? "";
        const name = filenameFromDisposition(response.response.headers.get("content-disposition"), target.name);
        if (isPdfPreview(name, contentType)) {
          setState({ status: "ready", name, contentType, url: response.url });
          return;
        }
        if (!isTextPreview(name, contentType)) {
          setState({ status: "error", message: t.unsupportedPreview });
          return;
        }
        setState({ status: "ready", name, contentType, content: await response.response.text(), url: response.url });
      })
      .catch((error) => {
        if (controller.signal.aborted) return;
        setState({ status: "error", message: error instanceof Error ? error.message : t.readFileFailed });
      });
    return () => controller.abort();
  }, [t.readFileFailed, t.unsupportedPreview, target]);

  if (!target) return null;
  if (state.status === "ready" && isPdfPreview(state.name, state.contentType)) {
    return renderContent(state, t.noContent);
  }

  return (
    <div className="flex min-h-screen flex-col bg-white text-slate-900">
      <header className="flex h-14 shrink-0 items-center justify-between border-b border-gray-200 px-4">
        <div className="min-w-0">
          <h1 className="truncate text-sm font-semibold">{state.status === "ready" ? state.name : target.name}</h1>
        </div>
        <a
          className="inline-flex items-center gap-1 rounded-control border border-gray-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-gray-50"
          href={downloadReferenceUrl(target.projectId, target.name)}
          download={target.name}
        >
          <Download className="h-3.5 w-3.5" />
          {t.download}
        </a>
      </header>
      <main className="min-h-0 flex-1 overflow-auto">
        {state.status === "loading" ? (
          <div className="flex min-h-[calc(100vh-56px)] flex-col items-center justify-center gap-3 text-center">
            <Loader2 className="h-7 w-7 animate-spin text-slate-400" />
            <p className="text-sm text-slate-500">{t.readingFile}</p>
          </div>
        ) : null}
        {state.status === "error" ? <p className="p-6 text-sm text-red-600">{state.message}</p> : null}
        {state.status === "ready" ? renderContent(state, t.noContent) : null}
      </main>
    </div>
  );
}
