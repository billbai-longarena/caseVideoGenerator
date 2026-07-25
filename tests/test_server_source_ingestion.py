from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient
from pypdf import PdfWriter

from server.app.core.config import load_settings
from server.app.core.errors import AppError
from server.app.main import create_app
from server.app.services.queue import InMemoryJobQueue
from server.app.services.source_ingestion import SourceIngestion
from server.app.services.storage import JobStorage


class SourceIngestionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.settings = replace(
            load_settings(),
            data_root=self.root / "jobs",
            seed_projects_root=self.root / "seeds",
            dry_run=True,
            api_token=None,
            max_upload_bytes=1024 * 1024,
            max_external_excerpt_chars=64,
        )
        self.storage = JobStorage(self.settings)
        self.queue = InMemoryJobQueue()
        self.app = create_app(self.settings, self.storage, self.queue)
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def upload(self, filename: str, content: bytes, media_type: str) -> str:
        created = self.client.post(
            "/v1/uploads",
            json={
                "filename": filename,
                "size_bytes": len(content),
                "media_type": media_type,
                "sha256": hashlib.sha256(content).hexdigest(),
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        upload_id = created.json()["upload_id"]
        completed = self.client.put(
            f"/v1/uploads/{upload_id}",
            content=content,
            headers={"content-type": "application/octet-stream"},
        )
        self.assertEqual(completed.status_code, 200, completed.text)
        self.assertEqual(completed.json()["status"], "complete")
        return upload_id

    def test_source_upload_job_and_local_extraction_boundary(self) -> None:
        content = ("这是完整案例材料。" * 40).encode("utf-8")
        upload_id = self.upload("case.md", content, "text/markdown")
        response = self.client.post(
            "/v1/jobs",
            headers={"Idempotency-Key": "source-request-0001"},
            json={
                "project_name": "源材料案例",
                "input_mode": "source",
                "upload_ids": [upload_id],
                "approval_mode": "editorial",
                "target_duration_seconds": {"min": 240, "max": 420},
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        job_id = response.json()["job_id"]
        self.assertEqual(self.client.get(f"/v1/uploads/{upload_id}").json()["bound_job_id"], job_id)

        result = SourceIngestion(self.settings, self.storage, self.app.state.uploads).ingest(job_id)
        self.assertEqual(result["source_manifest"]["files"][0]["extraction_status"], "succeeded")
        self.assertLessEqual(result["boundary"]["total_excerpt_chars"], 64)
        extracted = (self.storage.job_root(job_id) / "source" / "extracted" / "src_0001.txt").read_text(
            encoding="utf-8"
        )
        self.assertGreater(len(extracted), result["boundary"]["total_excerpt_chars"])
        self.assertNotIn(extracted, json.dumps(result["boundary"], ensure_ascii=False))

    def test_scanned_pdf_is_an_explicit_ocr_error(self) -> None:
        pdf = self.root / "blank.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        with pdf.open("wb") as handle:
            writer.write(handle)
        upload_id = self.upload("blank.pdf", pdf.read_bytes(), "application/pdf")
        response = self.client.post(
            "/v1/jobs",
            json={"project_name": "扫描材料", "input_mode": "source", "upload_ids": [upload_id]},
        )
        self.assertEqual(response.status_code, 200, response.text)
        with self.assertRaises(AppError) as raised:
            SourceIngestion(self.settings, self.storage, self.app.state.uploads).ingest(response.json()["job_id"])
        self.assertEqual(raised.exception.code, "source_ocr_required")

    def test_structured_input_is_normalized_without_upload(self) -> None:
        long_private_value = "只应保留在本地的完整结构化原文" * 20
        response = self.client.post(
            "/v1/jobs",
            json={
                "project_name": "结构化案例",
                "input_mode": "structured",
                "structured_input": {
                    "customer": "甲公司",
                    "conflict": "渠道责任不清",
                    "private_notes": long_private_value,
                },
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        job_id = response.json()["job_id"]
        result = SourceIngestion(self.settings, self.storage, self.app.state.uploads).ingest(job_id)
        self.assertEqual(result["case_inputs"]["structured_fields"]["inline"]["customer"], "甲公司")
        self.assertEqual(result["source_manifest"]["files"][0]["upload_id"], None)
        boundary_text = json.dumps(result["boundary"], ensure_ascii=False)
        self.assertNotIn(long_private_value, boundary_text)
        self.assertLessEqual(result["boundary"]["total_excerpt_chars"], 64)

    def test_idempotency_key_rejects_a_different_body(self) -> None:
        first = self.client.post(
            "/v1/jobs",
            headers={"Idempotency-Key": "same-key-different-body"},
            json={
                "project_name": "请求一",
                "input_mode": "structured",
                "structured_input": {"fact": "A"},
            },
        )
        self.assertEqual(first.status_code, 200, first.text)
        conflict = self.client.post(
            "/v1/jobs",
            headers={"Idempotency-Key": "same-key-different-body"},
            json={
                "project_name": "请求二",
                "input_mode": "structured",
                "structured_input": {"fact": "B"},
            },
        )
        self.assertEqual(conflict.status_code, 409, conflict.text)
        self.assertEqual(conflict.json()["code"], "idempotency_conflict")

    def test_upload_rejects_paths_binary_text_and_source_zip(self) -> None:
        bad_name = self.client.post(
            "/v1/uploads",
            json={"filename": "../case.txt", "size_bytes": 1, "media_type": "text/plain"},
        )
        self.assertEqual(bad_name.status_code, 422)

        upload_id = self.client.post(
            "/v1/uploads",
            json={"filename": "binary.txt", "size_bytes": 3, "media_type": "text/plain"},
        ).json()["upload_id"]
        binary = self.client.put(f"/v1/uploads/{upload_id}", content=b"a\x00b")
        self.assertEqual(binary.status_code, 400, binary.text)
        self.assertEqual(binary.json()["code"], "source_invalid")


if __name__ == "__main__":
    unittest.main()
