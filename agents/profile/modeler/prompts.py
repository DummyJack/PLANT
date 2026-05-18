# Modeler prompt fragments shared across model generation and meeting responses.
import re

from agents.profile.elicitation_prompt import (
    COMMON_ELICITATION_CONTEXT_RULES,
    elicitation_action_rules,
    elicitation_action_task,
)

from agents.profile.conflict_review import (
    CONFLICT_REVIEW_LABEL_RULES,
    CONFLICT_REVIEW_REASON_RULES,
    CONFLICT_REVIEW_RESPONSE_CONTRACT,
)

UML_DIAGRAM_HEADINGS = {
    "context_diagram": "## Context Diagram",
    "use_case_diagram": "## Use Case Diagram",
    "activity_diagram": "## Activity Diagram",
    "sequence_diagram": "## Sequence Diagram",
    "state_machine": "## State Machine",
    "class_diagram": "## Class Diagram",
}


def markdown_section(content: str, heading: str) -> str:
    pattern = re.compile(
        rf"(^|\n)({re.escape(heading)}\n.*?)(?=\n## |\Z)",
        re.DOTALL,
    )
    match = pattern.search(content or "")
    return match.group(2).strip() if match else ""


def uml_skill_guidance(content: str, mode: str, diagram_type: str = "") -> str:
    mode_name = str(mode or "").strip()
    diagram_name = str(diagram_type or "").strip()
    common = [
        markdown_section(content, "## Overview"),
        markdown_section(content, "## MANDATORY: Evidence-First Approach"),
    ]
    if mode_name == "selection":
        sections = common + [
            markdown_section(content, "### Requirement-Level Diagrams"),
            markdown_section(content, "### Diagram Selection Guide"),
        ]
    elif mode_name == "use_case_text":
        sections = common + [
            markdown_section(content, "## Use Case Diagram"),
        ]
    elif mode_name == "repair":
        sections = [
            markdown_section(content, UML_DIAGRAM_HEADINGS.get(diagram_name, "")),
        ]
    else:
        sections = common + [
            markdown_section(content, UML_DIAGRAM_HEADINGS.get(diagram_name, "")),
        ]
    return "\n\n".join(section for section in sections if section)


def uml_skill_subset(skill: dict, mode: str, diagram_type: str = "") -> dict:
    content = str(skill.get("content") or "")
    guidance = uml_skill_guidance(content, mode, diagram_type)
    subset = dict(skill)
    subset["content"] = guidance or content
    subset.pop("content_user", None)
    subset.pop("reference_files", None)
    return subset


MODELER_ISSUE_TASK = (
    "輸出模型影響、元素邊界、待確認點與建議下一步。"
)

MODELER_ISSUE_RULES = """- text 需包含：結論、模型影響、元素邊界、建議下一步。
- 需明確指出受影響的模型元素、圖型或責任邊界，不要只講抽象原則。
- 若資訊不足，說明需補哪些角色互動、事件流程、資料輸入/輸出、資料物件、狀態或例外邊界，不可臆測。
- 可提到使用案例圖、類別圖或循序圖的具體影響。
- 若需要他人補資訊，再在 open_questions 提具體問題。
- 可用純文字表格或流程輔助；若使用，請放在程式碼區塊。"""


MODELER_CONFLICT_ISSUE_TASK = (
    "請逐筆再審查目前這批 Conflict/Neutral 項目，"
    "先根據 requirements 原文獨立重判，並將重判結果填入 proposed_label。"
)

MODELER_CONFLICT_ISSUE_RULES = f"""{CONFLICT_REVIEW_RESPONSE_CONTRACT}
- 使用建模觀點判斷，不需要真的產生圖。
- reason 必須寫成完整審查意見：說明你的獨立判斷依據，並至少指出資料結構、狀態轉移、事件流程、責任邊界、使用案例圖／類別圖／循序圖影響中的一種；不要只寫一般語義判斷。
- 任務不是提出新需求，而是再審查目前的 Conflict/Neutral 標籤是否合理。
{CONFLICT_REVIEW_LABEL_RULES}
{CONFLICT_REVIEW_REASON_RULES}
- 需特別檢查：同一角色、物件、關係、觸發條件、狀態、輸出或多重度是否被重複、細化或用不同限制描述，導致模型需要合併、改寫或裁定。
- 若支持 Conflict，必須指出模型層的互斥點，或說明為何模型元素、流程、狀態或責任邊界需要合併、改寫或裁定。
- 不要跳到技術實作細節。"""


MODELER_ELICITATION_CONTEXT_RULES = f"""{COMMON_ELICITATION_CONTEXT_RULES}

# Modeler 角度
- 聚焦使用者實際流程：怎麼開始、輸入、選擇、產生、查看結果、判斷任務完成，以及流程中的判斷點、例外情況與人工介入。
- 請用 user 能回答的需求訪談語言，不要要求使用者理解 UML、類別、狀態機或技術實作。
- 不要追問一般動機、商業價值或優先級；除非它會直接改變操作流程、角色互動、輸入/輸出、狀態、例外或人工介入。
- 前半段請先補足主要使用流程，不要把會議變成流程細節審查；只有當細節會直接改變主要流程、任務完成方式或需求成立性時才追問。
- 若本輪已有前面發言，請先判斷前面問題是否已覆蓋模型關注點；若已覆蓋，不要換句話重問，請提出更精準的下一層追問，或在資訊足夠時提出收束。
- 若目前流程、操作與例外理解已足夠，可以提出收束。"""


def modeler_elicitation_action_task(stop_phrase: str) -> str:
    return elicitation_action_task(stop_phrase)


def modeler_elicitation_action_rules(stop_phrase: str) -> str:
    return f"""{elicitation_action_rules(stop_phrase)}
- target_stakeholders 優先選擇最清楚實際操作流程、交接、例外處理、狀態判斷或人工介入的 stakeholder。
- 問題必須可回答、可抽取；回答後應能支援需求修正，或角色、工作流程、資料輸入/輸出、狀態、例外邊界修正。
- 問題應以 probe 為主，直接詢問利害關係人的使用步驟、輸入/輸出、角色互動、判斷點、例外流程、狀態變化或人工介入；避免用「目前不清楚 / it is unclear / could you clarify」作為主要問法。
- 不要重複 analyst 的需求目標/成功標準問題，也不要重複 expert 的限制/風險問題；你的問題應讓流程、互動或邊界更清楚。
- 提問前必須避開 `closed_issues` 與 `do_not_repeat`；不要重問利害關係人已回答、已說不在意、或已表示 covered 的流程/互動方向。
- 避免使用「還有什麼需求」「請多說一點」等泛問。
- 提問應承接目前理解，避免孤立訪談題。
- 若問題得到回答，應能直接支援需求修正或模型邊界修正。"""
