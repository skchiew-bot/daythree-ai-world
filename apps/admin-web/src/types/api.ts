export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export interface CurrentUser {
  id: string;
  tenant_id: string;
  email: string;
  display_name: string;
  role: string;
}

export interface Agent {
  id: string;
  agent_code: string;
  display_name: string;
  description: string | null;
  department: string | null;
  role_name: string | null;
  lifecycle_state: string;
  active_version_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface ToolPolicy {
  allow: string[];
  deny: string[];
}

export interface AgentVersionCreateRequest {
  system_prompt: string;
  runtime_adapter: string;
  model_policy_id: string;
  autonomy_level: "A1" | "A2" | "A3";
  tool_policy: ToolPolicy;
}

export interface AgentCreateRequest {
  agent_code: string;
  display_name: string;
  description?: string;
  department?: string;
  role_name?: string;
  version: AgentVersionCreateRequest;
}

export interface ModelPolicy {
  id: string;
  name: string;
  primary_provider: string;
  primary_model: string;
}

export interface BudgetPolicy {
  max_model_cost_usd: number;
  max_model_calls: number;
  max_runtime_minutes: number;
  max_retries: number;
  max_output_tokens: number;
}

export interface Mission {
  id: string;
  mission_code: string;
  title: string;
  objective: string;
  status: string;
  priority: string;
  risk_level: string;
  assigned_agent_id: string | null;
  budget_policy: BudgetPolicy;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface MissionCreateRequest {
  title: string;
  objective: string;
  assigned_agent_id: string;
  priority?: "low" | "normal" | "high" | "urgent";
  risk_level?: "low" | "medium" | "high";
}

export interface Task {
  id: string;
  mission_id: string;
  assigned_agent_id: string;
  title: string;
  status: string;
  retry_count: number;
  output_artifact_id: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface Artifact {
  id: string;
  mission_id: string;
  task_id: string;
  agent_id: string;
  agent_version_id: string;
  artifact_type: string;
  title: string;
  content_hash: string;
  mime_type: string;
  version: number;
  created_at: string;
}

export interface AuditEvent {
  id: string;
  event_type: string;
  actor_type: string;
  actor_id: string | null;
  mission_id: string | null;
  task_id: string | null;
  agent_id: string | null;
  correlation_id: string;
  causation_id: string | null;
  payload: Record<string, unknown>;
  occurred_at: string;
}

export interface ModelInvocation {
  id: string;
  task_id: string;
  provider: string;
  model: string;
  input_tokens: number;
  output_tokens: number;
  estimated_cost: string;
  latency_ms: number;
  status: string;
  created_at: string;
}

export interface DashboardSummary {
  total_agents: number;
  active_missions: number;
  failed_missions: number;
  completed_missions: number;
  model_calls: number;
  current_cost_usd: number;
  system_status: string;
}
