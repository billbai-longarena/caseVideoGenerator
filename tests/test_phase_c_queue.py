from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from server.app.persistence.artifact_commit import ArtifactCommitService, ArtifactSource
from server.app.persistence.database import Database
from server.app.persistence.object_store import LocalObjectStore
from server.app.persistence.repository import (
    ModelRunRegistration,
    PhaseCRepository,
    RepositoryNotFound,
    StageIdentity,
)
from server.app.services.streams import (
    InvalidStageMessage,
    InMemoryStreamsBroker,
    OutboxDispatcher,
    QueueRecoveryService,
    STAGE_QUEUES,
    StageExecutionError,
    StageExecutionResult,
    StageMessage,
    StageWorker,
    queue_for_stage,
)


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


@pytest.fixture()
def queue_system(tmp_path: Path):
    database = Database(f"sqlite+pysqlite:///{tmp_path / 'queue.sqlite'}")
    database.migrate()
    repository = PhaseCRepository(database)
    repository.ensure_tenant("ten_a", name="Tenant A")
    broker = InMemoryStreamsBroker()
    dispatcher = OutboxDispatcher(repository, broker)
    try:
        yield repository, broker, dispatcher
    finally:
        database.dispose()


def create_run(repository: PhaseCRepository, job_id: str, *, attempt_stage: str = "case.model") -> dict[str, object]:
    repository.create_job("ten_a", manifest(job_id))
    run, reused = repository.create_stage_run(
        StageIdentity(
            tenant_id="ten_a",
            job_id=job_id,
            stage=attempt_stage,
            input_hash="a" * 64,
            route_snapshot_hash="b" * 64,
            config_snapshot_hash="c" * 64,
        ),
        queue_name=queue_for_stage(attempt_stage),
    )
    assert reused is False
    return run


def test_all_twenty_one_stages_have_a_separated_worker_queue() -> None:
    assert len(STAGE_QUEUES) == 21
    assert set(STAGE_QUEUES.values()) == {"planning", "media", "render", "qa"}
    assert queue_for_stage("editorial.compose") == "planning"
    assert queue_for_stage("tts.generate") == "media"
    assert queue_for_stage("render.execute") == "render"
    assert queue_for_stage("qa.execute") == "qa"


def test_stage_message_rejects_material_or_prompt_payloads() -> None:
    payload = {
        "message_version": 1,
        "tenant_id": "ten_a",
        "job_id": "job_a",
        "stage_run_id": "run_a",
        "expected_job_version": 1,
        "input_snapshot_hash": "a" * 64,
        "priority": "normal",
        "enqueued_at": datetime.now(timezone.utc).isoformat(),
        "source_text": "must not enter Redis",
    }
    with pytest.raises(InvalidStageMessage, match="identifiers and snapshots only"):
        StageMessage.from_mapping(payload)


def test_outbox_duplicate_delivery_executes_paid_stage_once(queue_system) -> None:
    repository, broker, dispatcher = queue_system
    run = create_run(repository, "job_duplicate")
    assert dispatcher.dispatch_batch()["failed"] == 0
    original = broker.records("planning")[0].stage_message
    broker.publish_stage("planning", original, outbox_event_id="out_intentional_duplicate")

    calls: list[str] = []

    def handler(message: StageMessage, _: object) -> StageExecutionResult:
        calls.append(message.stage_run_id)
        return StageExecutionResult(output_hash="d" * 64, paid_result_key="provider_call_1")

    worker = StageWorker(
        repository,
        broker,
        queue_name="planning",
        worker_id="worker_a",
        handler=handler,
        heartbeat_seconds=60,
    )
    assert worker.process_one(block_ms=0)["outcome"] == "succeeded"
    assert worker.process_one(block_ms=0)["outcome"] == "already_succeeded"
    assert calls == [run["stage_run_id"]]
    assert repository.get_stage_run("ten_a", str(run["stage_run_id"]))["paid_result_key"] == "provider_call_1"
    assert broker.pending("planning") == 0


