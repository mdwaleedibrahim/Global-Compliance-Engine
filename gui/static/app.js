/* GCE Control Center — Frontend Logic */

// ============================================================
// State & Config
// ============================================================
const REFRESH_INTERVAL = 5000;
let currentSection = 'services';
let refreshTimer = null;
let rmsChart = null;
let perfOrderChart = null;
let perfControlChart = null;

// ============================================================
// Navigation
// ============================================================
document.querySelectorAll('.nav-item').forEach(item => {
  item.addEventListener('click', () => {
    const section = item.dataset.section;
    if (!section) return;
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
    item.classList.add('active');
    document.querySelectorAll('.section-panel').forEach(p => p.classList.remove('active'));
    const panel = document.getElementById('panel-' + section);
    if (panel) panel.classList.add('active');
    const titles = {
      services: 'Services', limits: 'GCE Limits', oms: 'OMS Browser',
      prices: 'Prices', instruments: 'Instruments', sessions: 'Exchange Sessions',
      reconciliation: 'Reconciliation', positions: 'Positions',
      rms: 'RMS Controls Summary', performance: 'Performance'
    };
    document.getElementById('section-title').textContent = titles[section] || section;
    currentSection = section;
    refreshCurrentSection();
  });
});

// ============================================================
// API Helper
// ============================================================
async function api(path) {
  try {
    const r = await fetch(path);
    return await r.json();
  } catch (e) {
    console.error('API error:', path, e);
    return null;
  }
}

async function apiPost(path) {
  try {
    const r = await fetch(path, { method: 'POST' });
    return await r.json();
  } catch (e) {
    console.error('API POST error:', path, e);
    return null;
  }
}

// ============================================================
// Section 1: Services
// ============================================================
async function loadServices() {
  const data = await api('/api/status');
  if (!data) return;
  const grid = document.getElementById('services-grid');
  const icons = { engine: '⚙️', pxfeeder: '📡', logger: '📝', datamgr: '🗄️' };
  const labels = { engine: 'GCE Engine', pxfeeder: 'PX Feeder', logger: 'Log Worker', datamgr: 'Data Manager' };

  grid.innerHTML = data.map(s => {
    const icon = icons[s.name] || '🔧';
    const label = labels[s.name] || s.name;
    const st = s.status;
    const canStop = s.name !== 'engine' && s.name !== 'datamgr';
    return `
      <div class="card service-card">
        <div class="service-icon ${st}">${icon}</div>
        <div class="service-info">
          <div class="service-name">${label}</div>
          <div class="service-detail">${s.detail || ''}</div>
        </div>
        <span class="service-status-badge badge-${st}">${st}</span>
        <div class="service-actions">
          ${st === 'stopped' ? `<button class="btn btn-success btn-sm" onclick="svcAction('${s.name}','start')">Start</button>` : ''}
          ${st === 'running' && canStop ? `<button class="btn btn-danger btn-sm" onclick="svcAction('${s.name}','stop')">Stop</button>` : ''}
          ${canStop ? `<button class="btn btn-ghost btn-sm" onclick="svcAction('${s.name}','restart')">↻</button>` : ''}
        </div>
      </div>`;
  }).join('');

  // Update status bar
  const eng = data.find(s => s.name === 'engine');
  if (eng) {
    const dot = document.getElementById('engine-dot');
    dot.className = 'status-dot ' + (eng.status === 'running' ? 'green pulse' : 'red');
    document.getElementById('engine-status-text').textContent = eng.status === 'running' ? 'Running' : 'Stopped';
    document.getElementById('status-uptime').textContent = eng.detail || '';
  }
}

async function svcAction(name, action) {
  await apiPost(`/api/service/${name}/${action}`);
  setTimeout(loadServices, 300);
}

// ============================================================
// Pagination Helper (Shows when > 20 records, 50 per page)
// ============================================================
const PAGE_SIZE = 50;

