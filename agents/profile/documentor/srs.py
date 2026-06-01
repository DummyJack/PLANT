# SRS generation implementation using the latest requirement draft.
from .prompts import build_srs_prompt
from storage.markdown import clean_llm_output


class DocumentorSrs:
    def create_srs_from_draft(
        self,
        draft_md: str,
    ) -> str:
        prompt = build_srs_prompt(draft_md=draft_md)
        srs_md = self.model.chat(
            self.build_direct_messages(prompt),
            action=self.usage_action("documentor.create_srs"),
        )
        return clean_llm_output(srs_md)

    def create_srs_from_latest_draft(self) -> str:
        """使用最新 draft 作為輸入，直接生成 SRS。"""
        latest_version = self.store.get_draft_version()
        if latest_version < 0:
            raise ValueError("尚無需求草稿，請先產生 draft 再生成 SRS")
        draft_md = self.store.load_draft(latest_version)
        if not draft_md:
            raise ValueError(f"無法載入草稿 draft_v{latest_version}.md")

        return self.create_srs_from_draft(draft_md)
