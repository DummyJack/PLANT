# Defines action usage timing and output rules.
from agents.profile.base import (
    elicitation_action_rules,
    elicitation_action_task,
    elicitation_context,
    reason_rules,
    review_contract,
)

# ========
# Defines tool usage policy function for this module workflow.
# ========
def tool_usage_policy() -> str:
    return """- artifact_query 用於查詢需求、scope、feedback、open_questions 與既有 models。
- 若議題、trace、source 或前文出現 URL-*、REQ-*、SM-*、CR-*，優先用 artifact_query mode=related_context, item_id=<id>, compact=true 取得關聯脈絡；需要整體模型清單時才用 get_section。
- plantuml_validate 用於驗證或修正 PlantUML 語法；驗證通過不代表需求內容已被正式決策。
- 模型必須以 User Requirements（URL-*）與目前 scope 為主。
- feedback 只能作為邊界、限制、風險或不確定性提示，不可被轉成新的 actor、use case、class、state 或流程步驟。
- 資訊不足時不要硬畫未確認元素，不可用圖反推新增需求。"""


# ========
# Defines use case text output rules function for this module workflow.
# ========
def use_case_text_rules() -> str:
    return """- 只能整理圖中已出現的 actor 與 use case；不要補入圖中沒有的 use case。
- related_requirement_ids 只能引用輸入中存在的 REQ-* 或 URL-*。
- interface 必須寫成此 use case 會使用到的頁面、畫面、後台模組或外部整合介面清單。
- interface 必須使用具體頁面、畫面、後台模組或外部整合介面名稱，不使用泛稱。
- interface 不可只寫「平台前台」、「平台後台」、「App」、「Web」、「App或Web」、「管理後台」這類泛稱。
- interface 不要寫成「使用者端－某功能入口」；應列出使用者會看到或系統會經過的具體頁面與介面。
- 若圖中未明確指定 UI，請依 actor 與 use case 名稱整理成需求層級頁面清單，不臆測按鈕或欄位細節。"""


# ========
# Defines model input boundary rules function for this module workflow.
# ========
def model_input_boundary_rules() -> str:
    return """# Project Boundary
- 只根據輸入中的需求與已接受脈絡建模。
- feedback 只作為邊界、限制、風險或未決事項參考，不可畫成已確認元素。
- related_requirement_ids 只能引用輸入中存在的 REQ-*；沒有 REQ 時才可用 URL-*。
- PlantUML 語法、diagram type 與 JSON key 維持英文；不要把語法關鍵字翻成中文。"""


# ========
# Defines model language rules function for this module workflow.
# ========
def model_language_rules() -> str:
    return """# Diagram Language Rules
- 圖中業務元素、狀態、關聯標籤使用目前輸出語系；若需求文件是繁體中文，圖中業務文字使用繁體中文。
- class_diagram 的 class 與 enum 名稱使用目前輸出語系；若需求文件是繁體中文，class 與 enum 名稱可使用繁體中文。
- class_diagram 的 attribute 名稱、attribute type、association label 與 enum value 固定使用英文，以維持資料模型欄位、型別引用、關聯語意與狀態值穩定。
- PlantUML 語法關鍵字與型別標註仍維持 PlantUML 可解析格式；不要把 class、enum、String、DateTime、Boolean 等語法或型別關鍵字翻成中文。"""


# ========
# Defines model create rules function for this module workflow.
# ========
def model_create_rules() -> str:
    return """# Create Model Rules
- 根據需求輸入建立新的需求層級模型。
- 資訊不足時保留抽象元素，不要臆測補入未被需求支持的 actor、class、state、message 或流程。"""


# ========
# Defines model update rules function for this module workflow.
# ========
def model_update_rules() -> str:
    return """# Update Model Rules
- 以上一版 PlantUML 為基礎，只修改受本次需求輸入或修訂脈絡影響的元素。
- 保留未受影響且仍有效的 actor、use case、流程、資料、狀態或概念。
- 不要因格式整理而改變原圖需求語意。"""


# ========
# Defines model output schema function for this module workflow.
# ========
def model_output_schema(*, diagram_type: str, description_field: str) -> str:
    return f"""# Output JSON
{{"name": "簡短直觀的模型名稱", "type": "{diagram_type}", "plantuml": "@startuml\\n...\\n@enduml", "related_requirement_ids": ["REQ-1"]{description_field}}}"""


