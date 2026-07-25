from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from server.app.persistence.artifact_commit import (
    ArtifactCommitInjectedFailure,
    ArtifactCommitService,
    ArtifactSource,
    fail_at,
)
from server.app.persistence.database import Database, SCHEMA_VERSION
from server.app.persistence.importer import LegacyJobImporter
from server.app.persistence.object_store import (
    InvalidObjectKey,
    LocalObjectStore,
    SignedObjectTokenError,
    SignedObjectTokenService,
    object_key_for_artifact,
)
from server.app.persistence.repository import (
    BudgetApprovalRequired,
    JobInputRegistration,
    PhaseCRepository,
    QuotaExceeded,
    RepositoryConflict,
    RepositoryNotFound,
    StageIdentity,
)
from server.app.services.contracts import canonical_json


def manifest(job_id: str, project_name: str, *, budget: int | None = None) -> dict[str, object]:
    timestamp = "2026-07-24T10:00:00+00:00"
    return {
        "manifest_version": 2,
        "job_id": job_id,
        "project_name": project_name,
        "status": "created",
        "display_status": "已创建",
        "stage": "created",
        "input_mode": "source",
        "approval_mode": "editorial",
        "contract_versions": {
            "source_manifest": "v1",
            "case_inputs": "v1",
            "case_model": "v1",
            "editorial": "v1",
            "editorial_review": "v1",
            "visual_plan": "v2",
            "image_prompts": "v2",
            "timeline": "v1",
            "artifact_index": "v1",
        },
        "current_revisions": {
            "case_model": None,
            "editorial": None,
            "visual_plan": None,
        },
        "approved_revisions": {
            "case_model": None,
            "editorial": None,
            "visual_plan": None,
        },
        "approval_checkpoints": {"visual_contract": None},
        "model_routes": {
            "narration": {"provider": "azure_anthropic", "model": "salesnail-cs-46"},
            "remotion": {"provider": "azure_anthropic", "model": "salesnail-cs-46"},
            "general": {"provider": "openai", "model": "gpt-5.5"},
        },
        "task_registry": {"test.task": {"version": "v1"}},
        "prompt_pins": {"test.task": {"version": "v1"}},
        "budget": {"currency": "USD", "limit_micros": budget, "spent_micros": 0},
        "stage_runs": {},
        "created_at": timestamp,
        "updated_at": timestamp,
    }


@pytest.fixture()
def phase_c(tmp_path: Path):
    database = Database(f"sqlite+pysqlite:///{tmp_path / 'phase-c.sqlite'}")
    database.migrate()
    repository = PhaseCRepository(database)
    repository.ensure_tenant("ten_a", name="Tenant A")
    repository.ensure_tenant("ten_b", name="Tenant B")
    store = LocalObjectStore(tmp_path / "objects")
    service = ArtifactCommitService(repository, store)
    try:
        yield database, repository, store, service
    finally:
        database.dispose()


def test_schema_migration_is_explicit_and_observable(tmp_path: Path) -> None:
    database = Database(f"sqlite+pysqlite:///{tmp_path / 'schema.sqlite'}")
    with pytest.raises(Exception):
        database.check_schema()
    database.migrate()
    assert database.check_schema() == SCHEMA_VERSION
    database.dispose()


def test_tenant_scope_cas_and_event_sequence(phase_c) -> None:
    _, repository, _, _ = phase_c
    created, inserted = repository.create_job("ten_a", manifest("job_shared", "A"))
    assert inserted is True
    repository.create_job("ten_b", manifest("job_shared", "B"))

    assert repository.get_job("ten_a", "job_shared")["project_name"] == "A"
    assert repository.get_job("ten_b", "job_shared")["project_name"] == "B"
    assert [item["project_name"] for item in repository.list_jobs("ten_a")] == ["A"]
    with pytest.raises(RepositoryNotFound):
        repository.get_job("ten_a", "missing")

    next_manifest = manifest("job_shared", "A2")
    updated = repository.replace_manifest(
        "ten_a",
        "job_shared",
        next_manifest,
        expected_version=created["row_version"],
    )
    assert updated["row_version"] == created["row_version"] + 1
    with pytest.raises(RepositoryConflict):
        repository.replace_manifest(
            "ten_a",
            "job_shared",
            manifest("job_shared", "stale"),
            expected_version=created["row_version"],
        )

    first = repository.append_event("ten_a", "job_shared", "job.started", stage="ingest", message="one")
    second = repository.append_event("ten_a", "job_shared", "job.progress", stage="ingest", message="two")
    assert (first["seq"], second["seq"]) == (1, 2)
    assert [event["seq"] for event in repository.list_events("ten_a", "job_shared")] == [1, 2]


