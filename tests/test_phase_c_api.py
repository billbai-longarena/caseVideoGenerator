from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Iterator
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from server.app.core.config import Settings, load_settings
from server.app.main import create_app
from server.app.persistence.artifact_commit import ArtifactCommitService, ArtifactSource
from server.app.persistence.database import Database
from server.app.persistence.object_store import LocalObjectStore, SignedObjectTokenService
from server.app.persistence.repository import BudgetApprovalRequired, PhaseCRepository
from server.app.security.uploads import upload_scanner_from_settings
from server.app.services.revisions import PROGRAM_CLOSER, PROGRAM_OPENER


AUTH = {"Authorization": "Bearer integration-secret"}


def _settings(tmp_path: Path, *, tenant_id: str = "ten_a", role: str = "admin") -> Settings:
    return replace(
        load_settings(),
        deployment_mode="distributed",
        auth_mode="static-token",
        api_token="integration-secret",
        default_tenant_id=tenant_id,
        default_user_id=f"usr_{role}_{tenant_id}",
        default_role=role,
        database_url=f"sqlite+pysqlite:///{tmp_path / 'phase-c-api.sqlite'}",
        object_store_backend="local",
        object_store_root=tmp_path / "objects",
        upload_scanner_mode="structural",
        max_upload_bytes=1024 * 1024,
        max_upload_files=5,
        cors_origins=("https://ui.example",),
        csrf_trusted_origins=("https://ui.example",),
        csrf_enabled=True,
        signed_url_ttl_seconds=300,
        metrics_enabled=True,
    )


@pytest.fixture()
def phase_c_api(tmp_path: Path):
    settings = _settings(tmp_path)
    database = Database(settings.database_url)
    database.migrate()
    repository = PhaseCRepository(database)
    repository.ensure_tenant(
        "ten_a",
        name="Tenant A",
        quotas={
            "active_jobs": 20,
            "upload_bytes": 10 * 1024 * 1024,
            "upload_files": 20,
        },
    )
    repository.ensure_tenant(
        "ten_b",
        name="Tenant B",
        quotas={
            "active_jobs": 20,
            "upload_bytes": 10 * 1024 * 1024,
            "upload_files": 20,
        },
    )
    store = LocalObjectStore(settings.object_store_root)
    signer = SignedObjectTokenService(b"phase-c-api-signing-secret")

    @contextmanager
    def client_for(*, tenant_id: str = "ten_a", role: str = "admin") -> Iterator[TestClient]:
        scoped = replace(
            settings,
            default_tenant_id=tenant_id,
            default_user_id=f"usr_{role}_{tenant_id}",
            default_role=role,
        )
        app = create_app(
            scoped,
            database=database,
            repository=repository,
            object_store=store,
            object_signer=signer,
            upload_scanner=upload_scanner_from_settings(scoped),
        )
        with TestClient(app, base_url="https://api.example") as client:
            yield client

    try:
        with client_for() as client:
            yield {
                "client": client,
                "client_for": client_for,
                "database": database,
                "repository": repository,
                "store": store,
                "signer": signer,
                "tmp_path": tmp_path,
            }
    finally:
        database.dispose()


def _upload(client: TestClient, *, filename: str = "case.txt", content: bytes = b"case facts") -> str:
    created = client.post(
        "/v1/uploads",
        headers=AUTH,
        json={
            "filename": filename,
            "size_bytes": len(content),
            "media_type": "text/plain",
        },
    )
    assert created.status_code == 201, created.text
    payload = created.json()
    assert "object_key" not in payload
    completed = client.put(payload["content_url"], headers=AUTH, content=content)
    assert completed.status_code == 200, completed.text
    assert "object_key" not in completed.json()
    return payload["upload_id"]


def _create_source_job(
    client: TestClient,
    upload_id: str,
    *,
    key: str = "request-key-0001",
    project_name: str = "Distributed API case",
):
    return client.post(
        "/v1/jobs",
        headers={**AUTH, "Idempotency-Key": key},
        json={
            "project_name": project_name,
            "input_mode": "source",
            "approval_mode": "editorial",
            "upload_ids": [upload_id],
        },
    )


