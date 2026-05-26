# Mediator prompt builders: keep long meeting prompts out of flow logic.
import json
from typing import Any, Dict, List, Optional

from agents.profile.scenario import scenario_prompt_value


DECISION_ISSUE_DISCUSSION_MODE_GUIDE = """# 討論模式（discussion_mode）情境說明
- **sequential（逐一發言）**：適合需要依序表態、回應前一位發言並逐步收斂的議題。後發言者會看到前面所有人的發言，可針對性回應，討論感較強。
- **simultaneous（同時發言）**：適合需要先獨立提出觀點，再比較差異的議題，不需即時回應前一位。每人只看到議題與專案狀態，不看同輪其他人的發言。
請依議題性質選擇其一。"""


DECISION_ISSUE_TITLE_RULES = """# 標題與描述撰寫要求（重要）
- **title（標題）**：一句話、具體、讓人一眼知道「要討論什麼」。要與本專案內容掛鉤，指出涉及的對象、需求或 Conflict 重點，勿只寫類型名稱。
- **description（描述）**：簡短說明「為什麼要開這個議題、要解決什麼」。可提及相關需求 id 或 Conflict id，並用一兩句話說明討論重點。
- 標題與描述都應直接服務於後續討論收斂，不要加入未在 artifact 中出現的新事實。"""


DECISION_ISSUE_CATEGORY_RULES = """# 決策議題類型與開題
- **conflict_resolution**：latest conflict report 中仍有會阻礙 SRS 定稿的 Conflict，且需要形成可寫入草稿或決策紀錄的解法時使用。
- **requirement_revision**：latest draft 中既有需求語意、邊界、責任、優先級或可驗證性不足，需要修正既有需求時使用；不得用來新增未被輸入支持的新需求。
- **srs_open_question**：latest draft、system models、conflict report 或 feedback 顯示仍有阻礙 SRS 生成的未決問題，需要正式會議確認時使用。
- **srs_open_question**：若同輪有多個 SRS 待確認問題，執行層會自動合併為單一集中回覆議題，讓相關 agent 一次回答。
- **tradeoff_decision**：多個需求、限制、品質目標或外部限制無法同時完全滿足，需要決定可接受折衷並讓 SRS 能明確描述時使用。
- 其餘依專案狀態與優先順序判斷，無強制對應。"""


DECISION_ISSUE_OUTPUT_SCHEMA = """# 輸出 JSON
{
  "items": [
    {
      "title": "具體決策議題標題（與本專案內容掛鉤的一句話）",
      "description": "簡短說明為何要討論、要解決什麼",
      "category": "類型 id",
      "participants": ["agent1", "agent2"],
      "discussion_mode": "sequential 或 simultaneous",
      "speaking_order": ["agent1", "agent2"],
      "source_ids": ["id1", "id2"]
    }
  ]
}"""


def decision_issues_prompt(
    *,
    types_text: str,
    context: str,
    skip: set,
    registered: List[str],
    limit: int,
) -> str:
    return f"""# 任務
    你是需求正式會議主持人。本輪 issue proposal 的明確目標是：找出最值得討論、且能讓 latest draft 更 SRS-ready 的決策議題。
    SRS-ready 指草稿足以讓後續 Documentor 轉成正式 SRS：需求清楚、邊界明確、衝突可決議、模型與需求一致、外部限制不會被誤寫成未確認需求。
    若有提供**最新需求草稿**，該草稿是主要依據；system_models、latest conflict_report 與 feedback 只能用來判斷草稿是否需要修正、補決策或標示待確認。請依這些輸入撰寫 issue 標題與描述。
    決策議題類型必須從下方「決策議題類型定義」中選擇，每個決策議題需決定：標題、描述、類型、參與者、討論模式、發言順序。

    # 決策議題類型定義（category 必須為以下 id 之一）
    {types_text}

    # 決策議題排程依據
    {context}

    # 已在本輪或前輪討論過的項目（可略過或合併，勿重複開相同議題）
    已討論 source_ids: {json.dumps(list(skip), ensure_ascii=False)}

    # 可用 agent（participants 與 speaking_order 僅能使用此清單內名稱）
    {json.dumps(registered, ensure_ascii=False)}

    {DECISION_ISSUE_DISCUSSION_MODE_GUIDE}

    {DECISION_ISSUE_TITLE_RULES}

    {DECISION_ISSUE_CATEGORY_RULES}

    # 約束
    - 最多排入 {limit} 個決策議題。請依你判斷的優先順序排列。
    - 優先選擇會阻礙 SRS 生成品質的議題：需求語意不清、範圍或責任邊界不明、Conflict 尚未形成可落地決策、系統模型與草稿不一致、feedback 指出但草稿尚未正確吸收或標示待確認的限制。
    - 不要為了補齊文件而新增輸入沒有支持的新需求；若需要確認，只開待確認或決策議題。
    - 不要討論純排版、措辭美化或不影響 SRS-ready 的小問題。
    - 若無需討論的議題，請回傳空陣列
    - category 只能是上述類型定義中的 id
    - discussion_mode 依上表情境選擇 "sequential" 或 "simultaneous"
    - 若有對應的 Conflict/需求/問題 id，請填在 source_ids 方便追蹤

    {DECISION_ISSUE_OUTPUT_SCHEMA}"""


