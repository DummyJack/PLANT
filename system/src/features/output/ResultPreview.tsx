import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { fetchFile } from "@/api/projects";
import { PanelChrome } from "@/components/PanelChrome";
import { JsonArtifactView } from "@/features/output/JsonArtifactView";
import { OutputFilePicker } from "@/features/output/OutputFilePicker";
import { useUiStore } from "@/stores/uiStore";
import {
  buildOutputFiles,
  findModelPair,
} from "@/utils/buildOutputFiles";
import type { FileTreeNode } from "@/types/api";
import { cn } from "@/utils/cn";

interface ResultPreviewProps {
  projectId: string | null;
  items: FileTreeNode[];
}

interface TocItem {
  id: string;
  text: string;
  level: number;
}

function ModelDualView({
  projectId,
  sourcePath,
  imagePath,
  title,
}: {
  projectId: string;
  sourcePath?: string;
  imagePath?: string;
  title: string;
}) {
  const [tab, setTab] = useState<"diagram" | "source">(
    imagePath ? "diagram" : "source",
  );

  const source = useQuery({
    queryKey: ["file", projectId, sourcePath],
    queryFn: () => fetchFile(projectId, sourcePath!),
    enabled: !!sourcePath,
    retry: false,
  });

  const image = useQuery({
    queryKey: ["file", projectId, imagePath],
    queryFn: () => fetchFile(projectId, imagePath!),
    enabled: !!imagePath,
    retry: false,
  });

  const hasBoth = !!sourcePath && !!imagePath;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {hasBoth && (
        <div className="flex shrink-0 gap-1 border-b border-gray-100 px-3 py-2">
          <button
            type="button"
            className={cn(
              "rounded-control px-2.5 py-1 text-xs font-medium",
              tab === "diagram"
                ? "bg-slate-900 text-white"
                : "text-slate-600 hover:bg-gray-100",
            )}
            onClick={() => setTab("diagram")}
          >
            圖表
          </button>
          <button
            type="button"
            className={cn(
              "rounded-control px-2.5 py-1 text-xs font-medium",
              tab === "source"
                ? "bg-slate-900 text-white"
                : "text-slate-600 hover:bg-gray-100",
            )}
            onClick={() => setTab("source")}
          >
            PlantUML
          </button>
        </div>
      )}

      {hasBoth ? (
        tab === "diagram" ? (
          <div className="flex flex-1 items-center justify-center overflow-auto p-4">
            {image.isLoading ? (
              <p className="text-sm text-slate-500">載入圖表中…</p>
            ) : image.data?.content ? (
              <img
                src={`data:${image.data.mime ?? "image/png"};base64,${image.data.content}`}
                alt={title}
                className="max-h-full max-w-full rounded-control object-contain"
              />
            ) : (
              <p className="text-sm text-slate-500">圖形尚無法預覽</p>
            )}
          </div>
        ) : (
          <pre className="min-h-0 flex-1 overflow-auto p-4 font-mono text-xs leading-relaxed text-slate-700">
            {source.isLoading
              ? "載入中…"
              : (source.data?.content ?? "無法載入 PlantUML")}
          </pre>
        )
      ) : (
        <div className="grid min-h-0 flex-1 grid-cols-1 gap-px bg-gray-100 md:grid-cols-2">
          <div className="flex flex-col bg-white">
            <div className="shrink-0 border-b border-gray-100 px-3 py-1.5 text-xs font-medium text-slate-500">
              圖表
            </div>
            <div className="flex flex-1 items-center justify-center overflow-auto p-3">
              {imagePath ? (
                image.isLoading ? (
                  <p className="text-xs text-slate-500">載入中…</p>
                ) : image.data?.content ? (
                  <img
                    src={`data:${image.data.mime ?? "image/png"};base64,${image.data.content}`}
                    alt={title}
                    className="max-h-full max-w-full rounded-control object-contain"
                  />
                ) : (
                  <p className="text-xs text-slate-400">無圖表</p>
                )
              ) : (
                <p className="text-xs text-slate-400">無圖表</p>
              )}
            </div>
          </div>
          <div className="flex min-h-0 flex-col bg-white">
            <div className="shrink-0 border-b border-gray-100 px-3 py-1.5 text-xs font-medium text-slate-500">
              PlantUML
            </div>
            <pre className="min-h-0 flex-1 overflow-auto p-3 font-mono text-xs leading-relaxed text-slate-700">
              {sourcePath
                ? source.isLoading
                  ? "載入中…"
                  : (source.data?.content ?? "無法載入")
                : "無 PlantUML"}
            </pre>
          </div>
        </div>
      )}
    </div>
  );
}

