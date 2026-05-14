# Analyst elicitation logic: extract requirement candidates from elicitation meeting turns.
import json
from typing import Any, Dict, List, Optional

from .validation import validate_elicited_reqts


class AnalystElicitation:
    def extract_elicited_reqts(
        self,
        discussion_text: str,
        existing_ids: List[str],
        *,
        mode: str = "oracle",
        scenario: Any = None,
        valid_source_stakeholders: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        opa = self.run_action_loop(
            name="elicitation_extraction",
            context={
                "elicitation_action": "extract_elicited_reqts",
                "discussion_text": discussion_text,
                "existing_ids": existing_ids,
                "mode": mode,
                "scenario": scenario or {},
                "valid_source_stakeholders": valid_source_stakeholders or [],
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
            "discussion_length": len(str(kwargs.get("discussion_text") or "")),
            "existing_id_count": len(kwargs.get("existing_ids") or []),
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
                kwargs.get("discussion_text") or "",
                kwargs.get("existing_ids") or [],
                mode=kwargs.get("mode", "oracle"),
                scenario=kwargs.get("scenario") or {},
                valid_source_stakeholders=kwargs.get("valid_source_stakeholders") or [],
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
        discussion_text: str,
        existing_ids: List[str],
        *,
        mode: str = "oracle",
        scenario: Any = None,
        valid_source_stakeholders: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """從需求擷取討論中提取候選需求（原始 JSON）。"""
        mode_name = str(mode or "oracle").strip().lower()
        valid_names = [
            str(name or "").strip()
            for name in (valid_source_stakeholders or [])
            if str(name or "").strip()
        ]
        source_stakeholder_rule = (
            "# 合法 source_stakeholders\n"
            f"{json.dumps(valid_names, ensure_ascii=False)}\n"
            "- 每筆 candidate 的 source_stakeholders 只能從上述名單選擇。\n"
            "- 即使討論逐字稿中出現【user】，user 只是受訪者發言標記，不是合法 source_stakeholders。\n"
            "- 不可填 user、analyst、expert、modeler、system 或任何不在合法名單中的名稱。\n"
            "- 如果無法判斷需求來源對應到哪個合法利害關係人，該 candidate 不要輸出。\n\n"
        )
        scenario_text = json.dumps(scenario or {}, ensure_ascii=False, indent=2)
        if mode_name == "main_flow":
            rules = (
                "# 規則\n"
                "- 只從本輪 interviewer/user 對話中提取尚未被記錄的新需求候選\n"
                "- 只有 user signal 明確支持需求意圖時才提取；不得憑空新增功能、角色、外部系統或量化目標\n"
                "- 每筆需含：text, type (FR/NFR/constraint), priority (must/should/could), "
                "source_stakeholders, source（引用討論中的原話或情境片段作為依據，不可編造）, "
                "acceptance_criteria\n"
                "- acceptance_criteria 要可觀察、可驗收；不要只重述需求文字\n"
                "- 若 type 是 NFR，請輸出初步 metric 與 target；metric 是要觀察或衡量的指標，target 是目標條件或待確認門檻\n"
                "- NFR 的 metric/target 只能根據 user signal 或討論內容推導；資訊不足時 target 請寫「待確認」，不要憑空填入數字\n"
                "- 若 user 回答修正了既有理解，candidate text 應反映修正後的需求，而不是只摘錄 user 原話\n"
                "- 若只是 open question、支持不足、缺乏 source 引述或重複已有需求，不要輸出\n\n"
            )
        else:
            rules = (
                "# 規則\n"
                "- 只提取討論中明確提及、尚未被記錄，且與產品情境直接相關的新需求\n"
                "- 每筆需含：text, type (FR/NFR/constraint), priority (must/should/could), "
                "source_stakeholders, source（討論中的原話引述，作為來源憑證）, "
                "acceptance_criteria\n"
                "- acceptance_criteria 要可觀察、可驗收；不要只重述需求文字\n"
                "- 若 type 是 NFR，請輸出初步 metric 與 target；metric 是要觀察或衡量的指標，target 是目標條件或待確認門檻\n"
                "- NFR 的 metric/target 只能根據討論內容推導；資訊不足時 target 請寫「待確認」，不要憑空填入數字\n"
                "- 若只是 open question、支持不足、缺乏 source 引述或重複已有需求，不要輸出\n"
                "- 若無新需求，回傳空陣列\n\n"
            )
        prompt = (
            "請從以下需求擷取會議中提取尚未被記錄的新需求候選。\n\n"
            f"# 產品情境（不可偏離）\n{scenario_text}\n\n"
            f"# 討論內容\n{discussion_text}\n\n"
            f"# 目前已有的需求 ID\n{json.dumps(sorted(existing_ids), ensure_ascii=False)}\n\n"
            f"# 模式\n{mode_name}\n\n"
            f"{source_stakeholder_rule}"
            f"{rules}"
            "- 候選需求的 text 與 acceptance_criteria 必須能看出和產品情境的關聯；看不出關聯就不要輸出。\n"
            '# 輸出 JSON\n{"candidates": [...]}'
        )
        messages = self.build_direct_messages(prompt)
        data = self.chat_json(messages, action="elicited_requirement_extract")
        raw = data.get("candidates", []) if isinstance(data, dict) else []
        return validate_elicited_reqts(raw)
