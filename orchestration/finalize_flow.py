from copy import deepcopy
from typing import Any, Dict, List, Set
from .validation_gate import run_validation_gate


def _requirement_status(req: Dict[str, Any]) -> str:
    status = str(req.get("status") or "draft").strip().lower()
    if status not in {"draft", "approved", "baselined", "rejected"}:
        status = "draft"
    return status


def _build_srs_artifact(artifact: Dict[str, Any], allowed_statuses: Set[str]) -> Dict[str, Any]:
    out = deepcopy(artifact)
    out["requirements"] = [
        dict(req)
        for req in (artifact.get("requirements", []) or [])
        if isinstance(req, dict) and _requirement_status(req) in allowed_statuses
    ]
    return out


def _collect_rtm_rows(artifact: Dict[str, Any]) -> List[Dict[str, Any]]:
    effects = artifact.get("topic_resolution_effects", []) or []
    decision_by_topic: Dict[str, List[str]] = {}
    decision_by_requirement: Dict[str, List[tuple]] = {}
    for dec in artifact.get("decisions", []) or []:
        if not isinstance(dec, dict):
            continue
        tid = str(dec.get("source_topic_id") or "").strip()
        did = str(dec.get("id") or "").strip()
        if not did:
            continue
        if tid:
            decision_by_topic.setdefault(tid, []).append(did)
        for _rid in (dec.get("affected_requirement_ids", []) or []):
            _rid_s = str(_rid).strip()
            if _rid_s:
                decision_by_requirement.setdefault(_rid_s, []).append((did, tid))

    rows: List[Dict[str, Any]] = []
    for req in artifact.get("requirements", []) or []:
        if not isinstance(req, dict):
            continue
        rid = str(req.get("id") or "").strip()
        if not rid:
            continue
        linked_topics = []
        for row in effects:
            if not isinstance(row, dict):
                continue
            tid = str(row.get("topic_id") or "").strip()
            affected = [
                str(x).strip()
                for x in (row.get("affected_requirement_ids", []) or [])
                if str(x).strip()
            ]
            if tid and rid in affected:
                linked_topics.append(tid)
        linked_decisions = []
        for tid in linked_topics:
            linked_decisions.extend(decision_by_topic.get(tid, []))
        for _did, _dtid in decision_by_requirement.get(rid, []):
            linked_decisions.append(_did)
            if _dtid:
                linked_topics.append(_dtid)
        linked_topics = sorted(set(linked_topics))
        linked_decisions = sorted(set(linked_decisions))
        rows.append(
            {
                "requirement_id": rid,
                "status": _requirement_status(req),
                "source_stakeholders": req.get("source_stakeholders", []),
                "topic_ids": linked_topics,
                "decision_ids": linked_decisions,
                "verification_method": str(req.get("verification_method") or "").strip(),
                "acceptance_criteria": str(req.get("acceptance_criteria") or "").strip(),
            }
        )
    return rows


def _render_rtm_markdown(rows: List[Dict[str, Any]]) -> str:
    header = (
        "# Requirements Traceability Matrix\n\n"
        "| Requirement ID | Status | Source Stakeholders | Topic IDs | Decision IDs | Verification Method | Acceptance Criteria |\n"
        "|---|---|---|---|---|---|---|\n"
    )
    lines = []
    for row in rows:
        lines.append(
            "| {rid} | {status} | {src} | {topics} | {decisions} | {vm} | {ac} |".format(
                rid=row.get("requirement_id", ""),
                status=row.get("status", ""),
                src=", ".join(row.get("source_stakeholders", []) or []) or "待補",
                topics=", ".join(row.get("topic_ids", []) or []) or "待補",
                decisions=", ".join(row.get("decision_ids", []) or []) or "待補",
                vm=row.get("verification_method", "") or "待補",
                ac=row.get("acceptance_criteria", "") or "待補",
            )
        )
    if not lines:
        lines.append("| (無) | - | - | - | - | - | - |")
    return header + "\n".join(lines) + "\n"


def _render_unapproved_requirements_markdown(rows: List[Dict[str, Any]]) -> str:
    md = (
        "# Unapproved Requirements\n\n"
        "以下需求尚未進入 approved/baselined，未納入正式 SRS。\n\n"
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
                status=_requirement_status(req),
                text=(str(req.get("text") or "").strip() or "待補").replace("\n", " "),
            )
        )
    return md + "\n".join(out) + "\n"


