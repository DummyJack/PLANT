from typing import Dict, Any
from agents import Memory, AgentRegistry
from team import (
    UserAgent,
    AnalystAgent,
    ExpertAgent,
    MediatorAgent,
    ModelerAgent,
    DocumentorAgent,
)
from model import create_model
from store import Store
from utils import Logger, MoMManager, Collect


class Flow:
    def __init__(self, config: Dict[str, Any], store: Store, logger: Logger):
        self.config = config
        self.store = store
        self.logger = logger
        self.mom_manager = MoMManager()

        self.model = create_model(
            provider=config.get("provider"),
            model_name=config.get("model"),
            temperature=config.get("temperature"),
        )

        self.enable_reflection = config.get("enable_reflection", True)
        self.enable_agent_communication = config.get("enable_agent_communication", True)

        self.registry = AgentRegistry() if self.enable_agent_communication else None

        self.memories = {
            "user": Memory(self.model),
            "analyst": Memory(self.model),
            "expert": Memory(self.model),
            "mediator": Memory(self.model),
            "modeler": Memory(self.model),
            "documentor": Memory(self.model),
        }

        # 初始化 Agents
        self.user_agent = UserAgent(
            self.model, memory=self.memories["user"], registry=self.registry,
        )
        self.analyst_agent = AnalystAgent(
            self.model, memory=self.memories["analyst"], registry=self.registry,
        )
        if not self.enable_reflection:
            self.analyst_agent.reflection_criteria = ""

        self.expert_agent = ExpertAgent(
            self.model, memory=self.memories["expert"], registry=self.registry,
            doc_dir="doc", enable_web_search=config.get("enable_web_search", True),
        )
        if not self.enable_reflection:
            self.expert_agent.reflection_criteria = ""

        self.mediator_agent = MediatorAgent(
            self.model, memory=self.memories["mediator"], registry=self.registry,
        )
        self.modeler_agent = ModelerAgent(
            self.model, self.store, memory=self.memories["modeler"], registry=self.registry,
            plantuml_server=config.get("plantuml_server", "http://www.plantuml.com/plantuml"),
        )
        if not self.enable_reflection:
            self.modeler_agent.reflection_criteria = ""

        self.documentor_agent = DocumentorAgent(
            self.model, self.store, memory=self.memories["documentor"], registry=self.registry,
        )
        if not self.enable_reflection:
            self.documentor_agent.reflection_criteria = ""

        # 註冊到 Registry
        if self.registry:
            self.registry.register("user", self.user_agent, "利害關係人模擬專家")
            self.registry.register("analyst", self.analyst_agent, "需求分析師，負責衝突分析")
            self.registry.register("expert", self.expert_agent, "領域專家，提供法規/標準/最佳實務建議")
            self.registry.register("mediator", self.mediator_agent, "需求調解主持人，負責衝突報告、決策和草稿")
            self.registry.register("modeler", self.modeler_agent, "系統建模專家，負責 UML 模型")
            self.registry.register("documentor", self.documentor_agent, "文件撰寫專家，負責 SRS")

        self.logger.info(f"Agent 系統初始化完成")

    def summarize_memories(self, round_num: int):
        for memory in self.memories.values():
            if memory.messages:
                memory.summarize_round(round_num)

    def run(self, rough_idea: str) -> Dict[str, Any]:
        rounds = self.config.get("rounds", 1)
        start_round = self.config.get("start_round", 1)

        artifact = {
            "rough_idea": rough_idea,
            "project_goal": "",
            "proposed_stakeholders": [],
            "stakeholders": [],
            "analyse": [],
            "reports": [],
            "feedback": [],
            "options": [],
            "decisions": [],
        }

        self.store.save_artifact(artifact)

        # Phase 0: 建立專案目標
        self.logger.info("Phase 0: 建立專案目標")
        project_goal = self.mediator_agent.establish_project_goal(rough_idea)
        artifact["project_goal"] = project_goal
        self.store.save_artifact(artifact)
        self.logger.info(f"✓ 專案目標: {project_goal}")

        for round_num in range(start_round, rounds + 1):
            self.logger.info(f"Round {round_num}/{rounds}")
            self.mom_manager.start_round(round_num)
            artifact = self.run_flow(artifact, round_num)
            self.summarize_memories(round_num)
            self.logger.info(f"Round {round_num} 完成\n")

        self.generate_srs(artifact)
        self.logger.info("流程完成！")
        return artifact

    def run_continue(self, existing_artifact: Dict[str, Any]) -> Dict[str, Any]:
        rounds = self.config.get("rounds", 1)
        start_round = self.config.get("start_round", 1)
        artifact = existing_artifact

        if not artifact.get("project_goal"):
            self.logger.info("Phase 0: 補建專案目標")
            rough_idea = artifact.get("rough_idea", "")
            if rough_idea:
                artifact["project_goal"] = self.mediator_agent.establish_project_goal(rough_idea)
                self.store.save_artifact(artifact)

        self.logger.info(f"繼續現有專案，從 Round {start_round} 開始")

        for round_num in range(start_round, rounds + 1):
            self.logger.info(f"Round {round_num}/{rounds}")
            self.mom_manager.start_round(round_num)
            artifact = self.run_flow(artifact, round_num)
            self.summarize_memories(round_num)
            self.logger.info(f"Round {round_num} 完成\n")

        self.generate_srs(artifact)
        self.logger.info("流程完成！")
        return artifact

    def run_flow(self, artifact: Dict[str, Any], round_num: int) -> Dict[str, Any]:
        if round_num == 1:
            return self.run_discovery_round(artifact, round_num)
        else:
            return self.run_discussion_round(artifact, round_num)

    # Round 1

    def run_discovery_round(self, artifact: Dict[str, Any], round_num: int) -> Dict[str, Any]:
        rough_idea = artifact["rough_idea"]

        # Stage 1-2: 利害關係人
        if self.config.get("enable_user", True):
            self.logger.info("Stage 1: 產生利害關係人")
            proposed = self.user_agent.propose_stakeholders(rough_idea)
            artifact["proposed_stakeholders"] = proposed
            self.store.save_artifact(artifact)
            self.mom_manager.add_stage("產生利害關係人", "User", f"建議 {len(proposed)} 位", outputs={"proposed_stakeholders": proposed})

            self.logger.info("請選擇利害關係人")
            selected_indices = Collect.user_selection(proposed)
            selected = [proposed[i]["name"] for i in selected_indices]
            print()
            self.logger.info(f"✓ 已選擇 {len(selected)} 位利害關係人")
            self.mom_manager.add_stage("人類決策", "Human", f"選擇 {len(selected)} 位", outputs={"selected": selected})

            self.logger.info("Stage 2: 利害關係人提出需求")
            stakeholders = self.user_agent.generate_stakeholder_requirements(rough_idea, selected)
            artifact["stakeholders"] = stakeholders
            self.store.save_artifact(artifact)
            self.logger.info(f"✓ 產生 {len(stakeholders)} 位利害關係人需求")
            self.mom_manager.add_stage("利害關係人提出需求", "User", f"{len(stakeholders)} 位", outputs={"stakeholders": stakeholders})
        else:
            selected = [sh["name"] for sh in artifact.get("stakeholders", [])]
            stakeholders = artifact.get("stakeholders", [])

        # Stage 3: 衝突分析
        conflict_groups = []
        if self.config.get("enable_analyst", True):
            self.logger.info("Stage 3: 衝突分析")
            groups = self.analyst_agent.analyze_groups(stakeholders)
            artifact["analyse"] = groups
            conflict_groups = [g for g in groups if g["label"] == "Conflict"]
            self.logger.info(f"✓ 識別出 {len(conflict_groups)} 個衝突")
            self.store.save_artifact(artifact)
            self.mom_manager.add_stage("衝突分析", "Analyst", f"{len(conflict_groups)} 個衝突", outputs={"analyse": groups})
        else:
            conflict_groups = [g for g in artifact.get("analyse", []) if isinstance(g, dict) and g.get("label") == "Conflict"]

        # Stage 4: 衝突報告
        report = []
        if self.config.get("enable_mediator", True) and conflict_groups:
            self.logger.info("Stage 4: 產生衝突報告")
            report = self.mediator_agent.generate_conflict_report(conflict_groups)
            artifact["reports"] = report
            self.store.save_artifact(artifact)

            report_md = self.store.generate_report_markdown(report)
            self.store.save_markdown(report_md, "report.md")
            self.mom_manager.add_stage("產生衝突報告", "Mediator", f"{len(report)} 份", outputs={"report": report})
        elif not conflict_groups:
            self.logger.info("Stage 4: 無衝突，跳過")
            report = artifact.get("reports", [])

        # Stage 5: 專家建議
        feedback = []
        if self.config.get("enable_expert", True):
            self.logger.info("Stage 5: 專家提供建議")
            feedback = self.expert_agent.provide_feedback(report, rough_idea)
            artifact["feedback"] = feedback
            self.store.save_artifact(artifact)
            self.mom_manager.add_stage("專家提供建議", "Expert", f"{len(feedback)} 則", outputs={"feedback": feedback})

        # Stage 6: 決策
        decisions = []
        if self.config.get("enable_mediator", True) and report:
            self.logger.info("Stage 6: 產生決策選項")
            decision_options = self.mediator_agent.generate_decision_options(report, feedback)
            artifact["options"] = decision_options
            self.store.save_artifact(artifact)
            self.mom_manager.add_stage("產生決策選項", "Mediator", f"{len(decision_options)} 組")

            self.logger.info("請進行衝突裁決：")
            for option in decision_options:
                decision = Collect.user_decision(option)
                decisions.append(decision)
                self.mom_manager.add_stage("人類決策", "Human", f"{decision['conflict_title']}", outputs=decision)
                self.mom_manager.add_conflict_resolution(decision["conflict_title"], decision["decision"], decision["rationale"])

            for dec in decisions:
                dec["round"] = round_num
            if "all_decisions" not in artifact:
                artifact["all_decisions"] = []
            artifact["all_decisions"].extend(decisions)
            artifact["decisions"] = decisions
            self.store.save_artifact(artifact)
            self.logger.info(f"✓ 完成 {len(decisions)} 個決策")

        # Stage 7: 草稿
        if self.config.get("enable_mediator", True):
            self.logger.info("Stage 7: 產生需求草稿")
            spec_template = self.store.load_spec_template()
            draft_template = spec_template.get("draft", [])
            draft = self.mediator_agent.generate_draft(artifact, draft_template)
            self.store.save_draft(draft, round_num)

            draft_md = self.store.generate_draft_markdown(draft)
            self.store.save_markdown(draft_md, f"draft_{round_num}.md")
            self.logger.info(f"✓ 產生 draft_{round_num}.json")
            self.mom_manager.add_stage("產生需求草稿", "Mediator", "draft.json", outputs={"draft_generated": True})
        else:
            draft = self.store.load_draft()

        # Stage 8: UML
        if self.config.get("enable_modeler", True):
            self.logger.info("Stage 8: 建立系統模型")
            uml_data = self.modeler_agent.generate_system_model(draft)
            draft["uml"] = uml_data
            self.store.save_draft(draft, round_num)
            self.store.save_plantuml_files(uml_data)
            self.logger.info(f"✓ 系統模型已整合至 draft_{round_num}.json")
            self.mom_manager.add_stage("產生系統模型", "Modeler", f"draft_{round_num}.json", outputs={"model_generated": True})

        self.store.save_round_mom(self.mom_manager.get_current_round())
        return artifact

    # Round 2+

    def run_discussion_round(self, artifact: Dict[str, Any], round_num: int) -> Dict[str, Any]:
        project_goal = artifact.get("project_goal", "")

        prev_round = round_num - 1
        try:
            current_spec = self.store.load_json(self.store.artifact_dir / f"draft_{prev_round}.json")
        except FileNotFoundError:
            self.logger.warning(f"找不到 draft_{prev_round}.json，使用空 Spec")
            current_spec = {}

        previous_meetings = self.mom_manager.get_meetings()

        # Step 1: 生成議題
        self.logger.info("Step 1: Mediator 生成議題清單")
        topics = self.mediator_agent.generate_topics(current_spec, project_goal, previous_meetings)
        self.logger.info(f"✓ 生成 {len(topics)} 個議題")

        print(f"\n{'='*60}")
        print(f"Round {round_num} 議題清單")
        print(f"{'='*60}")
        for t in topics:
            mode_label = "逐一發言" if t["discussion_mode"] == "sequential" else "同時發言"
            print(f"  [{t['id']}] {t['title']} ({t['type']}) — {mode_label}")
        print(f"{'='*60}\n")

        # Step 2: 逐一討論
        all_resolutions = []
        for topic in topics:
            self.logger.info(f"討論議題 [{topic['id']}] {topic['title']}")

            if topic["discussion_mode"] == "sequential":
                contributions = self.mediator_agent.moderate_sequential(topic, self.registry)
            else:
                contributions = self.mediator_agent.moderate_simultaneous(topic, self.registry)

            result = self.mediator_agent.synthesize_and_resolve(topic, contributions)
            self.logger.info(f"  結果: {result['resolution']}")

            escalated_to_human = False

            # 升級路徑
            if result["resolution"] == "unresolved" or result.get("escalation_needed"):
                self.logger.info(f"  升級至 Expert 拘束性裁決")
                expert_ruling = self.expert_agent.provide_binding_ruling(topic, contributions)

                if expert_ruling.get("resolved"):
                    result = expert_ruling
                else:
                    self.logger.info(f"  Expert 無法裁決，升級至人類")
                    result = Collect.human_decision_on_topic(topic, contributions)
                    escalated_to_human = True

            self.mom_manager.add_meeting(round_num, topic, contributions, result, escalated_to_human)
            all_resolutions.append({"topic": topic, "resolution": result})

        # Step 3: 更新 Draft
        self.logger.info("Step 3: Mediator 更新 Draft")
        resolutions_context = []
        for r in all_resolutions:
            t, res = r["topic"], r["resolution"]
            resolutions_context.append({
                "topic_id": t.get("id", ""), "topic_title": t.get("title", ""),
                "decision": res.get("decision", ""), "summary": res.get("summary", ""),
            })

        artifact["decisions"] = resolutions_context
        if "all_decisions" not in artifact:
            artifact["all_decisions"] = []
        artifact["all_decisions"].extend(resolutions_context)

        spec_template = self.store.load_spec_template()
        draft_template = spec_template.get("draft", [])
        draft = self.mediator_agent.generate_draft(artifact, draft_template)
        self.store.save_draft(draft, round_num)

        draft_md = self.store.generate_draft_markdown(draft)
        self.store.save_markdown(draft_md, f"draft_{round_num}.md")
        self.logger.info(f"✓ 更新 draft_{round_num}.json")

        # Step 4: 更新 UML
        if self.config.get("enable_modeler", True):
            self.logger.info("Step 4: Modeler 更新 UML")
            draft["uml"] = current_spec.get("uml", {})
            uml_data = self.modeler_agent.refine_model(draft)
            draft["uml"] = uml_data
            self.store.save_draft(draft, round_num)
            self.store.save_plantuml_files(uml_data)

        self.store.save_artifact(artifact)
        self.store.save_round_mom(self.mom_manager.get_current_round())
        return artifact

    # 最終: SRS

    def generate_srs(self, artifact: Dict[str, Any]):
        if not self.config.get("enable_documentor", True):
            return

        self.logger.info("最終階段: 產生文件")

        dr_md = self.documentor_agent.generate_design_rationale(self.mom_manager.get_mom_data())
        self.store.save_markdown(dr_md, "dr.md")

        import glob
        draft_files = glob.glob(str(self.store.artifact_dir / "draft_*.json"))
        if draft_files:
            latest_draft_file = max(draft_files, key=lambda x: int(x.split('_')[-1].split('.')[0]))
            draft = self.store.load_json(latest_draft_file)
        else:
            self.logger.warning("未找到 draft 文件")
            draft = {}

        uml = draft.get("uml", {})
        spec_template = self.store.load_spec_template()
        ieee_template = spec_template.get("ieee_29148")

        srs_json = self.documentor_agent.generate_srs_json(draft, uml, ieee_template)
        self.store.save_srs(srs_json)

        srs_md = self.store.generate_srs_markdown(srs_json)
        self.store.save_markdown(srs_md, "srs.md")
        self.logger.info("✓ 產生 SRS")