function renderPaginationBar(containerId, totalCount, currentPage, pageSize, onPageChange, labelText = 'Total Records') {
  const container = document.getElementById(containerId);
  if (!container) return;

  if (totalCount <= 20) {
    container.style.display = 'none';
    container.innerHTML = '';
    return;
  }

  container.style.display = 'flex';
  const totalPages = Math.ceil(totalCount / pageSize);
  const safePage = Math.max(1, Math.min(currentPage, totalPages));

  container.innerHTML = `
    <div class="pagination-info">
      <span>${labelText}: <strong style="color:var(--text-bright)">${totalCount.toLocaleString()}</strong></span>
    </div>
    <div class="pagination-controls">
      <button class="pagination-btn" id="${containerId}-prev" ${safePage <= 1 ? 'disabled' : ''}>⏮ Prev</button>
      <span class="page-indicator">Page <strong style="color:var(--text-bright)">${safePage}</strong> of <strong>${totalPages}</strong></span>
      <button class="pagination-btn" id="${containerId}-next" ${safePage >= totalPages ? 'disabled' : ''}>Next ⏭</button>
    </div>
  `;

  const prevBtn = document.getElementById(`${containerId}-prev`);
  const nextBtn = document.getElementById(`${containerId}-next`);

  if (prevBtn) {
    prevBtn.onclick = () => {
      if (safePage > 1) onPageChange(safePage - 1);
    };
  }

  if (nextBtn) {
    nextBtn.onclick = () => {
      if (safePage < totalPages) onPageChange(safePage + 1);
    };
  }
}

// ============================================================
// Section 3: OMS Browser
// ============================================================
let omsAllFilteredOrders = [];
let omsPage = 1;

async function loadOrders() {
  const data = await api('/api/orders');
  if (!data) return;
  document.getElementById('order-count-badge').textContent = data.length;

  const search = (document.getElementById('oms-search').value || '').toLowerCase();
  const statusFilter = document.getElementById('oms-status-filter').value;

  let filtered = data;
  if (search) {
    filtered = filtered.filter(o =>
      (o.order_id || '').toLowerCase().includes(search) ||
      (o.ric || '').toLowerCase().includes(search) ||
      (o.symbol || '').toLowerCase().includes(search) ||
      (o.trader || '').toLowerCase().includes(search)
    );
  }
  if (statusFilter) {
    filtered = filtered.filter(o => o.status === statusFilter);
  }

  omsAllFilteredOrders = filtered;
  omsPage = 1;
  renderOMSTable();
}

function renderOMSTable() {
  const tbody = document.getElementById('oms-tbody');
  const empty = document.getElementById('oms-empty');
  const total = omsAllFilteredOrders.length;

  if (total === 0) {
    tbody.innerHTML = '';
    empty.style.display = 'block';
    renderPaginationBar('oms-pagination', 0, 1, PAGE_SIZE, () => {}, 'Total Records');
    return;
  }
  empty.style.display = 'none';

  const startIdx = (omsPage - 1) * PAGE_SIZE;
  const pageSlice = omsAllFilteredOrders.slice(startIdx, startIdx + PAGE_SIZE);

  tbody.innerHTML = pageSlice.map(o => {
    const sideBadge = o.side === 'B' ? 'badge-buy' : 'badge-sell';
    const sideLabel = o.side === 'B' ? 'BUY' : 'SELL';
    let statusBadge = 'badge-live';
    const sl = (o.status || '').toLowerCase();
    if (sl.includes('reject')) statusBadge = 'badge-rejected';
    else if (sl.includes('fill')) statusBadge = 'badge-fill';
    else if (sl.includes('cancel')) statusBadge = 'badge-cancelled';

    return `<tr>
      <td style="color:var(--text-bright);font-weight:500">${o.order_id}</td>
      <td>${o.ric || o.symbol}</td>
      <td><span class="badge ${sideBadge}">${sideLabel}</span></td>
      <td>${(o.quantity || 0).toLocaleString()}</td>
      <td>${(o.price || 0).toFixed(2)}</td>
      <td><span class="badge ${statusBadge}">${o.status}</span></td>
      <td>${o.trader}</td>
      <td>${o.account}</td>
      <td>${o.filled || 0}</td>
      <td style="font-size:11px;color:var(--text-muted)">${(o.timestamp || '').substring(0, 19)}</td>
    </tr>`;
  }).join('');

  renderPaginationBar('oms-pagination', total, omsPage, PAGE_SIZE, newPage => {
    omsPage = newPage;
    renderOMSTable();
  }, 'Total Records');
}

