# Handles module workflow behavior.
from .actions.simulate import (
    revise_stakeholder_text as revise_stakeholder_text_prompt,
    suggest_stakeholders,
    write_stakeholder_text,
)
import json
from typing import Any, Dict, List

stakeholder_types = {
    "primary_user",
    "system_owner",
    "external_party",
}


# ========
# Defines parse selection function for this module workflow.
# ========
def parse_selection(selected: List[Any]) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for item in selected or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        stakeholder_type = str(item.get("type") or "").strip()
        if not name:
            continue
        if stakeholder_type not in stakeholder_types:
            raise ValueError(f"利害關係人 type 不合法: {name} -> {stakeholder_type or '<empty>'}")
        records.append({"name": name, "type": stakeholder_type})
    return records


def stakeholder_text_items(row: Dict[str, Any]) -> List[Dict[str, str]]:
    text = row.get("text")
    if isinstance(text, str):
        return [{"id": "", "text": line.strip()} for line in text.splitlines() if line.strip()]
    if isinstance(text, list):
        rows: List[Dict[str, str]] = []
        for item in text:
            if isinstance(item, dict):
                value = str(item.get("text") or "").strip()
                if value:
                    rows.append({"id": str(item.get("id") or "").strip(), "text": value})
                continue
            value = str(item).strip()
            if value:
                rows.append({"id": "", "text": value})
        return rows
    value = str(text or "").strip()
    return [{"id": "", "text": value}] if value else []