export function ResultPreview({ projectId, items }: ResultPreviewProps) {
  const selectedOutputPath = useUiStore((s) => s.selectedOutputPath);
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [tocOpen, setTocOpen] = useState(false);
  const [tocItems, setTocItems] = useState<TocItem[]>([]);

  const files = useMemo(() => buildOutputFiles(items), [items]);
  const fileMeta = files.find((f) => f.path === selectedOutputPath);
  const title = fileMeta?.label ?? "";
  const modelPair = fileMeta ? findModelPair(files, fileMeta) : {};
  const isModelArtifact =
    fileMeta?.modelBase &&
    (fileMeta.kind === "plantuml" || fileMeta.kind === "image");
  const isHtmlArtifact = fileMeta?.kind === "html";
  const showToc =
    isHtmlArtifact &&
    !!selectedOutputPath &&
    (/^results\/(srs|design_rationale)\.html$/i.test(selectedOutputPath) ||
      /^results\/drafts\/draft_v\d+\.html$/i.test(selectedOutputPath));

  const file = useQuery({
    queryKey: ["file", projectId, selectedOutputPath],
    queryFn: () => fetchFile(projectId!, selectedOutputPath!),
    enabled:
      !!projectId && !!selectedOutputPath && !isModelArtifact && !isHtmlArtifact,
    retry: false,
  });

  const content = file.data?.content ?? "";
  const htmlPreviewUrl =
    projectId && selectedOutputPath?.startsWith("results/")
      ? `/api/projects/${encodeURIComponent(projectId)}/results/${selectedOutputPath
          .slice("results/".length)
          .split("/")
          .map(encodeURIComponent)
          .join("/")}`
      : null;

  useEffect(() => {
    setTocOpen(false);
    setTocItems([]);
  }, [selectedOutputPath]);

  const collectHtmlToc = () => {
    const doc = iframeRef.current?.contentDocument;
    if (!doc) return;
    const headings = Array.from(doc.querySelectorAll("h1, h2, h3"));
    const items = headings
      .map((heading, index) => {
        const text = heading.textContent?.trim() ?? "";
        if (!text) return null;
        let id = heading.id;
        if (!id) {
          id = `artifact-heading-${index + 1}`;
          heading.id = id;
        }
        return {
          id,
          text,
          level: Number(heading.tagName.slice(1)),
        };
      })
      .filter((item): item is TocItem => item !== null);
    setTocItems(items);
  };

  const scrollToTocItem = (id: string) => {
    const doc = iframeRef.current?.contentDocument;
    const target = doc?.getElementById(id);
    target?.scrollIntoView({ behavior: "smooth", block: "start" });
    setTocOpen(false);
  };

  return (
    <PanelChrome
      title="Artifact"
      centerTitle
      actions={
        showToc ? (
          <div className="relative">
            <button
              type="button"
              className="rounded-control border border-gray-200 bg-white px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-gray-50"
              onClick={() => setTocOpen((open) => !open)}
            >
              目錄
            </button>
            {tocOpen && (
              <div className="absolute left-0 top-full z-30 mt-2 max-h-80 w-64 overflow-y-auto rounded-card border border-gray-200 bg-white p-2 shadow-lg">
                {tocItems.length === 0 ? (
                  <p className="px-2 py-3 text-xs text-slate-500">尚無目錄</p>
                ) : (
                  <div className="space-y-0.5">
                    {tocItems.map((item) => (
                      <button
                        key={item.id}
                        type="button"
                        className={cn(
                          "block w-full rounded-control px-2 py-1.5 text-left text-xs text-slate-700 hover:bg-gray-50",
                          item.level === 2 && "pl-4",
                          item.level === 3 && "pl-6 text-slate-500",
                        )}
                        onClick={() => scrollToTocItem(item.id)}
                      >
                        {item.text}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        ) : null
      }
      trailing={<OutputFilePicker projectId={projectId} items={items} />}
      bodyClassName="flex min-h-0 flex-col"
    >
      {!projectId ? (
        <div className="flex min-h-0 flex-1 items-center justify-center p-4 text-sm text-slate-500">
          未選擇任何檔案
        </div>
      ) : !selectedOutputPath ? (
        <div className="flex min-h-0 flex-1 items-center justify-center p-4 text-sm text-slate-500">
          未選擇任何檔案
        </div>
      ) : isModelArtifact ? (
        <ModelDualView
          projectId={projectId}
          title={title}
          sourcePath={
            modelPair.source?.path ??
            (fileMeta?.kind === "plantuml" ? fileMeta.path : undefined)
          }
          imagePath={
            modelPair.image?.path ??
            (fileMeta?.kind === "image" ? fileMeta.path : undefined)
          }
        />
      ) : file.isLoading ? (
        <p className="p-4 text-sm text-slate-500">載入中…</p>
      ) : file.isError ? (
        <p className="p-4 text-sm text-slate-500">無法載入檔案</p>
      ) : fileMeta?.kind === "json" || file.data?.type === "json" ? (
        <JsonArtifactView path={selectedOutputPath ?? ""} content={content} />
      ) : fileMeta?.kind === "image" || file.data?.type === "image" ? (
        <div className="flex flex-1 items-center justify-center overflow-auto p-4">
          {file.data?.content ? (
            <img
              src={`data:${file.data.mime ?? "image/png"};base64,${file.data.content}`}
              alt={title}
              className="max-h-full max-w-full rounded-control object-contain"
            />
          ) : (
            <p className="text-sm text-slate-500">圖形尚無法預覽</p>
          )}
        </div>
      ) : isHtmlArtifact || file.data?.type === "html" ? (
        <iframe
          ref={iframeRef}
          title={title || "Artifact"}
          src={htmlPreviewUrl ?? undefined}
          sandbox="allow-same-origin"
          onLoad={collectHtmlToc}
          className="min-h-0 flex-1 border-0 bg-white"
        />
      ) : (
        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          <pre className="whitespace-pre-wrap font-mono text-xs leading-relaxed text-slate-700">
            {content}
          </pre>
        </div>
      )}
    </PanelChrome>
  );
}
