const GAUGE_START_DEG = 135;
const GAUGE_SWEEP_DEG = 270;
const GAUGE_DANGER_THRESHOLD = 80;
const TWEEN_MS = 350;
const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

function toRad(deg) {
  return (deg * Math.PI) / 180;
}

function setupHiDPICanvas(canvas) {
  const cssSize = canvas.clientWidth;
  const dpr = window.devicePixelRatio || 1;
  canvas.width = cssSize * dpr;
  canvas.height = cssSize * dpr;
  canvas.style.width = `${cssSize}px`;
  canvas.style.height = `${cssSize}px`;
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  return { ctx, cssSize };
}

function drawGauge(ctx, size, value, needleColor) {
  const clamped = Math.max(0, Math.min(100, value));
  const center = size / 2;
  const radius = size / 2 - 10;

  ctx.clearRect(0, 0, size, size);

  // Bezel arc
  ctx.strokeStyle = "#4a5568";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.arc(center, center, radius, toRad(GAUGE_START_DEG), toRad(GAUGE_START_DEG + GAUGE_SWEEP_DEG));
  ctx.stroke();

  // Danger zone tint past the threshold (jewel ruby — a status signal, not a decorative accent)
  const dangerStartDeg = GAUGE_START_DEG + (GAUGE_DANGER_THRESHOLD / 100) * GAUGE_SWEEP_DEG;
  ctx.strokeStyle = "rgba(201, 63, 74, 0.55)";
  ctx.lineWidth = 3;
  ctx.beginPath();
  ctx.arc(center, center, radius, toRad(dangerStartDeg), toRad(GAUGE_START_DEG + GAUGE_SWEEP_DEG));
  ctx.stroke();

  // Tick marks
  for (let v = 0; v <= 100; v += 5) {
    const isMajor = v % 20 === 0;
    const angle = toRad(GAUGE_START_DEG + (v / 100) * GAUGE_SWEEP_DEG);
    const outer = radius;
    const inner = radius - (isMajor ? 10 : 5);
    const x1 = center + outer * Math.cos(angle);
    const y1 = center + outer * Math.sin(angle);
    const x2 = center + inner * Math.cos(angle);
    const y2 = center + inner * Math.sin(angle);

    ctx.strokeStyle = isMajor ? "#7d8899" : "rgba(125, 136, 153, 0.5)";
    ctx.lineWidth = isMajor ? 2 : 1;
    ctx.beginPath();
    ctx.moveTo(x1, y1);
    ctx.lineTo(x2, y2);
    ctx.stroke();

    if (v === 0 || v === 50 || v === 100) {
      const labelRadius = inner - 10;
      const lx = center + labelRadius * Math.cos(angle);
      const ly = center + labelRadius * Math.sin(angle);
      ctx.fillStyle = "#7d8699";
      ctx.font = "9px 'Share Tech Mono', monospace";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(String(v), lx, ly);
    }
  }

  // Needle — neon glow, color varies per gauge (cyan/magenta "competing" accents)
  const needleAngle = toRad(GAUGE_START_DEG + (clamped / 100) * GAUGE_SWEEP_DEG);
  ctx.save();
  ctx.strokeStyle = needleColor;
  ctx.shadowColor = needleColor;
  ctx.shadowBlur = 10;
  ctx.lineWidth = 2;
  ctx.lineCap = "round";
  ctx.beginPath();
  ctx.moveTo(center, center);
  ctx.lineTo(center + (radius - 14) * Math.cos(needleAngle), center + (radius - 14) * Math.sin(needleAngle));
  ctx.stroke();
  ctx.restore();

  // Hub — glowing power-core pivot
  ctx.save();
  ctx.shadowColor = needleColor;
  ctx.shadowBlur = 6;
  const hubGradient = ctx.createRadialGradient(center, center, 1, center, center, 7);
  hubGradient.addColorStop(0, "#ffffff");
  hubGradient.addColorStop(0.45, needleColor);
  hubGradient.addColorStop(1, "#2a3142");
  ctx.fillStyle = hubGradient;
  ctx.beginPath();
  ctx.arc(center, center, 6, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
}

function makeGaugeController(canvasId, needleColor) {
  const canvas = document.getElementById(canvasId);
  let { ctx, cssSize } = setupHiDPICanvas(canvas);
  let displayedValue = 0;
  let animationFrame = null;

  function render(value) {
    drawGauge(ctx, cssSize, value, needleColor);
  }

  render(0);

  return function update(targetValue) {
    if (animationFrame) cancelAnimationFrame(animationFrame);

    if (prefersReducedMotion) {
      displayedValue = targetValue;
      render(displayedValue);
      return;
    }

    const startValue = displayedValue;
    const startTime = performance.now();

    function step(now) {
      const progress = Math.min(1, (now - startTime) / TWEEN_MS);
      const eased = 1 - (1 - progress) * (1 - progress);
      displayedValue = startValue + (targetValue - startValue) * eased;
      render(displayedValue);
      if (progress < 1) {
        animationFrame = requestAnimationFrame(step);
      }
    }

    animationFrame = requestAnimationFrame(step);
  };
}

const updateCpuGauge = makeGaugeController("cpu-chart", "#4de8dc");
const updateMemGauge = makeGaugeController("mem-chart", "#ff2e88");

const FLICKER_CHANCE = 0.12; // occasional, not on every update — a calm idle machine, not an alert

function flickerValue(el) {
  if (prefersReducedMotion) return;
  if (Math.random() > FLICKER_CHANCE) return;
  el.classList.remove("value-flicker");
  void el.offsetWidth; // force reflow so the animation restarts on repeat updates
  el.classList.add("value-flicker");
}

function setStatText(elementId, text) {
  const el = document.getElementById(elementId);
  el.textContent = text;
  flickerValue(el);
}

async function pollStats() {
  try {
    const res = await fetch("/api/stats");
    const data = await res.json();

    setStatText("cpu-value", `${data.cpu_percent.toFixed(1)}%`);
    setStatText("mem-value", `${data.memory_percent.toFixed(1)}% (${data.memory_used_gb} / ${data.memory_total_gb} GB)`);
    setStatText("disk-value", `${data.disk_percent.toFixed(1)}% (${data.disk_used_gb} / ${data.disk_total_gb} GB)`);
    setStatText("net-value", `↑ ${data.net_sent_mb} MB / ↓ ${data.net_recv_mb} MB`);

    updateCpuGauge(data.cpu_percent);
    updateMemGauge(data.memory_percent);
  } catch (err) {
    console.error("Failed to fetch stats:", err);
  }
}

pollStats();
setInterval(pollStats, 2000);

function buildDiagnosisCard(diagnosis) {
  const card = document.createElement("div");
  card.className = `diagnosis-card severity-${diagnosis.severity}`;

  const summary = document.createElement("p");
  summary.className = "diagnosis-summary";
  const dot = document.createElement("span");
  dot.className = "severity-dot";
  summary.appendChild(dot);
  summary.appendChild(document.createTextNode(diagnosis.summary));
  card.appendChild(summary);

  const details = document.createElement("details");
  details.className = "diagnosis-evidence";
  const detailsSummary = document.createElement("summary");
  detailsSummary.textContent = "Evidence";
  details.appendChild(detailsSummary);

  const dl = document.createElement("dl");
  for (const [key, value] of Object.entries(diagnosis.evidence)) {
    const dt = document.createElement("dt");
    dt.textContent = key.replace(/_/g, " ");
    dl.appendChild(dt);

    const dd = document.createElement("dd");
    dd.textContent = Array.isArray(value) || (value && typeof value === "object") ? JSON.stringify(value) : String(value);
    dl.appendChild(dd);
  }
  details.appendChild(dl);
  card.appendChild(details);

  return card;
}

function renderDiagnostics(diagnoses) {
  const container = document.getElementById("diagnostics-list");
  container.innerHTML = "";

  if (diagnoses.length === 0) {
    const p = document.createElement("p");
    p.className = "diagnostics-empty";
    p.textContent = "Nothing unusual detected — CPU, memory, and disk activity all look normal right now.";
    container.appendChild(p);
    return;
  }

  const fragment = document.createDocumentFragment();
  for (const diagnosis of diagnoses) {
    fragment.appendChild(buildDiagnosisCard(diagnosis));
  }
  container.appendChild(fragment);
}

function updateDiagnosticsIndicator(diagnoses) {
  const dot = document.getElementById("diagnostics-indicator-dot");
  const hasWarning = diagnoses.some((d) => d.severity === "warning");
  const hasFinding = diagnoses.length > 0;

  dot.classList.remove("dot-neutral", "dot-info", "dot-warning");
  if (hasWarning) {
    dot.classList.add("dot-warning");
  } else if (hasFinding) {
    dot.classList.add("dot-info");
  } else {
    dot.classList.add("dot-neutral");
  }
}

async function pollDiagnostics() {
  const container = document.getElementById("diagnostics-list");
  try {
    const res = await fetch("/api/diagnostics");
    const diagnoses = await res.json();
    // Rendered into the popup and the indicator's badge dot every poll
    // regardless of whether the popup is currently expanded, so the badge
    // stays current even while collapsed.
    renderDiagnostics(diagnoses);
    updateDiagnosticsIndicator(diagnoses);
  } catch (err) {
    console.error("Failed to fetch diagnostics:", err);
    container.innerHTML = '<p class="muted-note">Failed to load diagnostics.</p>';
  }
}

pollDiagnostics();
setInterval(pollDiagnostics, 2000);

const diagnosticsIndicator = document.getElementById("diagnostics-indicator");
const diagnosticsPopup = document.getElementById("diagnostics-popup");
const diagnosticsClose = document.getElementById("diagnostics-close");

function setDiagnosticsExpanded(expanded) {
  diagnosticsPopup.hidden = !expanded;
  diagnosticsIndicator.setAttribute("aria-expanded", String(expanded));
  diagnosticsIndicator.classList.toggle("is-expanded", expanded);
}

diagnosticsIndicator.addEventListener("click", () => {
  setDiagnosticsExpanded(diagnosticsPopup.hidden);
});

diagnosticsIndicator.addEventListener("keydown", (e) => {
  if (e.key === "Enter" || e.key === " ") {
    e.preventDefault();
    setDiagnosticsExpanded(diagnosticsPopup.hidden);
  }
});

diagnosticsClose.addEventListener("click", (e) => {
  e.stopPropagation();
  setDiagnosticsExpanded(false);
});

// Collapse on an outside click, but not on the click that opened it.
document.addEventListener("click", (e) => {
  if (diagnosticsPopup.hidden) return;
  if (diagnosticsPopup.contains(e.target) || diagnosticsIndicator.contains(e.target)) return;
  setDiagnosticsExpanded(false);
});

// Shared by the Process Manager and Startup Audit tables: manages a
// {key, direction} sort state for one <table>, wires up click-to-sort +
// direction-toggle on its `th.sortable` headers, and keeps their arrow
// indicators in sync. `accessors` maps a sort key to a function producing
// a comparable value per row; `defaultDirections` is the direction a key
// starts in the first time it's selected (e.g. text ascending, numeric
// magnitude descending).
function makeSortController({ tableId, accessors, defaultDirections, initialKey, initialDirection, onChange }) {
  let sortKey = initialKey;
  let sortDirection = initialDirection;

  function updateIndicators() {
    document.querySelectorAll(`#${tableId} th.sortable`).forEach((th) => {
      const arrow = th.querySelector(".sort-arrow");
      if (th.dataset.sortKey === sortKey) {
        arrow.textContent = sortDirection === "asc" ? "▲" : "▼";
      } else {
        arrow.textContent = "";
      }
    });
  }

  document.querySelectorAll(`#${tableId} th.sortable`).forEach((th) => {
    th.addEventListener("click", () => {
      const key = th.dataset.sortKey;
      if (sortKey === key) {
        sortDirection = sortDirection === "asc" ? "desc" : "asc";
      } else {
        sortKey = key;
        sortDirection = defaultDirections[key];
      }
      updateIndicators();
      onChange();
    });
  });

  updateIndicators();

  return {
    sort(items) {
      const accessor = accessors[sortKey];
      const sorted = [...items].sort((a, b) => {
        const valueA = accessor(a);
        const valueB = accessor(b);
        if (valueA < valueB) return -1;
        if (valueA > valueB) return 1;
        return 0;
      });
      if (sortDirection === "desc") sorted.reverse();
      return sorted;
    },
    get key() {
      return sortKey;
    },
  };
}

const SOURCE_ORDER = ["startup_folder", "registry_run", "service", "scheduled_task"];
const SOURCE_LABELS = {
  startup_folder: "Startup Folder",
  registry_run: "Registry (Run / RunOnce)",
  service: "Service",
  scheduled_task: "Scheduled Task",
};
const IMPACT_RANK = { low: 0, medium: 1, high: 2 };

let startupItems = [];

const STARTUP_SORT_ACCESSORS = {
  name: (item) => item.name.toLowerCase(),
  // Composite key so ties within the same source still fall back to
  // alphabetical order, matching the table's original default sort.
  source: (item) => `${SOURCE_ORDER.indexOf(item.source)}_${item.name.toLowerCase()}`,
  impact: (item) => IMPACT_RANK[item.estimated_impact] ?? -1,
  enabled: (item) => (item.enabled ? 1 : 0),
};
const STARTUP_SORT_DEFAULT_DIRECTION = {
  name: "asc",
  source: "asc",
  impact: "desc",
  enabled: "desc",
};

const startupSort = makeSortController({
  tableId: "startup-table",
  accessors: STARTUP_SORT_ACCESSORS,
  defaultDirections: STARTUP_SORT_DEFAULT_DIRECTION,
  initialKey: "source",
  initialDirection: "asc",
  onChange: () => renderStartupTable(filterStartupItems(document.getElementById("startup-search").value)),
});

function buildGroupRow(source, count) {
  const tr = document.createElement("tr");
  tr.className = "group-row";
  tr.dataset.source = source;
  const td = document.createElement("td");
  td.colSpan = 5;
  td.textContent = `${SOURCE_LABELS[source] || source} (${count})`;
  tr.appendChild(td);
  return tr;
}

function buildStartupRow(item) {
  const tr = document.createElement("tr");

  const nameTd = document.createElement("td");
  const nameLine = document.createElement("div");
  nameLine.className = "startup-name-line";
  nameLine.appendChild(document.createTextNode(item.name));
  if (item.is_orphaned) {
    const orphanBadge = document.createElement("span");
    orphanBadge.className = "orphaned-badge";
    orphanBadge.textContent = "Orphaned";
    nameLine.appendChild(orphanBadge);
  }
  nameTd.appendChild(nameLine);

  if (item.is_orphaned) {
    // Takes priority over known_description — a "Steam is a game
    // launcher…" blurb would be misleading once the exe itself is gone.
    const description = document.createElement("p");
    description.className = "known-description orphaned-description";
    description.textContent =
      "This program appears to be uninstalled — the file no longer exists. Safe to remove this leftover registry entry.";
    nameTd.appendChild(description);
  } else if (item.known_description) {
    const description = document.createElement("p");
    description.className = "known-description";
    description.textContent = item.known_description;
    description.title = item.known_description;
    nameTd.appendChild(description);
  }
  tr.appendChild(nameTd);

  const sourceTd = document.createElement("td");
  sourceTd.textContent = SOURCE_LABELS[item.source] || item.source;
  tr.appendChild(sourceTd);

  const commandTd = document.createElement("td");
  commandTd.className = "command-cell";
  commandTd.textContent = item.command;
  commandTd.title = item.command;
  tr.appendChild(commandTd);

  const impactTd = document.createElement("td");
  if (item.estimated_impact) {
    const impactBadge = document.createElement("span");
    impactBadge.className = `impact-badge impact-${item.estimated_impact}`;
    impactBadge.textContent = item.estimated_impact;
    impactTd.appendChild(impactBadge);
  } else {
    impactTd.textContent = "—";
    impactTd.className = "muted-note";
  }
  tr.appendChild(impactTd);

  const statusTd = document.createElement("td");
  const badge = document.createElement("span");
  badge.className = `status-badge ${item.enabled ? "is-enabled" : "is-disabled"}`;
  badge.textContent = item.enabled ? "Enabled" : "Disabled";
  statusTd.appendChild(badge);
  tr.appendChild(statusTd);

  return tr;
}

function renderStartupTable(items) {
  const tbody = document.getElementById("startup-table-body");
  const countEl = document.getElementById("startup-count");
  tbody.innerHTML = "";

  if (items.length === 0) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 5;
    td.className = "muted-note";
    td.textContent = "No startup items match your filter.";
    tr.appendChild(td);
    tbody.appendChild(tr);
    countEl.textContent = `0 of ${startupItems.length} items`;
    return;
  }

  const sorted = startupSort.sort(items);
  const fragment = document.createDocumentFragment();

  // The grouped-by-source header rows only make sense when that's actually
  // the active sort order — sorting by another column (e.g. Impact)
  // interleaves sources, so a per-source header would repeat misleadingly.
  if (startupSort.key === "source") {
    const groupSizes = new Map();
    for (const item of sorted) {
      groupSizes.set(item.source, (groupSizes.get(item.source) || 0) + 1);
    }

    let currentSource = null;
    for (const item of sorted) {
      if (item.source !== currentSource) {
        currentSource = item.source;
        fragment.appendChild(buildGroupRow(currentSource, groupSizes.get(currentSource)));
      }
      fragment.appendChild(buildStartupRow(item));
    }
  } else {
    for (const item of sorted) {
      fragment.appendChild(buildStartupRow(item));
    }
  }

  tbody.appendChild(fragment);
  countEl.textContent = `${items.length} of ${startupItems.length} items`;
}