def test_create_job_bundle_is_atomic_idempotent_and_enqueues_first_stage(phase_c) -> None:
    database, repository, _, _ = phase_c
    now = datetime(2026, 7, 24, 10, tzinfo=timezone.utc)
    repository.update_tenant_governance("ten_a", quotas={"active_jobs": 2})
    repository.create_upload(
        "ten_a",
        upload_id="upl_bundle",
        filename="case.pdf",
        safe_name="case.pdf",
        declared_size_bytes=3,
        declared_media_type="application/pdf",
        declared_sha256="abc",
        expires_at=now + timedelta(hours=1),
    )
    repository.complete_upload(
        "ten_a",
        "upl_bundle",
        object_key="tenants/ten_a/uploads/upl_bundle/abc",
        size_bytes=3,
        sha256="abc",
        detected_media_type="application/pdf",
        scan_status="clean",
        now=now,
    )
    job_manifest = {
        **manifest("job_bundle", "Atomic Bundle"),
        "idempotency_key_hash": "idem-bundle",
    }
    inputs = [
        JobInputRegistration(
            input_id="inp_bundle",
            kind="upload",
            upload_id="upl_bundle",
            object_key="tenants/ten_a/uploads/upl_bundle/abc",
            sha256="abc",
            size_bytes=3,
            media_type="application/pdf",
        )
    ]
    created, stage, inserted = repository.create_job_bundle(
        "ten_a",
        job_manifest,
        inputs=inputs,
        request_hash="request-a",
        actor_id="usr_a",
        request_id="req-a",
        now=now,
    )
    assert inserted is True
    assert created["snapshot_sequence"] == 1
    assert stage["stage"] == "ingest.validate"
    assert stage["queue_name"] == "planning"
    assert repository.get_upload("ten_a", "upl_bundle")["bound_job_id"] == "job_bundle"
    assert [event["type"] for event in repository.list_events("ten_a", "job_bundle")] == [
        "job.created"
    ]

    replay_job, replay_stage, replay_inserted = repository.create_job_bundle(
        "ten_a",
        job_manifest,
        inputs=inputs,
        request_hash="request-a",
        actor_id="usr_a",
        request_id="req-retry",
        now=now,
    )
    assert replay_inserted is False
    assert replay_job["job_id"] == created["job_id"]
    assert replay_stage["stage_run_id"] == stage["stage_run_id"]
    assert len(repository.list_audit("ten_a", action="job.create")) == 1
    assert repository.quota_summary(
        "ten_a",
        dimension="active_jobs",
        mode="capacity",
        window="capacity",
        now=now,
    )["committed"] == 1

    from server.app.persistence.models import JobInput, JobStageRun, OutboxEvent
    from sqlalchemy import func, select

    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(JobInput)) == 1
        assert session.scalar(select(func.count()).select_from(JobStageRun)) == 1
        assert session.scalar(select(func.count()).select_from(OutboxEvent)) == 3


