import { agentLabel } from "@/constants/agents";
import { useChatStore } from "@/stores/chatStore";
import type { RunState } from "@/types/api";
import { cn } from "@/utils/cn";

interface StatusBarProps {
  run: RunState | null;
  lastLogMessage?: string;
  historyLoading?: boolean;
}

function statusLabel(run: RunState | null): string {
  if (!run) return "待命";
  switch (run.status) {
    case "queued":
      return "排隊中";
    case "running":
      return "執行中";
    case "waiting_for_human":
      return "等待決策";
    case "cancelling":
      return "取消中";
    case "completed":
      return "已完成";
    case "failed":
      return "執行失敗";
    case "cancelled":
      return "已取消";
    case "interrupted":
      return "已中斷";
    default:
      return run.status;
  }
}

function parseAgentAction(message?: string): { agent: string; action: string } | null {
  const match = /^(\w+)\s*\[\d+\/\d+\]:\s*(.+)$/i.exec(String(message || "").trim());
  if (!match) return null;
  return {
    agent: agentLabel(match[1].replace(/agent$/i, "").toLowerCase()),
    action: match[2].trim(),
  };
}

function waitingActivity(
  message?: string,
  currentStage?: string,
):
  | "planning"
  | "meeting"
  | "analyzing"
  | "researching"
  | "modeling"
  | "drafting"
  | "documenting"
  | null {
  const text = `${currentStage || ""} ${message || ""}`.trim();
  if (!text) return null;
  if (/plan|planning|規劃|決定.*action|下一步|策略/i.test(text)) return "planning";
  if (/meeting|會議|討論|issue|議題|conflict|衝突|裁決/i.test(text)) return "meeting";
  if (/analyst|analyz|analysis|requirement|需求分析|分析需求|refine|update_requirement|formalize|clarify/i.test(text)) return "analyzing";
  if (/expert|research|reference|feedback|domain|web_search|read_file|研究|參考|資料|回饋/i.test(text)) return "researching";
  if (/modeler|model|plantuml|diagram|uml|系統模型|建模|模型|圖/i.test(text)) return "modeling";
  if (/draft|草稿|use case|usecase|使用案例/i.test(text)) return "drafting";
  if (/documentor|document|srs|design rationale|\bdr\b|mom|html|文件|規格書|設計緣由|會議紀錄/i.test(text)) return "documenting";
  return null;
}

export function StatusBar({
  run,
  lastLogMessage,
  historyLoading,
}: StatusBarProps) {
  const latestActionText = useChatStore((s) => {
    for (let i = s.messages.length - 1; i >= 0; i -= 1) {
      const msg = s.messages[i];
      if (msg.kind === "action" && (msg.action || msg.text)) {
        return `${msg.label ?? agentLabel(msg.speaker ?? "mediator")}: ${
          msg.action ?? msg.text
        }`;
      }
    }
    return null;
  });
  const waiting = run?.status === "waiting_for_human";
  const runActive =
    !!run &&
    ["queued", "running", "waiting_for_human", "cancelling"].includes(
      run.status,
    );

  if (!runActive && !historyLoading) return null;

  const statusMessage = (() => {
    if (historyLoading && !runActive) return "載入既有討論紀錄";
    if (run) {
      if (run.status === "cancelling") {
        return {
          text: "cancelling ...",
          pulse: true,
        };
      }
      const parsed = parseAgentAction(lastLogMessage);
      if (parsed) {
        return {
          text: `${parsed.agent}: ${parsed.action}`,
          pulse: false,
        };
      }
      const activity = waitingActivity(lastLogMessage, run.current_stage);
      if (activity) {
        return {
          text: `${activity} ...`,
          pulse: true,
        };
      }
      if (latestActionText) {
        return {
          text: latestActionText,
          pulse: false,
        };
      }
      if (waiting) return "等待你的決策";
      return {
        text: "planning ...",
        pulse: true,
      };
    }
    return "";
  })();
  const message =
    typeof statusMessage === "string" ? statusMessage : statusMessage.text;
  const pulseMessage =
    typeof statusMessage === "string" ? false : statusMessage.pulse;

  return (
    <div className="flex h-11 shrink-0 items-center gap-3 border-b border-gray-100 bg-slate-50/90 px-4 text-sm text-slate-600">
      <span
        className={cn(
          "inline-flex h-7 shrink-0 items-center gap-2 rounded-full border px-3 font-semibold",
          waiting
            ? "border-amber-200 bg-amber-50 text-amber-900"
            : runActive
              ? "border-emerald-200 bg-emerald-50 text-emerald-900"
              : "border-gray-200 bg-white text-slate-600",
        )}
      >
        <span
          className={cn(
            "h-2 w-2 shrink-0 rounded-full",
            waiting
              ? "bg-amber-500"
              : runActive
                ? "bg-emerald-500 animate-pulse"
                : "bg-slate-300",
          )}
        />
        {statusLabel(run)}
      </span>

      <span
        className={cn(
          "min-w-0 flex-1 truncate",
          runActive ? "text-slate-700" : "text-slate-400",
          waiting && "font-medium text-amber-800",
          pulseMessage && "animate-pulse font-medium",
        )}
      >
        {message}
      </span>
    </div>
  );
}
