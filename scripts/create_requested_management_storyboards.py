#!/usr/bin/env python3
from __future__ import annotations

import argparse
from copy import deepcopy
from pathlib import Path
from typing import Any

from create_priority_and_management_storyboards import MANAGEMENT_STYLE, S, V, bar, build_project, metric


ROOT = Path(__file__).resolve().parents[1]

PORTRAIT_STYLE = (
    "Single Chinese businessperson character cutout for a sales-management case video, "
    "centered waist-up figure on pure clean white background, generous margin on all sides, "
    "near-black faceless silhouette with clear professional posture, deep navy and cobalt clothing layers, "
    "burnt-orange rim light, warm cream paper grain, flat cut-paper and screen-print feel. "
    "No detailed face, no props, no readable text, no letters, no numbers, no logos, no watermark, no border. "
)

VARIANT_TARGETS = ["point-2", "dialogue", "comparison", "relationship", "metric-1"]


def P(person: str, file_name: str, description: str) -> dict[str, str]:
    return {
        "id": f"portrait-{person}",
        "file": f"images/characters/{file_name}",
        "prompt": PORTRAIT_STYLE + description,
    }


def C(
    subtitle: str,
    portraits: list[dict[str, str]],
    scenes: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "projectType": "sales-management-case",
        "title": "",
        "coverTitle": "",
        "subtitle": subtitle,
        "visualStyle": "warm-manager-silhouette-motion-graphics",
        "style": MANAGEMENT_STYLE,
        "generatedPortraits": portraits,
        "scenes": scenes,
    }


def _cycle_links() -> list[dict[str, Any]]:
    return [
        {"from": 1, "to": 2, "label": "引出"},
        {"from": 2, "to": 3, "label": "推高"},
        {"from": 3, "to": 4, "label": "形成"},
        {"from": 4, "to": 1, "label": "反推"},
    ]


def _hub_links() -> list[dict[str, Any]]:
    return [
        {"from": 1, "to": 2, "label": "牵动"},
        {"from": 1, "to": 3, "label": "牵动"},
        {"from": 1, "to": 4, "label": "牵动"},
    ]


def add_network_variety(scenes: list[dict[str, Any]]) -> None:
    relationship_cycle = False
    relationship_hub = False
    mechanism_cycle = False
    for scene in scenes:
        if len(scene.get("nodes", [])) < 4 or not scene.get("links"):
            continue
        role = str(scene.get("role", "context"))
        if role in {"map", "metaphor"}:
            if not mechanism_cycle:
                scene["links"] = _cycle_links()
                mechanism_cycle = True
            continue
        if not relationship_cycle:
            scene["links"] = _cycle_links()
            relationship_cycle = True
        elif not relationship_hub:
            scene["links"] = _hub_links()
            relationship_hub = True


