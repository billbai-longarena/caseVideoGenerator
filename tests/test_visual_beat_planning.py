from __future__ import annotations

import unittest

from scripts.create_priority_and_management_storyboards import (
    V,
    build_beat_candidates,
    build_visual_beats,
    build_network,
    select_scene_layout,
    select_scene_motion,
    select_scene_transition,
)
from scripts.visual_beat_planning import BeatCandidate, schedule_visual_beats


def timeline_units(texts: list[str], *, seconds_per_unit: float = 4.0) -> dict[int, dict]:
    return {
        index: {
            "index": index,
            "text": text,
            "start": (index - 1) * seconds_per_unit,
            "end": index * seconds_per_unit,
        }
        for index, text in enumerate(texts, start=1)
    }


class VisualBeatPlanningTests(unittest.TestCase):
    def test_visual_variants_bind_assets_by_candidate_semantics(self) -> None:
        scene = {
            "headline": "口号很响\n行动为零",
            "kicker": "动员失效",
            "cards": ["团队动员", "完成培训", "仍然没有行动"],
            "person": None,
            "speaker": None,
            "quote": None,
            "role": "context",
            "treatment": "natural",
            "bars": [],
            "metrics": [],
            "nodes": [],
            "links": [],
        }
        units = timeline_units(
            [
                "经理动员团队。",
                "团队完成培训。",
                "大家拍下合照。",
                "回到办公室仍然没有行动。",
            ]
        )

        beats = build_visual_beats(
            scene,
            2,
            1,
            4,
            units,
            scene_count=4,
            default_asset="bg-s02-context",
            candidate_asset_map={"point-2": "bg-s02-training", "point-3": "bg-s02-empty"},
        )
        assets_by_key = {beat["candidateKey"]: beat["baseAsset"] for beat in beats}

        self.assertEqual(assets_by_key["claim"], "bg-s02-context")
        self.assertEqual(assets_by_key["point-2"], "bg-s02-training")
        self.assertEqual(assets_by_key["point-3"], "bg-s02-empty")

    def test_visual_variant_definition_requires_explicit_semantic_targets(self) -> None:
        with self.assertRaises(ValueError):
            V("empty-office", "An empty office.", [])

    def test_scene_fallback_style_is_semantic_not_index_driven(self) -> None:
        evidence_scene = {
            "role": "evidence",
            "treatment": "natural",
            "metrics": [{"label": "成交额", "value": {"to": 80}}],
            "bars": [],
            "nodes": [],
            "links": [],
            "person": "manager",
        }
        relationship_scene = {
            "role": "map",
            "treatment": "natural",
            "metrics": [],
            "bars": [],
            "nodes": ["销售", "客户"],
            "links": [{"from": 1, "to": 2}],
            "person": None,
        }

        self.assertEqual(
            select_scene_layout(evidence_scene, is_first=False, is_last=False),
            "split-data",
        )
        self.assertEqual(select_scene_transition(evidence_scene), "paper")
        self.assertEqual(select_scene_motion(evidence_scene, is_last=False), "center")
        self.assertEqual(
            select_scene_layout(relationship_scene, is_first=False, is_last=False),
            "decision-board",
        )
        self.assertEqual(select_scene_transition(relationship_scene), "push")
        self.assertEqual(select_scene_motion(relationship_scene, is_last=False), "left")

        self.assertEqual(
            select_scene_layout(evidence_scene, is_first=True, is_last=False),
            "hook-alert",
        )
        self.assertEqual(
            select_scene_layout(evidence_scene, is_first=False, is_last=True),
            "closing-idea",
        )
        self.assertEqual(select_scene_motion(evidence_scene, is_last=True), "breathe")

    def test_scheduler_uses_same_twelve_second_boundary_as_validator(self) -> None:
        units = {
            1: {"index": 1, "text": "建立情境。", "start": 0.0, "end": 4.0},
            2: {"index": 2, "text": "过渡信息。", "start": 4.0, "end": 8.0},
            3: {"index": 3, "text": "补充信息。", "start": 8.0, "end": 11.99},
            4: {"index": 4, "text": "关键证据。", "start": 11.99, "end": 16.0},
            5: {"index": 5, "text": "形成结论。", "start": 16.0, "end": 20.0},
        }
        beats = schedule_visual_beats(
            [
                BeatCandidate(
                    key="claim",
                    intent="context",
                    cue_texts=("建立情境",),
                    layers=({"kind": "text", "text": "建立情境"},),
                    anchor_policy="start",
                ),
                BeatCandidate(
                    key="evidence",
                    intent="evidence",
                    cue_texts=("关键证据",),
                    layers=({"kind": "text", "text": "关键证据"},),
                ),
            ],
            scene_id="s01",
            first=1,
            last=5,
            unit_by_index=units,
            base_asset="bg-s01",
        )

        self.assertEqual([beat["atUnit"] for beat in beats], [1, 4])

    def test_numeric_evidence_anchors_to_matching_narration_unit(self) -> None:
        units = timeline_units(
            [
                "客户一开始只谈流程。",
                "预算范围仍然模糊。",
                "关键证据显示，订单金额达到80万。",
                "经理据此做出决策。",
                "团队开始执行。",
            ]
        )
        candidates = [
            BeatCandidate(
                key="context",
                intent="context",
                cue_texts=("客户流程",),
                layers=({"kind": "text", "text": "客户流程"},),
            ),
            BeatCandidate(
                key="evidence",
                intent="evidence",
                cue_texts=("订单金额80万",),
                layers=(
                    {
                        "kind": "counter",
                        "label": "订单金额",
                        "value": {"to": 80, "suffix": "万"},
                    },
                ),
            ),
            BeatCandidate(
                key="decision",
                intent="decision",
                cue_texts=("经理做出决策",),
                layers=({"kind": "text", "text": "做出决策"},),
            ),
        ]

        beats = schedule_visual_beats(
            candidates,
            scene_id="s01",
            first=1,
            last=5,
            unit_by_index=units,
            base_asset="bg-s01",
        )

        evidence = next(beat for beat in beats if beat["visualIntent"] == "evidence")
        self.assertEqual(evidence["atUnit"], 3)

    def test_coverage_guard_rebalances_authored_beats_without_filler(self) -> None:
        units = timeline_units([f"第{index}句。" for index in range(1, 9)])
        candidates = [
            BeatCandidate(
                key=f"point-{index}",
                intent="claim",
                cue_texts=("没有直接命中的提示",),
                layers=({"kind": "text", "text": f"观点{index}"},),
                preferred_fraction=0.0,
            )
            for index in range(1, 5)
        ]

        beats = schedule_visual_beats(
            candidates,
            scene_id="s02",
            first=1,
            last=8,
            unit_by_index=units,
            base_asset="bg-s02",
        )

        self.assertEqual(len(beats), len(candidates))
        event_times = [units[beat["atUnit"]]["start"] for beat in beats]
        event_times.append(units[8]["end"])
        max_gap = max(later - earlier for earlier, later in zip(event_times, event_times[1:]))
        self.assertLessEqual(max_gap, 12.0)

    def test_network_builder_does_not_invent_relationships(self) -> None:
        self.assertEqual(build_network({"nodes": [], "links": []}, None), ([], []))

        nodes, links = build_network(
            {"nodes": ["客户", "销售", "交付"], "links": []},
            None,
        )
        self.assertEqual(len(nodes), 3)
        self.assertEqual(links, [])

        nodes, links = build_network(
            {
                "nodes": ["客户", "销售"],
                "links": [{"from": 1, "to": 2, "label": "确认"}],
            },
            None,
        )
        self.assertEqual(links, [{"from": "n1", "to": "n2", "label": "确认"}])

    def test_unlinked_labels_do_not_become_a_network_candidate(self) -> None:
        scene = {
            "headline": "口号很响\n行动为零",
            "kicker": "动员失效",
            "cards": ["动员", "培训", "零行动"],
            "person": None,
            "speaker": None,
            "quote": None,
            "role": "metaphor",
            "treatment": "natural",
            "bars": [],
            "metrics": [],
            "nodes": ["动员", "培训", "合照", "零行动"],
            "links": [],
        }

        candidates = build_beat_candidates(scene, is_first=False, is_last=False)

        self.assertNotIn("relationship", {candidate.key for candidate in candidates})

    def test_scheduled_beats_keep_authored_semantic_cues(self) -> None:
        units = timeline_units(["建立情境。", "订单金额达到80万。"])
        beats = schedule_visual_beats(
            [
                BeatCandidate(
                    key="claim",
                    intent="context",
                    cue_texts=("建立情境",),
                    layers=({"kind": "text", "text": "案例开始"},),
                    anchor_policy="start",
                ),
                BeatCandidate(
                    key="evidence",
                    intent="evidence",
                    cue_texts=("订单金额80万",),
                    layers=({"kind": "counter", "label": "订单金额", "value": {"to": 80}},),
                ),
            ],
            scene_id="s01",
            first=1,
            last=2,
            unit_by_index=units,
            base_asset="bg-s01",
        )

        self.assertEqual(beats[0]["candidateKey"], "claim")
        self.assertEqual(beats[1]["semanticCues"], ["订单金额80万"])

    def test_management_candidates_never_generate_legacy_box_annotations(self) -> None:
        scene = {
            "headline": "管理者重算\n团队时间",
            "kicker": "资源配置",
            "cards": ["每周45小时", "内部事务超过40%", "家长时间不足"],
            "person": "lin-wei",
            "speaker": "林薇",
            "quote": "我从来没有算过这个比例。",
            "role": "evidence",
            "treatment": "natural",
            "bars": [],
            "metrics": [
                {
                    "label": "内部事务",
                    "value": {"to": 40, "suffix": "%+"},
                    "tone": "bad",
                }
            ],
            "nodes": [],
            "links": [],
        }

        candidates = build_beat_candidates(scene, is_first=False, is_last=False)
        annotation_shapes = [
            layer.get("shape")
            for candidate in candidates
            for layer in candidate.layers
            if layer.get("kind") == "annotate"
        ]

        self.assertEqual(annotation_shapes, [])

    def test_rich_evidence_replaces_duplicate_point_cards_when_pacing_allows(self) -> None:
        scene = {
            "headline": "成交额10%\n计入协同贡献",
            "kicker": "机制改造",
            "cards": ["成交额10%计入考核", "80万变8万贡献分", "审批不超过5分钟"],
            "person": "he-chen",
            "speaker": "何晨",
            "quote": "让帮助别人，也能帮助自己。",
            "role": "evidence",
            "treatment": "natural",
            "bars": [],
            "metrics": [
                {"label": "协同贡献", "value": {"to": 10, "suffix": "%"}, "tone": "good"},
                {"label": "审批时间", "value": {"to": 5, "suffix": "分钟"}, "tone": "good"},
            ],
            "nodes": [],
            "links": [],
        }

        candidates = build_beat_candidates(
            scene,
            is_first=False,
            is_last=False,
            minimum_count=4,
        )
        keys = {candidate.key for candidate in candidates}

        self.assertNotIn("point-1", keys)
        self.assertIn("point-2", keys)
        self.assertNotIn("point-3", keys)
        self.assertTrue({"metric-1", "metric-2"} <= keys)

    def test_pacing_floor_can_preserve_duplicate_authored_points(self) -> None:
        scene = {
            "headline": "三十天\n协助从0到11",
            "kicker": "行为改变",
            "cards": ["30天", "主动协助0到11次", "线索开始双向流动"],
            "person": None,
            "speaker": None,
            "quote": None,
            "role": "evidence",
            "treatment": "natural",
            "bars": [
                {"label": "规则前", "value": 0, "suffix": "次"},
                {"label": "规则后", "value": 11, "suffix": "次"},
            ],
            "metrics": [
                {
                    "label": "主动协助",
                    "value": {"from": 0, "to": 11, "suffix": "次"},
                    "tone": "good",
                }
            ],
            "nodes": [],
            "links": [],
        }

        candidates = build_beat_candidates(
            scene,
            is_first=False,
            is_last=False,
            minimum_count=5,
        )

        self.assertEqual(len(candidates), 5)
        self.assertNotIn("metric-1", {candidate.key for candidate in candidates})


if __name__ == "__main__":
    unittest.main()
