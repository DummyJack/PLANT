import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from storage.atomic import atomic_write_text

ACTIVE_STATUSES = {"queued", "running", "waiting_for_human", "cancelling"}


INTERNAL_KEYS = {"events", "config_snapshot"}
INTERNAL_PREFIX = "_"


class RunPersistence:
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir

    def runs_dir(self, project_id: str) -> Path:
        return self.base_dir / "projects" / project_id / "runs"

    def run_dir(self, project_id: str, run_id: str) -> Path:
        return self.runs_dir(project_id) / run_id

    def state_path(self, project_id: str, run_id: str) -> Path:
        return self.run_dir(project_id, run_id) / "state.json"

    def events_path(self, project_id: str, run_id: str) -> Path:
        return self.run_dir(project_id, run_id) / "events.jsonl"

    def public_state(self, run: Dict[str, Any]) -> Dict[str, Any]:
        return {
            key: value
            for key, value in run.items()
            if key not in INTERNAL_KEYS and not key.startswith(INTERNAL_PREFIX)
        } | {"event_count": len(run.get("events", []))}

    def save_state(self, run: Dict[str, Any]) -> None:
        project_id = str(run.get("project_id") or "").strip()
        run_id = str(run.get("run_id") or "").strip()
        if not project_id or not run_id:
            return
        path = self.state_path(project_id, run_id)
        payload = self.public_state(run)
        atomic_write_text(
            path,
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def append_event(self, project_id: str, run_id: str, event: Dict[str, Any]) -> None:
        path = self.events_path(project_id, run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")

    def load_events(self, project_id: str, run_id: str, since: int = 0) -> List[Dict[str, Any]]:
        path = self.events_path(project_id, run_id)
        if not path.exists():
            return []
        events: List[Dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return [event for event in events if int(event.get("id", -1)) >= since]

    def list_runs(self, project_id: Optional[str] = None) -> List[Dict[str, Any]]:
        projects_root = self.base_dir / "projects"
        if not projects_root.exists():
            return []

        project_dirs = [projects_root / project_id] if project_id else sorted(projects_root.iterdir())
        runs: List[Dict[str, Any]] = []
        for project_path in project_dirs:
            if not project_path.is_dir():
                continue
            runs_dir = project_path / "runs"
            if not runs_dir.exists():
                continue
            state_files = list(runs_dir.glob("run_*/state.json"))
            for state_file in sorted(state_files):
                try:
                    row = json.loads(state_file.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict):
                    runs.append(row)
        runs.sort(key=lambda item: (item.get("started_at", ""), item.get("run_id", "")), reverse=True)
        return runs

    def count_runs_by_status(self, status: str) -> int:
        return sum(1 for run in self.list_runs() if str(run.get("status") or "") == status)

    def recover_interrupted_runs(self) -> int:
        recovered = 0
        for run in self.list_runs():
            status = str(run.get("status") or "")
            if status not in ACTIVE_STATUSES:
                continue
            project_id = str(run.get("project_id") or "")
            run_id = str(run.get("run_id") or "")
            if not project_id or not run_id:
                continue
            run["status"] = "interrupted"
            run["finished_at"] = datetime.now().isoformat()
            run["error"] = run.get("error") or "Server restarted while run was active"
            self.save_state(run)
            self.append_event(
                project_id,
                run_id,
                {
                    "id": int(run.get("event_count") or 0),
                    "type": "run_interrupted",
                    "message": run["error"],
                    "timestamp": datetime.now().isoformat(),
                },
            )
            recovered += 1
        return recovered
