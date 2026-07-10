# Defines action usage timing and output rules.
from agents.profile.base import label_rules as base_label_rules, reason_rules, review_contract
from agents.profile.base import elicitation_action_rules, elicitation_action_task, elicitation_context

label_rules = base_label_rules


# ========
# Defines tool usage policy function for this module workflow.
# ========
def tool_usage_policy() -> str:
    return """- artifact_query 用於查詢目前需求、衝突、open_questions、decisions 與相關來源。
- 若議題、trace、source 或前文出現 URL-*、REQ-*、SM-*、CR-*，優先用 artifact_query mode=related_context, item_id=<id>, compact=true 取得關聯脈絡；不要逐筆 find_items 查同一批來源。
- 使用工具取得專案事實後，仍須判斷需求品質、可測試性、追蹤性與 scope 邊界。
- 工具結果不得直接覆蓋已定案需求；有不確定性時提出 open question 或 change candidate。"""


# ========
# Defines url extraction rules function for this module workflow.
# ========
def url_extraction_rules() -> str:
    return """1. 只抽取輸入明確支持的需求。
2. 保持粗粒度；同一個利害關係人目標下的細節要合併。
3. 不要把按鈕、欄位、通知、狀態變化、例外、SOP 步驟或驗收細節拆成獨立需求。
4. 每筆 text 應能回答：哪個利害關係人在什麼目標或情境下，需要什麼能力、結果或限制。
5. 抽取時以 skill 的 User Story 三要素判斷需求是否成立：as_a、i_want、so_that。
6. 輸出時不要使用 User Story 欄位；請合併成一條中性的 User Requirement text。
7. 若輸入包含數值門檻、驗收條件、系統處理方式或技術限制，URL 只保留 stakeholder goal；細節留到 refine_requirement。
8. 不要產生系統規格、實作細節、量化指標、驗證方式、優先級、相依性、風險或假設。
9. 不使用第一人稱；不要輸出「我需要」「我希望」「我擔心」等發言語氣。請改寫為以利害關係人為主詞的中性需求描述。
10. 若輸入有利害關係人名稱，沿用原名稱。

# 輸出
- 只輸出 requirement_candidates JSON object。
- requirement_candidates 每筆只包含 text。
- text 用中性需求描述，表達該利害關係人的目標、需求或限制。"""


# ========
# Defines requirement context rules function for this module workflow.
# ========
def requirement_context_rules() -> str:
    return """# Context Rules
- current_URL 是最新 User Requirements，也是正式 REQ 的主要來源。
- current_REQ 是既有正式需求；仍有效的 REQ 必須保留 id，只更新受來源或本議題決議影響的欄位。
- scope 只用來判斷需求是否屬於本系統範圍，不直接轉成 REQ。
- feedback 只作為領域背景、限制候選、風險與建議考量；可補充 rationale、risks、assumptions、constraint 判斷或 open question，不能單獨創造功能需求。
- feedback.recommendations 是建議考量，不是已確認需求、stakeholder statement 或實作指令；只有 current_URL、明確會議決議或人工直接編輯支持時，才可反映到 REQ。
- system_models 只作為流程、actor、資料、狀態與邊界參考；不能單獨創造 stakeholder 未支持的新需求。
- discussion 只使用明確表態、已回答問題、已收斂或人類裁決的內容。
- req_source_index 提供 source_id 到既有 REQ-* 的索引；請直接引用，不要逐筆 artifact_query 比對。"""