def meeting_action_prompt(
    *,
    state_summary: Dict[str, Any],
    last_observation: Dict[str, Any],
    enable_human_escalation: bool,
) -> str:
    state_text = json.dumps(state_summary, ensure_ascii=False, indent=2)
    obs_text = json.dumps(last_observation, ensure_ascii=False, indent=2)
    escalate_hint = ""
    escalate_action = ""
    if enable_human_escalation:
        escalate_action = (
            "- escalate_to_human：某議題交由人類裁決。"
            "params: {{ \"issue_id\": \"T-01\" }}（須已 start_discussion）\n"
        )
        escalate_hint = "；若未共識可選 escalate_to_human 再 save_issue"

    return f"""# 任務
    你是本輪主持人。根據當前狀態與上一動結果，選下一個動作。

    # 動作
    - generate_decision_issues：issues 為空時
    - expand_decision_issues：僅在 state.can_expand_decision_issues=true 且確有新議題時
    - start_discussion：{{"issue_id":"T-01"}}
    - resolve_issue：{{"issue_id":"T-01"}}，需已 start_discussion
    {escalate_action}- save_issue：{{"issue_id":"T-01"}}，需已 resolve 或 escalate
    - finish_round：僅在 formal issues 已 save、queue 已處理或遞延，且無需 expand / escalate 時

    # 當前狀態
    {state_text}

    # 上一步結果
    {obs_text}

    # 規則
    - issues 為空先 generate_decision_issues
    - queue-first：能由 clarification / direct_apply / human_decision 先處理的議題，不要急著重開 formal meeting
    - issue 順序：start_discussion → resolve_issue → save_issue{escalate_hint}
    - 若上一步 resolve_issue 結果含 needs_human=true，必須先 escalate_to_human 再 save_issue
    - queue 未處理完不得 finish_round
    - 有 deferred 項或新 open_questions 時，先判斷 expand / escalate；需求品質問題應併入正式議題討論
    - 若某題在討論後已明確自然收斂，應直接 resolve_issue 整理結論。
    - formal meeting 題目經討論後仍無法收斂時，resolve_issue 會整理決策選項與 recommendation，接著必須 escalate_to_human 交由人類裁決，不交給 user agent。
    - 所有議題 save 完畢且 can_expand_decision_issues=true 時，應主動評估是否有新議題需補充討論（expand_decision_issues）；確認無追加需求才 finish_round
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
你是需求擷取會議主持人。請安排本輪需求擷取會議。

你要決定 participants、goal、agent_actions、meeting_phase。

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
- analyst：使用者目標、需求文字是否成立、產出內容、優先級、成功標準。
- modeler：主要流程、輸入/輸出、角色互動、狀態變化、例外流程、人工介入。
- expert：外部限制、資料可信度、營運約束、合規/安全/風險底線、結果可接受性。

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
    "analyst": {{"action": "ask_user | supplement_question | propose_finish"}},
    "expert": {{"action": "ask_user | supplement_question | propose_finish"}},
    "modeler": {{"action": "ask_user | supplement_question | propose_finish"}}
  }}
}}"""


def conflict_review_prompt(
    *,
    participants: List[str],
    candidate_count: int,
) -> str:
    return f"""你是需求會議主持人，即將進行「衝突批次再審查」（同一輪內可能有多筆 Conflict/Neutral 項目需一併做標籤再審查）。

    請決定本輪討論模式（只能二選一）：
    - sequential：參與者依你指定的 participants **陣列順序**逐一發言。此模式**不得**使用 speaking_order 欄位；順序**只能**用 participants 表達。
    - simultaneous：每位參與者各自獨立、同時提出看法（實作上並行蒐集發言），不強調逐一輪替。

    本輪待審項目數（Conflict + Neutral）：{max(1, candidate_count)}

    可選參與者代號：
    {json.dumps(participants, ensure_ascii=False)}

    輸出**僅可**為一個 JSON 物件，欄位如下：
    {{
      "discussion_mode": "sequential 或 simultaneous",
      "participants": ["至少兩位可選參與者代號"]
    }}

    規則：
    - participants 只能從可選參與者代號中挑選，不可包含 user。
    - participants 至少需要兩位；若某角色角度對本批項目沒有幫助，可以不安排。
    - participants 的陣列順序即為 sequential 時的發言順序。
    - 若需逐步比對證據、修正他人判準或逐筆重判，可優先 sequential；若只需快速蒐集獨立判斷可選 simultaneous。
    """