def _create_budget_wait(
    client: TestClient,
    repository: PhaseCRepository,
    *,
    key: str,
) -> tuple[str, str, int]:
    upload_id = _upload(client)
    created = client.post(
        "/v1/jobs",
        headers={**AUTH, "Idempotency-Key": key},
        json={
            "project_name": f"Budget {key}",
            "input_mode": "source",
            "approval_mode": "editorial",
            "upload_ids": [upload_id],
            "budget_limit_micros": 100,
        },
    )
    assert created.status_code == 202, created.text
    body = created.json()
    job_id = body["job"]["job_id"]
    stage_run_id = body["initial_stage"]["stage_run_id"]
    repository.claim_stage_run(
        "ten_a",
        stage_run_id,
        worker_id=f"worker-{key}",
        lease_seconds=90,
    )
    with pytest.raises(BudgetApprovalRequired):
        repository.reserve_cost(
            "ten_a",
            job_id,
            stage_run_id=stage_run_id,
            amount_micros=101,
            provider="openai",
            usage={"input_tokens": 10},
            pricing_version="test-v1",
            reference_id=f"call-{key}",
        )
    repository.pause_stage_run_for_budget(
        "ten_a",
        stage_run_id,
        worker_id=f"worker-{key}",
    )
    version = repository.get_job("ten_a", job_id)["row_version"]
    return job_id, stage_run_id, version


def _valid_narration(*, suffix: str = "") -> str:
    sentence = "客户团队梳理业务流程，销售经理逐项核对事实，双方围绕真实问题形成共识。"
    body = sentence * 30
    if suffix:
        body = f"{body}{suffix}"
    return f"{PROGRAM_OPENER}\n\n{body}\n\n{PROGRAM_CLOSER}"


def _seed_editorial(client: TestClient, *, key: str) -> tuple[str, dict]:
    upload_id = _upload(client)
    created = _create_source_job(client, upload_id, key=key)
    assert created.status_code == 202, created.text
    job_id = created.json()["job"]["job_id"]
    revision = client.app.state.distributed_revisions.create_editorial(
        "ten_a",
        job_id,
        title="一次共识如何改变销售管理",
        narration=_valid_narration(),
        change_summary="建立待审核文稿",
        actor="system-seed",
        author_type="model",
        enforce_concurrency=False,
    )
    return job_id, revision


def test_distributed_readiness_capabilities_and_strict_model_routes(phase_c_api) -> None:
    client = phase_c_api["client"]
    assert client.get("/health/live").json() == {"status": "ok"}
    ready = client.get("/health/ready")
    assert ready.status_code == 200
    assert ready.json()["deployment_mode"] == "distributed"

    unauthorized = client.get("/v1/capabilities")
    assert unauthorized.status_code == 401
    capabilities = client.get("/v1/capabilities", headers=AUTH)
    assert capabilities.status_code == 200
    routes = capabilities.json()["model_routes"]
    assert routes["narration"] == {
        "provider": "azure_anthropic",
        "model": "salesnail-cs-46",
        "task_family": "narration",
        "api_version": routes["narration"]["api_version"],
        "transport": "anthropic_messages",
    }
    assert routes["remotion"]["provider"] == "azure_anthropic"
    assert routes["remotion"]["transport"] == "anthropic_messages"
    assert routes["general"]["provider"] == "openai"
    assert routes["general"]["model"] == "gpt-5.5"
    assert routes["general"]["transport"] == "openai_responses"
    readiness = capabilities.json()["model_route_readiness"]
    assert readiness["narration"]["configured"] is True
    assert readiness["remotion"]["configured"] is True
    assert readiness["general"]["configured"] is True
    assert capabilities.json()["pipeline_stage_count"] == 21


