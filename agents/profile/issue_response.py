import json

# Issue response support shared by meeting-capable agents.
from typing import Any, Dict, List, Optional


class IssueResponseSupport:
    def clean_text(self, text: Any) -> str:
        text = str(text or "").strip()
        if text in {"{}", "[]", "null", '""'}:
            return ""
        return text

    def issue_response_payload(self, payload: Any) -> Dict[str, Any]:
        data = dict(payload or {}) if isinstance(payload, dict) else {}
        final_text = self.clean_text(data.get("text"))
        if not final_text and isinstance(data.get("pair_reviews"), list):
            compact_payload = {"pair_reviews": data.get("pair_reviews")}
            review_summary = self.clean_text(data.get("review_summary"))
            if review_summary:
                compact_payload = {
                    "review_summary": review_summary,
                    "pair_reviews": data.get("pair_reviews"),
                }
            final_text = json.dumps(compact_payload, ensure_ascii=False, separators=(",", ":"))
        normalized = {
            "text": final_text,
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
        if not final_text:
            normalized["error"] = "missing_text"
            normalized["format_error"] = "issue response must include a non-empty text field"
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
                        "text": "",
                        "open_questions": [],
                        "error": "invalid_json",
                        "format_error": str(e),
                    }
                return self.issue_response_payload(parsed)
            return {"text": "", "open_questions": [], "error": "invalid_issue_response_mode"}
        action = kwargs.pop("action", f"{self.name}.issue.response")
        try:
            parsed = self.chat_json(messages, action=action, **kwargs)
            return self.issue_response_payload(parsed)
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
