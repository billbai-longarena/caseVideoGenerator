#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path


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


CASES = {
    "sales_case02_video": {
        "type": "sales-case", "style": "sales", "title": "全员上线失败后，SaaS 项目还要继续吗", "subtitle": "销售案例 02",
        "headlines": ["全员上线\n活跃率只有18%", "六百人项目\n站到暂停边缘", "员工为什么\n不愿意使用", "十二步流程\n困住真实工作", "三百六十万\n缩成八十万", "先证明一件事\n值得被改变", "让一线员工\n参与设计规则", "六个步骤\n逐项取消", "活跃率升到83%", "规模变小\n合作重新启动", "采用发生在\n真实工作里", "销售不复杂\n下期再见"],
        "kickers": ["案例开场", "上线警报", "多方解释", "流程诊断", "主动缩单", "关键选择", "共同设计", "试点推进", "结果验证", "核心转折", "销售启示", "栏目收束"],
        "analysisHeadlines": ["四个变量\n共同降低阻力", "从真实场景\n逐步扩展规模"],
        "analysisKickers": ["决策拆解", "迁移方法"],
        "visuals": [
            "A factory campus at launch day, hundreds of small employee figures face a glowing software portal while only a few lights activate, visual tension and empty foreground.",
            "A large rollout launch scene collapses into a small dim adoption island with only a few lit points, executives and workers separated across layers.",
            "Three viewpoints around one workflow: executive tower, IT cables, and frontline desks with duplicate forms, connected in one panorama.",
            "A returns process represented as many winding approval stations crossing warehouse, finance, sales and service, workers carrying the same package twice.",
            "A huge project block carefully reduced into one focused customer-service pilot zone, tense leaders watching the choice.",
            "One authentic return case becomes a clear path through organizational fog, a small team gathers around it.",
            "Frontline employees rearrange blank field cards and approval gates with designers, collaborative workshop energy.",
            "Several redundant gates fade away from a workflow, leaving a short bright path and faster moving package.",
            "A service team workspace brightens as adoption spreads through ordinary daily work, active users shown as warm lit silhouettes around real return cases, no screens or text.",
            "A smaller focused partnership circle restarts around one validated pilot path, leaders on both sides lean in while a large paused rollout fades into blue distance.",
            "Four sources of resistance appear as translucent barriers around one frontline workflow, each barrier becoming lighter as the team addresses practical friction.",
            "One authentic work scene expands outward from a service desk to warehouse, finance and sales teams, gradual scale without losing the original field context.",
            "A salesperson stands inside the customer workplace observing real motion instead of presenting slides, daily tasks and human constraints clearly visible.",
            "A calm closing scene with blue and yellow business watercolor, a clear path through a modern workplace and clean space for final motion graphics.",
        ],
    },
    "sales_case03_video": {
        "type": "sales-case", "style": "sales", "title": "上市倒计时：一笔贷款之外的三个月", "subtitle": "销售案例 03",
        "headlines": ["利率差二十万\n窗口只剩91天", "客户要的\n真是一笔续贷吗", "三条时间线\n从未连接", "币种 法务 股权\n同时收紧", "最贵的风险\n藏在日期里", "九十一天节点图\n逐项展开", "四支专业团队\n进入同一张表", "二十万利息\n对比半年窗口", "三周完成\n授信锁汇托管", "没有最低价格\n守住关键节点", "完整风险地图\n建立战略关系", "销售不复杂\n下期再见"],
        "kickers": ["案例开场", "价格压力", "隐藏信息", "连续追问", "期限收紧", "节点设计", "内部协作", "价值重估", "联合交付", "结果验证", "销售启示", "栏目收束"],
        "analysisHeadlines": ["先锁定日期\n再展开条件", "三张表连接\n产品与节点"],
        "analysisKickers": ["决策拆解", "迁移方法"],
        "visuals": [
            "A precision manufacturing CFO at a table with several blank bank offer folders, a closing calendar shadow behind the room.",
            "A small interest-rate scale in foreground while a distant stock-market filing gate begins to close, strong depth.",
            "Three separate abstract rivers represent bank funding, imported equipment, and family equity, not yet connected.",
            "Imported equipment crates, overseas receivables and tangled ownership rings converge around a worried finance leader.",
            "A closing legal gate approaches an unfinished filing package, calendar pages accelerating through a business landscape.",
            "A luminous compressed route with several milestone stations and distinct professional teams entering from different directions.",
            "Investment banking, foreign exchange, custody and private banking specialists assemble around one integrated timeline, no readable screens.",
            "A tiny cost pebble beside a huge closing market window, founder choosing to coordinate the whole plan.",
            "Several professional workstreams converge into one clean execution corridor, the client team walks through a narrow listing window with steady support.",
            "A founder and finance leader stand before a bright closing gate while separate service teams hold the path open, calm urgency without text or numbers.",
            "A complete risk map appears as abstract terrain around the client, with funding, legal, foreign exchange and ownership paths connected by light.",
            "Three linked business tables appear as abstract worksheets without text: deadline map, risk map and resource map, all converging toward one decision point.",
            "Product specialists and calendar milestones lock together around one client decision path, abstract service blocks attached to key dates without readable labels.",
            "A quiet decision room with a leader considering which date and which risk to lock first, several blank folders arranged like future options.",
            "A calm closing scene with blue and yellow business watercolor, a clear route from pressure to coordinated execution, clean negative space.",
        ],
    },
    "sales_case04_video": {
        "type": "sales-case", "style": "sales", "title": "经销商把库存表摔在桌上之后", "subtitle": "销售案例 04",
        "headlines": ["库存82天\n临期商品31%", "出货增长\n终端只卖掉42%", "新主管先去仓库", "产品和门店\n发生错配", "暂停压货\n共同承担代价", "三十家门店\n六周试点", "返利从进货\n转向售罄", "库存 销量 价格\n每周展开", "售罄率升到68%", "经销商主动\n开放每日数据", "信任来自\n共同承担风险", "销售不复杂\n下期再见"],
        "kickers": ["案例开场", "渠道危机", "现场盘库", "问题诊断", "试点方案", "范围控制", "机制改变", "数据协作", "结果验证", "信任恢复", "销售启示", "栏目收束"],
        "analysisHeadlines": ["共同承担代价\n换回真实数据", "四步修复\n渠道增长逻辑"],
        "analysisKickers": ["决策拆解", "迁移方法"],
        "visuals": [
            "A distributor slams a blank inventory sheet onto a meeting table, warehouse stacks rise behind him like a wall.",
            "Brand shipments surge into a warehouse while only a thin stream reaches neighborhood stores, blank shelf tags under pressure.",
            "A newly appointed female regional leader walks warehouse aisles with the distributor, counting cartons under warm industrial light.",
            "Large packages crowd tiny community shops while small modern packs are absent from bright convenience stores, split urban scene.",
            "Brand and distributor place shared cost tokens into a small pilot circle, large quarterly target tower paused in background.",
            "A small controlled test network of varied retail stores, a compact joint team moving between them.",
            "Incentive current turns from warehouse intake toward consumer sell-through, shelves becoming balanced and active.",
            "Warehouse ledgers, store shelves and price conversations come together in one open review meeting, trust gradually brightening the scene.",
            "A once-overloaded warehouse aisle becomes organized as real sell-through signals move toward store shelves, brand and distributor silhouettes watch together.",
            "A distributor opens daily operating visibility to a brand team, abstract data lights flow from stores to warehouse without readable dashboards.",
            "Brand and distributor share one risk table, cost tokens and inventory blocks balanced between them under blue and yellow watercolor light.",
            "Four practical repair steps unfold across warehouse, store, price conversation and weekly review scenes, connected by a single clear route.",
            "A channel growth mechanism is repaired as inventory, sell-through, pricing and review rhythms begin moving in sync across one watercolor business landscape.",
            "A regional sales leader pauses in the aisle before choosing the first move, messy cartons and quiet store shelves showing the tradeoff.",
            "A calm closing scene with blue and yellow business watercolor, a refreshed retail route and open space for final motion graphics.",
        ],
    },
    "sales_management_case02_video": {
        "type": "sales-management-case", "style": "management", "title": "总部多加的三千万指标，该压给谁", "subtitle": "销售管理案例 02",
        "headlines": ["预算刚通过\n又加三千万", "简单平均\n制造新的不公平", "三种分法\n三种经营选择", "先画可赢收入桥", "过去贡献\n不等于未来增量", "机会 产能 交付\n同时核对", "指标拆成三层", "基础 机会 战略\n逐层释放", "目标移动\n资源跟着移动", "复杂规则\n换来清楚责任", "分配指标\n也是投资未来", "销售不复杂\n下期再见"],
        "kickers": ["案例开场", "分配争议", "规则选择", "证据准备", "数据反转", "能力约束", "三层目标", "逐步分配", "资源联动", "季度复盘", "管理启示", "栏目收束"],
        "analysisHeadlines": ["三层目标\n使用不同节奏", "四个连接\n组成目标机制"],
        "analysisKickers": ["管理设计", "迁移方法"],
        "visuals": [
            "Additional target pressure lands in a regional planning room. Overhead three-quarter view: a glowing heavy folder drops onto a blank territory map while several manager silhouettes lean back under the weight, cream negative space above the table.",
            "Equal allocation creates visible unfairness. Wide executive review room with one large regional team trapped beneath the tallest stack of blank folders, smaller teams standing aside in cool navy layers, strong orange rim light from the far window.",
            "Three allocation choices become three doors. Long corporate corridor with three warm-lit rooms ahead, leader silhouettes pause at the intersection: one door shows past sales trophies as abstract shapes, one shows a market skyline, one shows a strategic bridge. No text.",
            "A winnable revenue bridge is assembled. Low-angle planning table where renewal blocks, opportunity folders, market-capacity tiles, people calendars and delivery gates form one bridge across a dark gap, managers placing pieces carefully.",
            "Past contribution is separated from future increment. Split-depth office war room: a mature eastern-region silhouette stands near a nearly full warm wall, while southern and central teams hold unresolved late-stage customer folders in deeper blue space.",
            "Capacity constraint appears at the service desk. Pre-sales specialists crowd around a narrow glowing counter, several sales-team silhouettes wait with customer folders, delivery gate shadows behind them reveal the bottleneck.",
            "Three layers of target are released separately. Dark planning hall with three transparent stacks of blank target folders rising at different heights and brightness, a director silhouette points to the base, opportunity and strategic layers without any text.",
            "Target and resources move together. Transparent allocation meeting seen from above: each regional leader receives a different folder beside matching staffing calendars and support tokens, clean responsibility lines connect across the table.",
            "A moving target mechanism is adjusted in a dark executive room: support tokens and staffing calendars shift together with regional folders, clear human silhouettes and warm rim light, no text.",
            "Complex allocation rules become clear responsibility. Several managers sign off around one table of blank responsibility cards, tension easing as ownership lines become visible, no words.",
            "Assigning targets becomes an investment choice. A senior leader places resources toward future-growth regions while stable regions hold the base, strong amber backlight and navy silhouettes.",
            "Three target layers run on different rhythms. A planning room shows base work, opportunity pursuit and strategic bets as three separate moving platforms, human operators present, no labels.",
            "Four management connections lock together around one goal mechanism: opportunity, capacity, delivery and review represented by connected desks and leader silhouettes, cinematic cut-paper style.",
            "A responsible leader stands before several possible allocation rules, pausing over which rule to change first, warm silhouette scene with clean negative space.",
            "A calm closing scene in warm manager-silhouette style, meeting room lights dimming around a clear future operating path, no readable text.",
        ],
    },
    "sales_management_case03_video": {
        "type": "sales-management-case", "style": "management", "title": "预测准确率 90%，季度末为什么仍然爆雷", "subtitle": "销售管理案例 03",
        "headlines": ["预测准确率90%\n最后六天爆雷", "两笔订单延期\n缺口2200万", "最终报表\n解释不了风险", "十二周快照\n开始回放", "总额很稳定\n订单一直在换", "团队汇报\n老板想听的确定性", "三项指标\n揭开平滑曲线", "客户承诺\n逐笔提供证据", "风险主动下调\n不再立即追责", "曲线波动变大\n突发缺口减少", "预测让坏消息\n更早出现", "销售不复杂\n下期再见"],
        "kickers": ["案例开场", "季度爆雷", "错误问题", "快照追踪", "底层流动", "机制诱因", "指标重算", "证据规则", "问责改变", "结果验证", "管理启示", "栏目收束"],
        "analysisHeadlines": ["三种声音\n必须清楚标识", "提问方式\n决定风险是否出现"],
        "analysisKickers": ["管理设计", "迁移方法"],
        "visuals": [
            "Smooth forecast hides late risk. A polished glass forecast table glows in an executive room while a cracked dark foundation is visible beneath the reflection, finance and sales silhouettes notice too late.",
            "Quarter-end gap opens suddenly. Two oversized deal blocks fall out of a revenue tower near the top, shocked executive silhouettes below reach upward under amber spotlights, deep negative space on the left.",
            "Final report cannot explain risk. A clean blank report folder stands like a screen in the foreground, while shadowy customer deal folders move behind it; a sales-operations leader silhouette looks past the surface.",
            "Weekly snapshots start to rewind. Many translucent paper-like layers unfold through a dark meeting room, one analyst silhouette traces deal movement across them with a thin warm light path.",
            "Stable total masks deal replacement. Top summary slab remains level in the foreground while individual opportunity folders underneath keep swapping lanes in navy shadow, viewed from a high oblique angle.",
            "Managers learn to report certainty. Before a weekly meeting, several manager silhouettes quietly move risk cards under a harsh authority spotlight, the closed executive door glows at the far end.",
            "Three evidence lamps reveal the forecast. Separate warm cones of light expose unstable commitments, shifted dates and missing customer action around one planning table, evidence folders appear sequentially.",
            "Commit stage receives a stricter gate. Opportunities pass through three staffed review desks for customer confirmation, decision process and next action; the path is cinematic and human, not a flowchart.",
            "Forecast volatility becomes visible earlier. A weekly review room shows larger but healthier waves under the forecast table while leaders respond before quarter-end pressure builds.",
            "Late surprises shrink as risk is surfaced sooner. A sales operations leader opens a dark side door early, releasing warning light before the final week arrives.",
            "Bad news appears early enough to manage. A leader sees warning folders emerging at the start of the quarter path, with teams already adjusting resources under warm light.",
            "Three reporting voices are separated in a meeting room: customer evidence, seller judgment and manager pressure appear as distinct human groups under separate light cones, no labels.",
            "The manager changes the question in a forecast meeting, shifting attention from a smooth total to unstable individual commitments, strong silhouette gestures.",
            "A regional manager hesitates before reporting bad news early, facing a supportive review table instead of a punishment spotlight, warm backlight.",
            "A calm closing scene in warm manager-silhouette style, forecast layers settling into a transparent operating rhythm, no text or numbers.",
        ],
    },
    "sales_management_case04_video": {
        "type": "sales-management-case", "style": "management", "title": "两支销售队伍争夺同一个客户", "subtitle": "销售管理案例 04",
        "headlines": ["同一客户\n收到两份报价", "两个价格\n两套承诺", "客户归属规则\n放大零和竞争", "冻结报价\n先停止内部失序", "六个月记录\n拼出完整决策链", "真正冲突\n落到利益分配", "建立唯一账户契约", "责任 权限 收入\n逐项拆开", "二百四十万试点\n重新赢得入场券", "规则推广到\n十二个重叠客户", "内部契约\n最终成为客户体验", "销售不复杂\n下期再见"],
        "kickers": ["案例开场", "客户质问", "制度缺口", "止损动作", "关系还原", "利益冲突", "账户契约", "权责展开", "试点验证", "机制推广", "管理启示", "栏目收束"],
        "analysisHeadlines": ["先保护客户界面\n再处理内部利益", "四个答案\n组成账户治理"],
        "analysisKickers": ["管理设计", "迁移方法"],
        "visuals": [
            "One customer receives two offers. A procurement leader silhouette places two blank proposal covers on one table, two sales teams face each other from opposite sides in a tense amber-lit customer room.",
            "Two promises collide at the customer interface. Regional and industry team silhouettes push different price-and-timeline folders toward the same automotive-group meeting table, their routes crossing without text.",
            "First-registration rule becomes a narrow gate. Inside a dark corporate corridor, two organizational branches pull one account folder toward a small glowing gate, a customer silhouette waits beyond it.",
            "Director freezes the disorder. A sales director silhouette physically holds back two outgoing proposal folders before they leave the office, the customer doorway glows in the distance.",
            "Six months of relationship history is reconstructed. Blank contact cards, meeting-photo shapes and route lines spread across a wall showing group headquarters and a local factory as abstract silhouettes.",
            "The real conflict lands on interests. Relationship ownership, solution design and commission concern pull three leader silhouettes in different directions around one account folder under a single spotlight.",
            "A single-account agreement creates order. A large blank account board stands in the center with one clear owner silhouette and two responsibility zones connected by clean light paths, no labels.",
            "Account governance becomes operating architecture. Four unlabeled work tables unfold across a deep office floor for customer responsibility, decision rights, revenue allocation and shared information, architectural clarity.",
            "The pilot customer meeting reopens after internal order is restored. One unified team enters the room together while two former routes merge behind them, no text.",
            "Overlapping customers are reviewed through a shared account mechanism. Several account folders move into one operating corridor across a dark office floor, no labels.",
            "Customer experience becomes cleaner as internal agreements align. A procurement leader sees one coordinated team instead of two competing silhouettes.",
            "The customer interface is protected first. Two internal teams step back from a glowing customer doorway while leaders resolve commercial interests inside the office.",
            "Four governance answers connect into one account mechanism, shown as responsibility, authority, revenue and information desks joined by light paths without readable labels.",
            "A sales leader pauses before choosing the first rule to change, two teams waiting on opposite sides of one customer doorway, warm rim light.",
            "A calm closing scene in warm manager-silhouette style, one unified customer path leading out of a dark meeting room, clean negative space.",
        ],
    },
}


