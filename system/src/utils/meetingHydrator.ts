import { agentLabel } from "@/constants/agents";
import type { ChatMessage } from "@/types/api";

interface MeetingTurn {
  text?: string;
  speaking_as?: string | string[];
  agent?: string;
  role?: string;
  response?: { text?: string };
}

interface MeetingIssue {
  title?: string;
  issue_id?: string;
  meeting_id?: string;
  category?: string;
  discussion_mode?: string;
  conversation?: MeetingTurn[];
  turns?: MeetingTurn[];
}

function turnText(turn: MeetingTurn): string {
  const direct = String(turn.text ?? "").trim();
  if (direct) return direct;
  const nested = turn.response?.text;
  return typeof nested === "string" ? nested.trim() : "";
}

function turnSpeaker(turn: MeetingTurn): string {
  let speaker = turn.agent ?? turn.role ?? "mediator";
  const speakingAs = turn.speaking_as;
  if (Array.isArray(speakingAs) && speakingAs[0]) {
    speaker = String(speakingAs[0]);
  } else if (typeof speakingAs === "string" && speakingAs) {
    speaker = speakingAs;
  }
  return speaker;
}

function normalizeDialogueSpeech(speaker: string, text: string): { speaker: string; label: string; text: string } {
  const rawSpeaker = speaker.trim();
  const stakeholderPrefix = /^(消費者|利害關係人|使用者)\s*[:：]\s*([\s\S]+)$/.exec(text.trim());
  const agentLikeSpeaker = /^(analyst|expert|modeler|mediator|documentor|documenter|分析師|專家|建模師|主持人)$/i.test(rawSpeaker);

  if (stakeholderPrefix && agentLikeSpeaker) {
    return {
      speaker,
      label: agentLabel(speaker),
      text: stakeholderPrefix[2].trim(),
    };
  }

  if (/^(消費者|利害關係人|使用者)$/.test(rawSpeaker)) {
    return {
      speaker: "stakeholder",
      label: rawSpeaker,
      text: text.replace(/^(消費者|利害關係人|使用者)\s*[:：]\s*/, "").trim(),
    };
  }

  const directed = /^(Analyst|Expert|Modeler|Mediator|User|分析師|專家|建模師|主持人|使用者)\s*(?:→|->)\s*([^:：]+)\s*[:：]\s*([\s\S]+)$/.exec(text.trim());
  if (directed) {
    const aliases: Record<string, string> = {
      analyst: "analyst",
      expert: "expert",
      modeler: "modeler",
      mediator: "mediator",
      user: "user",
      分析師: "analyst",
      專家: "expert",
      建模師: "modeler",
      主持人: "mediator",
      使用者: "user",
    };
    const normalized = aliases[directed[1].toLowerCase()] ?? aliases[directed[1]] ?? speaker;
    return {
      speaker: normalized,
      label: agentLabel(normalized),
      text: directed[3].trim(),
    };
  }

  if (stakeholderPrefix) {
    return {
      speaker: "stakeholder",
      label: stakeholderPrefix[1].trim(),
      text: stakeholderPrefix[2].trim(),
    };
  }

  return {
    speaker,
    label: agentLabel(speaker),
    text,
  };
}

function issueHeader(issue: MeetingIssue): string | null {
  const title = issue.title?.trim();
  if (title) {
    return `議題：${title}${issue.discussion_mode ? `（${issue.discussion_mode}）` : ""}`;
  }
  const id = issue.issue_id?.trim() || issue.meeting_id?.trim();
  if (!id) return null;
  const category = issue.category?.trim();
  const mode = issue.discussion_mode ? `（${issue.discussion_mode}）` : "";
  return category
    ? `議題：${id} · ${category}${mode}`
    : `議題：${id}${mode}`;
}

