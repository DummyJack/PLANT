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
      messages.push({
        id: `${prefix}-${issueIndex}-${turnIndex}`,
        role: "agent",
        kind: "speech",
        speaker,
        label: agentLabel(speaker),
        text,
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
      for (const [speaker, value] of Object.entries(record)) {
        if (speaker === "id" || typeof value !== "string") continue;
        const text = value.trim();
        if (!text) continue;
        messages.push({
          id: `${prefix}-${roundKey}-${rowIndex}-${speaker}`,
          role: "agent",
          kind: "speech",
          speaker,
          label: agentLabel(speaker),
          text,
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
