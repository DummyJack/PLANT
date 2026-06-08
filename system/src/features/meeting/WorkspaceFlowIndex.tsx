import { useEffect, useMemo, useRef, useState } from "react";
import { ListTree } from "lucide-react";
import { useChatStore } from "@/stores/chatStore";
import { useUiStore } from "@/stores/uiStore";
import type { ChatMessage } from "@/types/api";
import { cn } from "@/utils/cn";

interface FlowItem {
  id: string;
  title: string;
  detail: string;
  outputPath?: string;
  tone: "user" | "action" | "decision" | "output" | "status";
}

function snippet(text: string, fallback: string) {
  const compact = text.replace(/\s+/g, " ").trim();
  if (!compact) return fallback;
  return compact.length > 48 ? `${compact.slice(0, 48)}...` : compact;
}

function messageToFlowItem(msg: ChatMessage): FlowItem | null {
  if (msg.role === "user") {
    return {
      id: msg.id,
      title: "User",
      detail: snippet(msg.text, "使用者輸入"),
      tone: "user",
    };
  }

  if (msg.kind === "action") {
    const agent = msg.label ?? msg.speaker ?? "Agent";
    return {
      id: msg.id,
      title: `${agent}: ${msg.action ?? msg.text}`,
      detail:
        msg.status === "done"
          ? "完成"
          : msg.status === "failed"
            ? "失敗"
            : "執行中",
      tone: "action",
    };
  }

  if (msg.kind === "decision") {
    return {
      id: msg.id,
      title: "Human Decision",
      detail: snippet(msg.text, "等待使用者決策"),
      tone: "decision",
    };
  }

  if (msg.kind === "output" || msg.outputPath) {
    return {
      id: msg.id,
      title: "Output",
      detail: snippet(msg.text, msg.outputPath ?? "產出物"),
      outputPath: msg.outputPath,
      tone: "output",
    };
  }

  if (msg.status === "waiting" || msg.status === "failed") {
    return {
      id: msg.id,
      title: msg.status === "failed" ? "Error" : "Waiting",
      detail: snippet(msg.text, msg.status === "failed" ? "執行錯誤" : "等待中"),
      tone: "status",
    };
  }

  return null;
}

const toneClass: Record<FlowItem["tone"], string> = {
  user: "bg-slate-900",
  action: "bg-violet-500",
  decision: "bg-amber-500",
  output: "bg-emerald-500",
  status: "bg-slate-400",
};

export function WorkspaceFlowIndex() {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const messages = useChatStore((s) => s.messages);
  const setScrollTargetMessageId = useUiStore((s) => s.setScrollTargetMessageId);
  const setSelectedOutputPath = useUiStore((s) => s.setSelectedOutputPath);

  const items = useMemo(
    () => messages.map(messageToFlowItem).filter((item): item is FlowItem => !!item),
    [messages],
  );

  useEffect(() => {
    if (!open) return;
    const handler = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const jumpTo = (item: FlowItem) => {
    setScrollTargetMessageId(item.id);
    if (item.outputPath) setSelectedOutputPath(item.outputPath);
    setOpen(false);
  };

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        className={cn(
          "inline-flex h-7 items-center gap-1.5 rounded-control border px-2.5 text-xs font-medium transition",
          open
            ? "border-slate-300 bg-slate-50 text-slate-800"
            : "border-gray-200 bg-white text-slate-600 hover:border-slate-300 hover:text-slate-800",
        )}
        onClick={() => setOpen((v) => !v)}
      >
        <ListTree className="h-3.5 w-3.5" />
        流程
      </button>

      {open && (
        <div className="absolute left-0 top-full z-30 mt-2 max-h-80 w-72 overflow-y-auto rounded-card border border-gray-200 bg-white p-2 shadow-lg">
          {items.length === 0 ? (
            <p className="px-2 py-3 text-xs text-slate-500">無任何內容</p>
          ) : (
            <div className="space-y-1">
              {items.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className="flex w-full items-start gap-2 rounded-control px-2 py-2 text-left hover:bg-slate-50"
                  onClick={() => jumpTo(item)}
                >
                  <span
                    className={cn(
                      "mt-1 h-2 w-2 shrink-0 rounded-full",
                      toneClass[item.tone],
                    )}
                  />
                  <span className="min-w-0">
                    <span className="block truncate text-xs font-semibold text-slate-700">
                      {item.title}
                    </span>
                    <span className="block truncate text-[11px] text-slate-500">
                      {item.detail}
                    </span>
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