// Wire up search/filter
document.getElementById('oms-search').addEventListener('input', loadOrders);
document.getElementById('oms-status-filter').addEventListener('change', loadOrders);

// ============================================================
// Section 4: Prices & FX
// ============================================================
let pricesAllData = [];
let pricesPage = 1;

async function loadPrices() {
  const data = await api('/api/prices');
  pricesAllData = data || [];
  pricesPage = 1;
  renderPricesTable();
}

function renderPricesTable() {
  const tbody = document.getElementById('prices-tbody');
  const empty = document.getElementById('prices-empty');
  const total = pricesAllData.length;

  if (total === 0) {
    tbody.innerHTML = '';
    empty.style.display = 'block';
    renderPaginationBar('prices-pagination', 0, 1, PAGE_SIZE, () => {}, 'Total Records');
    return;
  }
  empty.style.display = 'none';

  const startIdx = (pricesPage - 1) * PAGE_SIZE;
  const pageSlice = pricesAllData.slice(startIdx, startIdx + PAGE_SIZE);

  tbody.innerHTML = pageSlice.map(p => `<tr>
    <td style="color:var(--text-bright);font-weight:500">${p.ric}</td>
    <td>${(p.open || 0).toFixed(2)}</td>
    <td>${(p.bid || 0).toFixed(2)}</td>
    <td>${(p.ask || 0).toFixed(2)}</td>
    <td>${(p.last || 0).toFixed(2)}</td>
    <td>${(p.close || 0).toFixed(2)}</td>
    <td>${(p.mid || 0).toFixed(2)}</td>
  </tr>`).join('');

  renderPaginationBar('prices-pagination', total, pricesPage, PAGE_SIZE, newPage => {
    pricesPage = newPage;
    renderPricesTable();
  }, 'Total Records');
}

async function loadFX() {
  const data = await api('/api/fx');
  const grid = document.getElementById('fx-grid');
  const empty = document.getElementById('fx-empty');
  if (!data || Object.keys(data).length === 0) {
    grid.innerHTML = '';
    empty.style.display = 'block';
    return;
  }
  empty.style.display = 'none';
  grid.innerHTML = Object.entries(data).map(([pair, rate]) => `
    <div class="card fx-card">
      <div class="fx-pair">${pair}</div>
      <div class="fx-rate">${Number(rate).toFixed(4)}</div>
    </div>`).join('');
}

