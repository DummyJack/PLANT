# Expert domain research: optional skill context plus evidence gathering loop.
from agents.profile.prompt_catalog import render_prompt
import json

from agents.profile.scenario import scenario_prompt_value

from .validation import clean_domain_research, clean_research_result


ACTIONS = [
    "read_reference_docs",
    "research_issue",
    "update_feedback",
    "done",
]


def research_requirement_candidates(artifact):
    rows = []
    for req in artifact.get("URL") or []:
        if not isinstance(req, dict) or not str(req.get("text") or "").strip():
            continue
        row = {
            "id": req.get("id"),
            "text": req.get("text"),
            "priority": req.get("priority"),
            "source": req.get("source", ""),
        }
        rows.append(row)
    return rows


def research_stakeholders(artifact):
    rows = []
    for stakeholder in artifact.get("stakeholders") or []:
        if not isinstance(stakeholder, dict):
            continue
        name = str(stakeholder.get("name") or "").strip()
        if not name:
            continue
        row = {"name": name}
        stakeholder_type = str(stakeholder.get("type") or "").strip()
        if stakeholder_type:
            row["type"] = stakeholder_type
        rows.append(row)
    return rows


def research_open_questions(artifact):
    rows = []
    for question in artifact.get("open_questions") or []:
        if not isinstance(question, dict):
            continue
        text = str(question.get("question") or "").strip()
        if not text:
            continue
        rows.append(
            {
                "question": text,
                "status": question.get("status"),
                "type": question.get("type"),
            }
        )
    return rows


def research_source(artifact):
    issue = artifact.get("current_issue") if isinstance(artifact.get("current_issue"), dict) else {}
    meeting_id = str(issue.get("meeting_id") or "").strip()
    if meeting_id:
        return meeting_id
    issue_id = str(issue.get("id") or "").strip()
    if issue_id:
        return issue_id
    return "initial"