function filterStartupItems(query) {
  const q = query.trim().toLowerCase();
  if (!q) return startupItems;
  return startupItems.filter((item) => {
    const sourceLabel = (SOURCE_LABELS[item.source] || item.source).toLowerCase();
    return (
      item.name.toLowerCase().includes(q) ||
      sourceLabel.includes(q) ||
      item.command.toLowerCase().includes(q) ||
      (item.known_description || "").toLowerCase().includes(q)
    );
  });
}

async function loadStartupAudit() {
  const tbody = document.getElementById("startup-table-body");
  try {
    const res = await fetch("/api/startup");
    startupItems = await res.json();
    renderStartupTable(startupItems);
  } catch (err) {
    console.error("Failed to fetch startup audit:", err);
    tbody.innerHTML = '<tr><td colspan="5" class="muted-note">Failed to load startup audit data.</td></tr>';
  }
}

document.getElementById("startup-search").addEventListener("input", (e) => {
  renderStartupTable(filterStartupItems(e.target.value));
});

loadStartupAudit();

let processGroups = [];
let processSearchQuery = "";
const expandedProcessGroups = new Set();

// Sorting applies to the top-level grouped rows only, using each group's
// own label/count/summed values — expanded member rows always stay
// attached to their parent group rather than being resorted independently.
const PROCESS_SORT_ACCESSORS = {
  name: (group) => group.label.toLowerCase(),
  pid: (group) => (group.process_count === 1 ? group.members[0].pid : group.process_count),
  cpu: (group) => group.total_cpu_percent,
  memory: (group) => group.total_memory_mb,
};
const PROCESS_SORT_DEFAULT_DIRECTION = {
  name: "asc",
  pid: "asc",
  cpu: "desc",
  memory: "desc",
};

