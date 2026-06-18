import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, LayoutPanelLeft, Moon, Settings, Sun } from "lucide-react";
import { fetchConfig, updateConfig } from "@/api/config";
import {
  activateCode,
  deactivateCode,
  deleteModelApiKey,
  fetchActivationStatus,
  fetchModelApiKeys,
  updateModelApiKey,
} from "@/api/secrets";
import {
  HEADER_AGENT_LABELS,
  HEADER_AGENT_ORDER,
  type AgentId,
} from "@/constants/agents";
import { useBootstrap } from "@/hooks/useBootstrap";
import { useActiveRun } from "@/hooks/useActiveRun";
import { useNoticeStore } from "@/stores/noticeStore";
import { useUiStore } from "@/stores/uiStore";
import type { AgentModelConfig, PlantConfig } from "@/types/api";
import { cn } from "@/utils/cn";
import { errorMessage } from "@/utils/errorMessage";
import { useEffect, useMemo, useRef, useState } from "react";

const ACTIVE_STATUSES = new Set([
  "queued",
  "running",
  "waiting_for_human",
  "cancelling",
]);

const API_KEY_PROVIDERS = [
  { provider: "openai", label: "OpenAI", envKey: "OPENAI_API_KEY" },
  { provider: "claude", label: "Claude", envKey: "ANTHROPIC_API_KEY" },
  { provider: "gemini", label: "Gemini", envKey: "GEMINI_API_KEY" },
] as const;

const RECOMMENDED_MODELS: Record<string, string[]> = {
  openai: ["gpt-4.1", "gpt-4.1-mini", "o4-mini"],
  claude: ["claude-3-5-sonnet-latest", "claude-3-5-haiku-latest", "claude-3-opus-latest"],
  gemini: ["gemini-1.5-pro", "gemini-1.5-flash", "gemini-2.0-flash"],
};

type ApiKeyProvider = (typeof API_KEY_PROVIDERS)[number]["provider"];
type InlineMessage = { tone: "success" | "error"; text: string };
type ConfirmAction =
  | { type: "api-key"; provider: ApiKeyProvider }
  | { type: "activation" };

function providerLabel(provider: ApiKeyProvider): string {
  return API_KEY_PROVIDERS.find((item) => item.provider === provider)?.label ?? provider;
}

function displayProvider(value: string): string {
  const normalized = value.trim().toLowerCase();
  const known = API_KEY_PROVIDERS.find((item) => item.provider === normalized);
  return known?.label ?? value;
}

function apiKeyConfiguredMap(
  providers?: Array<{ provider: string; configured: boolean }>,
): Record<ApiKeyProvider, boolean> {
  const rows = new Map(
    (providers ?? []).map((row) => [row.provider.toLowerCase(), row.configured]),
  );
  return {
    openai: rows.get("openai") === true,
    claude: rows.get("claude") === true,
    gemini: rows.get("gemini") === true,
  };
}

function agentModelReady(
  config: PlantConfig | null | undefined,
  agentId: string,
  configuredProviders: Record<ApiKeyProvider, boolean>,
): boolean {
  const modelConfig = config?.agent_models?.[agentId];
  const provider = String(modelConfig?.provider ?? "").trim().toLowerCase() as ApiKeyProvider;
  const model = String(modelConfig?.model ?? "").trim();
  return !!provider && !!model && configuredProviders[provider] === true;
}

function ModelOptionGroup({
  title,
  options,
  onSelect,
}: {
  title: string;
  options: string[];
  onSelect: (value: string) => void;
}) {
  return (
    <div>
      <div className="px-2 pb-1 pt-1 text-[10px] font-semibold text-slate-400">
        {title}
      </div>
      {options.map((value) => (
        <button
          key={`${title}-${value}`}
          type="button"
          className="block w-full truncate px-2 py-1.5 text-left text-xs text-slate-700 hover:bg-gray-50"
          onMouseDown={(event) => event.preventDefault()}
          onClick={() => onSelect(value)}
        >
          {value}
        </button>
      ))}
    </div>
  );
}

