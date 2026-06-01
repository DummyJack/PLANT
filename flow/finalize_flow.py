# SRS flow: generate srs.md from the latest draft.
from typing import Any, Dict


def finalize(
    flow,
    artifact: Dict[str, Any],
) -> None:
    srs_md = flow.documentor_agent.create_srs()
    flow.store.save_markdown(srs_md, "srs.md")
    flow.logger.info("Documentor：已儲存 srs.md")

    flow.store.save_artifact(artifact)
