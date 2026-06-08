export type RunStatus =
  | "queued"
  | "running"
  | "waiting_for_human"
  | "cancelling"
  | "completed"
  | "failed"
  | "cancelled"
  | "interrupted";

export interface ProjectSummary {
  project_id: string;
  created_at?: string;
  rough_idea?: string;
  scenario?: string;
  has_results?: boolean;
  status_hint?: string;
  active_run?: {
    run_id: string;
    status: RunStatus;
    pending_decision?: PendingDecision | null;
  } | null;
}

export interface BootstrapResponse {
  config: { loaded: boolean; error: string | null };
  model_summary: string;
  api_keys: { valid: boolean; error: string | null };
  projects: ProjectSummary[];
  active_runs: Record<string, { run_id: string; status: RunStatus }>;
  interrupted_run_count: number;
  formal_meeting_enabled: boolean;
  requires_rounds_input: boolean;
}

export interface RunState {
  run_id: string;
  project_id: string;
  mode: "new" | "continue";
  status: RunStatus;
  current_stage: string;
  current_agent: string;
  round: number | null;
  rough_idea: string;
  attached_reference_paths?: string[];
  requires_rounds_input: boolean;
  pending_decision: PendingDecision | null;
  cancel_requested: boolean;
  started_at: string;
  finished_at: string | null;
  error: string | null;
  event_count: number;
}

export interface PendingDecision {
  id: string;
  kind: "stakeholder_selection" | "human_decision";
  title: string;
  description: string;
  proposed?: Array<{ name: string; type: string; reason: string }>;
  max_select?: number;
  issue?: Record<string, unknown>;
  options?: Record<string, unknown>;
}

export interface RunEvent {
  id: number;
  type: string;
  message?: string;
  level?: string;
  timestamp?: string;
  decision_id?: string;
  decision?: PendingDecision;
  payload?: Record<string, unknown>;
  attached_reference_paths?: string[];
  error?: string;
}

export interface FileTreeNode {
  path: string;
  name: string;
  kind: "file" | "directory";
  size: number | null;
  editable: boolean;
  previewable: boolean;
}

export interface FileContent {
  path: string;
  type: string;
  encoding: string;
  content: string;
  editable: boolean;
  readonly: boolean;
  mime?: string;
}

export interface LibraryRow {
  id: string;
  name: string;
  source: "外部上傳" | "Documenter" | "Analyst" | "Meeting" | "Modeler";
  path: string;
  editable: boolean;
  deletable: boolean;
}

export interface ChatMessage {
  id: string;
  role: "user" | "agent" | "system";
  kind?: "stage" | "action" | "speech" | "decision" | "output";
  speaker?: string;
  label?: string;
  text: string;
  action?: string;
  stage?: string;
  status?: "running" | "done" | "waiting" | "failed";
  round?: string;
  issue?: string;
  outputPath?: string;
  timestamp?: string;
}

export interface SystemModel {
  id: string;
  name: string;
  type: string;
  plantuml?: string;
  image_path?: string;
}

export type SpecKind = "draft" | "srs" | "dr";
export type ModelLayout = "dual" | "code" | "diagram";
export type DiscussionMode = "sequential" | "simultaneous";

export interface AgentModelConfig {
  provider: string;
  model: string;
  temperature?: number;
}

export interface PlantConfig {
  rounds?: number;
  stage?: Record<string, boolean>;
  agent_models?: Record<string, AgentModelConfig>;
  enable_agents?: Record<string, boolean>;
  [key: string]: unknown;
}
