# Mediator discussion logic: collect agent responses and handle meeting questions.
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional


class MediatorDiscussion:
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

    def validate_issue_response_contract(
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
        if not isinstance(raw_reviews, list):
            text = str(response.get("text") or "").strip()
            try:
                text_payload = json.loads(text)
            except json.JSONDecodeError:
                text_payload = None
            if isinstance(text_payload, dict):
                raw_reviews = text_payload.get("pair_reviews")
        if not isinstance(raw_reviews, list):
            raise ValueError("pair_reviews must be a list")

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

        missing = sorted(pair_id_set - seen)
        if missing:
            errors.append("missing pair ids: " + ", ".join(missing))
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
        response = self.validate_issue_response_contract(response, contract)
        return self.validate_requirement_elicitation_response(response, issue, agent_name)

    def run_agent_response_loop(
        self,
        agent: Any,
        issue: Dict[str, Any],
        *,
        previous_responses: Optional[List[Dict[str, Any]]] = None,
        artifact_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        contract = issue.get("response_contract") if isinstance(issue, dict) else None
        context = {
            "issue": issue,
            "previous_responses": previous_responses,
            "artifact_context": artifact_context,
        }
        loop_name = (
            "conflict_review"
            if str(issue.get("category") or "").strip() == "conflict_resolution"
            else "agent_response"
        )
        opa = agent.run_action_loop(
            name=loop_name,
            context=context,
            build_observation=agent.build_issue_response_observation,
            decide_action=agent.decide_issue_response_action,
            execute_action=agent.execute_issue_response_action,
            validate_result=(
                lambda result: self.validate_agent_response(
                    result,
                    contract=contract,
                    issue=issue,
                    agent_name=getattr(agent, "name", ""),
                )
            ),
        )
        trace = opa.get("opa_trace") or []
        result = dict((trace[-1].get("result") if trace else {}) or {})
        if result.get("format_error"):
            raise ValueError(
                f"{getattr(agent, 'name', '')} agent response output contract invalid after agent loop: "
                f"{result.get('format_error')}"
            )
        return {
            "agent": getattr(agent, "name", ""),
            "text": result.get("text", ""),
            "pair_reviews": result.get("pair_reviews", []),
            "open_questions": result.get("open_questions", []),
            "oracle_action_type": result.get("oracle_action_type", ""),
            "oracle_is_relevant": bool(result.get("oracle_is_relevant", False)),
            "oracle_revealed_ids": result.get("oracle_revealed_ids", []),
            "suggested_next_action": result.get("suggested_next_action"),
            "target_stakeholders": result.get("target_stakeholders", []),
            "speaking_as": result.get("speaking_as", []),
            "opa_trace": opa.get("opa_trace", []),
        }

    def collect_issue_response(
        self,
        agent: Any,
        issue: Dict[str, Any],
        *,
        previous_responses: Optional[List[Dict[str, Any]]] = None,
        artifact_context: Optional[Dict[str, Any]] = None,
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
        )

    def moderate_sequential(
        self, issue: Dict, registry, artifact: Optional[Dict[str, Any]] = None
    ) -> tuple:
        """逐一發言；輪到某人前先讓他即時回答指向他的問題，再發言（可依問答調整立場）。回傳 (contributions, oq_records)。"""
        contributions = [
            c for c in (issue.get("seed_previous_responses") or [])
            if isinstance(c, dict)
        ]
        oq_records = []
        speaking_order = issue.get("speaking_order") or issue.get("participants") or []
        if not speaking_order:
            self.logger.warning(f"[{issue['id']}] 無發言者")
            return (contributions, oq_records)
        self.sync_artifact_context_files(artifact)
        for agent_name in speaking_order:
            agent = registry.get(agent_name)
            if not agent:
                raise RuntimeError(f"Agent '{agent_name}' 未註冊")
            answer_contribs, answer_oq = self.answer_questions_for_agent(
                contributions, agent_name, registry, artifact
            )
            contributions.extend(answer_contribs)
            oq_records.extend(answer_oq)
            try:
                response = self.collect_issue_response(
                    agent,
                    issue,
                    previous_responses=contributions,
                )
                response = self.attach_agent_action(issue, agent_name, response)
                contributions.append(
                    {
                        "agent": agent_name,
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
                contributions, answer_contribs, registry, artifact
            )
            contributions.extend(follow_ups)

        return (contributions, oq_records)

    def respond_one_simultaneous(
        self,
        agent_name: str,
        issue: Dict,
        registry,
        artifact: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """單一 agent 發言，供 moderate_simultaneous 並行呼叫。"""
        agent = registry.get(agent_name)
        if not agent:
            raise RuntimeError(f"Agent '{agent_name}' 未註冊")
        try:
            response = self.collect_issue_response(
                agent,
                issue,
                previous_responses=None,
            )
            response = self.attach_agent_action(issue, agent_name, response)
            return {
                "agent": agent_name,
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
        actions = issue.get("agent_actions") if isinstance(issue.get("agent_actions"), dict) else {}
        action_info = actions.get(agent_name) if isinstance(actions.get(agent_name), dict) else {}
        action = str(action_info.get("action") or "").strip()
        focus = str(action_info.get("focus") or "").strip()
        targets = payload.get("target_stakeholders")
        if action:
            payload["action"] = action
        if focus:
            payload["action_focus"] = focus
        if not targets and not str(issue.get("id") or "").startswith("ELICIT-"):
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
        self, issue: Dict, registry, artifact: Optional[Dict[str, Any]] = None
    ) -> List[Dict]:
        participants = issue.get("participants") or []
        if not participants:
            self.logger.warning(f"[{issue.get('id', '?')}] 無發言者")
            return []
        title = issue.get("title", "") or "（無標題）"
        self.logger.info(f"[{issue['id']}] {title} — 同時: {', '.join(participants)}")

        self.sync_artifact_context_files(artifact)
        max_workers = min(len(participants), 6)
        contributions_by_agent = {}

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    self.respond_one_simultaneous,
                    agent_name,
                    issue,
                    registry,
                    artifact,
                ): agent_name
                for agent_name in participants
            }
            for future in as_completed(futures):
                agent_name = futures[future]
                try:
                    contrib = future.result()
                    contributions_by_agent[contrib["agent"]] = contrib
                except Exception as e:
                    raise RuntimeError(f"{agent_name} 發言失敗") from e

        contributions = [
            contributions_by_agent[name]
            for name in participants
            if name in contributions_by_agent
        ]
        return contributions

    def get_questions_to_agent(
        self, contributions: List[Dict], to_agent_name: str
    ) -> List[Dict]:
        """從 contributions 中蒐集所有指向 to_agent_name 的 open_questions。"""
        out = []
        for c in contributions:
            agent_name = c.get("agent", "")
            resp = c.get("response", {}) if isinstance(c.get("response"), dict) else {}
            for q in resp.get("open_questions", []):
                if isinstance(q, str):
                    q = {"question": q, "to": "user"}
                elif not isinstance(q, dict):
                    continue
                to_agent = q.get("to", "user")
                if to_agent != to_agent_name:
                    continue
                out.append({
                    "from_agent": agent_name,
                    "to_agent": to_agent,
                    "question": q.get("question", ""),
                })
        return [q for q in out if q.get("question")]

    def collect_suggested_next_actions(
        self,
        contributions: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        suggestions: List[Dict[str, Any]] = []
        seen = set()
        for c in contributions or []:
            if not isinstance(c, dict):
                continue
            agent_name = str(c.get("agent") or "").strip()
            resp = c.get("response", {}) if isinstance(c.get("response"), dict) else {}
            suggestion = resp.get("suggested_next_action")
            if not isinstance(suggestion, dict):
                continue
            action_type = str(suggestion.get("type") or "").strip()
            reason = str(suggestion.get("reason") or "").strip()
            target_ids = [
                str(x).strip()
                for x in (suggestion.get("target_ids") or [])
                if str(x).strip()
            ]
            urgency = str(suggestion.get("urgency") or "").strip().lower()
            if urgency not in {"low", "medium", "high"}:
                urgency = "medium"
            if not action_type or not reason:
                continue
            key = (agent_name, action_type, reason, tuple(target_ids), urgency)
            if key in seen:
                continue
            seen.add(key)
            suggestions.append(
                {
                    "from_agent": agent_name,
                    "type": action_type,
                    "reason": reason,
                    "target_ids": target_ids,
                    "urgency": urgency,
                }
            )
        return suggestions

    def answer_questions_for_agent(
        self,
        contributions: List[Dict],
        agent_name: str,
        registry,
        artifact: Optional[Dict[str, Any]],
    ) -> tuple:
        """讓 agent_name 即時回答目前 contributions 中指向他的問題。回傳 (要 append 的 contributions, oq_records)。"""
        questions = self.get_questions_to_agent(contributions, agent_name)
        if not questions:
            return ([], [])
        target_agent = registry.get(agent_name) if registry else None
        if not target_agent:
            raise RuntimeError(f"open question 目標 agent 未註冊: {agent_name}")
        added = []
        oq_records = []
        current_contributions = list(contributions)
        for q_record in questions:
            try:
                q_issue = self.build_reply_issue(
                    question=q_record["question"],
                    from_agent=q_record["from_agent"],
                    follow_up_hint=(
                        "（請簡要針對此問題回答；若前面發言已涵蓋可寫「如前述」或只補充重點。"
                        "回答後若尚未發言，可在輪到你發言時依此問答補充或微調立場。）"
                    ),
                )
                response = self.collect_issue_response(
                    target_agent,
                    q_issue,
                    previous_responses=current_contributions,
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
                contrib = {
                    "agent": agent_name,
                    "response": resp,
                    "is_reply": True,
                }
                added.append(contrib)
                current_contributions.append(contrib)
                oq_records.append({**q_record, "status": "answered", "answer": answer})
            except Exception as e:
                raise RuntimeError("open question 回答失敗") from e
        return (added, oq_records)

    def get_follow_ups_after_answers(
        self,
        contributions: List[Dict],
        answer_contribs: List[Dict],
        registry,
        artifact: Optional[Dict[str, Any]],
    ) -> List[Dict]:
        """回答完成後，讓提問者依回答簡要補充或調整發言。"""
        if not answer_contribs:
            return []
        requester_qa: Dict[str, List[tuple]] = {}
        for c in answer_contribs:
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
                f"你問：{q}\n對方回答：{a}" for q, a in qa_list
            ]
            follow_issue = {
                "id": "OQ-follow",
                "title": "依回答補充或調整發言",
                "description": (
                    "\n\n".join(desc_parts)
                    + "\n\n請依上述回答簡要說明你是否要補充或調整你的立場；若無需補充請寫「無需補充」。"
                ),
            }
            try:
                response = self.collect_issue_response(
                    agent,
                    follow_issue,
                    previous_responses=contributions,
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

    def handle_open_questions(
        self,
        contributions: List[Dict],
        registry,
        stakeholders: List[Dict],
        artifact: Optional[Dict[str, Any]] = None,
    ) -> List[Dict]:
        """將 open_questions 依 to 欄位路由到對應 agent 回答（用於 simultaneous 模式：所有人發言後再集中回答）。"""
        oq_records = []
        self.sync_artifact_context_files(artifact)

        all_questions = []
        for c in contributions:
            agent_name = c.get("agent", "")
            resp = c.get("response", {}) if isinstance(c.get("response"), dict) else {}
            for q in resp.get("open_questions", []):
                if isinstance(q, str):
                    q = {"question": q, "to": "user"}
                elif not isinstance(q, dict):
                    continue
                to_agent = q.get("to", "user")
                if to_agent == agent_name:
                    continue
                all_questions.append(
                    {
                        "from_agent": agent_name,
                        "to_agent": to_agent,
                        "question": q.get("question", ""),
                    }
                )

        valid_questions = [q for q in all_questions if q.get("question")]
        if not valid_questions:
            return oq_records

        def answer_one(q_record: Dict) -> tuple:
            """回答單一問題，回傳 (q_record, contribution_entry or None, oq_record)。"""
            target_name = q_record["to_agent"]
            target_agent = registry.get(target_name) if registry else None
            if not target_agent:
                raise RuntimeError(f"open question 目標 agent 未註冊: {target_name}")
            try:
                q_issue = self.build_reply_issue(
                    question=q_record["question"],
                    from_agent=q_record["from_agent"],
                    follow_up_hint=(
                        "（請簡要針對此問題回答，若前面發言已涵蓋可寫「如前述」或只補充重點，勿整段重複相同內容。）"
                    ),
                )
                response = self.collect_issue_response(
                    target_agent,
                    q_issue,
                    previous_responses=contributions,
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
                contrib = {
                    "agent": target_name,
                    "response": resp,
                    "is_reply": True,
                }
                return (
                    q_record,
                    contrib,
                    {
                        **q_record,
                        "status": "answered",
                        "answer": answer,
                        "needs_issue": False,
                    },
                )
            except Exception as e:
                raise RuntimeError("開放問題回答失敗") from e

        max_workers = min(len(valid_questions), 6)
        results_by_idx = {}

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(answer_one, q_record): i
                for i, q_record in enumerate(valid_questions)
            }
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    q, contrib, oq = future.result()
                    results_by_idx[idx] = (contrib, oq)
                except Exception as e:
                    raise RuntimeError(f"開放問題回答失敗: {e}") from e

        for i in range(len(valid_questions)):
            if i not in results_by_idx:
                raise RuntimeError(f"開放問題回答缺少結果: index={i}")
            contrib, oq = results_by_idx[i]
            if oq.get("status") != "answered":
                oq["needs_issue"] = self.should_escalate_open_question(oq)
                if oq["needs_issue"]:
                    oq["status"] = "escalate_to_issue"
            oq_records.append(oq)
            if contrib:
                contributions.append(contrib)

        return oq_records