# ========
# Defines model layout hint function for this module workflow.
# ========
def model_layout_hint(diagram_type: str) -> str:
    hints = {
        "context_diagram": """
本專案限制：context_diagram 對外作為「情境圖」，呈現系統邊界與高層互動，不是功能分解圖、流程圖、使用案例圖或內部元件圖。
圖中心只能是本系統；外圍只能放 context.stakeholders 中已選擇的利害關係人作為 actor，不得新增未被選擇的利害關係人、外部組織或 external system。
線條只標示主要資料流、事件流、請求/回應、通知或責任邊界；不要畫詳細操作步驟、流程分支、use case、資料表、service、database、controller 或內部模組。
情境圖必須保持為 overview；若需要說明例外流程、狀態、資料結構或多方順序，請改由 activity_diagram、state_machine、class_diagram 或 sequence_diagram 承擔，不要塞進 context_diagram。
不可把 provider/API、第三方服務、外部系統、外部資料來源、監管/社區/金融/身分驗證服務畫成情境圖節點；即使 requirements 提到它們，也只能放在線條標籤、description 的限制說明或其他 detail 圖中，除非它們已被使用者選為 stakeholders。
同一個外部 actor 只能畫一次；若多筆需求都指向同一 actor，必須合併成同一個 actor，並把多個互動合併到同一條或同一組關係標籤。不得因來源需求不同而重複畫出同名或同義 actor。
actor 命名必須使用穩定的利害關係人名稱；同一 actor 只能出現一次，不要拆成多個同義 actor。
若需求只改變流程步驟、例外條件、驗收標準、外部服務細節或功能細節，而沒有改變已選 stakeholders、主要資料/事件流或責任邊界，不應更新 context_diagram。""",
        "use_case_diagram": """
版面要求：actor 與 use case 的關聯要一目了然；若單圖連線過多，可精簡為核心用例或依 actor 拆分。
use_case_diagram 只呈現 actor 可以使用哪些系統能力，不要把流程步驟、例外判斷、狀態轉移、資料欄位或驗收條件畫進用例圖。
include/extend 只在需求明確表示必要共用行為或可選擴充行為時使用；不要為了連接所有需求而大量加入 include/extend。
同一個 actor 或 use case 只能畫一次；若多筆需求指向同一使用者任務或同一 actor，必須合併成同一元素，不得因來源需求不同而重複畫出同名或同義元素。""",
        "activity_diagram": """
本專案限制：不要放入技術實作步驟。
一張 activity_diagram 只聚焦一個主要工作流程或例外流程；若同時涵蓋多個不相關流程，請拆成多張聚焦圖。
相同語意的活動節點只畫一次；若多筆需求描述同一操作、判斷或狀態更新，請合併成同一流程節點，不要重複畫同義步驟。""",
        "class_diagram": """
本專案限制：只作為需求層級 domain model；避免加入未確認的 service、database、API 或實作類別。
class_diagram 可以較複雜，但每個 class、attribute、enum 或 association 都必須能說明需求中的資料、責任、權限、紀錄保存或追蹤關係；不要做成實作資料庫 schema。
圖的標題與說明使用目前輸出語系；PlantUML 圖內 class 與 enum 名稱也可使用目前輸出語系。
class 與 enum 名稱使用穩定的需求領域名詞，例如「異常事件」、「通知紀錄」、「補償狀態」。
attribute 名稱固定使用英文 camelCase，attribute type 也固定使用英文或技術型別，例如 `orderId: UUID`、`sentAt: DateTime`、`isBackupChannel: Boolean`、`status: ExceptionStatus`；即使 enum 顯示名稱使用中文，attribute type 仍不得寫成中文。
enum value 固定使用英文 PascalCase，例如 `Reported`、`Notified`、`InProcess`。
association label 固定使用簡短英文動詞或名詞，例如 `generates`、`triggers`、`requires`。
可包含少量需求層級 operation，但只放 register()、login()、updateMenu()、submitComplaint() 這類明確系統能力；不要加入 controller/service/repository/API/database 操作。
不要列出所有欄位；只保留對需求可驗證性、責任歸屬、追蹤或合規有意義的屬性。
可使用常見需求層級型別：UUID、String、Int、Decimal、Date、DateTime、Boolean、List<T>、enum type。
同一個 domain concept 只能畫一次；若多筆需求指向同一資料物件、業務概念或 actor concept，必須合併成同一 class，不得重複畫同名或同義 class。""",
        "sequence_diagram": """
本專案限制：一張圖聚焦一個主要情境流程；lifeline 使用需求層級 actor/系統，不要放入低階 service/database 實作。
sequence_diagram 只描述一個互動情境的訊息順序；不要同時塞入多個不相關流程，也不要把資料結構或狀態機畫成訊息序列。
同一個參與者、系統或外部服務只能有一條 lifeline；若多筆需求指向同一參與者，必須合併成同一 participant，不得重複畫同名或同義 lifeline。""",
        "state_machine": """
本專案限制：若狀態不明確，不要硬畫。
state_machine 只描述一個業務物件的生命週期；不要把一般流程步驟硬改成狀態。
同一個業務狀態只能畫一次；若多筆需求描述同一狀態，必須合併成同一 state，不得因不同轉移來源重複畫同名或同義 state。""",
    }
    return hints.get(str(diagram_type or "").strip(), "")


