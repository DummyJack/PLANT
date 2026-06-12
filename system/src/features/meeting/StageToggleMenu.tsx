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
  { id: "init", label: "Init", keys: ["init"] },
  { id: "elicitation", label: "Elicitation", keys: ["elicitation"] },
  { id: "conflict_detection", label: "Conflict Detection", keys: ["conflict_detection"] },
  { id: "research_domain", label: "Research Domain", keys: ["research_domain"] },
  { id: "system_model", label: "System Model", keys: ["system_model"] },
  { id: "draft", label: "Draft", keys: ["default_update_draft", "general_update_draft"] },
  { id: "default_meeting", label: "Default Meeting", keys: ["default_formal_meeting", "default_update_draft"] },
  { id: "general_meeting", label: "General Meeting", keys: ["general_formal_meeting", "general_update_draft"] },
  { id: "DR", label: "Design Rationale", keys: ["DR"] },
  { id: "SRS", label: "SRS", keys: ["SRS"] },
];

function stageEnabled(
  config: PlantConfig | undefined,
  keys: string[],
  stageOverrides?: Record<string, boolean>,
) {
  const stage = config?.stage ?? {};
  return keys.every((key) => (stageOverrides?.[key] ?? stage[key]) === true);
}

function setStageKeys(config: PlantConfig, keys: string[], enabled: boolean): PlantConfig {
  const stage = { ...(config.stage ?? {}) };
  keys.forEach((key) => {
    stage[key] = enabled;
  });
  return { ...config, stage };
}

interface StageToggleMenuProps {
  disabled?: boolean;
  disabledReason?: string;
  stageOverrides?: Record<string, boolean>;
}

export function StageToggleMenu({
  disabled = false,
  disabledReason,
  stageOverrides,
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
    const nextEnabled = !stageEnabled(config, keys);
    saveMut.mutate(setStageKeys(config, keys, nextEnabled));
  };

  return (
    <div ref={rootRef} className="group relative">
      <button
        type="button"
        aria-label="階段"
        className={cn(
          "inline-flex h-7 w-7 items-center justify-center rounded-control border text-xs font-medium transition",
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
      </button>
      <span className="pointer-events-none absolute left-0 top-full z-40 mt-2 whitespace-nowrap rounded-control border border-gray-200 bg-white px-2 py-1 text-xs font-medium text-slate-700 opacity-0 shadow-md transition-opacity delay-500 duration-150 group-hover:opacity-100">
        階段
      </span>
      {open && (
        <div className="absolute left-0 top-full z-30 mt-2 w-64 rounded-card border border-gray-200 bg-white p-2 shadow-lg">
          {configQuery.isLoading ? (
            <p className="px-2 py-2 text-xs text-slate-400">讀取階段設定...</p>
          ) : (
            <div className="space-y-1">
              {STAGE_ROWS.map((row) => {
                const overridden = row.keys.some((key) => key in (stageOverrides ?? {}));
                const enabled = stageEnabled(configQuery.data, row.keys, stageOverrides);
                return (
                  <button
                    key={row.id}
                    type="button"
                    disabled={disabled || saveMut.isPending || !configQuery.data || overridden}
                    title={
                      disabled
                        ? (disabledReason ?? "執行中不可調整階段")
                        : overridden
                          ? "既有檔案已完成，此階段繼續專案時會跳過"
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
