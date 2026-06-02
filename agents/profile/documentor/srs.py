# SRS generation implementation using the latest requirement draft.
from pathlib import Path
import re
import shutil

from .prompts import build_srs_prompt
from storage.markdown import clean_llm_output


class DocumentorSrs:
    IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif", ".bmp"}

    def _sync_model_images_to_output(self) -> None:
        """複製 artifact/models 的圖片到 output/models，讓 SRS 的 ../models 引用成立。"""
        artifact_models = Path(self.store.artifact_dir) / "models"
        output_models = Path(self.store.output_dir) / "models"
        if not artifact_models.exists():
            return

        output_models.mkdir(parents=True, exist_ok=True)
        for src in artifact_models.iterdir():
            if not src.is_file():
                continue
            if src.suffix.lower() not in self.IMAGE_SUFFIXES:
                continue
            dst = output_models / src.name
            shutil.copy2(src, dst)

    @staticmethod
    def _normalize_model_image_links(srs_md: str) -> str:
        """將草稿常見的 ../models 路徑改為 output 下可直接使用的 ./models。"""
        return re.sub(r"\(\.\./models/", "(./models/", srs_md or "")

    def create_srs_from_draft(
        self,
        draft_md: str,
    ) -> str:
        # 先同步模型圖，讓 SRS 可直接使用 ../models/xxx 參考輸出目錄。
        self._sync_model_images_to_output()
        prompt = build_srs_prompt(draft_md=draft_md)
        srs_md = self.model.chat(
            self.build_direct_messages(prompt),
            action=self.usage_action("documentor.create_srs"),
        )
        srs_md = clean_llm_output(srs_md)
        return self._normalize_model_image_links(srs_md)

    def create_srs_from_latest_draft(self) -> str:
        """使用最新 draft 作為輸入，直接生成 SRS。"""
        latest_version = self.store.get_draft_version()
        if latest_version < 0:
            raise ValueError("尚無需求草稿，請先產生 draft 再生成 SRS")
        draft_md = self.store.load_draft(latest_version)
        if not draft_md:
            raise ValueError(f"無法載入草稿 draft_v{latest_version}.md")

        return self.create_srs_from_draft(draft_md)
