"""MeetingCoordinator — 會議協調窗口。

所有實作已拆至子模組：
  - main_meeting          : 每輪主會議生命週期
  - meeting_hidden_elicitation : 隱性需求挖掘
  - meeting_conflict_review    : 衝突複核 / 需求變更
  - meeting_subflows           : agenda loop / queue 子流程
"""
from typing import Any, Dict

from .main_meeting import (
    _apply_mediator_updates,
    _collect_topic_proposals,
    _normalize_topic_proposal,
    _recent_topic_discussions,
    _run_enabled_reviews,
    run_meeting_round_block,
)
from .meeting_conflict_review import run_pre_meeting_conflict_review_block
from .meeting_hidden_elicitation import run_hidden_requirement_elicitation_meeting_block
from .meeting_subflows import run_agenda_loop_block


class MeetingCoordinator:
    def __init__(self, flow):
        self.flow = flow

    # ------ 共用小工具（window 保留供 flow.py 委派呼叫） ------

    def _is_last_meeting_round(self, artifact: Dict[str, Any], round_num: int) -> bool:
        meta = artifact.get("meta") or {}
        end = meta.get("session_end_round")
        if end is not None:
            try:
                return int(round_num) == int(end)
            except (TypeError, ValueError):
                pass
        try:
            total = int(self.flow.config.get("rounds", 1) or 1)
        except (TypeError, ValueError):
            total = 1
        return int(round_num) >= total

    # ------ 委派：main_meeting ------

    def _run_enabled_reviews(self, artifact, *, recent_discussions, roles):
        _run_enabled_reviews(self, artifact, recent_discussions=recent_discussions, roles=roles)

    def _recent_topic_discussions(self, artifact, *, rounds=1):
        return _recent_topic_discussions(artifact, rounds=rounds)

    def _normalize_topic_proposal(self, item, *, proposed_by, round_num, index):
        return _normalize_topic_proposal(item, proposed_by=proposed_by, round_num=round_num, index=index)

    def _collect_topic_proposals(self, artifact, *, round_num):
        return _collect_topic_proposals(self, artifact, round_num=round_num)

    def _apply_mediator_updates(self, artifact, updates):
        return _apply_mediator_updates(artifact, updates)

    # ------ 委派：meeting_subflows ------

    def _run_agenda_loop(self, runner):
        run_agenda_loop_block(self, runner)

    # ------ 委派：主流程入口 ------

    def run_hidden_requirement_elicitation_meeting(self, artifact, round_num):
        return run_hidden_requirement_elicitation_meeting_block(self, artifact, round_num)

    def run_pre_meeting_conflict_review(self, artifact, round_num):
        return run_pre_meeting_conflict_review_block(self, artifact, round_num)

    def run_meeting_round(self, artifact, round_num):
        return run_meeting_round_block(self, artifact, round_num)
