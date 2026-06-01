# Mediator prompt builders: keep long meeting prompts out of flow logic.
import json
from typing import Any, Dict, List, Optional

from agents.profile.scenario import scenario_prompt_value


MEDIATOR_SYSTEM_PROMPT = """需求調解主持：整理議題提案、規劃正式會議、主持討論並形成收斂結果。

規則：
1. mediator 預設提案直接進入正式會議規劃；其他 agent 提案依本輪容量分流為 issues 或 backlog；不得憑空新增議題來源。
2. 需要人類裁決時走 human decision；其餘議題進 formal meeting，由正式會議收斂。
3. 未自然收斂時，整理可選方案、影響與 recommendation，交由人類裁決；不得由代理人或 user agent 替人類定案。
4. 正式會議維持問題導向討論，不把會議變成欄位填寫；會議結果再由 Analyst 沉澱成 REQ-* 需求條目。
5. 無法形成明確建議時，升級至人類裁決。"""


def issue_selection_prompt(
    *,
    proposals: List[Dict[str, Any]],
    max_items: int,
    skip_source_ids: List[str],
    is_last_round: bool,
    round_num: int,
) -> str:
    return f"""# 任務
請根據非預設議題提案進行分流，產生本輪正式會議議題、backlog 與 discarded。

# 議題提案
{json.dumps(proposals, ensure_ascii=False, indent=2)}

# 分流規則
- 本輪 round={round_num}，is_last_round={str(is_last_round).lower()}，max_issues={max_items}，already_discussed_source_ids={json.dumps(skip_source_ids, ensure_ascii=False)}。
- 只處理非 mediator 提案；mediator 預設提案已由程式直接送入正式會議規劃。
- agent proposal 只是候選訊號，不是正式會議題目；Mediator 必須負責合併、淘汰與定題。
- 預設會議已處理整份衝突報告、全部 User Requirements 初步正式化；非 mediator 提案不得重複提出這兩類泛稱議題。
- 只有當預設會議後的 latest draft 仍留下具體 source id、open question、決策缺口、scope/責任分歧、限制確認、模型不一致或人類裁決需求時，才可選入正式議題；一般議題不得再提出需求衝突解決，需求衝突只由預設會議處理。
- 一般議題選入優先序：
  1. Requirement Completeness：既有 REQ-* 缺 acceptance criteria、verification、可量化 NFR 門檻、外部限制影響、source coverage，或仍抽象不可測。
  2. Boundary / Responsibility：系統、人工、第三方或角色責任不清。
  3. Tradeoff：多方需求有方案取捨但尚未形成衝突。
  4. Model Alignment：模型揭露流程、狀態、actor、資料或責任不一致。
  5. New Requirement / Expansion：新增或延伸需求；只有前面高優先缺口不阻礙定稿時才選入。
- 若 Requirement Completeness 類提案存在且有具體 source 支持，應優先選入 issues；不要先選新增功能或低優先建議。
- 選入 issues 的數量最多 max_issues；在不降低品質的前提下，盡量填滿 max_issues。
- 高價值且本輪容量內的提案放 issues。
- 可能有價值但本輪排不下、證據尚不夠成熟、或需要等後續 draft/meeting 補足的提案放 backlog。
- 只有明確低價值、重複、已被討論涵蓋、沒有 source 支持、可由單一 agent 直接修稿/更新 feedback/更新模型、或不需要正式會議的提案才放 discarded。
- 只有「需要正式會議處理」的提案才能進 issues/backlog：必須能讓需求更明確、可驗收、可追溯、可建模或一致，且需要多方確認、取捨、scope/責任裁定、限制確認、模型與需求一致性確認或人類裁決。
- 正式議題必須代表一組相關需求背後的共同問題，例如同一使用流程、狀態規則、責任邊界、外部限制、方案取捨或模型一致性缺口。
- 不得讓單一 requirement、單一 open question、單一 acceptance criteria、單一來源追蹤或單一模型項目直接成為正式議題；除非 evidence 明確顯示它代表更大的共同問題。
- 可由單一 agent 直接修稿、更新 feedback、更新模型、補格式、補命名、補一般說明的項目放 discarded。
- 避免重複討論 already_discussed_source_ids 已涵蓋的提案；可合併重複或高度相近提案，合併時保留 trace.proposal_ids。
- 依 sources、expect_outcome、importance、reason 判斷；issues 優先選會影響 REQ-* 需求條目完整性的議題，尤其是 acceptance criteria、verification、NFR metric、外部限制影響、source coverage；再選邊界裁定、方案取捨、限制確認、模型與需求一致性問題與定稿阻礙。
- 若多筆提案指向同一使用流程、狀態規則、責任邊界、外部限制、方案取捨、模型缺口、同一批來源 id 或同一個決策結果，合併成一個較大的議題，不要拆成多個小議題，並保留來源追蹤。
- importance 為 low 的提案，除非是最後一輪且會阻礙需求規格定稿，否則放 discarded；不要放 backlog。
- 不要新增輸入資料沒有支持的新需求。
- discarded 每筆至少保留 title、reason、source proposal id 或 trace，並用一句話說明丟棄原因；discarded 不會進入會議，但會保留供稽核。

# 輸出 JSON
{{
  "issues": [],
  "backlog": [],
  "discarded": []
}}"""


