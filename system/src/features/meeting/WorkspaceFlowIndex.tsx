import { useEffect, useMemo, useRef, useState } from "react";
import { Bot, ListTree, UserRound } from "lucide-react";
import { useI18n } from "@/i18n";
import { useChatStore } from "@/stores/chatStore";
import { useUiStore } from "@/stores/uiStore";
import type { FileTreeNode, RunCheckpoint, RunState } from "@/types/api";
import { cn } from "@/utils/cn";
import { checkpointCleanupLabel, checkpointStageLabel } from "./RunCheckpointNotice";
import { FormalMeetingFlowMenu } from "./FormalMeetingFlowMenu";
import {
  buildWorkspaceFlowItems,
  isHumanFlowItem,
  stageCardSummary,
  type FlowItem,
} from "./workspaceFlowModel";

function FlowItemIcon({ item, className }: { item: FlowItem; className?: string }) {
  if (isHumanFlowItem(item)) return <UserRound className={className} />;
  if (item.dedupeKey === "group:formal_meeting") {
    return <img src="/meeting.png" alt="" className={className} draggable={false} />;
  }
  return <Bot className={className} />;
}

const FLOW_RAIL_START_PERCENT = 6;
const FLOW_RAIL_SPAN_PERCENT = 88;

function flowRailTop(index: number, itemCount: number) {
  if (itemCount <= 1) return 50;
  return FLOW_RAIL_START_PERCENT + (index / (itemCount - 1)) * FLOW_RAIL_SPAN_PERCENT;
}

