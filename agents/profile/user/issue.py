# Handles issue proposal and issue response flow.
import json
from typing import Any, Dict, List

from agents.profile.base import proposal_prompt


# Defines UserIssue class for this module workflow.
class UserIssue:
    # Defines propose issues function for this module workflow.
    def propose_issues(
        self,
        artifact: Dict[str, Any],
        *,
        round_num: int,
        max_items: int = 20,
    ) -> List[Dict[str, Any]]:
        opa = self.run_action_loop(
            name="user_issue_proposal",
            context={
                "artifact": artifact,
                "round_num": round_num,
                "max_items": max(1, max_items),
            },
            obs_fn=self.obs_issue,
            decide_action=self.plan_issue,
            execute_action=self.run_issue_action,
        )
        trace = opa.get("opa_trace") or []
        result = dict((trace[-1].get("result") if trace else {}) or {})
        if result.get("error"):
            raise RuntimeError(result.get("format_error") or result.get("error"))
        return result.get("proposals", [])[: max(1, max_items)]

    # Defines obs issue function for this module workflow.
    def obs_issue(self, **kwargs: Any) -> Dict[str, Any]:
        artifact = kwargs["artifact"]
        return {
            "iteration": kwargs.get("iteration", 0) + 1,
            "max_iterations": kwargs["max_iterations"],
            "round_num": kwargs.get("round_num"),
            "max_items": kwargs.get("max_items", 20),
            "latest_draft": artifact.get("latest_draft", ""),
            "artifact_slices": artifact.get("artifact_slices") if isinstance(artifact.get("artifact_slices"), dict) else {},
        }

    # Defines run issue action function for this module workflow.
    def run_issue_action(
        self,
        *,
        decision: Dict[str, Any],
        observation: Dict[str, Any],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        action = str(decision.get("action") or "").strip()
        if action != "propose_issues":
            return {
                "action": action,
                "status": "failed",
                "error": "unsupported_action",
                "format_error": f"User issue proposal 不支援 action: {action}",
            }

        max_items = int(observation.get("max_items") or 20)
        context = {
            "round_num": observation.get("round_num"),
            "latest_draft": observation.get("latest_draft", ""),
            "artifact_slices": observation.get("artifact_slices") or {},
        }
        prompt = proposal_prompt(
            agent_label="使用者 / 利害關係人",
            focus="使用者語意、使用邊界、責任歸屬、可接受條件或待確認議題",
            value_gate=[
                "會阻礙需求規格定稿、使用者需求確認、責任邊界、可接受條件或重要 tradeoff。",
                "可能需要指定利害關係人進入正式會議表態、確認或取捨；若不確定只是偏好還是需求底線，也可以提出給 Mediator 判斷。",
            ],
            reject_rule=(
                "通常不值得提出：泛泛使用者意見、低影響 UI 偏好、沒有明確利害關係人的小問題。"
                "單一缺口若可能影響使用底線、責任歸屬、驗收方式或可接受條件，也可以提出。"
            ),
        )
        try:
            data = self.chat_json(self.build_direct_messages(prompt, context=context))
            proposals = self.issue_payload(
                data,
                round_num=int(observation.get("round_num") or 0),
                max_items=max_items,
            )
        except Exception as e:
            return {
                "action": action,
                "status": "failed",
                "error": "invalid_issue_proposal_output",
                "format_error": str(e),
                "summary": "User issue proposal 輸出格式不合格",
            }
        return {
            "action": action,
            "status": "success",
            "proposals": proposals,
            "summary": f"User 提出 {len(proposals)} 筆 issue proposal",
        }

    # Defines issue payload function for this module workflow.
    def issue_payload(
        self,
        data: Dict[str, Any],
        *,
        round_num: int,
        max_items: int,
    ) -> List[Dict[str, Any]]:
        raw_issues = data
        if isinstance(raw_issues, dict):
            raw_issues = raw_issues.get("issues") or raw_issues.get("proposals") or []
        if not isinstance(raw_issues, list):
            raise ValueError("User issue proposal 必須直接輸出 issues list")

        allowed_importance = {"high", "medium", "low"}
        proposals: List[Dict[str, Any]] = []
        seen = set()
        for idx, row in enumerate(raw_issues, 1):
            if not isinstance(row, dict):
                raise ValueError(f"issues[{idx}] 必須是 object")
            title = str(row.get("title") or "").strip()
            if not title:
                raise ValueError(f"issues[{idx}] 缺少 title")
            expect_outcome = str(row.get("expect_outcome") or "").strip()
            sources = []
            for source in row.get("sources") or []:
                if not isinstance(source, dict):
                    continue
                artifact = str(source.get("artifact") or "").strip()
                ids = [
                    str(x).strip()
                    for x in (source.get("ids") or [])
                    if str(x).strip()
                ]
                evidence = str(source.get("evidence") or "").strip()
                if artifact and evidence:
                    sources.append({"artifact": artifact, "ids": list(dict.fromkeys(ids)), "evidence": evidence})
            reason = str(row.get("reason") or "").strip()
            if not expect_outcome or not sources or not reason:
                raise ValueError(f"issues[{idx}] 缺少 expect_outcome/sources/reason")

            importance = str(row.get("importance") or "").strip().lower()
            if importance not in allowed_importance:
                raise ValueError(f"issues[{idx}] importance 不合法: {importance or '<empty>'}")
            issue_level = str(row.get("issue_level") or "").strip().lower()
            if issue_level not in {"blocking", "improvement"}:
                issue_level = "blocking" if importance == "high" else "improvement"

            key = (title, json.dumps(sources, ensure_ascii=False, sort_keys=True))
            if key in seen:
                continue
            seen.add(key)
            proposals.append(
                {
                    "title": title,
                    "category": str(row.get("category") or "").strip(),
                    "issue_focus": str(row.get("issue_focus") or "").strip(),
                    "expect_outcome": expect_outcome,
                    "sources": sources,
                    "issue_level": issue_level,
                    "importance": importance,
                    "reason": reason,
                    "proposed_by": "user",
                    "round": round_num,
                }
            )
            if len(proposals) >= max_items:
                break
        return proposals
