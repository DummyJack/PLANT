# SRS generation implementation using the latest Analyst draft.
from typing import Any, Dict, Optional

from storage.markdown import clean_llm_output


class DocumentorSrs:
    def generate_srs_from_draft(
        self,
        analyst_draft: str,
        context: Dict[str, Any],
    ) -> str:
        if "SRS" not in self.skill_names:
            raise ValueError("DocumentorAgent 未賦予 SRS skill，無法產生正式 SRS")

        task = f"""# 任務
請依 SRS skill，將下方「最新 Analyst Requirement Draft」整理成一份 Software Requirements Specification。

# 輸入邊界
- 唯一需求來源是「最新 Analyst Requirement Draft」。
- 不得使用任何外部資料或自行補充 draft 沒有的需求。
- draft 中的 User Requirements、衝突、開放問題、領域研究與模型摘要，只能依 draft 內的狀態與內容使用。

# SRS skill 使用方式
- 使用 SRS skill 的 IEEE 830 文件結構與寫作規範。
- 若 skill 範例中的 ID、RTM 或範例章節與本任務規則衝突，以本任務規則為準。
- 不要輸出 Requirements Traceability Matrix 或 Change Request Process。
- 不要保留 template placeholder、TODO 或範例資料。

# 需求 ID 規則
- 若 draft 中有 REQ-*，使用 REQ-*。
- 若沒有 REQ-*，使用 draft 中的 SRC-*、FRC-*、NFRC-*。
- 不得新增、刪除、合併、拆分、重新命名 draft 中已有的需求 ID。
- 不得輸出 draft 中不存在的 REQ-*、SRC-*、FRC-*、NFRC-*。

# Pending / Open 規則
- draft 中 pending、open、unresolved、待確認、待決議的內容，不得寫成已確認需求。
- 可以放入「待確認」或「Open Issues」類型的小節，但不得包裝成正式已定案需求。
- 若資料不足，寫「待補」，不得臆測。

# Requirement 條目格式
- 每一條列入 Specific Requirements 的需求必須獨立成節。
- 每一條需求必須包含下列英文欄位標題：
  - Requirement:
  - Acceptance Criteria:
- 若 draft 沒有 acceptance criteria，Acceptance Criteria 寫「待補」。
- 不得只把 Acceptance Criteria 放在總表或附錄。

# 輸出限制
- 最終只輸出 Markdown。
- 不要解釋。
- 不要包 code fence。

# 最新 Analyst Requirement Draft
{analyst_draft}
"""
        polished = self.invoke_skill("SRS", task, context=context)
        return clean_llm_output(polished)

    @classmethod
    def build_srs_context(
        cls,
        draft_md: str,
    ) -> Dict[str, Any]:
        return {
            "draft_markdown": draft_md,
        }

    def generate_srs_from_latest_draft(self) -> str:
        """使用 Analyst 最新 draft 作為輸入，再由 SRS skill 正式化。"""
        latest_version = self.store.get_draft_version()
        if latest_version < 0:
            raise ValueError("尚無需求草稿，請先產生 draft 再生成 SRS")
        draft_md = self.store.load_draft(latest_version)
        if not draft_md:
            raise ValueError(f"無法載入草稿 draft_v{latest_version}.md")

        context = self.build_srs_context(
            draft_md=draft_md,
        )
        polished_srs = self.generate_srs_from_draft(draft_md, context)
        self.logger.info(f"  已由 SRS skill 產生正式 SRS（draft_v{latest_version}）")
        return polished_srs
