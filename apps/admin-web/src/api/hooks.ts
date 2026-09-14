import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/api/client";
import type {
  Agent,
  AgentCreateRequest,
  AgentRoomsResponse,
  Artifact,
  AuditEvent,
  CurrentUser,
  DashboardSummary,
  ExternalAgentStatus,
  Mission,
  MissionCreateRequest,
  ModelInvocation,
  ModelPolicy,
  Task,
} from "@/types/api";

export function useCurrentUser(enabled: boolean) {
  return useQuery({
    queryKey: ["me"],
    queryFn: () => api.get<CurrentUser>("/api/v1/auth/me"),
    enabled,
    retry: false,
  });
}

export function useDashboardSummary() {
  return useQuery({
    queryKey: ["dashboard-summary"],
    queryFn: () => api.get<DashboardSummary>("/api/v1/dashboard/summary"),
    refetchInterval: 10_000,
  });
}

export function useAgents() {
  return useQuery({ queryKey: ["agents"], queryFn: () => api.get<Agent[]>("/api/v1/agents") });
}

export function useModelPolicies() {
  return useQuery({
    queryKey: ["model-policies"],
    queryFn: () => api.get<ModelPolicy[]>("/api/v1/model-policies"),
  });
}

export function useCreateAgent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: AgentCreateRequest) => api.post<Agent>("/api/v1/agents", payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["agents"] });
      queryClient.invalidateQueries({ queryKey: ["agent-rooms"] });
    },
  });
}

export function useActivateAgent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ agentId, versionId }: { agentId: string; versionId: string }) =>
      api.post<Agent>(`/api/v1/agents/${agentId}/activate?version_id=${versionId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["agents"] });
      queryClient.invalidateQueries({ queryKey: ["agent-rooms"] });
    },
  });
}

export function useSuspendAgent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (agentId: string) => api.post<Agent>(`/api/v1/agents/${agentId}/suspend`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["agents"] });
      queryClient.invalidateQueries({ queryKey: ["agent-rooms"] });
    },
  });
}

export function useAgentRooms() {
  return useQuery({
    queryKey: ["agent-rooms"],
    queryFn: () => api.get<AgentRoomsResponse>("/api/v1/agent-rooms"),
    refetchInterval: 3_000,
  });
}

export function useMissions() {
  return useQuery({
    queryKey: ["missions"],
    queryFn: () => api.get<Mission[]>("/api/v1/missions"),
    refetchInterval: 5_000,
  });
}

export function useMission(missionId: string | undefined) {
  return useQuery({
    queryKey: ["missions", missionId],
    queryFn: () => api.get<Mission>(`/api/v1/missions/${missionId}`),
    enabled: !!missionId,
    refetchInterval: 3_000,
  });
}

export function useCreateMission() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: MissionCreateRequest) => api.post<Mission>("/api/v1/missions", payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["missions"] }),
  });
}

export function useStartMission() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (missionId: string) => api.post<Mission>(`/api/v1/missions/${missionId}/start`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["missions"] }),
  });
}

export function useCancelMission() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (missionId: string) => api.post<Mission>(`/api/v1/missions/${missionId}/cancel`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["missions"] }),
  });
}

export function useMissionTasks(missionId: string | undefined) {
  return useQuery({
    queryKey: ["missions", missionId, "tasks"],
    queryFn: () => api.get<Task[]>(`/api/v1/missions/${missionId}/tasks`),
    enabled: !!missionId,
    refetchInterval: 3_000,
  });
}

export function useRetryTask() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (taskId: string) => api.post<Task>(`/api/v1/tasks/${taskId}/retry`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["missions"] }),
  });
}

export function useMissionArtifacts(missionId: string | undefined) {
  return useQuery({
    queryKey: ["missions", missionId, "artifacts"],
    queryFn: () => api.get<Artifact[]>(`/api/v1/missions/${missionId}/artifacts`),
    enabled: !!missionId,
    refetchInterval: 5_000,
  });
}

export function useArtifactDownloadUrl() {
  return useMutation({
    mutationFn: (artifactId: string) =>
      api.get<{ download_url: string; expires_in_seconds: number }>(
        `/api/v1/artifacts/${artifactId}/download`,
      ),
  });
}

export function useMissionModelInvocations(missionId: string | undefined) {
  return useQuery({
    queryKey: ["missions", missionId, "model-invocations"],
    queryFn: () => api.get<ModelInvocation[]>(`/api/v1/missions/${missionId}/model-invocations`),
    enabled: !!missionId,
    refetchInterval: 5_000,
  });
}

export function useExternalAgentStatuses() {
  return useQuery({
    queryKey: ["external-agents"],
    queryFn: () => api.get<ExternalAgentStatus[]>("/api/v1/external-agents"),
    refetchInterval: 3_000,
  });
}

export function useMissionTimeline(missionId: string | undefined) {
  return useQuery({
    queryKey: ["missions", missionId, "timeline"],
    queryFn: () => api.get<AuditEvent[]>(`/api/v1/missions/${missionId}/timeline`),
    enabled: !!missionId,
    refetchInterval: 3_000,
  });
}
