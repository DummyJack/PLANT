import { agentLabel } from "@/constants/agents";
import type { ChatMessage, RunEvent } from "@/types/api";

const HARD_SKIP =
  /^(\[debug\]|health_probe|\.pyc|\/Users\/|HTTP Request:)/i;

const AGENT_NAME_ALIASES: Record<string, string> = {
  user: "user",
  useragent: "user",
  analyst: "analyst",
  analystagent: "analyst",
  expert: "expert",
  expertagent: "expert",
  modeler: "modeler",
  modeleragent: "modeler",
  documentor: "documentor",
  documentoragent: "documentor",
  mediator: "mediator",
  mediatoragent: "mediator",
};

const AGENT_PATTERNS: Array<{ pattern: RegExp; agent: string }> = [
  { pattern: /analyst|分析/i, agent: "analyst" },
  { pattern: /expert|專家|領域/i, agent: "expert" },
  { pattern: /modeler|建模/i, agent: "modeler" },
  { pattern: /documentor|文件/i, agent: "documentor" },
  { pattern: /mediator|主持/i, agent: "mediator" },
  { pattern: /\buser\b|使用者|利害關係人/i, agent: "user" },
];

function inferAgent(message: string): string {
  for (const { pattern, agent } of AGENT_PATTERNS) {
    if (pattern.test(message)) return agent;
  }
  return "mediator";
}

function normalizeAgentName(raw: string): string {
  const key = raw.replace(/agent$/i, "").toLowerCase();
  return AGENT_NAME_ALIASES[key] ?? inferAgent(raw);
}

function shouldSkip(message: string): boolean {
  const t = message.trim();
  if (!t) return true;
  if (HARD_SKIP.test(t)) return true;
  return false;
}

function isSystemProgress(message: string): boolean {
  const t = message.trim();
  return /^={3,}/.test(t) || /^✓/.test(t) || /^跳過/.test(t);
}

function cleanStageText(message: string): string {
  return message
    .trim()
    .replace(/^=+\s*/, "")
    .replace(/\s*=+$/, "")
    .trim();
}

function parseAgentLog(message: string): { agent: string; action: string; text: string } | null {
  const bracket = /^(\w+)\s*\[\d+\/\d+\]:\s*(.+)$/i.exec(message.trim());
  if (!bracket) return null;
  const action = bracket[2].trim();
  return {
    agent: normalizeAgentName(bracket[1]),
    action,
    text: action || message.trim(),
  };
}

function completionMessage(message: string): ChatMessage | null {
  const text = message.trim();
  if (!text.startsWith("✓")) return null;
  return {
    id: "",
    role: "system",
    kind: "stage",
    status: "done",
    text,
  };
}

function outputMessage(event: RunEvent, message: string): ChatMessage | null {
  const text = message.trim();
  if (
    !/(已生成|已產生|已儲存|已保存|已更新|已輸出|已轉成 html|產生完成|生成完成)/.test(
      text,
    )
  ) {
    return null;
  }
  return {
    id: `out-${event.id}`,
    role: "system",
    kind: "output",
    status: "done",
    text,
    outputPath: outputPathForText(text),
    timestamp: event.timestamp,
  };
}

function outputPathForText(text: string): string | undefined {
  if (/srs|軟體需求規格書/i.test(text)) return "results/srs.html";
  if (/design rationale|design_rationale|dr|設計緣由/i.test(text))
    return "results/design_rationale.html";
  if (/conflict_report|需求衝突報告|衝突報告/i.test(text))
    return "results/report/conflict_report.html";
  const draft = /draft_v(\d+)|Draft v(\d+)|草稿.*?(\d+)/i.exec(text);
  if (draft) {
    const version = draft[1] ?? draft[2] ?? draft[3];
    return `results/drafts/draft_v${version}.html`;
  }
  return undefined;
}

function decisionPayloadText(event: RunEvent): string {
  const payload = event.payload ?? {};
  const stakeholders = Array.isArray(payload.stakeholders)
    ? payload.stakeholders
        .map((row) => {
          if (!row || typeof row !== "object") return "";
          const item = row as Record<string, unknown>;
          return String(item.name ?? "").trim();
        })
        .filter(Boolean)
    : [];
  if (stakeholders.length) {
    return `已選擇利害關係人：${stakeholders.join("、")}`;
  }

  const selections = Array.isArray(payload.selections)
    ? payload.selections
        .map((row) => {
          if (!row || typeof row !== "object") return "";
          const item = row as Record<string, unknown>;
          return item.index != null ? `#${String(item.index)}` : String(item.name ?? "").trim();
        })
        .filter(Boolean)
    : [];
  if (selections.length) {
    return `已選擇利害關係人：${selections.join("、")}`;
  }

  const chosenOptions = Array.isArray(payload.chosen_options)
    ? payload.chosen_options
        .map((row) => {
          if (!row || typeof row !== "object") return "";
          const item = row as Record<string, unknown>;
          return String(item.title ?? item.id ?? "").trim();
        })
        .filter(Boolean)
    : [];
  if (chosenOptions.length) {
    return `已採納方案：${chosenOptions.join("、")}`;
  }

  const choices = Array.isArray(payload.choices)
    ? payload.choices.map((v) => String(v)).filter(Boolean)
    : [];
  const custom = String(payload.custom_decision ?? payload.decision ?? "").trim();
  if (custom) return `已提交裁決：${custom}`;
  if (choices.length) return `已採納方案：${choices.join("、")}`;
  if (payload.skipped === true) return "已略過本次裁決";
  return "已提交決策";
}

