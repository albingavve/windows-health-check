const MAX_POINTS = 30;
const cpuHistory = [];
const memHistory = [];

function makeChart(canvasId, label, color) {
  const ctx = document.getElementById(canvasId).getContext("2d");
  return new Chart(ctx, {
    type: "line",
    data: {
      labels: [],
      datasets: [{
        label,
        data: [],
        borderColor: color,
        backgroundColor: color + "33",
        tension: 0.3,
        fill: true,
        pointRadius: 0,
      }],
    },
    options: {
      animation: false,
      scales: {
        y: { min: 0, max: 100, ticks: { color: "#8b93a1" } },
        x: { display: false },
      },
      plugins: { legend: { display: false } },
    },
  });
}

const cpuChart = makeChart("cpu-chart", "CPU %", "#4da6ff");
const memChart = makeChart("mem-chart", "Memory %", "#ff9f4d");

function pushPoint(chart, history, value) {
  history.push(value);
  if (history.length > MAX_POINTS) history.shift();
  chart.data.labels = history.map((_, i) => i);
  chart.data.datasets[0].data = history;
  chart.update();
}

async function pollStats() {
  try {
    const res = await fetch("/api/stats");
    const data = await res.json();

    document.getElementById("cpu-value").textContent = `${data.cpu_percent.toFixed(1)}%`;
    document.getElementById("mem-value").textContent =
      `${data.memory_percent.toFixed(1)}% (${data.memory_used_gb} / ${data.memory_total_gb} GB)`;
    document.getElementById("disk-value").textContent =
      `${data.disk_percent.toFixed(1)}% (${data.disk_used_gb} / ${data.disk_total_gb} GB)`;
    document.getElementById("net-value").textContent =
      `↑ ${data.net_sent_mb} MB / ↓ ${data.net_recv_mb} MB`;

    pushPoint(cpuChart, cpuHistory, data.cpu_percent);
    pushPoint(memChart, memHistory, data.memory_percent);
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
  const td = document.createElement("td");
  td.colSpan = 4;
  td.textContent = `${SOURCE_LABELS[source] || source} (${count})`;
  tr.appendChild(td);
  return tr;
}

function buildStartupRow(item) {
  const tr = document.createElement("tr");

  const nameTd = document.createElement("td");
  nameTd.textContent = item.name;
  tr.appendChild(nameTd);

  const sourceTd = document.createElement("td");
  sourceTd.textContent = SOURCE_LABELS[item.source] || item.source;
  tr.appendChild(sourceTd);

  const commandTd = document.createElement("td");
  commandTd.className = "command-cell";
  commandTd.textContent = item.command;
  commandTd.title = item.command;
  tr.appendChild(commandTd);

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
    td.colSpan = 4;
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
      item.command.toLowerCase().includes(q)
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
    tbody.innerHTML = '<tr><td colspan="4" class="muted-note">Failed to load startup audit data.</td></tr>';
  }
}

document.getElementById("startup-search").addEventListener("input", (e) => {
  renderStartupTable(filterStartupItems(e.target.value));
});

loadStartupAudit();
