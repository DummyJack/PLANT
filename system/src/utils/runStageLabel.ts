export function runStageActivityLabel(stageValue: string | null | undefined): string | null {
  const stage = String(stageValue || "").trim();
  if (!stage) return null;
  if (/SRS|software.requirements|規格/i.test(stage)) return "SRS 生成中";
  if (/DR|design.rationale|design_rationale|設計緣由/i.test(stage)) {
    return "Design Rationale 生成中";
  }
  if (/document|document_generation|規格化/i.test(stage)) return "文件生成中";
  if (/meeting|會議|開會/i.test(stage)) return "會議中";
  return null;
}
