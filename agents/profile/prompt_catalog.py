# Central prompt catalog for long prompt templates used by profile modules.
from typing import Any

PROMPTS: dict[str, tuple[bool, str]] = {
    'agents_profile_analyst_elicitation_repair_prompt_2': (True, '上一輪 elicitation extraction 輸出不是合法 JSON array。請只修正格式，不要重新分析、不要新增需求。\n\n# 必須輸出\n[\n  {{"text":"候選 User Requirement"}}\n]\n\n# 規則\n- 只能輸出 JSON array。\n- 每筆只包含 text。\n- 不要輸出 priority、acceptance criteria、validation、metric、dependencies、risks 或 assumptions。\n- 如果原始輸出沒有可抽取的新需求，輸出 []。\n- 不要輸出 Markdown、程式碼區塊、前言或額外文字。\n\n# 原始輸出\n{str(raw_text or "")[:12000]}'),
    'agents_profile_analyst_conflicts_repair_prompt_3': (True, '上一輪 {error_label} 輸出不是合法 JSON object。請只根據原始輸出與指定 pairs 修正格式，不要重新分析、不要新增 pair。\n\n# 必須輸出\n{{"conflicts":[...]}}\n\n# 欄位規則\n- conflicts 必須是 array。\n- 每筆必須包含 pair_index、label、reason。\n- label 只能是 "Conflict" 或 "Neutral"。\n- label 是 "Conflict" 時才可包含 type。\n- pair_index 只能來自指定 pairs。\n\n# 指定 pairs\n{json.dumps(pair_rows, ensure_ascii=False, indent=2)}\n\n# 原始輸出\n{str(raw or "")[:12000]}'),
    'agents_profile_analyst_conflicts_repair_prompt_4': (True, '上一輪批次補找 Pair 輸出不是合法 JSON object。請只修正格式，不要重新分析。\n\n# 必須輸出\n{{"conflicts":[...]}}\n\n# 欄位規則\n- conflicts 必須是 array。\n- 每筆必須包含 label="Conflict"、requirement_ids、reason。\n- requirement_ids 必須剛好 2 個需求 id，且只能來自本批需求。\n- conflicts 只包含 Conflict 項目。\n\n# 本批需求\n{json.dumps(batch_rows, ensure_ascii=False, indent=2)}\n\n# 原始輸出\n{str(raw or "")[:12000]}'),
    'agents_profile_analyst_conflicts_repair_prompt_5': (True, '上一輪整體 Conflict 分析輸出不是合法 JSON object。請只修正格式，不要重新分析。\n\n# 必須輸出\n{{"conflicts":[...]}}\n\n# 規則\n- 若原始輸出沒有明確 group conflict，輸出 {{"conflicts":[]}}。\n- 每筆 Conflict 必須包含 label="Conflict" 與 requirement_ids。\n- requirement_ids 必須包含至少 2 個需求 id。\n- related_pairs 可選；只有原始輸出有明確 pair 來源時才保留。\n- 輸出只包含上述 JSON object。\n\n# 原始輸出\n{str(holistic_raw or "")[:12000]}'),
    'agents_profile_analyst_conflicts_repair_prompt_6': (True, '上一輪 conflict signoff 輸出不是合法 JSON array。請只修正格式，不要重新裁定。\n\n# 必須輸出\n[{{"id":"衝突ID","new_label":"Conflict 或 Neutral","reason":"一句繁中裁定理由"}}]\n\n# 規則\n- 只能輸出 JSON array。\n- 必須對 proposal_list 中每個 id 輸出一筆 decision。\n- new_label 只能是 Conflict 或 Neutral。\n- 輸出只包含上述 JSON array。\n\n# proposal_list\n{json.dumps(proposal_list, ensure_ascii=False, indent=2)}\n\n# 原始輸出\n{raw[:12000]}'),
    'agents_profile_analyst_conflicts_repair_prompt_7': (True, '上一輪 conflict final reason 輸出不是合法 JSON array。請只修正格式，不要重新分析、不要新增項目。\n\n# 必須輸出\n[{{"id":"PAIR-1","description":"最終裁定描述","final_type":"scope"}}]\n\n# 規則\n- 只能輸出 JSON array。\n- 必須只包含 decision_list 中存在的 id。\n- 每筆必須包含 id 與 description。\n- final_label 是 Conflict 時可包含 final_type；final_type 只能是 logical、technical、resource、temporal、data、state、priority、scope、other。\n- final_label 是 Neutral 時只輸出 id 與 description。\n- 輸出只包含上述 JSON array。\n\n# decision_list\n{json.dumps(decision_list, ensure_ascii=False, indent=2)}\n\n# 原始輸出\n{raw[:12000]}'),
    'agents_profile_analyst_conflicts_task_8': (False, '根據上一版與最新需求衝突資料修訂需求衝突 Markdown 報告。\n\n本專案約束：\n- 每筆最新衝突都要列入報告。\n- 保留上一版仍有效內容，移除與最新衝突資料不一致的內容。\n- 只渲染輸入資料，不重新分類、不新增或移除項目。\n- 衝突描述、解決選項與建議解法視為已定案內容，不可改寫。\n- 報告 H1 標題固定使用「需求衝突報告」。\n- 每筆衝突使用 id 作為顯示編號；不要輸出 Source 欄位。\n- 涉及需求必須完整列出每個需求 ID 與需求內容；多需求也要逐筆列出，不省略、不留下空白段落。\n- 不要產生 Executive Summary。\n- 不要產生整體 recommendations 區塊。\n\n每筆衝突格式：\n## CR-1\n\n### 涉及需求\n- URL-1：需求內容\n- URL-2：需求內容\n\n### 衝突描述\n...\n\n### 解決選項\n1. ...\n\n### 建議解法\n...\n\n只輸出 Markdown。'),
    'agents_profile_analyst_conflicts_task_9': (False, '根據需求衝突資料產生需求衝突 Markdown 報告。\n\n本專案約束：\n- 每筆輸入都要列入報告。\n- 只渲染輸入資料，不重新分類、不新增或移除項目。\n- 衝突描述、解決選項與建議解法視為已定案內容，不可改寫。\n- 報告 H1 標題固定使用「需求衝突報告」。\n- 每筆衝突使用 id 作為顯示編號；不要輸出 Source 欄位。\n- 涉及需求必須完整列出每個需求 ID 與需求內容；多需求也要逐筆列出，不省略、不留下空白段落。\n- 不要產生 Executive Summary。\n- 不要產生整體 recommendations 區塊。\n\n每筆衝突格式：\n## CR-1\n\n### 涉及需求\n- URL-1：需求內容\n- URL-2：需求內容\n\n### 衝突描述\n...\n\n### 解決選項\n1. ...\n\n### 建議解法\n...\n\n只輸出 Markdown。'),
    'agents_profile_analyst_conflicts_task_10': (False, '根據單一已定案 Conflict 項目產生解決選項。\n\n本專案約束：\n- 輸入資料已完成衝突辨識與衝突再審查。\n- 不重新分類、不新增衝突、不移除衝突。\n- label、type、description 視為定案內容。\n- type 只作為策略候選方向；實際解法必須根據需求內容與衝突描述決定。\n- 若 type 是 other，不要硬套特定衝突類型；請根據需求內容與衝突描述產生可行解法。\n- 若本任務沒有提供 resolution strategy guidance，代表此 Conflict 無對應類型策略；請只根據需求內容與衝突描述產生解法。\n- id 必須使用輸入 Conflict 項目的 id，不可自行產生 CONF-* 或 CR-*。\n- 需求 id 與 text 只作為判斷依據，不可改寫。\n- 輸出只包含下方 JSON 欄位。\n\n# 輸出 JSON\n{\n  "id": "Conflict 項目 id",\n  "resolution_options": [\n    {\n      "option": "A",\n      "strategy": "Resolution strategy name",\n      "description": "處理方式",\n      "pros": ["優點"],\n      "cons": ["限制或代價"],\n      "recommendation": true\n    }\n  ],\n  "recommended_resolution": "建議採用的 resolution 與理由"\n}'),
    'agents_profile_analyst_analyze_task_11': (False, '# 任務\n根據 rough_idea，產生一個可實際開發的系統情境名稱。\n\n# 判斷重點\n- 將 rough_idea 轉成清楚的系統名稱。\n- scenario 只輸出名稱字串，不要輸出物件。\n\n# 輸出 JSON\n{\n  "scenario": "可以做的系統名稱"\n}'),
    'agents_profile_analyst_analyze_task_12': (False, '# 任務\n根據產品情境（scenario）與 URL / User Requirements，界定本專案初始需求範圍。\n\n# 規則\n- 只根據產品情境與 URL / User Requirements 判斷；不得新增未被資料支持的範圍。\n- Scope 是專案邊界，不是需求清單；詳細功能、驗收條件、限制與風險留給後續需求條目與草稿章節處理。\n- 範圍內（in_scope）只放高層系統責任邊界，不放逐條 User Requirement；每項應代表一組能力域、流程域、資料責任或外部介接邊界。\n- in_scope 建議 3 到 7 項；不得把 URL-* 需求逐條改寫成 scope。\n- 不要把情緒、抱怨、商業目標、抽象品質或研究建議直接放入範圍內。\n- 範圍外（out_of_scope）只放資料明確排除，或明顯由第三方、線下流程、外部組織負責的內容。\n- out_of_scope 建議 0 到 5 項；不要為了完整而自行補排除項。\n- 不確定是否排除時，不要放入範圍外；沒有明確排除項時輸出空陣列。\n- 輸出只包含 in_scope 與 out_of_scope。\n\n# 輸出 JSON\n{\n  "scope": {\n    "in_scope": [],\n    "out_of_scope": []\n  }\n}'),
    'agents_profile_analyst_analyze_task_13': (True, '請依照 requirements-analyst skill，只根據目前這一條 source_text 抽取尚未記錄的新 User Requirements。\n\n完整 all_text 只作為理解語境的背景，不可從其他 all_text 條目產生需求。\n\n# 目前已有的候選需求摘要\n{existing_requirements_json}\n\n{extraction_rules}\n\n# 粗粒度整理\n- 若 source_text 同時包含目標與細節，輸出的 text 只保留粗粒度 stakeholder goal、need 或 constraint。\n- 同一個利害關係人目標下的操作步驟、欄位、狀態、通知、例外、驗收條件或量化門檻要合併到同一筆 User Requirement，不要拆成多筆。\n- 每筆 User Requirement 應代表一個可討論的使用者目標、需求、限制或責任邊界，而不是單一 UI 元件、單一規則細節或單一步驟。\n\n# 去重\n- 若 source_text 只是重述、同義改寫或細化目前已有候選需求，且沒有形成新的 stakeholder goal、need、constraint 或責任邊界，回傳空陣列。\n- 若 source_text 只補充條件、例外、處理方式、驗收方式、SOP 或量化門檻，不新增 User Requirement；這些細節留到後續需求正式化階段。\n'),
    'agents_profile_modeler_modeling_user_prompt_19': (True, '# 任務\n    以下 PlantUML 程式碼有語法錯誤，請修正後回傳。\n\n    # 模型名稱\n    {model.get(\'name\', \'\')}\n\n    # 原始程式碼\n    {model.get(\'plantuml\', \'\')}\n\n    # 驗證錯誤\n    {error_msg}\n\n    - 只修正 PlantUML 語法，不得改變圖的需求語意、範圍、角色、流程或資料關係。\n    - 修正語法時必須維持原圖元素語言，不可把繁體中文改成英文，也不可把英文改成繁體中文。\n    - 不要新增或移除需求內容；如果資訊不足，維持原本抽象元素，不要臆測補齊。\n\n    # 輸出 JSON\n    {{{{\n    "plantuml": "@startuml\\\\n...修正後的完整程式碼...\\\\n@enduml"\n    }}}}'),
    'agents_profile_user_stakeholder_user_prompt_21': (True, '# 任務\n根據以下產品情境，建議 10 位可能相關的利害關係人。\n\n# 產品情境\n{scenario_context}\n\n# 分類\n- Primary Users：每天直接操作系統、輸入資料、接收通知或完成任務的人。\n- System Owners & Management：負責派工、監督流程、營運決策、權限、資料品質、系統穩定性、安全或維護的人。\n- External Parties：外部會影響或受影響的單位，例如客戶、供應商、第三方服務、稽核、主管機關或合作單位。\n\n# 輸出規則\n- 三類都必須出現。\n- Primary Users 必須剛好 4 位。\n- System Owners & Management 必須剛好 4 位。\n- External Parties 必須剛好 2 位。\n- 輸出順序：Primary Users → System Owners & Management → External Parties。\n- 每位利害關係人必須直接存在於產品情境中。\n- 每位利害關係人的使用情境與責任邊界要明確且不同。\n- 避免使用情境重疊。\n- name 只填名稱，不要用括號補充說明。\n- type 只能是 Primary Users、System Owners & Management、External Parties。\n- reason 用一句話說明選擇理由。\n\n# 輸出 JSON\n{{{{\n    "proposed_stakeholders": [\n        {{{{"name": "利害關係人名稱", "type": "Primary Users | System Owners & Management | External Parties", "reason": "一句話選擇理由"}}}}\n    ]\n}}}}'),
    'agents_profile_user_stakeholder_user_prompt_22': (True, '# 任務\n模擬以下利害關係人，以第一人稱、口語方式從各自角度提出需求。\n\n# 利害關係人\n{stakeholder_list}\n\n# 產品情境\n{scenario_context}\n\n# 發言面向\n1. 日常使用情境\n2. 痛點與困擾\n3. 期望功能\n4. 擔心的事\n5. 最在意的限制、底線或不可接受情況\n6. 與其他角色可能產生取捨的地方\n\n# 輸出規則\n- 每位利害關係人產生 3-5 條 text。\n- 只根據該利害關係人的日常經驗。\n- 不替未選中的角色發言。\n- 每條 text 都必須能回扣產品情境。\n- 請自然描述該角色的目標、擔憂、限制、底線與可接受/不可接受的取捨。\n- 不要刻意製造衝突；只有在產品情境中合理時，才描述可能與其他角色目標拉扯的地方。\n\n# 輸出 JSON\n{{{{\n    "stakeholders": [\n        {{{{\n            "name": "...",\n            "text": ["...", "..."]\n        }}}}\n    ]\n}}}}'),
    'agents_profile_expert_domain_research_user_prompt_26': (True, '# 任務\n根據目前專案狀態與上一步結果，決定下一個 domain research action。\n\n# 可用 action\n- read_reference_docs：需要專案文件證據時使用。\n- research_issue：需要外部領域知識、公開證據、法規、標準或最佳實務時使用。\n- update_feedback：已有 research_results 時必須使用，將結果保存到 feedback。\n- done：沒有需要研究或已完成保存時使用。\n\n# 當前狀態\n{state_text}\n\n# 上一步結果\n{obs_text}\n\n# 規則\n- 研究問題必須來自 scenario、scope、stakeholders、open_questions、URL / User Requirements 或 REQ 的具體內容。\n- 若既有 artifact 或 feedback 已足夠，選 done，不重複研究。\n- read_reference_docs 只在 doc/ 專案文件可能回答問題時使用，並排在相關 research_issue 前。\n- research_issue 每次只聚焦一個問題；需要網路資料時優先官方文件、法規、標準或原始來源。\n- 來源使用純文字名稱或完整 URL，不使用 Markdown link。\n- action_plan.steps 可包含多個步驟；若包含 research_issue，最後必須包含 update_feedback。\n- reasoning 用一句繁體中文說明。\n\n# 輸出 JSON\n{{\n  "action": "done",\n  "params": {{}},\n  "reasoning": "一句說明",\n  "action_plan": {{\n    "goal": "本輪 domain research 目標",\n    "steps": [\n      {{"action": "read_reference_docs", "params": {{"query": "具體文件查詢問題"}}}},\n      {{"action": "research_issue", "params": {{"query": "具體研究問題"}}}},\n      {{"action": "update_feedback", "params": {{}}}}\n    ]\n  }}\n}}'),
    'agents_profile_analyst_analyze_repair_task_27': (True, '上一個回覆不是合法 JSON array。請只修正格式，不要重新分析、不要新增需求。\n\n輸出必須是 JSON array，每筆只包含 text。\n\n原始回覆：\n{raw}'),
    'agents_profile_analyst_analyze_repair_task_28': (True, '上一版需求草稿 Markdown 的 URL-* 覆蓋不符合契約。請只修正 Markdown，不要重新分析，不要新增需求，不要改變原有需求語意。\n\n修正目標：\n- 移除或更正輸入 URL / User Requirements 中不存在的 URL-*：{unknown_ids}\n- 補回缺少的 URL-*：{missing_ids}\n- 每個 URL-* 必須出現在「User Requirements」表。\n- 不得新增輸入資料以外的 URL-*。\n- 不得把 feedback、open_questions、system_models 或 conflict_report 直接轉成 User Requirements。\n\n原始草稿：\n{md}\n\n請只輸出修正後的完整 Markdown 草稿。'),
}

