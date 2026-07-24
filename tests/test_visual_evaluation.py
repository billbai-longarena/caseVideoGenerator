from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest

from PIL import Image

from scripts.evaluate_visual_storyboard import evaluate_project, write_report


class VisualEvaluationTests(unittest.TestCase):
    def make_project(
        self,
        root: Path,
        *,
        unit_count: int,
        seconds_per_unit: float,
        beats: list[dict],
    ) -> Path:
        project = root / "case"
        image_path = project / "images" / "bg.png"
        image_path.parent.mkdir(parents=True)
        Image.new("RGB", (320, 180), "#225ea8").save(image_path)

        units = [
            {
                "index": index,
                "paragraph": 1,
                "text": f"第{index}个信息点。",
                "start": (index - 1) * seconds_per_unit,
                "end": index * seconds_per_unit,
            }
            for index in range(1, unit_count + 1)
        ]
        timeline = {"duration": unit_count * seconds_per_unit, "units": units}
        storyboard = {
            "title": "快速评估测试",
            "visualAssets": [
                {
                    "id": "bg",
                    "type": "image",
                    "src": "images/bg.png",
                    "role": "context",
                    "origin": "generated",
                }
            ],
            "scenes": [
                {
                    "id": "s01",
                    "units": [1, unit_count],
                    "headline": "测试场景",
                    "visualMode": "editorial",
                    "visualBeats": beats,
                }
            ],
        }
        (project / "narration.timeline.json").write_text(
            json.dumps(timeline, ensure_ascii=False), encoding="utf-8"
        )
        (project / "rich_storyboard.json").write_text(
            json.dumps(storyboard, ensure_ascii=False), encoding="utf-8"
        )
        return project

    def test_disabled_box_is_reported_but_not_counted_as_visual_event(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.make_project(
                Path(directory),
                unit_count=2,
                seconds_per_unit=8.0,
                beats=[
                    {
                        "id": "s01-b01",
                        "atUnit": 1,
                        "visualIntent": "context",
                        "purpose": "establish",
                        "composition": "full-bleed",
                        "baseAsset": "bg",
                        "layers": [
                            {
                                "kind": "annotate",
                                "shape": "box",
                                "revealAtUnit": 2,
                            }
                        ],
                    }
                ],
            )

            report = evaluate_project(project)
            issue_codes = {issue["code"] for issue in report["issues"]}

            self.assertEqual(report["metrics"]["maxVisualGapSeconds"], 16.0)
            self.assertEqual(report["metrics"]["disabledAnnotationShapeCounts"], {"box": 1})
            self.assertIn("disabled-annotate-shape", issue_codes)
            self.assertEqual(report["scenes"][0]["beats"][0]["disabledAnnotations"], ["box"])

    def test_periodic_template_is_detected_even_when_story_labels_rotate(self) -> None:
        intents = [
            "context",
            "evidence",
            "claim",
            "consequence",
            "mechanism",
            "decision",
            "reflection",
            "protagonist",
        ]
        compositions = [
            "full-bleed",
            "split",
            "portrait-left",
            "evidence-collage",
            "document-focus",
            "portrait-right",
            "triptych",
            "full-bleed",
        ]
        beats = []
        for position in range(8):
            layer = (
                {"kind": "text", "text": f"观点{position + 1}"}
                if position % 2 == 0
                else {
                    "kind": "counter",
                    "label": f"指标{position + 1}",
                    "value": {"to": position + 1},
                }
            )
            beats.append(
                {
                    "id": f"s01-b{position + 1:02d}",
                    "atUnit": position + 1,
                    "visualIntent": intents[position],
                    "purpose": "explain",
                    "composition": compositions[position],
                    "baseAsset": "bg",
                    "layers": [layer],
                }
            )

        with tempfile.TemporaryDirectory() as directory:
            project = self.make_project(
                Path(directory),
                unit_count=8,
                seconds_per_unit=2.0,
                beats=beats,
            )
            report = evaluate_project(project)
            issue_codes = {issue["code"] for issue in report["issues"]}

            self.assertIn("periodic-scene-schedule", issue_codes)
            self.assertEqual(report["scenes"][0]["periodicPattern"]["period"], 2)

    def test_report_writer_creates_render_free_debug_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.make_project(
                Path(directory),
                unit_count=2,
                seconds_per_unit=2.0,
                beats=[
                    {
                        "id": "s01-b01",
                        "atUnit": 1,
                        "visualIntent": "context",
                        "purpose": "establish",
                        "composition": "full-bleed",
                        "baseAsset": "bg",
                        "layers": [{"kind": "text", "text": "建立情境"}],
                    }
                ],
            )

            output_dir = write_report(evaluate_project(project))

            self.assertTrue((output_dir / "visual_eval.json").is_file())
            self.assertTrue((output_dir / "visual_eval.md").is_file())
            self.assertTrue((output_dir / "index.html").is_file())
            self.assertTrue((output_dir / "contact_sheet.jpg").is_file())

    def test_scene_contract_and_local_schedule_alignment_are_reported_separately(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.make_project(
                Path(directory),
                unit_count=2,
                seconds_per_unit=3.0,
                beats=[
                    {
                        "id": "s01-b01",
                        "atUnit": 1,
                        "visualIntent": "evidence",
                        "purpose": "evidence",
                        "composition": "split",
                        "baseAsset": "bg",
                        "semanticCues": ["订单金额80万"],
                        "layers": [
                            {
                                "kind": "counter",
                                "label": "订单金额",
                                "value": {"to": 80, "suffix": "万"},
                            }
                        ],
                    },
                    {
                        "id": "s01-b02",
                        "atUnit": 2,
                        "visualIntent": "reflection",
                        "purpose": "reset",
                        "composition": "full-bleed",
                        "baseAsset": "bg",
                        "semanticCues": ["复盘"],
                        "layers": [{"kind": "text", "text": "复盘"}],
                    },
                ],
            )
            timeline_path = project / "narration.timeline.json"
            timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
            timeline["units"][0]["text"] = "先介绍客户背景。"
            timeline["units"][1]["text"] = "关键证据显示订单金额达到80万，随后复盘。"
            timeline_path.write_text(
                json.dumps(timeline, ensure_ascii=False), encoding="utf-8"
            )

            report = evaluate_project(project)
            first_beat = report["scenes"][0]["beats"][0]

            self.assertGreater(
                first_beat["sceneCueAlignment"], first_beat["localCueAlignment"]
            )
            self.assertIn("averageSceneCueAlignment", report["metrics"])
            self.assertIn("averageLocalCueAlignment", report["metrics"])

    def test_stale_rich_storyboard_is_reported_when_plan_is_newer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.make_project(
                Path(directory),
                unit_count=2,
                seconds_per_unit=2.0,
                beats=[
                    {
                        "id": "s01-b01",
                        "atUnit": 1,
                        "visualIntent": "context",
                        "purpose": "establish",
                        "composition": "full-bleed",
                        "baseAsset": "bg",
                        "layers": [],
                    }
                ],
            )
            storyboard_path = project / "rich_storyboard.json"
            plan_path = project / "storyboard_plan.json"
            plan_path.write_text('{"project": {}, "scenes": []}', encoding="utf-8")
            newer = storyboard_path.stat().st_mtime + 2.0
            os.utime(plan_path, (newer, newer))

            report = evaluate_project(project)
            issue_codes = {issue["code"] for issue in report["issues"]}

            self.assertFalse(report["metrics"]["sourceArtifactFresh"])
            self.assertIn("stale-derived-storyboard", issue_codes)


if __name__ == "__main__":
    unittest.main()
