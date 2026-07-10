# Handles shared agent profile prompts and helper behavior.
import json
from typing import Any, Dict, List, Optional

from agents.profile.analyst.conflicts import conflict_entries_count
from storage.requirements import requirement_discussion_pool
from agents.profile.mediator.rules import issue_required_actions

from .conflict import ConflictPlan
from .elicitation import ElicitationPlan
from ..validation import (
    issue_type_ids,
    issue_types,
    meeting_actions,
    meeting_action_decision,
    meeting_issue,
)


CATEGORY_ALIASES = {
    "requirement_completeness": "clarify_requirement",
    "open_question_answer": "clarify_requirement",
    "new_requirement": "clarify_requirement",
    "boundary_responsibility": "define_boundary",
    "model_alignment": "align_model",
}


# ========
# Defines normalized discussion rounds function for this module workflow.
# ========
def normalized_discussion_rounds(value: Any, fallback: int = 1) -> int:
    if value in (None, ""):
        value = fallback
    try:
        return max(1, min(3, int(value)))
    except (TypeError, ValueError):
        return 1


# ========
# Defines select issues function for this module workflow.
# ========
def select_issues(
    *,
    proposals: List[Dict[str, Any]],
    max_items: int,
    skip_artifact_ids: List[str],
    is_last_round: bool,
    round_num: int,
) -> str:
    return f"""# 任務
請根據非預設議題提案進行分流，產生本輪正式會議議題、backlog 與 discarded。

# 非預設議題提案
{json.dumps(proposals, ensure_ascii=False, indent=2)}

- 本輪 round={round_num}，is_last_round={str(is_last_round).lower()}，max_issues={max_items}，already_discussed_artifact_ids={json.dumps(skip_artifact_ids, ensure_ascii=False)}。
- 只處理非 mediator 提案；mediator 預設提案已由程式直接送入正式會議規劃。
- proposal 是候選訊號；Mediator 負責合併、淘汰、排序與定題。
- proposed_by="human" 是人工加入議題；只要格式有效且數量未超過 max_issues，必須納入本輪 issues，不得直接 discarded、不得只放 backlog，也不得被一般 agent 議題擠掉。
- human 議題不必固定排第一；Mediator 應依 blocking 程度、依賴順序、衝突風險、SRS 定稿影響安排討論順序。若 human 議題依賴其他議題的結論，可排在相關前置議題之後。
- proposal.category 只表示正式會議類型；proposal.issue_focus 表示排序焦點。
- proposal.issue_level 分為 blocking / improvement：
  - blocking：會阻礙 SRS 定稿、可驗收性、可追蹤性、一致性、責任邊界或外部證據底線，優先進 issues。
  - improvement：可改善需求品質、模型一致性、風險揭露或驗收完整性；只有本輪容量足夠且不擠壓 blocking 時才進 issues，否則放 backlog。
- 一般議題不得重複提出預設會議已處理的泛稱衝突解決或需求正式化；需求衝突只由預設會議處理。
- 需要正式會議才能處理的共同問題可進 issues/backlog；只有純格式、純措辭、無決策影響且不影響驗收、追蹤、責任邊界、風險、模型一致性或 SRS 可用性的項目才放 discarded。
- 正式議題優先代表一組相關需求背後的共同問題。
- 單一 REQ、單一 open question、單一 acceptance criteria、單一 source 或單一模型項目，只要 source/evidence 具體且可能影響驗收、追蹤、責任邊界、風險、模型一致性或 SRS 可用性，也可以進 issues/backlog；不要只因為範圍小就丟棄。
- 若多筆提案指向同一共同問題，合併成一個議題，保留 trace.proposal_ids 與來源追蹤。
- 在不犧牲 blocking 優先級與具體 source 的前提下，issues 應盡量涵蓋不同 category / issue_focus；避免本輪全部選成同一類型，除非其他類型沒有足夠證據或都已討論過。
- 若同一類型有多筆相近候選，先選該類型中最值得討論、最能阻礙或改善 SRS 品質的一筆代表；其餘合併或放 backlog。
- 避免重複討論 already_discussed_artifact_ids 已涵蓋的提案。
- 不要新增輸入資料沒有支持的新需求。

1. requirement_completeness：既有 REQ-* 缺或弱化 acceptance criteria、NFR category、metric、validation、外部限制影響、source coverage，或 title、description、rationale、risks、assumptions 不清楚、混雜、不可測、不可追溯、只是重述需求。
2. boundary_responsibility：系統、人工、第三方或角色責任不清。
3. tradeoff：多方需求有方案取捨但尚未形成衝突。
4. model_alignment：模型揭露流程、狀態、actor、資料或責任不一致。
5. new_requirement：新增或延伸需求；只有前面高優先缺口不阻礙定稿時才選入。

- issues：blocking 優先；若仍有容量，可放入 source 具體且能明顯改善 Specific / Testable / Traceable / Consistent 的 improvement。
- backlog：有價值但本輪排不下、證據尚不成熟、或屬 improvement 但容量不足的候選。
- discarded：低價值、重複、已涵蓋、沒有 source、只補格式/措辭且不影響需求品質，或不需要正式會議的候選。
- importance=low 除非最後一輪且會阻礙定稿，否則放 discarded；不要放 backlog。
- discarded 每筆至少保留 title、reason、source proposal id 或 trace，並用一句話說明丟棄原因；discarded 不會進入會議，但會保留供稽核。

# 輸出 JSON
{{
  "issues": [],
  "backlog": [],
  "discarded": []
}}"""


