# Issue response support shared by meeting-capable agents.
from typing import Any, Dict, List, Optional


class IssueResponseSupport:
    def clean_statement(self, text: Any) -> str:
        statement = str(text or "").strip()
        if statement in {"{}", "[]", "null", '""'}:
            return ""
        return statement

    def issue_response_payload(self, payload: Any) -> Dict[str, Any]:
        data = dict(payload or {}) if isinstance(payload, dict) else {}
        final_statement = self.clean_statement(data.get("statement"))
        normalized = {
            "statement": final_statement,
            "open_questions": (
                data.get("open_questions")
                if isinstance(data.get("open_questions"), list)
                else []
            ),
            "suggested_next_action": (
                data.get("suggested_next_action")
                if isinstance(data.get("suggested_next_action"), dict)
                else None
            ),
        }
        for key, value in data.items():
            if key not in normalized:
                normalized[key] = value
        if not final_statement:
            normalized["error"] = "missing_statement"
            normalized["format_error"] = "issue response must include a non-empty statement field"
        return normalized

    def chat_for_issue_response(
        self, messages: List[Dict], parse_json: bool = True, **kwargs: Any
    ) -> Dict[str, Any]:
        """有 tools 則 chat_with_tools，否則 chat_json。"""
        if self.tools:
            raw = self.chat_with_tools(messages)
            if parse_json:
                try:
                    parsed = self.parse_issue_response_json(raw)
                except ValueError as e:
                    return {
                        "statement": "",
                        "open_questions": [],
                        "error": "invalid_json",
                        "format_error": str(e),
                    }
                return self.issue_response_payload(parsed)
            return {"statement": "", "open_questions": [], "error": "invalid_issue_response_mode"}
        action = kwargs.pop("action", f"{self.name}.issue.response")
        try:
            parsed = self.chat_json(messages, action=action, **kwargs)
            return self.issue_response_payload(parsed)
        except Exception as e:
            self.logger.warning("%s issue.response JSON 解析失敗: %s", self.name, e)
            return {
                "statement": "",
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
            statement = response.get("statement", "")
            speaking_as = response.get("speaking_as", [])
            if isinstance(speaking_as, str):
                speaking_as = [speaking_as]
            speaking_as = [item for item in speaking_as if isinstance(item, str) and item.strip()]
            role_hint = f"（代表：{'、'.join(speaking_as)}）" if speaking_as else ""
            parts.append(f"【{agent_name}{role_hint}】\n{statement}")
        return f"\n# {title}\n" + "\n\n".join(parts)

    def issue_response_observation(
        self,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        issue = kwargs["issue"]
        previous_responses = kwargs.get("previous_responses") or []
        artifact_snapshot = kwargs.get("artifact_snapshot") or {}
        return {
            "issue": issue,
            "issue_id": str(issue.get("id") or ""),
            "issue_category": str(issue.get("category") or ""),
            "previous_responses": previous_responses,
            "previous_response_count": len(previous_responses),
            "artifact_snapshot": artifact_snapshot,
            "has_artifact_snapshot": bool(artifact_snapshot),
            "recent_ask_history": issue.get("recent_ask_history") or [],
            "iteration": kwargs.get("iteration", 0) + 1,
            "max_iterations": kwargs.get("max_iterations", 1),
        }

    def issue_response_decision(
        self,
        observation: Dict[str, Any],
        *,
        done_reasoning: str,
        active_reasoning: str,
        last_result: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if isinstance(last_result, dict) and not last_result.get("error"):
            return {
                "action": "done",
                "params": {},
                "reasoning": done_reasoning,
            }
        issue = observation.get("issue") or {}
        action = (
            "respond_conflict_discussion"
            if issue.get("category") == "conflict_discussion"
            else "respond_discussion"
        )
        return {
            "action": action,
            "params": {},
            "reasoning": active_reasoning,
        }
