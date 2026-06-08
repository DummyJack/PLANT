import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from fastapi import HTTPException

from server.services.artifact_service import ArtifactService
from server.services.config_service import validate_config
from server.services.human_decisions import parse_human_decision_response, parse_stakeholder_response
from server.services.project_service import ProjectService
from server.services.run_config import (
    apply_run_enable_agents,
    normalize_attached_reference_paths,
    resolve_run_rounds,
    validate_enable_agents,
)
from server.services.run_manager import RunManager, sse_done
from storage import Store
from server.services.run_persistence import RunPersistence
from utils.cancel import clear_cancel_checker, is_cancelled, register_cancel_checker, raise_if_cancelled


class RunConfigTests(unittest.TestCase):
    def test_resolve_rounds_for_general_formal_meeting(self):
        config = {"stage": {"general_formal_meeting": True}, "rounds": 3}
        self.assertEqual(resolve_run_rounds(config), 3)
        self.assertEqual(resolve_run_rounds(config, 2), 2)

    def test_resolve_rounds_requires_value_for_general_formal_meeting(self):
        config = {"stage": {"general_formal_meeting": True}}
        with self.assertRaises(ValueError):
            resolve_run_rounds(config)

    def test_apply_enable_agents_merges_override(self):
        config = {
            "enable_agents": {
                "user": True,
                "analyst": True,
                "expert": True,
                "mediator": True,
                "modeler": True,
                "documentor": True,
            }
        }
        result = apply_run_enable_agents(
            config,
            {"analyst": False, "expert": False, "mediator": False},
        )
        self.assertFalse(result["enable_agents"]["analyst"])
        self.assertFalse(result["enable_agents"]["expert"])
        self.assertTrue(result["enable_agents"]["user"])
        self.assertTrue(result["enable_agents"]["mediator"])

    def test_validate_enable_agents_rejects_unknown(self):
        with self.assertRaises(ValueError):
            validate_enable_agents({"unknown_agent": True})

    def test_normalize_attached_reference_paths(self):
        paths = normalize_attached_reference_paths(
            "proj123",
            ["spec.md", "doc/proj123/other.pdf", "spec.md", "../evil.txt"],
        )
        self.assertEqual(paths, ["proj123/spec.md", "proj123/other.pdf", "proj123/evil.txt"])


class ConfigServiceTests(unittest.TestCase):
    def test_validate_config_rejects_non_object(self):
        result = validate_config([])
        self.assertFalse(result["valid"])

    def test_validate_config_rejects_invalid_stage(self):
        config = {
            "agent_models": {"default": {"provider": "openai", "model": "gpt-4o-mini"}},
            "stage": "bad",
        }
        result = validate_config(config)
        self.assertFalse(result["valid"])
        self.assertTrue(any("stage" in err for err in result["errors"]))


class HumanDecisionTests(unittest.TestCase):
    def test_parse_structured_stakeholders(self):
        proposed = [{"name": "使用者", "type": "primary_user", "reason": "主要"}]
        result = parse_stakeholder_response(
            {
                "stakeholders": [
                    {"name": "系統管理員", "type": "system_owner", "reason": "使用者自訂"}
                ]
            },
            proposed,
            max_select=5,
        )
        self.assertEqual(result[0]["name"], "系統管理員")
        self.assertEqual(result[0]["type"], "system_owner")

    def test_parse_human_decision_choices(self):
        options = {
            "best_options": [{"title": "方案 A", "description": "說明 A"}],
            "compromise": {"title": "折衷方案", "description": "說明 C", "rationale": "理由"},
        }
        result = parse_human_decision_response({"choices": [1]}, options)
        self.assertEqual(result["status"], "human_decision")
        self.assertIn("方案 A", result["decision"])


