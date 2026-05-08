/**
 * Flow Kit — Side Panel
 * Displays live connection status, metrics, and request log.
 */

// ── Type label map ───────────────────────────────────────────

const TYPE_LABELS = {
  // Worker request types
  GENERATE_IMAGE:           'GEN IMAGE',
  REGENERATE_IMAGE:         'REGEN IMAGE',
  EDIT_IMAGE:               'EDIT IMAGE',
  GENERATE_CHARACTER_IMAGE: 'GEN REF',
  REGENERATE_CHARACTER_IMAGE: 'REGEN REF',
  EDIT_CHARACTER_IMAGE:     'EDIT REF',
  GENERATE_VIDEO:           'GEN VIDEO',
  GENERATE_VIDEO_REFS:      'GEN VIDEO FROM REFS',
  UPSCALE_VIDEO:            'UPSCALE VIDEO',
  // Captcha action types
  IMAGE_GENERATION:         'GEN IMAGE',
  VIDEO_GENERATION:         'GEN VIDEO',
  // Extension-classified API types
  GEN_IMG:                  'GEN IMAGE',
  GEN_VID:                  'GEN VIDEO',
  GEN_VID_REF:              'GEN VIDEO FROM REFS',
  UPSCALE:                  'UPSCALE VIDEO',
  UPS_IMG:                  'UPSCALE IMAGE',
  POLL:                     'CHECK GEN VIDEO',
  CREDITS:                  'CHECK CREDIT',
  CREATE_PROJECT:           'CREATE PROJECT',
  UPLOAD:                   'UPLOAD IMAGE',
  MEDIA:                    'READ MEDIA',
  TRACKING:                 'GOOGLE FLOW TRACK',
  URL_REFRESH:              'URL REFRESH',
  TRPC:                     'TRPC',
  API:                      'API',
};

const LOCAL_AGENT_BASE = 'http://127.0.0.1:8100';
const LOCAL_AGENT_DASHBOARD_URL = `${LOCAL_AGENT_BASE}/operator`;
const LOCAL_AGENT_REPAIR_URL = `${LOCAL_AGENT_BASE}/api/local-agent/repair`;
const LOCAL_AGENT_STATUS_URL = `${LOCAL_AGENT_BASE}/api/local-agent/status`;
const LOCAL_AGENT_CONTENT_PACK_URL = `${LOCAL_AGENT_BASE}/api/operator/content-pack`;
const LOCAL_AGENT_REPAIR_COMMAND = '.\\scripts\\install-local-agent.ps1';

let _localAgentStatus = null;
let _localAgentError = null;
let _operatorPack = null;
let _operatorPackError = null;
let _dashboardReachable = null;
let _dashboardError = null;

function formatType(type) {
  if (!type) return '—';
  return TYPE_LABELS[type] || type.slice(0, 5).toUpperCase();
}

// ── Time formatting ──────────────────────────────────────────

function formatTime(iso) {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    const hh = String(d.getHours()).padStart(2, '0');
    const mm = String(d.getMinutes()).padStart(2, '0');
    const ss = String(d.getSeconds()).padStart(2, '0');
    return `${hh}:${mm}:${ss}`;
  } catch {
    return '—';
  }
}

// ── Status update ────────────────────────────────────────────

