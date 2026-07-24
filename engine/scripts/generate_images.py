#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
from collections import deque
import concurrent.futures
from datetime import timezone
import email.utils
import http.client
from io import BytesIO
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image, UnidentifiedImageError


ENGINE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ENGINE_ROOT.parent
DEPLOYMENT = "gpt-image-2"
API_VERSION = "2025-04-01-preview"
DEFAULT_REQUESTS_PER_MINUTE = 12
REQUEST_WINDOW_SECONDS = 60.0
IMAGE_OUTPUT_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
FORBIDDEN_GENERATED_IMAGE_DIR_PARTS = {
    "qa",
    "video",
    "contact-sheet",
    "contact-sheets",
    "contact_sheet",
    "contact_sheets",
}
FORBIDDEN_GENERATED_IMAGE_NAME_MARKERS = (
    "contact-sheet",
    "contact_sheet",
    "overview",
    "thumbnail",
)

STYLE_PREFIX = (
    "Bright editorial watercolor and gouache illustration, cinematic 16:9 composition, "
    "dominant vivid azure blue and bright cadmium yellow palette, high value contrast, "
    "deep cobalt blue shadows against luminous yellow highlights, crisp dark-light separation, "
    "airy white negative space, "
    "broad translucent washes, clean flat shapes, light dry-brush edges, modern business magazine style, "
    "foreground subject relatively clear and readable, everything beyond the foreground is impressionist and semi-abstract, "
    "background city and sky rendered as loose color fields and soft silhouettes, minimal details, simplified silhouettes, "
    "abstracted architecture, optimistic sunlit atmosphere, "
    "not heavy oil painting, not photorealistic, no dense rendering, no logos, no brand marks, "
    "no readable text, no watermark, no detailed faces, no detailed windows, no hard architectural linework in the background."
)

DEFAULT_PROMPTS = [
    ("bg_01_ipo_pause", "A confident business executive silhouette on a phone call near a Hong Kong financial district skyline, low-angle heroic framing, abstract IPO roadshow tension, blue suit shapes and yellow sunlight washes."),
    ("bg_02_airport_roadshow", "A simplified airport lounge with business travelers and rolling suitcases, bright blue glass walls, yellow sunset flooding the floor."),
    ("bg_03_boardroom_pause", "A boardroom table with loose paper shapes and abstract charts, executives as soft silhouettes, yellow lamp glow against blue night windows."),
    ("bg_04_beer_industry", "A warm brewery interior with copper tanks suggested by broad strokes, blue shadows and bright yellow highlights, simple beer glasses without labels."),
    ("bg_05_old_industry", "An old neighborhood bar and brewery street corner, simplified architecture, yellow awnings and blue evening air, calm traditional industry mood."),
    ("bg_06_global_slowdown", "A world map suggested by broad blue brush shapes behind muted market bars, yellow and blue abstract trend lines, mature market slowdown mood."),
    ("bg_07_mature_markets", "Quiet European and Japanese city bar silhouettes blended into one impressionist scene, cool blue storefronts and yellow window lights."),
    ("bg_08_asia_city", "A vibrant Asian city evening with restaurants, scooters, young professionals, yellow lantern light and electric blue reflections."),
    ("bg_09_consumption_upgrade", "Premium casual dining tables and raised glasses without logos, simplified people, vivid blue shadows and bright yellow highlights."),
    ("bg_10_growth_engine", "An abstract Asian city map glowing like a growth engine, blue rivers of light and yellow urban nodes, energetic but low detail."),
    ("bg_11_local_market", "A local open-air market beside a small brewery, yellow umbrellas, blue shaded stalls, community business atmosphere."),
    ("bg_12_multi_brand", "Abstract shelves and product shapes without labels, bright yellow blocks and blue negative space, many-market portfolio feeling."),
    ("bg_13_local_operations", "Local managers and workers as soft figures near brewery tanks and neighborhood streets, yellow sunlight and blue shadows."),
    ("bg_14_capital_pressure", "A large balance scale suggested by loose brush strokes, one side debt papers, the other side a glowing blue-yellow Asia map."),
    ("bg_15_debt_wall", "A wall of abstract debt ledgers and acquisition folders, deep blue background with bright yellow pressure highlights, no readable text."),
    ("bg_16_hongkong_listing", "Hong Kong harbor and exchange-like tower shapes in impressionist light, vivid blue water and bright yellow skyline glow."),
    ("bg_17_investor_questions", "Investor meeting silhouettes with floating question-mark-like abstract shapes, blue conference room and yellow spotlight."),
    ("bg_18_valuation_doubt", "A simplified valuation chart projected on a wall, blue grid shapes and yellow warning glow, no readable numbers or text."),
    ("bg_19_global_roadshow", "A montage of Shanghai, Singapore, London, New York and Chicago as abstract skyline strips, blue and yellow travel motion."),
    ("bg_20_plan_stopped", "A dramatic pause moment at a conference table, empty chair, papers, blue night and bright yellow desk light."),
    ("bg_21_three_paths", "Three illuminated corridors in a modern office, left yellow, center blue, right white-yellow, strategic choice mood."),
    ("bg_22_dividend_asset", "Abstract financial crossroads with dividend coins and asset blocks as simple shapes, bright blue floor and yellow light."),
    ("bg_23_future_pricing", "A global company silhouette facing a bright blue-yellow horizon, abstract city and brewery shapes merging."),
    ("bg_24_closing_future", "A final optimistic impressionist skyline with blue morning sky and bright yellow sun, simple path forward, business future mood."),
]


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def azure_resource_root(endpoint: str) -> str:
    parsed = urllib.parse.urlparse(endpoint)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("AZURE_OPENAI_ENDPOINT is not a valid URL")
    return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))