export function logEventToChat(event: RunEvent): ChatMessage | null {
  if (event.type === "references_attached") {
    const paths = Array.isArray(event.attached_reference_paths)
      ? event.attached_reference_paths.map((path) => String(path).split("/").pop() ?? String(path))
      : [];
    return {
      id: `refs-${event.id}`,
      role: "system",
      kind: "output",
      status: "done",
      text: paths.length
        ? `已使用參考文件：${paths.join("、")}`
        : "已使用參考文件",
      timestamp: event.timestamp,
    };
  }
  if (event.type === "waiting_for_human") {
    return {
      id: `sys-${event.id}`,
      role: "system",
      kind: "decision",
      status: "waiting",
      text: event.decision?.title ?? event.message ?? "等待你的決策",
      timestamp: event.timestamp,
    };
  }
  if (event.type === "human_decision_submitted") {
    return {
      id: `user-dec-${event.id}`,
      role: "user",
      kind: "decision",
      status: "done",
      label: "你",
      text: decisionPayloadText(event),
      timestamp: event.timestamp,
    };
  }
  if (event.type === "cancel_requested") {
    return {
      id: `sys-${event.id}`,
      role: "system",
      kind: "stage",
      status: "running",
      text: "已送出停止請求，等待目前步驟結束...",
      timestamp: event.timestamp,
    };
  }
  if (event.type === "run_started") {
    return {
      id: `sys-${event.id}`,
      role: "system",
      kind: "stage",
      status: "running",
      text: "工作坊已啟動",
      timestamp: event.timestamp,
    };
  }
  if (
    event.type === "run_completed" ||
    event.type === "run_failed" ||
    event.type === "run_cancelled"
  ) {
    const label =
      event.type === "run_completed"
        ? "執行完成"
        : event.type === "run_failed"
          ? "執行失敗"
          : "已取消";
    return {
      id: `sys-${event.id}`,
      role: "system",
      kind: "stage",
      status: event.type === "run_failed" ? "failed" : "done",
      text: event.message?.trim() || label,
      timestamp: event.timestamp,
    };
  }
  if (event.type !== "log") return null;

  const message = event.message ?? "";
  if (shouldSkip(message)) return null;

  const output = outputMessage(event, message);
  if (output) return output;

  if (isSystemProgress(message)) {
    const completed = completionMessage(message);
    return {
      id: `log-${event.id}`,
      role: "system",
      kind: "stage",
      status: completed?.status ?? (message.trim().startsWith("跳過") ? "done" : "running"),
      text: completed?.text ?? cleanStageText(message),
      timestamp: event.timestamp,
    };
  }

  const parsed = parseAgentLog(message);
  const agent = parsed?.agent ?? inferAgent(message);
  return {
    id: `log-${event.id}`,
    role: "agent",
    kind: parsed ? "action" : "speech",
    speaker: agent,
    label: agentLabel(agent),
    action: parsed?.action,
    status: parsed ? "running" : undefined,
    text: parsed?.text ?? message.trim(),
    timestamp: event.timestamp,
  };
}

export function mergeChatMessages(messages: ChatMessage[]): ChatMessage[] {
  const out: ChatMessage[] = [];
  for (const msg of messages) {
    const prev = out[out.length - 1];
    if (
      prev &&
      msg.role === "agent" &&
      prev.role === "agent" &&
      prev.speaker === msg.speaker &&
      msg.kind === "speech" &&
      prev.kind === "speech" &&
      prev.text.length < 200
    ) {
      prev.text = `${prev.text}\n${msg.text}`;
      continue;
    }
    out.push({ ...msg });
  }
  return out;
}

export function buildInitialUserMessage(roughIdea: string): ChatMessage {
  return {
    id: "rough-idea",
    role: "user",
    kind: "speech",
    label: agentLabel("user"),
    text: roughIdea,
  };
}