def test_upload_job_creation_is_atomic_idempotent_and_outbox_driven(phase_c_api) -> None:
    client = phase_c_api["client"]
    repository = phase_c_api["repository"]
    upload_id = _upload(client)

    first = _create_source_job(client, upload_id)
    assert first.status_code == 202, first.text
    first_payload = first.json()
    assert first_payload["created"] is True
    job_id = first_payload["job"]["job_id"]
    assert first_payload["initial_stage"]["stage"] == "ingest.validate"

    repeated = _create_source_job(client, upload_id)
    assert repeated.status_code == 202
    assert repeated.json()["created"] is False
    assert repeated.json()["job"]["job_id"] == job_id

    conflict = _create_source_job(client, upload_id, project_name="Different request")
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "idempotency_conflict"

    pending = repository.pending_outbox()
    assert any(
        item["topic"] == "queue.planning"
        and item["aggregate_id"] == first_payload["initial_stage"]["stage_run_id"]
        and item["payload"]["stage_run_id"] == first_payload["initial_stage"]["stage_run_id"]
        for item in pending
    )
    detail = client.get(f"/v1/jobs/{job_id}", headers=AUTH)
    assert detail.status_code == 200
    assert detail.json()["inputs"][0]["upload_id"] == upload_id
    assert "object_key" not in detail.json()["inputs"][0]

    events = client.get(f"/v1/jobs/{job_id}/events", headers=AUTH)
    assert events.status_code == 200
    assert events.json()["items"]
    stream = client.get(f"/v1/jobs/{job_id}/events/stream?follow=false", headers=AUTH)
    assert stream.status_code == 200
    assert "retry: 2000" in stream.text
    assert "event:" in stream.text
    assert ": heartbeat" in stream.text


def test_project_input_browser_csrf_and_quarantine_boundaries(phase_c_api) -> None:
    client = phase_c_api["client"]
    rejected = client.post(
        "/v1/jobs",
        headers={**AUTH, "Idempotency-Key": "project-mode-key"},
        json={"project_name": "unsafe", "input_mode": "project", "seed_project": "legacy"},
    )
    assert rejected.status_code == 400

    browser_headers = {**AUTH, "Origin": "https://ui.example"}
    blocked = client.post(
        "/v1/uploads",
        headers=browser_headers,
        json={"filename": "case.txt", "size_bytes": 4, "media_type": "text/plain"},
    )
    assert blocked.status_code == 403
    assert blocked.json()["code"] == "forbidden"

    csrf = client.post("/v1/session/csrf", headers=browser_headers)
    assert csrf.status_code == 200
    token = csrf.json()["csrf_token"]
    accepted = client.post(
        "/v1/uploads",
        headers={**browser_headers, "X-CSRF-Token": token},
        json={"filename": "case.txt", "size_bytes": 4, "media_type": "text/plain"},
    )
    assert accepted.status_code == 201

    eicar = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
    with phase_c_api["client_for"]() as api_client:
        infected_id = _upload(api_client, filename="malware.txt", content=eicar)
        infected = api_client.get(f"/v1/uploads/{infected_id}", headers=AUTH).json()
        assert infected["status"] == "quarantined"
        assert infected["scan_status"] == "infected"
        cannot_bind = _create_source_job(api_client, infected_id, key="infected-key-0001")
        assert cannot_bind.status_code == 409


def test_browser_csrf_trusts_request_origin_without_weakening_cross_origin_checks(
    phase_c_api,
) -> None:
    client = phase_c_api["client"]
    original_settings = client.app.state.settings
    client.app.state.settings = replace(
        original_settings,
        cors_origins=(),
        csrf_trusted_origins=(),
    )
    try:
        same_origin = client.post(
            "/v1/session/csrf",
            headers={**AUTH, "Origin": "https://api.example"},
        )
        assert same_origin.status_code == 200, same_origin.text

        cross_origin = client.post(
            "/v1/session/csrf",
            headers={**AUTH, "Origin": "https://evil.example"},
        )
        assert cross_origin.status_code == 403, cross_origin.text
        assert cross_origin.json()["code"] == "forbidden"
    finally:
        client.app.state.settings = original_settings