class RequestRateLimiter:
    def __init__(self, max_requests: int, window_seconds: float = REQUEST_WINDOW_SECONDS) -> None:
        self.max_requests = max(1, max_requests)
        self.window_seconds = window_seconds
        self._timestamps: deque[float] = deque()
        self._lock = threading.Lock()

    def wait_for_slot(self) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                self._drop_expired(now)
                if len(self._timestamps) < self.max_requests:
                    self._timestamps.append(now)
                    return
                wait_seconds = self._seconds_until_next_slot(now)
            print(
                f"rate limit wait {wait_seconds:.1f}s "
                f"limit={self.max_requests}/min",
                flush=True,
            )
            time.sleep(max(0.1, wait_seconds))

    def seconds_until_next_slot(self) -> float:
        with self._lock:
            now = time.monotonic()
            self._drop_expired(now)
            if len(self._timestamps) < self.max_requests:
                return 0.0
            return self._seconds_until_next_slot(now)

    def _drop_expired(self, now: float) -> None:
        while self._timestamps and now - self._timestamps[0] >= self.window_seconds:
            self._timestamps.popleft()

    def _seconds_until_next_slot(self, now: float) -> float:
        return max(0.1, self.window_seconds - (now - self._timestamps[0]) + 0.1)


def retry_after_seconds(error: urllib.error.HTTPError) -> float | None:
    value = error.headers.get("Retry-After")
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        retry_at = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=timezone.utc)
    return max(0.0, retry_at.timestamp() - time.time())


def retry_delay_seconds(
    *,
    attempt: int,
    error: Exception,
    rate_limiter: RequestRateLimiter,
) -> float:
    if isinstance(error, urllib.error.HTTPError) and error.code == 429:
        retry_after = retry_after_seconds(error)
        if retry_after is not None:
            return retry_after + 1.0
        return max(rate_limiter.seconds_until_next_slot(), REQUEST_WINDOW_SECONDS)
    return min(30.0, float(2 ** attempt))


