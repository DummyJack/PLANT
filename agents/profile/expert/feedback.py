# Handles module workflow behavior.
import json
import re

from agents.skills.base import get_skill
from storage import parse_first_json

from .actions.feedback import update_feedback
from .actions.read_reference import read_docs
from .actions.research import research_issue
from .plan import ExpertResearchPlan
from .repair import repair_action_output
from .skill import domain_skill_subset

from .validation import clean_feedback, clean_research_result, requires_url_sources, source_records, source_urls


# ========
# Defines empty feedback marker function for this module workflow.
# ========
def empty_feedback_marker(reason: str) -> dict:
    return {
        "findings": [],
        "sources": [],
        "constraints": [],
        "risks": [],
        "recommendations": [],
        "status": "no_applicable_feedback",
        "reason": reason,
    }


# ========
# Defines research requirement candidates function for this module workflow.
# ========
def research_requirement_candidates(artifact):
    rows = []
    for req in artifact.get("URL") or []:
        if not isinstance(req, dict) or not str(req.get("text") or "").strip():
            continue
        row = {
            "id": req.get("id"),
            "text": req.get("text"),
            "priority": req.get("priority"),
            "source": req.get("source", ""),
        }
        rows.append(row)
    return rows


# ========
# Defines research stakeholders function for this module workflow.
# ========
def research_stakeholders(artifact):
    rows = []
    for stakeholder in artifact.get("stakeholders") or []:
        if not isinstance(stakeholder, dict):
            continue
        name = str(stakeholder.get("name") or "").strip()
        if not name:
            continue
        row = {"name": name}
        stakeholder_type = str(stakeholder.get("type") or "").strip()
        if stakeholder_type:
            row["type"] = stakeholder_type
        rows.append(row)
    return rows


# ========
# Defines research open questions function for this module workflow.
# ========
def research_open_questions(artifact):
    rows = []
    for question in artifact.get("open_questions") or []:
        if not isinstance(question, dict):
            continue
        text = str(question.get("question") or "").strip()
        if not text:
            continue
        rows.append(
            {
                "question": text,
                "status": question.get("status"),
                "type": question.get("type"),
            }
        )
    return rows


# ========
# Defines feedback keywords function for this module workflow.
# ========
def feedback_keywords(text: str) -> set[str]:
    normalized = str(text or "").lower()
    keywords = set(re.findall(r"[A-Za-z0-9_]+", normalized))
    for term in (
        "付款",
        "支付",
        "金流",
        "退款",
        "通知",
        "申訴",
        "客服",
        "補償",
        "個資",
        "隱私",
        "資料",
        "交易",
        "紀錄",
        "保存",
        "稽核",
        "安全",
        "外送員",
        "餐廳",
        "消費者",
        "第三方",
        "責任",
        "異常",
        "訂單",
    ):
        if term in normalized:
            keywords.add(term)
    return keywords


# ========
# Defines infer feedback requirement refs function for this module workflow.
# ========
def infer_feedback_requirement_refs(text: str, artifact: dict) -> list[str]:
    item_keywords = feedback_keywords(text)
    if not item_keywords:
        return []
    matches: list[tuple[int, str]] = []
    for req in research_requirement_candidates(artifact):
        req_id = str(req.get("id") or "").strip()
        req_text = str(req.get("text") or "").strip()
        if not req_id or not req_text:
            continue
        overlap = item_keywords & feedback_keywords(req_text)
        score = len(overlap)
        if score:
            matches.append((score, req_id))
    matches.sort(key=lambda row: (-row[0], row[1]))
    return [req_id for _, req_id in matches[:5]]


# ========
# Defines normalize feedback links function for this module workflow.
# ========
def normalize_feedback_links(feedback: dict, artifact: dict) -> dict:
    if not isinstance(feedback, dict):
        return feedback
    for section in ("findings", "constraints", "risks", "recommendations"):
        rows = feedback.get(section)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            row.pop("sources", None)
            refs = [
                str(value).strip()
                for value in (row.get("related_requirement_ids") or [])
                if str(value).strip()
            ]
            if not refs:
                refs = infer_feedback_requirement_refs(str(row.get("text") or ""), artifact)
            row["related_requirement_ids"] = list(dict.fromkeys(refs))
    return feedback


# ========
# Defines research source function for this module workflow.
# ========
def research_source(artifact):
    issue = artifact.get("current_issue") if isinstance(artifact.get("current_issue"), dict) else {}
    meeting_id = str(issue.get("meeting_id") or "").strip()
    if meeting_id:
        return meeting_id
    issue_id = str(issue.get("id") or "").strip()
    if issue_id:
        return issue_id
    return "initial"

