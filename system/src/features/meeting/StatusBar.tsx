import { agentLabel } from "@/constants/agents";
import { useChatStore } from "@/stores/chatStore";
import type { RunState } from "@/types/api";
import { cn } from "@/utils/cn";
import { runStageActivityLabel } from "@/utils/runStageLabel";

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
  const text = String(message || "").trim();
  const match = /^(\w+)\s*\[\d+\/\d+\]:\s*(.+)$/i.exec(text);
  if (match) {
    return {
      agent: agentLabel(match[1].replace(/agent$/i, "").toLowerCase()),
      action: match[2].trim(),
    };
  }

  const direct = /^(Analyst|Expert|Modeler|Mediator|Documentor)\s*[：:]\s*(.+)$/i.exec(text);
  if (direct) {
    return {
      agent: agentLabel(direct[1].toLowerCase()),
      action: direct[2].trim(),
    };
  }

  const mapped = mapLogToAgentAction(text);
  if (mapped) return mapped;

  return null;
}

function mapLogToAgentAction(message: string): { agent: string; action: string } | null {
  const text = message.trim();
  if (!text) return null;
  if (/^=+|^Round\s+\d+|^第[一二三四五六七八九十]+輪/.test(text)) return null;
  if (/正式會議議程|本次會議結束|流程完成|初步情境分析/.test(text)) return null;

  const rules: Array<{ pattern: RegExp; agent: string; action: string }> = [
    { pattern: /需求衝突再審查|需求衝突辨識|Conflict Gate/i, agent: "analyst", action: "衝突辨識" },
    { pattern: /MoM|會議紀錄|已保存：R\d+-M\d+\.md/i, agent: "mediator", action: "MoM" },
    { pattern: /formalize_requirement|需求正式化/i, agent: "mediator", action: "需求正式化" },
    { pattern: /領域研究|domain|research/i, agent: "expert", action: "領域研究" },
    { pattern: /系統模型|PlantUML|use case|用例圖|情境圖|model/i, agent: "modeler", action: "系統模型產生" },
    { pattern: /draft|草稿/i, agent: "analyst", action: "更新草稿" },
    { pattern: /SRS|軟體需求規格/i, agent: "documentor", action: "SRS" },
    { pattern: /Design Rationale|design_rationale|設計緣由/i, agent: "documentor", action: "Design Rationale" },
  ];

  const hit = rules.find(({ pattern }) => pattern.test(text));
  if (!hit) return null;
  return {
    agent: agentLabel(hit.agent),
    action: hit.action,
  };
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
          text: "停止中",
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
      const stageLabel = runStageActivityLabel(run.current_stage);
      if (stageLabel) {
        return {
          text: stageLabel,
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
      if (run.current_agent) {
        return {
          text: `${agentLabel(run.current_agent)}: 執行中`,
          pulse: true,
        };
      }
      return {
        text: "執行中",
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
    <div className="flex h-8 shrink-0 items-center gap-2 border-b border-gray-100 bg-slate-50/90 px-3 text-xs text-slate-600">
      <span
        className={cn(
          "inline-flex h-5 shrink-0 items-center gap-1.5 rounded-full border px-2 font-semibold",
          waiting
            ? "border-amber-200 bg-amber-50 text-amber-900"
            : runActive
              ? "border-emerald-200 bg-emerald-50 text-emerald-900"
              : "border-gray-200 bg-white text-slate-600",
        )}
      >
        <span
          className={cn(
            "h-1.5 w-1.5 shrink-0 rounded-full",
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
