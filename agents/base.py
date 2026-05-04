# Agent base layer: shared prompts, skill/tool policy, JSON parsing, and tool calling.
import json
import re
import logging
import ast
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set

from agents.profile.agent_loop import AgentActionLoop
from utils.language import current_output_language

if TYPE_CHECKING:
    from agents.tools.base import BaseTool


# ---------------------------------------------------------------------------
# Agent Registry
# ---------------------------------------------------------------------------

class AgentRegistry:
    def __init__(self):
        self._agents: Dict[str, Any] = {}

    def register(self, name: str, agent):
        self._agents[name] = agent

    def get(self, agent_name: str):
        return self._agents.get(agent_name)

    def get_names(self) -> list:
        return list(self._agents.keys())


# ---------------------------------------------------------------------------
# Skill / Tool Policy
# ---------------------------------------------------------------------------

DEFAULT_AGENT_SKILL_MAPPING: Dict[str, List[str]] = {
    "analyst": ["requirements-analyst", "conflict-analyzer"],
    "expert": ["domain-research"],
    "modeler": ["UML"],
    "documentor": ["SRS"],
    "mediator": [],
    "user": [],
}

DEFAULT_AGENT_TOOL_MAPPING: Dict[str, List[str]] = {
    "analyst": ["artifact_query"],
    "expert": ["web_search", "file_parser", "artifact_query"],
    "modeler": ["plantuml_validate", "artifact_query"],
    "documentor": [],
    "mediator": ["artifact_query"],
    "user": [],
}

DEFAULT_SKILL_TOOL_ALLOWLIST: Dict[str, List[str]] = {
    "domain-research": ["web_search", "file_parser", "artifact_query"],
    "requirements-analyst": ["artifact_query"],
    "conflict-analyzer": ["artifact_query"],
    "UML": ["plantuml_validate", "artifact_query"],
    "SRS": ["artifact_query"],
}


def build_pre_meeting_conflict_review_description(conflict_summaries: List[str]) -> str:
    return (
        "以下為本輪會前需審查的 Conflict/Neutral 項目。\n"
        "請先根據每個 pair 的 requirement_a / requirement_b 原文獨立重判，"
        "並將重判結果填入 proposed_label（Conflict 或 Neutral）。\n"
        "你必須同時做兩層檢視：\n"
        "1) 整體檢視：說明你對整批標註品質的整體判斷（是否有系統性偏誤）。\n"
        "2) 逐筆（pair-by-pair）檢視：每個 [PAIR-xxx] 都必須明確寫出：\n"
        "   - proposed_label: 你重判後建議採用的標籤（Conflict 或 Neutral）\n"
        "   - confidence: high / medium / low\n"
        "   - reason: 一句到兩句審查理由，需說明你的獨立判斷依據\n"
        "reason 只能填純理由文字，不要包含 id、proposed_label、confidence 或欄位名稱。\n"
        "Neutral 的定義：兩項需求既不衝突、也不重複，且沒有直接語義關係。\n\n"
        "待審清單：\n" + "\n".join(conflict_summaries)
    )


JSON_OUTPUT_DIRECTIVE = "請只輸出合法 JSON，不要其他文字。"


def directive_embed() -> str:
    if current_output_language() == "en":
        return "Please respond in English."
    return "請使用繁體中文回覆。"


def global_conventions_text() -> str:
    if current_output_language() == "en":
        return "Be specific, concise, and actionable; avoid vague wording. When citing URLs, paste full URLs directly instead of Markdown links."
    return "請具體、精簡、可執行；避免空泛描述。引用網址時直接貼出完整 URL，不要使用 Markdown 超連結語法。"


def short_reasoning_line() -> str:
    if current_output_language() == "en":
        return "Use one short English sentence for reasoning."
    return "reasoning 請使用一句繁體中文簡述。"


def user_requirement_cards() -> str:
    if current_output_language() == "en":
        return "Write requirement cards in English."
    return "需求卡片請使用繁體中文。"


def user_stakeholder_name_reason() -> str:
    return "每位利害關係人需包含名稱與理由。"


def analyst_draft_decision_table_note() -> str:
    return "若有決策，請用精簡決策表呈現。"


def expert_fallback_viewpoint() -> str:
    return "請以領域專家角度，簡短給出觀點與風險提醒。"


def mediator_agenda_language_line() -> str:
    if current_output_language() == "en":
        return "Use English for title/description."
    return "title/description 請使用繁體中文。"


