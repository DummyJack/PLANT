from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from agents import AgentRegistry
from agents.profile.analyst import ALLOWED_CONFLICT_TYPES
from agents.profile import (
    UserAgent,
    AnalystAgent,
    ExpertAgent,
    MediatorAgent,
    ModelerAgent,
    DocumentorAgent,
)
from agents.profile.mediator import AgendaRunner, AGENDA_CATEGORY_LABEL
from pathlib import Path
from model import create_model
from store import Store
from utils import Logger, Collect
from agents.profile.expert import has_supported_doc_files
from agents.tools.read_external_file import ReadExternalFileTool


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
        enable_tools = config.get("enable_tools") or {}
        enable_agents = config.get("enable_agents") or {}

        doc_dir = Path("doc")
        doc_dir.mkdir(parents=True, exist_ok=True)
        expert_tools = []
        if enable_tools.get("web_search", False):
            from agents.tools import WebSearchTool
            expert_tools.append(WebSearchTool())
        if enable_tools.get("read_external_file", True) and has_supported_doc_files(doc_dir):
            expert_tools.append(ReadExternalFileTool(base_dir=doc_dir))
        self.user_agent = UserAgent(self.model, registry=self.registry)
        self.analyst_agent = AnalystAgent(self.model, registry=self.registry)
        self.expert_agent = ExpertAgent(
            self.model, tools=expert_tools, registry=self.registry, doc_dir="doc"
        )
        self.mediator_agent = MediatorAgent(self.model, registry=self.registry)
        modeler_tools = []
        if enable_tools.get("plantuml_validate", True):
            from agents.tools import PlantUMLValidatorTool
            opts = config.get("plantuml_validate") or {}
            modeler_tools.append(
                PlantUMLValidatorTool(
                    jar_path=opts.get("jar_path", "plantuml.jar"),
                    use_online=opts.get("use_online", True),
                    server_url=opts.get("server_url", ""),
                )
            )
        self.modeler_agent = ModelerAgent(
            self.model, tools=modeler_tools, registry=self.registry
        )
        self.documentor_agent = DocumentorAgent(
            self.model,
            self.store,
            registry=self.registry,
        )

        for name, agent in [
            ("user", self.user_agent),
            ("analyst", self.analyst_agent),
            ("expert", self.expert_agent),
            ("mediator", self.mediator_agent),
            ("modeler", self.modeler_agent),
            ("documentor", self.documentor_agent),
        ]:
            if enable_agents.get(name, True):
                self.registry.register(name, agent)

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

        self.logger.info("=== Phase 0: 初始草稿建立 ===")
        artifact = self.run_init_phase(artifact)

        # 開會前產出需求衝突報告，供與會參考
        if artifact.get("conflicts"):
            self.logger.info("產出需求衝突報告")
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

        # 開會前產出需求衝突報告，供與會參考
        if artifact.get("conflicts"):
            self.logger.info("產出需求衝突報告")
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
        selected_indices = Collect.user_selection(proposed)
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

        self.logger.info("Analyst 執行衝突辨識")
        artifact = self.analyst_agent.run_conflict_detection(artifact)
        self.store.save_artifact(artifact)

        self.logger.info("Expert 提供領域知識")
        scope = artifact.get("scope", {})
        project_overview = scope.get("description") or ""
        injection = self.expert_agent.provide_domain_knowledge(
            artifact["requirements"],
            artifact["conflicts"],
            project_overview=project_overview,
        )
        if injection.get("feedback"):
            artifact.setdefault("feedback", {})
            artifact["feedback"].update(injection["feedback"])
        self.store.save_artifact(artifact)
        dr = artifact.get("feedback", {}).get("domain_research") or {}
        if dr and isinstance(dr, dict) and dr:
            self.logger.info("✓ 領域研究結果已寫入 artifact.feedback.domain_research")
        else:
            self.logger.info(
                "artifact.feedback.domain_research 已寫入但為空（domain-research skill 未產出或解析失敗）"
            )

        self.logger.info("Analyst 草稿化")
        draft_md = self.analyst_agent.create_draft(
            artifact,
            draft_version=0,
            recent_decisions_limit=self.config.get("agenda_items", 5),
        )
        self.store.save_draft(draft_md, version=0)
        self.logger.info(
            f"✓ Draft v0: {len(artifact['requirements'])} 條需求，{len(artifact.get('conflicts', []))} 個衝突"
        )

        meta = artifact.setdefault("meta", {})
        meta["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.store.save_artifact(artifact)

        return artifact

    # Round k: 開會

    def run_meeting_round(
        self, artifact: Dict[str, Any], round_num: int, skip_agenda: bool = False
    ) -> Dict[str, Any]:
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
            topic_id = params.get("topic_id")
            title_hint = ""
            category_hint = ""
            if topic_id:
                for t in state.get("topics", []):
                    if t.get("id") == topic_id:
                        title_hint = f" 《{t.get('title', '')}》"
                        category_hint = t.get("category_label") or t.get("category", "")
                        break
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

        # Step 5.1: Mediator 更新決策與衝突（含討論中提出的新增衝突，可補辨識漏報）
        self.logger.info("Step 5.1: Mediator 更新決策與衝突")
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
        # 討論中提出的新增衝突（漏報補正）：指派 id 後併入
        valid_conflict_types = set(ALLOWED_CONFLICT_TYPES)
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
                ctype = ""
            new_conflicts.append(
                {
                    "id": f"CF-{max_num + 1:02d}",
                    "label": "Conflict",
                    "description": nc.get("description", ""),
                    "conflict_type": ctype,
                    "requirement_ids": nc.get("requirement_ids", []),
                }
            )
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
                artifact["requirements"], prev_models
            )
        else:
            model_data = self.modeler_agent.generate_system_model(
                artifact["requirements"], artifact["stakeholders"]
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

        # Step 5.5: 只要有衝突列表就產出需求衝突報告（含已解決／未解決），每輪更新
        if artifact.get("conflicts"):
            self.logger.info("Step 5.5: 產出需求衝突報告（Analyst，Markdown）")
            conflict_md = self.analyst_agent.generate_conflict_report(
                artifact,
                round_num,
                recent_decisions_limit=self.config.get("agenda_items", 5),
            )
            self.store.save_markdown(conflict_md, "conflict_report.md")
            self.logger.info("  ✓ 已存 conflict_report.md")
        else:
            self.logger.info("Step 5.5: 無衝突資料，略過 conflict_report.md")

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
