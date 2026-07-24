#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
from typing import Any

try:
    from scripts.visual_beat_planning import (
        BeatCandidate,
        schedule_visual_beats,
        text_alignment_score,
    )
except ModuleNotFoundError:  # Direct execution: scripts/ is sys.path[0].
    from visual_beat_planning import BeatCandidate, schedule_visual_beats, text_alignment_score


ROOT = Path(__file__).resolve().parents[1]

SALES_STYLE = (
    "Bright contemporary editorial watercolor and gouache illustration for a Chinese business case video, "
    "matching a blue-and-yellow industrial watercolor reference, luminous cream paper, dominant cobalt blue and sky blue washes, "
    "warm cadmium yellow highlights, expressive human figures, layered spatial depth, dynamic asymmetrical composition, "
    "generous clean negative space for motion graphics, no red, no coral, no pink, no rust, no orange-red accents, "
    "no logos, no readable text, no numerals, no letters, no watermark, cinematic 16:9, no flat vector art, "
    "no programmatic diagram, no icon set, no flowchart. "
)

MANAGEMENT_STYLE = (
    "Cohesive editorial silhouette illustration for a Chinese sales-management case video, cinematic 16:9 frame. "
    "Solid near-black foreground silhouettes with clear body language, secondary people and furniture layered in translucent deep navy, "
    "muted cobalt blue, burnt orange and dusty peach. Warm cream-to-amber backlight, high contrast rim lighting, flat cut-paper and screen-print shapes, "
    "subtle paper grain, simplified geometry, sophisticated corporate atmosphere, no detailed faces. "
    "Preserve generous clean negative space for motion graphics. No readable text, no letters, no numbers, no logos, no watermark, "
    "no name cards, no certificates, no presentation text, no legible laptop screens. "
    "Keep the same palette and rendering language across the whole set while changing location, camera angle, number of people and visual metaphor in every scene. "
    "This must be an AI-generated editorial narrative illustration, not a programmatic diagram, icon set, flowchart, UI dashboard or placeholder graphic. "
)

JAPANESE_PORTRAIT_STYLE = (
    "Square editorial watercolor and gouache character portrait matching a bright cobalt-blue and cadmium-yellow business illustration series. "
    "Pure clean white background with no shadow scenery, one Japanese businessperson shown from waist or mid-torso upward, formal dark business clothing, "
    "natural professional posture, recognizable but softly painted facial features, crisp foreground silhouette, cream paper texture only inside the figure, "
    "no props, no text, no letters, no numerals, no logos, no watermark, no border. "
)

def metric(
    label: str,
    to: float,
    suffix: str = "",
    *,
    from_value: float | None = None,
    prefix: str = "",
    decimals: int = 0,
    tone: str = "neutral",
) -> dict[str, Any]:
    value: dict[str, Any] = {"to": to}
    if suffix:
        value["suffix"] = suffix
    if prefix:
        value["prefix"] = prefix
    if decimals:
        value["decimals"] = decimals
    if from_value is not None:
        value["from"] = from_value
    return {"label": label, "value": value, "tone": tone}


