from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_SERVICES = {
    "api",
    "backup",
    "bootstrap",
    "dispatcher",
    "legacy-migration-dry-run",
    "legacy-migration-import",
    "legacy-migration-shadow",
    "maintenance",
    "media-worker",
    "migration",
    "planning-worker",
    "qa-worker",
    "queue-rebuild",
    "reaper",
    "render-worker-1",
    "render-worker-2",
    "render-worker-3",
    "upgrade-capture",
    "upgrade-verify",
}


def _compose_config() -> dict[str, object]:
    if shutil.which("docker") is None:
        pytest.skip("docker compose is not installed")
    probe = subprocess.run(
        ["docker", "compose", "version"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if probe.returncode != 0:
        pytest.skip("docker compose is not available")

    environment = {
        **os.environ,
        "CASE_VIDEO_DATABASE_URL": (
            "postgresql+psycopg://casevideo:test@postgres:5432/casevideo"
        ),
        "CASE_VIDEO_RENDER_ENGINE_DIGEST": "sha256:" + "a" * 64,
        "CASE_VIDEO_OBJECT_STORE_SIGNING_SECRET": "test-signing-secret-at-least-32-bytes",
        "MINIO_ROOT_USER": "casevideo-test",
        "MINIO_ROOT_PASSWORD": "test-minio-password",
        "POSTGRES_PASSWORD": "test-postgres-password",
        "AZURE_ANTHROPIC_ENDPOINT": "https://example.test/anthropic/v1/messages",
        "AZURE_ANTHROPIC_API_KEY": "test-anthropic-key",
        "AZURE_OPENAI_ENDPOINT": "https://example.test/openai/v1",
        "AZURE_OPENAI_API_KEY": "test-openai-key",
    }
    result = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            "/dev/null",
            "--profile",
            "render-ha",
            "--profile",
            "operations",
            "config",
            "--format",
            "json",
        ],
        cwd=REPO_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_compose_declares_full_phase_c_topology_and_strict_model_routes() -> None:
    config = _compose_config()
    services = config["services"]
    assert isinstance(services, dict)
    expected = APP_SERVICES | {
        "postgres",
        "redis",
        "minio",
        "minio-init",
        "clamav",
        "operations-volume-init",
    }
    assert expected <= set(services)

    environment = services["api"]["environment"]
    assert environment["CASE_VIDEO_NARRATION_PROVIDER"] == "azure_anthropic"
    assert environment["CASE_VIDEO_NARRATION_MODEL"] == "salesnail-cs-46"
    assert environment["CASE_VIDEO_REMOTION_PROVIDER"] == "azure_anthropic"
    assert environment["CASE_VIDEO_REMOTION_MODEL"] == "salesnail-cs-46"
    assert environment["CASE_VIDEO_AZURE_ANTHROPIC_DEPLOYMENT"] == "salesnail-cs-46"
    assert environment["CASE_VIDEO_GENERAL_PROVIDER"] == "openai"
    assert environment["CASE_VIDEO_GENERAL_MODEL"] == "gpt-5.5"
    assert environment["CASE_VIDEO_GENERAL_REQUEST_MODEL"] == "gpt-5.5"
    assert environment["CASE_VIDEO_GENERAL_AUTH_MODE"] == "api-key"
    assert environment["CASE_VIDEO_RATE_LIMIT_BACKEND"] == "redis"
    assert environment["CASE_VIDEO_API_RATE_LIMIT_PER_MINUTE"] == "240"
    assert environment["CASE_VIDEO_API_RATE_LIMIT_BURST"] == "40"
    assert environment["CASE_VIDEO_MAX_UPLOAD_BYTES"] == "209715200"
    assert environment["CASE_VIDEO_MAX_UPLOAD_FILES"] == "25"
    assert environment["AZURE_ANTHROPIC_ENDPOINT"].endswith("/v1/messages")
    assert environment["AZURE_OPENAI_ENDPOINT"].endswith("/openai/v1")
    assert services["clamav"]["platform"] == "linux/amd64"


def test_compose_hardens_app_containers_and_isolates_render_workers() -> None:
    config = _compose_config()
    services = config["services"]
    for name in APP_SERVICES:
        service = services[name]
        assert service["user"] == "10001:10001"
        assert service["read_only"] is True
        assert "ALL" in service["cap_drop"]
        assert "no-new-privileges:true" in service["security_opt"]
        assert all("docker.sock" not in str(volume) for volume in service.get("volumes", []))

    for index in range(1, 4):
        service = services[f"render-worker-{index}"]
        assert service["command"][-1] == "render"
        assert service["environment"]["REMOTION_CONCURRENCY"] == "1"
        assert service["cpus"] == 4
        assert int(service["mem_limit"]) == 8 * 1024**3
        assert service["pids_limit"] == 1024
        assert int(service["shm_size"]) == 2 * 1024**3
        volume_targets = {item["target"] for item in service["volumes"]}
        assert {"/work/stages", "/work/renders"} <= volume_targets
        assert "egress" not in service["networks"]

    assert config["networks"]["backend"]["internal"] is True
    assert set(services["api"]["networks"]) == {"backend", "egress"}
    assert set(services["planning-worker"]["networks"]) == {"backend", "egress"}
    assert set(services["media-worker"]["networks"]) == {"backend", "egress"}
    assert set(services["clamav"]["networks"]) == {"backend", "egress"}
    assert services["api"]["depends_on"]["clamav"]["condition"] == "service_healthy"

    bootstrap_capabilities = {"CHOWN", "DAC_OVERRIDE", "FOWNER", "SETGID", "SETUID"}
    for name in ("postgres", "redis", "clamav"):
        assert set(services[name]["cap_add"]) == bootstrap_capabilities
        assert "ALL" in services[name]["cap_drop"]
    assert not services["minio"].get("cap_add")

    volume_init = services["operations-volume-init"]
    assert volume_init["user"] == "0:0"
    assert volume_init["network_mode"] == "none"
    assert volume_init["read_only"] is True
    assert set(volume_init["cap_drop"]) == {"ALL"}
    assert set(volume_init["cap_add"]) == {"CHOWN", "FOWNER"}
    assert "no-new-privileges:true" in volume_init["security_opt"]
    assert set(volume_init["profiles"]) == {"operations"}

    for name in (
        "backup",
        "upgrade-capture",
        "upgrade-verify",
        "legacy-migration-dry-run",
        "legacy-migration-import",
        "legacy-migration-shadow",
    ):
        assert (
            services[name]["depends_on"]["operations-volume-init"]["condition"]
            == "service_completed_successfully"
        )


def test_runtime_image_is_non_root_and_uses_system_chromium() -> None:
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    package = json.loads(
        (REPO_ROOT / "engine" / "remotion" / "package.json").read_text(encoding="utf-8")
    )

    assert "USER ${APP_UID}:${APP_GID}" in dockerfile
    assert "ENTRYPOINT [\"/usr/bin/tini\", \"--\"]" in dockerfile
    assert "REMOTION_BROWSER_EXECUTABLE=/usr/bin/chromium" in dockerfile
    assert "PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1" in dockerfile
    assert "chmod -R a-w /app" in dockerfile
    assert "postgresql-client" in dockerfile
    assert "--browser-executable=$REMOTION_BROWSER_EXECUTABLE" in package["scripts"]["render"]
    assert "--browser-executable=$REMOTION_BROWSER_EXECUTABLE" in package["scripts"]["render:video"]


def test_upgrade_operations_share_immutable_release_evidence() -> None:
    services = _compose_config()["services"]
    capture = services["upgrade-capture"]
    verify = services["upgrade-verify"]
    assert capture["command"][-2:] == ["capture", "/release-evidence/pre-upgrade.json"]
    assert verify["command"][-4:] == [
        "verify",
        "/release-evidence/pre-upgrade.json",
        "--report",
        "/release-evidence/upgrade-verification.json",
    ]
    for service in (capture, verify):
        targets = {volume["target"] for volume in service["volumes"]}
        assert "/release-evidence" in targets


def test_legacy_migration_operations_mount_source_read_only_and_persist_reports() -> None:
    services = _compose_config()["services"]
    expected_mode = {
        "legacy-migration-dry-run": "--dry-run",
        "legacy-migration-import": None,
        "legacy-migration-shadow": "--shadow-only",
    }
    for name, mode in expected_mode.items():
        service = services[name]
        source = next(volume for volume in service["volumes"] if volume["target"] == "/migration-source")
        evidence = next(
            volume for volume in service["volumes"] if volume["target"] == "/release-evidence"
        )
        assert source["read_only"] is True
        assert evidence.get("read_only", False) is False
        assert service["command"][0:4] == [
            "python",
            "-m",
            "server.app.persistence.import_legacy",
            "/migration-source",
        ]
        if mode is None:
            assert "--dry-run" not in service["command"]
            assert "--shadow-only" not in service["command"]
        else:
            assert mode in service["command"]
        assert "--report" in service["command"]
