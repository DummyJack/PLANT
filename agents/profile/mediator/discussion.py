# Mediator discussion logic: collect agent responses and handle meeting questions.
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional


class MediatorDiscussion:
    @staticmethod
    def retry_issue_response_prompt(
        issue: Dict[str, Any],
        previous_responses: Optional[List[Dict[str, Any]]],
        action_results: List[Dict[str, Any]],
        *,
        is_answer_question: bool,
    ) -> str:
        output_contract = (
            '{\n  "text": "直接回答問題",\n  "open_questions": []\n}'
            if is_answer_question
            else '{\n  "text": "根據本輪 action 結果提出自然語言會議發言",\n  "open_questions": [],\n  "stance": {"state": "ready_to_close"}\n}'
        )
        stance_rule = (
            ""
            if is_answer_question
            else "- stance.state 必須輸出，且只能是 ready_to_close 或 needs_more_discussion。\n"
        )
        return (
            "# 任務\n"
            "上一個會議發言不符合輸出契約。請根據同一議題、前文與本輪 action 結果，重新產生一次正式會議發言。\n\n"
            "# 限制\n"
            "- 不要重跑 action，不要新增或修改 artifact。\n"
            "- 不要輸出 action 結果 JSON；text 必須是自然語言發言。\n"
            f"{stance_rule}"
            "- 若 action 產生或更新模型、需求、feedback 或分析結果，text 要說明這些結果如何支持本議題判斷。\n"
            "- open_questions 只放本議題仍需要對方回答的關鍵問題；沒有就輸出空陣列。\n\n"
            "# 議題\n"
            f"{json.dumps(issue, ensure_ascii=False, indent=2)}\n\n"
            "# 前文\n"
            f"{json.dumps(previous_responses or [], ensure_ascii=False, indent=2)}\n\n"
            "# 本輪 action 結果\n"
            f"{json.dumps(action_results, ensure_ascii=False, indent=2)}\n\n"
            "# 輸出 JSON\n"
            f"{output_contract}"
        )

    @staticmethod
    def suppress_open_questions_for_issue(issue: Dict[str, Any]) -> bool:
        title = str((issue or {}).get("title") or "").strip()
        category = str((issue or {}).get("category") or "").strip()
        return (
            title in {"解決需求衝突", "需求正式化"}
            or category in {"resolve_conflict"}
            or (
                category == "clarify_requirement"
                and title == "需求正式化"
            )
        )

    def pair_review_record(
        self,
        raw: Dict[str, Any],
        *,
        pair_id_set: set[str],
        current_labels_by_id: Optional[Dict[str, str]] = None,
    ) -> Optional[Dict[str, Any]]:
        pair_id = str(raw.get("id") or "").strip()
        if not pair_id or pair_id not in pair_id_set:
            return None
        proposed_label = str(raw.get("proposed_label") or "").strip()
        if proposed_label not in {"Conflict", "Neutral"}:
            return None
        current_label = ""
        if current_labels_by_id:
            current_label = str(current_labels_by_id.get(pair_id) or "").strip()
        decision = "keep"
        if current_label in {"Conflict", "Neutral"} and proposed_label != current_label:
            decision = "modify"
        return {
            "id": pair_id,
            "decision": decision,
            "proposed_label": proposed_label,
            "reason": str(raw.get("reason") or "").strip(),
        }

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
            normalized = self.pair_review_record(
                raw,
                pair_id_set=pair_id_set,
                current_labels_by_id=current_labels_by_id,
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
        actions = issue.get("agent_actions") if isinstance(issue.get("agent_actions"), dict) else {}
        action_info = actions.get(agent_name) if isinstance(actions.get(agent_name), dict) else {}
        action = str(action_info.get("action") or "").strip()
        if action not in {"ask_user", "supplement_question"}:
            return response
        raw_targets = response.get("target_stakeholders")
        if not raw_targets:
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
        return self.validate_requirement_elicitation_response(response, issue, agent_name)

    def run_agent_response_loop(
        self,
        agent: Any,
        issue: Dict[str, Any],
        *,
        previous_responses: Optional[List[Dict[str, Any]]] = None,
        artifact_context: Optional[Dict[str, Any]] = None,
        artifact: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        contract = issue.get("conflict_review_contract") if isinstance(issue, dict) else None
        context = {
            "issue": issue,
            "previous_responses": previous_responses,
            "artifact_context": artifact_context,
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
            build_observation=agent.build_issue_response_observation,
            decide_action=agent.decide_issue_response_action,
            execute_action=agent.execute_issue_response_action,
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
        if format_errors:
            raise ValueError(
                f"{getattr(agent, 'name', '')} agent action output invalid after agent loop: "
                f"{'; '.join(format_errors)}"
            )
        actions = []
        action_results = []
        for row in step_results:
            action_name = str(row.get("action") or "").strip()
            if action_name:
                actions.append(action_name)
            action_result = row.get("action_result")
            if isinstance(action_result, dict):
                action_results.append(action_result)
            elif row:
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
        prompt_issue = dict(issue)
        if is_answer_question:
            prompt_issue["id"] = "OQ"
        final_context = dict(artifact_context or {})
        final_context["issue_action_results"] = action_results
        user_prompt = agent.build_issue_response_prompt(
            issue=prompt_issue,
            previous_responses=previous_responses,
            artifact_context=final_context,
        )
        is_pair_review_round = (
            isinstance(contract, dict)
            and str(contract.get("type") or "").strip() == "pair_reviews"
        )
        response = agent.chat_for_issue_response(
            agent.build_direct_messages(user_prompt),
            include_stance=not is_answer_question and not is_pair_review_round,
            allow_pair_reviews=is_pair_review_round,
        )
        response = self.validate_agent_response(
            response,
            contract=contract,
            issue=prompt_issue,
            agent_name=getattr(agent, "name", ""),
        )
        if response.get("format_error") and not is_pair_review_round:
            retry_prompt = self.retry_issue_response_prompt(
                prompt_issue,
                previous_responses,
                action_results,
                is_answer_question=is_answer_question,
            )
            response = agent.chat_for_issue_response(
                agent.build_direct_messages(retry_prompt),
                include_stance=not is_answer_question,
                allow_pair_reviews=False,
            )
            response = self.validate_agent_response(
                response,
                contract=contract,
                issue=prompt_issue,
                agent_name=getattr(agent, "name", ""),
            )
        if response.get("format_error"):
            raise ValueError(
                f"{getattr(agent, 'name', '')} agent response output contract invalid after agent loop: "
                f"{response.get('format_error')}"
            )
        if not is_pair_review_round:
            response.pop("pair_reviews", None)
        if not is_answer_question and (not actions or actions[-1] != "respond_issue"):
            actions.append("respond_issue")
        if self.suppress_open_questions_for_issue(issue):
            response["open_questions"] = []
        return {
            "agent": getattr(agent, "name", ""),
            "actions": actions or ([result.get("action")] if result.get("action") else []),
            "text": response.get("text", ""),
            "pair_reviews": response.get("pair_reviews", []),
            "open_questions": response.get("open_questions", []),
            "speaking_as": response.get("speaking_as", []),
            "stance": response.get("stance", {}),
            "issue_action_results": action_results,
        }

    def collect_issue_response(
        self,
        agent: Any,
        issue: Dict[str, Any],
        *,
        previous_responses: Optional[List[Dict[str, Any]]] = None,
        artifact_context: Optional[Dict[str, Any]] = None,
        artifact: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        required = (
            "run_action_loop",
            "build_issue_response_observation",
            "decide_issue_response_action",
            "execute_issue_response_action",
        )
        if not all(hasattr(agent, name) for name in required):
            raise NotImplementedError(
                f"Agent '{getattr(agent, 'name', type(agent).__name__)}' does not support agent response loop"
            )
        return self.run_agent_response_loop(
            agent,
            issue,
            previous_responses=previous_responses,
            artifact_context=artifact_context,
            artifact=artifact,
        )

    def moderate_sequential(
        self,
        issue: Dict,
        registry,
        artifact: Optional[Dict[str, Any]] = None,
        artifact_context: Optional[Dict[str, Any]] = None,
    ) -> tuple:
        """逐一發言；輪到某人前先讓他即時回答指向他的問題，再發言（可依問答調整立場）。回傳 (record, oq_records)。"""
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
                record, agent_name, registry, artifact, issue, artifact_context
            )
            record.extend(answer_records)
            oq_records.extend(answer_oq)
            try:
                response = self.collect_issue_response(
                    agent,
                    issue,
                    previous_responses=record,
                    artifact_context=artifact_context,
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
            follow_ups = self.get_follow_ups_after_answers(
                record, answer_records, registry, artifact, artifact_context
            )
            record.extend(follow_ups)
        final_answers, final_oq = self.answer_pending_questions(
            record,
            registry,
            artifact,
            issue,
            artifact_context,
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
        artifact_context: Optional[Dict[str, Any]] = None,
        previous_responses: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """單一 agent 發言，供 moderate_simultaneous 並行呼叫。"""
        agent = registry.get(agent_name)
        if not agent:
            raise RuntimeError(f"Agent '{agent_name}' 未註冊")
        try:
            response = self.collect_issue_response(
                agent,
                issue,
                previous_responses=previous_responses,
                artifact_context=artifact_context,
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
        actions = issue.get("agent_actions") if isinstance(issue.get("agent_actions"), dict) else {}
        action_info = actions.get(agent_name) if isinstance(actions.get(agent_name), dict) else {}
        action = str(action_info.get("action") or "").strip()
        focus = str(action_info.get("focus") or "").strip()
        targets = payload.get("target_stakeholders")
        if action:
            payload["actions"] = [action]
        if focus:
            payload["action_focus"] = focus
        if not targets:
            targets = action_info.get("target_stakeholders")
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
        artifact_context: Optional[Dict[str, Any]] = None,
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
                    artifact_context,
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
        ):
            answer_records, answer_oq = self.answer_questions_for_agent(
                list(previous_responses or []) + record,
                agent_name,
                registry,
                artifact,
                issue,
                artifact_context,
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
    ) -> List[str]:
        targets: List[str] = []
        for row in self.pending_open_questions(record, issue=issue, registry=registry):
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
        target = str(raw_target or "user").strip() or "user"
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
    ) -> List[Dict]:
        answered = set()
        for c in record:
            if not c.get("is_reply"):
                continue
            resp = c.get("response", {}) if isinstance(c.get("response"), dict) else {}
            question = str(resp.get("reply_to_question") or "").strip()
            from_agent = str(resp.get("reply_to_agent") or "").strip()
            answer_agent = str(c.get("agent") or "").strip()
            if question and from_agent and answer_agent:
                answered.add((from_agent, answer_agent, question))

        pending: List[Dict] = []
        seen = set()
        for c in record:
            if c.get("is_reply"):
                continue
            from_agent = str(c.get("agent") or "").strip()
            resp = c.get("response", {}) if isinstance(c.get("response"), dict) else {}
            for q in resp.get("open_questions", []):
                if isinstance(q, str):
                    q = {"question": q, "to": "user"}
                elif not isinstance(q, dict):
                    continue
                question = str(q.get("question") or "").strip()
                to_agent, target_stakeholders = self.normalize_open_question_target(
                    q.get("to") or "user",
                    issue=issue,
                    registry=registry,
                )
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
    ) -> List[Dict]:
        """從 record 中蒐集所有指向 to_agent_name 的 open_questions。"""
        return [
            q for q in self.pending_open_questions(record, issue=issue, registry=registry)
            if q.get("to_agent") == to_agent_name
        ]

    def answer_pending_questions(
        self,
        record: List[Dict],
        registry,
        artifact: Optional[Dict[str, Any]],
        issue: Optional[Dict[str, Any]] = None,
        artifact_context: Optional[Dict[str, Any]] = None,
    ) -> tuple:
        added: List[Dict] = []
        oq_records: List[Dict] = []
        current_record = list(record)
        for agent_name in self.pending_question_targets(current_record, registry, issue):
            answer_records, answer_oq = self.answer_questions_for_agent(
                current_record,
                agent_name,
                registry,
                artifact,
                issue,
                artifact_context,
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
        artifact_context: Optional[Dict[str, Any]] = None,
    ) -> tuple:
        """讓 agent_name 即時回答目前 record 中指向他的問題。回傳 (要 append 的 record, oq_records)。"""
        questions = self.get_questions_to_agent(record, agent_name, issue=issue, registry=registry)
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
                    follow_up_hint=(
                        "（請簡要針對此問題回答；若前面發言已涵蓋可寫「如前述」或只補充重點。"
                        "回答後若尚未發言，可在輪到該 agent 發言時依此問答補充或微調立場。）"
                    ),
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
                    artifact_context=artifact_context,
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
                answer_text = resp.get("text", "")
                entry = {
                    "agent": agent_name,
                    "round_index": (issue or {}).get("discussion_round_index"),
                    "response": resp,
                    "is_reply": True,
                }
                added.append(entry)
                current_record.append(entry)
                oq_records.append({**q_record, "status": "answered", "answer_text": answer_text})
            except Exception as e:
                raise RuntimeError("open question 回答失敗") from e
        return (added, oq_records)

    def get_follow_ups_after_answers(
        self,
        record: List[Dict],
        answer_records: List[Dict],
        registry,
        artifact: Optional[Dict[str, Any]],
        artifact_context: Optional[Dict[str, Any]] = None,
    ) -> List[Dict]:
        """回答完成後，讓提問者依回答簡要補充或調整發言。"""
        if not answer_records:
            return []
        requester_qa: Dict[str, List[tuple]] = {}
        for c in answer_records:
            resp = c.get("response", {}) if isinstance(c.get("response"), dict) else {}
            from_agent = resp.get("reply_to_agent")
            if not from_agent:
                continue
            q = resp.get("reply_to_question", "")
            ans = resp.get("text", "")
            requester_qa.setdefault(from_agent, []).append((q, ans))
        result = []
        for requester_name, qa_list in requester_qa.items():
            agent = registry.get(requester_name) if registry else None
            if not agent:
                continue
            desc_parts = [
                f"提問：{q}\n回答：{a}" for q, a in qa_list
            ]
            follow_issue = {
                "id": "OQ-follow",
                "title": "依回答補充或調整發言",
                "description": (
                    "\n\n".join(desc_parts)
                    + "\n\n請依上述回答簡要說明是否要補充或調整立場；若無需補充請寫「無需補充」。"
                ),
            }
            try:
                response = self.collect_issue_response(
                    agent,
                    follow_issue,
                    previous_responses=record,
                    artifact_context=artifact_context,
                    artifact=artifact,
                )
                resp = (
                    response
                    if isinstance(response, dict)
                    else {"content": str(response)}
                )
                resp = dict(resp)
                result.append({
                    "agent": requester_name,
                    "response": resp,
                    "is_follow_up": True,
                })
            except Exception as e:
                raise RuntimeError(f"{requester_name} open question follow-up 失敗") from e
        return result
