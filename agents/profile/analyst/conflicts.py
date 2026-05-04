# Analyst conflict logic: detect, recheck, sign off, and report requirement conflicts.
import json
import re
from typing import Any, Dict, List, Optional

from storage.markdown import clean_llm_output


class AnalystConflicts:
    def run_conflict_detection(self, artifact: Dict) -> Dict:
        """依 conflict-analyzer skill 僅針對「需求」做 Conflict 辨識：判斷為衝突則 label=Conflict，無衝突則 label=Neutral。"""
        meta = artifact.get("meta") or {}
        requirements = artifact.get("requirements", [])
        # 通用布林開關：
        # - True  : pairwise 後再做整體檢查（可抓 3+ 需求衝突）
        # - False : 只做 pairwise
        holistic_enabled_cfg = self.project_config.get(
            "enable_all_conflict_check", True
        )
        holistic_enabled = bool(
            meta.get("enable_all_conflict_check", holistic_enabled_cfg)
        )

        pairwise_mode = bool(meta.get("pairwise_only"))
        n_pairs = 0
        pairwise_extra = ""
        pair_id_prefix = str(meta.get("pair_id_prefix") or "PAIR").strip() or "PAIR"
        if pairwise_mode:
            n_pairs = int(meta.get("pair_count") or 0)
            if n_pairs <= 0:
                return {**artifact, "conflicts": list(artifact.get("conflicts", []))}
            # 已明確提供 pairwise 對照時，固定採 pairwise-only 流程。
            holistic_enabled = False
            lines = []
            for i in range(n_pairs):
                rid_a, rid_b = (
                    f"{pair_id_prefix}-P{i}-a",
                    f"{pair_id_prefix}-P{i}-b",
                )
                ta = tb = ""
                for r in requirements:
                    if not isinstance(r, dict):
                        continue
                    if str(r.get("id") or "").strip() == rid_a:
                        ta = str(r.get("text") or "").strip()
                    if str(r.get("id") or "").strip() == rid_b:
                        tb = str(r.get("text") or "").strip()
                lines.append(
                    f"- pair_index={i}  ids=[{rid_a},{rid_b}]  A={ta[:500]}  B={tb[:500]}"
                )
            pairwise_extra = (
                f"\n\n【pairwise 模式附加規則】\n"
                f"- 以下共有 {n_pairs} 對需求，對與對完全獨立。\n"
                "- 你只能比較同一 pair_index 下的 A 與 B，絕不可跨 pair 比較。\n"
                f"- 每一對都必須輸出恰好一筆結果，共 {n_pairs} 筆；"
                f"pair_index 必須涵蓋 0..{n_pairs - 1} 各一次。\n"
                "- 每筆必含 pair_index、label、description、requirement_ids；"
                "其中 requirement_ids 必須對應該對的兩個 id。\n\n"
                "對照表：\n"
                f"{chr(10).join(lines)}\n\n"
                "輸出格式（嚴格）：\n"
                '{"conflicts":[{"pair_index":0,"label":"Conflict","description":"...",'
                f'"requirement_ids":["{pair_id_prefix}-P0-a","{pair_id_prefix}-P0-b"]}}, ...]}}'
            )

        context: Dict[str, Any] = {"requirements": requirements}
        if artifact.get("stakeholders"):
            context["stakeholders"] = artifact["stakeholders"]
        if artifact.get("scope"):
            context["scope"] = artifact["scope"]
        base_task = """依 conflict-analyzer skill，僅根據 Context.requirements 辨識需求關係；本步不看系統模型或其他回饋。

判斷任務：
- label 只用英文 "Conflict" 或 "Neutral"。
- 檢查所有有分析價值的需求對或需求群；不同互斥核心請拆成不同項目。
- references/conflict_patterns.md 只能作為掃描線索，不能取代以下判準。

Conflict 判準：
- 需求必須處於同一 subject 與可比較範圍。
- 只有在無法同時滿足，或一方成立會直接違反另一方時，才標為 Conflict。
- 資訊不足、尚待澄清、一般 trade-off、範圍未明、角色不同或流程階段不同，不可直接升級為 Conflict。
- conflict_type 只是描述結果，不是產生 Conflict 的理由。

Neutral 判準：
- 只有在可明確判定兩項需求不衝突、不重複，且沒有直接語義關係時，才標為 Neutral。
- 若兩項需求是重述、細化、依賴、範圍重疊、同一流程相鄰步驟或同一輸出行為，不要標為 Neutral。

輸出要求：
- Conflict：需包含 description、requirement_ids 或 related_requirements；description 說明涉及哪些需求、互斥點與為何不能同時成立。
- Neutral：需包含 description；可選填 requirement_ids；description 說明為何無衝突、無重複且無直接語義關係。
- requirement_ids 必須精確對應直接涉及的需求；無法明確對應就不要臆測。

只輸出一個 JSON 物件：{{"conflicts":[...]}}。勿輸出 Markdown 或其他文字。"""

        pairwise_only_extra = """

【pairwise-only 模式附加規則】
- 請優先以兩兩（pairwise）角度掃描需求關係後輸出結果。
- 不要輸出需要 3 條以上需求同時成立才會出現的群組衝突。"""

        holistic_extra = """

【pairwise+holistic 模式附加規則】
- 你可先利用 Context.pairwise_conflict_hints 作為線索，但最終請做整體一致性檢查。
- 除了兩兩衝突，也要找出三條以上需求共同造成的群組衝突。"""

        task = base_task + pairwise_extra
        if (not holistic_enabled) and (not pairwise_mode):
            task += pairwise_only_extra
        if holistic_enabled and not pairwise_mode:
            pairwise_hint_task = base_task + pairwise_only_extra
            try:
                hint_raw = self.invoke_skill(
                    "conflict-analyzer", pairwise_hint_task, context=context
                )
                hint_data = self.parse_topic_response_json(hint_raw)
                hints = hint_data.get("conflicts", [])
                if isinstance(hints, list) and hints:
                    context["pairwise_conflict_hints"] = hints
            except Exception as e:
                self.logger.warning(f"pairwise 預掃描失敗，改以整體檢查繼續: {e}")
            task += holistic_extra

        try:
            raw = self.invoke_skill("conflict-analyzer", task, context=context)
            data = self.parse_topic_response_json(raw)
        except Exception as e:
            if pairwise_mode:
                self.logger.warning(f"pairwise 批次衝突分析失敗: {e}")
                return {
                    **artifact,
                    "conflicts": [],
                }
            self.logger.warning(f"Conflict 分析失敗: {e}")
            return artifact

        raw_list = data.get("conflicts", [])
        if not isinstance(raw_list, list):
            raw_list = []

        if pairwise_mode:
            by_pair: Dict[int, Dict[str, Any]] = {}
            for c in raw_list:
                if not isinstance(c, dict):
                    continue
                try:
                    pi = int(c.get("pair_index"))
                except (TypeError, ValueError):
                    continue
                if pi < 0 or pi >= n_pairs:
                    continue
                label = (c.get("label") or "").strip()
                if label not in {"Conflict", "Neutral"}:
                    continue
                rid_a, rid_b = (
                    f"{pair_id_prefix}-P{pi}-a",
                    f"{pair_id_prefix}-P{pi}-b",
                )
                rel = (
                    c.get("requirement_ids")
                    or c.get("related_requirements")
                    or [rid_a, rid_b]
                )
                entry: Dict[str, Any] = {
                    "id": f"PAIR-{pi:03d}",
                    "label": label,
                    "pair_index": pi,
                    "description": (c.get("description") or "").strip(),
                    "requirement_ids": rel if isinstance(rel, list) else [rid_a, rid_b],
                }
                if label == "Conflict":
                    entry["conflict_type"] = (c.get("conflict_type") or "").strip()
                by_pair[pi] = entry

            conflicts: List[Dict[str, Any]] = []
            for i in range(n_pairs):
                if i in by_pair:
                    conflicts.append(by_pair[i])
            missing_pairs = [i for i in range(n_pairs) if i not in by_pair]

            nc = len([x for x in conflicts if x.get("label") == "Conflict"])
            nn = len([x for x in conflicts if x.get("label") == "Neutral"])
            self.logger.info(
                f"pairwise 批次辨識 {n_pairs} 對（Conflict: {nc}，Neutral: {nn}，Missing: {len(missing_pairs)}）"
            )
            return {
                **artifact,
                "conflicts": conflicts,
            }

        conflicts = []
        design_count = 0
        neutral_count = 0
        for c in raw_list:
            label = (c.get("label") or "").strip()
            if label == "Neutral":
                neutral_count += 1
                nf_entry = {
                    "id": f"NF-{neutral_count:02d}",
                    "label": "Neutral",
                    "description": c.get("description", ""),
                }
                conflicts.append(nf_entry)
                continue
            if label != "Conflict":
                continue
            # conflict_type 為描述用，可為 8 類或模型自訂類型，不限制
            ctype = (c.get("conflict_type") or "").strip()
            rel_reqs = c.get("requirement_ids") or c.get("related_requirements") or []
            if c.get("stakeholder_names"):
                cf_id = f"CF-{len([x for x in conflicts if x.get('label') == 'Conflict']) + 1:02d}"
                entry = {
                    "id": cf_id,
                    "label": "Conflict",
                    "description": c.get("description", ""),
                    "stakeholder_names": c.get("stakeholder_names", []),
                    "conflict_type": ctype,
                }
            elif rel_reqs or c.get("requirement_ids"):
                cf_id = f"CF-{len([x for x in conflicts if x.get('label') == 'Conflict']) + 1:02d}"
                entry = {
                    "id": cf_id,
                    "label": "Conflict",
                    "description": c.get("description", ""),
                    "requirement_ids": rel_reqs or c.get("requirement_ids", []),
                    "conflict_type": ctype,
                }
            else:
                design_count += 1
                cf_id = f"CF-D{design_count:02d}"
                entry = {
                    "id": cf_id,
                    "label": "Conflict",
                    "description": c.get("description", ""),
                    "requirement_ids": rel_reqs,
                }
            conflicts.append(entry)

        if conflicts:
            n_conflict = len([x for x in conflicts if x.get("label") == "Conflict"])
            n_neutral = len([x for x in conflicts if x.get("label") == "Neutral"])
            self.logger.info(
                f"辨識出 {len(conflicts)} 筆（Conflict: {n_conflict}，Neutral: {n_neutral}）"
            )
        return {**artifact, "conflicts": conflicts}

    def signoff_conflict_recheck(
        self,
        proposal_list: List[Dict[str, Any]],
        discussion_rows: List[Dict[str, Any]],
        extracted_pair_reviews: Optional[List[Dict[str, Any]]] = None,
    ) -> tuple[List[Dict[str, Any]], str]:
        """Analyst 根據 pair_reviews 與原始 requirement pair 做最終裁定。"""
        if not proposal_list:
            return [], ""
        prompt = (
            "你是資深需求分析師（Analyst）。請根據 requirement pair 原文與各 agent 的逐筆 pair_reviews，"
            "對每筆 Conflict/Neutral pair 做最終裁定。\n\n"
            f"# 待裁定項目\n{json.dumps(proposal_list, ensure_ascii=False, indent=2)}\n\n"
            f"# 各 agent 的 pair_reviews\n{json.dumps(extracted_pair_reviews or [], ensure_ascii=False, indent=2)}\n\n"
            f"# 補充會議內容（僅在 pair_reviews 不足時參考）\n{json.dumps(discussion_rows, ensure_ascii=False, indent=2)}\n\n"
            "# 裁定規則\n"
            "- 先看 requirement_a / requirement_b 原文，再看各 agent 的 pair_reviews。\n"
            "- discussion_rows 只在 pair_reviews 證據不足時作補充參考。\n"
            "- 若 pair_reviews 與 pair 原文足以支持改判，new_label 可改為 Conflict 或 Neutral。\n"
            "- 若 extracted_pair_reviews 為空，預設維持 current_label，除非 requirement_a / requirement_b 原文本身已足以明確推翻現標籤。\n"
            "- 若證據不足、理由不一致或沒有明確共識，維持 current_label。\n"
            "- Conflict 只在兩項需求無法同時成立，或一方成立會直接違反另一方時成立。\n"
            "- Neutral 只在兩項需求既不衝突、也不重複，且沒有直接語義關係時成立。\n"
            "- 若兩項需求描述同一功能範圍、同一流程、同一資料處理或同一輸出行為，即表示存在直接語義關係；不能僅因兩者可共存就判為 Neutral。\n"
            "- 若 supporting pair_reviews 主要以 subset、refinement、complementary step 或 same-flow relationship 支持 Neutral，必須重新檢查是否其實已存在直接語義關係；若存在，不可僅因不互斥就維持 Neutral。\n"
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
        if isinstance(data, list):
            return data, raw
        if isinstance(data, dict) and isinstance(data.get("decisions"), list):
            return data["decisions"], raw
        return [], raw

    def generate_conflict_report(
        self,
        artifact: Dict[str, Any],
        round_num: Optional[int] = None,
        recent_decisions_limit: Optional[int] = None,
    ) -> str:
        """依 conflict-analyzer skill 與 assets/conflict_report_template.json 結構，從 artifact 產出需求 Conflict 分析報告（Markdown）；含所有 Conflict（含已解決）並標示是否已解決。"""
        n = 10 if recent_decisions_limit is None else max(0, recent_decisions_limit)
        decisions = artifact.get("decisions", [])[-n:] if n else []
        all_conflicts = artifact.get("conflicts", [])
        context = {
            "conflicts": all_conflicts,
            "requirements": artifact.get("requirements", []),
            "stakeholders": artifact.get("stakeholders", []),
            "scope": artifact.get("scope", {}),
            "project_overview": (artifact.get("scope") or {}).get("description", ""),
            "open_questions": artifact.get("open_questions", []),
            "decisions": decisions,
            "system_models": artifact.get("system_models", {}),
            "round_num": round_num,
            "domain_research": artifact.get("feedback", {}).get("domain_research"),
        }
        task = """依本 skill 與 conflict_report_template.json（已在 skill 附件中）產出需求 Conflict 分析報告。

規則：
- Context.conflicts 全部都要列入。
- label=Conflict 視為 unresolved；label=Neutral 視為 resolved。
- resolved / unresolved 統計請與此規則一致。
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
