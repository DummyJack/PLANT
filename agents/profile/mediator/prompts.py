# Mediator prompt builders: keep long meeting prompts out of flow logic.
import json
from typing import Any, Dict, List, Optional


DECISION_ISSUE_DISCUSSION_MODE_GUIDE = """# 討論模式（discussion_mode）情境說明
- **sequential（逐一發言）**：適合需要「依序陳述並回應前一位」的議題。例如：衝突再審查、決策取捨、開放問題釐清、需求取捨（NFR 競合）。後發言者會看到前面所有人的發言，可針對性回應，討論感較強。
- **simultaneous（同時發言）**：適合「先各自表態、再比較差異」的議題。例如：腦力激盪、多方案並列、各自提出對某議題的立場或建議，不需即時回應前一位。每人只看到議題與專案狀態，不看同輪其他人的發言。
請依議題性質選擇其一。"""


DECISION_ISSUE_TITLE_RULES = """# 標題與描述撰寫要求（重要）
- **title（標題）**：一句話、具體、讓人一眼知道「要討論什麼」。要與本專案內容掛鉤，例如寫出涉及的對象、需求或 Conflict 重點，勿只寫類型名稱（如勿只寫「Conflict 討論」「需求取捨」）。
- **description（描述）**：簡短說明「為什麼要開這個議題、要解決什麼」。可提及相關需求 id 或 Conflict id，並用一兩句話說明討論重點。
- 範例：標題可為「CF-01 付款失敗處理與退款責任協調」而非「Conflict 討論」；描述可為「請協調相關需求的實作邊界、責任分工與可驗收決策」。"""


DECISION_ISSUE_CATEGORY_RULES = """# 決策議題類型與開題
- **conflict_discussion**：當有 label 為 Conflict 且需要協調可執行解法時，應考慮開此類議題。Neutral label 再審查不進一般正式會議。
- **open_question**：當草稿（或摘要）中有待處理開放問題（含需求描述模糊、邊界待確認）時，可開此類。
- **open_question**：若同輪有多個 open_question，執行層會自動合併為單一「集中回覆」議題，讓相關 agent 一次回答；因此可先正常產生 open_question，無需刻意拆得很細。
- **new_requirement**：當草稿（或摘要）中出現「提出新功能、新限制、新例外情境、新需求」時，**應考慮開此類**，勿忽略；此外，若有跡象顯示既有需求需要修正（例如描述不準確、優先順序變動、邊界條件改變），也可用此類議題讓 User 檢視並調整既有需求。
- **tradeoff**：當需求摘要中有多個非功能需求，或 Conflict 涉及效能、可用性、成本等非功能面向之間的競合取捨時，**應考慮開此類**。
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
    你是需求調解主持人。請根據下方「決策議題排程依據」與「已討論過項目」，自行判斷本輪應處理哪些決策議題。
    若有提供**最新需求草稿**，該草稿為**唯一依據**（含其中的需求表、Conflict、開放問題等章節——開放問題應已寫在草稿內）；請依草稿內文與 id 撰寫 issue 標題與描述。若僅有專案摘要（無草稿檔），則依該摘要判斷。
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
    - 需要補專案事實時，遵守本輪 Tool Context
    - 一次只回一個動作

    # 輸出 JSON
    {{
      "action": "動作名稱",
      "params": {{}} or {{"issue_id":"T-01"}},
      "reasoning": "一句說明"
    }}"""


