from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from PIL import Image, ImageDraw

from scripts.case_video_readiness import (
    analyze_cover_overlay,
    evaluation_findings,
    input_hashes,
    portrait_asset_ids,
    validate_cover_geometry,
    validate_plan_contract,
    validate_portraits,
)


class CaseVideoReadinessTests(unittest.TestCase):
    def write_overlay(self, path: Path, box: tuple[int, int, int, int]) -> None:
        image = Image.new("RGBA", (1920, 1080), (0, 0, 0, 0))
        ImageDraw.Draw(image).rectangle(box, fill=(3, 12, 24, 180))
        image.save(path)

    def test_centered_compact_cover_overlay_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "overlay.png"
            self.write_overlay(path, (500, 325, 1420, 790))

            metrics = analyze_cover_overlay(path)

            self.assertEqual(validate_cover_geometry(metrics), [])
            self.assertTrue(metrics["insideCenteredSquare"])
            self.assertLess(metrics["bboxAreaSquareRatio"], 0.48)

    def test_left_aligned_or_oversized_cover_overlay_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            left_path = Path(directory) / "left.png"
            broad_path = Path(directory) / "broad.png"
            self.write_overlay(left_path, (430, 325, 1130, 790))
            self.write_overlay(broad_path, (430, 210, 1490, 870))

            left_codes = {
                finding.code
                for finding in validate_cover_geometry(analyze_cover_overlay(left_path))
            }
            broad_codes = {
                finding.code
                for finding in validate_cover_geometry(analyze_cover_overlay(broad_path))
            }

            self.assertIn("cover-not-centered", left_codes)
            self.assertIn("cover-scrim-too-large", broad_codes)

    def test_periodic_schedule_is_a_blocker_even_if_evaluator_calls_it_warning(self) -> None:
        report = {
            "score": 92.0,
            "issues": [
                {
                    "severity": "warning",
                    "code": "periodic-scene-schedule",
                    "message": "A one-in-three template repeats.",
                    "scene": "s02",
                }
            ],
            "metrics": {
                "beatCount": 20,
                "uniqueFingerprintRatio": 0.5,
                "topFingerprintShare": 0.2,
                "uniqueBaseAssetCount": 10,
                "explicitIntentRatio": 1.0,
                "maxVisualGapSeconds": 8.0,
            },
        }
        storyboard = {"visualAssets": []}

        findings = evaluation_findings(
            report,
            storyboard,
            set(),
            "plan",
            80.0,
            {"beatCount": 20, "editorialSceneCount": 4},
        )

        periodic = next(finding for finding in findings if finding.code == "periodic-scene-schedule")
        self.assertEqual(periodic.severity, "blocker")

    def test_invalid_first_scene_does_not_crash_cover_contract(self) -> None:
        storyboard = {
            "visualStyle": "manager-silhouette-warm",
            "cover": {"title": "冲突标题", "throughUnit": 1},
            "visualAssets": [],
            "scenes": [{"id": "s01", "units": "1-2", "visualBeats": []}],
        }
        timeline = {
            "units": [
                {"index": 1, "start": 0.0, "end": 1.0},
                {"index": 2, "start": 1.0, "end": 2.0},
            ]
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "case"
            project.mkdir()
            (project / "title.txt").write_text("冲突标题\n", encoding="utf-8")
            findings, _ = validate_plan_contract(
                project,
                storyboard,
                timeline,
                {},
                {},
                root,
            )

        codes = {finding.code for finding in findings}
        self.assertIn("scene-units", codes)
        self.assertIn("cover-duration", codes)

    def test_title_source_is_required_and_must_match_cover(self) -> None:
        storyboard = {
            "visualStyle": "manager-silhouette-warm",
            "cover": {"title": "原始标题", "throughUnit": 1},
            "visualAssets": [],
            "scenes": [{"id": "s01", "units": [1, 1], "visualBeats": []}],
        }
        timeline = {"units": [{"index": 1, "start": 0.0, "end": 1.0}]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "case"
            project.mkdir()

            missing_findings, _ = validate_plan_contract(
                project, storyboard, timeline, {}, {}, root
            )
            (project / "title.txt").write_text("最终标题\n", encoding="utf-8")
            mismatch_findings, _ = validate_plan_contract(
                project, storyboard, timeline, {}, {}, root
            )
            storyboard["cover"]["title"] = "最终标题"
            matching_findings, _ = validate_plan_contract(
                project, storyboard, timeline, {}, {}, root
            )

        self.assertIn("title-source", {item.code for item in missing_findings})
        self.assertIn(
            "title-source-mismatch", {item.code for item in mismatch_findings}
        )
        matching_codes = {item.code for item in matching_findings}
        self.assertNotIn("title-source", matching_codes)
        self.assertNotIn("title-source-mismatch", matching_codes)

    def test_title_file_participates_in_readiness_input_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / "title.txt").write_text("可追踪的标题\n", encoding="utf-8")

            hashes = input_hashes(project, {"visualAssets": [], "scenes": []}, "plan")

        self.assertIn("title.txt", hashes)
        self.assertEqual(len(hashes["title.txt"]), 64)

    def test_only_real_portrait_assets_receive_portrait_contract(self) -> None:
        storyboard = {
            "visualStyle": "sales-watercolor-blue-yellow",
            "visualAssets": [
                {
                    "id": "bg-with-person",
                    "src": "images/generated/team.png",
                    "role": "person",
                    "origin": "generated",
                },
                {
                    "id": "curated-office-background",
                    "src": "images/pool/office.png",
                    "role": "background",
                    "origin": "curated",
                    "poolAssetId": "visual-office-001",
                },
                {
                    "id": "portrait-li",
                    "src": "images/characters/li.png",
                    "role": "person",
                    "origin": "generated",
                },
            ],
            "scenes": [
                {
                    "visualBeats": [
                        {"layers": [{"kind": "dialogue", "portrait": "portrait-li"}]}
                    ]
                }
            ],
        }
        self.assertEqual(portrait_asset_ids(storyboard), {"portrait-li"})

    def test_generated_portrait_prompt_requires_crop_background_and_style(self) -> None:
        storyboard = {
            "visualStyle": "manager-silhouette-warm",
            "visualAssets": [
                {
                    "id": "portrait-li",
                    "src": "images/characters/li.png",
                    "role": "person",
                    "origin": "generated",
                }
            ],
            "scenes": [
                {
                    "visualBeats": [
                        {"layers": [{"kind": "dialogue", "portrait": "portrait-li"}]}
                    ]
                }
            ],
        }
        bad_prompts = {
            "images/characters/li.png": {"prompt": "A detailed executive in an office."}
        }
        good_prompts = {
            "images/characters/li.png": {
                "prompt": (
                    "Square half-body Chinese manager silhouette, cut-paper and screen-print style, "
                    "pure white background, deep navy and burnt orange palette."
                )
            }
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bad_findings, _ = validate_portraits(
                root / "case", storyboard, bad_prompts, {}, root, require_files=False
            )
            good_findings, _ = validate_portraits(
                root / "case", storyboard, good_prompts, {}, root, require_files=False
            )

        bad_codes = {finding.code for finding in bad_findings}
        good_codes = {finding.code for finding in good_findings}
        self.assertIn("portrait-prompt-contract", bad_codes)
        self.assertIn("portrait-prompt-style", bad_codes)
        self.assertNotIn("portrait-prompt-contract", good_codes)
        self.assertNotIn("portrait-prompt-style", good_codes)


if __name__ == "__main__":
    unittest.main()