@pytest.mark.parametrize("failure_mode", ["quarantined", "cross_tenant"])
def test_create_job_bundle_rolls_back_all_authoritative_rows_on_invalid_upload(
    phase_c,
    failure_mode: str,
) -> None:
    database, repository, _, _ = phase_c
    now = datetime(2026, 7, 24, 10, tzinfo=timezone.utc)
    owner = "ten_a" if failure_mode == "quarantined" else "ten_b"
    upload_id = f"upl_{failure_mode}"
    repository.create_upload(
        owner,
        upload_id=upload_id,
        filename="case.pdf",
        safe_name="case.pdf",
        declared_size_bytes=3,
        declared_media_type="application/pdf",
        declared_sha256="abc",
        expires_at=now + timedelta(hours=1),
    )
    repository.complete_upload(
        owner,
        upload_id,
        object_key=f"tenants/{owner}/uploads/{upload_id}/abc",
        size_bytes=3,
        sha256="abc",
        detected_media_type="application/pdf",
        scan_status="infected" if failure_mode == "quarantined" else "clean",
        now=now,
    )
    registration = JobInputRegistration(
        input_id="inp_invalid",
        kind="upload",
        upload_id=upload_id,
        object_key=f"tenants/{owner}/uploads/{upload_id}/abc",
        sha256="abc",
        size_bytes=3,
        media_type="application/pdf",
    )
    expected = RepositoryConflict if failure_mode == "quarantined" else RepositoryNotFound
    with pytest.raises(expected):
        repository.create_job_bundle(
            "ten_a",
            manifest(f"job_{failure_mode}", failure_mode),
            inputs=[registration],
            request_hash=f"request-{failure_mode}",
            actor_id="usr_a",
            now=now,
        )

    with pytest.raises(RepositoryNotFound):
        repository.get_job("ten_a", f"job_{failure_mode}")
    assert repository.get_upload(owner, upload_id, include_expired=True)["bound_job_id"] is None

    from server.app.persistence.models import AuditLog, Job, JobEvent, JobInput, JobStageRun, OutboxEvent
    from sqlalchemy import func, select

    with database.session() as session:
        for model in (Job, JobInput, JobStageRun, JobEvent, AuditLog, OutboxEvent):
            assert session.scalar(select(func.count()).select_from(model)) == 0


def test_create_job_bundle_serializes_active_job_quota_race(phase_c) -> None:
    _, repository, _, _ = phase_c
    now = datetime(2026, 7, 24, 10, tzinfo=timezone.utc)
    repository.update_tenant_governance("ten_a", quotas={"active_jobs": 1})

    def create(index: int) -> bool:
        try:
            repository.create_job_bundle(
                "ten_a",
                manifest(f"job_race_{index}", f"Race {index}"),
                inputs=[
                    JobInputRegistration(
                        input_id=f"inp_race_{index}",
                        kind="structured",
                        object_key=f"tenants/ten_a/inputs/race-{index}",
                        sha256=f"{index:064x}",
                        size_bytes=2,
                        media_type="application/json",
                    )
                ],
                request_hash=f"request-race-{index}",
                actor_id="usr_a",
                now=now,
            )
            return True
        except QuotaExceeded:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(create, range(2)))
    assert sum(outcomes) == 1
    assert len(repository.list_jobs("ten_a")) == 1
    assert repository.quota_summary(
        "ten_a",
        dimension="active_jobs",
        mode="capacity",
        window="capacity",
        now=now,
    )["committed"] == 1


@pytest.mark.parametrize("failure_point", ["after_upload", "before_db_commit"])
def test_precommit_crash_leaves_only_collectable_orphan(phase_c, tmp_path: Path, failure_point: str) -> None:
    _, repository, store, service = phase_c
    repository.create_job("ten_a", manifest("job_crash", "Crash"))
    source = tmp_path / f"{failure_point}.txt"
    source.write_text("immutable", encoding="utf-8")

    with pytest.raises(ArtifactCommitInjectedFailure):
        service.commit(
            tenant_id="ten_a",
            job_id="job_crash",
            domain="editorial",
            revision_id=f"rev_{failure_point}",
            sources=[ArtifactSource("title.txt", source)],
            created_by="usr_a",
            failure_hook=fail_at(failure_point),
        )

    assert repository.consistency_snapshot("ten_a", "job_crash")["artifact_count"] == 0
    assert len(list(store.list("tenants/ten_a/jobs/job_crash"))) == 1
    removed = service.cleanup_orphans(older_than=datetime.now(timezone.utc) + timedelta(seconds=1))
    assert len(removed) == 1
    assert list(store.list("tenants/ten_a/jobs/job_crash")) == []


def test_postcommit_response_loss_is_idempotently_recoverable(phase_c, tmp_path: Path) -> None:
    _, repository, store, service = phase_c
    repository.create_job("ten_a", manifest("job_commit", "Commit"))
    source = tmp_path / "title.txt"
    source.write_text("已提交", encoding="utf-8")
    kwargs = {
        "tenant_id": "ten_a",
        "job_id": "job_commit",
        "domain": "editorial",
        "revision_id": "rev_commit",
        "sources": [ArtifactSource("title.txt", source)],
        "created_by": "usr_a",
    }
    with pytest.raises(ArtifactCommitInjectedFailure):
        service.commit(**kwargs, failure_hook=fail_at("after_db_commit"))

    snapshot = repository.consistency_snapshot("ten_a", "job_commit")
    assert snapshot["revision_count"] == 1
    assert snapshot["artifact_count"] == 1
    replay = service.commit(**kwargs)
    assert replay["revision_id"] == "rev_commit"
    assert len(list(store.list("tenants/ten_a/jobs/job_commit"))) == 1