class ExpertDomainResearch:
    def run_domain_research_loop(self, artifact):
        """Expert domain research 走共用 agent loop，由 Expert 判斷是否寫回 feedback。"""
        result = self.run_action_loop(
            name="domain_research",
            context={
                "artifact": artifact,
                "research_results": [],
            },
            build_observation=self.build_domain_research_observation,
            decide_action=self.decide_domain_research_action,
            execute_action=self.execute_domain_research_loop_action,
        )
        return result

    def build_research_observation(
        self, artifact,
        research_results, iteration, max_iterations,
    ):
        user_requirements = research_requirement_candidates(artifact)
        existing = artifact.get("feedback") if isinstance(artifact.get("feedback"), dict) else {}
        scenario_source = artifact.get("scenario") or artifact.get("rough_idea")
        return {
            "issue": artifact.get("current_issue") if isinstance(artifact.get("current_issue"), dict) else {},
            "scenario": scenario_prompt_value(scenario_source),
            "scope": artifact.get("scope", {}),
            "user_requirements": user_requirements,
            "stakeholders": research_stakeholders(artifact),
            "open_questions": research_open_questions(artifact),
            "has_existing_research": bool(existing),
            "research_results_count": len(research_results),
            "document_evidence_count": len(artifact.get("document_evidence", []) or []),
            "has_read_file": "read_file" in self.tools,
            "has_web_search": "web_search" in self.tools,
            "iteration": iteration + 1,
            "max_iterations": max_iterations,
        }

    def execute_domain_research_action(
        self, action, params, artifact, research_results,
    ):
        obs: dict = {"action": action, "result": None, "error": None, "summary": ""}

        if action == "read_reference_docs":
            if "read_file" not in self.tools:
                obs["summary"] = "read_file 工具不可用，略過文件讀取"
                obs["result"] = {"document_evidence": [], "gaps": ["read_file 工具不可用"]}
                return obs
            query = str(params.get("query") or params.get("topic") or "").strip()
            if not query:
                obs["error"] = "query 參數為空"
                obs["summary"] = "文件讀取失敗：未提供查詢問題"
                return obs
            scenario_source = artifact.get("scenario") or artifact.get("rough_idea")
            context = {
                "issue": artifact.get("current_issue") if isinstance(artifact.get("current_issue"), dict) else {},
                "scenario": scenario_prompt_value(scenario_source),
                "scope": artifact.get("scope", {}),
                "user_requirements": research_requirement_candidates(artifact),
                "stakeholders": research_stakeholders(artifact),
                "open_questions": research_open_questions(artifact),
                "existing_document_evidence": artifact.get("document_evidence", []) or [],
            }
            task = f"""# 任務
針對以下研究問題，先查找 doc/ 內專案參考文件並整理文件證據。

# 研究問題
{query}

# 規則
- 必須使用 read_file 搜尋或讀取相關文件片段。
- 只整理和研究問題、source requirements 或目前議題直接相關的文件證據。
- 若文件沒有相關內容，document_evidence 輸出空陣列，並在 gaps 說明缺口。
- 每筆 document_evidence 必須包含 source；source 要能追蹤到文件名稱、路徑或片段位置。
- related_requirement_ids 只能引用輸入 user_requirements 中存在的 id；不能編造 URL-*。
- 不要根據文件證據產生正式需求；只做 evidence summary。

# 輸出 JSON
{{
  "document_evidence": [
    {{
      "source": "doc/...",
      "section": "章節或片段位置",
      "summary": "文件證據摘要",
      "related_requirement_ids": ["URL-1"]
    }}
  ],
  "gaps": []
}}"""
            try:
                raw = self.chat_with_tools(
                    self.build_direct_messages(task, context=context),
                    active_skill="domain-research",
                )
                data = self.parse_first_json(raw)
                evidence = self.clean_document_evidence(data.get("document_evidence"))
                gaps = [
                    str(item).strip()
                    for item in (data.get("gaps") or [])
                    if str(item).strip()
                ]
                artifact["document_evidence"] = self.merge_document_evidence(
                    artifact.get("document_evidence", []),
                    evidence,
                )
                obs["result"] = {"document_evidence": evidence, "gaps": gaps}
                obs["context_updates"] = {"artifact": artifact}
                obs["summary"] = f"文件證據 {len(evidence)} 筆，缺口 {len(gaps)} 筆"
            except Exception as e:
                obs["error"] = str(e)
                obs["summary"] = f"文件讀取失敗: {e}"
            return obs

        if action == "research_issue":
            query = params.get("query", "")
            if not query:
                obs["error"] = "query 參數為空"
                obs["summary"] = "研究失敗：未提供研究問題"
                return obs
            scenario_source = artifact.get("scenario") or artifact.get("rough_idea")
            context = {
                "issue": artifact.get("current_issue") if isinstance(artifact.get("current_issue"), dict) else {},
                "scenario": scenario_prompt_value(scenario_source),
                "scope": artifact.get("scope", {}),
                "user_requirements": research_requirement_candidates(artifact),
                "stakeholders": research_stakeholders(artifact),
                "open_questions": research_open_questions(artifact),
                "document_evidence": artifact.get("document_evidence", []) or [],
            }
            source_ref = research_source(artifact)
            task = render_prompt('agents_profile_expert_domain_research_task_24', **locals())
            messages = self.build_direct_messages(task, context=context)
            try:
                raw = (
                    self.chat_with_tools(
                        messages,
                        active_skill="domain-research",
                    )
                    if self.tools
                    else self.model.chat(messages)
                )
                result = clean_research_result(
                    self.parse_first_json(raw),
                    default_source=source_ref,
                )
                research_results.append({"query": query, **result})
                obs["result"] = result
                obs["summary"] = (
                    f"研究 '{query}': "
                    f"{len(result.get('findings', []))} 項發現"
                )
            except Exception as e:
                obs["error"] = str(e)
                obs["summary"] = f"研究失敗: {e}"
            return obs

        if action == "update_feedback":
            if not research_results:
                obs["summary"] = "無研究結果可更新"
                return obs
            existing = artifact.get("feedback") if isinstance(artifact.get("feedback"), dict) else {}
            context = {
                "research_results": research_results,
                "existing_research": existing,
                "document_evidence": artifact.get("document_evidence", []) or [],
            }
            source_ref = research_source(artifact)
            task = render_prompt('agents_profile_expert_domain_research_task_25', **locals())
            try:
                raw = self.invoke_skill("domain-research", task, context=context)
                dr = clean_domain_research(
                    self.parse_first_json(raw),
                    default_source=source_ref,
                )
                if dr:
                    artifact["feedback"] = dr
                    obs["summary"] = "已更新領域研究資料"
                else:
                    obs["error"] = "解析失敗"
                    obs["summary"] = "更新失敗：解析錯誤"
            except Exception as e:
                obs["error"] = str(e)
                obs["summary"] = f"更新失敗: {e}"
            return obs

        obs["error"] = f"未知動作: {action}"
        return obs

    def decide_research_action(self, state, last_observation=None):
        state_text = json.dumps(state, ensure_ascii=False, indent=2)
        obs_text = json.dumps(last_observation or {}, ensure_ascii=False, indent=2)

        user_prompt = render_prompt('agents_profile_expert_domain_research_user_prompt_26', **locals())

        messages = self.build_direct_messages(user_prompt)
        try:
            if "artifact_query" in self.tools:
                raw = self.chat_with_tools(
                    messages,
                    active_skill="domain-research",
                )
                response = self.parse_issue_response_json(raw)
            else:
                response = self.chat_json(messages)
        except Exception as e:
            raise RuntimeError(f"Expert domain research 決策輸出格式不合格: {e}") from e
        if not isinstance(response, dict):
            raise ValueError(f"Expert domain research 決策必須是 JSON object，收到 {type(response).__name__}")

        action_plan = response.get("action_plan") if isinstance(response.get("action_plan"), dict) else {}
        steps = action_plan.get("steps") if isinstance(action_plan.get("steps"), list) else []
        clean_steps = []
        for step in steps:
            if not isinstance(step, dict):
                continue
            step_action = str(step.get("action") or "").strip()
            if step_action not in {"read_reference_docs", "research_issue", "update_feedback"}:
                continue
            params = step.get("params") if isinstance(step.get("params"), dict) else {}
            if step_action in {"read_reference_docs", "research_issue"} and not str(params.get("query") or "").strip():
                continue
            clean_steps.append({"action": step_action, "params": params})
        if any(step.get("action") == "research_issue" for step in clean_steps) and not any(
            step.get("action") == "update_feedback" for step in clean_steps
        ):
            clean_steps.append({"action": "update_feedback", "params": {}})
        if clean_steps:
            return {
                "action": "done",
                "params": {},
                "reasoning": response.get("reasoning", ""),
                "action_plan": {
                    "goal": str(action_plan.get("goal") or "完成本輪 domain research").strip(),
                    "steps": clean_steps,
                },
            }

        action = (response.get("action") or "").strip()
        if action not in ACTIONS:
            raise ValueError(f"Expert domain research action 不合法: {action or '<empty>'}")
        if action == "research_issue":
            params = response.get("params") or {}
            return {
                "action": "done",
                "params": {},
                "reasoning": response.get("reasoning", ""),
                "action_plan": {
                    "goal": "完成本輪 domain research",
                    "steps": [
                        {"action": "research_issue", "params": params},
                        {"action": "update_feedback", "params": {}},
                    ],
                },
            }
        if action == "done" and state.get("research_results_count", 0) > 0:
            action = "update_feedback"
        out = {
            "action": action,
            "params": response.get("params") or {},
            "reasoning": response.get("reasoning", ""),
        }
        return out

    @staticmethod
    def clean_document_evidence(raw):
        rows = []
        seen = set()
        for item in raw or []:
            if not isinstance(item, dict):
                continue
            source = str(item.get("source") or "").strip()
            summary = str(item.get("summary") or "").strip()
            if not source or not summary:
                continue
            row = {
                "source": source,
                "summary": summary,
                "related_requirement_ids": [
                    str(value).strip()
                    for value in (item.get("related_requirement_ids") or [])
                    if str(value).strip()
                ],
            }
            section = str(item.get("section") or "").strip()
            if section:
                row["section"] = section
            key = json.dumps(row, ensure_ascii=False, sort_keys=True)
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
        return rows

    @classmethod
    def merge_document_evidence(cls, existing, new_rows):
        rows = cls.clean_document_evidence(existing)
        seen = {
            json.dumps(row, ensure_ascii=False, sort_keys=True)
            for row in rows
        }
        for row in cls.clean_document_evidence(new_rows):
            key = json.dumps(row, ensure_ascii=False, sort_keys=True)
            if key in seen:
                continue
            rows.append(row)
            seen.add(key)
        return rows
