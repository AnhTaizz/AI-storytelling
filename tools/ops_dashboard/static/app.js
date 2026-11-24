"use strict";

const STRINGS = {
  vi: {
    brand: "AI Operations", skip: "Bỏ qua menu", menu: "Menu", navigation: "Điều hướng",
    banner: "DỮ LIỆU MẪU — chưa kết nối hệ thống thật", mockEnglish: "MOCK DATA — not connected",
    language: "Ngôn ngữ", theme: "Giao diện", auto: "Tự động", light: "Sáng", dark: "Tối",
    vietnamese: "Tiếng Việt", english: "English",
    overview: "Tổng quan", providers: "Nhà cung cấp", usage: "Mức sử dụng",
    requests: "Lịch sử yêu cầu", "routing-policy": "Quy tắc chọn model", pipeline: "Tiến độ quy trình",
    snapshot: "Cập nhật lúc {time}", loading: "Đang tải…", loadError: "Không tải được dữ liệu.",
    refresh: "Làm mới", dataTime: "Dữ liệu gần nhất {time}", noDataTime: "Chưa có mốc dữ liệu",
    static: "Theo tài liệu nhà cung cấp, kiểm tra ngày {date}", notConfigured: "Chưa cấu hình",
    unobserved: "Chưa có lượt gửi", configuredKeys: "Key đã cấu hình", eligibleKeys: "Key đủ điều kiện",
    scopeCount: "Số phạm vi quota", quotaLimit: "Hạn mức", quotaUsed: "Đã dùng", quotaRemaining: "Còn lại",
    quotaCounters: "Bộ đếm quota đã báo", contextTokens: "Token ngữ cảnh", requestTokens: "Token mỗi yêu cầu",
    previous: "Trang trước", next: "Trang sau", policyHashLive: "SHA-256 của tệp quy tắc",
    calls: "Lần gọi", seconds: "Giây", tokens: "Token", started: "Bắt đầu", updated: "Cập nhật",
    noLiveIncidents: "Chưa ghi nhận sự cố gần đây.", skipReasons: "Lý do bỏ qua",
    RUNNING: "Đang chạy", UNKNOWN: "Không rõ", NOT_RUN: "Chưa chạy",
    STOPPED_AFTER_BRIEF: "Dừng sau bước tóm tắt", STOPPED_AFTER_PLAN: "Dừng sau bước lập dàn ý",
    STOPPED_AFTER_SCRIPT: "Dừng sau bước viết kịch bản", COMPLETED_WITH_FAILURES: "Hoàn thành có lỗi",
    todayTime: "{time} hôm nay", yesterdayTime: "hôm qua {time}", time: "Giờ địa phương",
    timeBucket: "Bắt đầu khoảng thời gian", remainingTime: "còn {duration}", elapsed: "đã hết thời gian chờ",
    healthy: "Hoạt động", cooldown: "Chờ quota", degraded: "Gặp sự cố", critical: "Cần kiểm tra",
    systemGood: "Hệ thống ổn", systemWait: "Hệ thống đang chờ quota",
    systemIssue: "Hệ thống có sự cố", systemCritical: "Hệ thống cần kiểm tra",
    systemCounts: "{status}: {healthy}/{total} nhà cung cấp hoạt động{waiting}{issues}.",
    waitingClause: ", {count} đang chờ quota ({providers})", issueClause: ", {count} cần kiểm tra",
    requestsToday: "Yêu cầu hôm nay", utcDay: "Tính từ đầu ngày UTC, gồm cả lượt bỏ qua",
    successRate: "Tỉ lệ thành công", sentOnly: "Tính trên các lượt đã gửi",
    tokensUsed: "Token đã dùng", estimatedCount: "trong đó {count} ước tính",
    cost: "Chi phí", freeCost: "0 ₫", freeOnly: "Chỉ dùng gói miễn phí", waiting: "Đang chờ quota",
    provider: "Nhà cung cấp", providerHealth: "Tình trạng nhà cung cấp", incidents: "Sự cố gần đây",
    noIncidents: "Chưa có sự cố trong dữ liệu mẫu.", stageRequests: "Yêu cầu theo bước hôm nay",
    noRecords: "Hôm nay chưa có yêu cầu.", stage: "Bước", outcome: "Kết quả", error: "Lỗi",
    latency: "Độ trễ", scope: "Phạm vi quota", model: "Model", cooldownUntil: "Chờ đến",
    lastError: "Lỗi gần nhất", usedLimit: "Đã dùng {used} / {limit} {unit}",
    remaining: "Còn {count} {unit}", projectModelLimit: "Tùy dự án và model",
    rpd: "Yêu cầu mỗi ngày (RPD)", tpm: "Token mỗi phút (TPM)",
    utcRpd: "Yêu cầu miễn phí mỗi ngày UTC", utcNeurons: "Neuron mỗi ngày UTC",
    requestUnit: "yêu cầu", tokenUnit: "token", neuronUnit: "Neuron",
    project: "Dự án", org: "Tổ chức", account: "Tài khoản",
    help: "Giải thích về {topic}", tokenSources: "Nguồn số token",
    tokenHelp: "Thực tế là số nhà cung cấp báo. Ước tính có thể gồm phần dự trữ cho đầu ra. Không rõ nghĩa là thiếu số token.",
    neuronHelp: "Neuron là đơn vị Cloudflare dùng để tính mức sử dụng AI. Mỗi model có mức tính riêng.",
    rateHelp: "TPM là số token mỗi phút. RPD là số yêu cầu mỗi ngày.",
    scopeHelp: "Các lượt dùng trong cùng dự án, tổ chức hoặc tài khoản có thể chia sẻ hạn mức.",
    cooldownHelp: "Thời gian tạm chờ trước khi có thể thử lại với nhà cung cấp.",
    reported: "Thực tế", estimated: "Ước tính", unknown: "Không rõ",
    overviewChart: "Yêu cầu trong 24 giờ qua", tokensChart: "Token theo thời gian",
    requestsChart: "Yêu cầu theo thời gian", last24h: "24 giờ qua", last7d: "7 ngày qua",
    range: "Khoảng thời gian", sharedScale: "Các nhà cung cấp dùng chung thang đo trong mỗi nhóm biểu đồ.",
    unknownRequests: "Ở biểu đồ yêu cầu, màu xám là lượt không có số token.",
    inspectChart: "Trỏ, chạm hoặc dùng phím Tab để xem số liệu.",
    showTable: "Xem dạng bảng", showChart: "Xem biểu đồ", total: "Tổng",
    noRequests: "Không có yêu cầu trong khoảng này.",
    filters: "Bộ lọc yêu cầu", all: "Tất cả", request: "Mã yêu cầu", inOut: "Token vào / ra",
    reasoning: "{count} token suy luận", matching: "Đang xem {shown}/{total} lượt xét chọn",
    noMatches: "Không có yêu cầu phù hợp với bộ lọc.",
    policyVersion: "Cấu hình chỉ đọc · Phiên bản {version}", policyHash: "SHA-256 của cấu hình mẫu",
    stageAssignments: "Quy tắc theo bước", tier: "Nhóm", candidates: "Thứ tự thử model",
    fallback: "Thử nhà cung cấp khác", enabled: "Có", disabled: "Không", reserve: "Token đầu ra dự trữ",
    quality_critical: "Ưu tiên chất lượng", utility: "Tác vụ hỗ trợ", default: "Mặc định",
    brief: "Tóm tắt", brief_check: "Kiểm tra tóm tắt", plan: "Lập dàn ý", script: "Viết kịch bản",
    critic: "Đánh giá", source_check: "Đối chiếu nguồn", revise: "Chỉnh sửa", patch: "Sửa bổ sung",
    progress: "Tiến độ các bước", done: "Đã xong", current: "Đang dừng ở bước này", pending: "Chưa tới",
    resumeAfter: "Có thể tiếp tục sau {time} ({remaining})",
    callLog: "Cộng từ nhật ký lượt gọi", partialCallLog: "Cộng từ một phần nhật ký lượt gọi",
    latestInvocation: "Chỉ tính lần chạy gần nhất", reviewReasons: "Số lý do cần duyệt",
    sourceCheckIncomplete: "Đối chiếu nguồn chưa xong một phần",
    pausedHint: "Khi hết thời gian chờ, dùng lại thư mục đầu ra cũ để giữ các bước đã xong.",
    reviewHint: "Kiểm tra bản chỉnh sửa được đánh dấu trước khi tiếp tục.",
    completeHint: "Cả năm bước đã hoàn thành.", failedHint: "Xem lỗi lập dàn ý trong manifest của lượt chạy.",
    SUCCESS: "Thành công", FAILED: "Thất bại", SKIPPED: "Bỏ qua", COMPLETED: "Đã hoàn thành",
    PAUSED_QUOTA: "Tạm dừng vì hết quota (có thể chạy tiếp)", NEEDS_REVIEW: "Cần người duyệt",
    QUOTA_EXHAUSTED: "Hết quota — tự chạy tiếp khi quota hồi",
    REQUEST_TOO_LARGE: "Yêu cầu quá dài cho model này",
    EDGE_BLOCKED: "Bị tường lửa của nhà cung cấp chặn",
    RATE_LIMIT: "Bị giới hạn tốc độ, đang chờ", AUTH_FAILURE: "Key không hợp lệ",
    SERVER_FAILURE: "Máy chủ nhà cung cấp quá tải",
  },
  en: {
    brand: "AI Operations", skip: "Skip to content", menu: "Menu", navigation: "Dashboard navigation",
    banner: "DỮ LIỆU MẪU — chưa kết nối hệ thống thật", mockEnglish: "MOCK DATA — not connected",
    language: "Language", theme: "Theme", auto: "System", light: "Light", dark: "Dark",
    vietnamese: "Tiếng Việt", english: "English",
    overview: "Overview", providers: "Providers", usage: "Usage",
    requests: "Request history", "routing-policy": "Routing policies", pipeline: "Pipeline monitor",
    snapshot: "Updated {time}", loading: "Loading…", loadError: "Could not load dashboard data.",
    refresh: "Refresh", dataTime: "Latest data {time}", noDataTime: "No data timestamp",
    static: "Provider documentation, checked on {date}", notConfigured: "Not configured",
    unobserved: "No observed calls", configuredKeys: "Configured keys", eligibleKeys: "Eligible keys",
    scopeCount: "Quota scopes", quotaLimit: "Limit", quotaUsed: "Used", quotaRemaining: "Remaining",
    quotaCounters: "Reported quota counters", contextTokens: "Context tokens", requestTokens: "Tokens per request",
    previous: "Previous page", next: "Next page", policyHashLive: "Policy file SHA-256",
    calls: "Calls", seconds: "Seconds", tokens: "Tokens", started: "Started", updated: "Updated",
    noLiveIncidents: "No recent incidents recorded.", skipReasons: "Skip reasons",
    RUNNING: "Running", UNKNOWN: "Unknown", NOT_RUN: "Not run",
    STOPPED_AFTER_BRIEF: "Stopped after brief", STOPPED_AFTER_PLAN: "Stopped after plan",
    STOPPED_AFTER_SCRIPT: "Stopped after script", COMPLETED_WITH_FAILURES: "Completed with failures",
    todayTime: "{time} today", yesterdayTime: "yesterday at {time}", time: "Local time",
    timeBucket: "Time bucket starts", remainingTime: "{duration} left", elapsed: "wait time ended",
    healthy: "Operational", cooldown: "Waiting for quota", degraded: "Degraded", critical: "Needs attention",
    systemGood: "System operational", systemWait: "System waiting for quota",
    systemIssue: "System degraded", systemCritical: "System needs attention",
    systemCounts: "{status}: {healthy}/{total} providers operational{waiting}{issues}.",
    waitingClause: ", {count} waiting for quota ({providers})", issueClause: ", {count} need attention",
    requestsToday: "Requests today", utcDay: "Since the start of the UTC day, including skips",
    successRate: "Success rate", sentOnly: "For requests actually sent",
    tokensUsed: "Tokens used", estimatedCount: "including {count} estimated",
    cost: "Cost", freeCost: "$0", freeOnly: "Free plans only", waiting: "Waiting for quota",
    provider: "Provider", providerHealth: "Provider health", incidents: "Recent incidents",
    noIncidents: "No incidents in this snapshot.", stageRequests: "Requests by stage today",
    noRecords: "No requests today.", stage: "Stage", outcome: "Outcome", error: "Error",
    latency: "Latency", scope: "Quota scope", model: "Model", cooldownUntil: "Wait until",
    lastError: "Last error", usedLimit: "Used {used} / {limit} {unit}",
    remaining: "{count} {unit} left", projectModelLimit: "Varies by project and model",
    rpd: "Requests per day (RPD)", tpm: "Tokens per minute (TPM)",
    utcRpd: "Free requests per UTC day", utcNeurons: "Neurons per UTC day",
    requestUnit: "requests", tokenUnit: "tokens", neuronUnit: "Neurons",
    project: "Project", org: "Organization", account: "Account",
    help: "Help with {topic}", tokenSources: "Token count sources",
    tokenHelp: "Reported counts come from the provider. Estimates can include reserved output. Unknown means the token count is missing.",
    neuronHelp: "Neurons are Cloudflare's AI usage unit. The rate varies by model.",
    rateHelp: "TPM means tokens per minute. RPD means requests per day.",
    scopeHelp: "Usage within the same project, organization, or account can share a limit.",
    cooldownHelp: "How long to wait before trying the provider again.",
    reported: "Reported", estimated: "Estimated", unknown: "Unknown",
    overviewChart: "Requests in the past 24 hours", tokensChart: "Tokens over time",
    requestsChart: "Requests over time", last24h: "Past 24 hours", last7d: "Past 7 days",
    range: "Time range", sharedScale: "Providers share the same scale within each group of charts.",
    unknownRequests: "In request charts, grey means the request has no token count.",
    inspectChart: "Point, tap, or press Tab to see values.",
    showTable: "View as table", showChart: "View chart", total: "Total",
    noRequests: "No requests in this time bucket.",
    filters: "Request filters", all: "All", request: "Request ID", inOut: "Tokens in / out",
    reasoning: "{count} reasoning tokens", matching: "Showing {shown}/{total} candidate records",
    noMatches: "No requests match the filters.",
    policyVersion: "Read-only policy · Version {version}", policyHash: "Mock policy SHA-256",
    stageAssignments: "Rules by stage", tier: "Tier", candidates: "Model attempt order",
    fallback: "Try another provider", enabled: "Yes", disabled: "No", reserve: "Reserved output tokens",
    quality_critical: "Quality critical", utility: "Utility", default: "Default",
    brief: "Brief", brief_check: "Check brief", plan: "Plan", script: "Script",
    critic: "Review", source_check: "Check sources", revise: "Revise", patch: "Patch",
    progress: "Stage progress", done: "Done", current: "Stopped at this stage", pending: "Pending",
    resumeAfter: "Can resume after {time} ({remaining})",
    callLog: "Totals from the call log", partialCallLog: "Totals from a partial call log",
    latestInvocation: "Latest invocation only", reviewReasons: "Review reasons",
    sourceCheckIncomplete: "Source cross-check is partly incomplete",
    pausedHint: "After the wait, reuse the same output directory to keep completed stages.",
    reviewHint: "Review the flagged revision before continuing.",
    completeHint: "All five stages finished.", failedHint: "Inspect the plan failure in the run manifest.",
    SUCCESS: "Successful", FAILED: "Failed", SKIPPED: "Skipped", COMPLETED: "Completed",
    PAUSED_QUOTA: "Paused for quota (can resume)", NEEDS_REVIEW: "Needs human review",
    QUOTA_EXHAUSTED: "Quota exhausted — resumes when quota resets",
    REQUEST_TOO_LARGE: "Request too long for this model",
    EDGE_BLOCKED: "Blocked by the provider's firewall",
    RATE_LIMIT: "Rate limited, waiting", AUTH_FAILURE: "Invalid key",
    SERVER_FAILURE: "Provider server overloaded",
  },
};

