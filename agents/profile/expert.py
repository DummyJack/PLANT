import json
from typing import Dict, List, Optional
from pathlib import Path

from agents.base import BaseAgent
from utils import (
    OUTPUT_LANG_EN,
    expert_fallback_viewpoint,
    expert_topic_bullets_task,
    short_reasoning_line,
)

# 與 FileParserTool 支援的副檔名一致（供 flow 組裝工具時判斷）
DOC_SUPPORTED_SUFFIXES = (".txt", ".md", ".json", ".pdf", ".docx", ".doc")


def has_supported_doc_files(doc_dir: Path) -> bool:
    """檢查 doc 目錄下是否至少有一個支援的檔案（含子目錄）。"""
    if not doc_dir.is_dir():
        return False
    for p in doc_dir.rglob("*"):
        if p.is_file() and p.suffix.lower() in DOC_SUPPORTED_SUFFIXES:
            return True
    return False


EXPERT_REVIEW_ACTIONS = [
    "research_topic",
    "update_findings",
    "flag_compliance_risk",
    "done",
]


class ExpertAgent(BaseAgent):
    """領域專家 Agent — 賦予 domain-research skill，可搭配 file_parser 等工具。"""

    name = "expert"

    system_prompt = """你是領域專家，負責提供必須遵守的法規、標準、安全規範。
核心原則：Evidence-first、可追溯來源、無證據不建議；約束須含具體條文、適用範圍、合規要求與風險。"""

    def __init__(
        self,
        model,
        tools: Optional[list] = None,
        registry=None,
        doc_dir: str = "doc",
    ):
        self.doc_dir = Path(doc_dir)
        self.doc_dir.mkdir(parents=True, exist_ok=True)
        super().__init__(
            model,
            tools=tools or [],
            registry=registry,
            skill_names=["domain-research"],
        )

    def has_doc_reference_files(self) -> bool:
        """與 ToolRegistry 一致：doc/ 下是否有至少一個可給 file_parser 使用的檔案。"""
        return has_supported_doc_files(self.doc_dir)

    @staticmethod
    def parse_first_json(raw: str) -> Dict:
        """從可能含多個 JSON 或後綴文字的內容中，只解析第一個完整 JSON 物件。"""
        if not raw or not isinstance(raw, str):
            return {}
        raw = raw.strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
        start = raw.find("{")
        if start == -1:
            return {}
        depth = 0
        for i in range(start, len(raw)):
            if raw[i] == "{":
                depth += 1
            elif raw[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(raw[start : i + 1])
                    except json.JSONDecodeError:
                        pass
                    break
        return {}

    def provide_domain_knowledge(
        self,
        requirements: List[Dict],
        conflicts: List[Dict],
        project_overview: str = "",
    ) -> Dict:
        """Phase 0: 提供領域知識。依 domain-research skill 的 Research Results 格式產出，結果寫入 artifact.feedback.domain_research，不修改 requirements。"""
        project_overview = (project_overview or "").strip()
        context = {
            "project_overview": project_overview,
            "requirements": requirements,
            "conflicts": conflicts,
        }
        doc_hint = ""
        if self.has_doc_reference_files():
            doc_hint = (
                "若有 file_parser 工具：建議先 action=search_chunks 檢索 doc/，"
                "再 action=read_chunks 讀回片段後綜合；若已知檔名且需全文可 action=read_full。"
            )
        task = f"""依 domain-research skill 的 **Output Format: Research Results** 執行領域研究並產出結果。
審查 Context 中的需求與專案概述，依專案範圍識別法規/標準/安全規範與 derived_requirements。
{doc_hint}
輸出「僅一個」JSON 物件，鍵名 "research_session"，值為物件，須含：
- id（如 RES-{{timestamp}}）
- domain, topic, timestamp
- findings（domain_context, best_practices, regulatory, competitive 等陣列）
- derived_requirements（陣列，每筆含 id, text, source, source_detail, confidence, needs_validation, category；法規/約束類請產出於此）
- recommendations（選填）
- gaps_in_research（選填）
id、category 等欄位名維持英文。勿輸出 Markdown，只輸出該 JSON。"""
        raw = self.invoke_skill("domain-research", task, context=context)
        response = self.parse_first_json(raw or "")
        research_session = response.get("research_session")
        if isinstance(research_session, dict):
            pass
        elif isinstance(response, dict) and (
            response.get("findings") or response.get("derived_requirements")
        ):
            # skill 有時直接回傳 research 內容於頂層
            research_session = response
        else:
            research_session = {}
        if not research_session:
            self.logger.warning(
                "domain-research skill 未產出 research_session（可能為 JSON 解析失敗或 skill 回傳格式不符）"
            )
        return {"feedback": {"domain_research": research_session}}

    def get_optional_skill_context(
        self, topic: Dict, artifact_snapshot: Optional[Dict]
    ) -> Optional[str]:
        """議題涉及 Conflict 協調、需求釐清或 NFR 取捨時，觸發 domain-research 產出簡短要點供發言參考。"""
        if topic.get("category") not in (
            "conflict_resolution", "requirement_clarification", "tradeoff"
        ):
            return None
        if "domain-research" not in self.skill_names:
            return None
        context = {"topic": topic, "artifact_snapshot": artifact_snapshot or {}}
        task = expert_topic_bullets_task(self.output_language)
        try:
            raw = self.invoke_skill("domain-research", task, context=context)
            return (raw or "").strip()
        except Exception as e:
            self.logger.debug("議程中觸發 domain-research 失敗: %s", e)
            return None

    def respond_to_topic(self, topic, previous_responses=None, artifact_snapshot=None):
        topic_text = f"議題 [{topic.get('id', '')}]: {topic.get('title', '')}\n描述: {topic.get('description', '')}"

        prev_text = ""
        if previous_responses:
            parts = [
                f"【{r.get('agent', '?')}】\n{r.get('response', {}).get('statement', '')}"
                for r in previous_responses
            ]
            prev_text = "\n前面的發言:\n" + "\n\n".join(parts)

        snapshot_text = ""
        if artifact_snapshot:
            snapshot_text = f"\n# 當前專案狀態（供參考）\n{json.dumps(artifact_snapshot, ensure_ascii=False, indent=2)}"

        skill_section = ""
        skill_context = self.get_optional_skill_context(topic, artifact_snapshot)
        if skill_context:
            skill_section = f"\n# Skill 參考（本輪依議題類型觸發）\n{skill_context}\n"

        tool_hint = ""
        if self.tools:
            fp_line = ""
            if self.has_doc_reference_files():
                fp_line = (
                    "- file_parser：建議 search_chunks → read_chunks 再綜合；"
                    "或 read_full 讀單檔（text / json_summary）。\n"
                )
            tool_hint = (
                "\n# 工具使用\n"
                f"{fp_line}"
                "- 最後**必須**輸出下列 JSON。"
            )

        user_prompt = f"""{topic_text}
{prev_text}
{snapshot_text}
{skill_section}
{tool_hint}

# 思考與發言流程
1. 先思考：(1) 此議題相關的法規、標準或技術限制 (2) 你作為專家在此議題上必須堅守的底線（須能附法規/標準依據）(3) 在合規前提下可接受的調整或折衷空間 (4) 不合規風險與可能後果
2. 上述 (2)(3) 只用來**內部**整理立場；撰寫 statement 時請勿以「我可讓步的點是…」「不可讓步的點是…」或類似小標／口頭套語作答，應把堅持與彈性**自然融入**合規結論、依據與建議的敘述中，如同真實會議發言。
3. 再根據思考結果，撰寫一段完整的發言（statement），建議採「先合規結論、再依據、再風險與建議」順序，針對議題提出你的專業見解與法規依據
4. 若有需要請其他角色回答的問題，列入 open_questions（to 填寫目標 agent 名稱，如 "user"、"analyst"、"modeler"）

# 表達方式（僅能以文字呈現）
- 發言時可善用**文字形式**的圖、表格、流程、草圖輔助說明，例如：Markdown 表格（| 項目 | 說明 |）、編號步驟流程（1. … 2. …）、箭頭式流程（A → B → C）、簡要結構縮排或文字草圖；無法產出真實圖片，僅能以文字表達。**若有使用表格、流程或圖示，請用 ``` … ``` 程式碼區塊包住，與一般敘述分開，方便閱讀。**

# 發言風格
- 以真實需求工程會議中的領域專家口吻：先給合規判斷，再說明依據、適用範圍、風險與可行替代方案
- 引用法規/標準時盡量指出來源線索（條文、章節、機構或文件名稱），不要只給結論
- 資訊不足時可明確說「這部分需要再查證」或「依目前查到的資料…」，不捏造

# 約束
- statement 必須包含具體的法規依據和不合規風險，禁止虛構法規或標準名稱
- 論點必須有客觀依據，無依據則標註「資訊不足」
- 若引用內容非最終法源（例如二手整理或網頁摘要），需清楚標註可信度與待驗證性
- 若此議題與法規/標準無直接對應，仍請以領域專家角度簡要說明最佳實務、業界常見做法或技術/風險建議；切勿留空或僅輸出 JSON 結構
- 投票將在討論結束後另行進行，發言時只需專注法規與風險說明

輸出 JSON:
{{{{
    "statement": "針對此議題的完整發言內容（含法規依據與風險說明）",
    "open_questions": [{{{{"to": "目標 agent 名稱", "question": "問題"}}}}]
}}}}"""

        messages = self.build_direct_messages(user_prompt)
        response = self.chat_for_topic_response(messages)
        statement = (response.get("statement") or "").strip()

        # 若仍為空（例如模型只回 JSON 殼、或議題非純法規導致拒答），用簡短重試強制產出內容
        if not statement:
            fallback_prompt = f"{topic_text}\n\n{expert_fallback_viewpoint(self.output_language)}"
            fallback_messages = self.build_direct_messages(fallback_prompt)
            try:
                raw_fallback = self.model.chat(fallback_messages)
                statement = (raw_fallback or "").strip()
            except Exception as e:
                self.logger.warning("expert 簡短重試失敗: %s", e)
                statement = (
                    "(Insufficient information to cite specific regulations; please verify after the meeting.)"
                    if self.output_language == OUTPUT_LANG_EN
                    else "（依目前資訊暫無法提供具體法規依據，建議會後再查證後補充分享。）"
                )

        return {
            "agent": self.name,
            "statement": statement,
            "open_questions": response.get("open_questions", []),
        }

    # ===== 子 OODA 循環 =====

    def run_review_loop(self, artifact, recent_discussions=None, *, max_iterations):
        """Expert 子 OODA：自主研究 → 更新發現 → 標記風險。max_iterations 為此次複審上限（caller 傳入，通常為 5）；第一輪可選填 max_iterations（1–5）由 Expert 自訂此次實際輪數。"""
        observation = None
        actions_taken = []
        pending_issues = []
        research_results = []
        effective_max = min(max_iterations, 5)  # 上限 5，agent 自訂 1–5
        i = 0

        while i < effective_max:
            state = self.build_review_state(
                artifact, recent_discussions, actions_taken,
                research_results, i, effective_max,
            )
            decision = self.decide_next_review_action(state, observation)
            if i == 0:
                n = decision.get("max_iterations")
                if n is not None and isinstance(n, int) and 1 <= n <= 5:
                    effective_max = n
                    self.logger.info(f"  Expert 自訂此次複審輪數: {effective_max}（1–5）")
            action = decision.get("action", "done")
            self.logger.info(
                f"  Expert review [{i + 1}/{effective_max}]: {action}"
                f" — {decision.get('reasoning', '')}"
            )
            if action == "done" or action not in EXPERT_REVIEW_ACTIONS:
                break

            params = decision.get("params") or {}
            observation = self.execute_review_action(
                action, params, artifact, pending_issues, research_results,
            )
            actions_taken.append({
                "action": action,
                "params": params,
                "result_summary": observation.get("summary", ""),
            })
            if observation.get("error"):
                self.logger.warning(f"  Expert review error: {observation['error']}")
            i += 1

        return {
            "agent": self.name,
            "actions_taken": actions_taken,
            "pending_issues": pending_issues,
        }

    def decide_next_review_action(self, state, last_observation=None):
        state_text = json.dumps(state, ensure_ascii=False, indent=2)
        obs_text = json.dumps(last_observation or {}, ensure_ascii=False, indent=2)

        tools_hint = ""
        if state.get("available_tools"):
            tools_hint = (
                "\n- research_topic 執行時可自動使用工具："
                + ", ".join(state["available_tools"])
            )

        user_prompt = f"""# 任務
你是領域專家，正在對當前專案進行自主領域研究與合規分析。根據「當前狀態」與「上一步結果」，決定下一步行動。

# 可用動作
- research_topic：針對特定問題進行領域研究（搜尋法規、讀取文件）。params: {{ "query": "具體研究問題", "max_tool_rounds": 選填 1–10，此次研究允許的 tool 呼叫輪數 }}；使用搜尋工具時可自行決定要取幾筆結果（工具支援 max_results 參數）。{tools_hint}
- update_findings：綜合已有研究結果更新至專案領域研究資料。無參數。（研究完畢後呼叫）
- flag_compliance_risk：標記合規風險供主持人參考。params: {{ "description": "風險描述" }}
- done：分析完成，交還控制權。無參數。

# 當前狀態
{state_text}

# 上一步結果
{obs_text}

# 決策指引
- 若為第一輪（當前狀態中 iteration 為 1），可選填 max_iterations（1–5）表示此次複審你打算跑幾輪；不填則用目前上限（最多 5）。
- 若有近期討論涉及法規、標準、安全、合規問題，優先研究
- 若需求涉及受管制領域（用戶資料、支付、醫療、教育等），研究對應法規
- research_topic 可多次呼叫，每次聚焦一個具體問題
- 研究到足夠深度後呼叫 update_findings 寫入
- 發現重大合規風險時呼叫 flag_compliance_risk
- 無需進一步研究時呼叫 done
- {short_reasoning_line(self.output_language)}

輸出 JSON:
{{
    "action": "動作名稱",
    "params": {{}},
    "reasoning": "一句說明",
    "max_iterations": "選填，僅第一輪有效；填數字 1–5 表示此次複審自訂輪數"
}}"""

        messages = self.build_direct_messages(user_prompt)
        try:
            response = self.model.chat_json(messages)
        except Exception as e:
            self.logger.warning(f"Expert review 決策失敗: {e}")
            return {"action": "done", "params": {}, "reasoning": f"fallback: {e}"}

        action = (response.get("action") or "").strip()
        if action not in EXPERT_REVIEW_ACTIONS:
            action = "done"
        out = {
            "action": action,
            "params": response.get("params") or {},
            "reasoning": response.get("reasoning", ""),
        }
        if "max_iterations" in response:
            out["max_iterations"] = response["max_iterations"]
        return out

    def build_review_state(
        self, artifact, recent_discussions, actions_taken,
        research_results, iteration, max_iterations,
    ):
        reqs = artifact.get("requirements", [])
        summary_reqs = [
            {"id": r.get("id"), "type": r.get("type"),
             "text": (r.get("text") or "")}
            for r in reqs
        ]
        conflicts = [
            {"id": c.get("id"),
             "description": (c.get("description") or "")}
            for c in artifact.get("conflicts", [])
            if c.get("label") == "Conflict"
        ]
        neutrals = [
            {"id": c.get("id"),
             "description": (c.get("description") or "")}
            for c in artifact.get("conflicts", [])
            if c.get("label") == "Neutral"
        ]
        disc_summaries = []
        for disc in (recent_discussions or []):
            topic = disc.get("topic", {})
            resolution = disc.get("resolution", {})
            disc_summaries.append({
                "topic_id": topic.get("id"),
                "title": topic.get("title"),
                "resolution": resolution.get("resolution"),
                "summary": (resolution.get("summary") or ""),
            })
        existing = artifact.get("feedback", {}).get("domain_research", {})
        return {
            "requirements": summary_reqs,
            "conflicts": conflicts,
            "neutrals": neutrals,
            "scope": artifact.get("scope", {}),
            "has_existing_research": bool(existing),
            "recent_discussions": disc_summaries,
            "actions_taken": actions_taken,
            "research_results_count": len(research_results),
            "available_tools": list(self.tools.keys()),
            "iteration": iteration + 1,
            "max_iterations": max_iterations,
        }

    def execute_review_action(
        self, action, params, artifact, pending_issues, research_results,
    ):
        obs: Dict = {"action": action, "result": None, "error": None, "summary": ""}

        if action == "research_topic":
            query = params.get("query", "")
            if not query:
                obs["error"] = "query 參數為空"
                obs["summary"] = "研究失敗：未提供研究問題"
                return obs
            max_rounds = params.get("max_tool_rounds")
            if max_rounds is not None and isinstance(max_rounds, int) and 1 <= max_rounds <= 10:
                tool_rounds = max_rounds
            else:
                tool_rounds = self.tool_call_max_rounds
            context = {
                "project_overview": (artifact.get("scope") or {}).get(
                    "description", ""
                ),
            }
            tool_part = "web_search 搜尋時可帶 user_question 以利停止條件"
            if self.has_doc_reference_files():
                tool_part += (
                    "；file_parser 請優先 search_chunks 再 read_chunks 讀 doc/，"
                    "必要時 read_full"
                )
            task = f"""針對以下問題進行領域研究：{query}

請使用可用工具（{tool_part}）蒐集相關法規標準或參考文件，然後整理研究發現。
輸出「僅一個」JSON：
{{
    "findings": ["發現1", "發現2"],
    "sources": ["來源1"],
    "derived_requirements": [
        {{"text": "建議需求", "source": "來源", "category": "regulatory/best_practice/safety"}}
    ],
    "compliance_risks": ["風險描述"]
}}
只輸出 JSON。"""
            messages = self.build_direct_messages(task, context=context)
            try:
                raw = (
                    self.chat_with_tools(
                        messages,
                        max_rounds=tool_rounds,
                        active_skill="domain-research",
                    )
                    if self.tools
                    else self.model.chat(messages)
                )
                result = self.parse_first_json(raw)
                if not result:
                    result = {"findings": [(raw or "")]}
                research_results.append({"query": query, **result})
                obs["result"] = result
                obs["summary"] = (
                    f"研究 '{query}': "
                    f"{len(result.get('findings', []))} 項發現"
                )
            except Exception as e:
                obs["error"] = str(e)
                obs["summary"] = f"研究失敗: {e}"
            return obs

        if action == "update_findings":
            if not research_results:
                obs["summary"] = "無研究結果可更新"
                return obs
            existing = artifact.get("feedback", {}).get("domain_research", {})
            context = {
                "research_results": research_results,
                "existing_research": existing,
            }
            task = """綜合 Context.research_results 與 Context.existing_research，依 domain-research skill 格式產出合併後的領域研究資料。
輸出「僅一個」JSON，鍵名 "domain_research"，值含：
- findings（合併新舊研究發現）
- derived_requirements（合併新舊，勿重複）
- recommendations（選填）
只輸出 JSON。"""
            try:
                raw = self.invoke_skill("domain-research", task, context=context)
                result = self.parse_first_json(raw)
                dr = result.get("domain_research") or result
                if isinstance(dr, dict) and dr:
                    artifact.setdefault("feedback", {})["domain_research"] = dr
                    obs["summary"] = "已更新領域研究資料"
                else:
                    obs["error"] = "解析失敗"
                    obs["summary"] = "更新失敗：解析錯誤"
            except Exception as e:
                obs["error"] = str(e)
                obs["summary"] = f"更新失敗: {e}"
            return obs

        if action == "flag_compliance_risk":
            desc = (params.get("description") or "").strip()
            if not desc:
                obs["error"] = "description 為空"
                return obs
            pending_issues.append({
                "type": "compliance_risk",
                "description": desc,
                "source": "expert",
            })
            obs["summary"] = f"已標記合規風險: {desc}"
            return obs

        obs["error"] = f"未知動作: {action}"
        return obs