const processSort = makeSortController({
  tableId: "process-table",
  accessors: PROCESS_SORT_ACCESSORS,
  defaultDirections: PROCESS_SORT_DEFAULT_DIRECTION,
  initialKey: "memory",
  initialDirection: "desc",
  onChange: () => applyProcessFilterAndRender(),
});

function toggleProcessGroup(label) {
  if (expandedProcessGroups.has(label)) {
    expandedProcessGroups.delete(label);
  } else {
    expandedProcessGroups.add(label);
  }
  applyProcessFilterAndRender();
}

function filterProcessGroups(query) {
  const q = query.trim().toLowerCase();
  if (!q) return processGroups;

  // Only treat the query as a PID match when it's actually numeric, so
  // typing "3" doesn't match every PID containing a "3" by accident of
  // also being a plausible name substring search.
  const isNumericQuery = /^\d+$/.test(q);

  return processGroups.filter((group) => {
    if (group.label.toLowerCase().includes(q)) return true;
    return group.members.some(
      (member) => member.name.toLowerCase().includes(q) || (isNumericQuery && String(member.pid).includes(q))
    );
  });
}

function applyProcessFilterAndRender() {
  const filtered = filterProcessGroups(processSearchQuery);

  // A match inside a collapsed group's members must not be silently
  // hidden — auto-expand any matched group whose own label didn't match,
  // so the matching member row is actually visible.
  const q = processSearchQuery.trim().toLowerCase();
  if (q) {
    for (const group of filtered) {
      if (group.process_count > 1 && !group.label.toLowerCase().includes(q)) {
        expandedProcessGroups.add(group.label);
      }
    }
  }

  renderProcessTable(filtered);
}

