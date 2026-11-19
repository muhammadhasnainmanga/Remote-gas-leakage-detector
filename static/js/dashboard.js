const $ = (id) => document.getElementById(id);
let chart = null;
let currentPeriod = 'daily';
const rangeDescriptions = { daily: 'Last 24 hours · hourly averages', weekly: 'Last 7 days · daily averages', monthly: 'Last 30 days · daily averages' };
const numberFormat = new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 });
const dateFormat = new Intl.DateTimeFormat(undefined, { timeZone: 'Asia/Karachi', dateStyle: 'medium', timeStyle: 'short' });
function formatNumber(value) { return value === null || value === undefined ? '—' : numberFormat.format(value); }
function formatDate(value) { if (!value) return '—'; const date = new Date(value); return Number.isNaN(date.getTime()) ? '—' : dateFormat.format(date); }
function setConnection(kind, text) { $('connectionDot').className = `connection-dot ${kind}`; $('connectionText').textContent = text; }
function setChart(points, period) {
  const empty = points.length === 0;
  $('chartEmpty').hidden = !empty;
  if (!window.Chart) { $('chartEmpty').hidden = false; $('chartEmpty').textContent = 'Chart library could not load. Refresh this page while online.'; return; }
  const labels = points.map((point) => {
    const date = new Date(point.time);
    return period === 'daily'
      ? date.toLocaleTimeString([], { timeZone: 'Asia/Karachi', hour: 'numeric' })
      : date.toLocaleDateString([], { timeZone: 'Asia/Karachi', month: 'short', day: 'numeric' });
  });
  const values = points.map((point) => point.average);
  if (!chart) {
    chart = new Chart($('readingsChart'), {
      type: 'line',
      data: { labels, datasets: [{ label: 'Average raw ADC', data: values, borderColor: '#4d7bea', backgroundColor: 'rgba(77,123,234,.12)', borderWidth: 2.5, fill: true, tension: .32, pointRadius: period === 'daily' ? 1 : 3, pointHoverRadius: 5, pointBackgroundColor: '#fff', pointBorderWidth: 2 }] },
      options: { responsive: true, maintainAspectRatio: false, interaction: { intersect: false, mode: 'index' }, plugins: { legend: { display: false }, tooltip: { displayColors: false } }, scales: { x: { grid: { display: false }, ticks: { color: '#96a1b1', maxTicksLimit: 8, maxRotation: 0 } }, y: { beginAtZero: false, grid: { color: '#edf1f5' }, ticks: { color: '#96a1b1', maxTicksLimit: 5 } } } },
    });
  } else {
    chart.data.labels = labels; chart.data.datasets[0].data = values;
    chart.data.datasets[0].pointRadius = period === 'daily' ? 1 : 3; chart.update();
  }
}
function render(data) {
  const sensor = data.mq2;
  $('currentValue').textContent = formatNumber(sensor.latest_value);
  $('meterValue').textContent = formatNumber(sensor.latest_value);
  $('dailyAverage').textContent = formatNumber(sensor.daily_average);
  $('currentReadingAt').textContent = sensor.latest_at ? `Last reading ${formatDate(sensor.latest_at)}` : 'Waiting for a reading';
  $('sensorStatus').textContent = sensor.status === 'alert' ? 'Threshold hit' : sensor.status === 'offline' ? 'No recent data' : 'Normal';
  $('sensorStatus').className = `status-pill ${sensor.status}`;
  $('alertBanner').hidden = sensor.status !== 'alert';
  $('offlineBanner').hidden = sensor.status !== 'offline';
  $('lastDetection').textContent = sensor.last_detection_at ? formatDate(sensor.last_detection_at) : 'No threshold hit recorded';
  $('emailsSent').textContent = formatNumber(data.emails.total);
  $('lastEmailAt').textContent = data.emails.last_sent_at ? `Last sent ${formatDate(data.emails.last_sent_at)}` : 'No successful email logged yet';
  const raw = sensor.latest_value ?? 0;
  $('meterFill').style.width = `${Math.min(100, Math.max(0, raw / 65535 * 100))}%`;
  const threshold = data.threshold ?? 0;
  $('thresholdMarker').style.left = `${Math.min(100, Math.max(0, threshold / 65535 * 100))}%`;
  $('thresholdLabel').textContent = `Threshold ${formatNumber(data.threshold)}`;
  const cylinder = data.cylinder;
  if (cylinder.calibrated) {
    $('cylinderPercent').textContent = `${formatNumber(cylinder.percent_remaining)}%`;
    $('cylinderWeight').textContent = `${formatNumber(cylinder.weight_grams / 1000)} kg gross`;
    $('cylinderFill').style.width = `${cylinder.percent_remaining}%`;
    $('cylinderMessage').textContent = `Updated ${formatDate(cylinder.recorded_at)} · based on configured full and empty cylinder weights.`;
  } else {
    $('cylinderPercent').textContent = '—';
    $('cylinderWeight').textContent = cylinder.has_reading ? `${formatNumber(cylinder.weight_grams / 1000)} kg gross` : 'No weight data';
    $('cylinderFill').style.width = '0%';
    $('cylinderMessage').textContent = cylinder.has_reading ? 'Weight received; add full and empty cylinder weights to calculate remaining gas.' : 'Waiting for load-cell readings and cylinder calibration.';
  }
  $('updatedAt').textContent = formatDate(data.generated_at);
  $('rangeDescription').textContent = rangeDescriptions[data.period];
  setChart(sensor.points, data.period);
}
async function refreshDashboard() {
  try {
    const response = await fetch(`/api/dashboard?period=${encodeURIComponent(currentPeriod)}`, { cache: 'no-store' });
    if (!response.ok) throw new Error(`Dashboard API returned ${response.status}`);
    const data = await response.json(); render(data); $('errorBanner').hidden = true;
    setConnection(data.mq2.status === 'offline' ? 'down' : 'live', data.mq2.status === 'offline' ? 'Waiting for sensor' : 'Connected to Neon');
  } catch (error) {
    $('errorBanner').textContent = `Could not load dashboard data: ${error.message}`;
    $('errorBanner').hidden = false; setConnection('down', 'API unavailable');
  }
}
document.querySelectorAll('.range-button').forEach((button) => {
  button.addEventListener('click', () => {
    currentPeriod = button.dataset.period;
    document.querySelectorAll('.range-button').forEach((other) => {
      const active = other === button; other.classList.toggle('active', active); other.setAttribute('aria-pressed', String(active));
    });
    refreshDashboard();
  });
});
refreshDashboard();
window.setInterval(refreshDashboard, 15000);
