"use strict";

const page = document.querySelector("#page");
const heading = document.querySelector("#page-title");
const snapshot = document.querySelector("#snapshot");
const links = [...document.querySelectorAll("nav a")];
const number = new Intl.NumberFormat("en");
const percent = new Intl.NumberFormat("en", {style: "percent", maximumFractionDigits: 1});
const utc = new Intl.DateTimeFormat("en-GB", {
  timeZone: "UTC", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
});
const sources = ["reported", "estimated", "unknown"];
let navigation = 0;

function element(tag, attributes = {}, ...children) {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
  node.append(...children);
  return node;
}

function textNumber(value) {
  return value == null ? "—" : number.format(value);
}

function utcTime(value) {
  return value ? utc.format(new Date(value)) + " UTC" : "—";
}

function relativeTime(value) {
  const seconds = Math.round((Date.parse(value) - Date.now()) / 1000);
  const unit = Math.abs(seconds) >= 3600 ? "hour" : Math.abs(seconds) >= 60 ? "minute" : "second";
  const divisor = {hour: 3600, minute: 60, second: 1}[unit];
  return new Intl.RelativeTimeFormat("en", {numeric: "auto"}).format(Math.round(seconds / divisor), unit);
}

function chip(value) {
  const styles = {
    Healthy: "good", Cooldown: "warn", Degraded: "warn",
    SUCCESS: "good", FAILED: "bad", SKIPPED: "warn",
    COMPLETED: "good", PAUSED_QUOTA: "warn", NEEDS_REVIEW: "warn",
    reported: "good", estimated: "estimate",
  };
  return element("span", {class: "chip " + (styles[value] ?? "")}, value);
}

function table(headers, rows, label) {
  return element("div", {class: "table-wrap", tabindex: "0", role: "region", "aria-label": label},
    element("table", {},
      element("thead", {}, element("tr", {}, ...headers.map(header => element("th", {scope: "col"}, header)))),
      element("tbody", {}, ...rows.map(row => element("tr", {},
        ...row.map(cell => element("td", {}, cell)))))));
}

function section(title, ...children) {
  return element("section", {class: "section"}, element("h2", {class: "section-title"}, title), ...children);
}

function detail(label, ...children) {
  return element("div", {}, element("dt", {}, label), element("dd", {}, ...children));
}

function problem(node, message) {
  node.replaceChildren(element("p", {class: "problem", role: "alert"}, message));
}

async function getData(path) {
  const response = await fetch("/api/" + path);
  if (!response.ok) throw new Error("Dashboard request failed (" + response.status + ").");
  return response.json();
}

function overview(data) {
  const today = data.today;
  const tokens = today.tokens_by_source;
  const metrics = [
    ["Requests today", textNumber(today.requests), "Candidate records since 00:00 UTC"],
    ["Success rate", today.success_rate == null ? "—" : percent.format(today.success_rate), "Among dispatched candidates"],
    ["Tokens", textNumber(tokens.reported + tokens.estimated), textNumber(tokens.estimated) + " estimated"],
    ["Est. cost", data.estimated_cost_usd == null ? "—" : "$" + data.estimated_cost_usd.toFixed(2), "Free-tier mock scenario"],
    ["Active cooldowns", textNumber(data.active_cooldowns), "Provider snapshots"],
  ];
  const {fields} = data;
  const incidents = data.incidents.map(row => [
    element("span", {class: "nowrap"}, utcTime(row[fields.timestamp])), row[fields.provider],
    row[fields.stage], chip(row[fields.outcome]), element("code", {}, row[fields.error]),
  ]);
  const mix = Object.entries(today.stage_provider_mix).sort(([a], [b]) => a.localeCompare(b))
    .map(([stage, counts]) => [stage, ...data.providers.map(provider => textNumber(counts[provider.slug] ?? 0))]);
  const latency = ["p50", "p95"].map(key =>
    key + " " + (today.latency[key] == null ? "—" : textNumber(today.latency[key]) + " ms"));
  return [
    element("div", {class: "cards metrics"}, ...metrics.map(([label, value, note]) =>
      element("article", {class: "panel metric"}, element("h2", {}, label),
        element("strong", {}, value), element("small", {}, note)))),
    section("Provider health", element("div", {class: "cards health"}, ...data.providers.map(provider =>
      element("article", {class: "panel"}, element("h3", {}, provider.name), chip(provider.status))))),
    section("Recent incidents", incidents.length
      ? table(["Time", "Provider", "Stage", "Outcome", "Error code"], incidents, "Recent incidents")
      : element("p", {class: "notice"}, "No incidents in this snapshot.")),
    section("Requests by stage today", element("p", {class: "notice"}, "Latency · " + latency.join(" · ")),
      mix.length ? table(["Stage", ...data.providers.map(provider => provider.name)], mix, "Requests by stage")
        : element("p", {class: "notice"}, "No candidate records today.")),
  ];
}