# ========
# Defines requirement formalization rules function for this module workflow.
# ========
def requirement_formalization_rules() -> str:
    return """# Formalization Rules
- 每筆 current_URL 必須被 REQ.source 覆蓋，或在 coverage 中標示 excluded、needs_clarification、risk 或 assumption。
- coverage.covered_by 只能引用本次輸出或既有 current_REQ 中的 REQ-*。
- coverage 是來源去向檢查，不是 REQ 粒度規則；不要因為每筆 URL 都要 coverage，就把每筆 URL 都轉成一筆 REQ。
- update 模式修正既有項目時必須保留該項 REQ-* id；create 模式不要自行編 id。
- remove_REQ 只能放已被合併到其他 REQ 的既有 REQ-*；不得移除未被 coverage 指向其他 REQ 的來源。
- 正式化前先把 current_URL 依「同一 stakeholder、同一使用目標、同一系統能力或同一限制/品質面向」分群；一個群組通常形成一筆 REQ。
- 多筆 URL 描述同一能力的不同情境、介面、通知內容、例外、驗收細節或補充條件時，必須合併成同一筆 REQ，並把所有來源 URL-* 放入該 REQ.source。
- 相近 URL 應合併成一筆 REQ；只有在 stakeholder 目標、系統行為、品質屬性或限制本體明顯不同，且可獨立驗收或追蹤時，才拆成不同 REQ。
- create 模式下，合理輸出通常少於 current_URL 筆數；若 REQ 數量接近 URL 數量，必須確認不是把來源逐條改寫。
- 只要 URL 能辨識 stakeholder、need/constraint 與目的或痛點，就應正式化為 REQ 或併入既有 REQ；不需要等待會議逐字確認。
- needs_clarification 只用於無法辨識系統行為、品質要求或限制本體的 URL；缺少驗收細節不是 needs_clarification 的充分理由。"""


# ========
# Defines requirement refinement rules function for this module workflow.
# ========
def requirement_refinement_rules(source_id: str) -> str:
    return f"""# Refinement Rules
- 修正既有項目時必須保留該項 REQ-* id。
- 只回傳本議題新增或需要更新的 REQ；未受本議題影響的既有 REQ 不要重複回傳。
- 除非會議已明確收斂出新的可追蹤需求，否則不要新增 REQ。
- 新增 REQ 必須有 current_URL 或明確會議決議支持，source 必須包含 URL-* 或 {source_id}。
- 不要因 current_URL 中還有未覆蓋來源，就在本次一般議題主動補齊全量 REQ。
- coverage 只回報本議題實際處理的 source；不要為未進入本議題的 URL 建立 coverage。
- cleanup 模式處理的是正式化後品質：同一能力、限制或品質面向被拆太細時要合併，不是逐條重寫全部 REQ。
- 合併既有 REQ 時，保留最能代表群組的一筆 id，把被合併 REQ 的 source、驗收條件、風險與假設整合進保留項，並將被合併 id 放入 remove_REQ。"""


