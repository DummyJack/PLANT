from typing import Dict, Any, List
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
from utils import Logger, Collect


class Flow:
    def __init__(self, config: Dict[str, Any], store: Store, logger: Logger):
        self.config = config
        self.store = store
        self.logger = logger

        self.model = create_model(
            provider=config.get("provider"),
            model_name=config.get("model"),
            temperature=config.get("temperature"),
        )

        self.registry = AgentRegistry()

        self.user_agent = UserAgent(self.model, registry=self.registry)
        self.analyst_agent = AnalystAgent(self.model, registry=self.registry)
        self.expert_agent = ExpertAgent(
            self.model, registry=self.registry,
            doc_dir="doc", enable_web_search=config.get("enable_web_search", True),
        )
        self.mediator_agent = MediatorAgent(self.model, registry=self.registry)
        modeler_tools = []
        if config.get("enable_plantuml_validate", True):
            from agents.tools import PlantUMLValidatorTool
            opts = config.get("plantuml_validate") or {}
            modeler_tools.append(PlantUMLValidatorTool(
                jar_path=opts.get("jar_path", "plantuml.jar"),
                use_online=opts.get("use_online"),
                server_url=opts.get("server_url", ""),
            ))
        self.modeler_agent = ModelerAgent(self.model, tools=modeler_tools, registry=self.registry)
        self.documentor_agent = DocumentorAgent(
            self.model, self.store, registry=self.registry,
        )

        self.registry.register("user", self.user_agent)
        self.registry.register("analyst", self.analyst_agent)
        self.registry.register("expert", self.expert_agent)
        self.registry.register("mediator", self.mediator_agent)
        self.registry.register("modeler", self.modeler_agent)
        self.registry.register("documentor", self.documentor_agent)

    def run(self, rough_idea: str) -> Dict[str, Any]:
        rounds = self.config.get("rounds", 1)
        artifact = {
            "rough_idea": rough_idea,
            "stakeholders": [],
            "requirements": [],
            "conflicts": [],
            "decisions": [],
            "open_questions": [],
            "system_models": {},
            "discussions": [],
        }

        self.store.save_artifact(artifact)

        self.logger.info("=== Phase 0: 初始草稿建立 ===")
        artifact = self.run_init_phase(artifact)

        for round_num in range(1, rounds + 1):
            self.logger.info(f"=== Round {round_num}/{rounds}: 多輪會議精煉 ===")
            artifact = self.run_meeting_round(artifact, round_num)
            self.logger.info(f"Round {round_num} 完成\n")

        self.logger.info("=== 規格化 ===")
        self.finalize(artifact)

        self.logger.info("流程完成！")
        return artifact

    def run_continue(self, existing_artifact: Dict[str, Any]) -> Dict[str, Any]:
        artifact = existing_artifact
        self.user_agent.stakeholders = artifact.get("stakeholders", [])

        rounds = self.config.get("rounds", 1)
        start_round = len(artifact.get("discussions", [])) + 1
        self.logger.info(f"繼續現有專案，從 Round {start_round} 開始，共 {rounds} 輪")

        for round_num in range(start_round, start_round + rounds):
            self.logger.info(f"=== Round {round_num}: 多輪會議精煉 ===")
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
        selected_indices = Collect.user_selection(proposed)
        selected = [proposed[i]["name"] for i in selected_indices]
        print()
        self.logger.info(f"✓ 已選擇 {len(selected)} 位利害關係人")

        stakeholders = self.user_agent.generate_stakeholder_requirements(rough_idea, selected)
        artifact["stakeholders"] = stakeholders
        self.user_agent.stakeholders = stakeholders
        self.store.save_artifact(artifact)
        self.logger.info(f"✓ 產生 {len(stakeholders)} 位利害關係人需求")

        self.logger.info("利害關係人衝突辨識")
        stakeholder_conflicts = self.analyst_agent.detect_stakeholder_conflicts(stakeholders)
        name_to_text = {s.get("name", ""): s.get("text", "") for s in stakeholders}
        conflicts = []
        for c in stakeholder_conflicts:
            if c.get("label") != "Conflict":
                continue
            names = c.get("stakeholder_names", [])[:2]
            cf_id = f"CF-{len(conflicts) + 1:02d}"
            item = {
                "id": cf_id,
                "label": "Conflict",
                "source": "stakeholder",
                "description": c.get("description", ""),
                "stakeholder_names": names,
                "texts": {n: name_to_text.get(n, "") for n in names},
            }
            if c.get("conflict_type"):
                item["conflict_type"] = c["conflict_type"]
            conflicts.append(item)
        artifact["conflicts"] = conflicts
        self.store.save_artifact(artifact)
        self.logger.info(f"✓ 辨識出 {len(conflicts)} 個利害關係人衝突")

        self.logger.info("Analyst 建立 Draft")
        draft = self.analyst_agent.create_draft(stakeholders)
        artifact["requirements"] = draft["requirements"]
        self.store.save_artifact(artifact)
        draft_md = self.build_draft_markdown(artifact)
        self.store.save_draft(draft_md, version=0)
        self.logger.info(f"✓ Draft v0: {len(draft['requirements'])} 條需求，{len(conflicts)} 個衝突")

        self.logger.info("Expert 注入領域知識")
        injection = self.expert_agent.inject_domain(
            artifact["requirements"], artifact["conflicts"], rough_idea
        )
        artifact["requirements"] = injection["requirements"]
        artifact["conflicts"] = injection["conflicts"]
        self.store.save_artifact(artifact)
        constraint_count = len([r for r in artifact["requirements"] if r.get("type") == "constraint"])
        self.logger.info(f"✓ 注入 {constraint_count} 條約束")

        return artifact

    # Round k: 多輪會議精煉

    def run_meeting_round(self, artifact: Dict[str, Any], round_num: int, skip_agenda: bool = False) -> Dict[str, Any]:
        # 讀取前一輪草稿，讓本輪基於前一版草稿
        prev_version = round_num - 1
        prev_draft_md = self.store.load_draft(prev_version)
        if prev_draft_md:
            self.logger.info(f"載入 draft_v{prev_version}.md 作為本輪基礎")

        if skip_agenda:
            return artifact

        # ===== Step 1: Mediator 議程自動生成 =====
        self.logger.info("Step 1: Mediator 議程自動生成")
        max_agenda = self.config.get("agenda_items", 5)

        skip_source_ids = set()
        for disc in artifact.get("discussions", []):
            for td in disc.get("topics", []):
                for sid in td.get("source_ids", []):
                    skip_source_ids.add(sid)

        topics = self.mediator_agent.generate_agenda(
            artifact, registry=self.registry, max_items=max_agenda,
            skip_source_ids=skip_source_ids if skip_source_ids else None,
        )
        if not topics:
            self.logger.info(
                "本輪無議題可提出（可能原因：無未解決衝突、無待回答的 open_question，或前輪已討論完所有問題）"
            )
        else:
            self.logger.info(f"✓ 安排 {len(topics)} 個議程")

        print(f"\n{'='*60}")
        print(f"Round {round_num} 議程")
        print(f"{'='*60}")
        for t in topics:
            print(f"  [{t['id']}] {t['title']} ({t.get('discussion_mode', 'sequential')}) "
                  f"[{t.get('category', '')}]")
        print(f"{'='*60}\n")

        round_discussions = []
        all_open_questions = []
        topic_idx = 1

        for topic in topics:
            self.logger.info(f"討論議題 [{topic['id']}] {topic['title']}")

            # Step 2: 議程討論
            mode = topic.get("discussion_mode", "sequential")
            if mode == "simultaneous":
                contributions = self.mediator_agent.moderate_simultaneous(topic, self.registry)
            else:
                contributions = self.mediator_agent.moderate_sequential(topic, self.registry)

            # Step 3: Open Question 處理
            stakeholders = artifact.get("stakeholders", [])
            oq_records = self.mediator_agent.handle_open_questions(
                contributions, self.registry, stakeholders
            )
            all_open_questions.extend(oq_records)

            # 綜合結果
            resolution = self.mediator_agent.synthesize_and_resolve(topic, contributions)
            self.logger.info(f"  決議: {resolution['resolution']}")

            # 人類裁決（只在 unresolved 時生成 option）
            if resolution["resolution"] == "unresolved":
                self.logger.info("  需要人類裁決")
                options = self.mediator_agent.prepare_human_options(topic, contributions)
                resolution = Collect.human_decision_on_topic(topic, options)

            # Step 4: 產出議程級 Markdown 記錄
            meeting_md = self.mediator_agent.generate_meeting_markdown(
                topic, contributions, resolution, round_num=round_num
            )
            meeting_filename = f"R{round_num}-M{topic_idx:02d}.md"
            self.store.save_markdown(meeting_md, meeting_filename)
            self.logger.info(f"  ✓ 已存 {meeting_filename}")

            round_discussions.append({
                "topic": {"id": topic.get("id"), "title": topic.get("title")},
                "source_ids": topic.get("source_ids", []),
                "contributions": [
                    {"agent": c.get("agent"), "response": c.get("response", {})}
                    for c in contributions
                ],
                "resolution": resolution,
            })
            topic_idx += 1

        # 記錄討論歷史
        artifact.setdefault("discussions", []).append({
            "round": round_num,
            "topics": round_discussions,
        })

        # 更新 open_questions（含回答結果寫進 artifact）
        existing_oq = artifact.get("open_questions", [])
        for oq in all_open_questions:
            oq["round"] = round_num
        artifact["open_questions"] = existing_oq + all_open_questions
        self.store.save_artifact(artifact)

        # Step 5.1: Mediator 更新決策與衝突
        self.logger.info("Step 5.1: Mediator 更新決策與衝突")
        prev_conflicts_by_id = {c.get("id"): c for c in artifact.get("conflicts", []) if c.get("id")}
        updates = self.mediator_agent.update_decisions(artifact, round_discussions)
        artifact["decisions"].extend(updates.get("new_decisions", []))
        new_conflicts = updates.get("conflicts", artifact["conflicts"])
        for c in new_conflicts:
            orig = prev_conflicts_by_id.get(c.get("id"))
            if orig:
                orig_source = orig.get("source")
                c.setdefault("source", "analyst" if orig_source == "statement" else orig_source)
                if orig.get("requirement_ids") is not None:
                    c.setdefault("requirement_ids", orig["requirement_ids"])
        artifact["conflicts"] = new_conflicts

        # Step 5.2: Analyst 更新需求草稿
        self.logger.info("Step 5.2: Analyst 更新需求草稿")
        draft = self.analyst_agent.update_draft(artifact)
        artifact["requirements"] = draft["requirements"]

        # Step 5.3: Modeler 更新系統模型
        self.logger.info("Step 5.3: Modeler 更新系統模型")
        prev_models = artifact.get("system_models", {}).get("models", [])

        if prev_models:
            model_data = self.modeler_agent.refine_model(artifact["requirements"], prev_models)
        else:
            model_data = self.modeler_agent.generate_system_model(
                artifact["requirements"], artifact["stakeholders"]
            )

        artifact["system_models"] = model_data

        design_conflicts = model_data.get("design_conflicts", [])
        if design_conflicts:
            self.logger.info(f"  ⚠ 發現 {len(design_conflicts)} 個設計衝突")
            for dc in design_conflicts:
                cf_id = f"CF-D{len(artifact['conflicts']) + 1:02d}"
                artifact["conflicts"].append({
                    "id": cf_id,
                    "label": "Conflict",
                    "description": dc.get("description", ""),
                    "source": "modeler",
                })

        # Step 5.4: 產出 draft markdown（含系統模型）
        next_version = self.store.get_draft_version() + 1
        draft_md = self.build_draft_markdown(artifact)
        self.store.save_draft(draft_md, version=next_version)
        self.logger.info(f"  ✓ 已存 draft_v{next_version}.md")

        # Step 5.5: 僅當 artifact 中有 label=Conflict 時產出需求衝突報告
        active_conflicts = [c for c in artifact.get("conflicts", []) if c.get("label") == "Conflict"]
        if active_conflicts:
            self.logger.info("Step 5.5: 產出需求衝突報告")
            conflict_report_md = self.build_conflict_report(artifact, round_num)
            self.store.save_markdown(conflict_report_md, "conflict_report.md")
            self.logger.info("  ✓ 已存 conflict_report.md")
        else:
            self.logger.info("Step 5.5: 無未解決衝突，略過 conflict_report.md")

        self.store.save_artifact(artifact)
        self.store.save_plantuml_files(model_data)

        return artifact

    # ===== Draft Markdown 生成 =====

    def build_draft_markdown(self, artifact: Dict[str, Any]) -> str:
        """將 artifact 的需求、衝突、系統模型組成 draft markdown"""
        lines = ["# 需求草稿\n"]

        # 需求列表
        lines.append("## 需求列表\n")
        for req in artifact.get("requirements", []):
            rid = req.get("id", "?")
            rtype = req.get("type", "FR")
            text = req.get("text", "")
            sources = ", ".join(req.get("source_stakeholders", []))
            lines.append(f"### {rid} ({rtype})\n")
            lines.append(f"- **描述**: {text}")
            if sources:
                lines.append(f"- **來源**: {sources}")
            lines.append("")

        # 衝突列表
        conflicts = [c for c in artifact.get("conflicts", []) if c.get("label") == "Conflict"]
        if conflicts:
            lines.append("## 衝突列表\n")
            for c in conflicts:
                cid = c.get("id", "?")
                desc = c.get("description", "")
                source = "analyst" if c.get("source") == "statement" else c.get("source", "")
                ctype = c.get("conflict_type", "")
                lines.append(f"- **{cid}** [{source}]" + (f" ({ctype})" if ctype else "") + f": {desc}")
            lines.append("")

        # 未回答的 Open Questions（供後續議程討論）
        unanswered = [oq for oq in artifact.get("open_questions", []) if oq.get("status") != "answered"]
        if unanswered:
            lines.append("## 未回答的 Open Questions\n")
            for oq in unanswered:
                from_agent = oq.get("from_agent", "?")
                question = oq.get("question", "")
                if question:
                    lines.append(f"- **{from_agent}**: {question}")
            lines.append("")

        # 系統模型
        models = artifact.get("system_models", {}).get("models", [])
        if models:
            lines.append("## 系統模型\n")
            for m in models:
                name = m.get("name", "unnamed")
                mtype = m.get("type", "")
                plantuml = m.get("plantuml", "")
                lines.append(f"### {name} ({mtype})\n")
                if plantuml:
                    lines.append("```plantuml")
                    lines.append(plantuml)
                    lines.append("```\n")

        return "\n".join(lines)

    # ===== 需求衝突報告 =====

    def build_conflict_report(self, artifact: Dict[str, Any], round_num: int) -> str:
        """產出需求衝突報告，格式：標題、衝突描述、涉及利害關係人（不含衝突類型）"""
        lines = ["# 需求衝突報告\n"]

        all_conflicts = artifact.get("conflicts", [])
        active = [c for c in all_conflicts if c.get("label") == "Conflict"]
        resolved = [c for c in all_conflicts if c.get("label") == "Neutral"]

        req_by_id = {r.get("id"): r for r in artifact.get("requirements", []) if r.get("id")}

        for c in active:
            cid = c.get("id", "?")
            desc = c.get("description", "").strip()
            rid_list = c.get("requirement_ids", []) or list(c.get("texts", {}).keys())
            agents_list = c.get("agents", [])
            stakeholder_names = c.get("stakeholder_names", [])
            stakeholders = set()
            for rid in rid_list:
                req = req_by_id.get(rid) if isinstance(rid, str) else None
                if req:
                    stakeholders.update(req.get("source_stakeholders", []))
            if stakeholder_names:
                stakeholders_str = "利害關係人: " + ", ".join(sorted(stakeholder_names))
            elif agents_list:
                stakeholders_str = "發言者: " + ", ".join(sorted(agents_list))
            else:
                stakeholders_str = ", ".join(sorted(stakeholders)) if stakeholders else "—"

            title = desc.split("。")[0].strip() if desc else "需求衝突"
            if len(title) > 60:
                title = title[:57] + "..."

            lines.append(f"### {cid}: {title}\n")
            lines.append(f"衝突描述: {desc}\n")
            lines.append(f"涉及利害關係人: {stakeholders_str}\n")

        return "\n".join(lines)

    # Finalization

    def finalize(self, artifact: Dict[str, Any]):

        self.logger.info("Step F1: 產生 Design Rationale")
        dr_md = self.documentor_agent.generate_design_rationale(artifact)
        self.store.save_markdown(dr_md, "design_rationale.md")
        self.logger.info("✓ 產生 design_rationale.md")

        self.logger.info("Step F2: 產出 SRS Final")
        template = self.store.load_spec_template()
        srs_template = template.get("spec", [])
        srs_json, srs_md = self.documentor_agent.generate_srs(artifact, srs_template)
        self.store.save_srs(srs_json)
        self.store.save_markdown(srs_md, "srs.md")
        self.logger.info("✓ 產生 srs.json + srs.md")
