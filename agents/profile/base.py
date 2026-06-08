# Handles shared agent profile prompts and helper behavior.
import json
from typing import Any, Dict, List, Optional

from utils.template import render_template


def prompt_section(header: str, body: str) -> str:
    text = (body or "").strip()
    if not text:
        return ""
    return f"{header}\n{text}\n\n"


# ========
# Defines proposal prompt function for this module workflow.
# ========
def proposal_prompt(
    *,
    agent_label: str,
    focus: str,
    value_gate: List[str],
    reject_rule: str,
) -> str:
    gates = "\n".join(f"- {item}" for item in value_gate)
    return f"""# 任務
提出本輪的 {agent_label} issue proposal 候選，讓 latest draft 更接近可生成 SRS。

- latest_draft 是文件視角，用來判斷 SRS 可讀性與章節呈現缺口。
- artifact_slices 是 evidence 視角，包含 REQ、feedback、system_models、open_questions、conflicts、scope 等精簡資料；提案必須優先引用其中具體 ID 或片段。

- 提案可以寬鬆；agent 只負責提出有根據的候選訊號，Mediator 會合併、淘汰、排序與定題。
- 優先提出能改善以下面向的候選：{focus}。
- 可以提出單一 REQ、單一 open question、單一模型項目或單一來源造成的疑慮；只要 reason 說明它可能影響需求品質、追蹤、驗收、責任邊界、模型一致性或 SRS 可用性即可。
- 不需要先判斷是否值得開會；這是 Mediator triage 的責任。
- 預設會議已處理整份衝突報告與全部 User Requirements 初步正式化；一般提案只處理 latest draft 仍留下的具體缺口。
- 沒有具體 source/evidence 時，輸出空陣列。
- issue_level 分兩層：
  - blocking：會阻礙 SRS 定稿、需求可驗收性、可追蹤性、一致性、責任邊界或合規底線，必須優先開會。
  - improvement：不阻礙定稿，但能改善需求品質、可讀性、模型一致性、風險揭露或驗收完整性；有容量才進會議，否則進 backlog。

# issue_focus 選項
1. requirement_completeness
2. boundary_responsibility
3. tradeoff
4. model_alignment
5. new_requirement

符合以下條件時應提出；接近門檻、證據尚不完整但可能影響 SRS 品質時，也可以提出交由 Mediator triage：
{gates}
- sources.evidence 必須指出 draft 中的具體缺口、弱欄位、矛盾、未決問題、角色衝突、限制、模型缺口或來源 id。
- 單一 REQ 的 acceptance criteria、NFR category、metric、validation、rationale、risks、assumptions、source trace 或模型關聯若影響 SRS 可驗收性或可追蹤性，可以提出。
- NFR 不另開專屬會議類型；只有在品質要求不明確、不可驗收、metric/validation 缺失、priority 會影響 FR/NFR 版本取捨、或品質要求會影響設計/成本/模型/外部限制時才提出。
- 明確且已有來源支持的 NFR 不要只因為是 NFR 就提出會議；應由 update_requirement 或 refine_requirement 直接寫回 type=non-functional。
- constraint 是限制或底線，不作 priority 議題；若需要討論 constraint，聚焦是否成立、適用邊界、例外與如何遵守。
- expect_outcome 必須是會議後可落地的結果。
- 下列「不要提出」是低價值提醒，不是硬性 triage；若你能提供具體 source/evidence/reason，仍可提出給 Mediator 判斷。
{reject_rule}

- title：共同問題短標籤。
- category：clarify_requirement / formalize_requirement / define_boundary / tradeoff / align_model。
- issue_focus：requirement_completeness / boundary_responsibility / tradeoff / model_alignment / new_requirement。
- expect_outcome：會議後應得到的明確結果。
- sources：array，每筆為 object：{{"artifact": "URL|REQ|conflict_report|conversation|system_models|open_questions|scope|feedback", "ids": ["具體 id"], "evidence": "具體依據或缺口"}}。
- suggested_participants：可選，只能使用 analyst/expert/modeler/user。
- participant_reasoning：可選，說明每個 suggested participant 為何需要參與。
- issue_level：blocking / improvement。
- importance：high / medium / low。
- reason：為什麼這是共同問題，且會影響需求規格完整性。

# 輸出 JSON
[
  {{
    "title": "共同問題短標籤",
    "category": "clarify_requirement",
    "issue_focus": "requirement_completeness",
    "expect_outcome": "會議後可落地的結果",
    "sources": [{{"artifact": "REQ", "ids": ["REQ-1"], "evidence": "具體缺口"}}],
    "issue_level": "blocking",
    "importance": "high",
    "reason": "為什麼這是共同問題"
  }}
]"""