def issue_meeting_plan_prompt(
    *,
    issue: Dict[str, Any],
    artifact_context: Dict[str, Any],
    active_types: List[str],
    category_definitions: str,
    registered: List[str],
    stakeholder_names: List[str],
) -> str:
    category_values = "|".join([str(x).strip() for x in (active_types or []) if str(x).strip()])
    if not category_values:
        category_values = "clarify_requirement|define_boundary|tradeoff|align_model"
    return f"""# 任務
請把已選入正式會議的單一議題提案轉成正式會議議題。

# 議題提案
{json.dumps(issue, ensure_ascii=False, indent=2)}

# 相關專案資料
{json.dumps(artifact_context, ensure_ascii=False, indent=2)}

# 可用類型
{category_definitions}

# 可用利害關係人
{json.dumps(stakeholder_names, ensure_ascii=False, indent=2)}

# planning 規則
- category 只能使用上方可用類型；participants 只能使用 agents={json.dumps(registered, ensure_ascii=False)}。
- 若 participants 包含 user，必須填 target_stakeholders，且只能從上方可用利害關係人選擇一位或多位；若 participants 不包含 user，target_stakeholders 請省略或使用空陣列。
- target_stakeholders 必須是此議題實際需要表態或回答的利害關係人；不要因為有 user 參與就放入全部利害關係人。
- discussion_mode 只能是 sequential 或 simultaneous。
- participants 陣列順序就是 sequential 發言順序；simultaneous 會忽略順序。
- discussion_mode 用法：sequential 用於需要逐步比對證據、釐清前後依賴、處理衝突、做取捨或依角色順序修正結論；simultaneous 用於快速蒐集各角色獨立觀點、影響範圍、風險或確認意見，且不需要彼此接續推理。
- 若提供 discussion_rounds，請填 1~3；若未提供，系統將預設為 1 輪。執行時若參與者回覆 stance.state=needs_more_discussion，系統可額外延長最多 2 輪；到上限仍未收斂時交由人類裁決。
- 若 proposed_by 是可用 agents 中的實際 agent 且不是 mediator，participants 必須包含該提案人；mediator 只負責主持與整理，不作為討論發言者。
- title 是正式會議使用的標題，請根據議題提案與相關專案資料命名；必須描述群組化共同問題，不要只用單一來源 id、單一欄位缺口或單一 open question 命名；description 先保留空字串；proposed_by 必須保留原值。
- 若議題提案包含 expected_actions，請原樣保留；只能保留 participants 中對應 agent 的 action hint，不要新增 action。
- 若議題提案已指定 participants、discussion_mode 或 discussion_rounds，除非指定值不在可用 agents 內，請原樣保留。
- 若 title 是「解決需求衝突」，固定以 participants=["user","analyst"]、discussion_mode="sequential" 為基準，讓利害關係人先針對具體 conflict id / URL id 表態，analyst 最後整理與執行 action；只有衝突報告內容明確涉及法規/標準/安全/隱私/外部限制時才加入 expert，只有明確影響流程/狀態/資料/責任邊界或系統模型時才加入 modeler。這場只討論既有解決選項與建議解法的採用或調整，不重新辨識衝突，不提出 open questions；收斂時必須產生可執行 url_updates，說明每個相關 URL 要 keep、revise 或 remove；若已有明確 recommended_resolution 且沒有重大反對，後續可直接採用既有推薦收斂，只有缺少推薦、重大分歧或高風險未決時才交由人類裁決。
- 若 title 是「需求分類」，固定使用 participants=["analyst","user"]、discussion_mode="sequential"，讓 analyst 先執行 refine_requirement 產生或更新初步 REQ-*，再讓 user 依指定利害關係人角度檢查是否漏掉重要使用情境、業務規則、例外條件、驗收條件、品質限制、優先級、風險或假設；這場不做業務裁決，不提出 open questions，也不交由人類裁決。未完全確認的內容應保留於 assumptions、risks 或 open questions，後續正式議題再處理。
- 若一般議題涉及流程、狀態、actor/use case、資料生命週期、互動順序、系統邊界或責任分工，且用圖說明會比純文字更清楚，participants 應加入 modeler；modeler 可透過 model_system 建立或更新模型參與討論。
- 來源追蹤優先使用 sources[*].ids；若 sources.evidence 有 URL-12、REQ-3、CF-2 等具體 id，也要納入。
- 不要編造來源 id；把 proposal.issue_id 放入 trace.proposal_ids 保留提案追蹤。
- 正式會議議題要保持自然需求問題導向；不要用「補 dependencies 欄位」「填 risks 欄位」這類欄位填寫題目命名。若欄位缺口重要，請改寫成背後的需求問題、邊界問題、限制問題、方案取捨或模型不一致。
- 預期此議題收斂後，Analyst 可把結果沉澱到 REQ-* 需求條目的描述、驗收條件、相依性、風險、假設、限制、相關模型或開放問題。
- 根據議題提案與相關專案資料決定 participants 與 discussion_mode。

# 每個 issue 項目格式
{{
  "title": "正式會議議題標題",
  "description": "",
  "category": "{category_values}",
  "participants": ["analyst", "modeler"],
  "discussion_mode": "sequential",
  "target_stakeholders": [],
  "trace": {{"artifact_ids": ["..."], "proposal_ids": ["I-R1-..."]}},
  "proposed_by": "analyst",
  "expected_actions": {{"analyst": ["refine_requirement"]}}
}}

# 輸出 JSON
{{
  "issues": []
}}"""


