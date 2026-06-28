# Handles issue proposal and issue response flow.
import json
from typing import Any, Dict, List, Optional

from agents.profile.base import proposal_prompt
from .actions.response import issue_response

# ========
# Defines AnalystIssues class for this module workflow.
# ========
class AnalystIssues:
    # Defines propose issues function for this module workflow.
    def propose_issues(
        self,
        artifact: Dict[str, Any],
        *,
        round_num: int,
        max_items: int = 20,
    ) -> List[Dict[str, Any]]:
        opa = self.run_action_loop(
            name="analyst_issue_proposal",
            context={
                "artifact": artifact,
                "round_num": round_num,
                "max_items": max(1, max_items),
            },
            obs_fn=self.obs_issue,
            decide_action=self.decide_analyst_issue_action,
            execute_action=self.execute_analyst_issue_action,
        )
        trace = opa.get("opa_trace") or []
        result = dict((trace[-1].get("result") if trace else {}) or {})
        if result.get("error"):
            raise RuntimeError(result.get("format_error") or result.get("error"))
        return result.get("proposals", [])[: max(1, max_items)]

    # Defines build requirement issue signals function for this module workflow.
    def build_requirement_issue_signals(self, artifact: Dict[str, Any]) -> List[Dict[str, Any]]:
        signals: List[Dict[str, Any]] = []
        for c in all_conflict_rows(artifact):
            if not isinstance(c, dict):
                continue
            cid = str(c.get("id") or "").strip()
            if cid and str(c.get("final_label") or "").strip() == "Conflict":
                signals.append(
                    {
                        "kind": "unresolved_conflict",
                        "ids": [cid] + list(c.get("requirement_ids", []) or []),
                        "summary": str(c.get("description") or "").strip(),
                    }
                )

        for oq in artifact.get("open_questions", []) or []:
            if not isinstance(oq, dict) or oq.get("status") == "answered":
                continue
            question = str(oq.get("question") or "").strip()
            if question:
                signals.append(
                    {
                        "kind": "unanswered_open_question",
                        "ids": [
                            str(oq.get("source_conflict_id") or "").strip()
                        ] if str(oq.get("source_conflict_id") or "").strip() else [],
                        "summary": question,
                    }
                )

        for req in requirement_discussion_pool(artifact):
            if not isinstance(req, dict):
                continue
            rid = str(req.get("id") or "").strip()
            text = str(req.get("text") or "").strip()
            if not rid or not text:
                continue
            issues: List[str] = []
            source_text = str(req.get("source") or "").strip()
            if not source_text:
                issues.append("missing_source_trace")
            if len(text) < 12:
                issues.append("unclear_requirement_text")
            if issues:
                signals.append(
                    {
                        "kind": "requirement_quality_gap",
                        "ids": [rid],
                        "summary": text,
                        "issues": issues,
                    }
                )

        return signals

    # Defines obs issue function for this module workflow.
    def obs_issue(self, **kwargs: Any) -> Dict[str, Any]:
        artifact = kwargs["artifact"]
        return {
            "iteration": kwargs.get("iteration", 0) + 1,
            "max_iterations": kwargs["max_iterations"],
            "round_num": kwargs.get("round_num"),
            "max_items": kwargs.get("max_items", 20),
            "latest_draft": artifact.get("latest_draft", ""),
            "artifact_slices": artifact.get("artifact_slices") if isinstance(artifact.get("artifact_slices"), dict) else {},
        }

    # Defines decide analyst issue action function for this module workflow.
    def decide_analyst_issue_action(
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
                "reasoning": "上一輪 Analyst issue proposal 已符合格式契約，結束提案。",
            }
        return {
            "action": "propose_issues",
            "params": {},
            "reasoning": "根據需求品質、需求範圍、可驗收性、可追蹤性與未決缺口提出需要會議處理的議題。",
        }

    # Defines execute analyst issue action function for this module workflow.
    def execute_analyst_issue_action(
        self,
        *,
        decision: Dict[str, Any],
        observation: Dict[str, Any],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        action = str(decision.get("action") or "").strip()
        if action != "propose_issues":
            return {
                "action": action,
                "status": "failed",
                "error": "unsupported_action",
                "format_error": f"Analyst issue proposal 不支援 action: {action}",
            }

        max_items = int(observation.get("max_items") or 20)
        context = {
            "round_num": observation.get("round_num"),
            "latest_draft": observation.get("latest_draft", ""),
            "artifact_slices": observation.get("artifact_slices") or {},
        }
        prompt = proposal_prompt(
            agent_label="需求工程",
            focus="需求語意、範圍、驗收條件、來源追蹤或需求規格化",
            value_gate=[
                "會阻礙需求規格定稿、需求可驗收性、scope 穩定或來源追蹤。",
                "可能需要正式會議中的至少兩方觀點、取捨、確認或決策；若不確定是否需要開會，也可以提出給 Mediator 判斷。",
            ],
            reject_rule=(
                "通常不值得提出：純措辭潤飾、無 source id 的猜測、小型重複問題。"
                "單一欄位、單一 acceptance criteria 或單一 id 若可能影響驗收、追蹤、責任邊界或風險，也可以提出。"
            ),
        )
        try:
            data = self.chat_json(self.build_direct_messages(prompt, context=context))
            proposals = self.analyst_issue_proposals_payload(
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
                "summary": "Analyst issue proposal 輸出格式不合格",
            }
        return {
            "action": action,
            "status": "success",
            "proposals": proposals,
            "summary": f"Analyst 提出 {len(proposals)} 筆 issue proposal",
        }

    # Defines analyst issue proposals payload function for this module workflow.
    def analyst_issue_proposals_payload(
        self,
        data: Dict[str, Any],
        *,
        round_num: int,
        max_items: int,
    ) -> List[Dict[str, Any]]:
        raw_issues = data
        if isinstance(raw_issues, dict):
            raw_issues = raw_issues.get("issues") or raw_issues.get("proposals") or []
        if not isinstance(raw_issues, list):
            raise ValueError("Analyst issue proposal 必須直接輸出 issues list")

        allowed_importance = {"high", "medium", "low"}
        proposals: List[Dict[str, Any]] = []
        seen = set()
        for idx, row in enumerate(raw_issues, 1):
            if not isinstance(row, dict):
                raise ValueError(f"issues[{idx}] 必須是 object")
            title = str(row.get("title") or "").strip()
            if not title:
                raise ValueError(f"issues[{idx}] 缺少 title")
            expect_outcome = str(row.get("expect_outcome") or "").strip()
            sources = []
            for source in row.get("sources") or []:
                if not isinstance(source, dict):
                    continue
                artifact = str(source.get("artifact") or "").strip()
                ids = [
                    str(x).strip()
                    for x in (source.get("ids") or [])
                    if str(x).strip()
                ]
                evidence = str(source.get("evidence") or "").strip()
                if artifact and evidence:
                    sources.append({"artifact": artifact, "ids": list(dict.fromkeys(ids)), "evidence": evidence})
            reason = str(row.get("reason") or "").strip()
            if not expect_outcome or not sources or not reason:
                raise ValueError(f"issues[{idx}] 缺少 expect_outcome/sources/reason")

            importance = str(row.get("importance") or "").strip().lower()
            if importance not in allowed_importance:
                raise ValueError(f"issues[{idx}] importance 不合法: {importance or '<empty>'}")
            issue_level = str(row.get("issue_level") or "").strip().lower()
            if issue_level not in {"blocking", "improvement"}:
                issue_level = "blocking" if importance == "high" else "improvement"

            key = (title, json.dumps(sources, ensure_ascii=False, sort_keys=True))
            if key in seen:
                continue
            seen.add(key)
            proposals.append(
                {
                    "title": title,
                    "category": str(row.get("category") or "").strip(),
                    "issue_focus": str(row.get("issue_focus") or "").strip(),
                    "expect_outcome": expect_outcome,
                    "sources": sources,
                    "issue_level": issue_level,
                    "importance": importance,
                    "reason": reason,
                    "proposed_by": "analyst",
                    "round": round_num,
                }
            )
            if len(proposals) >= max_items:
                break
        return proposals

    # Defines build response function for this module workflow.
    def build_response(
        self,
        *,
        issue: Dict[str, Any],
        previous_responses: Optional[List[Dict[str, Any]]],
        related_context: Optional[Dict[str, Any]],
    ) -> str:
        return issue_response(
            issue=issue,
            previous_responses=previous_responses,
            related_context=related_context,
        )



# ========
# Defines AnalystResponse class for this module workflow.
# ========
class AnalystResponse:
    # Defines obs response function for this module workflow.
    def obs_response(self, **kwargs: Any) -> Dict[str, Any]:
        return self.issue_response_observation(**kwargs)

    # Defines execute action function for this module workflow.
    def execute_action(
        self,
        *,
        decision: Dict[str, Any],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        action = str(decision.get("action") or "").strip()
        artifact = kwargs.get("artifact")
        analyst_action_result = None
        if isinstance(artifact, dict):
            try:
                if action == "analyze_requirements":
                    meeting_stakeholders = self.meeting_requirement_sources(
                        kwargs.get("previous_responses"),
                        kwargs["issue"],
                    )
                    output = self.run_requirements_analyst(
                        "analyze_requirements",
                        stakeholders=meeting_stakeholders,
                        artifact=artifact,
                    )
                    self.merge_meeting_requirements(
                        artifact,
                        output,
                        issue=kwargs["issue"],
                    )
                    analyst_action_result = {
                        "action": action,
                        "requirements": output if isinstance(output, list) else [],
                    }
                elif action == "refine_scope":
                    analyst_action_result = self.execute_refine_scope(
                        artifact=artifact,
                        issue=kwargs["issue"],
                        previous_responses=kwargs.get("previous_responses"),
                    )
                elif action == "update_requirement":
                    analyst_action_result = self.execute_update_requirement(
                        artifact=artifact,
                        issue=kwargs["issue"],
                        previous_responses=kwargs.get("previous_responses"),
                    )
                elif action == "refine_requirement":
                    analyst_action_result = self.execute_refine_requirement(
                        artifact=artifact,
                        issue=kwargs["issue"],
                        previous_responses=kwargs.get("previous_responses"),
                    )
                elif action == "analyze_conflicts":
                    analyst_action_result = self.analyze_conflicts(
                        artifact=artifact,
                        last_result=kwargs.get("last_result"),
                    )
                elif action == "discuss_conflict":
                    analyst_action_result = {
                        "action": action,
                        "summary": "讀取既有衝突報告，針對解決選項與建議解法討論取捨，不重新執行衝突辨識。",
                    }
                elif action == "respond_issue":
                    analyst_action_result = {
                        "action": action,
                        "summary": "只產生會議回答，不更新專案資料。",
                    }
                elif action == "answer_question":
                    analyst_action_result = {
                        "action": action,
                        "summary": "回答 open question，不更新專案資料。",
                    }
            except Exception as e:
                analyst_action_result = {
                    "action": action,
                    "error": str(e),
                    "summary": f"analyst action failed: {action}",
                }
        elif action in {
            "analyze_requirements",
            "refine_scope",
            "update_requirement",
            "refine_requirement",
            "analyze_conflicts",
        }:
            return {
                "action": action,
                "status": "failed",
                "error": "missing_artifact",
                "format_error": f"{action} requires artifact context",
                "summary": f"analyst {action} 缺少 artifact，無法執行分析",
            }
        return analyst_action_result or {"action": action, "summary": f"完成 analyst action: {action}"}
