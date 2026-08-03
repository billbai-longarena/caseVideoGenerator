from __future__ import annotations

from html import escape

from fastapi import APIRouter
from fastapi.responses import HTMLResponse


router = APIRouter(include_in_schema=False)


def _shell(*, title: str, page: str, content: str, job_id: str | None = None) -> HTMLResponse:
    safe_title = escape(title)
    job_attr = f' data-job-id="{escape(job_id, quote=True)}"' if job_id else ""
    return HTMLResponse(
        f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="color-scheme" content="light">
  <title>{safe_title} · 案例视频工厂</title>
  <link rel="stylesheet" href="/static/app.css">
  <script src="/static/app.js" defer></script>
</head>
<body data-page="{escape(page, quote=True)}"{job_attr}>
  <a class="skip-link" href="#main">跳到主要内容</a>
  <header class="site-header">
    <a class="brand" href="/jobs" aria-label="案例视频工厂首页">
      <span class="brand-mark" aria-hidden="true">CV</span>
      <span><strong>案例视频工厂</strong><small>销售不复杂</small></span>
    </a>
    <div class="header-actions">
      <nav aria-label="主导航">
        <a href="/jobs">任务中心</a>
        <a href="/jobs/new">创建任务</a>
        <a href="/admin/health">系统状态</a>
        <a href="/admin/operations" id="admin-nav-link" hidden>管理与治理</a>
      </nav>
      <div class="session-tools" id="session-tools" hidden>
        <label class="workspace-switcher" for="tenant-switcher"><span>工作区</span><select id="tenant-switcher" aria-label="切换工作区"></select></label>
        <div class="session-identity"><strong id="session-user">当前用户</strong><small id="session-role"></small></div>
        <button class="button ghost compact" type="button" id="logout-button">退出</button>
      </div>
    </div>
  </header>
  <main id="main" class="page-shell">{content}</main>
  <div id="toast-region" class="toast-region" aria-live="polite" aria-atomic="true"></div>
  <div id="live-region" class="sr-only" aria-live="polite" aria-atomic="true"></div>
  <dialog id="confirm-dialog" class="dialog">
    <form method="dialog">
      <h2 id="confirm-title">请确认</h2>
      <p id="confirm-message"></p>
      <div class="dialog-actions">
        <button value="cancel" class="button secondary">取消</button>
        <button value="confirm" class="button danger" id="confirm-submit">确认</button>
      </div>
    </form>
  </dialog>
</body>
</html>"""
    )


def _admin_nav(active: str) -> str:
    links = (
        ("health", "/admin/health", "系统状态"),
        ("operations", "/admin/operations", "运维看板"),
        ("members", "/admin/members", "成员与角色"),
        ("governance", "/admin/governance", "额度与治理"),
        ("audit", "/admin/audit", "审计日志"),
        ("retention", "/admin/retention", "保留与删除"),
    )
    items = []
    for key, href, label in links:
        current = ' aria-current="page"' if key == active else ""
        items.append(f'<a href="{href}"{current}>{label}</a>')
    return '<nav class="admin-nav" aria-label="管理导航">' + "".join(items) + "</nav>"


@router.get("/login", response_class=HTMLResponse)
def login_page() -> HTMLResponse:
    return _shell(
        title="登录",
        page="login",
        content="""
<section class="login-layout">
  <div class="login-copy"><p class="eyebrow">Secure production workspace</p><h1>登录案例视频工厂</h1><p>在服务器端统一生产标题、旁白、视觉计划和 Remotion 成片。你只能访问已授权的工作区。</p><ul class="feature-list"><li>Claude 固定通过 Azure Anthropic Messages API</li><li>其他模型任务固定使用 gpt-5.5</li><li>人工审核、费用和每次管理操作都有审计记录</li></ul></div>
  <section class="panel login-panel" aria-labelledby="login-title"><h2 id="login-title">身份验证</h2><p id="login-description">正在读取服务器登录方式…</p><a class="button primary full" id="oidc-login" href="/auth/login" hidden>使用企业账号登录</a><form id="static-login-form" hidden><label>服务器访问令牌<input name="token" type="password" autocomplete="current-password" required></label><label>工作区 ID（可选）<input name="tenant_id" autocomplete="organization"></label><button class="button primary full" type="submit">登录</button></form><div class="inline-alert danger" id="login-error" role="alert" hidden></div></section>
</section>
""",
    )


@router.get("/jobs", response_class=HTMLResponse)
def jobs_page() -> HTMLResponse:
    return _shell(
        title="任务中心",
        page="jobs",
        content="""
<section class="page-heading split-heading">
  <div><p class="eyebrow">Production control</p><h1>任务中心</h1><p>查看生产进度、人工审核和正式交付状态。</p></div>
  <a class="button primary" href="/jobs/new">创建案例视频</a>
</section>
<section class="metric-grid" id="job-metrics" aria-label="任务概览"></section>
<section class="panel">
  <form id="job-filters" class="filter-grid" role="search">
    <label>搜索<input name="q" type="search" placeholder="案例名或任务 ID"></label>
    <label>状态<select name="status"><option value="">全部状态</option><option value="queued">排队中</option><option value="running">处理中</option><option value="waiting_approval">待审核</option><option value="succeeded">已完成</option><option value="failed">失败</option><option value="canceled">已取消</option></select></label>
    <label>人工动作<select name="needs_action"><option value="">全部</option><option value="true">需要处理</option><option value="false">无需处理</option></select></label>
    <label>审批模式<select name="approval_mode"><option value="">全部模式</option><option value="editorial">仅文稿审核</option><option value="full">文稿与视觉审核</option><option value="auto">自动</option></select></label>
    <label>创建日期从<input name="created_from" type="date"></label>
    <label>创建日期至<input name="created_to" type="date"></label>
    <div class="filter-actions"><button class="button primary" type="submit">筛选</button><button class="button ghost" type="button" id="clear-filters">清除</button></div>
  </form>
  <div id="jobs-loading" class="loading-block">正在加载任务…</div>
  <div class="table-wrap" hidden id="jobs-table-wrap">
    <table class="data-table"><thead><tr><th>任务</th><th>状态</th><th>当前阶段</th><th>进度</th><th>更新时间</th><th><span class="sr-only">操作</span></th></tr></thead><tbody id="jobs-body"></tbody></table>
  </div>
  <div class="empty-state" id="jobs-empty" hidden><h2>没有匹配的任务</h2><p>调整筛选条件，或创建一个新的案例视频任务。</p><a class="button primary" href="/jobs/new">创建任务</a></div>
</section>
""",
    )


@router.get("/jobs/new", response_class=HTMLResponse)
def new_job_page() -> HTMLResponse:
    return _shell(
        title="创建任务",
        page="job-new",
        content="""
<section class="page-heading"><a class="back-link" href="/jobs">← 返回任务中心</a><p class="eyebrow">New production</p><h1>创建案例视频</h1><p>四步完成材料上传和生产规则确认。模型路由由服务器固定，页面不能覆盖。</p></section>
<ol class="stepper" id="create-stepper" aria-label="创建进度">
  <li aria-current="step"><span>1</span>基本信息</li><li><span>2</span>上传材料</li><li><span>3</span>生产设置</li><li><span>4</span>确认提交</li>
</ol>
<form id="create-job-form" novalidate>
  <section class="panel wizard-step" data-step="1">
    <h2>基本信息</h2><p class="section-help">用于任务检索和成片生产，不会自动写入视频标题。</p>
    <div class="form-grid">
      <label class="span-2">案例名称<span aria-hidden="true"> *</span><input name="project_name" maxlength="120" required autocomplete="off" placeholder="例如：区域销售团队的责任重构"><small>1–120 个字符，不能包含路径符号。</small></label>
      <label>栏目<input name="program" value="销售不复杂" readonly></label>
      <label>审批模式<select name="approval_mode"><option value="full">文稿与视觉双审核（推荐）</option><option value="editorial">仅文稿审核</option><option value="auto">自动生产</option></select><small>双审核会在付费生图前再次暂停。</small></label>
    </div>
  </section>
  <section class="panel wizard-step" data-step="2" hidden>
    <h2>上传材料</h2><p class="section-help">支持 TXT、Markdown、JSON、PDF 和 DOCX。每个文件在上传前后都会校验类型与大小。</p>
    <label class="drop-zone" id="drop-zone"><input id="source-files" type="file" multiple accept=".txt,.md,.json,.pdf,.docx"><span class="drop-title">拖放材料到这里，或选择文件</span><span id="upload-limits">正在读取上传限制…</span></label>
    <ul class="upload-list" id="upload-list" aria-label="已选材料"></ul>
    <div class="inline-alert danger" id="upload-error" hidden role="alert"></div>
  </section>
  <section class="panel wizard-step" data-step="3" hidden>
    <h2>生产设置</h2>
    <div class="form-grid">
      <label>目标最短时长（秒）<input name="duration_min" type="number" min="60" max="1800" value="240" required></label>
      <label>目标最长时长（秒）<input name="duration_max" type="number" min="60" max="1800" value="420" required></label>
      <label>预算上限（美元，可选）<input name="budget_usd" type="number" min="0" step="0.01" placeholder="留空表示使用租户默认额度"></label>
    </div>
    <div class="route-summary" id="route-summary" aria-label="固定模型路由"></div>
  </section>
  <section class="panel wizard-step" data-step="4" hidden>
    <h2>确认提交</h2><p class="section-help">提交后材料将绑定到任务。生产中的每个模型调用都会记录模型、提示词版本和输入哈希。</p>
    <dl class="review-list" id="create-review"></dl>
    <label class="check-row"><input type="checkbox" name="confirm_sources" required> 我已确认材料可用于此案例视频生产，且不包含不应上传的敏感内容。</label>
    <div class="inline-alert danger" id="create-error" hidden role="alert"></div>
  </section>
  <div class="wizard-actions"><button type="button" class="button secondary" id="wizard-back" hidden>上一步</button><button type="button" class="button primary" id="wizard-next">下一步</button><button type="submit" class="button primary" id="wizard-submit" hidden>创建并开始生产</button></div>
</form>
""",
    )


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_detail_page(job_id: str) -> HTMLResponse:
    return _shell(
        title="任务详情",
        page="job-detail",
        job_id=job_id,
        content="""
<section class="page-heading split-heading"><div><a class="back-link" href="/jobs">← 返回任务中心</a><p class="eyebrow">Production job</p><h1 id="job-title">任务详情</h1><p class="mono" id="job-id"></p></div><div id="job-primary-action"></div></section>
<div class="connection-banner" id="event-connection" role="status">正在连接实时事件…</div>
<section class="job-summary-grid" id="job-summary"></section>
<section class="content-grid wide-main">
  <div class="stack">
    <section class="panel"><div class="panel-heading"><div><h2>生产阶段</h2><p>按 21 个受控阶段执行；跳过表示输入哈希未变化。</p></div><span id="stage-count" class="badge neutral">加载中</span></div><ol class="stage-list" id="stage-list"></ol></section>
    <section class="panel" id="job-error-panel" hidden><h2>失败信息</h2><dl class="detail-list" id="job-error"></dl><div class="button-row"><button class="button primary" id="retry-job">从失败阶段重试</button><button class="button secondary" id="force-retry-job">强制重跑</button></div></section>
  </div>
  <aside class="stack">
    <section class="panel"><h2>最近事件</h2><ol class="event-list" id="event-list"></ol><button class="button ghost full" id="load-older-events">加载全部事件</button></section>
    <section class="panel"><h2>固定模型路由</h2><dl class="detail-list" id="job-routes"></dl></section>
    <section class="panel"><h2>任务操作</h2><div class="button-stack"><a class="button secondary" id="artifact-link" href="#">查看产物</a><button class="button danger ghost" id="cancel-job">取消任务</button></div></section>
  </aside>
</section>
""",
    )


def _review_heading(kind: str) -> str:
    label = "标题与旁白审核" if kind == "editorial" else "视觉计划审核"
    return f'<section class="page-heading"><a class="back-link" id="review-back" href="#">← 返回任务详情</a><p class="eyebrow">Human approval</p><h1>{label}</h1><p id="review-subtitle">载入当前不可变版本、阻断项和历史记录。</p></section>'


@router.get("/jobs/{job_id}/review/editorial", response_class=HTMLResponse)
def editorial_review_page(job_id: str) -> HTMLResponse:
    return _shell(
        title="标题与旁白审核",
        page="review-editorial",
        job_id=job_id,
        content=_review_heading("editorial") + """
<section class="review-layout">
  <div class="stack">
    <section class="panel"><div class="panel-heading"><div><h2>当前文稿</h2><p id="editorial-version"></p></div><span id="editorial-state" class="badge neutral">加载中</span></div>
      <label>视频标题<input id="editorial-title" maxlength="120"></label>
      <label>旁白<textarea id="editorial-narration" rows="22"></textarea><small id="narration-count"></small></label>
      <label>修改说明<input id="editorial-summary" maxlength="1000" placeholder="说明本次修改目的"></label>
      <div class="sticky-actions"><button class="button primary" id="save-editorial">保存为新版本</button><button class="button success" id="approve-editorial">批准当前版本</button><button class="button danger ghost" id="reject-editorial">驳回</button></div>
    </section>
    <section class="panel"><h2>让 Claude 定向修订</h2><p>该操作固定调用 Azure Anthropic `case-video-claude`，随后由 `gpt-5.5` 独立审阅。</p><label>修订反馈<textarea id="editorial-feedback" rows="4" placeholder="例如：开头更快进入冲突，保留所有有来源的数字。"></textarea></label><button class="button secondary" id="model-editorial">生成新版本</button></section>
  </div>
  <aside class="stack">
    <section class="panel"><h2>验收检查</h2><div id="editorial-blockers"></div><div id="editorial-review-issues"></div></section>
    <section class="panel"><h2>版本历史</h2><div class="history-list" id="editorial-history"></div></section>
    <section class="panel"><h2>版本对比</h2><div class="compare-controls"><select id="diff-from" aria-label="起始版本"></select><select id="diff-to" aria-label="目标版本"></select><button class="button ghost" id="load-editorial-diff">对比</button></div><pre class="diff-view" id="editorial-diff">选择两个版本查看差异。</pre></section>
  </aside>
</section>
""",
    )


@router.get("/jobs/{job_id}/review/visual", response_class=HTMLResponse)
def visual_review_page(job_id: str) -> HTMLResponse:
    return _shell(
        title="视觉计划审核",
        page="review-visual",
        job_id=job_id,
        content=_review_heading("visual") + """
<section class="review-layout">
  <div class="stack">
    <section class="panel"><div class="panel-heading"><div><h2>场景计划</h2><p id="visual-version"></p></div><span id="visual-state" class="badge neutral">加载中</span></div><label>场景筛选<select id="scene-filter"><option value="all">全部</option><option value="blocker">存在 blocker</option><option value="warning">存在 warning</option><option value="modified">当前版本有修改</option></select></label><div class="scene-grid" id="scene-grid"></div></section>
    <section class="panel" id="scene-editor" hidden><h2>编辑所选场景</h2><p>unit 锚点和文件引用只读；可修改布局、标题、章节标签、关键词与画面意图。</p><p id="scene-mode-note" class="inline-alert info" role="status"></p><div class="form-grid"><label>布局<select id="scene-layout"><option value="director-canvas">director-canvas</option><option value="breaking-news">breaking-news</option><option value="hook-alert">hook-alert</option><option value="subject-reveal">subject-reveal</option><option value="reveal-card">reveal-card</option><option value="split-data">split-data</option><option value="insight-split">insight-split</option><option value="map-focus">map-focus</option><option value="focus-ring">focus-ring</option><option value="local-playbook">local-playbook</option><option value="resource-map">resource-map</option><option value="balance-beam">balance-beam</option><option value="tension-line">tension-line</option><option value="question-storm">question-storm</option><option value="question-cards">question-cards</option><option value="timeline-roadshow">timeline-roadshow</option><option value="milestone-rail">milestone-rail</option><option value="decision-board">decision-board</option><option value="option-board">option-board</option><option value="closing-quote">closing-quote</option><option value="closing-idea">closing-idea</option><option value="performance-ladder">performance-ladder</option><option value="decision-bottleneck">decision-bottleneck</option><option value="authority-matrix">authority-matrix</option><option value="cover">cover（旧版）</option><option value="statement">statement（旧版）</option><option value="split">split（旧版）</option><option value="timeline">timeline（旧版）</option><option value="comparison">comparison（旧版）</option><option value="summary">summary（旧版）</option></select></label><label>章节标签<input id="scene-kicker"></label><label class="span-2"><span id="scene-headline-label">场景标题</span><input id="scene-headline" aria-describedby="scene-headline-help"><small id="scene-headline-help"></small></label><label class="span-2">关键词（逗号分隔）<input id="scene-keywords"></label><label class="span-2">画面意图<span aria-hidden="true"> *</span><textarea id="scene-intent" rows="4" required></textarea></label></div><label>修改说明<input id="visual-summary" maxlength="1000" placeholder="说明本次视觉修改"></label><button class="button primary" id="save-visual">保存为新版本</button></section>
    <section class="panel"><h2>让 Claude 定向修订</h2><p>固定通过 Azure Anthropic Messages API 调用 `case-video-claude`，只修订视觉计划。</p><label>反馈<textarea id="visual-feedback" rows="4" placeholder="说明要修复的场景、信息层级或画面节奏。"></textarea></label><button class="button secondary" id="model-visual">生成修订版本</button></section>
  </div>
  <aside class="stack"><section class="panel"><h2>Readiness</h2><div id="visual-readiness"></div><div class="sticky-actions vertical"><button class="button success" id="approve-visual">批准并进入付费生图</button><button class="button danger ghost" id="reject-visual">驳回</button></div></section><section class="panel"><h2>版本历史</h2><div class="history-list" id="visual-history"></div></section></aside>
</section>
""",
    )


@router.get("/jobs/{job_id}/artifacts", response_class=HTMLResponse)
def artifacts_page(job_id: str) -> HTMLResponse:
    return _shell(
        title="产物中心",
        page="artifacts",
        job_id=job_id,
        content="""
<section class="page-heading split-heading"><div><a class="back-link" id="artifacts-back" href="#">← 返回任务详情</a><p class="eyebrow">Deliverables</p><h1>产物中心</h1><p>只有真实渲染且通过 QA 的视频会标记为“正式成片”。</p></div><span id="delivery-state" class="badge neutral">检查中</span></section>
<section class="artifact-groups" id="artifact-groups"></section>
<dialog id="preview-dialog" class="dialog preview-dialog"><form method="dialog"><div class="panel-heading"><h2 id="preview-title">产物预览</h2><button value="close" class="icon-button" aria-label="关闭预览">×</button></div><div id="preview-content"></div></form></dialog>
""",
    )


@router.get("/admin/health", response_class=HTMLResponse)
def health_page() -> HTMLResponse:
    return _shell(
        title="系统状态",
        page="health",
        content=_admin_nav("health") + """
<section class="page-heading"><p class="eyebrow">Operations</p><h1>系统状态</h1><p>检查 API、存储、队列和固定模型路由是否可用于生产。</p></section>
<section class="metric-grid" id="health-summary"></section><section class="panel"><div class="panel-heading"><h2>Readiness checks</h2><button class="button secondary" id="refresh-health">重新检查</button></div><dl class="detail-list" id="health-checks"></dl></section>
""",
    )


@router.get("/admin/operations", response_class=HTMLResponse)
def operations_page() -> HTMLResponse:
    return _shell(
        title="运维看板",
        page="admin-operations",
        content=_admin_nav("operations") + """
<section class="page-heading split-heading"><div><p class="eyebrow">Tenant operations</p><h1>运维看板</h1><p>查看当前工作区的任务、队列、worker、死信和模型路由健康度。</p></div><button class="button secondary" id="refresh-operations">刷新快照</button></section>
<section class="metric-grid" id="operations-summary" aria-label="运维概览"></section>
<section class="dashboard-grid">
  <section class="panel"><div class="panel-heading"><div><h2>队列压力</h2><p>关注最旧等待时间和死信数，不以短时队列长度单独判定故障。</p></div></div><div class="table-wrap"><table class="data-table"><thead><tr><th>队列</th><th>排队</th><th>运行</th><th>死信</th><th>最旧等待</th></tr></thead><tbody id="operations-queues"></tbody></table></div><div class="empty-state compact-empty" id="operations-queues-empty" hidden>暂无队列记录。</div></section>
  <section class="panel"><h2>固定模型路由</h2><p class="section-help">Claude 路由必须是 Azure Anthropic <code>/v1/messages</code>；页面不允许替换模型。</p><div id="operations-routes"></div></section>
</section>
<section class="panel"><div class="panel-heading"><div><h2>Worker 租约</h2><p>过期租约由 reaper 回收，重试依赖 fencing 和幂等提交。</p></div><span class="badge neutral" id="operations-generated-at"></span></div><div class="table-wrap"><table class="data-table"><thead><tr><th>Worker</th><th>活跃租约</th><th>过期</th><th>取消请求</th><th>最后心跳</th><th>租约到期</th></tr></thead><tbody id="operations-workers"></tbody></table></div><div class="empty-state compact-empty" id="operations-workers-empty" hidden>当前没有 worker 租约。</div></section>
<section class="panel"><div class="panel-heading"><div><h2>最近死信</h2><p>保留任务、阶段、尝试次数和可重试性，便于精确恢复。</p></div></div><div class="table-wrap"><table class="data-table"><thead><tr><th>任务</th><th>阶段</th><th>尝试</th><th>错误</th><th>可重试</th></tr></thead><tbody id="operations-dead-letters"></tbody></table></div><div class="empty-state compact-empty" id="operations-dead-letters-empty" hidden>暂无死信。</div></section>
""",
    )


@router.get("/admin/members", response_class=HTMLResponse)
def members_page() -> HTMLResponse:
    return _shell(
        title="成员与角色",
        page="admin-members",
        content=_admin_nav("members") + """
<section class="page-heading"><p class="eyebrow">Identity &amp; access</p><h1>成员与角色</h1><p>成员权限以当前工作区为边界。修改角色或停用成员前需要近期重新认证。</p></section>
<section class="role-grid" aria-label="角色能力摘要">
  <article><strong>Viewer</strong><span>查看任务和产物</span></article><article><strong>Editor</strong><span>创建、编辑、取消和重试</span></article><article><strong>Producer</strong><span>审批付费阶段并查看成本</span></article><article><strong>Admin</strong><span>成员、治理、审计和保留策略</span></article>
</section>
<section class="content-grid">
  <section class="panel"><div class="panel-heading"><div><h2>工作区成员</h2><p id="members-count">正在载入…</p></div><button class="button secondary" id="refresh-members">刷新</button></div><div class="table-wrap"><table class="data-table"><thead><tr><th>成员</th><th>Subject</th><th>角色</th><th>状态</th><th><span class="sr-only">操作</span></th></tr></thead><tbody id="members-body"></tbody></table></div><div class="empty-state compact-empty" id="members-empty" hidden>暂无成员。</div></section>
  <aside class="panel"><h2 id="member-form-title">添加成员</h2><form id="member-form"><input type="hidden" name="user_id"><label>用户 ID<input name="new_user_id" maxlength="120" required placeholder="usr_name"></label><label>OIDC subject<input name="subject" maxlength="255" required></label><label>显示名<input name="display_name" maxlength="200"></label><label>邮箱<input name="email" type="email" maxlength="320"></label><label>角色<select name="role"><option value="viewer">Viewer</option><option value="editor">Editor</option><option value="producer">Producer</option><option value="admin">Admin</option></select></label><label class="check-row"><input name="disabled" type="checkbox"> 停用该成员</label><div class="inline-alert danger" id="member-form-error" hidden role="alert"></div><div class="button-row"><button class="button primary" type="submit">保存成员</button><button class="button ghost" type="button" id="member-form-reset">清空</button></div></form></aside>
</section>
""",
    )


@router.get("/admin/governance", response_class=HTMLResponse)
def governance_page() -> HTMLResponse:
    return _shell(
        title="额度与治理",
        page="admin-governance",
        content=_admin_nav("governance") + """
<section class="page-heading"><p class="eyebrow">Governance</p><h1>额度、成本与租户策略</h1><p>查看当前消耗，并配置并发、上传、预算和保留边界。保存会覆盖后续新任务的默认行为。</p></section>
<section class="metric-grid" id="governance-cost-summary"></section>
<section class="panel"><div class="panel-heading"><div><h2>实时额度</h2><p>已占用包含正在上传和生产的保留量。</p></div><button class="button secondary" id="refresh-governance">刷新</button></div><div class="quota-grid" id="quota-summary"></div></section>
<form id="governance-form" class="stack">
  <section class="panel"><h2>容量与成本上限</h2><div class="form-grid"><label>同时活跃任务数<input name="active_jobs" type="number" min="1" step="1"></label><label>未绑定上传文件数<input name="upload_files" type="number" min="1" step="1"></label><label>未绑定上传总量（MB）<input name="upload_megabytes" type="number" min="1" step="1"></label><label>月度成本上限（美元）<input name="monthly_cost_usd" type="number" min="0" step="0.01"></label></div></section>
  <section class="panel"><h2>生产默认值</h2><div class="form-grid"><label>默认审批模式<select name="default_approval_mode"><option value="full">文稿与视觉双审核</option><option value="editorial">仅文稿审核</option><option value="auto">自动生产</option></select></label><label>单任务默认预算（美元）<input name="default_job_budget_usd" type="number" min="0" step="0.01"></label></div></section>
  <section class="panel"><h2>保留期</h2><p class="section-help">达到保留期的任务会先隐藏，依然可在恢复窗口内找回。legal hold 和固定任务不会被自动清理。</p><div class="form-grid"><label>已成功任务保留（天）<input name="succeeded_days" type="number" min="0" step="1"></label><label>失败任务保留（天）<input name="failed_days" type="number" min="0" step="1"></label><label>删除后恢复窗口（天）<input name="recovery_days" type="number" min="0" step="1"></label></div></section>
  <section class="panel danger-zone"><h2>保存治理配置</h2><p>此操作会影响当前工作区的新任务、上传和自动保留流程，需要近期重新认证。</p><label class="check-row"><input type="checkbox" name="confirm_governance" required> 我已确认影响对象是当前工作区，并已检查额度与保留期数值。</label><div class="inline-alert danger" id="governance-error" hidden role="alert"></div><button class="button danger" type="submit">保存工作区治理配置</button></section>
</form>
""",
    )


@router.get("/admin/audit", response_class=HTMLResponse)
def audit_page() -> HTMLResponse:
    return _shell(
        title="审计日志",
        page="admin-audit",
        content=_admin_nav("audit") + """
<section class="page-heading"><p class="eyebrow">Audit trail</p><h1>审计日志</h1><p>按操作人、任务、动作、结果和时间范围定位管理变更。筛选条件会保留在 URL 中。</p></section>
<section class="panel"><form id="audit-filters" class="filter-grid audit-filters" role="search"><label>操作人<input name="actor_id" placeholder="user ID"></label><label>任务 / 资源<input name="job_id" placeholder="job ID"></label><label>动作<input name="action" placeholder="governance.update"></label><label>结果<select name="result"><option value="">全部</option><option value="succeeded">成功</option><option value="failed">失败</option><option value="denied">拒绝</option></select></label><label>开始时间<input name="occurred_from" type="datetime-local"></label><label>结束时间<input name="occurred_to" type="datetime-local"></label><div class="filter-actions"><button class="button primary" type="submit">筛选</button><button class="button ghost" type="button" id="clear-audit-filters">清除</button></div></form><div class="table-wrap"><table class="data-table"><thead><tr><th>时间</th><th>操作人</th><th>动作</th><th>资源</th><th>结果</th><th>请求 ID</th></tr></thead><tbody id="audit-body"></tbody></table></div><div class="empty-state compact-empty" id="audit-empty" hidden>没有匹配的审计记录。</div><div class="pagination"><button class="button ghost" id="audit-previous" type="button">上一页</button><span id="audit-page-label">第 1 页</span><button class="button ghost" id="audit-next" type="button">下一页</button></div></section>
""",
    )


@router.get("/admin/retention", response_class=HTMLResponse)
def retention_page() -> HTMLResponse:
    return _shell(
        title="保留与删除",
        page="admin-retention",
        content=_admin_nav("retention") + """
<section class="page-heading split-heading"><div><p class="eyebrow">Lifecycle</p><h1>保留、恢复与删除</h1><p>明确区分活跃任务、已隐藏任务、恢复窗口和永久删除候选。固定或 legal hold 会阻止自动清理。</p></div><button class="button danger ghost" id="run-retention">运行保留期评估</button></section>
<section class="panel"><form id="retention-filters" class="filter-grid retention-filters" role="search"><label>搜索<input name="query" type="search" placeholder="案例名或任务 ID"></label><label>生命周期<select name="state"><option value="deleted">已隐藏 / 待清理</option><option value="active">活跃</option><option value="all">全部</option></select></label><div class="filter-actions"><button class="button primary" type="submit">筛选</button><button class="button ghost" type="button" id="clear-retention-filters">清除</button></div></form><div class="table-wrap"><table class="data-table"><thead><tr><th>任务</th><th>生产状态</th><th>生命周期</th><th>保护</th><th>清理时间</th><th>操作</th></tr></thead><tbody id="retention-body"></tbody></table></div><div class="empty-state compact-empty" id="retention-empty" hidden>没有匹配的任务。</div><div class="pagination"><button class="button ghost" id="retention-previous" type="button">上一页</button><span id="retention-page-label">第 1 页</span><button class="button ghost" id="retention-next" type="button">下一页</button></div></section>
<section class="inline-alert" id="retention-result" hidden role="status"></section>
""",
    )
