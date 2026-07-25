from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from server.app.core.config import Settings


PINNED_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


class RenderIsolationError(RuntimeError):
    pass


class RenderBusy(RenderIsolationError):
    pass


class RenderCanceled(RenderIsolationError):
    pass


class RenderTimedOut(RenderIsolationError):
    pass


@dataclass(frozen=True)
class RenderResult:
    output_path: Path
    duration_seconds: float
    probe: dict[str, Any]


CommandBuilder = Callable[[Path], Sequence[str]]
ProbeRunner = Callable[[Path], Mapping[str, Any]]


def validate_render_engine_digest(settings: Settings) -> None:
    if settings.deployment_mode != "distributed" or settings.dry_run:
        return
    if not PINNED_DIGEST.fullmatch(settings.render_engine_digest):
        raise RenderIsolationError(
            "distributed rendering requires CASE_VIDEO_RENDER_ENGINE_DIGEST=sha256:<64 hex>"
        )


class IsolatedRenderRunner:
    """Run one Remotion render in a unique, disposable project workspace.

    The engine is supplied by the immutable container image/read-only mount.
    Only the copied project is writable. A runner instance accepts one active
    job, and every exit path removes its scratch directory.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        command_builder: CommandBuilder | None = None,
        probe_runner: ProbeRunner | None = None,
    ) -> None:
        validate_render_engine_digest(settings)
        self.settings = settings
        self._uses_default_command = command_builder is None
        self.command_builder = command_builder or self._default_command
        self.probe_runner = probe_runner or self._ffprobe
        self._active = threading.Lock()
        self.settings.render_workspace_root.mkdir(parents=True, exist_ok=True)

    def run(
        self,
        job_id: str,
        project_root: Path,
        *,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> RenderResult:
        if not self._active.acquire(blocking=False):
            raise RenderBusy("this render runner already has an active job")
        scratch: Path | None = None
        started = time.monotonic()
        try:
            source = project_root.resolve()
            if not source.is_dir():
                raise RenderIsolationError(f"render project does not exist: {source}")
            symlinks = [path for path in source.rglob("*") if path.is_symlink()]
            if symlinks:
                raise RenderIsolationError("render projects may not contain symbolic links")

            safe_job_id = re.sub(r"[^A-Za-z0-9_.-]", "_", job_id)[:80] or "job"
            scratch = Path(
                tempfile.mkdtemp(
                    prefix=f"render-{safe_job_id}-",
                    dir=str(self.settings.render_workspace_root),
                )
            )
            isolated_project = scratch / "project"
            shutil.copytree(source, isolated_project, symlinks=False)
            log_path = scratch / "render.log"
            isolated_engine_root: Path | None = None
            if self._uses_default_command:
                isolated_engine_root = self._prepare_engine_workspace(scratch)
            command = [str(item) for item in self.command_builder(isolated_project)]
            if not command:
                raise RenderIsolationError("render command is empty")
            env = os.environ.copy()
            env["CASE_VIDEO_RENDER_ENGINE_DIGEST"] = self.settings.render_engine_digest
            env["CASE_VIDEO_RENDER_WORKSPACE"] = str(scratch)
            if isolated_engine_root is not None:
                env["CASE_VIDEO_ENGINE_ROOT"] = str(isolated_engine_root)
            with log_path.open("w", encoding="utf-8") as log:
                process = subprocess.Popen(
                    command,
                    cwd=str(self.settings.repo_root),
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                    text=True,
                )
                while process.poll() is None:
                    if cancel_requested is not None and cancel_requested():
                        self._terminate(process)
                        raise RenderCanceled(f"render canceled: {job_id}")
                    if time.monotonic() - started > self.settings.render_max_seconds:
                        self._terminate(process)
                        raise RenderTimedOut(f"render timed out after {self.settings.render_max_seconds}s")
                    time.sleep(0.2)
                if process.returncode != 0:
                    raise RenderIsolationError(f"render process failed with returncode {process.returncode}")

            isolated_output = isolated_project / "video" / "case_video.mp4"
            if not isolated_output.is_file() or isolated_output.stat().st_size <= 0:
                raise RenderIsolationError("render did not produce video/case_video.mp4")
            probe = dict(self.probe_runner(isolated_output))
            self._validate_probe(probe)
            destination = source / "video" / "case_video.mp4"
            destination.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                "wb",
                dir=str(destination.parent),
                prefix=".case_video-",
                suffix=".mp4",
                delete=False,
            ) as handle:
                with isolated_output.open("rb") as rendered:
                    shutil.copyfileobj(rendered, handle, length=1024 * 1024)
                handle.flush()
                os.fsync(handle.fileno())
                temporary = Path(handle.name)
            os.replace(temporary, destination)
            return RenderResult(
                output_path=destination,
                duration_seconds=time.monotonic() - started,
                probe=probe,
            )
        finally:
            if scratch is not None:
                shutil.rmtree(scratch, ignore_errors=True)
            self._active.release()

    def _default_command(self, project_root: Path) -> Sequence[str]:
        return (
            str(self.settings.repo_root / "scripts" / "case-video"),
            "render",
            str(project_root),
        )

    def _prepare_engine_workspace(self, scratch: Path) -> Path:
        """Materialize a job-local writable overlay from the immutable engine.

        Remotion's asset sync writes generated JSON and media below the engine
        tree. The canonical image layer must stay read-only, so the small
        application tree is copied for each render while the immutable npm
        dependency tree is linked read-only from the image.
        """

        source_remotion = self.settings.render_engine_root.resolve()
        source_engine = source_remotion.parent
        if not source_remotion.is_dir() or not (source_remotion / "package.json").is_file():
            raise RenderIsolationError(f"render engine is incomplete: {source_remotion}")
        if not (source_engine / "scripts" / "sync_assets.sh").is_file():
            raise RenderIsolationError(f"render engine scripts are incomplete: {source_engine}")

        destination_engine = scratch / "engine"

        def ignore(path: str, names: list[str]) -> set[str]:
            current = Path(path).resolve()
            ignored: set[str] = set()
            if current == source_remotion:
                ignored.update(
                    name
                    for name in ("node_modules", "public", "out", "dist", ".cache")
                    if name in names
                )
            if current == source_remotion / "src" / "data" and "generated" in names:
                ignored.add("generated")
            return ignored

        shutil.copytree(source_engine, destination_engine, symlinks=False, ignore=ignore)
        destination_remotion = destination_engine / "remotion"
        (destination_remotion / "public").mkdir(parents=True, exist_ok=True)
        (destination_remotion / "src" / "data" / "generated").mkdir(parents=True, exist_ok=True)

        source_modules = source_remotion / "node_modules"
        destination_modules = destination_remotion / "node_modules"
        if not source_modules.is_dir():
            raise RenderIsolationError(f"render engine dependencies are missing: {source_modules}")
        destination_modules.symlink_to(source_modules, target_is_directory=True)
        return destination_engine

    def _terminate(self, process: subprocess.Popen[str]) -> None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=self.settings.render_term_grace_seconds)
            return
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired as exc:
            raise RenderIsolationError("render process group did not terminate after SIGKILL") from exc

    @staticmethod
    def _ffprobe(path: Path) -> Mapping[str, Any]:
        completed = subprocess.run(
            (
                "ffprobe",
                "-v",
                "error",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(path),
            ),
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            raise RenderIsolationError(f"ffprobe failed: {completed.stderr.strip()[:500]}")
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise RenderIsolationError("ffprobe returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise RenderIsolationError("ffprobe result must be an object")
        return payload

    @staticmethod
    def _validate_probe(probe: Mapping[str, Any]) -> None:
        streams = probe.get("streams")
        if not isinstance(streams, list):
            raise RenderIsolationError("ffprobe result has no streams")
        video = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
        audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
        if not isinstance(video, Mapping) or not isinstance(audio, Mapping):
            raise RenderIsolationError("rendered video must contain both video and audio streams")
        if int(video.get("width", 0)) != 1920 or int(video.get("height", 0)) != 1080:
            raise RenderIsolationError("rendered video must be 1920x1080")
        rate = str(video.get("avg_frame_rate") or video.get("r_frame_rate") or "0/1")
        try:
            numerator, denominator = rate.split("/", 1)
            fps = float(numerator) / float(denominator)
        except (ValueError, ZeroDivisionError) as exc:
            raise RenderIsolationError("rendered video has an invalid frame rate") from exc
        if abs(fps - 30.0) > 0.01:
            raise RenderIsolationError("rendered video must be 30fps")
