import { agentLabel } from "@/constants/agents";
import type { ChatMessage, RunEvent } from "@/types/api";

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

  if (payload.skipped === true) return "已略過本次裁決";
  return "已提交決策";
}

function humanDecisionRequestText(decision?: RunEvent["decision"]): string {
  if (!decision) return "等待人類裁決";
  const options = decision.options && typeof decision.options === "object"
    ? (decision.options as Record<string, unknown>)
    : {};
  const bestOptions = Array.isArray(options.best_options)
    ? options.best_options
    : [];
  const rows = bestOptions
    .map((row, index) => {
      if (!row || typeof row !== "object") return "";
      const item = row as Record<string, unknown>;
      const title = String(item.title ?? item.summary ?? `方案 ${index + 1}`).trim();
      const description = String(item.description ?? "").trim();
      const letter = String.fromCharCode(65 + index);
      return description
        ? `${letter}. ${title}\n${description}`
        : `${letter}. ${title}`;
    })
    .filter(Boolean);
  return [
    decision.title,
    decision.description,
    rows.length ? `候選方案\n${rows.join("\n")}` : "",
  ]
    .map((item) => String(item ?? "").trim())
    .filter(Boolean)
    .join("\n\n");
}

function workspaceEventText(event: RunEvent, fallback: string) {
  return event.message?.trim() || event.title?.trim() || fallback;
}

function logMessageToAgent(text: string): { speaker: string; text: string } | null {
  const value = text.trim();
  if (!value || /^=+$/.test(value) || /^={2,}/.test(value)) return null;
  if (/^(stage|step)\s+(started|completed):/i.test(value)) return null;
  if (/^artifact created:/i.test(value)) return null;
  if (/^\s{2,}\S+(?:\s*→\s*[^：:]+)?[：:]/.test(text)) return null;

  const direct =
    /^\s*(user|analyst|expert|modeler|mediator|documentor|documenter)\s*[:：]\s*([\s\S]+)$/i.exec(value);
  if (direct) {
    const rawSpeaker = direct[1].toLowerCase();
    return {
      speaker: rawSpeaker === "documenter" ? "documentor" : rawSpeaker,
      text: direct[2].trim(),
    };
  }

  const arrow =
    /^\s*(user|analyst|expert|modeler|mediator|documentor|documenter)\s*(?:→|->)\s*([^：:]+)?[：:]\s*([\s\S]+)$/i.exec(value);
  if (arrow) {
    const rawSpeaker = arrow[1].toLowerCase();
    const target = String(arrow[2] ?? "").trim();
    const body = arrow[3].trim();
    return {
      speaker: rawSpeaker === "documenter" ? "documentor" : rawSpeaker,
      text: target ? `${target}：${body}` : body,
    };
  }

  const humanDecision = /^\s*人類裁決[：:]\s*([\s\S]+)$/i.exec(value);
  if (humanDecision) {
    return { speaker: "user", text: humanDecision[1].trim() };
  }

  return null;
}

function deltaContentText(content: unknown): string {
  if (typeof content === "string") return content.trim();
  if (content == null) return "";
  if (typeof content === "number" || typeof content === "boolean") {
    return String(content);
  }
  if (typeof content === "object") {
    const item = content as Record<string, unknown>;
    const title = String(item.title ?? item.heading ?? item.id ?? "").trim();
    const body = String(item.body ?? item.text ?? item.markdown ?? item.content ?? "").trim();
    if (title && body) return `${title}\n${body}`;
    if (title) return title;
    if (body) return body;
    try {
      return JSON.stringify(content, null, 2);
    } catch {
      return String(content);
    }
  }
  return String(content).trim();
}

