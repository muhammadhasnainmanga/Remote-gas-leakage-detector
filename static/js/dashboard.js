const $ = (id) => document.getElementById(id);
let chart = null;
let weightChart = null;
let currentPeriod = 'hourly';
let currentWeightPeriod = 'hourly';
let weightUnit = 'kg';
let lastDashboardData = null;

const rangeDescriptions = {
  hourly: 'Last hour · 1-minute averages (about 660 readings at 11 per minute)',
  daily: 'Last 24 hours · 5-minute averages',
  weekly: 'Last 7 days · hourly averages',
};
const weightRangeDescriptions = {
  hourly: 'Last hour · individual readings',
  daily: 'Last 24 hours · individual readings',
  weekly: 'Last 7 days · individual readings',
};

const numberFormat = new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 });
const dateFormat = new Intl.DateTimeFormat(undefined, { timeZone: 'Asia/Karachi', dateStyle: 'medium', timeStyle: 'short' });

function formatNumber(value) { return value === null || value === undefined ? '—' : numberFormat.format(value); }

function formatDate(value) { if (!value) return '—'; const date = new Date(value); return Number.isNaN(date.getTime()) ? '—' : dateFormat.format(date); }

function setText(id, value) { const element = $(id); if (element) element.textContent = value; }

function toDisplayWeight(grams) { return weightUnit === 'kg' ? grams / 1000 : grams; }

function formatWeightNumber(value) {
  if (value === null || value === undefined) return '—';
  const decimals = weightUnit === 'kg' ? 2 : 1;
  return new Intl.NumberFormat('en-US', { maximumFractionDigits: decimals }).format(value);
}

function displayWeight(grams) { return `${formatWeightNumber(toDisplayWeight(grams))} ${weightUnit}`; }

function setConnection(kind, text) {
  const dot = $('connectionDot');
  if (dot) dot.className = `connection-dot ${kind}`;
  setText('connectionText', text);
}


// function to render chart
function renderChart(points, period) {
  $('chartEmpty').hidden = points.length !== 0;
  if (!window.Chart) {
    $('chartEmpty').hidden = false;
    setText('chartEmpty', 'The chart library did not load. Check your internet connection and retry.');
    return;
  }
  const labels = points.map((point) => {
    const date = new Date(point.time);
    return period === 'weekly'
      ? date.toLocaleString([], { timeZone: 'Asia/Karachi', month: 'short', day: 'numeric', hour: 'numeric' })
      : date.toLocaleTimeString([], { timeZone: 'Asia/Karachi', hour: 'numeric', minute: '2-digit' });
  });
  const values = points.map((point) => point.average);
  if (!chart) {
    chart = new Chart($('readingsChart'), {
      type: 'line',
      data: { labels, datasets: [{ label: 'Average raw ADC', data: values, sampleCounts: points.map((point) => point.samples), borderColor: '#557895', backgroundColor: 'rgba(85,120,149,.10)', borderWidth: 2, fill: true, tension: .2, pointRadius: 0, pointHoverRadius: 4 }] },
      options: {
        responsive: true, maintainAspectRatio: false,
        interaction: { intersect: false, mode: 'index' },
        plugins: {
          legend: { display: false },
          tooltip: { displayColors: false, callbacks: { afterLabel: (context) => `${context.dataset.sampleCounts?.[context.dataIndex] ?? 0} samples in interval` } },
        },
        scales: {
          x: { grid: { display: false }, ticks: { color: '#8a949c', maxTicksLimit: 9, maxRotation: 0 } },
          y: { beginAtZero: false, grid: { color: '#edf0f1' }, ticks: { color: '#8a949c', maxTicksLimit: 5 } },
        },
      },
    });
  } else {
    chart.data.labels = labels;
    chart.data.datasets[0].data = values;
    chart.data.datasets[0].sampleCounts = points.map((point) => point.samples);
    chart.update();
  }
}


