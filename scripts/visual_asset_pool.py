#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
from typing import Any, Iterable

try:
    from PIL import Image
except ImportError:  # pragma: no cover - handled by audit/build output
    Image = None


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POOL = ROOT / "assets" / "visual-pool"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
FORBIDDEN_POOL_SOURCE_MARKERS = (
    "management_cutout/",
    "programmatic",
)
NON_BACKGROUND_SOURCE_PREFIXES = (
    "characters/",
)
DIMENSION_KEYS = (
    "settings",
    "activities",
    "participants",
    "storyFunctions",
    "objects",
    "moods",
    "industries",
    "visualFamilies",
)


def read_json(path: Path, default: Any = None) -> Any:
    if not path.is_file():
        if default is not None:
            return default
        raise SystemExit(f"missing JSON file: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid JSON: {path}: {exc}") from exc


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    if path.is_file() and path.read_text(encoding="utf-8") == rendered:
        return
    path.write_text(rendered, encoding="utf-8")


def normalize_relative(value: str) -> str:
    return value.replace("\\", "/").lstrip("./")


def flatten_text(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, (int, float)):
        return [str(value)]
    if isinstance(value, list):
        result: list[str] = []
        for child in value:
            result.extend(flatten_text(child))
        return result
    if isinstance(value, dict):
        result = []
        for child in value.values():
            result.extend(flatten_text(child))
        return result
    return []


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def image_metadata(path: Path) -> tuple[int | None, int | None, str]:
    if Image is None:
        return None, None, path.suffix.lstrip(".").upper()
    try:
        with Image.open(path) as image:
            return image.width, image.height, str(image.format or path.suffix.lstrip(".")).upper()
    except Exception as exc:  # noqa: BLE001 - inventory must report unreadable assets
        raise SystemExit(f"cannot read image {path}: {exc}") from exc


def taxonomy_values(taxonomy: dict, dimension: str) -> list[dict]:
    return taxonomy["dimensions"][dimension]["values"]


def taxonomy_lookup(taxonomy: dict, dimension: str) -> dict[str, dict]:
    return {item["id"]: item for item in taxonomy_values(taxonomy, dimension)}


def keyword_in_text(keyword: str, haystack: str) -> bool:
    normalized = keyword.casefold().strip()
    if not normalized:
        return False
    if all(ord(char) < 128 for char in normalized):
        pattern = rf"(?<![a-z0-9]){re.escape(normalized)}(?![a-z0-9])"
        return re.search(pattern, haystack) is not None
    return normalized in haystack


def strip_negated_clauses(text: str) -> str:
    """Remove prompt constraints such as `no boardroom` before semantic tagging."""
    cleaned = text.casefold()
    cleaned = re.sub(
        r"\b(?:no|without|avoid)\b[^,.;:\n]{0,100}",
        " ",
        cleaned,
    )
    cleaned = re.sub(
        r"\bnot\s+(?:an?\s+)?[^,.;:\n]{0,100}",
        " ",
        cleaned,
    )
    cleaned = re.sub(
        r"(?:不要|避免|没有|并非|不是|无须|无需)[^，。；：\n]{0,60}",
        " ",
        cleaned,
    )
    return cleaned


def match_dimension(text: str, taxonomy: dict, dimension: str) -> list[str]:
    config = taxonomy["dimensions"][dimension]
    raw_haystack = text.casefold()
    # `no people` is itself useful participant metadata. Other dimensions should
    # ignore negative prompt constraints such as `no conventional boardroom`.
    haystack = raw_haystack if dimension == "participants" else strip_negated_clauses(raw_haystack)
    scored: list[tuple[float, str]] = []
    for item in config["values"]:
        matches = []
        for keyword in item.get("keywords", []):
            normalized = str(keyword).casefold().strip()
            if keyword_in_text(normalized, haystack):
                matches.append(normalized)
        if matches:
            priority = float(item.get("priority", 0))
            specificity = sum(min(len(keyword), 30) / 30 for keyword in matches)
            scored.append((priority + specificity, item["id"]))
    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    max_matches = int(config.get("maxMatches", 5))
    result = [item_id for _, item_id in scored[:max_matches]]
    fallback = config.get("fallback")
    if not result and fallback:
        result = [fallback]
    return result


