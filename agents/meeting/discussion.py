# Handles meeting execution, response collection, records, and issue state.
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

from agents.tools.artifact_query import ArtifactQueryTool
from agents.profile.base import retry_response
from agents.meeting.pair_review import normalize_pair_review_record


class MediatorDiscussion:
    related_id_re = re.compile(r"\b(?:URL|REQ|SM|CR)-\d+\b")
    conflict_update_actions = frozenset({"keep", "revise", "remove"})
    recordable_action_result_keys = {
        "REQ",
        "URL",
        "conflict_report",
        "feedback",
        "scope",
        "scope_updates",
        "system_models",
        "model_changes",
    }

    @classmethod
    def recordable_issue_action_result(
        cls,
        action_name: str,
        action_result: Any,
    ) -> bool:
        action = str(action_name or "").strip()
        if action == "respond_issue":
            return False
        if not isinstance(action_result, dict):
            return bool(action)
        result_action = str(action_result.get("action") or action).strip()
        if result_action == "respond_issue":
            return False
        if result_action:
            return True
        return any(
            action_result.get(key) not in (None, "", [], {})
            for key in cls.recordable_action_result_keys
        )

    @classmethod
    def related_context_targets(
        cls,
        issue: Dict[str, Any],
        previous_responses: Optional[List[Dict[str, Any]]],
    ) -> List[str]:
        texts: List[str] = []
        for key in ("id", "title", "description", "category", "issue_focus", "expect_outcome"):
            value = (issue or {}).get(key)
            if value:
                texts.append(str(value))
        for key in ("trace",):
            value = (issue or {}).get(key)
            if value:
                texts.append(json.dumps(value, ensure_ascii=False))
        for row in (previous_responses or [])[-6:]:
            if not isinstance(row, dict):
                continue
            response = row.get("response") if isinstance(row.get("response"), dict) else {}
            text = response.get("text")
            if text:
                texts.append(str(text))
            open_questions = response.get("open_questions")
            if open_questions:
                texts.append(json.dumps(open_questions, ensure_ascii=False))
        ids: List[str] = []
        for text in texts:
            for item_id in cls.related_id_re.findall(text):
                if item_id not in ids:
                    ids.append(item_id)
        return ids

    @classmethod
    def enrich_related_context(
        cls,
        related_context: Optional[Dict[str, Any]],
        artifact: Optional[Dict[str, Any]],
        issue: Dict[str, Any],
        previous_responses: Optional[List[Dict[str, Any]]],
    ) -> Dict[str, Any]:
        context = dict(related_context or {})
        if not isinstance(artifact, dict):
            return context
        targets = cls.related_context_targets(issue, previous_responses)
        if not targets:
            return context
        related_context = dict(context.get("related_context") or {})
        query = ArtifactQueryTool("")
        for item_id in targets:
            if item_id in related_context:
                continue
            result = query.related_context(artifact, item_id=item_id, compact=False)
            if result.get("ok"):
                related_context[item_id] = result
        if related_context:
            context["related_context"] = related_context
        return context

    @staticmethod
    def suppress_open_questions_for_issue(issue: Dict[str, Any]) -> bool:
        title = str((issue or {}).get("title") or "").strip()
        category = str((issue or {}).get("category") or "").strip()
        return (
            title in {"解決需求衝突", "需求正式化"}
            or category in {"resolve_conflict", "formalize_requirement"}
            or (
                category == "clarify_requirement"
                and title == "需求正式化"
            )
        )

    @staticmethod
    def artifact_has_rows(artifact: Optional[Dict[str, Any]], *keys: str) -> bool:
        if not isinstance(artifact, dict):
            return False
        for key in keys:
            value = artifact.get(key)
            if isinstance(value, list) and value:
                return True
            if isinstance(value, dict) and any(value.values()):
                return True
        return False

    @classmethod
    def question_asks_for_existing_artifact(
        cls,
        question: str,
        artifact: Optional[Dict[str, Any]],
    ) -> bool:
        text = str(question or "").lower()
        if not text:
            return False
        asks_for_req = any(
            token in text
            for token in ("req", "正式需求", "需求條目", "user requirement", "user requirements")
        )
        asks_for_model = any(
            token in text
            for token in ("system model", "system_models", "系統模型", "uml", "模型")
        )
        asks_for_feedback = any(
            token in text
            for token in ("feedback", "領域回饋", "回饋")
        )
        asks_to_provide = any(
            token in text
            for token in ("請提供", "能否提供", "目前有哪些", "目前已確認", "是否已有", "需要看到")
        )
        if asks_to_provide and asks_for_req and cls.artifact_has_rows(artifact, "REQ", "URL"):
            return True
        if asks_to_provide and asks_for_model and cls.artifact_has_rows(artifact, "system_models"):
            return True
        if asks_to_provide and asks_for_feedback and cls.artifact_has_rows(artifact, "feedback"):
            return True
        return False

    @staticmethod
    def normalized_question_key(question: str) -> str:
        text = str(question or "").strip().lower()
        text = re.sub(r"\s+", "", text)
        text = re.sub(r"[?？。．.!！、，,；;：「」『』（）()【】\\[\\]]+", "", text)
        return text

    def clean_open_questions(
        self,
        questions: Any,
        *,
        issue: Dict[str, Any],
        agent_name: str,
        artifact: Optional[Dict[str, Any]],
        previous_responses: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, str]]:
        if self.suppress_open_questions_for_issue(issue):
            return []
        if not isinstance(questions, list):
            return []
        cleaned: List[Dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for entry in previous_responses or []:
            if not isinstance(entry, dict) or entry.get("is_reply"):
                continue
            response = entry.get("response") if isinstance(entry.get("response"), dict) else {}
            existing = response.get("open_questions")
            if not isinstance(existing, list):
                continue
            for row in existing:
                if not isinstance(row, dict):
                    continue
                target = str(row.get("to") or "").strip()
                text = str(row.get("question") or "").strip()
                if target and text:
                    seen.add((target, self.normalized_question_key(text)))
        for row in questions:
            q = row if isinstance(row, dict) else {"question": str(row)}
            text = str(q.get("question") or "").strip()
            target = str(q.get("to") or "").strip()
            if not text or not target or target == agent_name:
                continue
            if self.question_asks_for_existing_artifact(text, artifact):
                continue
            key = (target, self.normalized_question_key(text))
            if key in seen:
                continue
            seen.add(key)
            clean_row = {"to": target, "question": text}
            reason = str(q.get("reason") or "").strip()
            if reason:
                clean_row["reason"] = reason
            cleaned.append(clean_row)
        return cleaned

    def validate_conflict_review_contract(
        self,
        response: Dict[str, Any],
        contract: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if not isinstance(contract, dict) or not contract:
            return response
        if str(contract.get("type") or "").strip() != "pair_reviews":
            return response

        known_pair_ids = [
            str(x).strip()
            for x in (contract.get("known_pair_ids") or [])
            if str(x).strip()
        ]
        pair_id_set = set(known_pair_ids)
        current_labels_by_id = contract.get("current_labels_by_id") or {}
        raw_reviews = response.get("pair_reviews") if isinstance(response, dict) else None
        if isinstance(raw_reviews, str):
            try:
                raw_reviews = json.loads(raw_reviews)
            except json.JSONDecodeError:
                pass
        if not isinstance(raw_reviews, list):
            text = str(response.get("text") or "").strip()
            try:
                text_payload = json.loads(text)
            except json.JSONDecodeError:
                text_payload = None
            if isinstance(text_payload, dict):
                raw_reviews = text_payload.get("pair_reviews")
            elif isinstance(text_payload, list):
                raw_reviews = text_payload
        if isinstance(raw_reviews, str):
            try:
                raw_reviews = json.loads(raw_reviews)
            except json.JSONDecodeError:
                pass
        if isinstance(raw_reviews, dict):
            if raw_reviews.get("id"):
                raw_reviews = [raw_reviews]
            else:
                raw_reviews = [
                    item for item in raw_reviews.values()
                    if isinstance(item, dict)
                ]
        if not isinstance(raw_reviews, list):
            response["pair_reviews"] = []
            return response

        errors: List[str] = []
        reviews: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for idx, raw in enumerate(raw_reviews, 1):
            if not isinstance(raw, dict):
                errors.append(f"pair_reviews[{idx}] must be an object")
                continue
            pair_id = str(raw.get("id") or "").strip()
            proposed_label = str(raw.get("proposed_label") or "").strip()
            reason = str(raw.get("reason") or "").strip()
            if not pair_id:
                errors.append(f"pair_reviews[{idx}] missing id")
                continue
            if pair_id not in pair_id_set:
                errors.append(f"unknown pair id: {pair_id}")
                continue
            if pair_id in seen:
                errors.append(f"duplicate pair id: {pair_id}")
                continue
            if proposed_label not in {"Conflict", "Neutral"}:
                errors.append(f"{pair_id} invalid proposed_label: {proposed_label or '<empty>'}")
            if not reason:
                errors.append(f"{pair_id} missing reason")
            normalized = normalize_pair_review_record(
                raw,
                pair_id_set=pair_id_set,
                current_labels_by_id=current_labels_by_id,
                require_valid_label=True,
            )
            if normalized:
                reviews.append(normalized)
                seen.add(pair_id)

        if errors:
            raise ValueError("; ".join(errors))
        response["pair_reviews"] = reviews
        return response

    def validate_requirement_elicitation_response(
        self,
        response: Dict[str, Any],
        issue: Dict[str, Any],
        agent_name: str,
    ) -> Dict[str, Any]:
        issue_id = str(issue.get("id") or "").strip()
        if not issue_id.startswith("ELICIT-"):
            return response
        actions = issue.get("actions") if isinstance(issue.get("actions"), dict) else {}
        action_info = actions.get(agent_name) if isinstance(actions.get(agent_name), dict) else {}
        action = str(action_info.get("action") or "").strip()
        if action not in {"ask_user", "supplement_question"}:
            return response
        raw_targets = response.get("target_stakeholders")
        if raw_targets in (None, "", []):
            raw_targets = action_info.get("target_stakeholders")
        if isinstance(raw_targets, str):
            raw_targets = [raw_targets]
        if not isinstance(raw_targets, list):
            raise ValueError("ELICIT agent response must include target_stakeholders as a list")
        allowed = {
            str(name).strip()
            for name in (issue.get("allowed_stakeholders") or [])
            if str(name).strip()
        }
        targets = []
        for value in raw_targets:
            name = str(value or "").strip()
            if name and name in allowed and name not in targets:
                targets.append(name)
        if not targets:
            raise ValueError("ELICIT target_stakeholders must contain at least one selected stakeholder")
        response["target_stakeholders"] = targets
        text = str(response.get("text") or "").strip()
        if action in {"ask_user", "supplement_question"} and "?" not in text and "？" not in text:
            response["format_error"] = "ELICIT ask_user/supplement_question text must be a direct question"
        return response

    def validate_agent_response(
        self,
        response: Dict[str, Any],
        *,
        contract: Optional[Dict[str, Any]],
        issue: Dict[str, Any],
        agent_name: str,
    ) -> Dict[str, Any]:
        response = self.validate_conflict_review_contract(response, contract)
        response = self.validate_requirement_elicitation_response(response, issue, agent_name)
        return self.validate_conflict_resolution_response(response, issue, agent_name)

    @classmethod
    def validate_conflict_resolution_response(
        cls,
        response: Dict[str, Any],
        issue: Dict[str, Any],
        agent_name: str,
    ) -> Dict[str, Any]:
        if str(issue.get("category") or "").strip() != "resolve_conflict":
            return response
        actions = issue.get("actions") if isinstance(issue.get("actions"), dict) else {}
        action_info = actions.get(agent_name) if isinstance(actions.get(agent_name), dict) else {}
        if str(action_info.get("action") or "").strip() != "discuss_conflict":
            return response

        stance = response.get("stance") if isinstance(response.get("stance"), dict) else {}
        proposal = stance.get("proposal") if isinstance(stance.get("proposal"), dict) else {}
        updates = proposal.get("url_updates")
        errors: List[str] = []
        if not isinstance(updates, list) or not updates:
            errors.append("stance.proposal.url_updates must contain at least one update")
        else:
            for index, update in enumerate(updates, 1):
                if not isinstance(update, dict):
                    errors.append(f"url_updates[{index}] must be an object")
                    continue
                action = str(update.get("action") or "").strip().lower()
                ids = update.get("ids")
                reason = str(update.get("reason") or "").strip()
                if action not in cls.conflict_update_actions:
                    errors.append(f"url_updates[{index}].action is invalid")
                if not isinstance(ids, list) or not any(str(value).strip() for value in ids):
                    errors.append(f"url_updates[{index}].ids must not be empty")
                if action == "revise" and not str(update.get("text") or "").strip():
                    errors.append(f"url_updates[{index}].text is required for revise")
                if not reason:
                    errors.append(f"url_updates[{index}].reason is required")
        if errors:
            response["format_error"] = "; ".join(errors)
        return response

    def run_agent_response_loop(
        self,
        agent: Any,
        issue: Dict[str, Any],
        *,
        previous_responses: Optional[List[Dict[str, Any]]] = None,
        related_context: Optional[Dict[str, Any]] = None,
        artifact: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        contract = issue.get("conflict_review_contract") if isinstance(issue, dict) else None
        enriched_related_context = self.enrich_related_context(
            related_context,
            artifact,
            issue,
            previous_responses,
        )
        context = {
            "issue": issue,
            "previous_responses": previous_responses,
            "related_context": enriched_related_context,
            "artifact": artifact,
        }
        loop_name = (
            "conflict_review"
            if str(issue.get("category") or "").strip() == "resolve_conflict"
            else "agent_response"
        )
        opa = agent.run_action_loop(
            name=loop_name,
            context=context,
            obs_fn=agent.obs_response,
            decide_action=agent.plan_actions,
            execute_action=agent.execute_action,
        )
        trace = opa.get("opa_trace") or []
        result = dict((trace[-1].get("result") if trace else {}) or {})
        step_results = [
            row.get("result") or {}
            for row in trace
            if isinstance(row, dict) and isinstance(row.get("result"), dict)
        ]
        format_errors = [
            str(row.get("format_error") or "").strip()
            for row in step_results
            if str(row.get("format_error") or "").strip()
        ]
        action_errors = [
            str(row.get("error") or row.get("format_error") or row.get("summary") or "").strip()
            for row in step_results
            if (
                str(row.get("error") or "").strip()
                or str(row.get("format_error") or "").strip()
                or str(row.get("status") or "").strip() == "failed"
            )
        ]
        actions = []
        action_results = []
        for row in step_results:
            action_name = str(row.get("action") or "").strip()
            if action_name:
                actions.append(action_name)
            action_result = row.get("action_result")
            if isinstance(action_result, dict) and self.recordable_issue_action_result(action_name, action_result):
                action_results.append(action_result)
            elif row and self.recordable_issue_action_result(action_name, row):
                action_results.append(row)
        expected_actions = issue.get("expected_actions") if isinstance(issue.get("expected_actions"), dict) else {}
        role_expected = expected_actions.get(getattr(agent, "name", ""))
        if isinstance(role_expected, str):
            role_expected = [role_expected]
        normalized_expected = [str(item).strip() for item in (role_expected or []) if str(item).strip()]
        is_answer_question = (
            str(issue.get("id") or "").strip() == "OQ"
            or (
                "answer_question" in normalized_expected
                and "respond_issue" not in normalized_expected
            )
        )
        is_elicitation = str(issue.get("id") or "").strip().startswith("ELICIT-")
        prompt_issue = dict(issue)
        if is_answer_question:
            prompt_issue["id"] = "OQ"
        final_related_context = self.enrich_related_context(
            related_context,
            artifact,
            prompt_issue,
            previous_responses,
        )
        final_related_context["issue_action_results"] = action_results
        if action_errors or format_errors:
            final_related_context["action_errors"] = list(dict.fromkeys(action_errors + format_errors))
        user_prompt = agent.build_response(
            issue=prompt_issue,
            previous_responses=previous_responses,
            related_context=final_related_context,
        )
        is_pair_review_round = (
            isinstance(contract, dict)
            and str(contract.get("type") or "").strip() == "pair_reviews"
        )
        use_artifact_tools = False
        if not is_pair_review_round:
            use_artifact_tools = agent.should_use_artifact_query(
                issue=prompt_issue,
                related_context=final_related_context,
                previous_responses=previous_responses,
            )
        response = agent.chat_for_issue_response(
            agent.build_direct_messages(user_prompt),
            include_stance=not is_answer_question and not is_elicitation and not is_pair_review_round,
            allow_pair_reviews=is_pair_review_round,
            use_tools=use_artifact_tools,
        )
        try:
            response = self.validate_agent_response(
                response,
                contract=contract,
                issue=prompt_issue,
                agent_name=getattr(agent, "name", ""),
            )
        except Exception as e:
            if not is_pair_review_round:
                raise
            response = response if isinstance(response, dict) else {"text": str(response)}
            response["format_error"] = str(e)
        if response.get("format_error") and not is_pair_review_round:
            retry_prompt = retry_response(
                issue=prompt_issue,
                previous_responses=previous_responses,
                action_results=action_results,
                is_answer_question=is_answer_question,
            )
            response = agent.chat_for_issue_response(
                agent.build_direct_messages(retry_prompt),
                include_stance=not is_answer_question and not is_elicitation,
                allow_pair_reviews=False,
                use_tools=use_artifact_tools,
            )
            response = self.validate_agent_response(
                response,
                contract=contract,
                issue=prompt_issue,
                agent_name=getattr(agent, "name", ""),
            )
        if response.get("format_error"):
            fallback_context = dict(final_related_context)
            fallback_errors = list(fallback_context.get("action_errors") or [])
            fallback_errors.append(str(response.get("format_error") or "").strip())
            fallback_context["action_errors"] = list(dict.fromkeys(err for err in fallback_errors if err))
            fallback_prompt = agent.build_response(
                issue=prompt_issue,
                previous_responses=previous_responses,
                related_context=fallback_context,
            )
            response = agent.chat_for_issue_response(
                agent.build_direct_messages(fallback_prompt),
                include_stance=not is_answer_question and not is_elicitation and not is_pair_review_round,
                allow_pair_reviews=is_pair_review_round,
                use_tools=use_artifact_tools,
            )
            try:
                response = self.validate_agent_response(
                    response,
                    contract=contract,
                    issue=prompt_issue,
                    agent_name=getattr(agent, "name", ""),
                )
            except Exception as e:
                if not is_pair_review_round:
                    raise
                response = response if isinstance(response, dict) else {"text": str(response)}
                response["format_error"] = str(e)
        if response.get("format_error"):
            if is_pair_review_round:
                raise ValueError(
                    f"{getattr(agent, 'name', '')} agent response output contract invalid after fallback: "
                    f"{response.get('format_error')}"
                )
            format_error = str(response.get("format_error") or "").strip()
            raise ValueError(
                f"{getattr(agent, 'name', '')} agent response output contract invalid after fallback: "
                f"{format_error}"
            )
        if not is_pair_review_round:
            response.pop("pair_reviews", None)
        if not is_answer_question and (not actions or actions[-1] != "respond_issue"):
            actions.append("respond_issue")
        if is_elicitation and not response.get("speaking_as"):
            speaking_as = []
            for action_result in action_results:
                raw = action_result.get("speaking_as") if isinstance(action_result, dict) else None
                if isinstance(raw, str):
                    raw = [raw]
                for name in (raw or []):
                    value = str(name or "").strip()
                    if value and value not in speaking_as:
                        speaking_as.append(value)
            if speaking_as:
                response["speaking_as"] = speaking_as
        response["open_questions"] = self.clean_open_questions(
            response.get("open_questions"),
            issue=issue,
            agent_name=getattr(agent, "name", ""),
            artifact=artifact,
            previous_responses=previous_responses,
        )
        return {
            "agent": getattr(agent, "name", ""),
            "actions": actions or ([result.get("action")] if result.get("action") else []),
            "text": response.get("text", ""),
            "pair_reviews": response.get("pair_reviews", []),
            "open_questions": response.get("open_questions", []),
            "speaking_as": response.get("speaking_as", []),
            "target_stakeholders": response.get("target_stakeholders", []),
            "stance": response.get("stance", {}),
            "issue_action_results": action_results,
        }

    def collect_issue_response(
        self,
        agent: Any,
        issue: Dict[str, Any],
        *,
        previous_responses: Optional[List[Dict[str, Any]]] = None,
        related_context: Optional[Dict[str, Any]] = None,
        artifact: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        required = (
            "run_action_loop",
            "obs_response",
            "plan_actions",
            "execute_action",
        )
        if not all(hasattr(agent, name) for name in required):
            raise NotImplementedError(
                f"Agent '{getattr(agent, 'name', type(agent).__name__)}' does not support agent response loop"
            )
        return self.run_agent_response_loop(
            agent,
            issue,
            previous_responses=previous_responses,
            related_context=related_context,
            artifact=artifact,
        )

    def moderate_sequential(
        self,
        issue: Dict,
        registry,
        artifact: Optional[Dict[str, Any]] = None,
        related_context: Optional[Dict[str, Any]] = None,
    ) -> tuple:
        record = [
            c for c in (issue.get("seed_previous_responses") or [])
            if isinstance(c, dict)
        ]
        oq_records = []
        participants = issue.get("participants") or []
        if not participants:
            self.logger.warning(f"[{issue['id']}] 無發言者")
            return (record, oq_records)
        self.sync_artifact_context_files(artifact)
        for agent_name in participants:
            agent = registry.get(agent_name)
            if not agent:
                raise RuntimeError(f"Agent '{agent_name}' 未註冊")
            answer_records, answer_oq = self.answer_questions_for_agent(
                record, agent_name, registry, artifact, issue, related_context
            )
            record.extend(answer_records)
            oq_records.extend(answer_oq)
            if answer_records and self.is_open_question_answer_issue(issue):
                continue
            try:
                response = self.collect_issue_response(
                    agent,
                    issue,
                    previous_responses=record,
                    related_context=related_context,
                    artifact=artifact,
                )
                response = self.attach_agent_action(issue, agent_name, response)
                record.append(
                    {
                        "agent": agent_name,
                        "round_index": issue.get("discussion_round_index"),
                        "response": (
                            response
                            if isinstance(response, dict)
                            else {"content": str(response)}
                        ),
                    }
                )
            except Exception as e:
                raise RuntimeError(f"{agent_name} 發言失敗") from e
        final_answers, final_oq = self.answer_pending_questions(
            record,
            registry,
            artifact,
            issue,
            related_context,
        )
        record.extend(final_answers)
        oq_records.extend(final_oq)

        return (record, oq_records)

    def respond_one_simultaneous(
        self,
        agent_name: str,
        issue: Dict,
        registry,
        artifact: Optional[Dict[str, Any]],
        related_context: Optional[Dict[str, Any]] = None,
        previous_responses: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        agent = registry.get(agent_name)
        if not agent:
            raise RuntimeError(f"Agent '{agent_name}' 未註冊")
        try:
            response = self.collect_issue_response(
                agent,
                issue,
                previous_responses=previous_responses,
                related_context=related_context,
                artifact=artifact,
            )
            response = self.attach_agent_action(issue, agent_name, response)
            return {
                "agent": agent_name,
                "round_index": issue.get("discussion_round_index"),
                "response": (
                    response
                    if isinstance(response, dict)
                    else {"content": str(response)}
                ),
            }
        except Exception as e:
            raise RuntimeError(f"{agent_name} 發言失敗") from e

    def attach_agent_action(self, issue: Dict, agent_name: str, response: Any) -> Dict[str, Any]:
        payload = response if isinstance(response, dict) else {"content": str(response)}
        payload = dict(payload)
        if not str(issue.get("id") or "").startswith("ELICIT-"):
            return payload
        actions = issue.get("actions") if isinstance(issue.get("actions"), dict) else {}
        action_info = actions.get(agent_name) if isinstance(actions.get(agent_name), dict) else {}
        action = str(action_info.get("action") or "").strip()
        focus = str(action_info.get("focus") or "").strip()
        targets = payload.get("target_stakeholders")
        if action:
            payload["actions"] = [action]
        if focus:
            payload["action_focus"] = focus
        if targets:
            if isinstance(targets, str):
                targets = [targets]
            payload["target_stakeholders"] = [
                str(name).strip()
                for name in targets
                if str(name).strip()
            ]
        return payload

    def moderate_simultaneous(
        self,
        issue: Dict,
        registry,
        artifact: Optional[Dict[str, Any]] = None,
        related_context: Optional[Dict[str, Any]] = None,
        previous_responses: Optional[List[Dict[str, Any]]] = None,
        return_open_questions: bool = False,
    ):
        participants = issue.get("participants") or []
        if not participants:
            self.logger.warning(f"[{issue.get('id', '?')}] 無發言者")
            return ([], []) if return_open_questions else []
        title = issue.get("title", "") or "（無標題）"
        self.logger.debug("[%s] simultaneous participants=%s title=%s", issue["id"], ",".join(participants), title)

        self.sync_artifact_context_files(artifact)
        max_workers = min(len(participants), 6)
        records_by_agent = {}

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    self.respond_one_simultaneous,
                    agent_name,
                    issue,
                    registry,
                    artifact,
                    related_context,
                    previous_responses,
                ): agent_name
                for agent_name in participants
            }
            for future in as_completed(futures):
                agent_name = futures[future]
                try:
                    entry = future.result()
                    records_by_agent[entry["agent"]] = entry
                except Exception as e:
                    raise RuntimeError(f"{agent_name} 發言失敗") from e

        record = [
            records_by_agent[name]
            for name in participants
            if name in records_by_agent
        ]
        oq_records: List[Dict[str, Any]] = []
        for agent_name in self.pending_question_targets(
            list(previous_responses or []) + record,
            registry,
            issue,
            artifact,
        ):
            answer_records, answer_oq = self.answer_questions_for_agent(
                list(previous_responses or []) + record,
                agent_name,
                registry,
                artifact,
                issue,
                related_context,
            )
            if answer_records:
                record.extend(answer_records)
            if answer_oq:
                oq_records.extend(answer_oq)
        if return_open_questions:
            return (record, oq_records)
        return record

    def pending_question_targets(
        self,
        record: List[Dict],
        registry,
        issue: Optional[Dict[str, Any]] = None,
        artifact: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        targets: List[str] = []
        for row in self.pending_open_questions(
            record,
            issue=issue,
            registry=registry,
            artifact=artifact,
        ):
            target = str(row.get("to_agent") or "").strip()
            if target and registry and registry.get(target):
                targets.append(target)
        return list(dict.fromkeys(targets))

    @staticmethod
    def stakeholder_names_from_issue(issue: Optional[Dict[str, Any]]) -> set[str]:
        names = {
            str(name).strip()
            for name in ((issue or {}).get("target_stakeholders") or [])
            if str(name).strip()
        }
        for row in ((issue or {}).get("stakeholders") or []):
            if isinstance(row, dict):
                name = str(row.get("name") or "").strip()
                if name:
                    names.add(name)
        return names

    def normalize_open_question_target(
        self,
        raw_target: Any,
        *,
        issue: Optional[Dict[str, Any]],
        registry=None,
    ) -> tuple[str, List[str]]:
        target = str(raw_target or "").strip()
        if not target:
            return "", []
        if registry and registry.get(target):
            return target, []
        stakeholder_names = self.stakeholder_names_from_issue(issue)
        if target in stakeholder_names:
            return "user", [target]
        return target, []

    def pending_open_questions(
        self,
        record: List[Dict],
        *,
        issue: Optional[Dict[str, Any]] = None,
        registry=None,
        artifact: Optional[Dict[str, Any]] = None,
    ) -> List[Dict]:
        answered = set()
        answered_questions = set()
        for c in record:
            if not c.get("is_reply"):
                continue
            resp = c.get("response", {}) if isinstance(c.get("response"), dict) else {}
            question = str(resp.get("reply_to_question") or "").strip()
            from_agent = str(resp.get("reply_to_agent") or "").strip()
            answer_agent = str(c.get("agent") or "").strip()
            if question and from_agent and answer_agent:
                answered.add((from_agent, answer_agent, question))
                answered_questions.add(question)

        pending: List[Dict] = []
        seen = set()
        if self.is_open_question_answer_issue(issue) and isinstance(artifact, dict):
            source_ids = self.open_question_source_ids(issue)
            for row in artifact.get("open_questions") or []:
                if not isinstance(row, dict):
                    continue
                qid = str(row.get("id") or "").strip()
                if source_ids and qid not in source_ids:
                    continue
                question = str(row.get("question") or "").strip()
                if not question:
                    continue
                if str(row.get("status") or "").strip().lower() == "answered":
                    continue
                if question in answered_questions:
                    continue
                from_agent = str(row.get("from_agent") or "mediator").strip() or "mediator"
                to_agent, target_stakeholders = self.normalize_open_question_target(
                    row.get("to") or row.get("to_agent"),
                    issue=issue,
                    registry=registry,
                )
                if not to_agent or to_agent == from_agent:
                    continue
                key = (from_agent, to_agent, question)
                if key in seen or key in answered:
                    continue
                seen.add(key)
                pending_row = {
                    "id": qid,
                    "from_agent": from_agent,
                    "to_agent": to_agent,
                    "question": question,
                }
                reason = str(row.get("reason") or "").strip()
                if reason:
                    pending_row["reason"] = reason
                if target_stakeholders:
                    pending_row["target_stakeholders"] = target_stakeholders
                    pending_row["to_stakeholder"] = target_stakeholders[0]
                pending.append(pending_row)
        for c in record:
            if c.get("is_reply"):
                continue
            from_agent = str(c.get("agent") or "").strip()
            resp = c.get("response", {}) if isinstance(c.get("response"), dict) else {}
            for q in resp.get("open_questions", []):
                if not isinstance(q, dict):
                    continue
                question = str(q.get("question") or "").strip()
                to_agent, target_stakeholders = self.normalize_open_question_target(
                    q.get("to"),
                    issue=issue,
                    registry=registry,
                )
                if not to_agent:
                    continue
                if to_agent == from_agent:
                    continue
                key = (from_agent, to_agent, question)
                if not question or key in seen or key in answered:
                    continue
                seen.add(key)
                pending_row = {
                    "from_agent": from_agent,
                    "to_agent": to_agent,
                    "question": question,
                }
                reason = str(q.get("reason") or "").strip()
                if reason:
                    pending_row["reason"] = reason
                if target_stakeholders:
                    pending_row["target_stakeholders"] = target_stakeholders
                    pending_row["to_stakeholder"] = target_stakeholders[0]
                pending.append(pending_row)
        return pending

    def get_questions_to_agent(
        self,
        record: List[Dict],
        to_agent_name: str,
        *,
        issue: Optional[Dict[str, Any]] = None,
        registry=None,
        artifact: Optional[Dict[str, Any]] = None,
    ) -> List[Dict]:
        return [
            q for q in self.pending_open_questions(record, issue=issue, registry=registry, artifact=artifact)
            if q.get("to_agent") == to_agent_name
        ]

    def answer_pending_questions(
        self,
        record: List[Dict],
        registry,
        artifact: Optional[Dict[str, Any]],
        issue: Optional[Dict[str, Any]] = None,
        related_context: Optional[Dict[str, Any]] = None,
    ) -> tuple:
        added: List[Dict] = []
        oq_records: List[Dict] = []
        current_record = list(record)
        for agent_name in self.pending_question_targets(current_record, registry, issue, artifact):
            answer_records, answer_oq = self.answer_questions_for_agent(
                current_record,
                agent_name,
                registry,
                artifact,
                issue,
                related_context,
            )
            if answer_records:
                current_record.extend(answer_records)
                added.extend(answer_records)
            if answer_oq:
                oq_records.extend(answer_oq)
        return (added, oq_records)


    def answer_questions_for_agent(
        self,
        record: List[Dict],
        agent_name: str,
        registry,
        artifact: Optional[Dict[str, Any]],
        issue: Optional[Dict[str, Any]] = None,
        related_context: Optional[Dict[str, Any]] = None,
    ) -> tuple:
        questions = self.get_questions_to_agent(
            record,
            agent_name,
            issue=issue,
            registry=registry,
            artifact=artifact,
        )
        if not questions:
            return ([], [])
        target_agent = registry.get(agent_name) if registry else None
        if not target_agent:
            raise RuntimeError(f"open question 目標 agent 未註冊: {agent_name}")
        added = []
        oq_records = []
        current_record = list(record)
        for q_record in questions:
            try:
                q_issue = self.build_reply_issue(
                    question=q_record["question"],
                    from_agent=q_record["from_agent"],
                    target_stakeholders=(
                        q_record.get("target_stakeholders")
                        or (issue or {}).get("target_stakeholders", [])
                        if agent_name == "user"
                        else []
                    ),
                )
                response = self.collect_issue_response(
                    target_agent,
                    q_issue,
                    previous_responses=current_record,
                    related_context=related_context,
                    artifact=artifact,
                )
                resp = (
                    response
                    if isinstance(response, dict)
                    else {"content": str(response)}
                )
                resp = dict(resp)
                resp["reply_to_question"] = q_record["question"]
                resp["reply_to_agent"] = q_record["from_agent"]
                answer = resp.get("text", "")
                entry = {
                    "agent": agent_name,
                    "round_index": (issue or {}).get("discussion_round_index"),
                    "response": resp,
                    "is_reply": True,
                }
                added.append(entry)
                current_record.append(entry)
                oq_records.append({**q_record, "status": "answered", "answer": answer})
            except Exception as e:
                raise RuntimeError("open question 回答失敗") from e
        return (added, oq_records)

    @staticmethod
    def is_open_question_answer_issue(issue: Optional[Dict[str, Any]]) -> bool:
        if not isinstance(issue, dict):
            return False
        issue_id = str(issue.get("id") or "").strip()
        focus = str(issue.get("issue_focus") or "").strip()
        return issue_id == "OQ" or issue_id.startswith("OQ-") or focus == "open_question_answer"

    @staticmethod
    def open_question_source_ids(issue: Optional[Dict[str, Any]]) -> set[str]:
        if not isinstance(issue, dict):
            return set()
        ids: set[str] = set()
        for source in issue.get("sources") or []:
            if not isinstance(source, dict):
                continue
            artifact = str(source.get("artifact") or "").strip()
            if artifact != "open_questions":
                continue
            for item in source.get("ids") or []:
                value = str(item or "").strip()
                if value:
                    ids.add(value)
        return ids
