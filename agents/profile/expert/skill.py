# Organizes skill guidance used by the agent.
import re


def markdown_section(content: str, heading: str) -> str:
    pattern = re.compile(
        rf"(^|\n)({re.escape(heading)}\n.*?)(?=\n## |\Z)",
        re.DOTALL,
    )
    match = pattern.search(content or "")
    return match.group(2).strip() if match else ""


def domain_skill_guidance(content: str, mode: str) -> str:
    mode_name = str(mode or "").strip()
    priority = markdown_section(content, "## Priority Rules")
    capabilities = markdown_section(content, "## Research Capabilities")

    if mode_name == "read_docs":
        selected = [
            priority,
            markdown_section(content, "### Step 3: Gather Evidence"),
            markdown_section(content, "### Step 4: Synthesize Findings"),
            markdown_section(content, "### Step 5: Return Findings"),
        ]
    elif mode_name == "feedback":
        selected = [
            priority,
            markdown_section(content, "### Step 4: Synthesize Findings"),
            markdown_section(content, "### Step 5: Return Findings"),
            markdown_section(content, "### Follow-Up Work"),
        ]
    else:
        selected = [
            priority,
            capabilities,
            markdown_section(content, "### Step 3: Gather Evidence"),
            markdown_section(content, "### Step 4: Synthesize Findings"),
            markdown_section(content, "### Step 5: Return Findings"),
        ]
    return "\n\n".join(section for section in selected if section)


def domain_skill_subset(skill: dict, mode: str) -> dict:
    content = str(skill.get("content") or "")
    guidance = domain_skill_guidance(content, mode)
    subset = dict(skill)
    subset["content"] = guidance or content
    subset.pop("content_user", None)
    subset.pop("reference_files", None)
    return subset