export function logEventToChat(event: RunEvent): ChatMessage | null {
  if (event.type === "stage_completed") return null;

  if (event.type === "stage_started") {
    if (event.stage_id === "export") return null;
    return {
      id: `stage-${event.id}`,
      role: "system",
      kind: "stage",
      status: "running",
      stage: event.stage_id,
      text: workspaceEventText(
        event,
        "階段開始",
      ),
      timestamp: event.timestamp,
    };
  }

  if (event.type === "step_started") {
    if (event.step_id === "conflict_detection.write_report") {
      const speaker = event.agent || "analyst";
      return {
        id: `workspace-step-start-${event.id}`,
        role: "agent",
        kind: "action",
        speaker,
        label: agentLabel(speaker),
        action: event.step_id ?? event.action,
        stage: event.stage_id,
        status: "running",
        text: "衝突報告產生中 ...",
        timestamp: event.timestamp,
      };
    }
    if (
      event.step_id === "init.generate_scope" ||
      event.step_id === "elicitation.merge_requirements"
    ) {
      return null;
    }
    if (
      event.step_id === "init.analyze_scenario" ||
      event.step_id === "init.analyze_requirements"
    ) {
      const speaker = event.agent || "analyst";
      return {
        id: `workspace-init-analysis-${event.stage_id}`,
        role: "agent",
        kind: "action",
        speaker,
        label: agentLabel(speaker),
        action: event.step_id ?? event.action,
        stage: event.stage_id,
        status: "running",
        text: "分析中 ...",
        timestamp: event.timestamp,
      };
    }
    const speaker = event.agent || "mediator";
    const rawText = workspaceEventText(event, "步驟開始");
    const text =
      event.step_id?.startsWith("draft.") ||
      (speaker.toLowerCase() === "documentor" && /^產生\s*/.test(rawText))
        ? "生成中 ..."
        : rawText;
    return {
      id: `workspace-step-start-${event.id}`,
      role: "agent",
      kind: "action",
      speaker,
      label: agentLabel(speaker),
      action: event.step_id ?? event.action,
      stage: event.stage_id,
      status: "running",
      text,
      timestamp: event.timestamp,
    };
  }

  if (event.type === "step_completed") {
    if (
      event.step_id?.startsWith("document_generation.") &&
      !/^(results\/(?:srs|design_rationale)\.html|output\/(?:srs|design_rationale)\.md)$/i.test(event.output_path ?? "")
    ) {
      return null;
    }
    if (
      event.step_id === "conflict_detection.write_report" &&
      /^results\/report\/conflict_report_v\d+\.html$/i.test(event.output_path ?? "")
    ) {
      const speaker = event.agent || "analyst";
      return {
        id: `workspace-step-${event.id}`,
        role: "agent",
        kind: "output",
        speaker,
        label: agentLabel(speaker),
        action: event.step_id ?? event.action,
        stage: event.stage_id,
        status: "done",
        text: "產生衝突報告",
        outputPath: event.output_path,
        timestamp: event.timestamp,
      };
    }
    if (
      event.step_id === "init.write_stakeholder_text" ||
      event.step_id === "init.analyze_scenario" ||
      event.step_id === "elicitation.extract_requirements" ||
      (event.step_id?.startsWith("document_generation.") && !event.output_path) ||
      event.step_id === "conflict_review.run_review" ||
      /^formal_meeting\.round_\d+\.run_meeting$/i.test(event.step_id ?? "") ||
      event.step_id === "conflict_detection.write_report"
    ) {
      return null;
    }
    const speaker = event.agent || "mediator";
    return {
      id: `workspace-step-${event.id}`,
      role: "agent",
      kind: "action",
      speaker,
      label: agentLabel(speaker),
      action: event.step_id ?? event.action,
      stage: event.stage_id,
      status: "done",
      text: workspaceEventText(
        event,
        "步驟完成",
      ),
      outputPath: event.output_path,
      timestamp: event.timestamp,
    };
  }

  if (event.type === "artifact_created" || event.type === "artifact_updated") {
    return null;
  }

  if (event.type === "step_delta") {
    if (event.delta_type === "scope") return null;
    if (event.delta_type === "requirement") return null;
    if (event.delta_type === "model") return null;
    if (event.delta_type === "markdown_section" && event.stage_id === "draft") return null;
    if (event.delta_type === "markdown_section" && event.stage_id === "document_generation") return null;
    const text = deltaContentText(event.content);
    if (!text) return null;
    const speaker = event.agent || "mediator";
    return {
      id: `delta-${event.id}`,
      role: "agent",
      kind: event.delta_type === "speech" ? "speech" : "action",
      speaker,
      label: agentLabel(speaker),
      action: event.delta_type === "speech" ? undefined : event.step_id ?? event.action,
      stage: event.stage_id,
      status: "running",
      text,
      timestamp: event.timestamp,
    };
  }

  if (event.type === "heartbeat") {
    return {
      id: `heartbeat-${event.id}`,
      role: "system",
      kind: "stage",
      status: "running",
      stage: event.stage_id,
      text: workspaceEventText(event, "仍在處理中"),
      timestamp: event.timestamp,
    };
  }

  if (event.type === "log") {
    const parsed = logMessageToAgent(workspaceEventText(event, ""));
    if (!parsed) return null;
    return {
      id: `log-${event.id}`,
      role: parsed.speaker === "user" ? "user" : "agent",
      kind: "speech",
      status: event.level === "error" ? "failed" : "done",
      speaker: parsed.speaker,
      label: agentLabel(parsed.speaker),
      text: parsed.text,
      timestamp: event.timestamp,
    };
  }

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
    const stakeholderSelection = event.decision?.kind === "stakeholder_selection";
    const speaker = stakeholderSelection ? "user" : "mediator";
    return {
      id: `human-decision-request-${event.id}`,
      role: "agent",
      kind: "decision",
      status: "waiting",
      speaker,
      label: agentLabel(speaker),
      action: stakeholderSelection ? "stakeholder_selection_request" : "human_decision_request",
      text: humanDecisionRequestText(event.decision),
      timestamp: event.timestamp,
    };
  }
  if (event.type === "human_decision_submitted") {
    const payload = event.payload ?? {};
    if (Array.isArray(payload.stakeholders) || Array.isArray(payload.selections)) {
      return null;
    }
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
    return null;
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
  return null;
}

export function logEventToChats(event: RunEvent): ChatMessage[] {
  const message = logEventToChat(event);
  return message ? [message] : [];
}

export function mergeChatMessages(messages: ChatMessage[]): ChatMessage[] {
  const out: ChatMessage[] = [];
  const seenSpeech = new Set<string>();
  for (const msg of messages) {
    if (msg.role === "agent" && msg.kind === "speech") {
      const key = `${msg.speaker ?? ""}|${msg.text.trim()}`;
      if (seenSpeech.has(key)) continue;
      seenSpeech.add(key);
    }
    const prev = out[out.length - 1];
    if (
      prev &&
      msg.role === "agent" &&
      prev.role === "agent" &&
      prev.speaker === msg.speaker &&
      prev.text.trim() === msg.text.trim() &&
      msg.kind === prev.kind
    ) {
      continue;
    }
    if (
      prev &&
      msg.role === "agent" &&
      prev.role === "agent" &&
      prev.speaker === msg.speaker &&
      msg.kind === "speech" &&
      prev.kind === "speech" &&
      !msg.outputPath &&
      !prev.outputPath &&
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
    label: "您",
    text: roughIdea,
  };
}