def bar(label: str, value: float, suffix: str = "", tone: str = "neutral", maximum: float | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {"label": label, "value": value, "tone": tone}
    if suffix:
        item["suffix"] = suffix
    if maximum is not None:
        item["max"] = maximum
    return item


def V(name: str, prompt: str, candidate_keys: list[str]) -> dict[str, Any]:
    """Declare a semantic background variant for selected Visual Beat candidates."""

    if not re.fullmatch(r"[a-z0-9-]+", name):
        raise ValueError(f"visual variant name must be lowercase kebab-case: {name!r}")
    if not candidate_keys:
        raise ValueError(f"visual variant {name!r} must target at least one candidate key")
    return {
        "name": name,
        "prompt": prompt,
        "candidateKeys": candidate_keys,
    }


def S(
    paragraphs: list[int],
    headline: str,
    kicker: str,
    prompt: str,
    cards: list[str],
    *,
    person: str | None = None,
    speaker: str | None = None,
    quote: str | None = None,
    metrics: list[dict[str, Any]] | None = None,
    bars: list[dict[str, Any]] | None = None,
    nodes: list[str] | None = None,
    links: list[dict[str, Any]] | None = None,
    network_layout: str | None = None,
    role: str = "context",
    treatment: str = "natural",
    visual_variants: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "paragraphs": paragraphs,
        "headline": headline,
        "kicker": kicker,
        "prompt": prompt,
        "cards": cards,
        "person": person,
        "speaker": speaker,
        "quote": quote,
        "metrics": metrics or [],
        "bars": bars or [],
        "nodes": nodes or [],
        "links": links or [],
        "networkLayout": network_layout,
        "role": role,
        "treatment": treatment,
        "visualVariants": visual_variants or [],
    }


def select_scene_layout(
    scene: dict[str, Any],
    *,
    is_first: bool,
    is_last: bool,
) -> str:
    """Choose the scene fallback layout from narrative meaning, never scene index."""

    if is_first:
        return "hook-alert"
    if is_last:
        return "closing-idea"
    if scene.get("nodes") or scene.get("links"):
        return "decision-board"
    if scene.get("bars"):
        return "performance-ladder"
    if scene.get("metrics"):
        return "split-data"
    if scene.get("person"):
        return "subject-reveal"
    return "insight-split"


def select_scene_transition(scene: dict[str, Any]) -> str:
    """Use transition weight to signal story function rather than periodic variety."""

    if scene.get("treatment") == "crisis":
        return "ink"
    if scene.get("role") == "evidence":
        return "paper"
    if scene.get("nodes") or scene.get("links"):
        return "push"
    return "wash"


def select_scene_motion(scene: dict[str, Any], *, is_last: bool) -> str:
    """Choose restrained background motion from scene emphasis."""

    if is_last:
        return "breathe"
    if scene.get("treatment") == "crisis":
        return "lift"
    if scene.get("role") == "evidence" or scene.get("bars") or scene.get("metrics"):
        return "center"
    if scene.get("nodes") or scene.get("links"):
        return "left"
    if scene.get("person"):
        return "drift"
    return "breathe"


PROJECTS: dict[str, dict[str, Any]] = {
    "case09_logistics_priority_video": {
        "projectType": "sales-case",
        "title": "一份完美方案，为什么被退回两次",
        "coverTitle": "一份完美方案\n为什么被退回两次",
        "subtitle": "真正的优先级，藏在决策者的伤疤里",
        "visualStyle": "bright-editorial-watercolor sales-watercolor-blue-yellow",
        "style": SALES_STYLE,
        "scenes": [
            S([1, 2], "数据完美\n两次退回", "无声退回", "A Chinese cold-chain solution sales manager alone at a desk late at night, an unsigned proposal folder pushed back across the table, refrigerated trucks and warehouse lights outside, tense empty space around him.", ["数据完美", "两次退回", "没有理由"], person="chen-hao", speaker="陈昊", quote="这单到底卡在哪里？", metrics=[metric("退回次数", 2, "次", tone="bad")], treatment="crisis"),
            S([3, 4], "公开目标\n看似清晰", "降本方案", "A vast cold-chain distribution operation across several provinces, many small warehouse nodes connected by blue transport routes, a sales engineer presenting a consolidation concept while executives observe from a distance.", ["公开目标：降本", "前置仓从23到15", "年度节省1800万"], person="chen-hao", speaker="陈昊", quote="每个数字都有模型支撑。", metrics=[metric("前置仓", 15, "个", from_value=23, tone="good"), metric("年度节省", 1800, "万", tone="good")], bars=[bar("原有仓网", 23, "个", "neutral", 23), bar("优化后", 15, "个", "good", 23)]),
            S([5, 6], "所有线索\n都很模糊", "反复排查", "A sales manager moving between a procurement office, an IT dinner meeting and a wall of competitor clues, every doorway half closed, ambiguous body language and no clear answer.", ["内部流程", "周总很审慎", "竞争对手无异常"], person="chen-hao", speaker="陈昊", quote="能省这么多，为什么还审慎？", nodes=["陈昊", "采购总监", "IT负责人", "COO"], treatment="desaturated"),
            S([7, 8], "事故记忆\n突然浮现", "饭局转折", "An industry dinner conversation in the foreground, one operations manager leaning closer to reveal a secret, behind them a dramatic watercolor flashback of a refrigerated warehouse failure and spoiled frozen cargo.", ["30吨冻品", "停机6小时", "损失2300万"], person="zhang-lei", speaker="张磊", quote="你知道去年那批冻品的事吗？", metrics=[metric("冻品", 30, "吨", tone="bad"), metric("直接损失", 2300, "万", tone="bad")], role="evidence", treatment="crisis"),
            S([9, 9], "同一方案\n两种风险观", "视角冲突", "A split editorial metaphor: on one side an optimistic chief executive sees a streamlined warehouse network and sunlight, on the other an operations chief sees a longer fragile cold-chain route haunted by a past breakdown.", ["CEO看到降本", "COO看到风险", "减少节点意味着更长链路"], person="zhou-jianguo", speaker="周建国", quote="少一个节点，就多一段风险。", bars=[bar("原仓网", 23, "个", "neutral", 23), bar("精简后", 15, "个", "bad", 23)], nodes=["公开战略", "方案语言", "事故记忆", "审批判断"], role="metaphor", treatment="crisis"),
            S([10, 10], "降本叙事\n改成零中断", "重新表达", "A sales manager rebuilding a proposal from a blank page, backed by resilient cold-storage hubs with dual refrigeration systems, temperature sensors and alternative transport paths glowing in blue and yellow.", ["零中断冷链", "覆盖率87%到99.5%", "响应45分钟到8分钟"], person="chen-hao", speaker="陈昊", quote="先回答他最怕发生什么。", metrics=[metric("温控覆盖率", 99.5, "%", from_value=87, decimals=1, tone="good"), metric("异常响应", 8, "分钟", from_value=45, tone="good")], bars=[bar("原覆盖率", 87, "%", "bad", 100), bar("新覆盖率", 99.5, "%", "good", 100), bar("原响应", 45, "分钟", "bad", 45), bar("新响应", 8, "分钟", "good", 45)]),
            S([11, 11], "第53天\n终于获批", "审批结果", "An approved proposal arriving by phone call, a relieved sales manager in the foreground, operations leaders reviewing a resilient warehouse plan and a formal handshake near refrigerated logistics facilities.", ["第53天获批", "技术只改15%", "合同1200万"], person="chen-hao", speaker="陈昊", quote="产品没变，决策语言变了。", metrics=[metric("获批用时", 53, "天", tone="neutral"), metric("合同金额", 1200, "万", tone="good")], role="evidence"),
            S([12, 12], "决策者都戴着\n自己的眼镜", "案例诊断", "A decision chain of business leaders viewing the same logistics proposal through different translucent lenses, each lens shaped by a different recent experience, with one painful memory casting the strongest shadow.", ["同一份方案", "不同的判断镜片", "最近的痛塑造优先级"], nodes=["CEO公开目标", "COO事故记忆", "采购流程", "最终审批"], role="metaphor"),
            S([13, 13], "找到真实痛点\n换成对方语言", "销售启示", "A confident solution salesperson crossing a bright bridge from a technical proposal toward a customer's real operational priorities, cold-chain facilities becoming stable and connected in the distance.", ["找到真实痛点", "用对方语言重讲", "价值胜过包装"], person="chen-hao", speaker="陈昊", quote="先读懂那副眼镜。", role="metaphor"),
        ],
    },
    "case10_nev_parts_video": {
        "projectType": "sales-case",
        "title": "技术评分第一，为什么拿不到订单",
        "coverTitle": "技术评分第一\n为什么拿不到订单",
        "subtitle": "采购有另一张计分表",
        "visualStyle": "bright-editorial-watercolor sales-watercolor-blue-yellow",
        "style": SALES_STYLE,
        "scenes": [
            S([1, 2], "十二项通过\n依然没有订单", "技术冠军", "An advanced electric vehicle component test laboratory, a thermal-management module passing multiple rigorous test stations while an unopened procurement gate remains in the background.", ["12项验证全通过", "技术评分第一", "半年零订单"], person="chen-hao", speaker="陈昊", quote="技术赢了，订单为什么没来？", metrics=[metric("技术验证", 12, "项", tone="good"), metric("采购订单", 0, "张", tone="bad")], treatment="crisis"),
            S([3, 5], "研发出身\n相信数据定胜负", "主场错觉", "A technically trained sales engineer holding a compact automotive thermal module between an engineering lab and a major vehicle factory, confident that test data will open the commercial door.", ["八年行业经验", "研发转销售", "客户年产超40万台"], person="chen-hao", speaker="陈昊", quote="这应该是我的主场。", metrics=[metric("行业经验", 8, "年"), metric("客户年产", 40, "万台", tone="good")]),
            S([6, 8], "产品很强\n信心也很满", "测试证据", "A dynamic automotive test scene with a lightweight liquid-cooling module under heat, vibration and protection testing, engineers observing successful results and preparing capacity plans.", ["轻15%", "效率高22%", "综合评分93"], person="chen-hao", speaker="陈昊", quote="三个方案里，我们最高。", metrics=[metric("综合评分", 93, "分", tone="good")], bars=[bar("重量优势", 15, "%", "good", 25), bar("效率提升", 22, "%", "good", 25), bar("综合评分", 93, "分", "good", 100)], role="evidence"),
            S([9, 13], "采购很客气\n门却始终不开", "流程拖延", "A procurement manager behind a glass office wall, polite phone conversation in the foreground, unanswered email shapes and a quarterly review room beyond a closed door.", ["第三周申请对接", "等待季度评审", "暂不新增供应商"], person="fang-manager", speaker="方经理", quote="供应商导入有流程。", nodes=["技术验证", "商务对接", "季度评审", "暂不导入"], treatment="desaturated"),
            S([14, 16], "真正线索\n来自技术同事", "会后提醒", "After a technical retest meeting, a young engineer quietly speaks with the sales engineer in an empty corridor, pointing toward a distant procurement office and an unseen supplier structure.", ["技术确实认可", "采购另有考量", "先看三家供应商格局"], person="zhou-yang", speaker="周阳", quote="卡点跟技术评分关系不大。", nodes=["技术中心", "采购部门", "现有供应商", "陈昊"]),
            S([17, 18], "三家供应商\n形成稳定三角", "供应格局", "A candid supplier strategy workshop inside an automotive factory office: a procurement team examines three physically distinct component samples on a clean table, while three supplier representatives occupy separate, balanced positions in the room. Show people, components and spatial tension only. No charts, no labels, no arrows, no diagrams, no signs, no screens, no text, no letters, no numerals.", ["稳定品质", "性价比", "小批量验证"], nodes=["日资稳定型", "本土性价比", "台资试制型", "采购平衡"], bars=[bar("稳定型份额", 45, "%", "neutral", 50), bar("性价比份额", 35, "%", "good", 50), bar("试制型份额", 20, "%", "neutral", 50)], role="map"),
            S([19, 20], "第四家进入\n会打乱采购KPI", "组织利益", "A procurement leader balancing supplier quotations and annual cost targets, while a fourth supplier approaching the arrangement creates visible tension in the otherwise stable negotiating structure.", ["年节降5%到8%", "成本KPI权重40%", "第四家带来当期成本"], person="fang-manager", speaker="方经理", quote="我要先守住采购节奏。", metrics=[metric("KPI权重", 40, "%", tone="bad")], bars=[bar("年度节降下限", 5, "%", "neutral", 10), bar("年度节降上限", 8, "%", "good", 10), bar("成本KPI权重", 40, "%", "bad", 50)], role="metaphor", treatment="crisis"),
            S([21, 22], "技术赛道\n商务赛道", "平行计分", "Two parallel race lanes in an automotive business setting, one lined with laboratory tests and the other with procurement scorecards, the same sales engineer realizing the finish lines are controlled by different people.", ["技术验证是预选赛", "商务有独立规则", "决定权属于另一群人"], person="chen-hao", speaker="陈昊", quote="我赢的是另一场比赛。", nodes=["产品能力", "技术准入", "采购KPI", "订单决定"], role="metaphor"),
            S([23, 24], "不做新增\n改做结构优化", "重构方案", "A cost model being rebuilt around replacing one premium component share on a single vehicle platform, with a lighter thermal module entering the supplier structure without disrupting the whole system.", ["单件BOM降18元", "年产8万台", "年节降144万"], person="chen-hao", speaker="陈昊", quote="让采购的计分表更好看。", metrics=[metric("单件BOM", 18, "元", tone="good"), metric("年节降", 144, "万", tone="good")], bars=[bar("单件节省", 18, "元", "good", 20), bar("年度节省", 144, "万", "good", 160)], role="evidence"),
            S([25, 25], "拿到定点\n首年1600万", "订单与启示", "A supplier nomination moment beside a modern vehicle production line, the sales engineer and procurement leader reviewing a successful cost structure while components move toward delivery.", ["两个月后定点", "首年1600万", "先看懂计分规则"], person="chen-hao", speaker="陈昊", quote="技术是门票，采购决定要不要。", metrics=[metric("首年采购额", 1600, "万", tone="good")], role="evidence"),
        ],
    },
    "case12_semiconductor_silence_video": {
        "projectType": "sales-case",
        "title": "三次“検討します”背后的沉默否决",
        "coverTitle": "三次“検討します”\n背后的沉默否决",
        "subtitle": "复杂销售里，没说话的人也在投票",
        "visualStyle": "bright-editorial-watercolor sales-watercolor-blue-yellow",
        "style": SALES_STYLE,
        "generatedPortraits": [
            {"id": "portrait-tanaka", "file": "images/characters/tanaka.png", "prompt": JAPANESE_PORTRAIT_STYLE + "A Japanese male procurement executive in his early fifties, calm courteous expression, front three-quarter view, screen-left gaze."},
            {"id": "portrait-yamamoto", "file": "images/characters/yamamoto.png", "prompt": JAPANESE_PORTRAIT_STYLE + "A Japanese male quality director in his late fifties, reserved serious expression, front view, composed posture."},
        ],
        "scenes": [
            S([1, 4], "高效直接\n却败给友好沉默", "跨文化盲区", "A decisive Chinese semiconductor equipment salesperson arriving in Tokyo with confidence, facing a courteous Japanese meeting room where polite silhouettes and deep negative space suggest an invisible barrier.", ["八年设备销售", "预算超过2000万", "友好沉默慢慢杀单"], person="chen-rui", speaker="陈锐", quote="技术领先，价格合理，为什么不推进？", metrics=[metric("采购预算", 2000, "万+", tone="good")], treatment="crisis"),
            S([5, 8], "频频点头\n第一次“検討”", "东京首访", "A formal Tokyo conference room, a Chinese salesperson presenting a thick technical deck while a courteous Japanese procurement executive listens, takes notes and smiles without revealing a decision.", ["五十页方案", "演示四十分钟", "我们会検討します"], person="tanaka", speaker="田中诚一", quote="非常精彩，我们会検討します。", metrics=[metric("技术方案", 50, "页"), metric("演示时长", 40, "分钟")], role="evidence"),
            S([9, 12], "礼貌回复\n时间不断后移", "持续等待", "A sequence of polite follow-up moments: an email arriving quickly, a quiet phone call and calendar pages moving forward, while the procurement process remains visually motionless behind frosted glass.", ["两周后邮件", "一个月后电话", "仍在内部传阅"], person="tanaka", speaker="田中诚一", quote="请再给我们一些时间。", nodes=["邮件跟进", "部门传阅", "等待", "没有决定"], treatment="desaturated"),
            S([13, 16], "降价5%\n品质仍然沉默", "第二次拜访", "A second Japanese business meeting with the production representative asking technical questions while the quality director sits silent in a darker part of the room, and a revised offer rests between them.", ["报价降低5%", "生产追问细节", "品质全程沉默"], person="yamamoto", speaker="山本主任", quote="沉默本身就是信号。", metrics=[metric("主动降价", 5, "%", tone="bad")], nodes=["采购窗口", "生产部门", "品质部门", "陈锐"], treatment="crisis"),
            S([17, 19], "三次拜访\n三次“検討”", "沉默累积", "The same salesperson making repeated trips through an airport and into three similarly courteous meeting rooms, each ending at a softly closed door with no negotiation and no explicit rejection.", ["三次拜访", "三次検討します", "没有反对也没有砍价"], person="chen-rui", speaker="陈锐", quote="对方从没说不行。", metrics=[metric("拜访次数", 3, "次", tone="bad")], role="metaphor", treatment="crisis"),
            S([20, 21], "窗口在说话\n决策者藏在后面", "周航翻译", "An experienced colleague who knows Japanese companies sketches an invisible approval chain for the puzzled salesperson, revealing multiple decision makers behind the single procurement contact.", ["多少部门要签章", "采购窗口不等于决策", "礼貌意味着流程未过"], person="zhou-hang", speaker="周航", quote="还有人没签字。", nodes=["采购窗口", "内部部门", "未签章者", "订单结果"], role="map"),
            S([22, 22], "六个部门\n任何一处都能停住", "稟議制", "A Japanese consensus approval process shown as a ceremonial paper journey through several departments, dark silhouettes passing the document onward while one unlit quality gate stops the entire route.", ["技术与生产", "品质与财务", "法务与事业部长"], nodes=["采购技术", "生产品质", "财务法务", "事业部长"], role="map"),
            S([23, 24], "真正障碍\n是品质未签章", "隐藏否决", "A reserved quality director stands before a dark factory gate, with a flashback of chemical residue causing a semiconductor line stoppage and a demand for long-term stability evidence.", ["品质部未表态", "过去产线停两天", "需要三个月稳定记录"], person="yamamoto", speaker="山本主任", quote="我要看到持续稳定的数据。", metrics=[metric("产线停机", 2, "天", tone="bad"), metric("稳定记录", 3, "个月+", tone="good")], role="evidence", treatment="crisis"),
            S([25, 25], "不再催进度\n改送稳定证据", "精准补证", "A semiconductor salesperson carefully compiling long-running operating evidence from several wafer fabs, with abstract monitoring curves and clean equipment scenes passed discreetly into a quality department.", ["三家晶圆厂", "连续运行数据", "两个月整理证据"], person="chen-rui", speaker="陈锐", quote="补上他真正缺的证据。", metrics=[metric("运行工厂", 3, "家", tone="good"), metric("准备时间", 2, "个月")], role="evidence"),
            S([26, 26], "品质签章\n订单2300万", "流程转动", "A courteous procurement executive making a direct phone call as the previously dark quality gate lights up, followed by semiconductor cleaning equipment entering a modern Japanese fab.", ["三周后主动来电", "品质部已签章", "订单2300万"], person="tanaka", speaker="田中诚一", quote="品质部已经签章了。", metrics=[metric("订单金额", 2300, "万", tone="good"), metric("超预算", 15, "%", tone="good")], role="evidence"),
            S([27, 27], "读懂没说话的人\n解决没说出口的顾虑", "案例启示", "A listening metaphor in a quiet boardroom: one missing approval silhouette becomes illuminated as the salesperson slows down, listens to silence and connects with the real decision maker.", ["读懂谁没有说话", "找到未签章者", "解决未说出口的顾虑"], person="chen-rui", speaker="陈锐", quote="沉默的人，也在投票。", role="metaphor"),
        ],
    },
    "sales_management_case06_video": {
        "projectType": "sales-management-case",
        "title": "CRM为什么越管越不真实",
        "coverTitle": "CRM为什么\n越管越不真实",
        "subtitle": "数据质量的底层，是心理安全",
        "visualStyle": "warm-manager-silhouette-motion-graphics",
        "style": MANAGEMENT_STYLE,
        "scenes": [
            S([1, 4], "漏斗很健康\n结果差一半", "数据幻觉", "A senior sales leader silhouetted before a glowing sales funnel wall that looks full and healthy, while a much smaller signed-results stack sits in the foreground under a harsh amber spotlight.", ["47笔Commit", "漏斗1.2亿元", "预期9000万，实际5800万"], person="liu-yuanhang", speaker="刘远航", quote="漏斗这么健康，结果为什么差这么远？", metrics=[metric("Commit商机", 47, "笔"), metric("实际签约", 5800, "万", tone="bad")], bars=[bar("漏斗金额", 12000, "万", "neutral", 12000), bar("预期收入", 9000, "万", "good", 12000), bar("实际签约", 5800, "万", "bad", 12000)], treatment="crisis"),
            S([5, 7], "管理者发火\n团队保持沉默", "错误处方", "A sales vice president in a town-hall spotlight pointing toward a large CRM wall, with the whole team sitting in near-black silence and exchanging guarded glances.", ["每周抽查字段", "不合格扣绩效", "没人反驳也没人改变"], person="liu-yuanhang", speaker="刘远航", quote="下个月开始，直接扣绩效。", nodes=["管理者压力", "字段抽查", "团队沉默", "数据更假"], treatment="crisis"),
            S([8, 12], "说出坏消息\n付出四十分钟", "诚实代价", "An honest salesperson alone at a review table under a tight spotlight, entering a lost opportunity while a manager and colleagues question him for a long time, the room growing increasingly tense.", ["客户明确拒绝", "如实建议关闭", "公开追问40分钟"], person="chen-shi", speaker="陈实", quote="客户选择竞品，建议关闭。", metrics=[metric("公开盘问", 40, "分钟", tone="bad"), metric("跟进周期", 3, "个月")], role="evidence", treatment="crisis"),
            S([13, 16], "录“推进中”\n成本最低", "隐形规则", "Rows of salespeople shelter behind identical active-opportunity cards like shields, while one truthful closed record stands exposed under a bright interrogation light.", ["真话成本40分钟", "推进中成本为零", "一切正常最安全"], nodes=["客户拒绝", "录入关闭", "公开盘问", "改录推进中"], metrics=[metric("假话代价", 0, "", tone="good")], role="metaphor"),
            S([17, 19], "商机只进不出\n漏斗成了盾牌", "理性自保", "An inflated sales funnel shaped like a protective shield, packed with aging opportunities while real customer activity fades outside, managers viewing an impressive but hollow silhouette.", ["商机只进不出", "季末悄悄降级", "CRM用于自我保护"], nodes=["惩罚真话", "选择安全", "漏斗膨胀", "决策失真"], role="metaphor", treatment="desaturated"),
            S([20, 22], "23笔停留超90天\n11笔近30天零互动", "真相浮现", "A trusted top salesperson quietly explains the pattern over dinner, followed by the manager at night auditing stale opportunities spread across a long dark timeline.", ["李颖说出原因", "23笔超过90天", "11笔近30天无互动"], person="li-ying", speaker="李颖", quote="填真话的人，会被追问四十分钟。", metrics=[metric("长期滞留", 23, "笔", tone="bad"), metric("近期零互动", 11, "笔", tone="bad")], bars=[bar("滞留超90天", 23, "笔", "bad", 25), bar("近30天零互动", 11, "笔", "bad", 25)], role="evidence"),
            S([23, 25], "关闭变安全\n活跃要证据", "规则反转", "A sales leader publicly praising an honest closed opportunity, then flipping a rule board so truthful closure becomes safe while unsupported active deals face focused review.", ["关闭只写一句理由", "最多两行", "只追问无证据的活跃商机"], person="liu-yuanhang", speaker="刘远航", quote="坏消息也是有价值的数据。", nodes=["如实关闭", "释放精力", "活跃需证据", "真实漏斗"], role="evidence"),
            S([26, 27], "数字变难看\n经营反而变好", "真实结果", "A cleaner smaller sales funnel with only genuine opportunities, salespeople actively calling customers while the manager calmly allocates attention toward the strongest paths.", ["新增32条关闭", "漏斗1.2亿到7800万", "签约8300万，转化率65%"], metrics=[metric("新增关闭", 32, "条"), metric("季度签约", 8300, "万", tone="good"), metric("真实转化率", 65, "%", from_value=48, tone="good")], bars=[bar("原漏斗", 12000, "万", "neutral", 12000), bar("真实漏斗", 7800, "万", "good", 12000), bar("签约", 8300, "万", "good", 12000)], role="evidence"),
            S([28, 28], "系统流动数据\n也流动安全感", "管理启示", "A psychologically safe sales team in warm backlight, one representative writing a short factual update and then returning to customer calls while the manager reads data without blame.", ["两小时故事变五分钟事实", "追责让数据说谎", "决策让数据说实话"], person="chen-shi", speaker="陈实", quote="现在我写事实，剩下时间打客户。", metrics=[metric("录入用时", 5, "分钟", from_value=120, tone="good")], role="metaphor"),
        ],
    },
    "sales_management_case07_video": {
        "projectType": "sales-management-case",
        "title": "团队不协作，真的是人太自私吗",
        "coverTitle": "团队不协作\n真的是人太自私吗",
        "subtitle": "制度每天都在教团队如何选择",
        "visualStyle": "warm-manager-silhouette-motion-graphics",
        "style": MANAGEMENT_STYLE,
        "scenes": [
            S(
                [1, 3],
                "关系一共享\n效率就能翻倍？",
                "协作目标",
                "A symmetrical hospital corridor with medical-device sales teams from two specialties placed near the outer thirds, each holding different customer relationships. A promising shared product opportunity glows in the uncluttered center, leaving clean central negative space for a title.",
                ["跨科室联动", "共享客户关系", "推广效率翻倍"],
                person="he-chen",
                speaker="何晨",
                quote="一个人的关系，可以变成两个人的机会。",
                nodes=["心内科销售", "骨科销售", "医院关系", "新产品机会"],
                links=[{"from": 1, "to": 3, "label": "共享"}, {"from": 2, "to": 3, "label": "共享"}, {"from": 3, "to": 4, "label": "转化"}],
                network_layout="grid",
                visual_variants=[
                    V(
                        "relationship-handoff",
                        "Two medical-device salespeople from different specialties make a deliberate warm handoff to a hospital decision maker at a corridor intersection, one introducing the other while a product case sits between them. The human connection is clear through gesture and eyeline, with no diagrams or visible text.",
                        ["point-2", "point-3", "relationship"],
                    )
                ],
            ),
            S(
                [4, 6],
                "口号很响\n行动为零",
                "动员失效",
                "A regional manager gives an energetic teamwork speech to rows of medical salespeople in a warm training room, while the audience remains formally attentive rather than genuinely connected. Keep presentation surfaces blank and leave open space around the speaker.",
                ["团队精神动员", "专题培训", "什么都没发生"],
                person="he-chen",
                speaker="何晨",
                quote="大家一起赢。",
                nodes=["动员", "培训", "合照", "零行动"],
                links=[{"from": 1, "to": 2, "label": "追加"}, {"from": 2, "to": 3, "label": "完成"}, {"from": 3, "to": 4, "label": "未转化"}],
                network_layout="row",
                treatment="desaturated",
                visual_variants=[
                    V(
                        "posed-training-photo",
                        "A carefully posed medical sales team photo after an external collaboration workshop, everyone smiling formally under warm light but standing in separate rigid rows, suggesting surface-level unity. No banners, certificates, logos or readable signs.",
                        ["point-2"],
                    ),
                    V(
                        "empty-office-afterwards",
                        "The same sales office later sits quiet and compartmentalized: separate desks, unused chairs and isolated silhouettes working alone, with no one crossing the central aisle. The training energy has vanished and no collaboration is happening.",
                        ["point-3", "relationship"],
                    ),
                ],
            ),
            S(
                [7, 11],
                "线索就在手里\n王琦却不开口",
                "个人选择",
                "A medical-device salesperson notices a valuable orthopedic equipment opportunity while passing a hospital department doorway, but keeps the knowledge to himself as another specialty colleague walks away in the distance. Use body language and spatial separation, no signs or readable department labels.",
                ["知道骨科更新线索", "季度还差120万", "时间已经排满"],
                person="wang-qi",
                speaker="王琦",
                quote="我这个季度还差一百二十万。",
                metrics=[metric("指标缺口", 120, "万", tone="bad")],
                nodes=["王琦掌握线索", "帮助赵明", "占用自己时间", "自己指标承压"],
                links=[{"from": 1, "to": 2, "label": "可选择"}, {"from": 2, "to": 3, "label": "需要"}, {"from": 3, "to": 4, "label": "加重"}],
                network_layout="row",
                treatment="crisis",
                visual_variants=[
                    V(
                        "target-pressure",
                        "A pressured medical sales representative alone at a desk, surrounded by a crowded travel bag, phone, appointment folders and a looming abstract target shadow. He grips his calendar while the chance to help a colleague remains outside the light. All papers and screens are blank.",
                        ["point-2", "dialogue", "metric-1"],
                    ),
                    V(
                        "schedule-overload",
                        "A fast-moving week of hospital visits shown through one exhausted salesperson crossing multiple corridors and transit spaces, carrying samples and rushing past a colleague who needs help. Convey a completely full schedule without calendars, clocks, text or numbers.",
                        ["point-3", "relationship"],
                    ),
                ],
            ),
            S(
                [12, 14],
                "帮别人签80万\n自己的提成为零",
                "高铁真话",
                "Inside a Chinese high-speed train, a regional manager appears to rest by the window while two veteran medical salespeople in the adjacent row speak candidly in low voices. Passing light and reflected silhouettes create a private, revealing moment; no visible signage or screen text.",
                ["协助成交80万", "个人提成为零", "还损失拜访时间"],
                person="he-chen",
                speaker="老销售",
                quote="帮别人，月底我的报表看不到。",
                metrics=[metric("协助成交", 80, "万"), metric("协助提成", 0, "元", tone="bad")],
                role="evidence",
                visual_variants=[
                    V(
                        "manager-realization",
                        "The regional manager sits silently beside the train window after overhearing the conversation, eyes lowered in thought as two reflected paths appear in the glass: helping a colleague versus protecting one's own target. Keep the metaphor subtle and free of text, numbers or diagrams.",
                        ["point-2", "point-3", "metric-2"],
                    )
                ],
            ),
            S(
                [15, 15],
                "谁签单算谁的\n帮忙等于惩罚自己",
                "制度信号",
                "A stark incentive imbalance in a sales office: the salesperson signing a hospital deal stands elevated in warm light while a helper below carries extra samples, travel burden and paperwork in shadow. Show the unequal outcome through staging, not charts or text.",
                ["签单者拿全部业绩", "帮助者承担成本", "归属争议增加风险"],
                nodes=["帮助同事", "投入时间", "收益归别人", "理性地不帮"],
                links=[{"from": 1, "to": 2, "label": "增加"}, {"from": 2, "to": 3, "label": "换不来"}, {"from": 3, "to": 4, "label": "促成"}],
                network_layout="row",
                role="metaphor",
                treatment="crisis",
                visual_variants=[
                    V(
                        "ownership-conflict",
                        "Two medical salespeople stand on opposite sides of the same hospital opportunity folder, each reaching for ownership while a third helper withdraws from the argument. A rigid overhead shadow suggests an unfair commission rule; no labels, charts, arrows or text.",
                        ["point-3", "relationship"],
                    )
                ],
            ),
            S(
                [16, 16],
                "全年只协助7次\n4次来自新人",
                "行为证据",
                "A manager at night reviews an extremely sparse annual trail of real collaboration moments across a large dark office wall, with only a handful of warm human handoffs separated by long empty stretches. Keep every document and screen abstract and unreadable.",
                ["全年主动协助7次", "其中4次在入职前三个月", "培训曲线上没有痕迹"],
                metrics=[metric("全年协助", 7, "次", tone="bad"), metric("新人贡献", 4, "次")],
                bars=[bar("全年主动协助", 7, "次", "bad", 12), bar("新人前三个月", 4, "次", "neutral", 12)],
                role="evidence",
                visual_variants=[
                    V(
                        "newcomer-fading",
                        "Several newly hired medical salespeople enthusiastically introduce colleagues during their first weeks, but the warm connection gradually dims as they observe experienced staff working alone under the existing incentive system. Show a human before-and-after progression without charts or labels.",
                        ["point-2", "point-3", "comparison"],
                    )
                ],
            ),
            S(
                [17, 18],
                "成交额10%\n计入协同贡献",
                "机制改造",
                "A regional manager visits a better-performing peer team and listens closely as another manager explains a simple collaboration-credit practice around a blank tabletop. The atmosphere is practical and credible, with no presentation text or visible numbers.",
                ["成交额10%计入考核", "80万变8万贡献分", "审批不超过5分钟"],
                person="he-chen",
                speaker="何晨",
                quote="让帮助别人，也能帮助自己。",
                metrics=[metric("协同贡献", 10, "%", tone="good"), metric("审批时间", 5, "分钟", tone="good")],
                role="evidence",
                visual_variants=[
                    V(
                        "joint-hospital-service",
                        "Two medical-device salespeople jointly serve one hospital decision maker, each contributing distinct expertise while both remain visibly included in the successful handoff. Warm backlight joins the trio; no diagrams, text, numerals or paperwork details.",
                        ["point-1", "point-2", "metric-1", "dialogue"],
                    ),
                    V(
                        "quick-approval-handoff",
                        "A concise approval handoff moves smoothly from a collaborating salesperson to a calm regional manager and back to the team, shown through one small blank form and decisive gestures. Convey speed and low friction without clocks, UI, text or numbers.",
                        ["point-3", "metric-2"],
                    ),
                ],
            ),
            S(
                [19, 20],
                "三十天\n协助从0到11",
                "行为改变",
                "After the rule change, medical salespeople from different specialties now introduce one another to hospital decision makers and exchange leads in a lively corridor. Warm connections multiply through real gestures and eye contact, without drawn lines, labels or diagrams.",
                ["30天", "主动协助0到11次", "线索开始双向流动"],
                person="wang-qi",
                speaker="王琦",
                quote="这条线索，我和赵明一起跟。",
                metrics=[metric("主动协助", 11, "次", from_value=0, tone="good")],
                bars=[bar("规则前", 0, "次", "bad", 12), bar("规则后", 11, "次", "good", 12)],
                role="evidence",
                visual_variants=[
                    V(
                        "joint-customer-visit",
                        "Wang Qi and another specialist arrive together for a hospital customer visit, share product samples and enter the meeting side by side while colleagues exchange useful introductions nearby. The scene feels active, reciprocal and newly normal; no visible text or logos.",
                        ["point-2", "point-3", "dialogue", "comparison"],
                    )
                ],
            ),
            S(
                [21, 24],
                "制度是无声的\n二十四小时管理者",
                "管理启示",
                "A regional manager opens an abstract commission workbook on a desk and studies which daily behaviors the system rewards, while the sales team continues making choices in the background. Every page and screen is blank, with a large warm institutional shadow shaping the room.",
                ["制度每天都在说话", "奖励决定行为", "抱怨前先看提成表"],
                person="he-chen",
                speaker="何晨",
                quote="先看看制度在奖励什么。",
                metrics=[metric("制度管理", 24, "小时/天")],
                role="metaphor",
                visual_variants=[
                    V(
                        "silent-manager-shadow",
                        "Across morning, afternoon and evening, the same sales team repeatedly chooses between helping colleagues and protecting individual targets while a single silent system shadow remains over every scene. Use changing light and body language only, with no clocks, text, numbers or diagrams.",
                        ["point-1", "point-2", "metric-1"],
                    ),
                    V(
                        "incentive-review",
                        "The manager turns away from blaming individual personalities and calmly reviews the incentive arrangement with the team around a clean table, pointing to a blank commission sheet while colleagues recognize the real cause. Leave generous negative space for the closing message.",
                        ["point-3", "dialogue"],
                    ),
                ],
            ),
        ],
    },
    "sales_management_case09_video": {
        "projectType": "sales-management-case",
        "title": "加了客户考核，续费率为什么更低",
        "coverTitle": "加了客户考核\n续费率为什么更低",
        "subtitle": "想让团队多做价值，先把时间还给他们",
        "visualStyle": "warm-manager-silhouette-motion-graphics",
        "style": MANAGEMENT_STYLE,
        "scenes": [
            S([1, 4], "续费率58%\n再加两次面谈", "错误加法", "An education campus manager studies a low renewal result under an amber spotlight, then adds mandatory parent meetings onto an already crowded team schedule.", ["续费率58%", "公司标准75%", "每月新增两次面谈"], person="lin-wei", speaker="林薇", quote="团队不重视客户维护。", metrics=[metric("续费率", 58, "%", tone="bad"), metric("公司标准", 75, "%", tone="good")], bars=[bar("校区续费", 58, "%", "bad", 100), bar("公司标准", 75, "%", "good", 100)], treatment="crisis"),
            S([5, 6], "没人反对\n但日程已经满了", "执行前提", "A customer adviser silhouette trapped inside an overflowing daily calendar, surrounded by meetings, reporting, training and system-entry tasks, with no empty space left for parent conversations.", ["没有减掉旧工作", "普通周二已排满", "认同却做不到"], person="su-qing", speaker="苏晴", quote="时间从哪里来？", nodes=["晨会日报", "培训录入", "试听接待", "家长沟通"], role="metaphor"),
            S([7, 10], "一天九小时\n客户不到三小时", "时间审计", "A single education sales adviser moves through a long day of morning meetings, CRM entry, internal training, trial-class reception, callbacks and evening reporting, with customer-facing moments shown as a small warm island.", ["8点45到校", "内部事务超过6小时", "客户时间不到3小时"], person="su-qing", speaker="苏晴", quote="真正面对客户的时间太少。", metrics=[metric("客户时间", 3, "小时内", tone="bad"), metric("内部事务", 6, "小时+", tone="bad")], bars=[bar("面对客户", 3, "小时", "bad", 9), bar("内部事务", 6, "小时", "neutral", 9)], role="evidence"),
            S([11, 13], "新增面谈\n最后变成勾表", "形式完成", "An overflowing hourglass beside a parent-meeting checklist, where a meaningful conversation shrinks into a brief phone call and a checked box while the adviser rushes to the next internal task.", ["一次有效面谈45分钟", "每月新增1.5小时", "最后只打5分钟电话"], person="su-qing", speaker="苏晴", quote="只能把面谈做成走流程。", metrics=[metric("有效面谈", 45, "分钟"), metric("走流程电话", 5, "分钟", tone="bad")], bars=[bar("真正面谈", 45, "分钟", "good", 45), bar("走流程", 5, "分钟", "bad", 45)], role="metaphor", treatment="desaturated"),
            S([14, 16], "考核加码\n续费反降到55%", "结果恶化", "A renewal indicator falls further while a manager considers adding more mandatory meetings, then an experienced adviser sits across from her in an exit interview under quiet warm light.", ["续费率降到55%", "计划两次加到三次", "离职面谈揭开真相"], person="lin-wei", speaker="离职顾问", quote="我想做好，可你没给我时间。", metrics=[metric("续费率", 55, "%", from_value=58, tone="bad"), metric("计划面谈", 3, "次", from_value=2, tone="bad")], role="evidence", treatment="crisis"),
            S([17, 19], "每周45小时\n内部事务超40%", "管理者重算", "Late at night, the campus manager maps a complete workweek on a blank sheet, discovering that internal administration consumes a large dark block while parent-facing time remains narrow.", ["每周45小时", "内部事务超过40%", "面对家长不到15小时"], person="lin-wei", speaker="林薇", quote="我从来没有算过这个比例。", metrics=[metric("每周在岗", 45, "小时"), metric("内部事务", 40, "%+", tone="bad"), metric("家长时间", 15, "小时内", tone="bad")], bars=[bar("内部事务", 18, "小时+", "bad", 45), bar("面对家长", 15, "小时内", "good", 45)], role="evidence"),
            S([20, 20], "先删流程\n再谈客户价值", "减负动作", "A manager removes layers of reports and meetings from a team calendar, leaving a simple weekly page, two short stand-ups, one review and a small set of essential CRM fields.", ["日报改一页周报", "晨会每周两次20分钟", "晚会取消，CRM只留4项"], nodes=["周报一页", "短晨会", "周五复盘", "CRM四项"], role="map"),
            S([21, 22], "每周多8小时\n续费回到71%", "时间归还", "Education advisers now have unhurried conversations with parents over coffee, observe classes and respond thoughtfully in family groups, while the campus atmosphere becomes warmer and more human.", ["每周释放近8小时", "不再额外发面谈通知", "两个月续费71%"], person="su-qing", speaker="苏晴", quote="有了时间，价值行为自然发生。", metrics=[metric("释放时间", 8, "小时/周", tone="good"), metric("续费率", 71, "%", from_value=55, tone="good")], bars=[bar("减负前", 55, "%", "bad", 100), bar("减负后", 71, "%", "good", 100)], role="evidence"),
            S([23, 23], "加考核之前\n先减负担", "管理启示", "An open team calendar with generous breathing room becomes a bridge toward deeper customer relationships, while the manager steps back and lets advisers use restored time well.", ["先减掉低价值工作", "时间决定服务质量", "给团队时间去做好"], person="lin-wei", speaker="林薇", quote="想让团队做什么，先给时间。", role="metaphor"),
        ],
    },
    "sales_management_case10_video": {
        "projectType": "sales-management-case",
        "title": "销售不主动，可能是制度在拦路",
        "coverTitle": "销售不主动\n可能是制度在拦路",
        "subtitle": "边界上的客户，最能照出规则漏洞",
        "visualStyle": "warm-manager-silhouette-motion-graphics",
        "style": MANAGEMENT_STYLE,
        "scenes": [
            S([1, 3], "客户就在边界\n两天没人联系", "投诉邮件", "A commercial complex divided by an invisible regional boundary, a restaurant tenant waits between two sales zones and then walks toward a competing mall while a director reads a complaint.", ["看中A区商铺", "铺面归B区", "两天无人联系后流失"], person="fang-yi", speaker="方毅", quote="送上门的生意，为什么接不住？", nodes=["客户需求", "A区销售", "B区销售", "竞争项目"], treatment="crisis"),
            S([4, 8], "主动跟进\n业绩却可能算别人", "销售解释", "A project director questions an experienced salesperson beside a floor-zone map, while a previous cross-zone commission dispute appears as a dark memory behind them.", ["签约后算B区业绩", "协作提成没有规则", "默认各管各区"], person="zhou-yang", speaker="周洋", quote="我花时间，月底报表却看不到。", nodes=["主动跟进", "投入时间", "业绩归别人", "归属冲突"], treatment="crisis"),
            S([9, 12], "同样问题\n两个月发生三次", "边界失速", "Three layered commercial-property situations: an office inquiry passed aside, a shop client stranded between zones, and a national brand forced to meet several separate salespeople for one city plan.", ["C区询价无人接力", "交界客户两边都不动", "三个铺位要对接三次"], nodes=["单区询价", "交界商铺", "跨三区品牌", "共同流失"], role="evidence", treatment="desaturated"),
            S([13, 15], "47条线索\n只成交9条", "数据诊断", "A director traces a year of customer leads along glowing regional border lines, most fading before conversion while ordinary in-zone leads continue toward signed stores.", ["边界线索47条", "只成交9条", "19%对46%，流失超1000万"], person="fang-yi", speaker="方毅", quote="客户流失在我们自己的区域线上。", metrics=[metric("边界线索", 47, "条"), metric("边界成交", 9, "条", tone="bad"), metric("流失金额", 1000, "万+", tone="bad")], bars=[bar("边界转化", 19, "%", "bad", 50), bar("非边界转化", 46, "%", "good", 50)], role="evidence", treatment="crisis"),
            S([16, 19], "跟进会吃亏\n忽略却没代价", "理性选择", "A salesperson stands at a fork: one route requires extra time, conflict and lost credit, while the easy route ignores the boundary customer without personal penalty.", ["跟进：花时间精力", "结果：业绩可能归别人", "不跟进：个人没有惩罚"], nodes=["发现跨区客户", "主动跟进", "归属争议", "选择不动"], role="metaphor", treatment="crisis"),
            S([20, 20], "两周设计\n一页新规则", "机制起点", "A project director works at a warm desk drafting a concise boundary-customer mechanism, with several sales-zone silhouettes converging around one clear shared page.", ["两周设计", "三条核心规则", "一页纸说清楚"], person="fang-yi", speaker="方毅", quote="让主动的人先得到保障。", metrics=[metric("设计周期", 2, "周"), metric("核心条款", 3, "条")], role="evidence"),
            S([21, 21], "边界100米\n业绩双算", "规则一", "Two neighboring-zone salespeople jointly welcome a customer at a shop near the boundary, both clearly participating while the company absorbs the extra incentive cost.", ["交界100米内", "相邻两区共同跟进", "两人业绩全额体现"], metrics=[metric("边界范围", 100, "米"), metric("业绩计入", 2, "人", tone="good")], nodes=["边界客户", "A区销售", "B区销售", "公司承担成本"], role="map"),
            S([22, 22], "一个主对接\n协调奖金5%", "规则二", "One lead salesperson guides a multi-location tenant smoothly across three buildings while supporting regional colleagues handle local details behind a single customer-facing relationship.", ["一个主对接全程服务", "各区正常计提", "主对接额外5%"], metrics=[metric("协调奖金", 5, "%", tone="good")], nodes=["主对接销售", "A区支持", "B区支持", "C区支持"], role="map"),
            S([23, 25], "转介绍8%\n主动对接增到11次", "规则三与行动", "A warm handoff path lights up between sales zones as one salesperson introduces a client to another, quick approval follows, and colleagues jointly close a boundary lease.", ["转介绍提成8%", "五个工作日审批", "主动对接不足2次到11次"], person="zhou-yang", speaker="周洋", quote="这次我们一起把客户接住。", metrics=[metric("转介绍提成", 8, "%", tone="good"), metric("主动对接", 11, "次", from_value=2, tone="good")], bars=[bar("规则前每月", 2, "次内", "bad", 12), bar("规则后每月", 11, "次", "good", 12)], role="evidence"),
            S([26, 26], "转化19%到38%\n一页纸胜过半年动员", "结果与启示", "The former regional boundary transforms into a bright bridge filled with active storefronts, sales teams cooperate across zones and the project director reviews strong growth without giving another motivational speech.", ["边界转化19%到38%", "季度签约增长14%", "超三分之一增量来自边界"], person="fang-yi", speaker="方毅", quote="制度惩罚主动时，别怪人不主动。", metrics=[metric("边界转化", 38, "%", from_value=19, tone="good"), metric("季度增长", 14, "%", tone="good")], bars=[bar("改造前", 19, "%", "bad", 50), bar("改造后", 38, "%", "good", 50)], role="metaphor"),
        ],
    },
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def paragraph_bounds(timeline: dict[str, Any]) -> dict[int, tuple[int, int]]:
    grouped: dict[int, list[int]] = {}
    for unit in timeline["units"]:
        grouped.setdefault(int(unit["paragraph"]), []).append(int(unit["index"]))
    return {paragraph: (indices[0], indices[-1]) for paragraph, indices in grouped.items()}


def scene_bounds(bounds: dict[int, tuple[int, int]], paragraphs: list[int]) -> tuple[int, int]:
    first_paragraph, last_paragraph = paragraphs
    return bounds[first_paragraph][0], bounds[last_paragraph][1]


def portrait_id(person: str) -> str:
    return f"portrait-{person}"


def build_network(scene: dict[str, Any], person: str | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    labels = scene["nodes"][:4]
    if len(labels) < 2:
        return [], []
    nodes = []
    for position, label in enumerate(labels, start=1):
        node: dict[str, Any] = {"id": f"n{position}", "label": label}
        if position == 1 and person:
            node["asset"] = portrait_id(person)
        if position == 1 or position == len(labels):
            node["emphasis"] = True
        nodes.append(node)
    links: list[dict[str, Any]] = []
    for raw_link in scene.get("links", []):
        if not isinstance(raw_link, dict):
            continue
        link = dict(raw_link)
        for key in ("from", "to"):
            value = link.get(key)
            if isinstance(value, int):
                link[key] = f"n{value}"
        links.append(link)
    return nodes, links


def metric_cue(item: dict[str, Any]) -> str:
    value = item.get("value", {})
    return f"{item.get('label', '')}{value.get('from', '')}{value.get('to', '')}{value.get('suffix', '')}"


def bar_cue(item: dict[str, Any]) -> str:
    return f"{item.get('label', '')}{item.get('value', '')}{item.get('suffix', '')}"


def _number_label(value: int | float) -> str:
    number = float(value)
    return str(int(number)) if number.is_integer() else str(number)


def _representation_numbers(value: Any) -> set[str]:
    """Collect story numbers while ignoring technical scale fields such as bar.max."""

    if isinstance(value, bool) or value is None:
        return set()
    if isinstance(value, (int, float)):
        return {_number_label(value)}
    if isinstance(value, str):
        numbers = {
            token.rstrip("%")
            for token in re.findall(r"\d+(?:\.\d+)?%?", value.replace(",", ""))
        }
        if "零" in value:
            numbers.add("0")
        return numbers
    if isinstance(value, dict):
        numbers: set[str] = set()
        for key, item in value.items():
            if key == "max":
                continue
            numbers.update(_representation_numbers(item))
        return numbers
    if isinstance(value, (list, tuple)):
        numbers: set[str] = set()
        for item in value:
            numbers.update(_representation_numbers(item))
        return numbers
    return set()


def _metric_is_covered_by_bars(item: dict[str, Any], bars: list[dict[str, Any]]) -> bool:
    if not bars:
        return False
    metric_numbers = _representation_numbers(item.get("value", {}))
    bar_numbers = {
        number
        for bar_item in bars
        for number in _representation_numbers(bar_item.get("value"))
    }
    if metric_numbers and metric_numbers <= bar_numbers:
        return True
    return text_alignment_score((metric_cue(item),), " ".join(bar_cue(bar_item) for bar_item in bars)) >= 0.24


def _has_rich_semantic_layer(candidate: BeatCandidate) -> bool:
    return any(
        layer.get("kind") in {"bar-compare", "counter", "dialogue", "network"}
        for layer in candidate.layers
    )


def _prune_redundant_points(
    candidates: list[BeatCandidate],
    *,
    minimum_count: int,
) -> list[BeatCandidate]:
    """Let richer evidence replace duplicate text cards without creating pacing gaps."""

    minimum_count = max(1, min(minimum_count, len(candidates)))
    rich_candidates = [candidate for candidate in candidates if _has_rich_semantic_layer(candidate)]
    if not rich_candidates or len(candidates) <= minimum_count:
        return candidates

    redundant: list[tuple[float, str]] = []
    for candidate in candidates:
        if not candidate.key.startswith("point-"):
            continue
        point_text = " ".join(candidate.cue_texts)
        point_numbers = _representation_numbers(point_text)
        best_score = 0.0
        numeric_coverage = False
        for rich_candidate in rich_candidates:
            rich_text = " ".join(rich_candidate.cue_texts)
            best_score = max(best_score, text_alignment_score(candidate.cue_texts, rich_text))
            rich_numbers = _representation_numbers(rich_text)
            numeric_coverage = numeric_coverage or bool(
                point_numbers and point_numbers <= rich_numbers
            )
        zero_equivalence = "零" in point_text and "0" in {
            number
            for rich_candidate in rich_candidates
            for number in _representation_numbers(" ".join(rich_candidate.cue_texts))
        }
        if numeric_coverage or best_score >= 0.22 or (zero_equivalence and best_score >= 0.08):
            redundant.append((best_score + (1.0 if numeric_coverage else 0.0), candidate.key))

    remove_budget = max(0, len(candidates) - minimum_count)
    remove_keys = {
        key
        for _, key in sorted(redundant, reverse=True)[:remove_budget]
    }
    return [candidate for candidate in candidates if candidate.key not in remove_keys]


def build_beat_candidates(
    scene: dict[str, Any],
    *,
    is_first: bool,
    is_last: bool,
    minimum_count: int = 1,
) -> list[BeatCandidate]:
    headline = scene["headline"].replace("\n", "")
    cards = tuple(scene["cards"])
    candidates: list[BeatCandidate] = [
        BeatCandidate(
            key="claim",
            intent="context" if is_first else ("reflection" if is_last else "claim"),
            cue_texts=(headline,),
            layers=(
                {
                    "kind": "text",
                    "slot": "top-left",
                    "variant": "headline",
                    "label": scene["kicker"],
                    "text": scene["headline"],
                },
            ),
            priority=76,
            preferred_fraction=0.0,
            anchor_policy="start",
        )
    ]

    card_fractions = (0.28, 0.55, 0.82)
    for card_position, card in enumerate(cards[:3]):
        if is_last:
            card_intent = "reflection" if card_position == len(cards[:3]) - 1 else "consequence"
        elif scene["role"] in {"map", "metaphor"}:
            card_intent = "mechanism"
        elif scene["role"] == "evidence":
            card_intent = "evidence"
        elif scene["treatment"] == "crisis" and card_position == len(cards[:3]) - 1:
            card_intent = "decision"
        else:
            card_intent = "claim"
        candidates.append(
            BeatCandidate(
                key=f"point-{card_position + 1}",
                intent=card_intent,
                cue_texts=(card,),
                layers=(
                    {
                        "kind": "text",
                        "slot": "center",
                        "variant": "headline",
                        "label": scene["kicker"],
                        "text": card,
                    },
                ),
                priority=74,
                preferred_fraction=card_fractions[card_position],
                composition="full-bleed" if card_intent in {"claim", "reflection"} else "split",
            )
        )

    person = scene["person"]
    if person and scene["quote"]:
        intent = "reflection" if is_last else ("decision" if scene["treatment"] == "crisis" else "protagonist")
        candidates.append(
            BeatCandidate(
                key="dialogue",
                intent=intent,
                cue_texts=(scene["quote"],),
                layers=(
                    {"kind": "asset", "slot": "left", "asset": portrait_id(person)},
                    {
                        "kind": "dialogue",
                        "slot": "right",
                        "speaker": scene["speaker"] or "人物",
                        "text": scene["quote"],
                        "tail": "left",
                    },
                ),
                priority=94,
                preferred_fraction=0.18 if not is_last else 0.88,
                composition="portrait-left",
            )
        )
    elif person:
        candidates.append(
            BeatCandidate(
                key="protagonist",
                intent="protagonist",
                cue_texts=(scene["speaker"] or "", headline),
                layers=(
                    {"kind": "asset", "slot": "left", "asset": portrait_id(person)},
                    {"kind": "text", "slot": "right", "variant": "headline", "text": scene["headline"]},
                ),
                priority=84,
                preferred_fraction=0.18,
                composition="portrait-left",
            )
        )

    if scene["bars"]:
        candidates.append(
            BeatCandidate(
                key="comparison",
                intent="consequence" if is_last else "evidence",
                cue_texts=tuple(bar_cue(item) for item in scene["bars"]),
                layers=(
                    {
                        "kind": "text",
                        "slot": "top-left",
                        "variant": "caption",
                        "text": scene["headline"],
                    },
                    {
                        "kind": "bar-compare",
                        "slot": "right",
                        "label": scene["kicker"],
                        "bars": scene["bars"][:4],
                    },
                ),
                priority=98,
                preferred_fraction=0.48,
                composition="evidence-collage",
            )
        )

    unique_metrics = [
        item
        for item in scene["metrics"]
        if not _metric_is_covered_by_bars(item, scene["bars"])
    ][:2]
    metric_fractions = (0.40, 0.66)
    for metric_position, item in enumerate(unique_metrics):
        candidates.append(
            BeatCandidate(
                key=f"metric-{metric_position + 1}",
                intent="consequence" if is_last else "evidence",
                cue_texts=(metric_cue(item), item["label"]),
                layers=(
                    {
                        "kind": "text",
                        "slot": "top-left",
                        "variant": "caption",
                        "text": scene["headline"],
                    },
                    {
                        "kind": "counter",
                        "slot": "right" if metric_position % 2 == 0 else "left",
                        "label": item["label"],
                        "value": item["value"],
                        "deltaTone": item["tone"],
                    },
                ),
                priority=92,
                preferred_fraction=metric_fractions[metric_position],
                composition="split",
            )
        )

    nodes, links = build_network(scene, person)
    if nodes and links:
        relationship_intent = "mechanism" if scene["role"] in {"metaphor", "map"} else "relationship"
        candidates.append(
            BeatCandidate(
                key="relationship",
                intent=relationship_intent,
                cue_texts=(
                    *(node["label"] for node in nodes),
                    *(str(link.get("label", "")) for link in links if link.get("label")),
                ),
                layers=(
                    {
                        "kind": "text",
                        "slot": "top-left",
                        "variant": "caption",
                        "text": scene["headline"],
                    },
                    {
                        "kind": "network",
                        "slot": "center",
                        "label": "机制关系",
                        "nodes": nodes,
                        "links": links,
                        "networkLayout": scene.get("networkLayout") or "auto",
                    },
                ),
                priority=90,
                preferred_fraction=0.62,
                composition="document-focus",
            )
        )
    return _prune_redundant_points(candidates, minimum_count=minimum_count)


def build_visual_beats(
    scene: dict[str, Any],
    scene_position: int,
    first: int,
    last: int,
    unit_by_index: dict[int, dict[str, Any]],
    *,
    scene_count: int,
    default_asset: str,
    candidate_asset_map: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    start_value = unit_by_index[first].get("start")
    end_value = unit_by_index[last].get("end")
    if isinstance(start_value, (int, float)) and isinstance(end_value, (int, float)):
        duration = max(0.0, float(end_value) - float(start_value))
    else:
        duration = float(last - first + 1) * 4.0
    # Use a little headroom below the 12s hard limit because narration units
    # are discrete and cannot always land on an exact temporal quantile.
    minimum_count = max(1, math.ceil(duration / 11.25))
    candidates = build_beat_candidates(
        scene,
        is_first=scene_position == 1,
        is_last=scene_position == scene_count,
        minimum_count=minimum_count,
    )
    beats = schedule_visual_beats(
        candidates,
        scene_id=f"s{scene_position:02d}",
        first=first,
        last=last,
        unit_by_index=unit_by_index,
        base_asset=default_asset,
        treatment=scene["treatment"],
    )
    for beat in beats:
        candidate_key = beat.get("candidateKey")
        if candidate_asset_map and isinstance(candidate_key, str):
            beat["baseAsset"] = candidate_asset_map.get(candidate_key, default_asset)
    return beats


def portrait_assets(project: Path) -> list[dict[str, Any]]:
    manifest_path = project / "asset_pool_usage.json"
    if not manifest_path.is_file():
        return []
    manifest = load_json(manifest_path)
    assets = []
    for record in manifest.get("assets", []):
        if record.get("poolType") != "character-portrait":
            continue
        src = record["src"].replace("\\", "/")
        assets.append(
            {
                "id": f"portrait-{Path(src).stem.replace('_', '-')}",
                "type": "image",
                "src": src,
                "role": "person",
                "origin": "curated",
                "poolAssetId": record["assetId"],
            }
        )
    return assets


def build_project(slug: str, config: dict[str, Any]) -> None:
    project = ROOT / "output" / slug
    timeline = load_json(project / "narration.timeline.json")
    bounds = paragraph_bounds(timeline)
    unit_by_index = {int(unit["index"]): unit for unit in timeline["units"]}

    background_prompts: list[dict[str, str]] = []
    image_prompts: list[dict[str, str]] = []
    visual_assets: list[dict[str, Any]] = []
    scenes: list[dict[str, Any]] = []

    for position, source in enumerate(config["scenes"], start=1):
        is_first = position == 1
        is_last = position == len(config["scenes"])
        first, last = scene_bounds(bounds, source["paragraphs"])
        visual_variants = source.get("visualVariants", [])
        has_variants = bool(visual_variants)
        image_file = (
            f"images/generated/s{position:02d}_context.png"
            if has_variants
            else f"images/generated/s{position:02d}.png"
        )
        default_asset = (
            f"bg-s{position:02d}-context" if has_variants else f"bg-s{position:02d}"
        )
        prompt = source["prompt"]
        full_prompt = f"{config['style']} Scene: {prompt}"
        background_prompts.append({"file": image_file, "prompt": prompt})
        image_prompts.append({"file": image_file, "fullPrompt": full_prompt})
        visual_assets.append(
            {
                "id": default_asset,
                "type": "image",
                "src": image_file,
                "role": source["role"],
                "origin": "generated",
            }
        )
        candidate_asset_map: dict[str, str] = {}
        for variant in visual_variants:
            variant_name = str(variant["name"])
            variant_file = f"images/generated/s{position:02d}_{variant_name.replace('-', '_')}.png"
            variant_asset = f"bg-s{position:02d}-{variant_name}"
            variant_prompt = str(variant["prompt"])
            background_prompts.append({"file": variant_file, "prompt": variant_prompt})
            image_prompts.append(
                {"file": variant_file, "fullPrompt": f"{config['style']} Scene: {variant_prompt}"}
            )
            visual_assets.append(
                {
                    "id": variant_asset,
                    "type": "image",
                    "src": variant_file,
                    "role": source["role"],
                    "origin": "generated",
                }
            )
            for candidate_key in variant["candidateKeys"]:
                if candidate_key in candidate_asset_map:
                    raise ValueError(
                        f"{slug} scene {position} maps candidate {candidate_key!r} more than once"
                    )
                candidate_asset_map[candidate_key] = variant_asset
        scenes.append(
            {
                "id": f"s{position:02d}",
                "chapter": f"{position:02d}",
                "kicker": source["kicker"],
                "layout": select_scene_layout(
                    source,
                    is_first=is_first,
                    is_last=is_last,
                ),
                "background": image_file,
                "transition": select_scene_transition(source),
                "motion": select_scene_motion(source, is_last=is_last),
                "tone": "dark",
                "headline": source["headline"],
                "accent": source["cards"][:2],
                "keywords": [
                    {"text": source["cards"][0], "offset": 0},
                    {"text": source["cards"][1], "offset": 1},
                ],
                "props": {},
                "visualMode": "editorial",
                "visualBeats": build_visual_beats(
                    source,
                    position,
                    first,
                    last,
                    unit_by_index,
                    scene_count=len(config["scenes"]),
                    default_asset=default_asset,
                    candidate_asset_map=candidate_asset_map,
                ),
                "paragraphs": source["paragraphs"],
            }
        )

    visual_assets.extend(portrait_assets(project))
    portrait_prompts: list[dict[str, str]] = []
    for item in config.get("generatedPortraits", []):
        portrait_prompts.append({"file": item["file"], "fullPrompt": item["prompt"]})
        image_prompts.append({"file": item["file"], "fullPrompt": item["prompt"]})
        visual_assets.append(
            {
                "id": item["id"],
                "type": "image",
                "src": item["file"],
                "role": "person",
                "origin": "generated",
            }
        )

    first_scene_first, _ = scene_bounds(bounds, config["scenes"][0]["paragraphs"])
    plan = {
        "project": {
            "slug": slug,
            "projectType": config["projectType"],
            "title": config["title"],
            "subtitle": config["subtitle"],
            "brand": "销售不复杂",
            "subtitleLabel": "销售不复杂",
            "visualStyle": config["visualStyle"],
            "cover": {
                "title": config["coverTitle"],
                "subtitle": config["subtitle"],
                "kicker": "销售不复杂",
                "throughUnit": first_scene_first,
            },
        },
        "visualAssets": visual_assets,
        "displayReplacements": {},
        "scenes": scenes,
    }
    write_json(project / "storyboard_plan.json", plan)
    write_json(
        project / "background_prompts.json",
        {"stylePrefix": config["style"], "outputDir": "images/generated", "prompts": background_prompts},
    )
    write_json(
        project / "image_prompts.json",
        {"stylePrefix": "", "outputDir": "images/generated", "prompts": image_prompts},
    )
    if portrait_prompts:
        write_json(
            project / "portrait_prompts.json",
            {"stylePrefix": "", "outputDir": "images/characters", "prompts": portrait_prompts},
        )
    print(
        f"wrote {slug}: scenes={len(scenes)} beats={sum(len(scene['visualBeats']) for scene in scenes)} "
        f"backgrounds={len(background_prompts)} portraits={len(portrait_prompts)}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Create rich unit-anchored plans for priority sales and new management cases.")
    parser.add_argument("projects", nargs="*", help="Optional project slugs; defaults to all seven projects")
    args = parser.parse_args()
    selected = args.projects or list(PROJECTS)
    unknown = [slug for slug in selected if slug not in PROJECTS]
    if unknown:
        raise SystemExit(f"unknown projects: {', '.join(unknown)}")
    for slug in selected:
        build_project(slug, PROJECTS[slug])


if __name__ == "__main__":
    main()
