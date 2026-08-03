from __future__ import annotations

import copy
from pathlib import Path

from server.app.operations.upgrade import UpgradeSnapshotService, read_snapshot, write_snapshot
from server.app.persistence.database import Database
from server.app.persistence.models import Job
from server.app.persistence.repository import PhaseCRepository, StageIdentity, sha256_json


def _manifest(job_id: str) -> dict[str, object]:
    task_pin = {
        "task": "narration.compose",
        "route_family": "narration",
        "provider": "azure_anthropic",
        "model": "case-video-claude",
        "transport": "anthropic_messages",
        "prompt_version": "v1",
        "prompt_sha256": "1" * 64,
        "output_schema": {
            "name": "editorial",
            "version": "v1",
            "sha256": "2" * 64,
        },
    }
    return {
        "manifest_version": 2,
        "job_id": job_id,
        "project_name": "Upgrade acceptance",
        "status": "running",
        "display_status": "运行中",
        "stage": "editorial.compose",
        "input_mode": "source",
        "approval_mode": "editorial",
        "model_routes": {
            "narration": {
                "provider": "azure_anthropic",
                "model": "case-video-claude",
                "transport": "anthropic_messages",
            },
            "remotion": {
                "provider": "azure_anthropic",
                "model": "case-video-claude",
                "transport": "anthropic_messages",
            },
            "general": {
                "provider": "openai",
                "model": "gpt-5.5",
                "transport": "openai_responses",
            },
        },
        "contract_versions": {"editorial": "v1"},
        "prompt_pins": {
            "narration.compose": {"version": "v1", "sha256": "1" * 64}
        },
        "task_registry": {"narration.compose": task_pin},
    }


def _seed(database: Database) -> None:
    repository = PhaseCRepository(database)
    repository.ensure_tenant("ten_upgrade", name="Upgrade")
    manifest = _manifest("job_upgrade")
    repository.create_job(
        "ten_upgrade",
        manifest,
        config_snapshot={
            "manifest_version": 2,
            "contract_versions": manifest["contract_versions"],
            "prompt_pins": manifest["prompt_pins"],
            "task_registry": manifest["task_registry"],
        },
        engine_snapshot={
            "image": "case-video-generator",
            "digest": "sha256:" + "3" * 64,
        },
    )
    task_pin = manifest["task_registry"]["narration.compose"]
    stage, _ = repository.create_stage_run(
        StageIdentity(
            tenant_id="ten_upgrade",
            job_id="job_upgrade",
            stage="editorial.compose",
            input_hash="4" * 64,
            route_snapshot_hash=sha256_json(task_pin),
            config_snapshot_hash=sha256_json(
                {
                    "manifest_version": 2,
                    "contract_versions": manifest["contract_versions"],
                    "prompt_pin": manifest["prompt_pins"]["narration.compose"],
                    "task": task_pin,
                }
            ),
        ),
        queue_name="planning",
    )
    repository.record_model_run(
        "ten_upgrade",
        {
            "id": "mdl_upgrade",
            "job_id": "job_upgrade",
            "stage_run_id": stage["stage_run_id"],
            "task": "narration.compose",
            "provider": "azure_anthropic",
            "model": "case-video-claude",
            "route_snapshot": {
                "provider": "azure_anthropic",
                "model": "case-video-claude",
                "transport": "anthropic_messages",
            },
            "prompt_version": "v1",
            "schema_version": "v1",
            "status": "succeeded",
        },
    )


def test_rolling_upgrade_and_application_rollback_preserve_in_flight_pins(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'upgrade.sqlite'}"
    old_release = Database(database_url)
    old_release.migrate()
    _seed(old_release)
    baseline = UpgradeSnapshotService(old_release).capture()
    snapshot_path = tmp_path / "pre-upgrade.json"
    write_snapshot(snapshot_path, baseline)
    old_release.dispose()

    new_release = Database(database_url)
    new_release.migrate()
    assert UpgradeSnapshotService(new_release).verify(read_snapshot(snapshot_path))["passed"]
    new_release.dispose()

    rolled_back_release = Database(database_url)
    rolled_back_release.check_schema()
    rollback_report = UpgradeSnapshotService(rolled_back_release).verify(
        read_snapshot(snapshot_path)
    )
    assert rollback_report["passed"] is True
    assert rollback_report["jobs_checked"] == 1
    assert rollback_report["baseline_schema_version"] == rollback_report[
        "current_schema_version"
    ]
    rolled_back_release.dispose()


def test_upgrade_verifier_detects_snapshot_mutation_and_new_unpinned_model_run(
    tmp_path: Path,
) -> None:
    database = Database(f"sqlite+pysqlite:///{tmp_path / 'mutation.sqlite'}")
    database.migrate()
    _seed(database)
    service = UpgradeSnapshotService(database)
    baseline = service.capture()

    with database.transaction() as session:
        job = session.get(Job, ("ten_upgrade", "job_upgrade"))
        assert job is not None
        changed = copy.deepcopy(job.engine_snapshot)
        changed["digest"] = "sha256:" + "9" * 64
        job.engine_snapshot = changed

    repository = PhaseCRepository(database)
    repository.record_model_run(
        "ten_upgrade",
        {
            "id": "mdl_wrong_default",
            "job_id": "job_upgrade",
            "task": "narration.compose",
            "provider": "openai",
            "model": "gpt-5.5",
            "route_snapshot": {
                "provider": "openai",
                "model": "gpt-5.5",
                "transport": "openai_responses",
            },
            "prompt_version": "v2",
            "schema_version": "v2",
            "status": "succeeded",
        },
    )

    report = service.verify(baseline)
    assert report["passed"] is False
    assert {issue["code"] for issue in report["issues"]} == {
        "immutable_snapshot_changed",
        "model_run_not_pinned_to_job_registry",
    }
    assert any(
        "$.engine_snapshot.digest" in issue["paths"] for issue in report["issues"]
    )
    database.dispose()
