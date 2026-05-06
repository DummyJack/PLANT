# Finalization flow: prepare formal SRS artifact and write final outputs.
from copy import deepcopy
from typing import Any, Dict, List, Set

from agents.profile.analyst.requirements import normalize_requirement_status


def requirement_status(req: Dict[str, Any]) -> str:
    return normalize_requirement_status(req.get("status"))


def build_srs_artifact(artifact: Dict[str, Any], allowed_statuses: Set[str]) -> Dict[str, Any]:
    out = deepcopy(artifact)
    out["requirements"] = [
        dict(req)
        for req in (artifact.get("requirements", []) or [])
        if isinstance(req, dict) and requirement_status(req) in allowed_statuses
    ]
    return out


def render_unverified_requirements_markdown(rows: List[Dict[str, Any]]) -> str:
    md = (
        "# Unverified Requirements\n\n"
        "以下需求尚未通過 verified 狀態，未納入正式 SRS。\n\n"
        "| Requirement ID | Status | Text |\n"
        "|---|---|---|\n"
    )
    if not rows:
        return md + "| (無) | - | - |\n"
    out = []
    for req in rows:
        out.append(
            "| {rid} | {status} | {text} |".format(
                rid=req.get("id", ""),
                status=requirement_status(req),
                text=(str(req.get("text") or "").strip() or "待補").replace("\n", " "),
            )
        )
    return md + "\n".join(out) + "\n"


def finalize(
    flow,
    artifact: Dict[str, Any],
) -> Dict[str, Any]:
    allowed_statuses = {"verified"}
    verified_artifact = build_srs_artifact(artifact, allowed_statuses)
    verified_count = len(verified_artifact.get("requirements", []) or [])

    total_reqs = len([
        r for r in (artifact.get("requirements", []) or [])
        if isinstance(r, dict)
    ])
    ratio = (verified_count / total_reqs) if total_reqs > 0 else 0.0

    if verified_count <= 0:
        raise ValueError("沒有 verified requirements，不能產生正式 SRS")

    unverified_rows = [
        dict(req)
        for req in (artifact.get("requirements", []) or [])
        if isinstance(req, dict) and requirement_status(req) not in allowed_statuses
    ]
    if unverified_rows:
        artifact["unverified_requirements"] = render_unverified_requirements_markdown(unverified_rows)
        flow.logger.info("✓ 已寫入 artifact.unverified_requirements")

    flow.logger.info("產生 SRS（正式）")
    srs_md = flow.documentor_agent.generate_srs(verified_artifact)
    flow.store.save_markdown(srs_md, "srs.md")
    flow.logger.info("✓ 產生 srs.md")
    # 正式產出後，保留 verified 狀態並記錄 baseline version。
    baseline_version = int((artifact.get("meta") or {}).get("baseline_version") or 0) + 1
    for req in artifact.get("requirements", []) or []:
        if not isinstance(req, dict):
            continue
        if requirement_status(req) == "verified":
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
        "verified_count": verified_count,
        "total_requirements": total_reqs,
        "verified_ratio": ratio,
    }
