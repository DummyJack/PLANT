# Handles requirement conflict detection, review, and reporting.
from agents.profile.analyst.repair import render_repair_prompt
import json
import re
from typing import Any, Dict, List, Optional

from storage.markdown import clean_llm_output
from agents.skills.base import get_skill

from storage.requirements import requirement_discussion_pool
from .rules import conflict_detection_base_task
from .validation import conflict_records, signoff_decisions
from .actions.conflict.group_detection import group_detection
from .actions.conflict.pair_detection import pair_detection
from .actions.conflict.review import review_reason, review_signoff
from .actions.report.create import create_report
from .actions.report.resolution import report_resolution
from .actions.report.update import update_report
from .skill import conflict_skill_subset


conflict_types = {
    "logical",
    "technical",
    "resource",
    "temporal",
    "data",
    "state",
    "priority",
    "scope",
    "other",
}


def clean_conflict_report_markdown(markdown: Any) -> str:
    text = clean_llm_output(str(markdown or ""))
    text = re.sub(
        r"(?im)^\s*\*\*\s*(?:Label|Type)\s*\*\*\s*:\s*.*(?:\n|$)",
        "",
        text,
    )
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ========
# Defines requirement ids function for this module workflow.
# ========
def requirement_ids(row: Dict[str, Any]) -> List[str]:
    ids = [
        str(item).strip()
        for item in (row.get("requirement_ids") or [])
        if str(item).strip()
    ]
    if ids:
        return ids
    for req in row.get("requirements") or []:
        if not isinstance(req, dict):
            continue
        req_id = str(req.get("id") or "").strip()
        if req_id:
            ids.append(req_id)
    return list(dict.fromkeys(ids))


# ========
# Defines is multiple conflict function for this module workflow.
# ========
def is_multiple_conflict(row: Dict[str, Any]) -> bool:
    row_id = str(row.get("id") or "").strip()
    if row_id.startswith("MULTIPLE-"):
        return True
    conflict_scope = str(
        row.get("scope")
        or row.get("kind")
        or row.get("conflict_scope")
        or ""
    ).strip().lower()
    if conflict_scope in {"group", "multiple", "set", "group_conflict"}:
        return True
    if row.get("related_pairs"):
        return True
    return len(requirement_ids(row)) >= 3


