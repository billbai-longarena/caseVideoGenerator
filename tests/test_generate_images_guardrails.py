from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import sys
import tempfile
import unittest

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine" / "scripts"))

import generate_images  # noqa: E402


class GenerateImagesGuardrailTests(unittest.TestCase):
    def test_prompt_target_rejects_overview_path_before_generation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory).resolve()
            prompt_path = project / "image_prompts.json"
            prompt_path.write_text(
                json.dumps(
                    {
                        "prompts": [
                            {
                                "file": "images/generated/overview.png",
                                "prompt": "abstract overview sheet",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(SystemExit) as context:
                generate_images.project_prompt_items(project, prompt_path)
            self.assertIn("forbidden generated image path", str(context.exception))

    def test_prompt_target_must_stay_inside_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory).resolve()
            prompt_path = project / "image_prompts.json"
            prompt_path.write_text(
                json.dumps(
                    {
                        "prompts": [
                            {
                                "file": "../outside.png",
                                "prompt": "abstract",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(SystemExit) as context:
                generate_images.project_prompt_items(project, prompt_path)
            self.assertIn("must stay inside project root", str(context.exception))

    def test_generated_bytes_must_match_requested_size(self) -> None:
        buffer = BytesIO()
        Image.new("RGB", (1200, 1000), (255, 255, 255)).save(buffer, format="PNG")
        with self.assertRaises(RuntimeError) as context:
            generate_images.validate_generated_image_bytes(
                buffer.getvalue(),
                expected_size=(1536, 864),
                label="images/generated/person.png",
            )
        self.assertIn("unexpected size", str(context.exception))


if __name__ == "__main__":
    unittest.main()