# ========
# Defines meeting plan function for this module workflow.
# ========
def meeting_plan(
    *,
    issue: Dict[str, Any],
    related_context: Dict[str, Any],
    active_types: List[str],
    category_definitions: str,
    registered: List[str],
    stakeholder_names: List[str],
) -> str:
    category_values = "|".join([str(x).strip() for x in (active_types or []) if str(x).strip()])
    if not category_values:
        category_values = "clarify_requirement|define_boundary|tradeoff|align_model"
    return f"""# 任務
把已選入正式會議的單一議題提案，轉成一筆可執行的正式會議議題。

# 議題提案
{json.dumps(issue, ensure_ascii=False, indent=2)}

# 相關專案資料
{json.dumps(related_context, ensure_ascii=False, indent=2)}

{category_definitions}

# 可用利害關係人
{json.dumps(stakeholder_names, ensure_ascii=False, indent=2)}

- category 只能使用可用類型。
- participants 只能使用 agents={json.dumps(registered, ensure_ascii=False)}。
- 每位 participant 都必須有 participant_reasoning；沒有明確貢獻就不要加入。
- proposed_by 若是 analyst/expert/modeler/user 且不是 mediator，participants 必須包含該提案人。
- participants 包含 user 時，必須填 target_stakeholders，且只能從可用利害關係人選擇真正需要表態的人。
- title 必須描述群組化共同問題，不要只用單一來源 id、單一欄位缺口或單一 open question 命名。
- description 只寫會前要討論的共同問題，保持短句。
- discussion_mode 只能是 sequential 或 simultaneous。
- sequential 用於需要依序比對證據、修正結論、釐清依賴、處理取捨或模型對齊。
- simultaneous 用於快速蒐集獨立觀點、風險或影響範圍。
- discussion_rounds 是最低討論深度，必須輸出 1~3；系統可依 needs_more_discussion 額外延長。
- 討論深度規則：
  - Level 1 確認型：需求已清楚，只需確認或小修，discussion_rounds=1。
  - Level 2 釐清型：需求語意、驗收、責任邊界還需要互相回應，discussion_rounds=2。
  - Level 3 取捨/衝突型：多方利益衝突、方案選擇、模型/需求不一致，discussion_rounds=3。

- clarify_requirement：通常需要 analyst；只有需要利害關係人確認時才加入 user。
- define_boundary：需要 analyst；涉及流程、資料、actor、狀態、系統邊界或責任分工時加入 modeler。
- tradeoff：需要 analyst 與受影響的 user；若 feedback、evidence_type、coverage 或 gaps 指出外部限制或領域風險時加入 expert。
- align_model：需要 modeler；會改 REQ 時加入 analyst；需要利害關係人確認流程時加入 user。

- trace.artifact_ids 優先使用 proposal.sources[*].ids。
- 若 evidence 內有 URL-*、REQ-*、CR-*、SM-*，也要納入 trace.artifact_ids。
- trace.proposal_ids 必須保留 proposal id。
- 不要編造來源 id。
- expected_actions 只保留討論中真正需要立即執行的 action hint。
- category=align_model 時，expected_actions 必須包含 system_modeling，且 participants 必須包含 modeler。

# 輸出 JSON
{{
  "issues": [
    {{
      "title": "正式會議議題標題",
      "description": "可選，簡短說明會前要討論的共同問題",
      "category": "{category_values}",
      "participants": ["analyst", "modeler"],
      "discussion_mode": "sequential",
      "discussion_rounds": 2,
      "target_stakeholders": [],
      "trace": {{"artifact_ids": ["..."], "proposal_ids": ["R1-I1"]}},
      "proposed_by": "analyst",
      "issue_level": "blocking | improvement",
      "expected_actions": {{}},
      "participant_reasoning": {{"analyst": "需要修正受影響 REQ 欄位", "user": "需要確認利害關係人可接受條件"}}
    }}
  ]
}}"""


def repair_issue_selection(
    *,
    proposals: List[Dict[str, Any]],
    backlog: List[Dict[str, Any]],
    discarded: List[Dict[str, Any]],
    errors: List[str],
    max_items: int,
    skip_artifact_ids: List[str],
    is_last_round: bool,
    round_num: int,
) -> str:
    return f"""# 任務
上一次正式會議議題分流沒有產生可執行 issues。請由 Mediator 重新判斷是否應從候選或 backlog 中選出本輪正式會議議題。

# 可用候選 proposals
{json.dumps(proposals, ensure_ascii=False, indent=2)}

# 既有 backlog
{json.dumps(backlog, ensure_ascii=False, indent=2)}

# 既有 discarded
{json.dumps(discarded, ensure_ascii=False, indent=2)}

# 錯誤原因
{json.dumps(errors, ensure_ascii=False, indent=2)}

- 本輪 round={round_num}，is_last_round={str(is_last_round).lower()}，max_issues={max_items}，already_discussed_artifact_ids={json.dumps(skip_artifact_ids, ensure_ascii=False)}。
- 系統只提供候選、限制與錯誤原因；由 Mediator 自行判斷是否選入。
- 若有 proposed_by="human" 且格式有效，必須選入 issues，除非它重複或沒有任何可追蹤來源。
- 不要新增輸入沒有支持的新議題。
- 只選具體且可追蹤的 high/medium 或 blocking 議題；low 通常放 discarded。
- 若確定沒有任何值得正式會議處理的議題，可以讓 issues 為空，但必須在 discarded 說明原因。
- 回傳格式必須與原本分流相同。

# 輸出 JSON
{{
  "issues": [],
  "backlog": [],
  "discarded": []
}}"""


def repair_meeting_plan(
    *,
    proposal: Dict[str, Any],
    related_context: Dict[str, Any],
    invalid_output: Dict[str, Any],
    errors: List[str],
    active_types: List[str],
    category_definitions: str,
    registered: List[str],
    stakeholder_names: List[str],
) -> str:
    category_values = "|".join([str(x).strip() for x in (active_types or []) if str(x).strip()])
    if not category_values:
        category_values = "clarify_requirement|define_boundary|tradeoff|align_model"
    return f"""# 任務
上一次把提案轉成正式會議議題時格式無效。請 Mediator 根據錯誤原因修正，重新輸出有效 meeting issue。

# 原始議題提案
{json.dumps(proposal, ensure_ascii=False, indent=2)}

# 相關專案資料
{json.dumps(related_context, ensure_ascii=False, indent=2)}

# 上一次無效輸出
{json.dumps(invalid_output, ensure_ascii=False, indent=2)}

# 錯誤原因
{json.dumps(errors, ensure_ascii=False, indent=2)}

{category_definitions}

# 可用利害關係人
{json.dumps(stakeholder_names, ensure_ascii=False, indent=2)}

- category 只能使用：{category_values}
- participants 只能使用 agents={json.dumps(registered, ensure_ascii=False)}。
- 每位 participant 都必須有 participant_reasoning。
- proposed_by 若是 analyst/expert/modeler/user 且不是 mediator，participants 必須包含該提案人。
- participants 包含 user 時，target_stakeholders 必須從可用利害關係人選擇；如果不需要利害關係人表態，不要加入 user。
- trace 必須是 object，保留 proposal id，artifact_ids 只能使用輸入可追蹤來源。
- discussion_mode 只能是 sequential 或 simultaneous。
- discussion_rounds 必須是 1、2 或 3。
- 不要用程式預設硬補；請依提案內容自行決定最小可執行議題。
- 若此提案其實不應成為正式會議議題，輸出 issues=[] 並在 discarded_reason 說明。

# 輸出 JSON
{{
  "issues": [
    {{
      "title": "正式會議議題標題",
      "description": "可選，簡短說明會前要討論的共同問題",
      "category": "{category_values}",
      "participants": ["analyst"],
      "discussion_mode": "sequential",
      "discussion_rounds": 1,
      "target_stakeholders": [],
      "trace": {{"artifact_ids": [], "proposal_ids": ["..."]}},
      "proposed_by": "analyst",
      "issue_level": "blocking | improvement",
      "expected_actions": {{}},
      "participant_reasoning": {{"analyst": "需要釐清或修正需求內容"}}
    }}
  ],
  "discarded_reason": ""
}}"""