function AgentConfigPopover({
  agentId,
  config,
  configuredProviders,
  disabled,
  onSave,
}: {
  agentId: AgentId;
  config: PlantConfig | null;
  configuredProviders: Record<ApiKeyProvider, boolean>;
  disabled?: boolean;
  onSave: (next: PlantConfig) => void;
}) {
  const enabledAgents = useUiStore((s) => s.enabledAgents);
  const modelConfig = config?.agent_models?.[agentId];
  const configuredProvider = configuredProviders[
    (modelConfig?.provider ?? "").toLowerCase() as ApiKeyProvider
  ]
    ? (modelConfig?.provider ?? "").toLowerCase()
    : "";
  const [provider, setProvider] = useState(configuredProvider);
  const [model, setModel] = useState(configuredProvider ? (modelConfig?.model ?? "") : "");
  const [providerMenuOpen, setProviderMenuOpen] = useState(false);
  const [modelMenuOpen, setModelMenuOpen] = useState(false);
  const popoverRef = useRef<HTMLDivElement>(null);
  const on = enabledAgents[agentId] !== false;
  const providerOptions: string[] = API_KEY_PROVIDERS
    .map((item) => item.provider)
    .filter((value) => configuredProviders[value]);
  const recentModelOptions = Array.from(
    new Set(
      Object.values(config?.agent_models ?? {})
        .map((row) => row?.model)
        .filter((value): value is string => !!value && value !== modelConfig?.model),
    ),
  ).slice(0, 2);
  const recommendedModelOptions = (RECOMMENDED_MODELS[provider.toLowerCase()] ?? [
    "gpt-4.1",
    "claude-3-5-sonnet-latest",
    "gemini-1.5-pro",
  ])
    .filter((value) => value !== model && !recentModelOptions.includes(value))
    .slice(0, 3);
  const hasModelOptions = recentModelOptions.length > 0 || recommendedModelOptions.length > 0;
  if (provider && !providerOptions.includes(provider.toLowerCase())) {
    providerOptions.push(provider);
  }

  useEffect(() => {
    const nextProvider = configuredProviders[
      (modelConfig?.provider ?? "").toLowerCase() as ApiKeyProvider
    ]
      ? (modelConfig?.provider ?? "").toLowerCase()
      : "";
    setProvider(nextProvider);
    setModel(nextProvider ? (modelConfig?.model ?? "") : "");
  }, [configuredProviders, modelConfig?.provider, modelConfig?.model, agentId]);

  useEffect(() => {
    const onPointerDown = (event: PointerEvent) => {
      if (!popoverRef.current?.contains(event.target as Node)) {
        setProviderMenuOpen(false);
        setModelMenuOpen(false);
      }
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, []);

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
    <div
      ref={popoverRef}
      className="absolute left-1/2 top-full z-30 mt-1 w-56 -translate-x-1/2 rounded-control border border-gray-200 bg-white p-3 shadow-lg"
    >
      <div className="space-y-2">
        <div className="block">
          <span className="mb-1 block text-[11px] font-medium text-slate-500">
            Provider
          </span>
          <div className="relative">
            <button
              type="button"
              disabled={disabled || providerOptions.length === 0}
              className="flex h-8 w-full items-center justify-between rounded-control border border-gray-200 bg-white px-2 text-left text-xs text-slate-700 hover:border-gray-300 focus:border-slate-400 focus:outline-none disabled:opacity-50"
              onClick={() => setProviderMenuOpen((open) => !open)}
            >
              <span className={provider ? "text-slate-700" : "text-slate-400"}>
                {provider ? displayProvider(provider) : "未選擇"}
              </span>
              <ChevronDown className="h-3.5 w-3.5 shrink-0 text-slate-400" />
            </button>
            {providerMenuOpen && providerOptions.length > 0 && (
              <div className="absolute left-0 right-0 top-full z-40 mt-1 max-h-36 overflow-y-auto rounded-control border border-gray-200 bg-white py-1 shadow-lg">
                {providerOptions.map((value) => (
                  <button
                    key={value}
                    type="button"
                    className="block w-full truncate px-2 py-1.5 text-left text-xs text-slate-700 hover:bg-gray-50"
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={() => {
                      setProvider(value);
                      setModel("");
                      setProviderMenuOpen(false);
                      setModelMenuOpen(false);
                    }}
                  >
                    {displayProvider(value)}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
        <div className="block">
          <span className="mb-1 block text-[11px] font-medium text-slate-500">
            Model
          </span>
          <div className="relative">
            <input
              className="block h-8 w-full rounded-control border border-gray-200 px-2 pr-7 text-xs text-slate-700 placeholder:text-slate-400 focus:border-slate-400 focus:outline-none"
              value={model}
              disabled={disabled || !provider}
              placeholder="未選擇"
              onChange={(e) => {
                if (!provider) return;
                setModel(e.target.value);
              }}
            />
            <button
              type="button"
              disabled={disabled || !provider || !hasModelOptions}
              className="absolute right-1 top-1/2 flex h-6 w-6 -translate-y-1/2 items-center justify-center rounded text-slate-400 hover:bg-gray-50 hover:text-slate-700 disabled:opacity-30"
              onClick={() => setModelMenuOpen((open) => !open)}
            >
              <ChevronDown className="h-3.5 w-3.5" />
            </button>
            {modelMenuOpen && hasModelOptions && (
              <div className="absolute left-0 right-0 top-full z-40 mt-1 max-h-52 overflow-y-auto rounded-control border border-gray-200 bg-white py-1 shadow-lg">
                <ModelOptionGroup
                  title="最近使用"
                  options={recentModelOptions}
                  onSelect={(value) => {
                    setModel(value);
                    setModelMenuOpen(false);
                  }}
                />
                <div className="my-1 border-t border-gray-100" />
                {recommendedModelOptions.length > 0 && (
                  <ModelOptionGroup
                    title="推薦"
                    options={recommendedModelOptions}
                    onSelect={(value) => {
                      setModel(value);
                      setModelMenuOpen(false);
                    }}
                  />
                )}
              </div>
            )}
          </div>
        </div>
      </div>
      <div className="mt-3 flex justify-center">
        <button
          type="button"
          disabled={disabled || !provider.trim() || !model.trim()}
          className="rounded-control bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-800 disabled:opacity-40"
          onClick={() => save()}
        >
          儲存
        </button>
      </div>
    </div>
  );
}

function ApiKeySettingsPanel({
  providers,
  savingProvider,
  deletingProvider,
  values,
  messages,
  expandedProvider,
  onToggle,
  onChange,
  onSave,
  onDelete,
  locked,
}: {
  providers: Record<ApiKeyProvider, boolean>;
  savingProvider: ApiKeyProvider | null;
  deletingProvider: ApiKeyProvider | null;
  values: Record<ApiKeyProvider, string>;
  messages: Partial<Record<ApiKeyProvider, { tone: "success" | "error"; text: string }>>;
  expandedProvider: ApiKeyProvider | null;
  onToggle: (provider: ApiKeyProvider) => void;
  onChange: (provider: ApiKeyProvider, value: string) => void;
  onSave: (provider: ApiKeyProvider) => void;
  onDelete: (provider: ApiKeyProvider) => void;
  locked: boolean;
}) {
  return (
    <div className="space-y-1.5">
      {API_KEY_PROVIDERS.map((item) => {
        const configured = providers[item.provider];
        const expanded = expandedProvider === item.provider;
        const saving = savingProvider === item.provider;
        const deleting = deletingProvider === item.provider;
        const message = messages[item.provider];
        return (
          <div
            key={item.provider}
            className="rounded-control border border-gray-100 bg-white"
          >
            <button
              type="button"
              className="flex w-full items-center justify-between gap-3 px-2.5 py-2 text-left"
              onClick={() => onToggle(item.provider)}
            >
              <span className="flex min-w-0 items-center gap-2">
                <span
                  className={cn(
                    "h-2 w-2 rounded-full",
                    !locked && configured ? "bg-emerald-500" : "bg-gray-200",
                  )}
                />
                <span
                  className={cn(
                    "text-xs font-semibold",
                    !locked && configured ? "text-emerald-800" : "text-slate-700",
                  )}
                >
                  {item.label}
                </span>
              </span>
              <ChevronDown
                className={cn(
                  "h-3.5 w-3.5 shrink-0 text-slate-400 transition-transform",
                  expanded && "rotate-180",
                )}
              />
            </button>
            {expanded && (
              <div className="border-t border-gray-100 px-2.5 pb-2.5 pt-2">
                <div className="flex items-center gap-2">
                  <input
                    type="password"
                    className="min-w-0 flex-1 rounded-control border border-gray-200 bg-white px-2 py-1.5 text-xs text-slate-700 focus:border-slate-400 focus:outline-none"
                    placeholder={`輸入 ${item.label} API Key`}
                    value={values[item.provider]}
                    disabled={locked}
                    onChange={(event) => onChange(item.provider, event.target.value)}
                  />
                  <button
                    type="button"
                    disabled={locked || !values[item.provider].trim() || saving || deleting}
                    className="shrink-0 rounded-control bg-slate-900 px-2.5 py-1 text-[11px] font-medium text-white hover:bg-slate-800 disabled:bg-gray-300 disabled:text-white"
                    onClick={() => onSave(item.provider)}
                  >
                    {saving ? "儲存中" : "儲存"}
                  </button>
                  <button
                    type="button"
                    disabled={locked || !configured || saving || deleting}
                    className="shrink-0 rounded-control border border-red-100 bg-white px-2.5 py-1 text-[11px] font-medium text-red-600 hover:bg-red-50 disabled:border-gray-100 disabled:text-gray-300"
                    onClick={() => onDelete(item.provider)}
                  >
                    {deleting ? "移除中" : "移除"}
                  </button>
                </div>
                {message && (
                  <p
                    className={cn(
                      "mt-1.5 text-[11px]",
                      message.tone === "success" ? "text-emerald-700" : "text-red-600",
                    )}
                  >
                    {message.text}
                  </p>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function ActivationCodePanel({
  activated,
  value,
  saving,
  message,
  onChange,
  onSubmit,
  onDelete,
}: {
  activated: boolean;
  value: string;
  saving: boolean;
  message?: InlineMessage;
  onChange: (value: string) => void;
  onSubmit: () => void;
  onDelete: () => void;
}) {
  return (
    <div className="border-t border-gray-100 pt-3">
      <div className="flex items-center gap-2">
        <input
          type="password"
          className="min-w-0 flex-1 rounded-control border border-gray-200 bg-white px-2 py-1.5 text-xs text-slate-700 focus:border-slate-400 focus:outline-none"
          placeholder="輸入啟動碼"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") onSubmit();
          }}
        />
        <button
          type="button"
          disabled={!value.trim() || saving}
          className="shrink-0 rounded-control bg-slate-900 px-2.5 py-1 text-[11px] font-medium text-white hover:bg-slate-800 disabled:bg-gray-300 disabled:text-white"
          onClick={onSubmit}
        >
          {saving ? "啟動中" : "啟動"}
        </button>
        {activated && (
          <button
            type="button"
            disabled={saving}
            className="shrink-0 rounded-control border border-red-100 bg-white px-2.5 py-1 text-[11px] font-medium text-red-600 hover:bg-red-50 disabled:border-gray-100 disabled:text-gray-300"
            onClick={onDelete}
          >
            移除
          </button>
        )}
      </div>
      {message && (
        <p
          className={cn(
            "mt-1.5 text-[11px]",
            message.tone === "success" ? "text-emerald-700" : "text-red-600",
          )}
        >
          {message.text}
        </p>
      )}
    </div>
  );
}

function ConfirmBox({
  title,
  description,
  confirmLabel = "確定",
  loading,
  onCancel,
  onConfirm,
}: {
  title: string;
  description: string;
  confirmLabel?: string;
  loading?: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div
      className="absolute inset-0 z-50 flex items-center justify-center rounded-control bg-white/80 px-4 backdrop-blur-sm"
      onClick={onCancel}
    >
      <div
        className="w-full max-w-[260px] rounded-card border border-gray-200 bg-white p-4 shadow-lg"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="mb-3">
          <p className="text-sm font-semibold text-slate-900">{title}</p>
          <p className="mt-1 text-xs leading-5 text-slate-500">{description}</p>
        </div>
        <div className="flex justify-center gap-2">
          <button
            type="button"
            className="rounded-control border border-gray-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-gray-50"
            onClick={onCancel}
          >
            取消
          </button>
          <button
            type="button"
            disabled={loading}
            className="rounded-control bg-red-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-50"
            onClick={onConfirm}
          >
            {loading ? "處理中" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

export function HeaderBar() {
  const queryClient = useQueryClient();
  const bootstrap = useBootstrap();
  const projectId = useUiStore((s) => s.activeProjectId);
  const enabledAgents = useUiStore((s) => s.enabledAgents);
  const visiblePanels = useUiStore((s) => s.visiblePanels);
  const darkMode = useUiStore((s) => s.darkMode);
  const setEnabledAgents = useUiStore((s) => s.setEnabledAgents);
  const togglePanelVisibility = useUiStore((s) => s.togglePanelVisibility);
  const toggleDarkMode = useUiStore((s) => s.toggleDarkMode);
  const setCanWrite = useUiStore((s) => s.setCanWrite);
  const pushNotice = useNoticeStore((s) => s.pushNotice);
  const { activeRun } = useActiveRun(projectId);
  const [openAgent, setOpenAgent] = useState<AgentId | null>(null);
  const [layoutOpen, setLayoutOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [expandedApiKeyProvider, setExpandedApiKeyProvider] =
    useState<ApiKeyProvider | null>(null);
  const [apiKeyValues, setApiKeyValues] = useState<Record<ApiKeyProvider, string>>({
    openai: "",
    claude: "",
    gemini: "",
  });
  const [apiKeyMessages, setApiKeyMessages] = useState<
    Partial<Record<ApiKeyProvider, { tone: "success" | "error"; text: string }>>
  >({});
  const [activationCode, setActivationCode] = useState("");
  const [activationMessage, setActivationMessage] = useState<InlineMessage | undefined>();
  const [confirmAction, setConfirmAction] = useState<ConfirmAction | null>(null);
  const [activated, setActivated] = useState(false);
  const agentWrapRef = useRef<HTMLDivElement>(null);
  const settingsRef = useRef<HTMLDivElement>(null);

  const configQuery = useQuery({
    queryKey: ["config"],
    queryFn: async () => (await fetchConfig()).config,
    refetchInterval: 3000,
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
      queryClient.setQueryData(["config"], config);
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
    refetchInterval: 3000,
  });

  const activationQuery = useQuery({
    queryKey: ["activation-status"],
    queryFn: fetchActivationStatus,
    refetchInterval: settingsOpen ? 3000 : false,
  });

  const saveKeyMut = useMutation({
    mutationFn: ({ provider, apiKey }: { provider: ApiKeyProvider; apiKey: string }) =>
      updateModelApiKey(provider, apiKey),
    onSuccess: (_result, variables) => {
      queryClient.setQueryData(
        ["model-api-keys"],
        (current: Awaited<ReturnType<typeof fetchModelApiKeys>> | undefined) => ({
          providers: (current?.providers ?? API_KEY_PROVIDERS.map((item) => ({
            provider: item.provider,
            configured: false,
          }))).map((row) =>
            row.provider.toLowerCase() === variables.provider
              ? { ...row, configured: true }
              : row,
          ),
        }),
      );
      setApiKeyValues((current) => ({ ...current, [variables.provider]: "" }));
      setApiKeyMessages((current) => ({
        ...current,
        [variables.provider]: {
          tone: "success",
          text: "已儲存",
        },
      }));
      queryClient.invalidateQueries({ queryKey: ["model-api-keys"] });
      queryClient.invalidateQueries({ queryKey: ["bootstrap"] });
    },
    onError: (error, variables) => {
      setApiKeyMessages((current) => ({
        ...current,
        [variables.provider]: {
          tone: "error",
          text: errorMessage(error, "儲存失敗"),
        },
      }));
    },
  });

  const deleteKeyMut = useMutation({
    mutationFn: ({ provider }: { provider: ApiKeyProvider }) =>
      deleteModelApiKey(provider),
    onSuccess: (_result, variables) => {
      setConfirmAction(null);
      queryClient.setQueryData(
        ["model-api-keys"],
        (current: Awaited<ReturnType<typeof fetchModelApiKeys>> | undefined) => ({
          providers: (current?.providers ?? API_KEY_PROVIDERS.map((item) => ({
            provider: item.provider,
            configured: false,
          }))).map((row) =>
            row.provider.toLowerCase() === variables.provider
              ? { ...row, configured: false }
              : row,
          ),
        }),
      );
      setApiKeyValues((current) => ({ ...current, [variables.provider]: "" }));
      setApiKeyMessages((current) => ({
        ...current,
        [variables.provider]: {
          tone: "success",
          text: "成功移除",
        },
      }));
      queryClient.invalidateQueries({ queryKey: ["model-api-keys"] });
      queryClient.invalidateQueries({ queryKey: ["bootstrap"] });
    },
    onError: (error, variables) => {
      setApiKeyMessages((current) => ({
        ...current,
        [variables.provider]: {
          tone: "error",
          text: errorMessage(error, "移除失敗"),
        },
      }));
    },
  });

  const activateMut = useMutation({
    mutationFn: () => activateCode(activationCode.trim()),
    onSuccess: () => {
      setActivated(true);
      setCanWrite(true);
      setActivationCode("");
      setActivationMessage({ tone: "success", text: "成功啟動" });
      queryClient.invalidateQueries({ queryKey: ["activation-status"] });
    },
    onError: (error) => {
      setActivationMessage({
        tone: "error",
        text: errorMessage(error, "無效的啟動碼"),
      });
    },
  });

  const deactivateMut = useMutation({
    mutationFn: deactivateCode,
    onSuccess: () => {
      setConfirmAction(null);
      setActivated(false);
      setCanWrite(false);
      setActivationCode("");
      setActivationMessage({ tone: "success", text: "成功移除" });
      queryClient.invalidateQueries({ queryKey: ["activation-status"] });
    },
    onError: (error) => {
      setActivationMessage({
        tone: "error",
        text: errorMessage(error, "移除失敗"),
      });
    },
  });

  useEffect(() => {
    const next = !!activationQuery.data?.activated;
    setActivated(next);
    setCanWrite(next);
  }, [activationQuery.data?.activated, setCanWrite]);

  useEffect(() => {
    const timers = Object.entries(apiKeyMessages).map(([provider, message]) => {
      if (!message) return null;
      const delay = message.tone === "success" ? 1000 : 3000;
      return window.setTimeout(() => {
        setApiKeyMessages((current) => ({
          ...current,
          [provider as ApiKeyProvider]: undefined,
        }));
      }, delay);
    });
    return () => timers.forEach((timer) => timer && window.clearTimeout(timer));
  }, [apiKeyMessages]);

  useEffect(() => {
    if (!activationMessage) return;
    const delay = activationMessage.tone === "success" ? 1000 : 3000;
    const timer = window.setTimeout(() => setActivationMessage(undefined), delay);
    return () => window.clearTimeout(timer);
  }, [activationMessage]);

  useEffect(() => {
    if (!openAgent) return;
    const handler = (event: PointerEvent) => {
      const target = event.target as Node;
      if (agentWrapRef.current && !agentWrapRef.current.contains(target)) {
        setOpenAgent(null);
      }
    };
    document.addEventListener("pointerdown", handler);
    return () => document.removeEventListener("pointerdown", handler);
  }, [openAgent]);

  useEffect(() => {
    if (!settingsOpen) return;
    const handler = (event: MouseEvent) => {
      const target = event.target as Node;
      if (settingsRef.current && !settingsRef.current.contains(target)) {
        setConfirmAction(null);
        setSettingsOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [settingsOpen]);

  useEffect(() => {
    if (!settingsOpen) setConfirmAction(null);
  }, [settingsOpen]);

  const apiOk = bootstrap.data?.api_keys.valid !== false;
  const runActive = !!activeRun && ACTIVE_STATUSES.has(activeRun.status);
  const settingsLocked = !activated;
  const configuredProviderMap = useMemo(
    () => apiKeyConfiguredMap(keyQuery.data?.providers),
    [keyQuery.data?.providers],
  );

  return (
    <header className="shrink-0 bg-slate-50">
      {!apiOk && (
        <div className="bg-amber-50 px-4 py-1.5 text-xs text-amber-800">
          API 金鑰或設定異常：{bootstrap.data?.api_keys.error ?? "請檢查 .env"}
        </div>
      )}
      <div className="grid min-h-14 grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 px-3 py-2">
        <div className="justify-self-start text-lg font-bold tracking-tight text-slate-900">
          PLANT
        </div>

        <div
          className="flex min-w-0 flex-wrap items-center justify-center gap-1.5 justify-self-stretch"
          ref={agentWrapRef}
        >
	          {HEADER_AGENT_ORDER.map((id) => {
	            const enabled = enabledAgents[id] !== false;
	            const ready = agentModelReady(configQuery.data, id, configuredProviderMap);
	            const locked = runActive;
	            return (
	          <div key={id} className="relative shrink-0">
	                <button
	                  type="button"
	                  disabled={locked}
	                  className={cn(
	                    "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium disabled:cursor-not-allowed",
	                    settingsLocked || !ready
                        ? "border-gray-200 bg-gray-50 text-gray-400"
                        : enabled
	                      ? "border-emerald-200 bg-emerald-50 text-emerald-800"
	                      : "border-red-200 bg-red-50 text-red-700",
	                  )}
	                  title={
	                    locked
	                      ? `${HEADER_AGENT_LABELS[id]} — 執行中不可操作`
                        : settingsLocked
                          ? `${HEADER_AGENT_LABELS[id]} — 可查看，輸入啟動碼後可修改`
                          : !ready
                            ? `${HEADER_AGENT_LABELS[id]} — 請先設定 Provider、Model 與 API Key`
	                      : `${HEADER_AGENT_LABELS[id]} — 點擊設定 provider/model`
	                  }
	                  onClick={() => {
	                    if (!locked) setOpenAgent((current) => (current === id ? null : id));
	                  }}
	                >
	                  <span
	                    className={cn(
	                      "h-1.5 w-1.5 rounded-full",
	                      settingsLocked || !ready
                          ? "bg-gray-200"
                          : enabled
                            ? "bg-emerald-500"
                            : "bg-red-500",
	                    )}
	                  />
                  {HEADER_AGENT_LABELS[id]}
                </button>
                {openAgent === id && (
                  <AgentConfigPopover
                    agentId={id}
                    config={configQuery.data ?? null}
                    configuredProviders={configuredProviderMap}
                    disabled={saveConfigMut.isPending || settingsLocked}
                    onSave={(next) => saveConfigMut.mutate(next)}
                  />
                )}
              </div>
            );
          })}
        </div>

        <div className="flex items-center justify-end gap-2 justify-self-end">
          <button
            type="button"
            className={cn(
              "inline-flex h-7 w-7 items-center justify-center rounded-control border border-gray-200 bg-white text-slate-600 hover:bg-gray-50 hover:text-slate-900",
              darkMode && "border-slate-700 bg-slate-900 text-amber-200 hover:bg-slate-800 hover:text-amber-100",
            )}
            title={darkMode ? "切換亮色模式" : "切換深色模式"}
            aria-pressed={darkMode}
            onClick={() => {
              setOpenAgent(null);
              setLayoutOpen(false);
              toggleDarkMode();
            }}
          >
            {darkMode ? <Sun className="h-3.5 w-3.5" /> : <Moon className="h-3.5 w-3.5" />}
          </button>
          <div className="relative">
            <button
              type="button"
              className="inline-flex h-7 w-7 items-center justify-center rounded-control border border-gray-200 bg-white text-slate-600 hover:bg-gray-50 hover:text-slate-900"
              title="面板顯示"
              onClick={() => {
                setOpenAgent(null);
                setLayoutOpen((open) => !open);
              }}
            >
              <LayoutPanelLeft className="h-3.5 w-3.5" />
            </button>
            {layoutOpen && (
              <div className="absolute right-0 top-full z-40 mt-2 w-44 rounded-control border border-gray-200 bg-white p-2 shadow-lg">
                {[
                  ["references", "文件庫"],
                  ["workspace", "工作區"],
                  ["output", "產出物"],
                ].map(([id, label]) => {
                  const key = id as "references" | "workspace" | "output";
                  const on = visiblePanels[key];
                  return (
                    <button
                      key={id}
                      type="button"
                      className="flex w-full items-center justify-between rounded-control px-2 py-1.5 text-left text-xs text-slate-700 hover:bg-gray-50"
                      onClick={() => togglePanelVisibility(key)}
                    >
                      <span>{label}</span>
                      <span
                        className={cn(
                          "rounded-full px-2 py-0.5 text-[11px] font-medium",
                          on
                            ? "bg-emerald-50 text-emerald-700"
                            : "bg-gray-100 text-slate-400",
                        )}
                      >
                        {on ? "開啟" : "關閉"}
                      </span>
                    </button>
                  );
                })}
              </div>
            )}
          </div>
	          <div className="relative" ref={settingsRef}>
            <button
              type="button"
              className="inline-flex h-7 w-7 items-center justify-center rounded-control border border-gray-200 bg-white text-slate-600 hover:bg-gray-50 hover:text-slate-900"
              title="設定"
              onClick={() => {
                setOpenAgent(null);
                setSettingsOpen((open) => {
                  if (open) setConfirmAction(null);
                  return !open;
                });
              }}
            >
              <Settings className="h-3.5 w-3.5" />
            </button>
            {settingsOpen && (
              <div className="absolute right-0 top-full z-40 mt-2 w-80 rounded-control border border-gray-200 bg-white p-3 shadow-lg">
                <div className="border-b border-gray-100 pb-2">
                  <p className="text-sm font-semibold text-slate-900">設定</p>
                </div>
                <div className="mt-3 space-y-3">
                  <div>
                    <p className="text-xs font-semibold text-slate-700">API Key 設定</p>
                    {settingsLocked && (
                      <p className="mt-0.5 text-[11px] text-slate-400">
                        請先輸入啟動碼，才能修改 API Key。
                      </p>
                    )}
                  </div>
                  <ApiKeySettingsPanel
                    providers={configuredProviderMap}
                    savingProvider={
                      saveKeyMut.isPending
                        ? (saveKeyMut.variables?.provider ?? null)
                        : null
                    }
                    deletingProvider={
                      deleteKeyMut.isPending
                        ? (deleteKeyMut.variables?.provider ?? null)
                        : null
                    }
                    values={apiKeyValues}
                    messages={apiKeyMessages}
                    expandedProvider={expandedApiKeyProvider}
                    onToggle={(provider) =>
                      setExpandedApiKeyProvider((current) =>
                        current === provider ? null : provider,
                      )
                    }
                    onChange={(provider, value) => {
                      setApiKeyValues((current) => ({ ...current, [provider]: value }));
                      setApiKeyMessages((current) => ({
                        ...current,
                        [provider]: undefined,
                      }));
                    }}
                    onSave={(provider) =>
                      saveKeyMut.mutate({
                        provider,
                        apiKey: apiKeyValues[provider].trim(),
                      })
                    }
                    onDelete={(provider) => setConfirmAction({ type: "api-key", provider })}
                    locked={settingsLocked}
                  />
                  <ActivationCodePanel
                    activated={activated}
                    value={activationCode}
                    saving={activateMut.isPending || deactivateMut.isPending}
                    message={activationMessage}
                    onChange={(value) => {
                      setActivationCode(value);
                      setActivationMessage(undefined);
                    }}
                    onSubmit={() => {
                      if (!activationCode.trim() || activateMut.isPending) return;
                      activateMut.mutate();
                    }}
                    onDelete={() => setConfirmAction({ type: "activation" })}
                  />
                  {confirmAction && (
                    <ConfirmBox
                      title={
                        confirmAction.type === "api-key"
                          ? `移除 ${providerLabel(confirmAction.provider)} API Key？`
                          : "移除啟動碼？"
                      }
                      description={
                        confirmAction.type === "api-key"
                          ? "移除後，使用此 Provider 的 Agent 將無法呼叫模型，直到重新設定 API Key。"
                          : "移除後，網站會回到唯讀模式，需重新輸入啟動碼才能執行。"
                      }
                      loading={deleteKeyMut.isPending || deactivateMut.isPending}
                      onCancel={() => setConfirmAction(null)}
                      onConfirm={() => {
                        if (confirmAction.type === "api-key") {
                          deleteKeyMut.mutate({ provider: confirmAction.provider });
                        } else {
                          deactivateMut.mutate();
                        }
                      }}
                    />
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </header>
  );
}
