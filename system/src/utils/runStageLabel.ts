import { UI_TEXT } from "@/i18n";
import { useUiStore } from "@/stores/uiStore";

export function runStageActivityLabel(stageValue: string | null | undefined): string | null {
  const stage = String(stageValue || "").trim();
  if (!stage) return null;
  const t = UI_TEXT[useUiStore.getState().language];
  if (/SRS|software.requirements|規格/i.test(stage)) return t.generatingSpecDocument;
  if (/DR|design.rationale|design_rationale|設計緣由/i.test(stage)) {
    return t.generatingDesignRationale;
  }
  if (/document|document_generation|規格化/i.test(stage)) return t.generatingSpecDocument;
  if (/meeting|會議|開會/i.test(stage)) return t.elicitationMeeting;
  return null;
}
