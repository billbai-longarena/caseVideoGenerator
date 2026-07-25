from __future__ import annotations

import copy
import unittest

from server.app.core.errors import AppError
from server.app.services.intent_frames import select_intent_frames
from server.app.services.pipeline import CaseVideoPipeline


def timeline_fixture() -> dict[str, object]:
    return {
        "duration": 8.0,
        "units": [
            {"index": 1, "start": 0.0, "end": 2.0},
            {"index": 2, "start": 2.0, "end": 4.0},
            {"index": 3, "start": 4.0, "end": 6.0},
            {"index": 4, "start": 6.0, "end": 8.0},
        ],
    }


def storyboard_fixture() -> dict[str, object]:
    return {
        "fps": 30,
        "scenes": [
            {
                "id": "scene-001",
                "units": [1, 2],
                "dramaticFunction": "建立失序",
                "directorialIntent": "让责任断裂成为第一视觉焦点",
                "visualBeats": [
                    {"id": "beat-001", "atUnit": 1, "directorialIntent": "先看到散乱关系"},
                    {"id": "beat-002", "atUnit": 2, "directorialIntent": "再聚焦责任缺口"},
                ],
            },
            {
                "id": "scene-002",
                "units": [3, 4],
                "dramaticFunction": "完成转向",
                "directorialIntent": "让共同事实形成稳定秩序",
                "visualBeats": [
                    {"id": "beat-003", "atUnit": 3, "directorialIntent": "关系开始收束"},
                    {"id": "beat-004", "atUnit": 4, "directorialIntent": "以清晰行动收尾"},
                ],
            },
        ],
    }


def visual_plan_fixture() -> dict[str, object]:
    return {
        "version": "2",
        "width": 1920,
        "height": 1080,
        "fps": 30,
        "brand": "销售不复杂",
        "subtitleLabel": "销售不复杂",
        "cover": {"title": "事实如何重新组织团队", "throughUnit": 1},
        "direction": {"visualThesis": "从失序走向共同事实"},
        "assets": [{"id": "asset-001", "path": "images/generated/asset-001.png"}],
        "scenes": [
            {
                "id": "scene-001",
                "units": [1, 2],
                "chapter": "失序",
                "kicker": "责任断裂",
                "layout": "director-canvas",
                "visualMode": "editorial",
                "dramaticFunction": "建立失序",
                "directorialIntent": "让责任断裂成为第一视觉焦点",
                "keywords": [],
                "backgrounds": [],
                "visualBeats": [
                    {
                        "id": "beat-001",
                        "atUnit": 1,
                        "visualIntent": "呈现团队失序",
                        "purpose": "setup",
                        "directorialIntent": "用压迫的空间关系表现责任断裂",
                        "baseAsset": "asset-001",
                        "composition": "full-bleed",
                        "render": {
                            "transition": "cut",
                            "transitionFrames": 8,
                            "layerEnterFrames": 10,
                            "layerExitFrames": 8,
                            "cameraPath": {
                                "startScale": 1.0,
                                "endScale": 1.04,
                                "startX": 0.0,
                                "endX": 0.02,
                                "startY": 0.0,
                                "endY": 0.0,
                            },
                            "treatmentColor": "#10233f",
                        },
                        "layers": [
                            {
                                "id": "fact-title",
                                "kind": "text",
                                "text": "责任没有落位",
                                "slot": "center",
                                "enter": "fade",
                            }
                        ],
                    }
                ],
            }
        ],
    }


class IntentFrameSelectionTest(unittest.TestCase):
    def test_selection_covers_every_scene_and_then_samples_remaining_beats(self) -> None:
        frames = select_intent_frames(storyboard_fixture(), timeline_fixture(), max_frames=3)

        self.assertEqual(len(frames), 3)
        self.assertEqual({item["scene_id"] for item in frames}, {"scene-001", "scene-002"})
        self.assertEqual([item["frame_id"] for item in frames], ["frame-001", "frame-002", "frame-003"])
        self.assertEqual([item["frame"] for item in frames], sorted(item["frame"] for item in frames))

    def test_scene_coverage_overrides_a_too_small_soft_limit(self) -> None:
        frames = select_intent_frames(storyboard_fixture(), timeline_fixture(), max_frames=1)

        self.assertEqual(len(frames), 2)
        self.assertEqual({item["scene_id"] for item in frames}, {"scene-001", "scene-002"})

    def test_beat_outside_its_scene_is_rejected(self) -> None:
        storyboard = storyboard_fixture()
        storyboard["scenes"][0]["visualBeats"][0]["atUnit"] = 3

        with self.assertRaisesRegex(ValueError, "outside its scene"):
            select_intent_frames(storyboard, timeline_fixture())


class IntentFrameReviewTest(unittest.TestCase):
    def test_review_cannot_assign_a_frame_to_the_wrong_scene(self) -> None:
        frames = [
            {"frame_id": "frame-001", "scene_id": "scene-001"},
            {"frame_id": "frame-002", "scene_id": "scene-002"},
        ]
        review = {
            "scene_reviews": [
                {"scene_id": "scene-001", "frame_ids": ["frame-002"]},
                {"scene_id": "scene-002", "frame_ids": ["frame-001"]},
            ],
            "issues": [],
        }

        with self.assertRaises(AppError) as caught:
            CaseVideoPipeline._validate_frame_review_evidence(review, frames)

        self.assertEqual(caught.exception.code, "model_output_invalid")

    def test_composition_repair_preserves_protected_director_content(self) -> None:
        before = visual_plan_fixture()
        repaired = copy.deepcopy(before)
        beat = repaired["scenes"][0]["visualBeats"][0]
        beat["atUnit"] = 2
        beat["composition"] = "evidence-collage"
        beat["baseBox"] = {"x": 0.04, "y": 0.08, "width": 0.56, "height": 0.7}
        beat["render"]["cameraPath"]["endScale"] = 1.08
        beat["render"]["treatmentColor"] = "#24324a"
        beat["layers"][0]["slot"] = "right"
        beat["layers"][0]["revealAtUnit"] = 2
        repaired["scenes"][0]["chrome"] = {"progressRail": False}

        CaseVideoPipeline._assert_intent_repair_scope(before, repaired)

    def test_composition_repair_rejects_content_layout_and_asset_changes(self) -> None:
        before = visual_plan_fixture()
        mutations = {
            "text": lambda plan: plan["scenes"][0]["visualBeats"][0]["layers"][0].update(
                {"text": "责任已经落位"}
            ),
            "layout": lambda plan: plan["scenes"][0].update({"layout": "split-data"}),
            "base asset": lambda plan: plan["scenes"][0]["visualBeats"][0].update(
                {"baseAsset": "asset-002"}
            ),
        }

        for label, mutate in mutations.items():
            with self.subTest(change=label):
                changed = copy.deepcopy(before)
                mutate(changed)
                with self.assertRaises(AppError) as caught:
                    CaseVideoPipeline._assert_intent_repair_scope(before, changed)
                self.assertEqual(caught.exception.code, "semantic_review_blocked")


if __name__ == "__main__":
    unittest.main()