function providers(data) {
  return [element("div", {class: "cards"}, ...data.providers.map(provider => {
    const quotas = provider.limits.map(quota => {
      const capacity = quota.limit == null ? "Varies by project and model" : textNumber(quota.limit) + " " + quota.unit;
      const quotaBar = quota.used == null ? [] : [element("progress",
        {value: quota.used, max: quota.limit, "aria-label": quota.label + " used"})];
      return element("div", {class: "quota"}, element("h3", {}, quota.label),
        element("p", {}, capacity), ...quotaBar,
        element("p", {class: "muted"}, "Used " + textNumber(quota.used) + " · Remaining " + textNumber(quota.remaining) + " ", chip(quota.source)));
    });
    return element("article", {class: "panel"},
      element("div", {class: "card-head"}, element("h2", {}, provider.name), chip(provider.status)),
      element("dl", {class: "detail-list"}, detail("Quota scope", provider.scope),
        detail("Models", element("ul", {class: "model-list"}, ...provider.models.map(model =>
          element("li", {}, element("code", {}, model))))),
        detail("Cooldown until", provider.cooldown_until
          ? utcTime(provider.cooldown_until) + " (" + relativeTime(provider.cooldown_until) + ")" : "—"),
        detail("Last error", element("code", {}, provider.last_error ?? "—"))),
      ...quotas);
  }))];
}

