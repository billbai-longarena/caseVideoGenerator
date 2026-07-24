from __future__ import annotations

from copy import deepcopy
import unittest

from scripts.create_batch_storyboard_plans import stage_visual_layers


class BatchStoryboardPlanTests(unittest.TestCase):
    def test_stage_visual_layers_spreads_authored_events_without_callbacks(self) -> None:
        units = {
            index: {
                "index": index,
                "start": float((index - 1) * 4),
                "end": float(index * 4),
            }
            for index in range(1, 9)
        }
        scene = {
            "visualBeats": [
                {
                    "purpose": "explain",
                    "composition": "split",
                    "baseAsset": "asset-scene",
                    "layers": [
                        {"kind": "text", "text": "先看问题", "revealOffset": 0},
                        {
                            "kind": "bar-compare",
                            "bars": [
                                {"label": "成本", "value": 42, "revealOffset": 1},
                                {"label": "风险", "value": 88, "revealOffset": 2},
                            ],
                        },
                    ],
                }
            ]
        }

        stage_visual_layers(scene, 1, 8, units)

        self.assertEqual(len(scene["visualBeats"]), 1)
        self.assertFalse(
            any(beat.get("purpose") == "callback" for beat in scene["visualBeats"])
        )
        layer_offsets = [
            layer["revealOffset"] for layer in scene["visualBeats"][0]["layers"]
        ]
        bar_offsets = [
            bar["revealOffset"]
            for bar in scene["visualBeats"][0]["layers"][1]["bars"]
        ]
        self.assertEqual(layer_offsets[0], 0)
        self.assertEqual(layer_offsets + bar_offsets, sorted(layer_offsets + bar_offsets))
        self.assertGreater(bar_offsets[-1], layer_offsets[-1])

    def test_stage_visual_layers_is_deterministic(self) -> None:
        units = {
            index: {"index": index, "start": float(index - 1), "end": float(index)}
            for index in range(1, 7)
        }
        original = {
            "visualBeats": [
                {
                    "layers": [
                        {"kind": "text", "text": "问题"},
                        {
                            "kind": "network",
                            "nodes": [
                                {"id": "a", "label": "甲"},
                                {"id": "b", "label": "乙"},
                            ],
                            "links": [{"from": "a", "to": "b"}],
                        },
                    ]
                }
            ]
        }
        first = deepcopy(original)
        second = deepcopy(original)

        stage_visual_layers(first, 1, 6, units)
        stage_visual_layers(second, 1, 6, units)

        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
