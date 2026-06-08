import { Bot, Send, Square } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { fetchConfig, updateConfig } from "@/api/config";
import { AGENT_LABELS, AGENT_ORDER } from "@/constants/agents";
import { useUiStore } from "@/stores/uiStore";
import { useNoticeStore } from "@/stores/noticeStore";
import { cn } from "@/utils/cn";

interface MeetingComposerProps {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  onStop?: () => void;
  disabled?: boolean;
  noProject?: boolean;
  loading?: boolean;
  running?: boolean;
  stopping?: boolean;
}

const AGENT_OPTION_LABELS: Record<string, string> = {
  user: "User",
  analyst: "Analyst",
  expert: "Expert",
  modeler: "Modeler",
  documentor: "Documentor",
};

const LOCKED_AGENTS = new Set<string>();
const TOGGLEABLE_AGENTS = AGENT_ORDER.filter(
  (a) => a !== "mediator" && !LOCKED_AGENTS.has(a),
);

export function MeetingComposer({
  value,
  onChange,
  onSubmit,
  onStop,
  disabled,
  noProject,
  loading,
  running,
  stopping,
}: MeetingComposerProps) {
  const meetingRounds = useUiStore((s) => s.meetingRounds);
  const setMeetingRounds = useUiStore((s) => s.setMeetingRounds);
  const enabledAgents = useUiStore((s) => s.enabledAgents);
  const toggleAgent = useUiStore((s) => s.toggleAgent);
  const pushNotice = useNoticeStore((s) => s.pushNotice);

  const [showAgentPopover, setShowAgentPopover] = useState(false);
  const agentRef = useRef<HTMLDivElement>(null);

  const displayAgents = AGENT_ORDER.filter((a) => a !== "mediator");
  const enabledToggleableCount = TOGGLEABLE_AGENTS.filter(
    (a) => enabledAgents[a] !== false,
  ).length;
  const agentsCustomized = enabledToggleableCount < TOGGLEABLE_AGENTS.length;

  useEffect(() => {
    if (!showAgentPopover) return;
    const handler = (e: MouseEvent) => {
      const target = e.target as Node;
      if (showAgentPopover && agentRef.current && !agentRef.current.contains(target)) {
        setShowAgentPopover(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [showAgentPopover]);

  const saveDefaults = async (
    nextAgents = enabledAgents,
    nextRounds = meetingRounds,
  ) => {
    try {
      const { config } = await fetchConfig();
      await updateConfig({
        ...config,
        rounds: nextRounds,
        enable_agents: { ...nextAgents, mediator: true },
      });
      pushNotice({
        tone: "success",
        title: "已儲存",
        message: "代理人設定已更新",
      });
    } catch (e) {
      pushNotice({
        tone: "error",
        title: "儲存失敗",
        message: e instanceof Error ? e.message : "無法儲存代理人設定",
      });
    }
  };

  return (
    <div className="composer-shadow shrink-0 border-t border-gray-100 bg-white px-3 pb-4 pt-3">
      <div className="flex items-center gap-2">
        <div className="relative" ref={agentRef}>
          <button
            type="button"
            title="選擇啟用的代理（套用於下一次工作坊）"
            className={cn(
              "relative inline-flex h-[54px] shrink-0 items-center gap-1.5 rounded-bubble border px-3 text-sm font-medium transition-colors disabled:opacity-40",
              showAgentPopover
                ? "border-slate-300 bg-white text-slate-800 shadow-sm"
                : "border-gray-200 bg-gray-50 text-slate-600 hover:bg-white hover:text-slate-800",
              agentsCustomized && !showAgentPopover && "text-slate-700",
            )}
            disabled={disabled}
            onClick={() => {
              setShowAgentPopover((v) => !v);
            }}
          >
            <Bot className="h-4 w-4" />
            Agent
            {agentsCustomized && (
              <span className="flex h-4 min-w-4 items-center justify-center rounded-full bg-slate-800 px-1 text-[10px] font-semibold leading-none text-white">
                {enabledToggleableCount}
              </span>
            )}
          </button>

          {showAgentPopover && (
            <div className="absolute bottom-full left-0 z-20 mb-2 w-64 rounded-control border border-gray-200 bg-white shadow-lg">
              <div className="border-b border-gray-100 px-3 py-2">
                <p className="text-center text-xs font-semibold text-slate-800">代理人設定</p>
              </div>
              <div className="border-b border-gray-100 px-3 py-2.5">
                <div className="flex items-center gap-3 text-xs text-slate-600">
                  <label htmlFor="meeting-rounds" className="shrink-0 font-medium text-slate-700">
                    回合數
                  </label>
                  <input
                    id="meeting-rounds"
                    type="number"
                    min={1}
                    max={99}
                    step={1}
                    className="h-7 w-14 rounded-control border border-gray-200 bg-gray-50 px-2 text-center text-xs font-medium text-slate-700 focus:border-slate-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-slate-200 disabled:opacity-50"
                    disabled={disabled}
                    value={meetingRounds}
                    onChange={(e) => {
                      const next = Math.max(1, Number(e.target.value || 1));
                      setMeetingRounds(next);
                      void saveDefaults(enabledAgents, next);
                    }}
                  />
                </div>
              </div>
              <div className="py-1">
                {displayAgents.map((id) => {
                  const on = enabledAgents[id] !== false;
                  const locked = LOCKED_AGENTS.has(id);
                  return (
                    <label
                      key={id}
                      className={cn(
                        "flex items-center gap-2.5 px-3 py-2 text-xs transition-colors",
                        locked
                          ? "cursor-default text-slate-400"
                          : "cursor-pointer text-slate-700 hover:bg-gray-50",
                        disabled && "pointer-events-none opacity-50",
                      )}
                      title={locked ? "此代理固定啟用" : undefined}
                    >
                      <input
                        type="checkbox"
                        className="rounded border-gray-300 text-slate-800 focus:ring-slate-300"
                        disabled={disabled || locked}
                        checked={on}
                        onChange={() => {
                          const nextAgents = {
                            ...enabledAgents,
                            [id]: !on,
                          };
                          toggleAgent(id);
                          void saveDefaults(nextAgents, meetingRounds);
                        }}
                      />
                      <span className={cn(!on && !locked && "text-slate-400")}>
                        {AGENT_OPTION_LABELS[id] ?? AGENT_LABELS[id]}
                      </span>
                    </label>
                  );
                })}
              </div>
            </div>
          )}
        </div>

        <div className="relative flex min-h-[54px] min-w-0 flex-1 items-center gap-2 rounded-bubble border border-gray-200 bg-gray-50 p-2">
          <textarea
            rows={1}
            className="min-h-[36px] min-w-0 flex-1 resize-none bg-transparent px-1 py-2 text-sm text-slate-800 placeholder:text-slate-400 focus:outline-none"
            placeholder={
              noProject
                ? "輸入初步想法"
                : stopping
                  ? "正在停止工作坊，請稍候..."
                  : disabled
                  ? "工作坊執行中，請稍候…"
                  : "輸入初步想法"
            }
            value={value}
            disabled={disabled}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !disabled) {
                e.preventDefault();
                if (value.trim()) onSubmit();
              }
            }}
          />

          <button
            type="button"
            className={cn(
              "inline-flex shrink-0 items-center gap-1.5 rounded-xl px-4 py-2 text-sm font-medium text-white disabled:opacity-40",
              running ? "bg-red-600 hover:bg-red-700" : "bg-slate-900 hover:bg-slate-800",
              stopping && "bg-red-400 hover:bg-red-400",
            )}
            disabled={running ? loading || stopping : disabled || loading || !value.trim()}
            onClick={running ? onStop : onSubmit}
          >
            {running ? <Square className="h-4 w-4" /> : <Send className="h-4 w-4" />}
            {stopping ? "停止中..." : running ? "停止" : "執行"}
          </button>
        </div>
      </div>
    </div>
  );
}
