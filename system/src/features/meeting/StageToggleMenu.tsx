import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Layers } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { fetchConfig, updateConfig } from "@/api/config";
import { useNoticeStore } from "@/stores/noticeStore";
import type { PlantConfig } from "@/types/api";
import { cn } from "@/utils/cn";
import { errorMessage } from "@/utils/errorMessage";

const STAGE_ROWS: Array<{
  id: string;
  label: string;
  keys: string[];
}> = [
  { id: "init", label: "初始階段", keys: ["init"] },
  { id: "elicitation", label: "需求擷取", keys: ["elicitation"] },
  { id: "conflict_detection", label: "衝突辨識", keys: ["conflict_detection"] },
  { id: "research_domain", label: "領域研究", keys: ["research_domain"] },
  { id: "system_model", label: "系統模型", keys: ["system_model"] },
  { id: "draft", label: "草稿化", keys: ["draft"] },
  { id: "default_meeting", label: "預設會議", keys: ["default_formal_meeting", "default_update_draft"] },
  { id: "general_meeting", label: "一般會議", keys: ["general_formal_meeting", "general_update_draft"] },
  { id: "DR", label: "Design Rationale", keys: ["DR"] },
  { id: "SRS", label: "SRS", keys: ["SRS"] },
];

const FORCE_REGENERATE_KEYS = new Set([
  "elicitation",
  "conflict_detection",
  "research_domain",
  "system_model",
  "draft",
]);

function stageEnabled(
  config: PlantConfig | undefined,
  keys: string[],
  stageOverrides?: Record<string, boolean>,
) {
  const stage = config?.stage ?? {};
  const force = (config?.force_regenerate_outputs as Record<string, boolean> | undefined) ?? {};
  return keys.every((key) => {
    if (force[key] === true) return true;
    if (stage[key] === false) return false;
    return (stageOverrides?.[key] ?? stage[key]) === true;
  });
}

function setStageKeys(config: PlantConfig, keys: string[], enabled: boolean): PlantConfig {
  const stage = { ...(config.stage ?? {}) };
  keys.forEach((key) => {
    stage[key] = enabled;
  });
  return { ...config, stage };
}

function setForceRegenerateOutputs(
  config: PlantConfig,
  keys: string[],
  enabled: boolean,
  existingOutputs?: Record<string, boolean | undefined>,
  stageOverrides?: Record<string, boolean>,
): PlantConfig {
  const force = { ...((config.force_regenerate_outputs as Record<string, boolean> | undefined) ?? {}) };
  for (const key of keys) {
    if (
      enabled &&
      FORCE_REGENERATE_KEYS.has(key) &&
      (existingOutputs?.[key] || stageOverrides?.[key] === false)
    ) {
      force[key] = true;
    }
    if (!enabled) {
      delete force[key];
    }
  }
  if (!Object.keys(force).length) {
    const rest = { ...config };
    delete rest.force_regenerate_outputs;
    return rest;
  }
  return { ...config, force_regenerate_outputs: force };
}

interface StageToggleMenuProps {
  disabled?: boolean;
  disabledReason?: string;
  stageOverrides?: Record<string, boolean>;
  existingOutputs?: {
    [key: string]: boolean | undefined;
  };
  compact?: boolean;
  enabledRowIds?: string[];
}

