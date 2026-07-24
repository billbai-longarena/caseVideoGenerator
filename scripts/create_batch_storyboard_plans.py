#!/usr/bin/env python3
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def asset_id(src: str) -> str:
    stem = Path(src).stem.replace("_", "-")
    return f"asset-{stem}"


def role_for(src: str) -> str:
    name = Path(src).stem
    if any(token in name for token in ("docs", "proposal", "compliance", "cost", "contract", "stability", "data")):
        return "document"
    if any(token in name for token in ("network", "triangle", "structure", "flow", "process")):
        return "map"
    if any(token in name for token in ("hidden", "veto", "gate", "path", "closing", "silence")):
        return "metaphor"
    return "context"


def prompt_files(project: Path) -> set[str]:
    path = project / "image_prompts.json"
    if not path.is_file():
        return set()
    data = load_json(path)
    prompts = data if isinstance(data, list) else data.get("prompts", [])
    return {item["file"].replace("\\", "/") for item in prompts}


def pool_records(project: Path) -> dict[str, str]:
    path = project / "asset_pool_usage.json"
    if not path.is_file():
        return {}
    data = load_json(path)
    return {item["src"].replace("\\", "/"): item["assetId"] for item in data.get("assets", [])}


def paragraph_bounds(project: Path) -> dict[int, tuple[int, int]]:
    timeline = load_json(project / "narration.timeline.json")
    by_paragraph: dict[int, list[int]] = {}
    for unit in timeline["units"]:
        by_paragraph.setdefault(int(unit["paragraph"]), []).append(int(unit["index"]))
    return {paragraph: (units[0], units[-1]) for paragraph, units in by_paragraph.items()}


def timeline_units(project: Path) -> dict[int, dict]:
    timeline = load_json(project / "narration.timeline.json")
    return {int(unit["index"]): unit for unit in timeline["units"]}


def scene_units(bounds: dict[int, tuple[int, int]], paragraphs: int | list[int]) -> tuple[int, int]:
    if isinstance(paragraphs, int):
        return bounds[paragraphs]
    if len(paragraphs) == 2 and paragraphs[0] <= paragraphs[1]:
        selected = range(paragraphs[0], paragraphs[1] + 1)
    else:
        selected = paragraphs
    first = bounds[next(iter(selected))]
    selected_list = list(selected)
    return first[0], bounds[selected_list[-1]][1]


def clamp_offsets(value: Any, span: int) -> Any:
    if isinstance(value, dict):
        next_value = {}
        for key, child in value.items():
            if key in {"revealOffset", "exitOffset", "offset"} and isinstance(child, int):
                next_value[key] = max(0, min(span, child))
            else:
                next_value[key] = clamp_offsets(child, span)
        return next_value
    if isinstance(value, list):
        return [clamp_offsets(item, span) for item in value]
    return value


def offset_for_fraction(
    first: int,
    last: int,
    units: dict[int, dict],
    fraction: float,
) -> int:
    """Return the first narration-unit offset at or after a scene-time fraction."""
    scene_start = float(units[first]["start"])
    scene_end = float(units[last]["end"])
    target = scene_start + max(0.0, min(1.0, fraction)) * (scene_end - scene_start)
    for candidate in range(first, last + 1):
        if float(units[candidate]["start"]) >= target:
            return candidate - first
    return last - first


def stage_visual_layers(scene_spec: dict, first: int, last: int, units: dict[int, dict]) -> None:
    """Distribute real semantic reveals without manufacturing duplicate callbacks.

    Camera or composition changes do not create new story information. This helper
    therefore keeps the authored beat count intact and spreads the authored layers,
    bars, nodes, and links across the scene timeline. If those events are still too
    sparse, strict validation requires the storyboard author to add real evidence or
    another content-bearing beat.
    """
    beats = scene_spec.get("visualBeats")
    if not isinstance(beats, list):
        return

    for beat in beats:
        layers = beat.get("layers")
        if not isinstance(layers, list) or not layers:
            continue

        reveal_events: list[dict[str, Any]] = []
        for layer in layers:
            if not isinstance(layer, dict):
                continue
            reveal_events.append(layer)
            for nested_key in ("bars", "nodes", "links"):
                nested_items = layer.get(nested_key)
                if not isinstance(nested_items, list):
                    continue
                reveal_events.extend(item for item in nested_items if isinstance(item, dict))

        event_count = len(reveal_events)
        if event_count == 0:
            continue
        for position, event in enumerate(reveal_events):
            fraction = position / event_count
            event["revealOffset"] = offset_for_fraction(first, last, units, fraction)


