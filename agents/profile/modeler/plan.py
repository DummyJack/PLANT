# Plans model flow targets for the agent.
import json
from typing import Any, Dict, Optional

from agents.profile.base import json_only_rules


max_model_targets = 4

modeling_phase_policies = {
    "initial_system_model": {
        "purpose": "建立初始需求理解與模型邊界。",
        "preferred_types": ["context_diagram", "use_case_diagram"],
        "allowed_types": ["context_diagram", "use_case_diagram", "activity_diagram"],
        "max_targets": 2,
    },
    "post_requirement_formalization": {
        "purpose": "根據正式 REQ-* 對齊模型。",
        "preferred_types": [
            "activity_diagram",
            "sequence_diagram",
            "state_machine",
            "class_diagram",
        ],
        "allowed_types": [
            "context_diagram",
            "use_case_diagram",
            "activity_diagram",
            "sequence_diagram",
            "state_machine",
            "class_diagram",
        ],
        "max_targets": 4,
    },
    "align_model_issue": {
        "purpose": "針對特定模型對齊議題更新模型。",
        "preferred_types": [
            "activity_diagram",
            "sequence_diagram",
            "state_machine",
            "class_diagram",
        ],
        "allowed_types": [
            "context_diagram",
            "use_case_diagram",
            "activity_diagram",
            "sequence_diagram",
            "state_machine",
            "class_diagram",
        ],
        "max_targets": 2,
    },
}


def modeling_phase_policy(phase: str) -> Dict[str, Any]:
    key = str(phase or "").strip()
    return dict(modeling_phase_policies.get(key) or modeling_phase_policies["align_model_issue"])