def generate_image(
    prompt: str,
    *,
    rate_limiter: RequestRateLimiter,
    attempts: int = 8,
    size: str = "1536x864",
    quality: str = "low",
) -> bytes:
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
    api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    if not endpoint or not api_key:
        raise RuntimeError("AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY are required")

    root = azure_resource_root(endpoint)
    url = (
        f"{root}/openai/deployments/{DEPLOYMENT}/images/generations"
        f"?api-version={API_VERSION}"
    )
    payload = {
        "prompt": prompt,
        "n": 1,
        "size": size,
        "quality": quality,
        "output_format": "png",
    }
    body = None
    for attempt in range(1, attempts + 1):
        rate_limiter.wait_for_slot()
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "api-key": api_key,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=360) as response:
                body = response.read()
            break
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if exc.code < 500 and exc.code != 429:
                raise RuntimeError(f"Azure image request failed: HTTP {exc.code}: {detail}") from exc
            if attempt == attempts:
                raise RuntimeError(f"Azure image request failed after {attempts} attempts: HTTP {exc.code}: {detail}") from exc
            delay = retry_delay_seconds(attempt=attempt, error=exc, rate_limiter=rate_limiter)
            print(
                f"retry image request attempt={attempt + 1}/{attempts} "
                f"delay={delay:.1f}s reason=HTTP {exc.code}",
                flush=True,
            )
        except (
            urllib.error.URLError,
            TimeoutError,
            http.client.RemoteDisconnected,
            http.client.IncompleteRead,
        ) as exc:
            if attempt == attempts:
                raise RuntimeError(f"Azure image request failed after {attempts} attempts: {exc}") from exc
            delay = retry_delay_seconds(attempt=attempt, error=exc, rate_limiter=rate_limiter)
            print(
                f"retry image request attempt={attempt + 1}/{attempts} "
                f"delay={delay:.1f}s reason={exc.__class__.__name__}",
                flush=True,
            )
        time.sleep(delay)

    if body is None:
        raise RuntimeError("Azure image request returned no response body")

    data = json.loads(body.decode("utf-8"))
    item = data["data"][0]
    if "b64_json" in item:
        return base64.b64decode(item["b64_json"])
    if "url" in item:
        with urllib.request.urlopen(item["url"], timeout=360) as image_response:
            return image_response.read()
    raise RuntimeError("Azure image response did not contain b64_json or url")


def project_root_from_arg(project: str | None) -> Path:
    if project:
        return Path(project).expanduser().resolve()
    env_project = os.environ.get("VIDEO_PROJECT_DIR")
    if env_project:
        return Path(env_project).expanduser().resolve()
    return ENGINE_ROOT


def legacy_prompt_items(project_root: Path) -> tuple[Path, list[dict[str, str]]]:
    output_dir = project_root / "images" / "watercolor_bright"
    items = []
    for index, (name, scene_prompt) in enumerate(DEFAULT_PROMPTS, start=1):
        output_path = output_dir / f"{index:02d}_{name}.png"
        validate_generated_image_target(project_root, output_path, f"legacy prompt {index}")
        items.append(
            {
                "file": str(output_path),
                "prompt": f"{STYLE_PREFIX} Scene: {scene_prompt}",
            }
        )
    return output_dir, items


def resolve_project_path(project_root: Path, value: str, label: str) -> tuple[Path, str]:
    if not isinstance(value, str) or not value.strip():
        raise SystemExit(f"{label} path must be a non-empty string")
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = project_root / path
    path = path.resolve()
    try:
        relative = path.relative_to(project_root)
    except ValueError as exc:
        raise SystemExit(f"{label} must stay inside project root: {value}") from exc
    return path, relative.as_posix()


def validate_generated_output_dir(project_root: Path, output_dir: Path, label: str) -> None:
    try:
        relative = output_dir.resolve().relative_to(project_root)
    except ValueError as exc:
        raise SystemExit(f"{label} must stay inside project root: {output_dir}") from exc
    parts = {part.lower() for part in relative.parts}
    forbidden = next(
        (part for part in parts if part in FORBIDDEN_GENERATED_IMAGE_DIR_PARTS),
        None,
    )
    if forbidden:
        raise SystemExit(
            f"{label} uses forbidden generated image directory {output_dir!s} "
            f"matching {forbidden!r}"
        )