def text_layer(text: str, slot: str = "top-left", reveal: int = 0, variant: str = "headline", label: str | None = None) -> dict:
    layer: dict[str, Any] = {
        "kind": "text",
        "slot": slot,
        "variant": variant,
        "text": text,
        "revealOffset": reveal,
    }
    if label:
        layer["label"] = label
    return layer


def stamp(text: str, reveal: int = 2, slot: str = "bottom") -> dict:
    return text_layer(text, slot=slot, reveal=reveal, variant="stamp")


def bars(label: str, entries: list[tuple[str, int, str]], reveal: int = 2, slot: str = "right", text: str | None = None) -> dict:
    layer: dict[str, Any] = {
        "kind": "bar-compare",
        "slot": slot,
        "label": label,
        "revealOffset": reveal,
        "bars": [
            {"label": item_label, "value": value, "max": 100, "tone": tone, "revealOffset": reveal + index}
            for index, (item_label, value, tone) in enumerate(entries)
        ],
    }
    if text:
        layer["text"] = text
    return layer


def network(label: str, nodes: list[dict], links: list[dict], reveal: int = 2, slot: str = "center") -> dict:
    layer = {
        "kind": "network",
        "slot": slot,
        "label": label,
        "revealOffset": reveal,
        "nodes": deepcopy(nodes),
        "links": deepcopy(links),
    }
    for index, node in enumerate(layer["nodes"]):
        node.setdefault("revealOffset", reveal + index)
    for index, link in enumerate(layer["links"]):
        link.setdefault("revealOffset", reveal + len(nodes) + index)
    return layer


def cue_words(*words: str) -> list[dict]:
    return [{"text": word, "offset": index} for index, word in enumerate(words)]


def scene(
    sid: str,
    chapter: str,
    kicker: str,
    layout: str,
    paragraphs: int | list[int],
    background: str,
    headline: str,
    keywords: list[dict],
    layers: list[dict],
    *,
    purpose: str = "establish",
    composition: str = "full-bleed",
    camera: str = "breathe",
    treatment: str = "natural",
    motion: str = "breathe",
    transition: str = "wash",
    tone: str = "dark",
) -> dict:
    spec = {
        "id": sid,
        "chapter": chapter,
        "kicker": kicker,
        "layout": layout,
        "background": background,
        "transition": transition,
        "motion": motion,
        "tone": tone,
        "headline": headline,
        "keywords": keywords,
        "props": {},
        "visualMode": "editorial",
        "visualBeats": [
            {
                "purpose": purpose,
                "composition": composition,
                "baseAsset": asset_id(background),
                "transition": "dissolve",
                "camera": camera,
                "treatment": treatment,
                "layers": layers,
            }
        ],
    }
    if isinstance(paragraphs, int):
        spec["paragraph"] = paragraphs
    else:
        spec["paragraphs"] = paragraphs
    return spec


