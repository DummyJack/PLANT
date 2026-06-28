import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, LayoutPanelLeft, Settings } from "lucide-react";
import { fetchConfig, updateConfig } from "@/api/config";
import {
  activateCode,
  deactivateCode,
  deleteModelApiKey,
  fetchActivationStatus,
  fetchModelApiKeys,
  testModelApiKey,
  updateModelApiKey,
} from "@/api/secrets";
import {
  HEADER_AGENT_LABELS,
  HEADER_AGENT_ORDER,
  type AgentId,
} from "@/constants/agents";
import { useBootstrap } from "@/hooks/useBootstrap";
import { useActiveRun } from "@/hooks/useActiveRun";
import { useI18n } from "@/i18n";
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
  { provider: "gemini", label: "Gemini", envKey: "GEMINI_API_KEY" },
  { provider: "claude", label: "Claude", envKey: "ANTHROPIC_API_KEY" },
] as const;

const RECOMMENDED_MODELS: Record<string, string[]> = {
  openai: ["gpt-5.5", "gpt-4.1"],
  claude: ["claude-opus-4-8", "claude-sonnet-4-6"],
  gemini: ["gemini-3.5-flash", "gemini-3.1-pro-preview"],
};

type ApiKeyProvider = (typeof API_KEY_PROVIDERS)[number]["provider"];
type ApiKeyValidationStatus = "untested" | "valid" | "invalid";
type ApiKeyMessage = { tone: "success" | "error" | "pending"; text: string };
type InlineMessage = { tone: "success" | "error"; text: string };
type ConfirmAction =
  | { type: "api-key"; provider: ApiKeyProvider }
  | { type: "activation" };

const API_KEY_INLINE_INPUT_CLASS =
  "min-w-0 flex-1 rounded-control border border-gray-200 bg-white px-2 py-1.5 text-xs text-slate-700 placeholder:text-slate-400 focus:border-slate-400 focus:outline-none disabled:opacity-50";
const API_KEY_INLINE_BUTTON_CLASS =
  "shrink-0 rounded-control px-2.5 py-1 text-[11px] font-medium";

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
    gemini: rows.get("gemini") === true,
    claude: rows.get("claude") === true,
  };
}

function apiKeyValidationMap(
  providers?: Array<{ provider: string; configured: boolean; status?: string; valid?: boolean }>,
): Record<ApiKeyProvider, ApiKeyValidationStatus> {
  const rows = new Map(
    (providers ?? []).map((row) => [row.provider.toLowerCase(), row]),
  );
  const statusFor = (provider: ApiKeyProvider): ApiKeyValidationStatus => {
    const row = rows.get(provider);
    if (!row?.configured) return "untested";
    if (row.valid === true || row.status === "valid") return "valid";
    if (row.status === "invalid") return "invalid";
    return "untested";
  };
  return {
    openai: statusFor("openai"),
    gemini: statusFor("gemini"),
    claude: statusFor("claude"),
  };
}

function agentModelReady(
  config: PlantConfig | null | undefined,
  agentId: string,
  configuredProviders: Record<ApiKeyProvider, boolean>,
): boolean {
  void config;
  void agentId;
  return API_KEY_PROVIDERS.some((item) => configuredProviders[item.provider] === true);
}

function defaultProvider(
  configuredProviders: Record<ApiKeyProvider, boolean>,
): ApiKeyProvider | "" {
  return API_KEY_PROVIDERS.find((item) => configuredProviders[item.provider])?.provider ?? "";
}

function defaultModel(provider: string): string {
  return RECOMMENDED_MODELS[provider.toLowerCase()]?.[0] ?? "";
}