def test_stage_success_atomically_queues_the_next_stage(queue_system) -> None:
    repository, broker, dispatcher = queue_system
    run = create_run(repository, "job_stage_chain")
    assert dispatcher.dispatch_batch()["failed"] == 0

    next_manifest = manifest("job_stage_chain")
    next_manifest.update(
        {
            "status": "queued",
            "display_status": "正在生成标题与旁白",
            "stage": "editorial.compose",
        }
    )

    def handler(_: StageMessage, __: object) -> StageExecutionResult:
        return StageExecutionResult(
            output_hash="d" * 64,
            manifest=next_manifest,
            next_stage="editorial.compose",
        )

    worker = StageWorker(
        repository,
        broker,
        queue_name="planning",
        worker_id="worker_chain",
        handler=handler,
        heartbeat_seconds=60,
    )
    assert worker.process_one(block_ms=0)["outcome"] == "succeeded"

    stage_runs = repository.list_stage_runs("ten_a", "job_stage_chain")
    assert [item["stage"] for item in stage_runs] == ["case.model", "editorial.compose"]
    next_run = stage_runs[1]
    assert next_run["status"] == "queued"
    assert next_run["queue_name"] == "planning"
    assert next_run["input_hash"] == "d" * 64
    assert next_run["expected_job_version"] == repository.get_job("ten_a", "job_stage_chain")["row_version"]

    # The next-stage intent already exists in PostgreSQL before Redis dispatch.
    queued_topics = [event["topic"] for event in repository.pending_outbox()]
    assert "queue.planning" in queued_topics
    assert dispatcher.dispatch_batch()["failed"] == 0
    queued_messages = broker.records("planning")
    assert len(queued_messages) == 1
    assert queued_messages[0].stage_message.stage_run_id == next_run["stage_run_id"]


def test_stage_success_atomically_promotes_artifacts_and_queues_next_stage(
    queue_system,
    tmp_path: Path,
) -> None:
    repository, broker, dispatcher = queue_system
    run = create_run(repository, "job_atomic_artifact")
    dispatcher.dispatch_batch()
    store = LocalObjectStore(tmp_path / "objects")
    artifacts = ArtifactCommitService(repository, store)
    source = tmp_path / "case-model.json"
    source.write_text('{"case":"atomic"}', encoding="utf-8")

    def handler(message: StageMessage, _: object) -> StageExecutionResult:
        bundle = artifacts.stage_bundle(
            tenant_id=message.tenant_id,
            job_id=message.job_id,
            domain="case-model",
            revision_id=f"case-model-{message.stage_run_id}",
            sources=[ArtifactSource("case_model.json", source)],
            created_by="worker_atomic",
        )
        return StageExecutionResult(
            output_hash="d" * 64,
            manifest={**manifest(message.job_id), "stage": "editorial.compose", "status": "queued"},
            next_stage="editorial.compose",
            artifact_bundles=(bundle,),
        )

    worker = StageWorker(
        repository,
        broker,
        queue_name="planning",
        worker_id="worker_atomic",
        handler=handler,
        heartbeat_seconds=60,
    )
    assert worker.process_one(block_ms=0)["outcome"] == "succeeded"

    revision = repository.get_current_artifact_revision(
        "ten_a",
        "job_atomic_artifact",
        domain="case-model",
    )
    assert revision is not None
    assert revision["stage_run_id"] == run["stage_run_id"]
    assert revision["artifacts"][0]["logical_name"] == "case_model.json"
    pending_topics = [event["topic"] for event in repository.pending_outbox()]
    assert "artifact.revision.committed" in pending_topics
    assert "queue.planning" in pending_topics


def test_stage_success_atomically_records_model_provenance(queue_system) -> None:
    repository, broker, dispatcher = queue_system
    run = create_run(repository, "job_atomic_model")
    dispatcher.dispatch_batch()

    registration = ModelRunRegistration(
        id="mdl_atomic_model",
        task="case_model",
        provider="openai",
        model="gpt-5.5",
        route_snapshot={"transport": "openai_responses", "task_family": "general"},
        prompt_version="case-model-v2",
        schema_version="case-model-v2",
        provider_call_id="response_atomic",
        usage={"input_tokens": 10, "output_tokens": 20},
        cost_micros=123,
    )

    worker = StageWorker(
        repository,
        broker,
        queue_name="planning",
        worker_id="worker_atomic_model",
        handler=lambda *_: StageExecutionResult(
            output_hash="d" * 64,
            model_runs=(registration,),
        ),
        heartbeat_seconds=60,
    )
    assert worker.process_one(block_ms=0)["outcome"] == "succeeded"

    records = repository.list_model_runs(
        "ten_a",
        "job_atomic_model",
        stage_run_id=str(run["stage_run_id"]),
    )
    assert len(records) == 1
    assert records[0]["model_run_id"] == "mdl_atomic_model"
    assert records[0]["provider"] == "openai"
    assert records[0]["model"] == "gpt-5.5"
    assert records[0]["cost_micros"] == 123


