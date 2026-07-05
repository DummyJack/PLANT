# Defines agent skill loading and skill content handling.

import re
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SKILLS_ROOT = Path(__file__).resolve().parent
skill_cache: Dict[str, Dict[str, Any]] = {}


# ========
# Defines parse frontmatter function for this module workflow.
# ========
def parse_frontmatter(content: str) -> Tuple[Dict[str, str], str]:
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", content, re.DOTALL)
    if not match:
        return {}, content
    fm, body = match.group(1), match.group(2)
    attrs: Dict[str, str] = {}
    key = None
    for line in fm.split("\n"):
        m = re.match(r"^([\w-]+):\s*(.*)$", line)
        if m:
            key, attrs[m.group(1)] = m.group(1), m.group(2).strip()
        elif key and line.startswith(" "):
            attrs[key] = (attrs[key] + "\n" + line.strip()).strip()
    return attrs, body.strip()


# ========
# Defines get skill function for this module workflow.
# ========
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
        for f in sorted(ref_dir.glob("*.md")):
            if f.name not in ("template.md", "checklist.md"):
                reference_files[f.name] = f.read_text(encoding="utf-8")
    if template is None and (skill_dir / "template.md").exists():
        template = (skill_dir / "template.md").read_text(encoding="utf-8")
    if checklist is None:
        for checklist_name in ("checklist.md", "checklists.md"):
            checklist_file = skill_dir / checklist_name
            if checklist_file.exists():
                checklist = checklist_file.read_text(encoding="utf-8")
                break
    root_reference_names = {"resolution.md"}
    for ref_name in sorted(root_reference_names):
        ref_file = skill_dir / ref_name
        if ref_file.exists():
            reference_files[ref_name] = ref_file.read_text(encoding="utf-8")
    assets_dir = skill_dir / "assets"
    if assets_dir.is_dir():
        for f in sorted(assets_dir.glob("*")):
            if f.is_file() and f.suffix.lower() in (".md", ".json", ".txt"):
                reference_files[f.name] = f.read_text(encoding="utf-8")

    project_adapter = None
    adapter_file = skill_dir / "PROJECT_ADAPTER.md"
    if adapter_file.exists():
        project_adapter = adapter_file.read_text(encoding="utf-8").strip()

    result = {
        "name": name,
        "description": description,
        "metadata": attrs,
        "allowed_tools": [
            x.strip()
            for x in (attrs.get("allowed-tools") or "").split(",")
            if x.strip()
        ],
        "content": content,
        "content_system": content_system,
        "content_user": content_user,
        "template": template,
        "checklist": checklist,
        "reference_files": reference_files,
        "project_adapter": project_adapter,
        "path": skill_md,
    }
    if use_cache:
        skill_cache[skill_name] = result
    return result


# ========
# Defines SkillSupport class for this module workflow.
# ========
class SkillSupport:
    # Defines validate skill usage function for this module workflow.
    def validate_skill_usage(self, skill_name: str) -> None:
        if skill_name not in self.skill_names:
            raise ValueError(
                f"Agent '{self.name}' 未賦予 skill '{skill_name}'，可用: {self.skill_names}"
            )
        if self.policy and not self.policy.can_agent_use_skill(self.name, skill_name):
            raise ValueError(f"Policy 禁止 Agent '{self.name}' 使用 skill '{skill_name}'")

    # Defines build skill messages function for this module workflow.
    def build_skill_messages(
        self,
        skill: Dict[str, Any],
        skill_name: str,
        task: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, str]]:
        system_parts = [self.system_prompt]
        user_content = skill.get("content_user") or skill["content"]
        user_parts = [f"# Skill: {skill.get('name', skill_name)}\n\n"]
        if skill.get("content_system"):
            user_parts.extend(
                [
                    "# Skill 指引\n\n",
                    skill["content_system"],
                    "\n\n",
                ]
            )
        user_parts.extend(
            [
                f"# 輸出語系（必須遵守）\n{self.output_language_directive()}\n\n",
                user_content,
                "\n\n",
            ]
        )
        if context is not None:
            user_parts.append(
                "# Context\n"
                f"{json.dumps(context, ensure_ascii=False, indent=2)}\n\n"
            )
        if task.lstrip().startswith("# 任務"):
            user_parts.append(task)
        else:
            user_parts.append(f"# 任務\n\n{task}")
        if skill.get("project_adapter"):
            user_parts.extend(
                ["\n\n# Project Adapter（專案覆蓋規則）\n\n", skill["project_adapter"]]
            )
        if skill.get("template"):
            user_parts.extend(["\n\n# 範本（必須依此結構）\n\n", skill["template"]])
        if skill.get("checklist"):
            user_parts.extend(
                ["\n\n# 品質檢查清單（產出前須自檢通過）\n\n", skill["checklist"]]
            )
        for ref_name, ref_content in (skill.get("reference_files") or {}).items():
            user_parts.extend([f"\n\n# {ref_name}\n\n", ref_content])

        return [
            {"role": "system", "content": "".join(system_parts)},
            {"role": "user", "content": "\n".join(user_parts)},
        ]

    # Defines run skill messages function for this module workflow.
    def run_skill_messages(
        self,
        skill_name: str,
        messages: List[Dict[str, str]],
    ) -> str:
        if self.tools:
            return self.chat_with_tools(
                messages,
                active_skill=skill_name,
            )
        return self.model.chat(
            messages,
            action=self.usage_action(f"skill.{skill_name}"),
        )