# ========
# Defines requirement quality rules function for this module workflow.
# ========
def requirement_quality_rules() -> str:
    return """# Requirement Quality Rules
- source 是可追蹤來源 ID；優先使用 URL-*。若內容來自正式會議決議、feedback 或 system model，可加入 R*-M*、Feedback 或 SM-*。
- type 分類依本專案需求規則；不要重新定義 functional / non-functional / constraint。
- 每筆 REQ 只能表達一種主要性質：functional、non-functional 或 constraint。
- 若來源同時包含系統能力、品質要求與限制，且各自可獨立驗收或追蹤，請拆成多筆 REQ；不是因 URL 筆數拆分。
- 若品質或限制只是該功能的驗收條件，且不能獨立追蹤，可保留在 acceptance_criteria，不必拆。
- 若多個來源使用相同名詞、資料物件或功能名稱，但系統責任、業務目的、觸發情境、受影響使用者群體或完成邊界不同，應拆成不同 REQ；不得只因共同名詞而合併成泛化 description。
- 若多個來源描述的是相同系統責任、相同業務目的、相同主要使用者群體與相同可驗收結果，即使措辭不同，也應合併或更新同一筆 REQ；不得因來源句數不同而機械式拆成多筆。
- 明確且有來源支持的 non-functional 需求應直接寫入 type=non-functional，不要只因為它是 NFR 就留待會議。
- NFR 只有在 metric、validation、適用範圍或 FR/NFR priority 需要決策，或會造成品質/成本/設計/模型取捨時，才放入 open_questions、risks 或正式會議處理。
- title 是 brief description：用短詞概括需求核心，不寫完整句；title 應命名系統能力、限制、品質屬性或政策本體，不用利害關係人名稱作為開頭。
- 若需求只是在描述某利害關係人提出的目標，該資訊放在 description、source 或 trace，不放在 title 前綴。
- priority 只用於 functional 與 non-functional 需求，討論 FR/NFR 的實作、品質或版本優先順序；constraint 是限制或底線，不做 priority 取捨，也不要輸出 priority。
- functional / non-functional 的 priority 只使用 must、should、could；沒有足夠依據就省略。
- description 是正式需求敘述，應以系統可履行的行為、限制或品質要求撰寫。
- description 必須寫成可直接放入 SRS 的完整需求敘述；不得只寫功能名稱、短摘要、會議結論或「系統應提供...功能」這類空泛句。
- description 應在一段文字中交代：適用情境或觸發條件、主要使用者或受影響使用者群體、系統責任、必要資訊或處理內容，以及可驗證的完成邊界。若某項沒有來源支持，省略該項，不得臆測。
- description 應在來源支持範圍內盡可能具體完整；不得為了增加細節而加入來源未支持的功能、流程、資料欄位、使用者群體、權限、例外處理或驗收條件。
- description 說明系統責任與完成結果；具體可測試條件、輸入輸出檢查、狀態驗證、錯誤處理驗收方式應放入 acceptance_criteria，不要全部塞進 description。
- 若來源暗示某細節但不足以正式寫入 description，應將該細節寫入 assumptions、risks 或 open_questions，而不是在 description 中用模糊語氣包裝。
- functional description 應清楚描述系統在什麼情境下為誰完成什麼業務結果；例外處理、通知內容、資料揭露、狀態更新或權限邊界若有來源支持，應寫入同一段 description 或 acceptance_criteria。
- non-functional description 應清楚描述品質屬性、適用範圍與限制對象；可量測條件放入 metric，可執行驗證方式放入 validation，不要混在 description 中重複。
- constraint description 應清楚描述不可違反的政策、法規、資料邊界或系統限制；不寫 priority，也不要改寫成功能需求。
- acceptance_criteria 必須可驗收，不要只重述 description；若只有待確認條件，放入 risks、assumptions 或 open_questions。
- non-functional 可輸出 category、metric、validation：category 依 ISO/IEC 25010 且不用 functional suitability；metric 從 acceptance_criteria 或需求內容萃取可觀察條件；validation 寫成可執行方式。
- rationale 只寫為什麼需要此需求；risks 只寫可能失敗或不確定處；assumptions 只寫目前採用但尚未完全確認的前提。三者不得重複 description。
- 不確定、有爭議、超出範圍或需要裁決的內容，不要硬寫成 REQ；請放入 assumptions、risks、open_questions 或 coverage。
- coverage 只作內部檢查，不是正式需求內容；不要把 coverage reason 寫進 description、rationale、risks 或 assumptions。
- 有依據就填欄位；沒有依據就留空陣列或省略，不要臆測。"""


# ========
# Defines requirement coverage gap rules function for this module workflow.
# ========
def requirement_coverage_gap_rules(coverage_gaps=None) -> str:
    if not coverage_gaps:
        return ""
    return f"""# Coverage Gap Rules
- 上一輪仍有 {len(coverage_gaps)} 筆 User Requirements 沒有明確去處。
- 本輪只處理 coverage_gaps 中列出的 URL-*。
- 對每筆 gap 必須二選一：
  1. 併入既有 REQ 或新增 REQ，並讓該 URL-* 出現在 REQ.source。
  2. 若需求正式化討論已明確判斷該 URL-* 不需要、超出範圍或只能作為風險/假設，則在 coverage 標為 excluded、risk 或 assumption，並寫清楚 reason。
- 不要重寫已完整覆蓋的 REQ；只補缺口。
- 不要因缺少驗收條件、優先級、量化門檻或細節尚未完整，就把可辨識的需求標成 needs_clarification；先形成 REQ，將不確定內容放入 acceptance_criteria 空欄、assumptions、risks 或 open_questions。"""