def repair_meeting_action_output(*, raw: Any, error: str) -> str:
    return f"""# 任務
上一次 Mediator meeting action 輸出不是合法 JSON object。請只修正格式，不要重新規劃、不要新增輸入沒有支持的內容。

# 錯誤
{error}

# 可用 action
{json.dumps(meeting_actions, ensure_ascii=False, indent=2)}

# 修正規則
- action 必須保留原始輸出中明確表達的 action 意圖；不得因為範例或格式修復自行改成其他 action。
- params 只能保留原始輸出中已明確給出的參數；沒有參數時用空 object。
- reasoning 只能整理原始輸出已表達的理由；沒有理由時用空字串。
- 如果原始輸出沒有任何可辨識 action，請輸出 action="__invalid_unrepairable__"，讓 runtime 明確失敗；不要猜測或補預設 action。

# 輸出 JSON
{{
  "action": "必須是原始輸出中可辨識的 action；不可照抄此說明",
  "params": {{}},
  "reasoning": ""
}}

# 原始輸出
{raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False, indent=2)}
"""


# ========
# Defines meeting action function for this module workflow.
# ========
def meeting_action(
    *,
    state_summary: Dict[str, Any],
    last_observation: Dict[str, Any],
    enable_human_judgment: bool,
) -> str:
    state_text = json.dumps(state_summary, ensure_ascii=False, indent=2)
    obs_text = json.dumps(last_observation, ensure_ascii=False, indent=2)
    judgment_hint = ""
    judgment_action = ""
    if enable_human_judgment:
        judgment_action = (
            "- judge_issue：某議題交由人類裁決。"
            "params: {\"issue_id\": \"M-1\"}（須已 start_issue）\n"
        )
        judgment_hint = "；若 resolution.needs_human=true，先 judge_issue 再 save_issue"

    return f"""# 任務
根據當前狀態與上一動結果，選下一個正式會議動作。

- plan_issues：本輪 issues 為空時；若本輪 meeting_issues 已存在，系統會直接載入既有 agenda，不重新規劃
- add_issues：僅在 state.can_add_issues=true 且確有新議題時
- start_issue：{{"issue_id":"M-1"}}
- resolve_issue：{{"issue_id":"M-1"}}，需已 start_issue
{judgment_action}- save_issue：{{"issue_id":"M-1"}}，需已 resolve_issue；若 resolution.needs_human=true，需先 judge_issue
- finish_round：僅在 formal issues 已 save、human_decision_queue 已處理或遞延，且沒有可追加議題時

# 目前狀態
{state_text}

# 上一動結果
{obs_text}

- issues 為空先 plan_issues；既有本輪 agenda 會被重用
- human_decision_queue 優先：需要人類裁決的項目先交由裁決流程處理
- issue 順序：start_issue → resolve_issue → save_issue{judgment_hint}
- 若上一步 resolve_issue 結果含 needs_human=true，必須先 judge_issue 再 save_issue
- human_decision_queue 未處理完不得 finish_round
- 有 deferred 項或新 open_questions 時，先判斷 add_issues 或 judge_issue；需求品質問題應併入正式議題討論
- 若某題討論後 ready_to_close 多於 needs_more_discussion，且提案者也標示 ready_to_close，應直接 resolve_issue 整理結論。
- resolve_conflict 題目若已有明確 conflict_report recommended_resolution，且討論中沒有重大反對或新風險，resolve_issue 可直接採用既有推薦形成 agreed，但 resolution 必須包含 URL 層級的 keep / revise / remove 修改結果。
- formal meeting 題目經討論後仍缺少可採用推薦、存在重大分歧或有高風險未決時，resolve_issue 才整理決策選項與 recommendation，接著 judge_issue 交由人類裁決，不交給 user agent。
- 所有議題 save 完畢且 can_add_issues=true 時，應主動評估是否有新議題需補充討論（add_issues）；確認無追加需求才 finish_round
- 需要補專案事實時，遵守本輪工具使用資料
- 一次只回一個動作

# 輸出 JSON
{{
  "action": "動作名稱",
  "params": {{}} or {{"issue_id":"M-1"}},
  "reasoning": "一句說明"
}}"""