def requirement_elicitation_plan_prompt(
    *,
    turn: int,
    max_turns: int,
    default_participants: List[str],
    default_mode: str,
    default_sequence: List[str],
    stakeholder_rows: List[Dict[str, Any]],
    stakeholder_names: List[str],
    rough_idea: str,
    current_requirements: List[Dict[str, Any]],
    previous_turn_summary: Dict[str, Any],
    recent_ask_history: Optional[List[Dict[str, Any]]],
) -> str:
    prev = previous_turn_summary or {}
    return f"""# 任務
你是需求擷取會議主持人。請根據目前需求理解、已選定利害關係人、最近對話與訪談記憶，安排本輪需求擷取會議。

你要決定：
1. meeting_phase
2. participants
3. goal
4. agent_actions

# 本輪資訊
- turn: {turn}/{max_turns}
- default_participants: {default_participants}
- discussion_mode: simultaneous（固定）

# 產品情境
{rough_idea}

# 已選定利害關係人
{json.dumps(stakeholder_rows, ensure_ascii=False, indent=2)}

# 目前已有需求或候選需求
{json.dumps(current_requirements, ensure_ascii=False, indent=2)}

# 上一輪摘要
{json.dumps(prev, ensure_ascii=False, indent=2)}

# 最近幾輪正式提問與 user 回答
{json.dumps(recent_ask_history or [], ensure_ascii=False, indent=2)}

# 訪談記憶（避免重複）
- confirmed_issues：已確認方向，不要重問，只能在需要收斂時重述。
- closed_issues：User 已回答、不在意或不想深入的方向，除非出現矛盾，否則視為關閉。
- do_not_repeat：本輪不得原樣追問的問題類型。
{json.dumps({
    "confirmed_issues": prev.get("confirmed_issues", []),
    "closed_issues": prev.get("closed_issues", []),
    "do_not_repeat": prev.get("do_not_repeat", []),
}, ensure_ascii=False, indent=2)}

# 會議階段
meeting_phase 只能選：
- initial_requirement：對齊目前需求理解，找出最能形成候選需求的核心缺口。
- requirement_discussion：深入釐清流程、內容、互動、呈現、限制、例外或可接受標準。
- conclusion：整理目前理解，請 user 確認是否正確或遺漏，或提議收束。

# 發言模式
本需求擷取會議固定使用 simultaneous。
你不需要選擇 discussion_mode，也不要安排 speaking_order。
各 agent 會從自身角色角度獨立提出一個問題，User simulator 會依每題指定的 stakeholder 身份逐題回答。

# 訪談推進原則
請像真實需求訪談主持人一樣，根據 user 已回答內容決定下一個最自然、最能補足需求理解的問題。不要為了覆蓋分類而硬問。

goal 是本輪需求擷取的主題標題，不是一般摘要。請根據產品情境、目前已有需求、前面討論內容與訪談記憶，選出本輪最重要且尚未充分探索的方向。若前面已討論過某方向，除非它仍阻礙需求成形，否則本輪應往不同但重要的方向推進。

goal 應簡短、具體、可指導 agent 提問，例如「釐清尖峰時段點餐與結帳瓶頸」或「確認營運報表的即時資料需求」，避免寫成「繼續訪談」「了解更多需求」這種泛化目標。

每輪問題必須互補，不要讓多個 agent 追問同一個缺口。安排 agent_actions 時，請先判斷目前最需要補的是哪幾類資訊，並讓不同 agent 各自負責不同角度：
- analyst：需求文字能否成立、使用者目標、產出內容、優先級、成功標準、驗收條件。
- modeler：實際操作流程、輸入/輸出、角色互動、狀態變化、例外流程、人工介入。
- expert：外部限制、資料可信度、營運約束、合規/安全/風險底線、結果可接受性。

請先補足需求主幹，再進入細節審查。需求主幹包含：
- 使用者目標與需求成立原因。
- 主要使用流程與任務完成方式。
- 系統主要產出、回應或狀態改變。
- 使用者判斷結果有用、正確、足夠或可接受的標準。
- 資訊組織、呈現、互動或體驗偏好。
- 必須具備與可以延後的能力。

不要把「動機」當成預設必問項。只有當動機會改變需求內容、優先級、成功標準或範圍時，才安排追問；否則直接追問可形成需求候選的資訊。

在需求主幹尚未清楚前，不要優先安排細節審查問題。只有在 user 主動提到，或該問題會直接改變主要需求、使用流程、產出結果、結果可用性或需求成立性時，才進入細節審查。

如果 user 的回答自然帶到下一個方向，就順著回答追問；不要硬切換到尚未覆蓋但當下不重要的方向。

# 角色分工
- analyst 適合使用情境與目標、產出內容與優先級、呈現方式與使用判斷、收束確認。
- modeler 適合使用流程與互動、角色互動、狀態變化、判斷點、例外流程與人工介入。
- expert 只在風險或外部限制會影響需求成立、結果可信度或使用者接受度時深入。
- 若某角色本輪沒有明確且不重複的有效缺口，不要勉強安排它提問；可改由其他角色提問，或在資訊足夠時 propose_finish。

# agent action
你必須為每個非 user agent 指定 action：
- ask_user：本輪主要向 user 問一個主問題。
- supplement_question：從該角色角度補一個不重複的 user 問題。
- propose_finish：提議結束需求擷取。

# 規則
- participants 只能從 default_participants 選，且必須包含 user。
- discussion_mode 固定輸出 "simultaneous"。
- 不要輸出 speaking_order，或輸出空陣列。
- participants 應包含 2-3 位非 user agent 與 user。
- 除非本輪要 propose_finish，否則至少一個非 user agent 的 action 必須是 ask_user 或 supplement_question。
- propose_finish 只能在資訊足夠收束時使用；若使用 propose_finish，該 agent 的發言只能輸出固定停止句。
- 若上一輪已經確認某一方向，本輪應優先順著 user 回答推進到下一個自然缺口；若同一缺口仍重要，必須換成更具體但不誘導的問法。
- 不要重問 confirmed_issues、closed_issues 或 do_not_repeat 中的方向；如果 user 說過不在意、已列過、已覆蓋，就換下一個未確認的大方向。
- 同一輪內，不同 agent 不可追問同一個需求缺口；若 analyst 已問成功標準，modeler 應改問流程/例外，expert 應改問限制/可信度/風險。
- 每個被安排提問的 agent 都必須能問出可轉成候選需求、驗收條件、限制、NFR、流程邊界或待確認缺口的資訊。
- 僅輸出 JSON，不要附加說明。

# 輸出 JSON
{{
  "participants": {json.dumps(default_participants, ensure_ascii=False)},
  "meeting_phase": "initial_requirement | requirement_discussion | conclusion",
  "discussion_mode": "simultaneous",
  "speaking_order": [],
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
    return f"""你是需求會議主持人，即將進行「衝突批次再審查」（同一輪內可能有多筆 Conflict/Neutral pairs 需一併做標籤再審查）。

    請決定本輪討論模式（只能二選一）：
    - sequential：參與者依你指定的 participants **陣列順序**逐一發言。此模式**不得**使用 speaking_order 欄位；順序**只能**用 participants 表達。
    - simultaneous：每位參與者各自獨立、同時提出看法（實作上並行蒐集發言），不強調逐一輪替。

    本輪待審項目數（Conflict + Neutral）：{max(1, candidate_count)}

    可用的參與者代號（必須從下列集合挑出，不可自創；可刪減但建議保留多方觀點）：
    {json.dumps(participants, ensure_ascii=False)}

    輸出**僅可**為一個 JSON 物件，欄位如下：
    {{
      "discussion_mode": "sequential 或 simultaneous",
      "participants": ["..."]
    }}

    規則：
    - participants 至少 2 人，且每個元素必須屬於上方集合；**陣列順序即為 sequential 時的發言順序**。
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
    - 其餘依討論結果維持原 label。輸出 conflicts 時請保留每筆原有的所有欄位（id、description、conflict_type、requirement_ids、stakeholder_names 等），僅依討論結果更新 label
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
            "conflict_type": "Logical | Technical | Resource | Temporal | Data | State | Priority | Scope",
            "requirement_ids": ["R-01", "R-02"]
        }}
    ]
    }}"""


def closure_vote_prompt(
    *,
    role: str,
    proposer_role: str,
    role_focus: str,
    rough_idea: str,
    requirements: List[Dict[str, Any]],
    candidate_texts: List[str],
    recent_ask_history: List[Dict[str, Any]],
) -> str:
    return f"""你正在參與需求擷取會議的收束投票。本輪 {proposer_role} 已提議結束需求擷取，但必須由收束投票流程決定是否真的收束。

# 你的角色
{role}

# 你的判斷重點
{role_focus}

# 原始產品概念
{str(rough_idea or "").strip()}

# 目前正式需求
{json.dumps(requirements, ensure_ascii=False, indent=2)}

# 本次需求擷取已整理出的候選需求
{json.dumps(candidate_texts, ensure_ascii=False, indent=2)}

# 最近幾輪正式提問與 user 回答
{json.dumps(recent_ask_history or [], ensure_ascii=False, indent=2)}

# 投票規則
- 如果依你的角色判斷，目前資訊已足夠整理下一版 requirement set，vote 填 close。
- 如果仍有一個會明顯影響需求正確性的關鍵問題沒問，vote 填 continue。
- 不要因為還可以問更多細節就反對收束；只有缺口會影響需求正確性或可用性時才 vote continue。
- 若 vote continue，missing_question 必須是一個可直接問 user 的單一主問題。
- 僅輸出 JSON，不要輸出 Markdown。

# 輸出 JSON
{{"vote":"close|continue","reason":"一句話理由","missing_question":"若 vote=continue，填一個建議追問；否則空字串"}}"""