document.getElementById("process-search").addEventListener("input", (e) => {
  processSearchQuery = e.target.value;
  applyProcessFilterAndRender();
});

function buildProcessMemberRow(member) {
  const tr = document.createElement("tr");
  tr.className = "process-member-row";

  const nameTd = document.createElement("td");
  nameTd.className = "process-member-name";
  nameTd.textContent = member.name;
  if (member.role) {
    // Identifies process *role* (GPU/utility/renderer/...), not which tab
    // or site a renderer belongs to — psutil can't see that far.
    const role = document.createElement("p");
    role.className = "known-description";
    role.textContent = member.role;
    nameTd.appendChild(role);
  }
  tr.appendChild(nameTd);

  const pidTd = document.createElement("td");
  pidTd.textContent = member.pid;
  tr.appendChild(pidTd);

  const cpuTd = document.createElement("td");
  cpuTd.textContent = `${member.cpu_percent.toFixed(1)}%`;
  tr.appendChild(cpuTd);

  const memTd = document.createElement("td");
  memTd.textContent = `${member.memory_mb.toFixed(1)} MB`;
  tr.appendChild(memTd);

  return tr;
}

function buildProcessGroupRow(group) {
  const tr = document.createElement("tr");
  tr.className = "process-group-row";
  tr.addEventListener("click", () => toggleProcessGroup(group.label));

  const isExpanded = expandedProcessGroups.has(group.label);

  const nameTd = document.createElement("td");
  const toggle = document.createElement("span");
  toggle.className = "group-toggle";
  toggle.textContent = isExpanded ? "▾" : "▸";
  nameTd.appendChild(toggle);
  nameTd.appendChild(document.createTextNode(group.label));
  if (group.grouping_method === "shared_name") {
    nameTd.title =
      "Grouped by shared executable name only — no confirmed parent/child relationship between these processes.";
  }
  tr.appendChild(nameTd);

  const countTd = document.createElement("td");
  countTd.textContent = `${group.process_count} processes`;
  tr.appendChild(countTd);

  const cpuTd = document.createElement("td");
  cpuTd.textContent = `${group.total_cpu_percent.toFixed(1)}%`;
  tr.appendChild(cpuTd);

  const memTd = document.createElement("td");
  memTd.textContent = `${group.total_memory_mb.toFixed(1)} MB`;
  tr.appendChild(memTd);

  return tr;
}

