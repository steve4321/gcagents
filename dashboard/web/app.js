const API_BASE = '/api';
const REFRESH_INTERVAL = 30000;
const PIPELINE_PHASES = [
  { id: 'idle', label: 'Idle' },
  { id: 'scanning', label: 'Scan' },
  { id: 'evaluating', label: 'Evaluate' },
  { id: 'designing', label: 'Design' },
  { id: 'developing', label: 'Dev' },
  { id: 'testing', label: 'QA' },
  { id: 'building', label: 'Build' },
  { id: 'publishing', label: 'Deploy' },
  { id: 'operating', label: 'Operate' },
];

const statusBadge = {
  live: 'badge-live',
  published: 'badge-published',
  publishing: 'badge-published',
  developing: 'badge-developing',
  designing: 'badge-developing',
  testing: 'badge-testing',
  proposed: 'badge-proposed',
};

let refreshTimer = null;

function $(sel) { return document.querySelector(sel); }
function $$(sel) { return document.querySelectorAll(sel); }

function fmtTime(iso) {
  if (!iso) return '--';
  const d = new Date(iso);
  return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function fmtDate(iso) {
  if (!iso) return '--';
  const d = new Date(iso);
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function fmtDuration(seconds) {
  if (!seconds || seconds < 0) return '--';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  const parts = [];
  if (h > 0) parts.push(h + 'h');
  if (m > 0) parts.push(m + 'm');
  parts.push(s + 's');
  return parts.join(' ');
}

function showError(el, msg) {
  el.innerHTML = `<div class="error-state">&#9888; ${msg}</div>`;
}

function showLoader(el) {
  el.innerHTML = '<div class="loader"></div>';
}

async function fetchJSON(url) {
  const res = await fetch(url);
  if (!res.ok) {
    const body = await res.text().catch(() => '');
    throw new Error(`${res.status} ${res.statusText}${body ? ': ' + body.slice(0, 100) : ''}`);
  }
  return res.json();
}

/* --- Status --- */
async function renderStatus() {
  const el = $('#statusContent');
  showLoader(el);
  try {
    const data = await fetchJSON(`${API_BASE}/status`);
    const phase = data.phase || 'idle';
    const dot = $('#statusDot');
    const processingPhases = ['scanning', 'evaluating', 'designing', 'developing', 'testing', 'building', 'publishing'];
    if (phase === 'idle' || phase === 'operating') {
      dot.className = 'status-dot active';
    } else if (processingPhases.includes(phase)) {
      dot.className = 'status-dot processing';
    } else {
      dot.className = 'status-dot error';
    }

    const activeName = data.active_project ? data.active_project.name : 'None';
    const activeStatus = data.active_project ? data.active_project.status : '--';
    const hasErrors = data.errors && data.errors.length > 0;

    el.innerHTML = `
      <div class="status-grid">
        <div class="stat-item">
          <span class="stat-label">Pipeline Phase</span>
          <span class="stat-value">${phase.charAt(0).toUpperCase() + phase.slice(1)}</span>
        </div>
        <div class="stat-item">
          <span class="stat-label">Active Project</span>
          <span class="stat-value">${activeName} ${activeStatus !== '--' ? `<small>(${activeStatus})</small>` : ''}</span>
        </div>
        <div class="stat-item">
          <span class="stat-label">Last Scan</span>
          <span class="stat-value">${fmtTime(data.last_scan_time)}</span>
        </div>
        <div class="stat-item">
          <span class="stat-label">Redis</span>
          <span class="stat-value" style="color: ${data.redis_connected ? 'var(--green)' : 'var(--red)'}">
            ${data.redis_connected ? '&#9679; Connected' : '&#9679; Disconnected'}
          </span>
        </div>
      </div>
      ${hasErrors ? `<div class="error-state" style="margin-top:8px">&#9888; ${data.errors[0]}</div>` : ''}
    `;
  } catch (err) {
    showError(el, `Failed to load status: ${err.message}`);
  }
}

/* --- Pipeline --- */
async function renderPipeline() {
  const el = $('#pipelineContent');
  showLoader(el);
  try {
    const data = await fetchJSON(`${API_BASE}/status`);
    const currentPhase = data.phase || 'idle';
    const currentIdx = PIPELINE_PHASES.findIndex(p => p.id === currentPhase);

    let html = '<div class="pipeline-steps">';
    PIPELINE_PHASES.forEach((phase, i) => {
      let cls = '';
      if (i < currentIdx) cls = 'completed';
      else if (i === currentIdx) cls = 'active';
      if (data.errors && data.errors.length > 0 && i === currentIdx) cls = 'error';

      html += `<div class="pipeline-step ${cls}">`;
      html += `<div class="pipeline-dot">${cls === 'completed' ? '&#10003;' : i + 1}</div>`;
      html += `<div class="pipeline-label">${phase.label}</div>`;
      html += '</div>';
      if (i < PIPELINE_PHASES.length - 1) {
        html += '<div class="pipeline-connector"></div>';
      }
    });
    html += '</div>';
    el.innerHTML = html;
  } catch (err) {
    showError(el, `Failed to load pipeline: ${err.message}`);
  }
}

/* --- Market --- */
async function renderMarket() {
  const el = $('#marketContent');
  showLoader(el);
  try {
    const signals = await fetchJSON(`${API_BASE}/market/latest`);
    if (!signals || signals.length === 0) {
      el.innerHTML = '<p style="color:var(--text-muted);text-align:center;padding:20px;">No market data yet. The scanner will populate this as it runs.</p>';
      return;
    }

    const top = signals.slice(0, 20);
    let html = '<div class="market-list">';
    top.forEach(s => {
      const score = s.score || 0;
      const scoreClass = score >= 7 ? 'high' : score >= 4 ? 'medium' : 'low';
      const genre = s.genre || '';
      html += `
        <div class="market-item">
          <span class="market-score ${scoreClass}">${score.toFixed(1)}</span>
          <div class="market-info">
            <div class="market-title">${s.title || s.signal_type}</div>
            <div class="market-meta">
              <span>${s.source}</span>
              ${genre ? `<span class="market-genre">${genre}</span>` : ''}
              <span>${fmtDate(s.captured_at)}</span>
            </div>
          </div>
        </div>
      `;
    });
    html += '</div>';
    el.innerHTML = html;
  } catch (err) {
    showError(el, `Failed to load market data: ${err.message}`);
  }
}

/* --- Projects --- */
async function renderProjects() {
  const el = $('#projectsContent');
  showLoader(el);
  try {
    const projects = await fetchJSON(`${API_BASE}/projects`);
    if (!projects || projects.length === 0) {
      el.innerHTML = '<p style="color:var(--text-muted);text-align:center;padding:20px;">No game projects yet. They will appear once the pipeline creates them.</p>';
      return;
    }

    let html = '<div class="projects-grid">';
    projects.forEach(p => {
      const badgeCls = statusBadge[p.status] || '';
      const published = p.published_at ? fmtDate(p.published_at) : '--';
      const itch = p.itch_url || '';

      html += `
        <div class="project-card">
          <div class="project-card-header">
            <div>
              <div class="project-name">${p.name}</div>
              <div class="project-genre">${p.genre}</div>
            </div>
            <span class="badge ${badgeCls}">${p.status}</span>
          </div>
          <div class="project-metrics">
            <div class="metric-item">
              <span class="metric-label">Created</span>
              <span class="metric-value">${fmtDate(p.created_at)}</span>
            </div>
            <div class="metric-item">
              <span class="metric-label">Published</span>
              <span class="metric-value">${published}</span>
            </div>
          </div>
          ${itch ? `<a href="${itch}" class="project-link" target="_blank" rel="noopener">&#8599; Play on itch.io</a>` : ''}
        </div>
      `;
    });
    html += '</div>';
    el.innerHTML = html;
  } catch (err) {
    showError(el, `Failed to load projects: ${err.message}`);
  }
}

/* --- Memory --- */
async function renderMemory() {
  const el = $('#memoryContent');
  showLoader(el);
  try {
    const memories = await fetchJSON(`${API_BASE}/memory`);
    if (!memories || memories.length === 0) {
      el.innerHTML = '<p style="color:var(--text-muted);text-align:center;padding:20px;">No company memories yet. They will appear as the system learns.</p>';
      return;
    }

    let html = '<div class="memory-list">';
    memories.slice(0, 20).forEach(m => {
      const content = typeof m.content === 'string' ? m.content : (m.content?.summary || m.content?.text || JSON.stringify(m.content).slice(0, 200));

      html += `
        <div class="memory-item">
          <div class="memory-importance">${(m.importance * 100).toFixed(0)}%</div>
          <div class="memory-info">
            <div class="memory-title">${m.title}</div>
            <div class="memory-category">${m.category}</div>
            <div class="memory-content">${content}</div>
            <div class="memory-time">${fmtDate(m.created_at)}</div>
          </div>
        </div>
      `;
    });
    html += '</div>';
    el.innerHTML = html;
  } catch (err) {
    showError(el, `Failed to load memory: ${err.message}`);
  }
}

/* --- Refresh --- */
function updateTimestamp() {
  const el = $('#lastUpdateTime');
  if (el) el.textContent = new Date().toLocaleTimeString();
}

async function refreshAll() {
  updateTimestamp();
  await Promise.allSettled([
    renderStatus(),
    renderPipeline(),
    renderMarket(),
    renderProjects(),
    renderMemory(),
  ]);
}

/* --- Init --- */
function init() {
  refreshAll();
  if (refreshTimer) clearInterval(refreshTimer);
  refreshTimer = setInterval(refreshAll, REFRESH_INTERVAL);

  const btn = $('#refreshBtn');
  if (btn) {
    btn.addEventListener('click', () => {
      refreshAll();
    });
  }
}

document.addEventListener('DOMContentLoaded', init);