# ========
# Defines target prompt function for this module workflow.
# ========
def target_prompt(*, context: dict) -> str:
    ctx_text = json.dumps(context, ensure_ascii=False, indent=2)
    return f"""# 任務
分析需求輸入與現有模型，決定本輪 system_modeling 是否需要建立或更新 high-value system model。

# Action Boundary
- action=modeler.plan_system_modeling
- 本 action 規劃本輪 system_modeling 的 model_targets。
- model_targets 指定要 create 或 update 的 system model 類型、名稱、理由與需求來源。

# 建模情境
{ctx_text}

- model_targets：需處理的模型目標；同一 type 可有多張模型。
- modeling_phase 控制本輪產圖時機、偏好的圖型與最大數量；必須遵守 context.modeling_policy.allowed_types 與 max_targets。
- phase_decision 必須說明本輪如何依 modeling_phase 決定要產哪些圖或不產圖。
- skipped_targets 可列出本輪考慮過但跳過的圖型與原因，特別是 context/use case overview 圖不該被重畫時。
- 只規劃 high-value model target，不為了湊數建模。
- high-value 指模型能釐清需求文字無法清楚表達的結構：系統邊界、actor/use case 能力範圍、主要流程/例外流程、跨角色互動順序、狀態生命週期、資料概念/紀錄保存/責任資料/追蹤關係，或能支撐多個 REQ / 高風險 REQ。
- context_diagram 的 actor 範圍以 context.stakeholders 已選利害關係人為準；不得因需求提到外部服務、第三方系統、監管/社區/金融/身分驗證服務，就新增未選擇的外部系統節點。
- 不建低價值模型：只補 related_requirement_ids、只改描述文字、一般功能偏好、既有模型已足夠、建圖後不會讓需求更清楚。
- 沒有 high-value model target 時，model_targets 輸出空陣列，說明不需要新建或更新模型。
- 每次最多 {max_model_targets} 個 model target；超過時只保留最能釐清需求的目標。
- 每個 model target 都要輸出 related_requirement_ids，列出此圖預計支援或釐清的 REQ-*；若目前尚未產生 REQ，才可使用 URL-*。
- 每個 model target 必須輸出 value_reason，說明此模型為什麼值得建立或更新。
- operation 只能是 create 或 update。
- type 限 context_diagram, use_case_diagram, activity_diagram, sequence_diagram, state_machine, class_diagram；use_case_text 會由流程附在 use_case_diagram.text。
- update 必須盡量指定 target_model_id；若沒有 id，至少提供 type 與 name。
- create 必須提供簡短、直觀、可區分同 type 其他模型的 name。
- 若 context.requirement_source 是 REQ，請以 REQ-* 作為主要建模依據，URL-* 只作為來源追蹤背景。
- 若 context.requirement_source 是 URL，代表尚未產生正式 REQ-*，才以 User Requirements（URL-*）作為主要建模依據。
- 若既有模型已存在，這是帶有修訂脈絡的模型迭代；只標記受本次修訂脈絡或主要需求輸入影響的模型。
- 若 context.resume_checkpoint 存在且 stage_id=system_model，表示本輪是失敗後繼續；不得為了恢復而重畫已存在且仍符合本輪目標的模型，應聚焦 checkpoint.step_id / action 指向的失敗或未完成小步驟。
- 既有模型的 source 只用於追蹤來源，不可改寫成新需求。
- 未受影響的既有模型不得列入 model_targets。
- feedback 只作為領域背景、限制、風險、建議與未決事項參考；不得轉成新的模型元素。
- 未決、建議或研究性內容不可畫成已確認模型元素；只能影響模型邊界、限制註記或缺口說明。
- update 的判準：只有當既有模型與本次需求/議題的「目的、範圍、主要情境」相同，只是內容需要修正、補充或刪改時，才選 update。
- create 的判準：若本次需求/議題揭露新的主要流程、例外流程、跨角色互動、業務物件生命週期、資料概念群、責任邊界視角，且沒有既有模型以同一目的與範圍表達它，就選 create；即使已有同 type 模型也可以 create。
- 不要因為已有同 type 模型就強行 update；同一 type 可以有多張圖，每張圖應有可區分的 name 與 purpose。
- 若新內容只是某張既有 overview 圖中的局部節點，但細節已多到會讓 overview 圖過大或混亂，應 create 較聚焦的 activity_diagram、sequence_diagram 或 state_machine，而不是把 overview 圖越改越大。
- 若只是 related_requirement_ids、來源追蹤或文字描述變化，且圖中元素/流程/狀態/邊界不需要變動，不要列入 model_targets。
- context_diagram 在本專案就是情境圖；只有已選利害關係人、主要資料流或責任邊界變動時才列入，不得因一般功能、流程、外部服務細節或驗收條件更新就重畫。
- use_case_diagram 只處理 actor 與用例能力；activity_diagram 只處理流程；sequence_diagram 只處理互動順序；class_diagram 只處理需求層級資料概念；state_machine 只處理狀態生命週期。
- context_diagram 與 use_case_diagram 屬於 overview 圖；它們應保持可掃描，不應承擔流程分支、狀態規則、資料結構或例外責任。
- activity_diagram、sequence_diagram、state_machine、class_diagram 屬於 detail 圖；可以較複雜，但必須聚焦單一流程、互動情境、業務物件生命週期或資料概念群。
- 若需求細節會讓 overview 圖變大，優先 create 聚焦 detail 圖，不要把 context_diagram 或 use_case_diagram 持續擴張。
- 若 detail 圖已經涵蓋多個不相關情境，應 create 新的聚焦圖或 update 後縮小範圍，不要把所有情境塞進同一張圖。
- 圖型選擇優先順序：
  1. 若需求重點是狀態、生命週期、狀態轉移、完成/取消/失敗/審核中/待補件/已結案等狀態規則，優先選 state_machine，不要用 activity_diagram 取代。
  2. 若需求重點是多角色或系統間的互動順序、通知、回覆、等待、審核決策、例外處理決策或跨方協作責任，優先選 sequence_diagram，不要用 activity_diagram 取代。
  3. 若需求重點是資料物件、欄位、紀錄保存、查詢權限、關聯、責任資料或需求層級 domain concept，優先選 class_diagram，不要用 activity_diagram 取代。
  4. 若需求重點是某角色可執行哪些系統能力，才選 use_case_diagram。
  5. 若需求重點是單一角色或系統內流程步驟、分支、例外流程與責任交接，才選 activity_diagram。
  6. 若需求重點是本系統與已選利害關係人、主要資料流或責任邊界，才選 context_diagram；若重點只是外部服務介接或第三方系統細節，改選 detail 圖或列為 scope/assumption，不要擴張情境圖。
- 如果同一議題同時包含流程、狀態與資料概念，應依最需要釐清的需求缺口選一到兩張最有解釋力的圖；不要一律產生 use_case_diagram、activity_diagram、context_diagram。
- initial_system_model：優先建立 overview 模型；通常只選 context_diagram/use_case_diagram，只有明確主要流程缺口時才選 activity_diagram；最多 2 張。
- post_requirement_formalization：以最新 REQ-* 為主，優先建立或更新能支撐正式需求的 detail 圖；只有已選利害關係人、主要資料流或責任邊界變動時才更新 overview 圖。
- align_model_issue：只處理當前議題直接影響的模型；避免重畫無關 overview 圖；通常最多 2 張。
- 每個 model_targets.reason 必須明確說明為什麼是 create 或 update。
- 每個 model_targets.value_reason 必須明確說明該圖能釐清的需求價值；若無法說明，該 target 不應列入。

# Output JSON
{{
  "model_plan": {{
    "phase_decision": "本輪如何依 modeling_phase 與 policy 決定模型目標",
    "model_targets": [
      {{
        "operation": "create | update",
        "type": "diagram type",
        "target_model_id": "既有模型 id，create 時留空",
        "name": "模型名稱",
        "related_requirement_ids": ["REQ-1"],
        "reason": "為何需要 create 或 update",
        "value_reason": "此模型能釐清哪些高價值需求問題"
      }}
    ],
    "skipped_targets": [
      {{
        "type": "diagram type",
        "reason": "為什麼本輪跳過"
      }}
    ],
    "impact_summary": "影響摘要",
    "consistency_summary": "與需求一致性的整體說明",
    "gaps": ["缺口或不一致項目1", "缺口或不一致項目2"]
  }}
}}
{json_only_rules()}"""