def validate_generated_image_target(project_root: Path, output_path: Path, label: str) -> None:
    try:
        relative = output_path.resolve().relative_to(project_root)
    except ValueError as exc:
        raise SystemExit(f"{label} image target must stay inside project root: {output_path}") from exc
    if output_path.suffix.lower() not in IMAGE_OUTPUT_SUFFIXES:
        raise SystemExit(
            f"{label} image target must use one of {sorted(IMAGE_OUTPUT_SUFFIXES)}: "
            f"{relative.as_posix()}"
        )
    lower_name = output_path.name.lower()
    forbidden_name = next(
        (marker for marker in FORBIDDEN_GENERATED_IMAGE_NAME_MARKERS if marker in lower_name),
        None,
    )
    if forbidden_name:
        raise SystemExit(
            f"{label} uses forbidden generated image path {relative.as_posix()!r} "
            f"matching {forbidden_name!r}"
        )
    parts = {part.lower() for part in relative.parts}
    forbidden_part = next(
        (part for part in parts if part in FORBIDDEN_GENERATED_IMAGE_DIR_PARTS),
        None,
    )
    if forbidden_part:
        raise SystemExit(
            f"{label} uses forbidden generated image path {relative.as_posix()!r} "
            f"matching {forbidden_part!r}"
        )


def parse_image_size(size: str) -> tuple[int, int]:
    try:
        width_text, height_text = size.lower().split("x", 1)
        width = int(width_text)
        height = int(height_text)
    except (AttributeError, ValueError) as exc:
        raise SystemExit(f"invalid image size {size!r}; expected WIDTHxHEIGHT") from exc
    if width <= 0 or height <= 0:
        raise SystemExit(f"invalid image size {size!r}; dimensions must be positive")
    return width, height


def validate_generated_image_bytes(
    image_bytes: bytes,
    *,
    expected_size: tuple[int, int],
    label: str,
) -> None:
    try:
        with Image.open(BytesIO(image_bytes)) as image:
            actual_size = image.size
            image.verify()
    except (UnidentifiedImageError, OSError) as exc:
        raise RuntimeError(f"generated image is not a readable image: {label}") from exc
    if actual_size != expected_size:
        raise RuntimeError(
            f"generated image has unexpected size for {label}: "
            f"expected {expected_size[0]}x{expected_size[1]}, "
            f"got {actual_size[0]}x{actual_size[1]}"
        )