# ========
# Defines requirement candidates output schema function for this module workflow.
# ========
def requirement_candidates_output_schema() -> str:
    return """# Output JSON
{
  "requirement_candidates": [
    {"text": "候選 User Requirement"}
  ]
}"""


# ========
# Defines requirement output schema function for this module workflow.
# ========
def requirement_output_schema(*, source_id: str, include_remove_req: bool) -> str:
    remove_req = (
        '\n  "remove_REQ": ["update 模式才可填；列出已被合併進其他 REQ 的舊 REQ-*"],'
        if include_remove_req
        else ""
    )
    return f"""# Output JSON
{{
  "requirement_update": {{
    "REQ": [
      {{
        "type": "functional | non-functional | constraint",
        "id": "既有 REQ-*；新增時省略或留空",
        "title": "短標題",
        "description": "系統應...",
        "priority": "functional / non-functional 才填 must | should | could；constraint 不填",
        "category": "non-functional 才填 ISO/IEC 25010 品質特性",
        "metric": "non-functional 才填從 acceptance_criteria 或需求內容萃取出的可觀察或可測量條件",
        "validation": "non-functional 才填依 Requirement Validation 判斷的可執行驗證方式",
        "source": ["URL-1", "{source_id}"],
        "acceptance_criteria": [],
        "rationale": "為何需要此需求",
        "dependencies": [],
        "risks": [],
        "assumptions": []
      }}
    ],{remove_req}
    "coverage": [
      {{
        "source_id": "URL-1 或 {source_id}",
        "status": "covered | needs_clarification | assumption | risk | excluded",
        "covered_by": ["REQ-1"],
        "reason": "為何已覆蓋或為何暫不能形成 REQ"
      }}
    ],
    "reason": "一句說明"
  }}
}}"""


# ========
analyst_elicitation = f"""{elicitation_context}

- 聚焦 User Requirement 是否能成立：使用者目標、使用價值、產出內容、成功標準與待確認缺口。
- 若需要提問，只提出最會影響需求文字、範圍或可驗證性的那一個問題。
- 若資訊足以支撐需求草稿，提出收束，不要為了分工硬問。"""


# ========
# Defines analyst elicitation action task function for this module workflow.
# ========
def analyst_elicitation_action_task(stop_phrase: str) -> str:
    return elicitation_action_task(stop_phrase)


# ========
# Defines analyst elicitation action rules function for this module workflow.
# ========
def analyst_elicitation_action_rules(stop_phrase: str) -> str:
    return f"""{elicitation_action_rules(stop_phrase)}
- target_stakeholders 優先選擇能說明需求目標、使用情境、成功標準或待確認缺口的 stakeholder。
- 問題應直接補足最關鍵的需求判斷缺口；不要只問一般動機。
- 不要詢問領域法規、系統狀態建模或技術流程細節；這些不屬於本 action 補問範圍。"""

