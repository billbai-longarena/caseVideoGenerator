#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from collections import Counter
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageStat


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POOL = ROOT / "assets" / "character-portraits"


def read_json(path: Path, default: Any | None = None) -> Any:
    if not path.is_file():
        if default is not None:
            return default
        raise SystemExit(f"JSON file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def direction_copy(direction: str) -> tuple[str, str, list[str]]:
    if direction == "screen-right":
        return (
            "three-quarter portrait facing screen-right; the nose and gaze point toward the right edge",
            "left",
            ["dialogue-left", "character-introduction", "role-card"],
        )
    if direction == "screen-left":
        return (
            "three-quarter portrait facing screen-left; the nose and gaze point toward the left edge",
            "right",
            ["dialogue-right", "character-introduction", "role-card"],
        )
    return (
        "straight-on portrait facing the camera with a direct but natural eye line",
        "center-or-either",
        ["character-introduction", "role-card", "dialogue-either"],
    )


def gender_code(gender: str) -> str:
    return "m" if gender == "male" else "f"


def gender_subject(gender: str) -> str:
    return "Chinese man" if gender == "male" else "Chinese woman"


def prompt_for(style: dict[str, Any], profile: dict[str, Any]) -> str:
    direction, _, _ = direction_copy(profile["faceDirection"])
    is_manager_silhouette = style["id"] == "manager-silhouette-warm"
    use_case = "illustration-story" if not is_manager_silhouette else "faceless-symbolic-character"
    subject_kind = (
        f"faceless silhouette bust representing one distinct {gender_subject(profile['gender'])}"
        if is_manager_silhouette
        else f"exactly one distinct {gender_subject(profile['gender'])}"
    )
    lighting = (
        "Lighting/mood: graphic faceless managerial silhouette, restrained warm rim light, calm authority"
        if is_manager_silhouette
        else "Lighting/mood: polished editorial business portrait, calm professional presence, clear silhouette"
    )
    face_constraint = (
        "The face must remain a single uninterrupted near-black or deep-navy shape. Do not render facial anatomy "
        "or skin. This faceless treatment is mandatory, including on front-facing portraits."
        if is_manager_silhouette
        else "The face should remain clear, natural and recognizably Chinese."
    )
    style_text = "; ".join(style["promptClauses"])
    avoid = ", ".join(style["avoid"])
    return "\n".join(
        [
            f"Use case: {use_case}",
            "Asset type: reusable square Remotion character portrait for a Chinese business case video",
            (
                f"Primary request: {subject_kind}, approximately "
                f"{profile['age']} years old, in formal business attire"
            ),
            (
                "Scene/backdrop: seamless pure white #FFFFFF background; both top corners and all visible outer "
                "background must remain clean white; the bust may naturally exit through the bottom edge; no room, "
                "scenery, floor plane, furniture, props, cast shadow or frame"
            ),
            (
                f"Subject: {profile['appearance']}; {profile['attire']}; expression is "
                f"{profile['expression']}"
            ),
            f"Style/medium: {style_text}",
            f"Mandatory face treatment: {face_constraint}",
            (
                "Composition/framing: exact 1:1 square, centered chest-up head-and-shoulders bust, head and both "
                f"shoulders fully inside frame, 10 to 12 percent breathing room, {direction}; crop-safe for a round "
                "or rounded-square mask"
            ),
            lighting,
            (
                "Constraints: one adult only; recognizably Chinese; age must read plausibly; formal suit or blazer; "
                "an original fictional person who does not resemble a celebrity or public figure; no hands near the face; "
                "no text, letters, numerals, logos, badges, company marks, watermark or signature"
            ),
            f"Avoid: {avoid}; extra people; duplicate heads; cropped hair; cropped shoulders; busy background",
        ]
    )


def expected_assets(pool: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    specs = read_json(pool / "specs.json")
    target = specs["target"]
    style_ids = {style["id"] for style in specs["styles"]}
    assets: list[dict[str, Any]] = []
    for style in specs["styles"]:
        for profile in specs["profiles"]:
            requested_styles = set(profile.get("styles", style_ids))
            unknown_styles = requested_styles - style_ids
            if unknown_styles:
                raise SystemExit(
                    f"portrait profile slot={profile.get('slot')} has unknown styles: "
                    f"{sorted(unknown_styles)}"
                )
            if style["id"] not in requested_styles:
                continue
            code = gender_code(profile["gender"])
            asset_id = f"{style['idPrefix']}-{code}-{profile['slot']:02d}"
            relative = f"{style['directory']}/{asset_id}.png"
            _, placement, uses = direction_copy(profile["faceDirection"])
            assets.append(
                {
                    "id": asset_id,
                    "file": relative,
                    "style": style["id"],
                    "styleLabel": style["label"],
                    "gender": profile["gender"],
                    "age": profile["age"],
                    "ageBand": profile["ageBand"],
                    "faceDirection": profile["faceDirection"],
                    "recommendedPlacement": placement,
                    "recommendedUses": uses,
                    "nationality": target["nationality"],
                    "attire": target["attire"],
                    "background": target["background"],
                    "framing": target["framing"],
                    "expression": profile["expression"],
                    "appearance": profile["appearance"],
                    "wardrobe": profile["attire"],
                    "prompt": prompt_for(style, profile),
                }
            )
    ids = [asset["id"] for asset in assets]
    duplicates = sorted(asset_id for asset_id, count in Counter(ids).items() if count > 1)
    if duplicates:
        raise SystemExit(f"duplicate portrait asset IDs: {duplicates}")
    if not assets:
        raise SystemExit("portrait specifications produced no assets")
    return specs, assets


def command_prepare(args: argparse.Namespace) -> int:
    pool = Path(args.pool_root).resolve()
    specs, assets = expected_assets(pool)
    target = specs["target"]
    prompts = {
        "schemaVersion": 1,
        "assetType": "character-portrait",
        "outputDir": ".",
        "generation": {
            "provider": "Azure OpenAI",
            "deployment": "gpt-image-2",
            "size": f"{target['width']}x{target['height']}",
            "quality": args.quality,
            "format": target["format"].lower(),
        },
        "prompts": [
            {
                "id": asset["id"],
                "file": asset["file"],
                "fullPrompt": asset["prompt"],
                "style": asset["style"],
                "gender": asset["gender"],
                "age": asset["age"],
                "ageBand": asset["ageBand"],
                "faceDirection": asset["faceDirection"],
                "recommendedPlacement": asset["recommendedPlacement"],
                "recommendedUses": asset["recommendedUses"],
            }
            for asset in assets
        ],
    }
    write_json(pool / "generation_prompts.json", prompts)
    counts = Counter((asset["style"], asset["gender"]) for asset in assets)
    print(
        f"prepared {len(assets)} prompts groups={dict(counts)} "
        f"-> {pool / 'generation_prompts.json'}"
    )
    return 0


def image_metrics(path: Path) -> dict[str, Any]:
    with Image.open(path) as image:
        image.load()
        width, height = image.size
        image_format = image.format or path.suffix.lstrip(".").upper()
        rgb = image.convert("RGB")
    patch = max(24, min(width, height) // 16)
    boxes = [
        (0, 0, patch, patch),
        (width - patch, 0, width, patch),
        (0, height - patch, patch, height),
        (width - patch, height - patch, width, height),
    ]
    corner_means = [round(sum(ImageStat.Stat(rgb.crop(box)).mean) / 3, 2) for box in boxes]
    sample = rgb.resize((128, 128), Image.Resampling.LANCZOS)
    non_white = 0
    for red, green, blue in sample.getdata():
        if max(255 - red, 255 - green, 255 - blue) > 24:
            non_white += 1
    coverage = round(non_white / (128 * 128), 4)
    gray = rgb.convert("L").resize((16, 16), Image.Resampling.LANCZOS)
    pixels = list(gray.getdata())
    mean = sum(pixels) / len(pixels)
    perceptual_hash = 0
    for value in pixels:
        perceptual_hash = (perceptual_hash << 1) | int(value < mean)
    return {
        "width": width,
        "height": height,
        "format": image_format,
        "cornerWhiteMean": corner_means,
        "subjectCoverage": coverage,
        "perceptualHash": f"{perceptual_hash:064x}",
    }


def hamming(left: str, right: str) -> int:
    return (int(left, 16) ^ int(right, 16)).bit_count()


def build_contact_sheet(pool: Path, assets: list[dict[str, Any]], name: str, columns: int) -> Path:
    thumb = 220
    label_height = 34
    gap = 14
    rows = (len(assets) + columns - 1) // columns
    width = gap + columns * (thumb + gap)
    height = gap + rows * (thumb + label_height + gap)
    sheet = Image.new("RGB", (width, height), "#E9EDF3")
    draw = ImageDraw.Draw(sheet)
    for index, asset in enumerate(assets):
        row, column = divmod(index, columns)
        left = gap + column * (thumb + gap)
        top = gap + row * (thumb + label_height + gap)
        with Image.open(pool / asset["file"]) as source:
            tile = source.convert("RGB").resize((thumb, thumb), Image.Resampling.LANCZOS)
        sheet.paste(tile, (left, top))
        label = f"{asset['id']}  {asset['age']}y  {asset['faceDirection']}"
        draw.rectangle((left, top + thumb, left + thumb, top + thumb + label_height), fill="#0B1B32")
        draw.text((left + 7, top + thumb + 9), label, fill="white")
    output = pool / "contact-sheets" / f"{name}.jpg"
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output, quality=92, subsampling=0)
    return output


def finalized_catalog(pool: Path, *, reviewed: bool) -> dict[str, Any]:
    specs, expected = expected_assets(pool)
    target = specs["target"]
    missing: list[str] = []
    invalid: list[str] = []
    assets: list[dict[str, Any]] = []
    for asset in expected:
        path = pool / asset["file"]
        if not path.is_file():
            missing.append(asset["file"])
            continue
        metrics = image_metrics(path)
        issues: list[str] = []
        if metrics["width"] != target["width"] or metrics["height"] != target["height"]:
            issues.append("wrong-dimensions")
        # A chest-up portrait naturally exits through the bottom edge, so the
        # lower corners may contain the subject's jacket. The two top corners
        # are stable exposed-background samples for this asset contract.
        if min(metrics["cornerWhiteMean"][:2]) < 225:
            issues.append("top-background-not-white")
        if not 0.12 <= metrics["subjectCoverage"] <= 0.72:
            issues.append("subject-coverage-outlier")
        if issues:
            invalid.append(f"{asset['id']}: {', '.join(issues)}")
        assets.append(
            {
                **{key: value for key, value in asset.items() if key != "prompt"},
                "canonicalPath": asset["file"],
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
                "width": metrics["width"],
                "height": metrics["height"],
                "format": metrics["format"],
                "prompt": asset["prompt"],
                "qa": {
                    "cornerWhiteMean": metrics["cornerWhiteMean"],
                    "subjectCoverage": metrics["subjectCoverage"],
                    "issues": issues,
                    "visualReview": "accepted" if reviewed and not issues else "pending",
                },
                "perceptualHash": metrics["perceptualHash"],
            }
        )
    duplicate_pairs: list[str] = []
    for index, left in enumerate(assets):
        for right in assets[index + 1 :]:
            if left["style"] != right["style"]:
                continue
            distance = hamming(left["perceptualHash"], right["perceptualHash"])
            if distance <= 3:
                duplicate_pairs.append(f"{left['id']} / {right['id']} (distance={distance})")
    if missing or invalid or duplicate_pairs:
        messages = []
        if missing:
            messages.append("missing:\n  " + "\n  ".join(missing))
        if invalid:
            messages.append("invalid:\n  " + "\n  ".join(invalid))
        if duplicate_pairs:
            messages.append("possible duplicates:\n  " + "\n  ".join(duplicate_pairs))
        raise SystemExit("\n".join(messages))
    counts = Counter((asset["style"], asset["gender"]) for asset in assets)
    catalog = {
        "schemaVersion": 1,
        "poolType": "character-portraits",
        "poolRoot": "assets/character-portraits",
        "stats": {
            "assets": len(assets),
            "styles": len({asset["style"] for asset in assets}),
            "byStyleAndGender": {
                f"{style}:{gender}": count for (style, gender), count in sorted(counts.items())
            },
            "ageRange": [min(asset["age"] for asset in assets), max(asset["age"] for asset in assets)],
            "reviewedAssets": sum(asset["qa"]["visualReview"] == "accepted" for asset in assets),
        },
        "assets": assets,
    }
    return catalog


def command_finalize(args: argparse.Namespace) -> int:
    pool = Path(args.pool_root).resolve()
    catalog = finalized_catalog(pool, reviewed=args.reviewed)
    write_json(pool / "catalog.json", catalog)
    for style in sorted({asset["style"] for asset in catalog["assets"]}):
        subset = [asset for asset in catalog["assets"] if asset["style"] == style]
        path = build_contact_sheet(pool, subset, style, columns=5)
        print(f"contact sheet: {path}")
    combined = build_contact_sheet(pool, catalog["assets"], "all-character-portraits", columns=8)
    print(f"contact sheet: {combined}")
    print(
        f"catalog finalized: assets={catalog['stats']['assets']} "
        f"reviewed={catalog['stats']['reviewedAssets']} -> {pool / 'catalog.json'}"
    )
    return 0


def load_catalog(pool: Path) -> dict[str, Any]:
    return read_json(pool / "catalog.json")


def command_search(args: argparse.Namespace) -> int:
    pool = Path(args.pool_root).resolve()
    catalog = load_catalog(pool)
    matches = []
    for asset in catalog["assets"]:
        if args.style and asset["style"] != args.style:
            continue
        if args.gender and asset["gender"] != args.gender:
            continue
        if args.direction and asset["faceDirection"] != args.direction:
            continue
        if args.min_age is not None and asset["age"] < args.min_age:
            continue
        if args.max_age is not None and asset["age"] > args.max_age:
            continue
        matches.append(asset)
    for asset in matches:
        print(
            f"{asset['id']} | {asset['style']} | {asset['gender']} | age={asset['age']} | "
            f"direction={asset['faceDirection']} | placement={asset['recommendedPlacement']} | {asset['canonicalPath']}"
        )
    print(f"matches={len(matches)}")
    return 0


def command_checkout(args: argparse.Namespace) -> int:
    pool = Path(args.pool_root).resolve()
    catalog = load_catalog(pool)
    by_id = {asset["id"]: asset for asset in catalog["assets"]}
    if args.asset_id not in by_id:
        raise SystemExit(f"unknown portrait id: {args.asset_id}")
    asset = by_id[args.asset_id]
    source = pool / asset["canonicalPath"]
    project = Path(args.project)
    if not project.is_absolute():
        project = (ROOT / project).resolve()
    if not project.is_dir():
        raise SystemExit(f"project directory not found: {project}")
    destination_dir = project / args.destination
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / (args.name or source.name)
    if destination.exists() and sha256_file(destination) != asset["sha256"] and not args.force:
        raise SystemExit(f"destination exists with different content: {destination}; use --force")
    if not destination.exists() or sha256_file(destination) != asset["sha256"]:
        shutil.copy2(source, destination)
    project_relative = destination.relative_to(project).as_posix()
    manifest_path = project / "asset_pool_usage.json"
    manifest = read_json(manifest_path, {"schemaVersion": 1, "assets": []})
    records = [
        record
        for record in manifest.get("assets", [])
        if record.get("src") != project_relative and record.get("assetId") != asset["id"]
    ]
    records.append(
        {
            "assetId": asset["id"],
            "src": project_relative,
            "sha256": asset["sha256"],
            "poolPath": f"assets/character-portraits/{asset['canonicalPath']}",
            "sourceProjects": [],
            "poolType": "character-portrait",
            "tags": {
                "style": asset["style"],
                "gender": asset["gender"],
                "ageBand": asset["ageBand"],
                "faceDirection": asset["faceDirection"],
                "recommendedPlacement": asset["recommendedPlacement"],
            },
        }
    )
    manifest["assets"] = sorted(records, key=lambda record: record["src"])
    write_json(manifest_path, manifest)
    snippet = {
        "id": f"person-{asset['id']}",
        "type": "image",
        "src": project_relative,
        "role": "person",
        "origin": "curated",
        "poolAssetId": asset["id"],
    }
    print(f"checked out {asset['id']} -> {project_relative}")
    print(json.dumps(snippet, ensure_ascii=False))
    return 0


def command_audit(args: argparse.Namespace) -> int:
    pool = Path(args.pool_root).resolve()
    catalog = load_catalog(pool)
    rebuilt = finalized_catalog(pool, reviewed=False)
    expected = {asset["id"]: asset for asset in rebuilt["assets"]}
    actual = {asset["id"]: asset for asset in catalog["assets"]}
    if set(expected) != set(actual):
        raise SystemExit("catalog IDs do not match the current specifications and files")
    for asset_id, asset in expected.items():
        if actual[asset_id].get("sha256") != asset["sha256"]:
            raise SystemExit(f"catalog hash is stale: {asset_id}")
    counts = Counter((asset["style"], asset["gender"]) for asset in actual.values())
    print(f"character portrait pool audit passed: assets={len(actual)} groups={dict(counts)}")
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Build, inspect and checkout reusable character portraits")
    root.add_argument("--pool-root", default=str(DEFAULT_POOL))
    commands = root.add_subparsers(dest="command", required=True)

    prepare = commands.add_parser("prepare", help="expand specs into exact generation prompts")
    prepare.add_argument("--quality", choices=("low", "medium", "high"), default="medium")
    prepare.set_defaults(func=command_prepare)

    finalize = commands.add_parser("finalize", help="validate images and build catalog/contact sheets")
    finalize.add_argument("--reviewed", action="store_true", help="mark assets visually accepted after manual review")
    finalize.set_defaults(func=command_finalize)

    search = commands.add_parser("search", help="filter portraits by metadata")
    search.add_argument("--style")
    search.add_argument("--gender", choices=("male", "female"))
    search.add_argument("--direction", choices=("front", "screen-left", "screen-right"))
    search.add_argument("--min-age", type=int)
    search.add_argument("--max-age", type=int)
    search.set_defaults(func=command_search)

    checkout = commands.add_parser("checkout", help="copy a portrait into a case project and record provenance")
    checkout.add_argument("asset_id")
    checkout.add_argument("project")
    checkout.add_argument("--destination", default="images/characters")
    checkout.add_argument("--name")
    checkout.add_argument("--force", action="store_true")
    checkout.set_defaults(func=command_checkout)

    audit = commands.add_parser("audit", help="verify files, hashes, counts and catalog consistency")
    audit.set_defaults(func=command_audit)
    return root


def main() -> None:
    args = parser().parse_args()
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