function updateStatus(data) {
  if (!data) return;

  // Connection dot
  const dot = document.getElementById('conn-dot');
  const connected = data.agentConnected;
  dot.className = connected ? 'on' : '';

  // Toggle state
  const toggle = document.getElementById('main-toggle');
  const toggleLabel = document.getElementById('toggle-label');
  const isOn = data.state !== 'off';
  toggle.checked = isOn;
  toggleLabel.textContent = isOn ? 'ON' : 'OFF';

  // State badge
  const stateBadge = document.getElementById('state-badge');
  const st = data.state || 'off';
  stateBadge.textContent = st;
  stateBadge.className = st; // idle | running | off

  // Token status
  const tokenEl = document.getElementById('token-status');
  if (data.flowKeyPresent) {
    const ageMs = data.tokenAge || 0;
    const ageMin = Math.round(ageMs / 60000);
    if (ageMs > 3600000) {
      tokenEl.textContent = `token expired — open Flow to refresh`;
      tokenEl.className = 'warn';
    } else {
      tokenEl.textContent = `token synced ${ageMin}m`;
      tokenEl.className = 'ok';
    }
    // Auto-refresh when token age > 55 min and connected
    if (ageMs > 3300000 && data.agentConnected) {
      sendRuntimeMessageSafe({ type: 'REFRESH_TOKEN' });
    }
  } else {
    tokenEl.textContent = 'no token';
    tokenEl.className = 'bad';
  }

  // Metrics
  const m = data.metrics || {};
  document.getElementById('m-total').textContent   = m.requestCount || 0;
  document.getElementById('m-success').textContent = m.successCount || 0;
  document.getElementById('m-failed').textContent  = m.failedCount  || 0;
}

// ── Request log ──────────────────────────────────────────────

function updateRequestLog(entries) {
  const tbody = document.getElementById('log-body');
  const countEl = document.getElementById('log-count');

  if (!entries || entries.length === 0) {
    tbody.innerHTML = '<tr><td colspan="5" class="log-empty">No requests yet</td></tr>';
    countEl.textContent = '0';
    return;
  }

  countEl.textContent = entries.length;
  _logEntries = entries;

  // Render newest first (entries already sorted DESC by background.js)
  const rows = entries.map((entry) => {
    const shortId = entry.id ? String(entry.id).slice(0, 8) : '—';
    const type   = formatType(entry.type || entry.method);
    const time   = formatTime(entry.time || entry.timestamp || entry.createdAt);
    const status = entry.status || entry.state || 'pending';
    const error  = entry.error || '';

    let badgeHtml;
    if (status === 'COMPLETED' || status === 'success') {
      badgeHtml = '<span class="badge badge-ok">&#10003; done</span>';
    } else if (status === 'FAILED' || status === 'failed' || (typeof status === 'number' && status >= 400)) {
      badgeHtml = '<span class="badge badge-fail">&#10007; fail</span>';
    } else if (status === 'PROCESSING') {
      badgeHtml = '<span class="badge badge-proc">&#9203; gen...</span>';
    } else if (status === 200 || status === 'processing') {
      badgeHtml = '<span class="badge badge-proc">&#9203; sent</span>';
    } else {
      badgeHtml = '<span class="badge badge-proc">&#9203; sent</span>';
    }

    const errorDisplay = error
      ? `<td class="td-error" title="${escHtml(error)}">${escHtml(truncate(error, 28))}</td>`
      : `<td class="td-error empty">—</td>`;

    return `<tr>
      <td class="td-id" data-request-id="${escHtml(entry.id || '')}">${escHtml(shortId)}</td>
      <td class="td-type">${escHtml(type)}</td>
      <td class="td-time">${escHtml(time)}</td>
      <td>${badgeHtml}</td>
      ${errorDisplay}
    </tr>`;
  });

  tbody.innerHTML = rows.join('');

  // Attach click handlers to ID cells
  tbody.querySelectorAll('.td-id[data-request-id]').forEach(td => {
    td.addEventListener('click', () => {
      const reqId = td.getAttribute('data-request-id');
      if (reqId) showRequestDetail(reqId);
    });
  });
}

function escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function truncate(str, len) {
  if (!str || str.length <= len) return str;
  return str.slice(0, len) + '…';
}

// ── Request detail modal ────────────────────────────────────

let _logEntries = [];

