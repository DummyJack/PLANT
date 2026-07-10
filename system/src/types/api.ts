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
  has_cost_summary?: boolean;
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
  activated?: boolean;
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
  skip_all_human_interventions?: boolean;
  cancel_requested: boolean;
  started_at: string;
  finished_at: string | null;
  error: string | null;
  event_count: number;
  run_checkpoint?: RunCheckpoint | null;
}

export interface RunCheckpoint {
  status: "failed" | "cancelled" | "interrupted" | string;
  stage_id: string;
  step_id?: string;
  run_id: string;
  error?: string;
  dirty_outputs?: string[];
  last_round?: number;
  round?: number;
  issue_id?: string;
  agent?: string;
  action?: string;
  resume_policy?: string;
  created_at?: string;
}

export interface PendingDecision {
  id: string;
  kind:
    | "stakeholder_selection"
    | "human_decision"
    | "stakeholder_statement_review"
    | "requirements_review"
    | "domain_research_review"
    | "scope_review"
    | "meeting_issue_proposal_review";
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
  stage_id?: string;
  step_id?: string;
  agent?: string;
  action?: string;
  title?: string;
  status?: "running" | "done" | "waiting" | "failed";
  output_path?: string;
  delta_type?: string;
  content?: unknown;
  summary?: Record<string, unknown>;
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

export interface CostAgentSummary {
  model?: string;
  input_tokens?: number;
  output_tokens?: number;
  total_tokens?: number;
  "run_time(s)"?: number;
  estimated_cost?: number;
  "estimated_cost(USD)"?: number;
  [key: string]: unknown;
}

export interface CostSummary {
  project_id?: string;
  agents?: Record<string, CostAgentSummary>;
  totals?: CostAgentSummary;
  [key: string]: unknown;
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
  decisionId?: string;
  decision?: PendingDecision;
  decisionPayload?: Record<string, unknown>;
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
  max_issues?: number;
  stage?: Record<string, boolean>;
  export?: Record<string, boolean>;
  agent_models?: Record<string, AgentModelConfig>;
  enable_agents?: Record<string, boolean>;
  [key: string]: unknown;
}
