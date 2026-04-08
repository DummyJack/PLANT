from typing import Any, Dict


def finalize(flow, artifact: Dict[str, Any]):
    flow.logger.info("產生 SRS")
    srs_md = flow.documentor_agent.generate_srs(artifact)
    flow.store.save_markdown(srs_md, "srs.md")
    flow.logger.info("✓ 產生 srs.md")

    cost_summary = flow._build_cost_summary()
    if cost_summary:
        flow.store.save_json(cost_summary, flow.store.project_dir / "cost_summary.json")
        flow.logger.info("✓ 已儲存 cost_summary.json")
    else:
        flow.logger.info("無定價資訊，略過 cost_summary")

    agent_usage = flow._build_agent_usage_summary()
    flow.store.save_json(agent_usage, flow.store.project_dir / "agent_usage.json")
    flow.logger.info("✓ 已儲存 agent_usage.json")
