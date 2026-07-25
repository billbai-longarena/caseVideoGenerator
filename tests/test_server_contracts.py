from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

from server.app.core.config import load_settings
from server.app.core.errors import AppError
from server.app.main import create_app
from server.app.models.job import ApprovalMode
from server.app.services.model_gateway import ModelGateway, ModelGatewayError
from server.app.services.queue import InMemoryJobQueue
from server.app.services.storage import JobStorage
from server.app.services.task_registry import TASK_SPECS, TaskRegistry


EXPECTED_TASK_ROUTES = {
    "source.classify": ("openai", "gpt-5.5"),
    "case.extract": ("openai", "gpt-5.5"),
    "case.model": ("openai", "gpt-5.5"),
    "editorial.review": ("openai", "gpt-5.5"),
    "image_prompt.refine": ("openai", "gpt-5.5"),
    "remotion.frame-review": ("azure_anthropic", "salesnail-cs-46"),
    "delivery.summarize": ("openai", "gpt-5.5"),
    "narration.compose": ("azure_anthropic", "salesnail-cs-46"),
    "narration.rewrite": ("azure_anthropic", "salesnail-cs-46"),
    "remotion.plan": ("azure_anthropic", "salesnail-cs-46"),
    "remotion.repair": ("azure_anthropic", "salesnail-cs-46"),
}


def make_seed_project(root: Path) -> None:
    project = root / "seed_case"
    project.mkdir(parents=True, exist_ok=True)
    (project / "title.txt").write_text("合同测试案例\n", encoding="utf-8")
    (project / "narration.txt").write_text("这里是销售不复杂。\n", encoding="utf-8")
    (project / "storyboard_plan.json").write_text(json.dumps({"scenes": []}), encoding="utf-8")


def make_v2_visual_plan(*, overlap: bool = False) -> dict[str, object]:
    def scene(scene_id: str, units: list[int], asset_id: str, layout: str) -> dict[str, object]:
        return {
            "id": scene_id,
            "units": units,
            "chapter": scene_id,
            "kicker": "销售不复杂",
            "layout": layout,
            "tone": "dark",
            "visualMode": "layout",
            "dramaticFunction": f"推进{scene_id}的核心命题并建立下一场所需的因果关系。",
            "directorialIntent": f"让{scene_id}的信息层级清晰可见。",
            "headline": {"text": scene_id, "reveal": "perClause", "accent": []},
            "keywords": [],
            "backgrounds": [
                {"asset": asset_id, "atUnit": units[0], "transition": "wash", "motion": "center"}
            ],
            "sceneMotion": {"enter": "cut", "exit": "cut", "enterFrames": 2, "exitFrames": 2},
            "transition": "none",
            "transitionFrames": 2,
            "visualBeats": [],
        }

    return {
        "version": "2",
        "projectType": "sales-management",
        "visualStyle": "暖色经理剪影",
        "cover": {"title": "测试标题", "throughUnit": 1},
        "brand": "销售不复杂",
        "subtitleLabel": "销售不复杂",
        "direction": {
            "visualThesis": "责任逐步落到具体角色。",
            "pacingArc": "先建立冲突，再收束结论。",
            "densityStrategy": "每场只保留一个主要命题。",
            "continuityRules": ["保持人物方向一致"],
        },
        "chrome": {
            "brandBug": True,
            "chapterBadge": True,
            "subtitleBar": True,
            "progressRail": False,
            "cover": True,
        },
        "assets": [
            {"id": "asset-1", "sceneId": "s1", "role": "context", "promptIntent": "会议室剪影"},
            {"id": "asset-2", "sceneId": "s2", "role": "context", "promptIntent": "团队收束"},
        ],
        "scenes": [
            scene("s1", [1, 2], "asset-1", "breaking-news"),
            scene("s2", [2 if overlap else 3, 4], "asset-2", "closing-idea"),
        ],
    }


