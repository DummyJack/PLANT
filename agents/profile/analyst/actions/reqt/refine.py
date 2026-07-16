# Defines action prompts and output contracts.
from ...rules import (
    requirement_context_rules,
    requirement_output_schema,
    requirement_quality_rules,
    requirement_refinement_rules,
)
from agents.profile.base import forbidden_output_rules


def refine_requirement(*, source_id: str) -> str:
    return f"""# 任務
依本議題討論結果，修正 requirements.json 中受影響的 REQ-* 條目。

# Action Boundary
- action=refine_requirement
- 本 action 將本議題的 meeting resolution 轉成包含 REQ、remove_REQ、coverage 與 reason 的 JSON。
- 輸出只描述受本議題影響的正式 REQ 修正、合併、移除與 coverage。
- runtime 會驗證輸出後寫入 artifact.REQ / artifact.coverage。
- current_REQ 是修正基底；只更新本議題影響到的 REQ。
- current_URL 只作為本議題 trace 或來源查核，不是全量整理清單。
- 若 context.mode=refine_granularity_cleanup 或 context.cleanup_issues 有值，本次只處理 cleanup_issues 點名的 REQ 粒度、類型或合併問題，不做其他需求精修。
- 明確且已由會議或來源收斂的 NFR 直接寫回 type=non-functional、category、metric、validation 與 priority；仍未決的品質取捨放入 risks、assumptions 或 open_questions，不要硬寫成定案。
- 若本次需要合併多筆既有 REQ，請保留最合適的一筆既有 REQ id，合併 source 與驗收條件，並在 remove_REQ 列出被合併移除的舊 REQ id。

# Input
- issue、discussion、current_REQ、current_URL、scope、feedback、system_models 與 context 由 runtime context 提供。
- source_id={source_id}

# Context Boundary
- issue 與 discussion 是本次精修的直接來源。
- current_REQ 是唯一可被修正的正式需求基底。
- current_URL 只用於 trace 查核與補足來源，不可當成全量 formalization 清單。
- scope、feedback、system_models 只作為一致性參考；不能單獨創造新需求。

{requirement_context_rules()}

{requirement_refinement_rules(source_id)}

{requirement_quality_rules()}

# Generation Rules
- reason 只用一句話說明本次修正結果。

{requirement_output_schema(source_id=source_id, include_remove_req=True)}

{forbidden_output_rules(
        [
            "不輸出 draft_plan、scope_updates、conflicts 或 system_models。",
            "不輸出舊格式，例如最外層直接使用 REQ。",
            "不補全量 coverage。",
            "不新增沒有 current_URL 或明確會議決議支持的 REQ。",
        ]
    )}"""