function switchPriceTab(tab) {
  document.querySelectorAll('#panel-prices .tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('#panel-prices .tab-content').forEach(c => c.classList.remove('active'));
  if (tab === 'market') {
    document.querySelector('#panel-prices .tab-btn:first-child').classList.add('active');
    document.getElementById('tab-market').classList.add('active');
  } else {
    document.querySelector('#panel-prices .tab-btn:last-child').classList.add('active');
    document.getElementById('tab-fx').classList.add('active');
  }
}

// ============================================================
// Section 5: Instruments
// ============================================================
let instrAllData = [];
let instrPage = 1;

async function loadInstruments() {
  const search = document.getElementById('instr-search').value || '';
  const data = await api(`/api/instruments?search=${encodeURIComponent(search)}&limit=0`);
  instrAllData = data || [];
  instrPage = 1;
  renderInstrTable();
}

function renderInstrTable() {
  const tbody = document.getElementById('instr-tbody');
  const empty = document.getElementById('instr-empty');
  const total = instrAllData.length;

  if (total === 0) {
    tbody.innerHTML = '';
    empty.style.display = 'block';
    renderPaginationBar('instr-pagination', 0, 1, PAGE_SIZE, () => {}, 'Total Instruments');
    return;
  }
  empty.style.display = 'none';

  const startIdx = (instrPage - 1) * PAGE_SIZE;
  const pageSlice = instrAllData.slice(startIdx, startIdx + PAGE_SIZE);

  tbody.innerHTML = pageSlice.map(i => `<tr>
    <td style="color:var(--text-bright);font-weight:500">${i.ric}</td>
    <td>${i.stock_code}</td>
    <td>${i.name}</td>
    <td>${i.category}</td>
    <td>${(i.board_lot || 0).toLocaleString()}</td>
    <td>${i.currency}</td>
    <td>${i.shortsell ? '✅' : '—'}</td>
    <td>${i.cas ? '✅' : '—'}</td>
    <td>${i.vcm ? '✅' : '—'}</td>
  </tr>`).join('');

  renderPaginationBar('instr-pagination', total, instrPage, PAGE_SIZE, newPage => {
    instrPage = newPage;
    renderInstrTable();
  }, 'Total Instruments');
}

document.getElementById('instr-search').addEventListener('input', debounce(loadInstruments, 300));

// ============================================================
// Section 6: Exchange Sessions
// ============================================================
async function loadSessions() {
  const data = await api('/api/sessions');
  const container = document.getElementById('sessions-content');
  if (!data || Object.keys(data).length === 0) {
    container.innerHTML = '<div class="empty-state">No session data available</div>';
    return;
  }
  container.innerHTML = Object.entries(data).map(([exchange, info]) => {
    const stateBadge = info.state === 'trading' ? 'badge-trading' :
                       info.state === 'break' ? 'badge-break' : 'badge-closed';
    const stateLabel = info.status_text || (info.state || 'closed').toUpperCase();
    const sessions = (info.sessions || []).map(s =>
      `<div class="session-block trading" style="flex:1;padding:8px 12px">Session ${s.session} (${s.start}–${s.end})</div>`
    ).join('<div class="session-block break" style="flex:0.2;padding:8px 6px">Break</div>');

    return `<div class="session-exchange" style="margin-bottom:24px">
      <div class="session-exchange-name" style="margin-bottom:10px;font-size:14px;font-weight:600;display:flex;align-items:center;gap:10px">
        🏛️ ${exchange} <span class="badge ${stateBadge}">${stateLabel}</span>
      </div>
      <div class="session-timeline" style="display:flex;gap:6px">${sessions}</div>
    </div>`;
  }).join('');
}

async function reloadSessions() {
  await apiPost('/api/sessions/update');
  loadSessions();
}

// ============================================================
// Section 7: Reconciliation
// ============================================================
async function runReconciliation() {
  const data = await api('/api/reconciliation');
  const tbody = document.getElementById('recon-tbody');
  const empty = document.getElementById('recon-empty');
  const results = data && data.results ? data.results : (Array.isArray(data) ? data : []);
  if (results.length === 0) {
    tbody.innerHTML = '';
    empty.style.display = 'block';
    empty.textContent = data && data.error ? `Error: ${data.error}` : 'No reconciliation data';
    return;
  }
  empty.style.display = 'none';
  tbody.innerHTML = results.map(r => {
    let badge = 'badge-match';
    if (r.status === 'VARIANCE') badge = 'badge-variance';
    else if (r.status === 'MISSING_POSITION') badge = 'badge-missing';
    return `<tr>
      <td style="color:var(--text-bright);font-weight:500">${r.symbol}</td>
      <td>${r.trader || '—'}</td>
      <td>${r.total_orders}</td>
      <td>${r.filled_orders || 0}</td>
      <td>${r.net_quantity}</td>
      <td>${r.qty_variance}</td>
      <td><span class="badge ${badge}">${r.status}</span></td>
      <td style="font-size:11px;color:var(--text-muted)">${(r.issues || []).join('; ') || '—'}</td>
    </tr>`;
  }).join('');
}

// ============================================================
// Section 9: RMS Controls Summary
// ============================================================
async function loadRMS() {
  const data = await api('/api/rms/summary');
  if (!data) return;

  // Stat cards
  const statsEl = document.getElementById('rms-stats-cards');
  statsEl.innerHTML = `
    <div class="card stat-card"><div class="stat-value blue">${data.total_orders || 0}</div><div class="stat-label">Total Orders</div></div>
    <div class="card stat-card"><div class="stat-value green">${data.total_checks || 0}</div><div class="stat-label">Total Checks</div></div>
    <div class="card stat-card"><div class="stat-value amber">${Object.keys(data.controls || {}).length}</div><div class="stat-label">Controls Active</div></div>`;

  const controls = data.controls || {};
  const labels = Object.keys(controls);
  const passData = labels.map(l => controls[l].pass);
  const failData = labels.map(l => controls[l].fail);

  // Table
  const tbody = document.getElementById('rms-tbody');
  tbody.innerHTML = labels.map(l => {
    const c = controls[l];
    return `<tr class="clickable-row" onclick="drillDownRMS('${l}')">
      <td style="color:var(--text-bright);font-weight:500">${l}</td>
      <td><span class="badge badge-pass">${c.pass}</span></td>
      <td><span class="badge badge-fail">${c.fail}</span></td>
      <td>${c.total}</td>
      <td>${c.pass_rate}%</td>
    </tr>`;
  }).join('');

  // Chart
  const ctx = document.getElementById('rms-chart');
  if (rmsChart) rmsChart.destroy();
  rmsChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: labels,
      datasets: [
        { label: 'Pass', data: passData, backgroundColor: 'rgba(16, 185, 129, 0.6)', borderColor: 'rgba(16, 185, 129, 1)', borderWidth: 1 },
        { label: 'Fail', data: failData, backgroundColor: 'rgba(244, 63, 94, 0.6)', borderColor: 'rgba(244, 63, 94, 1)', borderWidth: 1 }
      ]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { labels: { color: '#94a3b8', font: { family: 'Inter' } } } },
      scales: {
        x: { ticks: { color: '#64748b', font: { size: 10 } }, grid: { color: 'rgba(148,163,184,0.06)' } },
        y: { ticks: { color: '#64748b' }, grid: { color: 'rgba(148,163,184,0.06)' }, beginAtZero: true }
      },
      onClick: (e, elems) => {
        if (elems.length > 0) {
          const idx = elems[0].index;
          drillDownRMS(labels[idx]);
        }
      }
    }
  });
}