close_gate = """# 收斂品質門檻
- stance.state 只有 ready_to_close 或 needs_more_discussion。
- ready_to_close 表示本輪已足以產生下一版 draft 或 resolution；不代表所有細節都已完美。
- 若本議題已有可收束內容，但仍需要人類在多個可行需求規則中裁決，stance.state 仍填 ready_to_close，並加上 stance.needs_human_decision=true。
- 符合以下條件時，應填 ready_to_close：
  - 本議題的主要需求語意、成功結果、責任邊界或取捨方向已能落地記錄。
  - 若會形成或更新 system requirement，已有可追溯來源。
  - 剩餘不足可明確寫成 acceptance_criteria=待確認、assumptions、risks 或 open_questions，而不會阻止本輪結論。
- 只有缺少會改變結論的關鍵資訊時，才填 needs_more_discussion。
- needs_more_discussion 必須同時提供最小可行 proposal，說明目前建議如何處理，以及仍缺哪個關鍵答案。"""


response_rules = """# response.text 規則
- text 是會議中的自然發言，不是 action 結果、JSON、報告或專案資料內容貼上。
- text 必須依本 agent / speaking_as 的立場發言，說明此立場會關心的需求、風險、限制、模型影響、取捨或底線。
- text 可使用短段落、條列或簡短表格輔助說明；只有在比較方案、列出缺口、限制、風險、模型不一致或衝突處理時才使用表格。
- 不要在 text 中輸出 JSON、schema、程式碼區塊、大型表格或長篇報告。
- 若本輪先執行 action，text 只用自然語言說明該 action 對本議題立場的影響；完整 action 產物會由 conversation 的 analysis / feedback / system_models 欄位保存。
- text 可以引用必要的 requirement id、conflict id 或 model id，但不要把結構化結果原封不動貼進 text。"""


question_rules = """# open_questions 規則
- 不用限制題數；只有真的會影響本議題結論、需求內容、驗收條件、風險、假設、責任邊界或模型判斷的問題才放入。
- ready_to_close 仍可提出 open_questions；若目前已有可落地結論，但某個具體答案會影響 REQ 欄位、驗收條件、責任邊界、風險、假設或模型一致性，應輸出 open_questions，而不是只寫進 assumptions / risks。
- 每題必須指定 to，且 to 只能是本議題參與者或議題指定的利害關係人。
- 每題必須附 reason，說明這個答案會如何影響本議題是否能收斂或寫入 artifact。
- 不要詢問自己可以透過 action 或 artifact_query 取得的既有資料；先查 artifact，再決定是否需要問人。
- 不要重複詢問前面已問過、已回答、或語意相同的問題。
- 沒有關鍵問題就輸出空陣列。"""


conflict_updates = """# resolve_conflict 額外規則
- 若 issue_category 是 resolve_conflict，發言重點是把採用的 resolution 落到 URL 層級。
- 所有發言都要扣回具體 conflict id / URL id；不要只談一般痛點、平台願景或抽象風險。
- 可以在 stance.proposal.url_updates 提出可執行修改：
  - keep：保留 URL。
  - revise：改寫 URL text，讓需求不再互相衝突。
  - remove：移除重複、被取代或不再成立的 URL。
- url_updates 每筆使用 action、ids、text、reason。只有 revise 需要 text。
- Analyst 若本次 action 是 discuss_conflict，必須在 stance.proposal.url_updates 輸出至少一筆可執行修改。
- 不要把多筆 URL 串成一筆巨大需求；語意整合應反映在後續 REQ，不在 URL 層合併。"""


