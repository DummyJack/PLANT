import json

# Issue response support shared by meeting-capable agents.
from typing import Any, Dict, List, Optional

from .issue_response_prompt import issue_response_action_plan_prompt


class IssueResponseSupport:
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
        """有 tools 可切換為 chat_with_tools，否則使用 chat_json。"""
        include_stance = bool(kwargs.pop("include_stance", True))
        allow_pair_reviews = bool(kwargs.pop("allow_pair_reviews", False))
        if use_tools and self.tools:
            raw = self.chat_with_tools(messages)
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
                        repair_messages = self.build_direct_messages(
                            "上一個回覆不是合法 JSON object。請只修正格式，不要重新分析、不要新增內容。"
                            f"輸出必須是單一 JSON object，且至少保留 {required_fields}。"
                            f"{stance_rule}\n\n"
                            f"原始回覆：\n{raw}"
                        )
                        repaired = self.model.chat(repair_messages)
                        parsed = self.parse_issue_response_json(repaired)
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
        """格式化前文發言（含 speaking_as）。"""
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
        artifact_context = kwargs.get("artifact_context") or self.load_artifact_context_from_files()
        return {
            "issue": issue,
            "issue_id": str(issue.get("id") or ""),
            "issue_category": str(issue.get("category") or ""),
            "previous_responses": previous_responses,
            "previous_response_count": len(previous_responses),
            "artifact_context": artifact_context,
            "has_artifact_context": bool(artifact_context),
            "recent_ask_history": issue.get("recent_ask_history") or [],
            "iteration": kwargs.get("iteration", 0) + 1,
            "max_iterations": kwargs["max_iterations"],
        }

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
        actions = dict(available_actions or {default_action: "一般正式會議發言。"})
        if default_action not in actions:
            actions[default_action] = "預設正式會議發言。"
        if str(issue.get("category") or "").strip() != "resolve_conflict":
            actions.pop("discuss_conflict", None)
        expected_actions = issue.get("expected_actions") if isinstance(issue.get("expected_actions"), dict) else {}
        role_expected = expected_actions.get(role)
        if isinstance(role_expected, str):
            role_expected = [role_expected]
        expected_steps = [
            str(action).strip()
            for action in (role_expected or [])
            if str(action).strip() in actions
        ]
        if "discuss_conflict" in actions and "discuss_conflict" not in expected_steps:
            actions = {name: desc for name, desc in actions.items() if name != "discuss_conflict"}
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
                        for action in expected_steps[:3]
                    ],
                },
            }
        actions_text = "\n".join(
            f"- {name}：{description}"
            for name, description in actions.items()
        )
        recent_responses = []
        for row in (observation.get("previous_responses") or [])[-6:]:
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
                    "text": text[:600],
                    "open_questions": response.get("open_questions") if isinstance(response.get("open_questions"), list) else [],
                }
            )
        prompt = issue_response_action_plan_prompt(
            role=role,
            issue=issue,
            issue_category=observation.get("issue_category"),
            previous_response_count=observation.get("previous_response_count", 0),
            recent_responses=recent_responses,
            has_artifact_context=observation.get("has_artifact_context", False),
            recent_ask_history=observation.get("recent_ask_history", []),
            actions_text=actions_text,
            default_action=default_action,
        )
        def _parse_decision() -> Optional[Dict[str, Any]]:
            decision = self.chat_json(self.build_direct_messages(prompt), action=f"{role}.issue.decide_action")
            action_plan = decision.get("action_plan") if isinstance(decision.get("action_plan"), dict) else {}
            raw_steps = action_plan.get("steps") if isinstance(action_plan.get("steps"), list) else []
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
                selected_steps = steps[:3]
                deferred_steps = steps[3:]
                reasoning = str(decision.get("reasoning") or active_reasoning).strip()
                if deferred_steps:
                    deferred_names = ", ".join(
                        str(step.get("action") or "").strip()
                        for step in deferred_steps
                        if str(step.get("action") or "").strip()
                    )
                    if deferred_names:
                        reasoning = (
                            f"{reasoning}；本次最多執行 3 個 action，"
                            f"其餘 action 延後到下一輪：{deferred_names}。"
                        )
                return {
                    "action": "done",
                    "params": {},
                    "reasoning": reasoning,
                    "action_plan": {
                        "goal": str(action_plan.get("goal") or "本次正式會議發言").strip(),
                        "steps": selected_steps,
                    },
                }

            return None

        try:
            parsed_decision = _parse_decision()
            if parsed_decision:
                return parsed_decision
            raise RuntimeError("action_plan has no valid steps")
        except Exception as e:
            self.logger.warning("%s issue action 決策失敗，重試 action plan: %s", role, e)
            try:
                parsed_decision = _parse_decision()
                if parsed_decision:
                    return parsed_decision
                raise RuntimeError("action_plan has no valid steps")
            except Exception as retry_error:
                raise RuntimeError(f"{role} issue action plan retry failed: {retry_error}") from retry_error
