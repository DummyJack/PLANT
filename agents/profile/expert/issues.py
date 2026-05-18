# Expert issue logic: propose domain issues and build expert meeting responses.
import json
from typing import Any, Dict, List, Optional

from utils.language import current_output_language

from agents.profile.conflict_review import conflict_review_text_hint
from agents.profile.analyst.conflict_store import all_conflict_rows
from agents.profile.analyst.requirements import requirement_discussion_pool

from .prompts import (
    EXPERT_CONFLICT_ISSUE_RULES,
    EXPERT_ELICITATION_CONTEXT_RULES,
    EXPERT_ISSUE_RULES,
    EXPERT_ISSUE_TASK,
    expert_elicitation_action_rules,
    expert_elicitation_action_task,
)


class ExpertIssues:
    def propose_issues(
        self,
        artifact: Dict[str, Any],
        *,
        round_num: int,
        max_items: int = 2,
    ) -> List[Dict]:
        opa = self.run_action_loop(
            name="expert_issue_proposal",
            context={
                "artifact": artifact,
                "round_num": round_num,
                "max_items": max(1, max_items),
            },
            build_observation=self.build_expert_issue_observation,
            decide_action=self.decide_expert_issue_action,
            execute_action=self.execute_expert_issue_action,
        )
        trace = opa.get("opa_trace") or []
        result = dict((trace[-1].get("result") if trace else {}) or {})
        if result.get("error"):
            raise RuntimeError(result.get("format_error") or result.get("error"))
        return result.get("proposals", [])[: max(1, max_items)]

    def build_expert_issue_observation(self, **kwargs: Any) -> Dict[str, Any]:
        artifact = kwargs["artifact"]
        research = artifact.get("feedback") if isinstance(artifact.get("feedback"), dict) else {}
        requirements = [
            row for row in requirement_discussion_pool(artifact) if isinstance(row, dict)
        ]
        open_questions = [
            row for row in (artifact.get("open_questions") or []) if isinstance(row, dict)
        ]
        conflicts = [
            row for row in all_conflict_rows(artifact) if isinstance(row, dict)
        ]
        return {
            "iteration": kwargs.get("iteration", 0) + 1,
            "max_iterations": kwargs["max_iterations"],
            "round_num": kwargs.get("round_num"),
            "max_items": kwargs.get("max_items", 2),
            "requirements": requirements,
            "open_questions": open_questions,
            "conflicts": conflicts,
            "feedback": research,
            "recent_discussions": artifact.get("recent_discussions", []),
            "existing_issue_proposals": artifact.get("issue_proposals", []),
            "decision_history": artifact.get("decisions", []),
        }

    def decide_expert_issue_action(
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
                "reasoning": "上一輪 Expert issue proposal 已符合格式契約，結束提案。",
            }
        return {
            "action": "propose_domain_issues",
            "params": {},
            "reasoning": "從外部義務、domain risk 與 evidence gap 角度提出需要會議處理的議題。",
        }

    def execute_expert_issue_action(
        self,
        *,
        decision: Dict[str, Any],
        observation: Dict[str, Any],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        action = str(decision.get("action") or "").strip()
        if action != "propose_domain_issues":
            return {
                "action": action,
                "status": "failed",
                "error": "unsupported_action",
                "format_error": f"Expert issue proposal 不支援 action: {action}",
            }

        max_items = int(observation.get("max_items") or 2)
        context = {
            "round_num": observation.get("round_num"),
            "requirements": observation.get("requirements", []),
            "open_questions": observation.get("open_questions", []),
            "conflicts": observation.get("conflicts", []),
            "feedback": observation.get("feedback", {}),
            "recent_discussions": observation.get("recent_discussions", []),
            "existing_issue_proposals": observation.get("existing_issue_proposals", []),
            "decision_history": observation.get("decision_history", []),
        }
        prompt = f"""# 任務
提出本輪需要進入 issue proposal 的 domain / compliance / risk 議題。

# 提案邊界
- 只提出會影響 requirement、constraint、risk 或 evidence basis 的議題。
- 可以根據既有 feedback 的 constraints / risks / recommendations / open_items 提案，但必須說明適用範圍與需求影響。
- feedback 是領域研究輔助資料，不是正式需求；不得直接把 recommendations 升格成 new_requirement，除非明確需要 stakeholder 或 analyst 確認。
- 可以根據 open_questions 提案，但只有合規、標準、安全、外部義務、領域風險或 evidence gap 會改變需求時才提出。
- 可以根據 requirements 主動發現問題，例如安全/合規/可用性/可靠性/NFR 沒有可驗證標準，或外部限制沒有證據。
- 議題必須聚焦 domain / compliance / risk / evidence basis，不提出無外部限制或證據影響的一般需求議題。
- 不要重複 existing_issue_proposals 或近期已完成決策。
- 最多提出 {max_items} 筆；若沒有必要議題，issues 請輸出空陣列。

# 每筆 issue schema
- title：issue proposal 的短標籤，供 triage 參考；正式會議標題由 Mediator 另行命名
- description：說明 domain risk / obligation / evidence gap，以及會影響哪些需求內容
- category：只能是 open_question、new_requirement、tradeoff、conflict_discussion 其中之一
- participants：從 expert、analyst、modeler、user 挑選，必須包含 expert；若需要 user 確認適用性或風險接受度，加入 user
- discussion_mode：sequential 或 simultaneous
- speaking_order：必須與 participants 成員一致
- source_ids：相關 requirement/conflict/open question/research id；沒有就空陣列
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
            proposals = self.expert_issue_proposals_payload(
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
                "summary": "Expert issue proposal 輸出格式不合格",
            }
        return {
            "action": action,
            "status": "success",
            "proposals": proposals,
            "summary": f"Expert 提出 {len(proposals)} 筆 issue proposal",
        }

    def expert_issue_proposals_payload(
        self,
        data: Dict[str, Any],
        *,
        round_num: int,
        max_items: int,
    ) -> List[Dict[str, Any]]:
        if not isinstance(data, dict):
            raise ValueError("Expert issue proposal 必須輸出 JSON object")
        raw_issues = data.get("issues")
        if not isinstance(raw_issues, list):
            raise ValueError("Expert issue proposal 必須包含 issues list")

        allowed_categories = {
            "conflict_discussion",
            "open_question",
            "new_requirement",
            "tradeoff",
        }
        allowed_participants = {"expert", "analyst", "modeler", "user"}
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
            if "expert" not in participants:
                raise ValueError(f"issues[{idx}] participants 必須包含 expert")

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
                    "proposed_by": "expert",
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
                f"【{r.get('agent', '?')}】\n{r.get('response', {}).get('text', '')}"
                for r in previous_responses
            ]
            prev_text = "\n前面的發言:\n" + "\n\n".join(parts)

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
        my_action = agent_actions.get("expert") if isinstance(agent_actions.get("expert"), dict) else {}
        if my_action:
            my_action_text = (
                "\n# 本輪你的 action\n"
                + json.dumps(my_action, ensure_ascii=False, indent=2)
            )

        skill_section = ""
        skill_context = self.get_optional_skill_context(issue, artifact_context)
        if skill_context:
            skill_section = f"\n# Skill 參考（本輪由 agent 自行判斷使用）\n{skill_context}\n"
        category = (issue.get("category") or "").strip()
        allow_suggested_next_action = (
            category != "conflict_discussion"
            and not issue_id.startswith("ELICIT-")
        )

        if category == "conflict_discussion":
            category_hint = EXPERT_CONFLICT_ISSUE_RULES
        elif category == "tradeoff":
            category_hint = """# 本議題特別要求（tradeoff）
    - 說明外部限制、證據強度、風險後果，以及在合規/安全底線下不可接受的選項。"""
        elif category == "open_question":
            category_hint = """# 本議題特別要求（open_question）
    - 優先回答可確認的領域事實、外部限制與證據缺口；只提出會影響限制、風險或證據依據的問題。"""
        elif category == "new_requirement":
            category_hint = """# 本議題特別要求（new_requirement）
    - 說明此新增需求是否只是候選限制、非功能需求或風險緩解方向，以及是否來自強制義務、最佳實務或證據缺口。"""
        else:
            category_hint = ""

        response_contract = """# 回應契約
    - text 必須有依據，不可只表態或宣告最終決議。
    - open_questions 只放真正需要後續回答、且會影響限制/風險/驗收邊界的單一具體問題；沒有就輸出空陣列。"""

        next_action_contract = ""
        pair_reviews_json = ""
        text_hint = '"text": "針對此議題的完整發言內容"'
        suggested_next_action_json = ""
        if allow_suggested_next_action:
            suggested_next_action_json = """,
    "suggested_next_action": {
        "type": "direct_clarification | new_issue",
        "reason": "為何建議會後安排這一步",
        "target_ids": ["可選，相關 requirement/conflict/issue id"],
        "urgency": "low | medium | high"
    }"""
        if allow_suggested_next_action:
            next_action_contract = """# suggested_next_action 規範
    - 可提供會後建議；它不會在會議中直接執行。無明確建議可省略或填 null。"""
        if category == "conflict_discussion":
            contract = issue.get("response_contract") if isinstance(issue.get("response_contract"), dict) else {}
            known_pair_ids = [
                str(pair_id).strip()
                for pair_id in (contract.get("known_pair_ids") or [])
                if str(pair_id).strip()
            ]
            known_pair_ids_text = json.dumps(known_pair_ids, ensure_ascii=False)
            pair_reviews_json = ""
            response_contract = """# 回應契約
    - 外層只能輸出合法 JSON object；不要 Markdown、不要 ```json 程式碼區塊、不要額外說明文字。
    - 外層只能有 text 欄位。
    - text 必須是 JSON object 字串，不是巢狀 object。
    - text JSON 結構必須為 {"pair_reviews":[...]}。
    - pair_reviews 必須逐筆涵蓋 response_contract.known_pair_ids 中每個 id，不能遺漏、不能新增未知 id。
    - 每筆 pair_reviews 都必須有 id、proposed_label、reason。
    - proposed_label 只能是 Conflict 或 Neutral。
    - reason 必須有依據，不可只表態或宣告最終決議。
    - 本輪必須涵蓋的 pair id：""" + known_pair_ids_text
            text_hint = conflict_review_text_hint()
            output_fields = f"    {text_hint}"
        else:
            if issue_id.startswith("ELICIT-"):
                output_fields = (
                    f"    {text_hint},\n"
                    '    "target_stakeholders": ["要詢問的 stakeholder 名稱，可一位或多位"]'
                    f"{suggested_next_action_json}{pair_reviews_json}"
                )
            else:
                output_fields = (
                    f"    {text_hint},\n"
                    '    "open_questions": [{"to": "目標 agent 名稱", "question": "問題"}]'
                    f"{suggested_next_action_json}{pair_reviews_json}"
                )

        elicitation_hint = ""
        task_block = EXPERT_ISSUE_TASK
        rules_block = EXPERT_ISSUE_RULES
        if issue_id.startswith("ELICIT-"):
            stop_phrase = (
                "I have gathered enough information"
                if current_output_language() == "en"
                else "我已蒐集足夠資訊"
            )
            elicitation_hint = EXPERT_ELICITATION_CONTEXT_RULES
            task_block = expert_elicitation_action_task(stop_phrase)
            rules_block = expert_elicitation_action_rules(stop_phrase)
        return f"""{issue_text}
    {prev_text}
    {context_text}
    {recent_ask_history_text}
    {my_action_text}
    {skill_section}
    {category_hint}
    {elicitation_hint}

    {response_contract}

    {next_action_contract}

    # 任務
    {task_block}

    # 規則
    {rules_block}

    # 輸出 JSON
    {{
{output_fields}
    }}"""
