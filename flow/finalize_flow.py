# Handles finalize flow logic for project flow orchestration and stage execution.
from typing import Any, Dict


def generate_dr(
    flow,
    artifact: Dict[str, Any],
) -> None:
    dr_md = flow.documentor_agent.generate_dr(artifact)
    flow.store.save_markdown(dr_md, "design_rationale.md")
    flow.logger.info("Documentor：已儲存 design_rationale.md")
    flow.store.save_artifact(artifact)


def generate_srs(
    flow,
    artifact: Dict[str, Any],
) -> None:
    srs_md = flow.documentor_agent.generate_srs()
    flow.store.save_markdown(srs_md, "srs.md")
    flow.logger.info("Documentor：已儲存 srs.md")

    flow.store.save_artifact(artifact)


def finalize(
    flow,
    artifact: Dict[str, Any],
) -> None:
    generate_dr(flow, artifact)
    generate_srs(flow, artifact)
