import json

from typing import Dict, List, Any, Optional
from agents.base import BaseAgent

class MediatorAgent(BaseAgent):
    name = "mediator"

    system_prompt = """你是需求調解主持人，負責主持需求討論會議。

核心職責：
1. 議程安排 — 分析需求與衝突，自動偵測問題並排定優先順序
2. 討論主持 — 決定討論模式（逐一發言/同時發言），維持討論秩序
3. 共識促成 — 綜合各方的不可讓步項與可讓步項，嘗試達成共識
4. 決策彙整 — 彙整每輪討論的決策並更新衝突標記

核心原則：
- 中立客觀 — 不偏袒任何利害關係人，不提出自己的技術觀點
- 忠於資料 — 只根據已有的分析結果和討論內容做出綜合判斷
- 無法共識時升級 — 無法達成共識時直接升級至人類裁決"""

    def __init__(self, model, tools: Optional[list] = None, registry=None):
        super().__init__(model, tools=tools, registry=registry)

    def generate_agenda(
        self, artifact: Dict[str, Any], registry=None,
        max_items: Optional[int] = None, skip_source_ids: Optional[set] = None,
    ) -> List[Dict]:
        limit = max_items
        exclude = {"mediator", "documentor"}
        if registry:
            registered = [n for n in registry.get_names() if n not in exclude]
        else:
            registered = ["user", "analyst", "expert", "modeler"]

        issues = self.detect_issues(artifact, skip_source_ids=skip_source_ids)
        if not issues:
            self.logger.info("未偵測到需要討論的問題")
            return []

        titles_and_descs = self.generate_topic_titles(issues)
        items = []
        for i, issue in enumerate(issues):
            td = titles_and_descs[i] if i < len(titles_and_descs) else {}
            raw_title = (td.get("title") or issue["description"]).strip()
            title = raw_title[:80] + ("..." if len(raw_title) > 80 else "")
            desc = td.get("description") or issue["description"]
            items.append({
                "issues": [issue],
                "summary": issue["description"],
                "title": title,
                "description": desc,
            })

        agenda_items = []
        for idx, cluster in enumerate(items, 1):
            score = self.compute_priority(cluster)
            category = self.classify(cluster)
            setup = self.decide_discussion_setup(cluster, category, registered)
            title = cluster.get("title", cluster.get("summary", "待討論議題"))
            description = cluster.get("description", cluster.get("summary", ""))

            source_ids = [issue["source_id"] for issue in cluster.get("issues", []) if issue.get("source_id")]
            agenda_items.append({
                "id": f"T-{idx:02d}",
                "title": title,
                "description": description,
                "category": category,
                "participants": setup["participants"],
                "discussion_mode": setup["discussion_mode"],
                "speaking_order": setup["speaking_order"],
                "priority_score": score,
                "source_ids": source_ids,
            })

        agenda_items.sort(key=lambda x: x["priority_score"], reverse=True)

        for idx, item in enumerate(agenda_items[:limit], 1):
            item["id"] = f"T-{idx:02d}"

        return agenda_items[:limit]

    def detect_issues(
        self, artifact: Dict[str, Any], skip_source_ids: Optional[set] = None
    ) -> List[Dict]:
        """從 artifact 偵測所有待處理的問題，對應六種議程類別"""
        issues = []
        skip = skip_source_ids or set()
        requirements = artifact.get("requirements", [])
        req_ids_in_models = set()
        for diagram in artifact.get("system_models", {}).get("models", []):
            for ref in diagram.get("requirement_refs", []):
                req_ids_in_models.add(ref)

        # 1. 衝突解決：未解決衝突
        for conflict in artifact.get("conflicts", []):
            if conflict.get("label") == "Conflict" and conflict.get("id", "") not in skip:
                stakeholders = list(conflict.get("texts", {}).keys()) or conflict.get("agents", []) or conflict.get("stakeholder_names", [])
                issues.append({
                    "type": "conflict",
                    "source_id": conflict.get("id", ""),
                    "description": conflict.get("description", ""),
                    "stakeholders": stakeholders,
                    "data": conflict,
                })

        # 2. 未回答 Open Question
        for oq in artifact.get("open_questions", []):
            oq_id = oq.get("id", oq.get("from_agent", ""))
            if oq.get("status") != "answered" and oq_id not in skip:
                issues.append({
                    "type": "open_question",
                    "source_id": oq_id,
                    "description": oq.get("question", ""),
                    "stakeholders": [],
                    "data": oq,
                })

        # 提出新需求：User / Expert / Modeler 可提出新功能、新限制、新例外情境
        stakeholder_names = {sh.get("name", "") for sh in artifact.get("stakeholders", [])}
        if stakeholder_names and "user_new_requirement" not in skip:
            issues.append({
                "type": "new_requirement",
                "source_id": "user_new_requirement",
                "description": "User 可提出新需求或補充需求（新功能、新限制、新例外情境），與既有需求一併納入討論。",
                "stakeholders": list(stakeholder_names),
                "data": {"from": "user"},
            })

        for req in requirements:
            rid = req.get("id", "")
            if rid in skip:
                continue
            text = req.get("text", "")
            rtype = req.get("type", "")
            source = req.get("source", "")

            # 提出新需求：User / Expert / Modeler 可提出新功能、新限制、新例外情境（expert 的 constraint、user 見上方）
            if source == "expert" or source == "modeler" or rtype == "constraint":
                issues.append({
                    "type": "new_requirement",
                    "source_id": rid,
                    "description": f"新增需求/約束 {rid}: {text}",
                    "stakeholders": req.get("source_stakeholders", []),
                    "data": req,
                })
                continue

            # 領域與合規檢查：需求涉及法規/合規/安全/隱私
            compliance_kw = ["法規", "合規", "GDPR", "CCPA", "隱私", "安全", "標準", "規範", "OWASP", "FSMA"]
            if any(kw in text for kw in compliance_kw):
                issues.append({
                    "type": "domain_compliance",
                    "source_id": rid,
                    "description": f"需求 {rid} 涉及領域/合規要求: {text}",
                    "stakeholders": req.get("source_stakeholders", []),
                    "data": req,
                })
                continue

            # 6. 取捨協商：NFR 可能互相競爭
            if rtype == "NFR":
                tradeoff_kw = ["效能", "性能", "可用性", "安全性", "擴展", "成本",
                               "performance", "availability", "security", "scalability"]
                if any(kw in text for kw in tradeoff_kw):
                    issues.append({
                        "type": "tradeoff",
                        "source_id": rid,
                        "description": f"NFR {rid} 可能涉及取捨: {text}",
                        "stakeholders": req.get("source_stakeholders", []),
                        "data": req,
                    })
                    continue

            # 7. 模型一致性與覆蓋：需求未被任何模型圖參照
            if req_ids_in_models and rid and rid not in req_ids_in_models:
                issues.append({
                    "type": "model_gap",
                    "source_id": rid,
                    "description": f"需求 {rid} 未被系統模型覆蓋: {text}",
                    "stakeholders": req.get("source_stakeholders", []),
                    "data": req,
                })

        return issues

    def generate_topic_titles(self, issues: List[Dict]) -> List[Dict]:
        """一次為多個 issue 產生簡短標題與一句描述，方便議程顯示"""
        if not issues:
            return []
        issues_text = json.dumps(
            [{"type": i["type"], "description": i["description"]} for i in issues],
            ensure_ascii=False,
            indent=2,
        )
        user_prompt = f"""# 任務
為以下每個問題各產生一個「簡短議程標題」與「一句描述」。

# 問題列表
{issues_text}

# 要求
- title：簡短好讀，約 10～20 字，能一眼看出討論重點，不要冗長或重複內文
- description：一句話說明需要討論與解決什麼（可略長，供議題說明用）

# 輸出 JSON
{{{{
    "items": [
        {{{{
            "title": "簡短標題",
            "description": "一句描述"
        }}}}
    ]
}}}}"""

        messages = self.build_direct_messages(user_prompt)
        try:
            response = self.model.chat_json(messages)
            items = response.get("items", [])
            return items[: len(issues)]
        except Exception:
            return []

    def compute_priority(self, cluster: Dict) -> float:
        """計算議題優先度分數"""
        type_weights = {
            "conflict": 2.5,
            "open_question": 2.5,
            "domain_compliance": 2.5,
            "new_requirement": 2.0,
            "tradeoff": 1.5,
            "model_gap": 1.5,
        }
        score = 0.0
        stakeholders_involved = set()

        for issue in cluster.get("issues", []):
            score += type_weights.get(issue["type"], 1.0)
            stakeholders_involved.update(issue.get("stakeholders", []))

        score *= (1 + len(stakeholders_involved) * 0.3)

        if len(cluster.get("issues", [])) > 1:
            score *= 1.2

        return round(score, 2)

    AGENDA_CATEGORIES = {
        "conflict_resolution": "衝突討論",
        "open_question": "開放問題討論",
        "new_requirement": "提出新需求",
        "tradeoff": "需求取捨（",
        "domain_compliance": "領域與合規檢查",
        "model_coverage": "模型一致性檢查",
    }

    def classify(self, cluster: Dict) -> str:
        types = {i["type"] for i in cluster.get("issues", [])}

        if "conflict" in types:
            return "conflict_resolution"
        if "open_question" in types:
            return "open_question"
        if "new_requirement" in types:
            return "new_requirement"
        if "tradeoff" in types:
            return "tradeoff"
        if "domain_compliance" in types:
            return "domain_compliance"
        if "model_gap" in types:
            return "model_coverage"

        return "new_requirement"

    def decide_discussion_setup(
        self, cluster: Dict, category: str, registered: List[str]
    ) -> Dict:
        """由 Mediator LLM 決定參與者、討論模式、發言順序。參與者只能從已註冊 agent 中挑選。"""
        issue_descriptions = "\n".join(
            f"- [{i['type']}] {i['description']}" for i in cluster.get("issues", [])
        )

        user_prompt = f"""# 任務
請根據以下議題資訊，決定：
1. 參與者（participants）：從「可用 agent」清單中挑選適合討論此議題的角色，只能使用清單內的 agent 名稱
2. 討論模式（discussion_mode）：sequential（逐一發言）或 simultaneous（同時發言）
3. 發言順序（speaking_order）：參與者的發言先後順序（僅 sequential 時有意義，但仍須提供）

# 議題類別
{category}

# 議題內容
{issue_descriptions}

# 可用 agent（參與者與發言順序僅能使用此清單內的名稱）
{json.dumps(registered, ensure_ascii=False)}

# 輸出 JSON
{{{{
    "participants": ["agent1", "agent2"],
    "discussion_mode": "sequential 或 simultaneous",
    "speaking_order": ["agent1", "agent2"]
}}}}"""

        messages = self.build_direct_messages(user_prompt)
        response = self.model.chat_json(messages)

        participants = [p for p in response.get("participants", registered) if p in registered]
        if not participants:
            participants = registered

        mode = response.get("discussion_mode", "sequential")
        if mode not in ("sequential", "simultaneous"):
            mode = "sequential"

        order = [p for p in response.get("speaking_order", participants) if p in participants]
        if set(order) != set(participants):
            order = participants

        return {
            "participants": participants,
            "discussion_mode": mode,
            "speaking_order": order,
        }

    # ===== 討論主持 =====

    def moderate_sequential(self, topic: Dict, registry) -> List[Dict]:
        contributions = []
        speaking_order = topic.get("speaking_order", topic.get("participants", []))
        self.logger.info(f"[{topic['id']}] 逐一發言: {' → '.join(speaking_order)}")

        for agent_name in speaking_order:
            agent = registry.get(agent_name)
            if not agent:
                self.logger.warning(f"Agent '{agent_name}' 未註冊，跳過")
                continue
            try:
                response = agent.respond_to_topic(topic, previous_responses=contributions)
                contributions.append({
                    "agent": agent_name,
                    "response": response if isinstance(response, dict) else {"content": str(response)},
                })
            except Exception as e:
                self.logger.warning(f"  {agent_name} 發言失敗: {e}")
                contributions.append({"agent": agent_name, "response": {"content": f"（發言失敗: {e}）"}})

        return contributions

    def moderate_simultaneous(self, topic: Dict, registry) -> List[Dict]:
        contributions = []
        participants = topic.get("participants", [])
        self.logger.info(f"[{topic['id']}] 同時發言: {', '.join(participants)}")

        for agent_name in participants:
            agent = registry.get(agent_name)
            if not agent:
                self.logger.warning(f"Agent '{agent_name}' 未註冊，跳過")
                continue
            try:
                response = agent.respond_to_topic(topic, previous_responses=None)
                contributions.append({
                    "agent": agent_name,
                    "response": response if isinstance(response, dict) else {"content": str(response)},
                })
            except Exception as e:
                self.logger.warning(f"  {agent_name} 發言失敗: {e}")
                contributions.append({"agent": agent_name, "response": {"content": f"（發言失敗: {e}）"}})

        return contributions

    # ===== Open Question 處理 =====

    def handle_open_questions(self, contributions: List[Dict], registry, stakeholders: List[Dict]) -> List[Dict]:
        """將 open_questions 依 to 欄位路由到對應 agent 回答"""
        oq_records = []

        all_questions = []
        for c in contributions:
            agent_name = c.get("agent", "")
            resp = c.get("response", {})
            for q in resp.get("open_questions", []):
                to_agent = q.get("to", "user")
                if to_agent == agent_name:
                    continue
                all_questions.append({
                    "from_agent": agent_name,
                    "to_agent": to_agent,
                    "question": q.get("question", ""),
                })

        for q_record in all_questions:
            if not q_record["question"]:
                continue

            target_name = q_record["to_agent"]
            target_agent = registry.get(target_name) if registry else None
            if target_agent:
                try:
                    q_topic = {
                        "id": "OQ",
                        "title": f"回答 {q_record['from_agent']} 的問題",
                        "description": (
                            f"{q_record['question']}\n\n"
                            "（請簡要針對此問題回答，若前面發言已涵蓋可寫「如前述」或只補充重點，勿整段重複相同內容。）"
                        ),
                    }
                    response = target_agent.respond_to_topic(q_topic, previous_responses=contributions)
                    resp = response if isinstance(response, dict) else {"content": str(response)}
                    resp = dict(resp)
                    resp["reply_to_question"] = q_record["question"]
                    resp["reply_to_agent"] = q_record["from_agent"]
                    contributions.append({
                        "agent": target_name,
                        "response": resp,
                        "is_reply": True,
                    })
                    answer = resp.get("statement") or resp.get("content", "")
                    oq_records.append({**q_record, "status": "answered", "answer": answer})
                except Exception:
                    oq_records.append({**q_record, "status": "deferred"})
            else:
                oq_records.append({**q_record, "status": "deferred"})

        return oq_records

    def generate_meeting_markdown(
        self, topic: Dict, contributions: List[Dict], resolution: Dict, round_num: int = 0
    ) -> str:
        mode = topic.get("discussion_mode", "sequential")
        participants = topic.get("participants", [])

        md = f"# {topic.get('title', '')}\n\n"
        md += f"- **Round**: {round_num}\n"
        summary = resolution.get("summary", "")
        decision = resolution.get("decision", "")
        md += f"- **Summary**: {summary}\n"
        if decision:
            md += f"- **Decision**: {decision}\n"
        md += f"- **Participants**: {', '.join(participants)}\n"
        md += f"- **Discussion mode**: {mode}\n\n"

        md += "## Participants content\n\n"
        for c in contributions:
            if c.get("is_reply", False):
                continue
            agent = c.get("agent", "?")
            resp = c.get("response", {})
            statement = resp.get("statement", "")
            md += f"### {agent}\n\n"
            if statement:
                md += f"{statement}\n\n"

        # ## Open Questions：以「提出者: 問題」與「回答者: 回答」格式列出
        oq_pairs = []
        for c in contributions:
            if not c.get("is_reply"):
                continue
            resp = c.get("response", {})
            question = resp.get("reply_to_question", "")
            from_agent = resp.get("reply_to_agent", "?")
            reply_agent = c.get("agent", "?")
            answer = resp.get("statement", "") or resp.get("content", "")
            if question or answer:
                oq_pairs.append((from_agent, question, reply_agent, answer))
        if oq_pairs:
            md += "## Open Questions\n\n"
            for from_agent, question, reply_agent, answer in oq_pairs:
                md += f"**{from_agent}**: {question}\n\n"
                md += f"**{reply_agent}**: {answer}\n\n"

        return md

    def synthesize_and_resolve(self, topic: Dict, contributions: List[Dict]) -> Dict:
        discussion_text = ""
        for c in contributions:
            agent = c.get("agent", "?")
            resp = c.get("response", {})
            statement = resp.get("statement", "")
            discussion_text += f"\n【{agent}】\n{statement}\n"

        user_prompt = f"""# 任務
綜合以下議題的討論結果，判斷是否達成共識。

# 議題資訊
標題: {topic.get('title', '')}
描述: {topic.get('description', '')}

# 各方討論內容
{discussion_text}

# 共識判斷標準（只有兩種）
- agreed: 各方發言立場一致或可整合，可直接形成決策
- unresolved: 各方發言立場衝突，無法自行解決，需升級至人類裁決

# 約束
- 如實反映各方立場，不要人為「製造」共識
- decision 必須具體可執行
- 若有發言立場互相衝突，一律判定為 unresolved

# 輸出 JSON
{{{{
    "resolution": "agreed 或 unresolved",
    "summary": "總結討論內容與結論（若 agreed 須含決策要點）",
    "decision": "具體決策內容（agreed 時填寫）"
}}}}"""

        messages = self.build_direct_messages(user_prompt)
        response = self.model.chat_json(messages)

        resolution = response.get("resolution", "unresolved")
        if resolution not in ("agreed", "unresolved"):
            resolution = "unresolved"

        return {
            "resolution": resolution,
            "summary": response.get("summary", ""),
            "decision": response.get("decision", "")
        }

    # ===== 人類裁決 =====

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
2. 另外設計 1 個折衷方案，結合各方可讓步的部分

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
        response = self.model.chat_json(messages)

        best = response.get("best_options", [])[:3]
        compromise = response.get("compromise", {})
        if compromise:
            compromise.setdefault("id", 4)

        return {"best_options": best, "compromise": compromise}

    # ===== 更新決策與衝突 =====

    def update_decisions(self, artifact: Dict[str, Any], round_discussions: List[Dict]) -> Dict:
        discussions_text = json.dumps(round_discussions, ensure_ascii=False, indent=2)
        conflicts_text = json.dumps(artifact.get("conflicts", []), ensure_ascii=False, indent=2)

        user_prompt = f"""# 任務
彙整本輪所有議程的討論決策，並更新衝突的 label。

# 本輪討論結果
{discussions_text}

# 當前衝突列表
{conflicts_text}

# 規則
- 若衝突已在本輪解決，將 label 改為 Neutral
- 未解決的衝突保持 label 為 Conflict

# 輸出 JSON
{{{{
    "new_decisions": [
        {{{{
            "id": "D-xx",
            "topic_id": "T-xx",
            "decision": "決策內容",
            "summary": "決策摘要"
        }}}}
    ],
    "conflicts": [
        {{{{
            "id": "CF-xx",
            "label": "Conflict 或 Neutral",
            "description": "...",
            "texts": {{}}
        }}}}
    ]
}}}}"""

        messages = self.build_direct_messages(user_prompt)
        response = self.model.chat_json(messages)

        return {
            "new_decisions": response.get("new_decisions", []),
            "conflicts": response.get("conflicts", artifact.get("conflicts", [])),
        }