PROJECTS: dict[str, dict[str, Any]] = {
    "output/case06_edu_triangle_video": {
        "title": "教育软件的三角权力",
        "subtitle": "签约之后，项目为什么卡住",
        "coverTitle": "教育软件的\n三角权力",
        "coverSubtitle": "签约以后，项目为什么停摆",
        "scenes": [
            scene("s01", "01", "开场", "hook-alert", [1, 2], "images/generated/school_contract_stalled.png", "签字以后\n项目停摆", cue_words("签字", "停摆"), [text_layer("签字以后\n项目停摆"), stamp("合同生效\n执行没动")], purpose="escalate", treatment="crisis"),
            scene("s02", "02", "表层说法", "subject-reveal", [3, 4], "images/pool/classroom_workshop.png", "再等等\n背后有阻力", cue_words("再等等", "阻力"), [text_layer("再等等\n背后有阻力", slot="top-right"), stamp("表层原因\n只是一层信号")], purpose="identify", camera="pan-left"),
            scene("s03", "03", "权力拆分", "split-data", [5, 7], "images/pool/principal_docs.png", "预算和执行\n分在两处", cue_words("预算", "执行"), [text_layer("预算和执行\n分在两处"), bars("两条线", [("预算权", 78, "neutral"), ("执行权", 92, "good"), ("监督权", 65, "neutral")], text="签字只覆盖一部分权力")], purpose="explain", composition="document-focus"),
            scene("s04", "04", "真实顾虑", "decision-bottleneck", [8, 10], "images/generated/teacher_review_gate.png", "她守住的\n是不可替代性", cue_words("教师", "权威"), [text_layer("她守住的\n是不可替代性", slot="top-right"), stamp("软件改变了\n责任边界")], purpose="evidence", composition="evidence-collage", camera="push-in"),
            scene("s05", "05", "权力地图", "authority-matrix", [11, 15], "images/generated/education_power_triangle.png", "三方权力\n拼出局面", cue_words("校长", "教务", "家委会"), [text_layer("三方权力\n拼出局面"), network("关键三角", [{"id": "principal", "label": "校长", "sub": "预算", "emphasis": True}, {"id": "teacher", "label": "教务", "sub": "执行"}, {"id": "parents", "label": "家委会", "sub": "监督"}], [{"from": "principal", "to": "teacher", "label": "授权"}, {"from": "teacher", "to": "parents", "label": "解释"}, {"from": "parents", "to": "principal", "label": "压力"}])], purpose="explain", composition="split", camera="pull-out", treatment="blueprint"),
            scene("s06", "06", "方案调整", "local-playbook", [16, 17], "images/pool/office_followup.png", "先保住\n执行者权力", cue_words("培训", "权限"), [text_layer("先保住\n执行者权力", slot="top-right"), stamp("让软件成为\n老师的工具")], purpose="consequence", camera="drift"),
            scene("s07", "07", "信任设计", "split-data", 18, "images/generated/fairness_summary_meeting.png", "给家委会\n可见公平", cue_words("公平", "可见"), [text_layer("给家委会\n可见公平"), bars("信任来源", [("黑箱感", 34, "bad"), ("可解释", 84, "good")], text="监督方需要看见过程")], purpose="evidence", composition="evidence-collage"),
            scene("s08", "08", "结果验证", "decision-board", [19, 21], "images/pool/meeting_table.png", "共识先行\n签字有效", cue_words("共识", "落地"), [text_layer("共识先行\n签字有效", slot="top-right"), stamp("会后推进\n进入执行")], purpose="consequence", camera="push-in"),
            scene("s09", "09", "销售启示", "map-focus", [22, 23], "images/pool/hidden_decision.png", "找对人之前\n先画地图", cue_words("角色", "地图"), [text_layer("找对人之前\n先画地图"), network("购买小组", [{"id": "payer", "label": "付钱者"}, {"id": "user", "label": "使用者", "emphasis": True}, {"id": "watcher", "label": "监督者"}], [{"from": "payer", "to": "user"}, {"from": "user", "to": "watcher"}])], purpose="explain", treatment="blueprint"),
            scene("s10", "10", "栏目收束", "closing-idea", 24, "images/pool/closing_path.png", "权力地图清楚\n方案才会动", cue_words("权力地图", "方案"), [text_layer("权力地图清楚\n方案才会动"), stamp("销售不复杂")], purpose="reset", camera="pull-out"),
        ],
    },
    "output/case07_fintech_veto_video": {
        "title": "金融科技项目的否决椅",
        "subtitle": "谁坐在最后一把椅子上",
        "coverTitle": "金融科技项目的\n否决椅",
        "coverSubtitle": "谁坐在最后一把椅子上",
        "scenes": [
            scene("s01", "01", "开场", "hook-alert", [1, 2], "images/generated/compliance_veto_chair.png", "长桌尽头\n一句否决", cue_words("否决", "长桌"), [text_layer("长桌尽头\n一句否决"), stamp("最后一把椅子\n改变结果")], purpose="escalate", treatment="crisis"),
            scene("s02", "02", "表面进展", "subject-reveal", 3, "images/generated/fintech_risk_launch.png", "业务和科技\n都已点头", cue_words("业务", "科技"), [text_layer("业务和科技\n都已点头", slot="top-right"), stamp("流程看似\n接近完成")], purpose="identify", camera="pan-left"),
            scene("s03", "03", "隐藏否决", "decision-bottleneck", 4, "images/pool/hidden_veto.png", "流程最后\n藏着否决权", cue_words("流程", "否决权"), [text_layer("流程最后\n藏着否决权"), stamp("合规拥有\n最终刹车")], purpose="evidence", treatment="blueprint"),
            scene("s04", "04", "重新调查", "local-playbook", [5, 6], "images/pool/risk_meeting.png", "先问原因\n再改打法", cue_words("原因", "打法"), [text_layer("先问原因\n再改打法", slot="top-right"), bars("推进方式", [("产品说服", 38, "bad"), ("风险访谈", 88, "good")], text="换问题，才看见阻力")], purpose="explain"),
            scene("s05", "05", "合规阴影", "split-data", 7, "images/pool/compliance_docs.png", "三年前事故\n留下合规阴影", cue_words("事故", "合规"), [text_layer("三年前事故\n留下合规阴影"), stamp("历史风险\n控制现在")], purpose="evidence", composition="document-focus", camera="push-in"),
            scene("s06", "06", "边界共创", "authority-matrix", 8, "images/generated/dual_track_approval.png", "让他定义\n安全边界", cue_words("边界", "共创"), [text_layer("让他定义\n安全边界", slot="top-right"), network("审批双轨", [{"id": "business", "label": "业务"}, {"id": "tech", "label": "科技"}, {"id": "risk", "label": "合规", "emphasis": True}], [{"from": "business", "to": "risk", "label": "收益"}, {"from": "tech", "to": "risk", "label": "方案"}])], purpose="explain", composition="split"),
            scene("s07", "07", "风险可见", "decision-board", 9, "images/generated/risk_monitoring_room.png", "审批双轨\n风险可追踪", cue_words("双轨", "追踪"), [text_layer("审批双轨\n风险可追踪"), bars("可控性", [("上线速度", 64, "neutral"), ("风险透明", 91, "good")], text="让风险变成可管理对象")], purpose="consequence", camera="drift"),
            scene("s08", "08", "重新过会", "map-focus", 10, "images/pool/veto_network.png", "合规参与设计\n项目重新过会", cue_words("合规", "过会"), [text_layer("合规参与设计\n项目重新过会", slot="top-right"), stamp("否决者变成\n共同设计者")], purpose="consequence", treatment="blueprint"),
            scene("s09", "09", "合同落地", "subject-reveal", 11, "images/pool/redesign_workshop.png", "条件通过\n换回合同", cue_words("通过", "合同"), [text_layer("条件通过\n换回合同"), stamp("条件写进方案\n订单才落下")], purpose="consequence"),
            scene("s10", "10", "栏目收束", "closing-idea", [12, 13], "images/pool/closing_path.png", "椅子数量\n比名片重要", cue_words("椅子", "名片"), [text_layer("椅子数量\n比名片重要"), stamp("销售不复杂")], purpose="reset", camera="pull-out"),
        ],
    },
    "output/case09_logistics_priority_video": {
        "title": "冷链物流的真实优先级",
        "subtitle": "同一套方案，换一副眼镜",
        "coverTitle": "冷链物流的\n真实优先级",
        "coverSubtitle": "同一套方案，换一副眼镜",
        "scenes": [
            scene("s01", "01", "开场", "hook-alert", [1, 2], "images/pool/contract_table.png", "数据最优\n方案退回", cue_words("最优", "退回"), [text_layer("数据最优\n方案退回"), stamp("指标漂亮\n客户没签")], purpose="escalate", treatment="crisis"),
            scene("s02", "02", "公开目标", "subject-reveal", [3, 4], "images/pool/warehouse_aisle.png", "公开目标\n只说降本", cue_words("降本", "目标"), [text_layer("公开目标\n只说降本", slot="top-right"), stamp("采购语言\n掩住真实担心")], purpose="identify"),
            scene("s03", "03", "数字失效", "split-data", 5, "images/pool/warehouse_flow.png", "漂亮数字\n压不住风险", cue_words("数字", "风险"), [text_layer("漂亮数字\n压不住风险"), bars("客户看见的风险", [("成本节省", 72, "neutral"), ("断链损失", 94, "bad")], text="风险权重大过节省")], purpose="evidence", camera="push-in"),
            scene("s04", "04", "内部信号", "map-focus", 6, "images/pool/dispatch_network.png", "内部信号\n开始含糊", cue_words("信号", "含糊"), [text_layer("内部信号\n开始含糊", slot="top-right"), network("决策链", [{"id": "proc", "label": "采购"}, {"id": "ops", "label": "运营", "emphasis": True}, {"id": "coo", "label": "COO"}], [{"from": "proc", "to": "ops"}, {"from": "ops", "to": "coo"}])], purpose="explain", treatment="blueprint"),
            scene("s05", "05", "事故记忆", "subject-reveal", [7, 8], "images/pool/logistics_operator.png", "三十吨货损\n改写标准", cue_words("货损", "标准"), [text_layer("三十吨货损\n改写标准"), stamp("过去事故\n定义今天阈值")], purpose="evidence", camera="drift"),
            scene("s06", "06", "高层视角", "decision-bottleneck", 9, "images/pool/warehouse_meeting.png", "COO看到\n事故重演", cue_words("COO", "重演"), [text_layer("COO看到\n事故重演", slot="top-right"), stamp("真正目标\n是供应稳定")], purpose="escalate"),
            scene("s07", "07", "语言转换", "split-data", 10, "images/pool/cold_chain_network.png", "换成安全语言\n方案被看见", cue_words("安全", "语言"), [text_layer("换成安全语言\n方案被看见"), bars("表达重点", [("节省路线", 48, "neutral"), ("稳定交付", 96, "good")], text="方案没变，优先级变清楚")], purpose="consequence", treatment="blueprint"),
            scene("s08", "08", "订单落地", "decision-board", 11, "images/pool/warehouse_team.png", "优先级重排\n订单落地", cue_words("优先级", "订单"), [text_layer("优先级重排\n订单落地", slot="top-right"), stamp("客户买的\n是确定性")], purpose="consequence"),
            scene("s09", "09", "栏目收束", "closing-idea", [12, 13], "images/pool/closing_path.png", "同一方案\n换一副眼镜", cue_words("方案", "眼镜"), [text_layer("同一方案\n换一副眼镜"), stamp("销售不复杂")], purpose="reset", camera="pull-out"),
        ],
    },
    "output/case10_nev_parts_video": {
        "title": "新能源零部件的采购门",
        "subtitle": "技术通过之后，订单还差什么",
        "coverTitle": "新能源零部件的\n采购门",
        "coverSubtitle": "技术通过之后，订单还差什么",
        "scenes": [
            scene("s01", "01", "开场", "hook-alert", [1, 2], "images/generated/ev_module_test_bench.png", "技术第一\n订单没来", cue_words("技术", "订单"), [text_layer("技术第一\n订单没来"), stamp("测试过关\n采购仍停住")], purpose="escalate", treatment="crisis"),
            scene("s02", "02", "技术认可", "subject-reveal", [3, 5], "images/pool/production_line.png", "测试报告\n先过技术门", cue_words("测试", "技术门"), [text_layer("测试报告\n先过技术门", slot="top-right"), stamp("工程团队\n愿意推荐")], purpose="identify"),
            scene("s03", "03", "验证完成", "split-data", [6, 8], "images/pool/auto_factory.png", "十二项验证\n全部过关", cue_words("十二项", "过关"), [text_layer("十二项验证\n全部过关"), bars("验证结果", [("性能", 94, "good"), ("稳定", 91, "good"), ("兼容", 88, "good")], text="技术门票已经拿到")], purpose="evidence"),
            scene("s04", "04", "采购卡点", "decision-bottleneck", [9, 13], "images/generated/procurement_gate_closed.png", "技术门开了\n采购门还关着", cue_words("采购门", "卡点"), [text_layer("技术门开了\n采购门还关着", slot="top-right"), stamp("采购要看的\n是组织风险")], purpose="escalate", camera="push-in"),
            scene("s05", "05", "供应结构", "authority-matrix", [14, 16], "images/generated/supplier_balance_structure.png", "供应商结构\n决定动作", cue_words("供应商", "结构"), [text_layer("供应商结构\n决定动作"), network("供应格局", [{"id": "old", "label": "老供应商"}, {"id": "new", "label": "新模块", "emphasis": True}, {"id": "proc", "label": "采购"}], [{"from": "old", "to": "proc", "label": "关系"}, {"from": "new", "to": "proc", "label": "收益"}])], purpose="explain", composition="split", treatment="blueprint"),
            scene("s06", "06", "两条决策线", "map-focus", [17, 18], "images/pool/business_gate.png", "两条决策线\n分开推进", cue_words("技术线", "商务线"), [text_layer("两条决策线\n分开推进", slot="top-right"), stamp("技术讲性能\n商务讲收益")], purpose="explain"),
            scene("s07", "07", "收益模型", "split-data", 19, "images/generated/cost_model_discussion.png", "算清更换供应商\n真实收益", cue_words("收益", "更换"), [text_layer("算清更换供应商\n真实收益"), bars("采购账本", [("切换成本", 46, "bad"), ("年度收益", 89, "good")], text="采购需要可交代的账")], purpose="evidence", composition="evidence-collage"),
            scene("s08", "08", "KPI工具", "decision-board", [20, 22], "images/pool/cost_docs.png", "小模块变成\n采购KPI工具", cue_words("KPI", "工具"), [text_layer("小模块变成\n采购KPI工具", slot="top-right"), stamp("从产品参数\n变成管理答案")], purpose="consequence", composition="document-focus"),
            scene("s09", "09", "销售启示", "local-playbook", [23, 24], "images/pool/office_model.png", "技术是门票\n商务决定进场", cue_words("门票", "进场"), [text_layer("技术是门票\n商务决定进场"), network("两张门票", [{"id": "tech", "label": "技术"}, {"id": "business", "label": "商务", "emphasis": True}, {"id": "order", "label": "订单"}], [{"from": "tech", "to": "order"}, {"from": "business", "to": "order"}])], purpose="explain", treatment="blueprint"),
            scene("s10", "10", "栏目收束", "closing-idea", 25, "images/pool/closing_path.png", "组织利益\n决定采购答案", cue_words("组织利益", "采购"), [text_layer("组织利益\n决定采购答案"), stamp("销售不复杂")], purpose="reset", camera="pull-out"),
        ],
    },
    "output/case12_semiconductor_silence_video": {
        "title": "日本半导体客户的沉默流程",
        "subtitle": "客户沉默时，到底在发生什么",
        "coverTitle": "日本半导体客户的\n沉默流程",
        "coverSubtitle": "客户沉默时，到底在发生什么",
        "scenes": [
            scene("s01", "01", "开场", "hook-alert", [1, 4], "images/generated/japanese_semiconductor_visit.png", "最擅长的直接\n成了噪音", cue_words("直接", "噪音"), [text_layer("最擅长的直接\n成了噪音"), stamp("追问越多\n回应越少")], purpose="escalate", treatment="crisis"),
            scene("s02", "02", "表面沉默", "split-data", [5, 8], "images/pool/proposal_docs.png", "报价和技术\n没换来回应", cue_words("报价", "技术"), [text_layer("报价和技术\n没换来回应", slot="top-right"), bars("外部材料", [("参数完整", 88, "good"), ("内部共识", 32, "bad")], text="材料充分，内部仍未成形")], purpose="identify", composition="document-focus"),
            scene("s03", "03", "流程信号", "subject-reveal", [9, 12], "images/pool/review_meeting.png", "沉默本身\n就是流程信号", cue_words("沉默", "流程"), [text_layer("沉默本身\n就是流程信号"), stamp("暂未回应\n可能在内部流转")], purpose="evidence"),
            scene("s04", "04", "稟议流程", "map-focus", [13, 16], "images/generated/ringi_silent_process.png", "稟议制\n拆成多道章", cue_words("稟议", "签章"), [text_layer("稟议制\n拆成多道章", slot="top-right"), network("内部流转", [{"id": "user", "label": "使用部门"}, {"id": "quality", "label": "品质", "emphasis": True}, {"id": "proc", "label": "采购"}, {"id": "chief", "label": "部长"}], [{"from": "user", "to": "quality"}, {"from": "quality", "to": "proc"}, {"from": "proc", "to": "chief"}])], purpose="explain", treatment="blueprint"),
            scene("s05", "05", "缺席签章", "decision-bottleneck", [17, 19], "images/pool/silent_veto.png", "缺席的签章\n暴露卡点", cue_words("签章", "卡点"), [text_layer("缺席的签章\n暴露卡点"), stamp("真正问题\n藏在内部意见")], purpose="escalate", camera="push-in"),
            scene("s06", "06", "品质顾虑", "split-data", [20, 22], "images/generated/quality_concern_cleanroom.png", "品质顾虑\n需要稳定证据", cue_words("品质", "稳定"), [text_layer("品质顾虑\n需要稳定证据", slot="top-right"), bars("品质关心", [("价格优势", 42, "neutral"), ("稳定记录", 94, "good")], text="品质部门要的是可追溯")], purpose="evidence", composition="evidence-collage"),
            scene("s07", "07", "证据包", "decision-board", [23, 24], "images/generated/stability_data_package.png", "证据先进入\n内部共识", cue_words("证据", "共识"), [text_layer("证据先进入\n内部共识"), stamp("先帮客户\n完成内部说明")], purpose="consequence", composition="document-focus"),
            scene("s08", "08", "订单启动", "subject-reveal", 25, "images/pool/data_package.png", "理解沉默\n订单重新启动", cue_words("沉默", "订单"), [text_layer("理解沉默\n订单重新启动", slot="top-right"), stamp("节奏对了\n项目才动")], purpose="consequence"),
            scene("s09", "09", "销售启示", "local-playbook", 26, "images/pool/hidden_process.png", "换一双耳朵\n听见顾虑", cue_words("倾听", "顾虑"), [text_layer("换一双耳朵\n听见顾虑"), network("沉默背后", [{"id": "contact", "label": "联系人"}, {"id": "process", "label": "流程"}, {"id": "concern", "label": "顾虑", "emphasis": True}], [{"from": "contact", "to": "process"}, {"from": "process", "to": "concern"}])], purpose="explain", treatment="blueprint"),
            scene("s10", "10", "栏目收束", "closing-idea", 27, "images/pool/closing_path.png", "听懂沉默\n销售才有下一步", cue_words("沉默", "下一步"), [text_layer("听懂沉默\n销售才有下一步"), stamp("销售不复杂")], purpose="reset", camera="pull-out"),
        ],
    },
}


