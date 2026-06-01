# Analyst conflict logic: detect, recheck, sign off, and report requirement conflicts.
from agents.profile.prompt_catalog import render_prompt
import json
import re
from typing import Any, Dict, List, Optional

from storage.markdown import clean_llm_output
from agents.skills.base import get_skill
from agents.profile.scenario import scenario_prompt_value
from agents.profile.conflict_review import CONFLICT_REVIEW_LABEL_RULES

from .conflict_store import (
    conflict_entries_count,
    set_multiple_conflicts,
    set_pair_conflicts,
)
from .requirements import requirement_discussion_pool
from .validation import conflict_records, signoff_decisions
from .prompts import conflict_skill_subset


CONFLICT_TYPE_VALUES = {
    "logical",
    "technical",
    "resource",
    "temporal",
    "data",
    "state",
    "priority",
    "scope",
    "other",
}


def conflict_type_guidance_from_skill() -> str:
    skill = get_skill("conflict-analyzer")
    skill_dir = skill["path"].parent
    patterns_path = skill_dir / "references" / "conflict_patterns.md"
    try:
        content = patterns_path.read_text(encoding="utf-8")
    except OSError:
        content = ""
    rows: List[str] = []
    for match in re.finditer(r"^## ([A-Za-z]+) Conflicts\s*$", content, flags=re.MULTILINE):
        title = match.group(1).strip().lower()
        if title not in CONFLICT_TYPE_VALUES:
            continue
        start = match.end()
        next_match = re.search(r"^## ", content[start:], flags=re.MULTILINE)
        section = content[start : start + next_match.start()] if next_match else content[start:]
        desc_match = re.search(r"### Description\s*(.*?)(?:\n### |\Z)", section, flags=re.DOTALL)
        description = ""
        if desc_match:
            description = " ".join(desc_match.group(1).strip().split())
        if description:
            rows.append(f"- {title}: {description}")
    rows.append("- other: Confirmed Conflict that does not fit the eight skill-defined types.")
    return "\n".join(rows)


def normalize_conflict_type(value: Any, *, final_label: str) -> str:
    if final_label != "Conflict":
        return ""
    conflict_type = str(value or "").strip().lower()
    return conflict_type if conflict_type in CONFLICT_TYPE_VALUES else "other"


def parse_json_array_text(raw: str) -> List[Any]:
    text = str(raw or "").strip()
    candidates = [text]
    if "```" in text:
        for part in text.split("```"):
            value = part.strip()
            if value.lower().startswith("json"):
                value = value[4:].strip()
            if value.startswith("[") and value.endswith("]"):
                candidates.append(value)
    start = text.find("[")
    end = text.rfind("]")
    if start >= 0 and end > start:
        candidates.append(text[start : end + 1])
    last_error = None
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError as e:
            last_error = e
            continue
        if isinstance(data, list):
            return data
    if last_error is not None:
        raise ValueError("JSON array parse failed") from last_error
    raise ValueError("JSON array parse failed")