class RunPersistenceTests(unittest.TestCase):
    def test_persist_state_and_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            persistence = RunPersistence(base_dir)
            run = {
                "run_id": "run_test1234",
                "project_id": "123456",
                "status": "running",
                "events": [{"id": 0, "type": "run_started", "message": "Run started"}],
            }
            persistence.save_state(run)
            persistence.append_event("123456", "run_test1234", run["events"][0])
            loaded = persistence.load_state("123456", "run_test1234")
            self.assertEqual(loaded["status"], "running")
            events = persistence.load_events("123456", "run_test1234")
            self.assertEqual(len(events), 1)

    def test_recover_interrupted_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            persistence = RunPersistence(base_dir)
            runs_dir = base_dir / "projects" / "123456" / "runs"
            runs_dir.mkdir(parents=True)
            state = {
                "run_id": "run_deadbeef",
                "project_id": "123456",
                "status": "running",
                "event_count": 1,
                "started_at": "2026-01-01T00:00:00",
            }
            (runs_dir / "run_deadbeef.json").write_text(
                json.dumps(state, ensure_ascii=False),
                encoding="utf-8",
            )
            recovered = persistence.recover_interrupted_runs()
            self.assertEqual(recovered, 1)
            updated = persistence.load_state("123456", "run_deadbeef")
            self.assertEqual(updated["status"], "interrupted")


class RunManagerTests(unittest.TestCase):
    def test_auto_export_skips_when_flow_already_exported(self):
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            manager = RunManager(base_dir)
            flow = MagicMock()
            flow.config = {"export": {"html": True, "cost": True}}
            with manager._lock:
                manager._runs["run_test"] = {
                    "run_id": "run_test",
                    "project_id": "123456",
                    "status": "running",
                    "events": [],
                }
            manager._auto_export_after_finish(
                "run_test",
                "123456",
                flow,
                output_exported_via_flow=True,
            )
            events = manager.events_since("run_test", 0)
            self.assertEqual(events[-1]["type"], "auto_export_completed")
            self.assertTrue(events[-1]["skipped"])

    def test_events_since_reads_persisted_jsonl_after_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            manager = RunManager(base_dir)
            persistence = RunPersistence(base_dir)
            persistence.append_event(
                "123456",
                "run_persist",
                {"id": 0, "type": "run_started", "message": "Run started"},
            )
            persistence.append_event(
                "123456",
                "run_persist",
                {"id": 1, "type": "log", "message": "hello"},
            )
            persistence.save_state(
                {
                    "run_id": "run_persist",
                    "project_id": "123456",
                    "status": "completed",
                    "events": [],
                }
            )
            events = manager.events_since("run_persist", 1)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["id"], 1)

    def test_sse_done_event(self):
        payload = sse_done("run_abc", "completed", next_event_id=3)
        self.assertIn("event: done", payload)
        self.assertIn("stream_done", payload)
        self.assertIn("run_abc", payload)

    def test_count_interrupted_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            persistence = RunPersistence(base_dir)
            runs_dir = base_dir / "projects" / "123456" / "runs"
            runs_dir.mkdir(parents=True)
            (runs_dir / "run_a.json").write_text(
                json.dumps({"run_id": "run_a", "project_id": "123456", "status": "interrupted"}),
                encoding="utf-8",
            )
            manager = RunManager(base_dir)
            self.assertEqual(manager.count_interrupted_runs(), 1)

    def test_prepare_artifact_for_run_updates_continue_rough_idea(self):
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            project_id = "123456"
            artifact_dir = base_dir / "projects" / project_id / "artifact"
            artifact_dir.mkdir(parents=True)
            (artifact_dir / "project.json").write_text(
                json.dumps({"rough_idea": "舊想法", "meta": {}}, ensure_ascii=False),
                encoding="utf-8",
            )
            (artifact_dir / "requirements.json").write_text(
                json.dumps({"URL": [], "REQ": []}, ensure_ascii=False),
                encoding="utf-8",
            )
            manager = RunManager(base_dir)
            store = Store(base_dir, project_id)
            artifact = manager._prepare_artifact_for_run(
                store,
                mode="continue",
                rough_idea="新想法",
                attached_reference_paths=["123456/spec.md"],
            )
            self.assertEqual(artifact["rough_idea"], "新想法")
            self.assertEqual(
                artifact["meta"]["attached_references"],
                ["123456/spec.md"],
            )
            reloaded = store.load_artifact() or {}
            self.assertEqual(reloaded["rough_idea"], "新想法")

    def test_submit_decision_sets_response(self):
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            manager = RunManager(base_dir)
            with manager._lock:
                manager._runs["run_test"] = {
                    "run_id": "run_test",
                    "project_id": "123456",
                    "status": "waiting_for_human",
                    "pending_decision": {"id": "decision_1"},
                    "events": [],
                    "_decision_event": __import__("threading").Event(),
                }
            result = manager.submit_decision(
                "run_test",
                "decision_1",
                {"decision": "採用方案 A", "choices": [1]},
            )
            self.assertEqual(result["status"], "running")
            with manager._lock:
                self.assertEqual(
                    manager._runs["run_test"].get("_decision_response"),
                    {"decision": "採用方案 A", "choices": [1]},
                )


