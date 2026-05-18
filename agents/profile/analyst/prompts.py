# Analyst prompt fragments shared across requirement analysis, issues, and conflicts.
import re

from agents.profile.elicitation_prompt import (
    COMMON_ELICITATION_CONTEXT_RULES,
    elicitation_action_rules,
    elicitation_action_task,
)


def markdown_section(content: str, heading: str) -> str:
    pattern = re.compile(
        rf"(^|\n)({re.escape(heading)}\n.*?)(?=\n### |\n## |\Z)",
        re.DOTALL,
    )
    match = pattern.search(content or "")
    return match.group(2).strip() if match else ""


def markdown_between(content: str, start: str, end: str) -> str:
    source = content or ""
    start_index = source.find(start)
    if start_index < 0:
        return ""
    end_index = source.find(end, start_index + len(start))
    if end_index < 0:
        end_index = len(source)
    return source[start_index:end_index].strip()


def markdown_from_heading_until(content: str, starts: list[str], stops: list[str]) -> str:
    source = content or ""
    start_index = -1
    for heading in starts:
        found = source.find(heading)
        if found >= 0 and (start_index < 0 or found < start_index):
            start_index = found
    if start_index < 0:
        return ""
    end_index = len(source)
    for marker in stops:
        found = source.find(marker, start_index + 1)
        if found >= 0 and found < end_index:
            end_index = found
    return source[start_index:end_index].strip()


def smart_user_requirement_guidance(content: str) -> str:
    smart_section = markdown_between(
        content,
        "**SMART Requirements:**",
        "**Completeness Checklist:**",
    )
    if not smart_section:
        return ""
    selected = []
    for label in ("Specific", "Relevant"):
        match = re.search(
            rf"({label}:\n(?:  - .+\n?)+)",
            smart_section,
            re.MULTILINE,
        )
        if match:
            selected.append(match.group(1).strip())
    if not selected:
        return ""
    return "**SMART Requirements:**\n```yaml\n" + "\n\n".join(selected) + "\n```"


def user_story_guidance(content: str) -> str:
    story_block = markdown_between(
        content,
        "**Universal User Story Format:**",
        "Acceptance Criteria:",
    ).strip()
    if not story_block:
        return ""
    if not story_block.endswith("```"):
        story_block = story_block.rstrip()
        if story_block.endswith("```yaml"):
            return story_block
        story_block += "\n```"
    return story_block


def requirements_skill_guidance(content: str, mode: str) -> str:
    mode_name = str(mode or "").strip()
    if mode_name == "analysis":
        selected = [
            user_story_guidance(content),
            markdown_section(content, "### 3. Priority Frameworks"),
            smart_user_requirement_guidance(content),
        ]
        return "\n\n".join(section for section in selected if section)

    headings_by_mode = {
        "draft": [
            "### Step 4: Documentation",
            "### Requirement Specification Document",
            "### 4. Requirement Quality Criteria",
        ],
    }
    sections = [
        markdown_section(content, heading)
        for heading in headings_by_mode.get(mode_name, [])
    ]
    selected = [section for section in sections if section]
    return "\n\n".join(selected)


def user_requirement_extraction_contract() -> str:
    return """# 輸出契約
- 只輸出 JSON array。
- 每筆只包含 text、priority。
- text 以利害關係人能做什麼或需要什麼來表達。
- text 不要寫成系統功能規格。
- priority 只能是 must、should 或 could；不收錄的項目不要輸出。
- 不要輸出其他欄位。"""


CONFLICT_ANALYSIS_HEADINGS = [
    "### Step 2: Systematic Conflict Detection",
    "## Common Pitfalls to Avoid",
]

CONFLICT_RESOLUTION_STRATEGIES = {
    "logical": ["Prioritization", "Conditional Logic", "Stakeholder Negotiation"],
    "technical": ["Technical Solution", "Decomposition", "Scope Adjustment"],
    "resource": ["Prioritization", "Sequencing", "Parallel Tracks"],
    "temporal": ["Sequencing", "Relaxation", "Scope Adjustment"],
    "data": ["Technical Solution", "Conditional Logic", "Decomposition"],
    "state": ["Decomposition", "Conditional Logic", "Technical Solution"],
    "priority": ["Stakeholder Negotiation", "Prioritization", "Compromise"],
    "scope": ["Scope Adjustment", "Prioritization", "Sequencing"],
}