def meeting_title_batch_prompt(
    *,
    entries: List[Dict[str, Any]],
    context_label: str,
) -> str:
    return f"""你是需求會議主持人。所有會議議題標題都由 Mediator 統一命名。
    請根據議題描述、類型、來源與參與者，為每個議題撰寫一句**簡短、易懂**的標題（讓人一眼知道要討論什麼）。

    # 會議情境
    {context_label}

    議題清單:
    {json.dumps(entries, ensure_ascii=False, indent=2)}

    規則:
    - 繁體中文、一句話；口語可讀，避免公文腔與長串頓號。
    - 長度約 **12～28 字**，最多不超過 36 字；不要只寫類型名稱（如「衝突討論」「需求取捨」）。
    - 若描述中有具體對象或 ID，標題應納入。
    - current_title 只作為背景參考，不可原樣照抄無內容的泛稱。
    - 僅輸出 JSON object，items 內的 index 對應原清單。

    輸出:
    {{"items": [{{"index": 0, "title": "具體標題"}}]}}"""


def meeting_title_prompt(
    *,
    previous_title: str,
    category: str,
    description: str,
    proposer_agent: Optional[str],
    summary: str,
    decision: str,
    resolution_status: str,
    contribution_text: str,
) -> str:
    proposer_line = ""
    if proposer_agent:
        proposer_line = f"\n原始提案者（agent id）: {proposer_agent}"
    return f"""你是需求會議主持人。以下議題已討論完畢並將存檔，請**只根據下方資訊**撰寫**一句**繁體中文「會議記錄標題」。

    風格（最重要）：
    - **簡單易懂**：用口語可讀的短句，避免公文腔、長串頓號或從句堆砌。
    - **精簡**：全長 **約 12～28 字為佳**，最多不超過 36 字；能短則短。
    - 點出「主題＋重點結論或決策方向」即可，不要複述整段決議全文。

    議前標題（可參考，必要時濃縮改寫）: {previous_title or "（無）"}
    類型: {category or "（無）"}
    說明: {description or "（無）"}{proposer_line}

    討論後摘要: {summary or "（無）"}
    決議文字: {decision or "（無）"}
    收斂狀態: {resolution_status or "（無）"}

    各方發言摘要:
    {contribution_text}

    規則:
    - 一句話、繁體中文；勿使用 Markdown、引號包裹整句、或條列式。
    - 勿虛構未出現的產品名詞或法規名稱。
    - 優先從「決議文字／摘要」濃縮，其次才參考發言摘要。

    只輸出一個 JSON 物件：{{"title": "最終標題"}}"""


def convergence_prompt(*, issue: Dict[str, Any], discussion_text: str) -> str:
    return f"""你是需求會議主持人。請判斷以下議題的討論是否已自然收斂。

    # 議題
    標題: {issue.get('title', '')}
    描述: {issue.get('description', '')}

    # 各方發言
    {discussion_text}

    # 判斷標準
    - 只有在主要參與者沒有需求層級的反對、保留或未回應疑慮時，才能判定為「收斂」。
    - 若仍有會影響 requirement、scope、acceptance criteria、風險或人類裁決的 open question，必須判定為「未收斂」。
    - 若只是多數同意但仍有一個重要角色提出未解疑慮，也必須判定為「未收斂」。
    - 若發言只是在補充語氣差異、不影響需求內容或驗收，才可視為已收斂。

    # 輸出 JSON
    {{
      "converged": true 或 false,
      "reason": "一句說明為何收斂/未收斂",
      "summary": "若收斂，簡述共識內容；若未收斂則空字串",
      "decision": "若收斂，寫出可作為決策的具體內容；若未收斂則空字串"
    }}
    只輸出 JSON。"""


