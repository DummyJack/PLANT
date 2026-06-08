import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, Settings } from "lucide-react";
import { fetchConfig, updateConfig } from "@/api/config";
import { fetchModelApiKeys, updateModelApiKey } from "@/api/secrets";
import {
  HEADER_AGENT_LABELS,
  HEADER_AGENT_ORDER,
  type AgentId,
} from "@/constants/agents";
import { useBootstrap } from "@/hooks/useBootstrap";
import { useActiveRun } from "@/hooks/useActiveRun";
import { useNoticeStore } from "@/stores/noticeStore";
import { useUiStore } from "@/stores/uiStore";
import type { AgentModelConfig, PlantConfig, RunState } from "@/types/api";
import { cn } from "@/utils/cn";
import { useEffect, useRef, useState } from "react";

const ACTIVE_STATUSES = new Set([
  "queued",
  "running",
  "waiting_for_human",
  "cancelling",
]);

type AgentPipelineStatus = "idle" | "running" | "waiting" | "done";

function agentPipelineStatus(
  agentId: string,
  run: RunState | null,
): AgentPipelineStatus {
  if (!run || !ACTIVE_STATUSES.has(run.status)) return "idle";

  const order = HEADER_AGENT_ORDER as readonly string[];
  const currentIdx = order.indexOf(run.current_agent);
  const agentIdx = order.indexOf(agentId);
  if (agentIdx < 0) return "idle";

  if (run.current_agent === agentId) {
    return run.status === "waiting_for_human" ? "waiting" : "running";
  }
  if (currentIdx >= 0 && agentIdx < currentIdx) return "done";
  return "idle";
}

const AGENT_STATUS_STYLES: Record<
  AgentPipelineStatus,
  { pill: string; dot: string }
> = {
  idle: {
    pill: "border-gray-100 bg-gray-50 text-gray-400",
    dot: "bg-gray-200",
  },
  running: {
    pill: "border-emerald-300 bg-emerald-50 text-emerald-800",
    dot: "bg-emerald-500 animate-pulse",
  },
  waiting: {
    pill: "border-amber-300 bg-amber-50 text-amber-800",
    dot: "bg-amber-500 animate-pulse",
  },
  done: {
    pill: "border-gray-200 bg-gray-50 text-slate-600",
    dot: "bg-emerald-400",
  },
};