def merge_unique(*groups: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for group in groups:
        for value in group:
            if value not in seen:
                seen.add(value)
                result.append(value)
    return result


def profile_tags(taxonomy: dict, project_name: str, dimension: str) -> list[str]:
    return list(taxonomy.get("projectProfiles", {}).get(project_name, {}).get(dimension, []))


def classify_text(
    text: str,
    taxonomy: dict,
    project_name: str,
    *,
    explicit_story_functions: Iterable[str] = (),
    path_hint: str = "",
) -> dict[str, list[str]]:
    combined = f"{text}\n{path_hint}"
    tags: dict[str, list[str]] = {}
    for dimension in DIMENSION_KEYS:
        matched = match_dimension(combined, taxonomy, dimension)
        if dimension in {"industries", "visualFamilies"}:
            matched = merge_unique(
                match_dimension(path_hint, taxonomy, dimension),
                profile_tags(taxonomy, project_name, dimension),
                matched,
            )
        if dimension == "storyFunctions":
            valid = taxonomy_lookup(taxonomy, dimension)
            matched = merge_unique(
                [value for value in explicit_story_functions if value in valid],
                matched,
            )
        tags[dimension] = matched
    return tags


def normalize_scene_demand_tags(tags: dict[str, list[str]], text: str, taxonomy: dict) -> None:
    """Give meaningful non-literal scenes a production-ready visual category.

    Storyboard text often explains a mechanism or dilemma without naming a
    physical room. For demand planning, that is an abstract editorial scene,
    not missing information. The unknown fallbacks remain available for truly
    empty or malformed scene records.
    """
    if not text.strip():
        return
    setting_fallback = taxonomy["dimensions"]["settings"].get("fallback")
    activity_fallback = taxonomy["dimensions"]["activities"].get("fallback")
    if tags.get("settings") == [setting_fallback]:
        tags["settings"] = ["abstract-editorial"]
    if tags.get("activities") == [activity_fallback]:
        tags["activities"] = ["metaphor-transition"]


def load_tag_overrides(pool: Path) -> dict:
    return read_json(
        pool / "tag_overrides.json",
        {"schemaVersion": 1, "assets": {}},
    )


def tag_override_errors(
    overrides: Any,
    taxonomy: dict,
    asset_ids: set[str] | None = None,
) -> list[str]:
    errors: list[str] = []
    if not isinstance(overrides, dict):
        return ["tag overrides must be a JSON object"]
    if overrides.get("schemaVersion") != 1:
        errors.append("tag overrides schemaVersion must be 1")
    records = overrides.get("assets")
    if not isinstance(records, dict):
        errors.append("tag overrides assets must be an object keyed by asset ID")
        return errors
    valid = {dimension: taxonomy_lookup(taxonomy, dimension) for dimension in DIMENSION_KEYS}
    allowed_record_keys = {"replace", "add", "remove", "note"}
    for asset_id, record in records.items():
        prefix = f"tag override {asset_id}"
        if not isinstance(asset_id, str) or not asset_id.startswith("va-"):
            errors.append(f"{prefix}: key must be a stable va-* asset ID")
            continue
        if asset_ids is not None and asset_id not in asset_ids:
            errors.append(f"{prefix}: asset does not exist in the current pool")
        if not isinstance(record, dict):
            errors.append(f"{prefix}: record must be an object")
            continue
        unknown_keys = sorted(set(record) - allowed_record_keys)
        if unknown_keys:
            errors.append(f"{prefix}: unknown fields: {', '.join(unknown_keys)}")
        if "note" in record and not isinstance(record["note"], str):
            errors.append(f"{prefix}: note must be a string")
        for operation in ("replace", "add", "remove"):
            mapping = record.get(operation, {})
            if not isinstance(mapping, dict):
                errors.append(f"{prefix}: {operation} must be an object")
                continue
            for dimension, values in mapping.items():
                if dimension not in DIMENSION_KEYS:
                    errors.append(f"{prefix}: unknown tag dimension in {operation}: {dimension}")
                    continue
                if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
                    errors.append(f"{prefix}: {operation}.{dimension} must be a string array")
                    continue
                if len(values) != len(set(values)):
                    errors.append(f"{prefix}: {operation}.{dimension} contains duplicate values")
                for value in values:
                    if value not in valid[dimension]:
                        errors.append(f"{prefix}: unknown {dimension} tag in {operation}: {value}")
    return errors


def apply_tag_overrides(assets: list[dict], taxonomy: dict, overrides: dict) -> None:
    by_id = {asset["id"]: asset for asset in assets}
    errors = tag_override_errors(overrides, taxonomy, set(by_id))
    if errors:
        raise SystemExit("invalid tag_overrides.json:\n- " + "\n- ".join(errors))
    for asset_id in sorted(overrides.get("assets", {})):
        record = overrides["assets"][asset_id]
        asset = by_id[asset_id]
        for dimension in DIMENSION_KEYS:
            values = list(asset["tags"].get(dimension, []))
            if dimension in record.get("replace", {}):
                values = list(record["replace"][dimension])
            removed = set(record.get("remove", {}).get(dimension, []))
            values = [value for value in values if value not in removed]
            values = merge_unique(values, record.get("add", {}).get(dimension, []))
            fallback = taxonomy["dimensions"][dimension].get("fallback")
            if fallback in values and len(values) > 1:
                values = [value for value in values if value != fallback]
            if not values and fallback:
                values = [fallback]
            asset["tags"][dimension] = values
        asset["primarySetting"] = asset["tags"]["settings"][0]
        asset["primaryActivity"] = asset["tags"]["activities"][0]
        asset["curation"] = {
            "manualOverride": True,
            "note": record.get("note", ""),
            "operations": {
                operation: record[operation]
                for operation in ("replace", "add", "remove")
                if record.get(operation)
            },
        }


def prompt_index(project: Path) -> tuple[dict[str, dict], dict[str, list[dict]], int]:
    path = project / "image_prompts.json"
    if not path.is_file():
        return {}, {}, 0
    raw = read_json(path)
    prompts = raw if isinstance(raw, list) else raw.get("prompts", [])
    style_prefix = "" if isinstance(raw, list) else str(raw.get("stylePrefix", ""))
    by_path: dict[str, dict] = {}
    by_basename: dict[str, list[dict]] = {}
    for item in prompts:
        if not isinstance(item, dict) or not isinstance(item.get("file"), str):
            continue
        normalized = normalize_relative(item["file"])
        record = {
            "file": normalized,
            "prompt": str(item.get("prompt", "")),
            "stylePrefix": style_prefix,
        }
        by_path[normalized] = record
        by_basename.setdefault(Path(normalized).name, []).append(record)
    return by_path, by_basename, len(prompts)


def headline_text(scene: dict) -> str:
    headline = scene.get("headline", "")
    if isinstance(headline, dict):
        return str(headline.get("text", ""))
    return str(headline)


def storyboard_context(project: Path) -> tuple[dict[str, list[dict]], list[dict], dict, int]:
    path = project / "rich_storyboard.json"
    if not path.is_file():
        return {}, [], {}, 0
    storyboard = read_json(path)
    assets_by_id = {
        item.get("id"): normalize_relative(item.get("src", ""))
        for item in storyboard.get("visualAssets", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str) and isinstance(item.get("src"), str)
    }
    refs: dict[str, list[dict]] = {}
    scene_rows: list[dict] = []
    for position, scene in enumerate(storyboard.get("scenes", []), start=1):
        scene_id = str(scene.get("id") or f"s{position:02d}")
        backgrounds = [
            normalize_relative(cue["image"])
            for cue in scene.get("backgrounds", [])
            if isinstance(cue, dict) and isinstance(cue.get("image"), str)
        ]
        beat_asset_ids: list[str] = []
        purposes: list[str] = []
        for beat in scene.get("visualBeats", []):
            if not isinstance(beat, dict):
                continue
            if isinstance(beat.get("purpose"), str):
                purposes.append(beat["purpose"])
            if isinstance(beat.get("baseAsset"), str):
                beat_asset_ids.append(beat["baseAsset"])
            for layer in beat.get("layers", []):
                if not isinstance(layer, dict):
                    continue
                for key in ("asset", "assetId"):
                    if isinstance(layer.get(key), str):
                        beat_asset_ids.append(layer[key])
        visual_paths = [assets_by_id[asset_id] for asset_id in beat_asset_ids if asset_id in assets_by_id]
        all_paths = merge_unique(backgrounds, visual_paths)
        visual_beat_text = []
        for beat in scene.get("visualBeats", []):
            if not isinstance(beat, dict):
                continue
            visual_beat_text.append(
                {
                    "layers": [
                        {"label": layer.get("label"), "text": layer.get("text")}
                        for layer in beat.get("layers", [])
                        if isinstance(layer, dict)
                    ]
                }
            )
        summary = {
            "project": project.name,
            "sceneId": scene_id,
            "position": position,
            "kicker": str(scene.get("kicker", "")),
            "headline": headline_text(scene),
            "units": scene.get("units"),
            "backgrounds": all_paths,
            "visualMode": str(scene.get("visualMode", "layout")),
            "explicitStoryFunctions": merge_unique(purposes),
            "text": "\n".join(
                flatten_text(
                    {
                        "kicker": scene.get("kicker"),
                        "headline": scene.get("headline"),
                        "subtitles": scene.get("subtitles"),
                        "props": scene.get("props"),
                        "visualBeatText": visual_beat_text,
                    }
                )
            ),
        }
        scene_rows.append(summary)
        for relative_path in all_paths:
            refs.setdefault(relative_path, []).append(
                {
                    "project": project.name,
                    "sceneId": scene_id,
                    "position": position,
                    "kicker": summary["kicker"],
                    "headline": summary["headline"],
                    "units": summary["units"],
                    "visualMode": summary["visualMode"],
                    "storyFunctions": summary["explicitStoryFunctions"],
                }
            )
    meta = {
        "title": str(storyboard.get("title", "")),
        "projectType": str(storyboard.get("projectType", "")),
        "visualStyle": str(storyboard.get("visualStyle", "")),
    }
    return refs, scene_rows, meta, len(storyboard.get("scenes", []))


def iter_projects(root: Path) -> list[Path]:
    output = root / "output"
    if not output.is_dir():
        return []
    return sorted(
        path
        for path in output.iterdir()
        if path.is_dir()
        and (
            (path / "rich_storyboard.json").is_file()
            or (path / "image_prompts.json").is_file()
            or (path / "images").is_dir()
        )
    )


def iter_source_images(project: Path) -> list[Path]:
    images = project / "images"
    if not images.is_dir():
        return []
    candidates = sorted(
        path
        for path in images.rglob("*")
        if path.is_file()
        and path.suffix.casefold() in IMAGE_SUFFIXES
        and not any(
            normalize_relative(str(path.relative_to(images))).casefold().startswith(prefix)
            for prefix in NON_BACKGROUND_SOURCE_PREFIXES
        )
    )
    forbidden = [
        path
        for path in candidates
        if any(
            marker in normalize_relative(str(path.relative_to(images))).casefold()
            for marker in FORBIDDEN_POOL_SOURCE_MARKERS
        )
    ]
    if forbidden:
        rendered = ", ".join(
            normalize_relative(str(path.relative_to(project))) for path in forbidden[:5]
        )
        suffix = "" if len(forbidden) <= 5 else f" (+{len(forbidden) - 5} more)"
        raise SystemExit(
            f"forbidden programmatic visual source(s) in {project.name}: "
            f"{rendered}{suffix}"
        )
    return candidates


def attach_prompt(
    relative: str,
    by_path: dict[str, dict],
    by_basename: dict[str, list[dict]],
) -> tuple[dict | None, str]:
    if relative in by_path:
        return by_path[relative], "exact"
    candidates = by_basename.get(Path(relative).name, [])
    if len(candidates) == 1:
        return candidates[0], "basename-variant"
    return None, "none"


def scene_inventory(
    projects: list[Path],
    taxonomy: dict,
    prompt_maps: dict[str, dict[str, dict]],
) -> list[dict]:
    rows: list[dict] = []
    for project in projects:
        _, scenes, meta, _ = storyboard_context(project)
        prompt_map = prompt_maps.get(project.name, {})
        for scene in scenes:
            prompt_text = "\n".join(
                prompt_map[path]["prompt"]
                for path in scene["backgrounds"]
                if path in prompt_map
            )
            text = "\n".join([scene.pop("text"), prompt_text])
            path_hint = " ".join(scene["backgrounds"] + [meta.get("visualStyle", "")])
            tags = classify_text(
                text,
                taxonomy,
                project.name,
                explicit_story_functions=scene.pop("explicitStoryFunctions"),
                path_hint=path_hint,
            )
            normalize_scene_demand_tags(tags, text, taxonomy)
            rows.append(
                {
                    "id": f"{project.name}:{scene['sceneId']}",
                    **scene,
                    "projectTitle": meta.get("title", ""),
                    "projectType": meta.get("projectType", ""),
                    "tags": tags,
                    "primarySetting": tags["settings"][0],
                    "primaryActivity": tags["activities"][0],
                }
            )
    return rows


def create_views(pool: Path, assets: list[dict]) -> int:
    views = pool / "views"
    if views.exists():
        resolved_pool = pool.resolve()
        resolved_views = views.resolve()
        if resolved_views.parent != resolved_pool or resolved_views.name != "views":
            raise SystemExit(f"refusing to reset unexpected views directory: {views}")
        shutil.rmtree(views)
    views.mkdir(parents=True)
    count = 0
    for asset in assets:
        canonical = pool / asset["canonicalPath"]
        ext = canonical.suffix
        display_name = f"{asset['id']}__{asset['sources'][0]['project']}{ext}"
        groups = {
            "by-setting": asset["tags"]["settings"],
            "by-activity": asset["tags"]["activities"],
            "by-style": asset["tags"]["visualFamilies"],
        }
        for group, values in groups.items():
            for value in values:
                target_dir = views / group / value
                target_dir.mkdir(parents=True, exist_ok=True)
                link = target_dir / display_name
                relative_target = os.path.relpath(canonical, target_dir)
                link.symlink_to(relative_target)
                count += 1
    return count


def count_values(rows: Iterable[dict], getter) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        for value in getter(row):
            counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def build_stats(
    projects: list[Path],
    assets: list[dict],
    scenes: list[dict],
    source_image_count: int,
    prompt_count: int,
    total_bytes: int,
) -> dict:
    return {
        "projectsScanned": len(projects),
        "storyboardScenes": len(scenes),
        "promptRecords": prompt_count,
        "sourceImages": source_image_count,
        "uniqueAssets": len(assets),
        "duplicateSourceFiles": source_image_count - len(assets),
        "sourceBytes": total_bytes,
        "assetsWithoutPrompt": sum(not asset.get("prompts") for asset in assets),
        "assetsWithoutStoryboardReference": sum(not asset.get("storyboardScenes") for asset in assets),
        "manuallyCuratedAssets": sum(bool(asset.get("curation", {}).get("manualOverride")) for asset in assets),
        "assetsByProject": count_values(assets, lambda row: [source["project"] for source in row["sources"]]),
        "assetsBySetting": count_values(assets, lambda row: row["tags"]["settings"]),
        "assetsByPrimarySetting": count_values(assets, lambda row: [row["primarySetting"]]),
        "assetsByActivity": count_values(assets, lambda row: row["tags"]["activities"]),
        "assetsByVisualFamily": count_values(assets, lambda row: row["tags"]["visualFamilies"]),
        "scenesBySetting": count_values(scenes, lambda row: row["tags"]["settings"]),
        "scenesByPrimarySetting": count_values(scenes, lambda row: [row["primarySetting"]]),
        "scenesByActivity": count_values(scenes, lambda row: row["tags"]["activities"]),
        "scenesByPrimaryActivity": count_values(scenes, lambda row: [row["primaryActivity"]]),
    }


def label_for(taxonomy: dict, dimension: str, value: str) -> str:
    item = taxonomy_lookup(taxonomy, dimension).get(value)
    return item.get("label", value) if item else value


def render_report(catalog: dict, inventory: dict, taxonomy: dict) -> str:
    stats = catalog["stats"]
    settings = taxonomy_values(taxonomy, "settings")
    observed = stats["scenesByPrimarySetting"]
    semantic_count = sum(item["id"] not in {"other-specialized-site", "unspecified-setting"} for item in settings)
    observed_semantic = sum(
        key not in {"other-specialized-site", "unspecified-setting"} and count > 0
        for key, count in observed.items()
    )
    setting_gaps = [
        (value, count)
        for value, count in stats["scenesBySetting"].items()
        if value not in {"other-specialized-site", "unspecified-setting"}
        and stats["assetsBySetting"].get(value, 0) == 0
    ]
    activity_gaps = [
        (value, count)
        for value, count in stats["scenesByActivity"].items()
        if value not in {"other-business-activity", "unspecified-activity"}
        and stats["assetsByActivity"].get(value, 0) == 0
    ]
    lines = [
        "# 视觉素材池覆盖报告",
        "",
        "## 总览",
        "",
        f"- 已扫描项目：{stats['projectsScanned']} 个",
        f"- 案例叙事分镜：{stats['storyboardScenes']} 个",
        f"- 图片提示词：{stats['promptRecords']} 条",
        f"- 现有源图片：{stats['sourceImages']} 张",
        f"- SHA-256 去重后素材：{stats['uniqueAssets']} 张",
        f"- 视觉场景词表：{len(settings)} 个值，其中 {semantic_count} 个业务语义类型，另有“其他专业场所”和“信息不足”两个边界类型",
        f"- 当前案例已命中的业务空间类型：{observed_semantic} 类",
        f"- 无提示词素材：{stats['assetsWithoutPrompt']} 张",
        f"- 未被当前分镜引用但可复用的素材：{stats['assetsWithoutStoryboardReference']} 张",
        f"- 人工纠偏标签素材：{stats['manuallyCuratedAssets']} 张",
        "",
        f"## {stats['storyboardScenes']} 个分镜的主场景分布",
        "",
        "| 场景 | 分镜数 |",
        "|---|---:|",
    ]
    for value, count in observed.items():
        lines.append(f"| {label_for(taxonomy, 'settings', value)} (`{value}`) | {count} |")
    lines.extend(
        [
            "",
            f"## {stats['uniqueAssets']} 张素材的主场景分布",
            "",
            "| 场景 | 素材数 |",
            "|---|---:|",
        ]
    )
    for value, count in stats["assetsByPrimarySetting"].items():
        lines.append(f"| {label_for(taxonomy, 'settings', value)} (`{value}`) | {count} |")
    lines.extend(
        [
            "",
            "## 视觉家族",
            "",
            "| 视觉家族 | 素材数 |",
            "|---|---:|",
        ]
    )
    for value, count in stats["assetsByVisualFamily"].items():
        lines.append(f"| {label_for(taxonomy, 'visualFamilies', value)} (`{value}`) | {count} |")
    lines.extend(
        [
            "",
            "## 当前文本需求对应的素材缺口",
            "",
            "缺口只表示当前案例分镜出现了该语义，而素材池尚无同标签图片；实际生产仍需结合画风、构图和人物关系判断是否生成。",
            "",
            "### 空间场景缺口",
            "",
            "| 场景 | 涉及分镜数 |",
            "|---|---:|",
        ]
    )
    if setting_gaps:
        for value, count in setting_gaps:
            lines.append(f"| {label_for(taxonomy, 'settings', value)} (`{value}`) | {count} |")
    else:
        lines.append("| 无 | 0 |")
    lines.extend(
        [
            "",
            "### 行为场景缺口",
            "",
            "| 行为 | 涉及分镜数 |",
            "|---|---:|",
        ]
    )
    if activity_gaps:
        for value, count in activity_gaps:
            lines.append(f"| {label_for(taxonomy, 'activities', value)} (`{value}`) | {count} |")
    else:
        lines.append("| 无 | 0 |")
    lines.extend(
        [
            "",
            "## 使用说明",
            "",
            "- `catalog.json` 是素材标签、来源、哈希和检索字段的机器源数据。",
            "- `tag_overrides.json` 保存少量人工复核后的标签增删改，不直接编辑生成的目录。",
            "- `scene_inventory.json` 是所有案例分镜的归类结果，用于分析场景覆盖和未来缺口。",
            "- `files/` 保存去重后的本地二进制素材；`views/` 提供按空间、行为和画风浏览的符号链接视图。",
            "- 新项目先生成项目本地新图，Remotion 仍只读取项目本地文件。",
            "- 只有明确复用、修订连续性或有意 callback/对照/证据放大时才检索并 checkout；新图通过 QA 后重新 build 入池。",
            "",
        ]
    )
    return "\n".join(lines)


def command_build(args: argparse.Namespace) -> int:
    root = Path(args.repo_root).resolve()
    pool = Path(args.pool_root).resolve()
    taxonomy = read_json(pool / "taxonomy.json")
    tag_overrides = load_tag_overrides(pool)
    projects = iter_projects(root)
    prompt_maps: dict[str, dict[str, dict]] = {}
    prompt_basename_maps: dict[str, dict[str, list[dict]]] = {}
    storyboard_refs: dict[str, dict[str, list[dict]]] = {}
    project_meta: dict[str, dict] = {}
    prompt_count = 0
    scene_count = 0
    for project in projects:
        by_path, by_basename, count = prompt_index(project)
        refs, _, meta, scenes = storyboard_context(project)
        prompt_maps[project.name] = by_path
        prompt_basename_maps[project.name] = by_basename
        storyboard_refs[project.name] = refs
        project_meta[project.name] = meta
        prompt_count += count
        scene_count += scenes

    grouped: dict[str, dict] = {}
    source_image_count = 0
    total_bytes = 0
    for project in projects:
        for path in iter_source_images(project):
            source_image_count += 1
            total_bytes += path.stat().st_size
            relative = normalize_relative(str(path.relative_to(project)))
            digest = sha256_file(path)
            width, height, image_format = image_metadata(path)
            prompt, prompt_match = attach_prompt(
                relative,
                prompt_maps[project.name],
                prompt_basename_maps[project.name],
            )
            scenes = storyboard_refs[project.name].get(relative, [])
            scene_text = "\n".join(
                "\n".join(flatten_text(scene)) for scene in scenes
            )
            prompt_text = prompt["prompt"] if prompt else ""
            meta = project_meta[project.name]
            # The prompt describes what is actually visible. Storyboard scenes
            # describe where the image was used and can include opener/closer or
            # reused-context language that must not overwrite image-content tags.
            classification_text = "\n".join(
                [prompt_text] if prompt_text else [scene_text]
            )
            explicit_functions = merge_unique(
                *[scene.get("storyFunctions", []) for scene in scenes]
            )
            tags = classify_text(
                classification_text,
                taxonomy,
                project.name,
                explicit_story_functions=explicit_functions,
                path_hint=f"{relative} {meta.get('visualStyle', '')}",
            )
            path_styles = match_dimension(relative, taxonomy, "visualFamilies")
            style_fallback = taxonomy["dimensions"]["visualFamilies"].get("fallback")
            if path_styles and path_styles != [style_fallback]:
                tags["visualFamilies"] = path_styles
            source = {
                "project": project.name,
                "path": f"output/{project.name}/{relative}",
                "relativePath": relative,
                "bytes": path.stat().st_size,
                "promptMatch": prompt_match,
            }
            if digest not in grouped:
                asset_id = f"va-{digest[:12]}"
                extension = path.suffix.casefold()
                canonical_relative = f"files/{digest[:2]}/{asset_id}{extension}"
                grouped[digest] = {
                    "id": asset_id,
                    "sha256": digest,
                    "canonicalPath": canonical_relative,
                    "width": width,
                    "height": height,
                    "format": image_format,
                    "bytes": path.stat().st_size,
                    "sources": [],
                    "prompts": [],
                    "storyboardScenes": [],
                    "tags": {key: [] for key in DIMENSION_KEYS},
                    "primarySetting": tags["settings"][0],
                    "primaryActivity": tags["activities"][0],
                }
                canonical = pool / canonical_relative
                canonical.parent.mkdir(parents=True, exist_ok=True)
                if not canonical.is_file() or sha256_file(canonical) != digest:
                    shutil.copy2(path, canonical)
            asset = grouped[digest]
            asset["sources"].append(source)
            if prompt:
                prompt_record = {
                    "project": project.name,
                    "declaredFile": prompt["file"],
                    "prompt": prompt["prompt"],
                    "stylePrefix": prompt["stylePrefix"],
                    "match": prompt_match,
                }
                if prompt_record not in asset["prompts"]:
                    asset["prompts"].append(prompt_record)
            for scene in scenes:
                if scene not in asset["storyboardScenes"]:
                    asset["storyboardScenes"].append(scene)
            for dimension in DIMENSION_KEYS:
                asset["tags"][dimension] = merge_unique(asset["tags"][dimension], tags[dimension])

    assets = sorted(grouped.values(), key=lambda item: item["id"])
    for asset in assets:
        asset["sources"].sort(key=lambda item: (item["project"], item["relativePath"]))
        asset["prompts"].sort(key=lambda item: (item["project"], item["declaredFile"]))
        asset["storyboardScenes"].sort(key=lambda item: (item["project"], item["position"]))
        for dimension in DIMENSION_KEYS:
            fallback = taxonomy["dimensions"][dimension].get("fallback")
            values = asset["tags"][dimension]
            if fallback in values and len(values) > 1:
                asset["tags"][dimension] = [value for value in values if value != fallback]
        if asset["tags"]["settings"]:
            asset["primarySetting"] = asset["tags"]["settings"][0]
        if asset["tags"]["activities"]:
            asset["primaryActivity"] = asset["tags"]["activities"][0]

    apply_tag_overrides(assets, taxonomy, tag_overrides)

    scenes = scene_inventory(projects, taxonomy, prompt_maps)
    if scene_count != len(scenes):
        raise SystemExit(f"scene inventory mismatch: counted={scene_count}, classified={len(scenes)}")
    stats = build_stats(
        projects,
        assets,
        scenes,
        source_image_count,
        prompt_count,
        total_bytes,
    )
    catalog = {
        "schemaVersion": 1,
        "taxonomyVersion": taxonomy.get("schemaVersion", 1),
        "poolRoot": "assets/visual-pool",
        "stats": stats,
        "assets": assets,
    }
    inventory = {
        "schemaVersion": 1,
        "taxonomyVersion": taxonomy.get("schemaVersion", 1),
        "stats": {
            "projects": len(projects),
            "scenes": len(scenes),
            "byPrimarySetting": stats["scenesByPrimarySetting"],
            "byPrimaryActivity": stats["scenesByPrimaryActivity"],
        },
        "scenes": scenes,
    }
    write_json(pool / "catalog.json", catalog)
    write_json(pool / "scene_inventory.json", inventory)
    view_count = 0 if args.no_views else create_views(pool, assets)
    report = render_report(catalog, inventory, taxonomy)
    report_path = pool / "coverage_report.md"
    if not report_path.is_file() or report_path.read_text(encoding="utf-8") != report:
        report_path.write_text(report, encoding="utf-8")
    print(
        "visual asset pool built: "
        f"projects={len(projects)} scenes={len(scenes)} prompts={prompt_count} "
        f"sourceImages={source_image_count} uniqueAssets={len(assets)} views={view_count}"
    )
    return 0


def load_catalog_and_taxonomy(pool_root: str) -> tuple[Path, dict, dict]:
    pool = Path(pool_root).resolve()
    taxonomy = read_json(pool / "taxonomy.json")
    catalog = read_json(pool / "catalog.json")
    return pool, catalog, taxonomy


def resolve_filter(taxonomy: dict, dimension: str, raw: str) -> str:
    needle = raw.casefold().strip()
    for item in taxonomy_values(taxonomy, dimension):
        choices = [item["id"], item.get("label", ""), *item.get("aliases", [])]
        if needle in {str(choice).casefold() for choice in choices}:
            return item["id"]
    raise SystemExit(f"unknown {dimension} tag: {raw}")


def query_score(asset: dict, query: str, taxonomy: dict) -> float:
    tokens = [token for token in query.casefold().split() if token]
    if not tokens:
        return 0.0
    tag_text_parts: list[str] = []
    for dimension, values in asset["tags"].items():
        lookup = taxonomy_lookup(taxonomy, dimension)
        for value in values:
            item = lookup.get(value, {})
            tag_text_parts.extend(
                [
                    value,
                    str(item.get("label", "")),
                    *item.get("aliases", []),
                    *item.get("keywords", []),
                ]
            )
    tag_text = " ".join(tag_text_parts).casefold()
    prompt_text = " ".join(prompt.get("prompt", "") for prompt in asset.get("prompts", [])).casefold()
    scene_text = " ".join(
        f"{scene.get('kicker', '')} {scene.get('headline', '')}"
        for scene in asset.get("storyboardScenes", [])
    ).casefold()
    source_text = " ".join(source.get("path", "") for source in asset.get("sources", [])).casefold()
    score = 0.0
    for token in tokens:
        if token in tag_text:
            score += 10
        if token in prompt_text:
            score += 5
        if token in scene_text:
            score += 3
        if token in source_text:
            score += 1
    return score


def command_search(args: argparse.Namespace) -> int:
    pool, catalog, taxonomy = load_catalog_and_taxonomy(args.pool_root)
    filters = {
        "settings": args.setting,
        "activities": args.activity,
        "participants": args.participant,
        "storyFunctions": args.story_function,
        "objects": args.object,
        "moods": args.mood,
        "industries": args.industry,
        "visualFamilies": args.style,
    }
    resolved = {
        dimension: [resolve_filter(taxonomy, dimension, value) for value in values]
        for dimension, values in filters.items()
        if values
    }
    query = " ".join(args.query or [])
    results: list[tuple[float, dict]] = []
    for asset in catalog.get("assets", []):
        if args.project and not any(source["project"] == args.project for source in asset["sources"]):
            continue
        if any(
            not all(value in asset["tags"].get(dimension, []) for value in values)
            for dimension, values in resolved.items()
        ):
            continue
        canonical = pool / asset["canonicalPath"]
        if args.available_only and not canonical.is_file():
            continue
        score = query_score(asset, query, taxonomy)
        if query and score <= 0:
            continue
        results.append((score, asset))
    results.sort(key=lambda item: (-item[0], item[1]["id"]))
    selected = results[: args.limit]
    if args.json:
        payload = []
        for score, asset in selected:
            payload.append(
                {
                    "score": score,
                    "id": asset["id"],
                    "canonicalPath": asset["canonicalPath"],
                    "available": (pool / asset["canonicalPath"]).is_file(),
                    "primarySetting": asset["primarySetting"],
                    "primaryActivity": asset["primaryActivity"],
                    "tags": asset["tags"],
                    "sources": asset["sources"],
                    "prompt": asset.get("prompts", [{}])[0].get("prompt", "") if asset.get("prompts") else "",
                }
            )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    print(f"matches={len(results)} showing={len(selected)}")
    for score, asset in selected:
        setting = label_for(taxonomy, "settings", asset["primarySetting"])
        activity = label_for(taxonomy, "activities", asset["primaryActivity"])
        styles = ", ".join(label_for(taxonomy, "visualFamilies", value) for value in asset["tags"]["visualFamilies"])
        source = asset["sources"][0]
        available = "local" if (pool / asset["canonicalPath"]).is_file() else "missing"
        print(
            f"{asset['id']} score={score:.1f} [{available}] {setting} / {activity} / {styles}\n"
            f"  source: {source['project']}:{source['relativePath']}\n"
            f"  pool: {asset['canonicalPath']}"
        )
    return 0


def command_checkout(args: argparse.Namespace) -> int:
    pool, catalog, _ = load_catalog_and_taxonomy(args.pool_root)
    by_id = {asset["id"]: asset for asset in catalog.get("assets", [])}
    if args.asset_id not in by_id:
        raise SystemExit(f"unknown asset id: {args.asset_id}")
    asset = by_id[args.asset_id]
    source = pool / asset["canonicalPath"]
    if not source.is_file():
        raise SystemExit(f"pool binary missing: {source}; run visual-assets build")
    project = Path(args.project)
    if not project.is_absolute():
        project = (ROOT / project).resolve()
    if not project.is_dir():
        raise SystemExit(f"project directory not found: {project}")
    destination_dir = project / normalize_relative(args.destination)
    destination_dir.mkdir(parents=True, exist_ok=True)
    filename = args.name or source.name
    if Path(filename).name != filename:
        raise SystemExit("--name must be a filename, not a path")
    destination = destination_dir / filename
    if destination.exists():
        if sha256_file(destination) != asset["sha256"] and not args.force:
            raise SystemExit(f"destination exists with different content: {destination}; use --force")
    if not destination.exists() or sha256_file(destination) != asset["sha256"]:
        shutil.copy2(source, destination)
    project_relative = normalize_relative(str(destination.relative_to(project)))
    manifest_path = project / "asset_pool_usage.json"
    manifest = read_json(manifest_path, {"schemaVersion": 1, "assets": []})
    records = [record for record in manifest.get("assets", []) if record.get("src") != project_relative]
    records.append(
        {
            "assetId": asset["id"],
            "src": project_relative,
            "sha256": asset["sha256"],
            "poolPath": asset["canonicalPath"],
            "sourceProjects": sorted({source_record["project"] for source_record in asset["sources"]}),
            "tags": asset["tags"],
        }
    )
    manifest["assets"] = sorted(records, key=lambda record: record["src"])
    write_json(manifest_path, manifest)
    print(f"checked out {asset['id']} -> {project_relative}")
    print(
        json.dumps(
            {
                "id": asset["id"],
                "type": "image",
                "src": project_relative,
                "role": "context",
                "origin": "curated",
                "poolAssetId": asset["id"],
            },
            ensure_ascii=False,
        )
    )
    return 0


def command_stats(args: argparse.Namespace) -> int:
    _, catalog, taxonomy = load_catalog_and_taxonomy(args.pool_root)
    if args.json:
        print(json.dumps(catalog["stats"], ensure_ascii=False, indent=2))
        return 0
    stats = catalog["stats"]
    print(
        f"projects={stats['projectsScanned']} scenes={stats['storyboardScenes']} "
        f"prompts={stats['promptRecords']} sourceImages={stats['sourceImages']} "
        f"uniqueAssets={stats['uniqueAssets']} duplicates={stats['duplicateSourceFiles']}"
    )
    for value, count in stats["assetsByPrimarySetting"].items():
        print(f"{value}\t{label_for(taxonomy, 'settings', value)}\t{count}")
    return 0


def command_audit(args: argparse.Namespace) -> int:
    pool, catalog, taxonomy = load_catalog_and_taxonomy(args.pool_root)
    errors: list[str] = []
    ids: set[str] = set()
    hashes: set[str] = set()
    valid = {dimension: taxonomy_lookup(taxonomy, dimension) for dimension in DIMENSION_KEYS}
    overrides = load_tag_overrides(pool)
    errors.extend(tag_override_errors(overrides, taxonomy, {asset["id"] for asset in catalog.get("assets", [])}))
    for asset in catalog.get("assets", []):
        if asset["id"] in ids:
            errors.append(f"duplicate asset id: {asset['id']}")
        ids.add(asset["id"])
        if asset["sha256"] in hashes:
            errors.append(f"duplicate catalog hash: {asset['sha256']}")
        hashes.add(asset["sha256"])
        canonical = pool / asset["canonicalPath"]
        if not canonical.is_file():
            errors.append(f"missing binary: {asset['canonicalPath']}")
        elif sha256_file(canonical) != asset["sha256"]:
            errors.append(f"hash mismatch: {asset['canonicalPath']}")
        for dimension in DIMENSION_KEYS:
            for value in asset["tags"].get(dimension, []):
                if value not in valid[dimension]:
                    errors.append(f"{asset['id']} unknown {dimension} tag: {value}")
        if asset.get("primarySetting") not in asset["tags"].get("settings", []):
            errors.append(f"{asset['id']} primarySetting is not in tags")
        if asset.get("primaryActivity") not in asset["tags"].get("activities", []):
            errors.append(f"{asset['id']} primaryActivity is not in tags")
    expected_assets = copy.deepcopy(catalog.get("assets", []))
    if not errors:
        apply_tag_overrides(expected_assets, taxonomy, overrides)
        expected_by_id = {asset["id"]: asset for asset in expected_assets}
        override_ids = set(overrides.get("assets", {}))
        for asset in catalog.get("assets", []):
            expected = expected_by_id[asset["id"]]
            for field in ("tags", "primarySetting", "primaryActivity", "curation"):
                if asset.get(field) != expected.get(field):
                    errors.append(f"{asset['id']} catalog is stale for tag overrides; run visual-assets build")
                    break
            if asset.get("curation", {}).get("manualOverride") and asset["id"] not in override_ids:
                errors.append(f"{asset['id']} has stale manual curation metadata; run visual-assets build")
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(
        f"visual asset pool audit passed: assets={len(ids)} "
        f"missingPrompt={catalog['stats']['assetsWithoutPrompt']} "
        f"unreferenced={catalog['stats']['assetsWithoutStoryboardReference']}"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build and query the shared case-video visual asset pool")
    parser.set_defaults(pool_root=str(DEFAULT_POOL))
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build", help="scan projects, deduplicate images, tag them, and rebuild catalog")
    build.add_argument("--repo-root", default=str(ROOT))
    build.add_argument("--pool-root", default=str(DEFAULT_POOL))
    build.add_argument("--no-views", action="store_true")
    build.set_defaults(func=command_build)

    search = subparsers.add_parser("search", help="search reusable images by semantic tags and text")
    search.add_argument("query", nargs="*")
    search.add_argument("--pool-root", default=str(DEFAULT_POOL))
    search.add_argument("--setting", action="append", default=[])
    search.add_argument("--activity", action="append", default=[])
    search.add_argument("--participant", action="append", default=[])
    search.add_argument("--story-function", action="append", default=[])
    search.add_argument("--object", action="append", default=[])
    search.add_argument("--mood", action="append", default=[])
    search.add_argument("--industry", action="append", default=[])
    search.add_argument("--style", action="append", default=[])
    search.add_argument("--project")
    search.add_argument("--limit", type=int, default=20)
    search.add_argument("--json", action="store_true")
    search.add_argument("--available-only", action="store_true", default=True)
    search.set_defaults(func=command_search)

    checkout = subparsers.add_parser("checkout", help="copy one pool asset into a project and record provenance")
    checkout.add_argument("asset_id")
    checkout.add_argument("project")
    checkout.add_argument("--pool-root", default=str(DEFAULT_POOL))
    checkout.add_argument("--destination", default="images/pool")
    checkout.add_argument("--name")
    checkout.add_argument("--force", action="store_true")
    checkout.set_defaults(func=command_checkout)

    stats = subparsers.add_parser("stats", help="show pool and scene coverage statistics")
    stats.add_argument("--pool-root", default=str(DEFAULT_POOL))
    stats.add_argument("--json", action="store_true")
    stats.set_defaults(func=command_stats)

    audit = subparsers.add_parser("audit", help="verify catalog tags, binaries, hashes, and primary classifications")
    audit.add_argument("--pool-root", default=str(DEFAULT_POOL))
    audit.set_defaults(func=command_audit)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