def test_browser_csrf_token_stays_valid_across_multiple_tabs(phase_c_api) -> None:
    client = phase_c_api["client"]
    headers = {**AUTH, "Origin": "https://ui.example"}

    first = client.post("/v1/session/csrf", headers=headers)
    second = client.post("/v1/session/csrf", headers=headers)
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["csrf_token"] == first.json()["csrf_token"]

    accepted = client.post(
        "/v1/uploads",
        headers={**headers, "X-CSRF-Token": first.json()["csrf_token"]},
        json={"filename": "multi-tab.txt", "size_bytes": 4, "media_type": "text/plain"},
    )
    assert accepted.status_code == 201, accepted.text


def test_role_matrix_and_cross_tenant_ids_are_enforced(phase_c_api) -> None:
    admin = phase_c_api["client"]
    upload_id = _upload(admin)
    created = _create_source_job(admin, upload_id, key="tenant-a-key-0001").json()
    job_id = created["job"]["job_id"]

    with phase_c_api["client_for"](tenant_id="ten_a", role="viewer") as viewer:
        assert viewer.get(f"/v1/jobs/{job_id}", headers=AUTH).status_code == 200
        denied = viewer.post(
            "/v1/uploads",
            headers=AUTH,
            json={"filename": "x.txt", "size_bytes": 1, "media_type": "text/plain"},
        )
        assert denied.status_code == 403

    with phase_c_api["client_for"](tenant_id="ten_a", role="editor") as editor:
        allowed = editor.post(
            "/v1/uploads",
            headers=AUTH,
            json={"filename": "x.txt", "size_bytes": 1, "media_type": "text/plain"},
        )
        assert allowed.status_code == 201
        assert editor.get("/v1/governance", headers=AUTH).status_code == 403

    with phase_c_api["client_for"](tenant_id="ten_a", role="producer") as producer:
        assert producer.get("/v1/costs/summary", headers=AUTH).status_code == 200
        assert producer.patch("/v1/governance", headers=AUTH, json={"quotas": {}}).status_code == 403

    with phase_c_api["client_for"](tenant_id="ten_b", role="admin") as tenant_b:
        hidden = tenant_b.get(f"/v1/jobs/{job_id}", headers=AUTH)
        assert hidden.status_code == 404
        hidden_events = tenant_b.get(f"/v1/jobs/{job_id}/events/stream", headers=AUTH)
        assert hidden_events.status_code == 404


def test_budget_decision_rbac_resumes_original_stage_and_operations_are_admin_only(
    phase_c_api,
) -> None:
    admin = phase_c_api["client"]
    repository = phase_c_api["repository"]
    job_id, stage_run_id, version = _create_budget_wait(
        admin,
        repository,
        key="budget-reduce-key",
    )

    with phase_c_api["client_for"](tenant_id="ten_a", role="producer") as producer:
        forbidden = producer.post(
            f"/v1/jobs/{job_id}/budget/decision",
            headers=AUTH,
            json={
                "decision": "approved",
                "resolution": "raise_limit",
                "expected_job_version": version,
                "new_limit_micros": 200,
            },
        )
        assert forbidden.status_code == 403

        approved = producer.post(
            f"/v1/jobs/{job_id}/budget/decision",
            headers=AUTH,
            json={
                "decision": "approved",
                "resolution": "reduce_scope",
                "expected_job_version": version,
                "reduced_scope": {"image_count": 4, "preview_only": True},
                "reason": "stay within the approved budget",
            },
        )
        assert approved.status_code == 200, approved.text
        payload = approved.json()
        assert payload["job"]["status"] == "queued"
        assert payload["job"]["generation_scope"]["image_count"] == 4
        assert payload["stage_run"]["stage_run_id"] == stage_run_id
        assert payload["stage_run"]["status"] == "queued"
        assert producer.get("/v1/operations/snapshot", headers=AUTH).status_code == 403
        assert producer.get(producer.app.state.settings.metrics_path, headers=AUTH).status_code == 403

    raised_job, raised_stage, raised_version = _create_budget_wait(
        admin,
        repository,
        key="budget-raise-key",
    )
    raised = admin.post(
        f"/v1/jobs/{raised_job}/budget/decision",
        headers=AUTH,
        json={
            "decision": "approved",
            "resolution": "raise_limit",
            "expected_job_version": raised_version,
            "new_limit_micros": 200,
            "reason": "administrator approved the incremental spend",
        },
    )
    assert raised.status_code == 200, raised.text
    assert raised.json()["job"]["budget"]["limit_micros"] == 200
    assert raised.json()["stage_run"]["stage_run_id"] == raised_stage

    snapshot = admin.get("/v1/operations/snapshot", headers=AUTH)
    assert snapshot.status_code == 200, snapshot.text
    body = snapshot.json()
    assert {item["queue"] for item in body["queues"]} == {
        "planning",
        "media",
        "render",
        "qa",
    }
    assert body["leases"] == {"active": 0, "expired": 0}
    assert "job_id" not in snapshot.text
    metrics = admin.get(admin.app.state.settings.metrics_path, headers=AUTH)
    assert metrics.status_code == 200
    assert "http_requests_total" in metrics.text
    assert "casevideo_metrics_collection_success 1" in metrics.text
    assert "casevideo_tenants 2" in metrics.text
    assert 'casevideo_queue_depth{queue="planning"}' in metrics.text
    assert 'casevideo_model_route_ready{provider="azure_anthropic",route="narration"}' in metrics.text
    assert 'casevideo_model_route_ready{provider="openai",route="general"}' in metrics.text
    assert "tenant_id=" not in metrics.text
    assert "job_id=" not in metrics.text
    assert "worker_id=" not in metrics.text


