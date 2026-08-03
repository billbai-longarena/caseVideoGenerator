from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

from server.app.core.config import load_settings
from server.app.main import create_app
from server.app.services.queue import InMemoryJobQueue
from server.app.services.revisions import DOMAINS, PROGRAM_CLOSER, PROGRAM_OPENER, RevisionService
from server.app.services.storage import JobStorage, atomic_write_json


VALID_BODY = "".join(
    ["测试团队梳理事实，明确责任，并按计划推进客户沟通。" for _ in range(12)]
)
VALID_NARRATION = f"{PROGRAM_OPENER}\n\n{VALID_BODY}\n\n{PROGRAM_CLOSER}"


class RevisionApiTest(unittest.TestCase):
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
        self.revisions = self.app.state.revisions

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def create_job(
        self,
        *,
        approval_mode: str = "full",
        title: str = "把事实、责任和行动连成一条线",
        narration: str = VALID_NARRATION,
    ) -> str:
        response = self.client.post(
            "/v1/jobs",
            json={
                "project_name": "版本评审测试",
                "input_mode": "structured",
                "structured_input": {"fact": "团队需要形成共同动作。"},
                "approval_mode": approval_mode,
                "target_duration_seconds": {"min": 60, "max": 180},
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        job_id = response.json()["job_id"]
        self.assertEqual(self.queue.dequeue(), job_id)
        self.revisions.create_editorial(
            job_id,
            title=title,
            narration=narration,
            change_summary="初始化文稿版本",
            author_type="model",
            actor="pipeline",
            enforce_concurrency=False,
        )
        return job_id

    def get_review(self, job_id: str, domain: str = "editorial") -> tuple[dict[str, object], str]:
        response = self.client.get(f"/v1/jobs/{job_id}/reviews/{domain}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["etag"], response.json()["etag"])
        return response.json(), response.headers["etag"]

    def save_editorial(
        self,
        job_id: str,
        review: dict[str, object],
        etag: str,
        *,
        title: str | None = None,
        narration: str | None = None,
        summary: str = "人工修订",
    ):
        return self.client.post(
            f"/v1/jobs/{job_id}/reviews/editorial/revisions",
            headers={"If-Match": etag},
            json={
                "base_revision": review["revision"],
                "title": title or str(review["files"]["title.txt"]).strip(),
                "narration": narration or str(review["files"]["narration.txt"]).strip(),
                "change_summary": summary,
                "actor": "tester",
            },
        )

    def approve(
        self,
        job_id: str,
        domain: str,
        review: dict[str, object],
        etag: str,
        *,
        unsaved: bool = False,
    ):
        return self.client.post(
            f"/v1/jobs/{job_id}/reviews/{domain}/approve",
            headers={"If-Match": etag},
            json={
                "revision": review["revision"],
                "base_revision": review["revision"],
                "has_unsaved_draft": unsaved,
                "actor": "tester",
                "reason": "已核对当前版本",
            },
        )

    def seed_succeeded_stages(self, job_id: str) -> None:
        stages = {
            "editorial.approval",
            "tts.generate",
            "visual.plan",
            "visual.build",
            "visual.repair",
            "visual.approval",
            "assets.generate",
            "render.prepare",
            "render.execute",
            "qa.execute",
            "delivery.finalize",
        }

        def mutation(manifest: dict[str, object]) -> None:
            manifest["stage_runs"] = {stage: {"status": "succeeded"} for stage in stages}

        self.storage.mutate_manifest(job_id, mutation)

    @staticmethod
    def valid_plan(title: str, *, units: int = 2) -> dict[str, object]:
        return {
            "version": "1",
            "cover": {"title": title, "proof": "基于当前旁白"},
            "brand": "销售不复杂",
            "subtitleLabel": "销售不复杂",
            "scenes": [
                {
                    "scene_id": "scene-001",
                    "atUnit": 0,
                    "units": units,
                    "layout": "cover",
                    "headline": title,
                    "kicker": "案例开场",
                    "visual_intent": "管理者剪影与留白承载标题。",
                    "keywords": ["事实", "责任", "行动"],
                    "reuse": False,
                    "allowBackgroundReuse": False,
                }
            ],
        }

    def test_review_exposes_exact_revision_etag_and_immutable_files(self) -> None:
        job_id = self.create_job()
        review, etag = self.get_review(job_id)

        self.assertEqual(review["revision"], "editorial-r0001")
        self.assertEqual(review["etag"], etag)
        self.assertTrue(review["can_approve"])
        self.assertIn(PROGRAM_OPENER, review["files"]["narration.txt"])
        revision = self.client.get(
            f"/v1/jobs/{job_id}/revisions/editorial/{review['revision']}"
        )
        self.assertEqual(revision.status_code, 200, revision.text)
        self.assertEqual(revision.json()["metadata"]["etag"], etag.strip('"'))

    def test_title_only_change_preserves_tts_and_invalidates_visual_outputs(self) -> None:
        job_id = self.create_job()
        self.seed_succeeded_stages(job_id)
        review, etag = self.get_review(job_id)

        saved = self.save_editorial(job_id, review, etag, title="责任落地后，销售团队发生了什么")
        self.assertEqual(saved.status_code, 200, saved.text)
        manifest = self.storage.read_manifest(job_id)

        self.assertEqual(manifest["stage_runs"]["tts.generate"]["status"], "succeeded")
        self.assertEqual(manifest["stage_runs"]["editorial.approval"]["status"], "succeeded")
        for stage in ("visual.plan", "render.execute", "qa.execute", "delivery.finalize"):
            self.assertEqual(manifest["stage_runs"][stage]["status"], "invalidated")
        latest = manifest["invalidations"][-1]
        self.assertEqual(latest["changes"], ["title"])
        self.assertNotIn("tts.generate", latest["stages"])

    def test_narration_change_invalidates_tts_and_all_paid_downstream_work(self) -> None:
        job_id = self.create_job()
        self.seed_succeeded_stages(job_id)
        review, etag = self.get_review(job_id)
        revised = VALID_NARRATION.replace(VALID_BODY, VALID_BODY + "团队同时复核了时间点。")

        saved = self.save_editorial(job_id, review, etag, narration=revised)
        self.assertEqual(saved.status_code, 200, saved.text)
        manifest = self.storage.read_manifest(job_id)
        for stage in (
            "editorial.approval",
            "tts.generate",
            "visual.plan",
            "assets.generate",
            "render.execute",
            "qa.execute",
            "delivery.finalize",
        ):
            self.assertEqual(manifest["stage_runs"][stage]["status"], "invalidated")
        self.assertEqual(manifest["approved_revisions"]["editorial"], None)
        self.assertEqual(manifest["approved_revisions"]["visual_plan"], None)

    def test_two_browser_stale_save_returns_merge_safe_conflict(self) -> None:
        job_id = self.create_job()
        browser_a, original_etag = self.get_review(job_id)
        browser_b = json.loads(json.dumps(browser_a, ensure_ascii=False))

        first = self.save_editorial(job_id, browser_a, original_etag, title="浏览器甲保存的新标题")
        self.assertEqual(first.status_code, 200, first.text)
        second = self.save_editorial(job_id, browser_b, original_etag, title="浏览器乙的过期标题")

        self.assertEqual(second.status_code, 409, second.text)
        payload = second.json()
        self.assertEqual(payload["code"], "revision_conflict")
        self.assertEqual(payload["current_revision"], first.json()["revision"])
        self.assertEqual(payload["current_etag"], first.json()["etag"])
        self.assertEqual(payload["reload_url"], f"/v1/jobs/{job_id}/reviews/editorial")

    def test_approval_requires_saved_current_non_blocked_revision(self) -> None:
        job_id = self.create_job()
        initial, initial_etag = self.get_review(job_id)

        unsaved = self.approve(job_id, "editorial", initial, initial_etag, unsaved=True)
        self.assertEqual(unsaved.status_code, 409, unsaved.text)
        self.assertEqual(unsaved.json()["code"], "approval_required")

        saved = self.save_editorial(job_id, initial, initial_etag, title="当前可批准的新标题")
        self.assertEqual(saved.status_code, 200, saved.text)
        stale = self.approve(job_id, "editorial", initial, initial_etag)
        self.assertEqual(stale.status_code, 409, stale.text)
        self.assertEqual(stale.json()["code"], "revision_conflict")

        current = saved.json()
        approved = self.approve(job_id, "editorial", current, saved.headers["etag"])
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertTrue(approved.json()["is_approved"])
        self.assertEqual(approved.json()["approved_revision"], current["revision"])
        self.assertEqual(self.queue.position(job_id), 1)
        records = [
            json.loads(line)
            for line in (self.storage.job_root(job_id) / "approvals.jsonl").read_text(
                encoding="utf-8"
            ).splitlines()
        ]
        self.assertEqual(records[-1]["revision"], current["revision"])
        self.assertEqual(records[-1]["action"], "approved")

    def test_blocker_prevents_approval_and_is_returned_to_ui(self) -> None:
        job_id = self.create_job(narration="正文缺少固定开场和固定结尾。")
        review, etag = self.get_review(job_id)
        self.assertFalse(review["can_approve"])
        self.assertGreaterEqual(len(review["blockers"]), 2)

        response = self.approve(job_id, "editorial", review, etag)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["code"], "approval_required")
        self.assertEqual(response.json()["blockers"], review["blockers"])

    def test_rejection_is_append_only_and_current_revision_cannot_be_approved(self) -> None:
        job_id = self.create_job()
        review, etag = self.get_review(job_id)
        rejected = self.client.post(
            f"/v1/jobs/{job_id}/reviews/editorial/reject",
            headers={"If-Match": etag},
            json={
                "revision": review["revision"],
                "base_revision": review["revision"],
                "actor": "reviewer",
                "reason": "标题钩子仍不够具体",
            },
        )
        self.assertEqual(rejected.status_code, 200, rejected.text)
        self.assertTrue(rejected.json()["is_rejected"])
        self.assertFalse(rejected.json()["can_approve"])

        records = [
            json.loads(line)
            for line in (self.storage.job_root(job_id) / "approvals.jsonl").read_text(
                encoding="utf-8"
            ).splitlines()
        ]
        self.assertEqual(records[-1]["action"], "rejected")
        events = self.storage.read_events(job_id)
        self.assertEqual(events[-1]["type"], "editorial.rejected")
        self.assertEqual(events[-1]["stage"], "editorial.approval")

    def test_restore_creates_a_new_revision_without_mutating_history(self) -> None:
        job_id = self.create_job(title="第一版标题")
        first, first_etag = self.get_review(job_id)
        first_metadata_path = (
            self.storage.job_root(job_id)
            / "revisions"
            / "editorial"
            / first["revision"]
            / "metadata.json"
        )
        first_metadata_before = first_metadata_path.read_bytes()
        second_response = self.save_editorial(job_id, first, first_etag, title="第二版标题")
        self.assertEqual(second_response.status_code, 200, second_response.text)
        second = second_response.json()

        restored = self.client.post(
            f"/v1/jobs/{job_id}/revisions/editorial/{first['revision']}/restore",
            headers={"If-Match": second_response.headers["etag"]},
            json={
                "base_revision": second["revision"],
                "change_summary": "恢复第一版用于重新评审",
                "actor": "tester",
            },
        )
        self.assertEqual(restored.status_code, 200, restored.text)
        self.assertEqual(restored.json()["revision"], "editorial-r0003")
        self.assertEqual(restored.json()["metadata"]["parent_revision"], second["revision"])
        self.assertEqual(restored.json()["files"]["title.txt"].strip(), "第一版标题")
        self.assertEqual(first_metadata_path.read_bytes(), first_metadata_before)
        self.assertEqual(
            restored.json()["metadata"]["content_sha256"], first["metadata"]["content_sha256"]
        )

    def test_worker_compatibility_layer_accepts_distributed_restored_revision_id(self) -> None:
        job_id = self.create_job(title="分布式恢复版本")
        review, _ = self.get_review(job_id)
        legacy_id = str(review["revision"])
        restored_id = f"{legacy_id}-cdd7a308"
        revision_root = self.storage.job_root(job_id) / "revisions" / "editorial"
        (revision_root / legacy_id).rename(revision_root / restored_id)

        metadata_path = revision_root / restored_id / "metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["revision_id"] = restored_id
        atomic_write_json(metadata_path, metadata)

        def mutation(manifest: dict[str, object]) -> None:
            manifest["current_revisions"]["editorial"] = restored_id

        self.storage.mutate_manifest(job_id, mutation)
        worker_revisions = RevisionService(
            self.storage,
            revision_namespace="job-0123456789ab",
        )

        restored = worker_revisions.get_revision(job_id, "editorial", restored_id)
        self.assertEqual(restored["metadata"]["revision_id"], restored_id)
        self.assertEqual(
            worker_revisions._next_revision_number(job_id, DOMAINS["editorial"]),
            2,
        )

    def test_model_revision_uses_claude_route_and_independent_gpt_review(self) -> None:
        job_id = self.create_job()
        review, etag = self.get_review(job_id)
        response = self.client.post(
            f"/v1/jobs/{job_id}/reviews/editorial/model-revisions",
            headers={"If-Match": etag},
            json={
                "base_revision": review["revision"],
                "feedback": "把责任落实的过程讲得更具体。",
                "issues": [],
                "change_summary": "根据人工意见修订",
                "actor": "reviewer",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["metadata"]["author_type"], "model")
        runs = [
            json.loads(line)
            for line in self.storage.model_runs_path(job_id).read_text(encoding="utf-8").splitlines()
        ]
        succeeded = {item["task"]: item for item in runs if item["status"] == "succeeded"}
        self.assertEqual(succeeded["narration.rewrite"]["provider"], "azure_anthropic")
        self.assertEqual(succeeded["narration.rewrite"]["model"], "case-video-claude")
        self.assertEqual(succeeded["narration.rewrite"]["transport"], "anthropic_messages")
        self.assertEqual(succeeded["editorial.review"]["provider"], "openai")
        self.assertEqual(succeeded["editorial.review"]["model"], "gpt-5.5")

    def test_visual_plan_readiness_blocks_overlap_then_allows_exact_approval(self) -> None:
        job_id = self.create_job()
        editorial, editorial_etag = self.get_review(job_id)
        approved_editorial = self.approve(job_id, "editorial", editorial, editorial_etag)
        self.assertEqual(approved_editorial.status_code, 200, approved_editorial.text)
        self.assertEqual(self.queue.dequeue(), job_id)

        atomic_write_json(
            self.storage.project_root(job_id) / "narration.timeline.json",
            {
                "duration": 2.0,
                "units": [
                    {"index": 1, "text": "甲", "start": 0.0, "end": 1.0},
                    {"index": 2, "text": "乙", "start": 1.0, "end": 2.0},
                ],
            },
        )
        title = str(editorial["files"]["title.txt"]).strip()
        invalid_plan = self.valid_plan(title)
        invalid_plan["scenes"].append(
            {
                "scene_id": "scene-001",
                "atUnit": 1,
                "units": 1,
                "layout": "summary",
                "headline": "重复且重叠的场景",
                "visual_intent": "用于验证阻断规则。",
                "keywords": [],
                "reuse": False,
                "allowBackgroundReuse": False,
            }
        )
        self.revisions.create_visual_plan(
            job_id,
            plan=invalid_plan,
            change_summary="创建待修复视觉计划",
            author_type="model",
            actor="pipeline",
            enforce_concurrency=False,
        )
        invalid, invalid_etag = self.get_review(job_id, "visual-plan")
        blocker_codes = {item["code"] for item in invalid["blockers"]}
        self.assertIn("duplicate_scene_id", blocker_codes)
        self.assertIn("unit_overlap", blocker_codes)
        blocked = self.approve(job_id, "visual-plan", invalid, invalid_etag)
        self.assertEqual(blocked.status_code, 409, blocked.text)

        valid = self.client.post(
            f"/v1/jobs/{job_id}/reviews/visual-plan/revisions",
            headers={"If-Match": invalid_etag},
            json={
                "base_revision": invalid["revision"],
                "plan": self.valid_plan(title),
                "image_prompts": {"version": "1", "prompts": []},
                "change_summary": "修复 unit 覆盖和场景编号",
                "actor": "tester",
            },
        )
        self.assertEqual(valid.status_code, 200, valid.text)
        self.assertEqual(valid.json()["blockers"], [])
        approved = self.approve(job_id, "visual-plan", valid.json(), valid.headers["etag"])
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertTrue(approved.json()["is_approved"])
        events = self.storage.read_events(job_id)
        self.assertEqual(events[-1]["type"], "visual-plan.approved")
        self.assertEqual(events[-1]["stage"], "visual.approval")


if __name__ == "__main__":
    unittest.main()