def test_budget_gate_persists_waiting_state_before_raising(phase_c) -> None:
    _, repository, _, _ = phase_c
    repository.create_job("ten_a", manifest("job_budget", "Budget", budget=100))
    with pytest.raises(BudgetApprovalRequired):
        repository.reserve_cost(
            "ten_a",
            "job_budget",
            stage_run_id=None,
            amount_micros=101,
            provider="azure_anthropic",
            usage={"input_tokens": 10},
            pricing_version="test-v1",
            reference_id="call_1",
        )
    job = repository.get_job("ten_a", "job_budget")
    assert job["status"] == "waiting_approval"
    assert job["needs_action"] is True
    pending = job["budget"]["pending_request"]
    assert pending["reference_id"] == "call_1"
    assert pending["projected_total_micros"] == 101
    assert pending["budget_limit_micros"] == 100
    assert repository.cost_ledger("ten_a", "job_budget") == []


def test_budget_approval_resumes_the_same_paused_stage_without_spending(phase_c) -> None:
    _, repository, _, _ = phase_c
    repository.create_job("ten_a", manifest("job_budget_resume", "Budget", budget=100))
    stage, _ = repository.create_stage_run(
        StageIdentity(
            tenant_id="ten_a",
            job_id="job_budget_resume",
            stage="case.model",
            input_hash="a" * 64,
            route_snapshot_hash="b" * 64,
            config_snapshot_hash="c" * 64,
        ),
        queue_name="planning",
    )
    stage_run_id = str(stage["stage_run_id"])
    repository.claim_stage_run(
        "ten_a",
        stage_run_id,
        worker_id="worker_budget",
        lease_seconds=90,
    )
    with pytest.raises(BudgetApprovalRequired):
        repository.reserve_cost(
            "ten_a",
            "job_budget_resume",
            stage_run_id=stage_run_id,
            amount_micros=101,
            provider="openai",
            usage={"input_tokens": 10},
            pricing_version="test-v1",
            reference_id="call_resume",
        )
    paused = repository.pause_stage_run_for_budget(
        "ten_a",
        stage_run_id,
        worker_id="worker_budget",
    )
    assert paused["status"] == "waiting_approval"
    assert paused["cycle_attempt"] == 1

    job = repository.get_job("ten_a", "job_budget_resume")
    approved = repository.decide_budget(
        "ten_a",
        "job_budget_resume",
        decision="approved",
        resolution="raise_limit",
        actor_id="usr_admin",
        reason="approved after review",
        expected_job_version=job["row_version"],
        new_limit_micros=200,
    )
    assert approved["job"]["status"] == "queued"
    assert approved["job"]["budget"]["limit_micros"] == 200
    assert "pending_request" not in approved["job"]["budget"]
    assert approved["stage_run"]["stage_run_id"] == stage_run_id
    assert approved["stage_run"]["status"] == "queued"
    assert approved["stage_run"]["cycle_attempt"] == 1
    assert repository.cost_ledger("ten_a", "job_budget_resume") == []
    assert any(
        event["aggregate_id"] == stage_run_id and event["topic"] == "queue.planning"
        for event in repository.pending_outbox()
    )