def test_cancel_and_retry_api_are_idempotent_rbac_protected_and_audited(phase_c_api) -> None:
    client = phase_c_api["client"]
    upload_id = _upload(client)
    created = _create_source_job(client, upload_id, key="cancel-retry-key-0001").json()
    job_id = created["job"]["job_id"]

    with phase_c_api["client_for"](tenant_id="ten_a", role="viewer") as viewer:
        denied = viewer.post(f"/v1/jobs/{job_id}/cancel", headers=AUTH, json={})
        assert denied.status_code == 403

    canceled = client.post(
        f"/v1/jobs/{job_id}/cancel",
        headers=AUTH,
        json={"reason": "operator requested stop"},
    )
    assert canceled.status_code == 200, canceled.text
    assert canceled.json()["job"]["status"] == "canceled"
    repeated_cancel = client.post(f"/v1/jobs/{job_id}/cancel", headers=AUTH, json={})
    assert repeated_cancel.status_code == 200
    assert repeated_cancel.json()["job"]["cancellation"] == "already_canceled"

    retried = client.post(f"/v1/jobs/{job_id}/retry", headers=AUTH, json={})
    assert retried.status_code == 202, retried.text
    assert retried.json()["created"] is True
    assert retried.json()["stage_run"]["retry_cycle"] == 1
    repeated_retry = client.post(f"/v1/jobs/{job_id}/retry", headers=AUTH, json={})
    assert repeated_retry.status_code == 202
    assert repeated_retry.json()["created"] is False
    assert repeated_retry.json()["stage_run"]["stage_run_id"] == retried.json()["stage_run"]["stage_run_id"]

    detail = client.get(f"/v1/jobs/{job_id}", headers=AUTH).json()
    assert len(detail["stage_runs"]) == 2
    quota = client.get(f"/v1/jobs/{job_id}/quotas", headers=AUTH)
    assert quota.status_code == 200
    active = [item for item in quota.json()["items"] if item["dimension"] == "active_jobs"]
    assert active and active[0]["status"] == "active"

    audit = client.get("/v1/audit", headers=AUTH).text
    assert "job.cancel" in audit
    assert "job.retry" in audit