def test_staged_artifacts_are_not_promoted_when_stage_commit_fails(
    queue_system,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, broker, dispatcher = queue_system
    create_run(repository, "job_atomic_failure")
    dispatcher.dispatch_batch()
    store = LocalObjectStore(tmp_path / "objects")
    artifacts = ArtifactCommitService(repository, store)
    source = tmp_path / "editorial.json"
    source.write_text('{"title":"orphan"}', encoding="utf-8")

    def handler(message: StageMessage, _: object) -> StageExecutionResult:
        return StageExecutionResult(
            output_hash="e" * 64,
            artifact_bundles=(
                artifacts.stage_bundle(
                    tenant_id=message.tenant_id,
                    job_id=message.job_id,
                    domain="editorial",
                    revision_id=f"editorial-{message.stage_run_id}",
                    sources=[ArtifactSource("editorial.json", source)],
                    created_by="worker_atomic_failure",
                ),
            ),
            model_runs=(
                ModelRunRegistration(
                    id="mdl_orphaned_stage",
                    task="editorial_compose",
                    provider="azure_anthropic",
                    model="case-video-claude",
                    route_snapshot={"transport": "anthropic_messages"},
                    prompt_version="editorial-v2",
                    schema_version="editorial-v2",
                ),
            ),
        )

    original_complete = repository.complete_stage_run

    def fail_complete(*args, **kwargs):
        raise RuntimeError("database commit unavailable")

    monkeypatch.setattr(repository, "complete_stage_run", fail_complete)
    worker = StageWorker(
        repository,
        broker,
        queue_name="planning",
        worker_id="worker_atomic_failure",
        handler=handler,
        heartbeat_seconds=60,
    )
    assert worker.process_one(block_ms=0)["outcome"] == "retry_queued"

    monkeypatch.setattr(repository, "complete_stage_run", original_complete)
    with pytest.raises(RepositoryNotFound):
        repository.get_current_artifact_revision(
            "ten_a",
            "job_atomic_failure",
            domain="editorial",
        )
    assert repository.list_model_runs("ten_a", "job_atomic_failure") == []
    assert len(list(store.list("tenants/ten_a/jobs/job_atomic_failure"))) == 1
    removed = artifacts.cleanup_orphans(
        older_than=datetime.now(timezone.utc) + timedelta(seconds=1)
    )
    assert len(removed) == 1


def test_unknown_message_version_is_quarantined_and_acked(queue_system) -> None:
    repository, broker, _ = queue_system
    broker._publish(  # type: ignore[attr-defined]  # inject a forward-version transport record
        broker.stream_key("planning"),
        {
            "message_version": "2",
            "tenant_id": "ten_a",
            "job_id": "job_future",
            "stage_run_id": "run_future",
            "expected_job_version": "1",
            "input_snapshot_hash": "a" * 64,
            "priority": "normal",
            "enqueued_at": datetime.now(timezone.utc).isoformat(),
        },
        "future-version-record",
    )

    worker = StageWorker(
        repository,
        broker,
        queue_name="planning",
        worker_id="worker_quarantine",
        handler=lambda *_: pytest.fail("unknown message versions must never reach a handler"),
        heartbeat_seconds=60,
    )
    result = worker.process_one(block_ms=0)
    assert result is not None
    assert result["outcome"] == "quarantined"
    assert "unsupported stage message version: 2" in result["reason"]
    assert broker.pending("planning") == 0
    quarantined = broker.quarantine_records()
    assert len(quarantined) == 1
    assert quarantined[0].fields["message_version"] == "2"
    assert quarantined[0].fields["payload_sha256"]


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("job_id", "job_wrong", "job_id"),
        ("expected_job_version", "99", "expected_job_version"),
        ("input_snapshot_hash", "f" * 64, "input_snapshot_hash"),
    ],
)
def test_stage_message_snapshot_mismatch_is_quarantined_before_handler(
    queue_system,
    field: str,
    value: str,
    reason: str,
) -> None:
    repository, broker, dispatcher = queue_system
    create_run(repository, f"job_mismatch_{field}")
    dispatcher.dispatch_batch()
    record = broker.records("planning")[0]
    record.fields[field] = value
    calls: list[str] = []
    worker = StageWorker(
        repository,
        broker,
        queue_name="planning",
        worker_id="worker_mismatch",
        handler=lambda *_: calls.append("called"),  # type: ignore[arg-type]
        heartbeat_seconds=60,
    )

    result = worker.process_one(block_ms=0)

    assert result is not None
    assert result["outcome"] == "quarantined"
    assert reason in result["reason"]
    assert calls == []
    assert broker.pending("planning") == 0