function hydrateIssues(
  issues: unknown[],
  prefix: string,
): ChatMessage[] {
const messages: ChatMessage[] = [];
  issues.forEach((issue, issueIndex) => {
    if (!issue || typeof issue !== "object") return;
    const row = issue as MeetingIssue;
    const header = issueHeader(row);
    if (header) {
      messages.push({
        id: `${prefix}-issue-${issueIndex}`,
        role: "system",
        kind: "stage",
        issue: header,
        text: header,
      });
    }
    const turns = row.conversation ?? row.turns ?? [];
    turns.forEach((turn, turnIndex) => {
      const text = turnText(turn);
      if (!text) return;
      const speaker = turnSpeaker(turn);
      const normalized = normalizeDialogueSpeech(speaker, text);
      messages.push({
        id: `${prefix}-${issueIndex}-${turnIndex}`,
        role: "agent",
        kind: "speech",
        speaker: normalized.speaker,
        label: normalized.label,
        text: normalized.text,
        issue: header ?? undefined,
      });
    });
  });
  return messages;
}

function hydrateElicitation(
  data: Record<string, unknown>,
  prefix: string,
): ChatMessage[] {
  const messages: ChatMessage[] = [];
  const meeting = data.meeting;
  if (!meeting || typeof meeting !== "object" || Array.isArray(meeting)) {
    return messages;
  }

  const plan = data.plan as { mode?: string } | undefined;
  const modeHint = plan?.mode ? `（${plan.mode}）` : "";

  for (const [roundKey, rows] of Object.entries(
    meeting as Record<string, unknown>,
  )) {
    if (!Array.isArray(rows)) continue;
    messages.push({
      id: `${prefix}-elicitation-${roundKey}`,
      role: "system",
      kind: "stage",
      round: roundKey.toUpperCase(),
      text: `需求訪談 · ${roundKey}${modeHint}`,
    });
    rows.forEach((row, rowIndex) => {
      if (!row || typeof row !== "object") return;
      const record = row as Record<string, unknown>;
      const orderedEntries = [
        ["analyst", record.analyst],
        ["消費者", record["消費者"]],
        ["expert", record.expert],
        ["消費者", record["消費者"]],
        ["modeler", record.modeler],
        ["消費者", record["消費者"]],
        ...Object.entries(record).filter(
          ([speaker]) => !["id", "analyst", "expert", "modeler", "消費者"].includes(speaker),
        ),
      ] as Array<[string, unknown]>;
      const seen = new Set<string>();
      for (const [speaker, value] of orderedEntries) {
        if (speaker === "id" || typeof value !== "string") continue;
        const key = `${speaker}:${value}`;
        if (seen.has(key)) continue;
        seen.add(key);
        const text = value.trim();
        if (!text) continue;
        const normalized = normalizeDialogueSpeech(speaker, text);
        messages.push({
          id: `${prefix}-${roundKey}-${rowIndex}-${speaker}`,
          role: "agent",
          kind: "speech",
          speaker: normalized.speaker,
          label: normalized.label,
          text: normalized.text,
          round: roundKey.toUpperCase(),
        });
      }
    });
  }
  return messages;
}

export function hydrateMeetingJson(
  data: unknown,
  prefix = "meeting",
): ChatMessage[] {
  if (!data || typeof data !== "object") return [];

  const root = data as Record<string, unknown>;

  if (
    root.meeting &&
    typeof root.meeting === "object" &&
    !Array.isArray(root.meeting)
  ) {
    return hydrateElicitation(root, prefix);
  }

  const issues = Array.isArray(root.issues)
    ? root.issues
    : Array.isArray(root)
      ? root
      : [root];

  return hydrateIssues(issues, prefix);
}

export function findMeetingJsonPaths(items: { path: string; kind: string }[]) {
  return items
    .filter(
      (i) =>
        i.kind === "file" &&
        /artifact\/meeting\/(formal_meeting_r\d+|elicitation_meeting)\.json$/i.test(
          i.path,
        ),
    )
    .map((i) => i.path)
    .sort((a, b) => {
      const round = (p: string) => {
        const m = /formal_meeting_r(\d+)/i.exec(p);
        return m ? Number(m[1]) : 0;
      };
      const ar = round(a);
      const br = round(b);
      if (ar !== br) return ar - br;
      return a.localeCompare(b);
    });
}