def meeting_action_prompt(
    *,
    state_summary: Dict[str, Any],
    last_observation: Dict[str, Any],
    enable_human_judgment: bool,
) -> str:
    state_text = json.dumps(state_summary, ensure_ascii=False, indent=2)
    obs_text = json.dumps(last_observation, ensure_ascii=False, indent=2)
    judgment_hint = ""
    judgment_action = ""
    if enable_human_judgment:
        judgment_action = (
            "- judge_issue：某議題交由人類裁決。"
            "params: {{ \"issue_id\": \"T-01\" }}（須已 start_issue）\n"
        )
        judgment_hint = "；若 resolution.needs_human=true，先 judge_issue 再 save_issue"

    return f"""# 任務
    根據當前狀態與上一動結果，選下一個正式會議動作。

    # 動作
    - plan_issues：本輪 issues 為空時；若本輪 meeting_issues 已存在，系統會直接載入既有 agenda，不重新規劃
    - add_issues：僅在 state.can_add_issues=true 且確有新議題時
    - start_issue：{{"issue_id":"T-01"}}
    - resolve_issue：{{"issue_id":"T-01"}}，需已 start_issue
    {judgment_action}- save_issue：{{"issue_id":"T-01"}}，需已 resolve_issue；若 resolution.needs_human=true，需先 judge_issue
    - finish_round：僅在 formal issues 已 save、human_decision_queue 已處理或遞延，且沒有可追加議題時

    # 當前狀態
    {state_text}

    # 上一步結果
    {obs_text}

    # 規則
    - issues 為空先 plan_issues；既有本輪 agenda 會被重用
    - human_decision_queue 優先：需要人類裁決的項目先交由裁決流程處理
    - issue 順序：start_issue → resolve_issue → save_issue{judgment_hint}
    - 若上一步 resolve_issue 結果含 needs_human=true，必須先 judge_issue 再 save_issue
    - human_decision_queue 未處理完不得 finish_round
    - 有 deferred 項或新 open_questions 時，先判斷 add_issues 或 judge_issue；需求品質問題應併入正式議題討論
    - 若某題討論後 ready_to_close 多於 needs_more_discussion，且提案者也標示 ready_to_close，應直接 resolve_issue 整理結論。
    - resolve_conflict 題目若已有明確 conflict_report recommended_resolution，且討論中沒有重大反對或新風險，resolve_issue 可直接採用既有推薦形成 agreed，但 resolution 必須包含 URL 層級的 keep / revise / remove 修改結果。
    - formal meeting 題目經討論後仍缺少可採用推薦、存在重大分歧或有高風險未決時，resolve_issue 才整理決策選項與 recommendation，接著 judge_issue 交由人類裁決，不交給 user agent。
    - 所有議題 save 完畢且 can_add_issues=true 時，應主動評估是否有新議題需補充討論（add_issues）；確認無追加需求才 finish_round
    - 需要補專案事實時，遵守本輪工具使用資料
    - 一次只回一個動作

    # 輸出 JSON
    {{
      "action": "動作名稱",
      "params": {{}} or {{"issue_id":"T-01"}},
      "reasoning": "一句說明"
    }}"""