export function StageToggleMenu({
  disabled = false,
  disabledReason,
  stageOverrides,
  existingOutputs,
  compact = false,
  enabledRowIds,
}: StageToggleMenuProps) {
  const queryClient = useQueryClient();
  const pushNotice = useNoticeStore((s) => s.pushNotice);
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  const configQuery = useQuery({
    queryKey: ["config"],
    queryFn: async () => (await fetchConfig()).config,
    enabled: open,
  });

  const saveMut = useMutation({
    mutationFn: updateConfig,
    onSuccess: ({ config }) => {
      queryClient.setQueryData(["config"], config);
      queryClient.invalidateQueries({ queryKey: ["config"] });
      queryClient.invalidateQueries({ queryKey: ["bootstrap"] });
      pushNotice({
        tone: "success",
        title: "已儲存",
        message: "階段設定已更新",
      });
    },
    onError: (error) => {
      pushNotice({
        tone: "error",
        title: "儲存失敗",
        message: errorMessage(error, "無法更新階段設定"),
      });
    },
  });

  useEffect(() => {
    if (!open) return;
    const handler = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const toggleStage = (keys: string[]) => {
    if (disabled) return;
    const config = configQuery.data;
    if (!config) return;
    const nextEnabled = !stageEnabled(config, keys, stageOverrides);
    const nextConfig = setForceRegenerateOutputs(
      setStageKeys(config, keys, nextEnabled),
      keys,
      nextEnabled,
      existingOutputs,
      stageOverrides,
    );
    saveMut.mutate(nextConfig);
  };
  const rowEnabledIds = enabledRowIds?.length ? new Set(enabledRowIds) : null;

  return (
    <div ref={rootRef} className="group relative">
      <button
        type="button"
        aria-label="階段"
        className={cn(
          "inline-flex h-7 items-center gap-1.5 rounded-control border text-xs font-medium transition",
          compact ? "w-7 justify-center px-0" : "px-2.5",
          disabled && !open
            ? "border-gray-200 bg-gray-50 text-slate-400 hover:border-slate-300 hover:text-slate-600"
            : open
            ? "border-slate-300 bg-slate-50 text-slate-800"
            : "border-gray-200 bg-white text-slate-600 hover:border-slate-300 hover:text-slate-800",
        )}
        title={disabled ? (disabledReason ?? "執行中只能查看階段") : "階段"}
        onClick={() => {
          setOpen((v) => !v);
        }}
      >
        <Layers className="h-3.5 w-3.5" />
        <span className={cn(compact && "sr-only")}>階段</span>
      </button>
      {compact && (
        <span className="pointer-events-none absolute left-0 top-full z-40 mt-2 whitespace-nowrap rounded-control border border-gray-200 bg-white px-2 py-1 text-xs font-medium text-slate-700 opacity-0 shadow-md transition-opacity delay-500 duration-150 group-hover:opacity-100">
          階段
        </span>
      )}
      {open && (
        <div className="absolute left-0 top-full z-30 mt-2 w-64 rounded-card border border-gray-200 bg-white p-2 shadow-lg">
          {configQuery.isLoading ? (
            <p className="px-2 py-2 text-xs text-slate-400">讀取階段設定...</p>
          ) : (
            <div className="space-y-1">
              {STAGE_ROWS.map((row) => {
                const enabled = stageEnabled(configQuery.data, row.keys, stageOverrides);
                const completed = row.keys.some((key) => (stageOverrides ?? {})[key] === false);
                const forceSupported = row.keys.some((key) => FORCE_REGENERATE_KEYS.has(key));
                const rowDisabled = !!rowEnabledIds && !rowEnabledIds.has(row.id);
                return (
                  <button
                    key={row.id}
                    type="button"
                    disabled={disabled || saveMut.isPending || !configQuery.data || rowDisabled}
                    title={
                      rowDisabled
                        ? "執行完成後只能重新執行一般會議、DR、SRS"
                        : disabled
                        ? (disabledReason ?? "執行中不可調整階段")
                        : completed && !enabled && forceSupported
                          ? "已完成；開啟後下次執行會重新產生"
                          : undefined
                    }
                    className="flex w-full items-center justify-between rounded-control px-2 py-1.5 text-left text-xs text-slate-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
                    onClick={() => toggleStage(row.keys)}
                  >
                    <span>{row.label}</span>
                    <span
                      className={cn(
                        "rounded-full px-2 py-0.5 text-[11px] font-medium",
                        enabled
                          ? "bg-emerald-50 text-emerald-700"
                          : "bg-gray-100 text-slate-400",
                      )}
                    >
                      {enabled ? "開啟" : "關閉"}
                    </span>
                  </button>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
