"""Skill：讀取 agents/skills/<name>/SKILL.md 與 references。"""

import re
import json
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from agents.skills.metadata_schema import validate_skill_metadata

SKILLS_ROOT = Path(__file__).resolve().parent
skill_cache: Dict[str, Dict[str, Any]] = {}


def parse_frontmatter(content: str) -> Tuple[Dict[str, str], str]:
    """解析 YAML frontmatter 與正文。"""
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


def list_skills() -> List[str]:
    """含 SKILL.md 的子目錄名稱列表。"""
    names = []
    if not SKILLS_ROOT.is_dir():
        return names
    for path in SKILLS_ROOT.iterdir():
        if path.is_dir() and (path / "SKILL.md").exists():
            names.append(path.name)
    return sorted(names)


def get_skill(skill_name: str, use_cache: bool = True) -> Dict[str, Any]:
    """讀取 SKILL.md 等；use_cache 時快取。"""
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
        for f in assets_dir.glob("*.md"):
            reference_files[f.name] = f.read_text(encoding="utf-8")

    metadata = load_skill_metadata(skill_dir, skill_name)
    metadata_valid, metadata_errors = validate_skill_metadata(metadata) if metadata else (False, ["metadata not found"])

    result = {
        "name": name,
        "description": description,
        "content": content,
        "content_system": content_system,
        "content_user": content_user,
        "template": template,
        "checklist": checklist,
        "reference_files": reference_files,
        "metadata": metadata,
        "metadata_valid": metadata_valid,
        "metadata_errors": metadata_errors,
    }
    if use_cache:
        skill_cache[skill_name] = result
    return result


def load_skill(skill_name: str) -> Dict[str, Any]:
    """相容舊介面：等同 get_skill(skill_name)。"""
    return get_skill(skill_name)


def load_skill_metadata(skill_dir: Path, skill_name: str) -> Dict[str, Any]:
    metadata_file = skill_dir / "metadata.json"
    if not metadata_file.exists():
        return {}
    raw = metadata_file.read_text(encoding="utf-8")
    data = json.loads(raw)
    if "name" not in data:
        data["name"] = skill_name
    return data