issue_task = (
    "聚焦需求意圖、需求範圍、需求條目品質、驗收條件、"
    "來源追蹤與未決缺口。"
)
issue_rules = """- text 需說明：此議題對需求的相關、目前可確認的需求內容、仍不可寫入正式需求的缺口、以及建議的需求處理方式。
- 依據優先引用 requirement id、conflict id、stakeholder 觀點、既有討論或議題描述。
- 判斷重點是需求是否清楚、可驗收、可追蹤、範圍是否穩定、是否需要拆成功能需求、非功能需求、限制條件或保留為未決問題。
- 若提出需求修正，必須指出要改哪個欄位：需求文字、優先級、驗收條件或來源追蹤。
- 若資訊不足，請說明缺少哪個可寫入需求的必要訊號，而不是只說需要更多資訊。
- 若需要他人補資訊，才在 open_questions 中提出能直接支援需求修正的具體問題。
- open_questions 的 to 欄位只能用 participants 代號：user、analyst、expert、modeler；禁止用利害關係人名稱。
- 若建議新增或修改需求，請說明應落在需求、驗收條件或未決問題哪一類。"""
resolution_task = (
    "直接針對既有衝突報告中的解決選項與建議解法做取捨。"
)
resolution_rules = """- 不重新判斷 Conflict/Neutral，也不重新執行 conflict detection。
- 以衝突報告已提供的解決選項與建議解法為主要討論對象。
- text 需說明：哪些既有方案可採用、哪些需要調整、調整理由、以及會影響哪些需求或驗收條件。
- 必須把結論落到 URL 層級：在 stance.proposal.url_updates 輸出 keep / revise / remove；revise 必須給出改寫後 text。
- url_updates 不得把多筆 URL 串成一筆巨大需求；若需要語意整合，應保留 URL 粒度並在後續 REQ 中整合。
- 若會議內容已足以採用或調整某個 resolution，stance.state 填 ready_to_close，stance.proposal 填具體建議方案與 url_updates。
- 若缺少業務取捨、領域規則或模型影響判斷，stance.state 填 needs_more_discussion，stance.proposal 仍須填目前最合理的候選方案或可裁決選項；不要提出 open_questions。
- 若無法在會議中做出內容抉擇，stance.proposal 應整理可交由人類裁決的方案，而不是要求重新分析衝突或延長討論。"""
conflict_task = (
    "請逐筆再審查目前這批 Conflict/Neutral 項目，"
    "先根據 User Requirements（URL-*）原文獨立重判，並將重判結果填入 proposed_label。"
)
conflict_rules = f"""{review_contract}
- 先只根據 User Requirements（URL-*）原文獨立判斷 proposed_label；不要先順著既有標籤想理由。
- 本 action 只判斷需求語意與 SRS 邊界：判斷是否同一需求槽位、是否能原樣共同放入 SRS、是否需要合併、改寫、刪除或人工裁定。
- Conflict 不限於執行時互斥；若同一需求槽位的支援範圍、限制、條件、門檻、輸出、允許集合或驗收口徑不同，且 SRS 必須合併、改寫、選擇、刪除或交由人工裁定，proposed_label 應為 Conflict。
- 判斷骨架：
  1. 不同需求槽位且可並存：通常 Neutral。
  2. 同一需求槽位且改變支援集合、義務強度、門檻、輸出行為、允許/禁止範圍或驗收邊界：通常 Conflict。
  3. 若有明確共存條件：不同情境/例外、不同條件分支、限定試辦範圍、方法與必要配件/前置條件通常 Neutral。
  4. 資訊不足時維持 current_label 並說明缺哪個關鍵依據。
- 同一槽位中，標準/非標準、精確/半精確、即時/未限定、量化/未量化、一般/具體、子集/超集、不同 UI 輸出、不同授權層級、shall/must/should/may 等規範強度差異，支持 Conflict；不要用「可同時實作、可擴充、可合併、可澄清」改判 Neutral。
- 對同一事件要求不同輸出物名稱（box/dialog/list/message）、對同一資料集合要求 standard/non-standard、對同一能力要求 full/partial/semi 程度、對同一繼承來源要求 higher/other level、對同一支援範圍要求 named subset/all，視為需要 SRS 統一或裁定，支持 Conflict。
- 若 requirement 原文明確指定 display/output 形式，不要把 box/dialog/list/message 等差異降格為 implementation detail；同一事件的輸出形式差異支持 Conflict。
- standard/non-standard、named subset/all 即使表面上可同時支援，也代表支援集合邊界不同；不要用「broader includes subset」或「additive」改判 Neutral。
- 若其中一項只是用 including / such as / for example 舉例說明支援資料，不是 only/限定集合，與另一項 named subset/standard 通常可並存，支持 Neutral。
- 若兩句除了 shall/must/should/may 等規範助動詞外幾乎相同，仍視為規範強度不同，支持 Conflict，不是同義 Neutral。
- 同一既有流程中，一項要求 mimic/preserve/follow existing practice，另一項要求 improve/make practical/change the same process，視為流程保留程度不同，支持 Conflict；不要只因都能改善使用者體驗就支持 Neutral。
- 同一 capability 中 personalized 與 semi-personalized 是支援程度與驗收邊界差異，支持 Conflict。
- 同一品質或效率目標中，一般 improvement 與 quantified threshold 是驗收門檻差異，支持 Conflict。
- 互補 guard condition（例如條件成立時做 A、條件不成立時等待/做 B）、方法與必要設備/憑證/步驟、階層深度與成員資格限制、限定試辦範圍與一般規則，除非原文要求同一條件下只能二選一，否則支持 Neutral。
- 若一項需求限定在 pilot/trial/exception/special case，另一項沒有相同限定範圍，即使兩者方法不同，也支持 Neutral；只有兩者都明確落在同一限定範圍或同一條件下才支持 Conflict。
- 不要推定 pilot/trial/exception/special case 與一般規則必然重疊；除非兩句原文都明確指向同一限定範圍，否則支持 Neutral，即使方法不同或一般規則使用 only。
- 若一項是 only if/enough/unique/success 條件成立時的自動行為，另一項是 if not/not enough/not unique/failure 條件下的等待或人工選擇，這是互補 guard condition，支持 Neutral。
- 若一項描述結構能力（hierarchy/subclass/tree depth/creation），另一項描述成員資格、憑證、設備、PIN、reader 或其他前置條件，不是同一槽位，支持 Neutral；不要把 hierarchy depth 與 membership cardinality 合併成同一衝突。
- 「允許客製能力」與「降低/最小化客製程度」可作為能力與政策並存；除非兩者同時對同一設定寫出 only/禁止/不得，否則支持 Neutral，不要只因方向看似相反就判 Conflict。
- 具體能力（例如 creation of personalized templates）與廣義設計政策（例如 minimize individual customization / similar across practices）可並存；除非政策明確禁止該具體能力，支持 Neutral。
- user class 是否可替代或補充 security keys，與 user class 可定義在 hospital-wide/service scope，是用途限制與組織範圍，不是同一槽位，支持 Neutral。
- 一般 allow/support 某能力，與提供該能力的強化版本（例如 real-time、decision support、advanced support）通常是一般能力與細化能力，可並存；除非兩者都定義同一必須時效或互斥門檻，支持 Neutral。
- 若兩項都在同一敏感資料顯示槽位，但一項要求 authorized users 可見/顯示，另一項要求 only if not authorized 才顯示，屬於相反顯示條件，支持 Conflict。
- 可無損合併不是 Neutral 的充分理由；若合併前必須選擇某個詞、範圍、門檻、格式或規範強度，支持 Conflict。完全同義且不改變任何邊界才支持 Neutral。
- 不要只因兩項需求可同時實作、可設為選項、可合併、或其中一項較具體，就支持 Neutral；Neutral 必須指出明確的不同槽位、不同情境、互補條件或無損包含關係。
- reason 必須寫成完整審查意見：說明獨立判斷依據，並說明需求語意、範圍、條件、互斥點或可驗證性；不要只重述兩句需求文字。
{reason_rules}
- 需特別檢查：是否為同一需求槽位、重複／近似重複、細化、範圍重疊，或需要合併、改寫、刪除、人工裁定後才能放入軟體需求規格書。
- 若只是語意模糊、範圍未明、使用者群體不同、情境不同、優先級不同或仍需補充條件，不能因看不出衝突就直接支持 Neutral。
- 若支持 Conflict，必須清楚指出互斥點；若支持 Neutral，必須清楚說明為何既不衝突、也不重複，且無直接語義關係。
- 以兩層判斷收斂理由：先說是否同一需求槽位，再說同槽位差異是否改變驗收邊界或需要裁定。
- 不要處理外部法規/合規研究，也不要處理模型可共存性推論；若只能從那些角度判斷，維持 current_label 並說明非本職責範圍。
- 不要跳到實作方案或最終決策。"""
