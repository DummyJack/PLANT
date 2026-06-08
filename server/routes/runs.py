import asyncio
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from storage import Store
from server.services.run_config import general_formal_meeting_enabled
from server.services.run_manager import sse_done, sse_format, sse_heartbeat


router = APIRouter()


class RunCreate(BaseModel):
    project_id: str
    mode: str = "continue"
    rounds: Optional[int] = None
    rough_idea: Optional[str] = None
    attached_reference_paths: Optional[List[str]] = None
    enable_agents: Optional[Dict[str, bool]] = None


class DecisionSubmit(BaseModel):
    payload: Dict[str, Any] = {}


def manager(request: Request):
    return request.app.state.run_manager


@router.get("/runs")
def list_runs(request: Request, project_id: Optional[str] = Query(default=None)):
    return {"runs": manager(request).list_runs(project_id=project_id)}


@router.post("/runs")
def create_run(payload: RunCreate, request: Request):
    if payload.mode not in {"new", "continue"}:
        raise HTTPException(status_code=400, detail="mode must be new or continue")
    try:
        config = Store(request.app.state.base_dir).load_config()
        if general_formal_meeting_enabled(config) and payload.rounds is None:
            raise HTTPException(
                status_code=400,
                detail="rounds is required when general_formal_meeting is enabled",
            )
        return manager(request).start_run(
            project_id=payload.project_id,
            mode=payload.mode,
            rounds=payload.rounds,
            rough_idea=payload.rough_idea,
            attached_reference_paths=payload.attached_reference_paths,
            enable_agents=payload.enable_agents,
            config=config,
        )
    except ValueError as exc:
        message = str(exc)
        status_code = 409 if "active run" in message else 400
        raise HTTPException(status_code=status_code, detail=message) from exc


@router.get("/runs/{run_id}")
def get_run(run_id: str, request: Request):
    run = manager(request).get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.get("/runs/{run_id}/events")
async def run_events(run_id: str, request: Request, since: int = 0):
    if not manager(request).get(run_id):
        raise HTTPException(status_code=404, detail="Run not found")

    async def stream():
        index = max(0, int(since))
        idle = 0
        heartbeat = 0
        while True:
            events = manager(request).events_since(run_id, index)
            for event in events:
                index = int(event["id"]) + 1
                yield sse_format(event)
                heartbeat = 0
            run = manager(request).get(run_id)
            if run and run.get("status") in {"completed", "failed", "cancelled", "interrupted"} and not events:
                idle += 1
                if idle > 2:
                    final_status = str(run.get("status") or "unknown")
                    next_event_id = manager(request).final_event_index(run_id)
                    yield sse_done(run_id, final_status, next_event_id=next_event_id)
                    break
            heartbeat += 1
            if heartbeat >= 15:
                yield sse_heartbeat()
                heartbeat = 0
            await asyncio.sleep(1)

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.post("/runs/{run_id}/decisions/{decision_id}")
def submit_decision(run_id: str, decision_id: str, payload: DecisionSubmit, request: Request):
    try:
        return manager(request).submit_decision(run_id, decision_id, payload.payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/runs/{run_id}/cancel")
def cancel_run(run_id: str, request: Request):
    try:
        return manager(request).cancel(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc
