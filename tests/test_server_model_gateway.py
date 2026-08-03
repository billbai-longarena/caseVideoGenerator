from __future__ import annotations

import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from server.app.core.config import ModelRoute, load_settings
from server.app.models.job import ApprovalMode
from server.app.services.model_gateway import ModelGateway, ModelGatewayError
from server.app.services.storage import JobStorage
from server.app.services.task_registry import TASK_SPECS


class FakeResponse:
    def __init__(self, payload: dict[str, object], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict[str, object]:
        return self._payload


def make_seed_project(root: Path) -> None:
    project = root / "seed_case"
    project.mkdir(parents=True, exist_ok=True)
    (project / "title.txt").write_text("模型网关测试\n", encoding="utf-8")
    (project / "narration.txt").write_text("这里是销售不复杂。\n", encoding="utf-8")
    (project / "storyboard_plan.json").write_text('{"scenes": []}\n', encoding="utf-8")


class ServerModelGatewayTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.seed_root = self.root / "seeds"
        make_seed_project(self.seed_root)
        self.settings = replace(
            load_settings(),
            data_root=self.root / "jobs",
            seed_projects_root=self.seed_root,
            api_token=None,
            dry_run=False,
            require_model_config=True,
            narration_route=ModelRoute(
                provider="azure_anthropic",
                model="case-video-claude",
                task_family="narration",
                endpoint="https://example.services.ai.azure.com/anthropic/v1/messages",
                api_key_env="TEST_AZURE_ANTHROPIC_KEY",
                api_version="2023-06-01",
                request_model="case-video-claude",
            ),
            remotion_route=ModelRoute(
                provider="azure_anthropic",
                model="case-video-claude",
                task_family="remotion",
                endpoint="https://example.services.ai.azure.com/anthropic/v1/messages",
                api_key_env="TEST_AZURE_ANTHROPIC_KEY",
                api_version="2023-06-01",
                request_model="case-video-claude",
            ),
            general_route=ModelRoute(
                provider="openai",
                model="gpt-5.5",
                task_family="general",
                base_url="https://api.openai.test/v1",
                api_key_env="TEST_OPENAI_KEY",
                request_model="gpt-5.5",
                auth_mode="bearer",
            ),
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    @patch.dict(
        os.environ,
        {"TEST_AZURE_ANTHROPIC_KEY": "anthropic-secret", "TEST_OPENAI_KEY": "openai-secret"},
        clear=False,
    )
    def test_narration_uses_only_azure_anthropic_messages_api(self) -> None:
        editorial = {
            "version": "1",
            "title": "一次销售管理转型如何落地",
            "narration": "这里是销售不复杂。团队从事实出发，明确责任并推进执行。",
            "change_summary": "完成初稿",
            "addressed_issue_ids": [],
        }
        captured: dict[str, object] = {}

        def fake_post(url: str, **kwargs: object) -> FakeResponse:
            captured.update({"url": url, **kwargs})
            return FakeResponse(
                {
                    "id": "msg_test",
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "emit_contract_output",
                            "input": editorial,
                        }
                    ],
                    "usage": {"input_tokens": 10, "output_tokens": 20},
                }
            )

        with patch("server.app.services.model_gateway.httpx.post", side_effect=fake_post):
            output = ModelGateway(self.settings).run_json(
                "narration.compose",
                "v1",
                {"task": "narration.compose", "context": {"project_name": "测试"}},
            )

        self.assertEqual(output, editorial)
        self.assertEqual(captured["url"], self.settings.narration_route.endpoint)
        headers = captured["headers"]
        self.assertIsInstance(headers, dict)
        self.assertEqual(headers["x-api-key"], "anthropic-secret")
        self.assertEqual(headers["anthropic-version"], "2023-06-01")
        self.assertNotIn("Authorization", headers)
        payload = captured["json"]
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload["model"], "case-video-claude")
        self.assertEqual(payload["tool_choice"], {"type": "tool", "name": "emit_contract_output"})
        self.assertEqual(payload["tools"][0]["input_schema"]["$id"], "urn:case-video:editorial:v1")

    @patch.dict(
        os.environ,
        {"TEST_AZURE_ANTHROPIC_KEY": "anthropic-secret", "TEST_OPENAI_KEY": "openai-secret"},
        clear=False,
    )
    def test_normalizes_numeric_contract_version_without_cross_model_repair(self) -> None:
        editorial = {
            "version": 1,
            "title": "一次销售管理转型如何落地",
            "narration": "这里是销售不复杂。团队从事实出发，明确责任并推进执行。",
            "change_summary": "完成初稿",
            "addressed_issue_ids": [],
        }

        def fake_post(url: str, **kwargs: object) -> FakeResponse:
            del url, kwargs
            return FakeResponse(
                {
                    "id": "msg_numeric_version",
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "emit_contract_output",
                            "input": editorial,
                        }
                    ],
                    "usage": {"input_tokens": 10, "output_tokens": 20},
                }
            )

        with patch("server.app.services.model_gateway.httpx.post", side_effect=fake_post) as mocked:
            output = ModelGateway(self.settings).run_json(
                "narration.compose",
                "v1",
                {"task": "narration.compose", "context": {"project_name": "测试"}},
            )

        self.assertEqual(output["version"], "1")
        self.assertEqual(mocked.call_count, 1)

    @patch.dict(
        os.environ,
        {"TEST_AZURE_ANTHROPIC_KEY": "anthropic-secret", "TEST_OPENAI_KEY": "openai-secret"},
        clear=False,
    )
    def test_general_tasks_use_only_gpt_55_responses_api(self) -> None:
        case_model = {
            "version": "1",
            "actors": [{"name": "销售团队", "role": "案例主体"}],
            "situation": "团队需要统一客户行动方案。",
            "conflict": "责任和节奏尚未统一。",
            "turning_points": ["团队核对事实并明确责任。"],
            "outcome": "团队形成可执行方案。",
            "lessons": ["先形成事实共识。"],
            "numbers": [],
            "source_refs": ["source-1"],
            "uncertainties": [],
        }
        captured: dict[str, object] = {}

        def fake_post(url: str, **kwargs: object) -> FakeResponse:
            captured.update({"url": url, **kwargs})
            return FakeResponse(
                {
                    "id": "resp_test",
                    "output_text": json.dumps(case_model, ensure_ascii=False),
                    "usage": {"input_tokens": 11, "output_tokens": 22},
                }
            )

        with patch("server.app.services.model_gateway.httpx.post", side_effect=fake_post):
            output = ModelGateway(self.settings).run_json(
                "case.model",
                "v1",
                {"task": "case.model", "context": {"source_refs": ["source-1"]}},
            )

        self.assertEqual(output, case_model)
        self.assertEqual(captured["url"], "https://api.openai.test/v1/responses")
        headers = captured["headers"]
        self.assertIsInstance(headers, dict)
        self.assertEqual(headers["Authorization"], "Bearer openai-secret")
        self.assertNotIn("x-api-key", headers)
        payload = captured["json"]
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload["model"], "gpt-5.5")
        self.assertFalse(payload["store"])
        self.assertEqual(payload["text"]["format"]["type"], "json_schema")
        self.assertEqual(payload["text"]["format"]["schema"]["$id"], "urn:case-video:case-model:v1")

    @patch.dict(
        os.environ,
        {"TEST_AZURE_OPENAI_KEY": "azure-openai-secret"},
        clear=False,
    )
    def test_general_tasks_support_azure_openai_api_key_authentication(self) -> None:
        azure_settings = replace(
            self.settings,
            general_route=replace(
                self.settings.general_route,
                base_url="https://example.cognitiveservices.azure.com/openai/v1",
                api_key_env="TEST_AZURE_OPENAI_KEY",
                auth_mode="api-key",
            ),
        )
        case_model = {
            "version": "1",
            "actors": [{"name": "销售团队", "role": "案例主体"}],
            "situation": "团队需要统一客户行动方案。",
            "conflict": "责任和节奏尚未统一。",
            "turning_points": ["团队核对事实并明确责任。"],
            "outcome": "团队形成可执行方案。",
            "lessons": ["先形成事实共识。"],
            "numbers": [],
            "source_refs": ["source-1"],
            "uncertainties": [],
        }
        captured: dict[str, object] = {}

        def fake_post(url: str, **kwargs: object) -> FakeResponse:
            captured.update({"url": url, **kwargs})
            return FakeResponse(
                {
                    "id": "resp_azure_test",
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": json.dumps(case_model, ensure_ascii=False),
                                }
                            ],
                        }
                    ],
                    "usage": {"input_tokens": 11, "output_tokens": 22},
                }
            )

        with patch("server.app.services.model_gateway.httpx.post", side_effect=fake_post):
            output = ModelGateway(azure_settings).run_json(
                "case.model",
                "v1",
                {"task": "case.model", "context": {"source_refs": ["source-1"]}},
            )

        self.assertEqual(output, case_model)
        self.assertEqual(
            captured["url"],
            "https://example.cognitiveservices.azure.com/openai/v1/responses",
        )
        headers = captured["headers"]
        self.assertIsInstance(headers, dict)
        self.assertEqual(headers["api-key"], "azure-openai-secret")
        self.assertNotIn("Authorization", headers)

    @patch.dict(
        os.environ,
        {
            "CASE_VIDEO_GENERAL_BASE_URL": "",
            "CASE_VIDEO_GENERAL_AUTH_MODE": "",
            "CASE_VIDEO_GENERAL_API_KEY": "",
            "OPENAI_API_KEY": "",
            "AZURE_OPENAI_ENDPOINT": "https://configured.cognitiveservices.azure.com/openai/v1",
            "AZURE_OPENAI_API_KEY": "configured-azure-key",
            "LLM_BASE_URL": "https://not-a-model.example.invalid/v1",
        },
        clear=False,
    )
    def test_settings_prefer_azure_openai_endpoint_and_ignore_legacy_llm_base_url(self) -> None:
        settings = load_settings()
        self.assertEqual(
            settings.general_route.base_url,
            "https://configured.cognitiveservices.azure.com/openai/v1",
        )
        self.assertEqual(settings.general_route.auth_mode, "api-key")
        self.assertEqual(settings.general_route.api_key_env, "AZURE_OPENAI_API_KEY")

    @patch.dict(
        os.environ,
        {
            "CASE_VIDEO_GENERAL_BASE_URL": "",
            "CASE_VIDEO_GENERAL_AUTH_MODE": "",
            "AZURE_OPENAI_ENDPOINT": (
                "https://configured.openai.azure.com/openai/deployments/legacy/chat/completions"
                "?api-version=2024-10-21"
            ),
            "AZURE_OPENAI_API_KEY": "configured-azure-key",
        },
        clear=False,
    )
    def test_settings_upgrade_legacy_azure_deployment_url_to_responses_base(self) -> None:
        settings = load_settings()
        self.assertEqual(
            settings.general_route.base_url,
            "https://configured.openai.azure.com/openai/v1",
        )
        self.assertEqual(settings.general_route.request_model, "gpt-5.5")
        self.assertEqual(settings.general_route.auth_mode, "api-key")

    @patch.dict(
        os.environ,
        {
            "CASE_VIDEO_GENERAL_BASE_URL": "",
            "AZURE_OPENAI_ENDPOINT": "https://configured.openai.azure.com/openai/v1/responses",
            "AZURE_OPENAI_API_KEY": "configured-azure-key",
        },
        clear=False,
    )
    def test_settings_strip_responses_suffix_from_azure_endpoint(self) -> None:
        settings = load_settings()
        self.assertEqual(
            settings.general_route.base_url,
            "https://configured.openai.azure.com/openai/v1",
        )

    def test_rejects_unknown_general_authentication_mode(self) -> None:
        invalid = replace(
            self.settings,
            general_route=replace(self.settings.general_route, auth_mode="query-string"),
        )
        with self.assertRaisesRegex(ModelGatewayError, "bearer or api-key"):
            ModelGateway(invalid).validate_required_routes(require_provider_config=False)

    @patch.dict(
        os.environ,
        {"TEST_AZURE_ANTHROPIC_KEY": "anthropic-secret", "TEST_OPENAI_KEY": "openai-secret"},
        clear=False,
    )
    def test_frame_review_sends_pixels_as_images_without_duplicating_base64_in_text(self) -> None:
        review = {
            "version": "1",
            "verdict": "pass",
            "summary": "代表帧实现了声明的导演意图。",
            "scene_reviews": [
                {
                    "scene_id": "scene-001",
                    "frame_ids": ["frame-001"],
                    "intent_alignment": 5,
                    "hierarchy": 5,
                    "legibility": 5,
                    "density": 4,
                    "assessment": "焦点、层级和密度与导演合同一致。",
                }
            ],
            "issues": [],
        }
        encoded = (
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8A"
            "AQUBAScY42YAAAAASUVORK5CYII="
        )
        captured: dict[str, object] = {}

        def fake_post(url: str, **kwargs: object) -> FakeResponse:
            captured.update({"url": url, **kwargs})
            return FakeResponse(
                {
                    "id": "msg_frame_review",
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "emit_contract_output",
                            "input": review,
                        }
                    ],
                    "usage": {"input_tokens": 21, "output_tokens": 34},
                }
            )

        with patch("server.app.services.model_gateway.httpx.post", side_effect=fake_post):
            output = ModelGateway(self.settings).run_json(
                "remotion.frame-review",
                "v1",
                {
                    "task": "remotion.frame-review",
                    "context": {"frames": [{"frame_id": "frame-001", "scene_id": "scene-001"}]},
                    "media": [
                        {
                            "media_id": "frame-001",
                            "mime_type": "image/png",
                            "data_base64": encoded,
                            "description": "scene-001 representative frame",
                        }
                    ],
                },
            )

        self.assertEqual(output, review)
        self.assertEqual(captured["url"], self.settings.remotion_route.endpoint)
        headers = captured["headers"]
        self.assertIsInstance(headers, dict)
        self.assertEqual(headers["x-api-key"], "anthropic-secret")
        self.assertEqual(headers["anthropic-version"], "2023-06-01")
        self.assertNotIn("Authorization", headers)
        payload = captured["json"]
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload["model"], "case-video-claude")
        self.assertEqual(payload["tool_choice"], {"type": "tool", "name": "emit_contract_output"})
        content = payload["messages"][0]["content"]
        self.assertIsInstance(content, list)
        self.assertEqual(content[0]["type"], "text")
        self.assertNotIn(encoded, content[0]["text"])
        self.assertEqual(content[1]["type"], "image")
        self.assertEqual(
            content[1]["source"],
            {
                "type": "base64",
                "media_type": "image/png",
                "data": encoded,
            },
        )

    def test_every_registered_task_has_a_contract_valid_dry_run(self) -> None:
        dry_settings = replace(self.settings, dry_run=True, require_model_config=False)
        gateway = ModelGateway(dry_settings)
        for spec in TASK_SPECS:
            with self.subTest(task=spec.name):
                payload = {"task": spec.name, "context": {}}
                if spec.require_media:
                    payload["context"] = {
                        "frames": [{"frame_id": "frame-001", "scene_id": "scene-001"}]
                    }
                    payload["media"] = [
                        {
                            "media_id": "frame-001",
                            "mime_type": "image/png",
                            "data_base64": (
                                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8A"
                                "AQUBAScY42YAAAAASUVORK5CYII="
                            ),
                            "description": "dry-run representative frame",
                        }
                    ]
                output = gateway.run_json(spec.name, spec.prompt_version, payload)
                gateway.registry.validate_output(spec.name, output)

    @patch.dict(
        os.environ,
        {"TEST_AZURE_ANTHROPIC_KEY": "anthropic-secret", "TEST_OPENAI_KEY": "openai-secret"},
        clear=False,
    )
    def test_rejects_azure_openai_deployment_url_for_claude(self) -> None:
        invalid = replace(
            self.settings,
            narration_route=replace(
                self.settings.narration_route,
                endpoint=(
                    "https://example.openai.azure.com/openai/deployments/"
                    "case-video-claude/chat/completions"
                ),
            ),
            remotion_route=replace(
                self.settings.remotion_route,
                endpoint=(
                    "https://example.openai.azure.com/openai/deployments/"
                    "case-video-claude/chat/completions"
                ),
            ),
        )
        with self.assertRaisesRegex(ModelGatewayError, "Anthropic Messages endpoint"):
            ModelGateway(invalid).validate_required_routes()

    @patch.dict(
        os.environ,
        {"TEST_AZURE_ANTHROPIC_KEY": "anthropic-secret", "TEST_OPENAI_KEY": "openai-secret"},
        clear=False,
    )
    def test_rejects_underlying_model_id_instead_of_azure_deployment_name(self) -> None:
        invalid = replace(
            self.settings,
            narration_route=replace(self.settings.narration_route, request_model="claude-sonnet-test"),
            remotion_route=replace(self.settings.remotion_route, request_model="claude-sonnet-test"),
        )
        with self.assertRaisesRegex(ModelGatewayError, "deployment case-video-claude"):
            ModelGateway(invalid).validate_required_routes()

    def test_model_cache_reuses_output_and_never_persists_secrets(self) -> None:
        dry_settings = replace(self.settings, dry_run=True, require_model_config=False)
        storage = JobStorage(dry_settings)
        manifest = storage.create_job(
            project_name="模型幂等测试",
            approval_mode=ApprovalMode.editorial,
            idempotency_key="model-cache-job",
            seed_project="seed_case",
        )
        job_id = manifest["job_id"]
        gateway = ModelGateway(dry_settings, storage)
        payload = {"task": "narration.compose", "context": {"project_name": "模型幂等测试"}}

        first = gateway.run_json("narration.compose", "v1", payload, job_id=job_id)
        second = gateway.run_json("narration.compose", "v1", payload, job_id=job_id)

        self.assertEqual(first, second)
        records = [
            json.loads(line)
            for line in (storage.job_root(job_id) / "model_runs.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual([record["status"] for record in records], ["started", "succeeded", "reused"])
        self.assertEqual(records[1]["deployment"], "case-video-claude")
        self.assertEqual(records[1]["transport"], "anthropic_messages")
        serialized = json.dumps(records, ensure_ascii=False)
        self.assertNotIn("anthropic-secret", serialized)
        self.assertNotIn("openai-secret", serialized)
        self.assertNotIn("example.services.ai.azure.com", serialized)
        self.assertNotIn("api.openai.test", serialized)


if __name__ == "__main__":
    unittest.main()
