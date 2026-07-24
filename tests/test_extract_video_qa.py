from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from scripts.extract_video_qa import beat_samples, probe_video_duration, scene_samples, unit_bounds


class ExtractVideoQaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.timeline = {
            "duration": 10.0,
            "units": [
                {"index": 1, "start": 0.0, "end": 2.0},
                {"index": 2, "start": 2.0, "end": 4.0},
                {"index": 3, "start": 4.0, "end": 8.0},
                {"index": 4, "start": 8.0, "end": 10.0},
            ],
        }
        self.storyboard = {
            "scenes": [
                {
                    "id": "opening scene",
                    "units": [1, 2],
                    "visualBeats": [
                        {"id": "first beat", "atUnit": 1},
                        {"id": "second beat", "atUnit": 2},
                    ],
                },
                {
                    "id": "closing",
                    "units": [3, 4],
                    "visualBeats": [{"id": "final beat", "atUnit": 3}],
                },
            ]
        }

    def test_scene_samples_include_boundaries_and_stable_scene_frames(self) -> None:
        samples = scene_samples(self.storyboard, unit_bounds(self.timeline), 10.0)

        self.assertEqual([sample.stem for sample in samples], [
            "00-frame-zero",
            "01-opening-scene",
            "02-closing",
            "99-final-frame",
        ])
        self.assertAlmostEqual(samples[1].seconds, 3.12)
        self.assertAlmostEqual(samples[2].seconds, 8.68)
        self.assertAlmostEqual(samples[3].seconds, 9.9)

    def test_beat_samples_use_each_beats_active_window(self) -> None:
        samples = beat_samples(self.storyboard, unit_bounds(self.timeline))

        self.assertEqual(len(samples), 3)
        self.assertAlmostEqual(samples[0].seconds, 1.56)
        self.assertAlmostEqual(samples[1].seconds, 3.56)
        self.assertAlmostEqual(samples[2].seconds, 8.68)
        self.assertIn("first-beat", samples[0].stem)

    @patch("scripts.extract_video_qa.subprocess.run")
    def test_probe_video_duration_uses_rendered_media(self, run: Mock) -> None:
        run.return_value = Mock(returncode=0, stdout="10.625000\n", stderr="")

        duration = probe_video_duration(Path("render.mp4"))

        self.assertEqual(duration, 10.625)
        self.assertIn("ffprobe", run.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