def test_legacy_importer_dry_run_import_and_resume(phase_c, tmp_path: Path) -> None:
    _, repository, store, service = phase_c
    source_root = tmp_path / "legacy"
    job_root = source_root / "job_legacy"
    (job_root / "project").mkdir(parents=True)
    (job_root / "job_manifest.json").write_text(
        json.dumps(manifest("job_legacy", "Legacy"), ensure_ascii=False),
        encoding="utf-8",
    )
    (job_root / "project" / "title.txt").write_text("迁移标题", encoding="utf-8")
    (job_root / ".env").write_text("SECRET=never-import", encoding="utf-8")
    importer = LegacyJobImporter(repository, service)

    dry = importer.run(source_root, tenant_id="ten_a", actor_id="migration", dry_run=True)
    assert dry.failed == 0
    assert dry.candidates[0].action == "validated"
    assert dry.candidates[0].artifact_count == 2
    assert dry.candidates[0].source_count == 0
    assert dry.candidates[0].revision_count == 0
    with pytest.raises(RepositoryNotFound):
        repository.get_job("ten_a", "job_legacy")

    first = importer.run(source_root, tenant_id="ten_a", actor_id="migration", dry_run=False)
    second = importer.run(source_root, tenant_id="ten_a", actor_id="migration", dry_run=False)
    assert first.imported == 1
    assert second.imported == 1
    assert first.candidates[0].shadow_status == "passed"
    assert first.candidates[0].object_verified_count == 2
    assert repository.consistency_snapshot("ten_a", "job_legacy")["artifact_count"] == 2
    keys = [item.key for item in store.list("tenants/ten_a/jobs/job_legacy")]
    assert len(keys) == 2
    assert not any(".env" in key for key in keys)

    shadow = importer.run(
        source_root,
        tenant_id="ten_a",
        actor_id="migration",
        dry_run=False,
        shadow_only=True,
    )
    assert shadow.verified == 1
    assert shadow.candidates[0].shadow_status == "passed"


def test_legacy_importer_dry_run_does_not_create_tenant(phase_c, tmp_path: Path) -> None:
    _, repository, _, service = phase_c
    source_root = tmp_path / "legacy"
    job_root = source_root / "job_read_only"
    job_root.mkdir(parents=True)
    (job_root / "job_manifest.json").write_text(
        json.dumps(manifest("job_read_only", "Read only"), ensure_ascii=False),
        encoding="utf-8",
    )

    report = LegacyJobImporter(repository, service).run(
        source_root,
        tenant_id="ten_dry_run_only",
        actor_id="migration",
        dry_run=True,
    )

    assert report.failed == 0
    assert report.candidates[0].action == "validated"
    with pytest.raises(RepositoryNotFound):
        repository.get_tenant("ten_dry_run_only")


def test_legacy_importer_validates_sources_and_revision_chain(phase_c, tmp_path: Path) -> None:
    _, repository, _, service = phase_c
    source_root = tmp_path / "legacy"
    job_root = source_root / "job_contract_inventory"
    structured_path = job_root / "source" / "structured_input.json"
    structured_path.parent.mkdir(parents=True)
    structured_path.write_text('{"customer":"示例客户"}', encoding="utf-8")
    structured_sha = hashlib.sha256(structured_path.read_bytes()).hexdigest()
    source_manifest = {
        "version": "1",
        "files": [
            {
                "source_id": "src_structured",
                "upload_id": None,
                "original_name": "structured_input.json",
                "safe_name": "structured_input.json",
                "media_type": "application/json",
                "size_bytes": structured_path.stat().st_size,
                "sha256": structured_sha,
                "extraction_status": "succeeded",
                "extracted_text_sha256": None,
                "external_sharing_policy": "summary_only",
                "warnings": [],
                "error_code": None,
            }
        ],
    }
    (job_root / "source" / "source_manifest.json").write_text(
        json.dumps(source_manifest, ensure_ascii=False),
        encoding="utf-8",
    )

    revision_id = "rev_editorial_0001"
    revision_root = job_root / "revisions" / "editorial" / revision_id
    revision_root.mkdir(parents=True)
    narration_path = revision_root / "narration.txt"
    narration_path.write_text("这是一段已审核旁白。", encoding="utf-8")
    content_hashes = {
        "narration.txt": hashlib.sha256(narration_path.read_bytes()).hexdigest(),
    }
    content_sha = hashlib.sha256(canonical_json(content_hashes).encode("utf-8")).hexdigest()
    revision_metadata = {
        "metadata_version": 1,
        "domain": "editorial",
        "revision_id": revision_id,
        "revision_number": 1,
        "parent_revision": None,
        "author_type": "human",
        "actor": "editor",
        "created_at": "2026-07-24T10:00:00+00:00",
        "input_hash": "1" * 64,
        "model_run_id": None,
        "prompt_versions": {},
        "schema_versions": {"editorial": "v1"},
        "content_hashes": content_hashes,
        "content_sha256": content_sha,
        "etag": content_sha,
        "change_summary": "migration fixture",
    }
    (revision_root / "metadata.json").write_text(
        json.dumps(revision_metadata, ensure_ascii=False),
        encoding="utf-8",
    )
    job_manifest = manifest("job_contract_inventory", "Contract inventory")
    job_manifest["inputs"] = {"upload_ids": [], "has_structured_input": True}
    job_manifest["current_revisions"]["editorial"] = revision_id
    job_manifest["approved_revisions"]["editorial"] = revision_id
    (job_root / "job_manifest.json").write_text(
        json.dumps(job_manifest, ensure_ascii=False),
        encoding="utf-8",
    )

    report = LegacyJobImporter(repository, service).run(
        source_root,
        tenant_id="ten_a",
        actor_id="migration",
        dry_run=False,
    )

    candidate = report.candidates[0]
    assert report.imported == 1
    assert candidate.source_count == 1
    assert candidate.revision_count == 1
    assert candidate.artifact_count == 5
    assert candidate.object_verified_count == 5