const page = document.querySelector("#page");
const heading = document.querySelector("#page-title");
const snapshot = document.querySelector("#snapshot");
const refresh = document.querySelector("#refresh");
const refreshPages = new Set(["overview", "providers", "pipeline"]);
const nav = document.querySelector("#navigation");
const links = [...nav.querySelectorAll("a")];
const menu = document.querySelector("#menu");
const languageSelect = document.querySelector("#language");
const themeSelect = document.querySelector("#theme");
const sources = ["reported", "estimated", "unknown"];
const icons = {good: "✓", warning: "◷", serious: "!", critical: "×"};
const providerStates = {
  Healthy: ["healthy", "good"], Cooldown: ["cooldown", "warning"], Degraded: ["degraded", "serious"],
  NotConfigured: ["notConfigured", "warning"], Unobserved: ["unobserved", "warning"],
};
const outcomeStates = {
  SUCCESS: "good", FAILED: "critical", SKIPPED: "warning",
  COMPLETED: "good", PAUSED_QUOTA: "warning", NEEDS_REVIEW: "serious",
};
const quotaLabels = {
  "Per project and model": "projectModelLimit", "Requests per day": "rpd",
  "Tokens per minute": "tpm", "Free requests per UTC day": "utcRpd", "Neurons per UTC day": "utcNeurons",
};
const quotaUnits = {requests: "requestUnit", tokens: "tokenUnit", Neurons: "neuronUnit"};
const runHints = {
  PAUSED_QUOTA: "pausedHint", NEEDS_REVIEW: "reviewHint", COMPLETED: "completeHint", FAILED: "failedHint",
};
const filters = new URLSearchParams({limit: "50"});
let language = readPreference("language", ["vi", "en"]);
let usageRange = "24h";
let navigation = 0;
let chartId = 0;