class AnalystConflicts:
    def invoke_conflict_skill(
        self,
        task: str,
        *,
        context: Any,
        mode: str = "analysis",
    ) -> str:
        skill = conflict_skill_subset(get_skill("conflict-analyzer"), mode)
        messages = self.build_skill_messages(skill, "conflict-analyzer", task, context=context)
        return self.run_skill_messages("conflict-analyzer", messages)

    def run_conflict_analysis_loop(self, action: str, **context: Any) -> Any:
        opa = self.run_action_loop(
            name="conflict_analysis",
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
            "max_iterations": kwargs["max_iterations"],
            "requirements_count": len(requirement_discussion_pool(artifact)),
            "conflicts_count": conflict_entries_count(artifact),
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
            if action == "run_pairwise_conflict_detection":
                output = self.execute_pairwise_conflict_detection(kwargs.get("artifact") or {})
            elif action == "run_group_conflict_detection":
                output = self.execute_group_conflict_detection(kwargs.get("artifact") or {})
            elif action == "review_conflicts":
                output = self.execute_review_conflicts(
                    kwargs.get("proposal_list") or [],
                    kwargs.get("discussion_rows") or [],
                    kwargs.get("extracted_pair_reviews"),
                )
            elif action == "finalize_review":
                output = self.execute_finalize_review(
                    kwargs.get("decision_list") or [],
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
            elif action == "generate_conflict_resolutions":
                output = self.generate_conflict_resolutions(kwargs.get("artifact") or {})
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

    def run_pairwise_conflict_detection(self, artifact: Dict) -> Dict:
        return self.run_conflict_analysis_loop(
            "run_pairwise_conflict_detection",
            artifact=artifact,
        )

    def run_group_conflict_detection(self, artifact: Dict) -> Dict:
        return self.run_conflict_analysis_loop(
            "run_group_conflict_detection",
            artifact=artifact,
        )

    def generate_conflict_resolutions(self, artifact: Dict) -> Dict:
        return self.run_conflict_analysis_loop(
            "generate_conflict_resolutions",
            artifact=artifact,
        )

    def review_conflicts(
        self,
        proposal_list: List[Dict[str, Any]],
        discussion_rows: List[Dict[str, Any]],
        extracted_pair_reviews: Optional[List[Dict[str, Any]]] = None,
    ) -> tuple[List[Dict[str, Any]], str]:
        return self.run_conflict_analysis_loop(
            "review_conflicts",
            proposal_list=proposal_list,
            discussion_rows=discussion_rows,
            extracted_pair_reviews=extracted_pair_reviews,
        )

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
        )

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

輸出只包含 JSON 物件：{{"conflicts":[...]}}。"""
        raw = ""
        try:
            raw = self.invoke_conflict_skill(task, context=context, mode="analysis")
            data = self.parse_issue_response_json(raw)
        except Exception as first_error:
            repair_prompt = render_prompt('agents_profile_analyst_conflicts_repair_prompt_3', **locals())
            try:
                data = self.chat_json(
                    self.build_direct_messages(repair_prompt, context=context),
                    action=self.usage_action("conflict.repair_pair_json"),
                )
            except Exception as repair_error:
                raw_preview = str(raw or "").strip().replace("\n", "\\n")[:500]
                raise RuntimeError(
                    f"{error_label}輸出格式不合格: {first_error}; "
                    f"修復失敗: {repair_error}; raw_preview={raw_preview}"
                ) from repair_error
        return conflict_records(
            data.get("conflicts", []),
            pairwise_mode=True,
            pair_count=pair_count,
            pair_requirements={
                int(row.get("pair_index")): [
                    str(req.get("id") or "").strip()
                    for req in (row.get("requirements") or [])
                    if isinstance(req, dict) and str(req.get("id") or "").strip()
                ]
                for row in pair_rows
                if isinstance(row, dict)
                and isinstance(row.get("pair_index"), int)
            },
        )

    def run_batch_pair_discovery(
        self,
        *,
        base_task: str,
        context: Dict[str, Any],
        requirements: List[Dict[str, Any]],
        existing_pairs: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        batch_size = 10
        config_block = (
            self.project_config.get("conflict_detection")
            if isinstance(self.project_config.get("conflict_detection"), dict)
            else {}
        )
        if config_block.get("enable_batch_pair_discovery") is False:
            return []
        try:
            batch_size = int(config_block.get("batch_pair_size", batch_size) or batch_size)
        except (TypeError, ValueError):
            batch_size = 10
        batch_size = max(3, batch_size)

        known_pairs = {
            frozenset(str(req_id).strip() for req_id in (row.get("requirement_ids") or []) if str(req_id).strip())
            for row in existing_pairs
            if isinstance(row, dict) and len(row.get("requirement_ids") or []) == 2
        }
        discovered: List[Dict[str, Any]] = []
        discovered_keys = set(known_pairs)

        for batch_start in range(0, len(requirements), batch_size):
            batch = requirements[batch_start : batch_start + batch_size]
            if len(batch) < 2:
                continue
            batch_rows = [
                {
                    "id": req.get("id"),
                    "text": req.get("text"),
                }
                for req in batch
            ]
            existing_in_batch = [
                sorted(pair_key)
                for pair_key in known_pairs
                if pair_key and pair_key.issubset({str(req.get("id") or "").strip() for req in batch})
            ]
            task = base_task + f"""

【批次補找 Pair】
- 這一步在固定相鄰 pair 判斷之後執行，用來找出同一批需求中「不相鄰但有衝突價值」的需求對。
- conflicts 只放額外發現的 Conflict pair。
- 每筆 Conflict 的 requirement_ids 必須剛好 2 個需求 id。
- 已判斷過的 pair 不再列入 conflicts。
- 若兩個需求不能直接同時定版，或需要補充規則、優先順序、條件邊界、責任歸屬、例外處理或人工裁定，標為 Conflict。
- 若沒有額外 Conflict pair，輸出 {{"conflicts":[]}}。

本批需求：
{json.dumps(batch_rows, ensure_ascii=False, indent=2)}

已判斷過的 pair：
{json.dumps(existing_in_batch, ensure_ascii=False, indent=2)}

輸出只包含 JSON 物件：{{"conflicts":[...]}}。"""
            raw = ""
            try:
                raw = self.invoke_conflict_skill(task, context=context, mode="analysis")
                data = self.parse_issue_response_json(raw)
            except Exception as first_error:
                repair_prompt = render_prompt('agents_profile_analyst_conflicts_repair_prompt_4', **locals())
                try:
                    data = self.chat_json(
                        self.build_direct_messages(repair_prompt, context=context),
                        action=self.usage_action("conflict.repair_batch_pair_json"),
                    )
                except Exception as repair_error:
                    raw_preview = str(raw or "").strip().replace("\n", "\\n")[:500]
                    raise RuntimeError(
                        f"批次補找 Pair 輸出格式不合格: {first_error}; "
                        f"修復失敗: {repair_error}; raw_preview={raw_preview}"
                    ) from repair_error

            batch_ids = {str(req.get("id") or "").strip() for req in batch}
            rows = conflict_records(data.get("conflicts", []))
            for row in rows:
                req_ids = [
                    str(req_id).strip()
                    for req_id in (row.get("requirement_ids") or [])
                    if str(req_id).strip()
                ]
                pair_key = frozenset(req_ids)
                if (
                    row.get("label") != "Conflict"
                    or len(req_ids) != 2
                    or not pair_key.issubset(batch_ids)
                    or pair_key in discovered_keys
                ):
                    continue
                discovered_keys.add(pair_key)
                discovered.append(row)

        next_index = len(existing_pairs) + 1
        for offset, row in enumerate(discovered):
            row["id"] = f"PAIR-{next_index + offset}"
            row["pair_source"] = "batch"
        return discovered

    def conflict_detection_requirements(self, artifact: Dict) -> List[Dict[str, Any]]:
        return [
            req for req in (artifact.get("URL") or [])
            if isinstance(req, dict)
            and str(req.get("id") or "").strip()
            and str(req.get("text") or "").strip()
        ]

    def conflict_detection_context(
        self,
        artifact: Dict,
        requirements: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        context_requirements: List[Dict[str, Any]] = []
        for req in requirements:
            stakeholder = req.get("stakeholder")
            stakeholder_name = (
                str(stakeholder.get("name") or "").strip()
                if isinstance(stakeholder, dict)
                else str(stakeholder or "").strip()
            )
            row = {
                "id": str(req.get("id") or "").strip(),
                "text": str(req.get("text") or "").strip(),
            }
            if stakeholder_name:
                row["stakeholder"] = stakeholder_name
            context_requirements.append(row)

        context: Dict[str, Any] = {}
        scenario_source = artifact.get("scenario") or artifact.get("rough_idea")
        if scenario_source:
            context["scenario"] = scenario_prompt_value(scenario_source)
        if artifact.get("scope"):
            context["scope"] = artifact["scope"]
        context["requirements"] = context_requirements
        return context

    def conflict_detection_base_task(self) -> str:
        return """僅根據輸入的 User Requirements 判斷 Conflict / Neutral；本步不看系統模型或其他回饋。

本專案覆蓋規則：
- 本步只做 requirement candidate conflict classification，不做報告或解決方案建議。
- 保持原需求文字不變；輸出不包含新增需求、解決方案或 meeting decision。
- 只輸出呼叫端指定的 JSON。
- 產品情境與需求範圍只作為產品邊界背景；Conflict / Neutral 仍以 User Requirements 原文為主要依據。

判斷任務：
- label 只用英文 "Conflict" 或 "Neutral"。
- 若 label 是 "Conflict"，必須輸出 type；type 只能是 logical、technical、resource、temporal、data、state、priority、scope、other。
- 若無法歸入前八類但仍是 Conflict，type 使用 other。
- Neutral 項目只輸出 label 與 reason。
- 檢查所有有分析價值的需求對或需求群；不同互斥核心請拆成不同項目。
- 若需求不能原樣共同放入 SRS，必須先合併、改寫、刪除或人工裁定，標為 Conflict。
- 若判定為 Neutral，reason 需說明為何兩者不產生需求衝突。

輸出要求：
- 兩兩判斷：只需輸出 pair_index、label、reason；若 label 是 Conflict，再輸出 type。
- 整體判斷：Conflict 需包含 requirement_ids 或 related_requirements。
- 整體判斷的 requirement_ids 必須精確對應直接涉及的需求；無法明確對應就不要臆測。
"""

    def execute_pairwise_conflict_detection(self, artifact: Dict) -> Dict:
        """使用 requirements 做相鄰兩兩需求衝突判斷。"""
        requirements = self.conflict_detection_requirements(artifact)
        if len(requirements) < 2:
            return set_pair_conflicts({**artifact}, [])

        context = self.conflict_detection_context(artifact, requirements)
        base_task = self.conflict_detection_base_task()
        pair_rows = []
        for pair_index, start in enumerate(range(0, len(requirements) - 1, 2)):
            req_a = requirements[start]
            req_b = requirements[start + 1]
            pair_rows.append(
                {
                    "pair_index": pair_index,
                    "requirements": [
                        {
                            "id": req_a.get("id"),
                            "text": req_a.get("text"),
                        },
                        {
                            "id": req_b.get("id"),
                            "text": req_b.get("text"),
                        },
                    ],
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
                "不需要輸出 requirement_ids，系統會根據 pair_index 自動對回 requirements。",
                "本步只處理指定 pair；群組衝突留給整體判斷。",
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
            self.logger.info("兩兩衝突補判 %s 對（Missing: %s）", len(missing_rows), len(missing_pairs))
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
                    "不需要輸出 requirement_ids，系統會根據 pair_index 自動對回 requirements。",
                    "輸出只涵蓋下列 missing pair。",
                    "本步只處理指定 pair；群組衝突留給整體判斷。",
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

        batch_conflicts = self.run_batch_pair_discovery(
            base_task=base_task,
            context=context,
            requirements=requirements,
            existing_pairs=pair_conflicts,
        )
        if batch_conflicts:
            pair_conflicts = list(pair_conflicts) + batch_conflicts
        self.logger.info(
            "批次補找衝突 pair 完成（新增 Conflict: %s）",
            len(batch_conflicts),
        )

        return set_pair_conflicts({**artifact}, pair_conflicts)

    def execute_group_conflict_detection(self, artifact: Dict) -> Dict:
        """使用 requirements 做集合型需求衝突判斷。"""
        requirements = self.conflict_detection_requirements(artifact)
        if len(requirements) < 2:
            self.logger.info("整體衝突判斷 0 組（Conflict: 0）")
            return artifact
        context = self.conflict_detection_context(artifact, requirements)
        pair_conflicts = [
            {
                "id": row.get("id"),
                "requirement_ids": row.get("requirement_ids"),
                "type": row.get("initial_type"),
                "reason": row.get("initial_reason"),
            }
            for row in ((artifact.get("conflict") or {}).get("pairs") or [])
            if isinstance(row, dict) and row.get("label") == "Conflict"
        ]
        context["pairwise_conflicts"] = pair_conflicts
        base_task = self.conflict_detection_base_task()
        holistic_task = base_task + """

【整體判斷】
- 第一步先找「決策主題」，不要先做固定配對。可用主題包含：
  - 資料揭露、保存、查詢權限、稽核責任。
  - 流程責任邊界、人工介入與自動化分工。
  - 即時性、效率、簡化流程 vs 安全、驗證、合規。
  - 使用者自主權、平台控管、營運效率、公平性或風險控管。
  - 狀態一致性、資料同步、付款/退款/取消/配送狀態。
  - scope、角色責任、第三方服務或人工流程邊界。
- 第二步才判斷：同一決策主題下，是否有兩筆以上 User Requirements 不能直接同時定稿。
- group 可以包含 2 條或 3 條以上需求；requirement_ids 至少 2 個。2 條也可以，但必須代表共同決策主題，不要只是重複 pairwise 的相鄰配對。
- 不要用 URL 編號順序做固定配對（例如 URL-1/URL-2、URL-3/URL-4、URL-5/URL-6）；pairwise detection 已負責固定 pair。整體判斷應以共同決策主題、規則邊界或一致性問題選取需求。
- pairwise_conflicts 只作為參考；若多個 pairwise conflicts 其實是同一個決策主題，請聚合成一筆 Conflict。
- 即使沒有 pairwise_conflicts，只要 User Requirements 顯示多筆需求在同一決策主題下無法一起寫入 SRS，也要輸出 Conflict。
- 若只是資訊不足、需要補問、語意模糊但尚未形成不能同時定稿的需求關係，不要標為 Conflict；可以在 reason 中說明不是衝突，但不要輸出到 conflicts。
- 只輸出會影響需求取捨、改寫、合併、刪除、責任分工或人類裁決的 Conflict。
- 每筆 Conflict 的 reason 必須說明「共同決策主題」以及「為什麼這些需求不能直接同時定稿」。
- 若 group 來自既有 pairwise_conflicts，才輸出 related_pairs；若是直接從 User Requirements 發現，related_pairs 可省略或輸出空陣列。
- 若沒有可定義的 group conflict，輸出 {"conflicts": []}。
- conflicts 只包含 label="Conflict" 的項目。

輸出只包含 JSON 物件：{"conflicts":[...]}。"""
        try:
            holistic_raw = self.invoke_conflict_skill(
                holistic_task, context=context, mode="analysis"
            )
            holistic_data = self.parse_issue_response_json(holistic_raw)
        except Exception as first_error:
            repair_prompt = render_prompt('agents_profile_analyst_conflicts_repair_prompt_5', **locals())
            try:
                holistic_data = self.chat_json(
                    self.build_direct_messages(repair_prompt, context=context),
                    action=self.usage_action("conflict.repair_holistic_json"),
                )
            except Exception as repair_error:
                raw_preview = str(holistic_raw or "").strip().replace("\n", "\\n")[:500]
                raise RuntimeError(
                    f"整體 Conflict 分析輸出格式不合格: {first_error}; "
                    f"修復失敗: {repair_error}; raw_preview={raw_preview}"
                ) from repair_error
        holistic_conflicts = [
            row for row in conflict_records(holistic_data.get("conflicts", []))
            if row.get("label") == "Conflict"
            and len(row.get("requirement_ids") or []) >= 2
        ]
        self.logger.info(
            "整體衝突判斷 %s 組（Conflict: %s）",
            len(holistic_conflicts),
            len(holistic_conflicts),
        )

        multiple_rows: List[Dict[str, Any]] = []
        for idx, row in enumerate(holistic_conflicts, 1):
            item = dict(row)
            item["id"] = f"MULTIPLE-{idx}"
            multiple_rows.append(item)
        return set_multiple_conflicts({**artifact}, multiple_rows)

    def execute_review_conflicts(
        self,
        proposal_list: List[Dict[str, Any]],
        discussion_rows: List[Dict[str, Any]],
        extracted_pair_reviews: Optional[List[Dict[str, Any]]] = None,
    ) -> tuple[List[Dict[str, Any]], str]:
        """Analyst 根據逐項 review、原文與會議發言做需求關係標籤確認。"""
        if not proposal_list:
            return [], ""
        prompt = (
            "請根據 User Requirements（URL-*）原文與各 agent 的逐筆 pair_reviews，"
            "對每筆 Conflict/Neutral 項目做最終裁定。\n\n"
            f"# 待裁定項目\n{json.dumps(proposal_list, ensure_ascii=False, indent=2)}\n\n"
            f"# 各 agent 的 pair_reviews\n{json.dumps(extracted_pair_reviews or [], ensure_ascii=False, indent=2)}\n\n"
            f"# 補充會議內容（僅在 pair_reviews 不足時參考）\n{json.dumps(discussion_rows, ensure_ascii=False, indent=2)}\n\n"
            "# 裁定規則\n"
            "- 先看 User Requirements（URL-*）原文，再看各 agent 的 pair_reviews。\n"
            "- discussion_rows 只在 pair_reviews 證據不足時作補充參考。\n"
            "- 若 pair_reviews 與 pair 原文足以支持改判，new_label 可改為 Conflict 或 Neutral。\n"
            "- 若 extracted_pair_reviews 為空，預設維持 current_label，除非 User Requirements（URL-*）原文本身已足以明確推翻現標籤。\n"
            "- 若證據不足、理由不一致或沒有明確共識，維持 current_label。\n"
            f"{CONFLICT_REVIEW_LABEL_RULES}\n"
            "- proposal_list 中每一個項目都必須輸出一筆 decision；即使決定維持 current_label，也不可省略。\n"
            "- 輸出只包含 JSON array。\n"
            "- 請直接做最終裁定，不要重述整場會議。\n\n"
            "# 輸出 JSON array\n"
            '[{"id": "衝突ID", "new_label": "Conflict 或 Neutral", '
            '"reason": "一句繁中裁定理由"}]'
        )
        messages = self.build_direct_messages(prompt)
        raw = (self.model.chat(messages, action="conflict_recheck_signoff") or "").strip()
        try:
            data = parse_json_array_text(raw)
        except ValueError as first_error:
            repair_prompt = render_prompt('agents_profile_analyst_conflicts_repair_prompt_6', **locals())
            repaired = self.model.chat(
                self.build_direct_messages(repair_prompt),
                action="conflict_recheck_signoff_repair",
            ) or ""
            try:
                data = parse_json_array_text(repaired)
            except ValueError as repair_error:
                raw_preview = raw.strip().replace("\n", "\\n")[:500]
                raise ValueError(
                    f"conflict signoff must return a JSON array: {first_error}; "
                    f"repair failed: {repair_error}; raw_preview={raw_preview}"
                ) from repair_error
        return signoff_decisions(data), raw

    def finalize_review(
        self,
        decision_list: List[Dict[str, Any]],
        discussion_rows: List[Dict[str, Any]],
        extracted_pair_reviews: Optional[List[Dict[str, Any]]] = None,
    ) -> tuple[List[Dict[str, str]], str]:
        return self.run_conflict_analysis_loop(
            "finalize_review",
            decision_list=decision_list,
            discussion_rows=discussion_rows,
            extracted_pair_reviews=extracted_pair_reviews,
        )

    def execute_finalize_review(
        self,
        decision_list: List[Dict[str, Any]],
        discussion_rows: List[Dict[str, Any]],
        extracted_pair_reviews: Optional[List[Dict[str, Any]]] = None,
    ) -> tuple[List[Dict[str, str]], str]:
        """Analyst 整理已定案的衝突再審查理由。"""
        if not decision_list:
            return [], ""
        type_guidance = conflict_type_guidance_from_skill()
        prompt = (
            f"# 已定案項目\n{json.dumps(decision_list, ensure_ascii=False, indent=2)}\n\n"
            f"# 各 agent 逐筆理由\n{json.dumps(extracted_pair_reviews or [], ensure_ascii=False, indent=2)}\n\n"
            f"# 衝突類型指引（摘自 conflict-analyzer skill）\n{type_guidance}\n\n"
            "# 任務\n"
            "請為每個已定案項目整理 description；若 final_label 是 Conflict，也要根據討論後的主要衝突原因判定 final_type。\n\n"
            "description 用來寫入 artifact/conflict.json，作為該項 final_label 的最終說明。\n"
            "請根據 final_label 與各 agent 逐筆理由，整理出一段清楚、精簡、可追溯的裁定描述。\n\n"
            "# 撰寫重點\n"
            "- 若 final_label 是 Conflict：說明需求之間的主要衝突點，或為什麼需要合併、改寫、刪除或裁定。\n"
            "- 若 final_label 是 Conflict：必須輸出 final_type；final_type 只能是 logical、technical、resource、temporal、data、state、priority、scope、other。\n"
            "- final_type 根據討論後的主要衝突原因決定，不必沿用 initial_type；若無法歸入前八類但仍是 Conflict，使用 other。\n"
            "- 若 final_label 是 Neutral：說明為什麼需求之間不構成衝突。\n"
            "- 若 final_label 是 Neutral：只輸出 id 與 description。\n"
            "- 使用各 agent 已提出的理由，不加入新的需求解釋或新的判準。\n"
            "- description 只整理裁定理由，不列 agent 名稱、投票過程或完整需求原文。\n\n"
            "# 輸出 JSON array\n"
            '[{"id": "PAIR-1", "description": "Conflict 的最終裁定描述", "final_type": "scope"}, '
            '{"id": "PAIR-2", "description": "Neutral 的最終裁定描述"}]'
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
            data = parse_json_array_text(text)
        except ValueError as first_error:
            repair_prompt = render_prompt('agents_profile_analyst_conflicts_repair_prompt_7', **locals())
            repaired = self.model.chat(
                self.build_direct_messages(repair_prompt),
                action="conflict_recheck_final_reason_repair",
            ) or ""
            try:
                data = parse_json_array_text(repaired)
            except ValueError as repair_error:
                raw_preview = raw.strip().replace("\n", "\\n")[:500]
                raise ValueError(
                    f"conflict final reason must return a JSON array: {first_error}; "
                    f"repair failed: {repair_error}; raw_preview={raw_preview}"
                ) from repair_error
        if not isinstance(data, list):
            raise ValueError("conflict final reason must return a JSON array")
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
            description = str(row.get("description") or "").strip()
            if pair_id in valid_ids and description:
                decision = next(
                    (item for item in decision_list if isinstance(item, dict) and str(item.get("id") or "").strip() == pair_id),
                    {},
                )
                final_label = str(decision.get("new_label") or decision.get("final_label") or "").strip()
                item = {"id": pair_id, "reason": description}
                final_type = normalize_conflict_type(row.get("final_type") or row.get("type"), final_label=final_label)
                if final_type:
                    item["final_type"] = final_type
                out.append(item)
        return out, raw

    def build_conflict_analysis_report(
        self,
        artifact: Dict[str, Any],
        round_num: Optional[int] = None,
        recent_decisions_limit: Optional[int] = None,
        previous_report: Optional[str] = None,
    ) -> str:
        """根據已定案的 conflict report rows 產出 Markdown 報告。"""
        _ = recent_decisions_limit
        conflict_rows = artifact.get("conflict_report", []) or []
        conflict_rows = [
            row for row in conflict_rows
            if isinstance(row, dict) and str(row.get("label") or "").strip() == "Conflict"
        ]
        if not conflict_rows:
            return ""
        context: Any = {
            "conflict_report": conflict_rows,
        }
        previous_report_text = (previous_report or "").strip()
        if previous_report_text:
            context = {
                "previous_conflict_report": previous_report_text,
                "conflict_report": conflict_rows,
            }
            task = render_prompt('agents_profile_analyst_conflicts_task_8', **locals())
        else:
            task = render_prompt('agents_profile_analyst_conflicts_task_9', **locals())
        try:
            raw = self.invoke_conflict_skill(task, context=context, mode="report")
        except Exception as e:
            raise RuntimeError(f"conflict report 生成失敗: {e}") from e
        out = clean_llm_output(raw)
        if not out:
            raise RuntimeError("conflict report 無內容")
        return out

    def generate_conflict_resolutions(self, artifact: Dict[str, Any]) -> Dict[str, Any]:
        """Use conflict skill resolution guidance to enrich conflict.report rows."""
        conflict_payload = artifact.get("conflict", {}) or {}
        report_rows = (
            conflict_payload.get("report", [])
            if isinstance(conflict_payload, dict)
            else []
        ) or []
        conflict_rows = [
            row for row in report_rows
            if isinstance(row, dict) and str(row.get("label") or "").strip() == "Conflict"
        ]
        if not conflict_rows:
            return artifact
        task = render_prompt('agents_profile_analyst_conflicts_task_10', **locals())
        by_id: Dict[str, Dict[str, Any]] = {}
        for conflict_row in conflict_rows:
            conflict_id = str(conflict_row.get("id") or "").strip()
            if not conflict_id:
                continue
            conflict_type = str(conflict_row.get("type") or "").strip().lower() or "other"
            try:
                data = self.parse_issue_response_json(
                    self.invoke_conflict_skill(
                        task,
                        context=conflict_row,
                        mode=f"resolution:{conflict_type}",
                    )
                )
            except Exception as e:
                raise RuntimeError(f"conflict resolution 生成失敗: {conflict_id}: {e}") from e
            if not isinstance(data, dict):
                raise RuntimeError(f"conflict resolution 必須輸出 JSON object: {conflict_id}")
            returned_id = str(data.get("id") or "").strip()
            if returned_id != conflict_id:
                raise RuntimeError(f"conflict resolution id 不一致: {conflict_id}")
            resolution_options = data.get("resolution_options")
            recommended_resolution = str(data.get("recommended_resolution") or "").strip()
            if not isinstance(resolution_options, list) or not resolution_options:
                raise RuntimeError(f"conflict resolution 缺少 resolution_options: {conflict_id}")
            if not recommended_resolution:
                raise RuntimeError(f"conflict resolution 缺少 recommended_resolution: {conflict_id}")
            clean_options: List[Dict[str, Any]] = []
            for option in resolution_options:
                if not isinstance(option, dict):
                    continue
                clean_option = {
                    "option": str(option.get("option") or "").strip(),
                    "strategy": str(option.get("strategy") or "").strip(),
                    "description": str(option.get("description") or "").strip(),
                    "pros": [
                        str(x).strip()
                        for x in (option.get("pros") or [])
                        if str(x).strip()
                    ],
                    "cons": [
                        str(x).strip()
                        for x in (option.get("cons") or [])
                        if str(x).strip()
                    ],
                    "recommendation": bool(option.get("recommendation")),
                }
                if clean_option["option"] and clean_option["strategy"] and clean_option["description"]:
                    clean_options.append(clean_option)
            if not clean_options:
                raise RuntimeError(f"conflict resolution 沒有有效 options: {conflict_id}")
            by_id[conflict_id] = {
                "resolution_options": clean_options,
                "recommended_resolution": recommended_resolution,
            }

        updated = dict(artifact)
        conflict_state = dict(conflict_payload)
        updated_report: List[Dict[str, Any]] = []
        for row in report_rows:
            if not isinstance(row, dict):
                continue
            item = dict(row)
            conflict_id = str(item.get("id") or "").strip()
            if conflict_id in by_id:
                item.update(by_id[conflict_id])
            updated_report.append(item)
        conflict_state["report"] = updated_report
        updated["conflict"] = conflict_state
        return updated
