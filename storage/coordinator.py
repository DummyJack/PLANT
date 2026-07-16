import json
import os
import shutil
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from .atomic import atomic_write_text


OWNER_WRITE_GRACE_SECONDS = 5.0
MIN_LOCK_STALE_SECONDS = 300.0
_LOCAL_LOCKS_GUARD = threading.Lock()
_LOCAL_LOCKS: Dict[str, Dict[str, Any]] = {}


class FileRunCoordinator:
    """Cross-process coordination for runs on one local filesystem."""

    def __init__(self, base_dir: Path):
        base_path = Path(base_dir)
        if base_path.parent.name == "projects":
            self.root = base_path / "runs" / ".runtime"
        else:
            self.root = base_path / "projects" / ".runtime"
        self.claims_dir = self.root / "active-projects"
        self.runs_dir = self.root / "runs"
        self.claims_dir.mkdir(parents=True, exist_ok=True)
        self.runs_dir.mkdir(parents=True, exist_ok=True)

    def claim_project(self, project_id: str, run_id: str, *, _retry: bool = True) -> bool:
        claim_dir = self.claims_dir / project_id
        try:
            claim_dir.mkdir(parents=False, exist_ok=False)
        except FileExistsError:
            owner = self.claim_owner(project_id)
            try:
                owner_pid = int(owner.get("pid") or 0)
            except (TypeError, ValueError):
                owner_pid = 0
            owner_run_id = str(owner.get("run_id") or "")
            owner_dead = owner_pid > 0 and not self._pid_alive(owner_pid)
            owner_missing = owner_pid <= 0 and self._directory_age_seconds(claim_dir) > OWNER_WRITE_GRACE_SECONDS
            if _retry and (owner_dead or owner_missing):
                self.release_project(project_id, owner_run_id or run_id)
                return self.claim_project(project_id, run_id, _retry=False)
            return False
        owner = {
            "project_id": project_id,
            "run_id": run_id,
            "pid": os.getpid(),
            "claimed_at": datetime.now().isoformat(),
            "heartbeat_at": datetime.now().isoformat(),
        }
        try:
            atomic_write_text(
                claim_dir / "owner.json",
                json.dumps(owner, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            try:
                claim_dir.rmdir()
            except OSError:
                pass
            raise
        return True

    def claim_owner(self, project_id: str) -> Dict[str, Any]:
        path = self.claims_dir / project_id / "owner.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        if pid <= 0:
            return False
        if os.name == "nt":
            import ctypes

            process_query_limited_information = 0x1000
            still_active = 259
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(
                process_query_limited_information,
                False,
                pid,
            )
            if not handle:
                return False
            try:
                exit_code = ctypes.c_ulong()
                if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                    return False
                return int(exit_code.value) == still_active
            finally:
                kernel32.CloseHandle(handle)
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True

    @staticmethod
    def _directory_age_seconds(path: Path) -> float:
        try:
            return max(0.0, time.time() - path.stat().st_mtime)
        except OSError:
            return 0.0

    def claim_is_alive(self, project_id: str, run_id: str) -> bool:
        owner = self.claim_owner(project_id)
        if str(owner.get("run_id") or "") != run_id:
            return False
        try:
            pid = int(owner.get("pid") or 0)
        except (TypeError, ValueError):
            return False
        if not self._pid_alive(pid):
            return False
        # Process liveness owns the claim. Heartbeats are diagnostic only: a busy
        # but still-running worker must never be reclaimed by another process.
        return True

    def heartbeat(self, project_id: str, run_id: str) -> bool:
        owner = self.claim_owner(project_id)
        if str(owner.get("run_id") or "") != run_id:
            return False
        owner["heartbeat_at"] = datetime.now().isoformat()
        atomic_write_text(
            self.claims_dir / project_id / "owner.json",
            json.dumps(owner, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return True

    def release_project(self, project_id: str, run_id: str) -> None:
        claim_dir = self.claims_dir / project_id
        owner = self.claim_owner(project_id)
        if owner and str(owner.get("run_id") or "") != run_id:
            return
        for child in claim_dir.glob("*") if claim_dir.exists() else []:
            if child.is_file():
                child.unlink(missing_ok=True)
        try:
            claim_dir.rmdir()
        except OSError:
            pass

    def _run_dir(self, run_id: str) -> Path:
        path = self.runs_dir / run_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def submit_decision(
        self,
        run_id: str,
        decision_id: str,
        payload: Dict[str, Any],
        payload_hash: str,
    ) -> bool:
        decision_dir = self._run_dir(run_id) / "decisions"
        decision_dir.mkdir(parents=True, exist_ok=True)
        target = decision_dir / f"{decision_id}.response.json"
        body = {
            "decision_id": decision_id,
            "payload_hash": payload_hash,
            "payload": payload,
            "accepted_at": datetime.now().isoformat(),
        }
        encoded = json.dumps(body, ensure_ascii=False, indent=2)
        try:
            fd = os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        except FileExistsError:
            existing = self.read_decision(run_id, decision_id) or {}
            if existing.get("payload_hash") == payload_hash:
                return False
            raise FileExistsError("decision already has a different response")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        return True

    def read_decision(self, run_id: str, decision_id: str) -> Optional[Dict[str, Any]]:
        path = self.runs_dir / run_id / "decisions" / f"{decision_id}.response.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def request_cancel(self, run_id: str) -> None:
        atomic_write_text(
            self._run_dir(run_id) / "cancel.request",
            datetime.now().isoformat(),
            encoding="utf-8",
        )

    def cancel_requested(self, run_id: str) -> bool:
        return (self.runs_dir / run_id / "cancel.request").exists()

    def cleanup_run(self, run_id: str) -> None:
        shutil.rmtree(self.runs_dir / run_id, ignore_errors=True)

    def snapshot_decision_references(
        self,
        run_id: str,
        decision_id: str,
        project_id: str,
        payload: Dict[str, Any],
    ) -> list[Dict[str, Any]]:
        components = (run_id, decision_id, project_id)
        if any(not value or Path(value).name != value for value in components):
            raise ValueError("Invalid human input attachment context")

        names: list[str] = []

        def collect(value: Any) -> None:
            if isinstance(value, dict):
                references = value.get("references")
                if isinstance(references, list):
                    for reference in references:
                        if not isinstance(reference, dict):
                            continue
                        name = str(reference.get("name") or "").strip()
                        if name and name not in names:
                            names.append(name)
                for nested in value.values():
                    collect(nested)
            elif isinstance(value, list):
                for nested in value:
                    collect(nested)

        collect(payload)
        if not names:
            return []

        base_dir = self.root.parent.parent
        source_dir = base_dir / "doc" / project_id
        relative_dir = Path(project_id) / ".human-inputs" / run_id / decision_id
        destination_dir = base_dir / "doc" / relative_dir
        attachments: list[Dict[str, Any]] = []
        with self.exclusive_lock(f"human-inputs-{run_id}-{decision_id}", timeout=30.0):
            destination_dir.mkdir(parents=True, exist_ok=True)
            for name in names:
                if Path(name).name != name:
                    raise ValueError(f"Invalid referenced file name: {name}")
                source = source_dir / name
                if not source.is_file():
                    raise ValueError(f"Referenced file not found: {name}")
                destination = destination_dir / name
                shutil.copy2(source, destination)
                attachments.append(
                    {
                        "name": name,
                        "path": (relative_dir / name).as_posix(),
                        "size": destination.stat().st_size,
                        "run_id": run_id,
                        "decision_id": decision_id,
                    }
                )
        return attachments

    def promote_pending_references(self, project_id: str) -> list[str]:
        if not project_id or Path(project_id).name != project_id:
            raise ValueError("Invalid project id for pending references")
        base_dir = self.root.parent.parent
        references_dir = base_dir / "doc" / project_id
        pending_dir = references_dir / ".pending"
        if not pending_dir.exists():
            return []
        promoted: list[str] = []
        with self.exclusive_lock(f"reference-upload-{project_id}", timeout=30.0):
            for source in sorted(pending_dir.iterdir()):
                if not source.is_file():
                    continue
                destination = references_dir / source.name
                if destination.exists():
                    continue
                os.replace(source, destination)
                promoted.append(source.name)
            try:
                pending_dir.rmdir()
            except OSError:
                pass
        return promoted

    def cleanup_expired_project_creations(self, *, max_age_days: int = 7) -> None:
        root = self.root / "project-creations"
        cutoff = time.time() - max_age_days * 24 * 60 * 60
        for path in root.glob("*.json") if root.exists() else []:
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink(missing_ok=True)
            except OSError:
                continue

    def project_creation(self, creation_id: str) -> Optional[Dict[str, Any]]:
        path = self.root / "project-creations" / f"{creation_id}.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def record_project_creation(self, creation_id: str, project_id: str, rough_idea: str) -> None:
        path = self.root / "project-creations" / f"{creation_id}.json"
        atomic_write_text(
            path,
            json.dumps(
                {"creation_id": creation_id, "project_id": project_id, "rough_idea": rough_idea},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    @contextmanager
    def exclusive_lock(self, name: str, *, timeout: float = 5.0):
        key = str((self.root / "locks" / name).resolve())
        with _LOCAL_LOCKS_GUARD:
            entry = _LOCAL_LOCKS.setdefault(key, {"lock": threading.Lock(), "users": 0})
            entry["users"] += 1
            local_lock = entry["lock"]
        acquired = local_lock.acquire(timeout=timeout)
        if not acquired:
            with _LOCAL_LOCKS_GUARD:
                entry["users"] -= 1
                if entry["users"] == 0:
                    _LOCAL_LOCKS.pop(key, None)
            raise TimeoutError(f"Timed out acquiring local file lock: {name}")
        try:
            with self._exclusive_file_lock(name, timeout=timeout):
                yield
        finally:
            local_lock.release()
            with _LOCAL_LOCKS_GUARD:
                entry["users"] -= 1
                if entry["users"] == 0 and not local_lock.locked():
                    _LOCAL_LOCKS.pop(key, None)

    @contextmanager
    def _exclusive_file_lock(self, name: str, *, timeout: float = 5.0):
        lock_dir = self.root / "locks" / name
        lock_dir.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + timeout
        stale_after = max(MIN_LOCK_STALE_SECONDS, timeout * 2)
        lock_id = uuid.uuid4().hex
        while True:
            try:
                lock_dir.mkdir(exist_ok=False)
                atomic_write_text(
                    lock_dir / "owner.json",
                    json.dumps(
                        {
                            "lock_id": lock_id,
                            "pid": os.getpid(),
                            "created_at": datetime.now().isoformat(),
                        }
                    ),
                    encoding="utf-8",
                )
                break
            except FileExistsError:
                owner = {}
                try:
                    owner = json.loads((lock_dir / "owner.json").read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    pass
                try:
                    owner_pid = int(owner.get("pid") or 0)
                except (TypeError, ValueError):
                    owner_pid = 0
                lock_age = self._directory_age_seconds(lock_dir)
                owner_dead = owner_pid > 0 and not self._pid_alive(owner_pid)
                owner_missing = owner_pid <= 0 and lock_age > OWNER_WRITE_GRACE_SECONDS
                owner_expired = owner_pid > 0 and lock_age > stale_after
                if owner_dead or owner_missing or owner_expired:
                    for child in lock_dir.glob("*"):
                        child.unlink(missing_ok=True)
                    try:
                        lock_dir.rmdir()
                    except OSError:
                        pass
                    continue
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"Timed out acquiring file lock: {name}")
                time.sleep(0.025)
        try:
            yield
        finally:
            owner = {}
            try:
                owner = json.loads((lock_dir / "owner.json").read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
            if str(owner.get("lock_id") or "") == lock_id:
                for child in lock_dir.glob("*") if lock_dir.exists() else []:
                    child.unlink(missing_ok=True)
                try:
                    lock_dir.rmdir()
                except OSError:
                    pass
