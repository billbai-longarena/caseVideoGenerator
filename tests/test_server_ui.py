from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from html.parser import HTMLParser
from pathlib import Path

from fastapi.testclient import TestClient

from server.app.core.config import load_settings
from server.app.main import create_app
from server.app.services.queue import InMemoryJobQueue
from server.app.services.storage import JobStorage


class SecurityMarkupParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.inline_scripts = 0
        self.style_tags = 0
        self.inline_handlers: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "script" and not attributes.get("src"):
            self.inline_scripts += 1
        if tag == "style":
            self.style_tags += 1
        self.inline_handlers.extend(name for name, _ in attrs if name.lower().startswith("on"))


class ServerUiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.settings = replace(
            load_settings(),
            data_root=self.root / "jobs",
            seed_projects_root=self.root / "seeds",
            dry_run=True,
            api_token=None,
        )
        self.storage = JobStorage(self.settings)
        self.queue = InMemoryJobQueue()
        self.app = create_app(self.settings, self.storage, self.queue)
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def create_job(self) -> str:
        response = self.client.post(
            "/v1/jobs",
            headers={"Idempotency-Key": "ui-acceptance-job"},
            json={
                "project_name": "UI 验收案例",
                "input_mode": "structured",
                "structured_input": {"fact": "团队需要统一事实、责任和行动。"},
                "approval_mode": "full",
                "target_duration_seconds": {"min": 60, "max": 180},
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        return str(response.json()["job_id"])

    def test_all_ui_pages_use_external_assets_and_security_headers(self) -> None:
        job_id = self.create_job()
        routes = [
            "/jobs",
            "/jobs/new",
            f"/jobs/{job_id}",
            f"/jobs/{job_id}/review/editorial",
            f"/jobs/{job_id}/review/visual",
            f"/jobs/{job_id}/artifacts",
            "/admin/health",
        ]

        for route in routes:
            with self.subTest(route=route):
                response = self.client.get(route)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertIn('src="/static/app.js"', response.text)
                self.assertIn('href="/static/app.css"', response.text)
                self.assertIn('class="skip-link"', response.text)
                self.assertIn("default-src 'self'", response.headers["content-security-policy"])
                self.assertEqual(response.headers["x-content-type-options"], "nosniff")
                parser = SecurityMarkupParser()
                parser.feed(response.text)
                self.assertEqual(parser.inline_scripts, 0)
                self.assertEqual(parser.style_tags, 0)
                self.assertEqual(parser.inline_handlers, [])

        self.assertEqual(self.client.get("/static/app.js").status_code, 200)
        self.assertEqual(self.client.get("/static/app.css").status_code, 200)

    def test_ui_exposes_twenty_one_stage_and_review_interaction_contracts(self) -> None:
        job_id = self.create_job()
        detail = self.client.get(f"/jobs/{job_id}").text
        editorial = self.client.get(f"/jobs/{job_id}/review/editorial").text
        visual = self.client.get(f"/jobs/{job_id}/review/visual").text
        artifacts = self.client.get(f"/jobs/{job_id}/artifacts").text
        script = self.client.get("/static/app.js").text

        self.assertIn("按 21 个受控阶段执行", detail)
        self.assertIn('id="event-connection"', detail)
        self.assertIn('id="retry-job"', detail)
        self.assertIn('id="force-retry-job"', detail)
        self.assertIn('id="stage-count" class="badge neutral">加载中</span>', detail)
        self.assertIn('id="model-editorial"', editorial)
        self.assertIn('id="editorial-history"', editorial)
        self.assertIn('id="editorial-diff"', editorial)
        self.assertIn('id="editorial-state" class="badge neutral">加载中</span>', editorial)
        self.assertIn("Azure Anthropic `case-video-claude`", editorial)
        self.assertIn('id="scene-filter"', visual)
        self.assertIn('id="visual-readiness"', visual)
        self.assertIn('id="model-visual"', visual)
        self.assertIn('id="visual-state" class="badge neutral">加载中</span>', visual)
        self.assertIn('id="scene-mode-note"', visual)
        self.assertIn('id="scene-headline-help"', visual)
        self.assertIn('id="scene-intent" rows="4" required', visual)
        self.assertIn("Azure Anthropic Messages API", visual)
        self.assertIn("正式成片", artifacts)
        self.assertIn("beforeunload", script)
        self.assertIn("events?follow=true&after=${lastSequence}", script)
        self.assertIn('addEventListener("offline"', script)
        self.assertIn('addEventListener("online"', script)
        self.assertIn("恢复网络后将自动重连", script)
        self.assertIn("sceneHeadlineText", script)
        self.assertIn("sceneRequiresHeadline", script)
        self.assertIn("editorial 场景以画面叙事为主，可以不显示屏幕标题。", script)
        self.assertIn("delete scene.headline", script)
        self.assertIn('scene.headline = {text: value, reveal: "perClause", accent: []}', script)
        self.assertIn("sceneDirectorialIntent", script)
        self.assertIn("sceneKeywordTexts", script)
        self.assertIn("model-revisions", script)
        self.assertIn("model-revision-requests", script)
        self.assertIn("function sleep", script)
        self.assertIn("trapFocus", script)
        self.assertIn("submit.focus()", script)
        self.assertIn("trigger.focus()", script)
        self.assertNotIn("innerHTML", script)

    def test_capabilities_publish_fixed_routes_without_client_override(self) -> None:
        response = self.client.get("/v1/capabilities")
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertFalse(payload["model_overrides_allowed"])
        self.assertEqual(payload["job"]["default_duration_seconds"], {"min": 240, "max": 420})
        routes = payload["model_routes"]
        self.assertEqual(routes["narration"]["provider"], "azure_anthropic")
        self.assertEqual(routes["narration"]["model"], "case-video-claude")
        self.assertEqual(routes["narration"]["transport"], "anthropic_messages")
        self.assertEqual(routes["remotion"]["provider"], "azure_anthropic")
        self.assertEqual(routes["general"]["model"], "gpt-5.5")
        self.assertNotIn("endpoint", response.text)
        self.assertNotIn("api_key", response.text)

    def test_public_manifest_redacts_private_stage_and_error_details(self) -> None:
        job_id = self.create_job()

        def mutation(manifest: dict[str, object]) -> None:
            manifest["private_secret"] = "never-public"
            manifest["stage_runs"] = {
                "editorial.compose": {
                    "stage": "editorial.compose",
                    "display": "生成标题与旁白",
                    "status": "failed",
                    "error_code": "model_provider_error",
                    "message": "模型服务暂时不可用",
                    "command": ["--api-key", "never-public"],
                    "provider_response": "never-public",
                }
            }
            manifest["error"] = {
                "error_id": "err_public123",
                "stage": "editorial.compose",
                "code": "model_provider_error",
                "message": "模型服务暂时不可用",
                "traceback": "never-public",
            }

        self.storage.mutate_manifest(job_id, mutation)
        response = self.client.get(f"/v1/jobs/{job_id}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn("never-public", response.text)
        payload = response.json()
        self.assertEqual(payload["error"]["error_id"], "err_public123")
        self.assertNotIn("traceback", payload["error"])
        self.assertNotIn("command", payload["stage_runs"]["editorial.compose"])

    def test_sse_resumes_after_last_event_id_without_duplicates(self) -> None:
        job_id = self.create_job()
        all_events = self.storage.read_events(job_id)
        self.assertGreaterEqual(len(all_events), 2)
        cursor = int(all_events[0]["seq"])
        response = self.client.get(
            f"/v1/jobs/{job_id}/events",
            headers={"Accept": "text/event-stream", "Last-Event-ID": str(cursor)},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("retry: 2000", response.text)
        self.assertNotIn(f"id: {cursor}\n", response.text)
        for event in all_events[1:]:
            self.assertEqual(response.text.count(f"id: {event['seq']}\n"), 1)

        invalid = self.client.get(
            f"/v1/jobs/{job_id}/events",
            headers={"Accept": "text/event-stream", "Last-Event-ID": "not-an-integer"},
        )
        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(invalid.json()["code"], "request_invalid")

    def test_dry_run_video_is_never_marked_as_formal_delivery(self) -> None:
        job_id = self.create_job()
        video = self.storage.project_root(job_id) / "video" / "final.mp4"
        video.parent.mkdir(parents=True, exist_ok=True)
        video.write_bytes(b"dry-run-video")

        def mutation(manifest: dict[str, object]) -> None:
            manifest["status"] = "succeeded"
            manifest["dry_run"] = True
            manifest["stage_runs"] = {"qa.execute": {"status": "succeeded", "dry_run": True}}

        self.storage.mutate_manifest(job_id, mutation)
        response = self.client.get(f"/v1/jobs/{job_id}/artifacts")
        self.assertEqual(response.status_code, 200, response.text)
        videos = [item for item in response.json()["artifacts"] if item["kind"] == "video"]
        self.assertEqual(len(videos), 1)
        self.assertFalse(videos[0]["formal_delivery"])


if __name__ == "__main__":
    unittest.main()
