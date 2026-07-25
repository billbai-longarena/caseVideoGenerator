from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from server.app.services.model_gateway import ModelGateway, ModelGatewayError
from server.app.services.queue import JobQueue
from server.app.services.storage import JobStorage


router = APIRouter()


def get_storage(request: Request) -> JobStorage:
    return request.app.state.storage


def get_queue(request: Request) -> JobQueue:
    return request.app.state.queue


def get_gateway(request: Request) -> ModelGateway:
    return request.app.state.model_gateway


@router.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
def ready(
    request: Request,
    storage: JobStorage = Depends(get_storage),
    queue: JobQueue = Depends(get_queue),
    gateway: ModelGateway = Depends(get_gateway),
) -> dict[str, object]:
    checks: dict[str, object] = {
        "storage": storage.root.exists(),
        "queue": queue.__class__.__name__,
        "dry_run": request.app.state.settings.dry_run,
    }
    try:
        gateway.validate_required_routes()
        checks["model_routes"] = "configured"
    except ModelGatewayError as exc:
        checks["model_routes"] = {"status": "failed", "code": exc.code, "message": exc.message}
    status = "ok" if checks["storage"] and checks["model_routes"] == "configured" else "degraded"
    return {"status": status, "checks": checks}
