import { agentLabel } from "@/constants/agents";
import { UI_TEXT } from "@/i18n";
import { useUiStore } from "@/stores/uiStore";
import type { ChatMessage, RunEvent } from "@/types/api";

const HIDDEN_STAGE_PILL_IDS = new Set(["export", "conflict_review"]);

function shouldHideStagePill(event: RunEvent, label: string): boolean {
  if (HIDDEN_STAGE_PILL_IDS.has(String(event.stage_id ?? "").trim())) return true;
  const normalizedLabel = label.trim();
  return (
    (event.stage_id === "draft" && normalizedLabel === "草稿更新") ||
    (event.stage_id === "formal_meeting" && normalizedLabel === "正式會議")
  );
}

function currentTexts() {
  return UI_TEXT[useUiStore.getState().language];
}

function displayText(value: string): string {
  return value.replace(
    /\b([A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]*[A-Za-z0-9])\b/g,
    (match) => {
      if (/\.(?:json|md|html|png|svg|plantuml|txt|csv|pdf|doc|docx|xlsx|pptx)$/i.test(match)) {
        return match;
      }
      return match.replace(/_/g, " ");
    },
  );
}

function decisionPayloadText(event: RunEvent): string {
  const payload = event.payload ?? {};
  const options = event.decision?.options && typeof event.decision.options === "object"
    ? (event.decision.options as Record<string, unknown>)
    : {};
  const bestOptions = Array.isArray(options.best_options)
    ? options.best_options
        .map((row, index) => {
          if (!row || typeof row !== "object") return null;
          const item = row as Record<string, unknown>;
          const id = String(item.option_id ?? item.id ?? String.fromCharCode(65 + index)).trim();
          const title = String(item.title ?? item.summary ?? item.description ?? "").trim();
          return { id, label: `選項 ${id}`, title };
        })
        .filter((row): row is { id: string; label: string; title: string } => Boolean(row))
    : [];
  const optionById = new Map(bestOptions.map((row) => [row.id, row]));
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
    return `已提交決策\n選擇：\n${stakeholders.join("\n")}`;
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
    return `已提交決策\n選擇：\n${selections.join("\n")}`;
  }

  const humanDecision = String(payload.human_decision ?? "").trim();
  if (humanDecision) {
    return `已提交決策\n建議：\n${humanDecision}`;
  }

  const choices = Array.isArray(payload.choices)
    ? payload.choices
        .map((choice, index) => {
          const id = String(choice ?? String.fromCharCode(65 + index)).trim();
          const matched = optionById.get(id);
          return `${matched?.label ?? `選項 ${id}`}：${matched?.title ?? ""}`.replace(/：$/, "");
        })
        .filter(Boolean)
    : [];
  if (choices.length) {
    return `已提交決策\n選擇：\n${choices.join("\n")}`;
  }

  const chosenOptions = Array.isArray(payload.chosen_options)
    ? payload.chosen_options
        .map((row, index) => {
          if (!row || typeof row !== "object") return "";
          const item = row as Record<string, unknown>;
          const id = String(item.option_id ?? item.id ?? String.fromCharCode(65 + index)).trim();
          const matched = optionById.get(id);
          const title = String(item.title ?? item.summary ?? item.description ?? matched?.title ?? "").trim();
          return `${matched?.label ?? `選項 ${id}`}：${title}`.replace(/：$/, "");
        })
        .filter(Boolean)
    : [];
  if (chosenOptions.length) {
    return `已提交決策\n選擇：\n${chosenOptions.join("\n")}`;
  }

  const customIssues = (Array.isArray(payload.custom_issues) ? payload.custom_issues : [])
        .map((row) => {
          if (!row || typeof row !== "object") return "";
          const item = row as Record<string, unknown>;
          return String(item.title ?? "").trim();
        })
        .filter(Boolean);
  if (customIssues.length) {
    return `已提交決策\n議題：\n${customIssues
      .map((issue, index) => `議題 ${index + 1}：${issue}`)
      .join("\n")}`;
  }

  if (payload.skip_all_human_interventions === true) return "後續人類介入將自動跳過";
  if (payload.skipped === true) return "已略過本次裁決";
  if (payload.action === "approve") return "已提交決策\n無補充建議";
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
  return displayText(event.message?.trim() || event.title?.trim() || fallback);
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
      text: displayText(direct[2].trim()),
    };
  }

  const arrow =
    /^\s*(user|analyst|expert|modeler|mediator|documentor|documenter)\s*(?:→|->)\s*([^：:]+)?[：:]\s*([\s\S]+)$/i.exec(value);
  if (arrow) {
    if (String(arrow[2] ?? "").trim()) return null;
    const rawSpeaker = arrow[1].toLowerCase();
    const target = String(arrow[2] ?? "").trim();
    const body = arrow[3].trim();
    return {
      speaker: rawSpeaker === "documenter" ? "documentor" : rawSpeaker,
      text: displayText(target ? `${target}：${body}` : body),
    };
  }

  const humanDecision = /^\s*人類裁決[：:]\s*([\s\S]+)$/i.exec(value);
  if (humanDecision) {
    return null;
  }

  return null;
}

