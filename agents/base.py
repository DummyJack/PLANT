import json
import re
import logging
import ast
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from typing import Any, Dict, List, Optional, Set
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
    "modeler": ["plantuml-syntax"],
    "documentor": ["srs-generation"],
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
    "domain-research": ["web_search", "file_parser"],
    "requirements-analyst": ["artifact_query"],
    "conflict-analyzer": [],
    "srs-generation": ["artifact_query"],
    "plantuml-syntax": ["plantuml_validate", "artifact_query"],
}


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

from utils import MAX_ITERATIONS, TOOL_CALL_MAX_ROUNDS, MAX_WEB_SEARCH_RESULTS


class BaseAgent:
    name: str = ""
    system_prompt: str = ""
    tool_call_max_rounds: int = TOOL_CALL_MAX_ROUNDS

    def __init__(
        self,
        model,
        tools: Optional[List[BaseTool]] = None,
        registry=None,
        skill_names: Optional[List[str]] = None,
        project_config: Optional[Dict[str, Any]] = None,
    ):
        self.model = model
        self.tools: Dict[str, BaseTool] = {t.name: t for t in (tools or [])}
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

    def _sanitize_statement_fallback(self, text: Any) -> str:
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

    def _extract_statement_from_structured_text(self, text: str) -> str:
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

        def _pick_from_dict(d: Dict[str, Any]) -> str:
            for key in self._STATEMENT_KEYS:
                v = self._sanitize_statement_fallback(d.get(key))
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
            return _pick_from_dict(parsed)
        if isinstance(parsed, list):
            parts: List[str] = []
            for item in parsed:
                if isinstance(item, dict):
                    s = _pick_from_dict(item)
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

    def _normalize_topic_response_payload(
        self,
        payload: Any,
        *,
        raw_fallback: str = "",
        debug_reason: str = "",
    ) -> Dict[str, Any]:
        data = dict(payload or {}) if isinstance(payload, dict) else {}
        statement = self._sanitize_statement_fallback(data.get("statement"))
        content = self._sanitize_statement_fallback(data.get("content"))
        fallback = self._sanitize_statement_fallback(raw_fallback)
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
            extracted = self._extract_statement_from_structured_text(final_statement)
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

    def _build_snapshot_text(self, artifact_snapshot: Optional[Dict[str, Any]]) -> str:
        if not artifact_snapshot:
            return ""
        return (
            "\n# 當前專案狀態（供參考）\n"
            f"{json.dumps(artifact_snapshot, ensure_ascii=False, indent=2)}"
        )

    def _build_tool_hint_for_meeting(self) -> str:
        if not self.tools:
            return ""
        return (
            "\n# 工具使用\n"
            "- 若需要查證、搜尋或驗證，可先使用可用工具。\n"
            "- 使用完工具後，**必須**根據結果與你的判斷輸出下列 JSON，勿僅回傳工具結果。"
        )

    def _build_topic_text(self, topic: Dict[str, Any]) -> str:
        return (
            f"議題 [{topic.get('id', '')}]: {topic.get('title', '')}\n"
            f"描述: {topic.get('description', '')}"
        )

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
                elif parsed and not self._sanitize_statement_fallback(parsed.get("statement")):
                    debug_reason = "tool_json_without_statement"
                return self._normalize_topic_response_payload(
                    parsed,
                    raw_fallback=raw,
                    debug_reason=debug_reason,
                )
            return self._normalize_topic_response_payload({"statement": raw, "open_questions": []})
        action = kwargs.pop("action", f"{self.name}.topic.response")
        try:
            parsed = self.model.chat_json(messages, action=action, **kwargs)
            debug_reason = ""
            if isinstance(parsed, dict) and not self._sanitize_statement_fallback(parsed.get("statement")):
                debug_reason = "chat_json_without_statement"
            return self._normalize_topic_response_payload(parsed, debug_reason=debug_reason)
        except Exception as e:
            self.logger.warning("%s topic.response JSON 解析失敗，改用文字 fallback: %s", self.name, e)
            raw = ""
            try:
                raw = self.model.chat(messages, action=action, **kwargs)
            except Exception as fallback_e:
                self.logger.warning("%s topic.response 文字 fallback 失敗: %s", self.name, fallback_e)
            debug_reason = f"chat_json_exception:{type(e).__name__}"
            return self._normalize_topic_response_payload(
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
        return self.model.chat_json(messages, action=action, **kwargs)

    def usage_action(self, suffix: str) -> str:
        return f"{self.name}.{suffix}"

    # ------------------------------------------------------------------
    # OPA helpers
    # ------------------------------------------------------------------

    def build_observation(self, *, mode: str, **kwargs: Any) -> Dict[str, Any]:
        raise NotImplementedError(
            f"{self.__class__.__name__} 尚未實作 build_observation(mode={mode!r})"
        )

    def decide_action(
        self,
        *,
        mode: str,
        observation: Dict[str, Any],
        last_result: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        raise NotImplementedError(
            f"{self.__class__.__name__} 尚未實作 decide_action(mode={mode!r})"
        )

    def execute_action(
        self,
        *,
        mode: str,
        decision: Dict[str, Any],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        raise NotImplementedError(
            f"{self.__class__.__name__} 尚未實作 execute_action(mode={mode!r})"
        )

    def summarize_opa_observation(
        self, observation: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        if not isinstance(observation, dict):
            return {}
        summary: Dict[str, Any] = {}
        for key in (
            "iteration",
            "max_iterations",
            "requirements_count",
            "has_scan_results",
            "has_validator",
        ):
            if key in observation:
                summary[key] = observation.get(key)
        if "conflicts" in observation and isinstance(observation.get("conflicts"), list):
            summary["conflict_count"] = len(observation.get("conflicts") or [])
        if "recent_discussions" in observation and isinstance(
            observation.get("recent_discussions"), list
        ):
            summary["recent_discussion_count"] = len(
                observation.get("recent_discussions") or []
            )
        if "current_models" in observation and isinstance(
            observation.get("current_models"), list
        ):
            summary["current_model_count"] = len(observation.get("current_models") or [])
        if not summary:
            summary["keys"] = sorted(observation.keys())
        return summary

    def make_opa_trace_entry(
        self,
        *,
        mode: str,
        iteration: int,
        observation: Dict[str, Any],
        decision: Dict[str, Any],
        result: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        return {
            "agent": self.name,
            "mode": mode,
            "iteration": iteration,
            "observation": self.summarize_opa_observation(observation),
            "decision": dict(decision or {}),
            "result": dict(result or {}),
        }

    def run_opa_loop(
        self,
        *,
        mode: str,
        max_iterations: int,
        loop_cap: int,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        context = dict(context or {})
        observation = None
        actions_taken = []
        pending_issues = context.setdefault("pending_issues", [])
        effective_max = min(max_iterations, loop_cap)
        i = 0

        while i < effective_max:
            observation = self.build_observation(
                mode=mode,
                iteration=i,
                max_iterations=effective_max,
                actions_taken=actions_taken,
                **context,
            )
            decision = self.decide_action(
                mode=mode,
                observation=observation,
                last_result=context.get("last_result"),
                **context,
            )
            if i == 0:
                n = decision.get("max_iterations")
                if n is not None and isinstance(n, int) and 1 <= n <= effective_max:
                    effective_max = n
                    self.logger.info(
                        "  %s %s 輪數: %s/%s",
                        self.__class__.__name__.replace("Agent", ""),
                        mode,
                        effective_max,
                        loop_cap,
                    )
            action = decision.get("action", "done")
            self.logger.info("  %s %s [%s/%s]: %s", self.__class__.__name__.replace("Agent", ""), mode, i + 1, effective_max, action)
            if action == "done":
                break

            result = self.execute_action(
                mode=mode,
                decision=decision,
                observation=observation,
                **context,
            )
            context["last_result"] = result
            if isinstance(result, dict):
                context_updates = result.get("context_updates")
                if isinstance(context_updates, dict):
                    context.update(context_updates)
            actions_taken.append(
                {
                    "action": action,
                    "params": decision.get("params") or {},
                    "result_summary": (result or {}).get("summary", ""),
                }
            )
            if result and result.get("error"):
                self.logger.warning("  %s %s error: %s", self.__class__.__name__.replace("Agent", ""), mode, result["error"])
            context.setdefault("opa_trace", []).append(
                self.make_opa_trace_entry(
                    mode=mode,
                    iteration=i + 1,
                    observation=observation,
                    decision=decision,
                    result=result,
                )
            )
            i += 1

        return {
            "agent": self.name,
            "actions_taken": actions_taken,
            "pending_issues": pending_issues,
            "opa_trace": context.get("opa_trace", []),
        }

    def run_single_opa(
        self,
        *,
        mode: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        context = dict(context or {})
        observation = self.build_observation(
            mode=mode,
            iteration=0,
            max_iterations=1,
            actions_taken=[],
            **context,
        )
        decision = self.decide_action(
            mode=mode,
            observation=observation,
            last_result=None,
            **context,
        )
        result = self.execute_action(
            mode=mode,
            decision=decision,
            observation=observation,
            **context,
        )
        trace_entry = self.make_opa_trace_entry(
            mode=mode,
            iteration=1,
            observation=observation,
            decision=decision,
            result=result,
        )
        return {
            "agent": self.name,
            "decision": decision,
            "result": result,
            "opa_trace": [trace_entry],
        }

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
        from utils import global_conventions_text

        text = global_conventions_text()
        if not text:
            return ""
        return f"\n\n# 全域輸出慣例\n{text}"

    def lang_directive(self) -> str:
        """task 內語系指示。"""
        from utils import directive_embed

        return directive_embed()

    def get_optional_skill_context(
        self, topic: Dict, artifact_snapshot: Optional[Dict]
    ) -> Optional[str]:
        """可選 skill 參考；預設 None。子類覆寫。"""
        return None

    def vote_on_topic(
        self,
        topic: Dict,
        previous_responses: Optional[List[Dict]] = None,
        artifact_snapshot: Optional[Dict] = None,
        mediator_compromise: Optional[Dict] = None,
    ) -> Dict[str, str]:
        """議題討論完成後的最終投票。僅回傳 vote 與簡短理由。

        若傳入 mediator_compromise 且含有效方案內容，表決對象為「是否同意採納該主持人方案」，
        而非評判其他與會者發言。
        """
        topic_text = self._build_topic_text(topic)

        mc = mediator_compromise or {}
        mc_title = (mc.get("title") or "").strip()
        mc_desc = (mc.get("description") or "").strip()
        mc_rat = (mc.get("rationale") or "").strip()
        has_mediator_package = bool(mc_desc or mc_title)

        prev_text = ""
        if not has_mediator_package:
            prev_text = self.format_previous_responses(
                previous_responses, title="本議題討論摘要（依發言順序）"
            )

        proposal_text = ""
        if has_mediator_package:
            proposal_text = (
                "\n# 主持人提出的折衷方案（**本題唯一表決對象**）\n"
                f"**標題**: {mc_title or '（無標題）'}\n\n"
                f"**內容**:\n{mc_desc}\n\n"
                f"**說明**: {mc_rat}\n\n"
                "**重要**: 請僅針對上述主持人方案表決是否願意採納為本議題決議基礎；"
                "勿改為比較或評判其他與會者先前發言孰是孰非。\n"
            )

        snapshot_text = self._build_snapshot_text(artifact_snapshot)

        if has_mediator_package:
            task_block = """# 任務
- 你正在對「主持人折衷方案」表決是否同意採納（非對整場發言做總評）
- 只需給出 vote 與簡短 rationale（1-2 句）

# 投票規則
- vote 只能是 "agreed" 或 "unresolved"
- agreed：你**同意**以主持人方案作為本議題決議基礎
- unresolved：你**無法接受**該方案（或認為仍有違反你專業底線／關鍵資訊不足），需再修訂
"""
        else:
            task_block = """# 任務
- 主持人方案未能產生，請根據本議題討論摘要與你的專業立場表決
- 只需給出 vote 與簡短 rationale（1-2 句）

# 投票規則
- vote 只能是 "agreed" 或 "unresolved"
- agreed：你認為本議題可形成決策
- unresolved：你認為仍有重要衝突或關鍵不確定，暫不應定案
"""

        user_prompt = f"""你正在進行本議題的「最終投票」。

{topic_text}
{proposal_text}{prev_text}
{snapshot_text}

{task_block}
# 約束
- 不要重寫長篇發言
- 不要新增 open_questions
- 若資訊不足，請投 unresolved 並在 rationale 說明原因

輸出 JSON:
{{
    "vote": "agreed 或 unresolved",
    "rationale": "簡短理由"
}}"""

        messages = self.build_direct_messages(user_prompt)
        response = self.chat_for_topic_response(
            messages,
            action=self.usage_action("topic.vote"),
        )
        v = (response.get("vote") or "").strip().lower()
        vote = "agreed" if v == "agreed" else "unresolved"
        rationale = (
            response.get("rationale")
            or response.get("reason")
            or response.get("statement")
            or ""
        )
        return {"agent": self.name, "vote": vote, "rationale": rationale}

    # ------------------------------------------------------------------
    # Skill execution helpers
    # ------------------------------------------------------------------

    def _validate_skill_usage(self, skill_name: str) -> None:
        if skill_name not in self.skill_names:
            raise ValueError(
                f"Agent '{self.name}' 未賦予 skill '{skill_name}'，可用: {self.skill_names}"
            )
        if self.policy and not self.policy.can_agent_use_skill(self.name, skill_name):
            raise ValueError(f"Policy 禁止 Agent '{self.name}' 使用 skill '{skill_name}'")

    def _build_skill_messages(
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

    def _run_skill_messages(
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
        self._validate_skill_usage(skill_name)
        from agents.skills.base import get_skill

        skill = get_skill(skill_name)
        messages = self._build_skill_messages(skill, skill_name, task, context=context)
        return self._run_skill_messages(skill_name, messages)

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

    def _tool_loop_action(self, active_skill: Optional[str] = None) -> str:
        return self.usage_action(
            f"tool_loop.{active_skill}" if active_skill else "tool_loop.general"
        )

    def _parse_tool_arguments(self, raw_arguments: str) -> Dict[str, Any]:
        try:
            return json.loads(raw_arguments)
        except json.JSONDecodeError:
            return {}

    def _run_single_tool_call(
        self,
        tool_call: Any,
        *,
        active_skill: Optional[str] = None,
    ) -> tuple[str, str]:
        fname = tool_call.function.name
        fargs = self._parse_tool_arguments(tool_call.function.arguments)
        self.logger.info("🔧 %s(%s)", fname, fargs)
        result = self.execute_tool(fname, fargs, active_skill=active_skill)
        return tool_call.id, result

    def _append_openai_tool_results(
        self,
        messages: List[Dict[str, Any]],
        tool_calls_list: List[Any],
        *,
        active_skill: Optional[str] = None,
    ) -> None:
        if len(tool_calls_list) == 1:
            tool_call_id, result = self._run_single_tool_call(
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
                    self._run_single_tool_call, tc, active_skill=active_skill
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

    def _chat_with_gemini_tools(
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
            action=self._tool_loop_action(active_skill),
        )

    def _chat_with_openai_tools(
        self,
        messages: List[Dict[str, Any]],
        max_rounds: int,
        *,
        active_skill: Optional[str] = None,
    ) -> str:
        tool_schemas = self.get_tool_schemas()
        action = self._tool_loop_action(active_skill)
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
            self._append_openai_tool_results(
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
            return self._chat_with_gemini_tools(
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
        return self._chat_with_openai_tools(
            messages,
            max_rounds,
            active_skill=active_skill,
        )