PROJECTS: dict[str, dict[str, Any]] = {
    "sales_management_case01_title_validation": C(
        "老销售的沉默，可能来自被封住的动力",
        [
            P("zheng-weimin", "zheng-weimin.png", "A late-forties veteran male salesperson, calm and reserved, shoulders slightly lowered, looking screen-right."),
            P("qin-yong", "qin-yong.png", "A mid-thirties male sales manager, alert and thoughtful, holding a blank folder close to the body."),
        ],
        [
            S(
                [1, 2],
                "老销售沉默\n团队跟着发冷",
                "阳奉阴违",
                "A warm sales office review room where a young manager watches a veteran salesperson sit silently at the edge of the table, the rest of the team observing the tension in shadow, large clean negative space above them.",
                ["老销售阳奉阴违", "经理越抓越累", "团队气氛变冷"],
                person="qin-yong",
                speaker="秦勇",
                quote="他到底怎么了？",
                treatment="crisis",
            ),
            S(
                [3, 4],
                "数字一路下滑\n经验没有消失",
                "异常业绩",
                "A veteran salesperson's desk at dusk with organized customer folders, a quiet phone, and a manager reviewing shrinking sales activity from a respectful distance, the mood restrained and analytical.",
                ["成交从110到73", "报价越来越慢", "客户迟迟不回"],
                person="zheng-weimin",
                speaker="郑伟民",
                quote="按流程来吧。",
                metrics=[metric("月成交", 73, "万", from_value=110, tone="bad")],
                bars=[
                    bar("高点", 110, "万", "good", 120),
                    bar("中段", 85, "万", "neutral", 120),
                    bar("当前", 73, "万", "bad", 120),
                ],
                role="evidence",
                treatment="crisis",
            ),
            S(
                [5, 9],
                "培训加码\n结果没有变化",
                "错误诊断",
                "A manager repeatedly coaches an experienced salesperson in role-play, joint customer visits and script practice, yet the veteran's body language stays polite and distant, with blank training papers scattered across the table.",
                ["重做话术", "陪访七次", "动作仍然迟缓"],
                person="qin-yong",
                speaker="秦勇",
                quote="我以为是方法问题。",
                metrics=[metric("陪访", 7, "次")],
                nodes=["培训", "陪访", "复盘", "结果无变化"],
                links=[{"from": 1, "to": 2, "label": "追加"}, {"from": 2, "to": 3, "label": "继续"}, {"from": 3, "to": 4, "label": "无效"}],
                treatment="desaturated",
            ),
            S(
                [10, 12],
                "一对一之后\n真正数字出现",
                "重新观察",
                "A private one-on-one conversation in a quiet meeting corner, with the manager listening rather than lecturing while scattered performance records become clearer in warm side light.",
                ["只看两个月数据", "成交率71%", "拜访量很低"],
                person="qin-yong",
                speaker="秦勇",
                quote="这次我只问原因。",
                metrics=[metric("成交率", 71, "%", tone="good")],
                bars=[bar("成交率", 71, "%", "good", 100), bar("拜访量", 39, "%", "bad", 100)],
                role="evidence",
            ),
            S(
                [13, 15],
                "一句饭桌问题\n打开真正原因",
                "真实动机",
                "A modest dinner table after work where the veteran salesperson finally speaks candidly, the manager leaning forward quietly, warm restaurant light isolating the two figures from a blurred city background.",
                ["能做更大单", "却不愿多做", "原因不在能力"],
                person="zheng-weimin",
                speaker="郑伟民",
                quote="多做也没多拿。",
                nodes=["能力", "大单机会", "回报封顶", "选择少做"],
                links=[{"from": 1, "to": 2, "label": "具备"}, {"from": 2, "to": 3, "label": "撞上"}, {"from": 3, "to": 4, "label": "诱发"}],
                role="evidence",
            ),
            S(
                [16, 20],
                "封顶线卡住动力\n多做五百万只多两千",
                "激励证据",
                "A veteran salesperson standing before a sealed bonus gate, with extra customer opportunities visible beyond it but no meaningful reward light reaching back to him, strong silhouette and amber rim light.",
                ["800万已经封顶", "1300万没有意义", "多500万只多不到2000元"],
                person="zheng-weimin",
                speaker="郑伟民",
                quote="这不就成了变相加薪吗？",
                metrics=[metric("额外回报", 2000, "元内", tone="bad")],
                bars=[
                    bar("封顶线", 800, "万", "neutral", 1300),
                    bar("可做业绩", 1300, "万", "good", 1300),
                    bar("额外业绩", 500, "万", "bad", 1300),
                ],
                role="evidence",
                treatment="crisis",
            ),
            S(
                [21, 22],
                "能力还在\n发动机被关掉",
                "管理诊断",
                "A symbolic sales engine inside a dark office, intact gears and customer files still present, but the fuel line is closed by a commission cap lever while the manager realizes the diagnosis was misplaced.",
                ["方法一直都在", "动力被封住", "管理诊断错位"],
                person="qin-yong",
                speaker="秦勇",
                quote="我看错了问题。",
                nodes=["销售能力", "激励封顶", "努力收益", "行为下降"],
                links=[{"from": 1, "to": 3, "label": "需要"}, {"from": 2, "to": 3, "label": "压住"}, {"from": 3, "to": 4, "label": "影响"}],
                role="metaphor",
            ),
            S(
                [23, 25],
                "激励池打开\n努力重新有回报",
                "机制改造",
                "A sales manager presents a revised incentive pool in a calm conference room, the veteran and team members watching as a previously closed pathway opens toward new customer opportunities.",
                ["600万潜力缺口", "阶梯比例重算", "团队看到新回报"],
                person="qin-yong",
                speaker="秦勇",
                quote="先让多做有意义。",
                metrics=[metric("潜力缺口", 600, "万", tone="good")],
                nodes=["潜力缺口", "激励池", "阶梯比例", "重新行动"],
                links=[{"from": 1, "to": 2, "label": "建立"}, {"from": 2, "to": 3, "label": "分配"}, {"from": 3, "to": 4, "label": "推动"}],
                role="map",
            ),
            S(
                [26, 27],
                "三个月后\n老销售重新领跑",
                "结果回升",
                "A brighter sales bullpen where the veteran salesperson is again active with customer calls and visits, while the manager observes from the side with a calmer expression and the team energy returns.",
                ["拜访开始恢复", "成交回到112万", "冲进全国前十"],
                person="zheng-weimin",
                speaker="郑伟民",
                quote="有奔头就愿意跑。",
                metrics=[metric("成交", 112, "万", from_value=73, tone="good")],
                bars=[
                    bar("调整前", 73, "万", "bad", 130),
                    bar("三个月后", 112, "万", "good", 130),
                    bar("高点", 121, "万", "good", 130),
                ],
                role="evidence",
            ),
            S(
                [28, 29],
                "方法一直在\n人需要被看见",
                "管理反思",
                "A reflective office scene where the manager reviews the same veteran's performance from a new angle, with the salesperson's effort, fairness and reward structure visible as subtle layered shadows.",
                ["别只看动作", "要看收益结构", "人会计算公平"],
                person="zheng-weimin",
                speaker="郑伟民",
                quote="方法一直都在。",
                role="metaphor",
            ),
            S(
                [30, 31],
                "看见动机\n才管得动行为",
                "销售不复杂",
                "A closing editorial scene where a sales manager opens a blocked incentive path for the team, silhouettes walking toward warmer customer light with clean negative space for the final lesson.",
                ["阳奉阴违是信号", "封住回报就封住行动", "先改机制再谈执行"],
                role="metaphor",
            ),
        ],
    ),
    "sales_management_case04_video": C(
        "沉默退场之前，公平已经被破坏",
        [
            P("zhao-jianguo", "zhao-jianguo.png", "A late-forties veteran male insurance salesperson, steady posture, restrained disappointment, screen-right gaze."),
            P("wu-min", "wu-min.png", "A forty-year-old female sales manager, composed and analytical, hands resting on a blank folder."),
        ],
        [
            S([1, 2], "八个月客户\n一夜变成协同", "协同失衡", "An insurance sales office where a veteran's long-nurtured client file is moved across the table toward a newcomer, while the veteran sits quietly in a hard side light.", ["老兵突然沉默", "客户被转给新人", "公平问题开始发酵"], person="zhao-jianguo", speaker="赵建国", quote="我先配合。", treatment="crisis"),
            S([3, 4], "十一年老销售\n维护四百个家庭", "老兵画像", "A respected insurance veteran visiting families over many years, warm home silhouettes and careful service gestures surrounding him while a manager observes his stable reputation.", ["11年保险老兵", "400个家庭", "续费率92%"], person="zhao-jianguo", speaker="赵建国", quote="客户信任是慢慢攒的。", metrics=[metric("从业", 11, "年"), metric("家庭客户", 400, "个"), metric("续费率", 92, "%", tone="good")], role="evidence"),
            S([5, 8], "新人要亮相\n公司临时改打法", "决策现场", "A manager arranging a high-value corporate insurance opportunity in a meeting room, placing a newcomer in the signing seat while the veteran is asked to support from the side.", ["80万企业年金", "新人主签", "老兵协同"], person="wu-min", speaker="吴敏", quote="这次你帮她带一带。", metrics=[metric("保费", 80, "万", tone="good")], nodes=["吴敏", "新人", "赵建国", "企业客户"], links=[{"from": 1, "to": 2, "label": "安排主签"}, {"from": 3, "to": 2, "label": "协同"}, {"from": 2, "to": 4, "label": "签约"}], role="map"),
            S([9, 14], "八个月铺垫\n没有写进分配", "利益归属", "A long relationship-building trail of client visits fades behind a final signing table where credit and commission are assigned elsewhere, the veteran's contribution remaining in shadow.", ["客户跟进八个月", "关系维护在前", "佣金记到新人名下"], person="zhao-jianguo", speaker="赵建国", quote="原来我的投入不用算。", metrics=[metric("铺垫周期", 8, "个月"), metric("协同佣金", 0, "元", tone="bad")], bars=[bar("前期投入", 8, "个月", "good", 8), bar("实际佣金", 0, "元", "bad", 8)], role="evidence", treatment="crisis"),
            S([15, 18], "沉默变成\n理性撤退", "无声抗议", "A veteran salesperson still appearing professional but gradually shrinking his customer visits and targets, walking through quieter office corridors while colleagues notice the cold distance.", ["日访从4到2", "月目标80到60", "合格成了抗议"], person="zhao-jianguo", speaker="赵建国", quote="合格就够了。", metrics=[metric("日均拜访", 2, "次", from_value=4, tone="bad")], bars=[bar("原日访", 4, "次", "good", 4), bar("现日访", 2, "次", "bad", 4), bar("原目标", 80, "万", "good", 80), bar("现目标", 60, "万", "bad", 80)], role="evidence", treatment="desaturated"),
            S([19, 20], "半年后辞职\n真相才被说出", "离职面谈", "A quiet exit interview between the veteran and manager, one signed resignation folder on a blank table, warm light revealing disappointment rather than anger.", ["动力已经断掉", "我干得动", "只是寒了心"], person="zhao-jianguo", speaker="赵建国", quote="我干得动，只是寒了心。", treatment="crisis"),
            S([21, 24], "管理错在\n把公平当小事", "复盘诊断", "A manager alone at night reconstructs the decision that damaged fairness, with contribution, credit and commission shown as separated shadows around one client relationship.", ["源头是分配决定", "协同缺少边界", "贡献没有被确认"], person="wu-min", speaker="吴敏", quote="问题源头是那次分配决定。", nodes=["客户关系", "协同安排", "佣金分配", "信任破裂"], links=[{"from": 1, "to": 2, "label": "被调用"}, {"from": 2, "to": 3, "label": "失衡"}, {"from": 3, "to": 4, "label": "导致"}], role="metaphor"),
            S([25, 27], "协作先算清贡献\n再要求主动帮忙", "销售不复杂", "A closing scene of a team redesigning collaboration rules around a clean table, each contributor visible in the warm light before a client relationship is handed forward.", ["客户关系有成本", "贡献要被看见", "规则决定合作意愿"], role="metaphor"),
        ],
    ),
    "sales_management_case05_video": C(
        "努力方式变了，管理标准也要跟着变",
        [
            P("xu-yang", "xu-yang.png", "A young male digital advertising salesperson, early twenties, relaxed but serious posture, screen-left gaze."),
            P("lin-nuo", "lin-nuo.png", "A female sales manager in her thirties, brisk professional posture, thoughtful expression implied through silhouette."),
        ],
        [
            S([1, 2], "到点就走\n业绩反而变差", "代际冲突", "A digital advertising sales office at closing time, young salespeople leaving on time while the manager watches a worsening sales mood under sharp evening light.", ["00后不愿加班", "经理持续加压", "转化继续下滑"], person="lin-nuo", speaker="林诺", quote="怎么越管越差？", treatment="crisis"),
            S([3, 4], "老办法很熟\n新团队不买账", "经验失灵", "A manager points to a traditional phone-sales routine while a young team sits politely detached, phones and blank laptops arranged in repeating rows with cold negative space.", ["每天80通电话", "晚间继续跟进", "五个年轻销售沉默"], person="lin-nuo", speaker="林诺", quote="按老办法先跑起来。", metrics=[metric("电话量", 80, "通/天"), metric("00后销售", 5, "人")], role="evidence"),
            S([5, 8], "压得越紧\n客户越反感", "错误加压", "A tense sales floor where call pressure increases but customer responses shrink, with one complaint conversation casting a dark shadow over the manager's desk.", ["拜访12到18", "转化8%到3%", "两起客户投诉"], person="lin-nuo", speaker="林诺", quote="量上去了，单子没回来。", metrics=[metric("客户投诉", 2, "起", tone="bad")], bars=[bar("拜访前", 12, "次", "neutral", 20), bar("拜访后", 18, "次", "good", 20), bar("原转化", 8, "%", "good", 10), bar("新转化", 3, "%", "bad", 10)], role="evidence", treatment="crisis"),
            S([9, 11], "短视频带来\n第一批新线索", "新路径", "A young salesperson editing a practical client-facing content clip in a clean office corner, while real prospects begin to appear as warm silhouettes beyond the screenless workspace.", ["3000播放", "6个咨询", "2000粉丝"], person="xu-yang", speaker="许洋", quote="我愿意努力，只是不想用这种方式。", metrics=[metric("咨询", 6, "个", tone="good"), metric("粉丝", 2000, "人", tone="good")], role="evidence"),
            S([12, 14], "关键问题\n是获客路径变了", "管理假设", "A manager studies two customer-acquisition paths in the same office: one path of cold calls fading, another path of content-led conversations warming up, no screens or labels.", ["表象是00后", "根因是方式错配", "客户注意力已经迁移"], person="lin-nuo", speaker="林诺", quote="关键是管理者的假设，00后只是表象。", nodes=["老电话模型", "年轻销售", "客户注意力", "内容线索"], links=[{"from": 1, "to": 2, "label": "压迫"}, {"from": 3, "to": 4, "label": "迁移"}, {"from": 4, "to": 2, "label": "激活"}], role="metaphor"),
            S([15, 16], "拿出40%时间\n验证内容获客", "试点规则", "A manager and young salesperson agree on a structured experiment, dividing work time between essential calls and content creation while keeping customer outcomes in the foreground.", ["下午做内容", "电话保留底线", "线索质量单独看"], person="lin-nuo", speaker="林诺", quote="先用结果验证。", metrics=[metric("内容时间", 40, "%", tone="good")], nodes=["电话底线", "内容时间", "线索质量", "试点复盘"], links=[{"from": 1, "to": 2, "label": "保留"}, {"from": 2, "to": 3, "label": "产出"}, {"from": 3, "to": 4, "label": "评估"}], role="map"),
            S([17, 19], "线索翻倍\n成交也回来了", "结果对照", "A lively digital-sales workspace where content-led inquiries and phone leads are compared through human activity, with young salespeople holding more focused customer conversations.", ["27条线索", "9个意向客户", "内容转化22%"], person="xu-yang", speaker="许洋", quote="客户先看懂，再愿意聊。", metrics=[metric("线索", 27, "条", tone="good"), metric("意向客户", 9, "个", tone="good")], bars=[bar("内容线索", 60, "条", "good", 60), bar("电话线索", 35, "条", "neutral", 60), bar("内容转化", 22, "%", "good", 25), bar("电话转化", 6, "%", "bad", 25)], role="evidence"),
            S([20, 21], "管理年轻人\n先管理假设", "销售不复杂", "A closing scene where a manager watches customer attention shift across channels and adjusts the work system, with the team moving into a more effective rhythm.", ["不要只盯工时", "看客户在哪里", "让努力进入有效通道"], role="metaphor"),
        ],
    ),
    "sales_management_case08_video": C(
        "客户等不起的，常常是公司的内部流程",
        [
            P("gao-feng", "gao-feng.png", "A male logistics sales manager in his forties, tense but controlled posture, holding a blank customer folder."),
            P("feng-tao", "feng-tao.png", "A male operations leader in his late thirties, practical posture, turned slightly toward a discussion table."),
        ],
        [
            S([1, 2], "丢了五个客户\n销售成了背锅人", "客户流失", "A logistics sales review room where five empty customer chairs create pressure around the sales team, while a manager looks for the real cause in the shadows behind them.", ["五个客户流失", "经理怀疑跟进差", "真正原因藏在内部"], person="gao-feng", speaker="高峰", quote="真的是跟进问题吗？", metrics=[metric("流失客户", 5, "个", tone="bad")], treatment="crisis"),
            S([3, 5], "成交周期翻倍\n团队开始互相指责", "异常数据", "A logistics office with salespeople, operations and finance silhouettes pointing toward each other while delayed customer proposals stack up in the center.", ["45天到90天", "报价迟迟出不来", "客户转向竞品"], person="gao-feng", speaker="高峰", quote="客户等不到我们。", bars=[bar("原周期", 45, "天", "good", 100), bar("现周期", 90, "天", "bad", 100), bar("峰值", 92, "天", "bad", 100)], role="evidence", treatment="crisis"),
            S([6, 7], "一次丢单复盘\n揭开审批链条", "典型客户", "A lost logistics customer case is reconstructed across a conference table, with a competitor's fast response suggested by a warm path outside while internal folders crawl slowly inside.", ["客户要快速方案", "竞品3天回复", "内部走了23天"], person="feng-tao", speaker="冯涛", quote="这单不是慢在客户那里。", metrics=[metric("竞品响应", 3, "天", tone="good"), metric("内部耗时", 23, "天", tone="bad")], role="evidence"),
            S([8, 13], "四个部门串行\n十八天耗在内部", "流程证据", "A logistics approval route passing through four departmental desks one after another, each desk holding the same blank proposal while the customer waits outside in fading light.", ["销售5天", "内部18天", "四部门逐个审批"], person="gao-feng", speaker="高峰", quote="客户等的是我们内部。", metrics=[metric("内部耗时", 18, "天", tone="bad")], bars=[bar("销售跟进", 5, "天", "good", 23), bar("内部审批", 18, "天", "bad", 23)], nodes=["销售", "运营", "财务", "法务"], links=[{"from": 1, "to": 2, "label": "提交"}, {"from": 2, "to": 3, "label": "等待"}, {"from": 3, "to": 4, "label": "再等"}], role="map", treatment="crisis"),
            S([14, 17], "客户等方案\n公司在等签字", "内部摩擦", "A customer silhouette waits beside a loading dock while inside the company several departments hold a proposal in separate pools of light, none moving at the same time.", ["价格卡两周", "技术等商务", "法务排队审核"], person="feng-tao", speaker="冯涛", quote="我们把快单走成了慢单。", nodes=["价格", "技术", "商务", "法务"], links=[{"from": 1, "to": 2, "label": "等待"}, {"from": 2, "to": 3, "label": "等待"}, {"from": 3, "to": 4, "label": "等待"}], role="metaphor"),
            S([18, 20], "50万以下快车道\n48小时给答案", "机制改造", "A cross-functional logistics team around one clean table creates a fast lane for smaller solutions, with sales, operations, finance and legal reviewing the same blank page together.", ["阈值前置", "并行评审", "销售拿到明确承诺"], person="gao-feng", speaker="高峰", quote="先把能快的单子快起来。", metrics=[metric("快车道阈值", 50, "万"), metric("承诺时限", 48, "小时", tone="good")], nodes=["销售", "运营", "财务", "法务"], links=[{"from": 1, "to": 2, "label": "并行"}, {"from": 1, "to": 3, "label": "并行"}, {"from": 1, "to": 4, "label": "并行"}], role="map"),
            S([21, 23], "审批2.3天\n周期回到52天", "结果回升", "A logistics team now hands proposals to customers while trucks move steadily in the background, the former internal bottleneck replaced by synchronized movement.", ["平均2.3天", "周期52天", "成交提升35%"], person="feng-tao", speaker="冯涛", quote="客户终于等到了确定性。", metrics=[metric("审批耗时", 2.3, "天", from_value=23, decimals=1, tone="good"), metric("成交提升", 35, "%", tone="good")], bars=[bar("改造前", 90, "天", "bad", 100), bar("改造后", 52, "天", "good", 100)], role="evidence"),
            S([24, 26], "跟进不力之前\n先看内部路径", "销售不复杂", "A closing editorial metaphor of a customer path passing through the company without blockage, with managers removing internal gates before blaming the frontline.", ["客户等的是确定性", "流程就是客户体验", "管理要拆掉内耗"], role="metaphor"),
        ],
    ),
    "sales_management_case11_video": C(
        "从自己赢，到让团队赢",
        [
            P("chen-zhiyuan", "chen-zhiyuan.png", "A male former top salesperson in his early thirties, ambitious but exhausted posture, jacket slightly loosened."),
            P("fang-yi", "fang-yi.png", "A female senior manager in her forties, steady coaching posture, calm authority."),
        ],
        [
            S([1, 2], "销冠升主管\n三个月累到住院", "角色错位", "A newly promoted sales supervisor sits under a hospital-like white light while sales files and team requests pile up around him, the team performance shadow looming behind.", ["三年销冠", "刚升主管", "团队反而更差"], person="chen-zhiyuan", speaker="陈志远", quote="我明明比以前更拼。", treatment="crisis"),
            S([3, 6], "过去靠自己赢\n现在要带六个人赢", "新角色", "A former champion salesperson stands between a personal trophy-lit path and a broader team path with six waiting salespeople, unsure how to shift from doing to leading.", ["连续三年第一", "个人业绩3100万", "团队目标1.2亿"], person="chen-zhiyuan", speaker="陈志远", quote="以前我自己冲就行。", metrics=[metric("个人业绩", 3100, "万", tone="good"), metric("团队目标", 1.2, "亿", tone="bad")], bars=[bar("第一年", 2100, "万", "good", 3200), bar("第二年", 2600, "万", "good", 3200), bar("第三年", 3100, "万", "good", 3200)], role="evidence"),
            S([7, 10], "下属一求助\n主管立刻亲自上", "救火模式", "A sales supervisor jumps into every subordinate's customer call, proposal draft and negotiation, leaving his team watching passively from the edge of the room.", ["客户谈判他上", "方案修改他写", "大单还是他签"], person="chen-zhiyuan", speaker="陈志远", quote="我来吧。", nodes=["下属求助", "主管代打", "问题解决", "能力停滞"], links=[{"from": 1, "to": 2, "label": "触发"}, {"from": 2, "to": 3, "label": "短期"}, {"from": 2, "to": 4, "label": "长期"}], treatment="crisis"),
            S([11, 13], "团队越来越依赖\n新人越来越不敢动", "依赖形成", "A team stands behind the supervisor's shadow, each holding a blank customer folder but waiting for him to move first, with the supervisor stretched between multiple demands.", ["问题先找主管", "独立拜访减少", "学习机会被拿走"], person="chen-zhiyuan", speaker="陈志远", quote="他们都等我拿主意。", nodes=["代打", "依赖", "少练习", "更依赖"], links=[{"from": 1, "to": 2, "label": "产生"}, {"from": 2, "to": 3, "label": "挤掉"}, {"from": 3, "to": 4, "label": "加深"}], role="metaphor"),
            S([14, 18], "每天十六小时\n身体先报警", "崩溃节点", "A late-night office and a hospital corridor overlap visually, the supervisor's phone still lit while the team makes only sparse customer visits without him.", ["16小时工作", "医院躺一周", "团队只做2次拜访"], person="chen-zhiyuan", speaker="陈志远", quote="我一停，团队也停了。", metrics=[metric("工作时长", 16, "小时/天", tone="bad"), metric("团队拜访", 2, "次", tone="bad")], role="evidence", treatment="crisis"),
            S([19, 22], "方怡问了一句\n你在培养谁", "教练转向", "A senior manager sits across from the exhausted supervisor in a quiet coaching conversation, pointing to a blank notebook while the supervisor begins to listen.", ["每次代打都在剥夺训练", "先问再给答案", "让下属复盘"], person="fang-yi", speaker="方怡", quote="你在培养谁？", nodes=["客户问题", "主管提问", "下属复盘", "下次独立"], links=[{"from": 1, "to": 2, "label": "转化"}, {"from": 2, "to": 3, "label": "引导"}, {"from": 3, "to": 4, "label": "训练"}], role="map"),
            S([23, 24], "一个月不代打\n独立拜访开始恢复", "行为改变", "A calmer sales office where subordinates prepare and enter customer conversations themselves while the supervisor stands slightly behind them with a coaching notebook.", ["主管只提问题", "下属自己约客户", "独立拜访超前三个月"], person="chen-zhiyuan", speaker="陈志远", quote="我现在先问他们怎么想。", metrics=[metric("不代打周期", 1, "个月", tone="good"), metric("独立拜访", 3, "个月+", tone="good")], role="evidence"),
            S([25, 27], "升职之后\n要让别人会做", "销售不复杂", "A closing scene where the former champion steps back and the team moves forward into customer light, with coaching questions replacing rescue actions.", ["个人能力不能替代管理", "救火会制造依赖", "教练才能复制能力"], role="metaphor"),
        ],
    ),
    "sales_management_case12_video": C(
        "勤奋方向错了，只会重复撞墙",
        [
            P("song-lei", "song-lei.png", "A young male semiconductor salesperson, earnest and hardworking, carrying a blank notebook close to his chest."),
            P("he-ming", "he-ming.png", "A male sales manager in his forties, technical and calm, leaning slightly forward as a coach."),
        ],
        [
            S([1, 2], "全组最勤奋\n半年一单没签", "勤奋失效", "A semiconductor sales office where the most diligent salesperson sits with full notebooks and visit bags, yet the signed-order space on the table remains empty.", ["每天三次拜访", "三本笔记", "六个月零成交"], person="song-lei", speaker="宋磊", quote="我已经跑得很满了。", metrics=[metric("拜访", 3, "次/天"), metric("成交", 0, "单", tone="bad")], treatment="crisis"),
            S([3, 8], "表面很努力\n问题越问越深", "客户现场", "A semiconductor customer meeting where technical buyers ask increasingly specific process questions, while the salesperson listens carefully but cannot answer with confidence.", ["半导体客户", "技术问题连续追问", "回答只能回去确认"], person="song-lei", speaker="宋磊", quote="这个我回去确认。", metrics=[metric("关键追问", 3, "个", tone="bad")], role="evidence", treatment="crisis"),
            S([9, 13], "经理先看路线\n没有发现懒惰", "误判排除", "A sales manager reviews visit routes, CRM notes and customer follow-up records late at night, discovering diligence is real while the bottleneck lies elsewhere.", ["拜访量足够", "CRM记录完整", "机会还在推进"], person="he-ming", speaker="何明", quote="他确实很努力。", nodes=["拜访量", "记录完整", "客户推进", "仍无成交"], links=[{"from": 1, "to": 2, "label": "证明"}, {"from": 2, "to": 3, "label": "支撑"}, {"from": 3, "to": 4, "label": "仍卡住"}], role="evidence"),
            S([14, 18], "第一道门槛\n是脑子里的技术底子", "真正短板", "A customer trust gate inside a semiconductor plant, where notebooks and enthusiasm stop before a deeper technical layer of wafers, process chambers and engineering judgment.", ["懂流程不懂原理", "客户要判断能力", "信任卡在专业深度"], person="he-ming", speaker="何明", quote="第一个门槛是脑子里的技术底子。", nodes=["拜访勤奋", "技术底子", "客户判断", "信任建立"], links=[{"from": 1, "to": 2, "label": "缺口"}, {"from": 2, "to": 3, "label": "支撑"}, {"from": 3, "to": 4, "label": "形成"}], role="metaphor"),
            S([19, 20], "继续多跑\n只会重复撞墙", "错误处方", "A diligent salesperson repeatedly reaching the same technical wall at different customer sites, each visit ending at a similar blank barrier while the manager sees the pattern.", ["拜访量已经够", "技术债没有补", "重复拜访消耗信任"], person="song-lei", speaker="宋磊", quote="我跑得越多，越心虚。", treatment="desaturated"),
            S([21, 24], "停掉陌拜一个月\n跟着售前补课", "训练重排", "A salesperson shadows a pre-sales engineer inside a semiconductor demo room, listening, sketching blank process flows and learning how technical answers are formed.", ["影子学习", "三次陪访", "客户问题逐条复盘"], person="song-lei", speaker="宋磊", quote="我先把听不懂的补上。", metrics=[metric("训练周期", 1, "个月"), metric("陪访", 3, "次", tone="good")], role="map"),
            S([25, 27], "十二页技术笔记\n变成新的销售武器", "能力迁移", "A clean technical notebook becomes a practical sales toolkit in the foreground, while the salesperson rehearses answering customer concerns with an engineer nearby.", ["工艺流程图", "失效原因库", "常见问题清单"], person="song-lei", speaker="宋磊", quote="我开始知道客户在担心什么。", metrics=[metric("技术笔记", 12, "页", tone="good")], role="evidence"),
            S([28, 30], "五个问题答出四个\n三十五天签下80万", "结果突破", "A semiconductor customer meeting turns warmer as the salesperson answers technical questions directly and a first purchase agreement moves into the light.", ["5问答出4个", "首单80万", "35天完成签约"], person="song-lei", speaker="宋磊", quote="这次我能当场回答。", metrics=[metric("首单", 80, "万", tone="good"), metric("签约周期", 35, "天", tone="good")], bars=[bar("关键问题", 5, "个", "neutral", 5), bar("当场回答", 4, "个", "good", 5)], role="evidence"),
            S([31, 33], "勤奋要对准门槛\n专业才能换来信任", "销售不复杂", "A closing scene where focused learning and customer visits align into one clear path through a technical customer gate, with the manager and salesperson walking forward together.", ["努力先找方向", "客户买的是判断", "管理要补能力缺口"], role="metaphor"),
        ],
    ),
    "sales_management_case13_video": C(
        "困难对话需要练，沉默也有代价",
        [
            P("zhou-yi", "zhou-yi.png", "A male regional sales manager in his late thirties, careful and conflict-avoidant posture, hands loosely folded."),
            P("li-yang", "li-yang.png", "A male pharmaceutical salesperson in his early thirties, polite but disappointed posture, screen-left gaze."),
        ],
        [
            S([1, 2], "三分钟面谈\n埋下长期风险", "绩效面谈", "A regional sales manager conducts an overly brief performance conversation in a quiet office, while unresolved issues collect as dark layered shadows behind the employee.", ["经理不敢说重话", "复盘总是很短", "问题持续累积"], person="zhou-yi", speaker="周毅", quote="我想好好谈，只是真的不知道怎么开口。", treatment="crisis"),
            S([3, 5], "十二人三省\n面谈只剩三五分钟", "管理习惯", "A regional manager moving across several province teams, ending each performance conversation quickly with a polite handshake while the real issue remains on the table.", ["12名销售", "3个省区", "绩效面谈3到5分钟"], person="zhou-yi", speaker="周毅", quote="你再加强一下。", metrics=[metric("销售", 12, "人"), metric("省区", 3, "个"), metric("面谈", 5, "分钟内", tone="bad")], role="evidence"),
            S([6, 10], "九个月提醒\n没有说清事实", "模糊反馈", "A pharmaceutical sales manager repeatedly gives vague feedback while a hospital account slowly dims in the background, the employee unable to see the concrete performance facts.", ["只说加强学术", "处方量下降40%", "医院风险被放大"], person="li-yang", speaker="李洋", quote="我以为问题不严重。", metrics=[metric("处方量下降", 40, "%", tone="bad"), metric("模糊提醒", 9, "个月", tone="bad")], bars=[bar("处方量下降", 40, "%", "bad", 50), bar("提醒周期", 9, "个月", "bad", 12)], role="evidence", treatment="crisis"),
            S([11, 15], "三个月后丢医院\n辞职信才说明白", "后果爆发", "A hospital customer door closes while the salesperson places a resignation letter on the manager's desk, both figures separated by a wide pool of silence.", ["重点医院流失", "只是导火索", "真正问题早已积累"], person="li-yang", speaker="李洋", quote="这次丢客户只是导火索。", metrics=[metric("后续拖延", 3, "个月", tone="bad")], role="evidence", treatment="crisis"),
            S([16, 19], "沉默会让关系\n持续崩坏", "管理代价", "A quiet office where unspoken facts become a widening crack between manager, employee and customer relationship, with every polite conversation leaving the crack larger.", ["员工以为还能拖", "经理以为自己体面", "团队失去修正机会"], person="zhou-yi", speaker="周毅", quote="沉默也在传递信号。", nodes=["模糊反馈", "误判严重性", "错过修正", "关系崩坏"], links=[{"from": 1, "to": 2, "label": "造成"}, {"from": 2, "to": 3, "label": "延误"}, {"from": 3, "to": 4, "label": "推高"}], role="metaphor"),
            S([20, 23], "先练事实影响问题\n再进入面谈", "能力训练", "A manager practices a difficult conversation in role-play with a coach, preparing concrete facts, impact statements and open questions on blank cards before the real meeting.", ["每两周角色扮演", "连续6次练习", "先准备30分钟"], person="zhou-yi", speaker="周毅", quote="我先把事实说清楚。", metrics=[metric("练习", 6, "次", tone="good"), metric("准备", 30, "分钟", tone="good")], nodes=["事实", "影响", "问题", "行动"], links=[{"from": 1, "to": 2, "label": "说明"}, {"from": 2, "to": 3, "label": "引出"}, {"from": 3, "to": 4, "label": "落地"}], role="map"),
            S([24, 27], "三分钟变二十分钟\n反馈开始落地", "新面谈", "A more substantial performance conversation in warm light, the manager names facts calmly and the employee writes down a concrete next step, the room no longer evasive.", ["准备三项事实", "面谈20分钟", "员工拿到下一步动作"], person="zhou-yi", speaker="周毅", quote="我们具体看这三件事。", metrics=[metric("面谈时长", 20, "分钟", from_value=3, tone="good")], bars=[bar("过去", 3, "分钟", "bad", 20), bar("现在", 20, "分钟", "good", 20)], role="evidence"),
            S([28, 30], "困难对话要练\n沉默也有代价", "销售不复杂", "A closing scene where a manager holds a clear, respectful performance conversation before issues grow, with the team path brighter and steadier beyond the meeting room.", ["离职率25%到8%", "团队回到前三", "事实先于评价"], metrics=[metric("离职率", 8, "%", from_value=25, tone="good"), metric("团队排名", 3, "内", tone="good")], bars=[bar("原离职率", 25, "%", "bad", 30), bar("新离职率", 8, "%", "good", 30)], role="metaphor"),
        ],
    ),
}


