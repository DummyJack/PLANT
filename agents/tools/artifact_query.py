# Artifact query tool: read compact project state for agents and skills.
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import BaseTool
from agents.profile.analyst.requirements import requirement_discussion_pool
from storage.artifact import load_artifact as load_split_artifact


def conflict_req_keys(item: Dict[str, Any]) -> List[str]:
    return sorted(
        [k for k in item.keys() if k.startswith("req_") and k[4:].isdigit()],
        key=lambda k: int(k[4:]),
    )


def conflict_req_values(item: Dict[str, Any]) -> List[str]:
    return [
        str(item.get(k) or "").strip()
        for k in conflict_req_keys(item)
        if str(item.get(k) or "").strip()
    ]


class ArtifactQueryTool(BaseTool):
    name = "artifact_query"
    description = (
        "查詢目前專案 artifact 中的需求、衝突、決議、議題、模型與研究資料。唯讀，不修改 artifact。\n"
        "用法：\n"
        "- summarize：只回摘要，可只填 mode；若要摘要單一區塊，再填 section。\n"
        "- get_section：必填 section。若該 section 是列表，必填 limit 與 compact；若是單一區塊，例如 conflict，不需要 limit/compact。\n"
        "- find_items：必填 section、非空 filters、limit、compact。沒有查詢條件時不要用 find_items，改用 get_section。\n"
        "- related_context：必填 item_id 與 compact。\n"
        "建議：一般查詢使用 compact=true；只有需要完整欄位時才用 compact=false。\n"
    )
    parameters = {
        "mode": {
            "type": "string",
            "description": "查詢模式：get_section / find_items / related_context / summarize。查列表用 get_section，條件搜尋用 find_items，查關聯脈絡用 related_context，只看數量用 summarize。",
            "required": True,
        },
        "section": {
            "type": "string",
            "description": "artifact 區塊名稱，例如 URL/REQ/conflict/conflict_report/conflict_pairs/conflict_multiple/decisions/open_questions。get_section/find_items 必填；summarize 可選。",
            "required": False,
        },
        "filters": {
            "type": "object",
            "description": "find_items 必填。條件過濾，例如 id/status/label/type/requirement_id/conflict_id/keyword",
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
            "description": "選填。只保留指定欄位；不確定需要哪些欄位時可省略。",
            "required": False,
        },
        "limit": {
            "type": "integer",
            "description": "回傳列表時必填。最多回傳幾筆",
            "required": False,
        },
        "compact": {
            "type": "boolean",
            "description": "回傳列表或 related_context 時必填。是否回傳精簡欄位",
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
                compact=kwargs.get("compact"),
            )
        elif mode == "find_items":
            result = self.find_items(
                artifact,
                section=str(kwargs.get("section") or "").strip(),
                filters=kwargs.get("filters"),
                fields=kwargs.get("fields"),
                limit=kwargs.get("limit"),
                compact=kwargs.get("compact"),
            )
        elif mode == "related_context":
            result = self.related_context(
                artifact,
                item_id=str(kwargs.get("item_id") or "").strip(),
                compact=kwargs.get("compact"),
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
        if section == "URL" and not artifact.get("URL"):
            return requirement_discussion_pool(artifact)
        if section in {"conflict_report", "conflict_pairs", "conflict_multiple"}:
            conflict = artifact.get("conflict") if isinstance(artifact.get("conflict"), dict) else {}
            if section == "conflict_report":
                raw = conflict.get("report", [])
            elif section == "conflict_pairs":
                raw = conflict.get("pairs", [])
            else:
                raw = conflict.get("multiple", [])
            return raw if isinstance(raw, list) else []
        raw = artifact.get(section, [])
        return raw if isinstance(raw, list) else []

    def parse_limit(self, limit: Any) -> Optional[int]:
        try:
            return max(1, int(limit))
        except (TypeError, ValueError):
            return None

    def parse_compact(self, compact: Any) -> Optional[bool]:
        if isinstance(compact, bool):
            return compact
        return None

    def compact_item(self, section: str, item: Dict[str, Any]) -> Dict[str, Any]:
        presets = {
            "URL": ["id", "text", "priority", "source"],
            "decisions": ["id", "decision", "summary", "status"],
            "open_questions": ["from_agent", "to_agent", "question", "status", "issue_id"],
            "issue_proposals": ["issue_id", "title", "importance", "proposed_by", "round"],
        }
        if section in {"conflict_report", "conflict_pairs", "conflict_multiple"}:
            fields = ["id"] + conflict_req_keys(item)
            if section == "conflict_report":
                fields += ["label", "description"]
            else:
                fields += ["initial_label", "final_label", "description", "status"]
            return {k: item.get(k) for k in fields if k in item}
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
            req_key_values = set(conflict_req_values(item))
            rel = item.get("requirement_ids") or item.get("related_requirements") or []
            if (
                str(requirement_id) not in {str(x) for x in rel}
                and str(requirement_id) not in req_key_values
            ):
                return False
        keyword = str(filters.get("keyword") or "").strip().lower()
        if keyword:
            blob = json.dumps(item, ensure_ascii=False).lower()
            if keyword not in blob:
                return False
        return True

    def post_process(
        self, section: str, items: List[Dict[str, Any]], fields: Any, compact: bool, max_n: int
    ) -> List[Dict[str, Any]]:
        out = []
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
        if section == "conflict":
            raw = artifact.get("conflict") if isinstance(artifact.get("conflict"), dict) else {}
            return {
                "ok": True,
                "mode": "get_section",
                "section": section,
                "item": raw,
                "summary": "conflict 為單一區塊",
            }
        if section in {"conflict_report", "conflict_pairs", "conflict_multiple"}:
            max_n = self.parse_limit(limit)
            compact_value = self.parse_compact(compact)
            if max_n is None:
                return {"ok": False, "error": "get_section 回傳列表時需要 limit，且必須是大於 0 的整數"}
            if compact_value is None:
                return {"ok": False, "error": "get_section 回傳列表時需要 compact，且必須是 boolean"}
            items = self.post_process(section, self.as_list(artifact, section), fields, compact_value, max_n)
            return {
                "ok": True,
                "mode": "get_section",
                "section": section,
                "count": len(items),
                "items": items,
                "summary": f"{section} 回傳 {len(items)} 筆",
            }
        raw = artifact.get(section)
        if isinstance(raw, list):
            max_n = self.parse_limit(limit)
            compact_value = self.parse_compact(compact)
            if max_n is None:
                return {"ok": False, "error": "get_section 回傳列表時需要 limit，且必須是大於 0 的整數"}
            if compact_value is None:
                return {"ok": False, "error": "get_section 回傳列表時需要 compact，且必須是 boolean"}
            items = self.post_process(section, raw, fields, compact_value, max_n)
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
        self, artifact: Dict[str, Any], *, section: str, filters: Any, fields: Any, limit: Any, compact: Any
    ) -> Dict[str, Any]:
        if not section:
            return {"ok": False, "error": "find_items 需要 section"}
        if not isinstance(filters, dict) or not filters:
            return {"ok": False, "error": "find_items 需要非空 filters"}
        max_n = self.parse_limit(limit)
        compact_value = self.parse_compact(compact)
        if max_n is None:
            return {"ok": False, "error": "find_items 需要 limit，且必須是大於 0 的整數"}
        if compact_value is None:
            return {"ok": False, "error": "find_items 需要 compact，且必須是 boolean"}
        rows = [it for it in self.as_list(artifact, section) if self.match_filters(it, filters)]
        items = self.post_process(section, rows, fields, compact_value, max_n)
        return {
            "ok": True,
            "mode": "find_items",
            "section": section,
            "count": len(items),
            "items": items,
            "summary": f"{section} 符合條件 {len(items)} 筆",
        }

    def related_context(self, artifact: Dict[str, Any], *, item_id: str, compact: Any) -> Dict[str, Any]:
        if not item_id:
            return {"ok": False, "error": "related_context 需要 item_id"}
        compact_value = self.parse_compact(compact)
        if compact_value is None:
            return {"ok": False, "error": "related_context 需要 compact，且必須是 boolean"}
        req = next((r for r in self.as_list(artifact, "URL") if r.get("id") == item_id), None)
        conflict_rows = self.as_list(artifact, "conflict_pairs") + self.as_list(artifact, "conflict_multiple")
        conflict = next((c for c in conflict_rows if c.get("id") == item_id), None)
        decision = next((d for d in self.as_list(artifact, "decisions") if d.get("id") == item_id), None)
        target = req or conflict or decision
        target_section = "URL" if req else ("conflict_pairs" if conflict else ("decisions" if decision else ""))
        if not target:
            return {"ok": False, "error": f"找不到 item_id: {item_id}"}

        related_conflicts = []
        related_decisions = []
        related_open_questions = []

        if req:
            rid = req.get("id")
            req_text = str(req.get("text") or "").strip()
            related_conflicts = [
                c for c in conflict_rows
                if (
                    rid in set((c.get("requirement_ids") or c.get("related_requirements") or []))
                    or req_text in set(conflict_req_values(c))
                    or rid in set(conflict_req_values(c))
                )
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
            rel_values = set(conflict_req_values(conflict))
            related_conflicts = [conflict]
            related_decisions = [
                d for d in self.as_list(artifact, "decisions")
                if item_id in json.dumps(d, ensure_ascii=False)
            ]
            related_open_questions = [
                q for q in self.as_list(artifact, "open_questions")
                if item_id in json.dumps(q, ensure_ascii=False)
            ]
            req = [
                r for r in self.as_list(artifact, "URL")
                if r.get("id") in rel_ids or str(r.get("text") or "").strip() in rel_values
            ]

        if compact_value:
            target = self.compact_item(target_section, target) if target_section else dict(target)
            if isinstance(req, dict):
                req = self.compact_item("URL", req)
            elif isinstance(req, list):
                req = [self.compact_item("URL", x) for x in req]
            related_conflicts = [self.compact_item("conflict_pairs", x) for x in related_conflicts]
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
            "URL": len(self.as_list(artifact, "URL")),
            "conflict_report": len(self.as_list(artifact, "conflict_report")),
            "conflict_pairs": len(self.as_list(artifact, "conflict_pairs")),
            "conflict_multiple": len(self.as_list(artifact, "conflict_multiple")),
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
