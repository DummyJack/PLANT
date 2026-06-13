# Handles finalize flow logic for project flow orchestration and stage execution.
from typing import Any, Dict

from flow.init_flow import emit_markdown_section_deltas


def generate_dr(
    flow,
    artifact: Dict[str, Any],
) -> None:
    flow.logger.step_started(
        "document_generation",
        "document_generation.generate_dr",
        "產生 Design Rationale",
        agent="documentor",
    )
    dr_md = flow.documentor_agent.generate_dr(artifact)
    flow.store.save_markdown(dr_md, "design_rationale.md")
    emit_markdown_section_deltas(
        flow,
        "document_generation",
        "document_generation.generate_dr",
        dr_md,
        agent="documentor",
        max_sections=10,
    )
    flow.logger.step_completed(
        "document_generation",
        "document_generation.generate_dr",
        "Design Rationale",
        agent="documentor",
        output_path="output/design_rationale.md",
    )
    flow.logger.artifact_created(
        "document_generation",
        "document_generation.generate_dr",
        "Design Rationale 已產生",
        "output/design_rationale.md",
    )
    flow.store.save_artifact(artifact)


def generate_srs(
    flow,
    artifact: Dict[str, Any],
) -> None:
    flow.logger.step_started(
        "document_generation",
        "document_generation.generate_srs",
        "產生 SRS",
        agent="documentor",
    )
    srs_md = flow.documentor_agent.generate_srs()
    flow.store.save_markdown(srs_md, "srs.md")
    emit_markdown_section_deltas(
        flow,
        "document_generation",
        "document_generation.generate_srs",
        srs_md,
        agent="documentor",
        max_sections=10,
    )
    flow.logger.step_completed(
        "document_generation",
        "document_generation.generate_srs",
        "SRS",
        agent="documentor",
        output_path="output/srs.md",
    )
    flow.logger.artifact_created(
        "document_generation",
        "document_generation.generate_srs",
        "SRS 已產生",
        "output/srs.md",
    )

    flow.store.save_artifact(artifact)


def finalize(
    flow,
    artifact: Dict[str, Any],
) -> None:
    generate_dr(flow, artifact)
    generate_srs(flow, artifact)
