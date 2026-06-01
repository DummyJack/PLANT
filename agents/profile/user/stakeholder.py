# User stakeholder helpers: derive stakeholder voices and initial requirements.
from agents.profile.prompt_catalog import render_prompt
import json
from typing import Any, Dict, List, Optional

from agents.profile.scenario import scenario_prompt_value


STAKEHOLDER_CATEGORIES = {
    "Primary Users",
    "System Owners & Management",
    "External Parties",
}


def selected_stakeholders(selected: List[Any]) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for item in selected or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        stakeholder_type = str(item.get("type") or "").strip()
        if not name:
            continue
        if stakeholder_type not in STAKEHOLDER_CATEGORIES:
            raise ValueError(f"利害關係人 type 不合法: {name} -> {stakeholder_type or '<empty>'}")
        records.append({"name": name, "type": stakeholder_type})
    return records


def merge_stakeholder_inputs(
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
        text = generated.get("text") if isinstance(generated, dict) else []
        if isinstance(text, str):
            text = [line.strip() for line in text.splitlines() if line.strip()]
        elif isinstance(text, list):
            text = [str(line).strip() for line in text if str(line).strip()]
        else:
            text = []
        row["text"] = text
        merged.append(row)
    return merged


class UserStakeholder:
    @staticmethod
    def scenario_context_text(value: Any) -> str:
        return json.dumps(scenario_prompt_value(value), ensure_ascii=False, indent=2)

    def propose_stakeholders(self, rough_idea: Any) -> List[Dict]:
        opa = self.run_action_loop(
            name="stakeholder_setup",
            context={
                "action": "propose_stakeholders",
                "rough_idea": rough_idea,
            },
            build_observation=self.build_stakeholder_observation,
            decide_action=self.decide_stakeholder_action,
            execute_action=self.execute_stakeholder_action,
        )
        trace = opa.get("opa_trace") or []
        result = dict((trace[-1].get("result") if trace else {}) or {})
        if result.get("error"):
            raise RuntimeError(result.get("error"))
        return result.get("output", [])

    def write_stakeholders(
        self, rough_idea: Any, selected_stakeholders: List
    ) -> List[Dict]:
        opa = self.run_action_loop(
            name="stakeholder_text",
            context={
                "action": "write_stakeholders",
                "rough_idea": rough_idea,
                "selected_stakeholders": selected_stakeholders,
            },
            build_observation=self.build_stakeholder_observation,
            decide_action=self.decide_stakeholder_action,
            execute_action=self.execute_stakeholder_action,
        )
        trace = opa.get("opa_trace") or []
        result = dict((trace[-1].get("result") if trace else {}) or {})
        if result.get("error"):
            raise RuntimeError(result.get("error"))
        return result.get("output", [])

    def build_stakeholder_observation(self, **kwargs) -> Dict:
        selected = kwargs.get("selected_stakeholders") or []
        return {
            "action": kwargs.get("action", ""),
            "iteration": kwargs.get("iteration", 0) + 1,
            "max_iterations": kwargs["max_iterations"],
            "has_rough_idea": bool(str(kwargs.get("rough_idea") or "").strip()),
            "selected_stakeholder_count": len(selected),
        }

    def decide_stakeholder_action(
        self,
        *,
        observation: Dict,
        last_result: Optional[Dict] = None,
        **kwargs,
    ) -> Dict:
        if isinstance(last_result, dict) and not last_result.get("error"):
            return {
                "action": "done",
                "params": {},
                "reasoning": "上一輪利害關係人需求擴展已完成，結束本次任務。",
            }
        action = str(observation.get("action") or "").strip()
        return {
            "action": action,
            "params": {},
            "reasoning": f"以 User agent 情境利害關係人視角執行：{action}。",
        }

    def execute_stakeholder_action(
        self,
        *,
        decision: Dict,
        **kwargs,
    ) -> Dict:
        action = str(decision.get("action") or "").strip()
        try:
            if action == "propose_stakeholders":
                output = self.propose_stakeholders_via_llm(kwargs.get("rough_idea", ""))
            elif action == "write_stakeholders":
                output = self.write_stakeholders_via_llm(
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

    def propose_stakeholders_via_llm(self, rough_idea: Any) -> List[Dict]:
        scenario_context = self.scenario_context_text(rough_idea)
        user_prompt = render_prompt('agents_profile_user_stakeholder_user_prompt_21', **locals())

        messages = self.build_direct_messages(user_prompt)
        response = self.chat_json(messages, temperature=1)
        proposed = response.get("proposed_stakeholders", [])
        if not isinstance(proposed, list):
            raise ValueError("proposed_stakeholders must be a list")

        categories = [
            "Primary Users",
            "System Owners & Management",
            "External Parties",
        ]
        counts = {category: 0 for category in categories}
        current_order = 0
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
            order = categories.index(stakeholder_type)
            if order < current_order:
                raise ValueError("stakeholders must be ordered by type priority")
            current_order = order
            counts[stakeholder_type] += 1

        if len(proposed) != 10:
            raise ValueError("propose_stakeholders must return exactly 10 stakeholders")
        expected_counts = {
            "Primary Users": 4,
            "System Owners & Management": 4,
            "External Parties": 2,
        }
        if counts != expected_counts:
            raise ValueError(
                "propose_stakeholders must return exactly 4 Primary Users, "
                "4 System Owners & Management, and 2 External Parties"
            )
        return proposed

    def write_stakeholders_via_llm(
        self, rough_idea: Any, selected_stakeholders: List
    ) -> List[Dict]:
        scenario_context = self.scenario_context_text(rough_idea)
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

        user_prompt = render_prompt('agents_profile_user_stakeholder_user_prompt_22', **locals())

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
