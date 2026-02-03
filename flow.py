from typing import Dict, Any
from agents import (
    UserAgent,
    AnalystAgent,
    ExpertAgent,
    MediatorAgent,
    ModelerAgent,
    DocumentorAgent,
)
from model import create_model
from store import Store
from utils import Logger, MoMManager, Collect, AgentSelector


# 流程
class Flow:
    def __init__(self, config: Dict[str, Any], store: Store, logger: Logger):
        self.config = config
        self.store = store
        self.logger = logger
        self.mom_manager = MoMManager()

        # 建立模型
        self.model = create_model(
            provider=config.get("provider"),
            model_name=config.get("model"),
            temperature=config.get("temperature"),
        )

        # 初始化 Agents
        self.user_agent = UserAgent(self.model)
        self.analyst_agent = AnalystAgent(self.model)
        self.expert_agent = ExpertAgent(
            self.model, 
            doc_dir="doc",
            enable_web_search=config.get("enable_web_search", True)
        )
        self.mediator_agent = MediatorAgent(self.model)
        self.modeler_agent = ModelerAgent(self.model)
        self.documentor_agent = DocumentorAgent(self.model, self.store)

    def run(self, rough_idea: str) -> Dict[str, Any]:
        rounds = self.config.get("rounds", 1)
        start_round = self.config.get("start_round", 1)

        # artifact.json 初始化
        artifact = {
            "rough_idea": rough_idea,
            "proposed_stakeholders": [],
            "stakeholders": [],
            "analyse": {"groups": [], "conflict_groups": [], "report": []},
            "feedback": [],
            "decisions": [],
        }

        # 建立初始 artifact
        self.store.save_artifact(artifact)
        self.logger.info("創建中間產物(artifact.json)")

        for round_num in range(start_round, rounds + 1):
            self.logger.info(f"\n{'='*60}")
            self.logger.info(f"Round {round_num}/{rounds}")
            self.logger.info(f"{'='*60}\n")

            self.mom_manager.start_round(round_num)
            artifact = self.run_single_round(artifact, round_num)

            self.logger.info(f"\nRound {round_num} 完成\n")

        self.generate_srs(artifact)

        self.logger.info("流程完成！")
        return artifact
    
    def run_continue(self, rough_idea: str, existing_artifact: Dict[str, Any]) -> Dict[str, Any]:
        """繼續現有專案的討論"""
        rounds = self.config.get("rounds", 1)
        start_round = self.config.get("start_round", 1)
        
        # 使用現有的 artifact
        artifact = existing_artifact
        
        self.logger.info("繼續現有專案的討論")
        self.logger.info(f"從 Round {start_round} 開始")

        for round_num in range(start_round, rounds + 1):
            self.logger.info(f"\n{'='*60}")
            self.logger.info(f"Round {round_num}/{rounds}")
            self.logger.info(f"{'='*60}\n")

            self.mom_manager.start_round(round_num)
            artifact = self.run_single_round(artifact, round_num)

            self.logger.info(f"\nRound {round_num} 完成\n")

        self.generate_srs(artifact)

        self.logger.info("流程完成！")
        return artifact

    def run_single_round(
        self, artifact: Dict[str, Any], round_num: int
    ) -> Dict[str, Any]:
        rough_idea = artifact["rough_idea"]

        if round_num == 1 and self.config.get("enable_user", True):
            self.logger.info("Stage 1: 產生利害關係人")

            # 產生利害關係人
            proposed = self.user_agent.propose_stakeholders(rough_idea)
            artifact["proposed_stakeholders"] = proposed

            self.store.save_artifact(artifact)

            self.mom_manager.add_stage(
                "Mediator",
                "MediatorAgent",
                f"建議 {len(proposed)} 位利害關係人",
                outputs={
                    "proposed_stakeholders": proposed,
                },
            )

            # 人類選擇利害關係人
            self.logger.info("\n請選擇利害關係人")
            selected_indices = Collect.user_selection(proposed)
            selected = [proposed[i]["name"] for i in selected_indices]
            self.logger.info(f"✓ 已選擇 {len(selected)} 位利害關係人")

            self.mom_manager.add_stage(
                "Human Selection",
                "Human",
                f"選擇 {len(selected)} 位利害關係人",
                outputs={"selected": selected},
            )
        else:
            selected = [sh["name"] for sh in artifact.get("stakeholders", [])]

        if self.config.get("enable_user", True):
            self.logger.info("\nStage 2: 利害關係人提出需求")

            if round_num == 1:
                stakeholders = self.user_agent.generate_stakeholder_requirements(
                    rough_idea, selected
                )
            else:
                # 多輪時精煉
                previous_draft = self.store.load_draft()
                stakeholders = self.user_agent.refine_stakeholders(
                    artifact["stakeholders"], previous_draft
                )
                self.logger.info(f"✓ 精煉 {len(stakeholders)} 位利害關係人需求")

            artifact["stakeholders"] = stakeholders
            self.store.save_artifact(artifact)
            self.logger.info(f"✓ 產生 {len(stakeholders)} 位利害關係人需求")

            self.mom_manager.add_stage(
                "User",
                "UserAgent",
                f"產生 {len(stakeholders)} 位利害關係人需求",
                outputs={"stakeholders": stakeholders},
            )
        else:
            self.logger.info("\nStage 2 跳過 (User 已停用)")
            stakeholders = artifact.get("stakeholders", [])

        if self.config.get("enable_analyst", True):
            self.logger.info("\nStage 3: 衝突分析")

            # 衝突分析
            groups = self.analyst_agent.analyze_groups(stakeholders)
            artifact["analyse"]["groups"] = groups

            # 濾出衝突組合
            conflict_groups = self.analyst_agent.filter_conflicts(groups)
            artifact["analyse"]["conflict_groups"] = conflict_groups

            self.logger.info(
                f"✓ 完成 {len(groups)} 組分析，識別出 {len(conflict_groups)} 個衝突"
            )

            self.store.save_artifact(artifact)

            self.mom_manager.add_stage(
                "Analyst",
                "AnalystAgent",
                f"識別 {len(conflict_groups)} 個衝突",
                outputs={
                    "total_groups": len(groups),
                    "conflict_count": len(conflict_groups),
                },
            )
        else:
            self.logger.info("\nStage 3 跳過 (Analyst 已停用)")
            conflict_groups = artifact.get("analyse", {}).get("conflict_groups", [])

        conflicts = []
        if self.config.get("enable_mediator", True) and conflict_groups:
            self.logger.info("\nStage 4: 產生衝突報告")
            conflicts = self.mediator_agent.generate_conflict_report(conflict_groups)
            artifact["analyse"]["report"] = conflicts
            self.store.save_artifact(artifact)
            self.logger.info(f"✓ 產生 {len(conflicts)} 份衝突報告")

            # 產生 report.md
            report_md = self.store.generate_report_markdown(conflicts)
            self.store.save_markdown(report_md, "report.md")
            self.logger.info("✓ 產生 report.md")

            self.mom_manager.add_stage(
                "Mediator",
                "MediatorAgent",
                f"產生 {len(conflicts)} 份衝突報告",
                outputs={"conflicts": conflicts},
            )
        else:
            if not self.config.get("enable_mediator", True):
                self.logger.info("\nStage 4 跳過 (Mediator 已停用)")
            else:
                self.logger.info("\nStage 4 無衝突，跳過衝突報告產生")
            conflicts = artifact.get("analyse", {}).get("report", [])

        feedback = []
        if self.config.get("enable_expert", True):
            self.logger.info("\nStage 5: 專家提供建議")

            if round_num == 1:
                # 第一輪：產生新的專家建議
                feedback = self.expert_agent.provide_feedback(rough_idea, conflicts)
            else:
                # 多輪：精煉先前的專家建議
                previous_feedback = artifact.get("feedback", [])
                if previous_feedback:
                    feedback = self.expert_agent.refine_feedback(previous_feedback)
                    self.logger.info(f"✓ 精煉 {len(feedback)} 則專家建議")
                else:
                    feedback = self.expert_agent.provide_feedback(rough_idea, conflicts)

            artifact["feedback"] = feedback
            self.store.save_artifact(artifact)
            self.mom_manager.add_stage(
                "Expert",
                "ExpertAgent",
                f"{'產生' if round_num == 1 else '精煉'} {len(feedback)} 則專家建議",
                outputs={"feedback": feedback},
            )
        else:
            self.logger.info("\nStage 5 跳過 (Expert 已停用)")

        decisions = []
        if self.config.get("enable_mediator", True) and conflicts:
            self.logger.info("\nStage 6: 產生決策選項並由人類選擇")

            decision_options = self.mediator_agent.generate_decision_options(
                conflicts, feedback
            )

            # 人類決策
            self.logger.info("\n請進行衝突裁決：")
            for option in decision_options:
                decision = Collect.user_decision(option)
                decisions.append(decision)

                # 記錄到 MoM
                self.mom_manager.add_stage(
                    "Human Decision",
                    "Human",
                    f"人類裁決 {decision['conflict_id']}",
                    outputs=decision,
                )
                self.mom_manager.add_conflict_resolution(
                    decision["conflict_id"], decision["decision"], decision["rationale"]
                )

            artifact["decisions"] = decisions
            self.store.save_artifact(artifact)
            self.logger.info(f"✓ 完成 {len(decisions)} 個決策")
        else:
            if not self.config.get("enable_mediator", True):
                self.logger.info("\nStage 4 跳過 (Mediator 已停用)")
            else:
                self.logger.info("\nStage 6: 無衝突需要裁決")

        # 產生需求草稿 (draft.json)
        if self.config.get("enable_analyst", True):
            # spec.json 必須存在
            self.logger.info("\nStage 7: 產生需求草稿")
            spec_template = self.store.load_spec_template()
            draft_template = spec_template.get("draft", [])

            draft = self.analyst_agent.generate_draft(artifact, draft_template)
            self.store.save_draft(draft)
            self.logger.info("✓ 產生 draft.json")
            self.mom_manager.add_stage(
                "Analyst",
                "AnalystAgent",
                "產生需求草稿",
                outputs={"draft_generated": True},
            )
        else:
            self.logger.info("\nStage 7 跳過 (Analyst 已停用)")
            draft = self.store.load_draft()

        if self.config.get("enable_modeler", True):
            self.logger.info("\nStage 8: 建立系統模型")

            if round_num == 1:
                # 第一輪：產生新模型
                uml_json = self.modeler_agent.generate_system_model(draft)
            else:
                # 多輪：調整現有模型
                current_uml = self.store.load_json("artifact/uml.json")
                uml_json = self.modeler_agent.refine_model(current_uml, draft)

            self.store.save_json(uml_json, "artifact/uml.json")

            # 產生 PlantUML 檔案
            self.store.save_plantuml_files(uml_json)

            self.logger.info("✓ 產生系統模型 (uml.json 和 .plantuml 檔案)")
            self.mom_manager.add_stage(
                "Modeler",
                "ModelerAgent",
                "產生系統模型",
                outputs={"model_generated": True},
            )
        else:
            self.logger.info("\nStage 8 跳過 (Modeler 已停用)")

        # 每輪結束後保存 MoM
        self.store.save_mom(self.mom_manager.get_mom_data())
        self.logger.info(f"✓ 儲存 Round {round_num} 的會議記錄")

        return artifact

    # 最終階段: 產生 SRS
    def generate_srs(self, artifact: Dict[str, Any]):
        if self.config.get("enable_documentor", True):
            generate_srs = (
                input("\n是否要生成正式的需求規格書(y/n)：")
                .strip()
                .lower()
            )

            if generate_srs == "y":
                self.logger.info("\n最終階段: 產生文件")

                # 產生 mom.md
                mom_data = self.store.load_mom()
                mom_md = self.store.generate_markdown(mom_data)
                self.store.save_markdown(mom_md, "mom.md")
                self.logger.info("✓ 產生會議記錄 (mom.md)")

                # 產生 Design Rationale (dr.md)
                dr_md = self.documentor_agent.generate_design_rationale()
                self.store.save_markdown(dr_md, "dr.md")
                self.logger.info("✓ 產生 Design Rationale (dr.md)")

                # 產生 SRS (srs.json / srs.md)
                spec_template = self.store.load_spec_template()
                ieee_template = spec_template.get("ieee_29148")

                draft = self.store.load_draft()
                srs_json = self.documentor_agent.generate_srs_json(draft, ieee_template)
                self.store.save_srs(srs_json)

                srs_md = self.store.generate_markdown(srs_json)
                self.store.save_markdown(srs_md, "srs.md")

                self.logger.info("✓ 產生 SRS (srs.json / srs.md)")
            else:
                self.logger.info("\n進入額外的討論")

                # 選擇要使用的代理
                AgentSelector.select_agents(self.config)
                
                # 詢問額外回合數
                extra_rounds = AgentSelector.set_rounds()

                # 執行額外討論輪次
                current_round = self.config.get("rounds", 1)
                for i in range(1, extra_rounds + 1):
                    round_num = current_round + i
                    self.logger.info(f"\n{'='*60}")
                    self.logger.info(
                        f"額外討論 Round {i}/{extra_rounds} (總 Round {round_num})"
                    )
                    self.logger.info(f"{'='*60}\n")

                    self.mom_manager.start_round(round_num)
                    artifact = self.run_single_round(artifact, round_num)

        else:
            self.logger.info("\nFinal Stage 跳過 (Documentor 已停用)")