def test_stage_message_on_wrong_queue_is_quarantined_before_handler(queue_system) -> None:
    repository, broker, dispatcher = queue_system
    create_run(repository, "job_wrong_queue", attempt_stage="tts.generate")
    dispatcher.dispatch_batch()
    media_record = broker.records("media")[0]
    broker._publish(  # type: ignore[attr-defined]
        broker.stream_key("planning"),
        dict(media_record.fields),
        "misrouted-record",
    )
    calls: list[str] = []
    worker = StageWorker(
        repository,
        broker,
        queue_name="planning",
        worker_id="worker_wrong_queue",
        handler=lambda *_: calls.append("called"),  # type: ignore[arg-type]
        heartbeat_seconds=60,
    )

    result = worker.process_one(block_ms=0)

    assert result is not None
    assert result["outcome"] == "quarantined"
    assert "queue_name" in result["reason"]
    assert calls == []


def test_budget_gate_pauses_worker_without_retry_or_dead_letter(queue_system) -> None:
    repository, broker, dispatcher = queue_system
    job_manifest = manifest("job_budget_pause")
    job_manifest["budget"] = {"currency": "USD", "limit_micros": 100, "spent_micros": 0}
    repository.create_job("ten_a", job_manifest)
    run, reused = repository.create_stage_run(
        StageIdentity(
            tenant_id="ten_a",
            job_id="job_budget_pause",
            stage="case.model",
            input_hash="a" * 64,
            route_snapshot_hash="b" * 64,
            config_snapshot_hash="c" * 64,
        ),
        queue_name="planning",
    )
    assert reused is False
    dispatcher.dispatch_batch()

    def handler(message: StageMessage, _: object) -> StageExecutionResult:
        repository.reserve_cost(
            message.tenant_id,
            message.job_id,
            stage_run_id=message.stage_run_id,
            amount_micros=101,
            provider="openai",
            usage={"input_tokens": 10},
            pricing_version="test-v1",
            reference_id="budget-call",
        )
        raise AssertionError("cost reservation must stop before the provider call")

    worker = StageWorker(
        repository,
        broker,
        queue_name="planning",
        worker_id="worker_budget",
        handler=handler,
        heartbeat_seconds=60,
        max_attempts=3,
    )
    result = worker.process_one(block_ms=0)
    assert result == {
        "outcome": "waiting_approval",
        "stage_run_id": run["stage_run_id"],
        "error_code": "budget_approval_required",
    }
    paused = repository.get_stage_run("ten_a", str(run["stage_run_id"]))
    assert paused["status"] == "waiting_approval"
    assert paused["attempt"] == 1
    assert paused["cycle_attempt"] == 1
    assert broker.pending("planning") == 0
    assert broker.records("planning", dead_letter=True) == []


def test_duplicate_stage_creation_reuses_the_active_identity(queue_system) -> None:
    repository, _, _ = queue_system
    first = create_run(repository, "job_active_identity")
    repeated, reused = repository.create_stage_run(
        StageIdentity(
            tenant_id="ten_a",
            job_id="job_active_identity",
            stage="case.model",
            input_hash="a" * 64,
            route_snapshot_hash="b" * 64,
            config_snapshot_hash="c" * 64,
        ),
        queue_name="planning",
    )
    assert reused is True
    assert repeated["stage_run_id"] == first["stage_run_id"]