function readPreference(key, allowed) {
  try {
    const value = localStorage.getItem("ops-dashboard-" + key);
    if (allowed.includes(value)) return value;
  } catch {
    // Browser storage can be disabled.
  }
  return allowed[0];
}

function savePreference(key, value) {
  try {
    localStorage.setItem("ops-dashboard-" + key, value);
  } catch {
    // Keep the selection for this page even when storage is unavailable.
  }
}

function t(key, values = {}) {
  const strings = STRINGS[language];
  const label = Object.hasOwn(strings, key) ? strings[key] : key;
  return label.replace(/\{(\w+)\}/g, (_, name) => values[name]);
}

function element(tag, attributes = {}, ...children) {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
  node.append(...children);
  return node;
}

function textNumber(value) {
  return value == null ? "—" : new Intl.NumberFormat(language).format(value);
}

function sourcedNumber(value, source, date) {
  const provenance = value == null ? "unknown" : source;
  const description = t(provenance ?? "unknown", {date});
  return value == null ? description : textNumber(value) + " · " + description;
}

function sourceNotices(data) {
  return Object.values(data.source_states ?? {}).map(state => notice(state.message));
}

function telemetryUnavailable(data) {
  const code = data.source_states?.telemetry?.code;
  return code && code !== "telemetry_capped";
}

