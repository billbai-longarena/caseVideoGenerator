(() => {
  "use strict";

  const page = document.body.dataset.page || "";
  const jobId = document.body.dataset.jobId || "";
  const byId = (id) => document.getElementById(id);
  const terminalStatuses = new Set(["succeeded", "failed", "canceled"]);
  const unsafeMethods = new Set(["POST", "PUT", "PATCH", "DELETE"]);
  const appState = {
    distributed: false,
    authConfig: null,
    session: null,
    csrfToken: null,
    csrfHeader: "X-CSRF-Token",
    eventSources: new Set(),
  };

  class ApiError extends Error {
    constructor(message, status, payload) {
      super(message);
      this.name = "ApiError";
      this.status = status;
      this.payload = payload || {};
      this.code = this.payload.code || "request_failed";
    }
  }

  function element(tag, attributes = {}, children = []) {
    const item = document.createElement(tag);
    Object.entries(attributes).forEach(([key, value]) => {
      if (value === undefined || value === null || value === false) return;
      if (key === "className") item.className = String(value);
      else if (key === "text") item.textContent = String(value);
      else if (key === "dataset") Object.entries(value).forEach(([name, content]) => {
        item.dataset[name] = String(content);
      });
      else if (key.startsWith("on") && typeof value === "function") {
        item.addEventListener(key.slice(2).toLowerCase(), value);
      } else if (value === true) item.setAttribute(key, "");
      else item.setAttribute(key, String(value));
    });
    const values = Array.isArray(children) ? children : [children];
    values.forEach((child) => {
      if (child === undefined || child === null || child === false) return;
      item.append(child instanceof Node ? child : document.createTextNode(String(child)));
    });
    return item;
  }

  function clear(target) {
    if (target) target.replaceChildren();
  }

  function setText(id, value) {
    const target = byId(id);
    if (target) target.textContent = value === undefined || value === null ? "—" : String(value);
  }

  async function api(path, options = {}) {
    const headers = new Headers(options.headers || {});
    const method = String(options.method || "GET").toUpperCase();
    headers.set("Accept", "application/json");
    if (unsafeMethods.has(method) && appState.csrfToken && !headers.has(appState.csrfHeader)) {
      headers.set(appState.csrfHeader, appState.csrfToken);
    }
    let body = options.body;
    if (body && !(body instanceof FormData) && !(body instanceof Blob) && typeof body !== "string") {
      headers.set("Content-Type", "application/json");
      body = JSON.stringify(body);
    }
    const response = await fetch(path, {
      ...options,
      headers,
      body,
      credentials: "same-origin",
    });
    let data = null;
    if (response.status !== 204) {
      const contentType = response.headers.get("content-type") || "";
      if (contentType.includes("application/json")) data = await response.json();
      else data = await response.text();
    }
    if (!response.ok) {
      const payload = data && typeof data === "object" ? data : {message: String(data || response.statusText)};
      if (response.status === 401 && payload.reauthentication_required && payload.action_url) {
        window.location.assign(payload.action_url);
      }
      throw new ApiError(payload.message || payload.detail || "请求失败", response.status, payload);
    }
    return {data, response};
  }

  function errorMessage(error) {
    if (error instanceof ApiError) {
      const requestId = error.payload.request_id ? `（请求 ${error.payload.request_id}）` : "";
      return `${error.message}${requestId}`;
    }
    return error && error.message ? error.message : "发生未知错误";
  }

  function toast(message, tone = "info") {
    const region = byId("toast-region");
    if (!region) return;
    const item = element("div", {className: `toast ${tone === "error" ? "error" : ""}`, role: "status"}, message);
    region.append(item);
    window.setTimeout(() => item.remove(), 5200);
  }

  function announce(message) {
    const region = byId("live-region");
    if (!region) return;
    region.textContent = "";
    window.setTimeout(() => { region.textContent = message; }, 20);
  }

  function setBusy(button, busy, busyText = "处理中…") {
    if (!button) return;
    if (busy) {
      button.dataset.previousText = button.textContent || "";
      button.textContent = busyText;
      button.disabled = true;
      button.setAttribute("aria-busy", "true");
    } else {
      button.textContent = button.dataset.previousText || button.textContent;
      button.disabled = false;
      button.removeAttribute("aria-busy");
    }
  }

  function formatDate(value) {
    if (!value) return "—";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return new Intl.DateTimeFormat("zh-CN", {
      year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", second: "2-digit",
    }).format(date);
  }

  function formatBytes(value) {
    const bytes = Number(value || 0);
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
    if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
    return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
  }

  function formatDuration(seconds) {
    if (seconds === undefined || seconds === null || Number.isNaN(Number(seconds))) return "待生成 timeline";
    const total = Math.max(0, Math.round(Number(seconds)));
    const minutes = Math.floor(total / 60);
    const rest = total % 60;
    return minutes ? `${minutes} 分 ${rest} 秒` : `${rest} 秒`;
  }

  function formatAge(seconds) {
    if (seconds === undefined || seconds === null) return "—";
    const total = Math.max(0, Number(seconds) || 0);
    if (total < 60) return `${Math.round(total)} 秒`;
    if (total < 3600) return `${Math.round(total / 60)} 分钟`;
    return `${(total / 3600).toFixed(1)} 小时`;
  }

  function formatMoneyMicros(value) {
    if (value === undefined || value === null) return "未设置";
    return new Intl.NumberFormat("zh-CN", {
      style: "currency",
      currency: "USD",
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(Number(value) / 1_000_000);
  }

  function hasPermission(permission) {
    return Boolean(appState.session && (appState.session.permissions || []).includes(permission));
  }

  function tenantScopedKey(name) {
    const tenant = appState.session && appState.session.tenant_id ? appState.session.tenant_id : "local";
    return `case-video:${tenant}:${name}`;
  }

  function closeEventSources() {
    appState.eventSources.forEach((source) => source.close());
    appState.eventSources.clear();
  }

  function safeReturnTo() {
    const value = new URLSearchParams(window.location.search).get("return_to") || "/jobs";
    return value.startsWith("/") && !value.startsWith("//") && !value.includes("\\") ? value : "/jobs";
  }

  async function loadAuthContext() {
    try {
      const response = await fetch("/auth/config", {
        headers: {Accept: "application/json"},
        credentials: "same-origin",
      });
      if (response.status === 404) return;
      if (!response.ok) throw new Error(`无法读取登录配置（HTTP ${response.status}）`);
      appState.authConfig = await response.json();
      appState.distributed = true;
      appState.csrfHeader = appState.authConfig.csrf_header || appState.csrfHeader;
    } catch (error) {
      if (page === "login") throw error;
      return;
    }

    if (page === "login") return;
    try {
      const {data} = await api("/v1/session");
      appState.session = data;
      const csrf = await api("/v1/session/csrf", {method: "POST"});
      appState.csrfToken = csrf.data.csrf_token;
      renderSessionTools();
      applyPermissionVisibility();
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        const returnTo = `${window.location.pathname}${window.location.search}`;
        window.location.replace(`/login?return_to=${encodeURIComponent(returnTo)}`);
        return;
      }
      throw error;
    }
  }

  function renderSessionTools() {
    const session = appState.session;
    const tools = byId("session-tools");
    if (!session || !tools) return;
    tools.hidden = false;
    setText("session-user", session.display_name || session.email || session.actor_id);
    setText("session-role", `${session.tenant_name || session.tenant_id} · ${String(session.role || "").toUpperCase()}`);
    const switcher = byId("tenant-switcher");
    clear(switcher);
    (session.memberships || []).forEach((membership) => {
      switcher.append(element("option", {
        value: membership.tenant_id,
        text: membership.tenant_name || membership.name || membership.tenant_id,
        selected: membership.tenant_id === session.tenant_id,
      }));
    });
    switcher.disabled = (session.memberships || []).length < 2;
    switcher.addEventListener("change", async () => {
      const tenantId = switcher.value;
      if (!tenantId || tenantId === session.tenant_id) return;
      closeEventSources();
      switcher.disabled = true;
      try {
        await api("/auth/tenant", {method: "POST", body: {tenant_id: tenantId}});
        window.location.reload();
      } catch (error) {
        toast(errorMessage(error), "error");
        switcher.value = session.tenant_id;
        switcher.disabled = (session.memberships || []).length < 2;
      }
    });
    byId("logout-button")?.addEventListener("click", async () => {
      closeEventSources();
      try {
        await api(appState.authConfig.logout_url || "/auth/logout", {method: "POST"});
      } finally {
        window.location.assign("/login");
      }
    });
  }

  function applyPermissionVisibility() {
    if (!appState.distributed || !appState.session) return;
    const canAdmin = [
      "governance.read", "worker.execute", "audit.read", "retention.manage",
    ].some(hasPermission);
    const adminLink = byId("admin-nav-link");
    if (adminLink) adminLink.hidden = !canAdmin;
    document.querySelectorAll('a[href="/jobs/new"]').forEach((link) => {
      link.hidden = !hasPermission("jobs.create");
    });
    const adminPermissions = new Map([
      ["/admin/operations", "worker.execute"],
      ["/admin/members", "governance.read"],
      ["/admin/governance", "governance.read"],
      ["/admin/audit", "audit.read"],
      ["/admin/retention", "retention.manage"],
    ]);
    document.querySelectorAll(".admin-nav a").forEach((link) => {
      const permission = adminPermissions.get(link.getAttribute("href"));
      if (permission) link.hidden = !hasPermission(permission);
    });
  }

  async function initLogin() {
    const description = byId("login-description");
    const error = byId("login-error");
    if (!appState.distributed || !appState.authConfig) {
      description.textContent = "当前服务未启用服务器登录，正在返回任务中心。";
      window.location.replace(safeReturnTo());
      return;
    }
    const returnTo = safeReturnTo();
    if (appState.authConfig.oidc_enabled) {
      description.textContent = "使用企业身份提供方完成登录。访问令牌不会暴露给浏览器脚本。";
      const link = byId("oidc-login");
      link.href = `${appState.authConfig.login_url || "/auth/login"}?return_to=${encodeURIComponent(returnTo)}`;
      link.hidden = false;
      return;
    }
    description.textContent = "输入服务器管理员提供的访问令牌。令牌仅用于建立 HttpOnly 会话。";
    const form = byId("static-login-form");
    form.hidden = false;
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const button = form.querySelector('button[type="submit"]');
      setBusy(button, true, "登录中…");
      error.hidden = true;
      try {
        await api("/auth/static", {
          method: "POST",
          body: {
            token: form.elements.namedItem("token").value,
            tenant_id: form.elements.namedItem("tenant_id").value.trim() || null,
          },
        });
        window.location.replace(returnTo);
      } catch (loginError) {
        error.textContent = errorMessage(loginError);
        error.hidden = false;
      } finally {
        setBusy(button, false);
      }
    });
  }

  const statusLabels = {
    created: "已创建", queued: "排队中", running: "处理中", waiting_approval: "待人工审核",
    succeeded: "已完成", failed: "失败", canceling: "正在取消", canceled: "已取消",
    pending: "未开始", skipped: "已跳过",
  };

  function statusTone(status) {
    if (["succeeded"].includes(status)) return "success";
    if (["failed", "canceled"].includes(status)) return "danger";
    if (["waiting_approval", "canceling"].includes(status)) return "warning";
    if (["running", "queued", "created"].includes(status)) return "info";
    return "neutral";
  }

  function badge(label, tone = "neutral") {
    return element("span", {className: `badge ${tone}`}, label);
  }

  function detailList(target, entries) {
    clear(target);
    entries.forEach(([label, value]) => {
      target.append(element("dt", {text: label}), element("dd", {}, value instanceof Node ? value : String(value ?? "—")));
    });
  }

  function metric(label, value, help = "") {
    const children = [element("span", {text: label}), element("strong", {text: value})];
    if (help) children.push(element("small", {text: help}));
    return element("article", {className: "metric-card"}, children);
  }

  function artifactUrl(name) {
    const safeName = String(name).split("/").map((part) => encodeURIComponent(part)).join("/");
    return `/v1/jobs/${encodeURIComponent(jobId)}/artifacts/${safeName}`;
  }

  function randomId() {
    if (window.crypto && typeof window.crypto.randomUUID === "function") return window.crypto.randomUUID();
    return `req-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }

  function sleep(ms) {
    return new Promise((resolve) => window.setTimeout(resolve, ms));
  }

  function confirmAction({title, message, confirmLabel = "确认", danger = true}) {
    const dialog = byId("confirm-dialog");
    if (!dialog || typeof dialog.showModal !== "function") return Promise.resolve(window.confirm(message));
    const trigger = document.activeElement;
    setText("confirm-title", title);
    setText("confirm-message", message);
    const submit = byId("confirm-submit");
    submit.textContent = confirmLabel;
    submit.className = `button ${danger ? "danger" : "primary"}`;
    dialog.returnValue = "";
    const focusableSelector = 'button,[href],input,select,textarea,[tabindex]:not([tabindex="-1"])';
    const trapFocus = (event) => {
      if (event.key !== "Tab") return;
      const focusable = [...dialog.querySelectorAll(focusableSelector)]
        .filter((item) => !item.disabled && item.offsetParent !== null);
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    dialog.showModal();
    dialog.addEventListener("keydown", trapFocus);
    submit.focus();
    return new Promise((resolve) => {
      const closed = () => {
        dialog.removeEventListener("close", closed);
        dialog.removeEventListener("keydown", trapFocus);
        if (trigger && typeof trigger.focus === "function") trigger.focus();
        resolve(dialog.returnValue === "confirm");
      };
      dialog.addEventListener("close", closed);
    });
  }

  async function copyText(value) {
    try {
      await navigator.clipboard.writeText(value);
      toast("已复制到剪贴板");
    } catch (_error) {
      toast("复制失败，请手动选择文本", "error");
    }
  }

  function renderRoutes(target, routes) {
    clear(target);
    const list = element("dl", {className: "detail-list"});
    const names = {narration: "标题与旁白", remotion: "Remotion 计划", general: "其他推理"};
    Object.entries(routes || {}).forEach(([name, route]) => {
      const model = route.model || "未配置";
      const provider = route.provider || "—";
      const transport = route.transport || "—";
      list.append(
        element("dt", {text: names[name] || name}),
        element("dd", {}, [
          element("strong", {className: "mono", text: model}),
          document.createTextNode(` · ${provider} · ${transport}`),
        ]),
      );
    });
    target.append(list);
  }

  function normalizeStageRuns(stageRuns) {
    if (!Array.isArray(stageRuns)) return stageRuns || {};
    const grouped = new Map();
    stageRuns.forEach((run) => {
      const existing = grouped.get(run.stage);
      if (!existing || Number(run.attempt || 0) >= Number(existing.attempt || 0)) {
        grouped.set(run.stage, {...run, run_count: 0});
      }
    });
    stageRuns.forEach((run) => {
      const current = grouped.get(run.stage);
      if (current) current.run_count += 1;
    });
    return Object.fromEntries(grouped);
  }

  function normalizeJobPayload(payload) {
    const job = payload && payload.job ? {...payload.job} : {...(payload || {})};
    const stageRuns = payload && payload.stage_runs !== undefined ? payload.stage_runs : job.stage_runs;
    job.stage_runs = normalizeStageRuns(stageRuns);
    return job;
  }

  async function initJobs() {
    const form = byId("job-filters");
    const params = new URLSearchParams(window.location.search);
    for (const [name, value] of params.entries()) {
      const field = form.elements.namedItem(name);
      if (field) field.value = value;
    }

    async function load() {
      byId("jobs-loading").hidden = false;
      byId("jobs-table-wrap").hidden = true;
      byId("jobs-empty").hidden = true;
      const query = new URLSearchParams();
      ["q", "status", "needs_action", "approval_mode", "created_from", "created_to"].forEach((name) => {
        const value = form.elements.namedItem(name).value.trim();
        if (value) query.set(name, value);
      });
      query.set("limit", "200");
      const visibleQuery = new URLSearchParams(query);
      visibleQuery.delete("limit");
      history.replaceState(null, "", `${window.location.pathname}${visibleQuery.size ? `?${visibleQuery}` : ""}`);
      try {
        const {data} = await api(`/v1/jobs?${query}`);
        const jobs = data.items || data.jobs || [];
        renderJobMetrics(jobs, data.total || 0);
        renderJobs(jobs);
      } catch (error) {
        toast(errorMessage(error), "error");
        renderJobs([]);
      } finally {
        byId("jobs-loading").hidden = true;
      }
    }

    function renderJobMetrics(jobs, total) {
      const target = byId("job-metrics");
      clear(target);
      target.append(
        metric("当前任务", total, "符合当前筛选"),
        metric("待人工处理", jobs.filter((job) => job.needs_action).length, "需审核或处理失败"),
        metric("生产中", jobs.filter((job) => ["queued", "running", "canceling"].includes(job.status)).length),
        metric("已完成", jobs.filter((job) => job.status === "succeeded").length),
      );
    }

    function renderJobs(jobs) {
      const body = byId("jobs-body");
      clear(body);
      byId("jobs-table-wrap").hidden = jobs.length === 0;
      byId("jobs-empty").hidden = jobs.length !== 0;
      jobs.forEach((job) => {
        const progress = `${Math.round(Math.max(0, Math.min(1, Number(job.overall_progress || 0))) * 100)}%`;
        const action = element("a", {className: "button ghost", href: job.job_url || `/jobs/${encodeURIComponent(job.job_id)}`}, job.needs_action ? "立即处理" : "查看");
        const status = badge(job.display_status || statusLabels[job.status] || job.status, statusTone(job.status));
        if (job.needs_action) status.append(document.createTextNode(" · 需处理"));
        body.append(element("tr", {}, [
          element("td", {className: "job-cell"}, [element("strong", {text: job.project_name}), element("small", {className: "mono", text: job.job_id})]),
          element("td", {}, status),
          element("td", {text: job.stage || "—"}),
          element("td", {text: progress}),
          element("td", {text: formatDate(job.updated_at)}),
          element("td", {}, action),
        ]));
      });
    }

    form.addEventListener("submit", (event) => { event.preventDefault(); load(); });
    byId("clear-filters").addEventListener("click", () => { form.reset(); load(); });
    await load();
  }

  async function initNewJob() {
    const form = byId("create-job-form");
    const draftKey = tenantScopedKey("create-draft-v2");
    const state = {
      step: 1,
      files: [],
      capabilities: null,
      requestId: randomId(),
    };

    try {
      const saved = JSON.parse(localStorage.getItem(draftKey) || "null");
      if (saved && typeof saved === "object") {
        ["project_name", "approval_mode", "duration_min", "duration_max", "budget_usd"].forEach((name) => {
          const field = form.elements.namedItem(name);
          if (field && saved[name] !== undefined) field.value = saved[name];
        });
        if (saved.requestId) state.requestId = saved.requestId;
      }
    } catch (_error) {
      localStorage.removeItem(draftKey);
    }

    function saveDraft() {
      const saved = {requestId: state.requestId};
      ["project_name", "approval_mode", "duration_min", "duration_max", "budget_usd"].forEach((name) => {
        saved[name] = form.elements.namedItem(name).value;
      });
      localStorage.setItem(draftKey, JSON.stringify(saved));
    }

    form.addEventListener("input", saveDraft);

    try {
      const {data} = await api("/v1/capabilities");
      state.capabilities = data;
      setText("upload-limits", `最多 ${data.upload.max_files} 个文件；单任务总量不超过 ${formatBytes(data.upload.max_file_bytes)}。`);
      renderRoutes(byId("route-summary"), data.model_routes);
    } catch (error) {
      setText("upload-limits", "无法读取服务器限制，请稍后重试。");
      toast(errorMessage(error), "error");
    }

    function setUploadError(message) {
      const target = byId("upload-error");
      target.textContent = message || "";
      target.hidden = !message;
    }

    function validateFile(file) {
      const limits = state.capabilities && state.capabilities.upload;
      const suffix = `.${file.name.split(".").pop().toLowerCase()}`;
      if (!file.size) return "文件为空";
      if (limits && !limits.allowed_extensions.includes(suffix)) return `不支持 ${suffix} 格式`;
      if (limits && file.size > limits.max_file_bytes) return `文件超过 ${formatBytes(limits.max_file_bytes)} 限制`;
      return "";
    }

    function addFiles(fileList) {
      const limits = state.capabilities && state.capabilities.upload;
      const candidates = Array.from(fileList || []);
      if (limits && state.files.length + candidates.length > limits.max_files) {
        setUploadError(`每个任务最多选择 ${limits.max_files} 个文件。`);
        return;
      }
      candidates.forEach((file) => {
        const key = `${file.name}:${file.size}:${file.lastModified}`;
        if (state.files.some((item) => item.key === key)) return;
        state.files.push({key, file, progress: 0, status: "pending", error: validateFile(file), uploadId: null});
      });
      const total = state.files.reduce((sum, item) => sum + item.file.size, 0);
      if (limits && total > limits.max_file_bytes) setUploadError(`所选文件合计 ${formatBytes(total)}，超过 ${formatBytes(limits.max_file_bytes)}。`);
      else setUploadError("");
      renderUploads();
    }

    async function removeFile(record) {
      state.files = state.files.filter((item) => item !== record);
      renderUploads();
      if (record.uploadId) {
        try { await api(`/v1/uploads/${encodeURIComponent(record.uploadId)}`, {method: "DELETE"}); }
        catch (_error) { /* Expired uploads are harmless here. */ }
      }
    }

    function renderUploads() {
      const target = byId("upload-list");
      clear(target);
      state.files.forEach((record) => {
        const status = record.error || ({pending: "等待上传", uploading: `上传 ${record.progress}%`, complete: "上传完成", failed: "上传失败"}[record.status] || record.status);
        const progress = element("div", {className: "progress-track", role: "progressbar", "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": record.progress},
          element("div", {className: "progress-bar"}));
        progress.firstElementChild.style.setProperty("--progress", `${record.progress}%`);
        target.append(element("li", {className: "upload-item"}, [
          element("div", {}, [element("strong", {text: record.file.name}), element("small", {text: `${formatBytes(record.file.size)} · ${status}`})]),
          progress,
          element("button", {className: "button ghost", type: "button", onClick: () => removeFile(record), disabled: record.status === "uploading"}, "移除"),
        ]));
      });
    }

    const input = byId("source-files");
    input.addEventListener("change", () => { addFiles(input.files); input.value = ""; });
    const dropZone = byId("drop-zone");
    ["dragenter", "dragover"].forEach((name) => dropZone.addEventListener(name, (event) => {
      event.preventDefault();
      dropZone.classList.add("dragging");
    }));
    ["dragleave", "drop"].forEach((name) => dropZone.addEventListener(name, (event) => {
      event.preventDefault();
      dropZone.classList.remove("dragging");
    }));
    dropZone.addEventListener("drop", (event) => addFiles(event.dataTransfer.files));

    function markInvalid(field, invalid) {
      if (!field) return;
      field.setAttribute("aria-invalid", invalid ? "true" : "false");
    }

    function validateStep(step) {
      if (step === 1) {
        const field = form.elements.namedItem("project_name");
        const value = field.value.trim();
        const invalid = !value || /[\\/\0]/.test(value);
        markInvalid(field, invalid);
        if (invalid) {
          toast("案例名称不能为空，也不能包含路径符号。", "error");
          field.focus();
          return false;
        }
      }
      if (step === 2) {
        const limits = state.capabilities && state.capabilities.upload;
        const total = state.files.reduce((sum, item) => sum + item.file.size, 0);
        if (!state.files.length || state.files.some((item) => item.error) || (limits && total > limits.max_file_bytes)) {
          setUploadError(!state.files.length ? "请至少选择一个材料文件。" : "请先移除不符合要求的文件。");
          byId("source-files").focus();
          return false;
        }
      }
      if (step === 3) {
        const minField = form.elements.namedItem("duration_min");
        const maxField = form.elements.namedItem("duration_max");
        const min = Number(minField.value);
        const max = Number(maxField.value);
        const invalid = !Number.isFinite(min) || !Number.isFinite(max) || min < 60 || max > 1800 || min > max;
        markInvalid(minField, invalid);
        markInvalid(maxField, invalid);
        if (invalid) {
          toast("时长范围必须在 60–1800 秒内，且最短时长不能超过最长时长。", "error");
          minField.focus();
          return false;
        }
      }
      return true;
    }

    function renderCreateReview() {
      const target = byId("create-review");
      const routes = state.capabilities ? state.capabilities.model_routes : {};
      const routeText = Object.values(routes).map((route) => route.model).join(" / ") || "服务器固定路由";
      detailList(target, [
        ["案例名称", form.elements.namedItem("project_name").value.trim()],
        ["材料", `${state.files.length} 个，共 ${formatBytes(state.files.reduce((sum, item) => sum + item.file.size, 0))}`],
        ["审批模式", form.elements.namedItem("approval_mode").selectedOptions[0].textContent],
        ["目标时长", `${form.elements.namedItem("duration_min").value}–${form.elements.namedItem("duration_max").value} 秒`],
        ["固定模型", routeText],
      ]);
    }

    function showStep(step) {
      state.step = Math.max(1, Math.min(4, step));
      document.querySelectorAll(".wizard-step").forEach((section) => {
        section.hidden = Number(section.dataset.step) !== state.step;
      });
      document.querySelectorAll("#create-stepper li").forEach((item, index) => {
        item.removeAttribute("aria-current");
        item.classList.toggle("complete", index + 1 < state.step);
        if (index + 1 === state.step) item.setAttribute("aria-current", "step");
      });
      byId("wizard-back").hidden = state.step === 1;
      byId("wizard-next").hidden = state.step === 4;
      byId("wizard-submit").hidden = state.step !== 4;
      if (state.step === 4) renderCreateReview();
      document.querySelector(`.wizard-step[data-step="${state.step}"] h2`).focus?.();
      announce(`已进入第 ${state.step} 步`);
    }

    byId("wizard-next").addEventListener("click", () => { if (validateStep(state.step)) showStep(state.step + 1); });
    byId("wizard-back").addEventListener("click", () => showStep(state.step - 1));

    function uploadBinary(record, uploadUrl) {
      return new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.open("PUT", uploadUrl);
        xhr.setRequestHeader("Content-Type", record.file.type || "application/octet-stream");
        if (appState.csrfToken) xhr.setRequestHeader(appState.csrfHeader, appState.csrfToken);
        xhr.upload.addEventListener("progress", (event) => {
          if (!event.lengthComputable) return;
          record.progress = Math.round((event.loaded / event.total) * 100);
          record.status = "uploading";
          renderUploads();
        });
        xhr.addEventListener("load", () => {
          if (xhr.status >= 200 && xhr.status < 300) resolve();
          else reject(new Error(`上传失败（HTTP ${xhr.status}）`));
        });
        xhr.addEventListener("error", () => reject(new Error("网络中断，文件未上传完成")));
        xhr.send(record.file);
      });
    }

    async function uploadOne(record) {
      if (record.status === "complete" && record.uploadId) return record.uploadId;
      record.status = "uploading";
      renderUploads();
      try {
        const {data} = await api("/v1/uploads", {
          method: "POST",
          body: {filename: record.file.name, size_bytes: record.file.size, media_type: record.file.type || null},
        });
        record.uploadId = data.upload_id;
        await uploadBinary(record, data.upload_url);
        record.status = "complete";
        record.progress = 100;
        renderUploads();
        return record.uploadId;
      } catch (error) {
        record.status = "failed";
        record.error = errorMessage(error);
        renderUploads();
        throw error;
      }
    }

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (!validateStep(1) || !validateStep(2) || !validateStep(3)) return;
      const confirmation = form.elements.namedItem("confirm_sources");
      if (!confirmation.checked) {
        confirmation.focus();
        setText("create-error", "请先确认材料使用范围。");
        byId("create-error").hidden = false;
        return;
      }
      const submit = byId("wizard-submit");
      setBusy(submit, true, "上传并创建中…");
      byId("create-error").hidden = true;
      try {
        const uploadIds = [];
        for (const record of state.files) uploadIds.push(await uploadOne(record));
        const budget = form.elements.namedItem("budget_usd").value.trim();
        const payload = {
          project_name: form.elements.namedItem("project_name").value.trim(),
          input_mode: "source",
          approval_mode: form.elements.namedItem("approval_mode").value,
          target_duration_seconds: {
            min: Number(form.elements.namedItem("duration_min").value),
            max: Number(form.elements.namedItem("duration_max").value),
          },
          program: "销售不复杂",
          upload_ids: uploadIds,
          client_request_id: state.requestId,
        };
        if (budget) payload.budget_limit_micros = Math.round(Number(budget) * 1_000_000);
        const {data} = await api("/v1/jobs", {
          method: "POST",
          headers: {"Idempotency-Key": state.requestId},
          body: payload,
        });
        localStorage.removeItem(draftKey);
        announce("任务创建成功，正在打开任务详情");
        window.location.assign(data.job_url || `/jobs/${encodeURIComponent(data.job_id)}`);
      } catch (error) {
        const target = byId("create-error");
        target.textContent = errorMessage(error);
        target.hidden = false;
        target.focus?.();
      } finally {
        setBusy(submit, false);
      }
    });

    showStep(1);
  }

  async function initJobDetail() {
    let currentJob = null;
    let source = null;
    let lastSequence = 0;
    let showAllEvents = false;
    const eventMap = new Map();
    let refreshTimer = null;

    function addEvents(events) {
      (events || []).forEach((event) => {
        const sequence = Number(event.seq || 0);
        if (!sequence || eventMap.has(sequence)) return;
        eventMap.set(sequence, event);
        lastSequence = Math.max(lastSequence, sequence);
      });
      while (eventMap.size > 2000) eventMap.delete(Math.min(...eventMap.keys()));
      renderEvents();
    }

    function renderEvents() {
      const target = byId("event-list");
      clear(target);
      const events = Array.from(eventMap.values()).sort((a, b) => b.seq - a.seq);
      const visible = showAllEvents ? events : events.slice(0, 12);
      visible.forEach((event) => {
        target.append(element("li", {className: "event-item"}, [
          element("p", {text: event.message || event.type}),
          element("small", {text: `${formatDate(event.timestamp)} · ${event.stage || "系统"} · #${event.seq}`}),
        ]));
      });
      byId("load-older-events").hidden = events.length <= 12 || showAllEvents;
    }

    function stageStatus(job, stage) {
      const run = job.stage_runs && job.stage_runs[stage.name];
      if (run && run.status) return run.status;
      if (job.stage === stage.name) return job.status === "waiting_approval" ? "waiting_approval" : job.status === "failed" ? "failed" : "running";
      return "pending";
    }

    function renderStages(job) {
      const target = byId("stage-list");
      clear(target);
      const stages = job.pipeline_stages || [];
      setText("stage-count", `${stages.length || 0} 个阶段`);
      stages.forEach((stage, index) => {
        const run = job.stage_runs && job.stage_runs[stage.name] || {};
        const status = stageStatus(job, stage);
        const timing = run.finished_at ? `完成于 ${formatDate(run.finished_at)}` : run.started_at ? `开始于 ${formatDate(run.started_at)}` : "尚未执行";
        const route = stage.model_task ? ` · 模型任务 ${stage.model_task}` : "";
        target.append(element("li", {className: "stage-item", dataset: {status}}, [
          element("span", {className: "stage-index", text: stage.index || index + 1}),
          element("div", {className: "stage-copy"}, [
            element("strong", {text: stage.display || stage.name}),
            element("small", {text: `${stage.name} · ${timing}${route}${run.run_count ? ` · 第 ${run.run_count} 次` : ""}`}),
          ]),
          badge(statusLabels[status] || status, statusTone(status)),
        ]));
      });
    }

    function primaryAction(job) {
      const target = byId("job-primary-action");
      clear(target);
      let action;
      if (job.needs_action && String(job.stage).includes("editorial")) {
        action = element("a", {className: "button primary", href: `/jobs/${encodeURIComponent(job.job_id)}/review/editorial`}, "审核标题与旁白");
      } else if (job.needs_action && String(job.stage).includes("visual")) {
        action = element("a", {className: "button primary", href: `/jobs/${encodeURIComponent(job.job_id)}/review/visual`}, "审核视觉计划");
      } else if (job.can_retry) {
        action = element("button", {className: "button primary", type: "button", onClick: () => retry(false)}, "从失败阶段重试");
      } else if (job.status === "succeeded") {
        action = element("a", {className: "button primary", href: `/jobs/${encodeURIComponent(job.job_id)}/artifacts`}, "查看正式交付");
      } else {
        action = element("button", {className: "button primary", type: "button", onClick: () => {
          byId("stage-list").scrollIntoView({behavior: "smooth", block: "start"});
        }}, job.status === "queued" ? "查看排队状态" : "查看当前阶段");
      }
      target.append(action);
    }

    function renderJob(job) {
      currentJob = job;
      setText("job-title", job.project_name);
      setText("job-id", job.job_id);
      const summary = byId("job-summary");
      clear(summary);
      summary.append(
        metric("状态", job.display_status || statusLabels[job.status] || job.status, job.needs_action ? "需要人工处理" : "无需人工处理"),
        metric("当前阶段", job.stage || "—", job.next_action || "按流水线继续执行"),
        metric("整体进度", `${Math.round(Number(job.overall_progress || 0) * 100)}%`, job.queue_position ? `队列第 ${job.queue_position} 位` : "暂不提供预计完成时间"),
        metric("最近心跳", formatDate(job.last_heartbeat_at || job.updated_at), job.dry_run ? "演练模式，不可作为正式成片" : "生产模式"),
      );
      renderStages(job);
      renderRoutes(byId("job-routes"), job.model_routes);
      primaryAction(job);
      byId("artifact-link").href = `/jobs/${encodeURIComponent(job.job_id)}/artifacts`;
      byId("cancel-job").hidden = !job.can_cancel;
      byId("force-retry-job").hidden = appState.distributed || (appState.session && !hasPermission("paid-rerun.force"));
      const errorPanel = byId("job-error-panel");
      errorPanel.hidden = !job.error;
      if (job.error) {
        const recommendation = job.error.code === "model_route_unavailable"
          ? "稍后从当前阶段重试；系统不会切换到其他模型。"
          : "检查错误信息后，从最近有效检查点重试。";
        const errorIdNode = element("span", {}, [
          element("span", {className: "mono", text: job.error.error_id || "未提供"}),
          job.error.error_id ? element("button", {className: "button ghost", type: "button", onClick: () => copyText(job.error.error_id)}, "复制") : "",
        ]);
        detailList(byId("job-error"), [
          ["摘要", job.error.message || "生产失败"],
          ["推荐动作", recommendation],
          ["错误码", job.error.code || "internal_error"],
          ["错误 ID", errorIdNode],
          ["阶段", job.error.stage || job.stage],
        ]);
      }
      if (terminalStatuses.has(job.status) && source) {
        source.close();
        appState.eventSources.delete(source);
      }
    }

    async function loadJob() {
      const {data} = await api(`/v1/jobs/${encodeURIComponent(jobId)}`);
      const job = normalizeJobPayload(data);
      renderJob(job);
      return job;
    }

    async function retry(force) {
      if (force) {
        const typed = window.prompt(`强制重跑会重新执行有效阶段并可能产生费用。请输入任务名“${currentJob.project_name}”确认：`);
        if (typed !== currentJob.project_name) {
          toast("任务名不匹配，未执行强制重跑。", "error");
          return;
        }
      } else {
        const confirmed = await confirmAction({
          title: "从有效检查点重试？",
          message: "普通重试会复用输入哈希未变化的模型、TTS、生图和渲染产物。",
          confirmLabel: "开始重试",
          danger: false,
        });
        if (!confirmed) return;
      }
      try {
        const path = appState.distributed
          ? `/v1/jobs/${encodeURIComponent(jobId)}/retry`
          : `/v1/jobs/${encodeURIComponent(jobId)}/retry?force=${force ? "true" : "false"}`;
        const {data} = await api(path, {method: "POST", body: appState.distributed ? {stage: null} : undefined});
        renderJob(normalizeJobPayload(data));
        toast("任务已重新入队");
        connectEvents();
      } catch (error) { toast(errorMessage(error), "error"); }
    }

    async function cancel() {
      const confirmed = await confirmAction({
        title: "取消生产任务？",
        message: "排队任务会立即取消；正在进行的模型、媒体或渲染阶段会尽力中止，并等待服务端完成清理。",
        confirmLabel: "确认取消",
      });
      if (!confirmed) return;
      const button = byId("cancel-job");
      setBusy(button, true, "正在取消…");
      try {
        const {data} = await api(`/v1/jobs/${encodeURIComponent(jobId)}/cancel`, {
          method: "POST",
          body: appState.distributed ? {reason: null} : undefined,
        });
        renderJob(normalizeJobPayload(data));
        announce("服务器已收到取消请求");
      } catch (error) { toast(errorMessage(error), "error"); }
      finally { setBusy(button, false); }
    }

    function scheduleRefresh() {
      if (refreshTimer) return;
      refreshTimer = window.setTimeout(async () => {
        refreshTimer = null;
        try {
          const previousStage = currentJob && currentJob.stage;
          const job = await loadJob();
          if (previousStage && previousStage !== job.stage) announce(`任务已进入 ${job.stage}`);
        } catch (error) { toast(errorMessage(error), "error"); }
      }, 300);
    }

    function connectEvents() {
      if (source) {
        source.close();
        appState.eventSources.delete(source);
      }
      const banner = byId("event-connection");
      if (!navigator.onLine) {
        banner.className = "connection-banner disconnected";
        banner.textContent = "网络已离线；实时事件暂停，恢复网络后将自动重连。";
        return;
      }
      banner.className = "connection-banner";
      banner.textContent = "正在连接实时事件…";
      const eventPath = appState.distributed
        ? `/v1/jobs/${encodeURIComponent(jobId)}/events/stream?after=${lastSequence}`
        : `/v1/jobs/${encodeURIComponent(jobId)}/events?follow=true&after=${lastSequence}`;
      source = new EventSource(eventPath);
      appState.eventSources.add(source);
      source.addEventListener("open", () => {
        banner.className = "connection-banner connected";
        banner.textContent = "实时事件已连接";
      });
      source.addEventListener("job-event", (event) => {
        try {
          const record = JSON.parse(event.data);
          addEvents([record]);
          scheduleRefresh();
        } catch (_error) { /* Ignore malformed browser event only. */ }
      });
      source.addEventListener("error", () => {
        banner.className = "connection-banner disconnected";
        banner.textContent = "实时连接中断，正在自动重连；当前数据可能不是最新。";
      });
    }

    window.addEventListener("offline", () => {
      if (source) {
        source.close();
        appState.eventSources.delete(source);
        source = null;
      }
      const banner = byId("event-connection");
      banner.className = "connection-banner disconnected";
      banner.textContent = "网络已离线；实时事件暂停，恢复网络后将自动重连。";
    });
    window.addEventListener("online", () => {
      if (!currentJob || terminalStatuses.has(currentJob.status)) return;
      connectEvents();
    });

    byId("load-older-events").addEventListener("click", () => { showAllEvents = true; renderEvents(); });
    byId("retry-job").addEventListener("click", () => retry(false));
    byId("force-retry-job").addEventListener("click", () => retry(true));
    byId("cancel-job").addEventListener("click", cancel);

    try {
      await loadJob();
      const {data} = await api(`/v1/jobs/${encodeURIComponent(jobId)}/events?after=0`);
      addEvents(data.items || data.events || []);
      if (!terminalStatuses.has(currentJob.status)) connectEvents();
      else {
        byId("event-connection").className = "connection-banner connected";
        byId("event-connection").textContent = "任务已结束，事件记录完整。";
      }
    } catch (error) {
      toast(errorMessage(error), "error");
      byId("event-connection").className = "connection-banner disconnected";
      byId("event-connection").textContent = "无法读取任务，请检查任务地址或权限。";
    }
  }

  function reviewCommon(domain, onReview) {
    const endpoint = `/v1/jobs/${encodeURIComponent(jobId)}/reviews/${domain}`;
    let review = null;
    let etag = "";
    let dirty = false;

    async function load() {
      const {data, response} = await api(endpoint);
      review = data;
      etag = response.headers.get("etag") || data.etag;
      dirty = false;
      await onReview(data, {setDirty, request, restore, listHistory, diff});
      return data;
    }

    function setDirty(value) {
      dirty = Boolean(value);
      announce(dirty ? "当前有未保存修改" : "修改已保存");
    }

    async function renderReview(data, response = null) {
      review = data;
      etag = (response && response.headers.get("etag")) || data.etag || etag;
      dirty = false;
      await onReview(data, {setDirty, request, restore, listHistory, diff});
      return data;
    }

    async function pollModelRevision(requestId) {
      const statusUrl = `/v1/jobs/${encodeURIComponent(jobId)}/model-revision-requests/${encodeURIComponent(requestId)}`;
      const deadline = Date.now() + 180000;
      let lastStatus = null;
      while (Date.now() < deadline) {
        const {data: status} = await api(statusUrl);
        lastStatus = status;
        if (status.status === "succeeded") {
          const {data: latest, response} = await api(endpoint);
          await renderReview(latest, response);
          return {...latest, model_revision_request: status};
        }
        if (["failed", "dead_letter", "canceled", "superseded"].includes(status.status)) {
          const detail = status.error && (status.error.message || status.error.code);
          throw new Error(detail || `模型修订未完成：${status.status}`);
        }
        announce(`模型修订${status.status === "running" ? "执行中" : "排队中"}，请求 ${requestId}`);
        await sleep(750);
      }
      throw new Error(`模型修订请求 ${requestId} 超时，请稍后刷新页面查看结果。`);
    }

    async function request(suffix, method, body) {
      const {data, response} = await api(`${endpoint}${suffix}`, {
        method,
        headers: {"If-Match": etag},
        body,
      });
      const revisionRequest = data && data.revision_request;
      if (response.status === 202 && revisionRequest && revisionRequest.request_id) {
        announce(`模型修订已入队，等待 Azure Anthropic case-video-claude 完成。`);
        return pollModelRevision(revisionRequest.request_id);
      }
      return renderReview(data, response);
    }

    async function restore(revisionId) {
      const {data, response} = await api(
        `/v1/jobs/${encodeURIComponent(jobId)}/revisions/${domain}/${encodeURIComponent(revisionId)}/restore`,
        {
          method: "POST",
          headers: {"If-Match": etag},
          body: {
            base_revision: review.revision,
            change_summary: `从 ${revisionId} 恢复为新版本`,
            actor: "web-user",
          },
        },
      );
      review = data;
      etag = response.headers.get("etag") || data.etag || etag;
      dirty = false;
      await onReview(data, {setDirty, request, restore, listHistory, diff});
      return data;
    }

    async function listHistory() {
      const {data} = await api(`/v1/jobs/${encodeURIComponent(jobId)}/revisions/${domain}`);
      return data.revisions || [];
    }

    async function diff(fromRevision, toRevision) {
      const params = new URLSearchParams({from_revision: fromRevision, to_revision: toRevision});
      const {data} = await api(`/v1/jobs/${encodeURIComponent(jobId)}/revisions/${domain}/diff?${params}`);
      return data;
    }

    window.addEventListener("beforeunload", (event) => {
      if (!dirty) return;
      event.preventDefault();
      event.returnValue = "";
    });

    return {load, getReview: () => review, getEtag: () => etag, isDirty: () => dirty, setDirty};
  }

  function renderIssues(target, issues, emptyText = "当前没有问题。") {
    clear(target);
    if (!issues || !issues.length) {
      target.append(element("p", {text: emptyText}));
      return;
    }
    const list = element("ul", {className: "issue-list"});
    issues.forEach((issue) => {
      const severity = issue.severity || (String(issue.code || "").includes("warning") ? "warning" : "blocker");
      list.append(element("li", {className: `issue-card ${severity}`}, [
        badge(severity === "blocker" ? "阻断" : severity === "warning" ? "警告" : "提示", severity === "blocker" ? "danger" : severity === "warning" ? "warning" : "neutral"),
        element("p", {text: issue.message || issue.code || "未命名问题"}),
        issue.suggestion ? element("small", {text: `建议：${issue.suggestion}`}) : "",
      ]));
    });
    target.append(list);
  }

  async function renderHistory(domain, target, currentRevision, common) {
    const revisions = await common.listHistory();
    clear(target);
    revisions.slice().reverse().forEach((metadata) => {
      const isCurrent = metadata.revision_id === currentRevision;
      const restore = element("button", {
        className: "button ghost", type: "button", disabled: isCurrent,
        onClick: async () => {
          const confirmed = await confirmAction({
            title: "恢复历史版本？",
            message: "系统会创建一个新的不可变版本，并按依赖图使下游产物失效；历史记录不会删除。",
            confirmLabel: "恢复为新版本",
            danger: false,
          });
          if (!confirmed) return;
          try { await common.restore(metadata.revision_id); toast("已恢复为新版本"); }
          catch (error) { toast(errorMessage(error), "error"); }
        },
      }, isCurrent ? "当前版本" : "恢复");
      target.append(element("article", {className: `history-card ${isCurrent ? "current" : ""}`}, [
        element("strong", {className: "mono", text: metadata.revision_id}),
        element("p", {text: metadata.change_summary || "无修改说明"}),
        element("small", {text: `${metadata.author_type || "unknown"} · ${metadata.actor || "unknown"} · ${formatDate(metadata.created_at)}`}),
        restore,
      ]));
    });
    return revisions;
  }

  async function initEditorialReview() {
    byId("review-back").href = `/jobs/${encodeURIComponent(jobId)}`;
    let baseline = {title: "", narration: ""};
    let common;
    const controller = reviewCommon("editorial", async (review, helpers) => {
      common = helpers;
      const title = String(review.files["title.txt"] || "").trim();
      const narration = String(review.files["narration.txt"] || "").trim();
      baseline = {title, narration};
      byId("editorial-title").value = title;
      byId("editorial-narration").value = narration;
      byId("editorial-summary").value = "";
      setText("editorial-version", `${review.revision} · ${review.metadata.change_summary || ""}`);
      const state = byId("editorial-state");
      state.className = `badge ${review.is_approved ? "success" : review.is_rejected ? "danger" : review.blockers.length ? "danger" : "warning"}`;
      state.textContent = review.is_approved ? "已批准" : review.is_rejected ? "已驳回" : review.blockers.length ? "有阻断项" : "待批准";
      updateNarrationCount();
      renderIssues(byId("editorial-blockers"), review.blockers || [], "确定性检查没有阻断项。");
      const modelReview = review.files["review.json"] || {};
      renderIssues(byId("editorial-review-issues"), modelReview.issues || [], "gpt-5.5 独立审查没有发现问题。");
      byId("approve-editorial").disabled = !review.can_approve;
      const revisions = await renderHistory("editorial", byId("editorial-history"), review.revision, helpers);
      renderDiffOptions(revisions, review.revision);
    });

    function updateNarrationCount() {
      const narration = byId("editorial-narration").value;
      const characters = narration.replace(/\s/g, "").length;
      setText("narration-count", `${characters} 个非空白字符 · 粗略口播 ${formatDuration(characters / 4)}`);
    }

    function detectDirty() {
      const dirty = byId("editorial-title").value.trim() !== baseline.title || byId("editorial-narration").value.trim() !== baseline.narration;
      controller.setDirty(dirty);
      updateNarrationCount();
    }

    byId("editorial-title").addEventListener("input", detectDirty);
    byId("editorial-narration").addEventListener("input", detectDirty);

    async function confirmEditorialInvalidation() {
      const titleChanged = byId("editorial-title").value.trim() !== baseline.title;
      const narrationChanged = byId("editorial-narration").value.trim() !== baseline.narration;
      const impacts = [];
      if (titleChanged) impacts.push("标题变化：视觉计划、readiness、渲染、QA 和交付摘要失效；TTS 不失效");
      if (narrationChanged) impacts.push("旁白变化：文稿批准、TTS、timeline、视觉计划、生图适配、渲染、QA 和交付摘要失效");
      if (!impacts.length) return true;
      return confirmAction({title: "保存并使下游产物失效？", message: impacts.join("；"), confirmLabel: "保存新版本"});
    }

    byId("save-editorial").addEventListener("click", async () => {
      const review = controller.getReview();
      const summary = byId("editorial-summary").value.trim();
      if (!controller.isDirty()) return toast("文稿没有变化。");
      if (!summary) return toast("请填写修改说明。", "error");
      if (!(await confirmEditorialInvalidation())) return;
      const button = byId("save-editorial");
      setBusy(button, true, "保存中…");
      try {
        await common.request("/revisions", "POST", {
          base_revision: review.revision,
          title: byId("editorial-title").value.trim(),
          narration: byId("editorial-narration").value.trim(),
          change_summary: summary,
          actor: "web-user",
        });
        toast("已保存为新的不可变版本");
      } catch (error) { toast(errorMessage(error), "error"); }
      finally { setBusy(button, false); }
    });

    byId("model-editorial").addEventListener("click", async () => {
      if (controller.isDirty()) return toast("先保存或撤销本地编辑，模型结果不会覆盖未保存内容。", "error");
      const feedback = byId("editorial-feedback").value.trim();
      if (!feedback) return toast("请填写修订反馈。", "error");
      const review = controller.getReview();
      const issues = (review.files["review.json"] || {}).issues || [];
      const button = byId("model-editorial");
      setBusy(button, true, "Claude 修订中…");
      try {
        const result = await common.request("/model-revisions", "POST", {
          base_revision: review.revision,
          feedback,
          issues,
          change_summary: `Claude 定向修订：${feedback.slice(0, 120)}`,
          actor: "web-user",
        });
        byId("editorial-feedback").value = "";
        const outcome = result.model_revision_request && result.model_revision_request.outcome;
        toast(
          outcome === "no_change"
            ? "Azure Anthropic case-video-claude 已完成修订，内容哈希未变化；gpt-5.5 已独立审查。"
            : "Azure Anthropic case-video-claude 已生成新版本，gpt-5.5 已独立审查。"
        );
      } catch (error) { toast(errorMessage(error), "error"); }
      finally { setBusy(button, false); }
    });

    byId("approve-editorial").addEventListener("click", async () => {
      if (controller.isDirty()) return toast("请先保存或撤销未保存内容。", "error");
      const review = controller.getReview();
      const confirmed = await confirmAction({title: "批准当前文稿？", message: "批准会锁定当前标题与旁白版本，并继续进入 Azure Speech TTS。", confirmLabel: "批准并继续", danger: false});
      if (!confirmed) return;
      try {
        await common.request("/approve", "POST", {revision: review.revision, base_revision: review.revision, has_unsaved_draft: false, actor: "web-user"});
        window.location.assign(`/jobs/${encodeURIComponent(jobId)}`);
      } catch (error) { toast(errorMessage(error), "error"); }
    });

    byId("reject-editorial").addEventListener("click", async () => {
      if (controller.isDirty()) return toast("请先保存或撤销未保存内容。", "error");
      const reason = window.prompt("请输入驳回原因：");
      if (!reason || !reason.trim()) return;
      const review = controller.getReview();
      try {
        await common.request("/reject", "POST", {revision: review.revision, base_revision: review.revision, reason: reason.trim(), actor: "web-user"});
        toast("当前版本已驳回");
      } catch (error) { toast(errorMessage(error), "error"); }
    });

    function renderDiffOptions(revisions, current) {
      [byId("diff-from"), byId("diff-to")].forEach((select) => {
        clear(select);
        revisions.forEach((metadata) => select.append(element("option", {value: metadata.revision_id, text: metadata.revision_id})));
      });
      if (revisions.length > 1) byId("diff-from").value = revisions[revisions.length - 2].revision_id;
      byId("diff-to").value = current;
    }

    byId("load-editorial-diff").addEventListener("click", async () => {
      const from = byId("diff-from").value;
      const to = byId("diff-to").value;
      if (!from || !to || from === to) return toast("请选择两个不同版本。", "error");
      try {
        const data = await common.diff(from, to);
        byId("editorial-diff").textContent = Object.values(data.files || {}).filter(Boolean).join("\n") || "两个版本没有文本差异。";
      } catch (error) { toast(errorMessage(error), "error"); }
    });

    try { await controller.load(); }
    catch (error) { toast(errorMessage(error), "error"); }
  }

  async function initVisualReview() {
    byId("review-back").href = `/jobs/${encodeURIComponent(jobId)}`;
    let selectedSceneId = null;
    let workingPlan = null;
    let baselinePlan = null;
    let sceneContext = new Map();
    let common;

    function sceneIdentifier(scene) {
      return String(scene.id || scene.scene_id || "");
    }

    function sceneHeadlineText(scene) {
      const headline = scene.headline;
      if (headline && typeof headline === "object") return String(headline.text || "");
      return String(headline || "");
    }

    function sceneRequiresHeadline(scene) {
      return String(workingPlan?.version || "") !== "2" || String(scene?.visualMode || "") !== "editorial";
    }

    function sceneDirectorialIntent(scene) {
      return String(scene.directorialIntent || scene.visual_intent || "");
    }

    function sceneUnitRange(scene) {
      if (Array.isArray(scene.units) && scene.units.length === 2) {
        return [Number(scene.units[0]), Number(scene.units[1])];
      }
      const first = Number(scene.atUnit || 0) + 1;
      return [first, first + Math.max(1, Number(scene.units || 1)) - 1];
    }

    function sceneKeywordTexts(scene) {
      return (scene.keywords || []).map((keyword) => (
        keyword && typeof keyword === "object" ? keyword.text : keyword
      )).filter(Boolean).map(String);
    }

    function setSceneHeadline(scene, value) {
      const isVersionTwo = String(workingPlan?.version || "") === "2";
      if (scene.headline && typeof scene.headline === "object") {
        if (!value && !sceneRequiresHeadline(scene)) {
          delete scene.headline;
          return;
        }
        scene.headline.text = value;
        scene.headline.accent = (scene.headline.accent || []).filter((accent) => value.includes(accent));
      } else if (isVersionTwo) {
        if (!value) {
          delete scene.headline;
          return;
        }
        scene.headline = {text: value, reveal: "perClause", accent: []};
      } else {
        scene.headline = value;
      }
    }

    function renderSceneFieldRequirements(scene) {
      const headlineRequired = sceneRequiresHeadline(scene);
      const headline = byId("scene-headline");
      headline.required = headlineRequired;
      setText("scene-headline-label", headlineRequired ? "场景标题 *" : "场景标题（可选）");
      setText(
        "scene-headline-help",
        headlineRequired
          ? "layout / hybrid 场景必须提供屏幕标题。"
          : "editorial 场景以画面叙事为主，可以不显示屏幕标题。",
      );
      setText(
        "scene-mode-note",
        `当前视觉模式：${scene.visualMode || "legacy"}。${headlineRequired ? "场景标题和画面意图均为必填。" : "画面意图必填，场景标题可选。"}`,
      );
    }

    function setSceneKeywords(scene, values) {
      const existing = scene.keywords || [];
      const isVersionTwo = String(workingPlan.version || "") === "2";
      if (!isVersionTwo) {
        scene.keywords = values;
        return;
      }
      const [firstUnit] = sceneUnitRange(scene);
      scene.keywords = values.map((text, index) => {
        const previous = existing[index];
        if (previous && typeof previous === "object") return {...previous, text};
        return {text, atUnit: firstUnit, display: false};
      });
    }

    function setSceneIntent(scene, value) {
      if (String(workingPlan.version || "") === "2" || Object.hasOwn(scene, "directorialIntent")) {
        scene.directorialIntent = value;
      } else {
        scene.visual_intent = value;
      }
    }

    const controller = reviewCommon("visual-plan", async (review, helpers) => {
      common = helpers;
      workingPlan = JSON.parse(JSON.stringify(review.files["storyboard_plan.json"]));
      baselinePlan = JSON.stringify(workingPlan);
      sceneContext = new Map((review.scene_context || []).map((item) => [item.scene_id, item]));
      setText("visual-version", `${review.revision} · ${review.metadata.change_summary || ""}`);
      const state = byId("visual-state");
      state.className = `badge ${review.is_approved ? "success" : review.is_rejected ? "danger" : review.blockers.length ? "danger" : "warning"}`;
      state.textContent = review.is_approved ? "已批准" : review.is_rejected ? "已驳回" : review.blockers.length ? "有阻断项" : "待批准";
      byId("approve-visual").disabled = !review.can_approve;
      renderReadiness(review);
      renderScenes(review);
      await renderHistory("visual-plan", byId("visual-history"), review.revision, helpers);
    });

    function currentScene() {
      return (workingPlan.scenes || []).find((scene) => sceneIdentifier(scene) === selectedSceneId) || null;
    }

    function sceneSeverity(scene, review) {
      const readiness = review.files["readiness.json"] || {};
      const blockers = readiness.blockers || [];
      const warnings = readiness.warnings || [];
      const sceneId = sceneIdentifier(scene);
      if (blockers.some((item) => String(item.message || "").includes(sceneId))) return "blocker";
      if (warnings.some((item) => String(item.message || "").includes(sceneId))) return "warning";
      return "none";
    }

    function renderScenes(review) {
      const target = byId("scene-grid");
      clear(target);
      const filter = byId("scene-filter").value;
      (workingPlan.scenes || []).forEach((scene, index) => {
        const sceneId = sceneIdentifier(scene);
        const headline = sceneHeadlineText(scene);
        const [firstUnit, lastUnit] = sceneUnitRange(scene);
        const context = sceneContext.get(sceneId) || {};
        const severity = sceneSeverity(scene, review);
        if (filter === "blocker" && severity !== "blocker") return;
        if (filter === "warning" && severity !== "warning") return;
        if (filter === "modified" && !context.changed) return;
        const thumb = element("div", {className: `scene-thumb ${context.preview_url ? "has-image" : ""}`});
        if (context.preview_url) thumb.append(element("img", {src: context.preview_url, alt: `场景 ${index + 1} 代表帧`, loading: "lazy"}));
        else thumb.append(element("small", {text: "代表帧待生成"}), element("strong", {text: headline}));
        const meta = element("div", {className: "scene-meta"}, [
          element("strong", {text: `${String(index + 1).padStart(2, "0")} · ${headline}`}),
          element("p", {text: `Unit ${context.first_unit || firstUnit}–${context.last_unit || lastUnit} · ${formatDuration(context.duration_seconds)}`}),
          element("small", {text: `${scene.layout} · ${context.style_family || "视觉样式待定"} · ${context.background_source || "pending"}`}),
          severity !== "none" ? badge(severity === "blocker" ? "Blocker" : "Warning", severity === "blocker" ? "danger" : "warning") : "",
          scene.reuse || scene.allowBackgroundReuse ? badge("复用背景", "info") : "",
        ]);
        target.append(element("button", {
          className: `scene-card ${selectedSceneId === sceneId ? "selected" : ""}`,
          type: "button",
          onClick: () => selectScene(sceneId),
          "aria-pressed": selectedSceneId === sceneId ? "true" : "false",
        }, [thumb, meta]));
      });
      if (!target.children.length) target.append(element("p", {text: "当前筛选下没有场景。"}));
    }

    function selectScene(sceneId) {
      selectedSceneId = sceneId;
      const scene = currentScene();
      if (!scene) return;
      byId("scene-editor").hidden = false;
      if (![...byId("scene-layout").options].some((option) => option.value === scene.layout)) {
        byId("scene-layout").append(element("option", {value: scene.layout, text: scene.layout}));
      }
      byId("scene-layout").value = scene.layout;
      byId("scene-kicker").value = scene.kicker || "";
      byId("scene-headline").value = sceneHeadlineText(scene);
      byId("scene-keywords").value = sceneKeywordTexts(scene).join("，");
      byId("scene-intent").value = sceneDirectorialIntent(scene);
      renderSceneFieldRequirements(scene);
      renderScenes(controller.getReview());
      byId("scene-editor").scrollIntoView({behavior: "smooth", block: "nearest"});
    }

    function updateWorkingScene() {
      const scene = currentScene();
      if (!scene) return;
      scene.layout = byId("scene-layout").value;
      scene.kicker = byId("scene-kicker").value.trim();
      setSceneHeadline(scene, byId("scene-headline").value.trim());
      setSceneKeywords(scene, byId("scene-keywords").value.split(/[，,]/).map((value) => value.trim()).filter(Boolean));
      setSceneIntent(scene, byId("scene-intent").value.trim());
      controller.setDirty(JSON.stringify(workingPlan) !== baselinePlan);
      renderScenes(controller.getReview());
    }

    ["scene-layout", "scene-kicker", "scene-headline", "scene-keywords", "scene-intent"].forEach((id) => byId(id).addEventListener("input", updateWorkingScene));
    byId("scene-filter").addEventListener("change", () => renderScenes(controller.getReview()));

    function renderReadiness(review) {
      const target = byId("visual-readiness");
      clear(target);
      const readiness = review.files["readiness.json"] || {};
      target.append(
        badge(readiness.status === "ready" ? "Ready" : "Blocked", readiness.status === "ready" ? "success" : "danger"),
        element("p", {text: `预计生成 ${readiness.estimated_image_count ?? "—"} 张图片。`}),
      );
      const issues = element("div", {className: "readiness-issues"});
      target.append(issues);
      renderIssues(issues, [...(readiness.blockers || []), ...(readiness.warnings || [])], "视觉计划已通过 readiness。");
    }

    byId("save-visual").addEventListener("click", async () => {
      updateWorkingScene();
      if (!controller.isDirty()) return toast("视觉计划没有变化。");
      const scene = currentScene();
      if (!scene || !sceneDirectorialIntent(scene)) return toast("画面意图不能为空。", "error");
      if (sceneRequiresHeadline(scene) && !sceneHeadlineText(scene)) return toast("当前视觉模式要求填写场景标题。", "error");
      const summary = byId("visual-summary").value.trim();
      if (!summary) return toast("请填写修改说明。", "error");
      const confirmed = await confirmAction({
        title: "保存视觉计划新版本？",
        message: "视觉批准、生图、渲染、QA 和交付摘要将失效；TTS 与 timeline 不会重做。",
        confirmLabel: "保存新版本",
      });
      if (!confirmed) return;
      const review = controller.getReview();
      const button = byId("save-visual");
      setBusy(button, true, "保存中…");
      try {
        await common.request("/revisions", "POST", {
          base_revision: review.revision,
          plan: workingPlan,
          rich_storyboard: null,
          image_prompts: review.files["image_prompts.json"] || null,
          readiness: null,
          change_summary: summary,
          actor: "web-user",
        });
        byId("visual-summary").value = "";
        toast("视觉计划已保存为新版本");
      } catch (error) { toast(errorMessage(error), "error"); }
      finally { setBusy(button, false); }
    });

    byId("model-visual").addEventListener("click", async () => {
      if (controller.isDirty()) return toast("先保存或撤销本地编辑，模型结果不会覆盖未保存内容。", "error");
      const feedback = byId("visual-feedback").value.trim();
      if (!feedback) return toast("请填写视觉修订反馈。", "error");
      const review = controller.getReview();
      const readiness = review.files["readiness.json"] || {};
      const button = byId("model-visual");
      setBusy(button, true, "Claude 修订中…");
      try {
        const result = await common.request("/model-revisions", "POST", {
          base_revision: review.revision,
          feedback,
          issues: [...(readiness.blockers || []), ...(readiness.warnings || [])],
          scene_ids: selectedSceneId ? [selectedSceneId] : [],
          change_summary: `Claude 视觉修订：${feedback.slice(0, 120)}`,
          actor: "web-user",
        });
        byId("visual-feedback").value = "";
        const outcome = result.model_revision_request && result.model_revision_request.outcome;
        toast(
          outcome === "no_change"
            ? "Azure Anthropic case-video-claude 已完成视觉修订，内容哈希未变化。"
            : "Azure Anthropic case-video-claude 已生成视觉计划新版本。"
        );
      } catch (error) { toast(errorMessage(error), "error"); }
      finally { setBusy(button, false); }
    });

    byId("approve-visual").addEventListener("click", async () => {
      if (controller.isDirty()) return toast("请先保存或撤销未保存内容。", "error");
      const review = controller.getReview();
      const readiness = review.files["readiness.json"] || {};
      const confirmed = await confirmAction({
        title: "批准视觉计划并进入付费生图？",
        message: `当前计划预计生成 ${readiness.estimated_image_count ?? "若干"} 张图片。批准后将进入图片生成阶段。`,
        confirmLabel: "批准并开始生图",
        danger: false,
      });
      if (!confirmed) return;
      try {
        await common.request("/approve", "POST", {revision: review.revision, base_revision: review.revision, has_unsaved_draft: false, actor: "web-user"});
        window.location.assign(`/jobs/${encodeURIComponent(jobId)}`);
      } catch (error) { toast(errorMessage(error), "error"); }
    });

    byId("reject-visual").addEventListener("click", async () => {
      if (controller.isDirty()) return toast("请先保存或撤销未保存内容。", "error");
      const reason = window.prompt("请输入驳回原因：");
      if (!reason || !reason.trim()) return;
      const review = controller.getReview();
      try {
        await common.request("/reject", "POST", {revision: review.revision, base_revision: review.revision, reason: reason.trim(), actor: "web-user"});
        toast("当前视觉版本已驳回");
      } catch (error) { toast(errorMessage(error), "error"); }
    });

    if (window.matchMedia("(max-width: 767px)").matches) {
      ["scene-layout", "scene-kicker", "scene-headline", "scene-keywords", "scene-intent", "save-visual"].forEach((id) => { byId(id).disabled = true; });
      toast("移动端支持查看与批准；复杂场景编辑请使用桌面端。" );
    }

    try { await controller.load(); }
    catch (error) { toast(errorMessage(error), "error"); }
  }

  async function initArtifacts() {
    byId("artifacts-back").href = `/jobs/${encodeURIComponent(jobId)}`;
    const kindLabels = {text: "文稿", audio: "音频", json: "分镜与数据", image: "图片", qa: "QA", video: "成片", log: "日志"};

    function inferArtifactKind(item) {
      const name = String(item.logical_name || item.name || "").toLowerCase();
      const mediaType = String(item.media_type || "").toLowerCase();
      if (mediaType.startsWith("video/") || /\.(mp4|mov|webm)$/.test(name)) return "video";
      if (mediaType.startsWith("audio/") || /\.(wav|mp3|m4a|ogg)$/.test(name)) return "audio";
      if (mediaType.startsWith("image/") || /\.(png|jpe?g|webp|gif)$/.test(name)) return "image";
      if (name.includes("qa") || name.includes("contact-sheet") || name.includes("ffprobe")) return "qa";
      if (mediaType.includes("json") || name.endsWith(".json")) return "json";
      if (name.endsWith(".log")) return "log";
      return "text";
    }

    function normalizeArtifact(item) {
      const name = item.logical_name || item.name;
      const kind = item.kind || inferArtifactKind(item);
      return {
        ...item,
        name,
        kind,
        size: item.size_bytes ?? item.size ?? 0,
        modified_at: item.modified_at || item.created_at,
        formal_delivery: item.formal_delivery ?? (
          kind === "video" && item.current !== false && ["delivery", "final"].includes(item.domain)
        ),
      };
    }

    async function resolveArtifactUrl(item) {
      if (!appState.distributed) return artifactUrl(item.name);
      const {data} = await api(`${artifactUrl(item.name)}/download`, {method: "POST"});
      return data.download_url;
    }

    try {
      const {data} = await api(`/v1/jobs/${encodeURIComponent(jobId)}/artifacts`);
      const artifacts = (data.items || data.artifacts || []).map(normalizeArtifact);
      const formal = artifacts.some((item) => item.formal_delivery);
      const state = byId("delivery-state");
      state.className = `badge ${formal ? "success" : "warning"}`;
      state.textContent = formal ? "存在正式成片" : "尚无正式成片";
      const grouped = new Map();
      artifacts.forEach((item) => {
        const key = item.kind || "text";
        if (!grouped.has(key)) grouped.set(key, []);
        grouped.get(key).push(item);
      });
      const target = byId("artifact-groups");
      clear(target);
      if (!artifacts.length) target.append(element("section", {className: "panel empty-state"}, [element("h2", {text: "暂无产物"}), element("p", {text: "任务执行后，当前有效版本会出现在这里。"})]));
      grouped.forEach((items, kind) => {
        const list = element("ul", {className: "artifact-list"});
        items.forEach((item) => {
          const preview = element("button", {className: "button ghost", type: "button", onClick: () => previewArtifact(item)}, "预览");
          const download = element("button", {
            className: "button secondary",
            type: "button",
            onClick: async () => {
              setBusy(download, true, "准备中…");
              try {
                window.location.assign(await resolveArtifactUrl(item));
              } catch (error) {
                toast(errorMessage(error), "error");
              } finally {
                setBusy(download, false);
              }
            },
          }, "下载");
          list.append(element("li", {className: "artifact-item"}, [
            element("div", {}, [
              element("strong", {text: item.name}),
              element("small", {text: `${formatBytes(item.size)} · ${formatDate(item.modified_at)} · ${item.current ? "当前有效" : "已失效"}`}),
              item.formal_delivery ? badge("正式成片", "success") : kind === "video" ? badge("调试视频", "warning") : "",
            ]),
            element("div", {className: "artifact-actions"}, [preview, download]),
          ]));
        });
        target.append(element("section", {className: "artifact-group"}, [element("h2", {text: kindLabels[kind] || kind}), list]));
      });
    } catch (error) { toast(errorMessage(error), "error"); }

    async function previewArtifact(item) {
      const dialog = byId("preview-dialog");
      const target = byId("preview-content");
      setText("preview-title", item.name);
      clear(target);
      try {
        const url = await resolveArtifactUrl(item);
        if (item.kind === "video") target.append(element("video", {src: url, controls: true, preload: "metadata"}));
        else if (item.kind === "audio") target.append(element("audio", {src: url, controls: true, preload: "metadata"}));
        else if (item.kind === "image") target.append(element("img", {src: url, alt: item.name}));
        else {
          const response = await fetch(url, {credentials: "same-origin"});
          if (!response.ok) throw new Error(`预览失败（HTTP ${response.status}）`);
          const text = await response.text();
          target.append(element("pre", {text: text.slice(0, 250000)}));
          if (text.length > 250000) target.append(element("p", {text: "文件较大，预览仅显示前 250,000 个字符。"}));
        }
        dialog.showModal();
      } catch (error) { toast(errorMessage(error), "error"); }
    }
  }

  async function initHealth() {
    async function load() {
      const button = byId("refresh-health");
      setBusy(button, true, "检查中…");
      try {
        const {data} = await api("/health/ready");
        const summary = byId("health-summary");
        clear(summary);
        if (data.deployment_mode === "distributed") {
          let capabilities = null;
          try { capabilities = (await api("/v1/capabilities")).data; }
          catch (_error) { /* Readiness remains useful without capability details. */ }
          summary.append(
            metric("总体状态", data.status === "ready" ? "可用" : "降级", data.status),
            metric("数据库", data.schema || "已连接", "迁移版本"),
            metric("对象存储", capabilities ? capabilities.object_store : "依赖探测通过"),
            metric("运行模式", "分布式", "API、队列与隔离 worker"),
          );
          const checks = [
            ["Deployment", "distributed"],
            ["Schema", data.schema || "ready"],
            ["Object store", capabilities ? capabilities.object_store : "ready"],
            ["Pipeline", capabilities ? `${capabilities.pipeline_stage_count} stages` : "21 stages"],
          ];
          Object.entries(capabilities ? (capabilities.model_route_readiness || capabilities.model_routes || {}) : {}).forEach(([name, route]) => {
            checks.push([`Model route · ${name}`, `${route.model || "—"} · ${route.provider || "—"} · ${route.ready === false ? "not ready" : "ready"}`]);
          });
          detailList(byId("health-checks"), checks);
          return;
        }
        summary.append(
          metric("总体状态", data.status === "ok" ? "可用" : "降级", data.status),
          metric("存储", data.checks.storage ? "正常" : "异常"),
          metric("队列", data.checks.queue || "—"),
          metric("运行模式", data.checks.dry_run ? "演练" : "生产"),
        );
        const model = typeof data.checks.model_routes === "string" ? data.checks.model_routes : `${data.checks.model_routes.code}: ${data.checks.model_routes.message}`;
        detailList(byId("health-checks"), [["Storage", data.checks.storage ? "可写目录存在" : "目录不可用"], ["Queue", data.checks.queue], ["Model routes", model], ["Dry run", data.checks.dry_run ? "是；不会产生正式成片" : "否"]]);
      } catch (error) { toast(errorMessage(error), "error"); }
      finally { setBusy(button, false); }
    }
    byId("refresh-health").addEventListener("click", load);
    await load();
  }

  async function initOperations() {
    async function load() {
      const button = byId("refresh-operations");
      setBusy(button, true, "刷新中…");
      try {
        const {data} = await api("/v1/operations/snapshot");
        const statuses = data.jobs_by_status || {};
        const summary = byId("operations-summary");
        clear(summary);
        summary.append(
          metric("活跃任务", Number(statuses.queued || 0) + Number(statuses.running || 0), "排队与执行中"),
          metric("待人工处理", Number(statuses.waiting_approval || 0), `其中预算审批 ${data.budget_waiting || 0}`),
          metric("过期租约", data.leases ? data.leases.expired : 0, "应由 reaper 回收"),
          metric("Outbox", data.outbox ? data.outbox.pending : 0, data.outbox && data.outbox.failed ? `${data.outbox.failed} 条发送失败` : "无发送失败"),
        );
        const queueBody = byId("operations-queues");
        clear(queueBody);
        (data.queues || []).forEach((queue) => {
          queueBody.append(element("tr", {}, [
            element("td", {className: "mono", text: queue.queue}),
            element("td", {text: queue.queued}),
            element("td", {text: queue.running}),
            element("td", {}, badge(queue.dead_letter, queue.dead_letter ? "danger" : "neutral")),
            element("td", {text: formatAge(queue.oldest_queued_age_seconds)}),
          ]));
        });
        byId("operations-queues-empty").hidden = Boolean((data.queues || []).length);
        renderRoutes(byId("operations-routes"), data.model_routes || {});
        setText("operations-generated-at", formatDate(data.generated_at));

        const workers = byId("operations-workers");
        clear(workers);
        (data.workers || []).forEach((worker) => {
          workers.append(element("tr", {}, [
            element("td", {className: "mono", text: worker.worker_id}),
            element("td", {text: worker.active_leases}),
            element("td", {text: worker.expired_leases}),
            element("td", {text: worker.cancel_requested}),
            element("td", {text: formatDate(worker.last_heartbeat_at)}),
            element("td", {text: formatDate(worker.lease_expires_at)}),
          ]));
        });
        byId("operations-workers-empty").hidden = Boolean((data.workers || []).length);

        const deadLetters = byId("operations-dead-letters");
        clear(deadLetters);
        (data.recent_dead_letters || []).forEach((run) => {
          deadLetters.append(element("tr", {}, [
            element("td", {}, element("a", {href: `/jobs/${encodeURIComponent(run.job_id)}`, className: "mono"}, run.job_id)),
            element("td", {className: "mono", text: run.stage}),
            element("td", {text: `${run.attempt || 0} / cycle ${run.retry_cycle || 0}`}),
            element("td", {text: run.error_message || run.error_code || "—"}),
            element("td", {}, badge(run.retryable ? "是" : "否", run.retryable ? "warning" : "neutral")),
          ]));
        });
        byId("operations-dead-letters-empty").hidden = Boolean((data.recent_dead_letters || []).length);
      } catch (error) {
        toast(errorMessage(error), "error");
      } finally {
        setBusy(button, false);
      }
    }
    byId("refresh-operations").addEventListener("click", load);
    await load();
  }

  async function initMembers() {
    const form = byId("member-form");
    let members = [];

    function resetForm() {
      form.reset();
      form.elements.namedItem("user_id").value = "";
      form.elements.namedItem("new_user_id").disabled = false;
      setText("member-form-title", "添加成员");
      byId("member-form-error").hidden = true;
    }

    function editMember(member) {
      form.elements.namedItem("user_id").value = member.user_id;
      form.elements.namedItem("new_user_id").value = member.user_id;
      form.elements.namedItem("new_user_id").disabled = true;
      form.elements.namedItem("subject").value = member.oidc_subject || "";
      form.elements.namedItem("display_name").value = member.display_name || "";
      form.elements.namedItem("email").value = member.email || "";
      form.elements.namedItem("role").value = member.role;
      form.elements.namedItem("disabled").checked = Boolean(member.disabled);
      setText("member-form-title", `编辑 ${member.display_name || member.user_id}`);
      form.scrollIntoView({behavior: "smooth", block: "start"});
    }

    function render() {
      const body = byId("members-body");
      clear(body);
      members.forEach((member) => {
        const edit = element("button", {
          className: "button ghost",
          type: "button",
          hidden: !hasPermission("members.manage"),
          onClick: () => editMember(member),
        }, "编辑");
        body.append(element("tr", {}, [
          element("td", {}, [element("strong", {text: member.display_name || member.user_id}), element("small", {text: member.email || member.user_id})]),
          element("td", {className: "mono", text: member.oidc_subject || "—"}),
          element("td", {}, badge(String(member.role || "").toUpperCase(), member.role === "admin" ? "warning" : "info")),
          element("td", {}, badge(member.disabled ? "已停用" : "启用", member.disabled ? "danger" : "success")),
          element("td", {}, edit),
        ]));
      });
      setText("members-count", `${members.length} 位成员`);
      byId("members-empty").hidden = members.length !== 0;
    }

    async function load() {
      const button = byId("refresh-members");
      setBusy(button, true, "刷新中…");
      try {
        members = (await api("/v1/members")).data.items || [];
        render();
      } catch (error) {
        toast(errorMessage(error), "error");
      } finally {
        setBusy(button, false);
      }
    }

    const editable = hasPermission("members.manage");
    form.closest("aside").hidden = !editable;
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const existingId = form.elements.namedItem("user_id").value;
      const userId = existingId || form.elements.namedItem("new_user_id").value.trim();
      const error = byId("member-form-error");
      error.hidden = true;
      const button = form.querySelector('button[type="submit"]');
      setBusy(button, true, "保存中…");
      try {
        await api(`/v1/members/${encodeURIComponent(userId)}`, {
          method: "PUT",
          body: {
            subject: form.elements.namedItem("subject").value.trim(),
            display_name: form.elements.namedItem("display_name").value.trim() || null,
            email: form.elements.namedItem("email").value.trim() || null,
            role: form.elements.namedItem("role").value,
            disabled: form.elements.namedItem("disabled").checked,
          },
        });
        toast("成员权限已更新");
        resetForm();
        await load();
      } catch (saveError) {
        error.textContent = errorMessage(saveError);
        error.hidden = false;
      } finally {
        setBusy(button, false);
      }
    });
    byId("member-form-reset").addEventListener("click", resetForm);
    byId("refresh-members").addEventListener("click", load);
    await load();
  }

  async function initGovernance() {
    const form = byId("governance-form");
    let tenant = null;

    function setField(name, value) {
      const field = form.elements.namedItem(name);
      if (field) field.value = value === undefined || value === null ? "" : value;
    }

    function renderQuotaSummary(items) {
      const target = byId("quota-summary");
      clear(target);
      const labels = {active_jobs: "活跃任务", upload_bytes: "上传字节", upload_files: "上传文件"};
      (items || []).forEach((item) => {
        const bytes = item.dimension === "upload_bytes";
        const used = bytes ? formatBytes(item.committed) : item.committed;
        const limit = item.limit === null ? "无限制" : bytes ? formatBytes(item.limit) : item.limit;
        target.append(element("article", {}, [
          element("strong", {text: labels[item.dimension] || item.dimension}),
          element("span", {text: `${used} / ${limit}`}),
          element("small", {text: item.available === null ? "未设置硬上限" : `剩余 ${bytes ? formatBytes(item.available) : item.available}`}),
        ]));
      });
    }

    async function load() {
      const button = byId("refresh-governance");
      setBusy(button, true, "刷新中…");
      try {
        const [tenantResponse, costResponse, quotaResponse] = await Promise.all([
          api("/v1/governance"), api("/v1/costs/summary"), api("/v1/quotas"),
        ]);
        tenant = tenantResponse.data;
        const quotas = tenant.quotas || {};
        const retention = tenant.retention || {};
        const policy = tenant.policy || {};
        setField("active_jobs", quotas.active_jobs);
        setField("upload_files", quotas.upload_files);
        setField("upload_megabytes", quotas.upload_bytes === undefined ? "" : Math.round(Number(quotas.upload_bytes) / 1024 / 1024));
        setField("monthly_cost_usd", quotas.monthly_cost_micros === undefined ? "" : Number(quotas.monthly_cost_micros) / 1_000_000);
        setField("default_approval_mode", policy.default_approval_mode || "full");
        setField("default_job_budget_usd", policy.default_job_budget_micros === undefined ? "" : Number(policy.default_job_budget_micros) / 1_000_000);
        setField("succeeded_days", retention.succeeded_days);
        setField("failed_days", retention.failed_days);
        setField("recovery_days", retention.recovery_days);
        form.elements.namedItem("confirm_governance").checked = false;
        const cost = costResponse.data;
        const costTarget = byId("governance-cost-summary");
        clear(costTarget);
        costTarget.append(
          metric("本月实际成本", formatMoneyMicros(cost.actual_micros)),
          metric("已保留成本", formatMoneyMicros(cost.reserved_micros)),
          metric("承诺成本", formatMoneyMicros(cost.committed_micros)),
          metric("月度上限", formatMoneyMicros(cost.limit_micros), cost.limit_micros === null ? "未设置硬上限" : "达到上限会阻止新付费阶段"),
        );
        renderQuotaSummary(quotaResponse.data.items);
      } catch (error) {
        toast(errorMessage(error), "error");
      } finally {
        setBusy(button, false);
      }
    }

    form.querySelector('button[type="submit"]').hidden = !hasPermission("governance.write");
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (!tenant) return;
      const error = byId("governance-error");
      error.hidden = true;
      const number = (name, multiplier = 1) => {
        const raw = form.elements.namedItem(name).value.trim();
        return raw === "" ? null : Math.round(Number(raw) * multiplier);
      };
      const quotas = {...(tenant.quotas || {})};
      const retention = {...(tenant.retention || {})};
      const policy = {...(tenant.policy || {})};
      const assignments = [
        [quotas, "active_jobs", number("active_jobs")],
        [quotas, "upload_files", number("upload_files")],
        [quotas, "upload_bytes", number("upload_megabytes", 1024 * 1024)],
        [quotas, "monthly_cost_micros", number("monthly_cost_usd", 1_000_000)],
        [policy, "default_job_budget_micros", number("default_job_budget_usd", 1_000_000)],
        [retention, "succeeded_days", number("succeeded_days")],
        [retention, "failed_days", number("failed_days")],
        [retention, "recovery_days", number("recovery_days")],
      ];
      assignments.forEach(([target, key, value]) => {
        if (value === null) delete target[key];
        else target[key] = value;
      });
      policy.default_approval_mode = form.elements.namedItem("default_approval_mode").value;
      const button = form.querySelector('button[type="submit"]');
      setBusy(button, true, "保存中…");
      try {
        tenant = (await api("/v1/governance", {method: "PATCH", body: {quotas, retention, policy}})).data;
        toast("工作区治理配置已保存");
        await load();
      } catch (saveError) {
        error.textContent = errorMessage(saveError);
        error.hidden = false;
      } finally {
        setBusy(button, false);
      }
    });
    byId("refresh-governance").addEventListener("click", load);
    await load();
  }

  async function initAudit() {
    const form = byId("audit-filters");
    const limit = 50;
    let offset = Number(new URLSearchParams(window.location.search).get("offset") || 0);
    const params = new URLSearchParams(window.location.search);
    for (const [name, value] of params.entries()) {
      const field = form.elements.namedItem(name);
      if (field) field.value = value;
    }

    function queryParams() {
      const query = new URLSearchParams({limit: String(limit), offset: String(offset)});
      ["actor_id", "job_id", "action", "result", "occurred_from", "occurred_to"].forEach((name) => {
        const raw = form.elements.namedItem(name).value.trim();
        if (!raw) return;
        query.set(name, name.startsWith("occurred_") ? new Date(raw).toISOString() : raw);
      });
      return query;
    }

    async function load() {
      try {
        const query = queryParams();
        const visible = new URLSearchParams(query);
        visible.delete("limit");
        if (!offset) visible.delete("offset");
        history.replaceState(null, "", `${window.location.pathname}${visible.size ? `?${visible}` : ""}`);
        const {data} = await api(`/v1/audit?${query}`);
        const body = byId("audit-body");
        clear(body);
        (data.items || []).forEach((record) => {
          body.append(element("tr", {}, [
            element("td", {text: formatDate(record.occurred_at)}),
            element("td", {className: "mono", text: record.actor_id}),
            element("td", {className: "mono", text: record.action}),
            element("td", {}, [element("strong", {text: record.resource_type}), element("small", {className: "mono", text: record.resource_id})]),
            element("td", {}, badge(record.result, record.result === "succeeded" ? "success" : "danger")),
            element("td", {className: "mono", text: record.request_id || "—"}),
          ]));
        });
        byId("audit-empty").hidden = Boolean((data.items || []).length);
        setText("audit-page-label", `第 ${Math.floor(offset / limit) + 1} 页`);
        byId("audit-previous").disabled = offset === 0;
        byId("audit-next").disabled = !data.has_more;
      } catch (error) {
        toast(errorMessage(error), "error");
      }
    }

    form.addEventListener("submit", (event) => { event.preventDefault(); offset = 0; load(); });
    byId("clear-audit-filters").addEventListener("click", () => { form.reset(); offset = 0; load(); });
    byId("audit-previous").addEventListener("click", () => { offset = Math.max(0, offset - limit); load(); });
    byId("audit-next").addEventListener("click", () => { offset += limit; load(); });
    await load();
  }

  async function initRetention() {
    const form = byId("retention-filters");
    const limit = 50;
    let offset = 0;

    function isPurgeReady(job) {
      return Boolean(
        job.deleted_at && job.purge_after && new Date(job.purge_after).getTime() <= Date.now()
        && !job.pinned && !job.legal_hold
      );
    }

    async function updateProtection(job, field, value) {
      try {
        await api(`/v1/jobs/${encodeURIComponent(job.job_id)}/protection`, {
          method: "PATCH",
          body: {[field]: value},
        });
        toast(field === "pinned" ? "固定状态已更新" : "Legal hold 已更新");
        await load();
      } catch (error) { toast(errorMessage(error), "error"); }
    }

    async function restore(job) {
      try {
        await api(`/v1/jobs/${encodeURIComponent(job.job_id)}/restore`, {method: "POST"});
        toast("任务已恢复到任务中心");
        await load();
      } catch (error) { toast(errorMessage(error), "error"); }
    }

    async function hideJob(job) {
      const confirmed = await confirmAction({
        title: "隐藏并进入恢复窗口？",
        message: "任务会从任务中心隐藏，但在恢复窗口到期前仍可由管理员恢复。",
        confirmLabel: "隐藏任务",
      });
      if (!confirmed) return;
      try {
        await api(`/v1/jobs/${encodeURIComponent(job.job_id)}`, {method: "DELETE"});
        toast("任务已隐藏");
        await load();
      } catch (error) { toast(errorMessage(error), "error"); }
    }

    async function purge(job) {
      const expected = `永久删除 ${job.job_id}`;
      const typed = window.prompt(`永久删除会移除数据库记录与对象存储中的任务产物，且不可恢复。请输入“${expected}”确认：`);
      if (typed !== expected) {
        toast("确认文本不匹配，未永久删除。", "error");
        return;
      }
      try {
        const {data} = await api(`/v1/retention/jobs/${encodeURIComponent(job.job_id)}/purge`, {
          method: "POST",
          body: {confirmation: typed},
        });
        toast(`任务已永久删除；清理对象 ${data.deleted_object_count}/${data.object_count}`);
        await load();
      } catch (error) { toast(errorMessage(error), "error"); }
    }

    function render(items, total) {
      const body = byId("retention-body");
      clear(body);
      items.forEach((job) => {
        const actions = element("div", {className: "button-row compact-actions"});
        if (job.deleted_at) {
          actions.append(element("button", {className: "button ghost", type: "button", onClick: () => restore(job)}, "恢复"));
          if (isPurgeReady(job)) actions.append(element("button", {className: "button danger ghost", type: "button", onClick: () => purge(job)}, "永久删除"));
        } else {
          actions.append(element("button", {className: "button danger ghost", type: "button", onClick: () => hideJob(job)}, "隐藏"));
        }
        actions.append(
          element("button", {className: "button ghost", type: "button", onClick: () => updateProtection(job, "pinned", !job.pinned)}, job.pinned ? "取消固定" : "固定"),
          element("button", {className: "button ghost", type: "button", onClick: () => updateProtection(job, "legal_hold", !job.legal_hold)}, job.legal_hold ? "解除 hold" : "Legal hold"),
        );
        const lifecycle = !job.deleted_at ? "活跃" : isPurgeReady(job) ? "可永久删除" : "恢复窗口";
        const protection = [job.pinned ? "固定" : "", job.legal_hold ? "Legal hold" : ""].filter(Boolean).join(" · ") || "无";
        body.append(element("tr", {}, [
          element("td", {}, [element("strong", {text: job.project_name}), element("small", {className: "mono", text: job.job_id})]),
          element("td", {}, badge(statusLabels[job.status] || job.status, statusTone(job.status))),
          element("td", {}, badge(lifecycle, lifecycle === "可永久删除" ? "danger" : lifecycle === "恢复窗口" ? "warning" : "success")),
          element("td", {text: protection}),
          element("td", {text: job.purge_after ? formatDate(job.purge_after) : "—"}),
          element("td", {}, actions),
        ]));
      });
      byId("retention-empty").hidden = items.length !== 0;
      setText("retention-page-label", `第 ${Math.floor(offset / limit) + 1} 页 · 共 ${total} 项`);
      byId("retention-previous").disabled = offset === 0;
      byId("retention-next").disabled = offset + limit >= total;
    }

    async function load() {
      const query = new URLSearchParams({
        state: form.elements.namedItem("state").value,
        limit: String(limit),
        offset: String(offset),
      });
      const search = form.elements.namedItem("query").value.trim();
      if (search) query.set("query", search);
      try {
        const {data} = await api(`/v1/retention/jobs?${query}`);
        render(data.items || [], data.total || 0);
      } catch (error) { toast(errorMessage(error), "error"); }
    }

    form.addEventListener("submit", (event) => { event.preventDefault(); offset = 0; load(); });
    byId("clear-retention-filters").addEventListener("click", () => { form.reset(); offset = 0; load(); });
    byId("retention-previous").addEventListener("click", () => { offset = Math.max(0, offset - limit); load(); });
    byId("retention-next").addEventListener("click", () => { offset += limit; load(); });
    byId("run-retention").addEventListener("click", async () => {
      const confirmed = await confirmAction({
        title: "运行保留期评估？",
        message: "达到保留期且未固定、未处于 legal hold 的任务会进入恢复窗口。",
        confirmLabel: "运行评估",
      });
      if (!confirmed) return;
      const button = byId("run-retention");
      setBusy(button, true, "评估中…");
      try {
        const {data} = await api("/v1/retention/run", {method: "POST", body: {}});
        const result = byId("retention-result");
        result.textContent = `本次隐藏 ${data.hidden.length} 个任务；${data.purge_ready.length} 个任务已满足永久删除时间条件。`;
        result.hidden = false;
        await load();
      } catch (error) { toast(errorMessage(error), "error"); }
      finally { setBusy(button, false); }
    });
    await load();
  }

  const initializers = {
    login: initLogin,
    jobs: initJobs,
    "job-new": initNewJob,
    "job-detail": initJobDetail,
    "review-editorial": initEditorialReview,
    "review-visual": initVisualReview,
    artifacts: initArtifacts,
    health: initHealth,
    "admin-operations": initOperations,
    "admin-members": initMembers,
    "admin-governance": initGovernance,
    "admin-audit": initAudit,
    "admin-retention": initRetention,
  };

  async function start() {
    await loadAuthContext();
    if (initializers[page]) await initializers[page]();
  }

  start().catch((error) => toast(errorMessage(error), "error"));
})();
