from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

from server.app.core.config import load_settings
from server.app.main import create_app
from server.app.services.model_gateway import ModelGateway, ModelGatewayError
from server.app.services.pipeline import CaseVideoPipeline
from server.app.services.queue import InMemoryJobQueue
from server.app.services.storage import JobStorage, StorageError


def make_seed_project(root: Path, name: str = "seed_case") -> Path:
    project = root / name
    project.mkdir(parents=True, exist_ok=True)
    (project / "title.txt").write_text("可部署服务器测试案例\n", encoding="utf-8")
    (project / "narration.txt").write_text("这里是销售不复杂。\n\n测试旁白。\n", encoding="utf-8")
    (project / "storyboard_plan.json").write_text(json.dumps({"scenes": []}), encoding="utf-8")
    return project


class ServerAppTest(unittest.TestCase):
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
            max_upload_bytes=1024 * 1024,
        )
        self.storage = JobStorage(self.settings)
        self.queue = InMemoryJobQueue()
        self.client = TestClient(create_app(self.settings, self.storage, self.queue))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def create_seed_job(self, idempotency_key: str = "idem-1") -> dict[str, object]:
        response = self.client.post(
            "/v1/jobs",
            headers={"Idempotency-Key": idempotency_key},
            json={"project_name": "服务器测试", "seed_project": "seed_case"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_create_job_is_idempotent_and_listable(self) -> None:
        first = self.create_seed_job("idem-list")
        second = self.create_seed_job("idem-list")
        self.assertEqual(first["job_id"], second["job_id"])
        self.assertEqual(first["job_url"], f"/jobs/{first['job_id']}")
        self.assertEqual(second["queue_position"], 1)

        listed = self.client.get("/v1/jobs", params={"status": "queued", "q": "服务器"})
        self.assertEqual(listed.status_code, 200, listed.text)
        payload = listed.json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["jobs"][0]["job_id"], first["job_id"])

    def test_create_rejects_empty_phase_a_and_client_model_override(self) -> None:
        empty = self.client.post("/v1/jobs", json={"project_name": "空任务"})
        self.assertEqual(empty.status_code, 400)
        self.assertIn("phase A requires", empty.json()["detail"])

        override = self.client.post(
            "/v1/jobs",
            json={
                "project_name": "模型覆盖",
                "seed_project": "seed_case",
                "model": "other-model",
            },
        )
        self.assertEqual(override.status_code, 422)
        self.assertIn("cannot override", override.json()["detail"])

    def test_auth_can_be_required(self) -> None:
        settings = replace(self.settings, api_token="secret-token")
        client = TestClient(create_app(settings, JobStorage(settings), InMemoryJobQueue()))
        self.assertEqual(client.get("/health/live").status_code, 401)
        self.assertEqual(
            client.get("/health/live", headers={"Authorization": "Bearer secret-token"}).status_code,
            200,
        )

    def test_zip_upload_rejects_path_traversal(self) -> None:
        archive = self.root / "bad.zip"
        with zipfile.ZipFile(archive, "w") as handle:
            handle.writestr("../evil.txt", "evil")
            handle.writestr("title.txt", "title")
            handle.writestr("narration.txt", "narration")
            handle.writestr("storyboard_plan.json", "{}")

        with archive.open("rb") as uploaded:
            response = self.client.post(
                "/v1/jobs",
                data={"project_name": "坏压缩包"},
                files={"project_zip": ("bad.zip", uploaded, "application/zip")},
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn("escapes allowed root", response.json()["detail"])

    def test_dry_run_pipeline_completes_and_exposes_artifact(self) -> None:
        job = self.create_seed_job("idem-pipeline")
        job_id = str(job["job_id"])
        queued_job = self.queue.dequeue()
        self.assertEqual(queued_job, job_id)

        final_manifest = CaseVideoPipeline(self.settings, self.storage).run(job_id)
        self.assertEqual(final_manifest["status"], "succeeded")
        self.assertEqual(final_manifest["overall_progress"], 1.0)
        self.assertTrue(final_manifest["stage_runs"]["rendering"]["dry_run"])

        events = self.client.get(f"/v1/jobs/{job_id}/events").json()["events"]
        self.assertEqual([event["seq"] for event in events], list(range(1, len(events) + 1)))
        self.assertTrue(any(event["type"] == "job.succeeded" for event in events))

        artifacts = self.client.get(f"/v1/jobs/{job_id}/artifacts").json()["artifacts"]
        names = {artifact["name"] for artifact in artifacts}
        self.assertIn("project/qa/server-dry-run-report.json", names)

        blocked = self.client.get(f"/v1/jobs/{job_id}/artifacts/../job_manifest.json")
        self.assertEqual(blocked.status_code, 404)

    def test_model_gateway_routes_and_required_config(self) -> None:
        gateway = ModelGateway(self.settings, self.storage)
        self.assertEqual(gateway.route_for_task("narration.compose").model, "salesnail-cs-46")
        self.assertEqual(gateway.route_for_task("remotion.plan").model, "salesnail-cs-46")
        self.assertEqual(gateway.route_for_task("case.extract").model, "gpt-5.5")

        strict = replace(
            self.settings,
            require_model_config=True,
            dry_run=False,
            narration_route=replace(
                self.settings.narration_route,
                endpoint=None,
                api_key_env="CASE_VIDEO_TEST_MISSING_ANTHROPIC_KEY",
            ),
        )
        with self.assertRaises(ModelGatewayError):
            ModelGateway(strict).validate_required_routes()

    def test_storage_rejects_zip_traversal_directly(self) -> None:
        job = self.create_seed_job("idem-storage")
        archive = self.root / "direct-bad.zip"
        with zipfile.ZipFile(archive, "w") as handle:
            handle.writestr("nested/../../evil.txt", "evil")
        with self.assertRaises(StorageError):
            self.storage.extract_project_zip(str(job["job_id"]), archive)


if __name__ == "__main__":
    unittest.main()
