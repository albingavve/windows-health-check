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
