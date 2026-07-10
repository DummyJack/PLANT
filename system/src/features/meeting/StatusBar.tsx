import { agentLabel } from "@/constants/agents";
import { useI18n } from "@/i18n";
import { useChatStore } from "@/stores/chatStore";
import type { RunState } from "@/types/api";
import { cn } from "@/utils/cn";

interface StatusBarProps {
  run: RunState | null;
  lastLogMessage?: string;
  historyLoading?: boolean;
}

type UiTexts = ReturnType<typeof useI18n>["t"];

function statusLabel(run: RunState | null, t: UiTexts): string {
  if (!run) return t.idle;
  switch (run.status) {
    case "queued":
      return t.queued;
    case "running":
      return t.flowRunning;
    case "waiting_for_human":
      return t.waitingDecision;
    case "cancelling":
      return t.cancelling;
    case "completed":
      return t.completed;
    case "failed":
      return t.failed;
    case "cancelled":
      return t.cancelled;
    case "interrupted":
      return t.interrupted;
    default:
      return run.status;
  }
}

function parseAgentAction(message: string | undefined, t: UiTexts): { agent: string; action: string } | null {
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

  const mapped = mapLogToAgentAction(text, t);
  if (mapped) return mapped;

  return null;
}

function mapLogToAgentAction(message: string, t: UiTexts): { agent: string; action: string } | null {
  const text = message.trim();
  if (!text) return null;
  if (/^=+|^Round\s+\d+|^第[一二三四五六七八九十]+輪/.test(text)) return null;
  if (/正式會議議程|本次會議結束|流程完成|初步情境分析/.test(text)) return null;

  const rules: Array<{ pattern: RegExp; agent: string; action: string }> = [
    { pattern: /需求衝突再審查|需求衝突辨識|Conflict Gate/i, agent: "analyst", action: t.conflictDetection },
    { pattern: /MoM|會議紀錄|已保存：R\d+-M\d+\.md/i, agent: "mediator", action: "MoM" },
    { pattern: /formalize_requirement|需求正式化/i, agent: "mediator", action: t.formalizeRequirement },
    { pattern: /領域研究|domain|research/i, agent: "expert", action: t.domainResearch },
    { pattern: /系統模型|PlantUML|use case|用例圖|情境圖|model/i, agent: "modeler", action: t.systemModelGeneration },
    { pattern: /draft|草稿/i, agent: "analyst", action: t.updateDraft },
    { pattern: /SRS|軟體需求規格|規格書|規格化/i, agent: "documentor", action: t.stageLabels.SRS },
    { pattern: /Design Rationale|design_rationale|設計緣由/i, agent: "documentor", action: t.stageLabels.DR },
  ];

  const hit = rules.find(({ pattern }) => pattern.test(text));
  if (!hit) return null;
  return {
    agent: agentLabel(hit.agent),
    action: hit.action,
  };
}

function runStageActivityLabel(stageValue: string | null | undefined, t: UiTexts): string | null {
  const stage = String(stageValue || "").trim();
  if (!stage) return null;
  if (/SRS|software.requirements|規格/i.test(stage)) return t.generatingSpecDocument;
  if (/DR|design.rationale|design_rationale|設計緣由/i.test(stage)) {
    return t.generatingDesignRationale;
  }
  if (/document|document_generation|規格化/i.test(stage)) return t.generatingSpecDocument;
  if (/meeting|會議|開會/i.test(stage)) return t.elicitationMeeting;
  return null;
}

export function StatusBar({
  run,
  lastLogMessage,
  historyLoading,
}: StatusBarProps) {
  const { t } = useI18n();
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
    if (historyLoading && !runActive) return t.loadingExistingChat;
    if (run) {
      if (run.status === "cancelling") {
        return {
          text: t.stopping,
          pulse: true,
        };
      }
      const parsed = parseAgentAction(lastLogMessage, t);
      if (parsed) {
        return {
          text: `${parsed.agent}: ${parsed.action}`,
          pulse: false,
        };
      }
      const stageLabel = runStageActivityLabel(run.current_stage, t);
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
      if (waiting) return t.waitingYourDecision;
      if (run.current_agent) {
        return {
          text: t.agentRunning(agentLabel(run.current_agent)),
          pulse: true,
        };
      }
      return {
        text: t.flowRunning,
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
        {statusLabel(run, t)}
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
