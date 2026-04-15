from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


AMBIGUOUS_WORDS = (
    "快速",
    "容易",
    "友善",
    "穩定",
    "高效",
    "適當",
    "必要時",
    "盡快",
    "彈性",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _issue(
    *,
    issue_type: str,
    severity: str,
    message: str,
    requirement_id: str = "",
) -> Dict[str, Any]:
    return {
        "type": issue_type,
        "severity": severity,
        "requirement_id": requirement_id,
        "message": message,
    }


def _check_completeness(artifact: Dict[str, Any]) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    requirements = artifact.get("requirements", []) or []
    if not requirements:
        issues.append(
            _issue(
                issue_type="completeness",
                severity="critical",
                message="缺少 requirements，無法產生正式規格。",
            )
        )
        return issues

    for req in requirements:
        if not isinstance(req, dict):
            issues.append(
                _issue(
                    issue_type="completeness",
                    severity="critical",
                    message="requirements 出現非物件格式項目。",
                )
            )
            continue
        rid = str(req.get("id") or "").strip()
        if not rid:
            issues.append(
                _issue(
                    issue_type="completeness",
                    severity="critical",
                    requirement_id=rid,
                    message="需求缺少 id。",
                )
            )
        if not str(req.get("text") or "").strip():
            issues.append(
                _issue(
                    issue_type="completeness",
                    severity="critical",
                    requirement_id=rid,
                    message="需求缺少 text。",
                )
            )
        req_type = str(req.get("type") or "").strip()
        if req_type not in {"FR", "NFR", "constraint"}:
            issues.append(
                _issue(
                    issue_type="completeness",
                    severity="warning",
                    requirement_id=rid,
                    message=f"需求 type 非標準值（目前: {req_type or '空值'}）。",
                )
            )
        if str(req.get("priority") or "").strip() not in {"must", "should", "could"}:
            issues.append(
                _issue(
                    issue_type="completeness",
                    severity="warning",
                    requirement_id=rid,
                    message="需求 priority 非標準值（must/should/could）。",
                )
            )
        status = str(req.get("status") or "").strip().lower()
        if status not in {"draft", "approved", "baselined", "rejected"}:
            issues.append(
                _issue(
                    issue_type="completeness",
                    severity="warning",
                    requirement_id=rid,
                    message="需求缺少或使用了非標準 status（draft/approved/baselined/rejected）。",
                )
            )
    return issues


def _check_verifiability(artifact: Dict[str, Any]) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    allowed_methods = {"test", "review", "inspection"}
    for req in artifact.get("requirements", []) or []:
        if not isinstance(req, dict):
            continue
        rid = str(req.get("id") or "").strip()
        text = str(req.get("text") or "").strip()
        req_type = str(req.get("type") or "").strip()
        verification_method = str(req.get("verification_method") or "").strip().lower()
        acceptance_criteria = str(req.get("acceptance_criteria") or "").strip()
        if not text:
            continue
        if any(word in text for word in AMBIGUOUS_WORDS):
            issues.append(
                _issue(
                    issue_type="verifiability",
                    severity="warning",
                    requirement_id=rid,
                    message="需求包含模糊詞，可能降低可驗證性。",
                )
            )
        if verification_method not in allowed_methods:
            issues.append(
                _issue(
                    issue_type="verifiability",
                    severity="critical",
                    requirement_id=rid,
                    message=(
                        "需求缺少或使用了非標準 verification_method "
                        "（需為 test/review/inspection）。"
                    ),
                )
            )
        if req_type in {"FR", "NFR"} and not acceptance_criteria:
            issues.append(
                _issue(
                    issue_type="verifiability",
                    severity="critical",
                    requirement_id=rid,
                    message="FR/NFR 缺少 acceptance_criteria。",
                )
            )
        if req_type == "NFR" and not any(ch.isdigit() for ch in text):
            issues.append(
                _issue(
                    issue_type="verifiability",
                    severity="critical",
                    requirement_id=rid,
                    message="NFR 缺少可量測數值（建議補 metric/target）。",
                )
            )
        if req_type == "NFR":
            ac = str(req.get("acceptance_criteria") or "").strip()
            if ac and not any(ch.isdigit() for ch in ac):
                issues.append(
                    _issue(
                        issue_type="verifiability",
                        severity="critical",
                        requirement_id=rid,
                        message="NFR 的 acceptance_criteria 缺少可量測數值指標。",
                    )
                )
            nfr_metric = str(req.get("metric") or "").strip()
            nfr_target = str(req.get("target") or "").strip()
            if not nfr_metric or not nfr_target:
                issues.append(
                    _issue(
                        issue_type="verifiability",
                        severity="warning",
                        requirement_id=rid,
                        message="NFR 建議補充 metric 與 target 欄位以提升可驗證性。",
                    )
                )
    return issues


def _check_traceability(artifact: Dict[str, Any]) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    for req in artifact.get("requirements", []) or []:
        if not isinstance(req, dict):
            continue
        rid = str(req.get("id") or "").strip()
        src = req.get("source_stakeholders") or []
        if not isinstance(src, list) or not any(str(s).strip() for s in src):
            issues.append(
                _issue(
                    issue_type="traceability",
                    severity="warning",
                    requirement_id=rid,
                    message="需求缺少 source_stakeholders，追蹤性不足。",
                )
            )
    return issues


def _check_governance(artifact: Dict[str, Any]) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    unresolved_conflicts = [
        c for c in (artifact.get("conflicts", []) or [])
        if isinstance(c, dict) and str(c.get("label") or "").strip() == "Conflict"
    ]
    if unresolved_conflicts:
        issues.append(
            _issue(
                issue_type="governance",
                severity="critical",
                message=f"仍有 {len(unresolved_conflicts)} 筆未解 Conflict。",
            )
        )

    pending_candidates = [
        c for c in (artifact.get("requirement_change_candidates", []) or [])
        if isinstance(c, dict)
        and str(c.get("status") or "").strip() in {"pending_review", "proposed"}
    ]
    if pending_candidates:
        issues.append(
            _issue(
                issue_type="governance",
                severity="warning",
                message=f"仍有 {len(pending_candidates)} 筆需求變更候選尚未完成審核。",
            )
        )

    unanswered_questions = [
        q for q in (artifact.get("open_questions", []) or [])
        if isinstance(q, dict) and str(q.get("status") or "").strip() != "answered"
    ]
    if unanswered_questions:
        issues.append(
            _issue(
                issue_type="governance",
                severity="warning",
                message=f"仍有 {len(unanswered_questions)} 筆開放問題未回答。",
            )
        )

    discussions = artifact.get("discussions", []) or []
    if discussions and not (artifact.get("topic_resolution_effects") or []):
        issues.append(
            _issue(
                issue_type="governance",
                severity="warning",
                message="已有會議紀錄但缺少 topic_resolution_effects，建議補齊結構化議題輸出。",
            )
        )
    pending_approvals = [
        row for row in (artifact.get("approval_queue", []) or [])
        if isinstance(row, dict) and str(row.get("status") or "pending").strip() == "pending"
    ]
    if pending_approvals:
        issues.append(
            _issue(
                issue_type="governance",
                severity="critical",
                message=f"仍有 {len(pending_approvals)} 筆待批准變更（approval_queue）。",
            )
        )

    return issues


def _check_rtm_linkage(artifact: Dict[str, Any]) -> List[Dict[str, Any]]:
    """檢查 RTM 可追蹤性：議題決議→需求、決策→需求、open_questions→合法 agent。"""
    issues: List[Dict[str, Any]] = []
    valid_agents = {"user", "analyst", "expert", "modeler", "mediator", "documentor"}

    for effect in artifact.get("topic_resolution_effects", []) or []:
        if not isinstance(effect, dict):
            continue
        tid = str(effect.get("topic_id") or "").strip()
        affected = effect.get("affected_requirement_ids") or []
        if not affected:
            issues.append(
                _issue(
                    issue_type="traceability",
                    severity="warning",
                    message=f"議題 {tid} 的 topic_resolution_effect 缺少 affected_requirement_ids。",
                )
            )

    for dec in artifact.get("decisions", []) or []:
        if not isinstance(dec, dict):
            continue
        did = str(dec.get("id") or "").strip()
        affected = dec.get("affected_requirement_ids") or []
        if not affected:
            issues.append(
                _issue(
                    issue_type="traceability",
                    severity="warning",
                    message=f"決策 {did} 缺少 affected_requirement_ids，RTM 無法關聯。",
                )
            )

    for q in artifact.get("open_questions", []) or []:
        if not isinstance(q, dict):
            continue
        if q.get("status") == "answered":
            continue
        to_agent = str(q.get("to_agent") or q.get("to") or "").strip()
        if to_agent and to_agent not in valid_agents:
            issues.append(
                _issue(
                    issue_type="traceability",
                    severity="warning",
                    message=f"open_question 的 to_agent「{to_agent}」非系統角色名。",
                )
            )

    return issues


def _check_topic_dod(artifact: Dict[str, Any]) -> List[Dict[str, Any]]:
    """檢查每個已收斂議題是否符合 Definition of Done。"""
    issues: List[Dict[str, Any]] = []
    for effect in artifact.get("topic_resolution_effects", []) or []:
        if not isinstance(effect, dict):
            continue
        tid = str(effect.get("topic_id") or "").strip()
        if not effect.get("affected_requirement_ids"):
            pass  # already flagged by _check_rtm_linkage
        vi = effect.get("verification_impact")
        if not isinstance(vi, dict) or not str(vi.get("level") or "").strip():
            issues.append(
                _issue(
                    issue_type="dod",
                    severity="warning",
                    message=f"議題 {tid} 缺少 verification_impact.level，無法判定驗證衝擊。",
                )
            )
    for dec in artifact.get("decisions", []) or []:
        if not isinstance(dec, dict):
            continue
        did = str(dec.get("id") or "").strip()
        if not str(dec.get("decision") or dec.get("summary") or "").strip():
            issues.append(
                _issue(
                    issue_type="dod",
                    severity="critical",
                    message=f"決策 {did} 缺少 decision/summary 文字，不符 DoD。",
                )
            )
    return issues


def run_validation_gate(
    flow: Any,
    artifact: Dict[str, Any],
    *,
    stage: str,
    round_num: Optional[int] = None,
) -> Dict[str, Any]:
    checks = {
        "completeness": _check_completeness(artifact),
        "verifiability": _check_verifiability(artifact),
        "traceability": _check_traceability(artifact) + _check_rtm_linkage(artifact) + _check_topic_dod(artifact),
        "governance": _check_governance(artifact),
    }
    all_issues = [item for rows in checks.values() for item in rows]
    critical_count = sum(1 for item in all_issues if item.get("severity") == "critical")
    warning_count = sum(1 for item in all_issues if item.get("severity") == "warning")
    passed = critical_count == 0

    report = {
        "schema_version": "validation_gate.v1",
        "stage": stage,
        "round": round_num,
        "timestamp": _now_iso(),
        "passed": passed,
        "summary": {
            "critical": critical_count,
            "warning": warning_count,
            "total_issues": len(all_issues),
        },
        "checks": checks,
    }

    artifact.setdefault("validation_reports", []).append(report)
    artifact.setdefault("meta", {})["last_validation_stage"] = stage
    artifact.setdefault("meta", {})["last_validation_passed"] = passed
    if round_num is not None:
        artifact.setdefault("meta", {})["last_validation_round"] = round_num

    if passed:
        flow.logger.info(
            "Validation Gate（%s）通過：critical=%s, warning=%s",
            stage,
            critical_count,
            warning_count,
        )
    else:
        flow.logger.warning(
            "Validation Gate（%s）未通過：critical=%s, warning=%s",
            stage,
            critical_count,
            warning_count,
        )

    return report
