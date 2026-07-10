import { RotateCcw, X } from "lucide-react";
import { UI_TEXT, useI18n } from "@/i18n";
import { useUiStore } from "@/stores/uiStore";
import type { RunCheckpoint } from "@/types/api";
import { cn } from "@/utils/cn";

function stageLabel(stageId?: string) {
  const key = String(stageId || "").trim();
  const t = UI_TEXT[useUiStore.getState().language];
  const labels = t.checkpointStageLabels as Record<string, string>;
  return (labels[key] ?? key) || t.previousStage;
}

function cleanupLabel(paths?: string[]) {
  const t = UI_TEXT[useUiStore.getState().language];
  const rows = paths ?? [];
  if (!rows.length) return t.cleanupUnfinishedOutputs;
  if (rows.some((path) => /\/MoM\/|artifact\/MoM\//i.test(path))) {
    return t.cleanupMomPreview;
  }
  if (rows.some((path) => /draft_v\d+\.(?:md|html)$/i.test(path))) {
    return t.cleanupDraftPreview;
  }
  if (rows.some((path) => /(?:srs|design_rationale)\.(?:md|html)$/i.test(path))) {
    return t.cleanupSrsPreview;
  }
  if (rows.some((path) => /^results(?:\/|$)/i.test(path))) {
    return t.cleanupResultsPreview;
  }
  return t.cleanupOutputCount(rows.length);
}

function stageLabelText(stageId: string | undefined, t: ReturnType<typeof useI18n>["t"]) {
  const key = String(stageId || "").trim();
  const labels = t.checkpointStageLabels as Record<string, string>;
  return (labels[key] ?? key) || t.previousStage;
}

function cleanupLabelText(paths: string[] | undefined, t: ReturnType<typeof useI18n>["t"]) {
  const rows = paths ?? [];
  if (!rows.length) return t.cleanupUnfinishedOutputs;
  if (rows.some((path) => /\/MoM\/|artifact\/MoM\//i.test(path))) {
    return t.cleanupMomPreview;
  }
  if (rows.some((path) => /draft_v\d+\.(?:md|html)$/i.test(path))) {
    return t.cleanupDraftPreview;
  }
  if (rows.some((path) => /(?:srs|design_rationale)\.(?:md|html)$/i.test(path))) {
    return t.cleanupSrsPreview;
  }
  if (rows.some((path) => /^results(?:\/|$)/i.test(path))) {
    return t.cleanupResultsPreview;
  }
  return t.cleanupOutputCount(rows.length);
}

export function checkpointStageLabel(checkpoint?: RunCheckpoint | null) {
  return stageLabel(checkpoint?.stage_id);
}

export function checkpointCleanupLabel(checkpoint?: RunCheckpoint | null) {
  return cleanupLabel(checkpoint?.dirty_outputs);
}

export function RunCheckpointNotice({
  checkpoint,
  compact = false,
  onDismiss,
}: {
  checkpoint?: RunCheckpoint | null;
  compact?: boolean;
  onDismiss?: () => void;
}) {
  const { t } = useI18n();
  if (!checkpoint) return null;
  const failed = checkpoint.status === "failed";
  const stage = stageLabelText(checkpoint.stage_id, t);
  const title = failed ? t.checkpointFailedTitle(stage) : t.checkpointStoppedTitle(stage);
  const detail = t.checkpointDetail(cleanupLabelText(checkpoint.dirty_outputs, t));

  return (
    <div
      className={cn(
        "mb-2 flex items-start gap-2 rounded-control border border-amber-200 bg-amber-50 px-3 py-2 text-amber-950",
        compact && "px-2",
      )}
      title={detail}
    >
      <RotateCcw className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
      <div className="min-w-0 flex-1">
        <div className="truncate text-xs font-semibold">{title}</div>
        <div className="truncate text-[11px] text-amber-800">{detail}</div>
      </div>
      {onDismiss && (
        <button
          type="button"
          className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-amber-700 hover:bg-amber-100 hover:text-amber-950"
          aria-label={t.closeRecoveryNotice}
          title={t.closeNotice}
          onClick={onDismiss}
        >
          <X className="h-3.5 w-3.5" />
        </button>
      )}
    </div>
  );
}
