# SRS flow: generate srs.md from the latest draft.
from typing import Any, Dict


def finalize(
    flow,
    artifact: Dict[str, Any],
) -> Dict[str, Any]:
    flow.logger.info("產生 SRS")
    srs_md = flow.documentor_agent.generate_srs(artifact)
    flow.store.save_markdown(srs_md, "srs.md")
    flow.logger.info("✓ 產生 srs.md")

    flow.store.save_artifact(artifact)

    return {
        "produced_srs": True,
        "source": "latest_draft",
    }