def make_v2_visual_beat(
    *, base_asset: str = "asset-1", canvas_tone: str = "transparent", layers: list[dict[str, object]] | None = None
) -> dict[str, object]:
    return {
        "id": "beat-1",
        "atUnit": 1,
        "visualIntent": "claim",
        "purpose": "establish",
        "directorialIntent": "让责任命题成为唯一视觉焦点。",
        "composition": "full-bleed",
        "baseAsset": base_asset,
        "baseFit": "cover",
        "transition": "cut",
        "render": {
            "cameraPath": {
                "startScale": 1,
                "endScale": 1.02,
                "startX": 0,
                "endX": 0,
                "startY": 0,
                "endY": 0,
            },
            "treatmentColor": "#00000000",
            "ambientOpacity": 0,
            "vignette": 0,
            "overlay": "none",
            "transitionFrames": 2,
            "layerEnterFrames": 2,
            "layerExitFrames": 2,
            "layerStaggerFrames": 0,
            "emphasisScale": 1,
            "pulse": False,
            "flashbackFrame": False,
            "canvasTone": canvas_tone,
        },
        "layers": layers or [],
    }


class ServerContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.seed_root = self.root / "seeds"
        make_seed_project(self.seed_root)
        self.settings = replace(
            load_settings(),
            data_root=self.root / "jobs",
            seed_projects_root=self.seed_root,
            dry_run=True,
            api_token=None,
        )
        self.registry = TaskRegistry(self.settings)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_every_model_task_is_registered_and_strictly_routed(self) -> None:
        self.assertEqual({spec.name for spec in TASK_SPECS}, set(EXPECTED_TASK_ROUTES))
        snapshot = self.registry.snapshot()
        self.assertEqual(set(snapshot), set(EXPECTED_TASK_ROUTES))
        for task, (provider, model) in EXPECTED_TASK_ROUTES.items():
            self.assertEqual(snapshot[task]["provider"], provider)
            self.assertEqual(snapshot[task]["model"], model)
            self.assertEqual(len(snapshot[task]["prompt_sha256"]), 64)
            self.assertEqual(len(snapshot[task]["input_schema"]["sha256"]), 64)
            self.assertEqual(len(snapshot[task]["output_schema"]["sha256"]), 64)

        remotion_specs = [spec for spec in TASK_SPECS if spec.name.startswith("remotion.")]
        self.assertTrue(remotion_specs)
        for spec in remotion_specs:
            self.assertEqual(spec.route_family, "remotion")
            self.assertEqual(snapshot[spec.name]["provider"], "azure_anthropic")
            self.assertEqual(snapshot[spec.name]["model"], "salesnail-cs-46")

    def test_unregistered_task_and_wrong_route_are_rejected_without_fallback(self) -> None:
        with self.assertRaises(ModelGatewayError) as unknown:
            ModelGateway(self.settings).route_for_task("unregistered.task")
        self.assertEqual(unknown.exception.code, "model_task_unregistered")

        wrong = replace(
            self.settings,
            narration_route=replace(self.settings.narration_route, model="gpt-5.5"),
        )
        with self.assertRaises(AppError) as mismatched:
            TaskRegistry(wrong).snapshot()
        self.assertEqual(mismatched.exception.code, "model_route_missing")

    def test_required_phase_b_contracts_load_and_validate(self) -> None:
        required = {
            ("source_manifest", "v1"),
            ("case_inputs", "v1"),
            ("case_model", "v1"),
            ("editorial", "v1"),
            ("editorial_review", "v1"),
            ("timeline", "v1"),
            ("visual_plan", "v1"),
            ("visual_plan", "v2"),
            ("image_prompts", "v2"),
            ("frame_review", "v1"),
            ("artifact_index", "v1"),
            ("job_manifest", "v2"),
        }
        for name, version in required:
            ref = self.registry.contracts.ref(name, version)
            self.assertEqual(len(ref.sha256), 64)

        self.registry.contracts.validate(
            "editorial",
            "v1",
            {
                "version": "1",
                "title": "一场组织变革如何真正落地",
                "narration": "这里是销售不复杂。",
                "change_summary": "初稿",
            },
        )
        with self.assertRaises(AppError) as invalid:
            self.registry.contracts.validate(
                "editorial",
                "v1",
                {"version": "1", "title": "两行\n标题", "narration": "旁白", "change_summary": "初稿"},
            )
        self.assertEqual(invalid.exception.code, "contract_invalid")

    def test_semantic_contracts_block_prohibited_editorial_and_overlapping_units(self) -> None:
        with self.assertRaises(AppError) as editorial:
            self.registry.validate_output(
                "narration.compose",
                {
                    "version": "1",
                    "title": "测试标题",
                    "narration": "这不是流程问题，而是责任问题。",
                    "change_summary": "初稿",
                },
            )
        self.assertEqual(editorial.exception.code, "semantic_review_blocked")

        with self.assertRaises(AppError) as visual:
            self.registry.validate_output("remotion.plan", make_v2_visual_plan(overlap=True))
        self.assertEqual(visual.exception.code, "semantic_review_blocked")

    def test_v2_director_canvas_rejects_implicit_text_presentation(self) -> None:
        plan = make_v2_visual_plan()
        first_scene = plan["scenes"][0]  # type: ignore[index]
        first_scene["layout"] = "director-canvas"  # type: ignore[index]
        first_scene["visualMode"] = "editorial"  # type: ignore[index]
        first_scene["visualBeats"] = [  # type: ignore[index]
            {
                "id": "beat-1",
                "atUnit": 1,
                "visualIntent": "claim",
                "purpose": "establish",
                "directorialIntent": "让责任命题成为唯一视觉焦点。",
                "composition": "full-bleed",
                "baseAsset": "asset-1",
                "baseFit": "cover",
                "transition": "cut",
                "render": {
                    "cameraPath": {
                        "startScale": 1,
                        "endScale": 1.02,
                        "startX": 0,
                        "endX": 0,
                        "startY": 0,
                        "endY": 0,
                    },
                    "treatmentColor": "#00000000",
                    "ambientOpacity": 0,
                    "vignette": 0,
                    "overlay": "none",
                    "transitionFrames": 2,
                    "layerEnterFrames": 2,
                    "layerExitFrames": 2,
                    "layerStaggerFrames": 0,
                    "emphasisScale": 1,
                    "pulse": False,
                    "flashbackFrame": False,
                    "canvasTone": "dark",
                },
                "layers": [
                    {
                        "id": "claim",
                        "kind": "text",
                        "slot": "center",
                        "text": "责任没有落点",
                    }
                ],
            }
        ]

        with self.assertRaises(AppError) as invalid:
            self.registry.validate_output("remotion.plan", plan)
        self.assertEqual(invalid.exception.code, "model_output_invalid")
        self.assertIn("required property", str(invalid.exception))

    def test_v2_displayed_keyword_requires_explicit_presentation(self) -> None:
        plan = make_v2_visual_plan()
        first_scene = plan["scenes"][0]  # type: ignore[index]
        first_scene["keywords"] = [{"text": "事实", "atUnit": 1, "display": True}]  # type: ignore[index]

        with self.assertRaises(AppError) as invalid:
            self.registry.validate_output("remotion.plan", plan)
        self.assertEqual(invalid.exception.code, "model_output_invalid")
        self.assertIn("required property", str(invalid.exception))

    def test_v2_director_canvas_rejects_visible_keyword_component(self) -> None:
        plan = make_v2_visual_plan()
        first_scene = plan["scenes"][0]  # type: ignore[index]
        first_scene["layout"] = "director-canvas"  # type: ignore[index]
        first_scene["visualMode"] = "editorial"  # type: ignore[index]
        first_scene["visualBeats"] = [  # type: ignore[index]
            {
                "id": "beat-1",
                "atUnit": 1,
                "visualIntent": "claim",
                "purpose": "establish",
                "directorialIntent": "把事实命题放在画面中心并保留清晰负空间。",
                "composition": "full-bleed",
                "baseAsset": "asset-1",
                "baseFit": "cover",
                "transition": "cut",
                "render": {
                    "cameraPath": {
                        "startScale": 1,
                        "endScale": 1.02,
                        "startX": 0,
                        "endX": 0,
                        "startY": 0,
                        "endY": 0,
                    },
                    "treatmentColor": "#00000000",
                    "ambientOpacity": 0,
                    "vignette": 0,
                    "overlay": "none",
                    "transitionFrames": 2,
                    "layerEnterFrames": 2,
                    "layerExitFrames": 2,
                    "layerStaggerFrames": 0,
                    "emphasisScale": 1,
                    "pulse": False,
                    "flashbackFrame": False,
                    "canvasTone": "dark",
                },
                "layers": [],
            }
        ]
        first_scene["keywords"] = [  # type: ignore[index]
            {
                "text": "事实",
                "atUnit": 1,
                "display": True,
                "enter": "cut",
                "enterFrames": 2,
                "surface": "none",
                "background": "#000000",
                "color": "#FFFFFF",
                "rotation": 0,
                "fontSize": 42,
                "float": False,
            }
        ]

        with self.assertRaises(AppError) as invalid:
            self.registry.validate_output("remotion.plan", plan)
        self.assertEqual(invalid.exception.code, "semantic_review_blocked")
        self.assertIn("explicit text layers", str(invalid.exception))

    def test_v2_plan_rejects_opaque_canvas_for_background_base_asset(self) -> None:
        plan = make_v2_visual_plan()
        plan["assets"][0]["id"] = "bg-s1"  # type: ignore[index]
        first_scene = plan["scenes"][0]  # type: ignore[index]
        first_scene["layout"] = "director-canvas"  # type: ignore[index]
        first_scene["visualMode"] = "editorial"  # type: ignore[index]
        first_scene["backgrounds"] = []  # type: ignore[index]
        first_scene["visualBeats"] = [make_v2_visual_beat(base_asset="bg-s1", canvas_tone="dark")]  # type: ignore[index]

        with self.assertRaises(AppError) as invalid:
            self.registry.validate_output("remotion.plan", plan)

        self.assertEqual(invalid.exception.code, "semantic_review_blocked")
        self.assertIn("background-like baseAsset", str(invalid.exception))

    def test_v2_plan_rejects_unboxed_opaque_text_surface(self) -> None:
        plan = make_v2_visual_plan()
        first_scene = plan["scenes"][0]  # type: ignore[index]
        first_scene["layout"] = "director-canvas"  # type: ignore[index]
        first_scene["visualMode"] = "editorial"  # type: ignore[index]
        first_scene["backgrounds"] = []  # type: ignore[index]
        first_scene["visualBeats"] = [  # type: ignore[index]
            make_v2_visual_beat(
                layers=[
                    {
                        "id": "claim-card",
                        "kind": "text",
                        "slot": "center",
                        "text": "责任没有落点",
                        "variant": "headline",
                        "surface": "paper",
                        "align": "center",
                        "enter": "fade",
                        "fontSize": 58,
                        "fontWeight": 800,
                        "lineHeight": 1.1,
                        "color": "#111827",
                    }
                ]
            )
        ]

        with self.assertRaises(AppError) as invalid:
            self.registry.validate_output("remotion.plan", plan)

        self.assertEqual(invalid.exception.code, "semantic_review_blocked")
        self.assertIn("surface without an explicit box", str(invalid.exception))

    def test_manifest_v2_pins_registry_prompts_and_contracts(self) -> None:
        storage = JobStorage(self.settings)
        manifest = storage.create_job(
            project_name="合同快照",
            approval_mode=ApprovalMode.editorial,
            idempotency_key="contract-snapshot",
            seed_project="seed_case",
        )
        self.assertEqual(manifest["manifest_version"], 2)
        self.assertEqual(manifest["input_mode"], "project")
        self.assertEqual(manifest["task_registry"], self.registry.snapshot())
        self.assertEqual(manifest["prompt_pins"], self.registry.prompt_pins())
        self.assertEqual(manifest["current_revisions"]["editorial"], None)
        self.registry.contracts.validate("job_manifest", "v2", storage.read_manifest(manifest["job_id"]))

    def test_model_gateway_requires_the_pinned_prompt_version(self) -> None:
        gateway = ModelGateway(self.settings)
        with self.assertRaises(ModelGatewayError) as mismatch:
            gateway.run_json(
                "case.model",
                "v2",
                {"task": "case.model", "context": {}},
            )
        self.assertEqual(mismatch.exception.code, "contract_invalid")

    def test_public_errors_have_stable_shape_and_request_id(self) -> None:
        storage = JobStorage(self.settings)
        client = TestClient(create_app(self.settings, storage, InMemoryJobQueue()))
        response = client.get("/v1/jobs/job_missing")
        self.assertEqual(response.status_code, 404)
        payload = response.json()
        self.assertEqual(payload["code"], "not_found")
        self.assertFalse(payload["retryable"])
        self.assertTrue(payload["request_id"].startswith("req_"))
        self.assertEqual(response.headers["X-Request-ID"], payload["request_id"])
        self.assertIn("error_id", payload)
        self.assertNotIn("diagnostics", payload)


if __name__ == "__main__":
    unittest.main()