def normalize_stakeholder_text(stakeholders: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for stakeholder_index, item in enumerate(stakeholders or [], start=1):
        if not isinstance(item, dict):
            continue
        row = dict(item)
        row["id"] = str(row.get("id") or "").strip() or f"stakeholder-{stakeholder_index}"
        text_items = stakeholder_text_items(row)
        normalized_text = []
        for text_index, item in enumerate(text_items, start=1):
            normalized_text.append({
                "id": str(item.get("id") or "").strip() or f"ST-{stakeholder_index}-{text_index}",
                "text": str(item.get("text") or "").strip(),
            })
        row["text"] = normalized_text
        row.pop("statements", None)
        normalized.append(row)
    return normalized


# ========
# Defines merge stakeholder text function for this module workflow.
# ========
def merge_stakeholder_text(
    selected_records: List[Dict[str, Any]],
    generated_rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    generated_by_name = {
        str(row.get("name") or "").strip(): row
        for row in generated_rows or []
        if isinstance(row, dict) and str(row.get("name") or "").strip()
    }
    merged: List[Dict[str, Any]] = []
    for index, base in enumerate(selected_records, 1):
        row = dict(base)
        row["id"] = str(row.get("id") or "").strip() or f"stakeholder-{index}"
        generated = generated_by_name.get(row["name"], {})
        row["text"] = stakeholder_text_items(generated) if isinstance(generated, dict) else []
        merged.append(row)
    return normalize_stakeholder_text(merged)


# ========
# Defines UserStakeholder class for this module workflow.
# ========
class UserStakeholder:
    @staticmethod
    # Defines scenario json function for this module workflow.
    def scenario_json(value: Any) -> str:
        return json.dumps(str(value or "").strip(), ensure_ascii=False, indent=2)

    # Defines suggest stakeholders function for this module workflow.
    def suggest_stakeholders(self, rough_idea: Any) -> List[Dict]:
        opa = self.run_action_loop(
            name="stakeholder_setup",
            context={
                "action": "suggest_stakeholders",
                "rough_idea": rough_idea,
            },
            obs_fn=self.obs_setup,
            decide_action=self.plan_stakeholder,
            execute_action=self.run_setup_action,
        )
        trace = opa.get("opa_trace") or []
        result = dict((trace[-1].get("result") if trace else {}) or {})
        if result.get("error"):
            raise RuntimeError(result.get("error"))
        return result.get("output", [])

    # Defines write stakeholder text function for this module workflow.
    def write_stakeholder_text(
        self, rough_idea: Any, selected_stakeholders: List
    ) -> List[Dict]:
        opa = self.run_action_loop(
            name="stakeholder_text",
            context={
                "action": "write_stakeholder_text",
                "rough_idea": rough_idea,
                "selected_stakeholders": selected_stakeholders,
            },
            obs_fn=self.obs_setup,
            decide_action=self.plan_stakeholder,
            execute_action=self.run_setup_action,
        )
        trace = opa.get("opa_trace") or []
        result = dict((trace[-1].get("result") if trace else {}) or {})
        if result.get("error"):
            raise RuntimeError(result.get("error"))
        return result.get("output", [])

    def revise_stakeholder_text(
        self,
        rough_idea: Any,
        stakeholders: List[Dict[str, Any]],
        review_considerations: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        current = normalize_stakeholder_text(stakeholders or [])
        feedback_lines: List[str] = []
        for index, row in enumerate(review_considerations or [], start=1):
            if not isinstance(row, dict):
                continue
            text = str(row.get("text") or "").strip()
            targets = [
                str(value or "").strip()
                for value in (row.get("target_ids") or [])
                if str(value or "").strip()
            ]
            references = [
                str(ref.get("name") or "").strip()
                for ref in (row.get("references") or [])
                if isinstance(ref, dict) and str(ref.get("name") or "").strip()
            ]
            parts = []
            if targets:
                parts.append(f"target_ids={targets}")
            if references:
                parts.append(f"references={references}")
            if text:
                parts.append(text)
            if parts:
                feedback_lines.append(f"{index}. " + "；".join(parts))

        feedback_text = "\n".join(feedback_lines).strip()
        if not current or not feedback_text:
            return current

        user_prompt = revise_stakeholder_text_prompt(
            current_stakeholders_text=json.dumps(current, ensure_ascii=False, indent=2),
            feedback_text=feedback_text,
            scenario_context=self.scenario_json(rough_idea),
        )
        try:
            response = self.chat_json(self.build_direct_messages(user_prompt), temperature=0.7)
            revised_rows = response.get("stakeholders", [])
            if not isinstance(revised_rows, list):
                raise ValueError("stakeholders must be a list")
            revised_by_name = {
                str(row.get("name") or "").strip(): row
                for row in revised_rows
                if isinstance(row, dict) and str(row.get("name") or "").strip()
            }
            merged: List[Dict[str, Any]] = []
            for base in current:
                name = str(base.get("name") or "").strip()
                source = revised_by_name.get(name)
                next_row = dict(base)
                if isinstance(source, dict):
                    text_items = stakeholder_text_items(source)
                    if text_items:
                        next_row["text"] = text_items
                merged.append(next_row)
            return normalize_stakeholder_text(merged)
        except Exception as e:
            raise RuntimeError(f"User 修正利害關係人發言失敗: {e}")

    # Defines obs setup function for this module workflow.
    def obs_setup(self, **kwargs: Any) -> Dict[str, Any]:
        selected = kwargs.get("selected_stakeholders") or []
        return {
            "action": kwargs.get("action", ""),
            "iteration": kwargs.get("iteration", 0) + 1,
            "max_iterations": kwargs["max_iterations"],
            "has_rough_idea": bool(str(kwargs.get("rough_idea") or "").strip()),
            "selected_stakeholder_count": len(selected),
        }

    # Defines run setup action function for this module workflow.
    def run_setup_action(
        self,
        *,
        decision: Dict,
        **kwargs,
    ) -> Dict:
        action = str(decision.get("action") or "").strip()
        try:
            if action == "suggest_stakeholders":
                output = self.generate_candidates(kwargs.get("rough_idea", ""))
            elif action == "write_stakeholder_text":
                output = self.generate_needs(
                    kwargs.get("rough_idea", ""),
                    kwargs.get("selected_stakeholders") or [],
                )
            else:
                raise ValueError(f"未知 stakeholder action: {action}")
        except Exception as e:
            return {
                "action": action,
                "status": "failed",
                "error": str(e),
                "summary": f"stakeholder elicitation failed: {action}",
            }
        return {
            "action": action,
            "status": "success",
            "output": output,
            "summary": f"完成 stakeholder elicitation: {action}",
        }

    # Defines generate candidates function for this module workflow.
    def generate_candidates(self, rough_idea: Any) -> List[Dict]:
        scenario_context = self.scenario_json(rough_idea)
        user_prompt = suggest_stakeholders(scenario_context=scenario_context)

        messages = self.build_direct_messages(user_prompt)
        response = self.chat_json(messages, temperature=1)
        proposed = response.get("proposed_stakeholders", [])
        if not isinstance(proposed, list):
            raise ValueError("proposed_stakeholders must be a list")

        categories = [
            "primary_user",
            "system_owner",
            "external_party",
        ]
        counts = {category: 0 for category in categories}
        for row in proposed:
            if not isinstance(row, dict):
                raise ValueError("each proposed stakeholder must be an object")
            name = str(row.get("name") or "").strip()
            stakeholder_type = str(row.get("type") or "").strip()
            reason = str(row.get("reason") or "").strip()
            if not name or not reason:
                raise ValueError(
                    "each proposed stakeholder must include name and reason"
                )
            if stakeholder_type not in counts:
                raise ValueError(f"invalid stakeholder type: {stakeholder_type}")
            counts[stakeholder_type] += 1

        if len(proposed) < 2:
            raise ValueError("propose_stakeholders must return at least 2 stakeholders")
        return sorted(
            proposed,
            key=lambda row: categories.index(str(row.get("type") or "").strip()),
        )

    # Defines generate needs function for this module workflow.
    def generate_needs(
        self, rough_idea: Any, selected_stakeholders: List
    ) -> List[Dict]:
        scenario_context = self.scenario_json(rough_idea)
        stakeholder_rows = []
        for i, sh in enumerate(selected_stakeholders, 1):
            if isinstance(sh, dict):
                name = str(sh.get("name") or "").strip()
            else:
                name = str(sh).strip()
            if not name:
                continue
            stakeholder_rows.append(f"{i}. {name}")
        stakeholder_list = "\n".join(stakeholder_rows)

        user_prompt = write_stakeholder_text(stakeholder_list=stakeholder_list, scenario_context=scenario_context)

        try:
            messages = self.build_direct_messages(user_prompt)
            response = self.chat_json(messages, temperature=1)
            stakeholders = response.get("stakeholders", [])

            for sh in stakeholders:
                if not all(key in sh for key in ["name", "text"]):
                    raise ValueError(f"利害關係人格式錯誤: {sh}")
                if isinstance(sh["text"], str):
                    sh["text"] = [
                        s.strip() for s in sh["text"].split("\n") if s.strip()
                    ]
                if len(sh["text"]) < 3:
                    self.logger.warning(
                        f"{sh['name']} 只有 {len(sh['text'])} 條需求，不足 3 條"
                    )

            return stakeholders
        except Exception as e:
            raise RuntimeError(f"User 生成失敗: {e}")
