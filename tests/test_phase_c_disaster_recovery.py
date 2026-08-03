from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from server.app.operations.backup import (
    BackupService,
    BackupVerificationError,
    RestoreConfirmationError,
    RestoreService,
    verify_backup,
)
from server.app.persistence.artifact_commit import ArtifactCommitService, ArtifactSource
from server.app.persistence.database import Database, SCHEMA_VERSION
from server.app.persistence.object_store import LocalObjectStore
from server.app.persistence.repository import PhaseCRepository, StageIdentity
from server.app.services.streams import InMemoryStreamsBroker, OutboxDispatcher, queue_for_stage


def manifest(job_id: str) -> dict[str, object]:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "manifest_version": 2,
        "job_id": job_id,
        "project_name": job_id,
        "status": "created",
        "display_status": "已创建",
        "stage": "created",
        "input_mode": "source",
        "approval_mode": "editorial",
        "created_at": now,
        "updated_at": now,
        "model_routes": {
            "narration": {"provider": "azure_anthropic", "model": "case-video-claude"},
            "remotion": {"provider": "azure_anthropic", "model": "case-video-claude"},
            "general": {"provider": "openai", "model": "gpt-5.5"},
        },
    }


def create_stage(repository: PhaseCRepository, job_id: str) -> dict[str, object]:
    run, reused = repository.create_stage_run(
        StageIdentity(
            tenant_id="ten_a",
            job_id=job_id,
            stage="case.model",
            input_hash="a" * 64,
            route_snapshot_hash="b" * 64,
            config_snapshot_hash="c" * 64,
        ),
        queue_name=queue_for_stage("case.model"),
    )
    assert reused is False
    return run


def test_backup_restore_verifies_objects_and_rebuilds_empty_redis(tmp_path: Path) -> None:
    source_database = Database(f"sqlite+pysqlite:///{tmp_path / 'source.sqlite'}")
    source_database.migrate()
    source_repository = PhaseCRepository(source_database)
    source_repository.ensure_tenant("ten_a", name="Tenant A")
    source_store = LocalObjectStore(tmp_path / "source-objects")

    source_repository.create_job("ten_a", manifest("job_artifact"))
    title = tmp_path / "title.txt"
    title.write_text("恢复演练标题", encoding="utf-8")
    ArtifactCommitService(source_repository, source_store).commit(
        tenant_id="ten_a",
        job_id="job_artifact",
        domain="editorial",
        revision_id="rev_editorial_1",
        sources=[ArtifactSource("title.txt", title, "text/plain")],
        created_by="usr_test",
    )

    source_repository.create_job("ten_a", manifest("job_queued"))
    queued_run = create_stage(source_repository, "job_queued")
    source_repository.create_job("ten_a", manifest("job_running"))
    running_run = create_stage(source_repository, "job_running")

    # Simulate a healthy pre-disaster dispatcher. Its Redis contents are then
    # deliberately discarded; only PostgreSQL and object backup are restored.
    source_broker = InMemoryStreamsBroker()
    source_dispatcher = OutboxDispatcher(source_repository, source_broker)
    assert source_dispatcher.dispatch_batch(limit=1000)["failed"] == 0
    claimed = source_repository.claim_stage_run(
        "ten_a",
        str(running_run["stage_run_id"]),
        worker_id="worker_lost_in_disaster",
        lease_seconds=3600,
    )
    assert claimed["claim"] == "claimed"

    backup_dir = tmp_path / "backups" / "drill-20260724"
    backup = BackupService(source_database, source_store).create(
        backup_dir,
        backup_id="drill-20260724",
    )
    assert backup["schema_version"] == SCHEMA_VERSION
    assert backup["summary"]["object_count"] == 1
    source_database.dispose()

    target_database_url = f"sqlite+pysqlite:///{tmp_path / 'restored.sqlite'}"
    target_store = LocalObjectStore(tmp_path / "restored-objects")
    empty_broker = InMemoryStreamsBroker()
    report = RestoreService(
        target_database_url=target_database_url,
        target_store=target_store,
        broker=empty_broker,
        max_attempts=3,
    ).restore(backup_dir, confirmation="RESTORE drill-20260724")

    assert report["schema_version"] == SCHEMA_VERSION
    assert report["object_references"]["errors"] == []
    assert report["object_references"]["verified_count"] == 1
    assert report["queue_recovery"]["expired_leases"] == 1
    assert len(report["queue_recovery"]["recovered"]) == 1
    assert report["queue_recovery"]["failed"] == 0
    assert report["rpo_pass"] is True
    assert report["rto_pass"] is True

    restored_database = Database(target_database_url)
    try:
        assert restored_database.check_schema() == SCHEMA_VERSION
        restored_repository = PhaseCRepository(restored_database)
        assert restored_repository.consistency_snapshot("ten_a", "job_artifact")["artifact_count"] == 1
        assert restored_repository.get_stage_run(
            "ten_a", str(queued_run["stage_run_id"])
        )["status"] == "queued"
        restored_running = restored_repository.get_stage_run(
            "ten_a", str(running_run["stage_run_id"])
        )
        assert restored_running["status"] == "lease_expired"
    finally:
        restored_database.dispose()

    queued_messages = empty_broker.records("planning")
    assert len(queued_messages) == 2
    assert {record.stage_message.job_id for record in queued_messages} == {
        "job_queued",
        "job_running",
    }


def test_restore_requires_exact_confirmation_and_backup_hashes_are_enforced(tmp_path: Path) -> None:
    database = Database(f"sqlite+pysqlite:///{tmp_path / 'source.sqlite'}")
    database.migrate()
    repository = PhaseCRepository(database)
    repository.ensure_tenant("ten_a", name="Tenant A")
    store = LocalObjectStore(tmp_path / "objects")
    repository.create_job("ten_a", manifest("job_a"))
    backup_dir = tmp_path / "backup-a"
    BackupService(database, store).create(backup_dir, backup_id="backup-a")
    database.dispose()

    service = RestoreService(
        target_database_url=f"sqlite+pysqlite:///{tmp_path / 'target.sqlite'}",
        target_store=LocalObjectStore(tmp_path / "target-objects"),
        broker=InMemoryStreamsBroker(),
        max_attempts=3,
    )
    with pytest.raises(RestoreConfirmationError, match="RESTORE backup-a"):
        service.restore(backup_dir, confirmation="yes")

    database_snapshot = backup_dir / "database.sqlite3"
    with database_snapshot.open("ab") as handle:
        handle.write(b"tampered")
    with pytest.raises(BackupVerificationError, match="size mismatch"):
        verify_backup(backup_dir)