def project_prompt_items(project_root: Path, prompt_path: Path) -> tuple[Path, list[dict[str, str]]]:
    data = json.loads(prompt_path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        style_prefix = STYLE_PREFIX
        prompt_specs = data
        output_dir = project_root / "images" / "watercolor_bright"
    else:
        style_prefix = data.get("stylePrefix", STYLE_PREFIX)
        prompt_specs = data["prompts"]
        output_dir, _ = resolve_project_path(
            project_root,
            data.get("outputDir", "images/watercolor_bright"),
            "image outputDir",
        )
    validate_generated_output_dir(project_root, output_dir, "image outputDir")

    items = []
    for position, spec in enumerate(prompt_specs, start=1):
        file_name = spec["file"]
        output_path, _ = resolve_project_path(project_root, file_name, f"image prompt {position}")
        validate_generated_image_target(project_root, output_path, f"image prompt {position}")
        prompt = spec.get("fullPrompt") or f"{style_prefix} Scene: {spec['prompt']}"
        items.append({"file": str(output_path), "prompt": prompt})
    return output_dir, items


def write_prompt_image(
    *,
    index: int,
    total: int,
    project_root: Path,
    item: dict[str, str],
    force: bool,
    rate_limiter: RequestRateLimiter,
    attempts: int,
    size: str,
    quality: str,
) -> dict[str, str]:
    output_path = Path(item["file"])
    validate_generated_image_target(project_root, output_path, f"image prompt {index}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    prompt = item["prompt"]
    metadata = {"file": str(output_path.relative_to(project_root)), "prompt": prompt}
    if output_path.exists() and not force:
        print(f"skip {index:02d}/{total} {output_path}", flush=True)
        return metadata
    print(f"generate {index:02d}/{total} {output_path.name}", flush=True)
    started = time.time()
    image_bytes = generate_image(
        prompt,
        rate_limiter=rate_limiter,
        attempts=attempts,
        size=size,
        quality=quality,
    )
    validate_generated_image_bytes(
        image_bytes,
        expected_size=parse_image_size(size),
        label=str(output_path.relative_to(project_root)),
    )
    temp_path = output_path.with_name(
        f".{output_path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    )
    try:
        temp_path.write_bytes(image_bytes)
        temp_path.replace(output_path)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    print(f"saved {index:02d}/{total} {output_path.name} elapsed={time.time() - started:.1f}s", flush=True)
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default=None)
    parser.add_argument("--prompts", default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--start", type=int, default=1, help="1-based first prompt index")
    parser.add_argument("--end", type=int, default=None, help="1-based last prompt index")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--concurrency", type=int, default=1, help="Parallel Azure image requests")
    parser.add_argument("--requests-per-minute", type=int, default=DEFAULT_REQUESTS_PER_MINUTE)
    parser.add_argument("--max-attempts", type=int, default=8)
    parser.add_argument("--size", default="1536x864", help="Azure image size, for example 1024x1024")
    parser.add_argument("--quality", choices=("low", "medium", "high"), default="low")
    parser.add_argument("--skip-metadata", action="store_true")
    args = parser.parse_args()

    project_root = project_root_from_arg(args.project)
    prompt_path = Path(args.prompts).expanduser().resolve() if args.prompts else project_root / "image_prompts.json"
    env_paths = [REPO_ROOT / ".env", project_root / ".env", ENGINE_ROOT / ".env"]
    for env_path in env_paths:
        load_env(env_path)

    if prompt_path.exists():
        output_dir, prompt_items = project_prompt_items(project_root, prompt_path)
    else:
        output_dir, prompt_items = legacy_prompt_items(project_root)

    output_dir.mkdir(parents=True, exist_ok=True)

    first = max(1, args.start)
    last = args.end if args.end is not None else len(prompt_items)
    selected = list(enumerate(prompt_items[first - 1:last], start=first))
    if args.limit:
        selected = selected[: args.limit]
    total = len(prompt_items)
    concurrency = max(1, args.concurrency)
    requests_per_minute = max(1, args.requests_per_minute)
    attempts = max(1, args.max_attempts)
    rate_limiter = RequestRateLimiter(requests_per_minute)
    needs_generation = any(args.force or not Path(item["file"]).exists() for _, item in selected)
    if needs_generation:
        print(
            f"azure image request limit={requests_per_minute}/min "
            f"max_attempts={attempts} size={args.size} quality={args.quality}",
            flush=True,
        )

    metadata_by_index: dict[int, dict[str, str]] = {}
    if concurrency == 1 or len(selected) <= 1:
        for index, item in selected:
            metadata_by_index[index] = write_prompt_image(
                index=index,
                total=total,
                project_root=project_root,
                item=item,
                force=args.force,
                rate_limiter=rate_limiter,
                attempts=attempts,
                size=args.size,
                quality=args.quality,
            )
    else:
        print(f"parallel image generation concurrency={concurrency}", flush=True)
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
            future_to_index = {
                executor.submit(
                    write_prompt_image,
                    index=index,
                    total=total,
                    project_root=project_root,
                    item=item,
                    force=args.force,
                    rate_limiter=rate_limiter,
                    attempts=attempts,
                    size=args.size,
                    quality=args.quality,
                ): index
                for index, item in selected
            }
            try:
                for future in concurrent.futures.as_completed(future_to_index):
                    index = future_to_index[future]
                    metadata_by_index[index] = future.result()
            except Exception:
                for future in future_to_index:
                    future.cancel()
                raise

    metadata = [metadata_by_index[index] for index, _ in selected]

    if not args.skip_metadata:
        (output_dir / "prompts.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(f"done count={len(selected)} out={output_dir}", flush=True)


if __name__ == "__main__":
    main()
