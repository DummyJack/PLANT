from typing import Dict, Any
from agents import UserAgent, AnalystAgent, ExpertAgent, MediatorAgent, ModelerAgent, DocumentorAgent
from model import create_model
from store import Store
from utils import Logger, MoMManager

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
            temperature=config.get("temperature")
        )
        
        # 初始化 Agents
        self.user_agent = UserAgent(self.model)
        self.analyst_agent = AnalystAgent(self.model)
        self.expert_agent = ExpertAgent(self.model, doc_dir="doc")
        self.mediator_agent = MediatorAgent(self.model)
        self.modeler_agent = ModelerAgent(self.model)
        self.documentor_agent = DocumentorAgent(self.model)
    
    def run(self, rough_idea: str) -> Dict[str, Any]:
        rounds = self.config.get("rounds", 1)
        
        # 創建新的 artifact
        artifact = {
            "rough_idea": rough_idea,
            "system_description": "",
            "proposed_stakeholders": [],
            "stakeholders": [],
            "analyse": {
                "pairs": [],
                "report": []
            },
            "feedback": [],
            "decisions": []
        }
        
        # 建立初始 artifact
        self.store.save_artifact(artifact)
        self.logger.info("創建新的 artifact.json")
        
        for round_num in range(1, rounds + 1):
            self.logger.info(f"\n{'='*60}")
            self.logger.info(f"Round {round_num}/{rounds}")
            self.logger.info(f"{'='*60}\n")
            
            self.mom_manager.start_round(round_num)
            artifact = self.run_single_round(artifact, round_num)
            
            self.logger.info(f"\nRound {round_num} 完成\n")
        
        # 最後一步
        self._generate_outputs(artifact)
        
        self.logger.info("流程完成！")
        return artifact
    
    def run_single_round(self, artifact: Dict[str, Any], round_num: int) -> Dict[str, Any]:
        rough_idea = artifact["rough_idea"]
        
        # Stage 1: Mediator 介入
        if round_num == 1 and self.config.get("enable_mediator", True):
            self.logger.info("Stage 1: 產生利害關係人")
            
            # 1.1 產生系統概述
            description = self.mediator_agent.generate_system_description(rough_idea)
            artifact["system_description"] = description
            self.logger.info("✓ 產生系統概述")

            # 1.2 產生利害關係人建議
            proposed = self.mediator_agent.propose_stakeholders(description)
            artifact["proposed_stakeholders"] = proposed
            self.logger.info(f"✓ 建議 {len(proposed)} 位利害關係人")
            
            self.store.save_artifact(artifact)
            
            self.mom_manager.add_stage("Mediator", "MediatorAgent",
                                      f"產生系統概述與建議 {len(proposed)} 位利害關係人",
                                      outputs={
                                          "system_description": description,
                                          "proposed_stakeholders": proposed
                                      })
            
            # 1.3 Human 選擇
            self.logger.info("\n請選擇利害關係人")
            selected = self.mediator_agent.collect_stakeholder_selection(proposed)
            self.logger.info(f"✓ 已選擇 {len(selected)} 位利害關係人")
            
            self.mom_manager.add_stage("Human Selection", "Human",
                                      f"選擇 {len(selected)} 位利害關係人",
                                      outputs={"selected": selected})
        else:
            selected = [sh['name'] for sh in artifact.get("stakeholders", [])]
        
        # Stage 2: User - 扮演利害關係人提出需求
        if self.config.get("enable_user", True):
            self.logger.info("\nStage 2: 扮演利害關係人提出需求")
            system_description = artifact.get("system_description")
            
            if round_num == 1:
                stakeholders = self.user_agent.generate_stakeholder_requirements(system_description, selected)
            else:
                # 多輪時精煉
                previous_draft = self.store.load_draft()
                stakeholders = self.user_agent.refine_stakeholders(artifact["stakeholders"], previous_draft)
                self.logger.info(f"✓ 精煉 {len(stakeholders)} 位利害關係人需求")
            
            artifact["stakeholders"] = stakeholders
            self.store.save_artifact(artifact)
            self.logger.info(f"✓ 產生 {len(stakeholders)} 位利害關係人需求")
            
            self.mom_manager.add_stage("User", "UserAgent",
                                      f"產生 {len(stakeholders)} 位利害關係人需求",
                                      outputs={"stakeholders": stakeholders})
        else:
            self.logger.info("\nStage 2: 跳過 User Agent（已停用）")
            stakeholders = artifact.get("stakeholders", [])
        
        # Stage 3: Analyst - 分析與識別衝突
        if self.config.get("enable_analyst", True):
            self.logger.info("\nStage 3: 識別需求衝突")
            
            # 3.1 衝突分析
            pairs = self.analyst_agent.analyze_pairs(stakeholders)
            artifact["analyse"]["pairs"] = pairs
            conflict_count = sum(1 for p in pairs if p['label'] == 'Conflict')
            self.logger.info(f"✓ 完成 {len(pairs)} 衝突分析，識別出 {conflict_count} 個衝突")
            
            # 3.2 產生衝突報告
            conflicts = self.analyst_agent.generate_conflict_report(pairs, stakeholders)
            artifact["analyse"]["report"] = conflicts

            self.store.save_artifact(artifact)
            self.logger.info(f"✓ 產生衝突報告")
            
            # 3.3 產生 report.md
            report_md = self.analyst_agent.generate_report_markdown(system_description, conflicts)
            self.store.save_markdown(report_md, "report.md")
            self.logger.info("✓ 產生 report.md")
            
            self.mom_manager.add_stage("Analyst", "AnalystAgent", 
                                       f"識別 {len(conflicts)} 個衝突",
                                       outputs={
                                           "conflict_count": len(conflicts),
                                           "conflicts": conflicts
                                       })
        else:
            self.logger.info("\nStage 3: 跳過 Analyst Agent（已停用）")
            conflicts = artifact.get("analyse", {}).get("report", [])
        
        # Stage 4: Expert - 專家建議（可選）
        feedback = []
        if self.config.get("enable_expert", True):
            self.logger.info("\nStage 4: 收集專家建議")
            
            if round_num == 1:
                # 第一輪：產生新的專家建議
                feedback = self.expert_agent.provide_feedback(system_description, conflicts)
            else:
                # 多輪：精煉先前的專家建議
                previous_feedback = artifact.get("feedback", [])
                if previous_feedback:
                    feedback = self.expert_agent.refine_feedback(previous_feedback)
                    self.logger.info(f"✓ 精煉 {len(feedback)} 則專家建議")
                else:
                    feedback = self.expert_agent.provide_feedback(system_description, conflicts)
            
            artifact["feedback"] = feedback
            self.store.save_artifact(artifact)
            self.mom_manager.add_stage("Expert", "ExpertAgent",
                                       f"{'產生' if round_num == 1 else '精煉'} {len(feedback)} 則專家建議",
                                       outputs={"feedback": feedback})
        else:
            self.logger.info("\nStage 4: 跳過專家建議階段（已停用）")
        
        # Stage 5: Mediator - 人類決策 + 產生 draft.json
        decisions = []
        if self.config.get("enable_mediator", True) and conflicts:
            self.logger.info("\nStage 5: 產生決策選項並收集人類決策")
            
            # 5.1 產生決策選項
            decision_options = self.mediator_agent.generate_decision_options(conflicts, feedback)
            
            # 5.2 收集人類決策
            self.logger.info("\n請進行衝突裁決：")
            for option in decision_options:
                decision = self.mediator_agent.collect_human_decision(option)
                decisions.append(decision)
                
                # 記錄到 MoM
                self.mom_manager.add_stage("Human Decision", "Human",
                                          f"人類裁決 {decision['conflict_id']}",
                                          outputs=decision)
                self.mom_manager.add_conflict_resolution(
                    decision['conflict_id'],
                    decision['decision'],
                    decision['rationale']
                )
            
            artifact["decisions"] = decisions
            self.store.save_artifact(artifact)
            self.logger.info(f"✓ 完成 {len(decisions)} 個決策")
        else:
            self.logger.info("\nStage 5: 無衝突需要裁決")
        
        # 產生需求草稿 (draft.json)
        if self.config.get("enable_mediator", True):
            # spec.json 必須存在
            self.logger.info("\nStage 6: 產生需求草稿")
            spec_template = self.store.load_spec_template()
            draft_template = spec_template.get("draft", [])
            
            draft = self.mediator_agent.generate_draft(artifact, draft_template)
            self.store.save_draft(draft)
            self.logger.info("✓ 產生 draft.json")
            self.mom_manager.add_stage("Mediator", "MediatorAgent",
                                      "產生需求草稿",
                                      outputs={"draft_generated": True})
        else:
            self.logger.info("\nStage 6: 跳過 draft.json 產生（Mediator 已停用）")
            draft = self.store.load_draft()
        
        # Stage 7: Modeler - 系統模型（可選）
        if self.config.get("enable_modeler", True):
            self.logger.info("\nStage 7: 建立系統模型")
            
            if round_num == 1:
                # 第一輪：產生新模型
                uml_json = self.modeler_agent.generate_system_model(draft)
            else:
                # 多輪：調整現有模型
                current_uml = self.store.load_json("artifact/uml.json")
                uml_json = self.modeler_agent.refine_model(current_uml, draft)
            
            self.store.save_json(uml_json, "artifact/uml.json")
            
            # 產生 PlantUML 檔案
            output_dir = self.store.base_dir / "output"
            self.modeler_agent.save_plantuml_files(uml_json, output_dir)

            self.logger.info("✓ 產生系統模型 (uml.json 和 .plantuml 檔案)")
            self.mom_manager.add_stage("Modeler", "ModelerAgent",
                                      "產生系統模型",
                                      outputs={"model_generated": True})
        else:
            self.logger.info("\nStage 7: 跳過系統建模階段（已停用）")
        
        # 每輪結束後保存 MoM
        self.store.save_mom(self.mom_manager.get_mom_data())
        self.logger.info(f"✓ 儲存 Round {round_num} 的會議記錄")
        
        return artifact
    
    def _generate_outputs(self, artifact: Dict[str, Any]):
        # 產生所有輸出文件（在所有輪次結束後執行）
        if self.config.get("enable_documentor", True):
            self.logger.info("\n最終階段: 產生文件")
            
            # 1. Design Rationale (dr.md)
            dr_md = self.documentor_agent.generate_design_rationale(self.mom_manager.get_mom_data())
            self.store.save_markdown(dr_md, "dr.md")
            self.logger.info("✓ 產生 dr.md (Design Rationale)")
            
            # 2. SRS (srs.json / srs.md)
            spec_template = self.store.load_spec_template()
            ieee_template = spec_template.get("ieee_29148")
            
            draft = self.store.load_draft()
            srs_json = self.documentor_agent.generate_srs_json(draft, ieee_template)
            self.store.save_srs(srs_json)
            
            srs_md = self.documentor_agent.generate_srs_markdown(srs_json)
            self.store.save_markdown(srs_md, "srs.md")
            self.logger.info("✓ 產生 srs.json / srs.md (SRS)")
        else:
            self.logger.info("\n最終階段: 跳過文件產生（Documentor 已停用）")