# ========
# Defines model description contract function for this module workflow.
# ========
def model_description_contract(diagram_type: str) -> tuple[str, str]:
    diagram_type = str(diagram_type or "").strip()
    if diagram_type == "context_diagram":
        return (
            """
- description 只輸出一段簡短說明，說明這張情境圖用來釐清什麼系統邊界、已選利害關係人、主要互動或責任邊界。
- 不要使用 **用途**、**反映需求**、**讀圖重點** 或 **限制** 標題。
- description 只能描述圖中已呈現的內容，不得加入新需求。""",
            ', "description": "此情境圖用來釐清..."',
        )
    if diagram_type == "use_case_diagram":
        return (
            """
- description 只輸出一段簡短說明，說明這張 use case diagram 用來釐清哪些 actor 與系統能力。
- SRS 不會輸出此 description，會改用文字用例；但本欄仍需保留給模型紀錄。
- description 只能描述圖中已呈現的內容，不得加入新需求。""",
            ', "description": "此用例圖用來釐清..."',
        )
    return (
        """
- description 必須用兩段固定格式輸出，段落名稱依序為 **用途**、**反映需求**。
- **用途**：說明這張圖用來釐清哪一個需求面向。
- **反映需求**：說明此圖支撐哪些需求面向或已存在的 REQ-* / FR-*；只能使用已存在的需求 ID 或需求面向，不得虛構。
- description 只能描述圖中已呈現的內容，不得加入新需求；不要輸出 **讀圖重點** 或 **限制**。""",
        ', "description": "**用途**：...\\n**反映需求**：..."',
    )