def test_worker_crash_is_recovered_only_after_database_lease_expiry(queue_system) -> None:
    repository, broker, dispatcher = queue_system
    run = create_run(repository, "job_crash")
    dispatcher.dispatch_batch()
    record = broker.read_stage("planning", consumer="dead_worker", block_ms=0)[0]
    start = datetime(2026, 7, 24, tzinfo=timezone.utc)
    repository.claim_stage_run(
        "ten_a",
        str(run["stage_run_id"]),
        worker_id="dead_worker",
        lease_seconds=90,
        now=start,
    )
    assert repository.reap_expired_leases(now=start + timedelta(seconds=89), max_attempts=3) == []
    recovered = repository.reap_expired_leases(now=start + timedelta(seconds=91), max_attempts=3)
    assert recovered[0]["expired_stage_run_id"] == run["stage_run_id"]
    dispatcher.dispatch_batch()

    calls: list[str] = []

    def handler(message: StageMessage, _: object) -> StageExecutionResult:
        calls.append(message.stage_run_id)
        return StageExecutionResult(output_hash="e" * 64)

    worker = StageWorker(
        repository,
        broker,
        queue_name="planning",
        worker_id="worker_recovery",
        handler=handler,
        heartbeat_seconds=60,
    )
    assert worker.process_one(block_ms=0)["outcome"] == "succeeded"
    assert len(calls) == 1
    assert repository.get_stage_run("ten_a", str(run["stage_run_id"]))["status"] == "lease_expired"

    # The abandoned Redis delivery is harmless when it is later auto-claimed.
    time.sleep(0.002)
    stale = worker.process_one(block_ms=0, claim_idle_ms=1)
    assert stale is not None and stale["outcome"] == "stale_message"
    assert broker.ack("planning", [record.message_id]) == 0


def test_empty_redis_is_rebuilt_from_authoritative_queued_stage(queue_system) -> None:
    repository, broker, dispatcher = queue_system
    run = create_run(repository, "job_rebuild")
    dispatcher.dispatch_batch()
    assert len(broker.records("planning")) == 1
    broker.clear()

    recovery = QueueRecoveryService(repository, dispatcher, max_attempts=3)
    report = recovery.rebuild_and_dispatch()
    assert report["rebuilt"] == 1
    assert len(broker.records("planning")) == 1

    calls = 0

    def handler(_: StageMessage, __: object) -> StageExecutionResult:
        nonlocal calls
        calls += 1
        return StageExecutionResult(output_hash="f" * 64)

    worker = StageWorker(
        repository,
        broker,
        queue_name="planning",
        worker_id="worker_rebuild",
        handler=handler,
        heartbeat_seconds=60,
    )
    assert worker.process_one(block_ms=0)["outcome"] == "succeeded"
    broker.clear()
    assert recovery.rebuild_and_dispatch()["rebuilt"] == 0
    assert calls == 1
    assert repository.get_stage_run("ten_a", str(run["stage_run_id"]))["status"] == "succeeded"


def test_max_attempts_enters_dead_letter_and_updates_job(queue_system) -> None:
    repository, broker, dispatcher = queue_system
    create_run(repository, "job_dead_letter")
    dispatcher.dispatch_batch()

    def handler(_: StageMessage, __: object) -> StageExecutionResult:
        raise StageExecutionError("provider_unavailable", "provider stayed unavailable", retryable=True)

    worker = StageWorker(
        repository,
        broker,
        queue_name="planning",
        worker_id="worker_failure",
        handler=handler,
        heartbeat_seconds=60,
        max_attempts=3,
    )
    assert worker.process_one(block_ms=0)["outcome"] == "retry_queued"
    dispatcher.dispatch_batch()
    assert worker.process_one(block_ms=0)["outcome"] == "retry_queued"
    dispatcher.dispatch_batch()
    assert worker.process_one(block_ms=0)["outcome"] == "dead_letter"
    dispatcher.dispatch_batch()

    dead_letters = broker.records("planning", dead_letter=True)
    assert len(dead_letters) == 1
    assert dead_letters[0].fields["dead_letter_attempt"] == "3"
    assert dead_letters[0].fields["dead_letter_error_code"] == "provider_unavailable"
    job = repository.get_job("ten_a", "job_dead_letter")
    assert job["status"] == "failed"
    assert job["needs_action"] is True
    assert job["next_action"] == "查看 dead letter 并由管理员恢复"


