from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Dict, Any
from agents import AgentRegistry
from agents.coordinator import BaseAgentCoordinator
from agents.planner import PlannerService
from agents.policy import AgentSkillToolPolicy
from agents.profile import (
    UserAgent,
    AnalystAgent,
    ExpertAgent,
    MediatorAgent,
    ModelerAgent,
    DocumentorAgent,
)
from agents.profile.mediator import AgendaRunner, AGENDA_CATEGORY_LABEL
from model import create_model
from store import Store
from utils import Logger, Collect
from agents.tool_registry import ToolRegistry


class Flow:
    def __init__(self, config: Dict[str, Any], store: Store, logger: Logger):
        self.config = config
        self.store = store
        self.logger = logger

        self.agent_models = {
            "user": self.build_agent_model("user"),
            "analyst": self.build_agent_model("analyst"),
            "expert": self.build_agent_model("expert"),
            "mediator": self.build_agent_model("mediator"),
            "modeler": self.build_agent_model("modeler"),
            "documentor": self.build_agent_model("documentor"),
        }

        self.registry = AgentRegistry()
        enable_agents = config.get("enable_agents") or {}
        self.policy = AgentSkillToolPolicy()
        self.tool_registry = ToolRegistry(config=self.config, policy=self.policy)
        self.planner = PlannerService(policy=self.policy)
        self.coordinator = BaseAgentCoordinator(planner=self.planner)

        analyst_tools = self.tool_registry.build_tools_for_agent("analyst")
        expert_tools = self.tool_registry.build_tools_for_agent("expert")
        modeler_tools = self.tool_registry.build_tools_for_agent("modeler")
        documentor_tools = self.tool_registry.build_tools_for_agent("documentor")

        self.user_agent = UserAgent(
            self.agent_models["user"], registry=self.registry
        )
        self.analyst_agent = AnalystAgent(
            self.agent_models["analyst"], tools=analyst_tools, registry=self.registry
        )
        self.expert_agent = ExpertAgent(
            self.agent_models["expert"],
            tools=expert_tools,
            registry=self.registry,
            doc_dir="doc",
        )
        self.mediator_agent = MediatorAgent(
            self.agent_models["mediator"], registry=self.registry
        )
        self.modeler_agent = ModelerAgent(
            self.agent_models["modeler"], tools=modeler_tools, registry=self.registry
        )
        self.documentor_agent = DocumentorAgent(
            self.agent_models["documentor"],
            self.store,
            tools=documentor_tools,
            registry=self.registry,
        )

        # policy 強制：固定 analyst/expert/modeler/documentor 的 skill/tool 指派
        self.policy.validate_agent_assignment(
            "analyst", self.analyst_agent.skill_names, list(self.analyst_agent.tools.keys())
        )
        self.policy.validate_agent_assignment(
            "expert", self.expert_agent.skill_names, list(self.expert_agent.tools.keys())
        )
        self.policy.validate_agent_assignment(
            "modeler", self.modeler_agent.skill_names, list(self.modeler_agent.tools.keys())
        )
        self.policy.validate_agent_assignment(
            "documentor", self.documentor_agent.skill_names, list(self.documentor_agent.tools.keys())
        )

        tool_max = config.get("tool_call_max_rounds", 3)
        for name, agent in [
            ("user", self.user_agent),
            ("analyst", self.analyst_agent),
            ("expert", self.expert_agent),
            ("mediator", self.mediator_agent),
            ("modeler", self.modeler_agent),
            ("documentor", self.documentor_agent),
        ]:
            agent.tool_call_max_rounds = tool_max
            agent.low_confidence_threshold = config.get(
                "low_confidence_threshold", 0.7
            )
            agent.policy = self.policy
            if enable_agents.get(name, True):
                self.registry.register(name, agent)

        self.mediator_agent.enable_human_escalation = config.get(
            "enable_human_escalation", True
        )

        eat = config.get("enable_agenda_types")
        if isinstance(eat, dict):
            self.mediator_agent.enabled_agenda_type_ids = [
                k for k, v in eat.items() if v
            ]

    def build_agent_model(self, agent_name: str):
        am = self.config.get("agent_models") or {}
        default_cfg = am.get("default") or {}
        per_agent = am.get(agent_name) or default_cfg
        provider = per_agent.get("provider", self.config.get("provider"))
        model_name = per_agent.get("model", self.config.get("model"))
        temperature = per_agent.get("temperature", self.config.get("temperature"))
        max_tokens = per_agent.get("max_tokens")

        kwargs = {"temperature": temperature}
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        return create_model(provider=provider, model_name=model_name, **kwargs)

    def run(self, rough_idea: str) -> Dict[str, Any]:
        rounds = self.config.get("rounds", 1)
        now = datetime.now(timezone.utc).isoformat()
        artifact = {
            "rough_idea": rough_idea,
            "stakeholders": [],
            "scope": {"in_scope": [], "out_of_scope": [], "description": ""},
            "requirements": [],
            "conflicts": [],
            "feedback": {},
            "system_models": {},
            "discussions": [],
            "decisions": [],
            "open_questions": [],
            "meta": {"created_at": now, "updated_at": now, "last_round": 0},
        }

        self.store.save_artifact(artifact)

        planner_decision = self.coordinator.plan(
            task=rough_idea,
            context={
                "mode": "init_phase",
                "requirements_count": len(artifact.get("requirements", [])),
            },
        )
        artifact.setdefault("meta", {})["planner_decision_init"] = planner_decision

        self.logger.info("=== Phase 0: 初始草稿建立 ===")
        artifact = self.run_init_phase(artifact)

        # 開會前產出需求 Conflict 報告，供與會參考
        if artifact.get("conflicts"):
            self.logger.info("產出需求 Conflict 報告")
            conflict_md = self.analyst_agent.generate_conflict_report(
                artifact,
                round_num=0,
                recent_decisions_limit=self.config.get("agenda_items", 5),
            )
            self.store.save_markdown(conflict_md, "conflict_report.md")
            self.logger.info("  ✓ 已存 conflict_report.md")

        for round_num in range(1, rounds + 1):
            self.logger.info(f"=== Round {round_num}/{rounds}: 開會 ===")
            artifact = self.run_meeting_round(artifact, round_num)
            self.logger.info(f"Round {round_num} 完成\n")

        self.logger.info("=== 規格化 ===")
        self.finalize(artifact)

        self.logger.info("流程完成！")
        return artifact

    def run_continue(self, existing_artifact: Dict[str, Any]) -> Dict[str, Any]:
        artifact = existing_artifact
        artifact.setdefault(
            "scope", {"in_scope": [], "out_of_scope": [], "description": ""}
        )
        artifact.setdefault("feedback", {})
        artifact.setdefault("meta", {})
        self.user_agent.stakeholders = artifact.get("stakeholders", [])

        rounds = self.config.get("rounds", 1)
        start_round = len(artifact.get("discussions", [])) + 1
        self.logger.info(f"繼續現有專案，從 Round {start_round} 開始，共 {rounds} 輪")

        # 開會前產出需求 Conflict 報告，供與會參考
        if artifact.get("conflicts"):
            self.logger.info("產出需求 Conflict 報告")
            conflict_md = self.analyst_agent.generate_conflict_report(
                artifact,
                round_num=start_round - 1,
                recent_decisions_limit=self.config.get("agenda_items", 5),
            )
            self.store.save_markdown(conflict_md, "conflict_report.md")
            self.logger.info("  ✓ 已存 conflict_report.md")

        for round_num in range(start_round, start_round + rounds):
            self.logger.info(f"=== Round {round_num}: 開會 ===")
            artifact = self.run_meeting_round(artifact, round_num)
            self.logger.info(f"Round {round_num} 完成\n")

        self.logger.info("=== 規格化 ===")
        self.finalize(artifact)

        self.logger.info("流程完成！")
        return artifact

    # Phase 0: 初始草稿建立

    def run_init_phase(self, artifact: Dict[str, Any]) -> Dict[str, Any]:
        rough_idea = artifact["rough_idea"]

        self.logger.info("利害關係人識別與需求收集")
        proposed = self.user_agent.propose_stakeholders(rough_idea)

        self.logger.info("請選擇利害關係人")
        max_sh = self.config.get("max_stakeholders", 5)
        selected_indices = Collect.user_selection(proposed, max_select=max_sh)
        selected = [proposed[i]["name"] for i in selected_indices]
        print()
        self.logger.info(f"✓ 已選擇 {len(selected)} 位利害關係人")

        stakeholders = self.user_agent.generate_stakeholder_requirements(
            rough_idea, selected
        )
        artifact["stakeholders"] = stakeholders
        self.user_agent.stakeholders = stakeholders
        self.store.save_artifact(artifact)
        self.logger.info(f"✓ 產生 {len(stakeholders)} 位利害關係人需求")

        self.logger.info("Analyst 產出 scope")
        artifact["scope"] = self.analyst_agent.generate_scope(rough_idea, stakeholders)
        self.store.save_artifact(artifact)

        self.logger.info("Analyst 分析需求")
        analysis = self.analyst_agent.analyze_requirements(stakeholders)
        artifact["requirements"] = analysis["requirements"]
        self.store.save_artifact(artifact)

        self.logger.info("Analyst 執行 Conflict 辨識")
        artifact = self.analyst_agent.run_conflict_detection(artifact)
        self.store.save_artifact(artifact)

        self.logger.info("Expert 自主領域研究")
        mi = self.config.get("max_iterations") or {}
        review = self.expert_agent.run_review_loop(
            artifact,
            max_iterations=mi.get("expert_phase0", 10),
        )
        self.store.save_artifact(artifact)
        review_actions = review.get("actions_taken", [])
        review_issues = review.get("pending_issues", [])
        dr = artifact.get("feedback", {}).get("domain_research") or {}
        if dr and isinstance(dr, dict) and dr:
            self.logger.info(
                f"✓ 領域研究完成（{len(review_actions)} 步驟）"
            )
        else:
            self.logger.info("領域研究循環完成但無研究結果寫入")
        if review_issues:
            for issue in review_issues:
                artifact.setdefault("open_questions", []).append({
                    "from_agent": "expert",
                    "question": issue.get("description", ""),
                    "status": "pending",
                    "type": issue.get("type", "compliance_risk"),
                })
            self.logger.info(
                f"  Expert 標記了 {len(review_issues)} 個合規風險"
                "（加入 open_questions）"
            )

        self.logger.info("Modeler 初步建模")
        mi = self.config.get("max_iterations") or {}
        model_data = self.modeler_agent.generate_system_model(
            artifact["requirements"],
            artifact["stakeholders"],
            max_iterations=mi.get("modeler_phase0", 15),
        )
        artifact["system_models"] = model_data
        self.store.save_artifact(artifact)
        model_count = len(model_data.get("models", []))
        self.logger.info(f"  ✓ 產生 {model_count} 張 UML 圖")
        self.store.save_plantuml_files(model_data)

        self.logger.info("Analyst 草稿化")
        draft_md = self.analyst_agent.create_draft(
            artifact,
            draft_version=0,
            recent_decisions_limit=self.config.get("agenda_items", 5),
        )
        self.store.save_draft(draft_md, version=0)
        self.logger.info(
            f"✓ Draft v0: {len(artifact['requirements'])} 條需求，{len(artifact.get('conflicts', []))} 個 Conflict"
        )

        # Expert/Modeler 產出後，Analyst 再判斷一次並打信心分；信心低則加入討論
        self.logger.info("Analyst 對 Conflict 再判斷並打信心分")
        artifact = self.analyst_agent.assign_conflict_confidence(artifact)
        lc_threshold = self.config.get("low_confidence_threshold", 0.7)
        low_conf = [
            c for c in artifact.get("conflicts", [])
            if c.get("label") == "Conflict"
            and isinstance(c.get("confidence"), (int, float))
            and c["confidence"] < lc_threshold
        ]
        low_conf_neutrals = [
            c for c in artifact.get("conflicts", [])
            if c.get("label") == "Neutral"
            and isinstance(c.get("confidence"), (int, float))
            and c["confidence"] < lc_threshold
        ]
        if low_conf:
            for c in low_conf:
                amb = c.get("ambiguous_requirements", [])
                desc = (
                    f"Conflict {c['id']} 信心度低（{c.get('confidence', '?')}）"
                    f"：{c.get('description', '')}"
                )
                if amb:
                    desc += f"（涉及模糊需求: {', '.join(amb)}）"
                artifact.setdefault("open_questions", []).append({
                    "from_agent": "analyst",
                    "question": desc,
                    "status": "pending",
                    "type": "low_confidence_conflict",
                    "related_conflict_id": c["id"],
                })
            self.logger.info(
                f"  {len(low_conf)} 個低信心 Conflict 加入 open_questions，將進入討論"
            )
        if low_conf_neutrals:
            for c in low_conf_neutrals:
                amb = c.get("ambiguous_requirements", [])
                desc = (
                    f"Neutral {c['id']} 信心度低（{c.get('confidence', '?')}）"
                    f"，可能遺漏 Conflict：{c.get('description', '')[:80]}"
                )
                if amb:
                    desc += f"（涉及模糊需求: {', '.join(amb)}）"
                artifact.setdefault("open_questions", []).append({
                    "from_agent": "analyst",
                    "question": desc,
                    "status": "pending",
                    "type": "low_confidence_neutral",
                    "related_neutral_id": c["id"],
                })
            self.logger.info(
                f"  {len(low_conf_neutrals)} 個低信心 Neutral 加入 open_questions，將進入討論"
            )
        if low_conf or low_conf_neutrals:
            self.store.save_artifact(artifact)

        meta = artifact.setdefault("meta", {})
        meta["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.store.save_artifact(artifact)

        return artifact

    # Round k: 開會

    def run_meeting_round(
        self, artifact: Dict[str, Any], round_num: int
    ) -> Dict[str, Any]:
        # 讀取前一輪草稿，讓本輪基於前一版草稿
        prev_version = round_num - 1
        prev_draft_md = self.store.load_draft(prev_version)
        if prev_draft_md:
            self.logger.info(f"載入 draft_v{prev_version}.md 作為本輪基礎")

        # 議程由 Mediator Agent 驅動（產生議程、討論、綜合、人類裁決、存檔）
        self.logger.info("議程由 Mediator Agent 驅動")
        planner_decision = self.coordinator.plan(
            task=f"meeting_round_{round_num}",
            context={
                "mode": "meeting_round",
                "round_num": round_num,
                "open_questions": len(artifact.get("open_questions", [])),
                "conflicts": len(artifact.get("conflicts", [])),
            },
        )
        artifact.setdefault("meta", {}).setdefault("planner_round_decisions", []).append(
            {"round": round_num, **planner_decision}
        )
        runner = AgendaRunner(
            self.mediator_agent,
            self.registry,
            artifact,
            round_num,
            self.config,
            self.store,
            Collect,
            self.logger,
        )
        # 每輪先直接產出議程，再依 Mediator 決策逐項討論（省去一次「發現 topics 空就選 generate_agenda」的 LLM 呼叫）
        obs = runner.run("generate_agenda", None)
        if obs.get("error"):
            self.logger.warning(f"  產出議程: {obs['error']}")
        observation = None
        while True:
            state = runner.get_state_summary()
            decision = self.mediator_agent.decide_next_agenda_action(state, observation)
            action = decision.get("action", "finish_round")
            params = decision.get("params") or {}
            self.logger.info(
                f"  Agent 決策: {action} {params} — {decision.get('reasoning', '')}"
            )
            if action == "finish_round":
                break
            observation = runner.run(action, params)
            if observation.get("error"):
                self.logger.warning(f"  執行層: {observation['error']}")
        round_discussions = runner.get_round_discussions()
        all_open_questions = runner.get_all_open_questions()
        agenda_snapshot = runner.get_agenda_snapshot()
        if agenda_snapshot:
            print(f"\n{'='*60}\nRound {round_num} 議程\n{'='*60}")
            for t in agenda_snapshot:
                cat_label = AGENDA_CATEGORY_LABEL.get(t.get("category", ""), t.get("category", ""))
                print(
                    f"  [{t['id']}] {t['title']} ({t.get('discussion_mode', 'sequential')}) [{cat_label}]"
                )
            print(f"{'='*60}\n")

        # 記錄討論歷史（含本輪議程快照、open_questions 帶 topic_id）
        artifact.setdefault("discussions", []).append(
            {
                "round": round_num,
                "topics": round_discussions,
                "agenda_snapshot": agenda_snapshot,
            }
        )

        # 更新 open_questions（含回答結果寫進 artifact）
        existing_oq = artifact.get("open_questions", [])
        for oq in all_open_questions:
            oq["round"] = round_num
        artifact["open_questions"] = existing_oq + all_open_questions
        self.store.save_artifact(artifact)

        # Step 5.1: Mediator 更新決策與 Conflict（含討論中提出的新增 Conflict，可補辨識漏報）
        self.logger.info("Step 5.1: Mediator 更新決策與 Conflict")
        prev_conflicts_by_id = {
            c.get("id"): c for c in artifact.get("conflicts", []) if c.get("id")
        }
        updates = self.mediator_agent.update_decisions(artifact, round_discussions)
        new_decisions = updates.get("new_decisions", [])
        # 為本輪新決策指派 id（D-01, D-02, ...），供 resolved_by_decision_id 對應
        existing_ids = [
            d.get("id") for d in artifact.get("decisions", [])
            if isinstance(d.get("id"), str) and d["id"].startswith("D-")
        ]
        max_d = 0
        for eid in existing_ids:
            try:
                max_d = max(max_d, int(eid[2:].lstrip("-")))
            except ValueError:
                pass
        for i, d in enumerate(new_decisions):
            if not d.get("id"):
                d = dict(d)
                d["id"] = f"D-{max_d + i + 1:02d}"
                new_decisions[i] = d
        artifact["decisions"].extend(new_decisions)
        new_conflicts = list(updates.get("conflicts", artifact["conflicts"]))
        # 討論中提出的新增 Conflict（漏報補正）：指派 id 後併入；conflict_type 可為 8 類或模型自訂
        for nc in updates.get("new_conflicts", []):
            if not nc.get("description"):
                continue
            max_num = 0
            for c in new_conflicts:
                cid = c.get("id") or ""
                if cid.startswith("CF-") and not cid.startswith("CF-D"):
                    try:
                        max_num = max(max_num, int(cid[3:]))
                    except ValueError:
                        pass
            ctype = (nc.get("conflict_type") or "").strip()
            new_conflicts.append(
                {
                    "id": f"CF-{max_num + 1:02d}",
                    "label": "Conflict",
                    "description": nc.get("description", ""),
                    "conflict_type": ctype,
                    "requirement_ids": nc.get("requirement_ids", []),
                }
            )
        # 決策 ↔ Conflict 對應：依 resolved_conflict_ids 寫入 resolved_by_decision_id
        cf_to_decision = {}
        for d in new_decisions:
            did = d.get("id")
            for cf_id in d.get("resolved_conflict_ids", []):
                if cf_id:
                    cf_to_decision[cf_id] = did
        for c in new_conflicts:
            if c.get("label") == "Neutral" and c.get("id"):
                c.setdefault("resolved_by_decision_id", cf_to_decision.get(c["id"]))
            orig = prev_conflicts_by_id.get(c.get("id"))
            if orig:
                if orig.get("requirement_ids") is not None:
                    c.setdefault("requirement_ids", orig["requirement_ids"])
                if orig.get("conflict_type") and c.get("label") == "Conflict":
                    c.setdefault("conflict_type", orig["conflict_type"])
                if orig.get("resolved_by_decision_id") and c.get("label") == "Neutral":
                    c.setdefault(
                        "resolved_by_decision_id", orig["resolved_by_decision_id"]
                    )
        artifact["conflicts"] = new_conflicts

        # Step 5.2: Analyst 更新需求草稿
        self.logger.info("Step 5.2: Analyst 更新需求草稿")
        draft = self.analyst_agent.update_draft(artifact)
        artifact["requirements"] = draft["requirements"]

        # Step 5.3: Modeler 更新系統模型
        self.logger.info("Step 5.3: Modeler 更新系統模型")
        prev_models = artifact.get("system_models", {}).get("models", [])

        if prev_models:
            model_data = self.modeler_agent.refine_model(
                artifact["requirements"],
                prev_models,
                stakeholders=artifact.get("stakeholders", []),
            )
        else:
            mi = self.config.get("max_iterations") or {}
            model_data = self.modeler_agent.generate_system_model(
                artifact["requirements"],
                artifact["stakeholders"],
                max_iterations=mi.get("modeler_phase0", 15),
            )

        artifact["system_models"] = model_data

        # Step 5.4: 產出 draft markdown（含系統模型）
        next_version = self.store.get_draft_version() + 1
        draft_md = self.analyst_agent.create_draft(
            artifact,
            draft_version=next_version,
            round_num=round_num,
            recent_decisions_limit=self.config.get("agenda_items", 5),
        )
        self.store.save_draft(draft_md, version=next_version)
        self.logger.info(f"  ✓ 已存 draft_v{next_version}.md")

        # Step 5.5: 只要有 Conflict 列表就產出需求 Conflict 報告（含已解決／未解決），每輪更新
        if artifact.get("conflicts"):
            self.logger.info("Step 5.5: 產出需求 Conflict 報告（Analyst，Markdown）")
            conflict_md = self.analyst_agent.generate_conflict_report(
                artifact,
                round_num,
                recent_decisions_limit=self.config.get("agenda_items", 5),
            )
            self.store.save_markdown(conflict_md, "conflict_report.md")
            self.logger.info("  ✓ 已存 conflict_report.md")
        else:
            self.logger.info("Step 5.5: 無 Conflict 資料，略過 conflict_report.md")

        meta = artifact.setdefault("meta", {})
        meta["updated_at"] = datetime.now(timezone.utc).isoformat()
        meta["last_round"] = round_num
        self.store.save_artifact(artifact)
        self.store.save_plantuml_files(model_data)

        return artifact

    # Finalization

    def finalize(self, artifact: Dict[str, Any]):
        self.logger.info("Step F1 & F2: 並行產生 Design Rationale 與 SRS")
        with ThreadPoolExecutor(max_workers=2) as executor:
            f_dr = executor.submit(
                self.documentor_agent.generate_design_rationale, artifact
            )
            f_srs = executor.submit(self.documentor_agent.generate_srs, artifact)
            dr_md = f_dr.result()
            srs_md = f_srs.result()

        self.store.save_markdown(dr_md, "design_rationale.md")
        self.logger.info("✓ 產生 design_rationale.md")
        self.store.save_markdown(srs_md, "srs.md")
        self.logger.info("✓ 產生 srs.md")

        cost_by_agent = {}
        for agent_name, model in self.agent_models.items():
            if not hasattr(model, "getCostSummary"):
                continue
            summary = model.getCostSummary()
            if summary:
                cost_by_agent[agent_name] = summary

        if cost_by_agent:
            total_input = sum(v.get("input_tokens", 0) for v in cost_by_agent.values())
            total_output = sum(v.get("output_tokens", 0) for v in cost_by_agent.values())
            total_tokens = sum(v.get("total_tokens", 0) for v in cost_by_agent.values())
            total_elapsed = sum(v.get("run_time", 0.0) for v in cost_by_agent.values())
            total_cost = sum(v.get("estimated_cost(USD)", 0.0) for v in cost_by_agent.values())
            cost_summary = {
                "project_id": self.store.project_id,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "agents": cost_by_agent,
                "totals": {
                    "input_tokens": total_input,
                    "output_tokens": total_output,
                    "total_tokens": total_tokens,
                    "run_time": round(total_elapsed, 4),
                    "estimated_cost(USD)": round(total_cost, 8),
                },
            }
            self.store.save_json(cost_summary, self.store.project_dir / "cost_summary.json")
            self.logger.info("✓ 已儲存 cost_summary.json")
        else:
            self.logger.info("模型無定價資訊，略過輸出 cost_summary.json")