function renderWeightChart(points, period) {
  setText('weightChartLegend', `Gross weight (${weightUnit})`);
  $('weightChartEmpty').hidden = points.length !== 0;
  if (!window.Chart) {
    $('weightChartEmpty').hidden = false;
    setText('weightChartEmpty', 'The chart library did not load. Check your internet connection and retry.');
    return;
  }
  const labels = points.map((point) => {
    const date = new Date(point.time);
    return period === 'weekly'
      ? date.toLocaleString([], { timeZone: 'Asia/Karachi', month: 'short', day: 'numeric', hour: 'numeric' })
      : date.toLocaleTimeString([], { timeZone: 'Asia/Karachi', hour: 'numeric', minute: '2-digit' });
  });
  const values = points.map((point) => toDisplayWeight(point.weight_grams));
  if (!weightChart) {
    weightChart = new Chart($('weightChart'), {
      type: 'line',
      data: { labels, datasets: [{ label: `Gross weight (${weightUnit})`, data: values, borderColor: '#648b78', backgroundColor: 'rgba(100,139,120,.12)', borderWidth: 2, fill: true, tension: 0, pointRadius: 2, pointHoverRadius: 4 }] },
      options: {
        responsive: true, maintainAspectRatio: false,
        interaction: { intersect: false, mode: 'index' },
        plugins: {
          legend: { display: false },
          tooltip: { displayColors: false, callbacks: { label: (context) => `${formatWeightNumber(context.parsed.y)} ${weightUnit}` } },
        },
        scales: {
          x: { grid: { display: false }, ticks: { color: '#8a949c', maxTicksLimit: 9, maxRotation: 0 } },
          y: { beginAtZero: false, title: { display: true, text: `Gross weight (${weightUnit})` }, grid: { color: '#edf0f1' }, ticks: { color: '#8a949c', maxTicksLimit: 5, callback: (value) => formatWeightNumber(value) } },
        },
      },
    });
  } else {
    weightChart.data.labels = labels;
    weightChart.data.datasets[0].data = values;
    weightChart.data.datasets[0].label = `Gross weight (${weightUnit})`;
    weightChart.options.scales.y.title.text = `Gross weight (${weightUnit})`;
    weightChart.update();
  }
}



function renderData(data) {
  const sensor = data.mq2;
  const hit = sensor.last_threshold_hit;
  setText('lastReading', formatNumber(sensor.latest_value));
  setText('lastReadingTime', sensor.latest_at ? `Recorded ${formatDate(sensor.latest_at)}` : 'No reading recorded yet');
  setText('average24h', formatNumber(sensor.average_24h));
  setText('emailsSent', formatNumber(data.emails.total));
  setText('thresholdValue', hit ? formatNumber(hit.value) : '—');
  setText('thresholdTime', hit ? `Recorded ${formatDate(hit.time)}` : 'No threshold hit recorded');
  setText('sensorStatus', sensor.status === 'alert' ? 'Threshold hit' : sensor.status === 'offline' ? 'No recent data' : 'Below threshold');
  $('sensorStatus').className = `status-pill ${sensor.status}`;
  $('alertBanner').hidden = sensor.status !== 'alert';
  $('offlineBanner').hidden = sensor.status !== 'offline';
  const value = sensor.latest_value ?? 0;
  setText('meterValue', formatNumber(sensor.latest_value));
  $('meterFill').style.width = `${Math.min(100, Math.max(0, value / 65535 * 100))}%`;
  const threshold = data.threshold ?? 0;
  $('thresholdMarker').style.left = `${Math.min(100, Math.max(0, threshold / 65535 * 100))}%`;
  setText('thresholdLabel', `Threshold ${formatNumber(data.threshold)}`);
  setText('updatedAt', formatDate(data.generated_at));
  setText('rangeDescription', rangeDescriptions[data.period]);
  setText('sampleHint', `${numberFormat.format(sensor.points.reduce((sum, point) => sum + point.samples, 0))} readings grouped`);

  const cylinder = data.cylinder;
  $('weightAlertBanner').hidden = !cylinder.low_weight;
  setText('weightRemaining', cylinder.has_reading
    ? cylinder.remaining_grams === null
      ? 'Set empty cylinder weight to calculate gas remaining'
      : `${displayWeight(cylinder.remaining_grams)} gas remaining`
    : 'Waiting for load-cell data');
  setText('weightFigure', cylinder.has_reading
    ? `${displayWeight(cylinder.weight_grams)} gross`
    : `Gross — ${weightUnit}`);
  setText('weightDetails', cylinder.empty_weight_grams === null
    ? 'Enter the empty cylinder weight below to calculate gas remaining.'
    : `Empty cylinder: ${displayWeight(cylinder.empty_weight_grams)}`);
  setText('weightLastTime', cylinder.recorded_at
    ? `Last reading: ${formatDate(cylinder.recorded_at)}`
    : 'Last reading: none yet');
  if (cylinder.empty_weight_grams !== null && document.activeElement !== $('emptyCylinderKg')) {
    $('emptyCylinderKg').value = (cylinder.empty_weight_grams / 1000).toFixed(3);
  }
  setText('weightRangeDescription', weightRangeDescriptions[data.weight_period]);
  renderWeightChart(cylinder.points, data.weight_period);
  renderChart(sensor.points, data.period);
}

