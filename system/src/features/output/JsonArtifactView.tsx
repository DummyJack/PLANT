import { agentLabel } from "@/constants/agents";
import type { ReactNode } from "react";

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

function text(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function stopReasonLabel(reason: string): string {
  switch (reason) {
    case "judge_finish":
      return "收束投票通過";
    case "no_new_info":
      return "連續未產生新候選需求";
    case "max_turn":
    case "max_turns_reached":
      return "達到最大訪談輪次";
    case "":
      return "尚未記錄結束原因";
    default:
      return reason;
  }
}

function JsonBlock({ data }: { data: unknown }) {
  return (
    <pre className="overflow-auto rounded-control bg-slate-950 p-3 font-mono text-xs leading-relaxed text-slate-100">
      {JSON.stringify(data, null, 2)}
    </pre>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <section className="border-b border-gray-100 px-4 py-3 last:border-0">
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
        {title}
      </h3>
      {children}
    </section>
  );
}

function ElicitationView({ data }: { data: Record<string, unknown> }) {
  const plan = isRecord(data.plan) ? data.plan : {};
  const meeting = isRecord(data.meeting) ? data.meeting : {};
  const elicited = Array.isArray(data.elicited_reqts) ? data.elicited_reqts : [];
  const stopReason = text(data.elicitation_stop_reason);

  return (
    <div className="min-h-0 overflow-y-auto">
      <Section title="訪談狀態">
        <div className="flex flex-wrap gap-2 text-xs text-slate-600">
          <span className="rounded-full border border-gray-200 bg-white px-2 py-1">
            輪次上限：{String(plan.round_limit ?? "未設定")}
          </span>
          <span className="rounded-full border border-gray-200 bg-white px-2 py-1">
            模式：{text(plan.mode) || "未記錄"}
          </span>
          <span className="rounded-full border border-emerald-200 bg-emerald-50 px-2 py-1 text-emerald-800">
            結束：{stopReasonLabel(stopReason)}
          </span>
        </div>
      </Section>

      <Section title="訪談紀錄">
        {Object.keys(meeting).length === 0 ? (
          <p className="text-sm text-slate-500">尚無訪談問答紀錄</p>
        ) : (
          <div className="space-y-3">
            {Object.entries(meeting).map(([roundKey, rows]) => (
              <div key={roundKey}>
                <div className="mb-1 text-xs font-medium text-slate-500">
                  {roundKey.toUpperCase()}
                </div>
                <div className="space-y-2">
                  {(Array.isArray(rows) ? rows : []).map((row, index) => (
                    <div
                      key={`${roundKey}-${index}`}
                      className="rounded-control border border-gray-200 bg-white p-3"
                    >
                      {isRecord(row) &&
                        Object.entries(row)
                          .filter(([key]) => key !== "id")
                          .map(([speaker, value]) => (
                            <div key={speaker} className="mb-2 last:mb-0">
                              <div className="text-xs font-semibold text-slate-500">
                                {agentLabel(speaker)}
                              </div>
                              <div className="mt-0.5 whitespace-pre-wrap text-sm leading-relaxed text-slate-800">
                                {String(value ?? "")}
                              </div>
                            </div>
                          ))}
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </Section>

      <Section title="候選需求">
        {elicited.length === 0 ? (
          <p className="text-sm text-slate-500">尚無擷取候選需求</p>
        ) : (
          <div className="space-y-2">
            {elicited.map((row, index) => (
              <div
                key={index}
                className="rounded-control border border-gray-200 bg-white p-3 text-sm text-slate-800"
              >
                {isRecord(row) ? text(row.text) || JSON.stringify(row) : String(row)}
              </div>
            ))}
          </div>
        )}
      </Section>
    </div>
  );
}

function turnText(turn: unknown): string {
  if (!isRecord(turn)) return "";
  const direct = text(turn.text);
  if (direct) return direct;
  return isRecord(turn.response) ? text(turn.response.text) : "";
}

function FormalMeetingView({ data }: { data: Record<string, unknown> }) {
  const issues = Array.isArray(data.issues)
    ? data.issues
    : Array.isArray(data)
      ? data
      : [];

  return (
    <div className="min-h-0 overflow-y-auto">
      <Section title="正式會議">
        {issues.length === 0 ? (
          <p className="text-sm text-slate-500">尚無正式會議議題</p>
        ) : (
          <div className="space-y-3">
            {issues.map((issue, index) => {
              if (!isRecord(issue)) return null;
              const turns = Array.isArray(issue.conversation)
                ? issue.conversation
                : Array.isArray(issue.turns)
                  ? issue.turns
                  : [];
              return (
                <article
                  key={index}
                  className="rounded-control border border-gray-200 bg-white"
                >
                  <div className="border-b border-gray-100 px-3 py-2">
                    <div className="text-sm font-semibold text-slate-800">
                      {text(issue.title) || text(issue.issue_id) || `議題 ${index + 1}`}
                    </div>
                    <div className="mt-1 flex flex-wrap gap-1.5 text-[11px] text-slate-500">
                      {text(issue.category) && <span>{text(issue.category)}</span>}
                      {text(issue.discussion_mode) && <span>{text(issue.discussion_mode)}</span>}
                    </div>
                  </div>
                  <div className="space-y-2 px-3 py-3">
                    {turns.map((turn, turnIndex) => {
                      if (!isRecord(turn)) return null;
                      const speaker = text(turn.agent) || text(turn.role) || "mediator";
                      const body = turnText(turn);
                      if (!body) return null;
                      return (
                        <div key={turnIndex}>
                          <div className="text-xs font-semibold text-slate-500">
                            {agentLabel(speaker)}
                          </div>
                          <div className="mt-0.5 whitespace-pre-wrap text-sm leading-relaxed text-slate-800">
                            {body}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </Section>
    </div>
  );
}

export function JsonArtifactView({
  path,
  content,
}: {
  path: string;
  content: string;
}) {
  let data: unknown;
  try {
    data = JSON.parse(content);
  } catch {
    return <JsonBlock data={content} />;
  }

  if (isRecord(data) && /elicitation_meeting\.json$/i.test(path)) {
    return <ElicitationView data={data} />;
  }
  if (isRecord(data) && /formal_meeting_r\d+\.json$/i.test(path)) {
    return <FormalMeetingView data={data} />;
  }
  return (
    <div className="min-h-0 flex-1 overflow-auto p-4">
      <JsonBlock data={data} />
    </div>
  );
}
