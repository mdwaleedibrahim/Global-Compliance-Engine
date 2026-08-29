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
// Custom Dialog Modal System (Replaces native alert/confirm)
// Suppresses browser origin headers (e.g. "localhost:5050 says")
// ============================================================
function showAlert(message, title = 'Notification', type = 'info') {
  return new Promise((resolve) => {
    const modal = document.getElementById('gce-dialog-modal');
    if (!modal) {
      console.log(`[Alert] ${title}:`, message);
      return resolve(true);
    }
    const titleEl = document.getElementById('gce-dialog-title');
    const msgEl = document.getElementById('gce-dialog-message');
    const iconEl = document.getElementById('gce-dialog-icon');
    const inputContainer = document.getElementById('gce-dialog-input-container');
    const cancelBtn = document.getElementById('gce-dialog-cancel-btn');
    const okBtn = document.getElementById('gce-dialog-ok-btn');
    const closeBtn = document.getElementById('gce-dialog-close-btn');

    const msgStr = typeof message === 'object' ? JSON.stringify(message, null, 2) : String(message || '');
    const isError = type === 'error' || /error|failed|invalid|reject|cannot|fail/i.test(title + ' ' + msgStr);
    const isSuccess = type === 'success' || /success|saved|copied|completed|uploaded|imported/i.test(title + ' ' + msgStr);
    const isWarning = type === 'warning' || /warning|caution|required|select/i.test(title + ' ' + msgStr);

    if (isError) {
      iconEl.textContent = '❌';
      titleEl.innerHTML = `<span style="color:#f87171">⚠️ ${title || 'Error'}</span>`;
    } else if (isSuccess) {
      iconEl.textContent = '✅';
      titleEl.innerHTML = `<span style="color:#4ade80">✓ ${title || 'Success'}</span>`;
    } else if (isWarning) {
      iconEl.textContent = '⚠️';
      titleEl.innerHTML = `<span style="color:#fbbf24">⚠️ ${title || 'Notice'}</span>`;
    } else {
      iconEl.textContent = 'ℹ️';
      titleEl.innerHTML = `<span style="color:#38bdf8">ℹ️ ${title || 'Notification'}</span>`;
    }

    msgEl.innerHTML = msgStr.replace(/\n/g, '<br>');
    if (inputContainer) inputContainer.style.display = 'none';
    if (cancelBtn) cancelBtn.style.display = 'none';
    if (okBtn) {
      okBtn.textContent = 'OK';
      okBtn.className = isError ? 'btn btn-danger' : 'btn btn-primary';
    }

    const cleanup = () => {
      okBtn.removeEventListener('click', closeHandler);
      closeBtn.removeEventListener('click', closeHandler);
      document.removeEventListener('keydown', keyHandler);
    };

    const closeHandler = () => {
      modal.style.display = 'none';
      cleanup();
      resolve(true);
    };

    const keyHandler = (e) => {
      if (e.key === 'Enter' || e.key === 'Escape') {
        e.preventDefault();
        closeHandler();
      }
    };

    okBtn.addEventListener('click', closeHandler);
    closeBtn.addEventListener('click', closeHandler);
    document.addEventListener('keydown', keyHandler);

    modal.style.display = 'flex';
    setTimeout(() => { if (okBtn) okBtn.focus(); }, 50);
  });
}

function showConfirm(message, title = 'Confirm Action', options = {}) {
  return new Promise((resolve) => {
    const modal = document.getElementById('gce-dialog-modal');
    if (!modal) return resolve(true);

    const titleEl = document.getElementById('gce-dialog-title');
    const msgEl = document.getElementById('gce-dialog-message');
    const iconEl = document.getElementById('gce-dialog-icon');
    const inputContainer = document.getElementById('gce-dialog-input-container');
    const cancelBtn = document.getElementById('gce-dialog-cancel-btn');
    const okBtn = document.getElementById('gce-dialog-ok-btn');
    const closeBtn = document.getElementById('gce-dialog-close-btn');

    const msgStr = typeof message === 'object' ? JSON.stringify(message, null, 2) : String(message || '');
    const isDanger = options.danger || /delete|remove|stop|discard/i.test(title + ' ' + msgStr);

    iconEl.textContent = isDanger ? '🗑️' : '❓';
    titleEl.innerHTML = `<span style="color:${isDanger ? '#f87171' : '#38bdf8'}">${isDanger ? '⚠️' : '❓'} ${title}</span>`;
    msgEl.innerHTML = msgStr.replace(/\n/g, '<br>');

    if (inputContainer) inputContainer.style.display = 'none';
    if (cancelBtn) {
      cancelBtn.style.display = 'inline-flex';
      cancelBtn.textContent = options.cancelText || 'Cancel';
    }
    if (okBtn) {
      okBtn.textContent = options.confirmText || (isDanger ? 'Delete' : 'Confirm');
      okBtn.className = isDanger ? 'btn btn-danger' : 'btn btn-primary';
    }

    const cleanup = () => {
      okBtn.removeEventListener('click', confirmHandler);
      cancelBtn.removeEventListener('click', cancelHandler);
      closeBtn.removeEventListener('click', cancelHandler);
      document.removeEventListener('keydown', keyHandler);
    };

    const confirmHandler = () => {
      modal.style.display = 'none';
      cleanup();
      resolve(true);
    };

    const cancelHandler = () => {
      modal.style.display = 'none';
      cleanup();
      resolve(false);
    };

    const keyHandler = (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        confirmHandler();
      } else if (e.key === 'Escape') {
        e.preventDefault();
        cancelHandler();
      }
    };

    okBtn.addEventListener('click', confirmHandler);
    cancelBtn.addEventListener('click', cancelHandler);
    closeBtn.addEventListener('click', cancelHandler);
    document.addEventListener('keydown', keyHandler);

    modal.style.display = 'flex';
    setTimeout(() => { if (okBtn) okBtn.focus(); }, 50);
  });
}

// Global browser popup interception to eliminate browser origin headers
window.alert = (msg, title, type) => showAlert(msg, title, type);
window.confirm = (msg, title, options) => showConfirm(msg, title, options);

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
      services: 'Services', orders: 'Place Order', limits: 'GCE Limits', oms: 'OMS Browser',
      prices: 'Prices', instruments: 'Instruments', sessions: 'Exchange Sessions',
      reconciliation: 'Reconciliation', logs: 'Log Viewer', positions: 'Positions',
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