def test_running_stage_cancellation_fences_result_commit(queue_system) -> None:
    repository, _, _ = queue_system
    run = create_run(repository, "job_cancel_running")
    repository.claim_stage_run(
        "ten_a",
        str(run["stage_run_id"]),
        worker_id="worker_cancel",
        lease_seconds=90,
    )

    requested = repository.request_job_cancel(
        "ten_a",
        "job_cancel_running",
        actor_id="usr_editor",
        reason="user stopped the run",
    )
    assert requested["status"] == "canceling"
    heartbeat = repository.heartbeat_stage_run(
        "ten_a",
        str(run["stage_run_id"]),
        worker_id="worker_cancel",
        lease_seconds=90,
    )
    assert heartbeat["cancel_requested"] is True

    committed = repository.complete_stage_run(
        "ten_a",
        str(run["stage_run_id"]),
        worker_id="worker_cancel",
        output_hash="9" * 64,
        manifest={**manifest("job_cancel_running"), "status": "succeeded"},
        paid_result_key="provider-result-arrived-after-cancel",
    )
    assert committed["commit"] == "canceled"
    assert committed["paid_result_key"] == "provider-result-arrived-after-cancel"
    job = repository.get_job("ten_a", "job_cancel_running")
    assert job["status"] == "canceled"
    assert job["can_retry"] is True
    assert all(event["type"] != "stage.succeeded" for event in repository.list_events("ten_a", job["job_id"]))


def test_manual_retry_starts_a_new_attempt_cycle_and_is_idempotent(queue_system) -> None:
    repository, _, _ = queue_system
    first = create_run(repository, "job_retry_cycle")
    canceled = repository.request_job_cancel(
        "ten_a", "job_retry_cycle", actor_id="usr_editor"
    )
    assert canceled["status"] == "canceled"

    job, retried, created = repository.retry_job(
        "ten_a", "job_retry_cycle", actor_id="usr_editor"
    )
    assert created is True
    assert job["status"] == "queued"
    assert retried["attempt"] == int(first["attempt"]) + 1
    assert retried["retry_cycle"] == 1
    assert retried["cycle_attempt"] == 1

    repeated_job, repeated, repeated_created = repository.retry_job(
        "ten_a", "job_retry_cycle", actor_id="usr_editor"
    )
    assert repeated_created is False
    assert repeated_job["status"] == "queued"
    assert repeated["stage_run_id"] == retried["stage_run_id"]


def test_dispatch_failure_remains_in_outbox_and_retries(queue_system) -> None:
    repository, broker, _ = queue_system
    create_run(repository, "job_dispatch_retry")

    class FailsOnce:
        def __init__(self) -> None:
            self.failed = False

        def publish_event(self, topic, payload, *, outbox_event_id):
            return broker.publish_event(topic, payload, outbox_event_id=outbox_event_id)

        def publish_stage(self, queue_name, message, *, outbox_event_id, dead_letter=False, dead_letter_fields=None):
            if not self.failed:
                self.failed = True
                raise RuntimeError("Redis unavailable")
            return broker.publish_stage(
                queue_name,
                message,
                outbox_event_id=outbox_event_id,
                dead_letter=dead_letter,
                dead_letter_fields=dead_letter_fields,
            )

    dispatcher = OutboxDispatcher(repository, FailsOnce())
    first = dispatcher.dispatch_batch()
    assert first == {"delivered": 1, "failed": 1}
    pending = repository.pending_outbox()
    assert len(pending) == 1
    assert pending[0]["delivery_attempts"] == 1
    assert "Redis unavailable" in str(pending[0]["last_error"])
    assert dispatcher.dispatch_batch() == {"delivered": 1, "failed": 0}
    assert len(broker.records("planning")) == 1
