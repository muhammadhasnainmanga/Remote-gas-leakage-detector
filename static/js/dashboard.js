const $ = (id) => document.getElementById(id);
let chart = null;
let weightChart = null;
let currentPeriod = 'hourly';
let currentWeightPeriod = 'hourly';
let weightUnit = 'kg';
let lastDashboardData = null;
const animationLabels = {
  smile: 'Smile',
  blink: 'Blinking face',
  heart: 'Heart',
  wave: 'Waving face',
  star: 'Star eyes',
  surprised: 'Surprised face',
};

const rangeDescriptions = {
  hourly: 'Last hour · 1-minute averages',
  daily: 'Last 24 hours · 5-minute averages',
  weekly: 'Last 7 days · hourly averages',
};
const weightRangeDescriptions = {
  hourly: 'Last hour · original readings',
  daily: 'Last 24 hours · original readings',
  weekly: 'Last 7 days · original readings',
};
const validPeriods = new Set(['hourly', 'daily', 'weekly']);

const numberFormat = new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 });
const dateFormat = new Intl.DateTimeFormat(undefined, { timeZone: 'Asia/Karachi', dateStyle: 'medium', timeStyle: 'short' });

function formatNumber(value) { return value === null || value === undefined ? '—' : numberFormat.format(value); }

function formatDate(value) { if (!value) return '—'; const date = new Date(value); return Number.isNaN(date.getTime()) ? '—' : dateFormat.format(date); }

function setText(id, value) { const element = $(id); if (element) element.textContent = value; }

function renderAnimationState(state) {
  setText('currentAnimationName', state.current_animation || animationLabels[state.keyword] || 'Unknown');
  document.querySelectorAll('.animation-card').forEach((card) => {
    const selected = card.dataset.animationCard === state.keyword;
    card.classList.toggle('selected', selected);
    const button = card.querySelector('.animation-select-button');
    button.textContent = selected ? 'Selected' : 'Show on OLED';
    button.setAttribute('aria-pressed', String(selected));
  });
}

async function fetchAnimationState() {
  try {
    const response = await fetch('/api/animation', { cache: 'no-store' });
    if (!response.ok) throw new Error(`API returned ${response.status}`);
    renderAnimationState(await response.json());
  } catch (error) {
    setText('currentAnimationName', 'Unavailable');
    setText('animationMessage', `Could not load: ${error.message}`);
  }
}

async function selectAnimation(button) {
  const keyword = button.dataset.keyword;
  const message = $('animationMessage');
  document.querySelectorAll('.animation-select-button').forEach((item) => { item.disabled = true; });
  message.textContent = 'Saving…';
  try {
    const response = await fetch('/api/animation', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ keyword }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || `API returned ${response.status}`);
    renderAnimationState(result);
    message.textContent = 'Saved. The Pico will switch on its next check.';
  } catch (error) {
    message.textContent = `Could not save: ${error.message}`;
  } finally {
    document.querySelectorAll('.animation-select-button').forEach((item) => { item.disabled = false; });
  }
}

function toDisplayWeight(grams) { return weightUnit === 'kg' ? grams / 1000 : grams; }

function formatWeightNumber(value) {
  if (value === null || value === undefined) return '—';
  const decimals = weightUnit === 'kg' ? 2 : 0;
  return new Intl.NumberFormat('en-US', { maximumFractionDigits: decimals }).format(value);
}

function displayWeight(grams) { return `${formatWeightNumber(toDisplayWeight(grams))} ${weightUnit}`; }

function weightChartMax(points) {
  const largest = points.reduce((max, point) => Math.max(max, point.y), 0);
  const tickStep = weightUnit === 'kg' ? 0.1 : 100;
  if (largest === 0) return tickStep;
  return Math.ceil((largest * 1.15) / tickStep) * tickStep;
}

function setConnection(kind, text) {
  const dot = $('connectionDot');
  if (dot) dot.className = `connection-dot ${kind}`;
  setText('connectionText', text);
}