function chart(metric, provider, buckets) {
  const svg = document.querySelector("#chart-template").content.firstElementChild.cloneNode(true);
  const total = values => sources.reduce((sum, source) => sum + (values[source] ?? 0), 0);
  const points = buckets.map(bucket => bucket.providers[provider.slug][metric]);
  const max = Math.max(1, ...points.map(total));
  const width = 270 / points.length;
  const hatch = provider.slug + "-" + metric + "-hatch";
  svg.setAttribute("class", "chart");
  svg.setAttribute("aria-label", provider.name + " " + metric + " by time bucket, stacked by token source");
  function draw(parent, tag, attrs, label) {
    const shape = document.createElementNS(svg.namespaceURI, tag);
    for (const [key, value] of Object.entries(attrs)) shape.setAttribute(key, value);
    if (label != null) shape.textContent = label;
    parent.append(shape);
    return shape;
  }
  const pattern = draw(draw(svg, "defs", {}), "pattern",
    {id: hatch, width: 5, height: 5, patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)"});
  draw(pattern, "rect", {class: "hatch-bg", width: 5, height: 5});
  draw(pattern, "path", {class: "hatch-line", d: "M 0 0 V 5"});
  for (const [y, value] of [[12, max], [86, 0]]) {
    draw(svg, "line", {class: "guide", x1: 43, x2: 313, y1: y, y2: y});
    draw(svg, "text", {x: 38, y: y + 3, "text-anchor": "end"}, textNumber(value));
  }
  points.forEach((point, index) => {
    let bottom = 86;
    const x = 43 + index * width;
    sources.forEach(source => {
      const value = point[source];
      if (!value) return;
      const height = value / max * 74;
      bottom -= height;
      const attrs = source === "estimated" ? {fill: "url(#" + hatch + ")"} : {class: source};
      const bar = draw(svg, "rect", {...attrs, x: x + 1, y: bottom, width: width - 2, height});
      draw(bar, "title", {}, utcTime(buckets[index].start) + " · " + source + " · " + textNumber(value));
    });
  });
  const shortDate = new Intl.DateTimeFormat("en-GB", buckets.length === 24
    ? {timeZone: "UTC", hour: "2-digit", minute: "2-digit"}
    : {timeZone: "UTC", day: "numeric", month: "short"});
  const ticks = [0, Math.floor(points.length / 2), points.length - 1];
  ticks.forEach((index, i) => draw(svg, "text",
    {x: [43, 178, 313][i], y: 103, "text-anchor": ["start", "middle", "end"][i]},
    shortDate.format(new Date(buckets[index].start))));
  const breakdown = sources.filter(source => metric === "requests" || source !== "unknown")
    .map(source => textNumber(points.reduce((sum, point) => sum + point[source], 0)) + " " + source);
  return element("article", {class: "panel"}, element("h3", {}, provider.name), svg,
    element("p", {class: "chart-summary"}, breakdown.join(" · ")));
}

function drawUsage(data, region) {
  region.replaceChildren(...["tokens", "requests"].map(metric => section(
    metric === "tokens" ? "Tokens over time" : "Requests over time",
    element("div", {class: "cards"}, ...data.providers.map(provider => chart(metric, provider, data.buckets))),
  )));
}

function usage(data, current) {
  const region = element("div", {"aria-live": "polite"});
  const controls = element("div", {class: "controls", role: "group", "aria-label": "Usage time range"});
  let revision = 0;
  for (const [range, label] of [["24h", "Last 24 hours"], ["7d", "Last 7 days"]]) {
    const button = element("button", {type: "button", "aria-pressed": String(data.range === range)}, label);
    button.addEventListener("click", async () => {
      const selected = ++revision;
      for (const peer of controls.children) peer.setAttribute("aria-pressed", String(peer === button));
      region.replaceChildren(element("p", {class: "notice"}, "Loading usage…"));
      try {
        const updated = await getData("usage?range=" + range);
        if (current === navigation && selected === revision) drawUsage(updated, region);
      } catch (error) {
        if (current === navigation && selected === revision) problem(region, error.message);
      }
    });
    controls.append(button);
  }
  const legend = element("div", {class: "legend"}, ...[
    ["reported", "Reported"], ["estimate", "Estimated"], ["unknown", "Unknown"],
  ].map(([style, label]) => element("span", {}, element("i", {class: "swatch " + style, "aria-hidden": "true"}), label)));
  drawUsage(data, region);
  return [controls, legend, element("p", {class: "notice"},
    "Times are UTC. Each chart has its own scale. Unknown token counts appear in grey in the requests charts."),
  region];
}

function drawRequests(data, region) {
  const {fields} = data;
  const rows = data.requests.map(row => [
    element("span", {class: "nowrap"}, utcTime(row[fields.timestamp])),
    element("code", {}, row[fields.request]), row[fields.provider] ?? "—",
    row[fields.stage], chip(row[fields.outcome]),
    row[fields.latency] == null ? "—" : textNumber(row[fields.latency]) + " ms",
    element("div", {class: "nowrap"}, chip(row[fields.tokenSource]), element("div", {},
      textNumber(row[fields.input]) + " / " + textNumber(row[fields.output])),
    ...(row[fields.reasoning] == null ? [] : [element("small", {}, textNumber(row[fields.reasoning]) + " reasoning")])),
    element("code", {}, row[fields.error] ?? "—"),
  ]);
  region.replaceChildren(element("p", {class: "notice", role: "status"},
    rows.length ? textNumber(rows.length) + " of " + textNumber(data.matching) + " candidate records"
      : "No requests match these filters."),
  ...(rows.length ? [table(
    ["Time", "Request", "Provider", "Stage", "Outcome", "Latency", "Tokens in / out", "Error code"],
    rows, "Request history")] : []));
}

function requests(data, current) {
  const region = element("div");
  const controls = element("div", {class: "controls", role: "group", "aria-label": "Request filters"});
  let revision = 0;
  for (const [key, label] of [["provider", "Provider"], ["stage", "Stage"], ["outcome", "Outcome"]]) {
    const select = element("select", {name: key}, element("option", {value: ""}, "All"),
      ...data.options[key].map(value => element("option", {value}, value)));
    controls.append(element("label", {class: "field"}, label, select));
  }
  controls.addEventListener("change", async () => {
    const selected = ++revision;
    const params = new URLSearchParams({limit: "50"});
    for (const select of controls.querySelectorAll("select")) {
      if (select.value) params.set(select.name, select.value);
    }
    region.replaceChildren(element("p", {class: "notice", role: "status"}, "Loading requests…"));
    try {
      const updated = await getData("requests?" + params);
      if (current === navigation && selected === revision) drawRequests(updated, region);
    } catch (error) {
      if (current === navigation && selected === revision) problem(region, error.message);
    }
  });
  drawRequests(data, region);
  return [controls, region];
}

function routingPolicy(data) {
  const rows = Object.entries(data.stages).map(([stage, name]) => {
    const tier = data.tiers[name];
    const candidates = element("ol", {class: "model-list"},
      ...tier.candidates.map(candidate => element("li", {}, element("code", {}, candidate))));
    return [stage, element("code", {}, name), candidates, tier.cross_provider_fallback ? "Enabled" : "Disabled",
      textNumber(tier.max_output_tokens)];
  });
  return [
    element("div", {class: "panel"}, element("h2", {}, "Read-only policy · Version " + data.version),
      element("p", {class: "notice"}, "Mock policy SHA-256"),
      element("code", {}, data.sha256)),
    section("Stage assignments", table(["Stage", "Tier", "Candidates", "Cross-provider fallback", "Output reserve"],
      rows, "Stage assignments")),
  ];
}

function pipeline(data) {
  return [element("div", {class: "run-list"}, ...data.runs.map(run =>
    element("article", {class: "panel"},
      element("div", {class: "card-head"}, element("h2", {class: "mono"}, run.id), chip(run.status)),
      element("ol", {class: "stages", "aria-label": "Stage progress"}, ...data.stages.map(stage => {
        const done = run.completed.includes(stage);
        const current = run.current === stage;
        const state = done ? "completed" : current ? "current" : "pending";
        const mark = done ? "✓ " : current ? "◉ " : "○ ";
        return element("li", {class: done ? "done" : state, "aria-label": stage + ", " + state,
          ...(current ? {"aria-current": "step"} : {})}, element("span", {"aria-hidden": "true"}, mark), stage);
      })),
      element("p", {class: "muted"}, run.hint),
      ...(run.resume_at ? [element("p", {class: "notice"}, "Resume after " + utcTime(run.resume_at)
        + " (" + relativeTime(run.resume_at) + ")")] : []))))];
}

const routes = {
  overview: ["Overview", "Free-tier traffic and recent incidents", overview],
  providers: ["Providers", "Model availability, quota snapshots, and cooldowns", providers],
  usage: ["Usage", "Request volume and token provenance by provider", usage],
  requests: ["Request History", "Candidate-level outcomes, latency, and token counts", requests],
  "routing-policy": ["Routing Policies", "Candidate order and fallback rules by stage", routingPolicy],
  pipeline: ["Pipeline Monitor", "Stage progress and resume guidance for synthetic runs", pipeline],
};

async function route(moveFocus = false) {
  const hash = location.hash.slice(1);
  if (hash === "main") return;
  const key = Object.hasOwn(routes, hash) ? hash : "overview";
  const [title, description, render] = routes[key];
  const current = ++navigation;
  heading.textContent = title;
  document.querySelector("#page-description").textContent = description;
  document.title = title + " | AI Operations";
  snapshot.textContent = "";
  for (const link of links) {
    if (link.hash === "#" + key) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
  if (moveFocus) heading.focus();
  page.replaceChildren(element("p", {class: "notice", role: "status"}, "Loading…"));
  try {
    const data = await getData(key);
    if (current !== navigation) return;
    snapshot.textContent = "Snapshot " + utcTime(data.generated_at);
    page.replaceChildren(...render(data, current));
  } catch (error) {
    if (current === navigation) problem(page, error.message);
  }
}

document.querySelector(".skip-link").addEventListener("click", event => {
  event.preventDefault();
  document.querySelector("#main").focus();
});
window.addEventListener("hashchange", () => route(true));
route();
