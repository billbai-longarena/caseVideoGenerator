#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import shutil
import subprocess
import wave
from typing import Any

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROJECT = ROOT / "output" / "remotion_visual_lab"
FPS = 30
WIDTH = 1920
HEIGHT = 1080
UNITS_PER_SCENE = 4
UNIT_SECONDS = 0.9


LAYOUT_SPECS: list[dict[str, Any]] = [
    {
        "id": "layout-breaking-news",
        "layout": "breaking-news",
        "kicker": "冲突升级与关键信号识别",
        "headline": "客户连续三次拒绝\n价格已经降到审批底线",
        "keywords": ["连续三次降价", "审批底线", "客户仍然沉默", "电话不再接听"],
        "props": {
            "stamp": "重大转折",
            "infoLabel": "CASE EVIDENCE",
            "info": "报价已经触底，客户依然没有给出任何承诺，销售必须重新判断真正阻力。",
        },
    },
    {
        "id": "layout-subject-reveal",
        "layout": "subject-reveal",
        "kicker": "关键人物与隐藏阻力揭示",
        "headline": "表面联系人已经同意\n执行团队仍然拒绝启动",
        "keywords": ["联系人同意", "执行团队反对", "责任边界变化", "真实决策者出现"],
        "props": {
            "reveal": "实施团队负责人拥有最后否决权",
            "revealSize": 140,
            "noteLabel": "DECISION OWNER",
            "note": "签字只覆盖采购流程。真正承担上线风险的人，仍然没有被纳入方案设计。",
        },
    },
    {
        "id": "layout-split-data",
        "layout": "split-data",
        "kicker": "数据对照与旧标准失效",
        "headline": "同一份方案\n三类角色看到不同风险",
        "keywords": ["预算负责人", "一线使用者", "风险监督者", "最终审批人"],
        "props": {
            "signalLabel": "KEY SIGNAL",
            "signal": "满意度上升，执行率下降，说明评价标准与实际责任已经发生错位。",
        },
    },
    {
        "id": "layout-map-focus",
        "layout": "map-focus",
        "kicker": "购买小组与决策地图",
        "headline": "先画清决策地图\n再决定下一步拜访谁",
        "keywords": ["预算所有者", "业务使用者", "安全否决者", "组织影响者"],
        "props": {"centerLabel": "真正的\n决策中心", "keywordLarge": 1},
    },
    {
        "id": "layout-local-playbook",
        "layout": "local-playbook",
        "kicker": "资源组合与本地执行方案",
        "headline": "总部方案必须转成\n一线能够执行的动作",
        "keywords": ["本地培训", "试点客户", "交付支持", "复盘机制"],
        "props": {
            "badge": "关键资源组合",
            "cardTitle": "LOCAL PLAYBOOK",
            "cardText": "角色识别 + 资源整合 + 责任到人 + 每周复盘",
        },
    },
    {
        "id": "layout-balance-beam",
        "layout": "balance-beam",
        "kicker": "表层诉求与真实目标校准",
        "headline": "客户说价格太高\n真正担心的是失败责任",
        "keywords": ["采购价格", "上线风险", "内部问责", "个人信誉"],
        "props": {"formula": "表层价格异议 只是 风险责任无法被解释"},
    },
    {
        "id": "layout-question-storm",
        "layout": "question-storm",
        "kicker": "连续追问与问题诊断",
        "headline": "不要急着解释产品\n先把关键问题问完整",
        "keywords": [],
        "props": {
            "questions": [
                "谁会因为项目失败承担直接责任？",
                "现有流程究竟保护了谁的利益？",
                "什么证据能够让反对者愿意试一次？",
                "谁拥有暂停项目的最终权力？",
            ]
        },
    },
    {
        "id": "layout-timeline-roadshow",
        "layout": "timeline-roadshow",
        "kicker": "跨区域推进与关键里程碑",
        "headline": "六个城市连续推进\n最后一站突然叫停",
        "keywords": ["需求确认", "方案评审", "试点启动", "总部叫停"],
        "props": {
            "cities": ["华东一区", "华南示范区", "西南重点城市", "华北总部", "区域联合评审", "全国决策会"],
            "stamp": "临时叫停",
            "quote": "流程走完不代表共识已经形成，真正的考题现在才开始。",
            "railLabel": "REGIONAL MILESTONES",
        },
    },
    {
        "id": "layout-decision-board",
        "layout": "decision-board",
        "kicker": "多方案比较与决策选择",
        "headline": "四种推进路径\n必须明确取舍标准",
        "keywords": ["立即全面上线", "先做小范围试点", "联合客户共创方案", "暂停并重新调查"],
        "props": {},
    },
    {
        "id": "layout-closing-quote",
        "layout": "closing-quote",
        "kicker": "案例结论与方法收束",
        "headline": "工具必须贴合内容\n每一次展示都要清楚",
        "keywords": ["内容适配", "层级清晰", "证据可见", "行动明确"],
        "props": {
            "overline": "真正有效的视觉，不增加理解成本，只帮助观众更快抓住关系与证据。",
            "badge": "CASE\nMETHOD",
        },
    },
    {
        "id": "layout-performance-ladder",
        "layout": "performance-ladder",
        "kicker": "连续业绩与角色晋升",
        "headline": "业绩连续增长\n管理能力却没有同步形成",
        "keywords": [],
        "props": {
            "years": "第一季度|第二季度|第三季度|第四季度",
            "values": "三千九百万|四千三百万|四千八百万|五千二百万",
            "badge": "连续四个季度增长\n仍需建立团队判断机制",
        },
    },
    {
        "id": "layout-decision-bottleneck",
        "layout": "decision-bottleneck",
        "kicker": "管理瓶颈与授权边界",
        "headline": "所有问题都向上汇集\n团队逐渐停止独立判断",
        "keywords": [],
        "props": {
            "nodes": "客户关系负责人|销售运营经理|交付方案负责人|区域一线销售代表",
            "center": "区域总监\n亲自拍板",
            "warning": "每个问题都等待同一个人决定\n组织响应速度和判断力同时下降",
        },
    },
    {
        "id": "layout-authority-matrix",
        "layout": "authority-matrix",
        "kicker": "角色责任与决策权限矩阵",
        "headline": "谁判断谁行动\n必须在会议之前说清楚",
        "keywords": [],
        "props": {
            "roles": "客户关系负责人|区域销售经理|交付解决方案负责人|全国业务总监",
            "tasks": "维护客户关系并判断商务信号|决定资源投入与折扣边界|评估交付风险并拥有技术否决权|只追问证据责任人与下一步动作",
            "footer": "清楚的责任边界，让会议从汇报进度转向真正做出决定。",
        },
    },
]


