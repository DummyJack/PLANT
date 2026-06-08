# Defines action prompts and output contracts.


def refine_scope(*, source_id: str) -> str:
    return f"""# 任務
根據 requirements 與本議題討論，產生 scope.json 的最小更新。

# Action Boundary
- action=refine_scope
- 本 action 只負責產生 scope_updates patch。
- 不產生或修正 REQ、不抽取 User Requirements、不更新 draft、不做衝突辨識。
- 不直接更新 artifact；runtime 會根據 scope_updates 套用到 artifact.scope。

# Context Rules
- 主要依據 requirements 與 discussion；scenario 只能作為薄背景，不得用來新增 requirements 沒有支持的 scope。
- 只在討論已明確指出系統邊界、第三方責任、線下流程、in scope 或 out of scope 時更新。
- 不讀取 feedback、系統模型、衝突報告或 draft 作為直接 scope 來源。

# Input
- requirements、discussion、scenario 與 current_scope 由 runtime context 提供。
- source_id={source_id}

# Generation Rules
- 不改寫需求、不產生 system requirement。
- Scope 是專案邊界，不是需求清單；詳細功能、驗收條件、限制與風險留給後續需求條目與草稿章節處理。
- 不得把單一 URL-* 或 REQ-* 改寫成 scope item。
- in_scope_add 只放高層系統責任邊界、能力域、流程域、資料責任或外部介接邊界。
- out_of_scope_add 放明確不屬於本系統、由第三方/線下/外部組織負責，或會議已裁定排除的內容。
- 若討論只是補功能、驗收條件、限制、風險或需求文字，應交給 refine_requirement，不要更新 scope。
- 只有當會議明確裁定「屬於本系統 / 不屬於本系統 / 第三方負責 / 人工流程負責」時才更新 scope。
- remove 只在既有 scope 明顯被本議題決議推翻時使用；沒有明確依據請留空。
- 每個項目都要是短句，不要放空泛目標；新增後整體 scope 應維持精簡，若只是更細的需求，不要加入。
- source_id 固定使用：{source_id}
- 輸出只包含 scope_updates、reason、source_id。

# Output JSON
{{
  "scope_updates": {{
    "in_scope_add": [],
    "out_of_scope_add": [],
    "in_scope_remove": [],
    "out_of_scope_remove": []
  }},
  "reason": "一句說明",
  "source_id": "{source_id}"
}}

# Forbidden Output
- 不輸出 Markdown 說明。
- 不輸出 requirement_candidates、REQ、draft_plan 或 conflicts。
- 不輸出 artifact 全文。
- 不輸出 scope_updates 以外的 patch wrapper。
- 不把單一 URL-* 或 REQ-* 改寫成 scope item。
- 不根據 feedback、系統模型、衝突報告或 draft 單獨更新 scope。"""