# ========
# Defines response context function for this module workflow.
# ========
def response_context(
    *,
    issue: Dict[str, Any],
    previous_responses: Optional[List[Dict[str, Any]]],
    related_context: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    issue_id = str(issue.get("id") or "")
    category = str(issue.get("category") or "").strip()
    target_stakeholders = [
        str(name).strip()
        for name in (issue.get("target_stakeholders") or [])
        if str(name).strip()
    ]
    issue_text = f"議題 [{issue_id}]: {issue.get('title', '')}\n描述: {issue.get('description', '')}"

    prev_text = ""
    if previous_responses:
        parts = [
            f"【{r.get('agent', '?')}】\n{(r.get('response') or {}).get('text', '')}"
            for r in previous_responses
            if isinstance(r, dict)
        ]
        if parts:
            prev_text = "\n\n".join(parts)

    context_text = ""
    if related_context:
        context_text = json.dumps(related_context, ensure_ascii=False, indent=2)

    recent_ask_history_text = ""
    recent_ask_history = issue.get("recent_ask_history") or []
    if recent_ask_history:
        recent_ask_history_text = json.dumps(
            recent_ask_history,
            ensure_ascii=False,
            indent=2,
        )

    return {
        "issue_text": issue_text,
        "issue_id": issue_id,
        "category": category,
        "target_stakeholders": target_stakeholders,
        "prev_text": prev_text,
        "context_text": context_text,
        "recent_ask_history_text": recent_ask_history_text,
    }


# ========
# Defines action strategy prompt function for this module workflow.
# ========
def action_strategy_prompt(*, default_action: str) -> str:
    return f"""# action 選擇策略
- 只使用「可用 action」中列出的 action。
- action_plan.steps 必須至少有 1 筆合法 action。
- steps 可包含 1 到 3 個 action；只在本次發言前確實需要連續工作時使用多個 step。
- 若只是根據既有資料表達立場，選最小必要 action，通常是 {default_action}。
- 若沒有其他必要 action，也必須輸出 1 筆 {default_action} step；不要輸出空 steps。
- 若 recent_responses 出現新增、否定、修正或補充需求語意、條件、驗收方式、限制、責任邊界或優先級，且可用 action 中有會寫回對應 artifact 的 action，才選該 action。
- 若可用 action 沒有合適寫回 action，使用 respond_issue，並在發言中清楚說明可沉澱到 artifact 的修改方向與依據。
- 若 recent_responses 只是一般立場、偏好或未形成可記錄變更，使用 respond_issue。
- step 順序就是執行順序；不要重複相同 action，也不要為了湊數加 action。
- 每個 step.reasoning 用一句話說明此 action 為何必要。"""


# ========
# Defines response output prompt function for this module workflow.
# ========
def response_output_prompt(*, issue_category: str) -> str:
    conflict_rules = (
        f"\n\n{conflict_updates}"
        if str(issue_category or "").strip() == "resolve_conflict"
        else ""
    )
    return f"""# response 輸出規則
- action plan 完成後仍要產生自然語言發言；不要把 action 結果、JSON 或大型報告直接當成發言。
- 若 action 產生或更新 artifact，發言只說明它如何影響本議題的需求、限制、風險、模型或取捨。
{conflict_rules}"""


# ========
# Defines target stakeholder response rule function for this module workflow.
# ========
def response_target_stakeholder_rule(target_stakeholders: list, issue_id: str) -> str:
    if not target_stakeholders or issue_id == "OQ":
        return ""
    stakeholder_text = "、".join(str(name).strip() for name in target_stakeholders if str(name).strip())
    if not stakeholder_text:
        return ""
    return (
        "\n- 若 open_questions 的 to 是 user，問題必須是問議題規劃指定的利害關係人："
        f"{stakeholder_text}；不得改問其他利害關係人。"
    )


# ========
# Defines response stance rules function for this module workflow.
# ========
def response_stance_rules(*, issue_id: str, category: str, proposal_subject: str) -> str:
    if issue_id == "OQ" or issue_id.startswith("ELICIT-") or category == "resolve_conflict":
        return ""
    return f"""
- stance.state 表示本次發言的討論狀態：ready_to_close=資訊已足夠且可讓 mediator 結束本議題；needs_more_discussion=還需要其他參與者補充或回應。
- 若 stance.state 是 needs_more_discussion，必須在 stance.proposal 提供 proposal，說明建議的{proposal_subject}。
- ready_to_close 表示本輪已足以產生下一版 draft 或 resolution；不代表所有細節都已完美。
- 若本議題已有可收束內容，但仍需要人類在多個可行需求規則中裁決，stance.needs_human_decision=true。
- ready_to_close 可以同時帶 open_questions；這表示本議題可先收斂，但仍有需要後續回答並追蹤的具體問題。
- needs_more_discussion 必須同時提供最小可行 proposal，說明目前建議如何處理，以及仍缺哪個關鍵答案。"""


# ========
# Defines pair review response contract function for this module workflow.
# ========
def pair_review_response_contract(*, known_pair_ids: list, include_reason_basis: bool = False) -> str:
    known_pair_ids_text = json.dumps(
        [str(pair_id).strip() for pair_id in known_pair_ids if str(pair_id).strip()],
        ensure_ascii=False,
    )
    reason_rule = "\n- reason 必須有依據，不可只表態或宣告最終決議。" if include_reason_basis else ""
    return f"""- 外層輸出只包含 text 欄位的 JSON object。
- text 必須是 JSON object 字串，不是巢狀 object。
- text JSON 結構必須為 {{"pair_reviews":[...]}}。
- pair_reviews 必須逐筆涵蓋 本輪必須涵蓋的 pair id 中每個 id，不能遺漏、不能新增未知 id。
- 每筆 pair_reviews 都必須有 id、proposed_label、reason。
- proposed_label 只能是 Conflict 或 Neutral。{reason_rule}
- 本輪必須涵蓋的 pair id：{known_pair_ids_text}"""


# ========
# Defines response output fields function for this module workflow.
# ========
def response_output_fields(
    *,
    issue_id: str,
    is_pair_review: bool,
    text_hint: str,
) -> str:
    if issue_id == "OQ":
        return '    "text": "直接回答問題",\n    "open_questions": []'
    if is_pair_review:
        return f"    {conflict_review_text_hint()}"
    if issue_id.startswith("ELICIT-"):
        return (
            f"    {text_hint},\n"
            '    "target_stakeholders": ["要詢問的 stakeholder 名稱，可一位或多位"]'
        )
    return (
        f"    {text_hint},\n"
        '    "open_questions": [{"to": "目標參與者名稱（user、analyst、expert、modeler）", "question": "會影響本議題結論的具體問題", "reason": "此答案會如何影響本議題結論"}]'
        ',\n    "stance": {"state": "ready_to_close | needs_more_discussion", "needs_human_decision": false, "proposal": {"summary": "建議方案", "rationale": "理由", "tradeoffs": ["取捨或限制"]}}'
    )


# ========
# Defines action plan prompt function for this module workflow.
# ========
def action_plan_prompt(
    *,
    role: str,
    issue: Dict[str, Any],
    issue_category: str,
    previous_response_count: int,
    recent_responses: list,
    has_related_context: bool,
    recent_ask_history: list,
    actions_text: str,
    default_action: str,
) -> str:
    observation = {
        "role": role,
        "issue": issue,
        "issue_category": issue_category,
        "previous_response_count": previous_response_count,
        "recent_responses": recent_responses,
        "has_related_context": has_related_context,
        "recent_ask_history": recent_ask_history,
    }
    action_strategy = action_strategy_prompt(default_action=default_action)
    response_output = response_output_prompt(issue_category=issue_category)
    return f"""# 任務
請根據 observation 規劃本次正式會議發言前要執行的 action plan。

# Observation
{json.dumps(observation, ensure_ascii=False, indent=2)}

{actions_text}

{action_strategy}

{close_gate}

{response_output}

# 輸出 JSON
{{
  "action": "done",
  "params": {{}},
  "reasoning": "...",
  "action_plan": {{
    "goal": "本次正式會議發言目標",
    "steps": [
      {{"id": "{default_action}", "action": "{default_action}", "params": {{}}, "reasoning": "..."}}
    ]
  }}
}}"""


# ========
# Defines action plan repair prompt function for this module workflow.
# ========
def action_plan_repair_prompt(
    *,
    original_prompt: str,
    format_error: str,
    default_action: str,
) -> str:
    return f"""{original_prompt}

# 修復要求
上一次 action plan 不合法：{format_error}

請只重新輸出合法 JSON。
- action 必須是 done。
- action_plan.steps 必須至少有 1 筆。
- 每筆 step.action 必須來自「可用 action」。
- 如果沒有其他必要 action，輸出 1 筆 {default_action} step。
- 不要輸出空 steps，不要輸出解釋文字。"""


elicitation_context = """# Requirement Elicitation Interview
- 這是同一場需求擷取會議的接續發言，不是自由提問。
- 必須遵守本輪 action：ask_user/supplement_question 代表向利害關係人提問；propose_finish 只能輸出固定停止句。
- 問題必須承接目前需求理解、前面發言、利害關係人已回答內容與上一輪摘要。
- 不要重複問已確認、已拒絕、利害關係人說不在意、或已被記錄成候選需求的內容。
- 若目前理解已足夠，可以提出收束；停止句只代表提議收束，系統會再進入收束投票流程決定是否真的結束。"""


# ========
# Defines elicitation action task function for this module workflow.
# ========
def elicitation_action_task(stop_phrase: str) -> str:
    return (
        "依本輪 action 發言。若 action 是 ask_user 或 supplement_question，"
        "先用 1 句重述目前理解或缺口，再提出當下最重要、最能推進需求確認的一個問題（總長 2-4 句）；"
        "若判斷目前已蒐集到足夠資訊、可以收束本輪需求擷取，則 text 請只輸出以下固定句"
        f"（勿加引號、勿改寫、勿額外說明）：{stop_phrase}"
    )


# ========
# Defines elicitation action rules function for this module workflow.
# ========
def elicitation_action_rules(stop_phrase: str) -> str:
    return f"""- 輸出停止句不是單方結束會議，只是進入三方收束投票。
- 若本輪 action 是 propose_finish，text 必須只輸出停止句：{stop_phrase}
- 若本輪 action 是 ask_user 或 supplement_question，只提出當下最重要的一個問題；不要合併多題。
- 若本輪 action 是 ask_user 或 supplement_question，必須輸出 target_stakeholders，從已選利害關係人中選擇一位或多位。
- 問題內容必須對應 target_stakeholders 的立場、責任、痛點、利益或限制；不得把其他 stakeholder 的情境直接拿來問。
- 若同一主題要問不同 stakeholder，必須改寫成該 stakeholder 會關心的影響與判斷點，不得複製同一題。
- 問題必須可回答，且答案會明顯影響需求文字、範圍、限制、流程邊界或是否收束。
- 提問前必須避開 closed_issues 與 do_not_repeat；不要重問利害關係人已回答、已說不在意、或已表示 covered 的方向。
- 避免使用「還有什麼需求」「請多說一點」等泛問。
- 提問應承接目前理解，避免孤立訪談題。"""


review_contract = """- 外層必須只有 text 欄位。
- text 的值必須是 JSON object 字串，不是巢狀 object。
- text JSON 結構必須為：{"pair_reviews":[...]}。
- pair_reviews 必須逐筆涵蓋每個 [PAIR-xxx] 或 [MULTIPLE-xxx]；每筆都要有：id、proposed_label、reason。
- 不可用類 JSON 條列或文字摘要取代合法 JSON。"""


label_rules = """- 只有在兩項需求無法同時成立、或一方成立會直接違反另一方時，才支持 Conflict。
- Conflict 不只表示執行時互斥；若兩項需求不能原樣共同放入軟體需求規格書，必須先合併、改寫、刪除或人工裁定，也應支持 Conflict。
- 只有在兩項需求可明確判定為不衝突、不重複，且沒有直接語義關係時，才支持 Neutral。
- 若兩項需求描述同一功能範圍、同一流程、同一資料處理或同一輸出行為，即表示存在直接語義關係；不能僅因兩者可共存就判為 Neutral。
- 若一項需求是另一項的子集、細化、補充步驟或同流程的相鄰行為，不能直接判為 Neutral。
- 重複、近似重複、細化、範圍重疊、同一需求槽位的不同措辭、限制、觸發條件、數量或頻率，不可直接支持 Neutral；需判斷是否需要合併、改寫、刪除或人工裁定。"""


reason_rules = """- proposed_label 可以和其他 agent 相同，但 reason 必須提供獨立判斷依據；不要只重複一般語意判斷。
- reason 必須根據需求原文或會議中可追溯的證據，不可臆測不存在的需求、設計方案或外部情境。"""


# ========
# Defines conflict review text hint function for this module workflow.
# ========
def conflict_review_text_hint() -> str:
    return (
        '"text": "{\\"pair_reviews\\":[{\\"id\\":\\"PAIR-1 或 MULTIPLE-1\\",'
        '\\"proposed_label\\":\\"Conflict | Neutral\\",'
        '\\"reason\\":\\"完整審查理由\\"}]}"'
    )


repair_prompts: dict[str, tuple[bool, str]] = {
    'response_json_repair': (True, '上一個回覆不是合法 JSON object。請只修正格式，不要重新分析、不要新增內容。\n輸出必須是單一 JSON object，且至少保留 {required_fields}。{stance_rule}\n\n原始回覆：\n{raw}'),
}


# ========
# Defines render repair prompt function for this module workflow.
# ========
def render_repair_prompt(key: str, **context: Any) -> str:
    is_f, template = repair_prompts[key]
    if not is_f:
        return template
    return render_template(template, {"json": json, **context})


# ========
# Defines retry response function for this module workflow.
# ========
def retry_response(
    *,
    issue: Dict[str, Any],
    previous_responses: Optional[List[Dict[str, Any]]],
    action_results: List[Dict[str, Any]],
    is_answer_question: bool,
) -> str:
    is_elicitation = str((issue or {}).get("id") or "").startswith("ELICIT-")
    if is_answer_question:
        output_contract = '{\n  "text": "直接回答問題",\n  "open_questions": []\n}'
        stance_rule = ""
        task_line = "重新產生一次回答。"
        text_rule = "- text 必須直接回答問題。\n"
    elif is_elicitation:
        output_contract = (
            '{\n'
            '  "text": "一個可直接問指定利害關係人的具體問題？",\n'
            '  "target_stakeholders": ["指定利害關係人"]\n'
            '}'
        )
        stance_rule = ""
        task_line = "重新產生一個可直接詢問 User 的需求訪談問題。"
        text_rule = (
            "- text 必須是一個明確問句，且包含 ? 或 ？。\n"
            "- text 不可只是摘要、分析、會議發言或說明目前沒有更新 artifact。\n"
            "- target_stakeholders 必須使用議題中已指定的利害關係人。\n"
        )
    else:
        output_contract = '{\n  "text": "根據本輪 action 結果提出自然語言會議發言",\n  "open_questions": [],\n  "stance": {"state": "ready_to_close", "needs_human_decision": false}\n}'
        stance_rule = "- stance.state 必須輸出，且只能是 ready_to_close 或 needs_more_discussion。\n"
        task_line = "重新產生一次正式會議發言。"
        text_rule = "- text 必須是自然語言發言。\n"
    return (
        "# 任務\n"
        "上一個回覆不符合輸出契約。請根據同一議題、前文與本輪 action 結果，"
        f"{task_line}\n\n"
        "# 限制\n"
        "- 不要重跑 action，不要新增或修改 artifact。\n"
        "- 不要輸出 action 結果 JSON。\n"
        f"{text_rule}"
        f"{stance_rule}"
        "- 若 action 產生或更新模型、需求、feedback 或分析結果，text 要說明這些結果如何支持本議題判斷。\n"
        "- open_questions 只放本議題仍需要對方回答的關鍵問題；沒有就輸出空陣列。\n\n"
        "# 議題\n"
        f"{json.dumps(issue, ensure_ascii=False, indent=2)}\n\n"
        "# 前文\n"
        f"{json.dumps(previous_responses or [], ensure_ascii=False, indent=2)}\n\n"
        "# 本輪 action 結果\n"
        f"{json.dumps(action_results, ensure_ascii=False, indent=2)}\n\n"
        "# 輸出 JSON\n"
        f"{output_contract}"
    )