function buildProcessSingleRow(group) {
  // A lone process (process_count === 1) — nothing to expand, render like
  // a plain row using its one member's own values.
  const member = group.members[0];
  const tr = document.createElement("tr");

  const nameTd = document.createElement("td");
  nameTd.textContent = group.label;
  tr.appendChild(nameTd);

  const pidTd = document.createElement("td");
  pidTd.textContent = member.pid;
  tr.appendChild(pidTd);

  const cpuTd = document.createElement("td");
  cpuTd.textContent = `${member.cpu_percent.toFixed(1)}%`;
  tr.appendChild(cpuTd);

  const memTd = document.createElement("td");
  memTd.textContent = `${member.memory_mb.toFixed(1)} MB`;
  tr.appendChild(memTd);

  return tr;
}

function renderProcessTable(groups) {
  const tbody = document.getElementById("process-table-body");
  const countEl = document.getElementById("process-count");
  tbody.innerHTML = "";

  if (groups.length === 0) {
    const noDataYet = processGroups.length === 0;
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 4;
    td.className = "muted-note";
    td.textContent = noDataYet ? "No process data available." : "No processes match your filter.";
    tr.appendChild(td);
    tbody.appendChild(tr);
    countEl.textContent = noDataYet ? "" : `0 of ${processGroups.length} groups`;
    return;
  }

  const fragment = document.createDocumentFragment();
  let totalProcesses = 0;
  for (const group of processSort.sort(groups)) {
    totalProcesses += group.process_count;
    if (group.process_count === 1) {
      fragment.appendChild(buildProcessSingleRow(group));
      continue;
    }
    fragment.appendChild(buildProcessGroupRow(group));
    if (expandedProcessGroups.has(group.label)) {
      for (const member of group.members) {
        fragment.appendChild(buildProcessMemberRow(member));
      }
    }
  }
  tbody.appendChild(fragment);
  countEl.textContent = `${groups.length} of ${processGroups.length} groups, ${totalProcesses} processes shown`;
}

let processPollInFlight = false;

async function pollProcesses() {
  // /api/processes enumerates 250-300+ processes and can take several
  // seconds — longer than the 2s poll interval. Without this guard, a slow
  // response causes the next poll to fire before it returns, and those
  // overlapping requests pile up and exhaust the server's thread pool,
  // starving other endpoints (this is what broke the startup audit table).
  if (processPollInFlight) return;
  processPollInFlight = true;

  const tbody = document.getElementById("process-table-body");
  try {
    const res = await fetch("/api/processes");
    processGroups = await res.json();
    applyProcessFilterAndRender();
  } catch (err) {
    console.error("Failed to fetch process list:", err);
    tbody.innerHTML = '<tr><td colspan="4" class="muted-note">Failed to load process data.</td></tr>';
  } finally {
    processPollInFlight = false;
  }
}

pollProcesses();
setInterval(pollProcesses, 2000);