def finalize(flow, artifact: Dict[str, Any]):
    report_dir = (
        flow.store.artifact_dir
        if hasattr(flow.store, "artifact_dir")
        else flow.store.project_dir
    )
    report = None
    if flow.config.get("enable_validation_gate", True):
        report = run_validation_gate(flow, artifact, stage="pre_finalize")
        flow.store.save_artifact(artifact)
        if hasattr(flow.store, "project_dir"):
            flow.store.save_json(
                report,
                report_dir / "validation_report.json",
            )
            flow.logger.info("✓ 已儲存 validation_report.json")

    enforce_gate = flow.config.get("enforce_validation_gate_for_final_srs", True)
    blocked = bool(report and not report.get("passed") and enforce_gate)
    allowed_statuses = {"approved", "baselined"}
    approved_artifact = _build_srs_artifact(artifact, allowed_statuses)
    approved_count = len(approved_artifact.get("requirements", []) or [])
    if not blocked and approved_count == 0:
        blocked = True
        flow.logger.warning("未找到 approved/baselined 需求，改為輸出草稿 SRS。")

    total_reqs = len([
        r for r in (artifact.get("requirements", []) or [])
        if isinstance(r, dict)
    ])
    min_ratio = float(flow.config.get("min_approved_ratio_for_srs", 0.8))
    if not blocked and total_reqs > 0:
        ratio = approved_count / total_reqs
        if ratio < min_ratio:
            blocked = True
            flow.logger.warning(
                "Approved 比例 %.1f%% < 門檻 %.0f%%，改為輸出草稿 SRS。",
                ratio * 100, min_ratio * 100,
            )

    rtm_rows = _collect_rtm_rows(artifact)
    flow.store.save_markdown(_render_rtm_markdown(rtm_rows), "rtm.md")
    if hasattr(flow.store, "project_dir"):
        flow.store.save_json(
            {"rows": rtm_rows},
            report_dir / "rtm.json",
        )
        flow.logger.info("✓ 已儲存 rtm.json")

    unapproved_rows = [
        dict(req)
        for req in (artifact.get("requirements", []) or [])
        if isinstance(req, dict) and _requirement_status(req) not in allowed_statuses
    ]
    if unapproved_rows:
        flow.store.save_markdown(
            _render_unapproved_requirements_markdown(unapproved_rows),
            "unapproved_requirements.md",
        )
        flow.logger.info("✓ 已儲存 unapproved_requirements.md")

    strict_mode = flow.config.get("strict_formal_srs_mode", False)
    if blocked and strict_mode:
        flow.logger.warning("strict_formal_srs_mode：Validation Gate 未通過，不產生任何 SRS 檔案。")
        srs_md = None
    elif blocked:
        flow.logger.info("產生 SRS（草稿）")
        srs_md = flow.documentor_agent.generate_srs(artifact)
        flow.store.save_markdown(srs_md, "srs_draft.md")
        flow.logger.warning("Validation Gate 未通過，已輸出 srs_draft.md（未產生正式 srs.md）")
    else:
        flow.logger.info("產生 SRS（正式）")
        srs_md = flow.documentor_agent.generate_srs(approved_artifact)
    if not blocked:
        flow.store.save_markdown(srs_md, "srs.md")
        flow.logger.info("✓ 產生 srs.md")
        # 正式產出後，將 approved 需求提升為 baselined。
        baseline_version = int((artifact.get("meta") or {}).get("baseline_version") or 0) + 1
        for req in artifact.get("requirements", []) or []:
            if not isinstance(req, dict):
                continue
            if _requirement_status(req) in {"approved", "baselined"}:
                req["status"] = "baselined"
                req["baseline_version"] = baseline_version
        artifact.setdefault("meta", {})["baseline_version"] = baseline_version
        artifact.setdefault("meta", {})["baselined_at"] = report.get("timestamp") if report else ""
        flow.store.save_artifact(artifact)

    cost_summary = flow._build_cost_summary()
    if cost_summary:
        flow.store.save_json(cost_summary, flow.store.project_dir / "cost_summary.json")
        flow.logger.info("✓ 已儲存 cost_summary.json")
    else:
        flow.logger.info("無定價資訊，略過 cost_summary")

    agent_usage = flow._build_agent_usage_summary()
    flow.store.save_json(agent_usage, flow.store.project_dir / "agent_usage.json")
    flow.logger.info("✓ 已儲存 agent_usage.json")