function showRequestDetail(reqId) {
  const entry = _logEntries.find(e => e.id === reqId);
  if (!entry) return;

  const overlay = document.getElementById('detail-overlay');
  const title = document.getElementById('detail-title');
  const body = document.getElementById('detail-body');

  title.textContent = `Request ${String(reqId).slice(0, 12)}`;

  const fields = [
    ['ID', entry.id],
    ['Type', formatType(entry.type || entry.method)],
    ['Time', formatTime(entry.time || entry.timestamp || entry.createdAt)],
    ['Status', entry.status || entry.state || 'pending'],
    ['HTTP', entry.httpStatus || '—'],
    ['URL', entry.url || '—'],
    ['Payload', entry.payloadSummary || '—'],
    ['Response', entry.responseSummary || '—'],
    ['Error', entry.error || '—'],
  ];

  body.innerHTML = fields.map(([label, value]) => {
    let cls = 'detail-value';
    if (label === 'Error' && value && value !== '—') cls += ' error';
    if (label === 'Status' && (value === 'COMPLETED' || value === 'success')) cls += ' ok';
    return `<div class="detail-row">
      <div class="detail-label">${escHtml(label)}</div>
      <div class="${cls}">${escHtml(String(value || '—'))}</div>
    </div>`;
  }).join('');

  overlay.classList.add('open');
}

document.getElementById('detail-close').addEventListener('click', () => {
  document.getElementById('detail-overlay').classList.remove('open');
});

document.getElementById('detail-overlay').addEventListener('click', (e) => {
  if (e.target === e.currentTarget) {
    e.currentTarget.classList.remove('open');
  }
});

// ── Initial data fetch ───────────────────────────────────────

function fetchStatus() {
  chrome.runtime.sendMessage({ type: 'STATUS' }, (response) => {
    if (chrome.runtime.lastError) return;
    if (response?.ok) {
      updateStatus(response.data);
    }
  });
}

function fetchLog() {
  chrome.runtime.sendMessage({ type: 'REQUEST_LOG' }, (response) => {
    if (chrome.runtime.lastError) return;
    if (response?.ok && response.data?.log) {
      updateRequestLog(response.data.log);
    }
  });
}

function sendRuntimeMessageSafe(message, onResponse) {
  chrome.runtime.sendMessage(message, (response) => {
    if (chrome.runtime.lastError) return;
    if (typeof onResponse === 'function') onResponse(response);
  });
}

function applyAgentBadge(mode) {
  const statusEl = document.getElementById('operator-pack-status');
  if (mode === 'online') {
    statusEl.textContent = 'online';
    statusEl.style.background = 'rgba(34,197,94,0.15)';
    statusEl.style.color = 'var(--green)';
    return;
  }
  if (mode === 'repair') {
    statusEl.textContent = 'repair';
    statusEl.style.background = 'rgba(245,158,11,0.15)';
    statusEl.style.color = 'var(--yellow)';
    return;
  }
  statusEl.textContent = 'offline';
  statusEl.style.background = 'rgba(239,68,68,0.15)';
  statusEl.style.color = 'var(--red)';
}

function isLocalAgentHealthy() {
  return Boolean(
    _localAgentStatus &&
    _operatorPack &&
    _operatorPack.available &&
    _dashboardReachable !== false
  );
}

function needsRepairState() {
  if (!_localAgentStatus) return true;
  if (_operatorPackError) return true;
  if (_operatorPack && !_operatorPack.available) return true;
  if (_dashboardReachable === false) return true;
  return false;
}

function updateRepairButton() {
  const repairBtn = document.getElementById('btn-dashboard');
  repairBtn.classList.remove('btn-primary');
  repairBtn.disabled = false;

  if (needsRepairState()) {
    repairBtn.title = 'Repair guidance is available because the local agent is unhealthy.';
    return;
  }

  repairBtn.title = 'Local Agent is already online. No repair required.';
}