// function to render chart
function renderChart(points, period, threshold) {
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
  const thresholdValues = points.map(() => threshold);
  if (!chart) {
    chart = new Chart($('readingsChart'), {
      type: 'line',
      data: { labels, datasets: [
        { label: 'Average raw ADC', data: values, sampleCounts: points.map((point) => point.samples), borderColor: '#648b78', backgroundColor: 'rgba(100,139,120,.12)', borderWidth: 2, fill: true, tension: .2, pointRadius: 0, pointHoverRadius: 4 },
        { label: 'Alert threshold', data: thresholdValues, borderColor: '#c27a61', borderWidth: 1.5, borderDash: [6, 5], fill: false, tension: 0, pointRadius: 0, pointHoverRadius: 0 },
      ] },
      options: {
        responsive: true, maintainAspectRatio: false,
        interaction: { intersect: false, mode: 'index' },
        plugins: {
          legend: { display: false },
          tooltip: { displayColors: false, callbacks: {
            label: (context) => `${context.dataset.label}: ${formatNumber(context.parsed.y)}`,
            afterLabel: (context) => context.datasetIndex === 0 ? `${context.dataset.sampleCounts?.[context.dataIndex] ?? 0} samples in interval` : '',
          } },
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
    chart.data.datasets[1].data = thresholdValues;
    chart.update();
  }
}


function renderWeightChart(points, period) {
  setText('weightChartLegend', `Gas remaining (${weightUnit})`);
  $('weightChartEmpty').hidden = points.length !== 0;
  if (!window.Chart) {
    $('weightChartEmpty').hidden = false;
    setText('weightChartEmpty', 'The chart library did not load. Check your internet connection and retry.');
    return;
  }
  const values = points.map((point) => ({
    x: Date.parse(point.time),
    y: toDisplayWeight(point.weight_grams),
  }));
  if (!weightChart) {
    weightChart = new Chart($('weightChart'), {
      type: 'line',
      data: { datasets: [{ label: `Gas remaining (${weightUnit})`, data: values, borderColor: '#648b78', backgroundColor: 'rgba(100,139,120,.12)', borderWidth: 2, fill: true, tension: 0, pointRadius: 0, pointHoverRadius: 4 }] },
      options: {
        responsive: true, maintainAspectRatio: false,
        parsing: false,
        interaction: { intersect: false, mode: 'nearest' },
        plugins: {
          legend: { display: false },
          decimation: { enabled: true, algorithm: 'min-max', threshold: 1000 },
          tooltip: { displayColors: false, callbacks: {
            title: (items) => items.length ? formatDate(new Date(items[0].parsed.x).toISOString()) : '',
            label: (context) => `${formatWeightNumber(context.parsed.y)} ${weightUnit}`,
          } },
        },
        scales: {
          x: { type: 'linear', grid: { display: false }, ticks: { color: '#8a949c', maxTicksLimit: 8, maxRotation: 0, callback: (value) => {
            const date = new Date(value);
            return currentWeightPeriod === 'weekly'
              ? date.toLocaleString([], { timeZone: 'Asia/Karachi', month: 'short', day: 'numeric' })
              : date.toLocaleTimeString([], { timeZone: 'Asia/Karachi', hour: 'numeric', minute: '2-digit' });
          } } },
          y: { beginAtZero: true, max: weightChartMax(values), title: { display: true, text: `Gas remaining (${weightUnit})` }, grid: { color: '#edf0f1' }, ticks: { color: '#8a949c', maxTicksLimit: 5, callback: (value) => formatWeightNumber(value) } },
        },
      },
    });
  } else {
    weightChart.data.datasets[0].data = values;
    weightChart.data.datasets[0].label = `Gas remaining (${weightUnit})`;
    weightChart.options.scales.y.title.text = `Gas remaining (${weightUnit})`;
    weightChart.options.scales.y.max = weightChartMax(values);
    weightChart.update();
  }
}



function renderData(data) {
  const sensor = data.mq2;
  const hit = sensor.last_threshold_hit;
  setText('lastReading', formatNumber(sensor.latest_value));
  setText('lastReadingTime', sensor.latest_at ? `Recorded ${formatDate(sensor.latest_at)}` : 'No reading recorded yet');
  setText('average24h', formatNumber(sensor.average_24h));
  setText('emailsSent', formatNumber(data.emails.mq2.total));
  setText('thresholdValue', hit ? formatNumber(hit.value) : '—');
  setText('thresholdTime', hit ? `Recorded ${formatDate(hit.time)}` : 'No threshold hit recorded');
  setText('sensorStatus', sensor.status === 'alert' ? 'Alert active' : sensor.status === 'watch' ? `Checking ${sensor.high_streak}/10` : sensor.status === 'offline' ? 'No recent data' : 'Below threshold');
  $('sensorStatus').className = `status-pill ${sensor.status}`;
  $('alertBanner').hidden = sensor.status !== 'alert';
  $('offlineBanner').hidden = sensor.status !== 'offline';
  const value = sensor.latest_value ?? 0;
  setText('meterValue', formatNumber(sensor.latest_value));
  $('meterFill').className = `meter-fill ${sensor.status || ''}`;
  $('meterFill').style.width = `${Math.min(100, Math.max(0, value / 65535 * 100))}%`;
  const threshold = data.threshold ?? 0;
  $('thresholdMarker').style.left = `${Math.min(100, Math.max(0, threshold / 65535 * 100))}%`;
  setText('thresholdLabel', `Threshold ${formatNumber(data.threshold)} · 10 readings`);
  setText('updatedAt', formatDate(data.generated_at));
  setText('rangeDescription', rangeDescriptions[data.period]);
  setText('sampleHint', `${numberFormat.format(sensor.points.reduce((sum, point) => sum + point.samples, 0))} readings grouped`);

  const cylinder = data.cylinder;
  $('weightAlertBanner').hidden = !cylinder.low_weight;
  setText('weightRemaining', cylinder.has_reading
    ? displayWeight(cylinder.remaining_grams)
    : 'Waiting for load-cell data');
  setText('weightLastValue', cylinder.has_reading
    ? displayWeight(cylinder.remaining_grams)
    : `— ${weightUnit}`);
  setText('weightLastTime', cylinder.recorded_at
    ? `Last checked ${formatDate(cylinder.recorded_at)}`
    : 'Last checked: no reading yet');
  setText('cylinderEmailsSent', formatNumber(cylinder.emails.total));
  setText('cylinderLastEmail', cylinder.emails.last_sent_at
    ? `Last cylinder email: ${formatDate(cylinder.emails.last_sent_at)}`
    : 'Last cylinder email: none yet');
  if (document.activeElement !== $('emptyCylinderKg')) {
    $('emptyCylinderKg').value = (cylinder.empty_weight_grams / 1000).toFixed(2);
  }
  const capacityKg = cylinder.capacity_grams / 1000;
  const remainingKg = cylinder.has_reading ? cylinder.remaining_grams / 1000 : 0;
  const fillPercent = Math.min(100, Math.max(0, remainingKg / capacityKg * 100));
  $('cylinderFill').style.width = `${fillPercent}%`;
  $('cylinderFill').classList.toggle('low', cylinder.low_weight);
  setText('gasPercent', cylinder.has_reading ? `${Math.round(fillPercent)}%` : '—');
  const gasMeter = document.querySelector('.cylinder-track[role="meter"]');
  gasMeter.setAttribute('aria-valuemax', String(capacityKg));
  gasMeter.setAttribute('aria-valuenow', String(Math.min(capacityKg, remainingKg)));
  $('gasThresholdMarker').style.left = `${cylinder.low_threshold_grams / cylinder.capacity_grams * 100}%`;
  setText('weightRangeDescription', weightRangeDescriptions[data.weight_period]);
  renderWeightChart(cylinder.points, data.weight_period);
  renderChart(sensor.points, data.period, data.threshold);
}

//getting all the last data, values, and all type of true and false
async function fetchRecentData() {
  const button = $('refreshButton');
  currentPeriod = validPeriods.has(currentPeriod) ? currentPeriod : 'hourly';
  currentWeightPeriod = validPeriods.has(currentWeightPeriod) ? currentWeightPeriod : 'hourly';
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
  $('animationsPage').hidden = view !== 'animations';
  if (view === 'animations') fetchAnimationState();
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
document.querySelectorAll('.animation-select-button').forEach((button) => button.addEventListener('click', () => selectAnimation(button)));

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
fetchAnimationState();
setInterval(fetchRecentData, 15000);
setInterval(() => {
  if (!$('animationsPage').hidden) fetchAnimationState();
}, 5000);