LAYOUTS = [
    "breaking-news", "split-data", "subject-reveal", "decision-bottleneck",
    "balance-beam", "timeline-roadshow", "authority-matrix", "performance-ladder",
    "split-data", "closing-quote", "local-playbook", "authority-matrix", "closing-quote", "closing-quote",
    "closing-quote",
]

TRANSITIONS = ["flash", "push", "paper", "ink", "wash", "push", "wash", "paper", "flash", "ink", "wash", "push", "wash", "paper", "flash"]
MOTIONS = ["lift", "right", "left", "center", "left", "right", "lift", "center", "right", "left", "lift", "right", "lift", "center", "lift"]


def scene_props(case: dict, headlines: list[str], kickers: list[str], index: int) -> tuple[dict, dict]:
    headline = headlines[index]
    if index == 0:
        return {"stamp": "关键反转", "infoLabel": case["subtitle"], "info": headline.replace("\n", " · ")}, {"stampAtUnit": 1, "infoAtUnit": 3}
    if index in (1, 8):
        return {"signalLabel": "关键变化", "signal": headline.replace("\n", " → ")}, {"signalAtUnit": 2}
    if index == 2:
        return {"reveal": headline.replace("\n", " / "), "revealSize": 92, "noteLabel": "隐藏线索", "note": kickers[index]}, {"revealAtUnit": 1, "noteAtUnit": 3}
    if index == 3:
        return {"center": kickers[index], "nodes": "客户事实|团队判断|资源约束|责任边界", "warning": headline.replace("\n", "，")}, {"centerAtUnit": 0, "nodeAtUnits": [1, 2, 3, 4], "warningAtUnit": 5}
    if index == 4:
        return {"formula": headline.replace("\n", " ≠ ")}, {"formulaAtUnit": 3}
    if index == 5:
        return {"cities": ["事实", "节点", "责任", "行动"], "stamp": "展开", "quote": headline.replace("\n", "，"), "railLabel": "STEP BY STEP"}, {"stampAtUnit": 1, "quoteAtUnit": 4}
    if index == 6:
        return {"roles": "客户负责人|销售经理|专业团队|交付负责人", "tasks": "确认真实目标|配置资源边界|提供专业证据|验证执行结果", "footer": headline.replace("\n", "，")}, {"roleAtUnits": [0, 1, 2, 3], "footerAtUnit": 5}
    if index == 7:
        return {"years": "第一步|第二步|第三步", "values": "看见事实|调整机制|验证结果", "badge": headline,}, {"valueAtUnits": [0, 2, 4], "badgeAtUnit": 5}
    if index == 10:
        return {"badge": "迁移方法", "cardTitle": "PLAYBOOK", "cardText": headline.replace("\n", " · ")}, {}
    if index == 11:
        return {"roles": "事实|责任|资源|复盘", "tasks": "看见变化|明确负责人|匹配投入|持续修正", "footer": headline.replace("\n", "，")}, {"roleAtUnits": [0, 1, 2, 3], "footerAtUnit": 5}
    return {"overline": kickers[index], "badge": "销售\n不复杂" if index == len(headlines) - 1 else "CASE\nNOTE"}, {"badgeAtUnit": 2}


