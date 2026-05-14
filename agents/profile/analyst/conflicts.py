# Analyst conflict logic: detect, recheck, sign off, and report requirement conflicts.
import json
import re
from typing import Any, Dict, List, Optional

from storage.markdown import clean_llm_output

from .requirements import requirement_discussion_pool
from .validation import conflict_records, signoff_decisions


class AnalystConflicts:
    def run_conflict_analysis_loop(self, action: str, **context: Any) -> Any:
        opa = self.run_action_loop(
            name="conflict_analysis",
            max_iterations=3,
            loop_cap=self.agent_loop_round_cap(),
            context={
                "conflict_action": action,
                **context,
            },
            build_observation=self.build_conflict_analysis_observation,
            decide_action=self.decide_conflict_analysis_action,
            execute_action=self.execute_conflict_analysis_action,
        )
        trace = opa.get("opa_trace") or []
        result = dict((trace[-1].get("result") if trace else {}) or {})
        if result.get("error"):
            raise RuntimeError(result.get("error"))
        return result.get("output")

    def build_conflict_analysis_observation(self, **kwargs: Any) -> Dict[str, Any]:
        artifact = kwargs.get("artifact") or {}
        return {
            "action": kwargs.get("conflict_action", ""),
            "iteration": kwargs.get("iteration", 0) + 1,
            "max_iterations": kwargs.get("max_iterations", 3),
            "requirements_count": len(requirement_discussion_pool(artifact)),
            "conflicts_count": len(artifact.get("conflicts", []) or []),
            "discussion_rows_count": len(kwargs.get("discussion_rows") or []),
            "proposal_count": len(kwargs.get("proposal_list") or []),
        }

    def decide_conflict_analysis_action(
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
                "reasoning": "上一輪 conflict analysis 任務已完成，結束本次分析。",
            }
        action = str(observation.get("action") or "").strip()
        return {
            "action": action,
            "params": {},
            "reasoning": f"執行 Analyst conflict analysis 任務：{action}。",
        }

    def execute_conflict_analysis_action(
        self,
        *,
        decision: Dict[str, Any],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        action = str(decision.get("action") or "").strip()
        try:
            if action == "run_conflict_detection":
                output = self.execute_conflict_detection(kwargs.get("artifact") or {})
            elif action == "run_pairwise_conflict_detection":
                output = self.execute_pairwise_conflict_detection(kwargs.get("artifact") or {})
            elif action == "run_group_conflict_detection":
                output = self.execute_group_conflict_detection(kwargs.get("artifact") or {})
            elif action == "signoff_conflict_recheck":
                output = self.execute_signoff_conflict_recheck(
                    kwargs.get("proposal_list") or [],
                    kwargs.get("discussion_rows") or [],
                    kwargs.get("extracted_pair_reviews"),
                )
            elif action == "generate_conflict_report":
                output = self.build_conflict_analysis_report(
                    kwargs.get("artifact") or {},
                    round_num=kwargs.get("round_num"),
                    recent_decisions_limit=kwargs.get("recent_decisions_limit"),
                    previous_report=kwargs.get("previous_report"),
                )
            elif action == "get_resolution_options_for_issue":
                output = self.fetch_resolution_options_for_issue(
                    kwargs.get("issue") or {},
                    kwargs.get("artifact") or {},
                )
            else:
                raise ValueError(f"未知 conflict action: {action}")
        except Exception as e:
            return {
                "action": action,
                "status": "failed",
                "error": str(e),
                "summary": f"conflict analysis failed: {action}",
            }
        return {
            "action": action,
            "status": "success",
            "output": output,
            "context_updates": {"artifact": output} if isinstance(output, dict) else {},
            "summary": f"完成 conflict analysis: {action}",
        }

    def run_conflict_detection(self, artifact: Dict) -> Dict:
        steps = [
            {
                "id": "pairwise_conflict_detection",
                "action": "run_pairwise_conflict_detection",
                "reasoning": "先執行相鄰兩兩需求衝突判斷。",
            }
        ]
        if bool((artifact.get("meta") or {}).get("enable_group_conflict_check", True)):
            steps.append(
                {
                    "id": "group_conflict_detection",
                    "action": "run_group_conflict_detection",
                    "reasoning": "再檢查三個以上需求共同成立時才會出現的群組衝突。",
                }
            )
        return self.run_conflict_analysis_loop(
            "run_conflict_detection",
            artifact=artifact,
            action_plan={
                "goal": "先做兩兩需求衝突判斷，再視設定做 3+ 群組衝突判斷。",
                "steps": steps,
            },
        )

    def run_pairwise_conflict_detection(self, artifact: Dict) -> Dict:
        return self.run_conflict_analysis_loop(
            "run_pairwise_conflict_detection",
            artifact=artifact,
        )

    def signoff_conflict_recheck(
        self,
        proposal_list: List[Dict[str, Any]],
        discussion_rows: List[Dict[str, Any]],
        extracted_pair_reviews: Optional[List[Dict[str, Any]]] = None,
    ) -> tuple[List[Dict[str, Any]], str]:
        output = self.run_conflict_analysis_loop(
            "signoff_conflict_recheck",
            proposal_list=proposal_list,
            discussion_rows=discussion_rows,
            extracted_pair_reviews=extracted_pair_reviews,
        )
        if isinstance(output, tuple):
            return output
        return [], ""

    def generate_conflict_report(
        self,
        artifact: Dict[str, Any],
        round_num: Optional[int] = None,
        recent_decisions_limit: Optional[int] = None,
        previous_report: Optional[str] = None,
    ) -> str:
        return self.run_conflict_analysis_loop(
            "generate_conflict_report",
            artifact=artifact,
            round_num=round_num,
            recent_decisions_limit=recent_decisions_limit,
            previous_report=previous_report,
        ) or ""

    def run_pair_conflict_detection(
        self,
        *,
        base_task: str,
        context: Dict[str, Any],
        pair_rows: List[Dict[str, Any]],
        pair_count: int,
        heading: str,
        extra_rules: List[str],
        rows_label: str,
        error_label: str,
    ) -> List[Dict[str, Any]]:
        rules = "\n".join(f"- {rule}" for rule in extra_rules)
        task = base_task + f"""

【{heading}】
{rules}

{rows_label}：
{json.dumps(pair_rows, ensure_ascii=False, indent=2)}

只輸出一個 JSON 物件：{{"conflicts":[...]}}。勿輸出 Markdown 或其他文字。"""
        try:
            raw = self.invoke_skill("conflict-analyzer", task, context=context)
            data = self.parse_issue_response_json(raw)
        except Exception as e:
            raise RuntimeError(f"{error_label}輸出格式不合格: {e}") from e
        return conflict_records(
            data.get("conflicts", []),
            pairwise_mode=True,
            pair_count=pair_count,
        )

    def conflict_detection_requirements(self, artifact: Dict) -> List[Dict[str, Any]]:
        return [
            req for req in (artifact.get("reqt_candidates") or [])
            if isinstance(req, dict)
            and str(req.get("id") or "").strip()
            and str(req.get("text") or "").strip()
        ]

    def conflict_detection_context(
        self,
        artifact: Dict,
        requirements: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        context: Dict[str, Any] = {"requirements": requirements}
        if artifact.get("stakeholders"):
            context["stakeholders"] = artifact["stakeholders"]
        if artifact.get("scope"):
            context["scope"] = artifact["scope"]
        return context

    def conflict_detection_base_task(self) -> str:
        return f"""請使用 conflict-analyzer skill 作為主要分析框架，僅根據 Context.requirements 對 requirement pair 產生初步 Conflict / Neutral label；Context.requirements 是 reqt_candidates 需求池，本步不看正式 requirements、系統模型或其他回饋。

核心問題：
- 這一步是 initial classification，不是最終裁定。
- 只根據兩條 requirement 原文與其直接語義判斷，不替需求補不存在的前提、設計方案或外部情境。
- conflict-analyzer skill 的類型與範例不是封閉清單；若 requirement 原文顯示其他會造成需求衝突、驗收衝突、責任不清、重複但不一致、scope 不清或需要先合併/刪除/改寫/人工裁定的原因，也應判為 Conflict。

判斷任務：
- label 只用英文 "Conflict" 或 "Neutral"。

Analyst 判準：
- 從需求意圖、scope boundary、acceptance boundary、SRS 條文品質、需求是否應合併/拆分、驗收標準是否一致來判斷。
- 若兩條需求會造成需求意圖不一致、scope 不清、acceptance boundary 不一致、條文重複但語意不同，或必須先合併/拆分/改寫/人工裁定才能清楚驗收，標為 Conflict。
- 若兩條需求描述同一 requirement slot、同一使用意圖或同一驗收責任，但 wording、限制、觸發條件、優先級或 acceptance criteria 不一致，標為 Conflict。
- 若需求衝突原因不在上述例子中，但會讓驗收、追蹤、責任分配或需求治理出現不可接受的不一致，也可標為 Conflict；description 必須明確說明該原因。
- Neutral 的 description 必須說明為什麼兩個需求不產生衝突。
- conflict_type 只是描述結果，不是產生 Conflict 的理由。

輸出要求：
- Conflict：需包含 description、requirement_ids 或 related_requirements；description 說明涉及哪些需求、衝突點與原因。
- Neutral：需包含 description；可選填 requirement_ids；description 說明為什麼兩個需求不產生衝突。
- requirement_ids 必須精確對應直接涉及的需求；無法明確對應就不要臆測。
"""

    def execute_pairwise_conflict_detection(self, artifact: Dict) -> Dict:
        """用 reqt_candidates 做相鄰兩兩需求衝突判斷。"""
        requirements = [
            req for req in (artifact.get("reqt_candidates") or [])
            if isinstance(req, dict)
            and str(req.get("id") or "").strip()
            and str(req.get("text") or "").strip()
        ]
        if len(requirements) < 2:
            return {**artifact, "conflicts": []}

        context = self.conflict_detection_context(artifact, requirements)
        base_task = self.conflict_detection_base_task()
        pair_rows = []
        for pair_index, start in enumerate(range(0, len(requirements) - 1, 2)):
            req_a = requirements[start]
            req_b = requirements[start + 1]
            pair_rows.append(
                {
                    "pair_index": pair_index,
                    "requirement_ids": [req_a.get("id"), req_b.get("id")],
                    "requirement_a": req_a.get("text"),
                    "requirement_b": req_b.get("text"),
                }
            )

        pair_conflicts = self.run_pair_conflict_detection(
            base_task=base_task,
            context=context,
            pair_rows=pair_rows,
            pair_count=len(pair_rows),
            heading="兩兩判斷",
            extra_rules=[
                "只判斷下列指定 pair，pair 之間互相獨立。",
                "配對方式固定為需求順序 1 對 2、3 對 4、5 對 6；若最後剩一筆需求，不判斷。",
                "每一個 pair 都必須輸出恰好一筆結果。",
                "pair_index 必須與下列清單一致。",
                "requirement_ids 必須使用下列 pair 的原始需求 id。",
                "不要輸出 3 條以上需求共同造成的群組衝突。",
            ],
            rows_label="指定 pairs",
            error_label="兩兩 Conflict 分析",
        )
        present_pairs = {
            int(x.get("pair_index"))
            for x in pair_conflicts
            if isinstance(x, dict) and isinstance(x.get("pair_index"), int)
        }
        missing_pairs = [i for i in range(len(pair_rows)) if i not in present_pairs]
        pair_conflict_count = len([x for x in pair_conflicts if x.get("label") == "Conflict"])
        pair_neutral_count = len([x for x in pair_conflicts if x.get("label") == "Neutral"])
        self.logger.info(
            "兩兩衝突判斷 %s 對（Conflict: %s，Neutral: %s，Missing: %s）",
            len(pair_rows),
            pair_conflict_count,
            pair_neutral_count,
            len(missing_pairs),
        )
        if missing_pairs:
            missing_rows = [pair_rows[i] for i in missing_pairs]
            self.logger.info("兩兩衝突補判 Missing %s 對", len(missing_rows))
            retry_conflicts = self.run_pair_conflict_detection(
                base_task=base_task,
                context=context,
                pair_rows=missing_rows,
                pair_count=len(pair_rows),
                heading="兩兩 Missing 補判",
                extra_rules=[
                    "只判斷下列 missing pair，pair 之間互相獨立。",
                    "每一個 missing pair 都必須輸出恰好一筆結果。",
                    "pair_index 必須與下列清單一致，不可重新編號。",
                    "requirement_ids 必須使用下列 pair 的原始需求 id。",
                    "不要輸出清單以外的 pair。",
                    "不要輸出 3 條以上需求共同造成的群組衝突。",
                ],
                rows_label="Missing pairs",
                error_label="兩兩 Missing 補判",
            )
            retry_by_pair = {
                int(row.get("pair_index")): row
                for row in retry_conflicts
                if isinstance(row, dict)
                and isinstance(row.get("pair_index"), int)
                and int(row.get("pair_index")) in set(missing_pairs)
            }
            existing_by_pair = {
                int(row.get("pair_index")): row
                for row in pair_conflicts
                if isinstance(row, dict) and isinstance(row.get("pair_index"), int)
            }
            existing_by_pair.update(retry_by_pair)
            pair_conflicts = [
                existing_by_pair[i]
                for i in range(len(pair_rows))
                if i in existing_by_pair
            ]
            still_missing = [
                i for i in range(len(pair_rows))
                if i not in existing_by_pair
            ]
            self.logger.info(
                "兩兩衝突補判完成（補回 %s，仍 Missing: %s）",
                len(retry_by_pair),
                len(still_missing),
            )
            if still_missing:
                raise RuntimeError(f"兩兩 Conflict 分析仍缺少 pair_index: {still_missing}")

        return {**artifact, "conflicts": pair_conflicts}

    def execute_group_conflict_detection(self, artifact: Dict) -> Dict:
        """用 reqt_candidates 做 3+ 需求群組衝突判斷，並附加到既有兩兩結果。"""
        requirements = self.conflict_detection_requirements(artifact)
        if len(requirements) < 3:
            self.logger.info("整體衝突判斷：0 筆 3+ 需求衝突")
            return artifact
        context = self.conflict_detection_context(artifact, requirements)
        base_task = self.conflict_detection_base_task()
        holistic_task = base_task + """

【整體判斷】
- 只找出需要 3 條以上需求同時成立才會產生的群組衝突。
- 不要重複輸出兩兩 pair 已可判斷的衝突。
- 每筆 Conflict 的 requirement_ids 必須包含 3 個以上需求 id。
- 若沒有 3 條以上需求共同造成的衝突，輸出 {"conflicts": []}。
- 本步只輸出 label="Conflict" 的項目，不需要輸出 Neutral。

只輸出一個 JSON 物件：{"conflicts":[...]}。勿輸出 Markdown 或其他文字。"""
        try:
            holistic_raw = self.invoke_skill(
                "conflict-analyzer", holistic_task, context=context
            )
            holistic_data = self.parse_issue_response_json(holistic_raw)
        except Exception as e:
            raise RuntimeError(f"整體 Conflict 分析輸出格式不合格: {e}") from e
        holistic_conflicts = [
            row for row in conflict_records(holistic_data.get("conflicts", []))
            if row.get("label") == "Conflict"
            and len(row.get("requirement_ids") or []) >= 3
        ]
        self.logger.info("整體衝突判斷：%s 筆 3+ 需求衝突", len(holistic_conflicts))

        merged: List[Dict[str, Any]] = [
            dict(row) for row in (artifact.get("conflicts") or [])
            if isinstance(row, dict)
        ]
        for row in holistic_conflicts:
            item = dict(row)
            item["id"] = f"PAIR-{len(merged) + 1}"
            merged.append(item)
        return {**artifact, "conflicts": merged}

    def execute_conflict_detection(self, artifact: Dict) -> Dict:
        """相容入口：先做兩兩判斷，再做 3+ 需求整體衝突判斷。"""
        updated = self.execute_pairwise_conflict_detection(artifact)
        if bool((artifact.get("meta") or {}).get("enable_group_conflict_check", True)):
            updated = self.execute_group_conflict_detection(updated)
        return updated

    def execute_signoff_conflict_recheck(
        self,
        proposal_list: List[Dict[str, Any]],
        discussion_rows: List[Dict[str, Any]],
        extracted_pair_reviews: Optional[List[Dict[str, Any]]] = None,
    ) -> tuple[List[Dict[str, Any]], str]:
        """Analyst 根據逐 pair review、原文與會議發言做需求關係標籤確認。"""
        if not proposal_list:
            return [], ""
        prompt = (
            "你是資深需求分析師（Analyst）。請根據 requirement pair 原文與各 agent 的逐筆 pair_reviews，"
            "對每筆 Conflict/Neutral pair 做最終裁定。\n\n"
            f"# 待裁定項目\n{json.dumps(proposal_list, ensure_ascii=False, indent=2)}\n\n"
            f"# 各 agent 的 pair_reviews\n{json.dumps(extracted_pair_reviews or [], ensure_ascii=False, indent=2)}\n\n"
            f"# 補充會議內容（僅在 pair_reviews 不足時參考）\n{json.dumps(discussion_rows, ensure_ascii=False, indent=2)}\n\n"
            "# 裁定規則\n"
            "- 先看 requirements 原文清單，再看各 agent 的 pair_reviews。\n"
            "- 若只有兩筆需求，requirement_a / requirement_b 是前兩筆需求的別名。\n"
            "- discussion_rows 只在 pair_reviews 證據不足時作補充參考。\n"
            "- 若 pair_reviews 與 pair 原文足以支持改判，new_label 可改為 Conflict 或 Neutral。\n"
            "- 任一 agent 的 pair_review 若提出可由 requirements 原文支持的角色專屬有效證據，可作為改判依據；有效證據優先於多數同意或既有 current_label。\n"
            "- 若 extracted_pair_reviews 為空，仍須根據 requirements 原文重新裁定；不要只因缺少 review 就維持 current_label。\n"
            "- conflict-analyzer skill 的衝突類型不是封閉清單；若原文或 pair_reviews 顯示其他會造成 SRS 條文、驗收、責任、追蹤、scope 或需求治理不一致的原因，也可裁定為 Conflict。\n"
            "- Analyst 最終裁定角度：檢查 pair_reviews 是否指出 SRS 條文、scope、驗收、義務/風險、模型元素、流程、狀態、事件或輸出承諾層級的衝突。\n"
            "- 若任一 agent 的 pair_review 提出可由 requirement 原文支持的角色專屬衝突證據，應納入裁定；不要因其他 agent 說可同時實作就排除。\n"
            "- 不要因多個 agent 都說「可共存、互補、wording difference」就自動維持 Neutral；若 pair_reviews 顯示同一 requirement slot、capability、entity relationship 或 trigger-output pattern 存在不同需求承諾，仍應改判 Conflict。\n"
            "- 若 new_label 為 Neutral，reason 必須說明為什麼兩個需求不產生衝突。\n"
            "- 你必須對 proposal_list 中的每一個 pair 都輸出一筆 decision；即使決定維持 current_label，也不可省略。\n"
            "- 只輸出 JSON array，不要輸出 Markdown、程式碼區塊、前言或額外說明。\n"
            "- 請直接做最終裁定，不要重述整場會議。\n\n"
            "# 輸出 JSON array\n"
            '[{"id": "衝突ID", "new_label": "Conflict 或 Neutral", '
            '"reason": "一句繁中裁定理由"}]'
        )
        messages = self.build_direct_messages(prompt)
        raw = (self.model.chat(messages, action="conflict_recheck_signoff") or "").strip()
        text = raw
        if text.startswith("```json"):
            text = text[len("```json") :].strip()
        elif text.startswith("```"):
            text = text[len("```") :].strip()
        if text.endswith("```"):
            text = text[:-3].strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"(\[[\s\S]*\])", text)
            if match:
                try:
                    data = json.loads(match.group(1))
                except json.JSONDecodeError:
                    data = None
            else:
                data = None
        return signoff_decisions(data), raw

    def finalize_conflict_review_reasons(
        self,
        decision_list: List[Dict[str, Any]],
        discussion_rows: List[Dict[str, Any]],
        extracted_pair_reviews: Optional[List[Dict[str, Any]]] = None,
    ) -> tuple[List[Dict[str, str]], str]:
        """Analyst rewrites final conflict-review reasons after labels are fixed."""
        if not decision_list:
            return [], ""
        prompt = (
            "以下每筆 Conflict/Neutral pair 的 final_label 已經決定。"
            "請在不改變 final_label 的前提下，整理一段可放入 record 的最終理由。\n\n"
            f"# 已決定的 pairs\n{json.dumps(decision_list, ensure_ascii=False, indent=2)}\n\n"
            f"# 各 agent 的 pair_reviews\n{json.dumps(extracted_pair_reviews or [], ensure_ascii=False, indent=2)}\n\n"
            f"# 補充會議內容\n{json.dumps(discussion_rows, ensure_ascii=False, indent=2)}\n\n"
            "# 規則\n"
            "- 不可新增、刪除或改變任何 pair 的 final_label/new_label。\n"
            "- reason 必須根據 requirement 原文、各 agent 的 pair_reviews 與最終裁定整理。\n"
            "- reason 要清楚說明為什麼最後維持或改成該標籤。\n"
            "- 只輸出 JSON array，不要輸出 Markdown、程式碼區塊、前言或額外說明。\n\n"
            "# 輸出 JSON array\n"
            '[{"id": "衝突ID", "reason": "最終裁定理由"}]'
        )
        messages = self.build_direct_messages(prompt)
        raw = (self.model.chat(messages, action="conflict_recheck_final_reason") or "").strip()
        text = raw
        if text.startswith("```json"):
            text = text[len("```json") :].strip()
        elif text.startswith("```"):
            text = text[len("```") :].strip()
        if text.endswith("```"):
            text = text[:-3].strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"(\[[\s\S]*\])", text)
            if match:
                try:
                    data = json.loads(match.group(1))
                except json.JSONDecodeError:
                    data = None
            else:
                data = None
        if not isinstance(data, list):
            return [], raw
        out: List[Dict[str, str]] = []
        valid_ids = {
            str(row.get("id") or "").strip()
            for row in decision_list
            if isinstance(row, dict) and str(row.get("id") or "").strip()
        }
        for row in data:
            if not isinstance(row, dict):
                continue
            pair_id = str(row.get("id") or "").strip()
            reason = str(row.get("reason") or "").strip()
            if pair_id in valid_ids and reason:
                out.append({"id": pair_id, "reason": reason})
        return out, raw

    def build_conflict_analysis_report(
        self,
        artifact: Dict[str, Any],
        round_num: Optional[int] = None,
        recent_decisions_limit: Optional[int] = None,
        previous_report: Optional[str] = None,
    ) -> str:
        """依 conflict-analyzer skill 與 assets/conflict_report_template.json 結構，從 artifact 產出需求 Conflict 分析報告（Markdown）；含所有 Conflict（含已解決）並標示是否已解決。"""
        _ = recent_decisions_limit
        decisions = artifact.get("decisions", [])
        all_conflicts = artifact.get("conflicts", [])
        context = {
            "conflicts": all_conflicts,
            "requirements": requirement_discussion_pool(artifact),
            "stakeholders": artifact.get("stakeholders", []),
            "scope": artifact.get("scope", {}),
            "project_overview": (artifact.get("scope") or {}).get("description", ""),
            "open_questions": artifact.get("open_questions", []),
            "decisions": decisions,
            "round_num": round_num,
        }
        previous_report_text = (previous_report or "").strip()
        if previous_report_text:
            context["previous_conflict_report"] = previous_report_text
            task = """依本 skill 與 conflict_report_template.json（已在 skill 附件中），根據 Context.previous_conflict_report 與最新 Context 修訂需求 Conflict 分析報告。

規則：
- Context.conflicts 全部都要列入。
- label=Conflict 視為 unresolved；label=Neutral 視為 resolved。
- resolved / unresolved 統計請與此規則一致。
- 這是報告迭代修訂，不是從零重寫；保留上一版仍有效的章節與文字。
- 若上一版內容已被最新 conflicts、requirements 或 decisions 推翻，必須更新或移除。
- 本報告只整理需求關係、衝突狀態、影響需求與待確認缺口。
- 其餘章節依 report_template 結構整理。

只輸出 Markdown，勿輸出 JSON 或程式碼區塊。"""
        else:
            task = """依本 skill 與 conflict_report_template.json（已在 skill 附件中）產出需求 Conflict 分析報告。

規則：
- Context.conflicts 全部都要列入。
- label=Conflict 視為 unresolved；label=Neutral 視為 resolved。
- resolved / unresolved 統計請與此規則一致。
- 本報告只整理需求關係、衝突狀態、影響需求與待確認缺口。
- 其餘章節依 report_template 結構整理。

只輸出 Markdown，勿輸出 JSON 或程式碼區塊。"""
        try:
            raw = self.invoke_skill("conflict-analyzer", task, context=context)
        except Exception as e:
            self.logger.warning("conflict report 生成失敗: %s", e)
            return f"# 需求 Conflict 分析報告\n\n（報告生成失敗: {e}）"
        out = clean_llm_output(raw)
        if not out:
            self.logger.warning("conflict report 無內容")
            return "# 需求 Conflict 分析報告\n\n（報告無內容）"
        return out
