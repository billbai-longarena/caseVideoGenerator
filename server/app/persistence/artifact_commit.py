from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from server.app.persistence.object_store import (
    ObjectMetadata,
    ObjectStore,
    object_key_for_artifact,
    sha256_file,
)
from server.app.persistence.repository import (
    ArtifactBundleRegistration,
    BlobRegistration,
    PhaseCRepository,
    sha256_json,
)


class ArtifactCommitError(RuntimeError):
    pass


class ArtifactCommitInjectedFailure(ArtifactCommitError):
    pass


FailureHook = Callable[[str], None]


@dataclass(frozen=True)
class ArtifactSource:
    logical_name: str
    path: Path
    media_type: str | None = None


class ArtifactCommitService:
    """Two-phase object upload and authoritative database registration.

    Pending object keys are immutable and may remain the official keys after
    commit. Database registration is the promotion boundary.
    """

    def __init__(self, repository: PhaseCRepository, object_store: ObjectStore) -> None:
        self.repository = repository
        self.object_store = object_store

    def commit(
        self,
        *,
        tenant_id: str,
        job_id: str,
        domain: str,
        revision_id: str,
        sources: list[ArtifactSource],
        created_by: str,
        parent_id: str | None = None,
        stage_run_id: str | None = None,
        make_current: bool = True,
        manifest: dict[str, object] | None = None,
        expected_job_version: int | None = None,
        invalidated_stages: Sequence[str] = (),
        event: Mapping[str, Any] | None = None,
        audit: Mapping[str, Any] | None = None,
        failure_hook: FailureHook | None = None,
    ) -> dict[str, object]:
        bundle = self.stage_bundle(
            tenant_id=tenant_id,
            job_id=job_id,
            domain=domain,
            revision_id=revision_id,
            sources=sources,
            created_by=created_by,
            parent_id=parent_id,
            make_current=make_current,
            failure_hook=failure_hook,
        )
        self._fire(failure_hook, "before_db_commit")
        result = self.repository.commit_artifact_bundle(
            tenant_id,
            job_id,
            domain=domain,
            revision_id=revision_id,
            parent_id=parent_id,
            stage_run_id=stage_run_id,
            created_by=bundle.created_by,
            blobs=bundle.blobs,
            revision_hash=bundle.revision_hash,
            make_current=bundle.make_current,
            manifest=manifest,
            expected_job_version=expected_job_version,
            invalidated_stages=invalidated_stages,
            event=event,
            audit=audit,
        )
        self._fire(failure_hook, "after_db_commit")
        return result

    def stage_bundle(
        self,
        *,
        tenant_id: str,
        job_id: str,
        domain: str,
        revision_id: str,
        sources: list[ArtifactSource],
        created_by: str,
        parent_id: str | None = None,
        make_current: bool = True,
        failure_hook: FailureHook | None = None,
    ) -> ArtifactBundleRegistration:
        """Upload and verify immutable objects without promoting them in SQL."""

        if not sources:
            raise ArtifactCommitError("at least one artifact is required")
        names = [source.logical_name for source in sources]
        if len(set(names)) != len(names):
            raise ArtifactCommitError("artifact logical names must be unique")
        ordered = sorted(sources, key=lambda item: item.logical_name)
        uploaded: list[ObjectMetadata] = []
        for source in ordered:
            content_sha256 = sha256_file(source.path)
            # The database revision keeps the stable logical artifact name, while
            # the immutable object key is content addressed. A retry after an
            # ambiguous SQL commit can therefore upload changed bytes without
            # colliding with an orphan left by the prior attempt.
            object_name = f"blobs/{content_sha256}/{source.logical_name}"
            key = object_key_for_artifact(tenant_id, job_id, revision_id, object_name)
            media_type = source.media_type or mimetypes.guess_type(source.path.name)[0]
            uploaded.append(self.object_store.put_file(key, source.path, media_type=media_type))
        self._fire(failure_hook, "after_upload")

        registrations: list[BlobRegistration] = []
        for source, uploaded_item in zip(ordered, uploaded):
            verified = self.object_store.head(uploaded_item.key)
            if verified.sha256 != uploaded_item.sha256 or verified.size_bytes != uploaded_item.size_bytes:
                raise ArtifactCommitError(f"uploaded object verification failed: {uploaded_item.key}")
            registrations.append(
                BlobRegistration(
                    logical_name=source.logical_name,
                    object_key=verified.key,
                    size_bytes=verified.size_bytes,
                    sha256=verified.sha256,
                    media_type=verified.media_type,
                    scan_status="clean",
                )
            )
        revision_hash = sha256_json(
            {
                "domain": domain,
                "parent_id": parent_id,
                "artifacts": [
                    {
                        "logical_name": item.logical_name,
                        "sha256": item.sha256,
                        "size_bytes": item.size_bytes,
                        "media_type": item.media_type,
                    }
                    for item in registrations
                ],
            }
        )
        return ArtifactBundleRegistration(
            domain=domain,
            revision_id=revision_id,
            parent_id=parent_id,
            created_by=created_by,
            blobs=tuple(registrations),
            revision_hash=revision_hash,
            make_current=make_current,
        )

    def cleanup_orphans(
        self,
        *,
        older_than: datetime,
        prefix: str = "tenants",
    ) -> list[str]:
        referenced = self.repository.referenced_object_keys()
        removed: list[str] = []
        for item in self.object_store.list(prefix):
            modified = item.modified_at
            if modified.tzinfo is None:
                modified = modified.replace(tzinfo=timezone.utc)
            if item.key not in referenced and modified <= older_than:
                self.object_store.delete(item.key)
                removed.append(item.key)
        return removed

    def cleanup_orphans_by_ttl(self, *, ttl_seconds: int, now: datetime | None = None) -> list[str]:
        current = now or datetime.now(timezone.utc)
        return self.cleanup_orphans(older_than=current - timedelta(seconds=ttl_seconds))

    @staticmethod
    def _fire(hook: FailureHook | None, point: str) -> None:
        if hook is not None:
            hook(point)


def fail_at(point: str) -> FailureHook:
    def hook(current: str) -> None:
        if current == point:
            raise ArtifactCommitInjectedFailure(f"injected failure at {point}")

    return hook
