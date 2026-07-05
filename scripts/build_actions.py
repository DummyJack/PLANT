#!/usr/bin/env python3
"""Sync manual/agent/*.txt prompt files from agents/profile runtime modules."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agents.profile.analyst.actions.conflict.group_detection import group_detection
from agents.profile.analyst.actions.conflict.pair_detection import pair_detection
from agents.profile.analyst.actions.conflict.review import review_reason, review_signoff
from agents.profile.analyst.actions.draft.create import create_draft
from agents.profile.analyst.actions.draft.update import update_draft
from agents.profile.analyst.actions.report.create import create_report
from agents.profile.analyst.actions.report.resolution import report_resolution
from agents.profile.analyst.actions.reqt.analyze import analyze_requirement
from agents.profile.analyst.actions.reqt.extract import extract_requirement
from agents.profile.analyst.actions.reqt.refine import refine_requirement
from agents.profile.analyst.actions.reqt.update import update_requirement
from agents.profile.analyst.actions.response import answer as analyst_answer
from agents.profile.analyst.actions.response import conflict as analyst_conflict
from agents.profile.analyst.actions.response import elicitation as analyst_elicitation_resp
from agents.profile.analyst.actions.response import issue as analyst_issue
from agents.profile.analyst.actions.response import resolution as analyst_resolution
from agents.profile.analyst.actions.scenario import name_scenario
from agents.profile.analyst.actions.scope.generate import generate_scope
from agents.profile.analyst.actions.scope.refine import refine_scope
from agents.profile.analyst.conflicts import conflict_type_guidance_from_skill
from agents.profile.analyst.plan import (
    ANALYST_AVAILABLE_ACTIONS,
    ANALYST_NEW_REQUIREMENT_ACTION,
)
from agents.profile.analyst.actions.conflict.detection_rules import conflict_detection_base_task
from agents.profile.analyst.rules import url_extraction_rules
from agents.profile.analyst.skill import (
    conflict_skill_guidance,
    conflict_skill_subset,
    requirements_skill_guidance,
)
from agents.profile.base import action_plan_prompt, proposal_prompt
from agents.profile.documentor.agent import documentor_system
from agents.profile.documentor.actions.srs import generate_srs
from agents.profile.expert.actions.feedback import update_feedback
from agents.profile.expert.actions.read_reference import read_docs
from agents.profile.expert.actions.research import research_issue
from agents.profile.expert.actions.response import answer as expert_answer
from agents.profile.expert.actions.response import elicitation as expert_elicitation_resp
from agents.profile.expert.actions.response import issue as expert_issue
from agents.profile.expert.agent import expert_system
from agents.profile.expert.plan import research_prompt
from agents.profile.expert.skill import domain_skill_guidance, domain_skill_subset
from agents.profile.documentor.actions.dr import design_rationale
from agents.profile.mediator.actions.judge import judge_options
from agents.profile.mediator.actions.resolve import close_issue
from agents.profile.mediator.agent import mediator_system
from agents.profile.mediator.plan.conflict import build_conflict_review
from agents.profile.mediator.plan.elicitation import build_elicitation_plan
from agents.profile.mediator.actions.judge import closure_vote
from agents.profile.mediator.plan.formal import meeting_action, meeting_plan, select_issues
from agents.profile.mediator.validation import issue_type_ids, issue_types
from agents.profile.modeler.actions.create import create_model
from agents.profile.modeler.actions.response import answer as modeler_answer
from agents.profile.modeler.actions.response import elicitation as modeler_elicitation_resp
from agents.profile.modeler.actions.response import issue as modeler_issue
from agents.profile.modeler.actions.update import update_model
from agents.profile.modeler.actions.use_case import use_case_text
from agents.profile.modeler.agent import modeler_system
from agents.profile.modeler.plan import target_prompt
from agents.profile.modeler.rules import model_description_contract, model_layout_hint
from agents.profile.modeler.skill import uml_skill_guidance, uml_skill_subset
from agents.profile.user.actions.response import issue_response as user_issue_response
from agents.profile.user.actions.simulate import suggest_stakeholders, write_stakeholder_text
from agents.profile.user.agent import user_system
from agents.profile.user.rules import (
    category_hint as user_category_hint,
    open_question_rule,
    response_actions,
    response_flow,
    response_json,
    stance_json,
    stance_rule,
    stakeholder_contract,
)
from agents.profile.analyst.agent import analyst_system
from agents.skills.base import get_skill

MANUAL_AGENT = ROOT / "manual" / "agent"
SKILLS_SRC = ROOT / "agents" / "skills"

SAMPLE_ISSUE = {
    "id": "I-R1-001",
    "title": "訂單狀態規則是否一致",
    "category": "clarify_requirement",
    "description": "消費者、餐廳與外送員對訂單取消條件的理解是否一致？",
    "meeting_id": "R1-M1",
}

SAMPLE_OQ_ISSUE = {
    "id": "OQ",
    "title": "回答 analyst 的問題",
    "description": "取消規則應以出餐前還是出餐後為準？",
    "category": "clarify_requirement",
}

SAMPLE_ELICIT_ISSUE = {
    "id": "ELICIT-1",
    "title": "需求擷取訪談",
    "description": "補足訂單取消與狀態規則的理解缺口。",
    "category": "clarify_requirement",
    "target_stakeholders": ["消費者"],
}

SAMPLE_RESOLVE_ISSUE = {
    "id": "I-R1-002",
    "title": "解決訂單取消衝突",
    "category": "resolve_conflict",
    "description": "針對 CR-1 的解決選項做取捨。",
    "meeting_id": "R1-M1",
}

SAMPLE_PAIR_ISSUE = {
    "id": "I-R1-003",
    "title": "衝突再審查",
    "category": "resolve_conflict",
    "description": "逐筆再審查 Conflict/Neutral 項目。",
    "conflict_review_contract": {
        "type": "pair_reviews",
        "known_pair_ids": ["PAIR-1"],
    },
}

SAMPLE_CONTEXT = {
    "related_context": {
        "requirements": [
            {
                "id": "REQ-1",
                "title": "訂餐",
                "description": "系統應支援線上訂餐",
            }
        ]
    }
}

SAMPLE_EXISTING_URL = [
    {
        "id": "URL-1",
        "text": "消費者能完成線上訂餐",
        "stakeholder": "消費者",
        "source": "initial",
    }
]

SAMPLE_PLAN_CONTEXT = {
    "round_num": 1,
    "latest_draft": "",
    "proposal_context": {},
}

SAMPLE_PAIR_ROWS = [
    {
        "pair_index": 0,
        "requirements": [
            {"id": "URL-1", "text": "消費者能隨時取消訂單"},
            {"id": "URL-2", "text": "出餐後不可取消訂單"},
        ],
    }
]

SAMPLE_DR_REQUIREMENTS = [
    {
        "id": "REQ-1",
        "title": "線上訂餐",
        "type": "functional",
        "description": "系統應支援消費者線上訂餐",
    }
]

SAMPLE_DRAFT_SNIPPET = "# 需求草稿\n\n## scope\n\n### 系統範圍（in_scope）\n- 線上訂餐\n"

SAMPLE_STAKEHOLDERS = [
    {"name": "消費者", "type": "primary_user", "text": []},
]

SAMPLE_ROUGH_IDEA = "訂餐外送系統"

SAMPLE_RESEARCH_STATE = {
    "scenario": SAMPLE_ROUGH_IDEA,
    "scope": {"in_scope": ["線上訂餐"], "out_of_scope": []},
    "URL": [{"id": "URL-1", "text": "消費者能完成線上訂餐"}],
    "REQ": [],
    "open_questions": [],
}

SAMPLE_RESEARCH_OBS = {
    "has_existing_research": False,
    "research_results_count": 0,
}

def append_available_data(task: str, context: Optional[Dict[str, Any]] = None) -> str:
    if not context:
        return task
    block = (
        f"# Context\n"
        f"{json.dumps(context, ensure_ascii=False, indent=2)}\n\n"
    )
    return block + task.lstrip()


SAMPLE_ANALYZE_SCENARIO_CONTEXT = {"rough_idea": SAMPLE_ROUGH_IDEA}

SAMPLE_ANALYZE_REQUIREMENTS_CONTEXT = {
    "stakeholder": {
        "name": "消費者",
        "type": "primary_user",
        "source_text": "我希望可以隨時取消尚未出餐的訂單。",
        "all_text": ["我希望可以隨時取消尚未出餐的訂單。"],
    },
    "existing_requirements": SAMPLE_EXISTING_URL,
}

SAMPLE_SCOPE_GENERATE_CONTEXT = {
    "scenario": SAMPLE_ROUGH_IDEA,
    "URL": SAMPLE_EXISTING_URL,
}

SAMPLE_SCOPE_REFINE_CONTEXT = {
    "issue": {
        "id": SAMPLE_ISSUE["id"],
        "meeting_id": SAMPLE_ISSUE["meeting_id"],
        "title": SAMPLE_ISSUE["title"],
        "category": SAMPLE_ISSUE["category"],
        "trace": {},
    },
    "current_scope": {"in_scope": ["線上訂餐"], "out_of_scope": []},
    "requirements": SAMPLE_EXISTING_URL,
    "discussion": ["消費者：第三方配送流程不屬於本系統責任。"],
    "scenario": SAMPLE_ROUGH_IDEA,
}

SAMPLE_REQUIREMENT_UPDATE_CONTEXT = {
    "issue": {
        "id": "R1-M1",
        "meeting_id": "R1-M1",
        "title": "需求正式化",
        "category": "formalize_requirement",
        "trace": {},
    },
    "current_URL": SAMPLE_EXISTING_URL,
    "current_REQ": [],
    "scope": {"in_scope": ["線上訂餐"], "out_of_scope": []},
    "feedback": {},
    "system_models": [],
    "discussion": [],
    "req_source_index": {},
    "current_req_count": 0,
    "mode": "create",
    "coverage_gaps": [],
    "cleanup_issues": [],
}

SAMPLE_REQUIREMENT_REFINE_CONTEXT = {
    **SAMPLE_REQUIREMENT_UPDATE_CONTEXT,
    "issue": {
        "id": SAMPLE_ISSUE["id"],
        "meeting_id": SAMPLE_ISSUE["meeting_id"],
        "title": SAMPLE_ISSUE["title"],
        "category": SAMPLE_ISSUE["category"],
        "trace": {},
    },
    "current_REQ": [
        {
            "id": "REQ-1",
            "title": "線上訂餐",
            "type": "functional",
            "description": "系統應支援消費者線上訂餐",
            "source": ["URL-1"],
        }
    ],
    "current_req_count": 1,
    "mode": "",
}

SAMPLE_CONFLICT_DETECTION_CONTEXT = {
    "scenario": SAMPLE_ROUGH_IDEA,
    "scope": {"in_scope": ["線上訂餐"], "out_of_scope": []},
    "requirements": [
        {"id": "URL-1", "text": "消費者能隨時取消訂單", "stakeholder": "消費者"},
        {"id": "URL-2", "text": "出餐後不可取消訂單", "stakeholder": "餐廳"},
    ],
}

SAMPLE_GROUP_CONFLICT_CONTEXT = {
    **SAMPLE_CONFLICT_DETECTION_CONTEXT,
    "pairwise_conflicts": [
        {
            "pair_index": 0,
            "final_label": "Conflict",
            "final_type": "scope",
            "reason": "取消時點不一致",
        }
    ],
}

SAMPLE_CONFLICT_REPORT_ROW = {
    "id": "CR-1",
    "final_label": "Conflict",
    "final_type": "scope",
    "description": "取消規則無法同時成立",
    "requirements": [
        {"id": "URL-1", "text": "消費者能隨時取消訂單"},
        {"id": "URL-2", "text": "出餐後不可取消訂單"},
    ],
}

SAMPLE_CONFLICT_REPORT_CONTEXT = {
    "conflict_report": [SAMPLE_CONFLICT_REPORT_ROW],
}

SAMPLE_CONFLICT_REPORT_UPDATE_CONTEXT = {
    "previous_conflict_report": "# 需求衝突報告\n\n## 衝突ID：取消規則\n",
    **SAMPLE_CONFLICT_REPORT_CONTEXT,
}

SAMPLE_CONFLICT_RESOLUTION_CONTEXT = SAMPLE_CONFLICT_REPORT_ROW

SAMPLE_DRAFT_CREATE_CONTEXT = {
    "scope": {"in_scope": ["線上訂餐"], "out_of_scope": []},
    "URL": SAMPLE_EXISTING_URL,
    "open_questions": [],
    "feedback": {},
    "system_models": [],
    "version": 0,
    "stakeholders": SAMPLE_STAKEHOLDERS,
    "rough_idea": SAMPLE_ROUGH_IDEA,
    "scenario": SAMPLE_ROUGH_IDEA,
}

SAMPLE_DRAFT_UPDATE_CONTEXT = {
    **SAMPLE_DRAFT_CREATE_CONTEXT,
    "version": 1,
    "meeting_context": [],
    "REQ": [
        {
            "id": "REQ-1",
            "title": "線上訂餐",
            "type": "functional",
            "description": "系統應支援消費者線上訂餐",
            "source": ["URL-1"],
        }
    ],
    "previous_draft": SAMPLE_DRAFT_SNIPPET.strip(),
}

SAMPLE_DOMAIN_RESEARCH_CONTEXT = {
    "issue": SAMPLE_ISSUE,
    "scenario": SAMPLE_ROUGH_IDEA,
    "scope": {"in_scope": ["線上訂餐"], "out_of_scope": []},
    "URL": SAMPLE_EXISTING_URL,
    "REQ": [],
    "stakeholders": SAMPLE_STAKEHOLDERS,
    "open_questions": [],
    "existing_document_evidence": [],
}

SAMPLE_DOMAIN_RESEARCH_ISSUE_CONTEXT = {
    **SAMPLE_DOMAIN_RESEARCH_CONTEXT,
    "document_evidence": [],
}

SAMPLE_DOMAIN_FEEDBACK_CONTEXT = {
    "research_results": [],
    "existing_research": {},
    "document_evidence": [],
    "URL": SAMPLE_EXISTING_URL,
}

SAMPLE_PROPOSE_ISSUES_CONTEXT = {
    "round_num": 1,
    "latest_draft": "",
    "proposal_context": {},
}

EXPERT_AVAILABLE_ACTIONS = {
    "answer_question": "使用時機：有人在 open_questions 中指定 expert 回答。不要使用：一般議題發言或領域研究。寫回或影響：只回答問題，不更新專案資料。",
    "respond_issue": "使用時機：只需要根據 issue、前文與現有資料表達領域意見。不要使用：需要專案文件證據、外部法規/標準、第三方限制或 feedback 更新時。寫回或影響：只產生會議發言，不更新 feedback。",
    "research_domain": "流程 action。使用時機：議題需要文件證據、外部知識、法規/標準、第三方限制、合規、安全或隱私風險判斷。不要使用：一般功能偏好、純需求語意討論或現有資料已足夠。寫回或影響：內部依需要執行 read_reference_docs、research_issue、update_feedback；正式產物只寫回 feedback，不直接定案需求。",
}

MODELER_AVAILABLE_ACTIONS = {
    "answer_question": "使用時機：有人在 open_questions 中指定 modeler 回答。不要使用：一般議題發言或建模流程。寫回或影響：只回答問題，不更新專案資料。",
    "respond_issue": "使用時機：只需要根據 issue、前文與現有資料表達建模觀點。不要使用：需要建立、更新或驗證 UML/system model 時。寫回或影響：只產生會議發言，不更新系統模型。",
    "system_modeling": "流程 action。使用時機：議題涉及系統邊界、actor/use case、流程、資料、狀態、互動順序、責任分工或模型追蹤性，且建立/更新 UML/system model 能讓討論更清楚或檢查一致性。不要使用：只是需求文字、業務偏好或衝突取捨，且沒有流程、資料、狀態、角色互動、責任邊界或視覺化價值。寫回或影響：內部只規劃一次 plan_models，之後依 plan 逐一執行 create_model/update_model、必要時 write_use_case_text，並由 validate_model 驗證；驗證失敗時由 validate_model 內部修復一次。正式產物只更新 system_models，不從模型反推需求。",
}

PROPOSE_ISSUE_VARIANTS = [
    (
        "analyst/propose_issues.txt",
        proposal_prompt(
            agent_label="需求工程",
            focus="需求語意、範圍、驗收條件、來源追蹤或需求規格化",
            value_gate=[
                "會阻礙需求規格定稿、需求可驗收性、scope 穩定或來源追蹤。",
                "需要正式會議中的至少兩方觀點、取捨、確認或決策；若 analyst 可直接修稿或整理，不要提出。",
            ],
            reject_rule=(
                "不要提出：措辭潤飾、單一欄位補字、單一 acceptance criteria 補充、"
                "一般最佳實務提醒、無 source id 的猜測、小型重複問題。"
                "若單一 id 代表較大的流程、狀態、責任邊界、驗收標準或風險面向，"
                "可以提出，但 reason 必須說清楚共同問題。"
            ),
        ),
    ),
    (
        "expert/propose_issues.txt",
        proposal_prompt(
            agent_label="domain / compliance / risk",
            focus="外部限制、風險、證據缺口或待確認議題",
            value_gate=[
                "會阻礙需求規格的外部限制、合規/安全風險、證據依據、品質底線或待確認義務定稿。",
                "需要正式會議確認適用範圍、風險取捨、是否轉成需求或是否交由人類裁決；若只是研究建議或可直接寫入 feedback，不要提出。",
            ],
            reject_rule=(
                "不要提出：一般最佳實務提醒、無明確適用範圍的法規猜測、低影響風險、"
                "可由 research_domain 直接更新 feedback 的事項。若單一限制或風險會影響一組需求、"
                "驗收底線或是否能寫入 SRS，可以提出，但 reason 必須說清楚共同領域問題。"
            ),
        ),
    ),
    (
        "modeler/propose_issues.txt",
        proposal_prompt(
            agent_label="需求建模",
            focus="模型一致性、系統邊界、actor/use case、流程、資料或狀態缺口",
            value_gate=[
                "會阻礙需求規格中的流程、角色、資料、狀態、系統邊界或模型追蹤性的定稿。",
                "需要正式會議確認需求語意、角色責任、流程分歧、資料狀態或模型影響；若 modeler 可直接建立或更新模型，不要提出。",
            ],
            reject_rule=(
                "不要提出：單純補圖、命名調整、版面修正、可由建模 action 直接處理的模型生成工作。"
                "若單一模型缺口代表較大的流程、狀態、資料生命週期或責任邊界問題，"
                "可以提出，但 reason 必須說清楚共同模型問題。"
            ),
        ),
    ),
]

PAIR_DETECTION_RULES = [
    "只判斷下列指定 pair，pair 之間互相獨立。",
    "配對方式固定為需求順序 1 對 2、3 對 4、5 對 6；若最後剩一筆需求，不判斷。",
    "每一個 pair 都必須輸出恰好一筆結果。",
    "pair_index 必須與下列清單一致。",
    "不需要輸出 requirement_ids，系統會根據 pair_index 自動對回 requirements。",
    "本步只處理指定 pair；群組衝突留給整體判斷。",
]


def write(rel_path: str, content: str) -> None:
    path = MANUAL_AGENT / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")
    print(f"wrote {rel_path}")


def compose_skill_task(
    *,
    skill_name: str,
    guidance: str,
    task: str,
    context: Optional[Dict[str, Any]] = None,
) -> str:
    parts = [f"# Skill: {skill_name}\n"]
    if guidance.strip():
        parts.append(f"\n{guidance.strip()}\n\n")
    if context:
        parts.append(
            f"# Context\n"
            f"{json.dumps(context, ensure_ascii=False, indent=2)}\n\n"
        )
    if task.lstrip().startswith("# 任務"):
        parts.append(task.strip())
    else:
        parts.append(f"# 任務\n\n{task.strip()}")
    return "".join(parts)


def requirements_prompt(
    *,
    mode: str,
    task: str,
    context: Optional[Dict[str, Any]] = None,
) -> str:
    skill = get_skill("requirements-analyst")
    guidance = requirements_skill_guidance(str(skill.get("content") or ""), mode)
    return compose_skill_task(
        skill_name="requirements-analyst",
        guidance=guidance,
        task=task,
        context=context,
    )


def conflict_prompt(
    *,
    mode: str,
    task: str,
    context: Optional[Dict[str, Any]] = None,
) -> str:
    skill = conflict_skill_subset(get_skill("conflict-analyzer"), mode)
    skill_name = str(skill.get("name") or "conflict-analyzer")
    guidance = str(skill.get("content") or "").strip()
    if not guidance:
        guidance = conflict_skill_guidance(
            str(get_skill("conflict-analyzer").get("content") or ""),
            mode,
        )
    return compose_skill_task(
        skill_name=skill_name,
        guidance=guidance,
        task=task,
        context=context,
    )


def domain_prompt(
    *,
    mode: str,
    task: str,
    context: Optional[Dict[str, Any]] = None,
) -> str:
    skill = domain_skill_subset(get_skill("domain-research"), mode)
    skill_name = str(skill.get("name") or "domain-research")
    guidance = str(skill.get("content") or "").strip()
    if not guidance:
        guidance = domain_skill_guidance(
            str(get_skill("domain-research").get("content") or ""),
            mode,
        )
    return compose_skill_task(
        skill_name=skill_name,
        guidance=guidance,
        task=task,
        context=context,
    )


def uml_prompt(*, mode: str, task: str, diagram_type: str = "") -> str:
    skill = uml_skill_subset(get_skill("UML"), mode, diagram_type)
    skill_name = str(skill.get("name") or "uml-modeling")
    guidance = str(skill.get("content") or "").strip()
    if not guidance:
        guidance = uml_skill_guidance(
            str(get_skill("UML").get("content") or ""),
            mode,
            diagram_type,
        )
    return compose_skill_task(skill_name=skill_name, guidance=guidance, task=task)


def available_actions_doc(title: str, actions: Dict[str, str]) -> str:
    lines = [title, ""]
    lines.extend(f"- {name}：{desc}" for name, desc in actions.items())
    return "\n".join(lines)


def analyst_available_actions_doc(title: str = "# Analyst agent_action 可用 action") -> str:
    base = available_actions_doc(f"{title}\n\n## Base actions", ANALYST_AVAILABLE_ACTIONS)
    conditional = available_actions_doc(
        "## Conditional actions",
        ANALYST_NEW_REQUIREMENT_ACTION,
    )
    return f"{base}\n\n{conditional}"


def build_user_response_prompt(issue: Dict[str, Any]) -> str:
    issue_text = (
        f"議題 [{issue.get('id', '')}]: {issue.get('title', '')}\n"
        f"描述: {issue.get('description', '')}"
    )
    issue_category = str(issue.get("category") or "").strip()
    related_context = {
        "rough_idea": SAMPLE_ROUGH_IDEA,
        "stakeholders": SAMPLE_STAKEHOLDERS,
        **SAMPLE_CONTEXT,
    }
    stakeholder_contract_text = stakeholder_contract(
        related_context=related_context,
        stakeholders=SAMPLE_STAKEHOLDERS,
    )
    target_stakeholders = [
        str(name).strip()
        for name in (issue.get("target_stakeholders") or [])
        if str(name).strip()
    ]
    names_list = [sh["name"] for sh in SAMPLE_STAKEHOLDERS]
    if len(SAMPLE_STAKEHOLDERS) == 1:
        roles_text = f"\n# 本輪發言身份\n請「僅」以【{names_list[0]}】的身份發言。"
    else:
        roles_text = (
            "\n# 本輪回答身份\n"
            "本輪未指定回答身份；請只選擇與此議題最直接相關的一位或多位利害關係人發言，不要代表全部利害關係人泛泛回答。"
        )
    if target_stakeholders:
        roles_text += (
            "\n# 本輪指定回答身份\n"
            f"本輪身份由議題規劃指定，只能代表這些利害關係人回答：{', '.join(target_stakeholders)}。\n"
            "不得自行切換到其他利害關係人；如果問題不適合指定身份，請以該身份說明不適用或缺少情境。\n"
        )

    context_text = (
        f"{json.dumps(related_context, ensure_ascii=False, indent=2)}"
    )
    is_elicitation = str(issue.get("id") or "").startswith("ELICIT-")
    is_answer_question = str(issue.get("id") or "") == "OQ"
    contract = (
        issue.get("conflict_review_contract")
        if isinstance(issue.get("conflict_review_contract"), dict)
        else {}
    )
    is_pair_review = str(contract.get("type") or "").strip() == "pair_reviews"
    known_pair_ids = [
        str(pair_id).strip()
        for pair_id in (contract.get("known_pair_ids") or [])
        if str(pair_id).strip()
    ]
    need_speaking_as = len(SAMPLE_STAKEHOLDERS) > 1
    flow_hint = response_flow(
        need_speaking_as=need_speaking_as,
        answer_all_questions=False,
        is_answer_question=is_answer_question,
    )
    json_hint = response_json(
        need_speaking_as=need_speaking_as,
        is_elicitation=is_elicitation,
        is_answer_question=is_answer_question,
        is_pair_review=issue_category == "resolve_conflict" and is_pair_review,
    )
    category_text = user_category_hint(
        issue=issue,
        issue_category=issue_category,
        is_pair_review=is_pair_review,
        known_pair_ids=known_pair_ids,
    )
    open_questions_rule_text = open_question_rule(
        is_elicitation=is_elicitation,
        is_answer_question=is_answer_question,
    )
    suppress_stance = bool(
        is_elicitation
        or is_answer_question
        or (issue_category == "resolve_conflict" and is_pair_review)
    )
    names_list_text = ", ".join(names_list)
    return user_issue_response(
        stakeholder_contract_text=stakeholder_contract_text,
        roles_text=roles_text,
        issue_text=issue_text,
        prev_text="",
        context_text=context_text,
        category_hint=category_text,
        flow_hint=flow_hint,
        json_hint=json_hint,
        stance_json_text=stance_json(suppress_stance=suppress_stance),
        stance_rule_text=stance_rule(suppress_stance=suppress_stance),
        open_questions_rule=open_questions_rule_text,
        answer_all_questions=False,
        need_speaking_as=need_speaking_as,
        names_list_text=names_list_text,
        target_stakeholders=target_stakeholders,
    )


def export_analyst() -> None:
    write(
        "analyst/analyze_scenario.txt",
        append_available_data(name_scenario(), SAMPLE_ANALYZE_SCENARIO_CONTEXT),
    )

    extraction_rules = url_extraction_rules()
    write(
        "analyst/reqt/analyze_requirements.txt",
        requirements_prompt(
            mode="analysis",
            task=extract_requirement(
                scenario_json=json.dumps(SAMPLE_ROUGH_IDEA, ensure_ascii=False, indent=2),
                stakeholder_row={
                    "name": "消費者",
                    "type": "primary_user",
                    "text": "我希望可以隨時取消尚未出餐的訂單。",
                },
                existing_rows=[],
                mode_name="",
                rules=extraction_rules,
            ),
        ),
    )
    write(
        "analyst/reqt/update_requirement.txt",
        requirements_prompt(
            mode="update_requirement",
            task=update_requirement(
                requirement_mode="create",
                source_id="R1-M1",
                coverage_gaps=None,
            ),
            context=SAMPLE_REQUIREMENT_UPDATE_CONTEXT,
        ),
    )
    write(
        "analyst/reqt/refine_requirement.txt",
        requirements_prompt(
            mode="refine_requirement",
            task=refine_requirement(source_id="R1-M1"),
            context=SAMPLE_REQUIREMENT_REFINE_CONTEXT,
        ),
    )

    write(
        "analyst/scope/generate_scope.txt",
        append_available_data(generate_scope(), SAMPLE_SCOPE_GENERATE_CONTEXT),
    )
    write(
        "analyst/scope/refine_scope.txt",
        append_available_data(refine_scope(source_id="R1-M1"), SAMPLE_SCOPE_REFINE_CONTEXT),
    )

    base_task = conflict_detection_base_task()
    pair_rules = "\n".join(f"- {rule}" for rule in PAIR_DETECTION_RULES)
    write(
        "analyst/conflict/detect_pair_conflicts.txt",
        conflict_prompt(
            mode="analysis",
            task=pair_detection(
                base_task=base_task,
                heading="兩兩判斷",
                rules=pair_rules,
                rows_label="指定 pairs",
                pair_rows=SAMPLE_PAIR_ROWS,
            ),
            context=SAMPLE_CONFLICT_DETECTION_CONTEXT,
        ),
    )
    write(
        "analyst/conflict/detect_group_conflicts.txt",
        append_available_data(
            group_detection(base_task=base_task),
            SAMPLE_GROUP_CONFLICT_CONTEXT,
        ),
    )

    write(
        "analyst/report/generate_conflict_report.txt",
        conflict_prompt(
            mode="report",
            task=create_report(),
            context=SAMPLE_CONFLICT_REPORT_CONTEXT,
        ),
    )
    write(
        "analyst/report/resolve_conflicts.txt",
        conflict_prompt(
            mode="resolution:scope",
            task=report_resolution(),
            context=SAMPLE_CONFLICT_RESOLUTION_CONTEXT,
        ),
    )

    write(
        "analyst/draft/create_draft.txt",
        append_available_data(
            create_draft(version_note="初版草稿", version=0),
            SAMPLE_DRAFT_CREATE_CONTEXT,
        ),
    )
    write(
        "analyst/draft/update_draft.txt",
        append_available_data(
            update_draft(version_note="依會議更新", version=1),
            SAMPLE_DRAFT_UPDATE_CONTEXT,
        ),
    )

    write(
        "analyst/conflict/review_signoff.txt",
        review_signoff(
            proposal_list=[],
            extracted_pair_reviews=[],
            discussion_rows=[],
        ),
    )
    write(
        "analyst/conflict/review_reason.txt",
        review_reason(
            decision_list=[
                {
                    "id": "PAIR-1",
                    "final_label": "Conflict",
                    "final_type": "scope",
                }
            ],
            extracted_pair_reviews=[],
            type_guidance=conflict_type_guidance_from_skill(),
        ),
    )


def export_expert() -> None:
    query = "確認訂單取消與退款是否涉及消費者保護或支付相關限制"
    write(
        "expert/read_reference_docs.txt",
        domain_prompt(
            mode="read_docs",
            task=read_docs(query=query),
            context=SAMPLE_DOMAIN_RESEARCH_CONTEXT,
        ),
    )
    write(
        "expert/research_issue.txt",
        domain_prompt(
            mode="research",
            task=research_issue(
                query=query,
                source_ref="R1-M1",
                value_reason="此問題可能影響需求是否成立、驗收標準、風險、責任邊界或系統限制。",
            ),
            context=SAMPLE_DOMAIN_RESEARCH_ISSUE_CONTEXT,
        ),
    )
    write(
        "expert/update_feedback.txt",
        domain_prompt(
            mode="feedback",
            task=update_feedback(source_ref="R1-M1"),
            context=SAMPLE_DOMAIN_FEEDBACK_CONTEXT,
        ),
    )


def export_modeler() -> None:
    plan_context = {
        "issue": SAMPLE_ISSUE,
        "scenario": SAMPLE_ROUGH_IDEA,
        "stakeholders": SAMPLE_STAKEHOLDERS,
        "URL": SAMPLE_EXISTING_URL,
        "REQ": [],
        "scope": {"in_scope": ["線上訂餐"], "out_of_scope": []},
        "feedback": {},
        "open_questions": [],
        "current_models": [],
        "model_revision_context": {},
        "requirement_source": "URL",
    }
    write(
        "modeler/plan_models.txt",
        uml_prompt(mode="selection", task=target_prompt(context=plan_context)),
    )

    diagram_type = "sequence_diagram"
    type_name = "Sequence Diagram"
    req_text = json.dumps(SAMPLE_EXISTING_URL, ensure_ascii=False, indent=2)
    context_text = json.dumps(
        {"scope": {"in_scope": ["線上訂餐"]}, "feedback": {}},
        ensure_ascii=False,
        indent=2,
    )
    diagram_layout_hint = model_layout_hint(diagram_type)
    description_rule, description_field = model_description_contract(diagram_type)
    existing_plantuml = (
        "@startuml\n"
        "actor 消費者\n"
        "participant 訂餐系統\n"
        "消費者 -> 訂餐系統: 提交訂單\n"
        "@enduml"
    )
    write(
        "modeler/create/sequence_diagram.txt",
        uml_prompt(
            mode="diagram",
            diagram_type=diagram_type,
            task=create_model(
                type_name=type_name,
                req_text=req_text,
                context_text=context_text,
                diagram_layout_hint=diagram_layout_hint,
                diagram_type=diagram_type,
                description_rule=description_rule,
                description_field=description_field,
            ),
        ),
    )
    write(
        "modeler/update/sequence_diagram.txt",
        uml_prompt(
            mode="diagram",
            diagram_type=diagram_type,
            task=update_model(
                type_name=type_name,
                existing_plantuml=existing_plantuml,
                req_text=req_text,
                context_text=context_text,
                diagram_layout_hint=diagram_layout_hint,
                diagram_type=diagram_type,
                description_rule=description_rule,
                description_field=description_field,
            ),
        ),
    )
    write(
        "modeler/write_use_case_text.txt",
        uml_prompt(
            mode="use_case_text",
            task=use_case_text(
                req_text=req_text,
                use_case_diagram_text="{}",
                context_text=context_text,
            ),
        ),
    )


def export_plans() -> None:
    write(
        "analyst/plan/available_actions.txt",
        analyst_available_actions_doc(),
    )
    write(
        "analyst/plan/action_plan.txt",
        action_plan_prompt(
            role="analyst",
            issue=SAMPLE_ISSUE,
            issue_category=str(SAMPLE_ISSUE.get("category") or ""),
            previous_response_count=0,
            recent_responses=[],
            has_related_context=True,
            recent_ask_history=[],
            actions_text=available_actions_doc("", ANALYST_AVAILABLE_ACTIONS).strip(),
            default_action="respond_issue",
        ),
    )
    write(
        "expert/plan/available_actions.txt",
        available_actions_doc("# Expert agent_action 可用 action", EXPERT_AVAILABLE_ACTIONS),
    )
    write(
        "modeler/plan/available_actions.txt",
        available_actions_doc("# Modeler agent_action 可用 action", MODELER_AVAILABLE_ACTIONS),
    )
    write(
        "user/plan/available_actions.txt",
        available_actions_doc("# User agent_action 可用 action", response_actions()),
    )
    write(
        "expert/plan/research_domain.txt",
        research_prompt(
            state_text=json.dumps(SAMPLE_RESEARCH_STATE, ensure_ascii=False, indent=2),
            obs_text=json.dumps(SAMPLE_RESEARCH_OBS, ensure_ascii=False, indent=2),
        ),
    )


def export_responses() -> None:
    analyst_exports = [
        ("analyst/response/respond_issue.txt", analyst_issue.issue_response, SAMPLE_ISSUE),
        ("analyst/response/answer_question.txt", analyst_answer.issue_response, SAMPLE_OQ_ISSUE),
        ("analyst/response/ask_user.txt", analyst_elicitation_resp.issue_response, SAMPLE_ELICIT_ISSUE),
        ("analyst/response/pair_reviews.txt", analyst_conflict.issue_response, SAMPLE_PAIR_ISSUE),
        ("analyst/response/resolve_conflict.txt", analyst_resolution.issue_response, SAMPLE_RESOLVE_ISSUE),
    ]
    for rel_path, fn, issue in analyst_exports:
        write(
            rel_path,
            fn(
                issue=issue,
                previous_responses=[],
                related_context=SAMPLE_CONTEXT,
            ),
        )

    expert_exports = [
        ("expert/response/respond_issue.txt", expert_issue.issue_response, SAMPLE_ISSUE),
        ("expert/response/answer_question.txt", expert_answer.issue_response, SAMPLE_OQ_ISSUE),
        ("expert/response/ask_user.txt", expert_elicitation_resp.issue_response, SAMPLE_ELICIT_ISSUE),
    ]
    for rel_path, fn, issue in expert_exports:
        write(
            rel_path,
            fn(
                issue=issue,
                previous_responses=[],
                related_context=SAMPLE_CONTEXT,
            ),
        )

    modeler_exports = [
        ("modeler/response/respond_issue.txt", modeler_issue.issue_response, SAMPLE_ISSUE),
        ("modeler/response/answer_question.txt", modeler_answer.issue_response, SAMPLE_OQ_ISSUE),
        ("modeler/response/ask_user.txt", modeler_elicitation_resp.issue_response, SAMPLE_ELICIT_ISSUE),
    ]
    for rel_path, fn, issue in modeler_exports:
        write(
            rel_path,
            fn(
                issue=issue,
                previous_responses=[],
                related_context=SAMPLE_CONTEXT,
            ),
        )


def export_user_responses() -> None:
    write("user/response/respond_issue.txt", build_user_response_prompt(SAMPLE_ISSUE))
    write("user/response/answer_question.txt", build_user_response_prompt(SAMPLE_OQ_ISSUE))
    write(
        "user/response/response.txt",
        build_user_response_prompt(SAMPLE_ELICIT_ISSUE),
    )


def export_propose_issues() -> None:
    for rel_path, prompt in PROPOSE_ISSUE_VARIANTS:
        write(rel_path, append_available_data(prompt, SAMPLE_PROPOSE_ISSUES_CONTEXT))


def export_mediator_and_user() -> None:
    write(
        "mediator/resolve_issue.txt",
        close_issue(
            issue=SAMPLE_ISSUE,
            discussion_text="消費者：取消規則應在出餐前。\n餐廳：出餐後不可取消。",
            readiness={"stance": "ready_to_close", "summary": "主要立場已收斂"},
        ),
    )
    write(
        "mediator/judge_issue.txt",
        judge_options(
            issue=SAMPLE_ISSUE,
            discussion_text="消費者：取消規則應在出餐前。\n餐廳：出餐後不可取消。",
            decision_context=None,
        ),
    )
    write(
        "mediator/select_issues.txt",
        select_issues(
            proposals=[
                {
                    "title": "訂單狀態規則是否一致",
                    "category": "clarify_requirement",
                    "issue_focus": "requirement_completeness",
                    "importance": "high",
                    "reason": "取消規則影響需求可驗收性",
                    "sources": [
                        {
                            "artifact": "URL",
                            "ids": ["URL-1", "URL-2"],
                            "evidence": "兩筆需求對取消時點描述不一致",
                        }
                    ],
                }
            ],
            max_items=5,
            skip_artifact_ids=["URL-1"],
            is_last_round=False,
            round_num=1,
        ),
    )
    category_definitions = "\n".join(
        f"- {item['id']}：{item.get('description') or item.get('label') or item['id']}"
        for item in issue_types
        if item["id"] in set(issue_type_ids)
    )
    write(
        "mediator/meeting_plan.txt",
        meeting_plan(
            issue={
                "title": SAMPLE_ISSUE["title"],
                "category": SAMPLE_ISSUE["category"],
                "description": SAMPLE_ISSUE["description"],
                "expect_outcome": "釐清取消規則",
                "trace": {"proposal_ids": ["P-1"]},
            },
            related_context=SAMPLE_CONTEXT,
            active_types=list(issue_type_ids),
            category_definitions=category_definitions,
            registered=["user", "analyst", "expert", "modeler"],
            stakeholder_names=["消費者"],
        ),
    )
    write(
        "mediator/plan_elicitation.txt",
        build_elicitation_plan(
            turn=1,
            max_turns=3,
            default_participants=["analyst", "expert", "modeler", "user"],
            stakeholder_names=["消費者"],
            scenario=SAMPLE_ROUGH_IDEA,
            scope={"in_scope": ["線上訂餐"], "out_of_scope": []},
            current_requirements=SAMPLE_EXISTING_URL,
            previous_turn_summary={},
            recent_ask_history=[],
        ),
    )
    write(
        "mediator/plan_conflict_review.txt",
        build_conflict_review(
            participants=["analyst", "expert", "modeler"],
            candidate_count=2,
        ),
    )
    write(
        "mediator/meeting_action.txt",
        meeting_action(
            state_summary={
                "issues": [],
                "can_add_issues": True,
                "human_decision_queue": [],
                "meeting_issues": [],
            },
            last_observation={
                "action": "plan_issues",
                "status": "success",
            },
            enable_human_judgment=True,
        ),
    )
    write(
        "mediator/closure_vote.txt",
        closure_vote(
            role="analyst",
            proposer_role="user",
            role_focus="需求完整性與可驗收性",
            scenario=SAMPLE_ROUGH_IDEA,
            requirements=SAMPLE_EXISTING_URL,
            candidate_texts=["目前資訊是否已足夠整理下一版 requirement set？"],
            recent_ask_history=[],
        ),
    )

    scenario_context = json.dumps(SAMPLE_ROUGH_IDEA, ensure_ascii=False, indent=2)
    write(
        "user/suggest_stakeholders.txt",
        suggest_stakeholders(scenario_context=scenario_context),
    )
    write(
        "user/write_stakeholder_text.txt",
        write_stakeholder_text(
            stakeholder_list="1. 消費者",
            scenario_context=scenario_context,
        ),
    )


def export_system_and_documentor() -> None:
    write("analyst/system_prompt.txt", analyst_system)
    write("expert/system_prompt.txt", expert_system)
    write("modeler/system_prompt.txt", modeler_system)
    write("user/system_prompt.txt", user_system)
    write("mediator/system_prompt.txt", mediator_system)
    write("documentor/system_prompt.txt", documentor_system)
    write(
        "documentor/generate_srs.txt",
        generate_srs(draft_md=SAMPLE_DRAFT_SNIPPET),
    )
    write(
        "documentor/generate_dr.txt",
        design_rationale(requirements=SAMPLE_DR_REQUIREMENTS),
    )


def export_skills() -> None:
    dest_root = MANUAL_AGENT / "skills"
    if dest_root.exists():
        shutil.rmtree(dest_root)
    dest_root.mkdir(parents=True, exist_ok=True)

    for skill_dir in sorted(SKILLS_SRC.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_md = skill_dir / "SKILL.md"
        if skill_md.is_file():
            target_dir = dest_root / skill_dir.name
            target_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(skill_md, target_dir / "SKILL.md")
            print(f"wrote skills/{skill_dir.name}/SKILL.md")

        refs_dir = skill_dir / "references"
        if refs_dir.is_dir():
            target_refs = dest_root / skill_dir.name / "references"
            target_refs.mkdir(parents=True, exist_ok=True)
            for ref_file in sorted(refs_dir.glob("*.md")):
                shutil.copy2(ref_file, target_refs / ref_file.name)
                print(f"wrote skills/{skill_dir.name}/references/{ref_file.name}")


def main() -> None:
    export_analyst()
    export_expert()
    export_modeler()
    export_plans()
    export_responses()
    export_user_responses()
    export_propose_issues()
    export_mediator_and_user()
    export_system_and_documentor()
    export_skills()
    print("done")


if __name__ == "__main__":
    main()
