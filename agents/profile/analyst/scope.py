# Handles module workflow behavior.
from typing import Any, Dict, List, Optional

from .actions.scope.generate import generate_scope
from .actions.scope.refine import refine_scope
from storage.requirements import requirement_discussion_pool
from .validation import scope_payload


# Defines AnalystScope class for this module workflow.
class AnalystScope:
    # Defines generate scope function for this module workflow.
    def generate_scope(
        self, rough_idea: str, stakeholders: List[Dict],
        *, artifact: Optional[Dict[str, Any]] = None,
    ) -> Dict:
        context: Dict[str, Any] = {}
        if artifact:
            if artifact.get("scenario"):
                context["scenario"] = str(artifact["scenario"] or "").strip()
            elif rough_idea:
                context["scenario"] = str(rough_idea or "").strip()
            if artifact.get("scope"):
                context["current_scope"] = artifact["scope"]
            if artifact.get("scope_review_feedback"):
                consideration = str(artifact["scope_review_feedback"] or "").strip()
                context["scope_consideration"] = consideration
                context["human_decision"] = consideration
            req_pool = requirement_discussion_pool(artifact)
            if req_pool:
                context["URL"] = req_pool
        task = generate_scope()
        try:
            data = self.invoke_direct_requirements_object_json(
                task,
                context,
                action="requirements.scope",
            )
        except Exception as e:
            raise RuntimeError(f"scope 生成失敗: {e}") from e
        scope_definition = (
            data.get("scope_definition")
            if isinstance(data, dict) and isinstance(data.get("scope_definition"), dict)
            else {}
        )
        scope = scope_definition.get("scope") or {}
        return scope_payload(scope)

    # Defines execute refine scope function for this module workflow.
    def execute_refine_scope(
        self,
        *,
        artifact: Dict[str, Any],
        issue: Dict[str, Any],
        previous_responses: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        current_scope = scope_payload(artifact.get("scope", {}))
        requirements = self.scope_requirement_context(artifact)
        discussion = self.scope_discussion_context(previous_responses)
        source_id = str(issue.get("meeting_id") or issue.get("id") or "").strip()
        context = {
            "issue": {
                "id": issue.get("id"),
                "meeting_id": issue.get("meeting_id"),
                "title": issue.get("title"),
                "category": issue.get("category"),
                "trace": issue.get("trace", {}),
            },
            "current_scope": current_scope,
            "requirements": requirements,
            "discussion": discussion,
            "scenario": str(artifact.get("scenario") or "").strip(),
        }
        task = refine_scope(source_id=source_id)
        data = self.invoke_direct_requirements_object_json(
            task,
            context,
            action="requirements.refine_scope",
        )
        updates = self.clean_scope_updates(data.get("scope_updates") if isinstance(data, dict) else {})
        updated_scope = self.apply_scope_updates(current_scope, updates)
        artifact["scope"] = updated_scope
        return {
            "action": "refine_scope",
            "scope_updates": updates,
            "scope": updated_scope,
            "reason": str((data or {}).get("reason") or "").strip(),
            "source_id": source_id,
        }

    @staticmethod
    # Defines clean scope updates function for this module workflow.
    def clean_scope_updates(raw: Any) -> Dict[str, List[str]]:
        source = raw if isinstance(raw, dict) else {}
        updates: Dict[str, List[str]] = {}
        for key in ("in_scope_add", "out_of_scope_add", "in_scope_remove", "out_of_scope_remove"):
            value = source.get(key)
            if isinstance(value, list):
                rows = [str(item).strip() for item in value if str(item).strip()]
            else:
                text = str(value or "").strip()
                rows = [text] if text else []
            updates[key] = list(dict.fromkeys(rows))
        return updates

    @staticmethod
    # Defines apply scope updates function for this module workflow.
    def apply_scope_updates(current_scope: Dict[str, Any], updates: Dict[str, List[str]]) -> Dict[str, List[str]]:
        scope = scope_payload(current_scope)

        # Defines remove items function for this module workflow.
        def remove_items(rows: List[str], removals: List[str]) -> List[str]:
            remove_set = {item.strip().lower() for item in removals if item.strip()}
            return [item for item in rows if item.strip().lower() not in remove_set]

        # Defines add items function for this module workflow.
        def add_items(rows: List[str], additions: List[str]) -> List[str]:
            seen = {item.strip().lower() for item in rows if item.strip()}
            out = list(rows)
            for item in additions:
                marker = item.strip().lower()
                if marker and marker not in seen:
                    out.append(item)
                    seen.add(marker)
            return out

        in_scope = remove_items(scope.get("in_scope", []), updates.get("in_scope_remove", []))
        out_scope = remove_items(scope.get("out_of_scope", []), updates.get("out_of_scope_remove", []))
        in_scope = add_items(in_scope, updates.get("in_scope_add", []))
        out_scope = add_items(out_scope, updates.get("out_of_scope_add", []))
        return {"in_scope": in_scope, "out_of_scope": out_scope}
