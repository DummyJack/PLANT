# Analyst conflict logic: detect, recheck, sign off, and report requirement conflicts.
import json
import re
from typing import Any, Dict, List, Optional

from storage.markdown import clean_llm_output
from agents.skills.base import get_skill
from agents.profile.scenario import scenario_prompt_value
from agents.profile.conflict_review import CONFLICT_REVIEW_LABEL_RULES

from .conflict_store import (
    conflict_entries_count,
    set_multiple_conflicts,
    set_pair_conflicts,
)
from .requirements import requirement_discussion_pool
from .validation import conflict_records, signoff_decisions
from .prompts import conflict_skill_subset


CONFLICT_TYPE_VALUES = {
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
        if title not in CONFLICT_TYPE_VALUES:
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


def normalize_conflict_type(value: Any, *, final_label: str) -> str:
    if final_label != "Conflict":
        return ""
    conflict_type = str(value or "").strip().lower()
    return conflict_type if conflict_type in CONFLICT_TYPE_VALUES else "other"


class AnalystConflicts:
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

    def run_conflict_analysis_loop(self, action: str, **context: Any) -> Any:
        opa = self.run_action_loop(
            name="conflict_analysis",
            context={
                "conflict_action": action,
                **context,
            },
            build_observation=self.build_conflict_analysis_observation,
            decide_action=self.decide_conflict_analysis_action,
            execute_action=self.execute_conflict_analysis_action,
        )
        trace = opa.get("opa_trace") or []
        result = dict((trace[-1].get("result") if trace else {}) or {})
        if result.get("error"):
            raise RuntimeError(result.get("error"))
        return result.get("output")

    def build_conflict_analysis_observation(self, **kwargs: Any) -> Dict[str, Any]:
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

    def execute_conflict_analysis_action(
        self,
        *,
        decision: Dict[str, Any],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        action = str(decision.get("action") or "").strip()
        try:
            if action == "run_pairwise_conflict_detection":
                output = self.execute_pairwise_conflict_detection(kwargs.get("artifact") or {})
            elif action == "run_group_conflict_detection":
                output = self.execute_group_conflict_detection(kwargs.get("artifact") or {})
            elif action == "signoff_conflict_recheck":
                output = self.execute_signoff_conflict_recheck(
                    kwargs.get("proposal_list") or [],
                    kwargs.get("discussion_rows") or [],
                    kwargs.get("extracted_pair_reviews"),
                )
            elif action == "finalize_conflict_review_reasons":
                output = self.execute_finalize_conflict_review_reasons(
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
            elif action == "generate_conflict_resolutions":
                output = self.build_conflict_resolutions(kwargs.get("artifact") or {})
            elif action == "get_resolution_options_for_issue":
                output = self.fetch_resolution_options_for_issue(
                    kwargs.get("issue") or {},
                    kwargs.get("artifact") or {},
                )
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

    def run_pairwise_conflict_detection(self, artifact: Dict) -> Dict:
        return self.execute_pairwise_conflict_detection(artifact)

    def signoff_conflict_recheck(
        self,
        proposal_list: List[Dict[str, Any]],
        discussion_rows: List[Dict[str, Any]],
        extracted_pair_reviews: Optional[List[Dict[str, Any]]] = None,
    ) -> tuple[List[Dict[str, Any]], str]:
        return self.run_conflict_analysis_loop(
            "signoff_conflict_recheck",
            proposal_list=proposal_list,
            discussion_rows=discussion_rows,
            extracted_pair_reviews=extracted_pair_reviews,
        )

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

    def generate_conflict_resolutions(self, artifact: Dict[str, Any]) -> Dict[str, Any]:
        return self.run_conflict_analysis_loop(
            "generate_conflict_resolutions",
            artifact=artifact,
        )

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
        task = base_task + f"""

【{heading}】
{rules}

{rows_label}：
{json.dumps(pair_rows, ensure_ascii=False, indent=2)}

只輸出一個 JSON 物件：{{"conflicts":[...]}}。勿輸出 Markdown 或其他文字。"""
        try:
            raw = self.invoke_conflict_skill(task, context=context, mode="analysis")
            data = self.parse_issue_response_json(raw)
        except Exception as e:
            raise RuntimeError(f"{error_label}輸出格式不合格: {e}") from e
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

    def conflict_detection_requirements(self, artifact: Dict) -> List[Dict[str, Any]]:
        return [
            req for req in (artifact.get("URL") or [])
            if isinstance(req, dict)
            and str(req.get("id") or "").strip()
            and str(req.get("text") or "").strip()
        ]

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
            context["scenario"] = scenario_prompt_value(scenario_source)
        if artifact.get("scope"):
            context["scope"] = artifact["scope"]
        context["requirements"] = context_requirements
        return context

    def conflict_detection_base_task(self) -> str:
        return """僅根據輸入的 User Requirements 判斷 Conflict / Neutral；本步不看系統模型或其他回饋。

本專案覆蓋規則：
- 本步只做 requirement candidate conflict classification，不做報告或解決方案建議。
- 不改寫需求、不要新增需求、不要提出解決方案、不要做 meeting decision。
- 只輸出呼叫端指定的 JSON。
- 產品情境與需求範圍只作為產品邊界背景；Conflict / Neutral 仍以 User Requirements 原文為主要依據。

判斷任務：
- label 只用英文 "Conflict" 或 "Neutral"。
- 若 label 是 "Conflict"，必須輸出 type；type 只能是 logical、technical、resource、temporal、data、state、priority、scope、other。
- 若無法歸入前八類但仍是 Conflict，type 使用 other。
- 若 label 是 "Neutral"，不要輸出 type。
- 檢查所有有分析價值的需求對或需求群；不同互斥核心請拆成不同項目。
- 若需求不能原樣共同放入 SRS，必須先合併、改寫、刪除或人工裁定，標為 Conflict。
- 若判定為 Neutral，reason 需說明為何兩者不產生需求衝突。

輸出要求：
- 兩兩判斷：只需輸出 pair_index、label、reason；若 label 是 Conflict，再輸出 type。
- 整體判斷：Conflict 需包含 requirement_ids 或 related_requirements。
- 整體判斷的 requirement_ids 必須精確對應直接涉及的需求；無法明確對應就不要臆測。
"""

    def execute_pairwise_conflict_detection(self, artifact: Dict) -> Dict:
        """用 URL 做相鄰兩兩需求衝突判斷。"""
        requirements = [
            req for req in (artifact.get("URL") or [])
            if isinstance(req, dict)
            and str(req.get("id") or "").strip()
            and str(req.get("text") or "").strip()
        ]
        if len(requirements) < 2:
            return set_pair_conflicts({**artifact}, [])

        context = self.conflict_detection_context(artifact, requirements)
        base_task = self.conflict_detection_base_task()
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
                "不要輸出 3 條以上需求共同造成的群組衝突。",
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
                    "不要輸出清單以外的 pair。",
                    "不要輸出 3 條以上需求共同造成的群組衝突。",
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

    def execute_group_conflict_detection(self, artifact: Dict) -> Dict:
        """用 URL 做 3+ 需求群組衝突判斷，並附加到既有兩兩結果。"""
        requirements = self.conflict_detection_requirements(artifact)
        if len(requirements) < 3:
            self.logger.info("整體衝突判斷 0 組（Conflict: 0）")
            return artifact
        context = self.conflict_detection_context(artifact, requirements)
        base_task = self.conflict_detection_base_task()
        holistic_task = base_task + """

【整體判斷】
- 只找出需要 3 條以上需求同時成立才會產生的群組衝突。
- 不要重複輸出兩兩 pair 已可判斷的衝突。
- 每筆 Conflict 的 requirement_ids 必須包含 3 個以上需求 id。
- 若沒有 3 條以上需求共同造成的衝突，輸出 {"conflicts": []}。
- 本步只輸出 label="Conflict" 的項目，不需要輸出 Neutral。

只輸出一個 JSON 物件：{"conflicts":[...]}。勿輸出 Markdown 或其他文字。"""
        try:
            holistic_raw = self.invoke_conflict_skill(
                holistic_task, context=context, mode="analysis"
            )
            holistic_data = self.parse_issue_response_json(holistic_raw)
        except Exception as e:
            raise RuntimeError(f"整體 Conflict 分析輸出格式不合格: {e}") from e
        holistic_conflicts = [
            row for row in conflict_records(holistic_data.get("conflicts", []))
            if row.get("label") == "Conflict"
            and len(row.get("requirement_ids") or []) >= 3
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

    def execute_signoff_conflict_recheck(
        self,
        proposal_list: List[Dict[str, Any]],
        discussion_rows: List[Dict[str, Any]],
        extracted_pair_reviews: Optional[List[Dict[str, Any]]] = None,
    ) -> tuple[List[Dict[str, Any]], str]:
        """Analyst 根據逐項 review、原文與會議發言做需求關係標籤確認。"""
        if not proposal_list:
            return [], ""
        prompt = (
            "請根據 requirements 原文與各 agent 的逐筆 pair_reviews，"
            "對每筆 Conflict/Neutral 項目做最終裁定。\n\n"
            f"# 待裁定項目\n{json.dumps(proposal_list, ensure_ascii=False, indent=2)}\n\n"
            f"# 各 agent 的 pair_reviews\n{json.dumps(extracted_pair_reviews or [], ensure_ascii=False, indent=2)}\n\n"
            f"# 補充會議內容（僅在 pair_reviews 不足時參考）\n{json.dumps(discussion_rows, ensure_ascii=False, indent=2)}\n\n"
            "# 裁定規則\n"
            "- 先看 requirements 原文，再看各 agent 的 pair_reviews。\n"
            "- discussion_rows 只在 pair_reviews 證據不足時作補充參考。\n"
            "- 若 pair_reviews 與 pair 原文足以支持改判，new_label 可改為 Conflict 或 Neutral。\n"
            "- 若 extracted_pair_reviews 為空，預設維持 current_label，除非 requirements 原文本身已足以明確推翻現標籤。\n"
            "- 若證據不足、理由不一致或沒有明確共識，維持 current_label。\n"
            f"{CONFLICT_REVIEW_LABEL_RULES}\n"
            "- 你必須對 proposal_list 中的每一個項目都輸出一筆 decision；即使決定維持 current_label，也不可省略。\n"
            "- 只輸出 JSON array，不要輸出 Markdown、程式碼區塊、前言或額外說明。\n"
            "- 請直接做最終裁定，不要重述整場會議。\n\n"
            "# 輸出 JSON array\n"
            '[{"id": "衝突ID", "new_label": "Conflict 或 Neutral", '
            '"reason": "一句繁中裁定理由"}]'
        )
        messages = self.build_direct_messages(prompt)
        raw = (self.model.chat(messages, action="conflict_recheck_signoff") or "").strip()
        text = raw
        if text.startswith("```json"):
            text = text[len("```json") :].strip()
        elif text.startswith("```"):
            text = text[len("```") :].strip()
        if text.endswith("```"):
            text = text[:-3].strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError("conflict signoff must return a JSON array") from e
        if not isinstance(data, list):
            raise ValueError("conflict signoff must return a JSON array")
        return signoff_decisions(data), raw

    def finalize_conflict_review_reasons(
        self,
        decision_list: List[Dict[str, Any]],
        discussion_rows: List[Dict[str, Any]],
        extracted_pair_reviews: Optional[List[Dict[str, Any]]] = None,
    ) -> tuple[List[Dict[str, str]], str]:
        return self.run_conflict_analysis_loop(
            "finalize_conflict_review_reasons",
            decision_list=decision_list,
            discussion_rows=discussion_rows,
            extracted_pair_reviews=extracted_pair_reviews,
        )

    def execute_finalize_conflict_review_reasons(
        self,
        decision_list: List[Dict[str, Any]],
        discussion_rows: List[Dict[str, Any]],
        extracted_pair_reviews: Optional[List[Dict[str, Any]]] = None,
    ) -> tuple[List[Dict[str, str]], str]:
        """Analyst 整理已定案的衝突再審查理由。"""
        if not decision_list:
            return [], ""
        type_guidance = conflict_type_guidance_from_skill()
        prompt = (
            f"# 已定案項目\n{json.dumps(decision_list, ensure_ascii=False, indent=2)}\n\n"
            f"# 各 agent 逐筆理由\n{json.dumps(extracted_pair_reviews or [], ensure_ascii=False, indent=2)}\n\n"
            f"# 衝突類型指引（摘自 conflict-analyzer skill）\n{type_guidance}\n\n"
            "# 任務\n"
            "請為每個已定案項目整理 description；若 final_label 是 Conflict，也要根據討論後的主要衝突原因判定 final_type。\n\n"
            "description 用來寫入 artifact/conflict.json，作為該項 final_label 的最終說明。\n"
            "請根據 final_label 與各 agent 逐筆理由，整理出一段清楚、精簡、可追溯的裁定描述。\n\n"
            "# 撰寫重點\n"
            "- 若 final_label 是 Conflict：說明需求之間的主要衝突點，或為什麼需要合併、改寫、刪除或裁定。\n"
            "- 若 final_label 是 Conflict：必須輸出 final_type；final_type 只能是 logical、technical、resource、temporal、data、state、priority、scope、other。\n"
            "- final_type 根據討論後的主要衝突原因決定，不必沿用 initial_type；若無法歸入前八類但仍是 Conflict，使用 other。\n"
            "- 若 final_label 是 Neutral：說明為什麼需求之間不構成衝突。\n"
            "- 若 final_label 是 Neutral：不要輸出 final_type。\n"
            "- 使用各 agent 已提出的理由，不要加入新的需求解釋或新的判準。\n"
            "- 不要逐一列出 agent 名稱或投票過程。\n"
            "- 不要重述完整需求原文。\n\n"
            "# 輸出 JSON array\n"
            '[{"id": "PAIR-1", "description": "Conflict 的最終裁定描述", "final_type": "scope"}, '
            '{"id": "PAIR-2", "description": "Neutral 的最終裁定描述"}]'
        )
        messages = self.build_direct_messages(prompt)
        raw = (self.model.chat(messages, action="conflict_recheck_final_reason") or "").strip()
        text = raw
        if text.startswith("```json"):
            text = text[len("```json") :].strip()
        elif text.startswith("```"):
            text = text[len("```") :].strip()
        if text.endswith("```"):
            text = text[:-3].strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError("conflict final reason must return a JSON array") from e
        if not isinstance(data, list):
            raise ValueError("conflict final reason must return a JSON array")
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

    def build_conflict_analysis_report(
        self,
        artifact: Dict[str, Any],
        round_num: Optional[int] = None,
        recent_decisions_limit: Optional[int] = None,
        previous_report: Optional[str] = None,
    ) -> str:
        """根據已定案的 conflict report rows 產出 Markdown 報告。"""
        _ = recent_decisions_limit
        conflict_rows = artifact.get("conflict_report", []) or []
        conflict_rows = [
            row for row in conflict_rows
            if isinstance(row, dict) and str(row.get("label") or "").strip() == "Conflict"
        ]
        if not conflict_rows:
            return ""
        context: Any = {
            "scenario": str(artifact.get("scenario") or "").strip(),
            "conflict_report": conflict_rows,
        }
        previous_report_text = (previous_report or "").strip()
        if previous_report_text:
            context = {
                "scenario": str(artifact.get("scenario") or "").strip(),
                "previous_conflict_report": previous_report_text,
                "conflict_report": conflict_rows,
            }
            task = """根據 previous_conflict_report 與 conflict_report 修訂需求衝突 Markdown 報告。

本專案約束：
- 每筆 conflict_report 都要列入報告。
- 保留上一版仍有效內容，移除與最新 conflict_report 不一致的內容。
- 只渲染輸入資料，不重新分類、不新增或移除項目。
- description、resolution_options、recommended_resolution 視為已定案內容，不可改寫。
- 報告 H1 標題使用 scenario；若 scenario 為空，使用「需求衝突報告」。
- 不要產生 Executive Summary。
- 不要產生整體 recommendations 區塊。

只輸出 Markdown。"""
        else:
            task = """根據 conflict_report 產生需求衝突 Markdown 報告。

本專案約束：
- 每筆輸入都要列入報告。
- 只渲染輸入資料，不重新分類、不新增或移除項目。
- description、resolution_options、recommended_resolution 視為已定案內容，不可改寫。
- 報告 H1 標題使用 scenario；若 scenario 為空，使用「需求衝突報告」。
- 不要產生 Executive Summary。
- 不要產生整體 recommendations 區塊。

只輸出 Markdown。"""
        try:
            raw = self.invoke_conflict_skill(task, context=context, mode="report")
        except Exception as e:
            raise RuntimeError(f"conflict report 生成失敗: {e}") from e
        out = clean_llm_output(raw)
        if not out:
            raise RuntimeError("conflict report 無內容")
        return out

    def build_conflict_resolutions(self, artifact: Dict[str, Any]) -> Dict[str, Any]:
        """Use conflict skill resolution guidance to enrich conflict.report rows."""
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
        task = """根據單一已定案 Conflict 項目產生 resolution options。

本專案約束：
- 輸入資料已完成衝突辨識與衝突再審查。
- 不重新分類、不新增衝突、不移除衝突。
- label、type、description 視為定案內容。
- type 只作為策略候選方向；實際 resolution 必須根據 requirements 與 description 決定。
- 若 type 是 other，不要硬套特定衝突類型；請根據 requirements 與 description 產生可行 resolution。
- 若本任務沒有提供 resolution strategy guidance，代表此 Conflict 無對應類型策略；請只根據 requirements 與 description 產生 resolution。
- id 必須使用輸入 Conflict 項目的 id，不可自行產生 CONF-* 或 CR-*。
- requirements id 與 text 只作為判斷依據，不可改寫。
- 不要輸出 effort、impact 或輸出契約以外欄位。
- 只輸出本任務指定的合法 JSON 格式。

# 輸出 JSON
{
  "id": "Conflict 項目 id",
  "resolution_options": [
    {
      "option": "A",
      "strategy": "Resolution strategy name",
      "description": "處理方式",
      "pros": ["優點"],
      "cons": ["限制或代價"],
      "recommendation": true
    }
  ],
  "recommended_resolution": "建議採用的 resolution 與理由"
}"""
        by_id: Dict[str, Dict[str, Any]] = {}
        for conflict_row in conflict_rows:
            conflict_id = str(conflict_row.get("id") or "").strip()
            if not conflict_id:
                continue
            conflict_type = str(conflict_row.get("type") or "").strip().lower() or "other"
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
