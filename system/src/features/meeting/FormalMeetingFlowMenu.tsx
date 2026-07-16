import { useState } from "react";
import { createPortal } from "react-dom";
import { Bot, UserRound } from "lucide-react";
import { cn } from "@/utils/cn";
import { isHumanFlowItem, type FlowItem } from "./workspaceFlowModel";

interface FlowChildTooltip {
  id: string;
  title: string;
  top: number;
  left: number;
}

interface FormalMeetingFlowMenuProps {
  items: FlowItem[];
  onSelect: (item: FlowItem) => void;
}

export function FormalMeetingFlowMenu({ items, onSelect }: FormalMeetingFlowMenuProps) {
  const [tooltip, setTooltip] = useState<FlowChildTooltip | null>(null);

  const showTooltip = (button: HTMLButtonElement, item: FlowItem) => {
    const rect = button.getBoundingClientRect();
    setTooltip({
      id: item.id,
      title: item.title,
      top: rect.top + rect.height / 2,
      left: rect.right + 8,
    });
  };

  const hideTooltip = (itemId?: string) => {
    setTooltip((current) => !itemId || current?.id === itemId ? null : current);
  };

  return (
    <>
      <span
        className="scrollbar-hidden absolute bottom-1/2 left-full z-50 ml-4 flex max-h-[70vh] flex-col items-center gap-2 overflow-x-hidden overflow-y-auto rounded-full border border-gray-200 bg-white/95 px-1.5 py-2 shadow-lg backdrop-blur"
        onScroll={() => hideTooltip()}
      >
        {items.map((item) => {
          const human = isHumanFlowItem(item);
          return (
            <button
              key={item.id}
              type="button"
              aria-label={item.title}
              className="relative flex h-6 w-6 items-center justify-center rounded-full"
              onMouseEnter={(event) => showTooltip(event.currentTarget, item)}
              onMouseLeave={() => hideTooltip(item.id)}
              onFocus={(event) => showTooltip(event.currentTarget, item)}
              onBlur={() => hideTooltip(item.id)}
              onClick={(event) => {
                event.stopPropagation();
                hideTooltip();
                onSelect(item);
                event.currentTarget.blur();
              }}
            >
              <span
                className={cn(
                  "flex h-4 w-4 items-center justify-center rounded-full border bg-white shadow-sm",
                  human
                    ? "border-violet-200 text-violet-500"
                    : "border-slate-200 text-slate-500",
                )}
              >
                {human ? <UserRound className="h-2.5 w-2.5" /> : <Bot className="h-2.5 w-2.5" />}
              </span>
            </button>
          );
        })}
      </span>
      {tooltip && createPortal(
        <span
          className="pointer-events-none fixed z-[100] w-max max-w-44 -translate-y-1/2 rounded-control border border-gray-200 bg-white px-2.5 py-1.5 text-left shadow-lg"
          style={{ top: tooltip.top, left: tooltip.left }}
        >
          <span className="block truncate text-[12px] font-semibold text-slate-800">
            {tooltip.title}
          </span>
        </span>,
        document.body,
      )}
    </>
  );
}
