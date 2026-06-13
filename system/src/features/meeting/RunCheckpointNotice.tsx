import { RotateCcw, X } from "lucide-react";
import type { RunCheckpoint } from "@/types/api";
import { cn } from "@/utils/cn";

const STAGE_LABELS: Record<string, string> = {
  formal_meeting: "正式會議",
  meeting_issue_proposal_review: "正式會議",
  draft: "草稿化",
  document_generation: "規格化",
  export: "匯出",
  init: "初始階段",
  elicitation: "需求擷取",
  conflict_detection: "需求衝突辨識",
  research_domain: "領域研究",
  system_model: "系統模型",
};

function stageLabel(stageId?: string) {
  const key = String(stageId || "").trim();
  return (STAGE_LABELS[key] ?? key) || "上一階段";
}

function cleanupLabel(paths?: string[]) {
  const rows = paths ?? [];
  if (!rows.length) return "將清理此階段可能未完成的產出";
  if (rows.some((path) => /\/MoM\/|artifact\/MoM\//i.test(path))) {
    return "將清理最新 MoM 與對應預覽";
  }
  if (rows.some((path) => /draft_v\d+\.(?:md|html)$/i.test(path))) {
    return "將清理最新草稿與預覽";
  }
  if (rows.some((path) => /(?:srs|design_rationale)\.(?:md|html)$/i.test(path))) {
    return "將清理 SRS、Design Rationale 與預覽";
  }
  if (rows.some((path) => /^results(?:\/|$)/i.test(path))) {
    return "將清理 results 預覽輸出";
  }
  return `將清理 ${rows.length} 個可能未完成的產出`;
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
  if (!checkpoint) return null;
  const failed = checkpoint.status === "failed";
  const title = `上次執行在「${stageLabel(checkpoint.stage_id)}」${failed ? "失敗" : "停止"}，繼續時會重跑此步驟`;
  const detail = `${cleanupLabel(checkpoint.dirty_outputs)}，按「繼續」會先清理再執行。`;

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
          aria-label="關閉恢復提示"
          title="關閉提示"
          onClick={onDismiss}
        >
          <X className="h-3.5 w-3.5" />
        </button>
      )}
    </div>
  );
}
