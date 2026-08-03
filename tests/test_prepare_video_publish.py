from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.prepare_video_publish import (
    MediaInfo,
    Publication,
    PublishError,
    discover_projects,
    infer_series_and_sequence,
    link_or_copy,
    resolve_publication,
    sanitize_component,
    stage_publications,
    validate_delivery_pair,
    write_manifests,
)


class PrepareVideoPublishTests(unittest.TestCase):
    def test_infers_known_series_and_sequence(self) -> None:
        self.assertEqual(infer_series_and_sequence("fde_ep01_fmcg_excel_revert"), ("fde", 1))
        self.assertEqual(infer_series_and_sequence("sales_management_case20_video"), ("sales-management", 20))

    def test_sanitizes_cross_platform_filename_characters(self) -> None:
        self.assertEqual(sanitize_component('客户/总部：谁说"停"?'), "客户／总部：谁说“停”？")
        with self.assertRaises(PublishError):
            sanitize_component("   ")

    def test_publication_json_overrides_inference_and_builds_s_number(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "custom_project"
            project.mkdir()
            (project / "title.txt").write_text("一个具体标题\n", encoding="utf-8")
            (project / "publication.json").write_text(
                json.dumps(
                    {
                        "series": "custom-column",
                        "seriesLabel": "自定义栏目",
                        "sequence": 3,
                        "sequenceWidth": 2,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            publication = resolve_publication(project)

            self.assertIsNotNone(publication)
            assert publication is not None
            self.assertEqual(publication.series, "custom-column")
            self.assertEqual(publication.series_label, "自定义栏目")
            self.assertEqual(publication.output_folder, "自定义栏目")
            self.assertEqual(publication.filename, "S03_一个具体标题.mp4")

    def test_disabled_publication_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "fde_ep01_test"
            project.mkdir()
            (project / "publication.json").write_text('{"enabled": false}', encoding="utf-8")
            self.assertIsNone(resolve_publication(project))

    def test_reserved_topic_folder_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "fde_ep01_test"
            project.mkdir()
            (project / "title.txt").write_text("标题\n", encoding="utf-8")
            (project / "publication.json").write_text(
                '{"outputFolder": "_masters"}', encoding="utf-8"
            )
            with self.assertRaisesRegex(PublishError, "reserved"):
                resolve_publication(project)

    def test_discovery_only_returns_rendered_matching_projects(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            rendered = root / "fde_ep01_ready"
            (rendered / "video").mkdir(parents=True)
            (rendered / "video" / "case_video.mp4").write_bytes(b"video")
            unrendered = root / "fde_ep02_pending"
            unrendered.mkdir()
            other = root / "sales_case01_video"
            (other / "video").mkdir(parents=True)
            (other / "video" / "case_video.mp4").write_bytes(b"video")

            self.assertEqual(discover_projects(root, ["fde_ep*"]), [rendered])

    def test_manifest_outputs_are_sorted_by_topic_and_numeric_sequence(self) -> None:
        item_ten = {
            "series": "fde",
            "series_label": "FDE不复杂",
            "series_folder": "FDE不复杂",
            "sequence": 10,
            "title": "标题十",
            "filename": "S010_标题十.mp4",
            "project": "output/fde_ep10",
            "upload_path": "FDE不复杂/S010_标题十.mp4",
            "master_path": "",
            "duration_seconds": 123.4,
            "size_bytes": 456,
            "width": 1920,
            "height": 1080,
            "fps": 30.0,
            "sha256": "abc",
        }
        item_two = {
            **item_ten,
            "sequence": 2,
            "title": "标题二",
            "filename": "S002_标题二.mp4",
            "project": "output/fde_ep02",
            "upload_path": "FDE不复杂/S002_标题二.mp4",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_manifests(root, [item_ten, item_two])

            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["count"], 2)
            self.assertEqual([item["sequence"] for item in manifest["items"]], [2, 10])
            self.assertIn("S010_标题十.mp4", (root / "manifest.csv").read_text(encoding="utf-8-sig"))
            self.assertEqual(
                (root / "upload-list.txt").read_text(encoding="utf-8"),
                "FDE不复杂/S002_标题二.mp4\nFDE不复杂/S010_标题十.mp4\n",
            )

    def test_batch_rejects_duplicate_episode_numbers_in_one_topic_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            publications = [
                Publication(
                    project=root / "fde_ep01_a",
                    project_key="output/fde_ep01_a",
                    series="fde",
                    series_label="FDE不复杂",
                    output_folder="FDE不复杂",
                    sequence=1,
                    sequence_width=3,
                    filename_prefix="S",
                    title="标题甲",
                    filename="S001_标题甲.mp4",
                ),
                Publication(
                    project=root / "fde_ep01_b",
                    project_key="output/fde_ep01_b",
                    series="custom-fde-season",
                    series_label="FDE特别季",
                    output_folder="FDE不复杂",
                    sequence=1,
                    sequence_width=3,
                    filename_prefix="S",
                    title="标题乙",
                    filename="S001_标题乙.mp4",
                ),
            ]

            with self.assertRaisesRegex(PublishError, "duplicate episode"):
                stage_publications(
                    publications,
                    publish_root=root / "publish",
                    target_mb=50,
                    include_master=False,
                    force=False,
                    dry_run=True,
                )

    def test_delivery_validation_requires_upload_codecs_and_reasonable_size(self) -> None:
        master = MediaInfo(300, 100_000_000, 1920, 1080, 30, "h264", "aac")
        wrong_codec = MediaInfo(300, 49_000_000, 1920, 1080, 30, "hevc", "aac")
        undersized = MediaInfo(300, 20_000_000, 1920, 1080, 30, "h264", "aac")

        with self.assertRaisesRegex(PublishError, "H.264"):
            validate_delivery_pair(master, wrong_codec, target_bytes=50_000_000)
        with self.assertRaisesRegex(PublishError, "well below"):
            validate_delivery_pair(master, undersized, target_bytes=50_000_000)

    def test_republishing_same_hardlink_leaves_only_the_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.mp4"
            destination = root / "主题" / "S001_标题.mp4"
            temporary = root / ".tmp"
            source.write_bytes(b"video")

            self.assertEqual(
                link_or_copy(source, destination, temp_dir=temporary),
                "hardlink",
            )
            self.assertEqual(
                link_or_copy(source, destination, temp_dir=temporary),
                "hardlink",
            )

            self.assertEqual([path.name for path in destination.parent.iterdir()], [destination.name])
            self.assertEqual(list(temporary.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
