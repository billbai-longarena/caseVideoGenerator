from __future__ import annotations

import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest

from server.app.core.config import load_settings
from server.app.services.render_runner import (
    IsolatedRenderRunner,
    RenderIsolationError,
    RenderTimedOut,
)


VALID_PROBE = {
    "streams": [
        {"codec_type": "video", "width": 1920, "height": 1080, "avg_frame_rate": "30/1"},
        {"codec_type": "audio"},
    ]
}


def settings(tmp_path: Path, **updates):
    values = {
        "deployment_mode": "distributed",
        "dry_run": False,
        "render_workspace_root": tmp_path / "scratch",
        "render_engine_digest": "sha256:" + "a" * 64,
        "render_max_seconds": 10,
        "render_term_grace_seconds": 1,
        **updates,
    }
    return replace(load_settings(), **values)


def make_project(root: Path, marker: str) -> Path:
    project = root / marker
    project.mkdir(parents=True)
    (project / "marker.txt").write_text(marker, encoding="utf-8")
    return project


def render_command(project: Path) -> tuple[str, ...]:
    script = (
        "from pathlib import Path; "
        "p=Path(r'" + str(project) + "'); "
        "(p/'video').mkdir(parents=True, exist_ok=True); "
        "(p/'video'/'case_video.mp4').write_bytes((p/'marker.txt').read_bytes())"
    )
    return (sys.executable, "-c", script)


def test_three_parallel_jobs_use_separate_scratch_and_do_not_cross_contaminate(tmp_path: Path) -> None:
    configured = settings(tmp_path)
    projects = [make_project(tmp_path / "projects", f"job-{index}") for index in range(3)]

    def run(project: Path) -> bytes:
        runner = IsolatedRenderRunner(
            configured,
            command_builder=render_command,
            probe_runner=lambda _: VALID_PROBE,
        )
        return runner.run(project.name, project).output_path.read_bytes()

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(run, projects))

    assert results == [b"job-0", b"job-1", b"job-2"]
    assert list(configured.render_workspace_root.iterdir()) == []


def test_timeout_terminates_process_group_and_cleans_scratch(tmp_path: Path) -> None:
    configured = settings(tmp_path, render_max_seconds=1)
    project = make_project(tmp_path / "projects", "timeout")
    pid_path = tmp_path / "render.pid"

    def command(_: Path) -> tuple[str, ...]:
        script = (
            "import os,time; from pathlib import Path; "
            f"Path(r'{pid_path}').write_text(str(os.getpid())); time.sleep(30)"
        )
        return (sys.executable, "-c", script)

    runner = IsolatedRenderRunner(configured, command_builder=command, probe_runner=lambda _: VALID_PROBE)
    with pytest.raises(RenderTimedOut):
        runner.run("timeout", project)

    pid = int(pid_path.read_text(encoding="utf-8"))
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        pytest.fail("timed-out render process is still alive")
    assert list(configured.render_workspace_root.iterdir()) == []


def test_distributed_render_rejects_unpinned_engine_digest(tmp_path: Path) -> None:
    configured = settings(tmp_path, render_engine_digest="sha256:development-only-unpinned")
    with pytest.raises(RenderIsolationError, match="requires CASE_VIDEO_RENDER_ENGINE_DIGEST"):
        IsolatedRenderRunner(configured)


def test_default_render_materializes_job_local_engine_without_copying_runtime_assets(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    remotion = repo / "engine" / "remotion"
    (repo / "engine" / "scripts").mkdir(parents=True)
    (repo / "engine" / "scripts" / "sync_assets.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (remotion / "src" / "data" / "generated").mkdir(parents=True)
    (remotion / "src" / "data" / "generated" / "old.json").write_text("{}", encoding="utf-8")
    (remotion / "public" / "images").mkdir(parents=True)
    (remotion / "public" / "images" / "old.png").write_bytes(b"old")
    (remotion / "node_modules" / "pkg").mkdir(parents=True)
    (remotion / "node_modules" / "pkg" / "index.js").write_text("module.exports={}", encoding="utf-8")
    (remotion / "package.json").write_text("{}", encoding="utf-8")
    (remotion / "src" / "index.ts").write_text("export {};", encoding="utf-8")

    configured = settings(
        tmp_path,
        repo_root=repo,
        render_engine_root=remotion,
    )
    runner = IsolatedRenderRunner(configured, probe_runner=lambda _: VALID_PROBE)
    scratch = tmp_path / "engine-scratch"
    scratch.mkdir()
    isolated_engine = runner._prepare_engine_workspace(scratch)

    isolated_remotion = isolated_engine / "remotion"
    assert (isolated_remotion / "src" / "index.ts").is_file()
    assert not (isolated_remotion / "src" / "data" / "generated" / "old.json").exists()
    assert not (isolated_remotion / "public" / "images" / "old.png").exists()
    assert (isolated_remotion / "node_modules").is_symlink()
    assert (isolated_remotion / "node_modules").resolve() == (remotion / "node_modules").resolve()
    assert (remotion / "public" / "images" / "old.png").read_bytes() == b"old"