def build_case(name: str, case: dict) -> None:
    project = ROOT / "output" / name
    project.mkdir(parents=True, exist_ok=True)
    style_name = "bright-editorial-watercolor" if case["style"] == "sales" else "warm-manager-silhouette-motion-graphics"
    image_dir = "images/sales_watercolor" if case["style"] == "sales" else "images/manager_silhouette"
    style_prefix = SALES_STYLE if case["style"] == "sales" else MANAGEMENT_STYLE
    if name == "sales_case02_video":
        headlines = case["headlines"][:-2] + case["analysisHeadlines"] + case["headlines"][-2:]
        kickers = case["kickers"][:-2] + case["analysisKickers"] + case["kickers"][-2:]
    else:
        question = "如果你在现场\n会先改变哪一步" if case["style"] == "sales" else "如果你是负责人\n会先改哪条规则"
        headlines = case["headlines"][:-1] + case["analysisHeadlines"] + [question, case["headlines"][-1]]
        kickers = case["kickers"][:-1] + case["analysisKickers"] + ["留给你思考", case["kickers"][-1]]

    scenes = []
    if len(case["visuals"]) != len(headlines):
        raise SystemExit(
            f"{name} has {len(headlines)} scenes but {len(case['visuals'])} image prompts"
        )
    for index, headline in enumerate(headlines):
        props, timings = scene_props(case, headlines, kickers, index)
        scenes.append({
            "paragraph": index + 1,
            "kicker": kickers[index],
            "layout": LAYOUTS[index],
            "tone": "bright" if case["style"] == "sales" and index in (2, 5, 6, 7, 8, 10, 11) else ("archive" if index in (2, 4, 7) else "dark"),
            "headline": headline,
            "accent": [part for part in headline.split("\n")[-1:] if part],
            "background": f"{image_dir}/{index + 1:02d}.png",
            "transition": TRANSITIONS[index],
            "motion": MOTIONS[index],
            "keywords": [
                {"text": headline.replace("\n", " ").split(" ")[-1], "offset": 2, "sfx": "pop"},
                {"text": kickers[index], "offset": 4, "sfx": "stamp"},
            ],
            "props": props,
            "propTimings": timings,
        })

    plan = {
        "project": {
            "slug": name.replace("_video", "").replace("_", "-"),
            "title": case["title"],
            "subtitle": case["subtitle"],
            "brand": "销售不复杂",
            "projectType": case["type"],
            "visualStyle": style_name,
            "subtitleLabel": "销售不复杂",
        },
        "scenes": scenes,
    }
    (project / "storyboard_plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    prompts = []
    for index, visual in enumerate(case["visuals"], start=1):
        prompts.append({"file": f"{image_dir}/{index:02d}.png", "prompt": visual})
    prompt_file = {"stylePrefix": style_prefix, "outputDir": image_dir, "prompts": prompts}
    (project / "image_prompts.json").write_text(json.dumps(prompt_file, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    (project / "build_storyboard.py").write_text(
        "#!/usr/bin/env python3\n"
        "from pathlib import Path\n"
        "import subprocess\n\n"
        "root = Path(__file__).resolve().parents[2]\n"
        "subprocess.run([str(root / 'scripts/build_storyboard_from_plan.py'), str(Path(__file__).resolve().parent)], check=True)\n",
        encoding="utf-8",
    )
    (project / "build_storyboard.py").chmod(0o755)


def main() -> None:
    for name, case in CASES.items():
        build_case(name, case)
        print(f"planned {name}")


if __name__ == "__main__":
    main()
