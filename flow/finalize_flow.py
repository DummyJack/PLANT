# Finalization flow: write the formal SRS after the final meeting.
from typing import Any, Dict


def finalize(
    flow,
    artifact: Dict[str, Any],
) -> Dict[str, Any]:
    total_reqs = len([
        r for r in (artifact.get("requirements", []) or [])
        if isinstance(r, dict)
    ])
    if total_reqs <= 0:
        raise ValueError("沒有 requirements，不能產生正式 SRS")

    flow.logger.info("產生 SRS（正式）")
    srs_md = flow.documentor_agent.generate_srs(artifact)
    flow.store.save_markdown(srs_md, "srs.md")
    flow.logger.info("✓ 產生 srs.md")

    baseline_version = int((artifact.get("meta") or {}).get("baseline_version") or 0) + 1
    for req in artifact.get("requirements", []) or []:
        if isinstance(req, dict):
            req["baseline_version"] = baseline_version
    artifact.setdefault("meta", {})["baseline_version"] = baseline_version
    flow.store.save_artifact(artifact)

    cost_summary = flow.build_cost_summary()
    if cost_summary:
        flow.store.save_json(cost_summary, flow.store.project_dir / "cost_summary.json")
        flow.logger.info("✓ 已儲存 cost_summary.json")
    else:
        flow.logger.info("無定價資訊，略過 cost_summary")

    agent_usage = flow.build_agent_usage_summary()
    flow.store.save_json(agent_usage, flow.store.project_dir / "agent_usage.json")
    flow.logger.info("✓ 已儲存 agent_usage.json")
    return {
        "produced_formal_srs": True,
        "total_requirements": total_reqs,
    }