def collect_asset_sources(scenes: list[dict]) -> list[str]:
    sources: list[str] = []
    seen: set[str] = set()

    def add(src: str) -> None:
        if src not in seen:
            seen.add(src)
            sources.append(src)

    for scene_spec in scenes:
        add(scene_spec["background"])
        for beat in scene_spec.get("visualBeats", []):
            for layer in beat.get("layers", []):
                asset = layer.get("asset")
                if isinstance(asset, str):
                    add(asset)
                for node in layer.get("nodes", []):
                    node_asset = node.get("asset")
                    if isinstance(node_asset, str):
                        add(node_asset)
    return sources


def build_plan(project_path: str, config: dict[str, Any]) -> dict:
    project = ROOT / project_path
    generated = prompt_files(project)
    pool = pool_records(project)
    scenes = deepcopy(config["scenes"])
    bounds = paragraph_bounds(project)
    units = timeline_units(project)

    for scene_spec in scenes:
        paragraphs = scene_spec.get("paragraph", scene_spec.get("paragraphs"))
        first, last = scene_units(bounds, paragraphs)
        span = last - first
        scene_spec["visualBeats"] = clamp_offsets(scene_spec["visualBeats"], span)
        stage_visual_layers(scene_spec, first, last, units)

    visual_assets = []
    for src in collect_asset_sources(scenes):
        origin = "generated" if src in generated else "curated"
        asset = {
            "id": asset_id(src),
            "type": "image",
            "src": src,
            "role": role_for(src),
            "origin": origin,
        }
        if src in pool:
            asset["poolAssetId"] = pool[src]
        visual_assets.append(asset)

    slug = Path(project_path).name
    return {
        "project": {
            "slug": slug,
            "projectType": "sales-case",
            "title": config["title"],
            "subtitle": config["subtitle"],
            "brand": "销售不复杂",
            "subtitleLabel": "销售不复杂",
            "visualStyle": "sales-watercolor-blue-yellow",
            "cover": {
                "title": config["coverTitle"],
                "subtitle": config["coverSubtitle"],
                "kicker": "销售不复杂",
                "throughUnit": 1,
            },
        },
        "visualAssets": visual_assets,
        "displayReplacements": {},
        "scenes": scenes,
    }


def main() -> None:
    for project_path, config in PROJECTS.items():
        plan = build_plan(project_path, config)
        output = ROOT / project_path / "storyboard_plan.json"
        write_json(output, plan)
        print(f"wrote {output.relative_to(ROOT)} scenes={len(plan['scenes'])} assets={len(plan['visualAssets'])}")


if __name__ == "__main__":
    main()
