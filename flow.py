from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from agents import AgentRegistry
from agents.profile.analyst import CONFLICT_TYPE_LABELS
from agents.profile import (
    UserAgent,
    AnalystAgent,
    ExpertAgent,
    MediatorAgent,
    ModelerAgent,
    DocumentorAgent,
)
from agents.profile.mediator import AgendaRunner
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
        now = datetime.now(timezone.utc).isoformat()
        artifact = {
            "rough_idea": rough_idea,
            "stakeholders": [],
            "scope": {"in_scope": [], "out_of_scope": [], "description": ""},
            "glossary": [],
            "assumptions": [],
            "requirements": [],
            "conflicts": [],
            "decisions": [],
            "open_questions": [],
            "system_models": {},
            "discussions": [],
            "meta": {"created_at": now, "updated_at": now, "last_round": 0},
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
        artifact.setdefault("scope", {"in_scope": [], "out_of_scope": [], "description": ""})
        artifact.setdefault("glossary", [])
        artifact.setdefault("assumptions", [])
        artifact.setdefault("meta", {})
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

        self.logger.info("Analyst 產出 scope、glossary、assumptions")
        sga = self.analyst_agent.generate_scope_glossary_assumptions(rough_idea, stakeholders)
        artifact["scope"] = sga.get("scope", artifact.get("scope", {}))
        artifact["glossary"] = sga.get("glossary", [])
        artifact["assumptions"] = sga.get("assumptions", [])
        self.store.save_artifact(artifact)

        self.logger.info("Analyst 主動執行衝突辨識")
        artifact = self.analyst_agent.run_conflict_detection(artifact)
        self.store.save_artifact(artifact)

        self.logger.info("Analyst 建立 Draft")
        draft = self.analyst_agent.create_draft(stakeholders)
        artifact["requirements"] = draft["requirements"]
        self.store.save_artifact(artifact)
        draft_md = self.build_draft_markdown(artifact, draft_version=0)
        self.store.save_draft(draft_md, version=0)
        self.logger.info(f"✓ Draft v0: {len(draft['requirements'])} 條需求，{len(artifact.get('conflicts', []))} 個衝突")

        self.logger.info("Expert 注入領域知識（查詢與專案概述相關的法規/標準）")
        scope = artifact.get("scope", {})
        project_overview = scope.get("description") or rough_idea or ""
        injection = self.expert_agent.inject_domain(
            artifact["requirements"], artifact["conflicts"], rough_idea,
            project_overview=project_overview,
        )
        artifact["requirements"] = injection["requirements"]
        self.store.save_artifact(artifact)
        constraint_count = len([r for r in artifact["requirements"] if r.get("type") == "constraint"])
        self.logger.info(f"✓ 注入 {constraint_count} 條約束")
        if constraint_count == 0:
            self.logger.info("  （若需約束：請確認專案概述已填寫、或於 doc/ 放置參考文件、或設定 TAVILY_API_KEY 以啟用網搜）")

        self.logger.info("Analyst 主動執行衝突辨識")
        artifact = self.analyst_agent.run_conflict_detection(artifact)
        meta = artifact.setdefault("meta", {})
        meta["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.store.save_artifact(artifact)

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

        # 議程由 Mediator Agent 驅動（產生議程、討論、綜合、人類裁決、存檔）
        self.logger.info("議程由 Mediator Agent 驅動")
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
        observation = None
        while True:
            state = runner.get_state_summary()
            decision = self.mediator_agent.decide_next_agenda_action(state, observation)
            action = decision.get("action", "finish_round")
            params = decision.get("params") or {}
            self.logger.info(f"  Agent 決策: {action} {params} — {decision.get('reasoning', '')}")
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
                print(f"  [{t['id']}] {t['title']} ({t.get('discussion_mode', 'sequential')}) [{t.get('category', '')}]")
            print(f"{'='*60}\n")

        # 記錄討論歷史（含本輪議程快照、open_questions 帶 topic_id）
        artifact.setdefault("discussions", []).append({
            "round": round_num,
            "topics": round_discussions,
            "agenda_snapshot": agenda_snapshot,
        })

        # 更新 open_questions（含回答結果寫進 artifact）
        existing_oq = artifact.get("open_questions", [])
        for oq in all_open_questions:
            oq["round"] = round_num
        artifact["open_questions"] = existing_oq + all_open_questions
        self.store.save_artifact(artifact)

        # Step 5.1: Mediator 更新決策與衝突（含討論中提出的新增衝突，可補辨識漏報）
        self.logger.info("Step 5.1: Mediator 更新決策與衝突")
        prev_conflicts_by_id = {c.get("id"): c for c in artifact.get("conflicts", []) if c.get("id")}
        updates = self.mediator_agent.update_decisions(artifact, round_discussions)
        new_decisions = updates.get("new_decisions", [])
        artifact["decisions"].extend(new_decisions)
        new_conflicts = list(updates.get("conflicts", artifact["conflicts"]))
        # 討論中提出的新增衝突（漏報補正）：指派 id 後併入
        valid_conflict_types = set(CONFLICT_TYPE_LABELS.keys())
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
            if ctype not in valid_conflict_types:
                ctype = "Inconsistency"
            new_conflicts.append({
                "id": f"CF-{max_num + 1:02d}",
                "label": "Conflict",
                "description": nc.get("description", ""),
                "conflict_type": ctype,
                "requirement_ids": nc.get("requirement_ids", []),
            })
        # 決策 ↔ 衝突對應：依 resolved_conflict_ids 寫入 resolved_by_decision_id
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
                    c.setdefault("resolved_by_decision_id", orig["resolved_by_decision_id"])
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

        self.logger.info("Analyst 主動執行衝突辨識")
        artifact = self.analyst_agent.run_conflict_detection(artifact)

        # Step 5.4: 產出 draft markdown（含系統模型）
        next_version = self.store.get_draft_version() + 1
        draft_md = self.build_draft_markdown(
            artifact, draft_version=next_version, round_num=round_num
        )
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

        meta = artifact.setdefault("meta", {})
        meta["updated_at"] = datetime.now(timezone.utc).isoformat()
        meta["last_round"] = round_num
        self.store.save_artifact(artifact)
        self.store.save_plantuml_files(model_data)

        return artifact

    # ===== Draft Markdown 生成 =====

    def build_draft_markdown(
        self,
        artifact: Dict[str, Any],
        draft_version: Optional[int] = None,
        round_num: Optional[int] = None,
    ) -> str:
        """將 artifact 組成需求草稿 Markdown（含概述、利害關係人、需求、衝突、決策摘要、系統模型）。"""
        lines = ["# 需求草稿\n"]

        # 版本說明
        if draft_version is not None:
            lines.append(f"- **本稿版本**: draft_v{draft_version}")
        if round_num is not None:
            lines.append(f"- **對應輪次**: Round {round_num}")
        if draft_version is not None or round_num is not None:
            lines.append("")

        # 專案概述（使用 scope.description，不再使用 rough_idea）
        scope = artifact.get("scope") or {}
        scope_desc = (scope.get("description") or "").strip()
        if scope_desc:
            lines.append("## 專案概述\n")
            lines.append(scope_desc)
            lines.append("")

        # 專案範圍
        in_scope = scope.get("in_scope") or []
        out_scope = scope.get("out_of_scope") or []
        if in_scope or out_scope:
            lines.append("## 專案範圍\n")
            if in_scope:
                lines.append("- **範圍內**: " + "；".join(in_scope))
            if out_scope:
                lines.append("- **排除**: " + "；".join(out_scope))
            lines.append("")

        # 利害關係人
        stakeholders = artifact.get("stakeholders", [])
        if stakeholders:
            lines.append("## 利害關係人\n")
            for s in stakeholders:
                name = s.get("name", "?")
                raw = s.get("text", "")
                texts = raw if isinstance(raw, list) else [raw] if raw else []
                concern = "；".join(str(t) for t in texts) if texts else "—"
                lines.append(f"- **{name}**: {concern}")
            lines.append("")

        # 需求列表（含 constraint 的 ref）
        lines.append("## 需求列表\n")
        for req in artifact.get("requirements", []):
            rid = req.get("id", "?")
            rtype = req.get("type", "FR")
            priority = req.get("priority") or "should"
            if priority not in ("must", "should", "could"):
                priority = "should"
            text = req.get("text", "")
            sources = ", ".join(req.get("source_stakeholders", []))
            lines.append(f"### {rid} ({rtype}, {priority})\n")
            lines.append(f"- **描述**: {text}")
            if sources:
                lines.append(f"- **來源**: {sources}")
            ref = req.get("ref", "")
            if ref:
                lines.append(f"- **依據**: {ref}")
            lines.append("")

        # 衝突列表（含涉及需求 id / 利害關係人）
        conflicts = [c for c in artifact.get("conflicts", []) if c.get("label") == "Conflict"]
        if conflicts:
            lines.append("## 衝突列表\n")
            for c in conflicts:
                cid = c.get("id", "?")
                desc = c.get("description", "")
                ctype = c.get("conflict_type", "")
                line = f"- **{cid}**" + (f" ({ctype})" if ctype else "") + f": {desc}"
                lines.append(line)
                rid_list = c.get("requirement_ids", [])
                if rid_list:
                    lines.append(f"  - **涉及需求**: {', '.join(rid_list)}")
                st_names = c.get("stakeholder_names", [])
                if st_names:
                    lines.append(f"  - **涉及利害關係人**: {', '.join(st_names)}")
            lines.append("")

        # 決策摘要
        decisions = artifact.get("decisions", [])
        if decisions:
            lines.append("## 決策摘要\n")
            for d in decisions[-20:]:  # 最近 20 筆
                did = d.get("id", "?")
                topic_id = d.get("topic_id", "")
                decision = (d.get("decision") or "").strip()
                summary = (d.get("summary") or "").strip()
                resolved = d.get("resolved_conflict_ids", [])
                suffix = f" （解決: {', '.join(resolved)}）" if resolved else ""
                lines.append(f"- **{did}** (議題 {topic_id}): {summary or decision}{suffix}")
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
        """產出需求衝突報告，格式：標題、衝突類型、衝突描述、涉及利害關係人"""
        lines = ["# 需求衝突報告\n"]

        all_conflicts = artifact.get("conflicts", [])
        active = [c for c in all_conflicts if c.get("label") == "Conflict"]

        req_by_id = {r.get("id"): r for r in artifact.get("requirements", []) if r.get("id")}

        for c in active:
            cid = c.get("id", "?")
            desc = c.get("description", "").strip()
            ctype_id = c.get("conflict_type", "")
            ctype_str = CONFLICT_TYPE_LABELS.get(ctype_id, ctype_id or "—")
            rid_list = c.get("requirement_ids", [])
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

            lines.append(f"### {cid}: {title}\n")
            lines.append(f"衝突類型: {ctype_str}" + (f"（{ctype_id}）" if ctype_id else "") + "\n")
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
