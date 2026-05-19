# Analyst requirements logic: scope, drafts, requirement records, and change candidates.
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from agents.base import parse_json_array, parse_json_object
from storage.markdown import clean_llm_output
from storage.plantuml import plantuml_safe_name
from agents.skills.base import get_skill
from agents.profile.scenario import scenario_prompt_value

from .conflict_store import all_conflict_rows, conflict_entries_count
from .validation import (
    requirement_record as analyst_requirement_record,
    requirement_records,
    requirement_text as analyst_requirement_text,
    scope_payload,
)
from .requirements import requirement_discussion_pool
from .prompts import (
    build_draft_prompt,
    requirements_skill_guidance,
    user_requirement_extraction_contract,
)


def draft_stakeholders(artifact: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for stakeholder in artifact.get("stakeholders", []) or []:
        if not isinstance(stakeholder, dict):
            continue
        name = str(stakeholder.get("name") or "").strip()
        if not name:
            continue
        row = {"name": name}
        stakeholder_type = str(stakeholder.get("type") or "").strip()
        if stakeholder_type:
            row["type"] = stakeholder_type
        text = stakeholder.get("text")
        if isinstance(text, list):
            clean_texts = [
                str(item).strip()
                for item in text
                if str(item).strip()
            ]
            if clean_texts:
                row["text"] = clean_texts
        elif str(text or "").strip():
            row["text"] = str(text).strip()
        rows.append(row)
    return rows


def draft_feedback(artifact: Dict[str, Any]) -> Dict[str, Any]:
    feedback = artifact.get("feedback") if isinstance(artifact.get("feedback"), dict) else {}
    clean: Dict[str, Any] = {}
    for key in ("findings", "constraints", "risks", "recommendations", "open_items"):
        rows = [
            row for row in feedback.get(key, []) or []
            if isinstance(row, dict) and str(row.get("text") or "").strip()
        ]
        if rows:
            clean[key] = rows
    sources = [
        str(row or "").strip()
        for row in feedback.get("sources", []) or []
        if str(row or "").strip()
    ]
    if sources:
        clean["sources"] = sources
    return clean


def draft_open_questions(artifact: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for question in artifact.get("open_questions", []) or []:
        if not isinstance(question, dict):
            continue
        text = str(question.get("question") or "").strip()
        if not text:
            continue
        row = {"question": text}
        for key in ("id", "to", "status", "source", "type"):
            value = question.get(key)
            if value:
                row[key] = value
        rows.append(row)
    return rows


def draft_system_models(
    artifact: Dict[str, Any],
    artifact_dir: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    artifact_path = Path(artifact_dir) if artifact_dir else None
    rows: List[Dict[str, Any]] = []
    for model in artifact.get("system_models", []) or []:
        if not isinstance(model, dict):
            continue
        model_type = str(model.get("type") or "").strip()
        name = str(model.get("name") or "").strip()
        if not model_type and not name:
            continue
        row: Dict[str, Any] = {}
        if name:
            row["name"] = name
        if model_type:
            row["type"] = model_type
        description = str(model.get("description") or "").strip()
        if description:
            row["description"] = description
        if model.get("text"):
            row["text"] = model.get("text")
        plantuml = str(model.get("plantuml") or "").strip()
        row["has_plantuml"] = bool(plantuml)
        if row["has_plantuml"] and artifact_path:
            filename = f"{plantuml_safe_name(model)}.png"
            if (artifact_path / "models" / filename).is_file():
                row["image_path"] = f"../models/{filename}"
        if row["has_plantuml"] and not row.get("image_path"):
            row["plantuml"] = plantuml
        rows.append(row)
    return rows


def draft_requirement_id_issues(md: str, expected_ids: set[str]) -> tuple[List[str], List[str]]:
    draft_req_ids = set(re.findall(r"\bURL-\d+\b", md or ""))
    unknown_ids = sorted(draft_req_ids - expected_ids)
    missing_ids = sorted(expected_ids - draft_req_ids)
    return unknown_ids, missing_ids


class AnalystRequirements:
    def run_requirements_analyst(
        self,
        action: str,
        *,
        rough_idea: str = "",
        stakeholders: Optional[List[Dict]] = None,
        artifact: Optional[Dict[str, Any]] = None,
        draft_version: Optional[int] = None,
        previous_draft: Optional[str] = None,
        conflict_report_md: str = "",
        meeting_record_md: str = "",
        round_num: Optional[int] = None,
        artifact_dir: Optional[Any] = None,
    ):
        """requirements-analyst skill 統一入口。

        action:
            "analyze_scenario"        -> 回傳 Dict (scenario)
            "generate_scope"          -> 回傳 Dict (scope)
            "analyze_requirements"    -> 回傳 Dict (requirements list)
            "create_draft"            -> 回傳 str  (Markdown)
            "update_draft"            -> 回傳 Dict (requirements + change_candidates)
        """
        allowed_actions = {
            "analyze_scenario",
            "generate_scope",
            "analyze_requirements",
            "create_draft",
            "update_draft",
            "finalize_requirements",
        }
        if action not in allowed_actions:
            raise ValueError(f"未知 requirements action: {action}")
        opa = self.run_action_loop(
            name="requirements_analysis",
            context={
                "requirements_action": action,
                "rough_idea": rough_idea,
                "stakeholders": stakeholders or [],
                "artifact": artifact or {},
                "version": draft_version,
                "previous_draft": previous_draft,
                "conflict_report_md": conflict_report_md,
                "meeting_record_md": meeting_record_md,
                "round_num": round_num,
                "artifact_dir": artifact_dir,
            },
            build_observation=self.build_requirements_analysis_observation,
            decide_action=self.decide_requirements_analysis_action,
            execute_action=self.execute_requirements_analysis_action,
        )
        trace = opa.get("opa_trace") or []
        result = dict((trace[-1].get("result") if trace else {}) or {})
        if result.get("error"):
            raise RuntimeError(result.get("error"))
        return result.get("output")

    def build_requirements_analysis_observation(self, **kwargs: Any) -> Dict[str, Any]:
        artifact = kwargs.get("artifact") or {}
        stakeholders = kwargs.get("stakeholders") or []
        return {
            "action": kwargs.get("requirements_action", ""),
            "iteration": kwargs.get("iteration", 0) + 1,
            "max_iterations": kwargs["max_iterations"],
            "stakeholder_count": len(stakeholders),
            "requirements_count": len(requirement_discussion_pool(artifact)),
            "decisions_count": len(artifact.get("decisions", []) or []),
            "conflicts_count": conflict_entries_count(artifact),
            "has_scope": bool(artifact.get("scope")),
        }

    def decide_requirements_analysis_action(
        self,
        *,
        observation: Dict[str, Any],
        last_result: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        if isinstance(last_result, dict) and not last_result.get("error"):
            return {
                "action": "done",
                "params": {},
                "reasoning": "上一輪需求分析任務已完成，結束本次 requirements analysis。",
            }
        action = str(observation.get("action") or "").strip()
        return {
            "action": action,
            "params": {},
            "reasoning": f"執行 Analyst requirements analysis 任務：{action}。",
        }

    def execute_requirements_analysis_action(
        self,
        *,
        decision: Dict[str, Any],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        action = str(decision.get("action") or "").strip()
        try:
            if action == "analyze_scenario":
                output = self.analyze_scenario(kwargs.get("rough_idea", ""))
            elif action == "generate_scope":
                output = self.generate_scope(
                    kwargs.get("rough_idea", ""),
                    kwargs.get("stakeholders") or [],
                    artifact=kwargs.get("artifact") or {},
                )
            elif action == "analyze_requirements":
                output = self.analyze_requirements(kwargs.get("stakeholders") or [])
            elif action == "create_draft":
                output = self.create_draft(
                    kwargs.get("artifact") or {},
                    draft_version=kwargs.get("version"),
                    previous_draft=kwargs.get("previous_draft"),
                    conflict_report_md=kwargs.get("conflict_report_md") or "",
                    meeting_record_md=kwargs.get("meeting_record_md") or "",
                    round_num=kwargs.get("round_num"),
                    artifact_dir=kwargs.get("artifact_dir"),
                )
            elif action == "update_draft":
                output = self.update_draft(kwargs.get("artifact") or {})
            elif action == "finalize_requirements":
                output = self.finalize_requirements(kwargs.get("artifact") or {})
            else:
                raise ValueError(f"未知 requirements action: {action}")
        except Exception as e:
            return {
                "action": action,
                "status": "failed",
                "error": str(e),
                "summary": f"requirements analysis failed: {action}",
            }
        return {
            "action": action,
            "status": "success",
            "output": output,
            "summary": f"完成 requirements analysis: {action}",
        }

    @staticmethod
    def requirement_text(text: str) -> str:
        return analyst_requirement_text(text)

    @staticmethod
    def requirement_record(
        req: Dict[str, Any],
    ) -> Dict[str, Any]:
        return analyst_requirement_record(req)

    def analyze_scenario(self, rough_idea: str) -> Dict[str, Any]:
        context = {"rough_idea": rough_idea}
        task = """# 任務
根據 rough_idea，產生一個可實際開發的系統情境名稱。

# 判斷重點
- 將 rough_idea 轉成清楚的系統名稱。

# 輸出 JSON
{
  "scenario": {
    "name": "可以做的系統名稱"
  }
}"""
        try:
            data = self.invoke_direct_requirements_object_json(
                task,
                context,
                action="requirements.scenario",
            )
        except Exception as e:
            raise RuntimeError(f"scenario 分析失敗: {e}") from e
        scenario = data.get("scenario") if isinstance(data.get("scenario"), dict) else data
        name = str((scenario or {}).get("name") or "").strip()
        if not name:
            raise ValueError("scenario 分析未產生有效 name")
        return {"name": name}

    def generate_scope(
        self, rough_idea: str, stakeholders: List[Dict],
        *, artifact: Optional[Dict[str, Any]] = None,
    ) -> Dict:
        context: Dict[str, Any] = {}
        if artifact:
            if artifact.get("scenario"):
                context["scenario"] = scenario_prompt_value(artifact["scenario"])
            elif rough_idea:
                context["scenario"] = scenario_prompt_value(rough_idea)
            if artifact.get("scope"):
                context["current_scope"] = artifact["scope"]
            req_pool = requirement_discussion_pool(artifact)
            if req_pool:
                context["URL"] = req_pool
        task = """# 任務
根據產品情境與 User Requirements，界定本專案需求範圍。

# 可用資料
- scenario：產品情境。
- URL：目前已抽取的候選 User Requirements。

# 判斷規則
- in_scope 放本專案應處理的產品能力、使用情境、需求主題或限制。
- out_of_scope 放明確不屬於本專案、不符合產品情境，或已被排除的內容。
- 若輸入沒有明確排除項，仍可根據產品責任邊界列出合理 out_of_scope。
- out_of_scope 只能包含本系統不直接負責、需第三方、線下或外部組織負責，或超出目前產品版本目標的內容。
- 不得加入與 scenario 無關的排除項。
- 不確定是否排除時，不要放入 out_of_scope。
- out_of_scope 以 3-7 筆為宜；若確實沒有合理邊界，才輸出空陣列。
- 不要加入 assumptions、unknowns、description、status 或 source。

# 輸出 JSON
{
  "scope": {
    "in_scope": [],
    "out_of_scope": []
  }
}"""
        try:
            data = self.invoke_direct_requirements_object_json(
                task,
                context,
                action="requirements.scope",
            )
        except Exception as e:
            raise RuntimeError(f"scope 生成失敗: {e}") from e
        scope = data.get("scope") or {}
        return scope_payload(scope)

    def analyze_requirements(self, stakeholders: List[Dict]) -> Dict[str, Any]:
        all_requirements = []
        for idx, one_sh in enumerate(stakeholders):
            sh_label = str(one_sh.get("name") or "").strip()
            if not sh_label:
                raise ValueError(f"stakeholder 缺少 name，無法進行需求分析: index={idx}")
            sh_texts = one_sh.get("text") or []
            if isinstance(sh_texts, list):
                source_texts = [str(text).strip() for text in sh_texts if str(text).strip()]
            else:
                source_text = str(sh_texts or "").strip()
                source_texts = [source_text] if source_text else []
            for source_idx, source_text in enumerate(source_texts, 1):
                context = {
                    "stakeholder": {
                        "name": sh_label,
                        "type": one_sh.get("type"),
                        "source_text": source_text,
                        "all_text": source_texts,
                    }
                }
                task = f"""請依照 requirements-analyst skill，只根據目前這一條 source_text 抽取 User Requirements。

完整 all_text 只作為理解語境的背景，不可從其他 all_text 條目產生需求。

{user_requirement_extraction_contract()}
"""
                try:
                    data = self.invoke_requirements_analyst_array_json(task, context, mode="analysis")
                except Exception as e:
                    try:
                        raw = self.invoke_requirements_analyst_text(task, context, mode="analysis")
                        repair_task = f"""上一個回覆不是合法 JSON array。請只修正格式，不要重新分析、不要新增需求。

輸出必須是 JSON array，每筆只包含 text、priority。

原始回覆：
{raw}"""
                        data = self.invoke_direct_requirements_array_json(
                            repair_task,
                            context={},
                            action="requirements.analysis.repair",
                        )
                    except Exception:
                        raise RuntimeError(f"需求分析失敗（{sh_label}#{source_idx}）: {e}") from e
                raw_rows = data if isinstance(data, list) else []
                normalized_rows = [
                    row for row in requirement_records([
                        {
                            **row,
                            "stakeholder": {
                                "name": sh_label,
                                "type": one_sh.get("type"),
                            },
                            "source": "initial",
                        }
                        for row in raw_rows
                        if isinstance(row, dict)
                    ])
                    if row.get("stakeholder") and row.get("source")
                ]
                all_requirements.extend(normalized_rows)

        return {"requirements": all_requirements}

    def create_draft(
        self,
        artifact: Dict[str, Any],
        draft_version: Optional[int] = None,
        previous_draft: Optional[str] = None,
        conflict_report_md: str = "",
        meeting_record_md: str = "",
        round_num: Optional[int] = None,
        artifact_dir: Optional[Any] = None,
    ) -> str:
        user_requirements = requirement_discussion_pool(artifact)
        for req in user_requirements:
            req_norm = self.requirement_record(req)
            req.update(req_norm)

        scope = artifact.get("scope", {}) or {}
        context = {
            "rough_idea": str(artifact.get("rough_idea") or "").strip(),
            "scenario": scenario_prompt_value(artifact.get("scenario", {}) or {}),
            "scope": scope,
            "stakeholders": draft_stakeholders(artifact),
            "user_requirements": user_requirements,
            "conflict_report": (conflict_report_md or "").strip(),
            "meeting_record": (meeting_record_md or "").strip(),
            "feedback": draft_feedback(artifact),
            "open_questions": draft_open_questions(artifact),
            "system_models": draft_system_models(artifact, artifact_dir=artifact_dir),
            "version": draft_version if draft_version is not None else 0,
        }
        previous_draft_text = (previous_draft or "").strip()
        is_revision = bool(previous_draft_text and draft_version and draft_version > 0)
        if is_revision:
            context["previous_draft"] = previous_draft_text
        version_note = ""
        if draft_version is not None:
            version_note = f" 本稿版本: draft_v{draft_version}。"
        if round_num is not None:
            version_note += f" 對應輪次: Round {round_num}。"
        task = build_draft_prompt(
            is_revision=is_revision,
            version_note=version_note,
            version=draft_version if draft_version is not None else 0,
        )
        try:
            raw = self.invoke_requirements_analyst_text(task, context, mode="draft")
        except Exception as e:
            raise RuntimeError(f"draft 生成失敗: {e}") from e
        md = clean_llm_output(raw)
        expected_ids = {
            str(req.get("id") or "").strip()
            for req in user_requirements
            if isinstance(req, dict) and str(req.get("id") or "").strip()
        }
        unknown_ids, missing_ids = draft_requirement_id_issues(md, expected_ids)
        if unknown_ids:
            self.logger.warning("draft 包含 User Requirements 以外的需求 ID: %s", unknown_ids)
        if missing_ids:
            self.logger.warning("draft 未保留部分 User Requirements ID: %s", missing_ids)
        if unknown_ids or missing_ids:
            repair_task = f"""上一版需求草稿 Markdown 的 URL-* 覆蓋不符合契約。請只修正 Markdown，不要重新分析，不要新增需求，不要改變原有需求語意。

修正目標：
- 移除或更正輸入 user_requirements 中不存在的 URL-*：{unknown_ids}
- 補回缺少的 URL-*：{missing_ids}
- 每個 URL-* 必須出現在「使用者需求」表。
- 不得新增輸入資料以外的 URL-*。
- 不得把 feedback、open_questions、system_models、conflict_report 或 meeting_record 直接轉成 User Requirements。

原始草稿：
{md}

請只輸出修正後的完整 Markdown 草稿。"""
            try:
                repaired = self.invoke_requirements_analyst_text(
                    repair_task,
                    context,
                    mode="draft",
                )
                md = clean_llm_output(repaired)
                unknown_ids, missing_ids = draft_requirement_id_issues(md, expected_ids)
            except Exception as e:
                raise RuntimeError(f"draft 修復失敗: {e}") from e
            if unknown_ids or missing_ids:
                raise RuntimeError(
                    f"draft 修復後仍不符合 URL 覆蓋契約；unknown={unknown_ids}; missing={missing_ids}"
                )

        return md

    def update_draft(self, artifact: Dict) -> Dict:
        context = {
            "requirements": artifact.get("requirements", []),
            "decisions": artifact.get("decisions", []),
            "discussions": artifact.get("discussions", []),
            "conflicts": all_conflict_rows(artifact),
            "scope": artifact.get("scope", {}),
        }
        task = """請基於 User Requirements 更新需求，重點是消化已明確形成的 decisions / discussions 對需求文字的影響。

更新邊界：
1. requirements 陣列必須保留所有既有需求 id；不得重新編號。
2. 只調整受本輪 decisions 或 discussions 直接影響的條目；與本輪無關的需求不要改動。
3. 既有 id 除非 decisions 明確要求，不得任意改動。
4. 可追加 scope 內、且由 discussions/decisions 明確支持的新需求；不得新增超出 scope.out_of_scope 的內容。
5. 若只是推論，放到 open_questions/to_confirm，不要寫入 requirements。
6. 已解決的 conflict 對應需求應與決策方向一致。
7. 可整理 wording，但不得改變需求實質內容，也不得把未定案內容寫成已確認。
8. 每筆需求只保留 id、text、priority、stakeholder、source；若原本有 source_ref 必須保留。
9. stakeholder 必須保留為 {"name":"...","type":"..."}，不得改成字串，不得輸出 stakeholder.text。
10. source 只表示來源階段，例如 initial 或 elicitation_r1；不得改成原話。

只輸出一個 JSON 物件：{"requirements":[...]}。"""
        try:
            data = self.invoke_direct_requirements_object_json(
                task,
                context,
                action="requirements.update_draft",
            )
        except Exception as e:
            raise RuntimeError(f"draft 更新失敗: {e}") from e
        requirements = data.get("requirements", artifact.get("requirements", []))
        if not isinstance(requirements, list):
            requirements = artifact.get("requirements", [])
        prev_by_id = {
            r.get("id"): r for r in artifact.get("requirements", []) if r.get("id")
        }
        returned_ids = {r.get("id") for r in requirements if r.get("id")}
        for pid, prev_req in prev_by_id.items():
            if pid not in returned_ids:
                requirements.append(dict(prev_req))
                self.logger.debug("update_draft: 補回既有需求 %s", pid)
        for req in requirements:
            normalized = self.requirement_record(req)
            req.update(normalized)
        change_candidates = self.build_change_record(
            artifact.get("requirements", []),
            requirements,
            artifact=artifact,
        )
        return {
            "requirements": requirements,
            "conflicts": all_conflict_rows(artifact),
            "change_record": change_candidates,
        }

    def finalize_requirements(self, artifact: Dict) -> Dict:
        candidate_pool = requirement_discussion_pool(artifact)
        context = {
            "URL": candidate_pool,
            "decisions": artifact.get("decisions", []),
            "discussions": artifact.get("discussions", []),
            "conflicts": all_conflict_rows(artifact),
            "scope": artifact.get("scope", {}),
            "stakeholders": artifact.get("stakeholders", []),
            "elicitation": artifact.get("elicitation", {}),
        }
        task = """請根據輸入資料將候選需求池定版為正式 requirements。

輸入來源：
- User Requirements 是需求池，包含初始分析與 requirement elicitation meeting 產生的候選需求。
- 會議決策、討論紀錄與衝突結果是會議協調後的正式依據。

定版規則：
1. 正式 requirements 只能來自 URL，或由 decisions/discussions 明確支持的候選修訂；不得憑空新增需求。
2. 必須消化已明確形成的 decisions 與已解決 conflicts。
3. 若候選需求重複或只是同一需求的細化，請合併成一筆正式需求。
4. 若候選需求仍缺少支持、超出 scope.out_of_scope，或只是 open question，不要寫入正式 requirements。
5. 每筆正式需求都要有 id，格式為 REQ-1、REQ-2、REQ-3；不要使用 URL-*。
6. 每筆需求只輸出 text、priority、stakeholder、source；若候選需求有 source_ref 且仍可追溯，請保留 source_ref。
7. stakeholder 必須保留為 {"name":"...","type":"..."}，name 是利害關係人名稱，type 是 stakeholder 類型；不得輸出 stakeholder.text。
8. source 只表示來源階段，例如 initial 或 elicitation_r1；不得改成原話。
9. priority 只能是 must、should 或 could；不收錄的項目不要輸出。

只輸出一個 JSON 物件：{"requirements":[...]}。勿輸出 Markdown。"""
        try:
            data = self.invoke_direct_requirements_object_json(
                task,
                context,
                action="requirements.finalize",
            )
        except Exception as e:
            raise RuntimeError(f"正式 requirements 定版失敗: {e}") from e
        requirements = data.get("requirements", [])
        if not isinstance(requirements, list):
            requirements = []
        normalized: List[Dict[str, Any]] = []
        seen_ids = set()
        for idx, req in enumerate(requirements, 1):
            if not isinstance(req, dict):
                continue
            row = self.requirement_record(req)
            if not row.get("text"):
                continue
            rid = str(row.get("id") or "").strip()
            if not re.fullmatch(r"REQ-\d+", rid) or rid in seen_ids:
                rid = f"REQ-{len(normalized) + 1}"
            row["id"] = rid
            seen_ids.add(rid)
            normalized.append(row)
        return {
            "requirements": normalized,
            "conflicts": all_conflict_rows(artifact),
            "change_record": [],
        }

    def build_change_record(
        self,
        previous_requirements: List[Dict[str, Any]],
        updated_requirements: List[Dict[str, Any]],
        *,
        artifact: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """從舊新版需求清單推導可追蹤的變更候選，不自動產生刪除。"""
        previous_by_id = {
            req.get("id"): dict(req)
            for req in previous_requirements
            if isinstance(req, dict) and req.get("id")
        }
        decisions = (artifact or {}).get("decisions", []) or []
        discussions = (artifact or {}).get("discussions", []) or []
        source_ids = [
            item.get("id")
            for item in list(decisions) + list(discussions)
            if isinstance(item, dict) and item.get("id")
        ]
        candidates: List[Dict[str, Any]] = []
        seen_keys = set()
        next_index = 1

        for req in updated_requirements:
            if not isinstance(req, dict):
                continue
            req_id = req.get("id")
            if not req_id:
                continue
            before = previous_by_id.get(req_id)
            if before is None:
                key = ("add", req_id)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                candidates.append(
                    {
                        "id": f"RC-{next_index}",
                        "requirement_id": req_id,
                        "change_type": "add",
                        "field": "requirement",
                        "before": None,
                        "after": dict(req),
                        "reason": "Added by analyst draft update.",
                        "source_ids": list(source_ids),
                        "status": "proposed",
                    }
                )
                next_index += 1
                continue

            changed_fields = [
                field
                for field in (
                    "text",
                    "priority",
                    "stakeholder",
                    "source",
                )
                if before.get(field) != req.get(field)
            ]
            if not changed_fields:
                continue
            for field in changed_fields:
                key = ("update", req_id, field)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                candidates.append(
                    {
                        "id": f"RC-{next_index}",
                        "requirement_id": req_id,
                        "change_type": "update",
                        "field": field,
                        "before": before.get(field),
                        "after": req.get(field),
                        "reason": "Updated by analyst draft refresh after decisions/discussions.",
                        "source_ids": list(source_ids),
                        "status": "proposed",
                    }
                )
                next_index += 1

        return candidates


    def invoke_requirements_analyst_text(
        self, task: str, context: Dict[str, Any], *, mode: str = "analysis"
    ) -> str:
        self.validate_skill_usage("requirements-analyst")
        skill = get_skill("requirements-analyst")
        skill_content = str(skill.get("content") or "")
        selected_guidance = requirements_skill_guidance(skill_content, mode)
        prompt = (
            "# Skill: requirements-analyst\n\n"
            f"{selected_guidance}\n\n"
            "# 任務\n\n"
            f"{task}"
        )
        messages = self.build_direct_messages(prompt, context=context)
        if self.tools:
            return self.chat_with_tools(messages, active_skill="requirements-analyst")
        return self.model.chat(messages, action=self.usage_action("skill.requirements-analyst"))

    def invoke_requirements_analyst_object_json(
        self, task: str, context: Dict[str, Any], *, mode: str = "analysis"
    ) -> Dict[str, Any]:
        raw = self.invoke_requirements_analyst_text(task, context, mode=mode)
        return parse_json_object(raw)

    def invoke_requirements_analyst_array_json(
        self, task: str, context: Dict[str, Any], *, mode: str = "analysis"
    ) -> List[Any]:
        raw = self.invoke_requirements_analyst_text(task, context, mode=mode)
        return parse_json_array(raw)

    def invoke_direct_requirements_text(
        self, task: str, context: Dict[str, Any], *, action: str
    ) -> str:
        messages = self.build_direct_messages(task, context=context)
        return self.model.chat(messages, action=self.usage_action(action))

    def invoke_direct_requirements_object_json(
        self, task: str, context: Dict[str, Any], *, action: str
    ) -> Dict[str, Any]:
        raw = self.invoke_direct_requirements_text(task, context, action=action)
        return parse_json_object(raw)

    def invoke_direct_requirements_array_json(
        self, task: str, context: Dict[str, Any], *, action: str
    ) -> List[Any]:
        raw = self.invoke_direct_requirements_text(task, context, action=action)
        return parse_json_array(raw)