def render_prompt(key: str, **context: Any) -> str:
    is_f, template = PROMPTS[key]
    if not is_f:
        return template
    return render_template(template, context)


def render_template(template: str, context: dict[str, Any]) -> str:
    out: list[str] = []
    i = 0
    n = len(template)
    while i < n:
        ch = template[i]
        if ch == "{" and i + 1 < n and template[i + 1] == "{":
            out.append("{")
            i += 2
            continue
        if ch == "}" and i + 1 < n and template[i + 1] == "}":
            out.append("}")
            i += 2
            continue
        if ch != "{":
            out.append(ch)
            i += 1
            continue
        end = find_expr_end(template, i + 1)
        if end < 0:
            out.append(ch)
            i += 1
            continue
        expr = template[i + 1:end].strip()
        try:
            out.append(str(eval(expr, {}, dict(context))))
        except Exception:
            out.append("{" + template[i + 1:end] + "}")
        i = end + 1
    return "".join(out)


def find_expr_end(text: str, start: int) -> int:
    quote = ""
    escape = False
    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        if quote:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                quote = ""
            continue
        if ch in {"'", '"'}:
            quote = ch
            continue
        if ch in "([{":
            depth += 1
            continue
        if ch in ")]}":
            if ch == "}" and depth == 0:
                return i
            depth = max(0, depth - 1)
    return -1