function timeLabel(value, seconds) {
  const date = new Date(value);
  const now = new Date();
  const yesterday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1);
  const clock = {hour: "2-digit", minute: "2-digit", hourCycle: "h23",
    ...(seconds ? {second: "2-digit"} : {})};
  const time = new Intl.DateTimeFormat(language, clock);
  if (date.toDateString() === now.toDateString()) return t("todayTime", {time: time.format(date)});
  if (date.toDateString() === yesterday.toDateString()) return t("yesterdayTime", {time: time.format(date)});
  return new Intl.DateTimeFormat(language, {
    year: "numeric", month: "short", day: "numeric", ...clock,
  }).format(date);
}

function timeNode(value, seconds = false) {
  if (!value) return "—";
  const utc = new Date(value).toISOString();
  return element("time", {datetime: utc, title: utc}, timeLabel(value, seconds));
}

function timedSentence(key, value, values = {}) {
  const [before, after] = t(key, {...values, time: "\u0000"}).split("\u0000");
  return [before, timeNode(value, key === "snapshot"), after];
}

function relativeTime(value) {
  const seconds = Math.ceil((Date.parse(value) - Date.now()) / 1000);
  if (seconds <= 0) return t("elapsed");
  const [unit, divisor] = seconds >= 3600 ? ["hour", 3600] : seconds >= 60 ? ["minute", 60] : ["second", 1];
  const duration = new Intl.NumberFormat(language, {style: "unit", unit, unitDisplay: "long"})
    .format(Math.ceil(seconds / divisor));
  return t("remainingTime", {duration});
}

function status(label, tone) {
  return element("span", {class: "status " + tone}, element("span", {"aria-hidden": "true"}, icons[tone]), t(label));
}

function technical(value, tone) {
  if (!value) return "—";
  return element("div", {class: "technical"}, tone ? status(value, tone) : t(value),
    element("code", {}, value));
}

function help(topic, message) {
  return element("details", {class: "help"},
    element("summary", {"aria-label": t("help", {topic: t(topic)})}, "?"),
    element("p", {}, t(message)));
}

function table(headers, rows, label, numericFrom = headers.length) {
  const content = element("table", {},
    element("thead", {}, element("tr", {}, ...headers.map((header, index) =>
      element("th", {scope: "col", class: index >= numericFrom ? "numeric" : ""}, header)))),
    element("tbody", {}, ...rows.map(row => element("tr", {}, ...row.map((cell, index) =>
      element("td", {class: index >= numericFrom ? "numeric" : ""}, cell))))));
  const region = element("div", {class: "table-wrap", tabindex: "0", role: "region", "aria-label": label}, content);
  return region;
}

function section(title, ...children) {
  return element("section", {class: "section"}, element("h2", {class: "section-title"}, t(title)), ...children);
}

function detail(label, children, hint) {
  return element("div", {},
    element("dt", {class: "with-help"}, t(label), ...(hint ? [help(label, hint)] : [])),
    element("dd", {}, children));
}

function notice(message, attrs = {}) {
  return element("p", {class: "notice", ...attrs}, t(message));
}

function problem(node) {
  node.replaceChildren(element("p", {class: "problem", role: "alert"}, t("loadError")));
}

async function getData(path) {
  const response = await fetch("/api/" + path);
  if (!response.ok) throw new Error(String(response.status));
  return response.json();
}

function activeCooldown(provider, asOf) {
  return provider.cooldown_until && Date.parse(provider.cooldown_until) > Date.parse(asOf);
}

function overviewStatus(providers, asOf) {
  const cooling = providers.filter(provider => activeCooldown(provider, asOf));
  const healthy = providers.filter(provider => provider.status === "Healthy" && !activeCooldown(provider, asOf)).length;
  const issues = providers.length - healthy - cooling.length;
  let label = "systemGood";
  let tone = "good";
  if (!healthy && (!providers.length || issues)) {
    [label, tone] = ["systemCritical", "critical"];
  } else if (issues) {
    [label, tone] = ["systemIssue", "serious"];
  } else if (cooling.length) {
    [label, tone] = ["systemWait", "warning"];
  }

  const waiting = cooling.length ? t("waitingClause", {
    count: textNumber(cooling.length),
    providers: cooling.map(provider => provider.name + ", " + relativeTime(provider.cooldown_until)).join(" · "),
  }) : "";
  const sentence = t("systemCounts", {
    status: t(label), healthy: textNumber(healthy), total: textNumber(providers.length), waiting,
    issues: issues ? t("issueClause", {count: textNumber(issues)}) : "",
  });
  return element("p", {class: "system-status " + tone}, element("span", {"aria-hidden": "true"}, icons[tone]), sentence);
}

function quotaMeter(quota) {
  const label = quotaLabels[quota.label] ?? quota.label;
  const unit = t(quotaUnits[quota.unit] ?? quota.unit);
  const hint = quota.unit === "Neurons" ? "neuronHelp" : label === "tpm" || label === "rpd" || label === "utcRpd" ? "rateHelp" : null;
  if (quota.sources) {
    const metrics = [
      ["quotaLimit", "limit"], ["quotaUsed", "used"], ["quotaRemaining", "remaining"],
    ].filter(([, key]) => key === "remaining" || quota[key] != null);
    return element("div", {class: "quota"},
      element("strong", {}, t(label)), ...(hint ? [help(label, hint)] : []),
      ...metrics.map(([title, key]) => element("p", {class: "muted"},
        t(title) + " · " + sourcedNumber(quota[key], quota.sources[key], quota.verified_on))));
  }
  const known = quota.used != null && quota.limit > 0;
  const used = t("usedLimit", {used: textNumber(quota.used), limit: textNumber(quota.limit), unit});
  return element("div", {class: "quota"},
    element("div", {class: "with-help"}, element("strong", {}, t(label)), ...(hint ? [help(label, hint)] : [])),
    ...(known ? [element("p", {}, used),
      element("progress", {max: quota.limit, value: quota.used, "aria-label": t(label) + " · " + used}),
      element("p", {class: "muted"}, t("remaining", {count: textNumber(quota.remaining), unit}) + " · " + t(quota.source))]
      : [element("p", {class: "muted"}, t("unknown"))]));
}