//getting all the last data, values, and all type of true and false
async function fetchRecentData() {
  const button = $('refreshButton');
  button.disabled = true;
  button.textContent = 'Fetching…';
  try {
    const response = await fetch(`/api/dashboard?period=${encodeURIComponent(currentPeriod)}&weight_period=${encodeURIComponent(currentWeightPeriod)}`, { cache: 'no-store' });
    if (!response.ok) throw new Error(`API returned ${response.status}`);
    const data = await response.json();
    lastDashboardData = data;
    renderData(data);
    $('errorBanner').hidden = true;
    const deviceOffline = data.mq2.status === 'offline' && !data.cylinder.has_reading;
    setConnection(deviceOffline ? 'down' : 'live', deviceOffline ? 'No recent sensor data' : 'Connected');
  } catch (error) {
    setText('errorBanner', `Could not get recent data: ${error.message}`);
    $('errorBanner').hidden = false;
    setConnection('down', 'Could not connect');
  } finally {
    button.disabled = false;
    button.textContent = 'Get recent data';
  }
}


function showView(view) {
  $('leakagePage').hidden = view !== 'leakage';
  $('weightPage').hidden = view !== 'weight';
  document.querySelectorAll('.nav-button').forEach((button) => {
    const active = button.dataset.view === view;
    button.classList.toggle('active', active);
    button.setAttribute('aria-pressed', String(active));
  });
  if (view === 'weight' && weightChart) {
    requestAnimationFrame(() => weightChart.resize());
  }
}


document.querySelectorAll('.nav-button').forEach((button) => button.addEventListener('click', () => showView(button.dataset.view)));

document.querySelectorAll('.range-button:not(.weight-range-button)').forEach((button) => button.addEventListener('click', () => {
  currentPeriod = button.dataset.period;
  document.querySelectorAll('.range-button:not(.weight-range-button)').forEach((other) => {
    const active = other === button;
    other.classList.toggle('active', active);
    other.setAttribute('aria-pressed', String(active));
  });
  fetchRecentData();
}));
$('cylinderSettingsForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  const emptyWeightKg = Number($('emptyCylinderKg').value);
  const button = $('saveCylinderSettings');
  const message = $('settingsMessage');
  button.disabled = true;
  message.textContent = 'Saving…';
  try {
    const response = await fetch('/api/cylinder-settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ empty_weight_grams: emptyWeightKg * 1000 }),
    });
    if (!response.ok) throw new Error(`API returned ${response.status}`);
    message.textContent = 'Empty cylinder weight saved.';
    await fetchRecentData();
  } catch (error) {
    message.textContent = `Could not save: ${error.message}`;
  } finally {
    button.disabled = false;
  }
});

document.querySelectorAll('.weight-range-button').forEach((button) => button.addEventListener('click', () => {
  currentWeightPeriod = button.dataset.weightPeriod;
  document.querySelectorAll('.weight-range-button').forEach((other) => {
    const active = other === button;
    other.classList.toggle('active', active);
    other.setAttribute('aria-pressed', String(active));
  });
  fetchRecentData();
}));

document.querySelectorAll('.unit-button').forEach((button) => button.addEventListener('click', () => {
  weightUnit = button.dataset.weightUnit;
  document.querySelectorAll('.unit-button').forEach((other) => {
    const active = other === button;
    other.classList.toggle('active', active);
    other.setAttribute('aria-pressed', String(active));
  });
  if (lastDashboardData) renderData(lastDashboardData);
}));

$('refreshButton').addEventListener('click', fetchRecentData);
fetchRecentData();
setInterval(fetchRecentData, 60000);
