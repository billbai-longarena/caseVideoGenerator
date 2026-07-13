from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "scripts" / "build_storyboard_from_plan.py"
VALIDATOR = ROOT / "scripts" / "validate_case_project.py"


class VisualBeatProjectTests(unittest.TestCase):
    def make_project(self, root: Path, *, with_visual_beats: bool) -> Path:
        project = root / "case"
        (project / "audio").mkdir(parents=True)
        (project / "images").mkdir()
        (project / "audio" / "narration_azure.wav").write_bytes(b"RIFF-test")
        (project / "images" / "scene.png").write_bytes(b"png-test")
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

    def run_validator(self, project: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(VALIDATOR), str(project)],
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
            validated = self.run_validator(project)
            self.assertEqual(validated.returncode, 0, validated.stderr)
            self.assertIn("visualBeats=0", validated.stdout)

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
                    "shape": "ring",
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
            self.assertEqual(layers[2]["nodes"][1]["revealAtUnit"], 3)
            validated = self.run_validator(project)
            self.assertEqual(validated.returncode, 0, validated.stderr)

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
                        "shape": "ring",
                        "region": {"x": 0.5, "y": 0.5, "w": 1.4, "h": 0.2},
                    }
                ],
            )
            validated = self.run_validator(project)
            self.assertNotEqual(validated.returncode, 0)
            self.assertIn("region.w must be a number between 0 and 1", validated.stderr)

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