def decision_option_analysis_prompt(
    *,
    issue: Dict[str, Any],
    discussion_text: str,
) -> str:
    return f"""# 任務
    你是需求會議主持人。請把以下尚未自然收斂的議題整理成「需要人類裁決的決策分析」。
    不要替人類做最終決策，也不要模擬投票。你只能提出選項、影響與建議。

    # 議題
    標題: {issue.get("title", "")}
    描述: {issue.get("description", "")}

    # 各方發言
    {discussion_text or "（無發言紀錄）"}

    # 要求
    - options 請列 2-4 個可執行方案；若只有一個合理方案，也至少提供「採用」與「暫緩」兩種選項。
    - 每個 option 必須包含 pros、cons、impact、risk。
    - recommendation 只能是建議，不代表已決議；最後由人類裁決，不交給 user agent。
    - affected_requirement_ids 優先使用議題 source_ids 中的需求 id；若沒有，回空陣列。
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
      "affected_requirement_ids": ["REQ-01"],
      "unresolved_points": ["需要人類裁決的事項"]
    }}
    只輸出 JSON。"""


def human_option_slates_prompt(
    *,
    issue: Dict[str, Any],
    discussion_text: str,
) -> str:
    return f"""# 任務
    從以下議題討論中，整理可供人類做最終裁決的方案 slate。

    # 議題資訊
    標題: {issue.get('title', '')}
    描述: {issue.get('description', '')}

    # 各方討論內容
    {discussion_text}

    # 要求
    1. best_options 請列 2-3 個最具體、可執行、且可由人類裁決的方案。
    2. compromise 可提供 1 個折衷方案；若討論中沒有合理折衷，請回傳空物件。
    3. 每個方案都要能對應需求、範圍、驗收或風險的實際影響，不要只改寫發言內容。

    # 輸出 JSON
    {{
    "best_options": [
        {{
            "id": 1,
            "title": "方案標題",
            "description": "方案內容",
            "source": "提出此方案的 agent 名稱"
        }},
        {{
            "id": 2,
            "title": "方案標題",
            "description": "方案內容",
            "source": "提出此方案的 agent 名稱"
        }},
        {{
            "id": 3,
            "title": "方案標題",
            "description": "方案內容",
            "source": "提出此方案的 agent 名稱"
        }}
    ],
    "compromise": {{
        "id": 4,
        "title": "折衷方案標題",
        "description": "折衷方案內容",
        "rationale": "為何此方案能平衡各方需求"
    }}
    }}
    只輸出 JSON。"""


def update_decisions_prompt(
    *,
    round_discussions: List[Dict[str, Any]],
    conflicts: List[Dict[str, Any]],
) -> str:
    return f"""# 任務
    彙整本輪所有 issue 討論決策，並更新 Conflict 的 label。

    # 本輪討論結果
    {json.dumps(round_discussions, ensure_ascii=False, indent=2)}

    # 當前 Conflict 列表
    {json.dumps(conflicts, ensure_ascii=False, indent=2)}

    # 規則
    - 若本輪討論認定某筆 Conflict 已解決（非 Conflict），將該筆 label 改為 Neutral
    - 若本輪討論認定某筆 Neutral 實為 Conflict，將該筆 label 改為 Conflict（誤判修正與升級皆經討論 + 本步驟）
    - 其餘依討論結果維持原 label。輸出 conflicts 時請保留每筆原有的所有欄位（id、description、requirement_ids、stakeholder_names 等），僅依討論結果更新 label
    - 每個 new_decisions 項目請填寫 resolved_conflict_ids：此決策所解決的 Conflict id 列表（若該議題討論解決了某個 Conflict 則填其 CF-xx id，否則空陣列）
    - 若本輪討論中有人指出「尚未列在當前 Conflict 列表中的需求/立場 Conflict」（辨識漏報），請將該筆填入 new_conflicts，格式見下方。id 留空由系統指派。
    - 請清楚整理分歧與未解決事項。

    # 輸出 JSON
    {{
    "new_decisions": [...],
    "conflicts": [...],
    "new_conflicts": [
        {{
            "description": "Conflict 描述",
            "requirement_ids": ["R-01", "R-02"]
        }}
    ]
    }}"""


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
    return f"""你正在參與需求擷取會議的收束投票。本輪 {proposer_role} 已提議結束需求擷取，但必須由收束投票流程決定是否真的收束。

# 你的角色
{role}

# 你的判斷重點
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
- 如果依你的角色判斷，目前資訊已足夠整理下一版 requirement set，vote 填 close。
- 如果仍有一個會明顯影響需求正確性的關鍵問題沒問，vote 填 continue。
- 不要因為還可以問更多細節就反對收束；只有缺口會影響需求正確性或可用性時才 vote continue。
- 若 vote continue，missing_question 必須是一個可直接問利害關係人的單一主問題。
- 僅輸出 JSON，不要輸出 Markdown。

# 輸出 JSON
{{"vote":"close|continue","reason":"一句話理由","missing_question":"若 vote=continue，填一個建議追問；否則空字串"}}"""