def test_legacy_importer_blocks_declared_hash_mismatch(phase_c, tmp_path: Path) -> None:
    _, repository, _, service = phase_c
    source_root = tmp_path / "legacy"
    job_root = source_root / "job_bad_hash"
    title_path = job_root / "project" / "title.txt"
    title_path.parent.mkdir(parents=True)
    title_path.write_text("不能迁移的标题", encoding="utf-8")
    artifact_index = {
        "version": "1",
        "artifacts": [
            {
                "name": "project/title.txt",
                "size": title_path.stat().st_size,
                "sha256": "0" * 64,
                "kind": "text",
                "current": True,
            }
        ],
    }
    index_path = job_root / "artifact_index.json"
    index_path.write_text(
        json.dumps(artifact_index, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    job_manifest = manifest("job_bad_hash", "Bad hash")
    job_manifest["artifact_index_sha256"] = hashlib.sha256(index_path.read_bytes()).hexdigest()
    (job_root / "job_manifest.json").write_text(
        json.dumps(job_manifest, ensure_ascii=False),
        encoding="utf-8",
    )

    report = LegacyJobImporter(repository, service).run(
        source_root,
        tenant_id="ten_a",
        actor_id="migration",
        dry_run=False,
    )

    candidate = report.candidates[0]
    assert report.failed == 1
    assert candidate.hash_mismatch is True
    assert candidate.action == "failed"
    assert any("sha256 mismatch" in error for error in candidate.errors)
    with pytest.raises(RepositoryNotFound):
        repository.get_job("ten_a", "job_bad_hash")


def test_legacy_importer_blocks_unsupported_schema(phase_c, tmp_path: Path) -> None:
    _, repository, _, service = phase_c
    source_root = tmp_path / "legacy"
    job_root = source_root / "job_future_schema"
    job_root.mkdir(parents=True)
    future_manifest = manifest("job_future_schema", "Future schema")
    future_manifest["manifest_version"] = 99
    (job_root / "job_manifest.json").write_text(
        json.dumps(future_manifest, ensure_ascii=False),
        encoding="utf-8",
    )

    report = LegacyJobImporter(repository, service).run(
        source_root,
        tenant_id="ten_a",
        actor_id="migration",
        dry_run=False,
    )

    candidate = report.candidates[0]
    assert report.failed == 1
    assert candidate.unsupported_schema is True
    with pytest.raises(RepositoryNotFound):
        repository.get_job("ten_a", "job_future_schema")


def test_legacy_importer_shadow_detects_corrupted_object_bytes(phase_c, tmp_path: Path) -> None:
    _, repository, store, service = phase_c
    source_root = tmp_path / "legacy"
    job_root = source_root / "job_shadow_corrupt"
    title_path = job_root / "project" / "title.txt"
    title_path.parent.mkdir(parents=True)
    title_path.write_text("影子核对标题", encoding="utf-8")
    (job_root / "job_manifest.json").write_text(
        json.dumps(manifest("job_shadow_corrupt", "Shadow corrupt"), ensure_ascii=False),
        encoding="utf-8",
    )
    importer = LegacyJobImporter(repository, service)
    imported = importer.run(
        source_root,
        tenant_id="ten_a",
        actor_id="migration",
        dry_run=False,
    )
    assert imported.imported == 1
    revision = repository.get_current_artifact_revision(
        "ten_a",
        "job_shadow_corrupt",
        domain="migration.snapshot",
    )
    title_artifact = next(
        item for item in revision["artifacts"] if item["logical_name"] == "project/title.txt"
    )
    store._path(title_artifact["object_key"]).write_bytes(b"corrupted")

    shadow = importer.run(
        source_root,
        tenant_id="ten_a",
        actor_id="migration",
        dry_run=False,
        shadow_only=True,
    )

    candidate = shadow.candidates[0]
    assert shadow.failed == 1
    assert candidate.shadow_status == "blocked"
    assert candidate.hash_mismatch is True
    assert any("object bytes mismatch" in error for error in candidate.errors)


def test_signed_object_token_is_bound_to_tenant_job_and_expiry() -> None:
    signer = SignedObjectTokenService(b"0123456789abcdef0123456789abcdef")
    key = object_key_for_artifact("ten_a", "job_a", "rev_a", "video.mp4")
    token = signer.issue(tenant_id="ten_a", job_id="job_a", object_key=key, expires_at=200)
    assert signer.verify(token, tenant_id="ten_a", job_id="job_a", now_epoch=199)["object_key"] == key
    with pytest.raises(SignedObjectTokenError):
        signer.verify(token, tenant_id="ten_b", job_id="job_a", now_epoch=199)
    with pytest.raises(SignedObjectTokenError):
        signer.verify(token, tenant_id="ten_a", job_id="job_a", now_epoch=201)
    with pytest.raises(InvalidObjectKey):
        object_key_for_artifact("ten_a", "job_a", "rev_a", "../secret")


def test_cost_quota_uses_current_month_and_preserves_terminal_outcome(phase_c) -> None:
    _, repository, _, _ = phase_c
    repository.update_tenant_governance("ten_a", quotas={"monthly_cost_micros": 100})
    repository.create_job("ten_a", manifest("job_cost", "Cost"))
    december = datetime(2026, 12, 20, tzinfo=timezone.utc)
    january = datetime(2027, 1, 2, tzinfo=timezone.utc)
    repository.reserve_cost(
        "ten_a",
        "job_cost",
        stage_run_id=None,
        amount_micros=60,
        provider="azure_anthropic",
        usage={"input_tokens": 10},
        pricing_version="test-v1",
        reference_id="december-call",
        now=december,
    )
    repository.settle_cost(
        "ten_a",
        "job_cost",
        reference_id="december-call",
        actual_micros=60,
        provider="azure_anthropic",
        usage={"input_tokens": 10},
        pricing_version="test-v1",
        outcome="failed",
        now=december,
    )
    repository.reserve_cost(
        "ten_a",
        "job_cost",
        stage_run_id=None,
        amount_micros=100,
        provider="openai",
        usage={"input_tokens": 20},
        pricing_version="test-v1",
        reference_id="january-call",
        now=january,
    )
    summary = repository.tenant_cost_summary("ten_a", now=january)
    assert summary["actual_micros"] == 0
    assert summary["reserved_micros"] == 100
    failed_actual = next(
        entry
        for entry in repository.cost_ledger("ten_a", "job_cost")
        if entry["reference_id"] == "december-call" and entry["kind"] == "actual"
    )
    assert failed_actual["usage"]["outcome"] == "failed"


def test_quota_reservations_are_atomic_and_capacity_is_released(phase_c) -> None:
    _, repository, _, _ = phase_c
    repository.update_tenant_governance(
        "ten_a",
        quotas={"render_concurrency": 1, "model_input_tokens_daily": 100},
    )
    repository.create_job("ten_a", manifest("job_quota", "Quota"))

    def reserve(index: int) -> bool:
        try:
            repository.reserve_quota(
                "ten_a",
                dimension="render_concurrency",
                amount=1,
                mode="capacity",
                window="capacity",
                reference_id=f"render-{index}",
                job_id="job_quota",
            )
            return True
        except QuotaExceeded:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(reserve, range(8)))
    assert sum(results) == 1
    winner = f"render-{results.index(True)}"
    repository.release_quota(
        "ten_a",
        dimension="render_concurrency",
        reference_id=winner,
    )
    replacement = repository.reserve_quota(
        "ten_a",
        dimension="render_concurrency",
        amount=1,
        mode="capacity",
        window="capacity",
        reference_id="render-replacement",
        job_id="job_quota",
    )
    assert replacement["status"] == "active"

    now = datetime(2026, 7, 24, 10, tzinfo=timezone.utc)
    repository.reserve_quota(
        "ten_a",
        dimension="model_input_tokens",
        amount=80,
        window="daily",
        reference_id="model-1",
        job_id="job_quota",
        now=now,
    )
    repository.settle_quota(
        "ten_a",
        dimension="model_input_tokens",
        reference_id="model-1",
        actual_amount=75,
        outcome="superseded",
        now=now,
    )
    with pytest.raises(QuotaExceeded):
        repository.reserve_quota(
            "ten_a",
            dimension="model_input_tokens",
            amount=26,
            window="daily",
            reference_id="model-2",
            job_id="job_quota",
            now=now,
        )
    assert repository.quota_summary(
        "ten_a",
        dimension="model_input_tokens",
        mode="consumption",
        window="daily",
        now=now,
    )["committed"] == 75


def test_upload_quarantine_binding_expiry_and_audit_are_tenant_scoped(phase_c) -> None:
    _, repository, _, _ = phase_c
    now = datetime(2026, 7, 24, 10, tzinfo=timezone.utc)
    repository.create_job("ten_a", manifest("job_upload", "Upload"))
    repository.create_upload(
        "ten_a",
        upload_id="upl_clean",
        filename="source.pdf",
        safe_name="source.pdf",
        declared_size_bytes=3,
        declared_media_type="application/pdf",
        declared_sha256="abc",
        expires_at=now + timedelta(hours=24),
    )
    repository.complete_upload(
        "ten_a",
        "upl_clean",
        object_key="tenants/ten_a/uploads/upl_clean/source.pdf",
        size_bytes=3,
        sha256="abc",
        detected_media_type="application/pdf",
        scan_status="clean",
        now=now,
    )
    bound = repository.bind_upload("ten_a", "upl_clean", "job_upload", now=now)
    assert bound["bound_job_id"] == "job_upload"
    with pytest.raises(RepositoryNotFound):
        repository.get_upload("ten_b", "upl_clean")

    repository.create_upload(
        "ten_a",
        upload_id="upl_expired",
        filename="old.txt",
        safe_name="old.txt",
        declared_size_bytes=1,
        declared_media_type="text/plain",
        declared_sha256=None,
        expires_at=now - timedelta(seconds=1),
    )
    assert repository.expire_unbound_uploads("ten_a", now=now) == []
    with pytest.raises(RepositoryNotFound):
        repository.get_upload("ten_a", "upl_expired", now=now)

    repository.audit(
        "ten_a",
        actor_id="usr_a",
        action="upload.bind",
        resource_type="upload",
        resource_id="upl_clean",
        result="succeeded",
    )
    assert len(repository.list_audit("ten_a")) == 1
    assert repository.list_audit("ten_b") == []


def test_retention_honors_recovery_window_pin_and_legal_hold(phase_c) -> None:
    _, repository, _, _ = phase_c
    now = datetime(2026, 7, 24, 10, tzinfo=timezone.utc)
    for job_id in ("job_old", "job_pinned", "job_held"):
        repository.create_job("ten_a", {**manifest(job_id, job_id), "status": "failed"})
    repository.set_job_protection("ten_a", "job_pinned", pinned=True)
    repository.set_job_protection("ten_a", "job_held", legal_hold=True)
    with repository.database.transaction() as session:
        from server.app.persistence.models import Job

        for job_id in ("job_old", "job_pinned", "job_held"):
            session.get(Job, ("ten_a", job_id)).updated_at = now - timedelta(days=31)
    result = repository.apply_retention(
        "ten_a",
        now=now,
        succeeded_days=90,
        failed_days=30,
        recovery_days=7,
    )
    assert result == {"hidden": ["job_old"], "purge_ready": []}
    repository.restore_deleted_job("ten_a", "job_old", now=now + timedelta(days=6))
    repository.mark_job_deleted("ten_a", "job_old", recovery_days=7, now=now)
    with pytest.raises(RepositoryConflict):
        repository.restore_deleted_job("ten_a", "job_old", now=now + timedelta(days=8))
