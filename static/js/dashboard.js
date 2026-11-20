const $ = (id) => document.getElementById(id);
let chart = null;
let currentPeriod = 'hourly';
let currentView = 'leakage';

const rangeDescriptions = {
  hourly: 'Last hour · 1-minute averages (about 660 readings at 11 per minute)',
  daily: 'Last 24 hours · 5-minute averages',
  weekly: 'Last 7 days · hourly averages',
};

const numberFormat = new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 });
const dateFormat = new Intl.DateTimeFormat(undefined, { timeZone: 'Asia/Karachi', dateStyle: 'medium', timeStyle: 'short' });

function formatNumber(value) { return value === null || value === undefined ? '—' : numberFormat.format(value); }

function formatDate(value) { if (!value) return '—'; const date = new Date(value); return Number.isNaN(date.getTime()) ? '—' : dateFormat.format(date); }

function setConnection(kind, text) { $('connectionDot').className = `connection-dot ${kind}`; $('connectionText').textContent = text; }


// function to render chart
function renderChart(points, period) {
  $('chartEmpty').hidden = points.length !== 0;
  if (!window.Chart) {
    $('chartEmpty').hidden = false;
    $('chartEmpty').textContent = 'The chart library did not load. Check your internet connection and retry.';
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



function renderData(data) {
  const sensor = data.mq2;
  const hit = sensor.last_threshold_hit;
  $('lastReading').textContent = formatNumber(sensor.latest_value);
  $('lastReadingTime').textContent = sensor.latest_at ? `Recorded ${formatDate(sensor.latest_at)}` : 'No reading recorded yet';
  $('average24h').textContent = formatNumber(sensor.average_24h);
  $('emailsSent').textContent = formatNumber(data.emails.total);
  $('thresholdValue').textContent = hit ? formatNumber(hit.value) : '—';
  $('thresholdTime').textContent = hit ? `Recorded ${formatDate(hit.time)}` : 'No threshold hit recorded';
  $('sensorStatus').textContent = sensor.status === 'alert' ? 'Threshold hit' : sensor.status === 'offline' ? 'No recent data' : 'Below threshold';
  $('sensorStatus').className = `status-pill ${sensor.status}`;
  $('alertBanner').hidden = sensor.status !== 'alert';
  $('offlineBanner').hidden = sensor.status !== 'offline';
  const value = sensor.latest_value ?? 0;
  $('meterValue').textContent = formatNumber(sensor.latest_value);
  $('meterFill').style.width = `${Math.min(100, Math.max(0, value / 65535 * 100))}%`;
  const threshold = data.threshold ?? 0;
  $('thresholdMarker').style.left = `${Math.min(100, Math.max(0, threshold / 65535 * 100))}%`;
  $('thresholdLabel').textContent = `Threshold ${formatNumber(data.threshold)}`;
  $('updatedAt').textContent = formatDate(data.generated_at);
  $('rangeDescription').textContent = rangeDescriptions[data.period];
  $('sampleHint').textContent = `${numberFormat.format(sensor.points.reduce((sum, point) => sum + point.samples, 0))} readings grouped`;

  const cylinder = data.cylinder;
  if (cylinder.calibrated) {
    $('weightPercent').textContent = `${formatNumber(cylinder.percent_remaining)}% remaining`;
    $('weightFigure').textContent = `${formatNumber(cylinder.weight_grams / 1000)} kg gross`;
    $('cylinderFill').style.width = `${cylinder.percent_remaining}%`;
    $('weightDetails').textContent = `Latest load-cell reading: ${formatDate(cylinder.recorded_at)}.`;
  } else {
    $('weightPercent').textContent = cylinder.has_reading ? 'Weight received' : 'Waiting for load-cell data';
    $('weightFigure').textContent = cylinder.has_reading ? `${formatNumber(cylinder.weight_grams / 1000)} kg gross` : 'kg';
    $('cylinderFill').style.width = '0%';
    $('weightDetails').textContent = cylinder.has_reading
      ? 'Add full and empty cylinder gross weights in Azure settings to calculate the remaining percentage.'
      : 'No load-cell measurements are stored in Neon yet.';
  }
  renderChart(sensor.points, data.period);
}

//getting all the last data, values, and all type of true and false
async function fetchRecentData() {
  const button = $('refreshButton');
  button.disabled = true;
  button.textContent = 'Fetching…';
  try {
    const response = await fetch(`/api/dashboard?period=${encodeURIComponent(currentPeriod)}`, { cache: 'no-store' });
    if (!response.ok) throw new Error(`API returned ${response.status}`);
    const data = await response.json();
    renderData(data);
    $('errorBanner').hidden = true;
    setConnection(data.mq2.status === 'offline' ? 'down' : 'live', data.mq2.status === 'offline' ? 'No recent sensor data' : 'Connected');
  } catch (error) {
    $('errorBanner').textContent = `Could not get recent data: ${error.message}`;
    $('errorBanner').hidden = false;
    setConnection('down', 'Could not connect');
  } finally {
    button.disabled = false;
    button.textContent = 'Get recent data';
  }
}


function showView(view) {
  currentView = view;
  $('leakagePage').hidden = view !== 'leakage';
  $('weightPage').hidden = view !== 'weight';
  document.querySelectorAll('.nav-button').forEach((button) => {
    const active = button.dataset.view === view;
    button.classList.toggle('active', active);
    button.setAttribute('aria-pressed', String(active));
  });
}


document.querySelectorAll('.nav-button').forEach((button) => button.addEventListener('click', () => showView(button.dataset.view)));

document.querySelectorAll('.range-button').forEach((button) => button.addEventListener('click', () => {
  currentPeriod = button.dataset.period;
  document.querySelectorAll('.range-button').forEach((other) => {
    const active = other === button;
    other.classList.toggle('active', active);
    other.setAttribute('aria-pressed', String(active));
  });
  fetchRecentData();
}));
$('refreshButton').addEventListener('click', fetchRecentData);
fetchRecentData();