# ========
# Defines MediatorIssuePlanning class for this module workflow.
# ========
class MediatorIssuePlanning(ElicitationPlan, ConflictPlan):
    # Defines get active issue types function for this module workflow.
    def get_active_issue_types(self):
        if self.enabled_issue_type_ids is None:
            return issue_types, issue_type_ids
        active = tuple(
            t for t in issue_types
            if t["id"] in self.enabled_issue_type_ids
        )
        active_ids = [t["id"] for t in active]
        return active, active_ids

    @staticmethod
    # Defines active category function for this module workflow.
    def active_category(category: str, active_type_ids: List[str]) -> Optional[str]:
        category = str(category or "").strip()
        category = CATEGORY_ALIASES.get(category, category)
        if category in active_type_ids:
            return category
        return None

    @classmethod
    # Defines proposal category function for this module workflow.
    def proposal_category(cls, row: Dict[str, Any], active_type_ids: List[str]) -> Optional[str]:
        category = cls.active_category(str((row or {}).get("category") or ""), active_type_ids)
        if category:
            return category
        focus = str((row or {}).get("issue_focus") or "").strip()
        return cls.active_category(focus, active_type_ids)

    @staticmethod
    # Defines normalize issue participants function for this module workflow.
    def normalize_issue_participants(
        issue: Dict[str, Any],
        *,
        registered_agents: List[str],
        stakeholder_names: List[str],
    ) -> Dict[str, Any]:
        title = str(issue.get("title") or "").strip()
        registered = set(registered_agents)
        current = [
            str(value).strip()
            for value in (issue.get("participants") or [])
            if str(value).strip() in registered
        ]
        participants = list(current)
        proposed_by = str(issue.get("proposed_by") or "").strip()
        if proposed_by and proposed_by != "mediator" and proposed_by in registered_agents:
            if proposed_by not in participants:
                participants.insert(0, proposed_by)
        if title == "需求正式化":
            participants = [agent for agent in ["analyst", "user"] if agent in set(participants)]
            if "analyst" not in participants:
                participants.insert(0, "analyst")
            if "user" not in participants:
                participants.append("user")
        issue["participants"] = list(dict.fromkeys(participants))
        if "user" in issue["participants"]:
            targets = [
                str(value).strip()
                for value in (issue.get("target_stakeholders") or [])
                if str(value).strip()
            ]
            if not targets:
                issue["target_stakeholders"] = list(stakeholder_names)
        reasoning = issue.get("participant_reasoning")
        if isinstance(reasoning, dict):
            issue["participant_reasoning"] = {
                str(agent).strip(): str(reason or "").strip()
                for agent, reason in reasoning.items()
                if str(agent).strip() in set(issue["participants"]) and str(reason or "").strip()
            }
        return issue

    # Applies required action policy for each meeting issue category.
    def apply_issue_required_actions(
        self,
        issue: Dict[str, Any],
        *,
        registered_agents: List[str],
        stakeholder_names: List[str],
    ) -> Dict[str, Any]:
        category = str(issue.get("category") or "").strip()
        required = issue_required_actions().get(category, {})
        if not required:
            return issue

        participants = [
            str(agent).strip()
            for agent in (issue.get("participants") or [])
            if str(agent).strip() in set(registered_agents)
        ]
        expected_actions = issue.get("expected_actions")
        if not isinstance(expected_actions, dict):
            expected_actions = {}

        for agent, actions in required.items():
            if agent not in set(registered_agents):
                continue
            if agent not in participants:
                participants.append(agent)
            current = expected_actions.get(agent, [])
            if isinstance(current, str):
                current = [current]
            if not isinstance(current, list):
                current = []
            for action in actions:
                if action not in current:
                    current.append(action)
            expected_actions[agent] = current

        issue["participants"] = list(dict.fromkeys(participants))
        issue["expected_actions"] = expected_actions

        if "user" in issue["participants"]:
            targets = [
                str(value).strip()
                for value in (issue.get("target_stakeholders") or [])
                if str(value).strip() in set(stakeholder_names)
            ]
            if not targets:
                issue["target_stakeholders"] = list(stakeholder_names)

        reasoning = issue.get("participant_reasoning")
        if not isinstance(reasoning, dict):
            reasoning = {}
        for agent in issue["participants"]:
            if not str(reasoning.get(agent) or "").strip():
                actions = expected_actions.get(agent) or []
                action_text = "、".join(actions) if actions else "參與討論"
                reasoning[agent] = f"本議題類型要求 {agent} 執行 {action_text}。"
        issue["participant_reasoning"] = reasoning
        return issue

    # Defines run meeting planning loop function for this module workflow.
    def run_meeting_planning_loop(self, action: str, **context: Any) -> Any:
        opa = self.run_action_loop(
            name="meeting_planning",
            context={
                "meeting_planning_action": action,
                **context,
            },
            obs_fn=self.obs_meeting_planning,
            decide_action=self.decide_meeting_planning_action,
            execute_action=self.execute_meeting_planning_action,
        )
        trace = opa.get("opa_trace") or []
        result = dict((trace[-1].get("result") if trace else {}) or {})
        if result.get("error"):
            raise RuntimeError(result.get("error"))
        return result.get("output")

    # Defines obs meeting planning function for this module workflow.
    def obs_meeting_planning(self, **kwargs: Any) -> Dict[str, Any]:
        artifact = kwargs.get("artifact") or {}
        issue_pool = kwargs.get("issue_pool")
        return {
            "action": kwargs.get("meeting_planning_action", ""),
            "iteration": kwargs.get("iteration", 0) + 1,
            "max_iterations": kwargs["max_iterations"],
            "requirements_count": len(requirement_discussion_pool(artifact)),
            "conflicts_count": conflict_entries_count(artifact),
            "open_questions_count": len(artifact.get("open_questions", []) or []),
            "backlog_count": len(issue_pool or []) if isinstance(issue_pool, list) else 0,
        }

    # Defines decide meeting planning action function for this module workflow.
    def decide_meeting_planning_action(
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
                "reasoning": "上一輪 meeting planning 任務已完成，結束本次規劃。",
            }
        action = str(observation.get("action") or "").strip()
        return {
            "action": action,
            "params": {},
            "reasoning": f"執行 meeting planning 任務：{action}。",
        }

    # Defines execute meeting planning action function for this module workflow.
    def execute_meeting_planning_action(
        self,
        *,
        decision: Dict[str, Any],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        action = str(decision.get("action") or "").strip()
        try:
            if action == "plan_issues":
                output = self.plan_issues_internal(
                    kwargs.get("artifact") or {},
                    registry=kwargs.get("registry"),
                    max_items=kwargs.get("max_items"),
                    skip_artifact_ids=kwargs.get("skip_artifact_ids"),
                    issue_pool=kwargs.get("issue_pool"),
                )
            elif action == "plan_elicitation":
                output = self.run_elicitation_planning(
                    artifact=kwargs.get("artifact") or {},
                    turn=kwargs.get("turn", 1),
                    max_turns=kwargs.get("max_turns", 1),
                    default_participants=kwargs.get("default_participants") or [],
                    previous_turn_summary=kwargs.get("previous_turn_summary"),
                    recent_ask_history=kwargs.get("recent_ask_history"),
                )
            elif action == "plan_conflict_review":
                output = self.plan_conflict_review_internal(
                    kwargs.get("conflict") or {},
                    artifact=kwargs.get("artifact"),
                    registry=kwargs.get("registry"),
                )
            else:
                raise ValueError(f"未知 meeting planning action: {action}")
        except Exception as e:
            return {
                "action": action,
                "status": "failed",
                "error": str(e),
                "summary": f"meeting planning failed: {action}",
            }
        return {
            "action": action,
            "status": "success",
            "output": output,
            "summary": f"完成 meeting planning: {action}",
        }

    # Defines plan issues function for this module workflow.
    def plan_issues(
        self,
        artifact: Dict[str, Any],
        registry=None,
        max_items: Optional[int] = None,
        skip_artifact_ids: Optional[set] = None,
        issue_pool: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict]:
        return self.run_meeting_planning_loop(
            "plan_issues",
            artifact=artifact,
            registry=registry,
            max_items=max_items,
            skip_artifact_ids=skip_artifact_ids,
            issue_pool=issue_pool,
        ) or []

    # Defines plan elicitation function for this module workflow.
    def plan_elicitation(
        self,
        *,
        artifact: Dict[str, Any],
        turn: int,
        max_turns: int,
        default_participants: List[str],
        previous_turn_summary: Optional[Dict[str, Any]] = None,
        recent_ask_history: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        output = self.run_meeting_planning_loop(
            "plan_elicitation",
            artifact=artifact,
            turn=turn,
            max_turns=max_turns,
            default_participants=default_participants,
            previous_turn_summary=previous_turn_summary,
            recent_ask_history=recent_ask_history,
        )
        if not isinstance(output, dict):
            raise RuntimeError("plan_elicitation 在 agent loop 後未產生有效計畫")
        return output

    # Defines plan conflict review function for this module workflow.
    def plan_conflict_review(
        self,
        conflict: Dict[str, Any],
        artifact: Optional[Dict[str, Any]] = None,
        registry=None,
    ) -> Dict[str, Any]:
        output = self.run_meeting_planning_loop(
            "plan_conflict_review",
            conflict=conflict,
            artifact=artifact or {},
            registry=registry,
        )
        if not isinstance(output, dict):
            raise RuntimeError("plan_conflict_review 在 agent loop 後未產生有效計畫")
        return output

    @staticmethod
    # Defines artifact source function for this module workflow.
    def artifact_source(artifact: Dict[str, Any], meeting_artifact: Dict[str, Any]) -> Dict[str, Any]:
        return artifact if isinstance(artifact, dict) and artifact else meeting_artifact

    @staticmethod
    # Defines related items function for this module workflow.
    def related_items(rows: Any, source_ids: List[str], *, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        if not isinstance(rows, list):
            return []
        ids = {str(x).strip() for x in source_ids if str(x).strip()}
        if not ids:
            return [row for row in rows if isinstance(row, dict)]
        out: List[Dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            row_id = str(row.get("id") or "").strip()
            blob = json.dumps(row, ensure_ascii=False)
            if row_id not in ids and not any(source_id in blob for source_id in ids):
                continue
            out.append(row)
            if limit is not None and len(out) >= limit:
                break
        return out

    @staticmethod
    # Defines related feedback function for this module workflow.
    def related_feedback(feedback: Any, source_ids: List[str]) -> Dict[str, Any]:
        if not isinstance(feedback, dict):
            return {}
        ids = {str(x).strip() for x in source_ids if str(x).strip()}
        if not ids:
            return {}
        related: Dict[str, Any] = {}
        for section in ("findings", "constraints", "risks", "recommendations"):
            rows = []
            for idx, row in enumerate(feedback.get(section) or [], 1):
                if not isinstance(row, dict):
                    continue
                row_id = str(row.get("id") or f"{section}_{idx}").strip()
                related_ids = {
                    str(value).strip()
                    for value in (row.get("related_requirement_ids") or [])
                    if str(value).strip()
                }
                source = str(row.get("source") or "").strip()
                if row_id in ids or source in ids or related_ids.intersection(ids):
                    item = dict(row)
                    item.setdefault("id", row_id)
                    rows.append(item)
            if rows:
                related[section] = rows
        return related

    @staticmethod
    # Defines context summary function for this module workflow.
    def context_summary(value: Any) -> Any:
        if isinstance(value, list):
            return [
                MediatorIssuePlanning.context_summary(item)
                for item in value
                if isinstance(item, (dict, list, str, int, float, bool))
            ]
        if not isinstance(value, dict):
            return value
        keep = {}
        for key in (
            "id",
            "issue_id",
            "title",
            "type",
            "category",
            "status",
            "label",
            "name",
            "text",
            "description",
            "summary",
            "decision",
            "reason",
            "source",
            "source_id",
            "source_ids",
            "requirement",
            "requirements",
            "requirement_ids",
            "related_requirement_ids",
        ):
            if key not in value:
                continue
            item = value.get(key)
            if item in (None, "", [], {}):
                continue
            if isinstance(item, str):
                keep[key] = item
            elif isinstance(item, list):
                keep[key] = [
                    MediatorIssuePlanning.context_summary(row)
                    for row in item
                ]
            elif isinstance(item, dict):
                keep[key] = MediatorIssuePlanning.context_summary(item)
            else:
                keep[key] = item
        return keep

    # Defines related artifact context function for this module workflow.
    def related_artifact_context(
        self,
        issue: Dict[str, Any],
        artifact: Dict[str, Any],
    ) -> Dict[str, Any]:
        full_artifact = self.load_artifact_context_from_files()
        source = self.artifact_source(full_artifact, artifact)
        meeting_source = artifact if isinstance(artifact, dict) else {}
        related_rows = issue.get("sources") if isinstance(issue, dict) else []
        context: Dict[str, Any] = {"related_context": []}

        # Defines add section function for this module workflow.
        def add_section(name: str, value: Any) -> None:
            if value in (None, [], {}):
                return
            rows = value if isinstance(value, list) else [value]
            summarized = self.context_summary(rows)
            if summarized:
                context["related_context"].append({
                    "artifact": name,
                    "items": summarized,
                })

        for rel in related_rows or []:
            if not isinstance(rel, dict):
                continue
            artifact_name = str(rel.get("artifact") or "").strip()
            source_ids = [
                str(x).strip()
                for x in (rel.get("ids") or [])
                if str(x).strip()
            ]
            if not artifact_name:
                continue

            if artifact_name == "URL":
                rows = requirement_discussion_pool(source) or requirement_discussion_pool(meeting_source)
                add_section("URL", self.related_items(rows, source_ids))
                continue

            if artifact_name == "REQ":
                rows = source.get("REQ") if isinstance(source.get("REQ"), list) else meeting_source.get("REQ", [])
                add_section("REQ", self.related_items(rows, source_ids))
                continue

            if artifact_name == "conflict_report":
                rows = source.get("conflict_report") if isinstance(source.get("conflict_report"), list) else meeting_source.get("conflict_report", [])
                add_section("conflict_report", self.related_items(rows, source_ids))
                continue

            if artifact_name in {"system_models", "models", "model"}:
                rows = source.get("system_models") if isinstance(source.get("system_models"), list) else meeting_source.get("system_models", [])
                add_section("system_models", self.related_items(rows, source_ids))
                continue

            if artifact_name in {"open_questions", "open_question"}:
                rows = source.get("open_questions") if isinstance(source.get("open_questions"), list) else meeting_source.get("open_questions", [])
                add_section("open_questions", self.related_items(rows, source_ids))
                continue

            if artifact_name in {"conversation", "discussions"}:
                discussions = source.get("discussions") if isinstance(source.get("discussions"), list) else []
                decisions = source.get("decisions") if isinstance(source.get("decisions"), list) else []
                add_section("discussions", self.related_items(discussions, source_ids))
                add_section("decisions", self.related_items(decisions, source_ids))
                continue

            if artifact_name == "scope":
                add_section("scope", source.get("scope") or meeting_source.get("scope"))
                continue

            if artifact_name == "feedback":
                feedback = source.get("feedback") or meeting_source.get("feedback")
                add_section("feedback", self.related_feedback(feedback, source_ids))
                continue

            value = source.get(artifact_name) or meeting_source.get(artifact_name)
            if isinstance(value, list):
                value = self.related_items(value, source_ids)
            add_section(artifact_name, value)

        return context if context.get("related_context") else {}

    # Checks whether two proposal rows refer to the same proposal.
    @staticmethod
    def same_issue_proposal(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
        if not isinstance(left, dict) or not isinstance(right, dict):
            return False
        left_id = str(left.get("issue_id") or "").strip()
        right_id = str(right.get("issue_id") or "").strip()
        if left_id and right_id:
            return left_id == right_id
        return str(left.get("title") or "").strip() == str(right.get("title") or "").strip()

    # Defines triage issue proposals function for this module workflow.
    def triage_issue_proposals(
        self,
        issue_pool: List[Dict[str, Any]],
        *,
        artifact: Optional[Dict[str, Any]] = None,
        active_type_ids: List[str],
        registered: List[str],
        max_items: int,
        skip_artifact_ids: Optional[set] = None,
        is_last_round: bool = False,
        round_num: Optional[int] = None,
    ) -> Dict[str, Any]:
        skip = skip_artifact_ids or set()
        proposals = []
        seen = set()
        for p in issue_pool:
            if not isinstance(p, dict):
                continue
            p = dict(p)
            title = (p.get("title") or "").strip()
            related = []
            for x in p.get("sources") or []:
                if isinstance(x, dict):
                    artifact_name = str(x.get("artifact") or "").strip()
                    source_ids = tuple(str(s).strip() for s in (x.get("ids") or []) if str(s).strip())
                    if artifact_name:
                        related.append((artifact_name, source_ids))
            src = tuple(sorted(related))
            key = ((p.get("issue_id") or "").strip(), title, src)
            if not title or key in seen:
                continue
            seen.add(key)
            proposals.append(p)
        if not proposals:
            return {
                "issues": [],
                "backlog": [],
                "discarded": [],
            }

        # Defines proposal priority function for this module workflow.
        def proposal_priority(row: Dict[str, Any]) -> int:
            issue_level = str((row or {}).get("issue_level") or "").strip()
            focus = str((row or {}).get("issue_focus") or "").strip()
            category = str((row or {}).get("category") or "").strip()
            title_reason = " ".join(
                str((row or {}).get(key) or "")
                for key in ("title", "expect_outcome", "reason")
            )
            level_rank = 0 if issue_level == "blocking" else 10
            human_bias = -1 if str((row or {}).get("proposed_by") or "").strip().lower() == "human" else 0
            if (
                focus == "open_question_answer"
                or category == "clarify_requirement"
                and "OQ-" in title_reason
            ):
                return level_rank + 0 + human_bias
            if (
                focus == "requirement_completeness"
                or "Requirement Completeness" in title_reason
                or "需求完整" in title_reason
                or "驗收" in title_reason
                or "validation" in title_reason
                or "metric" in title_reason
            ):
                return level_rank + 1 + human_bias
            if focus == "boundary_responsibility" or category == "define_boundary":
                return level_rank + 2 + human_bias
            if focus == "tradeoff" or category == "tradeoff":
                return level_rank + 3 + human_bias
            if focus == "model_alignment" or category == "align_model":
                return level_rank + 4 + human_bias
            if focus == "new_requirement":
                return level_rank + 5 + human_bias
            return level_rank + 5 + human_bias

        # Defines proposal type key function for this module workflow.
        def proposal_type_key(row: Dict[str, Any]) -> str:
            focus = str((row or {}).get("issue_focus") or "").strip()
            category = self.proposal_category(row, active_type_ids) or "unspecified"
            return f"{category}:{focus or category}"

        # Defines diversify selected proposals function for this module workflow.
        def diversify_selected_proposals(rows: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
            ordered = sorted(
                [row for row in rows if isinstance(row, dict)],
                key=lambda row: (proposal_priority(row), str(row.get("issue_id") or "")),
            )
            if limit <= 0 or len(ordered) <= limit:
                return ordered[:limit]
            grouped: Dict[str, List[Dict[str, Any]]] = {}
            for row in ordered:
                grouped.setdefault(proposal_type_key(row), []).append(row)
            representatives = sorted(
                [group[0] for group in grouped.values() if group],
                key=lambda row: (proposal_priority(row), str(row.get("issue_id") or "")),
            )
            selected = representatives[:limit]
            if len(selected) >= limit:
                return selected
            for row in ordered:
                if any(self.same_issue_proposal(row, selected_row) for selected_row in selected):
                    continue
                selected.append(row)
                if len(selected) >= limit:
                    break
            return selected[:limit]

        triage = {"issues": [], "backlog": [], "discarded": []}
        if proposals:
            proposals = sorted(
                proposals,
                key=lambda row: (proposal_priority(row), str(row.get("issue_id") or "")),
            )
            prompt = select_issues(
                proposals=proposals,
                max_items=max_items,
                skip_artifact_ids=sorted(str(s) for s in skip),
                is_last_round=is_last_round,
                round_num=int(round_num or 1),
            )
            try:
                triage = self.chat_json(self.build_direct_messages(prompt))
            except Exception as e:
                raise RuntimeError(f"Issue triage LLM failed: {e}") from e
            if not isinstance(triage, dict):
                raise RuntimeError("Issue triage must return a JSON object")

        human_proposals = [
            row for row in proposals
            if isinstance(row, dict)
            and str(row.get("proposed_by") or "").strip().lower() == "human"
        ]

        def is_human_proposal(row: Dict[str, Any]) -> bool:
            return str((row or {}).get("proposed_by") or "").strip().lower() == "human"

        def issue_rows() -> List[Dict[str, Any]]:
            return [row for row in (triage.get("issues") or []) if isinstance(row, dict)]

        def displace_lowest_priority_non_human() -> None:
            issues = issue_rows()
            if len(issues) < max_items:
                return
            candidates = [
                row for row in issues
                if not is_human_proposal(row)
            ]
            if not candidates:
                return
            displaced = max(
                candidates,
                key=lambda row: (proposal_priority(row), str(row.get("issue_id") or "")),
            )
            triage["issues"] = [
                row for row in issues
                if not self.same_issue_proposal(row, displaced)
            ]
            triage.setdefault("backlog", []).append(displaced)

        for human in human_proposals:
            already_in_issues = any(
                self.same_issue_proposal(human, row)
                for row in issue_rows()
                if isinstance(row, dict)
            )
            if not already_in_issues:
                displace_lowest_priority_non_human()
                triage.setdefault("issues", []).append(human)
            triage["discarded"] = [
                row for row in (triage.get("discarded") or [])
                if not (isinstance(row, dict) and self.same_issue_proposal(human, row))
            ]
            triage["backlog"] = [
                row for row in (triage.get("backlog") or [])
                if not (isinstance(row, dict) and self.same_issue_proposal(human, row))
            ]

        selected_proposals = sorted(
            [p for p in (triage.get("issues") or []) if isinstance(p, dict)],
            key=lambda row: (proposal_priority(row), str(row.get("issue_id") or "")),
        )
        selected_proposals = diversify_selected_proposals(selected_proposals, max_items)
        for human in human_proposals:
            if any(self.same_issue_proposal(human, row) for row in selected_proposals):
                continue
            replaceable = [
                row for row in selected_proposals
                if not is_human_proposal(row)
            ]
            if replaceable:
                displaced = max(
                    replaceable,
                    key=lambda row: (proposal_priority(row), str(row.get("issue_id") or "")),
                )
                selected_proposals = [
                    row for row in selected_proposals
                    if not self.same_issue_proposal(row, displaced)
                ]
                triage.setdefault("backlog", []).append(displaced)
            selected_proposals.append(human)
            selected_proposals = sorted(
                selected_proposals,
                key=lambda row: (proposal_priority(row), str(row.get("issue_id") or "")),
            )
            while len(selected_proposals) > max_items:
                overflow_candidates = [
                    row for row in selected_proposals
                    if not is_human_proposal(row)
                ]
                if not overflow_candidates:
                    break
                displaced = max(
                    overflow_candidates,
                    key=lambda row: (proposal_priority(row), str(row.get("issue_id") or "")),
                )
                selected_proposals = [
                    row for row in selected_proposals
                    if not self.same_issue_proposal(row, displaced)
                ]
                triage.setdefault("backlog", []).append(displaced)
        if proposals and not selected_proposals:
            repair_prompt = repair_issue_selection(
                proposals=proposals,
                backlog=[row for row in (triage.get("backlog") or []) if isinstance(row, dict)],
                discarded=[row for row in (triage.get("discarded") or []) if isinstance(row, dict)],
                errors=["Issue triage produced no selected issues."],
                max_items=max_items,
                skip_artifact_ids=sorted(str(s) for s in skip),
                is_last_round=is_last_round,
                round_num=int(round_num or 1),
            )
            try:
                repaired_triage = self.chat_json(self.build_direct_messages(repair_prompt))
            except Exception as e:
                raise RuntimeError(f"Issue triage repair LLM failed: {e}") from e
            if not isinstance(repaired_triage, dict):
                raise RuntimeError("Issue triage repair must return a JSON object")
            triage = {
                "issues": [row for row in (repaired_triage.get("issues") or []) if isinstance(row, dict)],
                "backlog": [row for row in (repaired_triage.get("backlog") or []) if isinstance(row, dict)],
                "discarded": [row for row in (repaired_triage.get("discarded") or []) if isinstance(row, dict)],
            }
            selected_proposals = sorted(
                [p for p in (triage.get("issues") or []) if isinstance(p, dict)],
                key=lambda row: (proposal_priority(row), str(row.get("issue_id") or "")),
            )
            selected_proposals = diversify_selected_proposals(selected_proposals, max_items)
        general_type_ids = list(active_type_ids or issue_type_ids)
        category_definitions = "\n".join(
            f"- {t['id']}：{t.get('description') or t.get('label') or t['id']}"
            for t in issue_types
            if t["id"] in set(general_type_ids)
        )
        stakeholder_names = []
        for row in ((artifact or {}).get("stakeholders", []) or []):
            if not isinstance(row, dict):
                continue
            name = str(row.get("name") or "").strip()
            if name:
                stakeholder_names.append(name)
        meeting_issues = []
        for proposal in selected_proposals:
            related_context = self.related_artifact_context(
                proposal,
                artifact or {},
            )
            plan_prompt = meeting_plan(
                issue=proposal,
                related_context=related_context,
                active_types=general_type_ids,
                category_definitions=category_definitions,
                registered=registered,
                stakeholder_names=stakeholder_names,
            )
            try:
                planned = self.chat_json(self.build_direct_messages(plan_prompt))
            except Exception as e:
                raise RuntimeError(f"Issue meeting planning LLM failed: {e}") from e
            if not isinstance(planned, dict):
                raise RuntimeError("Issue meeting planning must return a JSON object")
            planned_rows = []
            row_errors = []
            for row in planned.get("issues") or []:
                if isinstance(row, dict):
                    if not str(row.get("proposed_by") or "").strip():
                        row_errors.append("Issue meeting planning output missing proposed_by")
                        continue
                    if not isinstance(row.get("trace"), dict):
                        row_errors.append("Issue meeting planning output missing trace")
                        continue
                    if proposal.get("expected_actions") and not row.get("expected_actions"):
                        row["expected_actions"] = proposal.get("expected_actions")
                    if proposal.get("suggested_participants") and not row.get("suggested_participants"):
                        row["suggested_participants"] = proposal.get("suggested_participants")
                    if proposal.get("participant_reasoning") and not row.get("participant_reasoning"):
                        row["participant_reasoning"] = proposal.get("participant_reasoning")
                    for key in ("participants", "discussion_mode", "discussion_rounds", "issue_level"):
                        if proposal.get(key) and not row.get(key):
                            row[key] = proposal.get(key)
                    planned_rows.append(row)
            if not planned_rows:
                repair_prompt = repair_meeting_plan(
                    proposal=proposal,
                    related_context=related_context,
                    invalid_output=planned,
                    errors=row_errors or ["Issue meeting planning produced no valid issue rows."],
                    active_types=general_type_ids,
                    category_definitions=category_definitions,
                    registered=registered,
                    stakeholder_names=stakeholder_names,
                )
                try:
                    repaired = self.chat_json(self.build_direct_messages(repair_prompt))
                except Exception as e:
                    raise RuntimeError(f"Issue meeting planning repair LLM failed: {e}") from e
                if not isinstance(repaired, dict):
                    raise RuntimeError("Issue meeting planning repair must return a JSON object")
                for row in repaired.get("issues") or []:
                    if isinstance(row, dict):
                        planned_rows.append(row)
            meeting_issues.extend(planned_rows)

        items = []
        for p in meeting_issues:
            if not isinstance(p, dict):
                continue
            p = self.apply_issue_required_actions(
                dict(p),
                registered_agents=registered,
                stakeholder_names=stakeholder_names,
            )
            p = self.normalize_issue_participants(
                p,
                registered_agents=registered,
                stakeholder_names=stakeholder_names,
            )
            if p.get("discussion_rounds") in (None, ""):
                p["discussion_rounds"] = 1
            else:
                p["discussion_rounds"] = normalized_discussion_rounds(p.get("discussion_rounds"))
            normalized = meeting_issue(
                p,
                allowed_categories=general_type_ids,
                registered_agents=registered,
                allowed_stakeholders=stakeholder_names,
                index=len(items) + 1,
            )
            if normalized:
                normalized = self.normalize_issue_participants(
                    normalized,
                    registered_agents=registered,
                    stakeholder_names=stakeholder_names,
                )
                items.append(normalized)
        if selected_proposals and not items:
            raise RuntimeError("Issue meeting planning repair produced no valid meeting issues")

        # Defines backlog rows function for this module workflow.
        def backlog_rows() -> List[Dict[str, Any]]:
            rows = []
            for row in triage.get("backlog") or []:
                if not isinstance(row, dict):
                    continue
                rows.append(dict(row))
            return rows

        # Defines discarded rows function for this module workflow.
        def discarded_rows() -> List[Dict[str, Any]]:
            rows = []
            for row in triage.get("discarded") or []:
                if not isinstance(row, dict):
                    continue
                rows.append(dict(row))
            return rows

        return {
            "issues": items,
            "backlog": backlog_rows(),
            "discarded": discarded_rows(),
        }

    # Defines plan issues internal function for this module workflow.
    def plan_issues_internal(
        self,
        artifact: Dict[str, Any],
        registry=None,
        max_items: Optional[int] = None,
        skip_artifact_ids: Optional[set] = None,
        issue_pool: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict]:
        limit = max_items or 5
        exclude = {"mediator", "documentor"}
        if registry:
            registered = [n for n in registry.get_names() if n not in exclude]
        else:
            registered = ["user", "analyst", "expert", "modeler"]

        _, active_ids = self.get_active_issue_types()
        skip = skip_artifact_ids or set()
        raw_items = []

        if issue_pool is None:
            raise ValueError("plan_issues requires issue_pool")

        meta = artifact.get("meta") if isinstance(artifact.get("meta"), dict) else {}
        try:
            current_round = int((issue_pool[0] or {}).get("round") or meta.get("last_round") or 1) if issue_pool else int(meta.get("last_round") or 1)
        except (AttributeError, TypeError, ValueError):
            current_round = 1
        config = getattr(self, "config", {}) or {}
        try:
            end_round = int(meta.get("meeting_end_round") or config.get("rounds", 1) or 1)
        except (TypeError, ValueError):
            end_round = 1
        is_last_round = current_round >= end_round
        triage_pool = list(issue_pool or [])
        triage = self.triage_issue_proposals(
            triage_pool,
            artifact=artifact,
            active_type_ids=active_ids,
            registered=registered,
            max_items=limit,
            skip_artifact_ids=skip,
            is_last_round=is_last_round,
            round_num=current_round,
        )
        raw_items = triage.get("issues", [])
        artifact["issue_backlog"] = triage.get("backlog", [])
        artifact["issue_discarded"] = triage.get("discarded", [])
        self.logger.info(
            "Issue Triage：%s 筆 → 入選 %s backlog %s discarded %s（上限 %s）",
            len(triage_pool),
            len(raw_items),
            len(artifact["issue_backlog"]),
            len(artifact["issue_discarded"]),
            limit,
        )

        if not raw_items:
            self.logger.info("issue_pool 無可用正式會議議題，略過本輪 meeting")
            return []

        if not raw_items:
            self.logger.info("本輪無新增決策議題")
            return []

        ordered_items = [
            item for item in raw_items
            if isinstance(item, dict)
        ][:limit]
        ordered_items = self.merge_open_question_items(
            ordered_items,
            artifact,
            registered,
        )

        issue_items = []
        for idx, item in enumerate(ordered_items, 1):
            category = self.proposal_category(item, active_ids)
            allowed_categories = active_ids or issue_type_ids
            if not category:
                continue
            normalized = meeting_issue(
                {
                    **item,
                    "id": item.get("id") or f"M-{idx}",
                    "category": category,
                },
                allowed_categories=allowed_categories,
                registered_agents=registered,
                index=idx,
            )
            if normalized:
                issue_items.append(normalized)

        return issue_items

    # Defines merge open question items function for this module workflow.
    def merge_open_question_items(
        self,
        items: List[Dict[str, Any]],
        artifact: Dict[str, Any],
        registered: List[str],
    ) -> List[Dict[str, Any]]:
        open_question_items = [
            it for it in items
            if (it.get("category") or "").strip() == "clarify_requirement"
            and any(
                str(src).strip().startswith("OQ-")
                for src in ((it.get("trace") or {}).get("artifact_ids", []) or [])
            )
        ]
        if not open_question_items:
            return items

        related_agents = set()
        for it in open_question_items:
            for a in (it.get("participants", []) or []):
                if a in registered:
                    related_agents.add(a)

        issue_questions: List[str] = []
        question_source_ids: List[str] = []
        expected_actions: Dict[str, List[str]] = {}
        requested_oq_ids = {
            str(src).strip()
            for it in open_question_items
            for src in ((it.get("trace") or {}).get("artifact_ids", []) or [])
            if str(src).strip().startswith("OQ-")
        }
        for q in artifact.get("open_questions", []):
            if q.get("status") == "answered":
                continue
            qid = str(q.get("id") or "").strip()
            if qid not in requested_oq_ids and not self.should_add_open_question_issue(q):
                continue
            to_agent = (q.get("to") or "").strip()
            if to_agent in registered:
                related_agents.add(to_agent)
                expected_actions.setdefault(to_agent, [])
                if "answer_question" not in expected_actions[to_agent]:
                    expected_actions[to_agent].append("answer_question")
            question = str(q.get("question") or "").strip()
            if question:
                issue_questions.append(f"- {question}")
            if qid:
                question_source_ids.append(qid)

        participants = [a for a in registered if a in related_agents]
        if not participants:
            participants = list(registered)
        participant_reasoning = {
            agent: "此參與者需要回覆或協助釐清待回答的 open question"
            for agent in participants
        }

        source_ids: List[str] = []
        proposal_ids: List[str] = []
        descriptions: List[str] = []
        titles: List[str] = []
        seen_ids = set()
        seen_proposal_ids = set()
        for it in open_question_items:
            title = str(it.get("title") or "").strip()
            description = str(it.get("description") or "").strip()
            if title:
                titles.append(title)
            if description:
                descriptions.append(f"- {title or 'open question'}: {description}")
            trace = it.get("trace") if isinstance(it.get("trace"), dict) else {}
            for sid in (trace.get("artifact_ids", []) or []):
                if not sid or sid in seen_ids:
                    continue
                seen_ids.add(sid)
                source_ids.append(sid)
            for proposal_id in (trace.get("proposal_ids", []) or []):
                proposal_id = str(proposal_id or "").strip()
                if proposal_id and proposal_id not in seen_proposal_ids:
                    seen_proposal_ids.add(proposal_id)
                    proposal_ids.append(proposal_id)
            item_expected = it.get("expected_actions") if isinstance(it.get("expected_actions"), dict) else {}
            for agent, actions in item_expected.items():
                if agent not in registered:
                    continue
                expected_actions.setdefault(agent, [])
                for action in actions if isinstance(actions, list) else [actions]:
                    action_name = str(action or "").strip()
                    if action_name and action_name not in expected_actions[agent]:
                        expected_actions[agent].append(action_name)
        for qid in question_source_ids:
            if qid not in seen_ids:
                seen_ids.add(qid)
                source_ids.append(qid)

        merged_title = "釐清待回答需求問題"
        body_parts = []
        if descriptions:
            body_parts.append("來源議題：\n" + "\n".join(descriptions))
        if issue_questions:
            body_parts.append("待回覆開放問題：\n" + "\n".join(issue_questions))
        if not body_parts:
            body_parts.append("本議題缺少具體開放問題；請先確認來源 proposal 是否可補齊。")

        merged_item = {
            "title": merged_title,
            "description": "\n\n".join(body_parts),
            "category": "clarify_requirement",
            "participants": participants,
            "participant_reasoning": participant_reasoning,
            "discussion_mode": "simultaneous",
            "trace": {"artifact_ids": source_ids, "proposal_ids": proposal_ids},
            "expected_actions": expected_actions,
        }

        merged: List[Dict[str, Any]] = []
        inserted = False
        for it in items:
            if it in open_question_items:
                if not inserted:
                    merged.append(merged_item)
                    inserted = True
                continue
            merged.append(it)
        return merged

    @staticmethod
    # Defines should add open question issue function for this module workflow.
    def should_add_open_question_issue(q: Dict[str, Any]) -> bool:
        if not isinstance(q, dict):
            return False
        if q.get("status") == "answered":
            return False
        if q.get("needs_issue") is True:
            return True
        if q.get("status") == "add_to_issue":
            return True
        if int(q.get("deferred_count") or 0) >= 2:
            return True
        return False

    # Defines plan meeting action internal function for this module workflow.
    def plan_meeting_action_internal(
        self,
        state_summary: Dict[str, Any],
        last_observation: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        last_observation = last_observation or {}
        user_prompt = meeting_action(
            state_summary=state_summary,
            last_observation=last_observation,
            enable_human_judgment=self.enable_human_judgment,
        )

        messages = self.build_direct_messages(user_prompt)
        try:
            if "artifact_query" in self.tools:
                raw = self.chat_with_tools(messages)
                try:
                    response = self.parse_issue_response_json(raw)
                except Exception as parse_error:
                    repair_prompt = repair_meeting_action_output(
                        raw=raw,
                        error=f"上一輪輸出不是合法 JSON object: {parse_error}",
                    )
                    response = self.chat_json(self.build_direct_messages(repair_prompt))
            else:
                response = self.chat_json(messages)
        except Exception as e:
            raise RuntimeError(f"meeting action LLM 輸出格式不合格: {e}") from e

        return meeting_action_decision(response)
