from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

from server.app.core.config import load_settings
from server.app.main import create_app
from server.app.services.pipeline import V2_STAGES, CaseVideoPipeline
from server.app.services.queue import InMemoryJobQueue
from server.app.services.storage import JobStorage


class FullPipelineV2Test(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.settings = replace(
            load_settings(),
            data_root=self.root / "jobs",
            seed_projects_root=self.root / "seeds",
            dry_run=True,
            require_model_config=False,
            api_token=None,
        )
        self.storage = JobStorage(self.settings)
        self.queue = InMemoryJobQueue()
        self.app = create_app(self.settings, self.storage, self.queue)
        self.client = TestClient(self.app)
        self.pipeline = CaseVideoPipeline(
            self.settings,
            self.storage,
            model_gateway=self.app.state.model_gateway,
            revisions=self.app.state.revisions,
            ingestion=self.app.state.ingestion,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def create_job(self, approval_mode: str) -> str:
        response = self.client.post(
            "/v1/jobs",
            json={
                "project_name": f"二十一阶段-{approval_mode}",
                "input_mode": "structured",
                "structured_input": {
                    "customer": "一家需要统一销售节奏的企业",
                    "situation": "销售、交付与管理团队使用不同的信息版本。",
                    "conflict": "客户目标没有被稳定映射到责任和行动。",
                    "outcome": "团队建立事实清单并形成可复核的推进路径。",
                },
                "approval_mode": approval_mode,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        job_id = response.json()["job_id"]
        self.assertEqual(self.queue.dequeue(), job_id)
        manifest = self.storage.read_manifest(job_id)
        self.assertEqual(manifest["target_duration_seconds"], {"min": 240, "max": 420})
        return job_id

    def approve_current(self, job_id: str, domain: str) -> None:
        review = self.client.get(f"/v1/jobs/{job_id}/reviews/{domain}")
        self.assertEqual(review.status_code, 200, review.text)
        payload = review.json()
        approved = self.client.post(
            f"/v1/jobs/{job_id}/reviews/{domain}/approve",
            headers={"If-Match": review.headers["etag"]},
            json={
                "revision": payload["revision"],
                "base_revision": payload["revision"],
                "has_unsaved_draft": False,
                "actor": "pipeline-v2-test",
                "reason": "P0 流水线续跑验收",
            },
        )
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertEqual(self.queue.dequeue(), job_id)

    def model_records(self, job_id: str) -> list[dict[str, object]]:
        return [
            json.loads(line)
            for line in self.storage.model_runs_path(job_id).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def assert_strict_routes(self, job_id: str) -> None:
        succeeded = [item for item in self.model_records(job_id) if item["status"] == "succeeded"]
        claude_tasks = {
            "narration.compose",
            "narration.rewrite",
            "remotion.plan",
            "remotion.repair",
            "remotion.frame-review",
        }
        for item in succeeded:
            if item["task"] in claude_tasks:
                self.assertEqual(item["provider"], "azure_anthropic")
                self.assertEqual(item["model"], "case-video-claude")
                self.assertEqual(item["deployment"], "case-video-claude")
                self.assertEqual(item["transport"], "anthropic_messages")
            else:
                self.assertEqual(item["provider"], "openai")
                self.assertEqual(item["model"], "gpt-5.5")
                self.assertEqual(item["transport"], "openai_responses")

    def test_auto_mode_completes_exact_twenty_one_stage_contract(self) -> None:
        job_id = self.create_job("auto")
        final = self.pipeline.run(job_id)

        self.assertEqual(final["status"], "succeeded", final.get("error"))
        expected = [stage.name for stage in V2_STAGES]
        self.assertEqual([item["name"] for item in final["pipeline_stages"]], expected)
        self.assertTrue(all(final["stage_runs"][name]["status"] == "succeeded" for name in expected))
        first_run_starts = [
            item["stage"]
            for item in self.storage.read_events(job_id)
            if item["type"] == "stage.started"
        ]
        self.assertEqual(first_run_starts, expected)
        self.assertEqual(final["approved_revisions"]["editorial"], final["current_revisions"]["editorial"])
        self.assertEqual(final["approved_revisions"]["visual_plan"], final["current_revisions"]["visual_plan"])
        self.assertTrue((self.storage.job_root(job_id) / "artifact_index.json").is_file())
        self.assertTrue((self.storage.project_root(job_id) / "qa" / "server-delivery-qa.json").is_file())
        self.assertTrue((self.storage.project_root(job_id) / "qa" / "intent-frame-review.json").is_file())
        self.assert_strict_routes(job_id)

        run_counts = {name: final["stage_runs"][name]["run_count"] for name in expected}
        rerun = self.pipeline.run(job_id)
        self.assertEqual(rerun["status"], "succeeded")
        for name in expected:
            self.assertLessEqual(rerun["stage_runs"][name]["run_count"], run_counts[name] + 1)
        events = self.storage.read_events(job_id)
        self.assertTrue(any(item["type"] == "stage.skipped" for item in events))

    def test_editorial_mode_pauses_then_resumes_from_exact_revision(self) -> None:
        job_id = self.create_job("editorial")
        waiting = self.pipeline.run(job_id)

        self.assertEqual(waiting["status"], "waiting_approval")
        self.assertEqual(waiting["stage"], "editorial.approval")
        self.assertTrue(waiting["can_approve"])
        self.assertNotIn("tts.generate", waiting["stage_runs"])

        self.approve_current(job_id, "editorial")
        final = self.pipeline.run(job_id)
        self.assertEqual(final["status"], "succeeded", final.get("error"))
        self.assertEqual(final["stage_runs"]["editorial.approval"]["run_count"], 2)
        self.assertEqual(final["approved_revisions"]["editorial"], final["current_revisions"]["editorial"])

    def test_full_mode_separates_contract_and_rendered_visual_approval(self) -> None:
        job_id = self.create_job("full")
        editorial_wait = self.pipeline.run(job_id)
        self.assertEqual(editorial_wait["stage"], "editorial.approval")

        self.approve_current(job_id, "editorial")
        contract_wait = self.pipeline.run(job_id)
        self.assertEqual(contract_wait["status"], "waiting_approval")
        self.assertEqual(contract_wait["stage"], "visual.contract-approval")
        self.assertTrue(contract_wait["can_approve"])
        self.assertNotIn("assets.generate", contract_wait["stage_runs"])
        contract_revision = contract_wait["current_revisions"]["visual_plan"]

        self.approve_current(job_id, "visual-plan")
        visual_wait = self.pipeline.run(job_id)
        self.assertEqual(visual_wait["status"], "waiting_approval")
        self.assertEqual(visual_wait["stage"], "visual.approval")
        self.assertTrue(visual_wait["can_approve"])
        self.assertEqual(visual_wait["approval_checkpoints"]["visual_contract"], contract_revision)
        self.assertNotEqual(visual_wait["current_revisions"]["visual_plan"], contract_revision)
        self.assertEqual(visual_wait["stage_runs"]["assets.generate"]["run_count"], 1)
        self.assertEqual(visual_wait["stage_runs"]["visual.preview"]["run_count"], 1)
        self.assertEqual(visual_wait["stage_runs"]["visual.intent-review"]["run_count"], 1)

        self.approve_current(job_id, "visual-plan")
        final = self.pipeline.run(job_id)
        self.assertEqual(final["status"], "succeeded", final.get("error"))
        self.assertEqual(final["approved_revisions"]["visual_plan"], final["current_revisions"]["visual_plan"])
        self.assertEqual(final["approval_checkpoints"]["visual_contract"], contract_revision)
        self.assertEqual(final["stage_runs"]["assets.generate"]["run_count"], 1)
        self.assertEqual(final["stage_runs"]["visual.preview"]["run_count"], 1)
        self.assertEqual(final["stage_runs"]["visual.intent-review"]["run_count"], 1)
        approval_events = [
            (item["type"], item["stage"])
            for item in self.storage.read_events(job_id)
            if item["type"] == "visual-plan.approved"
        ]
        self.assertIn(("visual-plan.approved", "visual.contract-approval"), approval_events)
        self.assertIn(("visual-plan.approved", "visual.approval"), approval_events)
        self.assert_strict_routes(job_id)


if __name__ == "__main__":
    unittest.main()
