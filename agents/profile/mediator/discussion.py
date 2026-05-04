# Mediator discussion logic: collect agent responses and handle meeting questions.
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional


class MediatorDiscussion:
    def collect_topic_response(
        self,
        agent: Any,
        topic: Dict[str, Any],
        *,
        previous_responses: Optional[List[Dict[str, Any]]] = None,
        artifact_snapshot: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        agent_name = getattr(agent, "name", "")
        context = {
            "topic": topic,
            "previous_responses": previous_responses,
            "artifact_snapshot": artifact_snapshot,
        }
        required = (
            "run_action_loop",
            "build_topic_response_observation",
            "decide_topic_response_action",
            "execute_topic_response_action",
        )
        if not all(hasattr(agent, name) for name in required):
            raise NotImplementedError(
                f"Agent '{getattr(agent, 'name', type(agent).__name__)}' does not support topic_response loop"
            )
        opa = agent.run_action_loop(
            name="topic_response",
            max_iterations=1,
            loop_cap=1,
            context=context,
            build_observation=agent.build_topic_response_observation,
            decide_action=agent.decide_topic_response_action,
            execute_action=agent.execute_topic_response_action,
        )
        trace = opa.get("opa_trace") or []
        result = dict((trace[-1].get("result") if trace else {}) or {})
        return {
            "agent": agent_name,
            "statement": result.get("statement", ""),
            "open_questions": result.get("open_questions", []),
            "oracle_action_type": result.get("oracle_action_type", ""),
            "oracle_is_relevant": bool(result.get("oracle_is_relevant", False)),
            "oracle_revealed_ids": result.get("oracle_revealed_ids", []),
            "suggested_next_action": result.get("suggested_next_action"),
            "opa_trace": opa.get("opa_trace", []),
        }

    def moderate_sequential(
        self, topic: Dict, registry, artifact: Optional[Dict[str, Any]] = None
    ) -> tuple:
        """逐一發言；輪到某人前先讓他即時回答指向他的問題，再發言（可依問答調整立場）。回傳 (contributions, oq_records)。"""
        contributions = [
            c for c in (topic.get("seed_previous_responses") or [])
            if isinstance(c, dict)
        ]
        oq_records = []
        speaking_order = topic.get("speaking_order") or topic.get("participants") or []
        if not speaking_order:
            self.logger.warning(f"[{topic['id']}] 無發言者")
            return (contributions, oq_records)
        title = topic.get("title", "") or "（無標題）"
        self.logger.info(f"[{topic['id']}] {title} — 逐一: {' → '.join(speaking_order)}")

        snapshot = self.build_artifact_snapshot(artifact)
        for agent_name in speaking_order:
            agent = registry.get(agent_name)
            if not agent:
                self.logger.warning(f"Agent '{agent_name}' 未註冊，跳過")
                continue
            answer_contribs, answer_oq = self.answer_questions_for_agent(
                contributions, agent_name, registry, snapshot, artifact
            )
            contributions.extend(answer_contribs)
            oq_records.extend(answer_oq)
            try:
                response = self.collect_topic_response(
                    agent,
                    topic,
                    previous_responses=contributions,
                    artifact_snapshot=snapshot,
                )
                response = self.attach_agent_action(topic, agent_name, response)
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
                self.logger.warning(f"  {agent_name} 發言失敗: {e}")
                contributions.append(
                    {"agent": agent_name, "response": {"content": f"（發言失敗: {e}）"}}
                )
            follow_ups = self.get_follow_ups_after_answers(
                contributions, answer_contribs, registry, snapshot, artifact
            )
            contributions.extend(follow_ups)

        return (contributions, oq_records)

    def respond_one_simultaneous(
        self,
        agent_name: str,
        topic: Dict,
        registry,
        artifact: Optional[Dict[str, Any]],
        snapshot: Dict[str, Any],
    ) -> Dict[str, Any]:
        """單一 agent 發言，供 moderate_simultaneous 並行呼叫。"""
        agent = registry.get(agent_name)
        if not agent:
            self.logger.warning(f"Agent '{agent_name}' 未註冊，跳過")
            return {"agent": agent_name, "response": {"content": "（未註冊，跳過）"}}
        try:
            response = self.collect_topic_response(
                agent,
                topic,
                previous_responses=None,
                artifact_snapshot=snapshot,
            )
            response = self.attach_agent_action(topic, agent_name, response)
            return {
                "agent": agent_name,
                "response": (
                    response
                    if isinstance(response, dict)
                    else {"content": str(response)}
                ),
            }
        except Exception as e:
            self.logger.warning(f"  {agent_name} 發言失敗: {e}")
            return {"agent": agent_name, "response": {"content": f"（發言失敗: {e}）"}}

    def attach_agent_action(self, topic: Dict, agent_name: str, response: Any) -> Dict[str, Any]:
        payload = response if isinstance(response, dict) else {"content": str(response)}
        payload = dict(payload)
        actions = topic.get("agent_actions") if isinstance(topic.get("agent_actions"), dict) else {}
        action_info = actions.get(agent_name) if isinstance(actions.get(agent_name), dict) else {}
        action = str(action_info.get("action") or "").strip()
        focus = str(action_info.get("focus") or "").strip()
        if action:
            payload["action"] = action
        if focus:
            payload["action_focus"] = focus
        return payload

    def moderate_simultaneous(
        self, topic: Dict, registry, artifact: Optional[Dict[str, Any]] = None
    ) -> List[Dict]:
        participants = topic.get("participants") or []
        if not participants:
            self.logger.warning(f"[{topic.get('id', '?')}] 無發言者")
            return []
        title = topic.get("title", "") or "（無標題）"
        self.logger.info(f"[{topic['id']}] {title} — 同時: {', '.join(participants)}")

        snapshot = self.build_artifact_snapshot(artifact)
        max_workers = min(len(participants), 6)
        contributions_by_agent = {}

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    self.respond_one_simultaneous,
                    agent_name,
                    topic,
                    registry,
                    artifact,
                    snapshot,
                ): agent_name
                for agent_name in participants
            }
            for future in as_completed(futures):
                agent_name = futures[future]
                try:
                    contrib = future.result()
                    contributions_by_agent[contrib["agent"]] = contrib
                except Exception as e:
                    self.logger.warning(f"  {agent_name} 發言失敗: {e}")
                    contributions_by_agent[agent_name] = {
                        "agent": agent_name,
                        "response": {"content": f"（發言失敗: {e}）"},
                    }

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
        snapshot: Dict,
        artifact: Optional[Dict[str, Any]],
    ) -> tuple:
        """讓 agent_name 即時回答目前 contributions 中指向他的問題。回傳 (要 append 的 contributions, oq_records)。"""
        questions = self.get_questions_to_agent(contributions, agent_name)
        if not questions:
            return ([], [])
        target_agent = registry.get(agent_name) if registry else None
        if not target_agent:
            return ([], [{**q, "status": "deferred"} for q in questions])
        added = []
        oq_records = []
        current_contributions = list(contributions)
        for q_record in questions:
            try:
                q_topic = self.build_reply_topic(
                    question=q_record["question"],
                    from_agent=q_record["from_agent"],
                    follow_up_hint=(
                        "（請簡要針對此問題回答；若前面發言已涵蓋可寫「如前述」或只補充重點。"
                        "回答後若尚未發言，可在輪到你發言時依此問答補充或微調立場。）"
                    ),
                )
                response = self.collect_topic_response(
                    target_agent,
                    q_topic,
                    previous_responses=current_contributions,
                    artifact_snapshot=snapshot,
                )
                resp = (
                    response
                    if isinstance(response, dict)
                    else {"content": str(response)}
                )
                resp = dict(resp)
                resp["reply_to_question"] = q_record["question"]
                resp["reply_to_agent"] = q_record["from_agent"]
                answer = resp.get("statement") or resp.get("content", "")
                contrib = {
                    "agent": agent_name,
                    "response": resp,
                    "is_reply": True,
                }
                added.append(contrib)
                current_contributions.append(contrib)
                oq_records.append({**q_record, "status": "answered", "answer": answer})
            except Exception:
                oq_records.append({**q_record, "status": "deferred"})
        return (added, oq_records)

    def get_follow_ups_after_answers(
        self,
        contributions: List[Dict],
        answer_contribs: List[Dict],
        registry,
        snapshot: Dict,
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
            ans = resp.get("statement") or resp.get("content", "")
            requester_qa.setdefault(from_agent, []).append((q, ans))
        result = []
        for requester_name, qa_list in requester_qa.items():
            agent = registry.get(requester_name) if registry else None
            if not agent:
                continue
            desc_parts = [
                f"你問：{q}\n對方回答：{a}" for q, a in qa_list
            ]
            follow_topic = {
                "id": "OQ-follow",
                "title": "依回答補充或調整發言",
                "description": (
                    "\n\n".join(desc_parts)
                    + "\n\n請依上述回答簡要說明你是否要補充或調整你的立場；若無需補充請寫「無需補充」。"
                ),
            }
            try:
                response = self.collect_topic_response(
                    agent,
                    follow_topic,
                    previous_responses=contributions,
                    artifact_snapshot=snapshot,
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
            except Exception:
                pass
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
        snapshot = self.build_artifact_snapshot(artifact)

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
                return (
                    q_record,
                    None,
                    {
                        **q_record,
                        "status": "deferred",
                        "deferred_count": int(q_record.get("deferred_count") or 0) + 1,
                        "needs_agenda": False,
                    },
                )
            try:
                q_topic = self.build_reply_topic(
                    question=q_record["question"],
                    from_agent=q_record["from_agent"],
                    follow_up_hint=(
                        "（請簡要針對此問題回答，若前面發言已涵蓋可寫「如前述」或只補充重點，勿整段重複相同內容。）"
                    ),
                )
                response = self.collect_topic_response(
                    target_agent,
                    q_topic,
                    previous_responses=contributions,
                    artifact_snapshot=snapshot,
                )
                resp = (
                    response
                    if isinstance(response, dict)
                    else {"content": str(response)}
                )
                resp = dict(resp)
                resp["reply_to_question"] = q_record["question"]
                resp["reply_to_agent"] = q_record["from_agent"]
                answer = resp.get("statement") or resp.get("content", "")
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
                        "needs_agenda": False,
                    },
                )
            except Exception:
                return (
                    q_record,
                    None,
                    {
                        **q_record,
                        "status": "deferred",
                        "deferred_count": int(q_record.get("deferred_count") or 0) + 1,
                        "needs_agenda": False,
                    },
                )

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
                    _q, contrib, oq = future.result()
                    results_by_idx[idx] = (contrib, oq)
                except Exception as e:
                    self.logger.warning(f"開放問題回答失敗: {e}")
                    results_by_idx[idx] = (
                        None,
                        {
                            **valid_questions[idx],
                            "status": "deferred",
                            "deferred_count": int(valid_questions[idx].get("deferred_count") or 0) + 1,
                            "needs_agenda": False,
                        },
                    )

        for i in range(len(valid_questions)):
            contrib, oq = results_by_idx.get(
                i,
                (
                    None,
                    {
                        **valid_questions[i],
                        "status": "deferred",
                        "deferred_count": int(valid_questions[i].get("deferred_count") or 0) + 1,
                        "needs_agenda": False,
                    },
                ),
            )
            q_text = (oq.get("question") or "").strip()
            if oq.get("status") != "answered":
                oq["needs_agenda"] = self.should_escalate_open_question(oq)
                if oq["needs_agenda"]:
                    oq["status"] = "escalate_to_topic"
            oq_records.append(oq)
            if contrib:
                contributions.append(contrib)

        return oq_records