def load_project_title(slug: str) -> str:
    title_path = ROOT / "output" / slug / "title.txt"
    raw = title_path.read_text(encoding="utf-8").strip()
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if len(lines) != 1:
        raise ValueError(f"{title_path} must contain exactly one non-empty title line")
    return lines[0]


def prepare_config(slug: str) -> dict[str, Any]:
    config = deepcopy(PROJECTS[slug])
    title = load_project_title(slug)
    config["title"] = title
    config["coverTitle"] = title
    for scene in config["scenes"][: min(5, len(config["scenes"]))]:
        if scene.get("visualVariants"):
            continue
        scene["visualVariants"] = [
            V(
                "gesture-detail",
                "Alternate camera angle of the same sales-management moment, closer focus on one decisive human gesture, "
                "a blank folder, table edge or doorway in the foreground, secondary silhouettes simplified in the background, "
                "same warm manager-silhouette palette and clean negative space, no readable text, no letters, no numbers. "
                f"Scene context: {scene['prompt']}",
                VARIANT_TARGETS,
            )
        ]
    for scene in config["scenes"]:
        if scene.get("links"):
            continue
        cards = list(scene.get("cards", []))
        if len(cards) < 3:
            continue
        if scene.get("person") and scene.get("speaker"):
            labels = [scene["speaker"], *cards[:3]]
        else:
            labels = cards[:3]
        scene["nodes"] = labels[:4]
        links = [
            {"from": 1, "to": 2, "label": "触发"},
            {"from": 2, "to": 3, "label": "推动"},
        ]
        if len(labels) >= 4:
            links.append({"from": 3, "to": 4, "label": "形成"})
        scene["links"] = links
    add_network_variety(config["scenes"])
    return config


def main() -> None:
    parser = argparse.ArgumentParser(description="Create requested sales-management storyboard plans.")
    parser.add_argument("projects", nargs="*", help="Optional project slugs; defaults to all requested projects")
    args = parser.parse_args()
    selected = args.projects or list(PROJECTS)
    unknown = [slug for slug in selected if slug not in PROJECTS]
    if unknown:
        raise SystemExit(f"unknown projects: {', '.join(unknown)}")
    for slug in selected:
        build_project(slug, prepare_config(slug))


if __name__ == "__main__":
    main()
