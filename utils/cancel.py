from typing import Callable, Dict, Optional

_checkers: Dict[str, Callable[[], bool]] = {}


def register_cancel_checker(project_id: str, checker: Callable[[], bool]) -> None:
    _checkers[project_id] = checker


def clear_cancel_checker(project_id: str) -> None:
    _checkers.pop(project_id, None)


def is_cancelled(project_id: Optional[str]) -> bool:
    if not project_id:
        return False
    checker = _checkers.get(project_id)
    return bool(checker and checker())


def raise_if_cancelled(project_id: Optional[str]) -> None:
    if is_cancelled(project_id):
        raise RuntimeError("Run cancelled")