def elicitation_plan_prompt(
    *,
    turn: int,
    max_turns: int,
    default_participants: List[str],
    stakeholder_names: List[str],
    scenario: Dict[str, Any],
    scope: Dict[str, Any],
    current_requirements: List[Dict[str, Any]],
    previous_turn_summary: Dict[str, Any],
    recent_ask_history: Optional[List[Dict[str, Any]]],
) -> str:
    prev = previous_turn_summary or {}
    return f"""# 任務
安排本輪需求擷取會議，決定 participants、goal、agent_actions、meeting_phase。

# 可用資料
- turn: {turn}/{max_turns}
- default_participants: {default_participants}

# scenario
{json.dumps(scenario_prompt_value(scenario), ensure_ascii=False, indent=2)}

# scope
{json.dumps(scope or {}, ensure_ascii=False, indent=2)}

# stakeholders
{json.dumps(stakeholder_names, ensure_ascii=False, indent=2)}

# current_user_requirements
{json.dumps(current_requirements, ensure_ascii=False, indent=2)}

# previous_turn_summary
{json.dumps(prev, ensure_ascii=False, indent=2)}

# recent_questions_and_answers
{json.dumps(recent_ask_history or [], ensure_ascii=False, indent=2)}

# 規劃原則
- 像真實需求訪談主持人一樣，根據已回答內容安排下一個最自然、最能補足需求理解的方向。
- 優先在 scope.in_scope 內推進；不要安排 scope.out_of_scope 方向。
- goal 是本輪需求擷取的主題標題，需簡短、具體、可指導 agent 提問；不要寫成「繼續訪談」「了解更多需求」。
- 若 previous_turn_summary 已標記某方向為已確認、已關閉或不要重複，除非仍阻礙需求成形，否則本輪應往不同但重要的方向推進。
- 先補足需求主幹，再進入細節審查；不要為了覆蓋分類而硬問。
- 不要把「動機」當成預設必問項；只有當動機會改變需求內容、優先級、成功標準或範圍時才追問。

# 角色分工
- analyst：使用者目標、需求語意、使用條件、成功結果與驗收邊界。
- expert：外部限制、領域規則、政策/合規風險、營運風險、公平性與責任歸屬。
- modeler：流程節點、狀態轉移、actor 責任、資料輸入輸出、例外流程與人工介入。
- 每個 agent 只能被安排符合自身分工的提問；若某 agent 本輪沒有符合分工的高價值問題，請不要安排該 agent 提問。
- 每個 ask_user/supplement_question 必須指定 target_stakeholders，且問題內容必須從該 stakeholder 的立場出發。
- 不要把消費者情境問題丟給外送員、餐廳、第三方支付或營運主管回答；若要問這些 stakeholder，必須改寫成該 stakeholder 會關心的影響、責任、限制或底線。

同一輪內，不同 agent 不可追問同一個需求缺口。
每個被安排提問的 agent 都必須能問出可轉成候選 User Requirement、限制、流程邊界或待確認缺口的資訊。

# action
- ask_user：本輪主要向 user 問一個主問題。
- supplement_question：從該角色角度補一個不重複的 user 問題。
- propose_finish：提議結束需求擷取。

# meeting_phase
meeting_phase 只用來標示本輪狀態：
- initial_requirement：找出最能形成候選需求的核心缺口。
- requirement_discussion：深入釐清流程、內容、互動、呈現、限制、例外或可接受標準。
- conclusion：確認目前理解是否正確或提議收束。

# 規則
- participants 只能從 default_participants 選，且必須包含 user。
- participants 應包含 2-3 位非 user agent 與 user。
- 除非本輪要 propose_finish，否則至少一個非 user agent 的 action 必須是 ask_user 或 supplement_question。
- propose_finish 只能在資訊足夠收束時使用；若使用 propose_finish，該 agent 的發言只能輸出固定停止句。
- 僅輸出 JSON，不要附加說明。

# 輸出 JSON
{{
  "participants": {json.dumps(default_participants, ensure_ascii=False)},
  "meeting_phase": "initial_requirement | requirement_discussion | conclusion",
  "goal": "本輪訪談目標",
  "agent_actions": {{
    "analyst": {{"action": "ask_user | supplement_question | propose_finish", "target_stakeholders": ["stakeholder name"]}},
    "expert": {{"action": "ask_user | supplement_question | propose_finish", "target_stakeholders": ["stakeholder name"]}},
    "modeler": {{"action": "ask_user | supplement_question | propose_finish", "target_stakeholders": ["stakeholder name"]}}
  }}
}}"""


