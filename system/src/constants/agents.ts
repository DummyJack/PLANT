const AGENT_ORDER = [
  "user",
  "analyst",
  "expert",
  "modeler",
  "documentor",
  "mediator",
] as const;

export type AgentId = (typeof AGENT_ORDER)[number];

/** Short labels for header status pills */
export const HEADER_AGENT_ORDER = [
  "user",
  "analyst",
  "expert",
  "modeler",
  "mediator",
  "documentor",
] as const;

export const HEADER_AGENT_LABELS: Record<string, string> = {
  user: "User",
  analyst: "Analyst",
  expert: "Expert",
  modeler: "Modeler",
  mediator: "Mediator",
  documentor: "Documentor",
};

/** Full labels for chat bubbles */
export const AGENT_LABELS: Record<string, string> = {
  user: "User",
  analyst: "Analyst",
  expert: "Expert",
  modeler: "Modeler",
  documentor: "Documentor",
  mediator: "Mediator",
};

export function agentLabel(id: string): string {
  return AGENT_LABELS[id] ?? id;
}
