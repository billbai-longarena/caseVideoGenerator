from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "visual_asset_pool.py"
TAXONOMY = ROOT / "assets" / "visual-pool" / "taxonomy.json"


class VisualAssetPoolTests(unittest.TestCase):
    def make_image(self, path: Path, color: tuple[int, int, int]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (64, 36), color).save(path)

    def make_repo(self, root: Path) -> tuple[Path, Path]:
        repo = root / "repo"
        pool = repo / "assets" / "visual-pool"
        pool.mkdir(parents=True)
        (pool / "taxonomy.json").write_text(TAXONOMY.read_text(encoding="utf-8"), encoding="utf-8")
        project = repo / "output" / "case_one"
        image_path = project / "images" / "sales_watercolor" / "01.png"
        duplicate_path = project / "images" / "sales_watercolor" / "copy.png"
        self.make_image(image_path, (20, 80, 180))
        duplicate_path.write_bytes(image_path.read_bytes())
        prompts = {
            "stylePrefix": "blue-and-yellow editorial watercolor",
            "prompts": [
                {
                    "file": "images/sales_watercolor/01.png",
                    "prompt": "A salesperson visits a customer production line and observes workers and machines, no conventional boardroom.",
                }
            ],
        }
        (project / "image_prompts.json").write_text(json.dumps(prompts), encoding="utf-8")
        storyboard = {
            "title": "工厂拜访",
            "projectType": "sales-case",
            "visualStyle": "bright-editorial-watercolor",
            "scenes": [
                {
                    "id": "s01",
                    "kicker": "现场拜访",
                    "headline": {"text": "销售走进生产线"},
                    "units": [1, 2],
                    "subtitles": [{"unit": 1, "text": "销售来到客户车间观察真实工作。"}],
                    "backgrounds": [{"atUnit": 1, "image": "images/sales_watercolor/01.png"}],
                },
                {
                    "id": "s02",
                    "kicker": "本期总结",
                    "headline": {"text": "把观察带回客户决策"},
                    "units": [3],
                    "subtitles": [{"unit": 3, "text": "这期案例到这里。"}],
                    "backgrounds": [{"atUnit": 3, "image": "images/sales_watercolor/01.png"}],
                }
            ],
        }
        (project / "rich_storyboard.json").write_text(json.dumps(storyboard), encoding="utf-8")
        return repo, pool

    def run_tool(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_build_deduplicates_tags_and_writes_scene_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, pool = self.make_repo(Path(directory))
            result = self.run_tool("build", "--repo-root", str(repo), "--pool-root", str(pool))
            self.assertEqual(result.returncode, 0, result.stderr)
            catalog = json.loads((pool / "catalog.json").read_text(encoding="utf-8"))
            self.assertEqual(catalog["stats"]["sourceImages"], 2)
            self.assertEqual(catalog["stats"]["uniqueAssets"], 1)
            asset = catalog["assets"][0]
            self.assertEqual(len(asset["sources"]), 2)
            self.assertIn("production-floor", asset["tags"]["settings"])
            self.assertIn("sales-visit", asset["tags"]["activities"])
            self.assertNotIn("corporate-boardroom", asset["tags"]["settings"])
            self.assertNotIn("title-stage", asset["tags"]["settings"])
            self.assertTrue((pool / asset["canonicalPath"]).is_file())
            inventory = json.loads((pool / "scene_inventory.json").read_text(encoding="utf-8"))
            self.assertEqual(inventory["stats"]["scenes"], 2)
            self.assertEqual(inventory["scenes"][0]["primarySetting"], "production-floor")

    def test_build_is_deterministic_and_audit_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, pool = self.make_repo(Path(directory))
            first = self.run_tool("build", "--repo-root", str(repo), "--pool-root", str(pool))
            self.assertEqual(first.returncode, 0, first.stderr)
            digest = hashlib.sha256((pool / "catalog.json").read_bytes()).hexdigest()
            second = self.run_tool("build", "--repo-root", str(repo), "--pool-root", str(pool))
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(digest, hashlib.sha256((pool / "catalog.json").read_bytes()).hexdigest())
            audited = self.run_tool("audit", "--pool-root", str(pool))
            self.assertEqual(audited.returncode, 0, audited.stderr)

    def test_search_and_checkout_copy_local_asset_with_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, pool = self.make_repo(Path(directory))
            built = self.run_tool("build", "--repo-root", str(repo), "--pool-root", str(pool))
            self.assertEqual(built.returncode, 0, built.stderr)
            catalog = json.loads((pool / "catalog.json").read_text(encoding="utf-8"))
            asset_id = catalog["assets"][0]["id"]
            searched = self.run_tool(
                "search",
                "工厂",
                "--pool-root",
                str(pool),
                "--setting",
                "产线",
                "--activity",
                "销售拜访",
                "--json",
            )
            self.assertEqual(searched.returncode, 0, searched.stderr)
            results = json.loads(searched.stdout)
            self.assertEqual(results[0]["id"], asset_id)
            destination_project = repo / "output" / "new_case"
            destination_project.mkdir()
            checked_out = self.run_tool(
                "checkout",
                asset_id,
                str(destination_project),
                "--pool-root",
                str(pool),
            )
            self.assertEqual(checked_out.returncode, 0, checked_out.stderr)
            manifest = json.loads((destination_project / "asset_pool_usage.json").read_text(encoding="utf-8"))
            checked_path = destination_project / manifest["assets"][0]["src"]
            self.assertTrue(checked_path.is_file())
            self.assertEqual(hashlib.sha256(checked_path.read_bytes()).hexdigest(), catalog["assets"][0]["sha256"])

    def test_build_does_not_scan_remotion_public_images(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, pool = self.make_repo(Path(directory))
            synced = repo / "output" / "case_one" / "remotion" / "public" / "images" / "copy.png"
            self.make_image(synced, (255, 0, 0))
            built = self.run_tool("build", "--repo-root", str(repo), "--pool-root", str(pool))
            self.assertEqual(built.returncode, 0, built.stderr)
            catalog = json.loads((pool / "catalog.json").read_text(encoding="utf-8"))
            self.assertEqual(catalog["stats"]["sourceImages"], 2)

    def test_build_routes_character_portraits_out_of_background_pool(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, pool = self.make_repo(Path(directory))
            portrait = repo / "output" / "case_one" / "images" / "characters" / "person.png"
            self.make_image(portrait, (245, 245, 245))
            built = self.run_tool("build", "--repo-root", str(repo), "--pool-root", str(pool))
            self.assertEqual(built.returncode, 0, built.stderr)
            catalog = json.loads((pool / "catalog.json").read_text(encoding="utf-8"))
            self.assertEqual(catalog["stats"]["sourceImages"], 2)
            source_paths = {
                source["relativePath"]
                for asset in catalog["assets"]
                for source in asset["sources"]
            }
            self.assertNotIn("images/characters/person.png", source_paths)

    def test_build_rejects_programmatic_management_cutout_sources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, pool = self.make_repo(Path(directory))
            forbidden = repo / "output" / "case_one" / "images" / "management_cutout" / "01.png"
            self.make_image(forbidden, (255, 0, 0))
            built = self.run_tool("build", "--repo-root", str(repo), "--pool-root", str(pool))
            self.assertNotEqual(built.returncode, 0)
            self.assertIn("forbidden programmatic visual source", built.stderr)

    def test_scene_without_literal_location_uses_abstract_demand_category(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, pool = self.make_repo(Path(directory))
            storyboard_path = repo / "output" / "case_one" / "rich_storyboard.json"
            storyboard = json.loads(storyboard_path.read_text(encoding="utf-8"))
            storyboard["scenes"].append(
                {
                    "id": "s03",
                    "kicker": "新的问题",
                    "headline": {"text": "另一面开始浮出水面"},
                    "units": [4],
                }
            )
            storyboard_path.write_text(json.dumps(storyboard), encoding="utf-8")
            built = self.run_tool("build", "--repo-root", str(repo), "--pool-root", str(pool))
            self.assertEqual(built.returncode, 0, built.stderr)
            inventory = json.loads((pool / "scene_inventory.json").read_text(encoding="utf-8"))
            scene = next(item for item in inventory["scenes"] if item["sceneId"] == "s03")
            self.assertEqual(scene["primarySetting"], "abstract-editorial")
            self.assertEqual(scene["primaryActivity"], "metaphor-transition")

    def test_manual_tag_override_replaces_auto_classification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, pool = self.make_repo(Path(directory))
            first = self.run_tool("build", "--repo-root", str(repo), "--pool-root", str(pool))
            self.assertEqual(first.returncode, 0, first.stderr)
            catalog = json.loads((pool / "catalog.json").read_text(encoding="utf-8"))
            asset_id = catalog["assets"][0]["id"]
            overrides = {
                "schemaVersion": 1,
                "assets": {
                    asset_id: {
                        "replace": {
                            "settings": ["corporate-boardroom"],
                            "activities": ["meeting-review"],
                        },
                        "add": {"moods": ["tense"]},
                        "note": "Visual review shows a tense review meeting.",
                    }
                },
            }
            (pool / "tag_overrides.json").write_text(json.dumps(overrides), encoding="utf-8")
            second = self.run_tool("build", "--repo-root", str(repo), "--pool-root", str(pool))
            self.assertEqual(second.returncode, 0, second.stderr)
            catalog = json.loads((pool / "catalog.json").read_text(encoding="utf-8"))
            asset = catalog["assets"][0]
            self.assertEqual(asset["tags"]["settings"], ["corporate-boardroom"])
            self.assertEqual(asset["tags"]["activities"], ["meeting-review"])
            self.assertIn("tense", asset["tags"]["moods"])
            self.assertTrue(asset["curation"]["manualOverride"])
            self.assertEqual(catalog["stats"]["manuallyCuratedAssets"], 1)
            audited = self.run_tool("audit", "--pool-root", str(pool))
            self.assertEqual(audited.returncode, 0, audited.stderr)

    def test_manual_tag_override_rejects_unknown_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, pool = self.make_repo(Path(directory))
            first = self.run_tool("build", "--repo-root", str(repo), "--pool-root", str(pool))
            self.assertEqual(first.returncode, 0, first.stderr)
            catalog = json.loads((pool / "catalog.json").read_text(encoding="utf-8"))
            asset_id = catalog["assets"][0]["id"]
            overrides = {
                "schemaVersion": 1,
                "assets": {asset_id: {"replace": {"settings": ["invented-room"]}}},
            }
            (pool / "tag_overrides.json").write_text(json.dumps(overrides), encoding="utf-8")
            rebuilt = self.run_tool("build", "--repo-root", str(repo), "--pool-root", str(pool))
            self.assertNotEqual(rebuilt.returncode, 0)
            self.assertIn("unknown settings tag", rebuilt.stderr)


if __name__ == "__main__":
    unittest.main()