def conflict_review_prompt(
    *,
    participants: List[str],
    candidate_count: int,
) -> str:
    return f"""# 任務
    安排衝突批次再審查的討論模式與參與者。

    # 可選討論模式
    - sequential：參與者依 participants 陣列順序逐一發言。
    - simultaneous：每位參與者各自獨立、同時提出看法（實作上並行蒐集發言），不強調逐一輪替。

    # 可用資料
    - 待審項目數（Conflict + Neutral）：{max(1, candidate_count)}

    # 可選參與者
    {json.dumps(participants, ensure_ascii=False)}

    # 輸出 JSON
    {{
      "discussion_mode": "sequential 或 simultaneous",
      "participants": ["至少兩位可選參與者代號"]
    }}

    # 規則
    - participants 只能從可選參與者代號中挑選，不可包含 user。
    - participants 至少需要兩位；若某角色角度對本批項目沒有幫助，可以不安排。
    - participants 的陣列順序即為 sequential 時的發言順序。
    - 若需逐步比對證據、修正他人判準或逐筆重判，可優先 sequential；若只需快速蒐集獨立判斷可選 simultaneous。
    """


def judge_options_prompt(
    *,
    issue: Dict[str, Any],
    discussion_text: str,
    decision_context: Optional[Dict[str, Any]] = None,
) -> str:
    context_block = ""
    if decision_context:
        context_block = (
            "\n    # 既有決策資料\n"
            f"    {json.dumps(decision_context, ensure_ascii=False, indent=2)}\n"
        )
    return f"""# 任務
    請把以下尚未自然收斂的正式會議議題整理成「需要人類裁決的決策分析」。
    不要替人類做最終決策，也不要模擬投票。只能提出選項、影響與建議。

    # 議題
    標題: {issue.get("title", "")}
    類型: {issue.get("category", "")}
    描述: {issue.get("description", "")}
    預期結果: {issue.get("expect_outcome", "")}

    # 討論紀錄
    {discussion_text or "（無發言紀錄）"}
{context_block}

    # 要求
    - options 請列 2-4 個可執行方案；若只有一個合理方案，也至少提供「採用」與「暫緩」兩種選項。
    - 若既有決策資料包含衝突報告的解決選項或建議解法，options 必須優先沿用這些既有方案；只能依討論內容調整文字或補充影響，不要重新發明與報告無關的新方案。
    - 優先使用各 agent 在 proposal 中提出的方案；也可從 text 中萃取可行方案。
    - 每個 option 必須包含優點、限制、影響與風險等級。
    - compromise 請整理 1 個可行折衷方案；若沒有合理折衷，回空物件。
    - recommendation 只能是建議，不代表已決議；最後由人類裁決，不交給 user agent。
    - affected_requirement_ids 優先使用議題來源追蹤中的需求 id；若沒有，回空陣列。
    - 請以繁體中文撰寫。

    # 輸出 JSON
    {{
      "summary": "此議題需要決策的原因",
      "options": [
        {{
          "id": "A",
          "summary": "方案摘要",
          "pros": ["優點"],
          "cons": ["缺點"],
          "impact": ["對需求、範圍、驗收或設計的影響"],
          "risk": "low | medium | high"
        }}
      ],
      "recommendation": {{
        "option_id": "A",
        "rationale": "為何建議此方案",
        "needs_human": true
      }},
      "compromise": {{
        "title": "折衷方案標題",
        "description": "折衷方案內容",
        "rationale": "為何此方案能平衡各方需求"
      }},
      "affected_requirement_ids": ["REQ-01"],
      "unresolved_points": ["需要人類裁決的事項"]
    }}
    只輸出 JSON。"""