function deltaContentText(content: unknown): string {
  if (typeof content === "string") return displayText(content.trim());
  if (content == null) return "";
  if (typeof content === "number" || typeof content === "boolean") {
    return String(content);
  }
  if (typeof content === "object") {
    const item = content as Record<string, unknown>;
    const title = String(item.title ?? item.heading ?? item.id ?? "").trim();
    const body = String(item.body ?? item.text ?? item.markdown ?? item.content ?? "").trim();
    if (title && body) return displayText(`${title}\n${body}`);
    if (title) return displayText(title);
    if (body) return displayText(body);
    try {
      return displayText(JSON.stringify(content, null, 2));
    } catch {
      return displayText(String(content));
    }
  }
  return displayText(String(content).trim());
}

function deltaContentLabel(content: unknown): string {
  if (!content || typeof content !== "object") return "";
  const item = content as Record<string, unknown>;
  return String(item.title ?? item.heading ?? item.id ?? "").trim();
}

function elicitationSpeechText(content: unknown): string {
  if (!content || typeof content !== "object") return deltaContentText(content);
  const item = content as Record<string, unknown>;
  return displayText(String(item.body ?? item.text ?? item.markdown ?? item.content ?? "").trim());
}

export function logEventToChat(event: RunEvent): ChatMessage | null {
  if (event.type === "stage_completed") return null;

  if (event.type === "stage_started") {
    const label = workspaceEventText(event, "階段開始");
    if (shouldHideStagePill(event, label)) return null;
    const round = /^第\s*(\d+)\s*輪正式會議開始$/.exec(label.trim())?.[1];
    return {
      id: `stage-${event.id}`,
      role: "system",
      kind: "stage",
      status: "running",
      stage: event.stage_id,
      text: round ? `第 ${round} 輪會議` : label,
      timestamp: event.timestamp,
    };
  }

  if (event.type === "step_started") {
    if (
      event.step_id === "elicitation.run_meeting" ||
      event.step_id === "conflict_detection.detect_pairs" ||
      event.step_id === "conflict_detection.detect_groups" ||
      /^formal_meeting\.round_\d+\.run_meeting$/i.test(event.step_id ?? "")
    ) {
      return null;
    }
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
      event.step_id === "conflict_detection.detect_pairs" ||
      event.step_id === "conflict_detection.detect_groups"
    ) {
      return null;
    }
    if (
      event.output_path &&
      (
        event.step_id === "init.analyze_requirements_review" ||
        event.step_id === "init.generate_scope_review"
      )
    ) {
      const isScopeReview = event.step_id === "init.generate_scope_review";
      const speaker = isScopeReview ? "analyst" : event.agent || "analyst";
      return {
        id: `workspace-review-output-${event.id}`,
        role: "agent",
        kind: "output",
        speaker,
        label: agentLabel(speaker),
        action: event.step_id ?? event.action,
        stage: event.stage_id,
        status: "done",
        text: isScopeReview ? "需求範圍修正" : workspaceEventText(event, "修正結果"),
        outputPath: event.output_path,
        timestamp: event.timestamp,
      };
    }
    if (
      event.output_path === "artifact/feedback.json" &&
      (
        event.step_id === "elicitation.update_feedback" ||
        event.step_id === "research_domain.update_feedback"
      )
    ) {
      const speaker = event.agent || "expert";
      return {
        id: `workspace-feedback-output-${event.id}`,
        role: "agent",
        kind: "output",
        speaker,
        label: agentLabel(speaker),
        action: event.step_id ?? event.action,
        stage: event.stage_id,
        status: "done",
        text: workspaceEventText(event, "領域研究"),
        outputPath: event.output_path,
        timestamp: event.timestamp,
      };
    }
    if (
      event.stage_id === "document_generation" &&
      event.output_path &&
      /^(?:results\/(?:srs|design_rationale)\.html|output\/(?:srs|design_rationale)\.md)$/i.test(event.output_path) &&
      (
        event.step_id === "document_generation.generate_dr" ||
        event.step_id === "document_generation.generate_srs"
      )
    ) {
      const speaker = event.agent || "documentor";
      return {
        id: `workspace-document-output-${event.id}`,
        role: "agent",
        kind: "output",
        speaker,
        label: agentLabel(speaker),
        action: event.step_id ?? event.action,
        stage: event.stage_id,
        status: "done",
        text: event.step_id === "document_generation.generate_srs"
          ? currentTexts().stageLabels.SRS
          : currentTexts().stageLabels.DR,
        outputPath: event.output_path,
        timestamp: event.timestamp,
      };
    }
    if (
      event.step_id?.startsWith("document_generation.") &&
      !/^(results\/(?:srs|design_rationale)\.html|output\/(?:srs|design_rationale)\.md)$/i.test(event.output_path ?? "")
    ) {
      return null;
    }
    if (
      event.stage_id === "system_model" &&
      (event.step_id === "system_model.review_models" ||
        (event.step_id === "system_model.modeling" && !event.output_path))
    ) {
      return null;
    }
    if (
      event.step_id === "conflict_detection.write_report" &&
      /^(?:results\/report\/conflict_report_v\d+\.html|artifact\/report\/conflict_report_v\d+\.md)$/i.test(event.output_path ?? "")
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
        text: "衝突報告",
        outputPath: event.output_path,
        timestamp: event.timestamp,
      };
    }
    if (
      event.step_id === "init.suggest_stakeholders" ||
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
    const momTitle =
      event.step_id === "formal_meeting.write_minutes"
        ? /artifact\/MoM\/(.+?)\.md$/i.exec(event.output_path ?? "")?.[1]
        : "";
    return {
      id: `workspace-step-${event.id}`,
      role: "agent",
      kind: "action",
      speaker,
      label: agentLabel(speaker),
      action: event.step_id ?? event.action,
      stage: event.stage_id,
      status: "done",
      text: momTitle || workspaceEventText(event, "步驟完成"),
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
    const text =
      event.stage_id === "elicitation" && event.delta_type === "speech"
        ? elicitationSpeechText(event.content)
        : deltaContentText(event.content);
    if (!text) return null;
    const speaker = event.agent || "mediator";
    const label =
      event.stage_id === "elicitation" &&
      event.delta_type === "speech" &&
      speaker === "user"
        ? deltaContentLabel(event.content) || agentLabel(speaker)
        : agentLabel(speaker);
    return {
      id: `delta-${event.id}`,
      role: "agent",
      kind: event.delta_type === "speech" ? "speech" : "action",
      speaker,
      label,
      action: event.delta_type === "speech" ? undefined : event.step_id ?? event.action,
      stage: event.stage_id,
      status: "done",
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
    const rawText = workspaceEventText(event, "");
    if (/^\s*(討論完成|收斂結果)[:：]/.test(rawText)) return null;
    if (/^\s*modeler\s*[:：]\s*系統模型已更新/i.test(rawText)) return null;
    const parsed = logMessageToAgent(rawText);
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
    return null;
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
      decisionId: event.decision_id,
      decision: event.decision,
    };
  }
  if (event.type === "human_decision_submitted") {
    return {
      id: `user-dec-${event.id}`,
      role: "user",
      kind: "decision",
      status: "done",
      label: "您",
      text: decisionPayloadText(event),
      timestamp: event.timestamp,
      decisionId: event.decision_id,
      decision: event.decision,
      decisionPayload: event.payload,
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
  if (event.type === "run_completed") {
    return null;
  }
  if (event.type === "run_failed" || event.type === "run_cancelled") {
    const label =
      event.type === "run_failed"
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
  if (
    event.type === "step_started" &&
    (event.step_id === "init.write_stakeholder_text" ||
      event.step_id === "init.write_stakeholder_text_review")
  ) {
    const message = logEventToChat(event);
    const title = String(event.title ?? "").trim();
    const isReview = event.step_id === "init.write_stakeholder_text_review";
    const isRevision = isReview || /修正|Human Decision|回饋/i.test(title);
    const output: ChatMessage = {
      id: `stakeholder-statement-output-${event.id}`,
      role: "agent",
      kind: "output",
      speaker: event.agent || "user",
      label: agentLabel(event.agent || "user"),
      action: isRevision ? "stakeholder_statement_revision" : "stakeholder_statement",
      stage: event.stage_id,
      status: "done",
      text: isReview ? title || "利害關係人發言修正" : isRevision ? "發言修正" : "利害關係人發言",
      outputPath: "artifact/project.json",
      timestamp: event.timestamp,
    };
    return [message, output].filter((item): item is ChatMessage => !!item);
  }
  const message = logEventToChat(event);
  return message ? [message] : [];
}

export function mergeChatMessages(messages: ChatMessage[]): ChatMessage[] {
  const out: ChatMessage[] = [];
  const seenSpeech = new Set<string>();
  const seenStagePills = new Set<string>();
  for (const msg of messages) {
    if (msg.role === "system" && msg.kind === "stage") {
      const key = `${msg.stage ?? ""}|${msg.text.trim()}`;
      if (seenStagePills.has(key)) continue;
      seenStagePills.add(key);
    }
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
      msg.kind === prev.kind &&
      (msg.outputPath ?? "") === (prev.outputPath ?? "")
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
