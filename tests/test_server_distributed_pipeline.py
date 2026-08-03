from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from server.app.core.config import load_settings
from server.app.persistence.database import Database
from server.app.persistence.object_store import InvalidObjectKey, LocalObjectStore
from server.app.persistence.repository import JobInputRegistration, PhaseCRepository, sha256_json
from server.app.services import revisions as revisions_module
from server.app.services.distributed_pipeline import DistributedStageExecutor, _safe_destination
from server.app.services.distributed_revisions import DistributedRevisionService
from server.app.services.manifest_factory import build_job_manifest
from server.app.services.revisions import PROGRAM_CLOSER, PROGRAM_OPENER
from server.app.services.streams import InMemoryStreamsBroker, OutboxDispatcher, StageWorker


def test_distributed_worker_rebuilds_workspace_and_preserves_strict_model_routes(
    tmp_path: Path,
) -> None:
    settings = replace(
        load_settings(),
        data_root=tmp_path / "local-jobs-are-not-authoritative",
        seed_projects_root=tmp_path / "seeds",
        dry_run=True,
        require_model_config=False,
        deployment_mode="distributed",
        database_url=f"sqlite+pysqlite:///{tmp_path / 'distributed.sqlite'}",
        object_store_backend="local",
        object_store_root=tmp_path / "objects",
        worker_workspace_root=tmp_path / "worker-workspaces",
        render_workspace_root=tmp_path / "render-workspaces",
    )
    database = Database(settings.database_url)
    database.migrate()
    repository = PhaseCRepository(database)
    repository.ensure_tenant("ten_distributed", name="Distributed Tenant")
    object_store = LocalObjectStore(settings.object_store_root)
    broker = InMemoryStreamsBroker()
    dispatcher = OutboxDispatcher(repository, broker)

    structured_input = {
        "customer": "一家需要统一销售节奏的企业",
        "situation": "销售、交付与管理团队使用不同的信息版本。",
        "conflict": "客户目标没有被稳定映射到责任和行动。",
        "outcome": "团队建立事实清单并形成可复核的推进路径。",
    }
    encoded = json.dumps(
        structured_input,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    job_id = "job_distributed_routes"
    input_id = "inp_distributed_routes"
    input_key = f"tenants/ten_distributed/inputs/{job_id}/{input_id}/{digest}.json"
    stored = object_store.put_bytes(input_key, encoded, media_type="application/json")

    manifest = build_job_manifest(
        settings,
        project_name="分布式严格模型路由验收",
        approval_mode="auto",
        input_mode="structured",
        idempotency_key="distributed-routes-test",
        structured_input=structured_input,
        job_id=job_id,
    )
    manifest.update(
        {
            "status": "queued",
            "display_status": "已排队",
            "stage": "ingest.validate",
            "stage_progress": {
                "ingest.validate": {"stage": "ingest.validate", "status": "queued"}
            },
            "overall_progress": 0.0,
        }
    )
    repository.create_job_bundle(
        "ten_distributed",
        manifest,
        inputs=[
            JobInputRegistration(
                input_id=input_id,
                kind="structured",
                object_key=input_key,
                sha256=stored.sha256,
                size_bytes=stored.size_bytes,
                media_type="application/json",
                extraction_status="ready",
            )
        ],
        request_hash=sha256_json(structured_input),
        actor_id="usr_test",
        request_id="req_distributed_routes",
        config_snapshot={
            "manifest_version": 2,
            "contract_versions": manifest["contract_versions"],
            "prompt_pins": manifest["prompt_pins"],
            "task_registry": manifest["task_registry"],
        },
        engine_snapshot={"source": "test-worker-image"},
    )

    executor = DistributedStageExecutor(settings, repository, object_store)
    worker = StageWorker(
        repository,
        broker,
        queue_name="planning",
        worker_id="worker_distributed_test",
        handler=executor,
        heartbeat_seconds=60,
    )
    expected = ["ingest.validate", "source.extract", "case.model", "editorial.compose"]
    for stage in expected:
        dispatched = dispatcher.dispatch_batch()
        assert dispatched["failed"] == 0
        outcome = worker.process_one(block_ms=0)
        assert outcome is not None
        assert outcome["outcome"] == "succeeded", (stage, outcome)
        succeeded = repository.list_stage_runs("ten_distributed", job_id)
        assert [item["stage"] for item in succeeded if item["status"] == "succeeded"] == expected[
            : expected.index(stage) + 1
        ]
        assert list(settings.worker_workspace_root.iterdir()) == []

    model_runs = repository.list_model_runs("ten_distributed", job_id)
    by_task = {item["task"]: item for item in model_runs}
    case_model = by_task["case.model"]
    assert case_model["provider"] == "openai"
    assert case_model["model"] == "gpt-5.5"
    assert case_model["route_snapshot"]["transport"] == "openai_responses"

    narration = by_task["narration.compose"]
    assert narration["provider"] == "azure_anthropic"
    assert narration["model"] == "case-video-claude"
    assert narration["route_snapshot"]["deployment"] == "case-video-claude"
    assert narration["route_snapshot"]["transport"] == "anthropic_messages"

    workspace = repository.get_current_artifact_revision(
        "ten_distributed",
        job_id,
        domain="workspace",
    )
    assert workspace["revision_id"].startswith("workspace-")
    assert workspace["artifacts"]
    assert repository.get_current_artifact_revision(
        "ten_distributed",
        job_id,
        domain="editorial",
    )["revision_id"] == repository.get_job("ten_distributed", job_id)["current_revisions"][
        "editorial"
    ]
    database.dispose()


def test_distributed_workspace_destination_rejects_path_traversal(tmp_path: Path) -> None:
    with pytest.raises(InvalidObjectKey):
        _safe_destination(tmp_path, "../outside")


def test_distributed_worker_completes_pinned_model_revision_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = replace(
        load_settings(),
        data_root=tmp_path / "local-jobs-are-not-authoritative",
        seed_projects_root=tmp_path / "seeds",
        dry_run=True,
        require_model_config=False,
        deployment_mode="distributed",
        database_url=f"sqlite+pysqlite:///{tmp_path / 'revision.sqlite'}",
        object_store_backend="local",
        object_store_root=tmp_path / "objects",
        worker_workspace_root=tmp_path / "worker-workspaces",
        render_workspace_root=tmp_path / "render-workspaces",
    )
    database = Database(settings.database_url)
    database.migrate()
    repository = PhaseCRepository(database)
    repository.ensure_tenant("ten_distributed", name="Distributed Tenant")
    object_store = LocalObjectStore(settings.object_store_root)
    broker = InMemoryStreamsBroker()
    dispatcher = OutboxDispatcher(repository, broker)

    source_payload = {"fact": "销售管理团队需要更快进入冲突。"}
    encoded = json.dumps(
        source_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    job_id = "job_distributed_model_revision"
    input_id = "inp_distributed_revision"
    input_key = f"tenants/ten_distributed/inputs/{job_id}/{input_id}/{digest}.json"
    stored = object_store.put_bytes(input_key, encoded, media_type="application/json")
    manifest = build_job_manifest(
        settings,
        project_name="分布式模型修订验收",
        approval_mode="editorial",
        input_mode="structured",
        idempotency_key="distributed-model-revision-test",
        structured_input=source_payload,
        job_id=job_id,
    )
    manifest.update(
        {
            "status": "waiting_approval",
            "display_status": "等待标题与旁白审核",
            "stage": "editorial.approval",
            "stage_progress": {
                "editorial.approval": {
                    "stage": "editorial.approval",
                    "status": "waiting",
                }
            },
            "overall_progress": 0.4,
        }
    )
    repository.create_job_bundle(
        "ten_distributed",
        manifest,
        inputs=[
            JobInputRegistration(
                input_id=input_id,
                kind="structured",
                object_key=input_key,
                sha256=stored.sha256,
                size_bytes=stored.size_bytes,
                media_type="application/json",
                extraction_status="ready",
            )
        ],
        request_hash=sha256_json(source_payload),
        actor_id="usr_test",
        request_id="req_distributed_revision",
        config_snapshot={
            "manifest_version": 2,
            "contract_versions": manifest["contract_versions"],
            "prompt_pins": manifest["prompt_pins"],
            "task_registry": manifest["task_registry"],
        },
        engine_snapshot={"source": "test-worker-image"},
    )
    distributed_revisions = DistributedRevisionService(settings, repository, object_store)
    distributed_revisions.create_editorial(
        "ten_distributed",
        job_id,
        title="一次共识如何改变销售管理",
        narration=(
            f"{PROGRAM_OPENER}\n\n"
            + "客户团队梳理业务流程，销售经理逐项核对事实，双方围绕真实问题形成共识。" * 30
            + f"\n\n{PROGRAM_CLOSER}"
        ),
        change_summary="建立待审核文稿",
        actor="system-seed",
        author_type="model",
        enforce_concurrency=False,
    )
    review = distributed_revisions.current_review("ten_distributed", job_id, "editorial")

    captured: list[dict[str, object]] = []
    original = revisions_module.RevisionService.create_editorial_model_revision

    def spy_create_editorial_model_revision(self, job_id: str, **kwargs):
        captured.append(dict(kwargs))
        return original(self, job_id, **kwargs)

    monkeypatch.setattr(
        revisions_module.RevisionService,
        "create_editorial_model_revision",
        spy_create_editorial_model_revision,
    )

    queued = distributed_revisions.request_model_revision(
        "ten_distributed",
        job_id,
        "editorial",
        base_revision=str(review["revision"]),
        if_match=str(review["etag"]),
        feedback="请让开头更快进入销售管理冲突，同时保持已有事实边界。",
        issues=[{"issue_id": "human-1", "severity": "warning", "message": "开场偏慢"}],
        change_summary="根据人工反馈重写文稿",
        actor="usr_editor",
    )
    request_id = queued["revision_request"]["request_id"]
    stage_run_id = queued["stage_run"]["stage_run_id"]
    assert queued["revision_request"]["status"] == "queued"
    assert queued["revision_request"]["stage_run_id"] == stage_run_id

    executor = DistributedStageExecutor(settings, repository, object_store)
    worker = StageWorker(
        repository,
        broker,
        queue_name="planning",
        worker_id="worker_revision_test",
        handler=executor,
        heartbeat_seconds=60,
    )
    assert dispatcher.dispatch_batch()["failed"] == 0
    outcome = None
    for _ in range(3):
        candidate = worker.process_one(block_ms=0)
        assert candidate is not None
        if candidate["stage_run_id"] == stage_run_id:
            outcome = candidate
            break
    assert outcome is not None
    assert outcome["outcome"] == "succeeded", outcome

    status = distributed_revisions.get_model_revision_request(
        "ten_distributed",
        job_id,
        request_id,
    )
    assert status["status"] == "succeeded"
    assert status["stage_run_id"] == stage_run_id
    assert status["result_revision"] == repository.get_job(
        "ten_distributed",
        job_id,
    )["current_revisions"]["editorial"]
    assert status["outcome"] in {"created", "no_change"}
    assert "feedback" not in json.dumps(status, ensure_ascii=False)
    assert captured
    assert captured[0]["feedback"] == "请让开头更快进入销售管理冲突，同时保持已有事实边界。"
    assert captured[0]["issues"] == [
        {"issue_id": "human-1", "severity": "warning", "message": "开场偏慢"}
    ]
    assert captured[0]["actor"] == "azure-anthropic:case-video-claude"

    model_runs = repository.list_model_runs("ten_distributed", job_id)
    narration_rewrite = next(item for item in model_runs if item["task"] == "narration.rewrite")
    assert narration_rewrite["stage_run_id"] == stage_run_id
    assert narration_rewrite["provider"] == "azure_anthropic"
    assert narration_rewrite["model"] == "case-video-claude"
    assert narration_rewrite["route_snapshot"]["transport"] == "anthropic_messages"
    editorial_review = next(item for item in model_runs if item["task"] == "editorial.review")
    assert editorial_review["stage_run_id"] == stage_run_id
    assert editorial_review["provider"] == "openai"
    assert editorial_review["model"] == "gpt-5.5"

    assert list(settings.worker_workspace_root.iterdir()) == []
    database.dispose()