def close_issue_prompt(
    *,
    issue: Dict[str, Any],
    discussion_text: str,
    readiness: Dict[str, Any],
) -> str:
    return f"""# 任務
    根據已收斂的正式會議議題，整理具體決議。

    # 議題
    標題: {issue.get("title", "")}
    類型: {issue.get("category", "")}
    描述: {issue.get("description", "")}
    預期結果: {issue.get("expect_outcome", "")}

    # 收斂狀態
    {json.dumps(readiness, ensure_ascii=False, indent=2)}

    # 討論紀錄
    {discussion_text or "（無發言紀錄）"}

    # 規則
    - 只整理討論中已明確收斂的內容，不新增需求、不擴張範圍。
    - decision 必須是可執行的具體決議，不要只寫「可以結束」。
    - agreed_points 列出已同意的重點。
    - affected_requirement_ids 優先使用議題來源追蹤中的需求 id；若沒有，回空陣列。
    - 若本議題是解決需求衝突，affected_conflict_ids 必須包含議題來源追蹤中的每一個 conflict_report id（CR-*）；不要只輸出討論中第一個或最明顯的一筆。
    - 其他議題的 affected_conflict_ids 優先使用議題來源追蹤中的 conflict_report id（CR-*）；若沒有，才使用 pair/group id；都沒有則回空陣列。
    - 請以繁體中文撰寫。

    # 輸出 JSON
    {{
      "summary": "決議摘要",
      "decision": "具體決議",
      "agreed_points": ["已同意重點"],
      "affected_requirement_ids": ["REQ-01"],
      "affected_conflict_ids": ["CR-1"]
    }}
    只輸出 JSON。"""


def closure_vote_prompt(
    *,
    role: str,
    proposer_role: str,
    role_focus: str,
    scenario: Dict[str, Any],
    requirements: List[Dict[str, Any]],
    candidate_texts: List[str],
    recent_ask_history: List[Dict[str, Any]],
) -> str:
    return f"""需求擷取會議收束投票。本輪 {proposer_role} 已提議結束需求擷取，但必須由收束投票流程決定是否真的收束。

# 參與者
{role}

# 判斷重點
{role_focus}

# 產品情境
{json.dumps(scenario_prompt_value(scenario), ensure_ascii=False, indent=2)}

# 目前正式需求
{json.dumps(requirements, ensure_ascii=False, indent=2)}

# 本次需求擷取已整理出的候選需求
{json.dumps(candidate_texts, ensure_ascii=False, indent=2)}

# 最近幾輪正式提問與利害關係人回答
{json.dumps(recent_ask_history or [], ensure_ascii=False, indent=2)}

# 投票規則
- 如果依此參與者判斷，目前資訊已足夠整理下一版 requirement set，vote 填 close。
- 如果仍有一個會明顯相關需求正確性的關鍵問題沒問，vote 填 continue。
- 不要因為還可以問更多細節就反對收束；只有缺口會相關需求正確性或可用性時才 vote continue。
- 若 vote continue，missing_question 必須是一個可直接問利害關係人的單一主問題。
- 輸出只包含下方 JSON。

# 輸出 JSON
{{"vote":"close|continue","reason":"一句話理由","missing_question":"若 vote=continue，填一個建議追問；否則空字串"}}"""