async function apiPost(path, body = null) {
  try {
    const opts = { method: 'POST' };
    if (body !== null && body !== undefined) {
      opts.headers = { 'Content-Type': 'application/json' };
      opts.body = typeof body === 'string' ? body : JSON.stringify(body);
    }
    const r = await fetch(path, opts);
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
  const grid = document.getElementById('services-grid');
  const data = await api('/api/status');
  if (!data || !grid) return;
  const icons = { engine: '⚙️', pxfeeder: '📡', logger: '📝', datamgr: '🗄️' };
  const labels = { engine: 'GCE Engine', pxfeeder: 'PX Feeder', logger: 'Log Worker', datamgr: 'Data Manager' };

  grid.innerHTML = data.map(s => {
    const icon = icons[s.name] || '🔧';
    const label = labels[s.name] || s.name;
    const st = (s.status === 'running' || s.status === 'ready') ? 'running' : 'stopped';
    const displayStatus = s.status;
    const canStop = s.name !== 'engine' && s.name !== 'datamgr';
    return `
      <div class="card service-card">
        <div class="service-icon ${st}">${icon}</div>
        <div class="service-info">
          <div class="service-name">${label}</div>
          <div class="service-detail">${s.detail || ''}</div>
        </div>
        <span class="service-status-badge badge-${st}">${displayStatus}</span>
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
    if (dot) dot.className = 'status-dot ' + (eng.status === 'running' ? 'green pulse' : 'red');
    const engStatusEl = document.getElementById('engine-status-text');
    if (engStatusEl) engStatusEl.textContent = eng.status === 'running' ? 'Running' : 'Stopped';
    const uptimeEl = document.getElementById('status-uptime');
    if (uptimeEl) uptimeEl.textContent = eng.detail || '';
  }
}

async function svcAction(name, action) {
  await apiPost(`/api/service/${name}/${action}`);
  setTimeout(loadServices, 300);
}

// ============================================================
// Section 2: GCE Limits (RMS Control Limits CRUD & Import/Export)
// ============================================================
let limitsAllData = [];
let limitsPage = 1;
let limitsOptions = null;

async function loadLimits() {
  const [data, options] = await Promise.all([
    api('/api/limits'),
    api('/api/limits/options')
  ]);

  limitsAllData = data || [];
  limitsOptions = options || {};
  populateLimitOptions();
  limitsPage = 1;
  filterAndRenderLimits();
}

function populateLimitOptions() {
  if (!limitsOptions) return;

  const populateSelect = (selectId, optionsList, defaultVal = '*') => {
    const el = document.getElementById(selectId);
    if (!el) return;
    const current = el.value || defaultVal;
    el.innerHTML = (optionsList || []).map(opt => `<option value="${opt}">${opt}</option>`).join('');
    if ((optionsList || []).includes(current)) el.value = current;
    else if (optionsList && optionsList.length > 0) el.value = optionsList[0];
  };

  // Populate search filter dropdowns
  populateSelect('limits-product-filter', ['All Products', ...(limitsOptions.Product || []).filter(p => p !== '*')], 'All Products');
  populateSelect('limits-sectype-filter', ['All SecurityTypes', ...(limitsOptions.SecurityType || []).filter(s => s !== '*')], 'All SecurityTypes');

  // Populate modal form dropdowns
  populateSelect('field-product', limitsOptions.Product || ['*'], '*');
  populateSelect('field-securitytype', limitsOptions.SecurityType || ['*'], '*');
  populateSelect('field-currency', limitsOptions.Currency || ['*'], '*');
  populateSelect('field-side', limitsOptions.Side || ['*', 'B', 'S', 'SS'], '*');
  populateSelect('field-ordertype', limitsOptions.OrderType || ['*', 'LMT', 'MKT'], '*');
  populateSelect('field-tif', limitsOptions.Tif || ['*', 'DAY', 'OPG', 'CLO'], '*');
  populateSelect('field-exchange', limitsOptions.exchange || ['*', 'XHKG', 'XSES'], '*');
  populateSelect('field-restricted', limitsOptions.Restricted || ['N', 'Y'], 'N');
  populateSelect('field-ssrestricted', limitsOptions.SSRestricted || ['N', 'Y'], 'N');
  populateSelect('field-enabled', limitsOptions.Enabled || ['Y', 'N'], 'Y');
}

let columnFilters = {};

function filterAndRenderLimits() {
  const search = (document.getElementById('limits-search').value || '').toLowerCase();
  const prodFilter = document.getElementById('limits-product-filter').value;
  const secTypeFilter = document.getElementById('limits-sectype-filter').value;
  const enabledFilter = document.getElementById('limits-enabled-filter').value;

  let filtered = limitsAllData;

  // Global toolbar search filter across all fields
  if (search) {
    filtered = filtered.filter(r =>
      Object.values(r).some(val => String(val || '').toLowerCase().includes(search))
    );
  }

  if (prodFilter && prodFilter !== 'All Products') {
    filtered = filtered.filter(r => r.Product === prodFilter);
  }

  if (secTypeFilter && secTypeFilter !== 'All SecurityTypes') {
    filtered = filtered.filter(r => r.SecurityType === secTypeFilter);
  }

  if (enabledFilter) {
    filtered = filtered.filter(r => r.Enabled === enabledFilter);
  }

  // Column-specific header filters
  Object.keys(columnFilters).forEach(col => {
    const term = (columnFilters[col] || '').trim().toLowerCase();
    if (!term) return;

    filtered = filtered.filter(r => {
      const val = r[col];
      if (val === undefined || val === null) return false;

      // Handle numerical search comparisons like '>1000' or '<50'
      if (/^[><=]/.test(term)) {
        const op = term[0];
        const numVal = parseFloat(term.slice(1));
        const cellVal = parseFloat(val);
        if (isNaN(numVal) || isNaN(cellVal)) return false;
        if (op === '>') return cellVal > numVal;
        if (op === '<') return cellVal < numVal;
        if (op === '=') return cellVal === numVal;
      }

      return String(val).toLowerCase().includes(term);
    });
  });

  renderLimitsTable(filtered);
}

function renderLimitsTable(data) {
  const tbody = document.getElementById('limits-tbody');
  const empty = document.getElementById('limits-empty');
  const total = data.length;

  if (total === 0) {
    tbody.innerHTML = '';
    empty.style.display = 'block';
    renderPaginationBar('limits-pagination', 0, 1, PAGE_SIZE, () => {}, 'Total Rules');
    return;
  }
  empty.style.display = 'none';

  const startIdx = (limitsPage - 1) * PAGE_SIZE;
  const pageSlice = data.slice(startIdx, startIdx + PAGE_SIZE);

  tbody.innerHTML = pageSlice.map(r => {
    const isEnabled = (r.Enabled || 'Y') === 'Y';
    const enabledBadge = isEnabled ? '<span class="badge badge-pass">Y</span>' : '<span class="badge badge-fail">N</span>';

    return `<tr>
      <td style="color:var(--text-bright);font-weight:600">#${r.DBId}</td>
      <td>${r.Product || '*'}</td>
      <td>${r.SecurityType || '*'}</td>
      <td>${r.Application || '*'}</td>
      <td>${r.Flow || '*'}</td>
      <td>${r.Trader || '*'}</td>
      <td>${r.Desk || '*'}</td>
      <td>${r.Account || '*'}</td>
      <td>${r.Client || '*'}</td>
      <td style="color:var(--text-bright);font-weight:500">${r.symbol || '*'}</td>
      <td>${r.exchange || '*'}</td>
      <td>${r.underlying || '*'}</td>
      <td>${r.AlgoStrategy || '*'}</td>
      <td>${r.Currency || '*'}</td>
      <td>${r.Side || '*'}</td>
      <td>${r.OrderType || '*'}</td>
      <td>${r.Tif || '*'}</td>
      <td>${r.ExtendedKey1 || '*'}</td>
      <td>${r.ExtendedKey2 || '*'}</td>
      <td>${r.ExtendedKey3 || '*'}</td>
      <td>${r.ExtendedKey4 || '*'}</td>
      <td>${r.ExtendedKey5 || '*'}</td>

      <td>${Number(r.MaxOrderSize || 0).toLocaleString()}</td>
      <td>$${Number(r.MaxOrderPrice || 0).toFixed(2)}</td>
      <td>$${Number(r.MaxOrderValue || 0).toLocaleString()}</td>
      <td>${r.MaxOrderADV || 0}%</td>
      <td>${r.ClosePriceTolerance || 0}%</td>
      <td>${r.LastPriceTolerance || 0}%</td>
      <td>${r.BBOPriceTolerance !== undefined ? r.BBOPriceTolerance : (r.BBOTolerance || 0)}%</td>
      <td>${r.MarketDepthCheck || 0}</td>

      <td>${Number(r.MaxDailyVolume || 0).toLocaleString()}</td>
      <td>$${Number(r.MaxDailyValue || 0).toLocaleString()}</td>
      <td>$${Number(r.MaxDailyNetValue || 0).toLocaleString()}</td>
      <td>$${Number(r.MaxDailyTurnover || 0).toLocaleString()}</td>
      <td>$${Number(r.MaxDailyExposure || 0).toLocaleString()}</td>
      <td>$${Number(r.MaxDailyOpenValue || 0).toLocaleString()}</td>
      <td>${r.MaxDailyActiveOrders || 0}</td>

      <td>${r.DuplicateOrders || '0'}</td>
      <td>${r.BurstOrders || '0'}</td>
      <td>${r.ExtendedValue1 || 0}</td>
      <td>${r.ExtendedValue2 || 0}</td>
      <td>${r.ExtendedValue3 || 0}</td>
      <td>${r.ExtendedValue4 || 0}</td>
      <td>${r.ExtendedValue5 || 0}</td>
      <td>${r.Flags || 0}</td>
      <td>${r.Restricted || 'N'}</td>
      <td>${r.SSRestricted || 'N'}</td>
      <td>${enabledBadge}</td>
      <td class="sticky-col-right" style="white-space:nowrap">
        <button class="btn btn-ghost btn-sm btn-icon-primary" onclick="openEditLimitModal(${r.DBId})" title="Edit Limit Rule">✏️ Edit</button>
        <button class="btn btn-ghost btn-sm btn-icon-info" onclick="openCopyLimitModal(${r.DBId})" title="Copy / Duplicate Limit Rule">📋 Copy</button>
        <button class="btn btn-ghost btn-sm btn-icon-danger" onclick="deleteLimitRule(${r.DBId})" title="Delete Limit Rule">🗑️</button>
      </td>
    </tr>`;
  }).join('');

  renderPaginationBar('limits-pagination', total, limitsPage, PAGE_SIZE, newPage => {
    limitsPage = newPage;
    renderLimitsTable(data);
  }, 'Total Rules');
}

// Wire up search, dropdown filters, & column filters
document.getElementById('limits-search').addEventListener('input', () => { limitsPage = 1; filterAndRenderLimits(); });
document.getElementById('limits-product-filter').addEventListener('change', () => { limitsPage = 1; filterAndRenderLimits(); });
document.getElementById('limits-sectype-filter').addEventListener('change', () => { limitsPage = 1; filterAndRenderLimits(); });
document.getElementById('limits-enabled-filter').addEventListener('change', () => { limitsPage = 1; filterAndRenderLimits(); });

document.querySelectorAll('.col-filter').forEach(input => {
  input.addEventListener('input', debounce(e => {
    const col = e.target.getAttribute('data-col');
    columnFilters[col] = e.target.value;
    limitsPage = 1;
    filterAndRenderLimits();
  }, 200));
});

// Modal Handlers
function openAddLimitModal() {
  document.getElementById('limits-modal-title').textContent = '➕ Add New RMS Limit Rule';
  document.getElementById('field-dbid').value = '';
  document.getElementById('limit-form').reset();
  populateLimitOptions();
  document.getElementById('limits-modal').style.display = 'flex';
}

function openEditLimitModal(dbId) {
  const rule = limitsAllData.find(r => r.DBId === dbId);
  if (!rule) return;

  document.getElementById('limits-modal-title').textContent = `✏️ Edit RMS Limit Rule #${dbId}`;
  document.getElementById('field-dbid').value = dbId;
  populateLimitOptions();

  const textFields = ['product', 'securitytype', 'application', 'flow', 'trader', 'desk', 'account', 'client', 'symbol', 'exchange', 'underlying', 'algostrategy', 'currency', 'side', 'ordertype', 'tif', 'extendedkey1', 'extendedkey2', 'extendedkey3', 'extendedkey4', 'extendedkey5', 'duplicateorders', 'burstorders', 'restricted', 'ssrestricted', 'enabled'];
  const numFields = ['maxordersize', 'maxorderprice', 'maxordervalue', 'maxorderadv', 'closepricetolerance', 'lastpricetolerance', 'bbopricetolerance', 'marketdepthcheck', 'maxdailyvolume', 'maxdailyvalue', 'maxdailynetvalue', 'maxdailyturnover', 'maxdailyexposure', 'maxdailyopenvalue', 'maxdailyactiveorders'];

  textFields.forEach(f => {
    const el = document.getElementById(`field-${f}`);
    if (el) {
      const dbKey = Object.keys(rule).find(k => k.toLowerCase() === f.toLowerCase()) || f;
      el.value = rule[dbKey] !== undefined ? rule[dbKey] : '*';
    }
  });

  numFields.forEach(f => {
    const el = document.getElementById(`field-${f}`);
    if (el) {
      const dbKey = Object.keys(rule).find(k => k.toLowerCase() === f.toLowerCase()) || f;
      el.value = rule[dbKey] !== undefined ? rule[dbKey] : 0;
    }
  });

  document.getElementById('limits-modal').style.display = 'flex';
}

function openCopyLimitModal(dbId) {
  const rule = limitsAllData.find(r => r.DBId === dbId);
  if (!rule) return;

  document.getElementById('limits-modal-title').textContent = `📋 Copy RMS Limit Rule (from #${dbId})`;
  document.getElementById('field-dbid').value = ''; // Cleared DBId creates a new duplicate rule on save
  populateLimitOptions();

  const textFields = ['product', 'securitytype', 'application', 'flow', 'trader', 'desk', 'account', 'client', 'symbol', 'exchange', 'underlying', 'algostrategy', 'currency', 'side', 'ordertype', 'tif', 'extendedkey1', 'extendedkey2', 'extendedkey3', 'extendedkey4', 'extendedkey5', 'duplicateorders', 'burstorders', 'restricted', 'ssrestricted', 'enabled'];
  const numFields = ['maxordersize', 'maxorderprice', 'maxordervalue', 'maxorderadv', 'closepricetolerance', 'lastpricetolerance', 'bbopricetolerance', 'marketdepthcheck', 'maxdailyvolume', 'maxdailyvalue', 'maxdailynetvalue', 'maxdailyturnover', 'maxdailyexposure', 'maxdailyopenvalue', 'maxdailyactiveorders'];

  textFields.forEach(f => {
    const el = document.getElementById(`field-${f}`);
    if (el) {
      const dbKey = Object.keys(rule).find(k => k.toLowerCase() === f.toLowerCase()) || f;
      el.value = rule[dbKey] !== undefined ? rule[dbKey] : '*';
    }
  });

  numFields.forEach(f => {
    const el = document.getElementById(`field-${f}`);
    if (el) {
      const dbKey = Object.keys(rule).find(k => k.toLowerCase() === f.toLowerCase()) || f;
      el.value = rule[dbKey] !== undefined ? rule[dbKey] : 0;
    }
  });

  document.getElementById('limits-modal').style.display = 'flex';
}

function closeLimitModal() {
  document.getElementById('limits-modal').style.display = 'none';
}

async function saveLimitRule() {
  const dbId = document.getElementById('field-dbid').value;
  const isEdit = Boolean(dbId);

  const payload = {
    Product: document.getElementById('field-product').value || '*',
    SecurityType: document.getElementById('field-securitytype').value || '*',
    Application: document.getElementById('field-application').value || '*',
    Flow: document.getElementById('field-flow').value || '*',
    Trader: document.getElementById('field-trader').value || '*',
    Desk: document.getElementById('field-desk').value || '*',
    Account: document.getElementById('field-account').value || '*',
    Client: document.getElementById('field-client').value || '*',
    symbol: document.getElementById('field-symbol').value || '*',
    exchange: document.getElementById('field-exchange').value || '*',
    underlying: document.getElementById('field-underlying').value || '*',
    AlgoStrategy: document.getElementById('field-algostrategy').value || '*',
    Currency: document.getElementById('field-currency').value || '*',
    Side: document.getElementById('field-side').value || '*',
    OrderType: document.getElementById('field-ordertype').value || '*',
    Tif: document.getElementById('field-tif').value || '*',
    ExtendedKey1: document.getElementById('field-extendedkey1').value || '*',
    ExtendedKey2: document.getElementById('field-extendedkey2').value || '*',
    ExtendedKey3: document.getElementById('field-extendedkey3').value || '*',
    ExtendedKey4: document.getElementById('field-extendedkey4').value || '*',
    ExtendedKey5: document.getElementById('field-extendedkey5').value || '*',

    MaxOrderSize: Number(document.getElementById('field-maxordersize').value || 0),
    MaxOrderPrice: Number(document.getElementById('field-maxorderprice').value || 0),
    MaxOrderValue: Number(document.getElementById('field-maxordervalue').value || 0),
    MaxOrderADV: Number(document.getElementById('field-maxorderadv').value || 0),
    ClosePriceTolerance: Number(document.getElementById('field-closepricetolerance').value || 0),
    LastPriceTolerance: Number(document.getElementById('field-lastpricetolerance').value || 0),
    BBOPriceTolerance: Number(document.getElementById('field-bbopricetolerance').value || 0),
    MarketDepthCheck: Number(document.getElementById('field-marketdepthcheck').value || 0),

    MaxDailyVolume: Number(document.getElementById('field-maxdailyvolume').value || 0),
    MaxDailyValue: Number(document.getElementById('field-maxdailyvalue').value || 0),
    MaxDailyNetValue: Number(document.getElementById('field-maxdailynetvalue').value || 0),
    MaxDailyTurnover: Number(document.getElementById('field-maxdailyturnover').value || 0),
    MaxDailyExposure: Number(document.getElementById('field-maxdailyexposure').value || 0),
    MaxDailyOpenValue: Number(document.getElementById('field-maxdailyopenvalue').value || 0),
    MaxDailyActiveOrders: Number(document.getElementById('field-maxdailyactiveorders').value || 0),

    DuplicateOrders: document.getElementById('field-duplicateorders').value || '0',
    BurstOrders: document.getElementById('field-burstorders').value || '0',
    Restricted: document.getElementById('field-restricted').value || 'N',
    SSRestricted: document.getElementById('field-ssrestricted').value || 'N',
    Enabled: document.getElementById('field-enabled').value || 'Y',
  };

  try {
    const url = isEdit ? `/api/limits/${dbId}` : '/api/limits';
    const method = isEdit ? 'PUT' : 'POST';
    const r = await fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const res = await r.json();
    if (res.ok) {
      closeLimitModal();
      loadLimits();
      const opTitle = isEdit ? `RMS Limit Rule #${dbId} Updated` : `RMS Limit Rule Added (DBId: #${res.db_id || 'New'})`;
      const opDetails = [
        `Operation: ${isEdit ? 'UPDATE' : 'CREATE'} RMS Limit Rule`,
        `DBId: ${isEdit ? dbId : (res.db_id || 'New')}`,
        `Product: ${payload.Product}`,
        `SecurityType: ${payload.SecurityType}`,
        `Trader: ${payload.Trader}`,
        `Desk: ${payload.Desk}`,
        `Account: ${payload.Account}`,
        `Client: ${payload.Client}`,
        `Symbol: ${payload.symbol}`,
        `Exchange: ${payload.exchange}`,
        `MaxOrderSize: ${payload.MaxOrderSize}`,
        `MaxOrderPrice: $${payload.MaxOrderPrice}`,
        `MaxOrderValue: $${payload.MaxOrderValue}`,
        `Enabled: ${payload.Enabled}`
      ].join('\n');
      showAlert(opDetails, opTitle, 'success');
    } else {
      showAlert(`Error saving rule: ${res.message}`, 'Save Error', 'error');
    }
  } catch (e) {
    showAlert(`Failed to save rule: ${e}`, 'Save Failed', 'error');
  }
}

async function deleteLimitRule(dbId) {
  const confirmed = await showConfirm(`Are you sure you want to delete RMS limit rule #${dbId}?`, 'Delete RMS Limit Rule', { danger: true });
  if (!confirmed) return;
  try {
    const r = await fetch(`/api/limits/${dbId}`, { method: 'DELETE' });
    const res = await r.json();
    if (res.ok) {
      loadLimits();
      showAlert(`Operation: DELETE RMS Limit Rule\n\nRule #${dbId} has been successfully deleted from GCE RMS database.`, 'RMS Limit Rule Deleted', 'success');
    } else {
      showAlert(`Error deleting rule: ${res.message}`, 'Delete Error', 'error');
    }
  } catch (e) {
    showAlert(`Failed to delete rule: ${e}`, 'Delete Failed', 'error');
  }
}

function exportLimitsCSV() {
  window.location.href = '/api/limits/export';
}

function openImportModal() {
  document.getElementById('upload-modal').style.display = 'flex';
}

function closeImportModal() {
  document.getElementById('upload-modal').style.display = 'none';
}

async function importLimitsCSV() {
  const fileInput = document.getElementById('import-file-input');
  if (!fileInput.files || fileInput.files.length === 0) {
    showAlert('Please select a CSV file to upload', 'File Required', 'warning');
    return;
  }

  const formData = new FormData();
  formData.append('file', fileInput.files[0]);
  formData.append('mode', document.getElementById('import-mode-select').value);

  try {
    const r = await fetch('/api/limits/import', {
      method: 'POST',
      body: formData
    });
    const res = await r.json();
    if (res.ok) {
      showAlert(res.message, 'Import Successful', 'success');
      closeImportModal();
      loadLimits();
    } else {
      showAlert(`Import failed: ${res.message}`, 'Import Failed', 'error');
    }
  } catch (e) {
    showAlert(`Failed to upload CSV: ${e}`, 'Upload Failed', 'error');
  }
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
      <td><button class="btn btn-ghost btn-sm" style="padding:2px 8px;font-size:11px" onclick="openOrderLogModal('${o.order_id}')">📜 Log</button></td>
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
  filterAndRenderPrices();
}

function filterAndRenderPrices() {
  const search = (document.getElementById('prices-search').value || '').toLowerCase();
  let filtered = pricesAllData;
  if (search) {
    filtered = filtered.filter(p => (p.ric || '').toLowerCase().includes(search));
  }
  renderPricesTable(filtered);
}

function renderPricesTable(data = pricesAllData) {
  const tbody = document.getElementById('prices-tbody');
  const empty = document.getElementById('prices-empty');
  const total = data.length;

  if (total === 0) {
    tbody.innerHTML = '';
    empty.style.display = 'block';
    renderPaginationBar('prices-pagination', 0, 1, PAGE_SIZE, () => {}, 'Total Records');
    return;
  }
  empty.style.display = 'none';

  const startIdx = (pricesPage - 1) * PAGE_SIZE;
  const pageSlice = data.slice(startIdx, startIdx + PAGE_SIZE);

  tbody.innerHTML = pageSlice.map(p => `<tr>
    <td style="color:var(--text-bright);font-weight:500">${p.ric}</td>
    <td>${(p.open || 0).toFixed(2)}</td>
    <td>${(p.bid || 0).toFixed(2)}</td>
    <td>${(p.ask || 0).toFixed(2)}</td>
    <td>${(p.last || 0).toFixed(2)}</td>
    <td>${(p.close || 0).toFixed(2)}</td>
    <td>${(p.mid || 0).toFixed(2)}</td>
    <td>
      <button class="btn btn-ghost btn-sm btn-icon-primary" onclick="openEditPriceModal('${p.ric}')">✏️ Edit</button>
      <button class="btn btn-ghost btn-sm btn-icon-danger" onclick="deletePrice('${p.ric}')">🗑️</button>
    </td>
  </tr>`).join('');

  renderPaginationBar('prices-pagination', total, pricesPage, PAGE_SIZE, newPage => {
    pricesPage = newPage;
    renderPricesTable(data);
  }, 'Total Records');
}

// Search input listener
document.getElementById('prices-search').addEventListener('input', () => { pricesPage = 1; filterAndRenderPrices(); });

// Auto-populate price fields if entered RIC exists in prices cache
function checkAndPopulatePriceByRIC(ricInput) {
  const cleanRic = (ricInput || '').trim();
  if (!cleanRic) return;

  const item = pricesAllData.find(p => p.ric.toLowerCase() === cleanRic.toLowerCase());
  if (item) {
    document.getElementById('price-field-open').value = item.open || 0;
    document.getElementById('price-field-bid').value = item.bid || 0;
    document.getElementById('price-field-ask').value = item.ask || 0;
    document.getElementById('price-field-last').value = item.last || 0;
    document.getElementById('price-field-close').value = item.close || 0;
  }
}

const priceRicInputEl = document.getElementById('price-field-ric');
priceRicInputEl.addEventListener('input', (e) => checkAndPopulatePriceByRIC(e.target.value));
priceRicInputEl.addEventListener('change', (e) => checkAndPopulatePriceByRIC(e.target.value));

// Price Modal Handlers
function openAddPriceModal() {
  document.getElementById('price-modal-title').textContent = '➕ Add / Edit Market Price';
  document.getElementById('price-field-ric').value = '';
  document.getElementById('price-field-ric').disabled = false;
  document.getElementById('price-field-open').value = '0.0';
  document.getElementById('price-field-bid').value = '0.0';
  document.getElementById('price-field-ask').value = '0.0';
  document.getElementById('price-field-last').value = '0.0';
  document.getElementById('price-field-close').value = '0.0';

  // Populate datalist with known RICs for autocomplete
  const datalist = document.getElementById('price-ric-list');
  if (datalist) {
    const knownRics = new Set([
      ...pricesAllData.map(p => p.ric),
      ...(instrAllData || []).map(i => i.ric)
    ]);
    datalist.innerHTML = Array.from(knownRics).slice(0, 500).map(ric => `<option value="${ric}">`).join('');
  }

  document.getElementById('price-modal').style.display = 'flex';
}

function openEditPriceModal(ric) {
  const item = pricesAllData.find(p => p.ric === ric);
  if (!item) return;

  document.getElementById('price-modal-title').textContent = `✏️ Edit Market Price (${ric})`;
  document.getElementById('price-field-ric').value = item.ric;
  document.getElementById('price-field-ric').disabled = true;
  document.getElementById('price-field-open').value = item.open || 0;
  document.getElementById('price-field-bid').value = item.bid || 0;
  document.getElementById('price-field-ask').value = item.ask || 0;
  document.getElementById('price-field-last').value = item.last || 0;
  document.getElementById('price-field-close').value = item.close || 0;
  document.getElementById('price-modal').style.display = 'flex';
}

function closePriceModal() {
  document.getElementById('price-modal').style.display = 'none';
}

async function savePrice() {
  const ric = (document.getElementById('price-field-ric').value || '').trim();
  if (!ric) {
    showAlert('Please enter a RIC symbol', 'Input Required', 'warning');
    return;
  }

  const payload = {
    ric,
    open: Number(document.getElementById('price-field-open').value || 0),
    bid: Number(document.getElementById('price-field-bid').value || 0),
    ask: Number(document.getElementById('price-field-ask').value || 0),
    last: Number(document.getElementById('price-field-last').value || 0),
    close: Number(document.getElementById('price-field-close').value || 0),
  };

  try {
    const r = await fetch('/api/prices', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const res = await r.json();
    if (res.ok) {
      closePriceModal();
      loadPrices();
      const opDetails = [
        `Operation: SAVE Market Price`,
        `RIC Symbol: ${payload.ric}`,
        `Bid: ${payload.bid}`,
        `Ask: ${payload.ask}`,
        `Last: ${payload.last}`,
        `Close: ${payload.close}`,
        `Open: ${payload.open}`
      ].join('\n');
      showAlert(opDetails, `Market Price Saved (${payload.ric})`, 'success');
    } else {
      showAlert(`Error saving price: ${res.message}`, 'Save Error', 'error');
    }
  } catch (e) {
    showAlert(`Failed to save price: ${e}`, 'Save Failed', 'error');
  }
}

async function deletePrice(ric) {
  const confirmed = await showConfirm(`Are you sure you want to delete price data for ${ric}?`, 'Delete Price Data', { danger: true });
  if (!confirmed) return;
  try {
    const r = await fetch(`/api/prices/${encodeURIComponent(ric)}`, { method: 'DELETE' });
    const res = await r.json();
    if (res.ok) {
      loadPrices();
      showAlert(`Operation: DELETE Market Price\n\nMarket price records for RIC ${ric} have been successfully deleted.`, 'Market Price Deleted', 'success');
    } else {
      showAlert(`Error deleting price: ${res.message}`, 'Delete Error', 'error');
    }
  } catch (e) {
    showAlert(`Failed to delete price: ${e}`, 'Delete Failed', 'error');
  }
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

async function loadInstruments(forceReload = false) {
  const search = document.getElementById('instr-search').value || '';
  const reloadParam = forceReload ? '&reload=true' : '';
  const data = await api(`/api/instruments?search=${encodeURIComponent(search)}&limit=0${reloadParam}`);
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
    <td><span class="badge badge-pass">${i.exchange || 'XHKG'}</span></td>
    <td>${i.name}</td>
    <td>${i.category}</td>
    <td>${i.security_type || i.sub_category || '—'}</td>
    <td>${(i.board_lot || 0).toLocaleString()}</td>
    <td>${i.currency}</td>
    <td>${i.shortsell ? '✅' : '—'}</td>
    <td>${i.cas ? '✅' : '—'}</td>
    <td>${i.vcm ? '✅' : '—'}</td>
    <td>
      <button class="btn btn-ghost btn-sm btn-icon-primary" onclick="openEditInstrModal('${i.ric}')">✏️ Edit</button>
      <button class="btn btn-ghost btn-sm btn-icon-danger" onclick="deleteInstrument('${i.ric}')">🗑️</button>
    </td>
  </tr>`).join('');

  renderPaginationBar('instr-pagination', total, instrPage, PAGE_SIZE, newPage => {
    instrPage = newPage;
    renderInstrTable();
  }, 'Total Instruments');
}

// Auto-populate instrument form fields if typed RIC exists in cache
function checkAndPopulateInstrByRIC(ricInput) {
  const cleanRic = (ricInput || '').trim();
  if (!cleanRic) return;

  const item = instrAllData.find(i => i.ric.toLowerCase() === cleanRic.toLowerCase());
  if (item) {
    document.getElementById('instr-field-code').value = item.stock_code || '';
    document.getElementById('instr-field-exchange').value = item.exchange || 'XHKG';
    document.getElementById('instr-field-name').value = item.name || '';
    document.getElementById('instr-field-category').value = item.category || '';
    document.getElementById('instr-field-sectype').value = item.security_type || item.sub_category || '';
    document.getElementById('instr-field-lot').value = item.board_lot || 100;
    document.getElementById('instr-field-currency').value = item.currency || 'HKD';
    document.getElementById('instr-field-isin').value = item.isin || '';
    document.getElementById('instr-field-shortsell').checked = !!item.shortsell;
    document.getElementById('instr-field-cas').checked = !!item.cas;
    document.getElementById('instr-field-vcm').checked = !!item.vcm;
  }
}

const instrRicEl = document.getElementById('instr-field-ric');
if (instrRicEl) {
  instrRicEl.addEventListener('input', (e) => checkAndPopulateInstrByRIC(e.target.value));
  instrRicEl.addEventListener('change', (e) => checkAndPopulateInstrByRIC(e.target.value));
}

// Instrument Modal Handlers
function openAddInstrModal() {
  document.getElementById('instr-modal-title').textContent = '➕ Add / Edit Instrument';
  document.getElementById('instr-field-ric').value = '';
  document.getElementById('instr-field-ric').disabled = false;
  document.getElementById('instr-field-code').value = '';
  document.getElementById('instr-field-exchange').value = 'XHKG';
  document.getElementById('instr-field-name').value = '';
  document.getElementById('instr-field-category').value = 'Equity';
  document.getElementById('instr-field-sectype').value = 'Equity Securities (Main Board)';
  document.getElementById('instr-field-lot').value = '100';
  document.getElementById('instr-field-currency').value = 'HKD';
  document.getElementById('instr-field-isin').value = '';
  document.getElementById('instr-field-shortsell').checked = false;
  document.getElementById('instr-field-cas').checked = false;
  document.getElementById('instr-field-vcm').checked = false;
  document.getElementById('instr-modal').style.display = 'flex';
}

function openEditInstrModal(ric) {
  const item = instrAllData.find(i => i.ric === ric);
  if (!item) return;

  document.getElementById('instr-modal-title').textContent = `✏️ Edit Instrument (${ric})`;
  document.getElementById('instr-field-ric').value = item.ric;
  document.getElementById('instr-field-ric').disabled = true;
  document.getElementById('instr-field-code').value = item.stock_code || '';
  document.getElementById('instr-field-exchange').value = item.exchange || 'XHKG';
  document.getElementById('instr-field-name').value = item.name || '';
  document.getElementById('instr-field-category').value = item.category || '';
  document.getElementById('instr-field-sectype').value = item.security_type || item.sub_category || '';
  document.getElementById('instr-field-lot').value = item.board_lot || 100;
  document.getElementById('instr-field-currency').value = item.currency || 'HKD';
  document.getElementById('instr-field-isin').value = item.isin || '';
  document.getElementById('instr-field-shortsell').checked = !!item.shortsell;
  document.getElementById('instr-field-cas').checked = !!item.cas;
  document.getElementById('instr-field-vcm').checked = !!item.vcm;
  document.getElementById('instr-modal').style.display = 'flex';
}

function closeInstrModal() {
  document.getElementById('instr-modal').style.display = 'none';
}

async function saveInstrument() {
  const ric = (document.getElementById('instr-field-ric').value || '').trim();
  if (!ric) {
    showAlert('Please enter a RIC masterkey', 'Input Required', 'warning');
    return;
  }

  const payload = {
    ric,
    stock_code: (document.getElementById('instr-field-code').value || '').trim(),
    exchange: (document.getElementById('instr-field-exchange').value || 'XHKG').trim(),
    name: (document.getElementById('instr-field-name').value || '').trim(),
    category: (document.getElementById('instr-field-category').value || '').trim(),
    security_type: (document.getElementById('instr-field-sectype').value || '').trim(),
    board_lot: Number(document.getElementById('instr-field-lot').value || 100),
    currency: (document.getElementById('instr-field-currency').value || 'HKD').trim(),
    isin: (document.getElementById('instr-field-isin').value || '').trim(),
    shortsell: document.getElementById('instr-field-shortsell').checked,
    cas: document.getElementById('instr-field-cas').checked,
    vcm: document.getElementById('instr-field-vcm').checked,
  };

  try {
    const r = await fetch('/api/instruments', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const res = await r.json();
    if (res.ok) {
      closeInstrModal();
      loadInstruments();
      const opDetails = [
        `Operation: SAVE Instrument`,
        `RIC Masterkey: ${payload.ric}`,
        `Stock Code: ${payload.stock_code}`,
        `Name: ${payload.name}`,
        `Exchange: ${payload.exchange}`,
        `Currency: ${payload.currency}`,
        `Category/Product: ${payload.category}`,
        `SecurityType: ${payload.security_type}`,
        `Board Lot: ${payload.board_lot}`
      ].join('\n');
      showAlert(opDetails, `Instrument Saved (${payload.ric})`, 'success');
    } else {
      showAlert(`Error saving instrument: ${res.message}`, 'Save Error', 'error');
    }
  } catch (e) {
    showAlert(`Failed to save instrument: ${e}`, 'Save Failed', 'error');
  }
}

async function deleteInstrument(ric) {
  const confirmed = await showConfirm(`Are you sure you want to delete instrument ${ric}?`, 'Delete Instrument', { danger: true });
  if (!confirmed) return;
  try {
    const r = await fetch(`/api/instruments/${encodeURIComponent(ric)}`, { method: 'DELETE' });
    const res = await r.json();
    if (res.ok) {
      loadInstruments();
      showAlert(`Operation: DELETE Instrument\n\nInstrument masterkey ${ric} has been successfully deleted.`, 'Instrument Deleted', 'success');
    } else {
      showAlert(`Error deleting instrument: ${res.message}`, 'Delete Error', 'error');
    }
  } catch (e) {
    showAlert(`Failed to delete instrument: ${e}`, 'Delete Failed', 'error');
  }
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
// Section: Place Order (Order Placement Ticket)
// ============================================================
let recentPlacedOrdersData = [];

function handleOrderTypeChange() {
  const orderType = document.getElementById('order-field-type') ? document.getElementById('order-field-type').value : 'LMT';
  const priceGroup = document.getElementById('order-group-price');
  const priceInput = document.getElementById('order-field-price');

  if (!priceInput) return;

  if (orderType === 'MKT') {
    priceInput.value = '0';
    priceInput.required = false;
    if (priceGroup) priceGroup.style.display = 'none';
  } else {
    if (priceInput.value === '0' || priceInput.value === '0.0' || !priceInput.value) {
      priceInput.value = '100.0';
    }
    priceInput.required = true;
    if (priceGroup) priceGroup.style.display = 'block';
  }
}

function autoFillOrderFieldsByRIC(inputRic) {
  const cleanRic = (inputRic || '').trim();
  if (!cleanRic) return;

  const inst = (instrAllData || []).find(i => i.ric.toLowerCase() === cleanRic.toLowerCase());
  if (inst) {
    document.getElementById('order-field-product').value = inst.category || 'Equity';
    document.getElementById('order-field-sectype').value = inst.security_type || inst.sub_category || 'Equity Securities';
    document.getElementById('order-field-exchange').value = inst.exchange || 'XHKG';
    document.getElementById('order-field-currency').value = inst.currency || 'HKD';
  }

  const orderType = document.getElementById('order-field-type') ? document.getElementById('order-field-type').value : 'LMT';
  if (orderType !== 'MKT') {
    const px = (pricesAllData || []).find(p => p.ric.toLowerCase() === cleanRic.toLowerCase());
    if (px && px.last) {
      document.getElementById('order-field-price').value = px.last;
    }
  }
}

const orderRicInputEl = document.getElementById('order-field-ric');
if (orderRicInputEl) {
  orderRicInputEl.addEventListener('input', (e) => autoFillOrderFieldsByRIC(e.target.value));
  orderRicInputEl.addEventListener('change', (e) => autoFillOrderFieldsByRIC(e.target.value));
}

const orderTypeSelectEl = document.getElementById('order-field-type');
if (orderTypeSelectEl) {
  orderTypeSelectEl.addEventListener('change', handleOrderTypeChange);
}

function resetOrderPlacementForm() {
  document.getElementById('order-placement-form').reset();
  handleOrderTypeChange();
  document.getElementById('order-field-qty').value = '100';
  document.getElementById('order-field-product').value = 'Equity';
  document.getElementById('order-field-exchange').value = 'XHKG';
  document.getElementById('order-field-currency').value = 'HKD';
  document.getElementById('order-field-trader').value = 'TRADER1';
  document.getElementById('order-field-account').value = 'ACC01';
  document.getElementById('order-field-client').value = 'CLIENT_A';
  document.getElementById('order-field-desk').value = 'HONGKONG_DESK';
  document.getElementById('order-field-tif').value = 'DAY';
  document.getElementById('order-field-app').value = 'AUTO_TRADER';
  document.getElementById('order-field-flow').value = 'DMA';
  document.getElementById('order-field-algo').value = 'VWAP';
  const alertEl = document.getElementById('order-validation-alert');
  if (alertEl) alertEl.style.display = 'none';
}

async function submitOrderPlacement() {
  const alertEl = document.getElementById('order-validation-alert');
  alertEl.style.display = 'none';

  const ric = (document.getElementById('order-field-ric').value || '').trim();
  const quantity = Number(document.getElementById('order-field-qty').value || 0);
  const orderType = document.getElementById('order-field-type').value;
  const price = orderType === 'MKT' ? 0.0 : Number(document.getElementById('order-field-price').value || 0);

  if (!ric) {
    showAlert('Please enter a RIC symbol', 'Input Required', 'warning');
    return;
  }
  if (quantity <= 0) {
    showAlert('Quantity must be greater than 0', 'Invalid Quantity', 'warning');
    return;
  }
  if (orderType === 'LMT' && price <= 0) {
    showAlert('Price must be greater than 0 for Limit orders', 'Invalid Price', 'warning');
    return;
  }

  const payload = {
    ric,
    order_id: (document.getElementById('order-field-id').value || '').trim(),
    side: document.getElementById('order-field-side').value,
    order_type: document.getElementById('order-field-type').value,
    quantity,
    price,
    product: (document.getElementById('order-field-product').value || 'Equity').trim(),
    security_type: (document.getElementById('order-field-sectype').value || '').trim(),
    exchange: (document.getElementById('order-field-exchange').value || 'XHKG').trim(),
    currency: (document.getElementById('order-field-currency').value || 'HKD').trim(),
    trader: (document.getElementById('order-field-trader').value || 'TRADER1').trim(),
    account: (document.getElementById('order-field-account').value || 'ACC01').trim(),
    client: (document.getElementById('order-field-client').value || 'CLIENT_A').trim(),
    desk: (document.getElementById('order-field-desk').value || 'HONGKONG_DESK').trim(),
    tif: document.getElementById('order-field-tif').value,
    application: (document.getElementById('order-field-app').value || 'AUTO_TRADER').trim(),
    flow: (document.getElementById('order-field-flow').value || 'DMA').trim(),
    algo_strategy: (document.getElementById('order-field-algo').value || 'VWAP').trim(),
  };

  try {
    const res = await apiPost('/api/orders/place', payload);
    if (!res) return;

    if (res.ok) {
      alertEl.style.display = 'block';
      if (res.status === 'APPROVED') {
        alertEl.style.background = 'rgba(34, 197, 94, 0.15)';
        alertEl.style.border = '1px solid var(--pass-color)';
        alertEl.style.color = '#4ade80';
        alertEl.innerHTML = `🟢 <strong>APPROVED</strong> — Order ${res.order.order_id} (${res.order.side} ${res.order.quantity} @ ${res.order.price}) passed all pre-trade GCE risk controls!`;
      } else {
        alertEl.style.background = 'rgba(239, 68, 68, 0.15)';
        alertEl.style.border = '1px solid var(--fail-color)';
        alertEl.style.color = '#f87171';
        const reasons = (res.rejections || []).join('<br>• ');
        alertEl.innerHTML = `🔴 <strong>REJECTED</strong> — Order ${res.order.order_id} failed GCE pre-trade risk controls:<br>• ${reasons || res.order.rejection_reason || 'Pre-trade risk limit check failed'}`;
      }

      if (res.order) {
        recentPlacedOrdersData.unshift(res.order);
        renderRecentPlacedOrders();
      }

      // Task 4: Show popup acknowledgement window for order entry
      const isApproved = res.status === 'APPROVED';
      const ordDetails = [
        `Operation: ORDER ENTRY (${res.status})`,
        `Order ID: ${res.order ? res.order.order_id : payload.order_id}`,
        `Status: ${res.status}`,
        `Side: ${payload.side}`,
        `Symbol: ${payload.ric}`,
        `Quantity: ${payload.quantity}`,
        `Price: ${payload.order_type === 'MKT' ? 'MKT' : payload.price}`,
        `Trader: ${payload.trader}`,
        `Account: ${payload.account}`,
        `Desk: ${payload.desk}`,
        `Client: ${payload.client}`,
        `Exchange: ${payload.exchange}`,
        isApproved ? `Result: Passed all pre-trade GCE risk controls` : `Rejection Reasons:\n• ${(res.rejections || []).join('\n• ')}`
      ].join('\n');
      showAlert(ordDetails, `Order Entry Acknowledgement: ${res.status}`, isApproved ? 'success' : 'error');
    } else {
      showAlert(`Error submitting order: ${res.message}`, 'Order Submission Error', 'error');
    }
  } catch (e) {
    showAlert(`Failed to submit order: ${e}`, 'Submission Failed', 'error');
  }
}

async function loadRecentPlacedOrders() {
  const data = await api('/api/orders');
  if (data) {
    recentPlacedOrdersData = data.slice(-20).reverse();
    renderRecentPlacedOrders();
  }
}

function renderRecentPlacedOrders() {
  const tbody = document.getElementById('recent-placed-orders-tbody');
  const empty = document.getElementById('recent-placed-orders-empty');
  if (!tbody) return;

  if (recentPlacedOrdersData.length === 0) {
    tbody.innerHTML = '';
    empty.style.display = 'block';
    return;
  }
  empty.style.display = 'none';

  tbody.innerHTML = recentPlacedOrdersData.map(o => {
    const isLive = o.status === 'Live' || o.status === 'APPROVED';
    const badgeClass = isLive ? 'badge-pass' : 'badge-fail';
    const timeStr = o.timestamp ? new Date(o.timestamp).toLocaleTimeString() : '—';
    const details = o.rejection_reason ? `<span style="color:#f87171">${o.rejection_reason}</span>` : 'Pre-trade risk validation passed';

    return `<tr>
      <td style="color:var(--text-bright);font-weight:500">${o.order_id}</td>
      <td>${o.ric || o.symbol}</td>
      <td><span class="badge ${o.side === 'B' ? 'badge-pass' : 'badge-fail'}">${o.side === 'B' ? 'BUY' : 'SELL'}</span></td>
      <td>${(o.quantity || 0).toLocaleString()}</td>
      <td>${(o.price || 0).toFixed(2)}</td>
      <td><span class="badge ${badgeClass}">${o.status}</span></td>
      <td>${o.trader}</td>
      <td>${o.account}</td>
      <td>${timeStr}</td>
      <td><small>${details}</small></td>
    </tr>`;
  }).join('');
}

// ============================================================
// Section: Log Viewer & Order Log Modal
// ============================================================
let logsFilterDebounceTimer = null;

async function loadLogsSection() {
  const search = (document.getElementById('logs-search') ? document.getElementById('logs-search').value : '').trim();
  const level = document.getElementById('logs-level-filter') ? document.getElementById('logs-level-filter').value : '';
  const limit = document.getElementById('logs-limit-select') ? document.getElementById('logs-limit-select').value : '200';

  const query = new URLSearchParams({ search, level, limit });
  const data = await api(`/api/logs?${query.toString()}`);
  const consoleEl = document.getElementById('log-console-content');
  const countLabel = document.getElementById('log-count-label');

  if (!data || !data.ok) {
    if (consoleEl) consoleEl.innerHTML = `<span style="color:#ef4444">Failed to load logs</span>`;
    if (countLabel) countLabel.textContent = '0 lines displayed';
    return;
  }

  const lines = data.lines || [];
  if (countLabel) countLabel.textContent = `${lines.length} lines displayed`;

  if (consoleEl) {
    if (lines.length === 0) {
      consoleEl.innerHTML = `<span style="color:#64748b">No matching log records found</span>`;
    } else {
      consoleEl.innerHTML = formatLogLinesHTML(lines);
      const autoScrollEl = document.getElementById('logs-autoscroll');
      if (autoScrollEl && autoScrollEl.checked) {
        consoleEl.scrollTop = consoleEl.scrollHeight;
      }
    }
  }
}

function formatLogLinesHTML(lines) {
  return lines.map(line => {
    let escaped = line.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    
    // Highlight log levels
    escaped = escaped.replace(/\[(INFO)\]/g, '<span style="color:#38bdf8;font-weight:600">[$1]</span>');
    escaped = escaped.replace(/\[(WARNING)\]/g, '<span style="color:#fbbf24;font-weight:600">[$1]</span>');
    escaped = escaped.replace(/\[(ERROR)\]/g, '<span style="color:#f87171;font-weight:600">[$1]</span>');
    escaped = escaped.replace(/\[(DEBUG)\]/g, '<span style="color:#a78bfa;font-weight:600">[$1]</span>');
    
    // Highlight PASS / FAIL statuses
    escaped = escaped.replace(/\[PASS\]/g, '<span style="color:#4ade80;font-weight:bold">[PASS]</span>');
    escaped = escaped.replace(/\[FAIL\]/g, '<span style="color:#f87171;font-weight:bold">[FAIL]</span>');
    
    // Highlight Order IDs
    escaped = escaped.replace(/\[(ORD-[^\]]+)\]/g, '[<span style="color:#f472b6;font-weight:600">$1</span>]');

    return escaped;
  }).join('\n');
}

function copyConsoleLogs() {
  const consoleEl = document.getElementById('log-console-content');
  if (!consoleEl) return;
  navigator.clipboard.writeText(consoleEl.textContent || '')
    .then(() => showAlert('Log content copied to clipboard!', 'Copied', 'success'))
    .catch(e => showAlert(`Copy failed: ${e}`, 'Copy Error', 'error'));
}

// Order-specific Floating Log Modal
async function openOrderLogModal(orderId) {
  if (!orderId) return;
  const modal = document.getElementById('order-log-modal');
  const titleEl = document.getElementById('order-log-modal-title');
  const ordIdEl = document.getElementById('order-log-modal-ordid');
  const countEl = document.getElementById('order-log-modal-count');
  const contentEl = document.getElementById('order-log-modal-content');

  if (titleEl) titleEl.textContent = `📜 Order Execution Logs — ${orderId}`;
  if (ordIdEl) ordIdEl.textContent = orderId;
  if (contentEl) contentEl.innerHTML = `<span style="color:#64748b">Loading order logs...</span>`;
  if (modal) modal.style.display = 'flex';

  const data = await api(`/api/logs?order_id=${encodeURIComponent(orderId)}&limit=0`);
  if (!data || !data.ok) {
    if (contentEl) contentEl.innerHTML = `<span style="color:#ef4444">Failed to retrieve logs for order ${orderId}</span>`;
    if (countEl) countEl.textContent = '0 matching log records';
    return;
  }

  const lines = data.lines || [];
  if (countEl) countEl.textContent = `${lines.length} matching log records`;
  if (contentEl) {
    if (lines.length === 0) {
      contentEl.innerHTML = `<span style="color:#64748b">No log records found for order ${orderId}</span>`;
    } else {
      contentEl.innerHTML = formatLogLinesHTML(lines);
      contentEl.scrollTop = contentEl.scrollHeight;
    }
  }
}

function closeOrderLogModal() {
  const modal = document.getElementById('order-log-modal');
  if (modal) modal.style.display = 'none';
}

function copyOrderLogs() {
  const contentEl = document.getElementById('order-log-modal-content');
  if (!contentEl) return;
  navigator.clipboard.writeText(contentEl.textContent || '')
    .then(() => showAlert('Order log records copied to clipboard!', 'Copied', 'success'))
    .catch(e => showAlert(`Copy failed: ${e}`, 'Copy Error', 'error'));
}

document.addEventListener('DOMContentLoaded', () => {
  const logSearchInput = document.getElementById('logs-search');
  const logLevelSelect = document.getElementById('logs-level-filter');
  const logLimitSelect = document.getElementById('logs-limit-select');

  if (logSearchInput) {
    logSearchInput.addEventListener('input', () => {
      clearTimeout(logsFilterDebounceTimer);
      logsFilterDebounceTimer = setTimeout(loadLogsSection, 300);
    });
  }
  if (logLevelSelect) {
    logLevelSelect.addEventListener('change', loadLogsSection);
  }
  if (logLimitSelect) {
    logLimitSelect.addEventListener('change', loadLogsSection);
  }

  // Ensure services load immediately when DOM is ready
  loadServices();
});

// ============================================================
// Refresh Logic
// ============================================================
function refreshCurrentSection() {
  const ts = new Date().toLocaleTimeString();
  document.getElementById('last-refresh').textContent = ts;
  switch (currentSection) {
    case 'services': loadServices(); break;
    case 'orders': loadRecentPlacedOrders(); break;
    case 'limits': loadLimits(); break;
    case 'oms': loadOrders(); break;
    case 'prices': loadPrices(); loadFX(); break;
    case 'instruments': loadInstruments(); break;
    case 'sessions': loadSessions(); break;
    case 'reconciliation': loadReconciliation(); break;
    case 'logs': loadLogsSection(); break;
    case 'rms': loadRMS(); break;
    case 'performance': loadPerformance(); break;
  }
}

// Auto-refresh for services and prices
setInterval(() => {
  if (currentSection === 'services') loadServices();
  if (currentSection === 'prices') { loadPrices(); loadFX(); }
  if (currentSection === 'logs') loadLogsSection();
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
window.addEventListener('load', loadServices);