function providerCard(provider, compact) {
  const [label, tone] = providerStates[provider.status] ?? ["critical", "critical"];
  const until = provider.cooldown_until;
  const wait = until ? element("span", {}, timeNode(until), " · " + relativeTime(until)) : "—";
  const headingTag = compact ? "h3" : "h2";
  const limits = compact && !provider.configuration
    ? provider.limits.filter(quota => quotaLabels[quota.label] !== "tpm") : provider.limits;
  const configuration = provider.configuration;
  const modelDetails = provider.model_details?.map(model => element("li", {},
    element("code", {}, model.model), element("small", {class: "muted"},
      " · " + t(model.source, {date: model.verified_on})),
    ...[["contextTokens", "context_tokens"], ["requestTokens", "max_request_tokens"]].map(([key, field]) =>
      element("div", {}, t(key) + " · " + sourcedNumber(model[field], model.sources[field], model.verified_on)))));
  return element("article", {class: "panel provider-card", "data-provider": provider.slug},
    element("div", {class: "card-head"}, element(headingTag, {}, provider.name), status(label, tone)),
    ...limits.map(quotaMeter),
    ...(compact && !until ? [] : [element("dl", {class: "detail-list"},
      detail("cooldownUntil", wait, "cooldownHelp"),
      ...(compact ? [] : [
        detail("scope", technical(provider.scope), "scopeHelp"),
        detail("model", element("ul", {class: "model-list"}, ...(modelDetails ?? provider.models.map(model =>
          element("li", {}, element("code", {}, model)))))),
        detail("lastError", technical(provider.last_error)),
        ...(configuration ? [
          ...(configuration.status === "not_configured" && provider.status !== "NotConfigured"
            ? [element("div", {class: "muted"}, t("notConfigured"))] : []),
          ...[["configuredKeys", "keys_configured"], ["eligibleKeys", "keys_eligible"],
            ["scopeCount", "key_scopes"]].map(([title, key]) =>
            detail(title, sourcedNumber(configuration[key], configuration.source))),
          detail("quotaCounters", provider.quota_counters.length ? element("ul", {class: "model-list"},
            ...provider.quota_counters.map(counter => element("li", {},
              [counter.name, counter.model, t(counter.scope ?? "unknown"),
                sourcedNumber(counter.value, counter.source)].filter(Boolean).join(" · "),
              " · ", timeNode(counter.timestamp)))) : t("unknown")),
          ...provider.blocks.map(block => detail("cooldownUntil", element("div", {},
            [block.model, block.scope_ref, block.reason].filter(Boolean).join(" · "), " · ", timeNode(block.until_utc)))),
        ] : []),
      ]))]));
}

function overview(data, providerData, history) {
  const today = data.today;
  const tokens = today.tokens_by_source;
  const success = today.success_rate == null ? "—" : new Intl.NumberFormat(language, {
    style: "percent", maximumFractionDigits: 1,
  }).format(today.success_rate);
  const cost = data.estimated_cost_usd;
  const live = data.data_mode === "live";
  const dailyCost = ["reported", "estimated"].flatMap(source => today.cost_by_source[source] == null
    ? [] : ["$" + sourcedNumber(today.cost_by_source[source], source)]).join(" · ");
  const metrics = live ? [
    ["requestsToday", telemetryUnavailable(data) ? t("unknown") :
      sourcedNumber(today.requests, today.sources.requests), t("utcDay")],
    ["successRate", success, t(today.sources.success_rate)],
    ["tokensUsed", tokens.reported || tokens.estimated ? textNumber(tokens.reported) + " " + t("reported") + " · " +
      textNumber(tokens.estimated) + " " + t("estimated") : t("unknown"), ""],
    ["cost", dailyCost || t("unknown"), ""],
    ["waiting", sourcedNumber(data.active_cooldowns, data.sources.active_cooldowns), ""],
  ] : [
    ["requestsToday", textNumber(today.requests), t("utcDay")],
    ["successRate", success, t("sentOnly")],
    ["tokensUsed", textNumber(tokens.reported + tokens.estimated), t("estimatedCount", {count: textNumber(tokens.estimated)})],
    ["cost", cost === 0 ? t("freeCost") : cost == null ? "—" : "$" + textNumber(cost), cost === 0 ? t("freeOnly") : ""],
    ["waiting", textNumber(data.active_cooldowns), ""],
  ];
  const {fields} = data;
  const incidents = data.incidents.map(row => [
    timeNode(row[fields.timestamp]), displayProvider(row[fields.provider]), technical(row[fields.stage]),
    technical(row[fields.outcome], outcomeStates[row[fields.outcome]]), technical(row[fields.error]),
  ]);
  const mix = Object.entries(today.stage_provider_mix).sort(([a], [b]) => a.localeCompare(b))
    .map(([stage, counts]) => [technical(stage), ...data.providers.map(provider => live
      ? sourcedNumber(counts[provider.slug] ?? 0, today.sources.stage_provider_mix)
      : textNumber(counts[provider.slug] ?? 0))]);
  const latency = ["p50", "p95"].map(key => key + " " +
    (today.latency[key] == null ? "—" : textNumber(today.latency[key]) + " ms" +
      (live ? " · " + t(today.sources.latency) : "")));
  return [
    ...sourceNotices(data),
    overviewStatus(providerData.providers, data.generated_at),
    element("div", {class: "cards metrics"}, ...metrics.map(([label, value, note]) =>
      element("article", {class: "panel metric"},
        element("div", {class: "with-help"}, element("h2", {}, t(label)),
          ...(label === "tokensUsed" ? [help("tokenSources", "tokenHelp")] : [])),
        element("strong", {}, value), ...(note ? [element("small", {}, note)] : [])))),
    section("providerHealth", element("div", {class: "cards health"},
      ...providerData.providers.map(provider => providerCard(provider, true)))),
    ...(telemetryUnavailable(history) ? [] : [overviewChart(history)]),
    section("incidents", incidents.length
      ? table(["time", "provider", "stage", "outcome", "error"].map(key => t(key)), incidents, t("incidents"))
      : notice(live ? "noLiveIncidents" : "noIncidents")),
    section("stageRequests", element("p", {class: "notice"}, t("latency") + " · " + latency.join(" · ")),
      mix.length ? table([t("stage"), ...data.providers.map(provider => provider.name)], mix, t("stageRequests"), 1)
        : notice("noRecords")),
    ...(live && Object.keys(today.skip_reason_counts).length ? [section("skipReasons",
      element("ul", {class: "model-list"}, ...Object.entries(today.skip_reason_counts).map(([reason, count]) =>
        element("li", {}, reason + " · " + sourcedNumber(count, today.sources.skip_reason_counts)))))] : []),
  ];
}

function providers(data) {
  return [...sourceNotices(data), element("div", {class: "cards"},
    ...data.providers.map(provider => providerCard(provider, false)))];
}

function displayProvider(slug) {
  return {gemini: "Gemini", groq: "Groq", openrouter: "OpenRouter", cloudflare: "Cloudflare"}[slug] ?? slug ?? "—";
}


