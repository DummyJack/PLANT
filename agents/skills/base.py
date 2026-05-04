# Skill loader for agents/skills/<name>/SKILL.md metadata and body.
"""Skill loader for agents/skills/<name>/SKILL.md."""

import re
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

SKILLS_ROOT = Path(__file__).resolve().parent
skill_cache: Dict[str, Dict[str, Any]] = {}


def parse_frontmatter(content: str) -> Tuple[Dict[str, str], str]:
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", content, re.DOTALL)
    if not match:
        return {}, content
    fm, body = match.group(1), match.group(2)
    attrs: Dict[str, str] = {}
    key = None
    for line in fm.split("\n"):
        m = re.match(r"^(\w+):\s*(.*)$", line)
        if m:
            key, attrs[m.group(1)] = m.group(1), m.group(2).strip()
        elif key and line.startswith(" "):
            attrs[key] = (attrs[key] + "\n" + line.strip()).strip()
    return attrs, body.strip()


def get_skill(skill_name: str, use_cache: bool = True) -> Dict[str, Any]:
    if use_cache and skill_name in skill_cache:
        return skill_cache[skill_name]

    skill_dir = SKILLS_ROOT / skill_name
    if not skill_dir.is_dir():
        raise FileNotFoundError(f"Skill 目錄不存在: {skill_dir}")

    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        raise FileNotFoundError(f"SKILL.md 不存在: {skill_md}")

    raw = skill_md.read_text(encoding="utf-8")
    attrs, body = parse_frontmatter(raw)
    name = attrs.get("name", skill_name)
    description = attrs.get("description", "")

    content_system: Optional[str] = None
    content_user: Optional[str] = None
    if "<!-- system end -->" in body:
        before, after = body.split("<!-- system end -->", 1)
        content_system = before.strip()
        content_user = after.strip()
    content = content_user if content_system else body

    template: Optional[str] = None
    checklist: Optional[str] = None
    reference_files: Dict[str, str] = {}
    ref_dir = skill_dir / "references"
    if ref_dir.is_dir():
        if (ref_dir / "template.md").exists():
            template = (ref_dir / "template.md").read_text(encoding="utf-8")
        if (ref_dir / "checklist.md").exists():
            checklist = (ref_dir / "checklist.md").read_text(encoding="utf-8")
        for f in ref_dir.glob("*.md"):
            if f.name not in ("template.md", "checklist.md"):
                reference_files[f.name] = f.read_text(encoding="utf-8")
    assets_dir = skill_dir / "assets"
    if assets_dir.is_dir():
        for f in assets_dir.glob("*"):
            if f.is_file() and f.suffix.lower() in (".md", ".json", ".txt"):
                reference_files[f.name] = f.read_text(encoding="utf-8")

    project_adapter = None
    adapter_file = skill_dir / "PROJECT_ADAPTER.md"
    if adapter_file.exists():
        project_adapter = adapter_file.read_text(encoding="utf-8").strip()

    result = {
        "name": name,
        "description": description,
        "content": content,
        "content_system": content_system,
        "content_user": content_user,
        "template": template,
        "checklist": checklist,
        "reference_files": reference_files,
        "project_adapter": project_adapter,
    }
    if use_cache:
        skill_cache[skill_name] = result
    return result

