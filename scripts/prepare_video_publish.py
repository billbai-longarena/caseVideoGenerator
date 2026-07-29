#!/usr/bin/env python3
"""Prepare upload-ready case videos in a centralized, Git-ignored directory."""

from __future__ import annotations

import argparse
import csv
import fnmatch
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PUBLISH_ROOT = REPO_ROOT / "publish"
MASTER_NAME = "case_video.mp4"
COMPRESSED_NAME = "case_video_compressed_50m.mp4"
MANIFEST_VERSION = 1
RESERVED_TOPIC_FOLDERS = {"_masters"}

SERIES_LABELS = {
    "baijiu": "杯中故事",
    "buxa": "BUXA",
    "fde": "FDE不复杂",
    "montessori": "蒙淇星",
    "sales": "销售不复杂",
    "sales-management": "销售管理",
}


class PublishError(RuntimeError):
    pass


@dataclass(frozen=True)
class MediaInfo:
    duration: float
    size_bytes: int
    width: int
    height: int
    fps: float
    video_codec: str
    audio_codec: str


@dataclass(frozen=True)
class Publication:
    project: Path
    project_key: str
    series: str
    series_label: str
    output_folder: str
    sequence: int
    sequence_width: int
    filename_prefix: str
    title: str
    filename: str


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PublishError(f"cannot read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise PublishError(f"{path} must contain a JSON object")
    return data


def _relative_to_repo(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def read_title(project: Path) -> str:
    path = project / "title.txt"
    if not path.is_file():
        raise PublishError(f"missing title.txt: {project}")
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(lines) != 1:
        raise PublishError(f"title.txt must contain exactly one non-empty line: {path}")
    return lines[0]


def sanitize_component(value: str, *, max_bytes: int = 180) -> str:
    # Keep reader-facing Chinese punctuation intact; only remove characters that
    # are unsafe in common desktop filesystems and upload clients.
    normalized = unicodedata.normalize("NFC", value)
    normalized = "".join(" " if ord(char) < 32 else char for char in normalized)
    replacements = {
        "\\": "／",
        "/": "／",
        ":": "：",
        "*": "＊",
        "?": "？",
        "<": "＜",
        ">": "＞",
        "|": "｜",
    }
    normalized = "".join(replacements.get(char, char) for char in normalized)
    quoted: list[str] = []
    opening_quote = True
    for char in normalized:
        if char == '"':
            quoted.append("“" if opening_quote else "”")
            opening_quote = not opening_quote
        else:
            quoted.append(char)
    normalized = "".join(quoted)
    normalized = re.sub(r"\s+", " ", normalized).strip(" ._-")
    if not normalized:
        raise PublishError("filename component is empty after sanitization")

    while len(normalized.encode("utf-8")) > max_bytes:
        normalized = normalized[:-1].rstrip(" ._-")
    if not normalized:
        raise PublishError("filename component is too long to sanitize safely")
    return normalized


def sanitize_series(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().lower()
    normalized = re.sub(r"[^a-z0-9._-]+", "-", normalized)
    normalized = re.sub(r"[-_.]{2,}", "-", normalized).strip("-._")
    if not normalized:
        raise PublishError("series must contain an ASCII letter or digit")
    return normalized


def infer_series_and_sequence(project_name: str) -> tuple[str | None, int | None]:
    rules = (
        (r"^sales_management_case(\d+)", "sales-management"),
        (r"^sales_case(\d+)", "sales"),
        (r"^fde_ep(\d+)", "fde"),
        (r"^baijiu_ep(\d+)", "baijiu"),
        (r"^montessori_ep(\d+)", "montessori"),
        (r"^case(\d+)", "sales"),
        (r"^buxa_(\d+)", "buxa"),
    )
    lowered = project_name.lower()
    for pattern, series in rules:
        match = re.match(pattern, lowered)
        if match:
            return series, int(match.group(1))

    generic = re.match(r"^([a-z0-9][a-z0-9_-]*?)_ep(\d+)(?:_|$)", lowered)
    if generic:
        return sanitize_series(generic.group(1)), int(generic.group(2))

    fallback = re.search(r"(?:^|[_-])(?:ep|case)[_-]?(\d+)(?:[_-]|$)", lowered)
    if fallback:
        prefix = lowered[: fallback.start()].strip("-_") or "misc"
        return sanitize_series(prefix), int(fallback.group(1))
    return None, None


def resolve_publication(
    project: Path,
    *,
    series_override: str | None = None,
    series_label_override: str | None = None,
    sequence_override: int | None = None,
) -> Publication | None:
    project = project.resolve()
    config_path = project / "publication.json"
    config = _read_json(config_path) if config_path.is_file() else {}
    if config.get("enabled", True) is False:
        return None

    inferred_series, inferred_sequence = infer_series_and_sequence(project.name)
    raw_series = series_override or config.get("series") or inferred_series
    raw_sequence = sequence_override if sequence_override is not None else config.get("sequence", inferred_sequence)
    if not raw_series:
        raise PublishError(
            f"cannot infer series for {project.name}; add publication.json or pass --series"
        )
    try:
        sequence = int(raw_sequence)
    except (TypeError, ValueError) as exc:
        raise PublishError(
            f"cannot infer sequence for {project.name}; add publication.json or pass --sequence"
        ) from exc
    if sequence < 1:
        raise PublishError(f"sequence must be at least 1 for {project.name}")

    try:
        sequence_width = int(config.get("sequenceWidth", 3))
    except (TypeError, ValueError) as exc:
        raise PublishError(f"sequenceWidth must be an integer in {config_path}") from exc
    if sequence_width < 1 or sequence_width > 6:
        raise PublishError(f"sequenceWidth must be between 1 and 6 in {config_path}")

    prefix = str(config.get("filenamePrefix", "S")).strip()
    prefix = re.sub(r"[^A-Za-z0-9_-]+", "", prefix).upper()
    if not prefix:
        raise PublishError(f"filenamePrefix is empty or invalid in {config_path}")

    series = sanitize_series(str(raw_series))
    series_label = str(
        series_label_override or config.get("seriesLabel") or SERIES_LABELS.get(series, series)
    ).strip()
    if not series_label:
        raise PublishError(f"seriesLabel is empty in {config_path}")
    raw_output_folder = str(config.get("outputFolder") or series_label)
    if unicodedata.normalize("NFC", raw_output_folder).strip().casefold() in RESERVED_TOPIC_FOLDERS:
        raise PublishError(f"outputFolder is reserved in {config_path}: {raw_output_folder}")
    output_folder = sanitize_component(raw_output_folder, max_bytes=100)
    if output_folder.casefold() in RESERVED_TOPIC_FOLDERS:
        raise PublishError(f"outputFolder is reserved in {config_path}: {output_folder}")
    title = read_title(project)
    safe_title = sanitize_component(title)
    number = str(sequence).zfill(sequence_width)
    filename = f"{prefix}{number}_{safe_title}.mp4"
    return Publication(
        project=project,
        project_key=_relative_to_repo(project),
        series=series,
        series_label=series_label,
        output_folder=output_folder,
        sequence=sequence,
        sequence_width=sequence_width,
        filename_prefix=prefix,
        title=title,
        filename=filename,
    )


def _parse_fps(value: str | None) -> float:
    if not value or value == "0/0":
        return 0.0
    try:
        return float(Fraction(value))
    except (ValueError, ZeroDivisionError):
        return 0.0


def probe_media(path: Path) -> MediaInfo:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration,size:stream=codec_type,codec_name,width,height,avg_frame_rate",
        "-of",
        "json",
        str(path),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise PublishError(f"cannot run ffprobe for {path}: {exc}") from exc
    if result.returncode != 0:
        raise PublishError(f"ffprobe failed for {path}: {result.stderr.strip()}")
    try:
        payload = json.loads(result.stdout)
        streams = payload.get("streams", [])
        video = next(stream for stream in streams if stream.get("codec_type") == "video")
        audio = next(stream for stream in streams if stream.get("codec_type") == "audio")
        duration = float(payload["format"]["duration"])
        size_bytes = int(payload["format"].get("size") or path.stat().st_size)
    except (KeyError, StopIteration, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise PublishError(f"{path} must contain readable video and audio streams") from exc
    if not math.isfinite(duration) or duration <= 0:
        raise PublishError(f"invalid media duration for {path}: {duration}")
    return MediaInfo(
        duration=duration,
        size_bytes=size_bytes,
        width=int(video.get("width") or 0),
        height=int(video.get("height") or 0),
        fps=_parse_fps(video.get("avg_frame_rate")),
        video_codec=str(video.get("codec_name") or ""),
        audio_codec=str(audio.get("codec_name") or ""),
    )


def validate_delivery_pair(master: MediaInfo, compressed: MediaInfo, *, target_bytes: int) -> None:
    if compressed.video_codec != "h264" or compressed.audio_codec != "aac":
        raise PublishError(
            "compressed copy must use H.264 video and AAC audio, got "
            f"{compressed.video_codec or 'unknown'}/{compressed.audio_codec or 'unknown'}"
        )
    if (compressed.width, compressed.height) != (master.width, master.height):
        raise PublishError(
            "compressed copy changed resolution: "
            f"{master.width}x{master.height} -> {compressed.width}x{compressed.height}"
        )
    if master.fps and compressed.fps and abs(compressed.fps - master.fps) > 0.02:
        raise PublishError(f"compressed copy changed frame rate: {master.fps:.3f} -> {compressed.fps:.3f}")
    if abs(compressed.duration - master.duration) > max(0.5, master.duration * 0.002):
        raise PublishError(
            f"compressed duration differs from master by {abs(compressed.duration - master.duration):.3f}s"
        )
    if compressed.size_bytes > int(target_bytes * 1.03):
        raise PublishError(
            f"compressed copy is {compressed.size_bytes / 1_000_000:.2f} MB, "
            f"above the {target_bytes / 1_000_000:.2f} MB target"
        )
    if master.size_bytes > int(target_bytes * 0.98) and compressed.size_bytes < int(target_bytes * 0.80):
        raise PublishError(
            f"compressed copy is only {compressed.size_bytes / 1_000_000:.2f} MB, "
            f"well below the {target_bytes / 1_000_000:.2f} MB target"
        )


def _copy_file(source: Path, destination: Path) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp-{os.getpid()}")
    temporary.unlink(missing_ok=True)
    shutil.copy2(source, temporary)
    os.replace(temporary, destination)
    return "copy"


def link_or_copy(source: Path, destination: Path, *, temp_dir: Path | None = None) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    for stale in destination.parent.glob(f".{destination.name}.tmp-*"):
        stale.unlink(missing_ok=True)
    if destination.exists():
        try:
            if os.path.samefile(source, destination):
                return "hardlink"
        except OSError:
            pass
    temporary_dir = temp_dir or destination.parent
    temporary_dir.mkdir(parents=True, exist_ok=True)
    temporary = temporary_dir / f"publish-{os.getpid()}-{uuid.uuid4().hex}.tmp"
    try:
        try:
            os.link(source, temporary)
            mode = "hardlink"
        except OSError:
            shutil.copy2(source, temporary)
            mode = "copy"
        os.replace(temporary, destination)
        return mode
    finally:
        temporary.unlink(missing_ok=True)


def _encode_two_pass(master: Path, destination: Path, *, video_kbps: int) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.stem}.encoding-{os.getpid()}.mp4")
    temporary.unlink(missing_ok=True)
    temp_root = destination.parents[1] / "tmp" / "publish"
    temp_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ffmpeg-pass-", dir=temp_root) as temp_dir:
        passlog = Path(temp_dir) / "pass"
        first = [
            "ffmpeg",
            "-nostdin",
            "-y",
            "-i",
            str(master),
            "-map",
            "0:v:0",
            "-c:v",
            "libx264",
            "-b:v",
            f"{video_kbps}k",
            "-pass",
            "1",
            "-passlogfile",
            str(passlog),
            "-an",
            "-f",
            "mp4",
            os.devnull,
        ]
        second = [
            "ffmpeg",
            "-nostdin",
            "-y",
            "-i",
            str(master),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0",
            "-c:v",
            "libx264",
            "-b:v",
            f"{video_kbps}k",
            "-pass",
            "2",
            "-passlogfile",
            str(passlog),
            "-c:a",
            "aac",
            "-b:a",
            "96k",
            "-movflags",
            "+faststart",
            str(temporary),
        ]
        for command in (first, second):
            try:
                result = subprocess.run(command, check=False)
            except OSError as exc:
                temporary.unlink(missing_ok=True)
                raise PublishError(f"cannot run ffmpeg for {master}: {exc}") from exc
            if result.returncode != 0:
                temporary.unlink(missing_ok=True)
                raise PublishError(f"ffmpeg two-pass compression failed for {master}")
    os.replace(temporary, destination)


def ensure_compressed(project: Path, *, target_mb: float, force: bool = False) -> tuple[Path, MediaInfo, MediaInfo]:
    master = project / "video" / MASTER_NAME
    compressed = project / "video" / COMPRESSED_NAME
    if not master.is_file():
        raise PublishError(f"master video not found: {master}")
    target_bytes = int(target_mb * 1_000_000)
    master_info = probe_media(master)

    if compressed.is_file() and not force and compressed.stat().st_mtime_ns >= master.stat().st_mtime_ns:
        try:
            compressed_info = probe_media(compressed)
            validate_delivery_pair(master_info, compressed_info, target_bytes=target_bytes)
            return compressed, master_info, compressed_info
        except PublishError as exc:
            print(f"rebuilding stale/invalid compressed copy: {exc}", file=sys.stderr)

    if master_info.size_bytes <= int(target_bytes * 0.98):
        _copy_file(master, compressed)
    else:
        total_kbps = target_bytes * 8 / master_info.duration / 1000
        video_kbps = max(200, int((total_kbps - 96) * 0.975))
        _encode_two_pass(master, compressed, video_kbps=video_kbps)
        compressed_info = probe_media(compressed)
        if compressed_info.size_bytes > int(target_bytes * 1.03):
            corrected_kbps = max(200, int(video_kbps * target_bytes / compressed_info.size_bytes * 0.97))
            _encode_two_pass(master, compressed, video_kbps=corrected_kbps)

    compressed_info = probe_media(compressed)
    validate_delivery_pair(master_info, compressed_info, target_bytes=target_bytes)
    return compressed, master_info, compressed_info


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def discover_projects(root: Path, patterns: Iterable[str]) -> list[Path]:
    if not root.is_dir():
        raise PublishError(f"batch root is not a directory: {root}")
    selected: list[Path] = []
    patterns = tuple(patterns) or ("*",)
    for child in sorted(root.iterdir(), key=lambda item: item.name):
        if not child.is_dir() or not any(fnmatch.fnmatch(child.name, pattern) for pattern in patterns):
            continue
        if (child / "video" / MASTER_NAME).is_file():
            selected.append(child)
    return selected


def _load_manifest(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    data = _read_json(path)
    if data.get("version") != MANIFEST_VERSION or not isinstance(data.get("items"), list):
        raise PublishError(f"unsupported publish manifest: {path}")
    return [item for item in data["items"] if isinstance(item, dict)]


def _safe_published_path(publish_root: Path, relative: str | None) -> Path | None:
    if not relative:
        return None
    candidate = (publish_root / relative).resolve()
    try:
        candidate.relative_to(publish_root.resolve())
    except ValueError as exc:
        raise PublishError(f"manifest path escapes publish root: {relative}") from exc
    return candidate


def _prune_empty_parents(path: Path, *, stop: Path) -> None:
    stop = stop.resolve()
    current = path.resolve()
    while current != stop:
        try:
            current.relative_to(stop)
        except ValueError:
            return
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent


def _atomic_write_text(path: Path, value: str, *, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(value, encoding=encoding)
    os.replace(temporary, path)


def write_manifests(publish_root: Path, items: list[dict[str, Any]]) -> None:
    items = sorted(
        items,
        key=lambda item: (item["series_folder"], int(item["sequence"]), item["title"]),
    )
    payload = {
        "version": MANIFEST_VERSION,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "count": len(items),
        "items": items,
    }
    _atomic_write_text(
        publish_root / "manifest.json",
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
    )

    csv_path = publish_root / "manifest.csv"
    csv_temp = csv_path.with_name(f".{csv_path.name}.tmp-{os.getpid()}")
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "series",
        "series_label",
        "series_folder",
        "sequence",
        "title",
        "filename",
        "project",
        "upload_path",
        "master_path",
        "duration_seconds",
        "size_bytes",
        "width",
        "height",
        "fps",
        "sha256",
    ]
    with csv_temp.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for item in items:
            writer.writerow({field: item.get(field, "") for field in fields})
    os.replace(csv_temp, csv_path)

    upload_list = "".join(f"{item['upload_path']}\n" for item in items)
    _atomic_write_text(publish_root / "upload-list.txt", upload_list)


def _entry_for(
    publication: Publication,
    *,
    publish_root: Path,
    upload_path: Path,
    master_path: Path | None,
    media: MediaInfo,
    link_mode: str,
    sha256: str,
) -> dict[str, Any]:
    relative_upload = upload_path.relative_to(publish_root).as_posix()
    relative_master = master_path.relative_to(publish_root).as_posix() if master_path else ""
    return {
        "series": publication.series,
        "series_label": publication.series_label,
        "series_folder": publication.output_folder,
        "sequence": publication.sequence,
        "title": publication.title,
        "filename": publication.filename,
        "project": publication.project_key,
        "upload_path": relative_upload,
        "master_path": relative_master,
        "source_master": _relative_to_repo(publication.project / "video" / MASTER_NAME),
        "source_compressed": _relative_to_repo(publication.project / "video" / COMPRESSED_NAME),
        "duration_seconds": round(media.duration, 3),
        "size_bytes": media.size_bytes,
        "width": media.width,
        "height": media.height,
        "fps": round(media.fps, 3),
        "video_codec": media.video_codec,
        "audio_codec": media.audio_codec,
        "sha256": sha256,
        "link_mode": link_mode,
        "published_at": datetime.now(timezone.utc).isoformat(),
    }


def stage_publications(
    publications: list[Publication],
    *,
    publish_root: Path,
    target_mb: float,
    include_master: bool,
    force: bool,
    dry_run: bool,
) -> list[dict[str, Any]]:
    publish_root = publish_root.resolve()
    destinations: dict[str, str] = {}
    episode_numbers: dict[tuple[str, int], str] = {}
    for publication in publications:
        relative = (Path(publication.output_folder) / publication.filename).as_posix()
        if relative in destinations:
            raise PublishError(
                f"publish filename collision: {relative} from {destinations[relative]} and {publication.project_key}; "
                "add or adjust publication.json"
            )
        destinations[relative] = publication.project_key
        episode_key = (publication.output_folder, publication.sequence)
        if episode_key in episode_numbers:
            raise PublishError(
                f"duplicate episode {publication.filename_prefix}{publication.sequence:0{publication.sequence_width}d} "
                f"in topic folder {publication.output_folder}: {episode_numbers[episode_key]} and "
                f"{publication.project_key}; disable the superseded project in publication.json or assign a new sequence"
            )
        episode_numbers[episode_key] = publication.project_key

    manifest_path = publish_root / "manifest.json"
    existing = _load_manifest(manifest_path)
    old_by_project = {str(item.get("project")): item for item in existing}
    retained = [item for item in existing if str(item.get("project")) not in {p.project_key for p in publications}]
    selected_episode_keys = {
        (publication.output_folder, publication.sequence) for publication in publications
    }
    for item in retained:
        try:
            retained_folder = str(
                item.get("series_folder") or item.get("series_label") or item["series"]
            )
            retained_key = (retained_folder, int(item["sequence"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise PublishError(f"invalid episode metadata in {manifest_path}: {item}") from exc
        if retained_key in selected_episode_keys:
            raise PublishError(
                f"episode {retained_key[1]} in topic folder {retained_key[0]} is already published by "
                f"{item.get('project')}; disable or replace that project before publishing another version"
            )
    entries: list[dict[str, Any]] = []
    publish_temp_root = publish_root / ".tmp"

    for publication in publications:
        upload_path = publish_root / publication.output_folder / publication.filename
        master_publish_path = (
            publish_root
            / "_masters"
            / publication.output_folder
            / publication.filename.replace(".mp4", "_master.mp4")
            if include_master
            else None
        )
        print(f"{publication.project_key} -> {upload_path.relative_to(publish_root)}")
        if dry_run:
            continue

        compressed, _, compressed_info = ensure_compressed(
            publication.project, target_mb=target_mb, force=force
        )

        for item in retained:
            if item.get("upload_path") == upload_path.relative_to(publish_root).as_posix():
                raise PublishError(
                    f"publish destination already belongs to {item.get('project')}: "
                    f"{upload_path.relative_to(publish_root)}"
                )

        old = old_by_project.get(publication.project_key)
        old_paths = [] if not old else [old.get("upload_path"), old.get("master_path")]
        link_mode = link_or_copy(compressed, upload_path, temp_dir=publish_temp_root)
        if master_publish_path:
            link_or_copy(
                publication.project / "video" / MASTER_NAME,
                master_publish_path,
                temp_dir=publish_temp_root,
            )

        for old_relative in old_paths:
            old_path = _safe_published_path(publish_root, old_relative)
            if old_path and old_path not in {upload_path, master_publish_path}:
                old_path.unlink(missing_ok=True)
                _prune_empty_parents(old_path.parent, stop=publish_root)

        entries.append(
            _entry_for(
                publication,
                publish_root=publish_root,
                upload_path=upload_path,
                master_path=master_publish_path,
                media=compressed_info,
                link_mode=link_mode,
                sha256=sha256_file(upload_path),
            )
        )

    if not dry_run:
        write_manifests(publish_root, retained + entries)
        if publish_temp_root.exists():
            publish_temp_root.rmdir()
    return entries


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Create upload-ready S001_标题.mp4 files under publish/<主题>/ "
            "and maintain JSON/CSV/path manifests."
        )
    )
    parser.add_argument("projects", nargs="*", type=Path, help="Project directories to publish")
    parser.add_argument("--discover", type=Path, help="Discover rendered projects one level below this root")
    parser.add_argument("--pattern", action="append", default=[], help="fnmatch pattern for --discover")
    parser.add_argument("--publish-root", type=Path, default=DEFAULT_PUBLISH_ROOT)
    parser.add_argument("--series", help="Override the series slug (single project only)")
    parser.add_argument("--series-label", help="Override the human-readable series label")
    parser.add_argument("--sequence", type=int, help="Override the S-number (single project only)")
    parser.add_argument("--target-mb", type=float, default=50.0, help="Upload-copy target in decimal MB")
    parser.add_argument("--include-master", action="store_true", help="Also stage the master under publish/_masters")
    parser.add_argument("--force", action="store_true", help="Rebuild the compressed copy even when current")
    parser.add_argument("--dry-run", action="store_true", help="Print planned destinations without writing")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not math.isfinite(args.target_mb) or args.target_mb <= 1:
        raise PublishError("--target-mb must be greater than 1")
    if args.discover and args.projects:
        raise PublishError("use explicit project paths or --discover, not both")
    if not args.discover and not args.projects:
        raise PublishError("provide at least one project or use --discover")

    projects = (
        discover_projects(args.discover.resolve(), args.pattern)
        if args.discover
        else [project.resolve() for project in args.projects]
    )
    if not projects:
        raise PublishError("no rendered projects matched the selection")
    if len(projects) != 1 and (args.series or args.series_label or args.sequence is not None):
        raise PublishError("--series, --series-label and --sequence only apply to one project")

    publications: list[Publication] = []
    skipped: list[str] = []
    for project in projects:
        try:
            publication = resolve_publication(
                project,
                series_override=args.series,
                series_label_override=args.series_label,
                sequence_override=args.sequence,
            )
            if publication is not None:
                publications.append(publication)
        except PublishError as exc:
            if args.discover:
                skipped.append(f"{project.name}: {exc}")
            else:
                raise
    if skipped:
        print("Skipped rendered projects without publish metadata:", file=sys.stderr)
        for message in skipped:
            print(f"  - {message}", file=sys.stderr)
    if not publications:
        raise PublishError("no publishable projects remained after metadata checks")
    publications.sort(key=lambda item: (item.output_folder, item.sequence, item.title))

    entries = stage_publications(
        publications,
        publish_root=args.publish_root,
        target_mb=args.target_mb,
        include_master=args.include_master,
        force=args.force,
        dry_run=args.dry_run,
    )
    if args.dry_run:
        print(f"dry run: {len(publications)} video(s) planned")
    else:
        print(f"published {len(entries)} video(s) below {args.publish_root.resolve()}")
        print(f"manifests: {args.publish_root.resolve() / 'manifest.csv'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PublishError as exc:
        print(f"publish error: {exc}", file=sys.stderr)
        raise SystemExit(2)
