from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from server.app.services.visual_adapter import (
    build_rich_storyboard,
    prompt_image_path,
    scene_image_path,
)


ROOT = Path(__file__).resolve().parents[1]


class VisualAdapterTest(unittest.TestCase):
    @staticmethod
    def timeline() -> dict[str, object]:
        return {
            "duration": 12.0,
            "units": [
                {"index": 1, "text": "第一句。", "start": 0.0, "end": 4.0},
                {"index": 2, "text": "第二句。", "start": 4.0, "end": 8.0},
                {"index": 3, "text": "第三句。", "start": 8.0, "end": 12.0},
            ],
        }

    @staticmethod
    def plan() -> dict[str, object]:
        return {
            "version": "1",
            "cover": {"title": "责任落地之后", "proof": "当前旁白"},
            "brand": "销售不复杂",
            "subtitleLabel": "销售不复杂",
            "scenes": [
                {
                    "scene_id": "scene/开场 01",
                    "atUnit": 0,
                    "units": 2,
                    "layout": "cover",
                    "headline": "责任从哪里开始",
                    "kicker": "案例开场",
                    "visual_intent": "管理者站在决策边界前。",
                    "keywords": ["事实", "责任"],
                    "reuse": False,
                    "allowBackgroundReuse": False,
                },
                {
                    "scene_id": "scene-002",
                    "atUnit": 2,
                    "units": 1,
                    "layout": "summary",
                    "headline": "行动形成闭环",
                    "kicker": "结论",
                    "visual_intent": "团队向共同目标收束。",
                    "keywords": ["行动"],
                    "reuse": True,
                    "allowBackgroundReuse": True,
                },
            ],
        }

    @staticmethod
    def plan_v2() -> dict[str, object]:
        first_beat = {
            "id": "beat-opening-pressure",
            "atUnit": 1,
            "visualIntent": "relationship",
            "purpose": "establish",
            "directorialIntent": "先让人物被空旷会议桌压住，再揭示责任断点。",
            "composition": "custom",
            "baseAsset": "asset-room",
            "baseBox": {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0},
            "baseFit": "cover",
            "transition": "cut",
            "camera": "push-in",
            "treatment": "desaturated",
            "render": {
                "cameraIntensity": 0.72,
                "ambientOpacity": 0.18,
                "vignette": 0.22,
                "overlay": "read-right",
                "transitionFrames": 7,
                "layerEnterFrames": 11,
                "layerExitFrames": 9,
                "layerStaggerFrames": 3,
                "emphasisScale": 1.04,
                "pulse": False,
                "flashbackFrame": False,
                "canvasTone": "dark",
            },
            "layers": [
                {
                    "id": "layer-thesis",
                    "kind": "text",
                    "box": {"x": 0.58, "y": 0.2, "width": 0.3, "height": 0.22},
                    "text": "责任没有落点",
                    "variant": "headline",
                    "surface": "none",
                    "align": "left",
                    "enter": "slide-right",
                    "fontSize": 62,
                    "fontWeight": 800,
                    "lineHeight": 1.1,
                    "color": "#F6E7B0",
                    "opacity": 0.96,
                    "revealAtUnit": 1,
                    "exitAtUnit": 2,
                }
            ],
        }
        return {
            "version": "2",
            "projectType": "sales-management",
            "visualStyle": "warm manager silhouettes with restrained evidence overlays",
            "cover": {
                "title": "责任落地之后",
                "subtitle": "一次组织责任重构",
                "kicker": "管理案例",
                "throughUnit": 2,
                "proof": "标题由第一场责任断点和第二场闭环共同支撑。",
            },
            "brand": "销售不复杂",
            "subtitleLabel": "销售不复杂",
            "direction": {
                "visualThesis": "用空间距离表现责任从悬空到落地。",
                "pacingArc": "前两句克制压迫，结尾快速收束。",
                "densityStrategy": "每一拍只有一个视觉论点。",
                "continuityRules": ["会议桌始终作为责任边界的空间锚点。"],
                "avoid": ["固定三拍", "重复信息卡"],
            },
            "chrome": {
                "brandBug": False,
                "chapterBadge": True,
                "subtitleBar": True,
                "progressRail": False,
                "cover": True,
            },
            "assets": [
                {
                    "id": "asset-room",
                    "sceneId": "scene-opening",
                    "role": "context",
                    "promptIntent": "空旷会议室与被拉开的管理者剪影，右侧保留文字负空间。",
                    "continuity": "保留长桌和暖色背光。",
                },
                {
                    "id": "asset-action",
                    "sceneId": "scene-close",
                    "role": "metaphor",
                    "promptIntent": "团队围绕一个明确行动点收束，人物不出现细致面孔。",
                },
            ],
            "scenes": [
                {
                    "id": "scene-opening",
                    "units": [1, 2],
                    "chapter": "01",
                    "kicker": "责任断点",
                    "layout": "director-canvas",
                    "tone": "dark",
                    "visualMode": "editorial",
                    "dramaticFunction": "先建立责任断点，再把组织压力推到台前。",
                    "directorialIntent": "用人物与桌面的距离建立组织压力。",
                    "headline": {
                        "text": "责任从哪里开始",
                        "reveal": "perClause",
                        "accent": ["责任"],
                    },
                    "keywords": [{"text": "责任", "atUnit": 2, "display": False, "sfx": "stamp"}],
                    "backgrounds": [
                        {
                            "asset": "asset-room",
                            "atUnit": 1,
                            "transition": "ink",
                            "motion": "left",
                        }
                    ],
                    "sceneMotion": {
                        "enter": "fade",
                        "exit": "lift",
                        "enterFrames": 13,
                        "exitFrames": 17,
                    },
                    "transition": "chapter-circle",
                    "transitionFrames": 19,
                    "chrome": {
                        "brandBug": False,
                        "chapterBadge": True,
                        "subtitleBar": True,
                    },
                    "visualBeats": [first_beat],
                },
                {
                    "id": "scene-close",
                    "units": [3, 3],
                    "chapter": "02",
                    "kicker": "行动闭环",
                    "layout": "closing-idea",
                    "tone": "bright",
                    "visualMode": "layout",
                    "dramaticFunction": "把前场冲突收束成可执行的行动闭环。",
                    "directorialIntent": "让行动点成为唯一高亮，快速结束。",
                    "headline": {
                        "text": "行动形成闭环",
                        "reveal": "perChar",
                        "accent": ["闭环"],
                    },
                    "keywords": [],
                    "backgrounds": [
                        {
                            "asset": "asset-action",
                            "atUnit": 3,
                            "transition": "paper",
                            "motion": "center",
                        }
                    ],
                    "sceneMotion": {
                        "enter": "rise",
                        "exit": "fade",
                        "enterFrames": 9,
                        "exitFrames": 12,
                    },
                    "transition": "none",
                    "transitionFrames": 5,
                    "layoutProps": {"statement": "责任必须落到下一步行动。"},
                    "visualBeats": [],
                },
            ],
        }

    def test_scene_id_maps_to_safe_deterministic_project_path(self) -> None:
        path = scene_image_path("../场景/一")
        self.assertRegex(path, r"^images/generated/[a-z0-9-]+\.png$")
        self.assertNotIn("..", path)
        self.assertEqual(path, scene_image_path("../场景/一"))
        self.assertEqual(prompt_image_path({"scene_id": "../场景/一"}), path)
        self.assertIsNone(prompt_image_path({"file": "../../secret.png"}))

    def test_visual_plan_zero_based_units_become_runtime_one_based_units(self) -> None:
        storyboard = build_rich_storyboard(
            self.plan(),
            self.timeline(),
            authored_title="责任落地之后",
            project_name="adapter-test",
            image_prompts={
                "version": "1",
                "prompts": [
                    {
                        "scene_id": "scene/开场 01",
                        "prompt": "管理者剪影",
                        "negative_prompt": "文字",
                        "style_family": "sales-management-silhouette",
                    }
                ],
            },
        )

        self.assertEqual(storyboard["projectType"], "sales-management")
        self.assertEqual(storyboard["cover"]["title"], "责任落地之后")
        self.assertEqual(storyboard["scenes"][0]["units"], [1, 2])
        self.assertEqual(storyboard["scenes"][1]["units"], [3, 3])
        self.assertEqual(
            storyboard["scenes"][1]["backgrounds"][0]["image"],
            storyboard["scenes"][0]["backgrounds"][0]["image"],
        )
        self.assertEqual(
            [subtitle["unit"] for scene in storyboard["scenes"] for subtitle in scene["subtitles"]],
            [1, 2, 3],
        )

    def test_adapter_rejects_unit_gaps_and_title_drift(self) -> None:
        gap = self.plan()
        gap["scenes"][1]["atUnit"] = 1  # type: ignore[index]
        with self.assertRaisesRegex(ValueError, "ordered, non-overlapping"):
            build_rich_storyboard(gap, self.timeline(), authored_title="责任落地之后")

        with self.assertRaisesRegex(ValueError, "exactly match title"):
            build_rich_storyboard(
                self.plan(), self.timeline(), authored_title="另一个标题"
            )

    def test_storyboard_builder_supports_visual_plan_v1(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "title.txt").write_text("责任落地之后\n", encoding="utf-8")
            (project / "narration.timeline.json").write_text(
                json.dumps(self.timeline(), ensure_ascii=False), encoding="utf-8"
            )
            (project / "storyboard_plan.json").write_text(
                json.dumps(self.plan(), ensure_ascii=False), encoding="utf-8"
            )
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts/build_storyboard_from_plan.py"), str(project)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            storyboard = json.loads((project / "rich_storyboard.json").read_text(encoding="utf-8"))
            self.assertEqual(storyboard["scenes"][0]["units"], [1, 2])

    def test_visual_plan_v2_is_compiled_without_creative_defaults(self) -> None:
        plan = self.plan_v2()
        prompts = {
            "version": "2",
            "prompts": [
                {"asset_id": "asset-room", "prompt": "会议室剪影"},
                {"asset_id": "asset-action", "prompt": "团队行动收束"},
            ],
        }
        storyboard = build_rich_storyboard(
            plan,
            self.timeline(),
            authored_title="责任落地之后",
            project_name="director-test",
            image_prompts=prompts,
        )

        self.assertEqual(storyboard["directorPlanVersion"], "2")
        self.assertEqual(storyboard["direction"], plan["direction"])
        self.assertEqual(storyboard["chrome"], plan["chrome"])
        self.assertEqual(storyboard["scenes"][0]["layout"], "director-canvas")
        self.assertEqual(storyboard["scenes"][0]["sceneMotion"], plan["scenes"][0]["sceneMotion"])
        self.assertEqual(storyboard["scenes"][0]["transition"], "chapter-circle")
        self.assertEqual(storyboard["scenes"][0]["transitionFrames"], 19)
        self.assertEqual(storyboard["scenes"][0]["keywords"], plan["scenes"][0]["keywords"])
        self.assertEqual(storyboard["scenes"][0]["visualBeats"], plan["scenes"][0]["visualBeats"])
        self.assertEqual(storyboard["scenes"][1]["props"], plan["scenes"][1]["layoutProps"])

    def test_visual_plan_v2_allows_asset_free_director_scenes(self) -> None:
        plan = self.plan_v2()
        plan["assets"] = []
        for scene in plan["scenes"]:  # type: ignore[index]
            scene["backgrounds"] = []
        first_beat = plan["scenes"][0]["visualBeats"][0]  # type: ignore[index]
        first_beat.pop("baseAsset")
        first_beat.pop("baseBox")
        first_beat.pop("baseFit")

        storyboard = build_rich_storyboard(
            plan,
            self.timeline(),
            authored_title="责任落地之后",
            project_name="type-only-director-test",
            image_prompts={"version": "2", "prompts": []},
        )

        self.assertEqual(storyboard["visualAssets"], [])
        self.assertEqual(storyboard["scenes"][0]["backgrounds"], [])
        self.assertEqual(storyboard["scenes"][1]["backgrounds"], [])
        self.assertNotIn("baseAsset", storyboard["scenes"][0]["visualBeats"][0])

    def test_storyboard_builder_supports_visual_plan_v2(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "title.txt").write_text("责任落地之后\n", encoding="utf-8")
            (project / "narration.timeline.json").write_text(
                json.dumps(self.timeline(), ensure_ascii=False), encoding="utf-8"
            )
            (project / "storyboard_plan.json").write_text(
                json.dumps(self.plan_v2(), ensure_ascii=False), encoding="utf-8"
            )
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts/build_storyboard_from_plan.py"), str(project)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            storyboard = json.loads((project / "rich_storyboard.json").read_text(encoding="utf-8"))
            self.assertEqual(storyboard["directorPlanVersion"], "2")
            self.assertEqual(storyboard["scenes"][0]["visualBeats"], self.plan_v2()["scenes"][0]["visualBeats"])


if __name__ == "__main__":
    unittest.main()