function AgentConfigPopover({
  agentId,
  config,
  disabled,
  onSave,
}: {
  agentId: AgentId;
  config: PlantConfig | null;
  disabled?: boolean;
  onSave: (next: PlantConfig) => void;
}) {
  const enabledAgents = useUiStore((s) => s.enabledAgents);
  const modelConfig = config?.agent_models?.[agentId];
  const [provider, setProvider] = useState(modelConfig?.provider ?? "");
  const [model, setModel] = useState(modelConfig?.model ?? "");
  const [modelMenuOpen, setModelMenuOpen] = useState(false);
  const on = enabledAgents[agentId] !== false;
  const providerOptions = Array.from(
    new Set(
      Object.values(config?.agent_models ?? {})
        .map((row) => row?.provider)
        .filter((value): value is string => !!value),
    ),
  );
  const modelOptions = Array.from(
    new Set(
      Object.values(config?.agent_models ?? {})
        .map((row) => row?.model)
        .filter((value): value is string => !!value),
    ),
  );
  if (provider && !providerOptions.includes(provider)) providerOptions.push(provider);
  if (model && !modelOptions.includes(model)) modelOptions.push(model);

  useEffect(() => {
    setProvider(modelConfig?.provider ?? "");
    setModel(modelConfig?.model ?? "");
  }, [modelConfig?.provider, modelConfig?.model, agentId]);

  const save = () => {
    if (!config) return;
    const agent_models = { ...(config.agent_models ?? {}) };
    agent_models[agentId] = {
      ...(agent_models[agentId] ?? {}),
      provider: provider.trim(),
      model: model.trim(),
    } as AgentModelConfig;
    const enable_agents = {
      ...(config.enable_agents ?? {}),
      ...enabledAgents,
      [agentId]: on,
    };
    const next = { ...config, agent_models, enable_agents };
    onSave(next);
  };

  return (
    <div className="absolute left-0 top-full z-30 mt-1 w-56 rounded-control border border-gray-200 bg-white p-3 shadow-lg">
      <div className="space-y-2">
        <label className="block">
          <span className="mb-1 block text-[11px] font-medium text-slate-500">
            Provider
          </span>
          <select
            className="w-full rounded-control border border-gray-200 px-2 py-1 text-xs text-slate-700 focus:border-slate-400 focus:outline-none"
            value={provider}
            disabled={disabled}
            onChange={(e) => setProvider(e.target.value)}
          >
            <option value="" disabled>
              Provider
            </option>
            {providerOptions.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className="mb-1 block text-[11px] font-medium text-slate-500">
            Model
          </span>
          <div className="relative">
            <input
              className="w-full rounded-control border border-gray-200 px-2 py-1 pr-7 text-xs text-slate-700 focus:border-slate-400 focus:outline-none"
              value={model}
              disabled={disabled}
              placeholder="Model"
              onFocus={() => setModelMenuOpen(true)}
              onChange={(e) => {
                setModel(e.target.value);
                setModelMenuOpen(true);
              }}
            />
            <button
              type="button"
              disabled={disabled || modelOptions.length === 0}
              className="absolute right-1 top-1/2 flex h-6 w-6 -translate-y-1/2 items-center justify-center rounded text-slate-400 hover:bg-gray-50 hover:text-slate-700 disabled:opacity-30"
              onClick={() => setModelMenuOpen((open) => !open)}
            >
              <ChevronDown className="h-3.5 w-3.5" />
            </button>
            {modelMenuOpen && modelOptions.length > 0 && (
              <div className="absolute left-0 right-0 top-full z-40 mt-1 max-h-36 overflow-y-auto rounded-control border border-gray-200 bg-white py-1 shadow-lg">
                {modelOptions.map((value) => (
                  <button
                    key={value}
                    type="button"
                    className="block w-full truncate px-2 py-1.5 text-left text-xs text-slate-700 hover:bg-gray-50"
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={() => {
                      setModel(value);
                      setModelMenuOpen(false);
                    }}
                  >
                    {value}
                  </button>
                ))}
              </div>
            )}
          </div>
        </label>
      </div>
      <div className="mt-3 flex justify-center">
        <button
          type="button"
          disabled={disabled || !provider.trim() || !model.trim()}
          className="rounded-control bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-800 disabled:opacity-40"
          onClick={() => save()}
        >
          {disabled ? "儲存中" : "儲存"}
        </button>
      </div>
    </div>
  );
}

export function HeaderBar() {
  const queryClient = useQueryClient();
  const bootstrap = useBootstrap();
  const projectId = useUiStore((s) => s.activeProjectId);
  const enabledAgents = useUiStore((s) => s.enabledAgents);
  const setEnabledAgents = useUiStore((s) => s.setEnabledAgents);
  const pushNotice = useNoticeStore((s) => s.pushNotice);
  const { activeRun } = useActiveRun(projectId);
  const [openAgent, setOpenAgent] = useState<AgentId | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [apiKeyProvider, setApiKeyProvider] = useState("openai");
  const [apiKeyValue, setApiKeyValue] = useState("");
  const agentWrapRef = useRef<HTMLDivElement>(null);
  const settingsRef = useRef<HTMLDivElement>(null);

  const configQuery = useQuery({
    queryKey: ["config"],
    queryFn: async () => (await fetchConfig()).config,
  });

  const saveConfigMut = useMutation({
    mutationFn: updateConfig,
    onSuccess: ({ config }) => {
      if (config.enable_agents) {
        setEnabledAgents({
          ...useUiStore.getState().enabledAgents,
          ...config.enable_agents,
        });
      }
      queryClient.invalidateQueries({ queryKey: ["config"] });
      queryClient.invalidateQueries({ queryKey: ["bootstrap"] });
      pushNotice({
        tone: "success",
        title: "已儲存",
        message: "代理模型設定已更新",
      });
    },
  });

  const keyQuery = useQuery({
    queryKey: ["model-api-keys"],
    queryFn: fetchModelApiKeys,
    enabled: settingsOpen,
  });

  const saveKeyMut = useMutation({
    mutationFn: () => updateModelApiKey(apiKeyProvider, apiKeyValue),
    onSuccess: () => {
      setApiKeyValue("");
      queryClient.invalidateQueries({ queryKey: ["model-api-keys"] });
      queryClient.invalidateQueries({ queryKey: ["bootstrap"] });
      pushNotice({
        tone: "success",
        title: "已儲存",
        message: "模型 API Key 已更新",
      });
    },
  });

  useEffect(() => {
    if (!openAgent) return;
    const handler = (event: MouseEvent) => {
      const target = event.target as Node;
      if (agentWrapRef.current && !agentWrapRef.current.contains(target)) {
        setOpenAgent(null);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [openAgent]);

  useEffect(() => {
    if (!settingsOpen) return;
    const handler = (event: MouseEvent) => {
      const target = event.target as Node;
      if (settingsRef.current && !settingsRef.current.contains(target)) {
        setSettingsOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [settingsOpen]);

  const apiOk = bootstrap.data?.api_keys.valid !== false;
  const runActive = !!activeRun && ACTIVE_STATUSES.has(activeRun.status);

  return (
    <header className="shrink-0 border-b border-gray-200 bg-white">
      {!apiOk && (
        <div className="bg-amber-50 px-4 py-1.5 text-xs text-amber-800">
          API 金鑰或設定異常：{bootstrap.data?.api_keys.error ?? "請檢查 .env"}
        </div>
      )}
      <div className="grid h-14 grid-cols-[1fr_auto_1fr] items-center gap-3 px-3">
        <div className="justify-self-start text-base font-bold tracking-tight text-slate-900">
          PLANT
        </div>

        <div className="flex items-center justify-center gap-1.5 justify-self-center" ref={agentWrapRef}>
          {HEADER_AGENT_ORDER.map((id) => {
            const status = agentPipelineStatus(id, activeRun);
            const styles = AGENT_STATUS_STYLES[status];
            const enabled = enabledAgents[id] !== false;
            return (
              <div key={id} className="relative">
                <button
                  type="button"
                  className={cn(
                    "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium",
                    enabled
                      ? "border-emerald-200 bg-emerald-50 text-emerald-800"
                      : "border-red-200 bg-red-50 text-red-700",
                    runActive && styles.pill,
                  )}
                  title={`${HEADER_AGENT_LABELS[id]} — 點擊設定 provider/model`}
                  onClick={() => setOpenAgent((current) => (current === id ? null : id))}
                >
                  <span
                    className={cn(
                      "h-1.5 w-1.5 rounded-full",
                      enabled ? "bg-emerald-500" : "bg-red-500",
                      runActive && styles.dot,
                    )}
                  />
                  {HEADER_AGENT_LABELS[id]}
                </button>
                {openAgent === id && (
                  <AgentConfigPopover
                    agentId={id}
                    config={configQuery.data ?? null}
                    disabled={saveConfigMut.isPending}
                    onSave={(next) => saveConfigMut.mutate(next)}
                  />
                )}
              </div>
            );
          })}
        </div>

        <div className="flex items-center justify-end gap-2 justify-self-end">
          {runActive && (
            <span className="inline-flex items-center gap-1.5 text-xs text-slate-500">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" />
              執行中
            </span>
          )}
          <div className="relative" ref={settingsRef}>
            <button
              type="button"
              className="inline-flex h-7 w-7 items-center justify-center rounded-control border border-gray-200 bg-white text-slate-600 hover:bg-gray-50 hover:text-slate-900"
              title="設定"
              onClick={() => setSettingsOpen((open) => !open)}
            >
              <Settings className="h-3.5 w-3.5" />
            </button>
            {settingsOpen && (
              <div className="absolute right-0 top-full z-40 mt-2 w-72 rounded-control border border-gray-200 bg-white p-3 shadow-lg">
                <div className="border-b border-gray-100 pb-2">
                  <p className="text-sm font-semibold text-slate-900">設定</p>
                  <p className="mt-1 text-xs text-slate-500">模型 API Key</p>
                </div>
                <div className="mt-3 space-y-3">
                  <label className="block">
                    <span className="mb-1 block text-xs font-medium text-slate-600">
                      Provider
                    </span>
                    <select
                      className="w-full rounded-control border border-gray-200 bg-white px-2 py-1.5 text-xs text-slate-700 focus:border-slate-400 focus:outline-none"
                      value={apiKeyProvider}
                      onChange={(event) => setApiKeyProvider(event.target.value)}
                    >
                      {(keyQuery.data?.providers ?? [
                        { provider: "openai", env_key: "OPENAI_API_KEY", configured: false },
                        { provider: "claude", env_key: "ANTHROPIC_API_KEY", configured: false },
                        { provider: "gemini", env_key: "GEMINI_API_KEY", configured: false },
                      ]).map((row) => (
                        <option key={row.provider} value={row.provider}>
                          {row.provider} {row.configured ? "已設定" : "未設定"}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="block">
                    <span className="mb-1 block text-xs font-medium text-slate-600">
                      API Key
                    </span>
                    <input
                      type="password"
                      className="w-full rounded-control border border-gray-200 bg-white px-2 py-1.5 text-xs text-slate-700 focus:border-slate-400 focus:outline-none"
                      placeholder="輸入新的 API Key"
                      value={apiKeyValue}
                      onChange={(event) => setApiKeyValue(event.target.value)}
                    />
                  </label>
                  {saveKeyMut.isError && (
                    <p className="text-xs text-red-600">
                      {saveKeyMut.error instanceof Error
                        ? saveKeyMut.error.message
                        : "儲存失敗"}
                    </p>
                  )}
                  <div className="flex justify-center">
                    <button
                      type="button"
                      disabled={!apiKeyValue.trim() || saveKeyMut.isPending}
                      className="rounded-control bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-800 disabled:opacity-40"
                      onClick={() => saveKeyMut.mutate()}
                    >
                      {saveKeyMut.isPending ? "儲存中" : "儲存"}
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </header>
  );
}