class ProjectServiceTests(unittest.TestCase):
    def test_list_projects_enriched(self):
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            project_id = "123456"
            project_dir = base_dir / "projects" / project_id / "artifact"
            project_dir.mkdir(parents=True)
            (project_dir / "project.json").write_text(
                json.dumps({"rough_idea": "測試系統"}, ensure_ascii=False),
                encoding="utf-8",
            )
            results_dir = base_dir / "projects" / project_id / "results"
            results_dir.mkdir(parents=True)
            (results_dir / "srs.html").write_text("<html></html>", encoding="utf-8")

            run_manager = MagicMock()
            run_manager.get_active_run.return_value = None
            run_manager.list_runs.return_value = [{"status": "completed"}]
            service = ProjectService(base_dir, run_manager=run_manager)
            rows = service.list_projects_enriched()
            self.assertEqual(rows[0]["project_id"], project_id)
            self.assertTrue(rows[0]["has_results"])
            self.assertEqual(rows[0]["status_hint"], "completed")

    def test_get_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            project_id = "123456"
            project_dir = base_dir / "projects" / project_id / "artifact"
            project_dir.mkdir(parents=True)
            (project_dir / "project.json").write_text(
                json.dumps({"rough_idea": "測試系統", "meta": {"last_round": 1}}, ensure_ascii=False),
                encoding="utf-8",
            )
            service = ProjectService(base_dir)
            summary = service.get_summary(project_id)
            self.assertEqual(summary["rough_idea"], "測試系統")
            self.assertEqual(summary["user_requirement_count"], 0)


class ArtifactServiceTests(unittest.TestCase):
    def test_write_blocked_during_active_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            project_id = "123456"
            artifact_dir = base_dir / "projects" / project_id / "artifact"
            artifact_dir.mkdir(parents=True)
            target = artifact_dir / "requirements.json"
            target.write_text("{}", encoding="utf-8")

            run_manager = MagicMock()
            run_manager.get_active_run.return_value = {"status": "running"}
            service = ArtifactService(base_dir, run_manager=run_manager)

            with self.assertRaises(HTTPException) as ctx:
                service.write_file(project_id, "artifact/requirements.json", "{}")
            self.assertEqual(ctx.exception.status_code, 409)


class CancelRegistryTests(unittest.TestCase):
    def test_cancel_registry(self):
        register_cancel_checker("p1", lambda: True)
        self.assertTrue(is_cancelled("p1"))
        with self.assertRaises(RuntimeError):
            raise_if_cancelled("p1")
        clear_cancel_checker("p1")
        self.assertFalse(is_cancelled("p1"))


if __name__ == "__main__":
    unittest.main()
