# Modeler issue logic: propose model issues and build modeler meeting responses.
import json
from typing import Any, Dict, List, Optional

from utils.language import current_output_language

from agents.profile.conflict_review import conflict_review_statement_hint
from agents.profile.analyst.requirements import requirement_discussion_pool

from .prompts import (
    MODELER_CONFLICT_ISSUE_RULES,
    MODELER_CONFLICT_ISSUE_TASK,
    MODELER_ELICITATION_CONTEXT_RULES,
    MODELER_ISSUE_RULES,
    MODELER_ISSUE_TASK,
    modeler_elicitation_action_rules,
    modeler_elicitation_action_task,
)


class ModelerIssues:
    def propose_issues(
        self,
        artifact: Dict[str, Any],
        *,
        round_num: int,
        max_items: int = 2,
    ) -> List[Dict[str, Any]]:
        opa = self.run_action_loop(
            name="modeler_issue_proposal",
            context={
                "artifact": artifact,
                "round_num": round_num,
                "max_items": max(1, max_items),
            },
            build_observation=self.build_modeler_issue_observation,
            decide_action=self.decide_modeler_issue_action,
            execute_action=self.execute_modeler_issue_action,
        )
        trace = opa.get("opa_trace") or []
        result = dict((trace[-1].get("result") if trace else {}) or {})
        if result.get("error"):
            raise RuntimeError(result.get("format_error") or result.get("error"))
        return result.get("proposals", [])[: max(1, max_items)]

    def build_model_issue_signals(self, artifact: Dict[str, Any]) -> List[Dict[str, Any]]:
        signals: List[Dict[str, Any]] = []
        models = (artifact.get("system_models") or {}).get("models") or []
        baseline_candidate_types = {
            "context_diagram",
            "use_case_diagram",
            "activity_diagram",
            "data_flow_diagram",
        }
        existing_types = {m.get("type") for m in models if m.get("type")}
        missing = sorted(list(baseline_candidate_types - existing_types))
        if missing:
            signals.append(
                {
                    "kind": "baseline_candidate_gap",
                    "source_ids": [f"MODEL-GAP-{mtype}" for mtype in missing],
                    "missing_diagram_types": missing,
                    "summary": (
                        "缺少可輔助需求理解的候選基礎圖型；只有在會影響需求理解、"
                        "流程討論、資料流、系統邊界或追蹤性時才需要提案。"
                    ),
                    "suggested_category": "open_question",
                }
            )

        for m in models:
            to_confirm = m.get("to_confirm") or []
            if not to_confirm:
                continue
            mtype = (m.get("type") or "").strip()
            signals.append(
                {
                    "kind": "model_to_confirm",
                    "source_ids": [mtype] if mtype else [],
                    "diagram_type": mtype,
                    "model_name": str(m.get("name") or "").strip(),
                    "summary": "；".join([str(x).strip() for x in to_confirm if str(x).strip()]),
                    "suggested_category": "open_question",
                }
            )
        return signals

    def build_modeler_issue_observation(self, **kwargs: Any) -> Dict[str, Any]:
        artifact = kwargs["artifact"]
        return {
            "iteration": kwargs.get("iteration", 0) + 1,
            "max_iterations": kwargs["max_iterations"],
            "round_num": kwargs.get("round_num"),
            "max_items": kwargs.get("max_items", 2),
            "requirements": requirement_discussion_pool(artifact),
            "current_models": (artifact.get("system_models") or {}).get("models", []),
            "model_issue_signals": self.build_model_issue_signals(artifact),
            "open_questions": artifact.get("open_questions", []),
            "recent_discussions": artifact.get("recent_discussions", []),
            "existing_issue_proposals": artifact.get("issue_proposals", []),
            "decisions": artifact.get("decisions", []),
        }

    def decide_modeler_issue_action(
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
                "reasoning": "上一輪 Modeler issue proposal 已符合格式契約，結束提案。",
            }
        return {
            "action": "propose_model_issues",
            "params": {},
            "reasoning": "根據需求、既有模型、模型待確認事項與近期決策判斷是否需要提出建模相關議題。",
        }

    def execute_modeler_issue_action(
        self,
        *,
        decision: Dict[str, Any],
        observation: Dict[str, Any],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        action = str(decision.get("action") or "").strip()
        if action != "propose_model_issues":
            return {
                "action": action,
                "status": "failed",
                "error": "unsupported_action",
                "format_error": f"Modeler issue proposal 不支援 action: {action}",
            }

        max_items = int(observation.get("max_items") or 2)
        context = {
            "round_num": observation.get("round_num"),
            "requirements": observation.get("requirements", []),
            "current_models": observation.get("current_models", []),
            "model_issue_signals": observation.get("model_issue_signals", []),
            "open_questions": observation.get("open_questions", []),
            "recent_discussions": observation.get("recent_discussions", []),
            "existing_issue_proposals": observation.get("existing_issue_proposals", []),
            "decisions": observation.get("decisions", []),
        }
        prompt = f"""# 任務
提出本輪需要進入 issue proposal 的需求建模議題。

# 提案邊界
- 只提出會影響 system boundary、actor/use case、user workflow、data flow、interaction order、state transition、model traceability 或模型 to_confirm 收斂的議題。
- 可以使用 Context.model_issue_signals 作為候選，但你必須自行判斷是否真的需要成為 issue proposal；候選基礎圖型不是必產物。
- Context.model_issue_signals 可能包含 baseline_candidate_gap 或 model_to_confirm；這些只是候選訊號，不代表一定要提案。
- 若缺少候選圖型但不影響需求理解、流程討論、資料流、系統邊界或追蹤性，不要提案。
- 若模型 to_confirm 已被 existing_issue_proposals 或近期 decisions 覆蓋，不要重複提案。
- 議題必須聚焦模型影響、流程/資料/狀態缺口或模型追蹤性；不得從模型反推新增需求。
- 最多提出 {max_items} 筆；若沒有必要議題，issues 請輸出空陣列。

# 每筆 issue schema
- title：issue proposal 的短標籤，供 triage 參考；正式會議標題由 Mediator 另行命名
- description：說明要釐清的模型缺口、受影響模型元素，以及它如何影響需求理解或追蹤性
- category：只能是 open_question、tradeoff、conflict_discussion 其中之一；不得從模型反推新增需求
- participants：從 modeler、analyst、expert、user 挑選，必須包含 modeler；需要使用者確認流程/資料/狀態時加入 user
- discussion_mode：sequential 或 simultaneous
- speaking_order：必須與 participants 成員一致
- source_ids：相關 requirement/model/open question/signal id；沒有就空陣列
- priority_hint：high / medium / low
- impact_level：high / medium / low
- why_now：說明為何本輪需要處理，而不是延後
- requires_multi_party：true/false
- blocks_decision：true/false
- routing_preference：direct_clarification / formal_meeting / human_decision

# 輸出 JSON
{{"issues": []}}"""
        try:
            data = self.chat_json(self.build_direct_messages(prompt, context=context))
            proposals = self.modeler_issue_proposals_payload(
                data,
                round_num=int(observation.get("round_num") or 0),
                max_items=max_items,
            )
        except Exception as e:
            return {
                "action": action,
                "status": "failed",
                "error": "invalid_issue_proposal_output",
                "format_error": str(e),
                "summary": "Modeler issue proposal 輸出格式不合格",
            }
        return {
            "action": action,
            "status": "success",
            "proposals": proposals,
            "summary": f"Modeler 提出 {len(proposals)} 筆 issue proposal",
        }

    def modeler_issue_proposals_payload(
        self,
        data: Dict[str, Any],
        *,
        round_num: int,
        max_items: int,
    ) -> List[Dict[str, Any]]:
        if not isinstance(data, dict):
            raise ValueError("Modeler issue proposal 必須輸出 JSON object")
        raw_issues = data.get("issues")
        if not isinstance(raw_issues, list):
            raise ValueError("Modeler issue proposal 必須包含 issues list")

        allowed_categories = {
            "conflict_discussion",
            "open_question",
            "tradeoff",
        }
        allowed_participants = {"analyst", "expert", "modeler", "user"}
        allowed_modes = {"sequential", "simultaneous"}
        allowed_priority = {"high", "medium", "low"}
        allowed_routing = {
            "direct_clarification",
            "formal_meeting",
            "human_decision",
        }
        proposals: List[Dict[str, Any]] = []
        seen = set()
        for idx, row in enumerate(raw_issues, 1):
            if not isinstance(row, dict):
                raise ValueError(f"issues[{idx}] 必須是 object")
            title = str(row.get("title") or "").strip()
            description = str(row.get("description") or "").strip()
            category = str(row.get("category") or "").strip()
            why_now = str(row.get("why_now") or "").strip()
            if not title or not description or not why_now:
                raise ValueError(f"issues[{idx}] 缺少 title/description/why_now")
            if category not in allowed_categories:
                raise ValueError(f"issues[{idx}] category 不合法: {category or '<empty>'}")

            participants = [
                str(x).strip()
                for x in (row.get("participants") or [])
                if str(x).strip()
            ]
            participants = list(dict.fromkeys(participants))
            if not participants or any(p not in allowed_participants for p in participants):
                raise ValueError(f"issues[{idx}] participants 不合法")
            if "modeler" not in participants:
                raise ValueError(f"issues[{idx}] participants 必須包含 modeler")

            mode = str(row.get("discussion_mode") or "").strip()
            if mode not in allowed_modes:
                raise ValueError(f"issues[{idx}] discussion_mode 不合法: {mode or '<empty>'}")
            speaking_order = [
                str(x).strip()
                for x in (row.get("speaking_order") or [])
                if str(x).strip()
            ]
            if set(speaking_order) != set(participants):
                raise ValueError(f"issues[{idx}] speaking_order 必須與 participants 成員一致")

            priority = str(row.get("priority_hint") or "").strip().lower()
            impact = str(row.get("impact_level") or "").strip().lower()
            if priority not in allowed_priority:
                raise ValueError(f"issues[{idx}] priority_hint 不合法: {priority or '<empty>'}")
            if impact not in allowed_priority:
                raise ValueError(f"issues[{idx}] impact_level 不合法: {impact or '<empty>'}")
            routing = str(row.get("routing_preference") or "").strip()
            if routing not in allowed_routing:
                raise ValueError(f"issues[{idx}] routing_preference 不合法: {routing or '<empty>'}")

            source_ids = [
                str(x).strip()
                for x in (row.get("source_ids") or [])
                if str(x).strip()
            ]
            key = (category, title, tuple(source_ids))
            if key in seen:
                continue
            seen.add(key)
            proposals.append(
                {
                    "title": title,
                    "description": description,
                    "category": category,
                    "participants": participants,
                    "discussion_mode": mode,
                    "speaking_order": speaking_order,
                    "source_ids": list(dict.fromkeys(source_ids)),
                    "priority_hint": priority,
                    "impact_level": impact,
                    "why_now": why_now,
                    "requires_multi_party": bool(row.get("requires_multi_party")),
                    "blocks_decision": bool(row.get("blocks_decision")),
                    "routing_preference": routing,
                    "proposed_by": "modeler",
                    "round": round_num,
                }
            )
            if len(proposals) >= max_items:
                break
        return proposals

    def build_issue_response_prompt(
        self,
        *,
        issue: Dict[str, Any],
        previous_responses: Optional[List[Dict[str, Any]]],
        artifact_context: Optional[Dict[str, Any]],
    ) -> str:
        issue_text = f"議題 [{issue.get('id', '')}]: {issue.get('title', '')}\n描述: {issue.get('description', '')}"
        issue_id = str(issue.get("id") or "")

        prev_text = ""
        if previous_responses:
            parts = [
                f"【{r.get('agent', '?')}】\n{r.get('response', {}).get('statement', '')}"
                for r in previous_responses
            ]
            prev_text = "\n# 前面的發言\n" + "\n\n".join(parts)

        context_text = ""
        if artifact_context:
            context_text = f"\n# 當前 artifact 分檔內容（供參考）\n{json.dumps(artifact_context, ensure_ascii=False, indent=2)}"

        recent_ask_history_text = ""
        recent_ask_history = issue.get("recent_ask_history") or []
        if recent_ask_history:
            recent_ask_history_text = (
                "\n# 最近幾輪正式提問摘要\n"
                + json.dumps(recent_ask_history, ensure_ascii=False, indent=2)
            )
        my_action_text = ""
        agent_actions = issue.get("agent_actions") if isinstance(issue.get("agent_actions"), dict) else {}
        my_action = agent_actions.get("modeler") if isinstance(agent_actions.get("modeler"), dict) else {}
        if my_action:
            my_action_text = (
                "\n# 本輪你的 action\n"
                + json.dumps(my_action, ensure_ascii=False, indent=2)
            )
        skill_section = ""
        skill_context = self.get_optional_skill_context(issue, artifact_context)
        if skill_context:
            skill_section = f"\n# Skill 參考（本輪由 agent 自行判斷使用）\n{skill_context}\n"
        allow_suggested_next_action = (
            (issue.get("category") or "").strip() != "conflict_discussion"
            and not issue_id.startswith("ELICIT-")
        )

        elicitation_hint = ""
        task_block = MODELER_ISSUE_TASK
        rules_block = MODELER_ISSUE_RULES
        if allow_suggested_next_action:
            rules_block += "\n- 若你認為本議題討論結束後應由外層流程安排下一步，可額外提供 suggested_next_action；這只是建議，不會在會議中直接執行。"
        if (issue.get("category") or "").strip() == "conflict_discussion":
            task_block = MODELER_CONFLICT_ISSUE_TASK
            rules_block = MODELER_CONFLICT_ISSUE_RULES
        if issue_id.startswith("ELICIT-"):
            stop_phrase = (
                "I have gathered enough information"
                if current_output_language() == "en"
                else "我已蒐集足夠資訊"
            )
            elicitation_hint = MODELER_ELICITATION_CONTEXT_RULES
            task_block = modeler_elicitation_action_task(stop_phrase)
            rules_block = modeler_elicitation_action_rules(stop_phrase)
        suggested_next_action_json = ""
        pair_reviews_json = ""
        statement_hint = '"statement": "針對此議題的完整發言內容"'
        if allow_suggested_next_action:
            suggested_next_action_json = """,
    "suggested_next_action": {
        "type": "direct_clarification | new_issue",
        "reason": "為何建議會後安排這一步",
        "target_ids": ["可選，相關 requirement/conflict/issue id"],
        "urgency": "low | medium | high"
    }"""
        if (issue.get("category") or "").strip() == "conflict_discussion":
            pair_reviews_json = ""
            statement_hint = conflict_review_statement_hint()
            output_fields = f"    {statement_hint}"
        else:
            target_json = ""
            if issue_id.startswith("ELICIT-"):
                target_json = ',\n    "target_stakeholders": ["要詢問的 stakeholder 名稱，可一位或多位"]'
            output_fields = (
                f"    {statement_hint}{target_json},\n"
                '    "open_questions": [{"to": "目標 agent 名稱", "question": "問題"}]'
                f"{suggested_next_action_json}{pair_reviews_json}"
            )
        return f"""{issue_text}
    {prev_text}
    {context_text}
    {recent_ask_history_text}
    {my_action_text}
    {skill_section}
    {elicitation_hint}

    # 任務
    {task_block}

    # 規則
    {rules_block}

    # 輸出 JSON
    {{
{output_fields}
    }}"""