def test_signed_artifact_download_is_authorized_and_not_audited_with_token(phase_c_api) -> None:
    client = phase_c_api["client"]
    repository = phase_c_api["repository"]
    store = phase_c_api["store"]
    source = phase_c_api["tmp_path"] / "artifact.txt"
    source.write_text("delivery bytes", encoding="utf-8")

    upload_id = _upload(client)
    created = _create_source_job(client, upload_id, key="download-key-0001").json()
    job_id = created["job"]["job_id"]
    ArtifactCommitService(repository, store).commit(
        tenant_id="ten_a",
        job_id=job_id,
        domain="delivery",
        revision_id="rev_delivery_1",
        sources=[ArtifactSource("final/artifact.txt", source, "text/plain")],
        created_by="usr_admin_ten_a",
    )

    issued = client.post(
        f"/v1/jobs/{job_id}/artifacts/final/artifact.txt/download",
        headers=AUTH,
    )
    assert issued.status_code == 200, issued.text
    download_url = issued.json()["download_url"]
    assert "integration-secret" not in download_url
    downloaded = client.get(download_url)
    assert downloaded.status_code == 200
    assert downloaded.content == b"delivery bytes"

    parts = urlsplit(download_url)
    token = parts.path.rsplit("/", 1)[-1]
    tampered = client.get(parts.path[: -len(token)] + token[:-1] + ("A" if token[-1] != "A" else "B"))
    assert tampered.status_code == 404

    audit = client.get("/v1/audit", headers=AUTH)
    assert audit.status_code == 200
    serialized = audit.text
    assert "artifact.download.issue" in serialized
    assert token not in serialized
    assert "download_url" not in serialized

    deleted = client.delete(f"/v1/jobs/{job_id}", headers=AUTH)
    assert deleted.status_code == 200
    assert client.get(download_url).status_code == 404


def test_distributed_revision_reads_project_prefixed_workspace_json(phase_c_api) -> None:
    client = phase_c_api["client"]
    repository = phase_c_api["repository"]
    store = phase_c_api["store"]
    timeline = {"units": [{"unit": 1, "text": "第一句"}]}
    timeline_path = phase_c_api["tmp_path"] / "narration.timeline.json"
    timeline_path.write_text(json.dumps(timeline, ensure_ascii=False), encoding="utf-8")

    upload_id = _upload(client)
    created = _create_source_job(client, upload_id, key="workspace-timeline-key").json()
    job_id = created["job"]["job_id"]
    ArtifactCommitService(repository, store).commit(
        tenant_id="ten_a",
        job_id=job_id,
        domain="workspace",
        revision_id="workspace-timeline-1",
        sources=[ArtifactSource("project/narration.timeline.json", timeline_path, "application/json")],
        created_by="worker-test",
    )

    revisions = client.app.state.distributed_revisions
    assert revisions._current_json_file("ten_a", job_id, "narration.timeline.json") == timeline
    assert revisions._timeline_unit_count("ten_a", job_id) == 1


def test_distributed_editorial_revisions_are_immutable_and_concurrency_safe(phase_c_api) -> None:
    admin = phase_c_api["client"]
    job_id, seeded = _seed_editorial(admin, key="editorial-concurrency-key")
    original_revision = seeded["metadata"]["revision_id"]

    review_response = admin.get(f"/v1/jobs/{job_id}/reviews/editorial", headers=AUTH)
    assert review_response.status_code == 200, review_response.text
    assert review_response.headers["cache-control"] == "no-store"
    assert review_response.headers["etag"] == review_response.json()["etag"]
    original_etag = review_response.headers["etag"]

    with phase_c_api["client_for"](tenant_id="ten_a", role="editor") as editor:
        saved = editor.post(
            f"/v1/jobs/{job_id}/reviews/editorial/revisions",
            headers={**AUTH, "If-Match": original_etag},
            json={
                "base_revision": original_revision,
                "title": "销售经理如何推动团队形成共识",
                "narration": _valid_narration(),
                "change_summary": "只修改标题",
                "actor": "spoofed-admin",
            },
        )
        assert saved.status_code == 200, saved.text
        current = saved.json()
        assert current["revision"] != original_revision
        assert current["metadata"]["actor"] == "usr_editor_ten_a"
        assert "tts.generate" not in current["metadata"].get("invalidated_stages", [])

        stale = editor.post(
            f"/v1/jobs/{job_id}/reviews/editorial/revisions",
            headers={**AUTH, "If-Match": original_etag},
            json={
                "base_revision": original_revision,
                "title": "过期客户端标题",
                "narration": _valid_narration(),
                "change_summary": "模拟过期保存",
            },
        )
        assert stale.status_code == 409
        assert stale.json()["code"] == "revision_conflict"
        assert stale.json()["current_revision"] == current["revision"]
        assert stale.json()["current_etag"] == current["etag"]

    history = admin.get(f"/v1/jobs/{job_id}/revisions/editorial", headers=AUTH)
    assert history.status_code == 200
    assert len(history.json()["revisions"]) == 2
    original = admin.get(
        f"/v1/jobs/{job_id}/revisions/editorial/{original_revision}",
        headers=AUTH,
    )
    assert original.status_code == 200
    assert original.json()["files"]["title.txt"].strip() == "一次共识如何改变销售管理"

    with phase_c_api["client_for"](tenant_id="ten_b", role="admin") as tenant_b:
        assert tenant_b.get(f"/v1/jobs/{job_id}/reviews/editorial", headers=AUTH).status_code == 404
        assert tenant_b.get(f"/v1/jobs/{job_id}/revisions/editorial", headers=AUTH).status_code == 404