def mediator_collect_line() -> str:
    return "請清楚整理分歧與未解決事項。"


def mediator_human_options_line() -> str:
    return "請提供 2～4 個可選方案並附優缺點。"


def mediator_reasoning_line() -> str:
    if current_output_language() == "en":
        return "reasoning should be one concise English sentence."
    return "reasoning 請使用一句繁體中文。"


def modeler_models_array_name_line() -> str:
    return "陣列欄位名稱請使用 models。"


def modeler_name_field_language() -> str:
    if current_output_language() == "en":
        return "Use English in the name field."
    return "name 欄位請使用繁體中文。"


def modeler_review_field_language() -> str:
    if current_output_language() == "en":
        return "Write review field descriptions in English."
    return "review 欄位說明請使用繁體中文。"


def documentor_srs_body_lang() -> str:
    if current_output_language() == "en":
        return "Write the document body in English."
    return "內文請使用繁體中文。"


def srs_title_instruction() -> str:
    return "文件主標題必須為「[系統名稱]軟體需求規格書」。"


@dataclass
class AgentSkillToolPolicy:
    """集中式 policy：鎖定 agent/skill/tool 邊界並做執行期檢查。"""

    agent_skill_mapping: Dict[str, List[str]] = field(
        default_factory=lambda: dict(DEFAULT_AGENT_SKILL_MAPPING)
    )
    agent_tool_mapping: Dict[str, List[str]] = field(
        default_factory=lambda: dict(DEFAULT_AGENT_TOOL_MAPPING)
    )
    skill_tool_allowlist: Dict[str, List[str]] = field(
        default_factory=lambda: dict(DEFAULT_SKILL_TOOL_ALLOWLIST)
    )

    def allowed_skills_for_agent(self, agent_name: str) -> List[str]:
        return list(self.agent_skill_mapping.get(agent_name, []))

    def allowed_tools_for_agent(self, agent_name: str) -> List[str]:
        return list(self.agent_tool_mapping.get(agent_name, []))

    def can_agent_use_skill(self, agent_name: str, skill_name: str) -> bool:
        return skill_name in set(self.agent_skill_mapping.get(agent_name, []))

    def can_agent_use_tool(self, agent_name: str, tool_name: str) -> bool:
        return tool_name in set(self.agent_tool_mapping.get(agent_name, []))

    def can_skill_use_tool(self, skill_name: str, tool_name: str) -> bool:
        if skill_name not in self.skill_tool_allowlist:
            return True
        return tool_name in set(self.skill_tool_allowlist.get(skill_name, []))

    def validate_agent_assignment(self, agent_name: str, skills: List[str], tools: List[str]) -> None:
        allowed_skills: Set[str] = set(self.allowed_skills_for_agent(agent_name))
        allowed_tools: Set[str] = set(self.allowed_tools_for_agent(agent_name))

        invalid_skills = [s for s in skills if s not in allowed_skills]
        invalid_tools = [t for t in tools if t not in allowed_tools]
        if invalid_skills or invalid_tools:
            raise ValueError(
                f"Policy violation for agent '{agent_name}': "
                f"invalid_skills={invalid_skills}, invalid_tools={invalid_tools}, "
                f"allowed_skills={sorted(allowed_skills)}, allowed_tools={sorted(allowed_tools)}"
            )

    def validate_mapping_integrity(self) -> None:
        mapped_skills: Set[str] = set()
        for skill_list in self.agent_skill_mapping.values():
            mapped_skills.update(skill_list)
        missing_allowlist = sorted(
            s for s in mapped_skills if s not in self.skill_tool_allowlist
        )
        if missing_allowlist:
            raise ValueError(
                "Policy integrity violation: missing skill_tool_allowlist entries for "
                f"{missing_allowlist}"
            )


# ---------------------------------------------------------------------------
# Base Agent
# ---------------------------------------------------------------------------

MAX_ITERATIONS: int = 1
TOOL_CALL_MAX_ROUNDS: int = 1
MAX_WEB_SEARCH_RESULTS: int = 5


