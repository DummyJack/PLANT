# Handles meeting execution, response collection, records, and issue state.
import json
import re

from typing import Any, Dict, List, Optional

from agents.profile.base import action_plan_prompt, action_plan_repair_prompt
from agents.profile.base import render_repair_prompt
from agents.json_schema import ACTION_PLAN_OUTPUT_SCHEMA


class IssueResponseSupport:
    # Checks whether the issue response should allow artifact query tool access.
    def should_use_artifact_query(
        self,
        *,
        issue: Optional[Dict[str, Any]] = None,
        related_context: Optional[Dict[str, Any]] = None,
        previous_responses: Optional[List[Dict[str, Any]]] = None,
    ) -> bool:
        if "artifact_query" not in getattr(self, "tools", {}):
            return False

        def has_artifact_reference(value: Any) -> bool:
            if isinstance(value, str):
                return bool(re.search(r"\b(?:URL|REQ|SM|CR|FB)-\d+\b|\bR\d+-M\d+\b", value))
            if isinstance(value, dict):
                return any(has_artifact_reference(item) for item in value.values())
            if isinstance(value, list):
                return any(has_artifact_reference(item) for item in value)
            return False

        if has_artifact_reference(issue or {}):
            return True
        if has_artifact_reference(previous_responses or []):
            return True
        context = related_context if isinstance(related_context, dict) else {}
        if not context:
            return True
        return has_artifact_reference(context)

    def clean_text(self, text: Any) -> str:
        text = str(text or "").strip()
        if text in {"{}", "[]", "null", '""'}:
            return ""
        return text

    def issue_response_payload(
        self,
        payload: Any,
        *,
        include_stance: bool = True,
        allow_pair_reviews: bool = False,
    ) -> Dict[str, Any]:
        data = dict(payload or {}) if isinstance(payload, dict) else {}
        final_text = self.clean_text(data.get("text"))
        normalized = {
            "text": final_text,
            "open_questions": (
                data.get("open_questions")
                if isinstance(data.get("open_questions"), list)
                else []
            ),
        }
        format_errors: List[str] = []
        if include_stance:
            stance = data.get("stance") if isinstance(data.get("stance"), dict) else {}
            status = str(stance.get("state") or "").strip()
            if status not in {"ready_to_close", "needs_more_discussion"}:
                format_errors.append(
                    "issue response stance.state must be ready_to_close or needs_more_discussion"
                )
                normalized["stance"] = {"state": status} if status else {}
            else:
                normalized["stance"] = {"state": status}
                if bool(stance.get("needs_human_decision")):
                    normalized["stance"]["needs_human_decision"] = True
            proposal = stance.get("proposal") if isinstance(stance.get("proposal"), dict) else None
            if isinstance(proposal, dict) and proposal:
                normalized.setdefault("stance", {})["proposal"] = proposal
        allowed_extra_response_keys = {
            "actions",
            "target_stakeholders",
            "speaking_as",
            "reply_to_question",
            "reply_to_agent",
            "issue_action_results",
            "url_updates",
        }
        if allow_pair_reviews:
            allowed_extra_response_keys.add("pair_reviews")
        for key, value in data.items():
            if key == "stance" and not include_stance:
                continue
            if key in allowed_extra_response_keys and key not in normalized:
                normalized[key] = value
        has_pair_reviews = allow_pair_reviews and isinstance(normalized.get("pair_reviews"), list)
        if not final_text and not has_pair_reviews:
            normalized["error"] = "missing_text"
            format_errors.append("issue response must include a non-empty text field")
        elif include_stance and final_text.startswith(("{", "[")):
            try:
                text_payload = json.loads(final_text)
            except Exception:
                text_payload = None
            if (
                isinstance(text_payload, dict)
                and "pair_reviews" in text_payload
            ) or (
                isinstance(text_payload, list)
                and any(isinstance(item, dict) and "pair_reviews" in item for item in text_payload)
            ):
                normalized["error"] = "invalid_text"
                format_errors.append(
                    "general issue response text must be natural language, not pair_reviews JSON"
                )
        if format_errors:
            normalized["format_error"] = "; ".join(format_errors)
        return normalized

    def chat_for_issue_response(
        self,
        messages: List[Dict],
        parse_json: bool = True,
        *,
        use_tools: bool = False,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        include_stance = bool(kwargs.pop("include_stance", True))
        allow_pair_reviews = bool(kwargs.pop("allow_pair_reviews", False))
        if use_tools and self.tools:
            try:
                raw = self.chat_with_tools(messages)
            except Exception as e:
                self.logger.warning("%s issue.response tool calling failed, fallback to chat_json: %s", self.name, e)
                use_tools = False
            else:
                if parse_json:
                    try:
                        parsed = self.parse_issue_response_json(raw)
                    except ValueError as e:
                        try:
                            required_fields = (
                                "text 與 stance.state"
                                if include_stance
                                else "text"
                            )
                            stance_rule = (
                                "stance.state 只能是 ready_to_close 或 needs_more_discussion。"
                                if include_stance
                                else ""
                            )
                            repair_task = render_repair_prompt(
                                "response_json_repair",
                                required_fields=required_fields,
                                stance_rule=stance_rule,
                                raw=raw,
                            )
                            repair_messages = self.build_direct_messages(repair_task)
                            parsed = self.chat_json(repair_messages)
                        except Exception:
                            return {
                                "text": "",
                                "open_questions": [],
                                "error": "invalid_json",
                                "format_error": str(e),
                            }
                    return self.issue_response_payload(
                        parsed,
                        include_stance=include_stance,
                        allow_pair_reviews=allow_pair_reviews,
                    )
                return {"text": "", "open_questions": [], "error": "invalid_issue_response_mode"}
        action = kwargs.pop("action", f"{self.name}.issue.response")
        try:
            parsed = self.chat_json(messages, action=action, **kwargs)
            return self.issue_response_payload(
                parsed,
                include_stance=include_stance,
                allow_pair_reviews=allow_pair_reviews,
            )
        except Exception as e:
            self.logger.warning("%s issue.response JSON 解析失敗: %s", self.name, e)
            return {
                "text": "",
                "open_questions": [],
                "error": "invalid_json",
                "format_error": str(e),
            }

    def format_previous_responses(
        self,
        previous_responses: Optional[List[Dict[str, Any]]],
        *,
        title: str = "前面的發言",
    ) -> str:
        if not previous_responses:
            return ""
        parts: List[str] = []
        for row in previous_responses:
            agent_name = row.get("agent", "?")
            response = row.get("response", {}) if isinstance(row.get("response"), dict) else {}
            text = response.get("text", "")
            speaking_as = response.get("speaking_as", [])
            if isinstance(speaking_as, str):
                speaking_as = [speaking_as]
            speaking_as = [item for item in speaking_as if isinstance(item, str) and item.strip()]
            role_hint = f"（代表：{'、'.join(speaking_as)}）" if speaking_as else ""
            parts.append(f"【{agent_name}{role_hint}】\n{text}")
        return f"\n# {title}\n" + "\n\n".join(parts)

    def issue_response_observation(
        self,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        issue = kwargs["issue"]
        previous_responses = kwargs.get("previous_responses") or []
        related_context = kwargs.get("related_context")
        if not isinstance(related_context, dict):
            related_context = {}
        issue_summary = {
            "id": str(issue.get("id") or ""),
            "title": str(issue.get("title") or ""),
            "category": str(issue.get("category") or ""),
            "description": str(issue.get("description") or ""),
            "proposed_by": str(issue.get("proposed_by") or ""),
            "participants": issue.get("participants") or [],
            "target_stakeholders": issue.get("target_stakeholders") or [],
            "expected_actions": issue.get("expected_actions") or {},
            "conflict_review_contract": (
                issue.get("conflict_review_contract")
                if isinstance(issue.get("conflict_review_contract"), dict)
                else {}
            ),
            "trace": issue.get("trace") if isinstance(issue.get("trace"), dict) else {},
        }
        return {
            "issue": issue_summary,
            "issue_id": str(issue.get("id") or ""),
            "issue_category": str(issue.get("category") or ""),
            "previous_responses": previous_responses,
            "previous_response_count": len(previous_responses),
            "related_context": related_context,
            "has_related_context": bool(related_context),
            "recent_ask_history": issue.get("recent_ask_history") or [],
            "iteration": kwargs.get("iteration", 0) + 1,
            "max_iterations": kwargs["max_iterations"],
        }

    # Checks whether a general issue may refine existing REQ entries.
    def issue_allows_refine_requirement(self, issue: Dict[str, Any]) -> bool:
        if bool(issue.get("allow_discussion_refine_requirement")):
            return True
        category = str(issue.get("category") or "").strip()
        if category not in {"clarify_requirement", "tradeoff", "align_model"}:
            return False

        def contains_requirement_reference(value: Any) -> bool:
            if isinstance(value, str):
                return "REQ-" in value or "URL-" in value
            if isinstance(value, dict):
                return any(contains_requirement_reference(item) for item in value.values())
            if isinstance(value, list):
                return any(contains_requirement_reference(item) for item in value)
            return False

        return contains_requirement_reference(issue.get("trace")) or contains_requirement_reference(
            issue.get("issue_context")
        )

    # Checks whether a failed broad update should be retried as targeted refinement.
    def should_switch_update_requirement_to_refine(
        self,
        last_result: Optional[Dict[str, Any]],
    ) -> bool:
        if not isinstance(last_result, dict):
            return False
        if str(last_result.get("action") or "").strip() != "update_requirement":
            return False
        error = str(last_result.get("error") or "").lower()
        if not error:
            return False
        local_repair_failures = (
            "requirement title repair failed",
            "non-functional field repair failed",
            "mixed requirement",
            "需求正式化來源追蹤仍未完成",
        )
        return any(marker in error for marker in local_repair_failures)

    def issue_response_decision(
        self,
        observation: Dict[str, Any],
        *,
        done_reasoning: str,
        active_reasoning: str,
        available_actions: Optional[Dict[str, str]] = None,
        default_action: str = "respond_issue",
        last_result: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if isinstance(last_result, dict) and not last_result.get("error"):
            return {
                "action": "done",
                "params": {},
                "reasoning": done_reasoning,
            }
        issue = observation.get("issue") or {}
        if str(issue.get("id") or "").strip() == "OQ":
            return {
                "action": "done",
                "params": {},
                "reasoning": "目前是回答其他參與者提出的問題，直接回覆該問題。",
                "action_plan": {
                    "goal": "回答其他參與者提出的問題",
                    "steps": [
                        {
                            "id": "answer_question",
                            "action": "answer_question",
                            "params": {},
                            "reasoning": "目前是回答其他參與者提出的問題，直接回覆該問題。",
                        }
                    ],
                },
            }
        role = str(getattr(self, "name", self.__class__.__name__) or "").strip()
        actions = dict(available_actions or {})
        if not actions:
            raise RuntimeError(f"{role} issue response has no available actions")
        if default_action not in actions:
            raise RuntimeError(
                f"{role} issue response missing default action: {default_action}"
            )
        category = str(issue.get("category") or "").strip()
        contract = issue.get("conflict_review_contract") if isinstance(issue.get("conflict_review_contract"), dict) else {}
        is_pair_review = (
            category == "resolve_conflict"
            and str(contract.get("type") or "").strip() == "pair_reviews"
        )
        if category != "resolve_conflict":
            actions.pop("discuss_conflict", None)
        expected_actions = issue.get("expected_actions") if isinstance(issue.get("expected_actions"), dict) else {}
        role_expected = expected_actions.get(role)
        if isinstance(role_expected, str):
            role_expected = [role_expected]
        allows_refine_requirement = self.issue_allows_refine_requirement(issue)
        if (
            role == "analyst"
            and allows_refine_requirement
            and self.should_switch_update_requirement_to_refine(last_result)
            and "refine_requirement" in actions
        ):
            return {
                "action": "done",
                "params": {},
                "reasoning": "update_requirement 修復局部 REQ 品質問題失敗，改用 refine_requirement 針對本議題受影響 REQ 做定點修正。",
                "action_plan": {
                    "goal": "改用 refine_requirement 修正局部 REQ 品質問題",
                    "steps": [
                        {
                            "id": "refine_requirement",
                            "action": "refine_requirement",
                            "params": {},
                            "reasoning": "上一輪 update_requirement 的局部 REQ 修復失敗；本議題允許 refine_requirement，應改走定點 refinement。",
                        }
                    ],
                },
            }
        if role == "analyst" and not allows_refine_requirement:
            role_expected = [
                action for action in (role_expected or [])
                if str(action).strip() != "refine_requirement"
            ]
        expected_steps = [
            str(action).strip()
            for action in (role_expected or [])
            if str(action).strip() in actions
        ]
        if expected_steps:
            return {
                "action": "done",
                "params": {},
                "reasoning": "本議題已指定此 agent 的預期 action，依指定順序執行。",
                "action_plan": {
                    "goal": "執行本議題指定的 action",
                    "steps": [
                        {
                            "id": action,
                            "action": action,
                            "params": {},
                            "reasoning": "本議題 expected_actions 指定執行此 action。",
                        }
                        for action in expected_steps
                    ],
                },
            }
        if role == "analyst":
            actions.pop("update_requirement", None)
            if not allows_refine_requirement:
                actions.pop("refine_requirement", None)
            if category != "define_boundary":
                actions.pop("refine_scope", None)
            if is_pair_review and default_action in actions:
                return {
                    "action": "done",
                    "params": {},
                    "reasoning": "本議題是需求衝突再審查，Analyst 以 pair_reviews 專門回覆逐筆審查結果。",
                    "action_plan": {
                        "goal": "逐筆再審查需求衝突 pair",
                        "steps": [
                            {
                                "id": default_action,
                                "action": default_action,
                                "params": {},
                                "reasoning": "pair review 會議應使用 respond_issue 產生 pair_reviews，不使用一般 conflict resolution action。",
                            }
                        ],
                    },
                }
            if category == "resolve_conflict" and "discuss_conflict" in actions:
                return {
                    "action": "done",
                    "params": {},
                    "reasoning": "本議題是需求衝突解決，Analyst 直接討論既有衝突報告與可採用解法。",
                    "action_plan": {
                        "goal": "討論並收斂既有需求衝突",
                        "steps": [
                            {
                                "id": "discuss_conflict",
                                "action": "discuss_conflict",
                                "params": {},
                                "reasoning": "resolve_conflict 類議題應使用既有 conflict report 討論解法，不重新正式化 REQ。",
                            }
                        ],
                    },
                }
        if category == "resolve_conflict" and default_action in actions:
            return {
                "action": "done",
                "params": {},
                "reasoning": "本議題是需求衝突解決，非 Analyst agent 直接提供專業審查意見。",
                "action_plan": {
                    "goal": "針對既有需求衝突提供專業審查意見",
                    "steps": [
                        {
                            "id": default_action,
                            "action": default_action,
                            "params": {},
                            "reasoning": "resolve_conflict 類議題已由 Analyst 負責寫回，其他 agent 聚焦審查理由與風險判斷。",
                        }
                    ],
                },
            }
        if role == "modeler" and category == "align_model" and "system_modeling" in actions:
            return {
                "action": "done",
                "params": {},
                "reasoning": "本議題是模型對齊，Modeler 直接建立或更新系統模型。",
                "action_plan": {
                    "goal": "用系統模型釐清需求、流程、狀態或邊界",
                    "steps": [
                        {
                            "id": "system_modeling",
                            "action": "system_modeling",
                            "params": {},
                            "reasoning": "align_model 類議題應優先使用模型結果，而不是只做一般發言。",
                        }
                    ],
                },
            }
        actions_text = "\n".join(
            f"- {name}：{description}"
            for name, description in actions.items()
        )
        recent_responses = []
        for row in (observation.get("previous_responses") or []):
            if not isinstance(row, dict):
                continue
            response = row.get("response") if isinstance(row.get("response"), dict) else {}
            text = str(response.get("text") or "").strip()
            if not text:
                continue
            recent_responses.append(
                {
                    "agent": str(row.get("agent") or "").strip(),
                    "actions": response.get("actions") if isinstance(response.get("actions"), list) else [],
                    "text": text,
                    "open_questions": response.get("open_questions") if isinstance(response.get("open_questions"), list) else [],
                }
            )
        prompt = action_plan_prompt(
            role=role,
            issue=issue,
            issue_category=observation.get("issue_category"),
            previous_response_count=observation.get("previous_response_count", 0),
            recent_responses=recent_responses,
            has_related_context=observation.get("has_related_context", False),
            recent_ask_history=observation.get("recent_ask_history", []),
            actions_text=actions_text,
            default_action=default_action,
        )
        def parse_decision(prompt_text: str) -> Optional[Dict[str, Any]]:
            decision = self.chat_json(
                self.build_direct_messages(prompt_text),
                action=f"{role}.issue.decide_action",
                schema=ACTION_PLAN_OUTPUT_SCHEMA,
            )
            raw_steps = decision.get("steps") if isinstance(decision.get("steps"), list) else []
            steps = []
            for raw_step in raw_steps:
                if not isinstance(raw_step, dict):
                    continue
                step_action = str(raw_step.get("action") or "").strip()
                if step_action not in actions:
                    continue
                steps.append(
                    {
                        "id": str(raw_step.get("id") or step_action).strip() or step_action,
                        "action": step_action,
                        "params": raw_step.get("params") if isinstance(raw_step.get("params"), dict) else {},
                        "reasoning": str(raw_step.get("reasoning") or "").strip(),
                    }
                )
            if steps:
                filtered_steps = []
                seen_step_actions = set()
                for step in steps:
                    step_action = str(step.get("action") or "").strip()
                    if step_action in seen_step_actions:
                        continue
                    if step_action == "analyze_conflicts" and "analyze_requirements" not in seen_step_actions:
                        continue
                    filtered_steps.append(step)
                    seen_step_actions.add(step_action)
                steps = filtered_steps
            if steps:
                reasoning = str(decision.get("reasoning") or active_reasoning).strip()
                return {
                    "action": "done",
                    "params": {},
                    "reasoning": reasoning,
                    "action_plan": {
                        "goal": str(decision.get("goal") or "本次正式會議發言").strip(),
                        "steps": steps,
                    },
                }

            return None

        try:
            parsed_decision = parse_decision(prompt)
            if parsed_decision:
                return parsed_decision
            raise RuntimeError("action_plan has no valid steps")
        except Exception as e:
            self.logger.warning("%s issue action 決策失敗，重試 action plan: %s", role, e)
            try:
                repair_prompt = action_plan_repair_prompt(
                    original_prompt=prompt,
                    format_error=str(e),
                    default_action=default_action,
                )
                parsed_decision = parse_decision(repair_prompt)
                if parsed_decision:
                    return parsed_decision
                raise RuntimeError("action_plan has no valid steps")
            except Exception as retry_error:
                raise RuntimeError(f"{role} issue action plan retry failed: {retry_error}") from retry_error