export function WorkspaceFlowIndex({
  compact = false,
  inline = false,
  runCheckpoint = null,
  artifactItems = [],
  activeRun = null,
}: {
  compact?: boolean;
  inline?: boolean;
  runCheckpoint?: RunCheckpoint | null;
  artifactItems?: FileTreeNode[];
  activeRun?: RunState | null;
}) {
  const { language, t } = useI18n();
  const [open, setOpen] = useState(false);
  const [expandedGroupId, setExpandedGroupId] = useState<string | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const itemRefs = useRef<Record<string, HTMLElement | null>>({});
  const messages = useChatStore((s) => s.messages);
  const activeFlowMessageId = useUiStore((s) => s.activeFlowMessageId);
  const setScrollTargetMessageId = useUiStore((s) => s.setScrollTargetMessageId);
  const setActiveFlowMessageId = useUiStore((s) => s.setActiveFlowMessageId);
  const setSelectedOutputPath = useUiStore((s) => s.setSelectedOutputPath);

  const items = useMemo(() => {
    const hideGeneratedDocuments = activeRun?.mode === "continue" &&
      ["queued", "running", "waiting_for_human", "cancelling"].includes(activeRun.status);
    return buildWorkspaceFlowItems(messages, artifactItems, hideGeneratedDocuments);
  }, [activeRun?.mode, activeRun?.status, artifactItems, language, messages]);
  const activeItemId = useMemo(() => {
    if (!activeFlowMessageId) return items[0]?.id ?? null;
    const itemIds = new Set(items.map((item) => item.id));
    if (itemIds.has(activeFlowMessageId)) return activeFlowMessageId;
    const itemByScrollTarget = items.find((item) => item.scrollTargetId === activeFlowMessageId);
    if (itemByScrollTarget) return itemByScrollTarget.id;
    const activeIndex = messages.findIndex((message) => message.id === activeFlowMessageId);
    if (activeIndex < 0) return items[0]?.id ?? null;
    for (let index = activeIndex; index >= 0; index -= 1) {
      const id = messages[index]?.id;
      if (id && itemIds.has(id)) return id;
      const item = items.find((candidate) => candidate.scrollTargetId === id);
      if (item) return item.id;
    }
    return items[0]?.id ?? null;
  }, [activeFlowMessageId, items, messages]);

  useEffect(() => {
    if (inline) {
      if (!expandedGroupId) return;
      const handler = (event: MouseEvent) => {
        if (!rootRef.current?.contains(event.target as Node)) setExpandedGroupId(null);
      };
      document.addEventListener("mousedown", handler);
      return () => document.removeEventListener("mousedown", handler);
    }
    if (!open) return;
    const handler = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [expandedGroupId, inline, open]);

  useEffect(() => {
    if ((!open && !inline) || !activeItemId) return;
    itemRefs.current[activeItemId]?.scrollIntoView({
      block: "nearest",
      behavior: "smooth",
    });
  }, [activeItemId, inline, open]);

  const jumpTo = (item: FlowItem) => {
    if (item.children?.length) {
      setExpandedGroupId((current) => current === item.id ? null : item.id);
      return;
    }
    setExpandedGroupId(null);
    setActiveFlowMessageId(item.id);
    if (item.scrollTargetId) {
      setScrollTargetMessageId(item.scrollTargetId);
    } else if (item.outputPath) {
      setSelectedOutputPath(item.outputPath, "manual");
    }
    if (!inline) setOpen(false);
  };

  const jumpToChild = (item: FlowItem) => {
    if (item.scrollTargetId) {
      setScrollTargetMessageId(item.scrollTargetId);
    } else if (item.outputPath) {
      setSelectedOutputPath(item.outputPath, "manual");
    }
  };

  const railContent = (
    <>
      {items.length === 0 ? (
        runCheckpoint ? (
          <button
            type="button"
            className="flex w-full items-start gap-2 rounded-control bg-amber-50 px-2 py-2 text-left"
            disabled
            title={checkpointCleanupLabel(runCheckpoint)}
          >
            <span className="mt-1 h-2 w-2 shrink-0 rounded-full bg-amber-500" />
            <span className="min-w-0">
              <span className="block truncate text-xs font-semibold text-amber-950">
                {t.continueRerun(checkpointStageLabel(runCheckpoint))}
              </span>
              <span className="block truncate text-[11px] text-amber-800">
                {checkpointCleanupLabel(runCheckpoint)}
              </span>
            </span>
          </button>
        ) : (
          <p className="px-2 py-3 text-xs text-slate-500">{t.noContent}</p>
        )
      ) : (
        <div className="relative space-y-1">
          <div className="absolute bottom-2 left-1/2 top-2 w-px -translate-x-1/2 bg-slate-200" />
          {runCheckpoint && (
            <button
              type="button"
              className="flex w-full items-start gap-2 rounded-control bg-amber-50 px-2 py-2 text-left"
              disabled
              title={checkpointCleanupLabel(runCheckpoint)}
            >
              <span className="mt-1 h-2 w-2 shrink-0 rounded-full bg-amber-500" />
              <span className="min-w-0">
                <span className="block truncate text-xs font-semibold text-amber-950">
                  {t.continueRerun(checkpointStageLabel(runCheckpoint))}
                </span>
                <span className="block truncate text-[11px] text-amber-800">
                  {checkpointCleanupLabel(runCheckpoint)}
                </span>
              </span>
            </button>
          )}
          {items.map((item) => {
            const active = item.id === activeItemId;
            const summary = stageCardSummary(item);
            const showSummary = isHumanFlowItem(item);
            return (
              <button
                key={item.id}
                type="button"
                ref={(node) => {
                  itemRefs.current[item.id] = node;
                }}
                aria-current={item.id === activeItemId ? "true" : undefined}
                title={item.title}
                className={cn(
                  "group relative flex h-6 w-full items-center justify-center rounded-control text-left transition-colors hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-300",
                  active && "bg-slate-50",
                )}
                onClick={() => jumpTo(item)}
              >
                <span
                  className={cn(
                    "relative z-10 h-0.5 rounded-full transition-all",
                    active ? "w-5 bg-slate-900" : "w-3.5 bg-slate-300 group-hover:w-5 group-hover:bg-slate-600 group-focus-visible:w-5 group-focus-visible:bg-slate-600",
                  )}
                />
                <span
                  className={cn(
                    "pointer-events-none absolute left-full top-1/2 z-40 ml-3 w-max max-w-48 -translate-y-1/2 rounded-control border px-2.5 py-1.5 text-left opacity-0 shadow-lg transition duration-150 group-hover:pointer-events-auto group-hover:opacity-100 group-focus-visible:pointer-events-auto group-focus-visible:opacity-100",
                    active
                      ? "border-slate-300 bg-white shadow-sm"
                      : "border-gray-200 bg-white",
                  )}
                >
                  <span className="flex min-w-0 items-start justify-between gap-3">
                    <span className={cn(
                      "min-w-0 truncate text-[13px] font-semibold",
                      active ? "text-slate-950" : "text-slate-800",
                    )}>
                      {item.title}
                    </span>
                  </span>
                    {showSummary && (
                      <span className="mt-1 block truncate text-[11px] leading-4 text-slate-500">
                        {summary}
                      </span>
                    )}
                </span>
              </button>
            );
          })}
        </div>
      )}
    </>
  );

  const inlineRailContent = items.length === 0 ? null : (
    <div className="relative h-full w-full">
      {items.slice(0, -1).map((item, index) => {
        const top = flowRailTop(index, items.length);
        const nextTop = flowRailTop(index + 1, items.length);
        return (
          <span
            key={`${item.id}-connector`}
            className="pointer-events-none absolute left-1/2 w-px -translate-x-1/2 bg-slate-200"
            style={{
              top: `calc(${top}% + 0.5rem)`,
              height: `calc(${nextTop - top}% - 1rem)`,
            }}
          />
        );
      })}
      {items.map((item, index) => {
        const active = item.id === activeItemId;
        const summary = stageCardSummary(item);
        const human = isHumanFlowItem(item);
        const groupExpanded = expandedGroupId === item.id;
        const top = flowRailTop(index, items.length);
        return (
          <div
            key={item.id}
            role="button"
            tabIndex={0}
            ref={(node) => {
              itemRefs.current[item.id] = node;
            }}
            aria-current={item.id === activeItemId ? "true" : undefined}
            aria-expanded={item.children?.length ? groupExpanded : undefined}
            aria-label={item.title}
            title={item.title}
            style={{ top: `${top}%` }}
            className={cn(
              "group absolute left-0 flex w-full -translate-y-1/2 items-center justify-center text-left focus-visible:outline-none",
              item.children?.length ? "h-7" : "h-5",
            )}
            onClick={(event) => {
              jumpTo(item);
              if (!item.children?.length) event.currentTarget.blur();
            }}
            onKeyDown={(event) => {
              if (event.key !== "Enter" && event.key !== " ") return;
              event.preventDefault();
              jumpTo(item);
              if (!item.children?.length) event.currentTarget.blur();
            }}
          >
            <span
              className={cn(
                "relative z-10 flex h-4 w-4 items-center justify-center rounded-full border bg-white shadow-sm transition",
                active
                  ? "border-slate-900 text-slate-900"
                  : human
                    ? "border-violet-200 text-violet-500 group-hover:border-violet-300 group-hover:text-violet-600 group-focus-visible:border-violet-300 group-focus-visible:text-violet-600"
                    : "border-slate-200 text-slate-500 group-hover:border-slate-300 group-hover:text-slate-700 group-focus-visible:border-slate-300 group-focus-visible:text-slate-700",
              )}
            >
              <FlowItemIcon item={item} className="h-2.5 w-2.5" />
            </span>
            {(!item.children?.length || !groupExpanded) ? (
              <span
                className={cn(
                  "pointer-events-none absolute left-full top-1/2 z-40 ml-3 w-max max-w-48 -translate-y-1/2 rounded-control border px-2.5 py-1.5 text-left opacity-0 shadow-lg transition duration-150 group-hover:pointer-events-auto group-hover:opacity-100 group-focus-visible:pointer-events-auto group-focus-visible:opacity-100",
                  active
                    ? "border-slate-300 bg-white shadow-sm"
                    : "border-gray-200 bg-white",
                )}
              >
                <span className="flex min-w-0 items-start justify-between gap-3">
                  <span className={cn(
                    "min-w-0 truncate text-[13px] font-semibold",
                    active ? "text-slate-950" : "text-slate-800",
                  )}>
                    {item.title}
                  </span>
                </span>
                {human && (
                  <span className="mt-1 block truncate text-[11px] leading-4 text-slate-500">
                    {summary}
                  </span>
                )}
              </span>
            ) : null}
            {item.children?.length && groupExpanded ? (
              <FormalMeetingFlowMenu items={item.children} onSelect={jumpToChild} />
            ) : null}
          </div>
        );
      })}
    </div>
  );

  if (inline) {
    return (
      <div
        ref={rootRef}
        className="group/flow-rail pointer-events-auto absolute bottom-6 left-0 top-6 z-20 w-9 overflow-visible"
        aria-label={t.workspaceFlow}
      >
        <div className="h-full w-8 px-1 py-2 opacity-0 transition-opacity duration-150 group-hover/flow-rail:opacity-100 group-focus-within/flow-rail:opacity-100">
          {inlineRailContent}
        </div>
      </div>
    );
  }

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        className={cn(
          "inline-flex h-7 items-center gap-1.5 rounded-control border text-xs font-medium transition",
          compact ? "w-7 justify-center px-0" : "px-2.5",
          open
            ? "border-slate-300 bg-slate-50 text-slate-800"
            : "border-gray-200 bg-white text-slate-600 hover:border-slate-300 hover:text-slate-800",
        )}
        aria-label={t.flow}
        title={t.flow}
        onClick={() => setOpen((v) => !v)}
      >
        <ListTree className="h-3.5 w-3.5" />
        <span className={cn(compact && "sr-only")}>{t.flow}</span>
      </button>

      {open && (
        <div className="absolute left-0 top-full z-30 mt-2 max-h-96 w-16 overflow-visible rounded-card border border-gray-200 bg-white px-2 py-2.5 shadow-lg">
          {railContent}
        </div>
      )}
    </div>
  );
}