# ========
# Defines ExpertDomainResearch class for this module workflow.
# ========
class ExpertDomainResearch(ExpertResearchPlan):
    # Defines obs research function for this module workflow.
    def obs_research(self, **kwargs):
        return self.obs_research_state(
            kwargs["artifact"],
            kwargs.get("research_results", []),
            kwargs.get("iteration", 0),
            kwargs["max_iterations"],
            kwargs.get("actions_taken", []),
        )

    # Defines decide research function for this module workflow.
    def decide_research(self, *, observation, last_result=None, **kwargs):
        return self.plan_research(observation, last_result)

    # Defines run research step function for this module workflow.
    def run_research_step(self, *, decision, **kwargs):
        return self.run_research_action(
            decision.get("action", "done"),
            decision.get("params") or {},
            kwargs["artifact"],
            kwargs.get("research_results", []),
        )

    # Defines run research loop function for this module workflow.
    def run_research_loop(self, artifact):
        result = self.run_action_loop(
            name="research_domain",
            context={
                "artifact": artifact,
                "research_results": [],
            },
            obs_fn=self.obs_research,
            decide_action=self.decide_research,
            execute_action=self.run_research_step,
        )
        return result

    # Defines obs research state function for this module workflow.
    def obs_research_state(
        self, artifact,
        research_results, iteration, max_iterations, actions_taken=None,
    ):
        url_requirements = research_requirement_candidates(artifact)
        existing = artifact.get("feedback") if isinstance(artifact.get("feedback"), dict) else {}
        scenario_source = artifact.get("scenario") or artifact.get("rough_idea")
        return {
            "issue": artifact.get("current_issue") if isinstance(artifact.get("current_issue"), dict) else {},
            "scenario": str(scenario_source or "").strip(),
            "scope": artifact.get("scope", {}),
            "URL": url_requirements,
            "REQ": artifact.get("REQ", []) if isinstance(artifact.get("REQ"), list) else [],
            "stakeholders": research_stakeholders(artifact),
            "open_questions": research_open_questions(artifact),
            "has_existing_research": bool(existing),
            "research_results_count": len(research_results),
            "document_evidence_count": len(artifact.get("document_evidence", []) or []),
            "has_read_file": "read_file" in self.tools,
            "has_web_search": "web_search" in self.tools,
            "actions_taken": actions_taken or [],
            "iteration": iteration + 1,
            "max_iterations": max_iterations,
        }

    # Defines run research action function for this module workflow.
    def run_research_action(
        self, action, params, artifact, research_results,
    ):
        obs: dict = {"action": action, "result": None, "error": None, "summary": ""}

        if action == "read_reference_docs":
            if "read_file" not in self.tools:
                obs["summary"] = "read_file 工具不可用，略過文件讀取"
                obs["result"] = {"document_evidence": [], "gaps": ["read_file 工具不可用"]}
                return obs
            query = str(params.get("query") or params.get("topic") or "").strip()
            if not query:
                obs["error"] = "query 參數為空"
                obs["summary"] = "文件讀取失敗：未提供查詢問題"
                return obs
            scenario_source = artifact.get("scenario") or artifact.get("rough_idea")
            meta = artifact.get("meta") if isinstance(artifact.get("meta"), dict) else {}
            attached_references = [
                str(path).strip()
                for path in (meta.get("attached_references") or [])
                if str(path).strip()
            ]
            context = {
                "issue": artifact.get("current_issue") if isinstance(artifact.get("current_issue"), dict) else {},
                "scenario": str(scenario_source or "").strip(),
                "scope": artifact.get("scope", {}),
                "URL": research_requirement_candidates(artifact),
                "REQ": artifact.get("REQ", []) if isinstance(artifact.get("REQ"), list) else [],
                "stakeholders": research_stakeholders(artifact),
                "open_questions": research_open_questions(artifact),
                "existing_document_evidence": artifact.get("document_evidence", []) or [],
                "attached_references": attached_references,
            }
            task = read_docs(query=query, attached_references=attached_references)
            try:
                skill = domain_skill_subset(get_skill("domain-research"), "read_docs")
                raw = self.chat_with_tools(
                    self.build_skill_messages(skill, "domain-research", task, context=context),
                    active_skill="domain-research",
                )
                data = self.parse_research_json(
                    raw,
                    action=action,
                    source_ref=research_source(artifact),
                )
                evidence = self.clean_document_evidence(data.get("document_evidence"))
                gaps = [
                    str(item).strip()
                    for item in (data.get("gaps") or [])
                    if str(item).strip()
                ]
                artifact["document_evidence"] = self.merge_document_evidence(
                    artifact.get("document_evidence", []),
                    evidence,
                )
                obs["result"] = {"document_evidence": evidence, "gaps": gaps}
                obs["context_updates"] = {"artifact": artifact}
                obs["summary"] = f"文件證據 {len(evidence)} 筆，缺口 {len(gaps)} 筆"
            except Exception as e:
                obs["error"] = str(e)
                obs["summary"] = f"文件讀取失敗: {e}"
            return obs

        if action == "research_issue":
            query = params.get("query", "")
            if not query:
                obs["error"] = "query 參數為空"
                obs["summary"] = "研究失敗：未提供研究問題"
                return obs
            value_reason = str(params.get("value_reason") or "").strip()
            scenario_source = artifact.get("scenario") or artifact.get("rough_idea")
            context = {
                "issue": artifact.get("current_issue") if isinstance(artifact.get("current_issue"), dict) else {},
                "scenario": str(scenario_source or "").strip(),
                "scope": artifact.get("scope", {}),
                "URL": research_requirement_candidates(artifact),
                "REQ": artifact.get("REQ", []) if isinstance(artifact.get("REQ"), list) else [],
                "stakeholders": research_stakeholders(artifact),
                "open_questions": research_open_questions(artifact),
                "document_evidence": artifact.get("document_evidence", []) or [],
            }
            web_search_evidence = ""
            web_urls = []
            if "web_search" in self.tools:
                search_tool = self.tools["web_search"]
                if callable(getattr(search_tool, "reset_session", None)):
                    search_tool.reset_session()
                web_search_evidence = search_tool.execute(
                    query=query,
                    max_results=5,
                    user_question=query,
                )
                web_urls = source_urls(web_search_evidence)
                context["web_search_evidence"] = web_search_evidence
                context["web_search_urls"] = web_urls
            source_ref = research_source(artifact)
            task = research_issue(
                query=query,
                source_ref=source_ref,
                value_reason=value_reason,
            )
            skill = domain_skill_subset(get_skill("domain-research"), "research")
            messages = self.build_skill_messages(skill, "domain-research", task, context=context)
            try:
                raw = (
                    self.chat_with_tools(
                        messages,
                        active_skill="domain-research",
                    )
                    if self.tools
                    else self.model.chat(messages)
                )
                result = self.clean_research_json(
                    raw,
                    action=action,
                    source_ref=source_ref,
                    cleaner=clean_research_result,
                    url_sources=web_urls,
                )
                if result:
                    research_results.append(
                        {
                            "query": query,
                            "value_reason": value_reason,
                            "research_evidence": result,
                        }
                    )
                obs["result"] = {"research_evidence": result} if result else {"research_evidence": {}}
                if result:
                    obs["summary"] = (
                        f"研究 '{query}': "
                        f"{len(result.get('findings', []))} 項發現"
                    )
                else:
                    obs["summary"] = f"研究 '{query}': 未取得可寫入 feedback 的 URL 證據"
            except Exception as e:
                obs["error"] = str(e)
                obs["summary"] = f"研究失敗: {e}"
            return obs

        if action == "update_feedback":
            if not research_results:
                artifact["feedback"] = empty_feedback_marker("domain research completed without URL-backed findings")
                obs["result"] = {"feedback": artifact["feedback"]}
                obs["summary"] = "無 URL 支撐的研究結果可更新，已標記領域研究完成"
                return obs
            existing = artifact.get("feedback") if isinstance(artifact.get("feedback"), dict) else {}
            context = {
                "research_results": research_results,
                "existing_research": existing,
                "document_evidence": artifact.get("document_evidence", []) or [],
            }
            source_ref = research_source(artifact)
            task = update_feedback(source_ref=source_ref)
            try:
                skill = domain_skill_subset(get_skill("domain-research"), "feedback")
                messages = self.build_skill_messages(skill, "domain-research", task, context=context)
                raw = self.run_skill_messages("domain-research", messages)
                dr = self.clean_research_json(
                    raw,
                    action=action,
                    source_ref=source_ref,
                    cleaner=clean_feedback,
                )
                if dr:
                    dr = normalize_feedback_links(dr, artifact)
                    merged = self.merge_feedback(existing, dr)
                    artifact["feedback"] = merged
                    obs["result"] = {"feedback": dr, "merged_feedback": merged}
                    obs["summary"] = "已更新領域研究資料"
                else:
                    artifact["feedback"] = existing or empty_feedback_marker("domain research produced no valid feedback rows")
                    obs["result"] = {"feedback": {}, "merged_feedback": artifact["feedback"]}
                    obs["summary"] = "無新增有效 feedback rows"
            except Exception as e:
                obs["error"] = str(e)
                obs["summary"] = f"更新失敗: {e}"
            return obs

        obs["error"] = f"未知動作: {action}"
        return obs

    # Defines parse research json function for this module workflow.
    def parse_research_json(self, raw, *, action: str, source_ref: str):
        try:
            return parse_first_json(raw)
        except Exception as e:
            repair_task = repair_action_output(
                action=action,
                raw=raw,
                error=str(e),
                source_ref=source_ref,
            )
            repaired = self.model.chat(self.build_direct_messages(repair_task))
            return parse_first_json(repaired)

    # Defines clean research json function for this module workflow.
    def clean_research_json(self, raw, *, action: str, source_ref: str, cleaner, url_sources=None):
        data = self.parse_research_json(raw, action=action, source_ref=source_ref)
        cleaned = cleaner(data, context_source=source_ref)
        cleaned = self.attach_url_sources(cleaned, url_sources)
        if cleaned and not self.missing_url_sources(cleaned):
            return cleaned
        error = "輸出缺少有效 findings / constraints / risks / recommendations"
        if cleaned:
            error = "輸出包含外部法規、標準、官方文件或合規主張，但 sources 缺少完整 URL"
        repair_task = repair_action_output(
            action=action,
            raw=data,
            error=error,
            source_ref=source_ref,
        )
        repaired = self.model.chat(self.build_direct_messages(repair_task))
        repaired_cleaned = cleaner(parse_first_json(repaired), context_source=source_ref)
        repaired_cleaned = self.attach_url_sources(repaired_cleaned, url_sources)
        if self.missing_url_sources(repaired_cleaned):
            raise ValueError("Expert feedback with external claims must include URL sources")
        return repaired_cleaned

    @staticmethod
    # Defines attach URL sources function for this module workflow.
    def attach_url_sources(payload, urls):
        if not isinstance(payload, dict):
            return payload
        merged = []
        seen = set()
        for source in source_records(list(payload.get("sources") or []) + list(urls or [])):
            url = str(source.get("url") or "").strip()
            if url and url not in seen:
                merged.append(source)
                seen.add(url)
        payload["sources"] = merged
        return payload

    @staticmethod
    # Defines merge feedback function for this module workflow.
    def merge_feedback(existing, delta):
        def row_key(row):
            if not isinstance(row, dict):
                return ""
            text = " ".join(str(row.get("text") or "").split()).lower()
            related = tuple(
                sorted(
                    str(value).strip()
                    for value in (row.get("related_requirement_ids") or [])
                    if str(value).strip()
                )
            )
            source = str(row.get("source") or "").strip()
            return json.dumps([text, related, source], ensure_ascii=False)

        merged = {"findings": [], "constraints": [], "risks": [], "recommendations": [], "sources": []}
        for section in ("findings", "constraints", "risks", "recommendations"):
            seen = set()
            for payload in (existing, delta):
                rows = payload.get(section) if isinstance(payload, dict) else []
                for row in rows or []:
                    if not isinstance(row, dict):
                        continue
                    key = row_key(row)
                    if not key or key in seen:
                        continue
                    merged[section].append(dict(row))
                    seen.add(key)

        seen_urls = set()
        for payload in (existing, delta):
            for source in source_records((payload.get("sources") if isinstance(payload, dict) else []) or []):
                url = str(source.get("url") or "").strip()
                if not url or url in seen_urls:
                    continue
                merged["sources"].append(source)
                seen_urls.add(url)

        return {
            key: value
            for key, value in merged.items()
            if value
        }

    @staticmethod
    # Defines missing URL sources function for this module workflow.
    def missing_url_sources(payload):
        return bool(payload) and requires_url_sources(payload) and not payload.get("sources")

    @staticmethod
    # Defines clean document evidence function for this module workflow.
    def clean_document_evidence(raw):
        rows = []
        seen = set()
        for item in raw or []:
            if not isinstance(item, dict):
                continue
            source = str(item.get("source") or "").strip()
            summary = str(item.get("summary") or "").strip()
            if not source or not summary:
                continue
            row = {
                "source": source,
                "summary": summary,
                "related_requirement_ids": [
                    str(value).strip()
                    for value in (item.get("related_requirement_ids") or [])
                    if str(value).strip()
                ],
            }
            section = str(item.get("section") or "").strip()
            if section:
                row["section"] = section
            key = json.dumps(row, ensure_ascii=False, sort_keys=True)
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
        return rows

    @classmethod
    # Defines merge document evidence function for this module workflow.
    def merge_document_evidence(cls, existing, new_rows):
        rows = cls.clean_document_evidence(existing)
        seen = {
            json.dumps(row, ensure_ascii=False, sort_keys=True)
            for row in rows
        }
        for row in cls.clean_document_evidence(new_rows):
            key = json.dumps(row, ensure_ascii=False, sort_keys=True)
            if key in seen:
                continue
            rows.append(row)
            seen.add(key)
        return rows
