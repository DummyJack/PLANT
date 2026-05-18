# Analyst elicitation logic: extract requirement candidates from elicitation meeting turns.
import json
from typing import Any, Dict, List, Optional

from agents.profile.scenario import scenario_prompt_value

from .prompts import user_requirement_extraction_contract
from .validation import validate_elicited_reqts


class AnalystElicitation:
    def extract_elicited_reqts(
        self,
        stakeholders: List[Dict[str, str]],
        existing_requirements: List[Dict[str, Any]],
        *,
        mode: str = "oracle",
        scenario: Any = None,
        source: str = "",
    ) -> List[Dict[str, Any]]:
        opa = self.run_action_loop(
            name="elicitation_extraction",
            context={
                "elicitation_action": "extract_elicited_reqts",
                "stakeholders": stakeholders,
                "existing_requirements": existing_requirements,
                "mode": mode,
                "scenario": scenario or {},
                "source": source,
            },
            build_observation=self.build_elicitation_observation,
            decide_action=self.decide_elicitation_action,
            execute_action=self.execute_elicitation_action,
        )
        trace = opa.get("opa_trace") or []
        result = dict((trace[-1].get("result") if trace else {}) or {})
        if result.get("error"):
            raise RuntimeError(result.get("error"))
        output = result.get("output")
        if not isinstance(output, list):
            raise RuntimeError("elicited requirement extraction output must be a list")
        return output

    def build_elicitation_observation(self, **kwargs: Any) -> Dict[str, Any]:
        return {
            "action": kwargs.get("elicitation_action", ""),
            "iteration": kwargs.get("iteration", 0) + 1,
            "max_iterations": kwargs["max_iterations"],
            "stakeholder_count": len(kwargs.get("stakeholders") or []),
            "existing_requirement_count": len(kwargs.get("existing_requirements") or []),
            "mode": kwargs.get("mode", "oracle"),
        }

    def decide_elicitation_action(
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
                "reasoning": "上一輪 elicitation extraction 已完成，結束本次候選需求抽取。",
            }
        return {
            "action": str(observation.get("action") or ""),
            "params": {},
            "reasoning": "從 requirement elicitation 討論中抽取可追蹤、可驗收的需求候選。",
        }

    def execute_elicitation_action(
        self,
        *,
        decision: Dict[str, Any],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        action = str(decision.get("action") or "").strip()
        try:
            if action != "extract_elicited_reqts":
                raise ValueError(f"未知 elicitation action: {action}")
            output = self.parse_elicited_reqts(
                kwargs.get("stakeholders") or [],
                kwargs.get("existing_requirements") or [],
                mode=kwargs.get("mode", "oracle"),
                scenario=kwargs.get("scenario") or {},
                source=kwargs.get("source") or "",
            )
        except Exception as e:
            return {
                "action": action,
                "error": str(e),
                "summary": f"elicitation extraction failed: {action}",
            }
        return {
            "action": action,
            "status": "success",
            "output": output,
            "summary": "完成 elicitation extraction",
        }

    def parse_elicited_reqts(
        self,
        stakeholders: List[Dict[str, str]],
        existing_requirements: List[Dict[str, Any]],
        *,
        mode: str = "oracle",
        scenario: Any = None,
        source: str = "",
    ) -> List[Dict[str, Any]]:
        """從需求擷取討論中提取候選需求（原始 JSON）。"""
        mode_name = str(mode or "oracle").strip().lower()
        scenario_text = json.dumps(scenario_prompt_value(scenario), ensure_ascii=False, indent=2)
        stakeholder_rows = [
            {
                "name": str(row.get("name") or "").strip(),
                "text": str(row.get("text") or "").strip(),
            }
            for row in (stakeholders or [])
            if isinstance(row, dict)
            and str(row.get("name") or "").strip()
            and str(row.get("text") or "").strip()
        ]
        existing_rows = [
            {
                "id": str(row.get("id") or "").strip(),
                "text": str(row.get("text") or "").strip(),
                "priority": str(row.get("priority") or "").strip(),
                "stakeholder": (
                    str((row.get("stakeholder") or {}).get("name") or "").strip()
                    if isinstance(row.get("stakeholder"), dict)
                    else str(row.get("stakeholder") or "").strip()
                ),
                "source": str(row.get("source") or "").strip(),
            }
            for row in (existing_requirements or [])
            if isinstance(row, dict) and str(row.get("text") or "").strip()
        ]
        rules = f"{user_requirement_extraction_contract()}\n\n"
        mapped: List[Dict[str, Any]] = []
        for stakeholder_row in stakeholder_rows:
            prompt = (
                "請依照 requirements-analyst skill，從本輪利害關係人回答中抽取尚未記錄的新 User Requirements。\n\n"
                "# 輸入\n"
                "- 產品情境\n"
                "- stakeholder\n"
                "- 目前已有的候選需求摘要\n\n"
                f"# 產品情境\n{scenario_text}\n\n"
                f"# stakeholder\n{json.dumps(stakeholder_row, ensure_ascii=False, indent=2)}\n\n"
                f"# 目前已有的候選需求摘要\n{json.dumps(existing_rows, ensure_ascii=False, indent=2)}\n\n"
                f"# 執行來源\n{mode_name}\n\n"
                f"{rules}"
                "# 去重\n"
                "- 若回答只是重述、同義改寫或細化目前已有候選需求，且沒有形成新的可獨立追蹤 User Requirement，回傳空陣列。\n\n"
                '# 輸出 JSON\n[...]'
            )
            raw_text = self.invoke_requirements_analyst_text(
                prompt,
                {},
                mode="analysis",
            )
            raw = self.parse_issue_response_json(raw_text)
            if not isinstance(raw, list):
                raise ValueError("elicitation extraction output must be a JSON array")
            for row in raw:
                if not isinstance(row, dict):
                    continue
                mapped.append({
                    "text": row.get("text"),
                    "priority": row.get("priority"),
                    "stakeholder": {
                        "name": stakeholder_row["name"],
                        "text": stakeholder_row["text"],
                    },
                    "source": source or "elicitation",
                })
        return validate_elicited_reqts(mapped)
