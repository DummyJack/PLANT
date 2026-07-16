# Handles agent responses during meetings.
import json
from typing import Any, Dict, List, Optional

from .actions.response import issue_response
from .repair import retry_response
from .rules import (
    category_hint as build_category_hint,
    open_question_rule,
    response_flow,
    response_json,
    stance_json,
    stance_rule,
    stakeholder_contract,
)


class UserResponse:
    def build_stakeholder_contract(
        self,
        related_context: Optional[Dict[str, Any]],
    ) -> str:
        return stakeholder_contract(
            related_context=related_context,
            stakeholders=self.stakeholders or [],
        )

    def build_response(
        self,
        *,
        issue: Dict[str, Any],
        previous_responses: Optional[List[Dict[str, Any]]],
        related_context: Optional[Dict[str, Any]],
    ) -> str:
        issue_text = f"議題 [{issue.get('id', '')}]: {issue.get('title', '')}\n描述: {issue.get('description', '')}"
        issue_category = (issue.get("category") or "").strip()
        stakeholder_contract_text = self.build_stakeholder_contract(related_context)
        target_stakeholders = [
            str(x).strip()
            for x in (issue.get("target_stakeholders") or [])
            if str(x).strip()
        ]
        target_set = set(target_stakeholders)
        answer_all_questions = bool(issue.get("answer_all"))

        speaking_as_list = []
        names_list: List[str] = []
        if self.stakeholders and target_set:
            speaking_as_list = [
                sh for sh in self.stakeholders
                if str(sh.get("name") or "").strip() in target_set
            ]
        if self.stakeholders and not speaking_as_list:
            if len(self.stakeholders) == 1:
                speaking_as_list = self.stakeholders
            else:
                speaking_as_list = []

        if len(speaking_as_list) == 1:
            sh = speaking_as_list[0]
            name = sh.get("name", "")
            names_list = [name]
            roles_text = f"\n# 本輪發言身份\n請「僅」以【{name}】的身份發言。"
        elif len(speaking_as_list) > 1:
            names = [s.get("name", "") for s in speaking_as_list]
            names_list = list(names)
            roles_text = (
                f"\n# 本輪發言身份（多位）\n請以【{'】與【'.join(names)}】的身份發言；若分段表述，請標明身份。"
            )
        elif self.stakeholders:
            names_list = [sh.get("name", "") for sh in self.stakeholders]
            roles_text = (
                "\n# 本輪回答身份\n"
                "本輪未指定回答身份；請只選擇與此議題最直接相關的一位或多位利害關係人發言，不要代表全部利害關係人泛泛回答。"
            )
        else:
            names_list = []
            roles_text = ""
        if target_stakeholders:
            roles_text += (
                "\n# 本輪指定回答身份\n"
                f"本輪身份由議題規劃指定，只能代表這些利害關係人回答：{', '.join(target_stakeholders)}。\n"
                "不得自行切換到其他利害關係人；如果問題不適合指定身份，請以該身份說明不適用或缺少情境。\n"
            )

        prev_text = self.format_previous_responses(
            previous_responses, title="前面的發言"
        )

        context_text = ""
        if related_context:
            context_text = (
                "\n# 當前專案資料（供參考）\n"
                + json.dumps(
                    related_context,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
        is_elicitation = str(issue.get("id") or "").startswith("ELICIT-")
        is_answer_question = str(issue.get("id") or "") == "OQ"

        need_speaking_as = len(self.stakeholders) > 1
        contract = issue.get("conflict_review_contract") if isinstance(issue.get("conflict_review_contract"), dict) else {}
        is_pair_review = str(contract.get("type") or "").strip() == "pair_reviews"
        known_pair_ids = [
            str(pair_id).strip()
            for pair_id in (contract.get("known_pair_ids") or [])
            if str(pair_id).strip()
        ]
        flow_hint = response_flow(
            need_speaking_as=need_speaking_as,
            answer_all_questions=answer_all_questions,
            is_answer_question=is_answer_question,
        )
        json_hint = response_json(
            need_speaking_as=need_speaking_as,
            is_elicitation=is_elicitation,
            is_answer_question=is_answer_question,
            is_pair_review=issue_category == "resolve_conflict" and is_pair_review,
        )
        category_text = build_category_hint(
            issue=issue,
            issue_category=issue_category,
            is_pair_review=is_pair_review,
            known_pair_ids=known_pair_ids,
        )
        open_questions_rule_text = open_question_rule(
            is_elicitation=is_elicitation,
            is_answer_question=is_answer_question,
        )
        suppress_stance = bool(is_elicitation or is_answer_question or (issue_category == "resolve_conflict" and is_pair_review))
        names_list_text = ", ".join(str(name) for name in names_list if str(name).strip())
        return issue_response(
            stakeholder_contract_text=stakeholder_contract_text,
            roles_text=roles_text,
            issue_text=issue_text,
            prev_text=prev_text,
            context_text=context_text,
            category_hint=category_text,
            flow_hint=flow_hint,
            json_hint=json_hint,
            stance_json_text=stance_json(suppress_stance=suppress_stance),
            stance_rule_text=stance_rule(suppress_stance=suppress_stance),
            open_questions_rule=open_questions_rule_text,
            answer_all_questions=answer_all_questions,
            need_speaking_as=need_speaking_as,
            names_list_text=names_list_text,
            target_stakeholders=target_stakeholders,
        )

    def retry_response_format(
        self,
        *,
        user_prompt: str,
        format_error: str,
        include_stance: bool,
        issue: Dict[str, Any],
        response: Dict[str, Any],
        allow_pair_reviews: bool,
    ) -> Dict[str, Any]:
        target_stakeholders = [
            str(name).strip()
            for name in (issue.get("target_stakeholders") or [])
            if str(name).strip()
        ]
        names_list_text = ", ".join(
            str(sh.get("name") or "").strip()
            for sh in (self.stakeholders or [])
            if str(sh.get("name") or "").strip()
        )
        retry_prompt = retry_response(
            user_prompt=user_prompt,
            format_error=format_error,
            include_stance=include_stance,
            need_speaking_as=len(self.stakeholders or []) > 1,
            names_list_text=names_list_text,
            target_stakeholders=target_stakeholders,
            invalid_response=response,
        )
        repaired = self.chat_for_issue_response(
            self.build_direct_messages(retry_prompt),
            temperature=1,
            include_stance=include_stance,
            allow_pair_reviews=allow_pair_reviews,
        )
        error_text = str(format_error or "").lower()
        if "text" not in error_text and str(response.get("text") or "").strip():
            repaired["text"] = response["text"]
        if "open_questions" not in error_text and isinstance(response.get("open_questions"), list):
            repaired["open_questions"] = response["open_questions"]
        stance = response.get("stance")
        if (
            include_stance
            and "stance" not in error_text
            and isinstance(stance, dict)
            and str(stance.get("state") or "").strip()
            in {"ready_to_close", "needs_more_discussion"}
        ):
            repaired["stance"] = stance
        if (
            allow_pair_reviews
            and "pair_review" not in error_text
            and isinstance(response.get("pair_reviews"), list)
        ):
            repaired["pair_reviews"] = response["pair_reviews"]
        return repaired

    def obs_response(self, **kwargs: Any) -> Dict[str, Any]:
        observation = self.issue_response_observation(**kwargs)
        observation["stakeholder_count"] = len(self.stakeholders or [])
        return observation

    def execute_action(
        self,
        *,
        decision: Dict[str, Any],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        issue = kwargs["issue"]
        user_prompt = self.build_response(
            issue=issue,
            previous_responses=kwargs.get("previous_responses"),
            related_context=(kwargs.get("observation") or {}).get("related_context"),
        )
        messages = self.build_direct_messages(user_prompt)
        issue_id = str(issue.get("id") or "")
        contract = issue.get("conflict_review_contract") if isinstance(issue.get("conflict_review_contract"), dict) else {}
        is_pair_review = str(contract.get("type") or "").strip() == "pair_reviews"
        include_stance = issue_id != "OQ" and not is_pair_review
        related_context = (kwargs.get("observation") or {}).get("related_context")
        use_artifact_tools = self.should_use_artifact_query(
            issue=issue,
            related_context=related_context,
            previous_responses=kwargs.get("previous_responses"),
        )
        response = self.chat_for_issue_response(
            messages,
            temperature=1,
            include_stance=include_stance,
            allow_pair_reviews=is_pair_review,
            use_tools=use_artifact_tools,
        )
        if response.get("format_error"):
            response = self.retry_response_format(
                user_prompt=user_prompt,
                format_error=str(response.get("format_error") or ""),
                include_stance=include_stance,
                issue=issue,
                response=response,
                allow_pair_reviews=is_pair_review,
            )

        text = response.get("text", "")
        open_questions = (
            [] if issue_id.startswith("ELICIT-") else response.get("open_questions", [])
        )
        stance = response.get("stance") if include_stance else {}
        if response.get("error") or response.get("format_error") or not str(text or "").strip():
            return {
                "action": decision.get("action", ""),
                "status": "failed",
                "error": response.get("error") or "missing_text",
                "format_error": response.get("format_error") or "issue response must include text",
                "summary": "user issue_response 格式不合格",
            }

        try:
            speaking_as = self.resolve_speaking_as(issue, response, text)
        except ValueError as exc:
            response = self.retry_response_format(
                user_prompt=user_prompt,
                format_error=str(exc),
                include_stance=include_stance,
                issue=issue,
                response=response,
                allow_pair_reviews=is_pair_review,
            )
            text = response.get("text", "")
            open_questions = (
                [] if issue_id.startswith("ELICIT-") else response.get("open_questions", [])
            )
            stance = response.get("stance") if include_stance else {}
            if response.get("error") or response.get("format_error") or not str(text or "").strip():
                return {
                    "action": decision.get("action", ""),
                    "status": "failed",
                    "error": response.get("error") or "missing_text",
                    "format_error": response.get("format_error") or "issue response must include text",
                    "summary": "user issue_response 格式修復失敗",
                }
            try:
                speaking_as = self.resolve_speaking_as(issue, response, text)
            except ValueError as retry_exc:
                return {
                    "action": decision.get("action", ""),
                    "status": "failed",
                    "error": "missing_valid_speaking_as",
                    "format_error": str(retry_exc),
                    "summary": "user issue_response 缺少合法 speaking_as",
                }
        return {
            "actions": [decision.get("action", "")] if decision.get("action") else [],
            "status": "success",
            "text": text,
            "open_questions": open_questions,
            "stance": stance,
            "speaking_as": speaking_as,
            "summary": "完成 user issue_response",
        }

    def resolve_speaking_as(
        self,
        issue: Dict[str, Any],
        response: Dict[str, Any],
        text: str,
    ) -> List[str]:
        speaking_as = []
        need_speaking_as = len(self.stakeholders) > 1
        speaking_as_list = []
        target_stakeholders = [
            str(name).strip()
            for name in (issue.get("target_stakeholders") or [])
            if str(name).strip()
        ]
        target_set = set(target_stakeholders)
        if self.stakeholders:
            if target_set:
                speaking_as_list = [
                    sh for sh in self.stakeholders
                    if str(sh.get("name") or "").strip() in target_set
                ]
            elif len(self.stakeholders) == 1:
                speaking_as_list = self.stakeholders
            else:
                speaking_as_list = []
        if need_speaking_as:
            raw = response.get("speaking_as")
            if isinstance(raw, str):
                raw = [raw]
            valid_names = {
                str(sh.get("name") or "").strip()
                for sh in self.stakeholders
                if str(sh.get("name") or "").strip()
            }
            speaking_as = [n for n in (raw or []) if n and n in valid_names]
            if target_set:
                speaking_as = [name for name in speaking_as if name in target_set]
            if not speaking_as:
                speaking_as = [
                    str(sh.get("name") or "").strip()
                    for sh in speaking_as_list
                    if str(sh.get("name") or "").strip()
                ]
            if not speaking_as:
                raise ValueError(
                    "user issue_response must include speaking_as with at least one valid assigned stakeholder name"
                )
        elif len(speaking_as_list) == 1:
            speaking_as = [speaking_as_list[0].get("name", "")]
        if len(speaking_as) > 1:
            labeled_by_name = {}
            for name in speaking_as:
                marker = f"【{name}】"
                start = str(text).find(marker)
                if start < 0:
                    continue
                next_positions = [
                    pos
                    for other in speaking_as
                    if other != name
                    for pos in [str(text).find(f"【{other}】", start + len(marker))]
                    if pos >= 0
                ]
                end = min(next_positions) if next_positions else len(str(text))
                part = str(text)[start + len(marker):end].strip()
                labeled_by_name[name] = part
            labeled_names = [
                name for name in speaking_as
                if str(labeled_by_name.get(name) or "").strip()
            ]
            speaking_as = labeled_names or speaking_as
        return speaking_as