# ========
# Defines conflict state function for this module workflow.
# ========
def conflict_state(artifact: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    state = artifact.get("conflict")
    if isinstance(state, dict):
        return {
            "pairs": [row for row in (state.get("pairs") or []) if isinstance(row, dict)],
            "multiple": [row for row in (state.get("multiple") or []) if isinstance(row, dict)],
        }
    return {"pairs": [], "multiple": []}


# ========
# Defines split conflict rows function for this module workflow.
# ========
def split_conflict_rows(rows: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    pairs: List[Dict[str, Any]] = []
    multiple: List[Dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        if is_multiple_conflict(item):
            multiple.append(item)
        else:
            pairs.append(item)
    return {"pairs": pairs, "multiple": multiple}


# ========
# Defines all conflict rows function for this module workflow.
# ========
def all_conflict_rows(artifact: Dict[str, Any]) -> List[Dict[str, Any]]:
    state = conflict_state(artifact)
    return list(state.get("pairs") or []) + list(state.get("multiple") or [])


# ========
# Defines normalize conflict state function for this module workflow.
# ========
def normalize_conflict_state(artifact: Dict[str, Any]) -> Dict[str, Any]:
    artifact["conflict"] = conflict_state(artifact)
    return artifact


# ========
# Defines set pair conflicts function for this module workflow.
# ========
def set_pair_conflicts(artifact: Dict[str, Any], rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    state = conflict_state(artifact)
    next_rows: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        next_rows.append(dict(row))
    state["pairs"] = next_rows
    artifact["conflict"] = state
    return artifact


# ========
# Defines set multiple conflicts function for this module workflow.
# ========
def set_multiple_conflicts(artifact: Dict[str, Any], rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    state = conflict_state(artifact)
    next_rows: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        next_rows.append(dict(row))
    state["multiple"] = next_rows
    artifact["conflict"] = state
    return artifact


# ========
# Defines set conflict entries function for this module workflow.
# ========
def set_conflict_entries(artifact: Dict[str, Any], rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    state = split_conflict_rows([dict(row) for row in rows if isinstance(row, dict)])
    artifact["conflict"] = state
    return artifact


# ========
# Defines conflict entries count function for this module workflow.
# ========
def conflict_entries_count(artifact: Dict[str, Any]) -> int:
    return len(all_conflict_rows(artifact))


# ========
# Defines conflict type guidance from skill function for this module workflow.
# ========
def conflict_type_guidance_from_skill() -> str:
    skill = get_skill("conflict-analyzer")
    skill_dir = skill["path"].parent
    patterns_path = skill_dir / "references" / "conflict_patterns.md"
    try:
        content = patterns_path.read_text(encoding="utf-8")
    except OSError:
        content = ""
    rows: List[str] = []
    for match in re.finditer(r"^## ([A-Za-z]+) Conflicts\s*$", content, flags=re.MULTILINE):
        title = match.group(1).strip().lower()
        if title not in conflict_types:
            continue
        start = match.end()
        next_match = re.search(r"^## ", content[start:], flags=re.MULTILINE)
        section = content[start : start + next_match.start()] if next_match else content[start:]
        desc_match = re.search(r"### Description\s*(.*?)(?:\n### |\Z)", section, flags=re.DOTALL)
        description = ""
        if desc_match:
            description = " ".join(desc_match.group(1).strip().split())
        if description:
            rows.append(f"- {title}: {description}")
    rows.append("- other: Confirmed Conflict that does not fit the eight skill-defined types.")
    return "\n".join(rows)


# ========
# Defines normalize conflict type function for this module workflow.
# ========
def normalize_conflict_type(value: Any, *, final_label: str) -> str:
    if final_label != "Conflict":
        return ""
    conflict_type = str(value or "").strip().lower()
    if conflict_type not in conflict_types:
        raise ValueError(f"conflict type 不合法: {conflict_type or '<empty>'}")
    return conflict_type


# ========
# Defines AnalystConflicts class for this module workflow.
# ========
class AnalystConflicts:
    # Defines invoke conflict skill function for this module workflow.
    def invoke_conflict_skill(
        self,
        task: str,
        *,
        context: Any,
        mode: str = "analysis",
    ) -> str:
        skill = conflict_skill_subset(get_skill("conflict-analyzer"), mode)
        messages = self.build_skill_messages(skill, "conflict-analyzer", task, context=context)
        return self.run_skill_messages("conflict-analyzer", messages)

    # Defines run conflict analysis loop function for this module workflow.
    def run_conflict_analysis_loop(self, action: str, **context: Any) -> Any:
        opa = self.run_action_loop(
            name="conflict_analysis",
            context={
                "conflict_action": action,
                **context,
            },
            obs_fn=self.obs_conflict_analysis,
            decide_action=self.decide_conflict_analysis_action,
            execute_action=self.execute_conflict_analysis_action,
        )
        trace = opa.get("opa_trace") or []
        result = dict((trace[-1].get("result") if trace else {}) or {})
        if result.get("error"):
            raise RuntimeError(result.get("error"))
        return result.get("output")

    # Defines obs conflict analysis function for this module workflow.
    def obs_conflict_analysis(self, **kwargs: Any) -> Dict[str, Any]:
        artifact = kwargs.get("artifact") or {}
        return {
            "action": kwargs.get("conflict_action", ""),
            "iteration": kwargs.get("iteration", 0) + 1,
            "max_iterations": kwargs["max_iterations"],
            "requirements_count": len(requirement_discussion_pool(artifact)),
            "conflicts_count": conflict_entries_count(artifact),
            "discussion_rows_count": len(kwargs.get("discussion_rows") or []),
            "proposal_count": len(kwargs.get("proposal_list") or []),
        }

    # Defines decide conflict analysis action function for this module workflow.
    def decide_conflict_analysis_action(
        self,
        *,
        observation: Dict[str, Any],
        last_result: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        if isinstance(last_result, dict) and not last_result.get("error"):
            return {
                "action": "done",
                "params": {},
                "reasoning": "上一輪 conflict analysis 任務已完成，結束本次分析。",
            }
        action = str(observation.get("action") or "").strip()
        return {
            "action": action,
            "params": {},
            "reasoning": f"執行 Analyst conflict analysis 任務：{action}。",
        }

    # Defines execute conflict analysis action function for this module workflow.
    def execute_conflict_analysis_action(
        self,
        *,
        decision: Dict[str, Any],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        action = str(decision.get("action") or "").strip()
        try:
            if action == "detect_pair_conflicts":
                output = self.execute_pairwise_conflict_detection(kwargs.get("artifact") or {})
            elif action == "detect_group_conflicts":
                output = self.execute_group_conflict_detection(kwargs.get("artifact") or {})
            elif action == "review_conflicts":
                output = self.execute_review_conflicts(
                    kwargs.get("proposal_list") or [],
                    kwargs.get("discussion_rows") or [],
                    kwargs.get("extracted_pair_reviews"),
                )
            elif action == "finalize_review":
                output = self.execute_finalize_review(
                    kwargs.get("decision_list") or [],
                    kwargs.get("discussion_rows") or [],
                    kwargs.get("extracted_pair_reviews"),
                )
            elif action == "generate_conflict_report":
                output = self.build_conflict_analysis_report(
                    kwargs.get("artifact") or {},
                    round_num=kwargs.get("round_num"),
                    recent_decisions_limit=kwargs.get("recent_decisions_limit"),
                    previous_report=kwargs.get("previous_report"),
                )
            elif action == "resolve_conflicts":
                output = self.resolve_conflicts(kwargs.get("artifact") or {})
            else:
                raise ValueError(f"未知 conflict action: {action}")
        except Exception as e:
            return {
                "action": action,
                "status": "failed",
                "error": str(e),
                "summary": f"conflict analysis failed: {action}",
            }
        return {
            "action": action,
            "status": "success",
            "output": output,
            "context_updates": {"artifact": output} if isinstance(output, dict) else {},
            "summary": f"完成 conflict analysis: {action}",
        }

    # Defines detect pair conflicts function for this module workflow.
    def detect_pair_conflicts(self, artifact: Dict) -> Dict:
        return self.run_conflict_analysis_loop(
            "detect_pair_conflicts",
            artifact=artifact,
        )

    # Defines detect group conflicts function for this module workflow.
    def detect_group_conflicts(self, artifact: Dict) -> Dict:
        return self.run_conflict_analysis_loop(
            "detect_group_conflicts",
            artifact=artifact,
        )

    # Defines review conflicts function for this module workflow.
    def review_conflicts(
        self,
        proposal_list: List[Dict[str, Any]],
        discussion_rows: List[Dict[str, Any]],
        extracted_pair_reviews: Optional[List[Dict[str, Any]]] = None,
    ) -> tuple[List[Dict[str, Any]], str]:
        return self.run_conflict_analysis_loop(
            "review_conflicts",
            proposal_list=proposal_list,
            discussion_rows=discussion_rows,
            extracted_pair_reviews=extracted_pair_reviews,
        )

    # Defines generate conflict report function for this module workflow.
    def generate_conflict_report(
        self,
        artifact: Dict[str, Any],
        round_num: Optional[int] = None,
        recent_decisions_limit: Optional[int] = None,
        previous_report: Optional[str] = None,
    ) -> str:
        return self.run_conflict_analysis_loop(
            "generate_conflict_report",
            artifact=artifact,
            round_num=round_num,
            recent_decisions_limit=recent_decisions_limit,
            previous_report=previous_report,
        )

    # Defines run pair conflict detection function for this module workflow.
    def run_pair_conflict_detection(
        self,
        *,
        base_task: str,
        context: Dict[str, Any],
        pair_rows: List[Dict[str, Any]],
        pair_count: int,
        heading: str,
        extra_rules: List[str],
        rows_label: str,
        error_label: str,
    ) -> List[Dict[str, Any]]:
        rules = "\n".join(f"- {rule}" for rule in extra_rules)
        task = pair_detection(
            base_task=base_task,
            heading=heading,
            rules=rules,
            rows_label=rows_label,
            pair_rows=pair_rows,
        )
        raw = ""
        try:
            raw = self.invoke_conflict_skill(task, context=context, mode="analysis")
            data = self.parse_issue_response_json(raw)
        except Exception as first_error:
            repair_prompt = render_repair_prompt(
                'pair_repair',
                error_label=error_label,
                pair_rows=pair_rows,
                raw=raw,
            )
            try:
                data = self.chat_json(
                    self.build_direct_messages(repair_prompt, context=context),
                    action=self.usage_action("conflict.repair_pair_json"),
                )
            except Exception as repair_error:
                raw_preview = str(raw or "").strip().replace("\n", "\\n")[:500]
                raise RuntimeError(
                    f"{error_label}輸出格式不合格: {first_error}; "
                    f"修復失敗: {repair_error}; raw_preview={raw_preview}"
                ) from repair_error
        return conflict_records(
            data.get("conflicts", []),
            pairwise_mode=True,
            pair_count=pair_count,
            pair_requirements={
                int(row.get("pair_index")): [
                    str(req.get("id") or "").strip()
                    for req in (row.get("requirements") or [])
                    if isinstance(req, dict) and str(req.get("id") or "").strip()
                ]
                for row in pair_rows
                if isinstance(row, dict)
                and isinstance(row.get("pair_index"), int)
            },
        )

    # Defines conflict detection requirements function for this module workflow.
    def conflict_detection_requirements(self, artifact: Dict) -> List[Dict[str, Any]]:
        return [
            req for req in (artifact.get("URL") or [])
            if isinstance(req, dict)
            and str(req.get("id") or "").strip()
            and str(req.get("text") or "").strip()
        ]

    # Defines conflict detection context function for this module workflow.
    def conflict_detection_context(
        self,
        artifact: Dict,
        requirements: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        context_requirements: List[Dict[str, Any]] = []
        for req in requirements:
            stakeholder = req.get("stakeholder")
            stakeholder_name = (
                str(stakeholder.get("name") or "").strip()
                if isinstance(stakeholder, dict)
                else str(stakeholder or "").strip()
            )
            row = {
                "id": str(req.get("id") or "").strip(),
                "text": str(req.get("text") or "").strip(),
            }
            if stakeholder_name:
                row["stakeholder"] = stakeholder_name
            context_requirements.append(row)

        context: Dict[str, Any] = {}
        scenario_source = artifact.get("scenario") or artifact.get("rough_idea")
        if scenario_source:
            context["scenario"] = str(scenario_source or "").strip()
        if artifact.get("scope"):
            context["scope"] = artifact["scope"]
        context["requirements"] = context_requirements
        return context

    # Defines execute pairwise conflict detection function for this module workflow.
    def execute_pairwise_conflict_detection(self, artifact: Dict) -> Dict:
        requirements = self.conflict_detection_requirements(artifact)
        if len(requirements) < 2:
            return set_pair_conflicts({**artifact}, [])

        context = self.conflict_detection_context(artifact, requirements)
        base_task = conflict_detection_base_task()
        pair_rows = []
        for pair_index, start in enumerate(range(0, len(requirements) - 1, 2)):
            req_a = requirements[start]
            req_b = requirements[start + 1]
            pair_rows.append(
                {
                    "pair_index": pair_index,
                    "requirements": [
                        {
                            "id": req_a.get("id"),
                            "text": req_a.get("text"),
                        },
                        {
                            "id": req_b.get("id"),
                            "text": req_b.get("text"),
                        },
                    ],
                }
            )

        pair_conflicts = self.run_pair_conflict_detection(
            base_task=base_task,
            context=context,
            pair_rows=pair_rows,
            pair_count=len(pair_rows),
            heading="兩兩判斷",
            extra_rules=[
                "只判斷下列指定 pair，pair 之間互相獨立。",
                "配對方式固定為需求順序 1 對 2、3 對 4、5 對 6；若最後剩一筆需求，不判斷。",
                "每一個 pair 都必須輸出恰好一筆結果。",
                "pair_index 必須與下列清單一致。",
                "不需要輸出 requirement_ids，系統會根據 pair_index 自動對回 requirements。",
                "本步只處理指定 pair；群組衝突留給整體判斷。",
            ],
            rows_label="指定 pairs",
            error_label="兩兩 Conflict 分析",
        )
        present_pairs = {
            int(x.get("pair_index"))
            for x in pair_conflicts
            if isinstance(x, dict) and isinstance(x.get("pair_index"), int)
        }
        missing_pairs = [i for i in range(len(pair_rows)) if i not in present_pairs]
        pair_conflict_count = len([x for x in pair_conflicts if x.get("label") == "Conflict"])
        pair_neutral_count = len([x for x in pair_conflicts if x.get("label") == "Neutral"])
        self.logger.info(
            "兩兩衝突判斷 %s 對（Conflict: %s，Neutral: %s，Missing: %s）",
            len(pair_rows),
            pair_conflict_count,
            pair_neutral_count,
            len(missing_pairs),
        )
        if missing_pairs:
            missing_rows = [pair_rows[i] for i in missing_pairs]
            self.logger.info("兩兩衝突補判 %s 對（Missing: %s）", len(missing_rows), len(missing_pairs))
            retry_conflicts = self.run_pair_conflict_detection(
                base_task=base_task,
                context=context,
                pair_rows=missing_rows,
                pair_count=len(pair_rows),
                heading="兩兩 Missing 補判",
                extra_rules=[
                    "只判斷下列 missing pair，pair 之間互相獨立。",
                    "每一個 missing pair 都必須輸出恰好一筆結果。",
                    "pair_index 必須與下列清單一致，不可重新編號。",
                    "不需要輸出 requirement_ids，系統會根據 pair_index 自動對回 requirements。",
                    "輸出只涵蓋下列 missing pair。",
                    "本步只處理指定 pair；群組衝突留給整體判斷。",
                ],
                rows_label="Missing pairs",
                error_label="兩兩 Missing 補判",
            )
            retry_by_pair = {
                int(row.get("pair_index")): row
                for row in retry_conflicts
                if isinstance(row, dict)
                and isinstance(row.get("pair_index"), int)
                and int(row.get("pair_index")) in set(missing_pairs)
            }
            existing_by_pair = {
                int(row.get("pair_index")): row
                for row in pair_conflicts
                if isinstance(row, dict) and isinstance(row.get("pair_index"), int)
            }
            existing_by_pair.update(retry_by_pair)
            pair_conflicts = [
                existing_by_pair[i]
                for i in range(len(pair_rows))
                if i in existing_by_pair
            ]
            still_missing = [
                i for i in range(len(pair_rows))
                if i not in existing_by_pair
            ]
            self.logger.info(
                "兩兩衝突補判完成（補回 %s，仍 Missing: %s）",
                len(retry_by_pair),
                len(still_missing),
            )
            if still_missing:
                raise RuntimeError(f"兩兩 Conflict 分析仍缺少 pair_index: {still_missing}")

        return set_pair_conflicts({**artifact}, pair_conflicts)

    # Defines execute group conflict detection function for this module workflow.
    def execute_group_conflict_detection(self, artifact: Dict) -> Dict:
        requirements = self.conflict_detection_requirements(artifact)
        if len(requirements) < 2:
            self.logger.info("整體衝突判斷 0 組（Conflict: 0）")
            return artifact
        context = self.conflict_detection_context(artifact, requirements)
        pair_conflicts = [
            {
                "id": row.get("id"),
                "requirement_ids": row.get("requirement_ids"),
                "type": row.get("initial_type"),
                "reason": row.get("initial_reason"),
            }
            for row in ((artifact.get("conflict") or {}).get("pairs") or [])
            if isinstance(row, dict) and row.get("label") == "Conflict"
        ]
        context["pairwise_conflicts"] = pair_conflicts
        base_task = conflict_detection_base_task()
        holistic_task = group_detection(base_task=base_task)
        try:
            holistic_raw = self.invoke_conflict_skill(
                holistic_task, context=context, mode="analysis"
            )
            holistic_data = self.parse_issue_response_json(holistic_raw)
        except Exception as first_error:
            repair_prompt = render_repair_prompt('group_repair', holistic_raw=holistic_raw)
            try:
                holistic_data = self.chat_json(
                    self.build_direct_messages(repair_prompt, context=context),
                    action=self.usage_action("conflict.repair_holistic_json"),
                )
            except Exception as repair_error:
                raw_preview = str(holistic_raw or "").strip().replace("\n", "\\n")[:500]
                raise RuntimeError(
                    f"整體 Conflict 分析輸出格式不合格: {first_error}; "
                    f"修復失敗: {repair_error}; raw_preview={raw_preview}"
                ) from repair_error
        holistic_conflicts = [
            row for row in conflict_records(holistic_data.get("conflicts", []))
            if row.get("label") == "Conflict"
            and len(row.get("requirement_ids") or []) >= 2
        ]
        self.logger.info(
            "整體衝突判斷 %s 組（Conflict: %s）",
            len(holistic_conflicts),
            len(holistic_conflicts),
        )

        multiple_rows: List[Dict[str, Any]] = []
        for idx, row in enumerate(holistic_conflicts, 1):
            item = dict(row)
            item["id"] = f"MULTIPLE-{idx}"
            multiple_rows.append(item)
        return set_multiple_conflicts({**artifact}, multiple_rows)

    # Defines execute review conflicts function for this module workflow.
    def execute_review_conflicts(
        self,
        proposal_list: List[Dict[str, Any]],
        discussion_rows: List[Dict[str, Any]],
        extracted_pair_reviews: Optional[List[Dict[str, Any]]] = None,
    ) -> tuple[List[Dict[str, Any]], str]:
        if not proposal_list:
            return [], ""
        prompt = review_signoff(
            proposal_list=proposal_list,
            extracted_pair_reviews=extracted_pair_reviews,
            discussion_rows=discussion_rows,
        )
        messages = self.build_direct_messages(prompt)
        raw = (self.model.chat(messages, action="conflict_recheck_signoff") or "").strip()
        try:
            payload = self.conflict_signoff_payload(self.parse_issue_response_json(raw))
            data = payload.get("decisions", [])
        except Exception as first_error:
            repair_prompt = render_repair_prompt(
                'signoff_repair',
                proposal_list=proposal_list,
                raw=raw,
            )
            repaired = self.model.chat(
                self.build_direct_messages(repair_prompt),
                action="conflict_recheck_signoff_repair",
            ) or ""
            try:
                payload = self.conflict_signoff_payload(self.parse_issue_response_json(repaired))
                data = payload.get("decisions", [])
            except Exception as repair_error:
                raw_preview = raw.strip().replace("\n", "\\n")[:500]
                raise ValueError(
                    f"conflict signoff must return conflict_signoff.decisions: {first_error}; "
                    f"repair failed: {repair_error}; raw_preview={raw_preview}"
                ) from repair_error
        return signoff_decisions(data), raw

    @staticmethod
    # Defines conflict signoff payload function for this module workflow.
    def conflict_signoff_payload(data: Any) -> Dict[str, Any]:
        if not isinstance(data, dict) or not isinstance(data.get("conflict_signoff"), dict):
            raise ValueError("conflict signoff output must contain conflict_signoff object")
        payload = data["conflict_signoff"]
        if not isinstance(payload.get("decisions"), list):
            raise ValueError("conflict_signoff.decisions must be a list")
        return payload

    # Defines finalize review function for this module workflow.
    def finalize_review(
        self,
        decision_list: List[Dict[str, Any]],
        discussion_rows: List[Dict[str, Any]],
        extracted_pair_reviews: Optional[List[Dict[str, Any]]] = None,
    ) -> tuple[List[Dict[str, str]], str]:
        return self.run_conflict_analysis_loop(
            "finalize_review",
            decision_list=decision_list,
            discussion_rows=discussion_rows,
            extracted_pair_reviews=extracted_pair_reviews,
        )

    # Defines execute finalize review function for this module workflow.
    def execute_finalize_review(
        self,
        decision_list: List[Dict[str, Any]],
        discussion_rows: List[Dict[str, Any]],
        extracted_pair_reviews: Optional[List[Dict[str, Any]]] = None,
    ) -> tuple[List[Dict[str, str]], str]:
        if not decision_list:
            return [], ""
        type_guidance = conflict_type_guidance_from_skill()
        prompt = review_reason(
            decision_list=decision_list,
            extracted_pair_reviews=extracted_pair_reviews,
            type_guidance=type_guidance,
        )
        messages = self.build_direct_messages(prompt)
        raw = (self.model.chat(messages, action="reason_check") or "").strip()
        try:
            payload = self.conflict_finalization_payload(self.parse_issue_response_json(raw))
            data = payload.get("reasons", [])
        except Exception as first_error:
            repair_prompt = render_repair_prompt(
                'reason_repair',
                decision_list=decision_list,
                raw=raw,
            )
            repaired = self.model.chat(
                self.build_direct_messages(repair_prompt),
                action="reason_repair",
            ) or ""
            try:
                payload = self.conflict_finalization_payload(self.parse_issue_response_json(repaired))
                data = payload.get("reasons", [])
            except Exception as repair_error:
                raw_preview = raw.strip().replace("\n", "\\n")[:500]
                raise ValueError(
                    f"conflict final reason must return conflict_finalization.reasons: {first_error}; "
                    f"repair failed: {repair_error}; raw_preview={raw_preview}"
                ) from repair_error
        if not isinstance(data, list):
            raise ValueError("conflict_finalization.reasons must be a list")
        out: List[Dict[str, str]] = []
        valid_ids = {
            str(row.get("id") or "").strip()
            for row in decision_list
            if isinstance(row, dict) and str(row.get("id") or "").strip()
        }
        for row in data:
            if not isinstance(row, dict):
                continue
            pair_id = str(row.get("id") or "").strip()
            description = str(row.get("description") or "").strip()
            if pair_id in valid_ids and description:
                decision = next(
                    (item for item in decision_list if isinstance(item, dict) and str(item.get("id") or "").strip() == pair_id),
                    {},
                )
                final_label = str(decision.get("new_label") or decision.get("final_label") or "").strip()
                item = {"id": pair_id, "reason": description}
                final_type = normalize_conflict_type(row.get("final_type") or row.get("type"), final_label=final_label)
                if final_type:
                    item["final_type"] = final_type
                out.append(item)
        return out, raw

    @staticmethod
    # Defines conflict finalization payload function for this module workflow.
    def conflict_finalization_payload(data: Any) -> Dict[str, Any]:
        if not isinstance(data, dict) or not isinstance(data.get("conflict_finalization"), dict):
            raise ValueError("conflict finalization output must contain conflict_finalization object")
        payload = data["conflict_finalization"]
        if not isinstance(payload.get("reasons"), list):
            raise ValueError("conflict_finalization.reasons must be a list")
        return payload

    # Defines build conflict analysis report function for this module workflow.
    def build_conflict_analysis_report(
        self,
        artifact: Dict[str, Any],
        round_num: Optional[int] = None,
        recent_decisions_limit: Optional[int] = None,
        previous_report: Optional[str] = None,
    ) -> str:
        _ = recent_decisions_limit
        conflict_rows = artifact.get("conflict_report", []) or []
        conflict_rows = [
            row for row in conflict_rows
            if isinstance(row, dict) and str(row.get("label") or "").strip() == "Conflict"
        ]
        if not conflict_rows:
            return ""
        context: Any = {
            "conflict_report": conflict_rows,
        }
        previous_report_text = (previous_report or "").strip()
        if previous_report_text:
            context = {
                "previous_conflict_report": previous_report_text,
                "conflict_report": conflict_rows,
            }
            task = update_report()
        else:
            task = create_report()
        try:
            raw = self.invoke_conflict_skill(task, context=context, mode="report")
        except Exception as e:
            raise RuntimeError(f"conflict report 生成失敗: {e}") from e
        out = clean_conflict_report_markdown(raw)
        if not out:
            raise RuntimeError("conflict report 無內容")
        return out

    # Defines resolve conflicts function for this module workflow.
    def resolve_conflicts(self, artifact: Dict[str, Any]) -> Dict[str, Any]:
        conflict_payload = artifact.get("conflict", {}) or {}
        report_rows = (
            conflict_payload.get("report", [])
            if isinstance(conflict_payload, dict)
            else []
        ) or []
        conflict_rows = [
            row for row in report_rows
            if isinstance(row, dict) and str(row.get("label") or "").strip() == "Conflict"
        ]
        if not conflict_rows:
            return artifact
        task = report_resolution()
        by_id: Dict[str, Dict[str, Any]] = {}
        for conflict_row in conflict_rows:
            conflict_id = str(conflict_row.get("id") or "").strip()
            if not conflict_id:
                continue
            conflict_type = str(conflict_row.get("type") or "").strip().lower()
            if conflict_type not in conflict_types:
                raise ValueError(
                    f"conflict resolution requires valid type: {conflict_id}"
                )
            try:
                data = self.parse_issue_response_json(
                    self.invoke_conflict_skill(
                        task,
                        context=conflict_row,
                        mode=f"resolution:{conflict_type}",
                    )
                )
            except Exception as e:
                raise RuntimeError(f"conflict resolution 生成失敗: {conflict_id}: {e}") from e
            if not isinstance(data, dict):
                raise RuntimeError(f"conflict resolution 必須輸出 JSON object: {conflict_id}")
            data = self.conflict_resolution_payload(data)
            returned_id = str(data.get("id") or "").strip()
            if returned_id != conflict_id:
                raise RuntimeError(f"conflict resolution id 不一致: {conflict_id}")
            resolution_options = data.get("resolution_options")
            recommended_resolution = str(data.get("recommended_resolution") or "").strip()
            if not isinstance(resolution_options, list) or not resolution_options:
                raise RuntimeError(f"conflict resolution 缺少 resolution_options: {conflict_id}")
            if not recommended_resolution:
                raise RuntimeError(f"conflict resolution 缺少 recommended_resolution: {conflict_id}")
            clean_options: List[Dict[str, Any]] = []
            for option in resolution_options:
                if not isinstance(option, dict):
                    continue
                clean_option = {
                    "option": str(option.get("option") or "").strip(),
                    "strategy": str(option.get("strategy") or "").strip(),
                    "description": str(option.get("description") or "").strip(),
                    "pros": [
                        str(x).strip()
                        for x in (option.get("pros") or [])
                        if str(x).strip()
                    ],
                    "cons": [
                        str(x).strip()
                        for x in (option.get("cons") or [])
                        if str(x).strip()
                    ],
                    "recommendation": bool(option.get("recommendation")),
                }
                if clean_option["option"] and clean_option["strategy"] and clean_option["description"]:
                    clean_options.append(clean_option)
            if not clean_options:
                raise RuntimeError(f"conflict resolution 沒有有效 options: {conflict_id}")
            by_id[conflict_id] = {
                "resolution_options": clean_options,
                "recommended_resolution": recommended_resolution,
            }

        updated = dict(artifact)
        conflict_state = dict(conflict_payload)
        updated_report: List[Dict[str, Any]] = []
        for row in report_rows:
            if not isinstance(row, dict):
                continue
            item = dict(row)
            conflict_id = str(item.get("id") or "").strip()
            if conflict_id in by_id:
                item.update(by_id[conflict_id])
            updated_report.append(item)
        conflict_state["report"] = updated_report
        updated["conflict"] = conflict_state
        return updated

    @staticmethod
    # Defines conflict resolution payload function for this module workflow.
    def conflict_resolution_payload(data: Any) -> Dict[str, Any]:
        if not isinstance(data, dict) or not isinstance(data.get("conflict_resolution"), dict):
            raise ValueError("conflict resolution output must contain conflict_resolution object")
        return data["conflict_resolution"]
