from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "scripts" / "build_storyboard_from_plan.py"
VALIDATOR = ROOT / "scripts" / "validate_case_project.py"


def write_test_image(path: Path, *, size: tuple[int, int] = (640, 360)) -> None:
    image = Image.new("RGB", size, (34, 94, 168))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, size[0], size[1]), fill=(34, 94, 168))
    draw.polygon(
        [(0, size[1]), (size[0] * 0.55, size[1] * 0.18), (size[0], size[1])],
        fill=(241, 190, 73),
    )
    draw.rectangle(
        (round(size[0] * 0.1), round(size[1] * 0.18), round(size[0] * 0.42), round(size[1] * 0.78)),
        outline=(248, 242, 223),
        width=max(2, size[0] // 160),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def write_contact_sheet_image(path: Path) -> None:
    image = Image.new("RGB", (1200, 1000), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    tile_width = 240
    tile_height = 145
    gap_x = 36
    gap_y = 52
    start_x = 42
    start_y = 42
    for row in range(4):
        for column in range(4):
            x = start_x + column * (tile_width + gap_x)
            y = start_y + row * (tile_height + gap_y)
            fill = (
                35 + row * 22,
                90 + column * 18,
                150 + ((row + column) % 3) * 20,
            )
            draw.rectangle((x, y, x + tile_width, y + tile_height), fill=fill)
            draw.rectangle(
                (x + 16, y + 18, x + tile_width - 20, y + tile_height - 22),
                outline=(246, 246, 246),
                width=4,
            )
            draw.rectangle(
                (x + 18, y + tile_height + 10, x + tile_width - 18, y + tile_height + 22),
                fill=(228, 228, 228),
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def write_white_character_portrait(path: Path) -> None:
    image = Image.new("RGB", (1024, 1024), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.ellipse((430, 145, 594, 310), fill=(18, 24, 32))
    draw.polygon(
        [(286, 375), (738, 375), (846, 995), (178, 995)],
        fill=(19, 45, 82),
    )
    draw.polygon(
        [(438, 384), (586, 384), (548, 590), (476, 590)],
        fill=(51, 104, 170),
    )
    draw.polygon([(498, 565), (526, 565), (554, 995), (466, 995)], fill=(16, 28, 47))
    draw.line((710, 375, 845, 995), fill=(220, 112, 35), width=18)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


class VisualBeatProjectTests(unittest.TestCase):
    def make_project(self, root: Path, *, with_visual_beats: bool) -> Path:
        project = root / "case"
        (project / "audio").mkdir(parents=True)
        (project / "images").mkdir()
        (project / "audio" / "narration_azure.wav").write_bytes(b"RIFF-test")
        write_test_image(project / "images" / "scene.png")
        (project / "title.txt").write_text("测试\n", encoding="utf-8")
        (project / "narration.txt").write_text("第一句。第二句。第三句。\n", encoding="utf-8")
        timeline = {
            "duration": 3.0,
            "units": [
                {"index": 1, "paragraph": 1, "text": "第一句。", "start": 0.0, "end": 1.0},
                {"index": 2, "paragraph": 1, "text": "第二句。", "start": 1.0, "end": 2.0},
                {"index": 3, "paragraph": 1, "text": "第三句。", "start": 2.0, "end": 3.0},
            ],
        }
        (project / "narration.timeline.json").write_text(
            json.dumps(timeline, ensure_ascii=False), encoding="utf-8"
        )
        (project / "image_prompts.json").write_text(
            json.dumps({"prompts": [{"file": "images/scene.png", "prompt": "abstract"}]}),
            encoding="utf-8",
        )
        scene = {
            "paragraph": 1,
            "kicker": "测试",
            "layout": "closing-quote",
            "headline": "测试场景",
            "background": "images/scene.png",
        }
        plan = {
            "project": {
                "slug": "visual-beat-test",
                "title": "测试",
                "subtitle": "测试",
                "brand": "销售不复杂",
                "projectType": "sales",
                "visualStyle": "sales-watercolor",
                "subtitleLabel": "销售不复杂",
            },
            "scenes": [scene],
        }
        if with_visual_beats:
            plan["visualAssets"] = [
                {
                    "id": "scene-image",
                    "type": "image",
                    "src": "images/scene.png",
                    "role": "context",
                    "origin": "generated",
                }
            ]
            scene["visualMode"] = "editorial"
            scene["visualBeats"] = [
                {
                    "id": "establish",
                    "offset": 0,
                    "purpose": "establish",
                    "composition": "full-bleed",
                    "baseAsset": "scene-image",
                    "layers": [],
                },
                {
                    "id": "evidence",
                    "offset": 1,
                    "purpose": "evidence",
                    "composition": "split",
                    "baseAsset": "scene-image",
                    "layers": [
                        {
                            "kind": "text",
                            "slot": "left",
                            "label": "测试指标",
                            "text": "82天",
                            "variant": "metric",
                            "revealOffset": 1,
                            "exitOffset": 2,
                        }
                    ],
                },
                {
                    "id": "consequence",
                    "offset": 2,
                    "purpose": "consequence",
                    "composition": "document-focus",
                    "baseAsset": "scene-image",
                    "layers": [],
                },
            ]
        (project / "storyboard_plan.json").write_text(
            json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return project

    def run_builder(self, project: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(BUILDER), str(project)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def run_validator(
        self, project: Path, *, strict_visuals: bool = False
    ) -> subprocess.CompletedProcess[str]:
        command = [sys.executable, str(VALIDATOR)]
        if strict_visuals:
            command.append("--strict-visuals")
        command.append(str(project))
        return subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_legacy_plan_builds_and_validates_without_visual_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.make_project(Path(directory), with_visual_beats=False)
            built = self.run_builder(project)
            self.assertEqual(built.returncode, 0, built.stderr)
            storyboard = json.loads((project / "rich_storyboard.json").read_text())
            self.assertNotIn("visualAssets", storyboard)
            self.assertNotIn("visualBeats", storyboard["scenes"][0])
            self.assertEqual(
                storyboard["cover"],
                {
                    "title": "测试",
                    "subtitle": "测试",
                    "kicker": "销售不复杂",
                    "throughUnit": 1,
                },
            )
            validated = self.run_validator(project)
            self.assertEqual(validated.returncode, 0, validated.stderr)
            self.assertIn("visualBeats=0", validated.stdout)

    def test_title_file_overrides_stale_plan_title_and_preserves_cover_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.make_project(Path(directory), with_visual_beats=False)
            (project / "title.txt").write_text(
                "客户为什么连续三次说贵\n", encoding="utf-8"
            )
            plan_path = project / "storyboard_plan.json"
            plan = json.loads(plan_path.read_text())
            plan["project"]["cover"] = {
                "title": "分镜阶段留下的旧标题",
                "subtitle": "",
                "throughUnit": 2,
            }
            plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
            built = self.run_builder(project)
            self.assertEqual(built.returncode, 0, built.stderr)
            storyboard = json.loads((project / "rich_storyboard.json").read_text())
            self.assertEqual(storyboard["title"], "客户为什么连续三次说贵")
            self.assertEqual(storyboard["cover"]["title"], "客户为什么连续三次说贵")
            self.assertEqual(storyboard["cover"]["subtitle"], "")
            self.assertEqual(storyboard["cover"]["kicker"], "销售不复杂")
            self.assertEqual(storyboard["cover"]["throughUnit"], 2)
            validated = self.run_validator(project)
            self.assertEqual(validated.returncode, 0, validated.stderr)

    def test_builder_rejects_multiline_title(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.make_project(Path(directory), with_visual_beats=False)
            (project / "title.txt").write_text("第一行\n第二行\n", encoding="utf-8")

            built = self.run_builder(project)

            self.assertNotEqual(built.returncode, 0)
            self.assertIn("exactly one non-empty logical line", built.stderr)

    def test_validator_rejects_title_cover_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.make_project(Path(directory), with_visual_beats=False)
            self.assertEqual(self.run_builder(project).returncode, 0)
            path = project / "rich_storyboard.json"
            storyboard = json.loads(path.read_text())
            storyboard["cover"]["title"] = "分镜里被改写的标题"
            path.write_text(json.dumps(storyboard), encoding="utf-8")

            validated = self.run_validator(project)

            self.assertNotEqual(validated.returncode, 0)
            self.assertIn("must exactly match the canonical title in title.txt", validated.stderr)

    def test_legacy_project_without_title_builds_with_warning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.make_project(Path(directory), with_visual_beats=False)
            (project / "title.txt").unlink()

            built = self.run_builder(project)

            self.assertEqual(built.returncode, 0, built.stderr)
            self.assertIn("title.txt is missing", built.stderr)
            storyboard = json.loads((project / "rich_storyboard.json").read_text())
            self.assertEqual(storyboard["cover"]["title"], "测试")
            validated = self.run_validator(project)
            self.assertEqual(validated.returncode, 0, validated.stderr)
            self.assertIn("title.txt is missing", validated.stdout)

    def test_visual_offsets_build_to_units_and_validate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.make_project(Path(directory), with_visual_beats=True)
            built = self.run_builder(project)
            self.assertEqual(built.returncode, 0, built.stderr)
            storyboard = json.loads((project / "rich_storyboard.json").read_text())
            beats = storyboard["scenes"][0]["visualBeats"]
            self.assertEqual([beat["atUnit"] for beat in beats], [1, 2, 3])
            layer = beats[1]["layers"][0]
            self.assertEqual(layer["revealAtUnit"], 2)
            self.assertEqual(layer["exitAtUnit"], 3)
            self.assertNotIn("revealOffset", layer)
            validated = self.run_validator(project)
            self.assertEqual(validated.returncode, 0, validated.stderr)
            self.assertIn("visualAssets=1", validated.stdout)
            self.assertIn("visualBeats=3", validated.stdout)

    def test_validator_rejects_unknown_asset_reference(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.make_project(Path(directory), with_visual_beats=True)
            self.assertEqual(self.run_builder(project).returncode, 0)
            path = project / "rich_storyboard.json"
            storyboard = json.loads(path.read_text())
            storyboard["scenes"][0]["visualBeats"][0]["baseAsset"] = "missing"
            path.write_text(json.dumps(storyboard), encoding="utf-8")
            validated = self.run_validator(project)
            self.assertNotEqual(validated.returncode, 0)
            self.assertIn("unknown baseAsset", validated.stderr)

    def test_validator_rejects_contact_sheet_visual_asset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.make_project(Path(directory), with_visual_beats=True)
            self.assertEqual(self.run_builder(project).returncode, 0)
            bad_image = project / "images" / "generated" / "person_bad.png"
            write_contact_sheet_image(bad_image)
            (project / "image_prompts.json").write_text(
                json.dumps(
                    {
                        "prompts": [
                            {"file": "images/scene.png", "prompt": "abstract"},
                            {"file": "images/generated/person_bad.png", "prompt": "portrait"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            storyboard_path = project / "rich_storyboard.json"
            storyboard = json.loads(storyboard_path.read_text())
            storyboard["visualAssets"][0]["src"] = "images/generated/person_bad.png"
            storyboard_path.write_text(json.dumps(storyboard), encoding="utf-8")
            validated = self.run_validator(project)
            self.assertNotEqual(validated.returncode, 0)
            self.assertIn("contact sheet/overview", validated.stderr)

    def test_validator_allows_white_character_portrait_asset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.make_project(Path(directory), with_visual_beats=True)
            self.assertEqual(self.run_builder(project).returncode, 0)
            portrait = project / "images" / "characters" / "person.png"
            write_white_character_portrait(portrait)
            (project / "image_prompts.json").write_text(
                json.dumps(
                    {
                        "prompts": [
                            {"file": "images/scene.png", "prompt": "abstract"},
                            {"file": "images/characters/person.png", "prompt": "portrait"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            storyboard_path = project / "rich_storyboard.json"
            storyboard = json.loads(storyboard_path.read_text())
            storyboard["visualAssets"][0]["src"] = "images/characters/person.png"
            storyboard_path.write_text(json.dumps(storyboard), encoding="utf-8")
            validated = self.run_validator(project)
            self.assertEqual(validated.returncode, 0, validated.stderr)

    def test_validator_rejects_overview_image_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.make_project(Path(directory), with_visual_beats=True)
            self.assertEqual(self.run_builder(project).returncode, 0)
            overview = project / "images" / "generated" / "overview.png"
            write_test_image(overview)
            (project / "image_prompts.json").write_text(
                json.dumps(
                    {
                        "prompts": [
                            {"file": "images/scene.png", "prompt": "abstract"},
                            {"file": "images/generated/overview.png", "prompt": "overview"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            storyboard_path = project / "rich_storyboard.json"
            storyboard = json.loads(storyboard_path.read_text())
            storyboard["visualAssets"][0]["src"] = "images/generated/overview.png"
            storyboard_path.write_text(json.dumps(storyboard), encoding="utf-8")
            validated = self.run_validator(project)
            self.assertNotEqual(validated.returncode, 0)
            self.assertIn("forbidden final image path", validated.stderr)

    def test_validator_rejects_late_first_beat_and_second_timing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.make_project(Path(directory), with_visual_beats=True)
            self.assertEqual(self.run_builder(project).returncode, 0)
            path = project / "rich_storyboard.json"
            storyboard = json.loads(path.read_text())
            storyboard["scenes"][0]["visualBeats"][0]["atUnit"] = 2
            path.write_text(json.dumps(storyboard), encoding="utf-8")
            validated = self.run_validator(project)
            self.assertNotEqual(validated.returncode, 0)
            self.assertIn("must begin a visual beat at unit 1", validated.stderr)

            storyboard["scenes"][0]["visualBeats"][0]["atUnit"] = 1
            storyboard["scenes"][0]["visualBeats"][0]["startSeconds"] = 0.5
            path.write_text(json.dumps(storyboard), encoding="utf-8")
            validated = self.run_validator(project)
            self.assertNotEqual(validated.returncode, 0)
            self.assertIn("second-based timing", validated.stderr)

    def test_pool_asset_provenance_replaces_generation_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.make_project(Path(directory), with_visual_beats=True)
            self.assertEqual(self.run_builder(project).returncode, 0)
            image_path = project / "images" / "scene.png"
            digest = hashlib.sha256(image_path.read_bytes()).hexdigest()
            (project / "image_prompts.json").write_text(
                json.dumps({"prompts": []}), encoding="utf-8"
            )
            (project / "asset_pool_usage.json").write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "assets": [
                            {
                                "assetId": "va-test12345678",
                                "src": "images/scene.png",
                                "sha256": digest,
                                "poolPath": "files/aa/va-test12345678.png",
                                "sourceProjects": ["source_case"],
                                "tags": {},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            storyboard_path = project / "rich_storyboard.json"
            storyboard = json.loads(storyboard_path.read_text())
            storyboard["visualAssets"][0]["origin"] = "curated"
            storyboard["visualAssets"][0]["poolAssetId"] = "va-test12345678"
            storyboard_path.write_text(json.dumps(storyboard), encoding="utf-8")
            validated = self.run_validator(project)
            self.assertEqual(validated.returncode, 0, validated.stderr)
            self.assertIn("poolAssets=1", validated.stdout)

    def install_story_layer_beat(self, project: Path, layers: list[dict]) -> Path:
        """Build the project then replace beat layers in rich_storyboard.json."""
        self.assertEqual(self.run_builder(project).returncode, 0)
        path = project / "rich_storyboard.json"
        storyboard = json.loads(path.read_text())
        storyboard["scenes"][0]["visualBeats"][1]["layers"] = layers
        path.write_text(json.dumps(storyboard, ensure_ascii=False), encoding="utf-8")
        return path

    def test_story_layers_build_and_validate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.make_project(Path(directory), with_visual_beats=True)
            plan_path = project / "storyboard_plan.json"
            plan = json.loads(plan_path.read_text())
            plan["scenes"][0]["visualBeats"][1]["layers"] = [
                {
                    "kind": "counter",
                    "slot": "left",
                    "label": "库存周转",
                    "value": {"from": 44, "to": 68, "suffix": "%"},
                    "deltaTone": "good",
                },
                {
                    "kind": "bar-compare",
                    "slot": "left",
                    "bars": [
                        {"label": "试点前", "value": 44, "suffix": "%", "tone": "bad"},
                        {"label": "试点后", "value": 68, "suffix": "%", "tone": "good", "revealOffset": 2},
                    ],
                },
                {
                    "kind": "network",
                    "slot": "center",
                    "networkLayout": "row",
                    "nodes": [
                        {"id": "a", "label": "赵海", "sub": "库存·数据"},
                        {"id": "b", "label": "总部", "sub": "政策·费用", "revealOffset": 2},
                    ],
                    "links": [{"from": "a", "to": "b", "label": "退货请求"}],
                },
                {
                    "kind": "dialogue",
                    "slot": "bottom",
                    "speaker": "赵海",
                    "text": "这次你们愿意跟我一起承担库存。",
                    "tail": "right",
                },
                {
                    "kind": "annotate",
                    "shape": "underline",
                    "region": {"x": 0.6, "y": 0.3, "w": 0.2, "h": 0.25},
                    "text": "大包装挤压小店",
                },
            ]
            plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
            built = self.run_builder(project)
            self.assertEqual(built.returncode, 0, built.stderr)
            storyboard = json.loads((project / "rich_storyboard.json").read_text())
            layers = storyboard["scenes"][0]["visualBeats"][1]["layers"]
            self.assertEqual(layers[1]["bars"][1]["revealAtUnit"], 3)
            self.assertNotIn("revealOffset", layers[1]["bars"][1])
            self.assertEqual(layers[2]["networkLayout"], "row")
            self.assertEqual(layers[2]["nodes"][1]["revealAtUnit"], 3)
            validated = self.run_validator(project)
            self.assertEqual(validated.returncode, 0, validated.stderr)

    def test_disabled_ring_annotation_warns_and_validates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.make_project(Path(directory), with_visual_beats=True)
            self.install_story_layer_beat(
                project,
                [
                    {
                        "kind": "annotate",
                        "shape": "ring",
                        "region": {"x": 0.6, "y": 0.3, "w": 0.2, "h": 0.25},
                    }
                ],
            )
            validated = self.run_validator(project)
            self.assertEqual(validated.returncode, 0, validated.stderr)
            self.assertIn("disabled annotate shape 'ring'", validated.stdout)
            self.assertIn("Remotion skips it", validated.stdout)

    def test_nested_bar_reveal_counts_as_internal_motion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.make_project(Path(directory), with_visual_beats=True)
            self.assertEqual(self.run_builder(project).returncode, 0)

            timeline_path = project / "narration.timeline.json"
            timeline = json.loads(timeline_path.read_text())
            for position, unit in enumerate(timeline["units"]):
                unit["start"] = position * 5.0
                unit["end"] = (position + 1) * 5.0
            timeline["duration"] = 15.0
            timeline_path.write_text(json.dumps(timeline), encoding="utf-8")

            storyboard_path = project / "rich_storyboard.json"
            storyboard = json.loads(storyboard_path.read_text())
            beats = storyboard["scenes"][0]["visualBeats"]
            beats[0]["layers"] = [
                {
                    "kind": "bar-compare",
                    "bars": [
                        {"label": "之前", "value": 0, "revealAtUnit": 1},
                        {"label": "之后", "value": 11, "revealAtUnit": 2},
                    ],
                }
            ]
            storyboard["scenes"][0]["visualBeats"] = [beats[0], beats[2]]
            storyboard_path.write_text(json.dumps(storyboard), encoding="utf-8")

            validated = self.run_validator(project)
            self.assertEqual(validated.returncode, 0, validated.stderr)
            self.assertNotIn("with no internal layer reveal", validated.stdout)

    def test_disabled_box_annotation_warns_and_validates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.make_project(Path(directory), with_visual_beats=True)
            self.install_story_layer_beat(
                project,
                [{"kind": "annotate", "shape": "box"}],
            )
            validated = self.run_validator(project)
            self.assertEqual(validated.returncode, 0, validated.stderr)
            self.assertIn("disabled annotate shape 'box'", validated.stdout)
            self.assertIn("Remotion skips it", validated.stdout)

    def test_disabled_box_does_not_count_as_semantic_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.make_project(Path(directory), with_visual_beats=True)
            self.install_story_layer_beat(
                project,
                [{"kind": "annotate", "shape": "box", "revealAtUnit": 3}],
            )
            validated = self.run_validator(project, strict_visuals=True)
            self.assertNotEqual(validated.returncode, 0)
            self.assertIn("introduces no semantic change", validated.stderr)

    def test_implicit_box_annotation_warns_and_validates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.make_project(Path(directory), with_visual_beats=True)
            self.install_story_layer_beat(
                project,
                [{"kind": "annotate"}],
            )
            validated = self.run_validator(project)
            self.assertEqual(validated.returncode, 0, validated.stderr)
            self.assertIn("old implicit 'box' default is disabled", validated.stdout)
            self.assertIn("Remotion skips it", validated.stdout)

    def test_validator_rejects_counter_without_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.make_project(Path(directory), with_visual_beats=True)
            self.install_story_layer_beat(
                project, [{"kind": "counter", "slot": "left", "label": "库存"}]
            )
            validated = self.run_validator(project)
            self.assertNotEqual(validated.returncode, 0)
            self.assertIn("counter layer must define value.to", validated.stderr)

    def test_validator_rejects_network_with_unknown_link_endpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.make_project(Path(directory), with_visual_beats=True)
            self.install_story_layer_beat(
                project,
                [
                    {
                        "kind": "network",
                        "nodes": [
                            {"id": "a", "label": "赵海"},
                            {"id": "b", "label": "总部"},
                        ],
                        "links": [{"from": "a", "to": "missing"}],
                    }
                ],
            )
            validated = self.run_validator(project)
            self.assertNotEqual(validated.returncode, 0)
            self.assertIn("must reference declared node ids", validated.stderr)

    def test_validator_rejects_invalid_network_layout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.make_project(Path(directory), with_visual_beats=True)
            self.install_story_layer_beat(
                project,
                [
                    {
                        "kind": "network",
                        "networkLayout": "orbit",
                        "nodes": [
                            {"id": "a", "label": "教务主任"},
                            {"id": "b", "label": "校长"},
                        ],
                        "links": [{"from": "a", "to": "b"}],
                    }
                ],
            )
            validated = self.run_validator(project)
            self.assertNotEqual(validated.returncode, 0)
            self.assertIn("invalid networkLayout", validated.stderr)

    def test_validator_rejects_triangle_layout_without_three_nodes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.make_project(Path(directory), with_visual_beats=True)
            self.install_story_layer_beat(
                project,
                [
                    {
                        "kind": "network",
                        "networkLayout": "triangle",
                        "nodes": [
                            {"id": "a", "label": "家委会"},
                            {"id": "b", "label": "教务主任"},
                        ],
                        "links": [{"from": "a", "to": "b"}],
                    }
                ],
            )
            validated = self.run_validator(project)
            self.assertNotEqual(validated.returncode, 0)
            self.assertIn("requires exactly 3 nodes", validated.stderr)

    def test_validator_rejects_dialogue_without_speaker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.make_project(Path(directory), with_visual_beats=True)
            self.install_story_layer_beat(
                project, [{"kind": "dialogue", "text": "库存谁来承担？"}]
            )
            validated = self.run_validator(project)
            self.assertNotEqual(validated.returncode, 0)
            self.assertIn("dialogue layer must define speaker", validated.stderr)

    def test_validator_rejects_annotate_region_out_of_bounds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.make_project(Path(directory), with_visual_beats=True)
            self.install_story_layer_beat(
                project,
                [
                    {
                        "kind": "annotate",
                        "shape": "underline",
                        "region": {"x": 0.5, "y": 0.5, "w": 1.4, "h": 0.2},
                    }
                ],
            )
            validated = self.run_validator(project)
            self.assertNotEqual(validated.returncode, 0)
            self.assertIn("region.w must be a number between 0 and 1", validated.stderr)

    def test_validator_rejects_annotate_region_crossing_canvas_edge(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.make_project(Path(directory), with_visual_beats=True)
            self.install_story_layer_beat(
                project,
                [
                    {
                        "kind": "annotate",
                        "shape": "underline",
                        "region": {"x": 0.7, "y": 0.2, "w": 0.4, "h": 0.2},
                    }
                ],
            )
            validated = self.run_validator(project)
            self.assertNotEqual(validated.returncode, 0)
            self.assertIn("exceeds the right canvas edge", validated.stderr)

    def test_strict_validator_rejects_repeated_callback_without_semantic_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.make_project(Path(directory), with_visual_beats=True)
            self.assertEqual(self.run_builder(project).returncode, 0)
            path = project / "rich_storyboard.json"
            storyboard = json.loads(path.read_text())
            beats = storyboard["scenes"][0]["visualBeats"]
            for position, beat in enumerate(beats):
                beat["layers"] = []
                beat["purpose"] = "establish" if position == 0 else "callback"
            path.write_text(json.dumps(storyboard, ensure_ascii=False), encoding="utf-8")

            validated = self.run_validator(project, strict_visuals=True)
            self.assertNotEqual(validated.returncode, 0)
            self.assertIn("introduces no semantic change", validated.stderr)
            self.assertIn("callbacks must be occasional", validated.stderr)

    def test_strict_validator_rejects_presentation_only_beat_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.make_project(Path(directory), with_visual_beats=True)
            self.assertEqual(self.run_builder(project).returncode, 0)
            path = project / "rich_storyboard.json"
            storyboard = json.loads(path.read_text())
            beats = storyboard["scenes"][0]["visualBeats"]
            presentations = [
                ("full-bleed", "static", "natural", "cut"),
                ("split", "push-in", "crisis", "dissolve"),
                ("triptych", "pan-left", "blueprint", "push"),
            ]
            for beat, (composition, camera, treatment, transition) in zip(
                beats, presentations
            ):
                beat["layers"] = []
                beat["composition"] = composition
                beat["camera"] = camera
                beat["treatment"] = treatment
                beat["transition"] = transition
            path.write_text(json.dumps(storyboard, ensure_ascii=False), encoding="utf-8")

            validated = self.run_validator(project, strict_visuals=True)
            self.assertNotEqual(validated.returncode, 0)
            self.assertIn("introduces no semantic change", validated.stderr)

    def test_strict_validator_rejects_hybrid_semantic_panels(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.make_project(Path(directory), with_visual_beats=True)
            self.assertEqual(self.run_builder(project).returncode, 0)
            path = project / "rich_storyboard.json"
            storyboard = json.loads(path.read_text())
            storyboard["scenes"][0]["visualMode"] = "hybrid"
            path.write_text(json.dumps(storyboard, ensure_ascii=False), encoding="utf-8")

            validated = self.run_validator(project, strict_visuals=True)
            self.assertNotEqual(validated.returncode, 0)
            self.assertIn("hybrid mode contains semantic Visual Beat layers", validated.stderr)

    def test_strict_validator_rejects_overlapping_panel_slots(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.make_project(Path(directory), with_visual_beats=True)
            self.install_story_layer_beat(
                project,
                [
                    {
                        "kind": "counter",
                        "slot": "left",
                        "value": {"to": 82, "suffix": "%"},
                    },
                    {
                        "kind": "bar-compare",
                        "slot": "left",
                        "bars": [{"label": "完成率", "value": 82}],
                    },
                ],
            )
            validated = self.run_validator(project, strict_visuals=True)
            self.assertNotEqual(validated.returncode, 0)
            self.assertIn("overlaps", validated.stderr)
            self.assertIn("slot 'left'", validated.stderr)

    def test_strict_validator_rejects_long_semantic_visual_gap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.make_project(Path(directory), with_visual_beats=True)
            self.assertEqual(self.run_builder(project).returncode, 0)
            timeline_path = project / "narration.timeline.json"
            timeline = json.loads(timeline_path.read_text())
            timeline["duration"] = 30.0
            for position, unit in enumerate(timeline["units"]):
                unit["start"] = position * 10.0
                unit["end"] = (position + 1) * 10.0
            timeline_path.write_text(json.dumps(timeline), encoding="utf-8")
            storyboard_path = project / "rich_storyboard.json"
            storyboard = json.loads(storyboard_path.read_text())
            storyboard["scenes"][0]["visualBeats"] = [
                storyboard["scenes"][0]["visualBeats"][0]
            ]
            storyboard_path.write_text(
                json.dumps(storyboard, ensure_ascii=False), encoding="utf-8"
            )

            validated = self.run_validator(project, strict_visuals=True)
            self.assertNotEqual(validated.returncode, 0)
            self.assertIn("gap without a semantic visual change", validated.stderr)

    def test_validator_rejects_cover_outside_first_scene(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.make_project(Path(directory), with_visual_beats=False)
            self.assertEqual(self.run_builder(project).returncode, 0)
            path = project / "rich_storyboard.json"
            storyboard = json.loads(path.read_text())
            storyboard["cover"]["throughUnit"] = 4
            path.write_text(json.dumps(storyboard), encoding="utf-8")
            validated = self.run_validator(project)
            self.assertNotEqual(validated.returncode, 0)
            self.assertIn("must be inside the first scene units", validated.stderr)

    def test_pool_asset_hash_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.make_project(Path(directory), with_visual_beats=False)
            self.assertEqual(self.run_builder(project).returncode, 0)
            (project / "asset_pool_usage.json").write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "assets": [
                            {
                                "assetId": "va-test12345678",
                                "src": "images/scene.png",
                                "sha256": "0" * 64,
                                "poolPath": "files/aa/va-test12345678.png",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            validated = self.run_validator(project)
            self.assertNotEqual(validated.returncode, 0)
            self.assertIn("hash mismatch", validated.stderr)


if __name__ == "__main__":
    unittest.main()