EDITORIAL_SPECS: list[dict[str, Any]] = [
    {
        "id": "editorial-full-bleed",
        "composition": "full-bleed",
        "purpose": "escalate",
        "camera": "push-in",
        "treatment": "crisis",
        "layers": [
            {"kind": "tint", "slot": "canvas", "color": "#071a33", "opacity": 0.3},
            {"kind": "text", "slot": "top-left", "variant": "headline", "label": "FULL BLEED", "text": "全画幅负责建立情绪\n文字只保留一个核心冲突"},
            {"kind": "counter", "slot": "right", "label": "连续等待", "value": {"to": 127, "suffix": "天"}, "deltaTone": "bad"},
        ],
    },
    {
        "id": "editorial-portrait-left",
        "composition": "portrait-left",
        "purpose": "identify",
        "camera": "breathe",
        "treatment": "natural",
        "layers": [
            {"kind": "dialogue", "slot": "right", "speaker": "实施负责人", "tail": "left", "text": "签字的人不承担上线失败的责任。请先告诉我，出了问题谁来负责？"},
            {"kind": "annotate", "shape": "arrow", "region": {"x": 0.12, "y": 0.25, "w": 0.3, "h": 0.42}, "text": "箭头只指向单个目标"},
        ],
    },
    {
        "id": "editorial-portrait-right",
        "composition": "portrait-right",
        "purpose": "evidence",
        "camera": "pan-left",
        "treatment": "desaturated",
        "layers": [
            {"kind": "bar-compare", "slot": "left", "label": "方案接受度", "text": "对照必须一眼读懂", "bars": [
                {"label": "原始方案", "value": 32, "max": 100, "tone": "bad"},
                {"label": "共同设计", "value": 76, "max": 100, "tone": "neutral"},
                {"label": "试点验证", "value": 94, "max": 100, "tone": "good"},
            ]},
            {"kind": "text", "slot": "bottom", "variant": "caption", "text": "人物、证据和结论必须形成明确阅读顺序"},
        ],
    },
    {
        "id": "editorial-split",
        "composition": "split",
        "purpose": "explain",
        "camera": "drift",
        "treatment": "blueprint",
        "layers": [
            {"kind": "network", "slot": "left", "label": "购买小组", "nodes": [
                {"id": "payer", "label": "预算负责人", "sub": "付钱", "emphasis": True},
                {"id": "user", "label": "一线使用团队", "sub": "执行"},
                {"id": "risk", "label": "安全合规负责人", "sub": "否决"},
                {"id": "boss", "label": "全国业务总监", "sub": "拍板"},
            ], "links": [
                {"from": "payer", "to": "user", "label": "授权"},
                {"from": "user", "to": "risk", "label": "责任"},
                {"from": "risk", "to": "boss", "label": "风险建议"},
            ]},
        ],
    },
    {
        "id": "editorial-network-hub",
        "composition": "full-bleed",
        "purpose": "explain",
        "camera": "drift",
        "treatment": "blueprint",
        "layers": [
            {"kind": "network", "slot": "center", "label": "两份共识", "nodes": [
                {"id": "director", "label": "教务主任", "sub": "愿意试"},
                {"id": "parent", "label": "家委会", "sub": "认可公开方案"},
                {"id": "principal", "label": "校长", "sub": "最后签字", "emphasis": True},
            ], "links": [
                {"from": "director", "to": "principal", "label": "执行共识"},
                {"from": "parent", "to": "principal", "label": "公开共识"},
            ]},
        ],
    },
    {
        "id": "editorial-network-shallow",
        "composition": "full-bleed",
        "purpose": "explain",
        "camera": "static",
        "treatment": "natural",
        "layers": [
            {"kind": "network", "slot": "bottom", "label": "推进链路", "nodes": [
                {"id": "discover", "label": "识别阻力", "sub": "发现"},
                {"id": "align", "label": "形成共识", "sub": "协商"},
                {"id": "pilot", "label": "小范围试点", "sub": "验证"},
                {"id": "approve", "label": "正式签字", "sub": "决策", "emphasis": True},
            ], "links": [
                {"from": "discover", "to": "align"},
                {"from": "align", "to": "pilot"},
                {"from": "pilot", "to": "approve"},
            ]},
        ],
    },
    {
        "id": "editorial-network-column",
        "composition": "portrait-left",
        "purpose": "explain",
        "camera": "breathe",
        "treatment": "desaturated",
        "layers": [
            {"kind": "network", "slot": "inset-right", "label": "审批顺序", "networkLayout": "column", "nodes": [
                {"id": "owner", "label": "业务负责人", "sub": "提出需求"},
                {"id": "risk", "label": "风险负责人", "sub": "给出意见"},
                {"id": "signer", "label": "最终审批人", "sub": "签字", "emphasis": True},
            ], "links": [
                {"from": "owner", "to": "risk"},
                {"from": "risk", "to": "signer"},
            ]},
        ],
    },
    {
        "id": "editorial-triptych",
        "composition": "triptych",
        "purpose": "explain",
        "camera": "static",
        "treatment": "natural",
        "triptych": True,
        "layers": [
            {"kind": "text", "slot": "bottom", "variant": "headline", "text": "三栏只展示可以并列比较的同类证据"},
        ],
    },
    {
        "id": "editorial-document-focus",
        "composition": "document-focus",
        "purpose": "evidence",
        "camera": "pull-out",
        "treatment": "desaturated",
        "layers": [
            {"kind": "annotate", "shape": "underline", "region": {"x": 0.38, "y": 0.47, "w": 0.24, "h": 0.06}, "text": "证据落点不能被字幕遮挡"},
            {"kind": "text", "slot": "top-left", "variant": "stamp", "text": "责任条款已被重新定义"},
            {"kind": "counter", "slot": "inset-right", "label": "试点周期", "value": {"to": 50, "suffix": "亩"}, "deltaTone": "good"},
        ],
    },
    {
        "id": "editorial-evidence-collage",
        "composition": "evidence-collage",
        "purpose": "consequence",
        "camera": "pan-right",
        "treatment": "natural",
        "layers": [
            {"kind": "dialogue", "slot": "left", "speaker": "客户", "tail": "right", "text": "我愿意先试，但结果、责任和退出条件都要提前写清楚。"},
            {"kind": "text", "slot": "top-right", "variant": "stamp", "label": "EVIDENCE", "text": "访谈记录\n试点数据\n责任清单"},
        ],
    },
]


