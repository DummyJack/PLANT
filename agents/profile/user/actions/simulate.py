# Defines action prompts and output contracts.


# ========
# Defines suggest candidates function for this module workflow.
# ========
def suggest_stakeholders(*, scenario_context: str) -> str:
    return f"""# 任務
根據以下初始產品描述，建議真正會影響需求分析的利害關係人，並依 type 分類。

# Action Boundary
- action=user.suggest_stakeholders
- 本 action 根據初始產品描述產生 proposed_stakeholders JSON。
- proposed_stakeholders 用來建立需求擷取會議的 stakeholder 視角。

# 初始產品描述
{scenario_context}

# Type
- primary_user：直接操作系統、輸入資料、接收通知、完成任務或接受服務的人。
- system_owner：負責營運、管理、權限、資料品質、風險、穩定性、安全或維護的人。
- external_party：外部合作、依賴、監管、金流、物流、稽核、契約或其他受影響單位。

# Selection Rules
- 選擇標準是需求視角不同，不是為了湊 type。
- 每位利害關係人必須能從初始產品描述合理推出，且會影響需求、限制、責任邊界、驗收、風險或決策。
- 若兩者的需求目標、日常情境、責任、風險與驗收觀點幾乎相同，合併。
- 同一 type 內若有不同需求、限制、責任邊界或驗收觀點，可以保留多位。
- 一般輸出 5 位左右；多方平台、交易平台或營運流程複雜的產品可輸出 6-9 位。
- 若初始產品描述很小或資訊不足，可以少於 4 位，但 reason 必須說明原因。
- name 只填名稱，不要用括號補充說明。
- type 只能是 primary_user、system_owner、external_party。
- reason 用一句話說明此利害關係人帶來哪種不同的需求、限制、責任邊界、驗收、風險或決策觀點。

# Output JSON
{{
    "proposed_stakeholders": [
        {{"name": "利害關係人名稱", "type": "primary_user | system_owner | external_party", "reason": "一句話選擇理由"}}
    ]
}}"""


# ========
# Defines write stakeholder text function for this module workflow.
# ========
def write_stakeholder_text(
    *,
    stakeholder_list: str,
    scenario_context: str,
) -> str:
    return f"""# 任務
模擬以下利害關係人，以第一人稱、口語方式從各自角度提出需求。

# Action Boundary
- action=user.write_stakeholder_text
- 本 action 為每位 stakeholder 產生第一人稱需求發言 JSON。
- text 會作為後續 User Requirements 抽取來源。

# 利害關係人
{stakeholder_list}

# 初始產品描述
{scenario_context}

1. 日常使用情境
2. 痛點與困擾
3. 期望功能
4. 擔心的事
5. 最在意的限制、底線或不可接受情況
6. 與其他角色可能產生取捨的地方

- 每位利害關係人產生 3-5 條 text。
- 只根據該利害關係人的日常經驗。
- 每條 text 都必須能回扣初始產品描述。
- 請自然描述該角色的目標、擔憂、限制、底線與可接受/不可接受的取捨。
- 只有在初始產品描述中合理時，才描述可能與其他角色目標拉扯的地方。

# Output JSON
{{
    "stakeholders": [
        {{
            "name": "利害關係人名稱",
            "text": ["第一人稱需求發言"]
        }}
    ]
}}"""


def revise_stakeholder_text(
    *,
    current_stakeholders_text: str,
    feedback_text: str,
    scenario_context: str,
) -> str:
    return f"""# 任務
根據人類審查建議，修正既有利害關係人發言。

# Action Boundary
- action=user.revise_stakeholder_text
- 本 action 根據人類審查建議修正 stakeholders JSON。
- stakeholders 保留既有 name，更新相關 text。

# 初始產品描述
{scenario_context}

# 目前利害關係人發言
{current_stakeholders_text}

# 人類審查建議
{feedback_text}

- 保留原有利害關係人 name，不要新增、刪除或改名。
- 只調整與建議相關的內容；沒有被建議影響的發言應盡量保留。
- 不要把同一條人類建議逐句附加到每一個 text，也不要在每句結尾重複補上相同方向。
- 若一條建議影響多個發言，請選擇最相關的 1-2 條整合；必要時可合併或替換原句，而不是全面追加。
- 修正後每位利害關係人的 text 數量應盡量接近原本數量；除非建議明確指出缺漏，否則不要大量新增句子。
- 每位利害關係人仍需維持第一人稱、口語、符合其角色視角。
- 每條 text 必須能回扣初始產品描述。
- 若建議與初始產品描述或角色視角不相符，請只採用合理部分。

# Output JSON
{{
    "stakeholders": [
        {{
            "name": "利害關係人名稱",
            "text": ["修正後的第一人稱需求發言"]
        }}
    ]
}}"""