# ========
# Defines ModelPlan class for this module workflow.
# ========
class ModelPlan:
    # Defines plan model function for this module workflow.
    def plan_model(self, state, last_observation=None):
        if not state.get("actions_taken"):
            return {
                "action": "plan_models",
                "params": {},
                "reasoning": "先規劃本次需要建立或更新的模型。",
            }
        planned = self.plan_targets(last_observation)
        if planned:
            return planned
        return {
            "action": "done",
            "params": {},
            "reasoning": "已依 plan_models 完成模型處理，不重新規劃。",
        }

    @staticmethod
    # Defines plan targets function for this module workflow.
    def plan_targets(last_observation: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not isinstance(last_observation, dict):
            return {}
        if last_observation.get("action") != "plan_models":
            return {}
        result = last_observation.get("result")
        if not isinstance(result, dict):
            return {}
        plan = result.get("model_plan") if isinstance(result.get("model_plan"), dict) else {}
        targets = plan.get("model_targets")
        if not isinstance(targets, list) or not targets:
            return {
                "action": "done",
                "params": {},
                "reasoning": "plan_models 判斷沒有高價值模型目標，不建立或更新模型。",
            }
        steps = []
        target_count = 0
        for idx, target in enumerate(targets, 1):
            if not isinstance(target, dict):
                continue
            if target_count >= max_model_targets:
                break
            operation = str(target.get("operation") or "").strip()
            if operation not in {"create", "update"}:
                continue
            value_reason = str(target.get("value_reason") or "").strip()
            if not value_reason:
                continue
            action = "create_model" if operation == "create" else "update_model"
            clean_target = {
                key: value
                for key, value in target.items()
                if value not in (None, "", [], {})
            }
            target_count += 1
            steps.append(
                {
                    "id": f"model-target-{idx}",
                    "action": action,
                    "params": {"target": clean_target},
                    "reasoning": str(target.get("reason") or "").strip(),
                }
            )
            if str(target.get("type") or "").strip() == "use_case_diagram":
                steps.append(
                    {
                        "id": f"model-target-{idx}-use-case-text",
                        "action": "write_use_case_text",
                        "params": {"target": clean_target},
                        "reasoning": "use_case_diagram 建立或更新後，補寫文字用例。",
                    }
                )
            steps.append(
                {
                    "id": f"model-target-{idx}-validate",
                    "action": "validate_model",
                    "params": {"target": clean_target},
                    "reasoning": "模型建立或更新後進行 PlantUML 驗證。",
                }
            )
        if not steps:
            return {}
        return {
            "action": steps[0]["action"],
            "params": steps[0]["params"],
            "reasoning": "依 plan_models 的 model_targets 逐一建立或更新模型。",
            "action_plan": {
                "goal": "完成 plan_models 指定的所有模型目標",
                "steps": steps,
            },
        }