HYBRID_SPEC: dict[str, Any] = {
    "id": "hybrid-layout-editorial",
    "layout": "subject-reveal",
    "composition": "portrait-right",
    "kicker": "Hybrid 工具分工边界测试",
    "headline": "布局说明结论\n人物图像提供证据",
    "keywords": ["结论层", "人物证据"],
    "props": {
        "reveal": "结构与证据各守一个区域",
        "note": "布局层给结论，图像层给人物与环境证据。",
    },
    "layers": [],
}


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def source_images() -> list[Path]:
    patterns = [
        "output/agri_tech_case_video/images/generated/*",
        "output/sales_management_case05_video/images/manager_silhouette/*",
        "output/sales_management_case05_video/images/pool/*",
    ]
    images: list[Path] = []
    for pattern in patterns:
        for path in sorted(ROOT.glob(pattern)):
            if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
                continue
            lowered = path.stem.lower()
            if any(token in lowered for token in ("contact", "overview", "sheet")):
                continue
            images.append(path)
    needed = len(LAYOUT_SPECS) + len(EDITORIAL_SPECS) + 4
    if len(images) < needed:
        raise SystemExit(f"visual lab needs {needed} source illustrations, found {len(images)}")
    return images[:needed]


def create_silent_wav(path: Path, duration: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sample_rate = 48_000
    frame_count = math.ceil(duration * sample_rate)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(b"\x00\x00" * frame_count)


def timed_props(spec: dict[str, Any], first_unit: int) -> dict[str, Any]:
    props = json.loads(json.dumps(spec.get("props", {}), ensure_ascii=False))
    layout = spec["layout"]
    if layout == "subject-reveal":
        props["revealAtUnit"] = first_unit + 1
    elif layout == "balance-beam":
        props["formulaAtUnit"] = first_unit + 2
    elif layout == "question-storm":
        props["questions"] = [
            {
                "text": question if isinstance(question, str) else question["text"],
                "atUnit": first_unit + min(index, UNITS_PER_SCENE - 1),
            }
            for index, question in enumerate(props.get("questions", []))
        ]
    elif layout == "timeline-roadshow":
        props["stampAtUnit"] = first_unit + 2
        props["quoteAtUnit"] = first_unit + 3
    elif layout == "performance-ladder":
        props["valueAtUnits"] = [first_unit + index for index in range(UNITS_PER_SCENE)]
        props["badgeAtUnit"] = first_unit + 3
    elif layout == "decision-bottleneck":
        props["nodeAtUnits"] = [first_unit + index for index in range(UNITS_PER_SCENE)]
        props["warningAtUnit"] = first_unit + 3
    elif layout == "authority-matrix":
        props["roleAtUnits"] = [first_unit + index for index in range(UNITS_PER_SCENE)]
        props["footerAtUnit"] = first_unit + 3
    return props


def keyword_cues(words: list[str], first_unit: int) -> list[dict[str, Any]]:
    return [
        {
            "text": word,
            "atUnit": first_unit + min(index, UNITS_PER_SCENE - 1),
            "sfx": "pop" if index % 2 == 0 else "stamp",
        }
        for index, word in enumerate(words)
    ]


def subtitles(first_unit: int, label: str) -> list[dict[str, Any]]:
    lines = [
        f"{label}：先检查主要信息是否完整进入安全区域。",
        "再检查长标题、四项并列和标签是否出现遮挡或越界。",
        "随后观察动画结束后的稳定状态，以及视觉层级是否符合内容关系。",
        "最后确认字幕、栏目标签、章节编号与主体工具互不争抢空间。",
    ]
    return [{"unit": first_unit + index, "text": text} for index, text in enumerate(lines)]


def scene_shell(
    *,
    spec: dict[str, Any],
    scene_index: int,
    image_src: str,
    visual_mode: str,
) -> dict[str, Any]:
    first_unit = scene_index * UNITS_PER_SCENE + 1
    last_unit = first_unit + UNITS_PER_SCENE - 1
    headline = spec.get("headline", f"{spec['id']}\n视觉边界测试")
    layout = spec.get("layout", "closing-quote")
    return {
        "id": spec["id"],
        "chapter": f"{scene_index + 1:02d}",
        "kicker": spec.get("kicker", f"{spec.get('composition', layout)} 视觉压力测试"),
        "layout": layout,
        "tone": ["dark", "archive", "bright"][scene_index % 3],
        "units": [first_unit, last_unit],
        "headline": {"text": headline, "reveal": "perClause", "accent": []},
        "keywords": keyword_cues(spec.get("keywords", []), first_unit),
        "subtitles": subtitles(first_unit, spec["id"]),
        "backgrounds": [
            {
                "image": image_src,
                "atUnit": first_unit,
                "transition": ["wash", "paper", "ink", "flash", "push"][scene_index % 5],
                "motion": ["center", "left", "right", "lift", "drift", "breathe"][scene_index % 6],
            }
        ],
        "visualMode": visual_mode,
        "props": timed_props({**spec, "layout": layout}, first_unit),
    }


def layer_with_ids(layers: list[dict[str, Any]], scene_id: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, layer in enumerate(layers, start=1):
        item = json.loads(json.dumps(layer, ensure_ascii=False))
        item["id"] = f"{scene_id}-layer-{index:02d}"
        result.append(item)
    return result


def build_project(project: Path) -> dict[str, Any]:
    if project.exists():
        shutil.rmtree(project)
    (project / "images" / "lab").mkdir(parents=True, exist_ok=True)
    (project / "audio").mkdir(parents=True, exist_ok=True)

    copied: list[str] = []
    for index, source in enumerate(source_images(), start=1):
        destination = project / "images" / "lab" / f"visual_{index:02d}{source.suffix.lower()}"
        shutil.copy2(source, destination)
        copied.append(destination.relative_to(project).as_posix())

    visual_assets = [
        {
            "id": f"lab-asset-{index:02d}",
            "type": "image",
            "src": src,
            "role": ["context", "person", "evidence", "document", "map", "metaphor"][
                (index - 1) % 6
            ],
            "origin": "curated",
        }
        for index, src in enumerate(copied, start=1)
    ]

    scenes: list[dict[str, Any]] = []
    manifest_scenes: list[dict[str, Any]] = []
    image_cursor = 0

    for spec in LAYOUT_SPECS:
        scene_index = len(scenes)
        scene = scene_shell(
            spec=spec,
            scene_index=scene_index,
            image_src=copied[image_cursor],
            visual_mode="layout",
        )
        scenes.append(scene)
        image_cursor += 1
        manifest_scenes.append({"id": spec["id"], "kind": "layout", "layout": spec["layout"]})

    for spec in EDITORIAL_SPECS:
        scene_index = len(scenes)
        base_asset_index = image_cursor + 1
        scene = scene_shell(
            spec=spec,
            scene_index=scene_index,
            image_src=copied[image_cursor],
            visual_mode="editorial",
        )
        first_unit = scene["units"][0]
        layers = layer_with_ids(spec["layers"], spec["id"])
        if spec.get("triptych"):
            for slot in ("left", "center", "right"):
                image_cursor += 1
                layers.insert(
                    len(layers) - 1,
                    {
                        "id": f"{spec['id']}-asset-{slot}",
                        "kind": "asset",
                        "slot": slot,
                        "asset": f"lab-asset-{image_cursor + 1:02d}",
                    },
                )
        scene["visualBeats"] = [
            {
                "id": f"{spec['id']}-beat",
                "atUnit": first_unit,
                "purpose": spec["purpose"],
                "composition": spec["composition"],
                "baseAsset": f"lab-asset-{base_asset_index:02d}",
                "transition": "cut",
                "camera": spec["camera"],
                "treatment": spec["treatment"],
                "layers": layers,
            }
        ]
        scenes.append(scene)
        manifest_scenes.append(
            {"id": spec["id"], "kind": "editorial", "composition": spec["composition"]}
        )
        image_cursor += 1

    scene_index = len(scenes)
    hybrid = scene_shell(
        spec=HYBRID_SPEC,
        scene_index=scene_index,
        image_src=copied[image_cursor],
        visual_mode="hybrid",
    )
    first_unit = hybrid["units"][0]
    hybrid["visualBeats"] = [
        {
            "id": f"{HYBRID_SPEC['id']}-beat",
            "atUnit": first_unit,
            "purpose": "identify",
            "composition": HYBRID_SPEC["composition"],
            "baseAsset": f"lab-asset-{image_cursor + 1:02d}",
            "transition": "cut",
            "camera": "breathe",
            "treatment": "natural",
            "layers": layer_with_ids(HYBRID_SPEC["layers"], HYBRID_SPEC["id"]),
        }
    ]
    scenes.append(hybrid)
    manifest_scenes.append(
        {
            "id": HYBRID_SPEC["id"],
            "kind": "hybrid",
            "layout": HYBRID_SPEC["layout"],
            "composition": HYBRID_SPEC["composition"],
        }
    )

    unit_count = len(scenes) * UNITS_PER_SCENE
    duration = unit_count * UNIT_SECONDS
    timeline_units = []
    narration_lines = []
    for unit_index in range(1, unit_count + 1):
        scene_number = (unit_index - 1) // UNITS_PER_SCENE + 1
        local_number = (unit_index - 1) % UNITS_PER_SCENE + 1
        text = f"视觉实验第{scene_number}组，第{local_number}项检查。"
        start = round((unit_index - 1) * UNIT_SECONDS, 3)
        end = round(unit_index * UNIT_SECONDS, 3)
        timeline_units.append(
            {
                "index": unit_index,
                "text": text,
                "start": start,
                "end": end,
                "pauseAfter": 0.0,
                "sentence": unit_index,
                "paragraph": scene_number,
            }
        )
        narration_lines.append(text)

    storyboard = {
        "slug": "remotion-visual-lab",
        "title": "Remotion 视觉实验室",
        "subtitle": "布局、语义图层与混合模式边界回归",
        "brand": "销售不复杂",
        "cover": {
            "title": "Remotion 视觉实验室",
            "subtitle": "布局、语义图层与混合模式边界回归",
            "kicker": "销售不复杂",
            "throughUnit": 1,
        },
        "projectType": "visual-qa",
        "visualStyle": "production-mixed-style-qa",
        "subtitleLabel": "销售不复杂",
        "fps": FPS,
        "width": WIDTH,
        "height": HEIGHT,
        "audio": "audio/narration_azure.wav",
        "timeline": "narration.timeline.json",
        "visualAssets": visual_assets,
        "scenes": scenes,
    }
    timeline = {
        "audio": "audio/narration_azure.wav",
        "duration": duration,
        "engine": "silent-visual-lab",
        "units": timeline_units,
    }
    write_json(project / "rich_storyboard.json", storyboard)
    write_json(project / "narration.timeline.json", timeline)
    (project / "narration.txt").write_text("\n".join(narration_lines) + "\n", encoding="utf-8")
    create_silent_wav(project / "audio" / "narration_azure.wav", duration)

    for index, item in enumerate(manifest_scenes):
        start = index * UNITS_PER_SCENE * UNIT_SECONDS
        scene_duration = UNITS_PER_SCENE * UNIT_SECONDS
        item.update(
            {
                "index": index + 1,
                "startSeconds": round(start, 3),
                "durationSeconds": scene_duration,
                "sampleSeconds": round(start + scene_duration - 0.45, 3),
                "sampleFrame": round((start + scene_duration - 0.45) * FPS),
            }
        )
    manifest = {
        "project": project.as_posix(),
        "fps": FPS,
        "durationSeconds": duration,
        "sceneCount": len(scenes),
        "scenes": manifest_scenes,
    }
    write_json(project / "visual_lab_manifest.json", manifest)
    return manifest


def run_ffmpeg(command: list[str]) -> None:
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        raise SystemExit(completed.stderr.strip() or "ffmpeg failed")


def contact_sheet(frame_paths: list[Path], output: Path) -> None:
    columns = 4
    tile_width = 480
    tile_height = 270
    label_height = 42
    rows = math.ceil(len(frame_paths) / columns)
    sheet = Image.new("RGB", (columns * tile_width, rows * (tile_height + label_height)), "#07111f")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(size=22)
    for index, path in enumerate(frame_paths):
        image = Image.open(path).convert("RGB")
        image.thumbnail((tile_width, tile_height), Image.Resampling.LANCZOS)
        x = (index % columns) * tile_width
        y = (index // columns) * (tile_height + label_height)
        sheet.paste(image, (x, y))
        draw.text((x + 12, y + tile_height + 8), path.stem, fill="#ffffff", font=font)
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output, quality=90)


def extract_artifacts(project: Path, video: Path) -> None:
    manifest = json.loads((project / "visual_lab_manifest.json").read_text(encoding="utf-8"))
    frames_dir = project / "qa" / "layout_frames"
    clips_dir = project / "qa" / "layout_clips"
    frames_dir.mkdir(parents=True, exist_ok=True)
    clips_dir.mkdir(parents=True, exist_ok=True)
    frame_paths: list[Path] = []
    for scene in manifest["scenes"]:
        stem = f"{scene['index']:02d}_{scene['id']}"
        frame_path = frames_dir / f"{stem}.png"
        clip_path = clips_dir / f"{stem}.mp4"
        run_ffmpeg(
            [
                "ffmpeg",
                "-y",
                "-ss",
                str(scene["sampleSeconds"]),
                "-i",
                str(video),
                "-frames:v",
                "1",
                str(frame_path),
            ]
        )
        run_ffmpeg(
            [
                "ffmpeg",
                "-y",
                "-ss",
                str(scene["startSeconds"]),
                "-i",
                str(video),
                "-t",
                str(scene["durationSeconds"]),
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "20",
                "-pix_fmt",
                "yuv420p",
                str(clip_path),
            ]
        )
        frame_paths.append(frame_path)
    contact_sheet(frame_paths, project / "qa" / "visual_lab_contact_sheet.jpg")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build and inspect a deterministic Remotion layout/semantic-layer visual lab."
    )
    parser.add_argument("--project", type=Path, default=DEFAULT_PROJECT)
    parser.add_argument(
        "--extract-from",
        type=Path,
        help="Extract one stable frame and one short clip per scene from this rendered video.",
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Rebuild the project before extraction even when a manifest already exists.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    project = args.project.expanduser().resolve()
    manifest_path = project / "visual_lab_manifest.json"
    should_build = args.rebuild or not args.extract_from or not manifest_path.is_file()
    if should_build:
        manifest = build_project(project)
        print(
            f"built {project}: scenes={manifest['sceneCount']} "
            f"duration={manifest['durationSeconds']:.1f}s"
        )
    else:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        print(f"reusing {project}: scenes={manifest['sceneCount']}")
    if args.extract_from:
        video = args.extract_from.expanduser().resolve()
        if not video.is_file():
            raise SystemExit(f"video not found: {video}")
        extract_artifacts(project, video)
        print(f"extracted clips and frames under {project / 'qa'}")


if __name__ == "__main__":
    main()