function unifiedModelProvider(
  config: PlantConfig | null | undefined,
  provider: ApiKeyProvider,
  model: string,
): boolean {
  const agentModels = config?.agent_models ?? {};
  const targetModel = model.trim();
  if (!targetModel) return false;
  return HEADER_AGENT_ORDER.every((agentId) => {
    const row = agentModels[agentId];
    return (
      String(row?.provider ?? "").trim().toLowerCase() === provider &&
      String(row?.model ?? "").trim() === targetModel
    );
  });
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
  defaultModels,
  disabled,
  onSave,
}: {
  agentId: AgentId;
  config: PlantConfig | null;
  configuredProviders: Record<ApiKeyProvider, boolean>;
  defaultModels: Record<ApiKeyProvider, string>;
  disabled?: boolean;
  onSave: (next: PlantConfig) => void;
}) {
  const { t } = useI18n();
  const enabledAgents = useUiStore((s) => s.enabledAgents);
  const modelConfig = config?.agent_models?.[agentId];
  const configuredProvider = (modelConfig?.provider ?? "").toLowerCase() as ApiKeyProvider;
  const fallbackProvider = defaultProvider(configuredProviders);
  const activeProvider = configuredProviders[configuredProvider]
    ? configuredProvider
    : fallbackProvider;
  const [provider, setProvider] = useState(activeProvider);
  const [model, setModel] = useState(activeProvider ? (modelConfig?.model ?? defaultModel(activeProvider)) : "");
  const [providerMenuOpen, setProviderMenuOpen] = useState(false);
  const [modelMenuOpen, setModelMenuOpen] = useState(false);
  const popoverRef = useRef<HTMLDivElement>(null);
  const on = enabledAgents[agentId] !== false;
  const providerOptions: ApiKeyProvider[] = API_KEY_PROVIDERS
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
    "gpt-5.5",
    "claude-opus-4-8",
    "gemini-3.5-flash",
  ])
    .filter((value) => value !== model && !recentModelOptions.includes(value))
    .slice(0, 4);
  const hasModelOptions = recentModelOptions.length > 0 || recommendedModelOptions.length > 0;

  useEffect(() => {
    const configured = (modelConfig?.provider ?? "").toLowerCase() as ApiKeyProvider;
    const fallback = defaultProvider(configuredProviders);
    const nextProvider = configuredProviders[configured] ? configured : fallback;
    setProvider(nextProvider);
    setModel(nextProvider ? (configured === nextProvider ? (modelConfig?.model ?? defaultModel(nextProvider)) : defaultModel(nextProvider)) : "");
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
                {provider ? displayProvider(provider) : t.selectedNone}
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
	                      setModel(defaultModel(value));
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
              placeholder={provider ? defaultModels[provider as ApiKeyProvider] : t.selectedNone}
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
                  title={t.recent}
                  options={recentModelOptions}
                  onSelect={(value) => {
                    setModel(value);
                    setModelMenuOpen(false);
                  }}
                />
                <div className="my-1 border-t border-gray-100" />
                {recommendedModelOptions.length > 0 && (
                  <ModelOptionGroup
                    title={t.recommended}
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
          {t.save}
        </button>
      </div>
    </div>
  );
}

function ApiKeySettingsPanel({
  providers,
  validation,
  config,
  savingProvider,
  deletingProvider,
  testingProvider,
  savingConfig,
  values,
  modelValues,
  messages,
  expandedProviders,
  onToggle,
  onChange,
  onModelChange,
  onSave,
  onDelete,
  onDefaultModelChange,
  onToggleUnifiedModel,
  locked,
}: {
  providers: Record<ApiKeyProvider, boolean>;
  validation: Record<ApiKeyProvider, ApiKeyValidationStatus>;
  config: PlantConfig | null;
  savingProvider: ApiKeyProvider | null;
  deletingProvider: ApiKeyProvider | null;
  testingProvider: ApiKeyProvider | null;
  savingConfig: boolean;
  values: Record<ApiKeyProvider, string>;
  modelValues: Record<ApiKeyProvider, string>;
  messages: Partial<Record<ApiKeyProvider, ApiKeyMessage>>;
  expandedProviders: Record<ApiKeyProvider, boolean>;
  onToggle: (provider: ApiKeyProvider) => void;
  onChange: (provider: ApiKeyProvider, value: string) => void;
  onModelChange: (provider: ApiKeyProvider, value: string) => void;
  onSave: (provider: ApiKeyProvider) => void;
  onDelete: (provider: ApiKeyProvider) => void;
  onDefaultModelChange: (provider: ApiKeyProvider, model: string) => void;
  onToggleUnifiedModel: (provider: ApiKeyProvider, model: string, enabled: boolean) => void;
  locked: boolean;
}) {
  const { t } = useI18n();
  const [modelMenuOpen, setModelMenuOpen] = useState<ApiKeyProvider | null>(null);
  return (
    <div className="space-y-1.5">
      {API_KEY_PROVIDERS.map((item) => {
        const configured = providers[item.provider];
        const status = configured ? validation[item.provider] : "untested";
        const expanded = expandedProviders[item.provider] === true;
        const saving = savingProvider === item.provider;
        const deleting = deletingProvider === item.provider;
        const testing = testingProvider === item.provider;
        const message = locked ? undefined : messages[item.provider];
        const valid = !locked && configured && status === "valid";
        const invalid = !locked && configured && status === "invalid";
        const modelValue = modelValues[item.provider];
        const placeholderModel = defaultModel(item.provider);
        const selectedModel = modelValue.trim() || placeholderModel;
        const unified = unifiedModelProvider(config, item.provider, selectedModel);
        const recommendedModelOptions = RECOMMENDED_MODELS[item.provider]
          .filter((value) => value !== modelValue)
          .slice(0, 2);
        const hasModelOptions = recommendedModelOptions.length > 0;
        const modelControlsDisabled = locked || savingConfig || !valid;
        const commitDefaultModel = () => {
          if (modelControlsDisabled) return;
          const next = modelValue.trim();
          if (!next) {
            onDefaultModelChange(item.provider, "");
            return;
          }
          if (next && next !== selectedModel) {
            onDefaultModelChange(item.provider, next);
          }
        };
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
                    valid ? "bg-emerald-500" : invalid ? "bg-amber-500" : "bg-gray-200",
                  )}
                />
                <span
                  className={cn(
                    "text-xs font-semibold",
                    valid ? "text-emerald-800" : invalid ? "text-amber-700" : "text-slate-700",
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
                    className={API_KEY_INLINE_INPUT_CLASS}
                    placeholder={t.providerApiKeyPlaceholder(item.label)}
                    value={values[item.provider]}
                    disabled={locked}
                    onChange={(event) => onChange(item.provider, event.target.value)}
                  />
                  <button
                    type="button"
                    disabled={locked || !values[item.provider].trim() || saving || deleting}
                    className={cn(
                      API_KEY_INLINE_BUTTON_CLASS,
                      "bg-slate-900 text-white hover:bg-slate-800 disabled:bg-gray-300 disabled:text-white",
                    )}
                    onClick={() => onSave(item.provider)}
                  >
                    {saving ? t.saving : t.save}
                  </button>
                  <button
                    type="button"
                    disabled={locked || !configured || saving || deleting || testing}
                    className={cn(
                      API_KEY_INLINE_BUTTON_CLASS,
                      "border border-red-100 bg-white text-red-600 hover:bg-red-50 disabled:border-gray-100 disabled:text-gray-300",
                    )}
                    onClick={() => onDelete(item.provider)}
                  >
                    {deleting ? t.removing : t.remove}
                  </button>
                </div>
                <div className="my-2 border-t border-gray-100" />
                <div className="flex items-center gap-2">
                  <div className="relative min-w-0 flex-1">
                    <input
                      className={cn(API_KEY_INLINE_INPUT_CLASS, "block w-full pr-7")}
                      value={modelValue}
                      disabled={modelControlsDisabled}
                      placeholder={t.defaultModel}
                      onBlur={commitDefaultModel}
                      onChange={(event) => onModelChange(item.provider, event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") {
                          event.preventDefault();
                          commitDefaultModel();
                          setModelMenuOpen(null);
                        }
                      }}
                    />
                    <button
                      type="button"
                      disabled={modelControlsDisabled || !hasModelOptions}
                      className="absolute right-1 top-1/2 flex h-6 w-6 -translate-y-1/2 items-center justify-center rounded text-slate-400 hover:bg-gray-50 hover:text-slate-700 disabled:opacity-30"
                      onMouseDown={(event) => event.preventDefault()}
                      onClick={() =>
                        setModelMenuOpen((current) =>
                          current === item.provider ? null : item.provider,
                        )
                      }
                    >
                      <ChevronDown className="h-3.5 w-3.5" />
                    </button>
                    {modelMenuOpen === item.provider && hasModelOptions && (
                      <div className="absolute left-0 right-0 top-full z-40 mt-1 max-h-52 overflow-y-auto rounded-control border border-gray-200 bg-white py-1 shadow-lg">
                        {recommendedModelOptions.length > 0 && (
                          <ModelOptionGroup
                            title={t.recommended}
                            options={recommendedModelOptions}
                            onSelect={(model) => {
                              onModelChange(item.provider, model);
                              onDefaultModelChange(item.provider, model);
                              setModelMenuOpen(null);
                            }}
                          />
                        )}
                      </div>
                    )}
                  </div>
                  <button
                    type="button"
                    disabled={modelControlsDisabled}
                    aria-pressed={unified}
                    className={cn(
                      API_KEY_INLINE_BUTTON_CLASS,
                      "border border-gray-200 bg-white text-slate-600 hover:bg-gray-50 disabled:opacity-40",
                    )}
                    onClick={() => onToggleUnifiedModel(item.provider, selectedModel, !unified)}
                  >
                    {t.switch}
                  </button>
                </div>
                {message && (
                  <p
                    className={cn(
                      "mt-1.5 text-[11px]",
                      message.tone === "success"
                        ? "text-emerald-700"
                        : message.tone === "pending"
                          ? "text-slate-500"
                          : "text-amber-700",
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
  const { t } = useI18n();
  return (
    <div className="border-t border-gray-100 pt-3">
      <div className="flex items-center gap-2">
        <input
          type="password"
          className="min-w-0 flex-1 rounded-control border border-gray-200 bg-white px-2 py-1.5 text-xs text-slate-700 focus:border-slate-400 focus:outline-none"
          placeholder={t.activationPlaceholder}
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
          {saving ? t.activating : t.activate}
        </button>
        {activated && (
          <button
            type="button"
            disabled={saving}
            className="shrink-0 rounded-control border border-red-100 bg-white px-2.5 py-1 text-[11px] font-medium text-red-600 hover:bg-red-50 disabled:border-gray-100 disabled:text-gray-300"
            onClick={onDelete}
          >
            {t.remove}
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
  confirmLabel,
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
  const { t } = useI18n();
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
            {t.cancel}
          </button>
          <button
            type="button"
            disabled={loading}
            className="rounded-control bg-red-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-50"
            onClick={onConfirm}
          >
            {loading ? t.processing : (confirmLabel ?? t.confirm)}
          </button>
        </div>
      </div>
    </div>
  );
}

export function HeaderBar() {
  const { language, t } = useI18n();
  const queryClient = useQueryClient();
  const bootstrap = useBootstrap();
  const projectId = useUiStore((s) => s.activeProjectId);
  const enabledAgents = useUiStore((s) => s.enabledAgents);
  const visiblePanels = useUiStore((s) => s.visiblePanels);
  const darkMode = useUiStore((s) => s.darkMode);
  const setEnabledAgents = useUiStore((s) => s.setEnabledAgents);
  const togglePanelVisibility = useUiStore((s) => s.togglePanelVisibility);
  const toggleDarkMode = useUiStore((s) => s.toggleDarkMode);
  const setLanguage = useUiStore((s) => s.setLanguage);
  const setCanWrite = useUiStore((s) => s.setCanWrite);
  const pushNotice = useNoticeStore((s) => s.pushNotice);
  const { activeRun } = useActiveRun(projectId);
  const [openAgent, setOpenAgent] = useState<AgentId | null>(null);
  const [layoutOpen, setLayoutOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [expandedApiKeyProviders, setExpandedApiKeyProviders] =
    useState<Record<ApiKeyProvider, boolean>>({
      openai: false,
      gemini: false,
      claude: false,
    });
  const [apiKeyValues, setApiKeyValues] = useState<Record<ApiKeyProvider, string>>({
    openai: "",
    gemini: "",
    claude: "",
  });
  const [defaultModelValues, setDefaultModelValues] = useState<Record<ApiKeyProvider, string>>({
    openai: "",
    gemini: "",
    claude: "",
  });
  const [dirtyDefaultModels, setDirtyDefaultModels] = useState<Record<ApiKeyProvider, boolean>>({
    openai: false,
    gemini: false,
    claude: false,
  });
  const [apiKeyMessages, setApiKeyMessages] = useState<
    Partial<Record<ApiKeyProvider, ApiKeyMessage>>
  >({});
  const [apiKeyValidation, setApiKeyValidation] = useState<Record<ApiKeyProvider, ApiKeyValidationStatus>>({
    openai: "untested",
    gemini: "untested",
    claude: "untested",
  });
  const [testingAllKeys, setTestingAllKeys] = useState(false);
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
        title: t.saved,
        message: t.savedAgentModel,
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

  const configuredProviderMap = useMemo(
    () => apiKeyConfiguredMap(keyQuery.data?.providers),
    [keyQuery.data?.providers],
  );
  const savedApiKeyValidation = useMemo(
    () => apiKeyValidationMap(keyQuery.data?.providers),
    [keyQuery.data?.providers],
  );

  const saveKeyMut = useMutation({
    mutationFn: ({ provider, apiKey }: { provider: ApiKeyProvider; apiKey: string }) =>
      updateModelApiKey(provider, apiKey),
    onMutate: (variables) => {
      setApiKeyValidation((current) => ({
        ...current,
        [variables.provider]: "untested",
      }));
    },
    onSuccess: (_result, variables) => {
      queryClient.setQueryData(
        ["model-api-keys"],
        (current: Awaited<ReturnType<typeof fetchModelApiKeys>> | undefined) => ({
          providers: (current?.providers ?? API_KEY_PROVIDERS.map((item) => ({
            provider: item.provider,
            env_key: item.envKey,
            configured: false,
          }))).map((row) =>
            row.provider.toLowerCase() === variables.provider
              ? {
                  ...row,
                  configured: true,
                  status: "untested",
                  valid: false,
                  error: null,
                  tested_at: null,
                }
              : row,
          ),
        }),
      );
      setApiKeyValues((current) => ({ ...current, [variables.provider]: "" }));
      setApiKeyMessages((current) => ({ ...current, [variables.provider]: undefined }));
      queryClient.invalidateQueries({ queryKey: ["model-api-keys"] });
      queryClient.invalidateQueries({ queryKey: ["bootstrap"] });
      testKeyMut.mutate({ provider: variables.provider });
    },
    onError: (error, variables) => {
      setApiKeyMessages((current) => ({
        ...current,
        [variables.provider]: {
          tone: "error",
          text: errorMessage(error, t.saveFailed),
        },
      }));
    },
  });

  const testKeyMut = useMutation({
    mutationFn: ({ provider }: { provider: ApiKeyProvider }) => testModelApiKey(provider),
    onMutate: (variables) => {
      setApiKeyMessages((current) => ({
        ...current,
        [variables.provider]: {
          tone: "pending",
          text: t.testingApiKey,
        },
      }));
    },
    onSuccess: (result, variables) => {
      const valid = result.valid === true;
      queryClient.setQueryData(
        ["model-api-keys"],
        (current: Awaited<ReturnType<typeof fetchModelApiKeys>> | undefined) => ({
          providers: (current?.providers ?? API_KEY_PROVIDERS.map((item) => ({
            provider: item.provider,
            env_key: item.envKey,
            configured: false,
          }))).map((row) =>
            row.provider.toLowerCase() === variables.provider
              ? {
                  ...row,
                  configured: true,
                  status: valid ? "valid" : "invalid",
                  valid,
                  error: result.error ?? null,
                  tested_at: result.tested_at ?? null,
                }
              : row,
          ),
        }),
      );
      setApiKeyValidation((current) => ({
        ...current,
        [variables.provider]: valid ? "valid" : "invalid",
      }));
      if (!valid) {
        setExpandedApiKeyProviders((current) => ({
          ...current,
          [variables.provider]: true,
        }));
      }
      setApiKeyMessages((current) => ({
        ...current,
        [variables.provider]: {
          tone: valid ? "success" : "error",
          text: valid ? t.testPassed : t.invalidApiKey,
        },
      }));
      queryClient.invalidateQueries({ queryKey: ["bootstrap"] });
    },
    onError: (_error, variables) => {
      setApiKeyValidation((current) => ({
        ...current,
        [variables.provider]: "invalid",
      }));
      setExpandedApiKeyProviders((current) => ({
        ...current,
        [variables.provider]: true,
      }));
      setApiKeyMessages((current) => ({
        ...current,
        [variables.provider]: {
          tone: "error",
          text: t.invalidApiKey,
        },
      }));
      queryClient.invalidateQueries({ queryKey: ["bootstrap"] });
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
            env_key: item.envKey,
            configured: false,
          }))).map((row) =>
            row.provider.toLowerCase() === variables.provider
              ? {
                  ...row,
                  configured: false,
                  status: "untested",
                  valid: false,
                  error: null,
                  tested_at: null,
                }
              : row,
          ),
        }),
      );
      setApiKeyValues((current) => ({ ...current, [variables.provider]: "" }));
      setApiKeyMessages((current) => ({
        ...current,
        [variables.provider]: {
          tone: "success",
          text: t.successRemoved,
        },
      }));
      setApiKeyValidation((current) => ({
        ...current,
        [variables.provider]: "untested",
      }));
      queryClient.invalidateQueries({ queryKey: ["model-api-keys"] });
      queryClient.invalidateQueries({ queryKey: ["bootstrap"] });
    },
    onError: (error, variables) => {
      setApiKeyMessages((current) => ({
        ...current,
        [variables.provider]: {
          tone: "error",
          text: errorMessage(error, t.removeFailed ?? "Remove failed"),
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
      setActivationMessage({ tone: "success", text: t.successActivated });
      queryClient.invalidateQueries({ queryKey: ["activation-status"] });
    },
    onError: (error) => {
      setActivationMessage({
        tone: "error",
        text: errorMessage(error, t.invalidActivationCode),
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
      setActivationMessage({ tone: "success", text: t.successRemoved });
      queryClient.invalidateQueries({ queryKey: ["activation-status"] });
    },
    onError: (error) => {
      setActivationMessage({
        tone: "error",
        text: errorMessage(error, t.removeFailed ?? "Remove failed"),
      });
    },
  });

  useEffect(() => {
    const next = !!activationQuery.data?.activated;
    setActivated(next);
    setCanWrite(next);
  }, [activationQuery.data?.activated, setCanWrite]);

  useEffect(() => {
    if (!activated) {
      setApiKeyValidation({
        openai: "untested",
        claude: "untested",
        gemini: "untested",
      });
      setApiKeyMessages({});
      return;
    }
    setApiKeyValidation(savedApiKeyValidation);
    setApiKeyMessages((current) => {
      const next = { ...current };
      for (const item of API_KEY_PROVIDERS) {
        if (savedApiKeyValidation[item.provider] === "invalid") {
          next[item.provider] = {
            tone: "error",
            text: t.invalidApiKey,
          };
        } else if (current[item.provider]?.text === t.invalidApiKey || current[item.provider]?.text === "無效的 API Key") {
          next[item.provider] = undefined;
        }
      }
      return next;
    });
  }, [activated, savedApiKeyValidation]);

  useEffect(() => {
    if (!activated) return;
    setExpandedApiKeyProviders((current) => {
      const next = { ...current };
      for (const item of API_KEY_PROVIDERS) {
        if (savedApiKeyValidation[item.provider] === "invalid") {
          next[item.provider] = true;
        }
      }
      return next;
    });
  }, [activated, savedApiKeyValidation]);

  useEffect(() => {
    const timers = Object.entries(apiKeyMessages).map(([provider, message]) => {
      if (!message || message.tone !== "success") return null;
      return window.setTimeout(() => {
        setApiKeyMessages((current) => ({
          ...current,
          [provider as ApiKeyProvider]: undefined,
        }));
      }, 1000);
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

  useEffect(() => {
    setDefaultModelValues((current) => ({
      openai: dirtyDefaultModels.openai ? current.openai : "",
      claude: dirtyDefaultModels.claude ? current.claude : "",
      gemini: dirtyDefaultModels.gemini ? current.gemini : "",
    }));
  }, [dirtyDefaultModels]);

  const apiOk = bootstrap.data?.api_keys.valid !== false;
  const runActive = !!activeRun && ACTIVE_STATUSES.has(activeRun.status);
  const settingsLocked = !activated;
  const usableProviderMap = useMemo(
    () => ({
      openai: configuredProviderMap.openai && apiKeyValidation.openai === "valid",
      gemini: configuredProviderMap.gemini && apiKeyValidation.gemini === "valid",
      claude: configuredProviderMap.claude && apiKeyValidation.claude === "valid",
    }),
    [apiKeyValidation, configuredProviderMap],
  );
  const configuredApiKeyProviders = API_KEY_PROVIDERS
    .map((item) => item.provider)
    .filter((provider) => configuredProviderMap[provider]);
  const currentTestingProvider = testKeyMut.isPending
    ? (testKeyMut.variables?.provider ?? null)
    : null;
  const testConfiguredApiKeys = async () => {
    if (settingsLocked || testingAllKeys || testKeyMut.isPending) return;
    const providersToTest = configuredApiKeyProviders;
    if (providersToTest.length === 0) return;
    setTestingAllKeys(true);
    try {
      for (const provider of providersToTest) {
        await testKeyMut.mutateAsync({ provider });
      }
    } finally {
      setTestingAllKeys(false);
    }
  };
  const saveProviderDefaultModel = (provider: ApiKeyProvider, model: string) => {
    setDefaultModelValues((current) => ({ ...current, [provider]: model }));
    setDirtyDefaultModels((current) => ({ ...current, [provider]: false }));
  };
  const toggleUnifiedProviderModel = (
    provider: ApiKeyProvider,
    model: string,
    _enabled: boolean,
  ) => {
    const config = configQuery.data;
    if (!config || settingsLocked || saveConfigMut.isPending) return;
    const agent_models = { ...(config.agent_models ?? {}) };
    for (const agentId of HEADER_AGENT_ORDER) {
      agent_models[agentId] = {
        ...(agent_models[agentId] ?? {}),
        provider,
        model,
      } as AgentModelConfig;
    }
    agent_models.default = {
      ...(agent_models.default ?? {}),
      provider,
      model,
    } as AgentModelConfig;
    saveConfigMut.mutate({
      ...config,
      agent_models,
    });
  };

  return (
    <header className="shrink-0 bg-slate-50">
      {!apiOk && (
        <div className="bg-amber-50 px-4 py-1.5 text-xs text-amber-800">
          {t.apiConfigError}：{bootstrap.data?.api_keys.error ?? t.checkEnv}
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
	            const ready = agentModelReady(configQuery.data, id, usableProviderMap);
		            const locked = runActive || settingsLocked || !ready;
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
                    runActive
                      ? t.agentRunningLocked(HEADER_AGENT_LABELS[id])
                      : settingsLocked
                        ? t.agentSettingsLocked(HEADER_AGENT_LABELS[id])
                        : !ready
                          ? t.agentApiKeyRequired(HEADER_AGENT_LABELS[id])
                          : t.agentConfigTitle(HEADER_AGENT_LABELS[id])
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
	                    configuredProviders={usableProviderMap}
                    defaultModels={defaultModelValues}
                    disabled={saveConfigMut.isPending || settingsLocked}
                    onSave={(next) => saveConfigMut.mutate(next)}
                  />
                )}
              </div>
            );
          })}
        </div>

        <div className="flex items-center justify-end gap-2 justify-self-end">
          <div className="relative">
            <button
              type="button"
              className="inline-flex h-7 w-7 items-center justify-center rounded-control border border-gray-200 bg-white text-slate-600 hover:bg-gray-50 hover:text-slate-900"
              title={t.layout}
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
                  ["references", t.references],
                  ["workspace", t.workspace],
                  ["output", t.output],
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
                          {on ? t.on : t.off}
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
              title={t.settings}
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
                  <p className="text-sm font-semibold text-slate-900">{t.settingsTitle}</p>
                </div>
                <div className="mt-3 space-y-3">
                  <div>
                    <div className="flex items-center justify-between gap-2">
                      <p className="text-xs font-semibold text-slate-700">{t.apiKey}</p>
                      <button
                        type="button"
                        disabled={
                          settingsLocked ||
                          testingAllKeys ||
                          testKeyMut.isPending ||
                          configuredApiKeyProviders.length === 0
                        }
                        className="shrink-0 rounded-control border border-gray-200 bg-white px-2.5 py-1 text-[11px] font-medium text-slate-600 hover:bg-gray-50 disabled:border-gray-100 disabled:text-gray-300"
                        onClick={testConfiguredApiKeys}
                      >
                        {testingAllKeys ? t.testing : t.test}
                      </button>
                    </div>
                    {settingsLocked && (
                      <p className="mt-0.5 text-[11px] text-slate-400">
                        {t.apiKeyLockedHint}
                      </p>
                    )}
                  </div>
                  <ApiKeySettingsPanel
                    providers={configuredProviderMap}
                    validation={apiKeyValidation}
                    config={configQuery.data ?? null}
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
                    testingProvider={currentTestingProvider}
                    savingConfig={saveConfigMut.isPending}
                    values={apiKeyValues}
                    modelValues={defaultModelValues}
                    messages={apiKeyMessages}
                    expandedProviders={expandedApiKeyProviders}
                    onToggle={(provider) =>
                      setExpandedApiKeyProviders((current) => ({
                        ...current,
                        [provider]: !current[provider],
                      }))
                    }
                    onChange={(provider, value) => {
                      setApiKeyValues((current) => ({ ...current, [provider]: value }));
                      setApiKeyMessages((current) => ({
                        ...current,
                        [provider]: undefined,
                      }));
                    }}
                    onModelChange={(provider, value) =>
                      {
                        setDefaultModelValues((current) => ({
                          ...current,
                          [provider]: value,
                        }));
                        setDirtyDefaultModels((current) => ({
                          ...current,
                          [provider]: true,
                        }));
                      }
                    }
                    onSave={(provider) =>
                      saveKeyMut.mutate({
                        provider,
                        apiKey: apiKeyValues[provider].trim(),
                      })
                    }
                    onDelete={(provider) => setConfirmAction({ type: "api-key", provider })}
                    onDefaultModelChange={saveProviderDefaultModel}
                    onToggleUnifiedModel={toggleUnifiedProviderModel}
                    locked={settingsLocked}
                  />
                  <div className="border-t border-gray-100 pt-3 pb-3">
                    <div className="flex items-center justify-between gap-3">
                      <p className="text-xs font-semibold text-slate-700">{t.darkMode}</p>
                      <button
                        type="button"
                        className={cn(
                          "relative inline-flex h-6 w-14 shrink-0 items-center rounded-full border transition-colors",
                          darkMode
                            ? "border-[var(--accent)] bg-[var(--accent)]"
                            : "border-gray-200 bg-gray-100 text-slate-500",
                        )}
                        role="switch"
                        aria-checked={darkMode}
                        title={darkMode ? t.lightModeTitle : t.darkModeTitle}
                        onClick={() => {
                          setOpenAgent(null);
                          setLayoutOpen(false);
                          toggleDarkMode();
                        }}
                      >
                        <span
                          className={cn(
                            "pointer-events-none absolute text-[11px] font-semibold leading-none",
                            darkMode
                              ? "left-1.5 text-slate-950"
                              : "right-1.5 text-slate-500",
                          )}
                        >
                          {darkMode ? t.on : t.off}
                        </span>
                        <span
                          className={cn(
                            "h-5 w-5 rounded-full bg-white shadow-sm transition-transform",
                            darkMode ? "translate-x-8" : "translate-x-0.5",
                          )}
                        />
                      </button>
                    </div>
                    <div className="mt-3 flex items-center justify-between gap-3">
                      <p className="text-xs font-semibold text-slate-700">{t.language}</p>
                      <div className="inline-flex rounded-control border border-gray-200 bg-gray-100 p-0.5">
                        {[
                          ["zh", t.chinese],
                          ["en", t.english],
                        ].map(([value, label]) => (
                          <button
                            key={value}
                            type="button"
                            className={cn(
                              "rounded-[6px] px-2 py-0.5 text-[11px] font-semibold transition-colors",
                              language === value
                                ? "bg-white text-slate-900 shadow-sm"
                                : "text-slate-500 hover:text-slate-700",
                            )}
                            onClick={() => setLanguage(value as "zh" | "en")}
                          >
                            {label}
                          </button>
                        ))}
                      </div>
                    </div>
                  </div>
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
                          ? t.removeApiKeyTitle(providerLabel(confirmAction.provider))
                          : t.removeActivationTitle
                      }
                      description={
                        confirmAction.type === "api-key"
                          ? t.removeApiKeyDescription
                          : t.removeActivationDescription
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
