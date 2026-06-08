# Organizes skill guidance used by the agent.
import re


# ========
# Defines markdown section function for this module workflow.
# ========
def markdown_section(content: str, heading: str) -> str:
    pattern = re.compile(
        rf"(^|\n)({re.escape(heading)}\n.*?)(?=\n### |\n## |\Z)",
        re.DOTALL,
    )
    match = pattern.search(content or "")
    return match.group(2).strip() if match else ""


# ========
# Defines markdown between function for this module workflow.
# ========
def markdown_between(content: str, start: str, end: str) -> str:
    source = content or ""
    start_index = source.find(start)
    if start_index < 0:
        return ""
    end_index = source.find(end, start_index + len(start))
    if end_index < 0:
        end_index = len(source)
    return source[start_index:end_index].strip()


# ========
# Defines markdown from heading until function for this module workflow.
# ========
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


# ========
# Defines requirements skill guidance function for this module workflow.
# ========
def requirements_skill_guidance(content: str, mode: str) -> str:
    mode_name = str(mode or "").strip()
    if mode_name == "analysis":
        skill_guidance = markdown_between(
            content,
            "**Universal User Story Format:**",
            "Acceptance Criteria:",
        )
        if skill_guidance and not skill_guidance.rstrip().endswith("```"):
            skill_guidance = skill_guidance.rstrip() + "\n```"
        return skill_guidance

    if mode_name in {"system_requirement", "update_requirement", "refine_requirement", "repair_requirement"}:
        selected = [
            markdown_between(content, "### 1. Requirement Decomposition", "### 2. Requirement Analysis Framework"),
            markdown_between(content, "### 2. Requirement Analysis Framework", "### 3. Priority Frameworks"),
            markdown_between(content, "### 3. Priority Frameworks", "**Kano Model:**"),
            markdown_section(content, "### 4. Requirement Quality Criteria"),
            markdown_section(content, "### 5. Requirement Validation"),
        ]
        guidance = "\n\n".join(section.strip() for section in selected if section.strip())
        override = """# 本專案覆寫規則
- type 分類依已注入的需求分析規則；不要在本 prompt 重新定義 functional / non-functional / constraint。
- feedback.constraints 是 Expert 的限制候選與證據，不等於正式需求；只有來源可追蹤且可寫成系統必須遵守的限制時，才正式化為 type=constraint。
- 明確且有來源支持的 non-functional 需求應直接寫入 type=non-functional；只有 metric、validation、適用範圍、FR/NFR priority 或品質取捨需要決策時，才留待會議或 open question。
- priority 只適用於 functional / non-functional；constraint 是限制或底線，不做 priority 取捨，也不要輸出 priority。
- functional / non-functional 的 priority 只使用 must、should、could；沒有足夠依據就省略，不輸出 wont，也不要預設。
- 每筆 REQ 只保留一個核心意圖；若來源同時包含功能、品質與限制，且可獨立追蹤，請拆成多筆 REQ。
- non-functional 可輸出 category、metric、validation；category 依 ISO/IEC 25010 且不用 functional suitability。
- source 只放已存在且可追蹤的 artifact ID。
- coverage 只作內部檢查，不是正式需求內容；Traceability 維持 Source 與 System Model。"""
        return "\n\n".join(section for section in (guidance, override) if section)

    return ""


# ========
# Defines requirements skill prompt function for this module workflow.
# ========
def requirements_skill_prompt(*, selected_guidance: str, task: str) -> str:
    return (
        "# Skill: requirements-analyst\n\n"
        f"{selected_guidance}\n\n"
        "# 任務\n\n"
        f"{task}"
    )


conflict_headings = [
    "### Step 2: Systematic Conflict Detection",
    "## Common Pitfalls to Avoid",
]

resolution_strategies = {
    "logical": ["Prioritization", "Conditional Logic", "Stakeholder Negotiation"],
    "technical": ["Technical Solution", "Decomposition", "Scope Adjustment"],
    "resource": ["Prioritization", "Sequencing", "Parallel Tracks"],
    "temporal": ["Sequencing", "Relaxation", "Scope Adjustment"],
    "data": ["Technical Solution", "Conditional Logic", "Decomposition"],
    "state": ["Decomposition", "Conditional Logic", "Technical Solution"],
    "priority": ["Stakeholder Negotiation", "Prioritization", "Compromise"],
    "scope": ["Scope Adjustment", "Prioritization", "Sequencing"],
}


# ========
# Defines resolution reference guidance function for this module workflow.
# ========
def resolution_reference_guidance(content: str, conflict_type: str) -> str:
    conflict_type = str(conflict_type or "").strip().lower()
    if conflict_type == "other":
        return ""
    strategies = resolution_strategies.get(conflict_type, [])
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


# ========
# Defines conflict skill guidance function for this module workflow.
# ========
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
        ).replace("### CONF-001: Connectivity Model", "### CR-1: Connectivity Model").strip()
    if base_mode == "resolution":
        resolution_guidance = markdown_from_heading_until(
            content,
            [
                "### Step 3: Recommend Resolution Strategies",
                "### Recommend Resolution Strategies",
            ],
            ["\n### Step 4:", "\n## Output Formats", "\n## Best Practices"],
        )
        resolution_guidance = re.sub(r"\n\d+\.\s+\*\*Implementation effort\*\*.*", "", resolution_guidance)
        resolution_guidance = re.sub(r"\n- Effort:.*", "", resolution_guidance).strip()
        if mode_detail == "other":
            return ""
        return resolution_guidance
    selected = [markdown_section(content, heading) for heading in conflict_headings]
    return "\n\n".join(section for section in selected if section)


# ========
# Defines conflict skill subset function for this module workflow.
# ========
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
