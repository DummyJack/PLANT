import type { RunEvent } from "@/types/api";

function text(value: unknown) {
  return String(value ?? "").trim();
}

function pathFromContent(content: unknown): string {
  if (!content || typeof content !== "object") return "";
  const item = content as Record<string, unknown>;
  return text(item.output_path ?? item.path ?? item.file ?? item.file_path);
}

function formalMeetingRoundPath(event: RunEvent): string | null {
  const value = `${event.step_id ?? ""} ${event.message ?? ""} ${event.title ?? ""}`;
  const match = /formal_meeting\.round_(\d+)|第\s*(\d+)\s*輪正式會議/i.exec(value);
  const round = match?.[1] ?? match?.[2];
  return round ? `artifact/meeting/formal_meeting_r${round}.json` : null;
}

export function outputPathFromRunEvent(event: RunEvent): string | null {
  const stage = text(event.stage_id);
  const step = text(event.step_id);
  const action = text(event.action);
  const message = text(event.message);
  const title = text(event.title);

  if (/document_generation/i.test(stage) && /design_rationale/i.test(step)) {
    return "results/design_rationale.html";
  }
  if (/document_generation/i.test(stage) && /srs/i.test(step)) return "results/srs.html";

  const directPath = text(event.output_path) || pathFromContent(event.content);
  if (directPath) return directPath;

  if (stage === "init") {
    const value = `${step} ${action} ${message} ${title}`;
    if (/requirements|analysis|需求分析|初始需求/i.test(value)) {
      return "artifact/requirements.json";
    }
    if (/scope|範圍/i.test(value)) return "artifact/scope.json";
    if (/project|scenario|stakeholder|專案|情境|利害關係人/i.test(value)) {
      return "artifact/project.json";
    }
    return null;
  }
  if (stage === "elicitation") {
    if (/requirements|analysis/i.test(step) || /requirements|analysis/i.test(action)) {
      return "artifact/requirements.json";
    }
    return "artifact/meeting/elicitation_meeting.json";
  }
  if (stage === "conflict_detection") return "artifact/result.json";
  if (stage === "research_domain") return "artifact/feedback.json";
  if (stage === "system_model") return "artifact/system_models.json";
  if (stage === "formal_meeting") return formalMeetingRoundPath(event);
  if (stage === "DR") return "results/design_rationale.html";
  if (stage === "SRS") return "results/srs.html";

  if (/draft/i.test(stage)) return null;
  return null;
}
