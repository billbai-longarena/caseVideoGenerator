from __future__ import annotations

from fastapi import APIRouter, Request

from server.app.services.uploads import ALLOWED_EXTENSIONS


router = APIRouter()


@router.get("/v1/capabilities")
def capabilities(request: Request) -> dict[str, object]:
    settings = request.app.state.settings
    return {
        "upload": {
            "allowed_extensions": sorted(ALLOWED_EXTENSIONS),
            "max_file_bytes": settings.max_upload_bytes,
            "max_files": settings.max_upload_files,
        },
        "job": {
            "input_modes": ["source", "structured", "project"],
            "approval_modes": ["editorial", "auto", "full"],
            "default_duration_seconds": {"min": 240, "max": 420},
        },
        "model_routes": settings.public_model_routes(),
        "model_overrides_allowed": False,
    }