class BaseAgent(AgentActionLoop):
    name: str = ""
    system_prompt: str = ""
    tool_call_max_rounds: int = TOOL_CALL_MAX_ROUNDS

    def __init__(
        self,
        model,
        tools: Optional[List["BaseTool"]] = None,
        registry=None,
        skill_names: Optional[List[str]] = None,
        project_config: Optional[Dict[str, Any]] = None,
    ):
        self.model = model
        self.tools: Dict[str, "BaseTool"] = {t.name: t for t in (tools or [])}
        self.registry = registry
        self.skill_names: List[str] = list(skill_names or [])
        self.policy = None
        self.project_config: Dict[str, Any] = dict(project_config or {})
        self.logger = logging.getLogger(f"Plant.{self.__class__.__name__}")

    def self_review_round_cap(self) -> int:
        """自主複審 OODA 上限（固定常數）。"""
        return MAX_ITERATIONS

    def max_web_search_results_cap(self) -> int:
        """單次 web_search 結果筆數上限；工具實例若已設定則優先採用。"""
        ws = self.tools.get("web_search")
        if ws is not None and hasattr(ws, "max_results_cap"):
            return max(1, int(ws.max_results_cap))
        return MAX_WEB_SEARCH_RESULTS

    def parse_topic_response_json(self, raw: str) -> Dict[str, Any]:
        """解析工具迴圈輸出中的 JSON。"""
        if not raw or not isinstance(raw, str):
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            m = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", raw, re.DOTALL)
            if m:
                try:
                    return json.loads(m.group(0))
                except json.JSONDecodeError:
                    pass
        return {}

    # ------------------------------------------------------------------
    # Meeting helpers
    # ------------------------------------------------------------------

    def sanitize_statement_fallback(self, text: Any) -> str:
        fallback = str(text or "").strip()
        for prefix in ("```json", "```"):
            if fallback.startswith(prefix):
                fallback = fallback[len(prefix) :].strip()
        if fallback.endswith("```"):
            fallback = fallback[:-3].strip()
        if fallback in {"{}", "[]", "null", '""', "```json\n{}\n```", "```json\n[]\n```"}:
            return ""
        return fallback

    _STATEMENT_KEYS = (
        "statement",
        "content",
        "answer",
        "reply",
        "text",
        "message",
        "summary",
        "note",
        "description",
    )

    def extract_statement_from_structured_text(self, text: str) -> str:
        """從 JSON/字典字串中抽取自然語言內容，避免 MoM 出現 JSON 原文。"""
        raw = (text or "").strip()
        if not raw:
            return ""

        # 剝除 ```json fence 或普通 ``` fence
        if raw.startswith("```"):
            first_nl = raw.find("\n")
            if first_nl != -1:
                raw = raw[first_nl + 1 :].strip()
            if raw.endswith("```"):
                raw = raw[:-3].strip()

        if not raw:
            return ""

        parsed: Any = None
        if raw.startswith("{") or raw.startswith("["):
            try:
                parsed = json.loads(raw)
            except Exception:
                try:
                    parsed = ast.literal_eval(raw)
                except Exception:
                    # 試著擷取第一個 {...} 片段
                    m = re.search(r"\{[\s\S]*\}", raw)
                    if m:
                        try:
                            parsed = json.loads(m.group(0))
                        except Exception:
                            try:
                                parsed = ast.literal_eval(m.group(0))
                            except Exception:
                                parsed = None

        if parsed is None:
            return ""

        def pick_from_dict(d: Dict[str, Any]) -> str:
            for key in self._STATEMENT_KEYS:
                v = self.sanitize_statement_fallback(d.get(key))
                if v and not (v.startswith("{") or v.startswith("[")):
                    return v
            # 實在沒有合適鍵，退而求其次把所有字串值串起來
            parts: List[str] = []
            for v in d.values():
                if isinstance(v, str):
                    s = v.strip()
                    if s and not (s.startswith("{") or s.startswith("[")):
                        parts.append(s)
            return " ".join(parts).strip()

        if isinstance(parsed, dict):
            return pick_from_dict(parsed)
        if isinstance(parsed, list):
            parts: List[str] = []
            for item in parsed:
                if isinstance(item, dict):
                    s = pick_from_dict(item)
                    if s:
                        parts.append(s)
                elif isinstance(item, str):
                    s = item.strip()
                    if s:
                        parts.append(s)
            return "\n".join(parts).strip()
        if isinstance(parsed, str):
            return parsed.strip()
        return ""

    def normalize_topic_response_payload(
        self,
        payload: Any,
        *,
        raw_fallback: str = "",
        debug_reason: str = "",
    ) -> Dict[str, Any]:
        data = dict(payload or {}) if isinstance(payload, dict) else {}
        statement = self.sanitize_statement_fallback(data.get("statement"))
        content = self.sanitize_statement_fallback(data.get("content"))
        fallback = self.sanitize_statement_fallback(raw_fallback)
        final_statement = statement or content or fallback
        # Conflict recheck intentionally stores a JSON object string inside
        # `statement` so downstream code can extract pair_reviews. Do not
        # collapse it into an overall_assessment sentence.
        preserve_structured_statement = False
        if final_statement.lstrip().startswith("{") and "pair_reviews" in final_statement:
            try:
                parsed_statement = json.loads(final_statement)
            except Exception:
                parsed_statement = None
            preserve_structured_statement = isinstance(parsed_statement, dict) and isinstance(
                parsed_statement.get("pair_reviews"), list
            )
        if not preserve_structured_statement:
            extracted = self.extract_statement_from_structured_text(final_statement)
            if extracted:
                final_statement = extracted
        normalized = {
            "statement": final_statement,
            "open_questions": (
                data.get("open_questions")
                if isinstance(data.get("open_questions"), list)
                else []
            ),
            "suggested_next_action": (
                data.get("suggested_next_action")
                if isinstance(data.get("suggested_next_action"), dict)
                else None
            ),
        }
        for key, value in data.items():
            if key not in normalized:
                normalized[key] = value
        if debug_reason:
            normalized["_debug_reason"] = debug_reason
        if raw_fallback:
            normalized["_debug_raw_response"] = str(raw_fallback)
        if not final_statement and (data or raw_fallback):
            normalized["_debug_empty_payload"] = True
        return normalized

    # ------------------------------------------------------------------
    # Meeting helpers
    # ------------------------------------------------------------------

    def build_snapshot_text(self, artifact_snapshot: Optional[Dict[str, Any]]) -> str:
        if not artifact_snapshot:
            return ""
        return (
            "\n# 當前專案狀態（供參考）\n"
            f"{json.dumps(artifact_snapshot, ensure_ascii=False, indent=2)}"
        )


    def build_topic_text(self, topic: Dict[str, Any]) -> str:
        return (
            f"議題 [{topic.get('id', '')}]: {topic.get('title', '')}\n"
            f"描述: {topic.get('description', '')}"
        )

    def ensure_json_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        has_json_mention = any(
            "json" in str(msg.get("content") or "").lower()
            for msg in messages or []
            if isinstance(msg, dict)
        )
        if has_json_mention:
            return messages
        updated = list(messages or [])
        updated.append({"role": "user", "content": JSON_OUTPUT_DIRECTIVE})
        return updated

    def chat_json(self, messages: List[Dict[str, Any]], **kwargs: Any) -> Dict[str, Any]:
        return self.model.chat_json(self.ensure_json_messages(messages), **kwargs)

    def chat_for_topic_response(
        self, messages: List[Dict], parse_json: bool = True, **kwargs: Any
    ) -> Dict[str, Any]:
        """有 tools 則 chat_with_tools，否則 chat_json。"""
        if self.tools:
            raw = self.chat_with_tools(messages, max_rounds=self.tool_call_max_rounds)
            if parse_json:
                parsed = self.parse_topic_response_json(raw)
                debug_reason = ""
                if not parsed and (raw or "").strip():
                    debug_reason = "tool_raw_not_json_or_empty"
                elif parsed and not self.sanitize_statement_fallback(parsed.get("statement")):
                    debug_reason = "tool_json_without_statement"
                return self.normalize_topic_response_payload(
                    parsed,
                    raw_fallback=raw,
                    debug_reason=debug_reason,
                )
            return self.normalize_topic_response_payload({"statement": raw, "open_questions": []})
        action = kwargs.pop("action", f"{self.name}.topic.response")
        try:
            parsed = self.chat_json(messages, action=action, **kwargs)
            debug_reason = ""
            if isinstance(parsed, dict) and not self.sanitize_statement_fallback(parsed.get("statement")):
                debug_reason = "chat_json_without_statement"
            return self.normalize_topic_response_payload(parsed, debug_reason=debug_reason)
        except Exception as e:
            self.logger.warning("%s topic.response JSON 解析失敗，改用文字 fallback: %s", self.name, e)
            raw = ""
            try:
                raw = self.model.chat(messages, action=action, **kwargs)
            except Exception as fallback_e:
                self.logger.warning("%s topic.response 文字 fallback 失敗: %s", self.name, fallback_e)
            debug_reason = f"chat_json_exception:{type(e).__name__}"
            return self.normalize_topic_response_payload(
                {},
                raw_fallback=raw,
                debug_reason=debug_reason,
            )

    def chat_for_conflict_topic_response(
        self, messages: List[Dict], parse_json: bool = True, **kwargs: Any
    ) -> Dict[str, Any]:
        """有 tools 則 chat_with_tools，否則 chat_json。"""
        if self.tools:
            raw = self.chat_with_tools(messages, max_rounds=self.tool_call_max_rounds)
            if parse_json:
                parsed = self.parse_topic_response_json(raw)
                # 若解析後 statement 為空但模型有產出文字，用原始文字當 fallback，避免發言/回答留空
                if not (parsed.get("statement") or "").strip() and (raw or "").strip():
                    fallback = (raw or "").strip()
                    for prefix in ("```json", "```"):
                        if fallback.startswith(prefix):
                            fallback = fallback[len(prefix) :].strip()
                    if fallback.endswith("```"):
                        fallback = fallback[:-3].strip()
                    parsed["statement"] = fallback
                return parsed
            return {"statement": raw, "open_questions": []}
        action = kwargs.pop("action", f"{self.name}.topic.response")
        return self.chat_json(messages, action=action, **kwargs)

    def usage_action(self, suffix: str) -> str:
        return f"{self.name}.{suffix}"

    def format_previous_responses(
        self,
        previous_responses: Optional[List[Dict[str, Any]]],
        *,
        title: str = "前面的發言",
    ) -> str:
        """格式化前文發言（含 speaking_as）。"""
        if not previous_responses:
            return ""
        parts: List[str] = []
        for r in previous_responses:
            agent_name = r.get("agent", "?")
            resp = r.get("response", {}) if isinstance(r.get("response"), dict) else {}
            statement = resp.get("statement", "")
            speaking_as = resp.get("speaking_as", [])
            if isinstance(speaking_as, str):
                speaking_as = [speaking_as]
            speaking_as = [s for s in speaking_as if isinstance(s, str) and s.strip()]
            role_hint = f"（代表：{'、'.join(speaking_as)}）" if speaking_as else ""
            parts.append(f"【{agent_name}{role_hint}】\n{statement}")
        return f"\n# {title}\n" + "\n\n".join(parts)

    def get_global_conventions_suffix(self) -> str:
        """全域輸出慣例後綴；子類可覆寫為 ''。"""
        text = global_conventions_text()
        if not text:
            return ""
        return f"\n\n# 全域輸出慣例\n{text}"

    def lang_directive(self) -> str:
        """task 內語系指示。"""
        return directive_embed()

    def get_optional_skill_context(
        self, topic: Dict, artifact_snapshot: Optional[Dict]
    ) -> Optional[str]:
        """討論階段由 agent 自行判斷是否需要使用自己已掛載的 skill。"""
        if not self.skill_names:
            return None
        topic_summary = {
            "id": topic.get("id"),
            "title": topic.get("title"),
            "description": topic.get("description"),
            "category": topic.get("category"),
            "source_ids": topic.get("source_ids") or [],
        }
        decision_prompt = (
            "你正在準備會議討論發言。請判斷是否需要先使用你自己的 skill 產生簡短參考。\n\n"
            f"# Agent\n{self.name}\n\n"
            f"# 可用 skills\n{json.dumps(self.skill_names, ensure_ascii=False)}\n\n"
            f"# 議題\n{json.dumps(topic_summary, ensure_ascii=False, indent=2)}\n\n"
            "# 判斷規則\n"
            "- 只有 skill 能明顯改善本輪發言品質時才使用。\n"
            "- 一次最多選一個 skill。\n"
            "- 若目前只需要一般角色判斷，不要使用 skill。\n"
            "- 不要為了形式而使用 skill。\n\n"
            "# 輸出 JSON\n"
            '{"use_skill": true/false, "skill_name": "可用 skill 名稱或空字串", "reason": "一句理由"}'
        )
        try:
            decision = self.chat_json(self.build_direct_messages(decision_prompt))
        except Exception as e:
            self.logger.debug("討論 skill 使用判斷失敗: %s", e)
            return None

        if not isinstance(decision, dict) or not decision.get("use_skill"):
            return None
        skill_name = str(decision.get("skill_name") or "").strip()
        if skill_name not in self.skill_names:
            return None

        context = {
            "topic": topic,
            "artifact_snapshot": artifact_snapshot or {},
            "usage_reason": decision.get("reason", ""),
        }
        task = (
            "請針對 Context 中的會議議題，依此 skill 產生本 agent 發言前可用的簡短參考。\n"
            "只輸出 1 到 4 點重點；包含必要依據、風險、限制或建議方向。\n"
            "不要產生最終決議，不要改寫 artifact，不要輸出 JSON。"
        )
        try:
            raw = self.invoke_skill(skill_name, task, context=context)
            text = (raw or "").strip()
            if not text:
                return None
            return f"Skill: {skill_name}\nReason: {decision.get('reason', '')}\n{text}"
        except Exception as e:
            self.logger.debug("討論階段使用 skill '%s' 失敗: %s", skill_name, e)
            return None

    def build_topic_response_observation_payload(
        self, **kwargs: Any
    ) -> Dict[str, Any]:
        topic = kwargs["topic"]
        previous_responses = kwargs.get("previous_responses") or []
        artifact_snapshot = kwargs.get("artifact_snapshot") or {}
        return {
            "topic": topic,
            "topic_id": str(topic.get("id") or ""),
            "topic_category": str(topic.get("category") or ""),
            "previous_responses": previous_responses,
            "previous_response_count": len(previous_responses),
            "artifact_snapshot": artifact_snapshot,
            "has_artifact_snapshot": bool(artifact_snapshot),
            "recent_ask_history": topic.get("recent_ask_history") or [],
            "iteration": kwargs.get("iteration", 0) + 1,
            "max_iterations": kwargs.get("max_iterations", 1),
        }

    def decide_default_topic_response_action(
        self,
        observation: Dict[str, Any],
        *,
        reasoning: str,
    ) -> Dict[str, Any]:
        topic = observation.get("topic") or {}
        topic_id = str(topic.get("id") or "")
        if topic.get("category") == "conflict_discussion":
            action = "respond_conflict_discussion"
        else:
            action = "respond_discussion"
        return {
            "action": action,
            "params": {},
            "reasoning": reasoning,
        }

    # ------------------------------------------------------------------
    # Skill execution helpers
    # ------------------------------------------------------------------

    def validate_skill_usage(self, skill_name: str) -> None:
        if skill_name not in self.skill_names:
            raise ValueError(
                f"Agent '{self.name}' 未賦予 skill '{skill_name}'，可用: {self.skill_names}"
            )
        if self.policy and not self.policy.can_agent_use_skill(self.name, skill_name):
            raise ValueError(f"Policy 禁止 Agent '{self.name}' 使用 skill '{skill_name}'")

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
                    "# Skill Guidance\n\n",
                    skill["content_system"],
                    "\n\n",
                ]
            )
        user_parts.extend(
            [
                f"# 輸出語系（必須遵守）\n{self.lang_directive()}\n\n",
                user_content,
                "\n\n# Task\n\n",
                task,
            ]
        )
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
        if context is not None:
            user_parts.append(
                f"\n\n# Context\n{json.dumps(context, ensure_ascii=False, indent=2)}"
            )

        suffix = self.get_global_conventions_suffix()
        if suffix:
            system_parts.append(suffix)
        return [
            {"role": "system", "content": "".join(system_parts)},
            {"role": "user", "content": "\n".join(user_parts)},
        ]

    def run_skill_messages(
        self,
        skill_name: str,
        messages: List[Dict[str, str]],
    ) -> str:
        if self.tools:
            return self.chat_with_tools(
                messages,
                max_rounds=self.tool_call_max_rounds,
                active_skill=skill_name,
            )
        return self.model.chat(
            messages,
            action=self.usage_action(f"skill.{skill_name}"),
        )

    def invoke_skill(
        self,
        skill_name: str,
        task: str,
        context: Optional[Dict] = None,
    ) -> str:
        """
        依名稱呼叫 agent 已賦予的 skill：載入該 skill 的內容與 references，
        組 system + user message 後呼叫 model，回傳模型輸出的字串。
        若此 agent 未賦予該 skill（skill_name 不在 self.skill_names），則拋錯。
        """
        self.validate_skill_usage(skill_name)
        from agents.skills.base import get_skill

        skill = get_skill(skill_name)
        messages = self.build_skill_messages(skill, skill_name, task, context=context)
        return self.run_skill_messages(skill_name, messages)

    def build_direct_messages(self, task: str, context: Optional[Dict] = None) -> List[Dict]:
        messages = []
        system_content = self.system_prompt + self.get_global_conventions_suffix()
        messages.append({"role": "system", "content": system_content})

        task_parts = [
            f"# 輸出語系（必須遵守）\n{self.lang_directive()}\n",
            task,
        ]
        if context:
            task_parts.append(f"\n上下文資料:\n{json.dumps(context, ensure_ascii=False, indent=2)}")
        messages.append({"role": "user", "content": "\n".join(task_parts)})
        return messages

    def execute_tool(
        self, tool_name: str, tool_args: Dict, *, active_skill: Optional[str] = None
    ) -> str:
        if tool_name not in self.tools:
            return f"錯誤: 未知工具 '{tool_name}'，可用: {list(self.tools.keys())}"
        if self.policy and not self.policy.can_agent_use_tool(self.name, tool_name):
            return f"錯誤: Policy 禁止 Agent '{self.name}' 使用工具 '{tool_name}'"
        if (
            active_skill
            and self.policy
            and not self.policy.can_skill_use_tool(active_skill, tool_name)
        ):
            return (
                f"錯誤: Policy 禁止在 skill '{active_skill}' 使用工具 '{tool_name}'"
            )

        tool = self.tools[tool_name]
        if not tool.validate_args(**tool_args):
            return f"錯誤: 工具 '{tool_name}' 參數不完整"

        try:
            return tool.execute(**tool_args)
        except Exception as e:
            return f"工具 '{tool_name}' 執行失敗: {str(e)}"

    def get_tool_schemas(self) -> List[Dict]:
        """將 self.tools 轉為 OpenAI function calling 格式"""
        schemas = []
        for tool in self.tools.values():
            properties = {}
            required = []
            for pname, pinfo in tool.parameters.items():
                ptype = pinfo.get("type", "string")
                prop = {
                    "type": pinfo.get("type", "string"),
                    "description": pinfo.get("description", ""),
                }
                # OpenAI function schema: array 必須提供 items。
                if ptype == "array":
                    prop["items"] = pinfo.get("items", {"type": "string"})
                properties[pname] = prop
                if pinfo.get("required", False):
                    required.append(pname)
            schemas.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": required,
                    },
                },
            })
        return schemas

    def supports_tool_calling(self) -> bool:
        """是否為 OpenAI 相容 client（支援 chat.completions.create 的 tools 參數）"""
        try:
            c = getattr(self.model, "client", None)
            return hasattr(c, "chat") and hasattr(c.chat, "completions")
        except Exception:
            return False

    def supports_gemini_tool_calling(self) -> bool:
        """Gemini（google-genai）手動 function calling，見 GeminiModel.gemini_chat_with_tools。"""
        return callable(getattr(self.model, "gemini_chat_with_tools", None))

    def reset_tool_sessions(self) -> None:
        for t in (self.tools or {}).values():
            reset = getattr(t, "reset_session", None)
            if callable(reset):
                try:
                    reset()
                except Exception as e:
                    self.logger.debug("tool reset_session: %s", e)

    # ------------------------------------------------------------------
    # Tool execution helpers
    # ------------------------------------------------------------------

    def tool_loop_action(self, active_skill: Optional[str] = None) -> str:
        return self.usage_action(
            f"tool_loop.{active_skill}" if active_skill else "tool_loop.general"
        )

    def parse_tool_arguments(self, raw_arguments: str) -> Dict[str, Any]:
        try:
            return json.loads(raw_arguments)
        except json.JSONDecodeError:
            return {}

    def run_single_tool_call(
        self,
        tool_call: Any,
        *,
        active_skill: Optional[str] = None,
    ) -> tuple[str, str]:
        fname = tool_call.function.name
        fargs = self.parse_tool_arguments(tool_call.function.arguments)
        self.logger.info("🔧 %s(%s)", fname, fargs)
        result = self.execute_tool(fname, fargs, active_skill=active_skill)
        return tool_call.id, result

    def append_openai_tool_results(
        self,
        messages: List[Dict[str, Any]],
        tool_calls_list: List[Any],
        *,
        active_skill: Optional[str] = None,
    ) -> None:
        if len(tool_calls_list) == 1:
            tool_call_id, result = self.run_single_tool_call(
                tool_calls_list[0], active_skill=active_skill
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": result,
                }
            )
            return

        max_workers = min(len(tool_calls_list), 6)
        results_by_id: Dict[str, str] = {}
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_tc = {
                executor.submit(
                    self.run_single_tool_call, tc, active_skill=active_skill
                ): tc
                for tc in tool_calls_list
            }
            for future in as_completed(future_to_tc):
                tc = future_to_tc[future]
                try:
                    tool_call_id, result = future.result()
                    results_by_id[tool_call_id] = result
                except Exception as e:
                    results_by_id[tc.id] = f"工具執行失敗: {e}"
        for tc in tool_calls_list:
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": results_by_id.get(tc.id, ""),
                }
            )

    def chat_with_gemini_tools(
        self,
        messages: List[Dict[str, Any]],
        max_rounds: int,
        *,
        active_skill: Optional[str] = None,
    ) -> str:
        return self.model.gemini_chat_with_tools(
            messages,
            openai_style_tool_schemas=self.get_tool_schemas(),
            execute_tool_fn=lambda name, args: self.execute_tool(
                name, args, active_skill=active_skill
            ),
            max_rounds=max_rounds,
            action=self.tool_loop_action(active_skill),
        )

    def chat_with_openai_tools(
        self,
        messages: List[Dict[str, Any]],
        max_rounds: int,
        *,
        active_skill: Optional[str] = None,
    ) -> str:
        tool_schemas = self.get_tool_schemas()
        action = self.tool_loop_action(active_skill)
        tracker = self.model.costTracker
        for _ in range(max_rounds):
            tracker.start()
            response = None
            try:
                response = self.model.client.chat.completions.create(
                    model=self.model.model_name,
                    messages=messages,
                    tools=tool_schemas,
                    tool_choice="auto",
                )
            except (AttributeError, TypeError) as e:
                tracker.end_segment()
                self.logger.warning("tool calling 呼叫失敗，改為普通 chat: %s", e)
                return self.model.chat(
                    messages,
                    action=self.usage_action("chat.tool_calling_fallback"),
                )
            finally:
                run_s = tracker.end_segment()
            raw_usage = getattr(response, "usage", None)
            if raw_usage:
                self.model.addUsage(
                    {
                        "prompt_tokens": getattr(raw_usage, "prompt_tokens", 0),
                        "completion_tokens": getattr(raw_usage, "completion_tokens", 0),
                        "total_tokens": getattr(raw_usage, "total_tokens", 0),
                    },
                    action=action,
                    run_time_s=run_s,
                )
            msg = response.choices[0].message
            if not getattr(msg, "tool_calls", None):
                return msg.content or ""
            messages.append(msg.model_dump())
            self.append_openai_tool_results(
                messages,
                list(msg.tool_calls),
                active_skill=active_skill,
            )

        tracker.start()
        last = None
        try:
            last = self.model.client.chat.completions.create(
                model=self.model.model_name,
                messages=messages,
            )
        except (AttributeError, TypeError):
            tracker.end_segment()
            return self.model.chat(
                messages,
                action=self.usage_action("chat.final_fallback"),
            )
        finally:
            run_s = tracker.end_segment()
        raw_usage = getattr(last, "usage", None)
        if raw_usage:
            self.model.addUsage(
                {
                    "prompt_tokens": getattr(raw_usage, "prompt_tokens", 0),
                    "completion_tokens": getattr(raw_usage, "completion_tokens", 0),
                    "total_tokens": getattr(raw_usage, "total_tokens", 0),
                },
                action=action,
                run_time_s=run_s,
            )
        return last.choices[0].message.content or ""

    def chat_with_tools(
        self,
        messages: List[Dict],
        max_rounds: int = 3,
        *,
        active_skill: Optional[str] = None,
    ) -> str:
        """帶 tool-call 迴圈的 chat：模型可多次呼叫工具，最終回傳文字結果。若 client 不支援 tool calling 則改為普通 chat。
        active_skill：若為 skill 情境（如 domain-research），會額外套用 policy.can_skill_use_tool。"""
        self.reset_tool_sessions()
        if not self.tools:
            return self.model.chat(
                messages,
                action=self.usage_action("chat.with_tools"),
            )
        if self.supports_gemini_tool_calling():
            return self.chat_with_gemini_tools(
                messages,
                max_rounds,
                active_skill=active_skill,
            )
        if not self.supports_tool_calling():
            self.logger.warning("目前 model client 不支援 tool calling，改為普通 chat（工具不會被呼叫）")
            return self.model.chat(
                messages,
                action=self.usage_action("chat.no_tool_support"),
            )
        return self.chat_with_openai_tools(
            messages,
            max_rounds,
            active_skill=active_skill,
        )
