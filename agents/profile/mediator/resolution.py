# Mediator resolution logic: convergence checks and decision option analysis.
import json
from typing import Any, Dict, List, Optional

from agents.base import mediator_human_options_line


class MediatorResolution:
    def assess_discussion_convergence(
        self,
        topic: Dict,
        contributions: List[Dict],
    ) -> Dict[str, Any]:
        """討論結束後判斷各方意見是否已自然收斂（無需折衷方案即可形成決議）。"""
        main_contribs = [c for c in contributions if not c.get("is_reply", False)]
        if not main_contribs:
            return {"converged": False, "reason": "無發言"}
        discussion_text = ""
        for c in main_contribs:
            agent = c.get("agent", "?")
            statement = (c.get("response") or {}).get("statement", "")
            discussion_text += f"\n【{agent}】\n{statement}\n"

        user_prompt = f"""你是需求會議主持人。請判斷以下議題的討論是否已自然收斂——亦即各方意見大致一致、無明顯反對或重大分歧，可直接形成決議。

    # 議題
    標題: {topic.get('title', '')}
    描述: {topic.get('description', '')}

    # 各方發言
    {discussion_text}

    # 判斷標準
    - 若所有（或絕大多數）發言者觀點一致、無人提出反對或重要保留，判定為「收斂」。
    - 若有明確分歧、互相矛盾的立場、或有人提出重要但未被回應的疑慮，判定為「未收斂」。

    # 輸出 JSON
    {{
      "converged": true 或 false,
      "reason": "一句說明為何收斂/未收斂",
      "summary": "若收斂，簡述共識內容；若未收斂則空字串",
      "decision": "若收斂，寫出可作為決策的具體內容；若未收斂則空字串"
    }}
    只輸出 JSON。"""
        messages = self.build_direct_messages(user_prompt)
        try:
            data = self.chat_json(messages)
            return {
                "converged": bool(data.get("converged")),
                "reason": (data.get("reason") or "").strip(),
                "summary": (data.get("summary") or "").strip(),
                "decision": (data.get("decision") or "").strip(),
            }
        except Exception as e:
            self.logger.warning("收斂判斷失敗: %s", e)
            return {"converged": False, "reason": str(e)}

    def build_converged_resolution(
        self,
        topic: Dict,
        contributions: List[Dict],
        convergence: Dict[str, Any],
    ) -> Dict[str, Any]:
        """討論已自然收斂時，直接產出 agreed resolution（無需折衷方案與投票）。"""
        summary = convergence.get("summary") or "討論各方意見一致，已自然收斂。"
        decision = convergence.get("decision") or summary
        affected_conflict_ids = [
            sid for sid in (topic.get("source_ids") or [])
            if isinstance(sid, str)
            and (sid.startswith("CF-") or sid.startswith("CF-D") or sid.startswith("NF-"))
        ]
        affected_requirement_ids = [
            sid for sid in (topic.get("source_ids") or [])
            if isinstance(sid, str)
            and sid.startswith(("REQ-", "FR-", "NFR-", "R-", "ELICIT-"))
        ]
        return self.build_topic_result(
            resolution_status="agreed",
            summary=summary,
            decision=decision,
            mediator_compromise={"title": "", "description": "", "rationale": ""},
            agreed_points=[decision] if decision else [summary],
            unresolved_points=[],
            new_open_questions=[],
            affected_conflict_ids=affected_conflict_ids,
            affected_requirement_ids=affected_requirement_ids,
            needs_approval=bool(affected_requirement_ids),
            needs_human=False,
        )

    def analyze_decision_options(
        self,
        topic: Dict,
        contributions: List[Dict],
    ) -> Dict[str, Any]:
        """將未收斂議題整理為可供人類裁決的決策選項，不由 agents 投票定案。"""
        main_contribs = [c for c in contributions if not c.get("is_reply", False)]
        discussion_text = ""
        for c in main_contribs:
            agent = c.get("agent", "?")
            statement = (c.get("response") or {}).get("statement", "")
            discussion_text += f"\n【{agent}】\n{statement}\n"

        user_prompt = f"""# 任務
    你是需求分析協調者。請把以下尚未自然收斂的議題整理成「需要人類裁決的決策分析」。
    不要替人類做最終決策，也不要模擬投票。你只能提出選項、影響與建議。

    # 議題
    標題: {topic.get("title", "")}
    描述: {topic.get("description", "")}

    # 各方發言
    {discussion_text or "（無發言紀錄）"}

    # 要求
    - options 請列 2-4 個可執行方案；若只有一個合理方案，也至少提供「採用」與「暫緩」兩種選項。
    - 每個 option 必須包含 pros、cons、impact、risk。
    - recommendation 只能是建議，不代表已決議；最後由人類裁決，不交給 user agent。
    - affected_requirement_ids 優先使用議題 source_ids 中的需求 id；若沒有，回空陣列。
    - 請以繁體中文撰寫。

    # 輸出 JSON
    {{
      "summary": "此議題需要決策的原因",
      "options": [
        {{
          "id": "A",
          "summary": "方案摘要",
          "pros": ["優點"],
          "cons": ["缺點"],
          "impact": ["對需求、範圍、驗收或設計的影響"],
          "risk": "low | medium | high"
        }}
      ],
      "recommendation": {{
        "option_id": "A",
        "rationale": "為何建議此方案",
        "confidence": "low | medium | high",
        "needs_human": true
      }},
      "affected_requirement_ids": ["REQ-01"],
      "unresolved_points": ["需要人類裁決的事項"]
    }}
    只輸出 JSON。"""
        messages = self.build_direct_messages(user_prompt)
        try:
            response = self.chat_json(messages)
        except Exception as e:
            self.logger.warning("決策選項分析失敗: %s", e)
            response = {}

        source_req_ids = [
            sid for sid in (topic.get("source_ids") or [])
            if isinstance(sid, str) and sid.startswith(("REQ-", "FR-", "NFR-", "R-", "ELICIT-"))
        ]
        options = response.get("options", [])
        if not isinstance(options, list):
            options = []
        clean_options = []
        for idx, option in enumerate(options, 1):
            if not isinstance(option, dict):
                continue
            oid = str(option.get("id") or chr(64 + idx)).strip() or chr(64 + idx)
            summary = str(option.get("summary") or "").strip()
            if not summary:
                continue
            clean_options.append(
                {
                    "id": oid,
                    "summary": summary,
                    "pros": [str(x).strip() for x in (option.get("pros") or []) if str(x).strip()],
                    "cons": [str(x).strip() for x in (option.get("cons") or []) if str(x).strip()],
                    "impact": [str(x).strip() for x in (option.get("impact") or []) if str(x).strip()],
                    "risk": str(option.get("risk") or "medium").strip().lower() or "medium",
                }
            )
        if not clean_options:
            clean_options = [
                {
                    "id": "A",
                    "summary": "採用目前討論中最小可行需求範圍，並將細節留待人類裁決。",
                    "pros": ["可讓 SRS 繼續收斂"],
                    "cons": ["仍需要人類裁決具體邊界"],
                    "impact": ["需求內容可能需後續調整"],
                    "risk": "medium",
                },
                {
                    "id": "B",
                    "summary": "暫緩納入正式需求，列為待確認事項。",
                    "pros": ["避免未確認內容進入正式 SRS"],
                    "cons": ["SRS 會保留未決問題"],
                    "impact": ["相關需求暫不 baseline"],
                    "risk": "low",
                },
            ]

        recommendation = response.get("recommendation", {})
        if not isinstance(recommendation, dict):
            recommendation = {}
        option_ids = {row["id"] for row in clean_options}
        rec_option = str(recommendation.get("option_id") or clean_options[0]["id"]).strip()
        if rec_option not in option_ids:
            rec_option = clean_options[0]["id"]
        confidence = str(recommendation.get("confidence") or "medium").strip().lower()
        if confidence not in {"low", "medium", "high"}:
            confidence = "medium"

        affected_requirement_ids = response.get("affected_requirement_ids", [])
        if not isinstance(affected_requirement_ids, list) or not affected_requirement_ids:
            affected_requirement_ids = source_req_ids

        unresolved_points = response.get("unresolved_points", [])
        if not isinstance(unresolved_points, list):
            unresolved_points = []

        return {
            "summary": str(response.get("summary") or "此議題需要人類裁決後才能成為正式需求決策。").strip(),
            "options": clean_options,
            "recommendation": {
                "option_id": rec_option,
                "rationale": str(recommendation.get("rationale") or "").strip(),
                "confidence": confidence,
                "needs_human": True,
            },
            "affected_requirement_ids": [
                str(x).strip() for x in affected_requirement_ids if str(x).strip()
            ],
            "unresolved_points": [
                str(x).strip() for x in unresolved_points if str(x).strip()
            ] or ["需要人類裁決採用哪個方案。"],
        }

    def prepare_human_options(self, topic: Dict, contributions: List[Dict]) -> Dict:
        discussion_text = ""
        for c in contributions:
            agent = c.get("agent", "?")
            resp = c.get("response", {})
            statement = resp.get("statement", "")
            discussion_text += f"\n【{agent}】\n{statement}\n"

        user_prompt = f"""# 任務
    從以下議題討論中，篩選出 3 個最佳方案和 1 個折衷方案，供人類做最終裁決。

    # 議題資訊
    標題: {topic.get('title', '')}
    描述: {topic.get('description', '')}

    # 各方討論內容
    {discussion_text}

    # 要求
    1. 從討論中提取 3 個最具體、可行性最高的方案
    2. 另外設計 1 個折衷方案，整合各方願意放寬或調整的面向（描述時無須使用「可讓步」等字眼）
    3. {mediator_human_options_line()}

    # 輸出 JSON
    {{{{
    "best_options": [
        {{{{
            "id": 1,
            "title": "方案標題",
            "description": "方案內容",
            "source": "提出此方案的 agent 名稱"
        }}}},
        {{{{
            "id": 2,
            "title": "方案標題",
            "description": "方案內容",
            "source": "提出此方案的 agent 名稱"
        }}}},
        {{{{
            "id": 3,
            "title": "方案標題",
            "description": "方案內容",
            "source": "提出此方案的 agent 名稱"
        }}}}
    ],
    "compromise": {{{{
        "id": 4,
        "title": "折衷方案標題",
        "description": "折衷方案內容",
        "rationale": "為何此方案能平衡各方需求"
    }}}}
    }}}}"""

        messages = self.build_direct_messages(user_prompt)
        response = self.chat_json(messages)

        best = response.get("best_options", [])
        compromise = response.get("compromise", {})
        if compromise:
            compromise.setdefault("id", 4)

        return {"best_options": best, "compromise": compromise}