def test_distributed_editorial_approval_is_rbac_guarded_atomic_and_audited(phase_c_api) -> None:
    admin = phase_c_api["client"]
    repository = phase_c_api["repository"]
    job_id, _ = _seed_editorial(admin, key="editorial-approval-key")
    review = admin.get(f"/v1/jobs/{job_id}/reviews/editorial", headers=AUTH).json()
    payload = {
        "revision": review["revision"],
        "base_revision": review["revision"],
        "has_unsaved_draft": False,
        "actor": "spoofed-approver",
    }

    with phase_c_api["client_for"](tenant_id="ten_a", role="editor") as editor:
        denied = editor.post(
            f"/v1/jobs/{job_id}/reviews/editorial/approve",
            headers={**AUTH, "If-Match": review["etag"]},
            json=payload,
        )
        assert denied.status_code == 403

    with phase_c_api["client_for"](tenant_id="ten_a", role="producer") as producer:
        blocked = producer.post(
            f"/v1/jobs/{job_id}/reviews/editorial/approve",
            headers={**AUTH, "If-Match": review["etag"]},
            json={**payload, "has_unsaved_draft": True},
        )
        assert blocked.status_code == 409
        assert blocked.json()["code"] == "approval_required"

        approved = producer.post(
            f"/v1/jobs/{job_id}/reviews/editorial/approve",
            headers={**AUTH, "If-Match": review["etag"]},
            json=payload,
        )
        assert approved.status_code == 200, approved.text
        body = approved.json()
        assert body["is_approved"] is True
        assert body["stage_run"]["stage"] == "tts.generate"
        stage_run_id = body["stage_run"]["stage_run_id"]

        repeated = producer.post(
            f"/v1/jobs/{job_id}/reviews/editorial/approve",
            headers={**AUTH, "If-Match": review["etag"]},
            json=payload,
        )
        assert repeated.status_code == 200
        assert repeated.json()["reused"] is True

    queued = next(item for item in repository.pending_outbox() if item["aggregate_id"] == stage_run_id)
    assert queued["topic"] == "queue.media"
    assert set(queued["payload"]) == {
        "message_version",
        "tenant_id",
        "job_id",
        "stage_run_id",
        "expected_job_version",
        "input_snapshot_hash",
        "priority",
        "enqueued_at",
    }
    audit = admin.get("/v1/audit", headers=AUTH)
    assert audit.status_code == 200
    assert "review.approved" in audit.text
    assert "usr_producer_ten_a" in audit.text
    assert "spoofed-approver" not in audit.text


