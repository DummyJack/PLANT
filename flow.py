from pathlib import Path
from typing import Dict, Any
from agents import AgentRegistry
from agents.profile import (
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

        self.enable_agent_communication = config.get("enable_agent_communication", True)

        self.registry = AgentRegistry() if self.enable_agent_communication else None

        # 初始化 Agents
        self.user_agent = UserAgent(self.model, registry=self.registry)
        self.analyst_agent = AnalystAgent(self.model, registry=self.registry)
        self.expert_agent = ExpertAgent(
            self.model, registry=self.registry,
            doc_dir="doc", enable_web_search=config.get("enable_web_search", True),
        )
        self.mediator_agent = MediatorAgent(self.model, registry=self.registry)
        self.modeler_agent = ModelerAgent(self.model, registry=self.registry)
        self.documentor_agent = DocumentorAgent(
            self.model, self.store, registry=self.registry,
        )

        # 註冊到 Registry
        if self.registry:
            self.registry.register("user", self.user_agent)
            self.registry.register("analyst", self.analyst_agent)
            self.registry.register("expert", self.expert_agent)
            self.registry.register("mediator", self.mediator_agent)
            self.registry.register("modeler", self.modeler_agent)
            self.registry.register("documentor", self.documentor_agent)

        self.logger.info(f"Agent 系統初始化完成")

    def run(self, rough_idea: str) -> Dict[str, Any]:
        rounds = self.config.get("rounds", 1)
        start_round = self.config.get("start_round", 1)

        artifact = {
            "rough_idea": rough_idea,
            "proposed_stakeholders": [],
            "stakeholders": [],
            "analyse": [],
            "reports": [],
            "feedback": []
        }

        self.store.save_artifact(artifact)

        for round_num in range(start_round, rounds + 1):
            self.logger.info(f"Round {round_num}/{rounds}")
            self.mom_manager.start_round(round_num)
            artifact = self.run_flow(artifact, round_num)
            self.logger.info(f"Round {round_num} 完成\n")

        self.generate_srs(artifact)
        self.logger.info("流程完成！")
        return artifact

    def run_continue(self, existing_artifact: Dict[str, Any]) -> Dict[str, Any]:
        rounds = self.config.get("rounds", 1)
        start_round = self.config.get("start_round", 1)
        artifact = existing_artifact

        self.logger.info(f"繼續現有專案，從 Round {start_round} 開始")

        for round_num in range(start_round, rounds + 1):
            self.logger.info(f"Round {round_num}/{rounds}")
            self.mom_manager.start_round(round_num)
            artifact = self.run_flow(artifact, round_num)
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
            self.user_agent.stakeholders = stakeholders
            self.store.save_artifact(artifact)
            self.logger.info(f"✓ 產生 {len(stakeholders)} 位利害關係人需求")
            self.mom_manager.add_stage("利害關係人提出需求", "User", f"{len(stakeholders)} 位", outputs={"stakeholders": stakeholders})
        else:
            selected = [sh["name"] for sh in artifact.get("stakeholders", [])]
            stakeholders = artifact.get("stakeholders", [])
            self.user_agent.stakeholders = stakeholders

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

        # Stage 6: 規格
        spec_md = ""
        if self.config.get("enable_mediator", True):
            self.logger.info("Stage 6: 產生需求草稿")
            spec_md = self.mediator_agent.generate_draft(artifact)
            self.store.save_spec_md(spec_md, round_num)
            self.logger.info(f"✓ 產生 spec_{round_num}.md")
            self.mom_manager.add_stage("產生需求規格", "Mediator", f"spec_{round_num}.md", outputs={"spec_generated": True})

        # Stage 7: UML
        if self.config.get("enable_modeler", True):
            self.logger.info("Stage 7: 建立系統模型")
            uml_data = self.modeler_agent.generate_system_model(spec_md)
            spec_md = self.store.append_uml_to_spec(spec_md, uml_data)
            self.store.save_spec_md(spec_md, round_num)
            self.store.save_plantuml_files(uml_data)
            artifact["uml"] = uml_data
            self.logger.info(f"✓ 系統模型已寫入 spec_{round_num}.md 附錄")
            self.mom_manager.add_stage("產生系統模型", "Modeler", f"spec_{round_num}.md", outputs={"model_generated": True})

        self.store.save_round_mom(self.mom_manager.get_current_round())
        return artifact

    # Round 2+

    def run_discussion_round(self, artifact: Dict[str, Any], round_num: int) -> Dict[str, Any]:
        prev_round = round_num - 1
        spec_md = self.store.load_spec_md(prev_round)
        if not spec_md:
            self.logger.warning(f"找不到 spec_{prev_round}.md，使用空 Spec")

        # Step 1: 生成議題
        self.logger.info("Step 1: Mediator 生成議題清單")
        rough_idea = artifact.get("rough_idea", "")
        topics = self.mediator_agent.generate_topics(spec_md, rough_idea, registry=self.registry)
        self.logger.info(f"✓ 生成 {len(topics)} 個議題")

        print(f"\n{'='*60}")
        print(f"Round {round_num} 議題清單")
        print(f"{'='*60}")
        for t in topics:
            print(f"  [{t['id']}] {t['title']} ({t['type']})")
        print(f"{'='*60}\n")

        # Step 2: 逐 topic 討論（先不進行人類裁決）
        all_resolutions = []
        pending_human = []  # 需要人類裁決的議題
        for idx, topic in enumerate(topics, 1):
            self.logger.info(f"討論議題 [{topic['id']}] {topic['title']}")

            # 2a: 根據 discussion_mode 選擇發言方式
            mode = topic.get("discussion_mode", "sequential")
            if mode == "simultaneous":
                contributions = self.mediator_agent.moderate_simultaneous(topic, self.registry)
            else:
                contributions = self.mediator_agent.moderate_sequential(topic, self.registry)

            # 2b: 綜合結果
            resolution = self.mediator_agent.synthesize_and_resolve(topic, contributions)
            self.logger.info(f"  決議: {resolution['resolution']}")

            # 2c: 若 Mediator 無法決定，先記錄待裁決，稍後統一處理
            needs_human = resolution["resolution"] == "unresolved" or resolution.get("escalation_needed")
            if needs_human:
                self.logger.info(f"  Mediator 無法達成共識，標記待人類裁決")
                options = self.mediator_agent.prepare_human_options(topic, contributions)
                pending_human.append({"idx": idx, "topic": topic, "contributions": contributions, "options": options})

            # 2d: 記錄 MOM + 即時存 MD（未裁決的先以 unresolved 記錄）
            self.mom_manager.add_meeting(round_num, topic, contributions, resolution, escalated_to_human=needs_human)
            meeting_data = self.mom_manager.get_latest_meeting()
            topic_title = topic.get("title", "未命名")
            meeting_id = meeting_data.get("meeting_id", f"R{round_num}-M{idx:02d}")
            md = self.store.generate_meeting_markdown(meeting_data)
            filename = self.store.safe_mom_filename(f"{meeting_id} {topic_title}")
            self.store.save_markdown(md, f"{filename}.md")
            self.logger.info(f"  ✓ 已存 {filename}.md")

            all_resolutions.append({"idx": idx, "topic": topic, "resolution": resolution})

        # Step 2e: 統一人類裁決
        if pending_human:
            self.logger.info(f"Step 2e: 統一人類裁決（{len(pending_human)} 個待決議題）")
            print(f"\n{'='*60}")
            print(f"Round {round_num} — 共 {len(pending_human)} 個議題需要人類裁決")
            print(f"{'='*60}")

            for item in pending_human:
                topic = item["topic"]
                options = item["options"]
                human_resolution = Collect.human_decision_on_topic(topic, options)

                # 更新 all_resolutions 中對應的 resolution
                for r in all_resolutions:
                    if r["idx"] == item["idx"]:
                        r["resolution"] = human_resolution
                        break

                # 更新 MOM 並重新存 MD
                self.mom_manager.update_meeting_resolution(round_num, item["idx"], human_resolution)
                meeting_data = self.mom_manager.get_meeting_by_index(round_num, item["idx"])
                if meeting_data:
                    topic_title = topic.get("title", "未命名")
                    meeting_id = meeting_data.get("meeting_id", f"R{round_num}-M{item['idx']:02d}")
                    md = self.store.generate_meeting_markdown(meeting_data)
                    filename = self.store.safe_mom_filename(f"{meeting_id} {topic_title}")
                    self.store.save_markdown(md, f"{filename}.md")
                    self.logger.info(f"  ✓ 已更新 {filename}.md")

        # Step 3: 更新 Spec
        self.logger.info("Step 3: Mediator 更新 Spec")
        resolutions_context = []
        for r in all_resolutions:
            t, res = r["topic"], r["resolution"]
            resolutions_context.append({
                "topic_id": t.get("id", ""), "topic_title": t.get("title", ""),
                "decision": res.get("decision", ""), "summary": res.get("summary", ""),
                "action_items": res.get("action_items", []),
            })

        spec_md = self.mediator_agent.generate_draft(artifact)
        self.store.save_spec_md(spec_md, round_num)
        self.logger.info(f"✓ 更新 spec_{round_num}.md")

        # Step 4: 更新 UML
        if self.config.get("enable_modeler", True):
            self.logger.info("Step 4: Modeler 更新 UML")
            prev_uml = artifact.get("uml", {})
            uml_data = self.modeler_agent.refine_model(spec_md, prev_uml)
            spec_md = self.store.append_uml_to_spec(spec_md, uml_data)
            self.store.save_spec_md(spec_md, round_num)
            self.store.save_plantuml_files(uml_data)
            artifact["uml"] = uml_data

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
        spec_files = glob.glob(str(self.store.output_dir / "spec_*.md"))
        if spec_files:
            latest_round = max(int(Path(f).stem.split('_')[-1]) for f in spec_files)
            spec_md = self.store.load_spec_md(latest_round)
        else:
            self.logger.warning("未找到 spec 文件")
            spec_md = ""

        template = self.store.load_spec_template()
        srs_template = template.get("spec", [])

        srs_json = self.documentor_agent.generate_srs_json(spec_md, srs_template)
        self.store.save_srs(srs_json)

        srs_md = self.store.generate_srs_markdown(srs_json)
        self.store.save_markdown(srs_md, "srs.md")
        self.logger.info("✓ 產生 SRS")
