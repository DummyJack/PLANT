# Artifact query tool: read compact project state for agents and skills.
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import BaseTool
from agents.profile.analyst.requirements import requirement_discussion_pool
from storage.artifact import load_artifact as load_split_artifact


class ArtifactQueryTool(BaseTool):
    name = "artifact_query"
    description = "查詢目前專案 artifact 中的需求、衝突、決議、議題、模型與研究資料。唯讀，不修改 artifact。"
    parameters = {
        "mode": {
            "type": "string",
            "description": "查詢模式：get_section / find_items / related_context / summarize",
            "required": True,
        },
        "section": {
            "type": "string",
            "description": "artifact 區塊名稱，例如 requirements/conflicts/decisions/open_questions",
            "required": False,
        },
        "filters": {
            "type": "object",
            "description": "條件過濾，例如 id/status/label/type/requirement_id/conflict_id/keyword",
            "required": False,
        },
        "item_id": {
            "type": "string",
            "description": "related_context 模式用的目標 id，例如 REQ-001 或 CF-01",
            "required": False,
        },
        "fields": {
            "type": "array",
            "items": {"type": "string"},
            "description": "只保留指定欄位",
            "required": False,
        },
        "limit": {
            "type": "integer",
            "description": "最多回傳幾筆",
            "required": False,
        },
        "compact": {
            "type": "boolean",
            "description": "是否回傳精簡欄位",
            "required": False,
        },
    }

    def __init__(self, artifact_path: str):
        self.artifact_path = Path(artifact_path)

    def execute(self, **kwargs) -> str:
        mode = str(kwargs.get("mode") or "").strip()
        if mode not in {"get_section", "find_items", "related_context", "summarize"}:
            return json.dumps(
                {"ok": False, "error": f"不支援的 mode: {mode}"},
                ensure_ascii=False,
                indent=2,
            )
        artifact = self.load_artifact()
        if artifact is None:
            return json.dumps(
                {"ok": False, "error": f"找不到 artifact: {self.artifact_path}"},
                ensure_ascii=False,
                indent=2,
            )

        if mode == "get_section":
            result = self.get_section(
                artifact,
                section=str(kwargs.get("section") or "").strip(),
                fields=kwargs.get("fields"),
                limit=kwargs.get("limit"),
                compact=bool(kwargs.get("compact", False)),
            )
        elif mode == "find_items":
            result = self.find_items(
                artifact,
                section=str(kwargs.get("section") or "").strip(),
                filters=kwargs.get("filters") or {},
                fields=kwargs.get("fields"),
                limit=kwargs.get("limit"),
                compact=bool(kwargs.get("compact", False)),
            )
        elif mode == "related_context":
            result = self.related_context(
                artifact,
                item_id=str(kwargs.get("item_id") or "").strip(),
                compact=bool(kwargs.get("compact", False)),
            )
        else:
            result = self.summarize(
                artifact,
                section=str(kwargs.get("section") or "").strip(),
            )

        return json.dumps(result, ensure_ascii=False, indent=2)

    def load_artifact(self) -> Optional[Dict[str, Any]]:
        if not self.artifact_path.exists():
            return None
        if self.artifact_path.is_dir():
            return load_split_artifact(self.artifact_path)
        with open(self.artifact_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def as_list(self, artifact: Dict[str, Any], section: str) -> List[Dict[str, Any]]:
        if section == "requirements" and not artifact.get("requirements"):
            return requirement_discussion_pool(artifact)
        raw = artifact.get(section, [])
        return raw if isinstance(raw, list) else []

    def limit_value(self, limit: Any) -> int:
        try:
            return max(1, int(limit))
        except (TypeError, ValueError):
            return 20

    def compact_item(self, section: str, item: Dict[str, Any]) -> Dict[str, Any]:
        presets = {
            "requirements": ["id", "text", "type", "priority", "source_stakeholders", "source", "acceptance_criteria"],
            "conflicts": ["id", "label", "description", "requirement_ids", "conflict_type", "status"],
            "decisions": ["id", "decision", "summary", "status"],
            "open_questions": ["from_agent", "to_agent", "question", "status", "issue_id"],
            "issue_proposals": ["issue_id", "title", "category", "priority_hint", "proposed_by", "round"],
        }
        fields = presets.get(section)
        if not fields:
            return dict(item)
        return {k: item.get(k) for k in fields if k in item}

    def select_fields(self, item: Dict[str, Any], fields: Any) -> Dict[str, Any]:
        if not isinstance(fields, list) or not fields:
            return dict(item)
        return {k: item.get(k) for k in fields if isinstance(k, str)}

    def match_filters(self, item: Dict[str, Any], filters: Dict[str, Any]) -> bool:
        if not isinstance(filters, dict):
            return True
        item_id = str(item.get("id") or "")
        if filters.get("id") and item_id != str(filters["id"]):
            return False
        ids = filters.get("ids")
        if isinstance(ids, list) and ids and item_id not in {str(x) for x in ids}:
            return False
        for key in ("status", "label", "type", "owner", "round", "issue_id"):
            expected = filters.get(key)
            if expected is None:
                continue
            actual = item.get(key)
            if isinstance(expected, list):
                if actual not in expected:
                    return False
            elif actual != expected:
                return False
        requirement_id = filters.get("requirement_id")
        if requirement_id:
            rel = item.get("requirement_ids") or item.get("related_requirements") or []
            if str(requirement_id) not in {str(x) for x in rel}:
                return False
        keyword = str(filters.get("keyword") or "").strip().lower()
        if keyword:
            blob = json.dumps(item, ensure_ascii=False).lower()
            if keyword not in blob:
                return False
        return True

    def post_process(
        self, section: str, items: List[Dict[str, Any]], fields: Any, compact: bool, limit: Any
    ) -> List[Dict[str, Any]]:
        out = []
        max_n = self.limit_value(limit)
        for item in items[:max_n]:
            row = self.compact_item(section, item) if compact else dict(item)
            row = self.select_fields(row, fields)
            out.append(row)
        return out

    def get_section(
        self, artifact: Dict[str, Any], *, section: str, fields: Any, limit: Any, compact: bool
    ) -> Dict[str, Any]:
        if not section:
            return {"ok": False, "error": "get_section 需要 section"}
        raw = artifact.get(section)
        if isinstance(raw, list):
            items = self.post_process(section, raw, fields, compact, limit)
            return {
                "ok": True,
                "mode": "get_section",
                "section": section,
                "count": len(items),
                "items": items,
                "summary": f"{section} 回傳 {len(items)} 筆",
            }
        return {
            "ok": True,
            "mode": "get_section",
            "section": section,
            "item": raw,
            "summary": f"{section} 為單一區塊",
        }

    def find_items(
        self, artifact: Dict[str, Any], *, section: str, filters: Dict[str, Any], fields: Any, limit: Any, compact: bool
    ) -> Dict[str, Any]:
        if not section:
            return {"ok": False, "error": "find_items 需要 section"}
        rows = [it for it in self.as_list(artifact, section) if self.match_filters(it, filters)]
        items = self.post_process(section, rows, fields, compact, limit)
        return {
            "ok": True,
            "mode": "find_items",
            "section": section,
            "count": len(items),
            "items": items,
            "summary": f"{section} 符合條件 {len(items)} 筆",
        }

    def related_context(self, artifact: Dict[str, Any], *, item_id: str, compact: bool) -> Dict[str, Any]:
        if not item_id:
            return {"ok": False, "error": "related_context 需要 item_id"}
        req = next((r for r in self.as_list(artifact, "requirements") if r.get("id") == item_id), None)
        conflict = next((c for c in self.as_list(artifact, "conflicts") if c.get("id") == item_id), None)
        decision = next((d for d in self.as_list(artifact, "decisions") if d.get("id") == item_id), None)
        target = req or conflict or decision
        target_section = "requirements" if req else ("conflicts" if conflict else ("decisions" if decision else ""))
        if not target:
            return {"ok": False, "error": f"找不到 item_id: {item_id}"}

        related_conflicts = []
        related_decisions = []
        related_open_questions = []

        if req:
            rid = req.get("id")
            related_conflicts = [
                c for c in self.as_list(artifact, "conflicts")
                if rid in set((c.get("requirement_ids") or c.get("related_requirements") or []))
            ]
            blob = rid or ""
            related_decisions = [
                d for d in self.as_list(artifact, "decisions")
                if blob and blob in json.dumps(d, ensure_ascii=False)
            ]
            related_open_questions = [
                q for q in self.as_list(artifact, "open_questions")
                if blob and blob in json.dumps(q, ensure_ascii=False)
            ]
        elif conflict:
            rel_ids = set(conflict.get("requirement_ids") or conflict.get("related_requirements") or [])
            related_conflicts = [conflict]
            related_decisions = [
                d for d in self.as_list(artifact, "decisions")
                if item_id in json.dumps(d, ensure_ascii=False)
            ]
            related_open_questions = [
                q for q in self.as_list(artifact, "open_questions")
                if item_id in json.dumps(q, ensure_ascii=False)
            ]
            req = [r for r in self.as_list(artifact, "requirements") if r.get("id") in rel_ids]

        if compact:
            target = self.compact_item(target_section, target) if target_section else dict(target)
            if isinstance(req, dict):
                req = self.compact_item("requirements", req)
            elif isinstance(req, list):
                req = [self.compact_item("requirements", x) for x in req]
            related_conflicts = [self.compact_item("conflicts", x) for x in related_conflicts]
            related_decisions = [self.compact_item("decisions", x) for x in related_decisions]
            related_open_questions = [self.compact_item("open_questions", x) for x in related_open_questions]

        return {
            "ok": True,
            "mode": "related_context",
            "item_id": item_id,
            "target": target,
            "related_requirements": req if isinstance(req, list) else ([req] if isinstance(req, dict) else []),
            "related_conflicts": related_conflicts,
            "related_decisions": related_decisions,
            "related_open_questions": related_open_questions,
            "summary": f"{item_id} 相關上下文已整理",
        }

    def summarize(self, artifact: Dict[str, Any], *, section: str) -> Dict[str, Any]:
        if section:
            raw = artifact.get(section)
            count = len(raw) if isinstance(raw, list) else (1 if raw else 0)
            return {
                "ok": True,
                "mode": "summarize",
                "section": section,
                "count": count,
                "summary": f"{section} 目前共有 {count} 筆",
            }
        summary = {
            "requirements": len(self.as_list(artifact, "requirements")),
            "conflicts": len(self.as_list(artifact, "conflicts")),
            "decisions": len(self.as_list(artifact, "decisions")),
            "open_questions": len(self.as_list(artifact, "open_questions")),
            "discussions": len(self.as_list(artifact, "discussions")),
        }
        return {
            "ok": True,
            "mode": "summarize",
            "counts": summary,
            "summary": "artifact 摘要已整理",
        }