def test_model_revision_is_queued_only_for_pinned_azure_anthropic_route(phase_c_api) -> None:
    admin = phase_c_api["client"]
    repository = phase_c_api["repository"]
    job_id, _ = _seed_editorial(admin, key="editorial-model-revision-key")
    review = admin.get(f"/v1/jobs/{job_id}/reviews/editorial", headers=AUTH).json()
    request_payload = {
        "base_revision": review["revision"],
        "feedback": "请强化开头冲突，并保持现有事实边界。",
        "issues": [{"issue_id": "human-1", "severity": "warning"}],
        "change_summary": "根据编辑反馈重写旁白",
        "actor": "spoofed-model-user",
    }

    with phase_c_api["client_for"](tenant_id="ten_a", role="editor") as editor:
        queued = editor.post(
            f"/v1/jobs/{job_id}/reviews/editorial/model-revisions",
            headers={**AUTH, "If-Match": review["etag"]},
            json=request_payload,
        )
        assert queued.status_code == 202, queued.text
        body = queued.json()
        assert body["stage_run"]["stage"] == "editorial.rewrite"
        assert body["stage_run"]["queue_name"] == "planning"
        assert body["revision_request"]["task"] == "narration.rewrite"
        assert body["revision_request"]["actor"] == "usr_editor_ten_a"
        assert body["revision_request"]["status"] == "queued"
        assert body["revision_request"]["stage_run_id"] == body["stage_run"]["stage_run_id"]
        request_id = body["revision_request"]["request_id"]
        stage_run_id = body["stage_run"]["stage_run_id"]

        status = editor.get(
            f"/v1/jobs/{job_id}/model-revision-requests/{request_id}",
            headers=AUTH,
        )
        assert status.status_code == 200, status.text
        status_body = status.json()
        assert status_body["request_id"] == request_id
        assert status_body["stage_run_id"] == stage_run_id
        assert status_body["status"] == "queued"
        assert status_body["task"] == "narration.rewrite"
        assert "feedback" not in status.text
        assert "issues" not in status.text

        repeated = editor.post(
            f"/v1/jobs/{job_id}/reviews/editorial/model-revisions",
            headers={**AUTH, "If-Match": review["etag"]},
            json=request_payload,
        )
        assert repeated.status_code == 202
        assert repeated.json()["reused"] is True
        assert repeated.json()["stage_run"]["stage_run_id"] == stage_run_id
        assert repeated.json()["revision_request"]["status"] == "queued"

    job = repository.get_job("ten_a", job_id)
    route = job["task_registry"]["narration.rewrite"]
    assert route["provider"] == "azure_anthropic"
    assert route["model"] == "salesnail-cs-46"
    assert route["transport"] == "anthropic_messages"
    message = next(item for item in repository.pending_outbox() if item["aggregate_id"] == stage_run_id)
    assert message["topic"] == "queue.planning"
    assert "feedback" not in message["payload"]
    assert "issues" not in message["payload"]


def test_editorial_invalidation_distinguishes_title_and_narration_changes(phase_c_api) -> None:
    client = phase_c_api["client"]
    repository = phase_c_api["repository"]
    job_id, _ = _seed_editorial(client, key="editorial-invalidation-key")
    initial = client.get(f"/v1/jobs/{job_id}/reviews/editorial", headers=AUTH).json()

    title_only = client.post(
        f"/v1/jobs/{job_id}/reviews/editorial/revisions",
        headers={**AUTH, "If-Match": initial["etag"]},
        json={
            "base_revision": initial["revision"],
            "title": "团队共识如何打开销售局面",
            "narration": _valid_narration(),
            "change_summary": "验证标题级失效范围",
        },
    )
    assert title_only.status_code == 200, title_only.text
    title_invalidation = repository.get_job("ten_a", job_id)["invalidations"][-1]
    assert title_invalidation["changes"] == ["title"]
    assert "tts.generate" not in title_invalidation["stages"]
    assert "visual.plan" in title_invalidation["stages"]

    title_review = title_only.json()
    narration_change = client.post(
        f"/v1/jobs/{job_id}/reviews/editorial/revisions",
        headers={**AUTH, "If-Match": title_review["etag"]},
        json={
            "base_revision": title_review["revision"],
            "title": "团队共识如何打开销售局面",
            "narration": _valid_narration(suffix="团队随后把行动责任落实到每一个关键节点。"),
            "change_summary": "验证旁白级失效范围",
        },
    )
    assert narration_change.status_code == 200, narration_change.text
    narration_invalidation = repository.get_job("ten_a", job_id)["invalidations"][-1]
    assert "narration" in narration_invalidation["changes"]
    assert "tts.generate" in narration_invalidation["stages"]