function sum(values) {
  return Object.values(values).reduce((total, value) => total + (value ?? 0), 0);
}

function legend(items, extra = []) {
  return element("div", {class: "legend"}, ...items.map(([label, provider, style]) =>
    element("span", {}, element("i", {
      class: "swatch " + style, "data-provider": provider, "aria-hidden": "true",
    }), label)), ...extra);
}

function shape(svg, tag, attrs, parent = svg) {
  const node = document.createElementNS(svg.namespaceURI, tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  parent.append(node);
  return node;
}

const plotHeight = 128;

function plotBar(segments, max) {
  const svg = document.querySelector("#chart-template").content.firstElementChild.cloneNode(true);
  const id = "bar-" + ++chartId;
  const total = segments.reduce((n, segment) => n + (segment.value ?? 0), 0);
  if (!total) return svg;

  const defs = shape(svg, "defs", {});
  const clip = shape(svg, "clipPath", {id}, defs);
  const top = plotHeight - total / max * plotHeight;
  shape(svg, "rect", {x: 0, y: top, width: "100%", height: plotHeight - top + 4, rx: 4}, clip);
  const stack = shape(svg, "g", {"clip-path": "url(#" + id + ")"});
  let bottom = plotHeight;
  for (const {provider, source, value} of segments) {
    if (!value) continue;
    const height = value / max * plotHeight;
    bottom -= height;
    const attrs = {"data-provider": provider, class: "bar " + (source ?? "provider-total")};
    if (source === "estimated") {
      const hatch = shape(svg, "pattern", {
        id: id + "-hatch", width: 6, height: 6, patternUnits: "userSpaceOnUse",
        patternTransform: "rotate(45)", "data-provider": provider,
      }, defs);
      shape(svg, "path", {class: "hatch-line", d: "M 0 0 V 6"}, hatch);
      attrs.fill = "url(#" + id + "-hatch)";
    }
    shape(svg, "rect", {...attrs, x: 0, y: bottom, width: "100%", height}, stack);
  }
  return svg;
}

function breakdown(series) {
  return [t("total") + " " + textNumber(sum(series)),
    ...sources.map(source => t(source) + " " + textNumber(series[source]))].join(" · ");
}

function chart({label, buckets, max, tableHeaders, rows}) {
  const plot = element("div", {class: "plot"});
  const shortTime = new Intl.DateTimeFormat(language, buckets.length === 24
    ? {hour: "2-digit", minute: "2-digit", hourCycle: "h23"}
    : {month: "short", day: "numeric"});
  const ticks = [buckets[0], buckets[Math.floor(buckets.length / 2)], buckets.at(-1)];
  const feedback = element("div", {class: "chart-feedback"}, notice("inspectChart"));
  let focused = null;

  function show(bucket) {
    feedback.replaceChildren(bucket
      ? element("div", {class: "chart-tooltip", role: "tooltip"}, timeNode(bucket.start),
        element("ul", {}, ...bucket.describe.map(line => element("li", {}, line))))
      : notice("inspectChart"));
  }

  for (const bucket of buckets) {
    const button = element("button", {
      type: "button", class: "plot-target", "aria-label": [timeLabel(bucket.start), ...bucket.describe].join(" · "),
    }, plotBar(bucket.segments, max));
    button.addEventListener("pointerenter", () => show(bucket));
    button.addEventListener("pointerleave", () => show(focused));
    button.addEventListener("focus", () => { focused = bucket; show(bucket); });
    button.addEventListener("blur", () => { focused = null; show(null); });
    button.addEventListener("click", () => show(bucket));
    plot.append(button);
  }
  const graph = element("div", {class: "graph", role: "group", "aria-label": label},
    element("div", {class: "y-axis", "aria-hidden": "true"},
      ...[max, max / 2, 0].map(value => element("span", {}, textNumber(value)))),
    plot,
    element("div", {class: "x-axis", "aria-hidden": "true"},
      ...ticks.map(bucket => element("span", {}, shortTime.format(new Date(bucket.start))))),
    feedback);
  const id = "chart-table-" + ++chartId;
  const alternative = element("div", {id, hidden: ""}, table(tableHeaders, rows, label, 2));
  const toggle = element("button", {type: "button", "aria-expanded": "false", "aria-controls": id}, t("showTable"));
  toggle.addEventListener("click", () => {
    const expanded = alternative.hidden;
    alternative.hidden = !expanded;
    graph.hidden = expanded;
    toggle.setAttribute("aria-expanded", String(expanded));
    toggle.textContent = t(expanded ? "showChart" : "showTable");
  });
  return element("div", {class: "chart"},
    element("div", {class: "chart-controls"}, toggle), graph, alternative);
}

function chartMax(value) {
  // Use an even ceiling so both the midpoint and upper tick are whole counts.
  const step = Math.max(2, 2 * 10 ** (Math.floor(Math.log10(Math.max(1, value))) - 1));
  return Math.max(2, Math.ceil(value / step) * step);
}

function overviewChart(data) {
  const buckets = data.buckets.map(bucket => {
    const segments = data.providers.map(({slug}) => ({provider: slug, value: sum(bucket.providers[slug].requests)}));
    const describe = data.providers.filter(({slug}) => sum(bucket.providers[slug].requests) > 0)
      .map(({slug, name}) => name + " · " + breakdown(bucket.providers[slug].requests));
    return {start: bucket.start, segments, describe: describe.length ? describe : [t("noRequests")]};
  });
  const max = chartMax(Math.max(...buckets.map(bucket => bucket.segments.reduce((n, segment) => n + segment.value, 0))));
  const headers = [t("timeBucket"), t("provider"), t("total"), ...sources.map(source => t(source))];
  const rows = data.buckets.flatMap(bucket => data.providers.map(({slug, name}) => {
    const series = bucket.providers[slug].requests;
    return [timeNode(bucket.start), name, textNumber(sum(series)), ...sources.map(source => textNumber(series[source]))];
  }));
  return section("overviewChart", element("div", {class: "panel"},
    legend(data.providers.map(({name, slug}) => [name, slug, "provider-total"]), [help("tokenSources", "tokenHelp")]),
    chart({label: t("overviewChart"), buckets, max, tableHeaders: headers, rows})));
}

function usage(data, current) {
  const controls = element("div", {class: "controls", role: "group", "aria-label": t("range")});
  for (const [range, key] of [["24h", "last24h"], ["7d", "last7d"]]) {
    const button = element("button", {type: "button", "aria-pressed": String(data.range === range)}, t(key));
    button.addEventListener("click", async () => {
      if (usageRange === range) return;
      usageRange = range;
      for (const peer of controls.children) peer.setAttribute("aria-pressed", String(peer === button));
      region.replaceChildren(notice("loading", {role: "status"}));
      const request = ++revision;
      try {
        const updated = await getData("usage?range=" + range);
        if (current === navigation && request === revision) drawUsage(updated, region);
      } catch {
        if (current === navigation && request === revision) {
          usageRange = null;
          problem(region);
        }
      }
    });
    controls.append(button);
  }
  const region = element("div");
  let revision = 0;
  drawUsage(data, region);
  return [controls, notice("sharedScale"), notice("unknownRequests"), region];
}

function drawUsage(data, region) {
  region.replaceChildren(...sourceNotices(data), ...(telemetryUnavailable(data) ? [] : ["tokens", "requests"].map(metric => {
    const title = metric === "tokens" ? "tokensChart" : "requestsChart";
    const max = chartMax(Math.max(...data.buckets.flatMap(bucket =>
      data.providers.map(({slug}) => sum(bucket.providers[slug][metric])))));
    return section(title, element("div", {class: "usage-grid"}, ...data.providers.map(({slug, name}) => {
      const buckets = data.buckets.map(bucket => {
        const series = bucket.providers[slug][metric];
        return {start: bucket.start,
          segments: sources.map(source => ({provider: slug, source, value: series[source]})),
          describe: [name + " · " + breakdown(series)]};
      });
      const rows = data.buckets.map(bucket => {
        const series = bucket.providers[slug][metric];
        return [timeNode(bucket.start), name, textNumber(sum(series)), ...sources.map(source => textNumber(series[source]))];
      });
      const tableHeaders = [t("timeBucket"), t("provider"), t("total"), ...sources.map(source => t(source))];
      return element("article", {class: "panel", "data-provider": slug},
        element("h3", {}, name),
        legend(sources.map(source => [t(source), slug, source]), [help("tokenSources", "tokenHelp")]),
        chart({label: name + " · " + t(title), buckets, max, tableHeaders, rows}));
    })));
  })));
}

function drawRequests(data, region, changePage) {
  const {fields} = data;
  const rows = data.requests.map(row => [
    timeNode(row[fields.timestamp]), element("code", {}, row[fields.request]),
    displayProvider(row[fields.provider]), technical(row[fields.stage]),
    technical(row[fields.outcome], outcomeStates[row[fields.outcome]]),
    row[fields.latency] == null ? "—" : textNumber(row[fields.latency]) + " ms" +
      (row.sources ? " · " + t(row.sources.latency_ms) : ""),
    element("div", {}, element("strong", {}, t(row[fields.tokenSource])),
      element("div", {}, textNumber(row[fields.input]) + " / " + textNumber(row[fields.output])),
      ...(row[fields.reasoning] == null ? [] : [element("small", {}, t("reasoning", {
        count: textNumber(row[fields.reasoning]),
      }))])),
    technical(row[fields.error]),
    ...(data.data_mode === "live" ? [
      element("code", {}, row[fields.model] ?? "—"),
      sourcedNumber(row[fields.reportedCost] ?? row[fields.estimatedCost], row[fields.costSource]),
      JSON.parse(row[fields.skipReasons] ?? "[]").join(" · ") || "—",
    ] : []),
  ]);
  const pages = element("div", {class: "controls"});
  if (data.offset > 0 || data.next_offset != null) {
    for (const [title, offset] of [["previous", data.offset > 0 ? Math.max(0, data.offset - data.limit) : null],
      ["next", data.next_offset]]) {
      const button = element("button", {type: "button"}, t(title));
      button.disabled = offset == null;
      button.addEventListener("click", () => changePage(offset));
      pages.append(button);
    }
  }
  region.replaceChildren(...sourceNotices(data), element("p", {class: "notice", role: "status"}, rows.length
    ? t("matching", {shown: textNumber(rows.length), total: textNumber(data.matching)}) : t("noMatches")),
  ...(rows.length ? [table(
    [t("time"), t("request"), t("provider"), t("stage"), t("outcome"), t("latency"),
      element("span", {class: "with-help"}, t("inOut"), help("tokenSources", "tokenHelp")), t("error"),
      ...(data.data_mode === "live" ? [t("model"), t("cost") + " (USD)", t("skipReasons")] : [])],
    rows, t("requests"))] : []), ...(pages.childElementCount ? [pages] : []));
}

function requests(data, current) {
  const region = element("div");
  const controls = element("div", {class: "controls", role: "group", "aria-label": t("filters")});
  let revision = 0;
  for (const key of ["provider", "stage", "outcome"]) {
    const select = element("select", {name: key}, element("option", {value: ""}, t("all")),
      ...data.options[key].map(value => element("option", {value}, key === "provider" ? displayProvider(value) : t(value))));
    select.value = filters.get(key) ?? "";
    controls.append(element("label", {class: "field"}, t(key), select));
  }
  async function changePage(offset) {
    const selected = ++revision;
    filters.set("offset", offset);
    region.replaceChildren(notice("loading", {role: "status"}));
    try {
      const updated = await getData("requests?" + filters);
      if (current === navigation && selected === revision) drawRequests(updated, region, changePage);
    } catch {
      if (current === navigation && selected === revision) problem(region);
    }
  }
  controls.addEventListener("change", ({target}) => {
    if (target.value) filters.set(target.name, target.value);
    else filters.delete(target.name);
    changePage(0);
  });
  drawRequests(data, region, changePage);
  return [controls, region];
}

function routingPolicy(data) {
  if (data.version == null) return sourceNotices(data);
  const rows = Object.entries(data.stages).filter(([, name]) => Object.hasOwn(data.tiers, name)).map(([stage, name]) => {
    const tier = data.tiers[name];
    const candidates = element("ol", {class: "model-list"},
      ...tier.candidates.filter(Boolean).map(candidate => element("li", {}, element("code", {}, candidate))));
    return [technical(stage), technical(name), candidates, t(tier.cross_provider_fallback ? "enabled" : "disabled"),
      tier.source ? sourcedNumber(tier.max_output_tokens, tier.source) : textNumber(tier.max_output_tokens)];
  });
  return [
    element("div", {class: "panel"}, element("h2", {}, t("policyVersion", {version: data.version})),
      notice(data.data_mode === "live" ? "policyHashLive" : "policyHash"), element("code", {}, data.sha256)),
    section("stageAssignments", table(["stage", "tier", "candidates", "fallback", "reserve"].map(key => t(key)),
      rows, t("stageAssignments"), 4)),
  ];
}

function pipeline(data) {
  return [...sourceNotices(data), element("div", {class: "run-list"}, ...data.runs.map(run => {
    const header = element("div", {class: "card-head"}, element("h2", {class: "mono"}, run.label ?? run.id ?? "—"),
      technical(run.status, outcomeStates[run.status]));
    if (run.label) return element("article", {class: "panel"}, header);
    const live = data.data_mode === "live";
    return element("article", {class: "panel"}, header,
      ...(run.completed ? [element("ol", {class: "stages", "aria-label": t("progress")}, ...data.stages.map(stage => {
        const stageInfo = run.stages?.[stage];
        const state = run.completed.includes(stage) ? "done" : run.current === stage ? "current" : "pending";
        const mark = {done: "✓", current: "◉", pending: "○"}[state];
        return element("li", {class: state, "aria-label": t(stage) + " · " + t(state),
          ...(state === "current" ? {"aria-current": "step"} : {})},
        element("span", {"aria-hidden": "true"}, mark), technical(stage),
        ...(stageInfo ? [element("small", {class: "muted"}, t(stageInfo.status) + " · " +
          sourcedNumber(stageInfo.seconds, stageInfo.source))] : []));
      }))] : []),
      ...(run.totals_scope ? [element("p", {class: "muted"}, t(run.totals_scope))] : []),
      ...(live ? [element("dl", {class: "detail-list"},
        ...["calls", "tokens", "seconds"].map(key => detail(key, sourcedNumber(run[key], run.sources[key]))),
        ...(run.review_reasons_count == null ? [] : [detail("reviewReasons",
          sourcedNumber(run.review_reasons_count, run.sources.review_reasons_count))]),
        ...(run.model || run.provider ? [detail("model", [run.provider, run.model].filter(Boolean).join(" · "))] : []),
        ...(run.error_code ? [detail("error", technical(run.error_code))] : []),
        ...(run.started_at ? [detail("started", timeNode(run.started_at))] : []),
        detail("updated", timeNode(run.updated_at)))] : []),
      ...(run.note ? [notice("sourceCheckIncomplete")] : []),
      ...(!live || ["PAUSED_QUOTA", "NEEDS_REVIEW"].includes(run.status) ?
        [element("p", {class: "muted"}, runHints[run.status] ? t(runHints[run.status]) : run.hint ?? "")] : []),
      ...(run.resume_at ? [element("p", {class: "notice"},
        ...timedSentence("resumeAfter", run.resume_at, {remaining: relativeTime(run.resume_at)}))] : []));
  }))];
}

const routes = {
  overview, providers, usage, requests, "routing-policy": routingPolicy, pipeline,
};

let refreshable = false;
let loading = false;

function showMode(data, key) {
  const live = data.data_mode === "live";
  document.querySelector("#mock-banner").hidden = live;
  document.querySelector("#mock-label").hidden = live;
  document.querySelector("#live-banner").hidden = !live;
  const dataTime = document.querySelector("#data-time");
  dataTime.hidden = !live;
  dataTime.replaceChildren(...(data.last_data_at
    ? timedSentence("dataTime", data.last_data_at) : [t("noDataTime")]));
  refreshable = live && refreshPages.has(key);
  refresh.hidden = !refreshable;
}

async function route(moveFocus = false, updating = false) {
  const hash = location.hash.slice(1);
  const key = Object.hasOwn(routes, hash) ? hash : "overview";
  const current = ++navigation;
  loading = true;
  refresh.disabled = true;
  heading.textContent = t(key);
  document.title = t(key) + " | " + t("brand");
  if (!updating) snapshot.textContent = "";
  for (const link of links) {
    if (link.hash === "#" + key) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
  if (moveFocus) heading.focus();
  if (!updating) page.replaceChildren(notice("loading", {role: "status"}));
  try {
    const path = key === "usage" ? "usage?range=" + (usageRange ?? "24h")
      : key === "requests" ? "requests?" + filters : key;
    const [data, providerData, history] = await Promise.all(key === "overview"
      ? [getData(path), getData("providers"), getData("usage?range=24h")]
      : [getData(path)]);
    if (current !== navigation) return;
    if (key === "usage") usageRange = data.range;
    showMode(data, key);
    snapshot.replaceChildren(...timedSentence("snapshot", data.generated_at));
    const content = key === "overview" ? overview(data, providerData, history) : routes[key](data, current);
    page.replaceChildren(...content);
  } catch {
    if (current === navigation) problem(page);
  } finally {
    if (current === navigation) {
      loading = false;
      refresh.disabled = false;
    }
  }
}

function applyLanguage() {
  document.documentElement.lang = language;
  languageSelect.value = language;
  languageSelect.setAttribute("aria-label", t("language"));
  themeSelect.setAttribute("aria-label", t("theme"));
  nav.setAttribute("aria-label", t("navigation"));
  document.querySelectorAll("[data-string]").forEach(node => { node.textContent = t(node.dataset.string); });
  route();
}

function setMenu(open) {
  menu.setAttribute("aria-expanded", String(open));
}

menu.addEventListener("click", () => setMenu(menu.getAttribute("aria-expanded") === "false"));
nav.addEventListener("click", event => {
  if (!event.target.closest("a")) return;
  setMenu(false);
  if (event.target.closest("a").hash === location.hash) heading.focus();
});
document.querySelector(".sidebar").addEventListener("keydown", event => {
  if (event.key === "Escape" && menu.getAttribute("aria-expanded") === "true") {
    setMenu(false);
    menu.focus();
  }
});
document.querySelector(".skip-link").addEventListener("click", event => {
  event.preventDefault();
  document.querySelector("#main").focus();
});
window.addEventListener("hashchange", () => {
  setMenu(false);
  route(true);
});
refresh.addEventListener("click", () => route(false, true));
setInterval(() => {
  if (refreshable && !document.hidden && !loading) route(false, true);
}, 30_000);

themeSelect.value = readPreference("theme", ["auto", "light", "dark"]);
document.documentElement.dataset.theme = themeSelect.value;
themeSelect.addEventListener("change", () => {
  document.documentElement.dataset.theme = themeSelect.value;
  savePreference("theme", themeSelect.value);
});
languageSelect.addEventListener("change", () => {
  language = languageSelect.value;
  savePreference("language", language);
  applyLanguage();
});
applyLanguage();