function renderLocalAgentPanel() {
  const summaryEl = document.getElementById('operator-summary');
  const productsEl = document.getElementById('operator-products');
  const enginesEl = document.getElementById('operator-engines');
  const silosEl = document.getElementById('operator-silos');

  if (_operatorPack) {
    productsEl.textContent = String((_operatorPack.products || []).length);
    enginesEl.textContent = String((_operatorPack.engines || []).length);
    silosEl.textContent = String((_operatorPack.silos || []).length);
  } else {
    productsEl.textContent = '0';
    enginesEl.textContent = '0';
    silosEl.textContent = '0';
  }

  if (!_localAgentStatus) {
    applyAgentBadge('offline');
    summaryEl.textContent = `Local Agent offline. PowerShell is only needed for repair/install diagnostics: ${LOCAL_AGENT_REPAIR_COMMAND}`;
    updateRepairButton();
    return;
  }

  if (isLocalAgentHealthy()) {
    applyAgentBadge('online');
    summaryEl.textContent = 'Local Agent online. Dashboard ready. PowerShell is only needed for repair/install diagnostics.';
    updateRepairButton();
    return;
  }

  applyAgentBadge('repair');
  if (_operatorPackError) {
    summaryEl.textContent = `Local Agent online, but operator content pack is unavailable: ${_operatorPackError}.`;
  } else if (_operatorPack && !_operatorPack.available) {
    summaryEl.textContent = 'Local Agent online, but operator content pack is not ready. Repair may be required.';
  } else if (_dashboardError || _dashboardReachable === false) {
    summaryEl.textContent = `Local Agent online, but dashboard URL is unreachable: ${_dashboardError || 'unknown error'}.`;
  } else {
    summaryEl.textContent = 'Local Agent online, but health checks are incomplete. Repair may be required.';
  }
  updateRepairButton();
}

async function fetchLocalAgentStatus() {
  try {
    const res = await fetch(LOCAL_AGENT_STATUS_URL);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    _localAgentStatus = await res.json();
    _localAgentError = null;
  } catch (error) {
    _localAgentStatus = null;
    _localAgentError = String(error?.message || error);
  }
  renderLocalAgentPanel();
}

async function fetchDashboardStatus() {
  try {
    const res = await fetch(LOCAL_AGENT_DASHBOARD_URL);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    _dashboardReachable = true;
    _dashboardError = null;
  } catch (error) {
    _dashboardReachable = false;
    _dashboardError = String(error?.message || error);
  }

  renderLocalAgentPanel();
}

async function fetchOperatorPack() {
  try {
    const res = await fetch(LOCAL_AGENT_CONTENT_PACK_URL);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    _operatorPack = await res.json();
    _operatorPackError = null;
  } catch (error) {
    _operatorPack = null;
    _operatorPackError = String(error?.message || error);
  }

  renderLocalAgentPanel();
}

// ── Message listener (push updates) ─────────────────────────

chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type === 'STATUS_PUSH') {
    fetchStatus();
  }
  if (msg.type === 'REQUEST_LOG_UPDATE') {
    if (msg.log) updateRequestLog(msg.log);
  }
});

// ── Toggle (connect / disconnect) ───────────────────────────

document.getElementById('main-toggle').addEventListener('change', (e) => {
  const msgType = e.target.checked ? 'RECONNECT' : 'DISCONNECT';
  sendRuntimeMessageSafe({ type: msgType }, () => {
    setTimeout(fetchStatus, 400);
  });
});

// ── Action buttons ───────────────────────────────────────────

document.getElementById('btn-flow').addEventListener('click', () => {
  sendRuntimeMessageSafe({ type: 'OPEN_FLOW_TAB' });
});

document.getElementById('btn-operator').addEventListener('click', async () => {
  await chrome.tabs.create({ url: LOCAL_AGENT_DASHBOARD_URL });
});

document.getElementById('btn-dashboard').addEventListener('click', async () => {
  const summaryEl = document.getElementById('operator-summary');

  if (isLocalAgentHealthy()) {
    summaryEl.textContent = 'Local Agent is already online. No repair required.';
    return;
  }

  if (_localAgentStatus) {
    await chrome.tabs.create({ url: LOCAL_AGENT_REPAIR_URL });
    return;
  }

  summaryEl.textContent = `Local Agent offline. Run installer: ${LOCAL_AGENT_REPAIR_COMMAND}`;
});

document.getElementById('btn-token').addEventListener('click', () => {
  const btn = document.getElementById('btn-token');
  btn.textContent = 'Opening...';
  btn.disabled = true;
  sendRuntimeMessageSafe({ type: 'REFRESH_TOKEN' }, () => {
    btn.textContent = 'Refresh Token';
    btn.disabled = false;
  });
});

// ── Init ─────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  fetchStatus();
  fetchLog();
  fetchLocalAgentStatus();
  fetchOperatorPack();
  fetchDashboardStatus();
});
