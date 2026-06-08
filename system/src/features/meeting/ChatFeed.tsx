import { useEffect, useRef } from "react";
import {
  AlertCircle,
  Bot,
  CheckCircle2,
  Clock3,
  User,
} from "lucide-react";
import { agentLabel } from "@/constants/agents";
import { useChatStore } from "@/stores/chatStore";
import { useUiStore } from "@/stores/uiStore";
import type { ChatMessage } from "@/types/api";
import { cn } from "@/utils/cn";

const ROLE_STYLES: Record<string, { bubble: string; avatar: string }> = {
  user: {
    bubble: "bg-slate-900 text-white",
    avatar: "bg-slate-800 text-white",
  },
  agent: {
    bubble: "bg-white border border-gray-200 text-slate-800 shadow-sm",
    avatar: "bg-violet-100 text-violet-700",
  },
  system: {
    bubble: "bg-slate-100 text-slate-600",
    avatar: "bg-slate-200 text-slate-600",
  },
};

function Bubble({ msg }: { msg: ChatMessage }) {
  const setSelectedOutputPath = useUiStore((s) => s.setSelectedOutputPath);
  const openOutput = () => {
    if (msg.outputPath) setSelectedOutputPath(msg.outputPath);
  };

  if (msg.role === "system") {
    const failed = msg.status === "failed";
    const waiting = msg.status === "waiting";
    return (
      <div className="my-4 flex items-center gap-2 text-xs text-slate-500">
        <div className="h-px flex-1 bg-gray-100" />
        <button
          type="button"
          disabled={!msg.outputPath}
          className={cn(
            "inline-flex max-w-[80%] items-center gap-1.5 rounded-full border bg-white px-2.5 py-1",
            msg.outputPath && "cursor-pointer hover:border-slate-300 hover:text-slate-700",
            failed
              ? "border-red-200 text-red-700"
              : waiting
                ? "border-amber-200 text-amber-800"
                : "border-gray-200 text-slate-500",
          )}
          onClick={openOutput}
        >
          {failed ? (
            <AlertCircle className="h-3.5 w-3.5 text-red-500" />
          ) : waiting ? (
            <Clock3 className="h-3.5 w-3.5 text-amber-500" />
          ) : (
            <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />
          )}
          <span className="truncate">{msg.text}</span>
        </button>
        <div className="h-px flex-1 bg-gray-100" />
      </div>
    );
  }

  const isUser = msg.role === "user";
  const isAction = msg.kind === "action";
  const isDecision = msg.kind === "decision";
  const styles = ROLE_STYLES[msg.role] ?? ROLE_STYLES.agent;
  const label = msg.label ?? (isUser ? agentLabel("user") : agentLabel("analyst"));
  const action = msg.action ?? (isAction ? msg.text.trim() : "");

  return (
    <div
      className={cn(
        "mb-4 flex w-full gap-2.5",
        isUser ? "flex-row-reverse justify-start" : "justify-start",
      )}
    >
      <div className="flex w-16 shrink-0 flex-col items-center gap-1">
        <div className="w-full break-words text-center text-xs font-semibold leading-tight text-slate-600">
          {label}
        </div>
        <div
          className={cn(
            "flex h-9 w-9 items-center justify-center rounded-full",
            styles.avatar,
          )}
        >
          {isUser ? (
            <User className="h-4.5 w-4.5" />
          ) : (
            <Bot className="h-4.5 w-4.5" />
          )}
        </div>
      </div>
      <div className={cn("min-w-0 max-w-[85%] pt-6", isUser && "items-end")}>
        {!isUser && (action || isDecision) && (
          <div className="mb-1 flex flex-wrap items-center gap-1.5 text-xs text-slate-500">
            {action && (
              <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[10px] text-slate-500">
                {action}
              </span>
            )}
            {isDecision && (
              <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] text-amber-700">
                decision
              </span>
            )}
          </div>
        )}
        <button
          type="button"
          disabled={!msg.outputPath}
          className={cn(
            "block rounded-control border px-3.5 py-2.5 text-left text-sm leading-relaxed",
            styles.bubble,
            isUser && "border-slate-900",
            msg.outputPath && "cursor-pointer hover:border-slate-300 hover:shadow",
          )}
          onClick={openOutput}
        >
          {isAction && action ? (
            <div className="space-y-1">
              <div className="text-xs font-medium text-slate-500">Action</div>
              <div className="font-mono text-sm text-slate-800">{action}</div>
              <div className="text-xs text-slate-400">
                {msg.status === "done"
                  ? "完成"
                  : msg.status === "failed"
                    ? "失敗"
                    : "執行中"}
              </div>
            </div>
          ) : (
            <div className="whitespace-pre-wrap">{msg.text}</div>
          )}
        </button>
      </div>
    </div>
  );
}

interface ChatFeedProps {
  historyLoading?: boolean;
}

export function ChatFeed({
  historyLoading = false,
}: ChatFeedProps) {
  const messages = useChatStore((s) => s.messages);
  const scrollTargetMessageId = useUiStore((s) => s.scrollTargetMessageId);
  const setScrollTargetMessageId = useUiStore((s) => s.setScrollTargetMessageId);
  const bottomRef = useRef<HTMLDivElement>(null);
  const messageRefs = useRef<Record<string, HTMLDivElement | null>>({});

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length]);

  useEffect(() => {
    if (!scrollTargetMessageId) return;
    const target = messageRefs.current[scrollTargetMessageId];
    if (!target) return;
    target.scrollIntoView({ behavior: "smooth", block: "center" });
    setScrollTargetMessageId(null);
  }, [scrollTargetMessageId, setScrollTargetMessageId]);

  const showEmpty = messages.length === 0 && !historyLoading;

  return (
    <div className="chat-scroll h-full overflow-y-auto px-4 py-3">
      <div className={cn(
        "mx-auto w-full max-w-[720px]",
        showEmpty && "flex h-full items-center justify-center",
      )}>
        {historyLoading && messages.length === 0 && (
          <div className="py-12 text-center text-sm text-slate-400">
            載入討論紀錄…
          </div>
        )}
        {showEmpty && (
          <div className="text-center">
            <p className="text-sm font-medium text-slate-500">
              請在下方輸入初步想法並按「執行」，Agent 團隊將協助您生成 SRS
            </p>
          </div>
        )}
        {messages.map((m) => (
          <div
            key={m.id}
            ref={(node) => {
              messageRefs.current[m.id] = node;
            }}
          >
            <Bubble msg={m} />
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
