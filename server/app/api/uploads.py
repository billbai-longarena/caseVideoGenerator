from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response

from server.app.models.job import CreateUploadRequest, UploadRecord
from server.app.services.uploads import UploadStorage


router = APIRouter()


def get_uploads(request: Request) -> UploadStorage:
    return request.app.state.uploads


def public_upload(record: dict[str, object], *, include_url: bool = False) -> dict[str, object]:
    payload = {
        "upload_id": record["upload_id"],
        "filename": record["filename"],
        "safe_name": record["safe_name"],
        "declared_size_bytes": record["declared_size_bytes"],
        "size_bytes": record.get("size_bytes"),
        "declared_media_type": record.get("declared_media_type"),
        "detected_media_type": record.get("detected_media_type"),
        "sha256": record.get("sha256"),
        "status": record["status"],
        "max_size_bytes": record["max_size_bytes"],
        "created_at": record["created_at"],
        "expires_at": record["expires_at"],
        "bound_job_id": record.get("bound_job_id"),
        "upload_url": f"/v1/uploads/{record['upload_id']}" if include_url else None,
    }
    return UploadRecord(**payload).model_dump()


@router.post("/v1/uploads", response_model=UploadRecord, status_code=201)
def create_upload(
    request: CreateUploadRequest,
    uploads: UploadStorage = Depends(get_uploads),
) -> dict[str, object]:
    return public_upload(uploads.create(request), include_url=True)


@router.put("/v1/uploads/{upload_id}", response_model=UploadRecord)
async def put_upload(
    upload_id: str,
    request: Request,
    uploads: UploadStorage = Depends(get_uploads),
) -> dict[str, object]:
    record = await uploads.put(upload_id, request.stream())
    return public_upload(record)


@router.get("/v1/uploads/{upload_id}", response_model=UploadRecord)
def get_upload(upload_id: str, uploads: UploadStorage = Depends(get_uploads)) -> dict[str, object]:
    return public_upload(uploads.get(upload_id))


@router.delete("/v1/uploads/{upload_id}", status_code=204)
def delete_upload(upload_id: str, uploads: UploadStorage = Depends(get_uploads)) -> Response:
    uploads.delete(upload_id)
    return Response(status_code=204)
