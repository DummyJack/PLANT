const STAGE_KEYWORDS: Array<{ pattern: RegExp; label: string }> = [
  { pattern: /初始|init/i, label: "初始階段" },
  { pattern: /elicitation|擷取/i, label: "需求擷取" },
  { pattern: /conflict|衝突/i, label: "衝突檢測" },
  { pattern: /research|領域/i, label: "領域研究" },
  { pattern: /model|建模/i, label: "系統建模" },
  { pattern: /draft|草案/i, label: "草案更新" },
  { pattern: /meeting|會議|開會/i, label: "正式會議" },
  { pattern: /SRS|規格/i, label: "規格化" },
  { pattern: /DR|設計緣由/i, label: "設計緣由" },
];

export function inferStageLabel(message: string, currentStage?: string): string {
  if (currentStage?.trim()) {
    for (const { pattern, label } of STAGE_KEYWORDS) {
      if (pattern.test(currentStage)) return label;
    }
    return currentStage;
  }
  for (const { pattern, label } of STAGE_KEYWORDS) {
    if (pattern.test(message)) return label;
  }
  return "需求討論";
}