def resolution_reference_guidance(content: str, conflict_type: str) -> str:
    conflict_type = str(conflict_type or "").strip().lower()
    if conflict_type == "other":
        return ""
    strategies = CONFLICT_RESOLUTION_STRATEGIES.get(conflict_type, [])
    if not strategies:
        return ""
    selected = [markdown_section(content, "## Resolution Framework")]
    for strategy in strategies:
        pattern = re.compile(
            rf"(^|\n)(### \d+\. {re.escape(strategy)}\n.*?)(?=\n### \d+\. |\n## |\Z)",
            re.DOTALL,
        )
        match = pattern.search(content or "")
        if match:
            selected.append(match.group(2).strip())
    return "\n\n".join(section for section in selected if section)


def conflict_skill_guidance(content: str, mode: str) -> str:
    mode_name = str(mode or "").strip()
    base_mode, _, mode_detail = mode_name.partition(":")
    if base_mode == "report":
        report_guidance = markdown_from_heading_until(
            content,
            [
                "### Step 7: Create Conflict Report",
                "### Step 4: Create Conflict Report",
                "### Create Conflict Report",
            ],
            ["\n## Output Formats", "\n## Best Practices"],
        )
        return re.sub(
            r"\n## Recommendations\n.*?(?=\n```|\Z)",
            "",
            report_guidance,
            flags=re.DOTALL,
        ).strip()
    if base_mode == "resolution":
        resolution_guidance = markdown_from_heading_until(
            content,
            [
                "### Step 3: Recommend Resolution Strategies",
                "### Recommend Resolution Strategies",
            ],
            ["\n### Step 4:", "\n## Output Formats", "\n## Best Practices"],
        )
        resolution_guidance = re.sub(
            r"\n\d+\.\s+\*\*Implementation effort\*\*.*",
            "",
            resolution_guidance,
        )
        resolution_guidance = re.sub(
            r"\n- Effort:.*",
            "",
            resolution_guidance,
        )
        resolution_guidance = resolution_guidance.strip()
        if mode_detail == "other":
            return ""
        return resolution_guidance
    headings = CONFLICT_ANALYSIS_HEADINGS
    selected = [markdown_section(content, heading) for heading in headings]
    return "\n\n".join(section for section in selected if section)


def conflict_skill_subset(skill: dict, mode: str) -> dict:
    mode_name = str(mode or "").strip()
    base_mode, _, mode_detail = mode_name.partition(":")
    content = str(skill.get("content") or "")
    guidance = conflict_skill_guidance(content, mode_name)
    subset = dict(skill)
    subset["content"] = guidance if base_mode == "resolution" else (guidance or content)
    subset.pop("content_user", None)
    reference_files = skill.get("reference_files") or {}
    if base_mode == "report":
        keep = set()
    elif base_mode == "resolution":
        keep = {"resolution_strategies.md"}
    else:
        keep = {"conflict_patterns.md"}
    subset_refs = {}
    for name, value in reference_files.items():
        if name not in keep:
            continue
        if base_mode == "resolution" and name == "resolution_strategies.md":
            sliced = resolution_reference_guidance(value, mode_detail)
            if sliced:
                subset_refs[name] = sliced
            continue
        subset_refs[name] = value
    subset["reference_files"] = subset_refs
    return subset


ANALYST_ELICITATION_CONTEXT_RULES = f"""{COMMON_ELICITATION_CONTEXT_RULES}

# Analyst 角度
- 聚焦 User Requirement 是否能成立：使用者目標、使用價值、產出內容、優先級、成功標準與待確認缺口。
- 問題應補足可寫成 User Requirement 的資訊；不要追問流程步驟、系統狀態或外部合規細節，除非它們會直接改變需求文字。
- 若本輪已有前面發言，請判斷前面問題是否已覆蓋需求分析關注點；若已覆蓋，提出更精準的下一層追問，或在資訊足夠時提出收束。
- 前半段請先補足需求主幹，不要過早進入細節審查。"""


def analyst_elicitation_action_task(stop_phrase: str) -> str:
    return elicitation_action_task(stop_phrase)


def analyst_elicitation_action_rules(stop_phrase: str) -> str:
    return f"""{elicitation_action_rules(stop_phrase)}
- target_stakeholders 優先選擇能說明需求目標、使用情境、成功標準、優先級或待確認缺口的 stakeholder。
- 問題必須對準需求文字可落地的欄位，例如：需求目標、使用情境、輸入/輸出、成功標準、優先級或待確認缺口。
- 不要只問「為什麼需要」或一般動機；只有當答案會改變需求內容、優先級、成功標準或範圍時才問動機。
- 若 Mediator 本輪已安排其他 agent 補流程、例外、限制或風險，你的問題應避開那些角度，專注需求文字與需求判斷。"""
