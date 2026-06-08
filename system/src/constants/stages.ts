export interface StageToggle {
  key: string;
  label: string;
}

export interface StageGroup {
  id: string;
  label: string;
  toggles: StageToggle[];
}

export const STAGE_GROUPS: StageGroup[] = [
  {
    id: "init",
    label: "初始化",
    toggles: [{ key: "init", label: "專案初始化" }],
  },
  {
    id: "elicitation",
    label: "需求擷取",
    toggles: [
      { key: "elicitation", label: "需求訪談" },
      { key: "conflict_detection", label: "衝突偵測" },
      { key: "research_domain", label: "領域研究" },
    ],
  },
  {
    id: "modeling",
    label: "系統建模",
    toggles: [{ key: "system_model", label: "系統模型" }],
  },
  {
    id: "docs",
    label: "文件產出",
    toggles: [
      { key: "draft", label: "草稿" },
      { key: "general_formal_meeting", label: "一般正式會議" },
      { key: "general_update_draft", label: "一般更新草稿" },
      { key: "default_formal_meeting", label: "預設正式會議" },
      { key: "default_update_draft", label: "預設更新草稿" },
      { key: "DR", label: "設計緣由 (DR)" },
      { key: "SRS", label: "需求規格 (SRS)" },
    ],
  },
];
