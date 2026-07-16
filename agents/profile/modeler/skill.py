# Organizes skill guidance used by the agent.
import re

diagram_headings = {
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
            markdown_section(content, diagram_headings.get(diagram_name, "")),
        ]
    else:
        sections = common + [
            markdown_section(content, diagram_headings.get(diagram_name, "")),
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
