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

const SOURCE_ORDER = ["startup_folder", "registry_run", "service", "scheduled_task"];
const SOURCE_LABELS = {
  startup_folder: "Startup Folder",
  registry_run: "Registry (Run / RunOnce)",
  service: "Service",
  scheduled_task: "Scheduled Task",
};

let startupItems = [];

function sortStartupItems(items) {
  return [...items].sort((a, b) => {
    const orderA = SOURCE_ORDER.indexOf(a.source);
    const orderB = SOURCE_ORDER.indexOf(b.source);
    if (orderA !== orderB) return orderA - orderB;
    return a.name.localeCompare(b.name);
  });
}

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
  nameTd.textContent = item.name;
  if (item.known_description) {
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

  const sorted = sortStartupItems(items);
  const groupSizes = new Map();
  for (const item of sorted) {
    groupSizes.set(item.source, (groupSizes.get(item.source) || 0) + 1);
  }

  const fragment = document.createDocumentFragment();
  let currentSource = null;
  for (const item of sorted) {
    if (item.source !== currentSource) {
      currentSource = item.source;
      fragment.appendChild(buildGroupRow(currentSource, groupSizes.get(currentSource)));
    }
    fragment.appendChild(buildStartupRow(item));
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