async function drillDownRMS(control) {
  const data = await api(`/api/rms/orders/${encodeURIComponent(control)}/`);
  if (!data) return;
  const container = document.getElementById('rms-drilldown');
  const title = document.getElementById('rms-drilldown-title');
  const tbody = document.getElementById('rms-drilldown-tbody');
  container.style.display = 'block';
  title.textContent = `📋 ${control} — ${data.length} check(s)`;
  tbody.innerHTML = data.map(o => {
    const badge = o.status === 'PASS' ? 'badge-pass' : 'badge-fail';
    const nsDisplay = o.elapsed_ns ? `${o.elapsed_ns}ns` : '—';
    return `<tr>
      <td style="font-size:11px;color:var(--text-muted)">${o.timestamp || ''}</td>
      <td>${o.control}</td>
      <td><span class="badge ${badge}">${o.status}</span></td>
      <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis">${o.message}</td>
      <td>${o.limit || '—'}</td>
      <td>${o.order_value || '—'}</td>
      <td style="font-size:11px">${o.source || '—'}</td>
      <td style="font-size:11px">${nsDisplay}</td>
    </tr>`;
  }).join('');
}

// ============================================================
// Section 10: Performance
// ============================================================
async function loadPerformance() {
  const data = await api('/api/performance');
  if (!data) return;

  const stats = data.stats || {};
  const statsEl = document.getElementById('perf-stats-cards');
  statsEl.innerHTML = `
    <div class="card stat-card"><div class="stat-value blue">${stats.avg_ms || 0}ms</div><div class="stat-label">Avg Latency</div></div>
    <div class="card stat-card"><div class="stat-value amber">${stats.p95_ms || 0}ms</div><div class="stat-label">P95 Latency</div></div>
    <div class="card stat-card"><div class="stat-value green">${stats.min_ms || 0}ms</div><div class="stat-label">Min Latency</div></div>
    <div class="card stat-card"><div class="stat-value red">${stats.max_ms || 0}ms</div><div class="stat-label">Max Latency</div></div>`;

  // Order time chart
  const orderTimes = data.order_times_ms || [];
  const orderLabels = orderTimes.map((_, i) => `#${i + 1}`);
  const ctxOrder = document.getElementById('perf-order-chart');
  if (perfOrderChart) perfOrderChart.destroy();
  perfOrderChart = new Chart(ctxOrder, {
    type: 'line',
    data: {
      labels: orderLabels,
      datasets: [{
        label: 'Validation Time (ms)',
        data: orderTimes,
        borderColor: 'rgba(59, 130, 246, 1)',
        backgroundColor: 'rgba(59, 130, 246, 0.1)',
        fill: true, tension: 0.3, pointRadius: 2, borderWidth: 2
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { labels: { color: '#94a3b8', font: { family: 'Inter' } } } },
      scales: {
        x: { ticks: { color: '#64748b', font: { size: 10 }, maxTicksLimit: 20 }, grid: { color: 'rgba(148,163,184,0.06)' } },
        y: { ticks: { color: '#64748b' }, grid: { color: 'rgba(148,163,184,0.06)' }, beginAtZero: true, title: { display: true, text: 'ms', color: '#64748b' } }
      }
    }
  });

  // Per-control timing chart (last 20 orders)
  const timings = data.control_timings || [];
  const maxOrder = Math.max(...timings.map(t => t.order_index), -1);
  const startIdx = Math.max(0, maxOrder - 19);
  const recentTimings = timings.filter(t => t.order_index >= startIdx);

  // Group by control
  const controlNames = [...new Set(recentTimings.map(t => t.control))];
  const orderIndices = [...new Set(recentTimings.map(t => t.order_index))].sort((a, b) => a - b);
  const ctrlLabels = orderIndices.map(i => `#${i + 1}`);

  const colors = [
    'rgba(59,130,246,0.7)', 'rgba(16,185,129,0.7)', 'rgba(244,63,94,0.7)',
    'rgba(245,158,11,0.7)', 'rgba(168,85,247,0.7)', 'rgba(34,211,238,0.7)'
  ];

  const datasets = controlNames.map((ctrl, ci) => {
    const vals = orderIndices.map(idx => {
      const match = recentTimings.find(t => t.order_index === idx && t.control === ctrl);
      return match ? match.elapsed_ns : 0;
    });
    return {
      label: ctrl, data: vals,
      backgroundColor: colors[ci % colors.length],
      borderWidth: 0
    };
  });

  const ctxCtrl = document.getElementById('perf-control-chart');
  if (perfControlChart) perfControlChart.destroy();
  perfControlChart = new Chart(ctxCtrl, {
    type: 'bar',
    data: { labels: ctrlLabels, datasets },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { labels: { color: '#94a3b8', font: { family: 'Inter', size: 10 } } } },
      scales: {
        x: { stacked: true, ticks: { color: '#64748b', font: { size: 10 } }, grid: { color: 'rgba(148,163,184,0.06)' } },
        y: { stacked: true, ticks: { color: '#64748b' }, grid: { color: 'rgba(148,163,184,0.06)' }, beginAtZero: true, title: { display: true, text: 'ns', color: '#64748b' } }
      }
    }
  });
}

// ============================================================
// Refresh Logic
// ============================================================
function refreshCurrentSection() {
  const ts = new Date().toLocaleTimeString();
  document.getElementById('last-refresh').textContent = ts;
  switch (currentSection) {
    case 'services': loadServices(); break;
    case 'oms': loadOrders(); break;
    case 'prices': loadPrices(); loadFX(); break;
    case 'instruments': loadInstruments(); break;
    case 'sessions': loadSessions(); break;
    case 'rms': loadRMS(); break;
    case 'performance': loadPerformance(); break;
  }
}

// Auto-refresh for services and prices
setInterval(() => {
  if (currentSection === 'services') loadServices();
  if (currentSection === 'prices') { loadPrices(); loadFX(); }
}, REFRESH_INTERVAL);

// ============================================================
// Utility
// ============================================================
function debounce(fn, ms) {
  let t;
  return function (...args) {
    clearTimeout(t);
    t = setTimeout(() => fn.apply(this, args), ms);
  };
}

// ============================================================
// Initial Load
// ============================================================
loadServices();
