"""
Skill 載入與註冊：agents/skills/<name>/ 下的 SKILL.md 與 references。
提供 list_skills()、get_skill(name)，供 agent 依名稱 invoke 使用。
"""

import re
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple

_SKILLS_ROOT = Path(__file__).resolve().parent
_cache: Dict[str, Dict[str, Any]] = {}


def _parse_frontmatter(content: str) -> Tuple[Dict[str, str], str]:
    """從 SKILL.md 抽出 YAML frontmatter（---...---）與 body。回傳 (attrs, body)。"""
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
    """列出所有已註冊的 skill 名稱（agents/skills/ 下含 SKILL.md 的子資料夾名）。"""
    names = []
    if not _SKILLS_ROOT.is_dir():
        return names
    for path in _SKILLS_ROOT.iterdir():
        if path.is_dir() and (path / "SKILL.md").exists():
            names.append(path.name)
    return sorted(names)


def get_skill(skill_name: str, use_cache: bool = True) -> Dict[str, Any]:
    """
    依名稱取得 skill：讀取 SKILL.md 與 references/，回傳統一介面。
    回傳 dict：name, description, content（SKILL 全文）, template, checklist。
    若 use_cache 為 True 則快取，同一 skill 只讀檔一次。
    """
    if use_cache and skill_name in _cache:
        return _cache[skill_name]

    skill_dir = _SKILLS_ROOT / skill_name
    if not skill_dir.is_dir():
        raise FileNotFoundError(f"Skill 目錄不存在: {skill_dir}")

    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        raise FileNotFoundError(f"SKILL.md 不存在: {skill_md}")

    content = skill_md.read_text(encoding="utf-8")
    attrs, _ = _parse_frontmatter(content)
    name = attrs.get("name", skill_name)
    description = attrs.get("description", "")

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

    result = {
        "name": name,
        "description": description,
        "content": content,
        "template": template,
        "checklist": checklist,
        "reference_files": reference_files,
    }
    if use_cache:
        _cache[skill_name] = result
    return result


def load_skill(skill_name: str) -> Dict[str, Any]:
    """相容舊介面：等同 get_skill(skill_name)。"""
    return get_skill(skill_name)
