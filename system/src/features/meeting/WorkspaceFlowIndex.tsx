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
  dedupeKey: string;
  outputPath?: string;
  tone: "user" | "action" | "decision" | "output" | "status";
}

function snippet(text: string, fallback: string) {
  const compact = text.replace(/\s+/g, " ").trim();
  if (!compact) return fallback;
  return compact.length > 48 ? `${compact.slice(0, 48)}...` : compact;
}

function actionTitle(value: string) {
  return value.replace(/^(?:[a-z_]+(?:\.\w+_\d+)?\.)+/i, "");
}

function messageToFlowItem(msg: ChatMessage): FlowItem | null {
  if (msg.role === "user") {
    return {
      id: msg.id,
      title: "User",
      detail: snippet(msg.text, "使用者輸入"),
      dedupeKey: `message:${msg.id}`,
      tone: "user",
    };
  }

  if (msg.kind === "action") {
    const agent = msg.label ?? msg.speaker ?? "Agent";
    const action = actionTitle(msg.action ?? msg.text);
    return {
      id: msg.id,
      title: `${agent}: ${action}`,
      detail:
        msg.status === "done"
          ? "完成"
          : msg.status === "failed"
            ? "失敗"
            : "執行中",
      dedupeKey: `action:${msg.stage ?? ""}:${msg.speaker ?? agent}:${msg.action ?? msg.text}`,
      tone: "action",
    };
  }

  if (msg.kind === "decision") {
    return {
      id: msg.id,
      title: "Human Decision",
      detail: "完成",
      dedupeKey: `message:${msg.id}`,
      tone: "decision",
    };
  }

  if (msg.kind === "output" || msg.outputPath) {
    return {
      id: msg.id,
      title: "Output",
      detail: snippet(msg.text, msg.outputPath ?? "產出物"),
      dedupeKey: msg.outputPath ? `output:${msg.outputPath}` : `message:${msg.id}`,
      outputPath: msg.outputPath,
      tone: "output",
    };
  }

  if (msg.status === "waiting" || msg.status === "failed") {
    return {
      id: msg.id,
      title: msg.status === "failed" ? "Error" : "Waiting",
      detail: snippet(msg.text, msg.status === "failed" ? "執行錯誤" : "等待中"),
      dedupeKey: `message:${msg.id}`,
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
  const itemRefs = useRef<Record<string, HTMLButtonElement | null>>({});
  const messages = useChatStore((s) => s.messages);
  const activeFlowMessageId = useUiStore((s) => s.activeFlowMessageId);
  const setScrollTargetMessageId = useUiStore((s) => s.setScrollTargetMessageId);
  const setSelectedOutputPath = useUiStore((s) => s.setSelectedOutputPath);

  const items = useMemo(() => {
    const byKey = new Map<string, FlowItem>();
    messages.forEach((message) => {
      const item = messageToFlowItem(message);
      if (!item) return;
      byKey.set(item.dedupeKey, item);
    });
    return Array.from(byKey.values());
  }, [messages]);
  const activeItemId = useMemo(() => {
    if (!activeFlowMessageId) return items[0]?.id ?? null;
    const itemIds = new Set(items.map((item) => item.id));
    if (itemIds.has(activeFlowMessageId)) return activeFlowMessageId;
    const activeIndex = messages.findIndex((message) => message.id === activeFlowMessageId);
    if (activeIndex < 0) return items[0]?.id ?? null;
    for (let index = activeIndex; index >= 0; index -= 1) {
      const id = messages[index]?.id;
      if (id && itemIds.has(id)) return id;
    }
    return items[0]?.id ?? null;
  }, [activeFlowMessageId, items, messages]);

  useEffect(() => {
    if (!open) return;
    const handler = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  useEffect(() => {
    if (!open || !activeItemId) return;
    itemRefs.current[activeItemId]?.scrollIntoView({
      block: "nearest",
      behavior: "smooth",
    });
  }, [activeItemId, open]);

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
                  ref={(node) => {
                    itemRefs.current[item.id] = node;
                  }}
                  aria-current={item.id === activeItemId ? "true" : undefined}
                  className={cn(
                    "flex w-full items-start gap-2 rounded-control px-2 py-2 text-left transition-colors hover:bg-slate-50",
                    item.id === activeItemId && "bg-slate-50",
                  )}
                  onClick={() => jumpTo(item)}
                >
                  <span
                    className={cn(
                      "mt-1 h-2 w-2 shrink-0 rounded-full transition",
                      toneClass[item.tone],
                      item.id === activeItemId && "ring-2 ring-slate-200 ring-offset-1",
                    )}
                  />
                  <span className="min-w-0">
                    <span className={cn(
                      "block truncate text-xs font-semibold",
                      item.id === activeItemId ? "text-slate-900" : "text-slate-700",
                    )}>
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