issue_task = (
    "輸出模型影響、元素邊界、待確認點與建議下一步。"
)
issue_rules = """- text 需包含：結論、模型影響、元素邊界、建議下一步。
- 需明確指出受影響的模型元素、圖型或責任邊界，不要只講抽象原則。
- 若資訊不足，說明需補哪些參與者互動、事件流程、資料輸入/輸出、資料物件、狀態或例外邊界，不可臆測。
- 可提到使用案例圖、類別圖或循序圖的具體影響。
- 若需要他人補資訊，再在 open_questions 提具體問題。
- 可用純文字表格或流程輔助；若使用，請放在程式碼區塊。"""
conflict_task = (
    "請逐筆再審查目前這批 Conflict/Neutral 項目，"
    "從模型可共存性角度根據 User Requirements（URL-*）原文審查，"
    "並依本 action 判斷範圍填入 proposed_label。"
)
conflict_rules = f"""{review_contract}
- 使用建模觀點判斷，不需要真的產生圖。
- reason 必須寫成完整審查意見：說明獨立判斷依據，並至少指出資料結構、狀態轉移、事件流程、責任邊界、使用案例圖／類別圖／循序圖影響中的一種；不要只寫一般語義判斷。
- 任務不是提出新需求，而是從模型可共存性再審查目前的 Conflict/Neutral 標籤是否合理。
- 本 action 只判斷：流程節點、狀態、資料物件、參與者互動、責任邊界、模型多重度、事件順序或模型元素是否可同時表示。
- 若兩項需求是互補條件分支、不同流程階段、不同上下文、不同模型元素，或模型上可同時表示，支持 Neutral。
- 「模型上可同時表示、可新增設定、可做成選項」本身不足以把 requirement-level Conflict 改判為 Neutral；只有原文已有明確互補條件、不同上下文、不同模型元素，或一者是另一者必要組成時，才支持 Neutral。
- 若兩項需求對同一模型元素施加不同且不可同時成立的狀態、流程、資料、參與者互動、責任邊界或多重度，支持 Conflict。
- 方法與必要配件、憑證、前置條件或操作步驟通常是同一流程的組成關係，不是模型衝突；例如某方法與其必要配件、憑證或驗證步驟可共存，除非原文明確寫 only / without / 不允許其他條件。
- 唯一識別成功時自動選取，與無法唯一識別時等待使用者手動選取，是互補條件分支；模型上可用 guard condition 表示，支持 Neutral。
- pilot/trial/exception/special case 與沒有相同限定範圍的一般規則，應建模為範圍限定或例外分支；即使方法不同也支持 Neutral。只有兩者都明確落在同一限定範圍或同一條件下，才可支持 Conflict。
- 不要從「可能同時適用」推定 pilot/trial/exception/special case 與一般規則重疊；模型審查只在原文明確同條件時支持 Conflict。
- general/default rule 與明確 exception、override 或優先規則通常可建模為條件分支或優先順序，不是模型衝突；只有兩者在同一條件與同一優先層級要求不同狀態或不同轉移時，才支持 Conflict。
- 時間、保存、有效期或觸發門檻若形成互斥邊界（例如同一資料同時要求最多 N 與超過 N 後才觸發下一步），會影響同一狀態轉移或 guard condition，支持 Conflict。
- 階層深度、子類別建立能力、分類樹結構，和單一成員資格/單一所屬類別是不同模型約束；除非兩者明確約束同一 association 的 multiplicity，支持 Neutral，不要把 hierarchy depth 與 membership cardinality 合併成同一衝突。
- 允許建立客製化項目，與降低或最小化客製化程度，可建模為能力與政策/預設限制並存；除非同一模型元素同時要求允許與禁止同一操作，支持 Neutral。
- 具體客製化能力與廣義最小化客製政策可建模為 capability 加 default/policy guard；除非原文明確禁止該 capability，支持 Neutral。
- 一般能力與該能力的強化版本可建模為 general use case 加 extension 或 quality guard；除非兩者明確定義互斥 guard condition，支持 Neutral。
- 同一敏感資料顯示事件若一項針對 authorized users，另一項針對 not authorized users 且使用 only if，這是相反 guard condition，支持 Conflict。
- 若只是 SRS 措辭、規範強度、需求槽位整理、一般/具體文字差異，且沒有模型元素差異，proposed_label 必須維持 current_label，不要做需求文字裁定。
{reason_rules}
- reason 必須說清楚：兩項需求是否落在同一模型元素；若不是，為何可共存；若是，哪個模型層條件不可同時成立。
- 不要跳到技術實作細節。"""
resolution_task = (
    "從系統模型、流程、狀態、資料與責任邊界角度，討論既有 conflict resolution 是否可採用或需要調整。"
)
resolution_rules = """- 直接針對衝突報告中既有解決選項與建議解法做取捨。
- 不重新判斷 Conflict/Neutral，也不重新執行 conflict detection。
- text 需說明：哪個既有方案對模型最一致、是否需要調整流程/狀態/資料/責任邊界、以及可能影響哪些模型。
- 若資訊足以支持採用或調整某個 resolution，stance.state 填 ready_to_close，stance.proposal 填具體模型/需求邊界建議。
- 若缺少關鍵流程、狀態、資料物件或責任邊界，stance.state 填 needs_more_discussion，stance.proposal 仍須填目前最合理的候選方案或可裁決選項；不要提出 open_questions。
- 若無法在會議內判斷，stance.proposal 應整理可交由人類裁決的模型影響取捨，不要求延長討論。"""
modeler_elicitation = f"""{elicitation_context}

- 聚焦使用者實際流程：怎麼開始、輸入、選擇、產生、查看結果、判斷任務完成，以及流程中的判斷點、例外情況與人工介入。
- 請用 user 能回答的需求訪談語言，不要要求使用者理解 UML、類別、狀態機或技術實作。
- 若需要提問，只提出最會影響流程、參與者互動、輸入/輸出、狀態或例外邊界的那一個問題。
- 若目前流程、操作與例外理解已足夠，提出收束，不要為了模型細節硬問。"""

# ========
# Defines elicitation task function for this module workflow.
# ========
def elicitation_task(stop_phrase: str) -> str:
    return elicitation_action_task(stop_phrase)

# ========
# Defines elicitation rules function for this module workflow.
# ========
def elicitation_rules(stop_phrase: str) -> str:
    return f"""{elicitation_action_rules(stop_phrase)}
- target_stakeholders 優先選擇最清楚實際操作流程、交接、例外處理、狀態判斷或人工介入的 stakeholder。
- 問題應聚焦流程節點、狀態轉移、actor 責任、資料輸入輸出、例外流程或人工介入。
- 不要詢問一般需求優先級、領域法規或風險底線；這些不屬於本 action 補問範圍。
- 提問前必須避開 `closed_issues` 與 `do_not_repeat`；不要重問利害關係人已回答、已說不在意、或已表示 covered 的流程/互動方向。
- 避免使用「還有什麼需求」「請多說一點」等泛問。
- 問題應承接目前理解，避免孤立訪談題。"""
