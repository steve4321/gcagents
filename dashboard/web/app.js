const API_BASE = '/api';
const REFRESH_INTERVAL = 15000;
const PIPELINE_POLL_INTERVAL = 3000;
const PIPELINE_FAST_REFRESH = 5000;
let pipelineRunning = false;
let pipelineStatusInterval = null;
let foreverActive = false;
const PIPELINE_PHASES = [
  { id: 'scan', label: 'Scan', icon: 'scan' },
  { id: 'evaluate', label: 'Evaluate', icon: 'evaluate' },
  { id: 'design', label: 'Design', icon: 'design' },
  { id: 'art', label: 'Art', icon: 'art' },
  { id: 'develop', label: 'Develop', icon: 'develop' },
  { id: 'qa', label: 'QA', icon: 'qa' },
  { id: 'build', label: 'Build', icon: 'build' },
  { id: 'deploy', label: 'Deploy', icon: 'deploy' },
];

const AGENTS = [
  { id: 'scan', name: 'Scanner', icon: 'M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z' },
  { id: 'evaluate', name: 'Evaluator', icon: 'M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z' },
  { id: 'design', name: 'Designer', icon: 'M11 4a2 2 0 114 0v1a1 1 0 001 1h3a1 1 0 011 1v3a1 1 0 01-1 1h-1a2 2 0 100 4h1a1 1 0 011 1v3a1 1 0 01-1 1h-3a1 1 0 01-1-1v-1a2 2 0 10-4 0v1a1 1 0 01-1 1H7a1 1 0 01-1-1v-3a1 1 0 00-1-1H4a2 2 0 110-4h1a1 1 0 001-1V7a1 1 0 011-1h3a1 1 0 001-1V4z' },
  { id: 'art', name: 'Artist', icon: 'M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z' },
  { id: 'develop', name: 'Developer', icon: 'M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4' },
  { id: 'qa', name: 'QA Tester', icon: 'M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z' },
  { id: 'build', name: 'Builder', icon: 'M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z' },
  { id: 'deploy', name: 'Deployer', icon: 'M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M9 19l3 3m0 0l3-3m-3 3V10' },
];

function $(sel) { return document.querySelector(sel); }
function $$(sel) { return document.querySelectorAll(sel); }

function fmtRelativeTime(isoString) {
  if (!isoString) return '--';
  const now = Date.now();
  const then = new Date(isoString).getTime();
  const diff = Math.floor((now - then) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

function fmtDuration(ms) {
  if (!ms || ms < 0) return '--';
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  const m = Math.floor(ms / 60000);
  const s = Math.floor((ms % 60000) / 1000);
  return s > 0 ? `${m}m ${s}s` : `${m}m`;
}

function fmtFileSize(bytes) {
  if (!bytes || bytes === 0) return '0 B';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(0)} KB`;
  if (bytes < 1073741824) return `${(bytes / 1048576).toFixed(1)} MB`;
  return `${(bytes / 1073741824).toFixed(1)} GB`;
}

function getStatusClass(status) {
  if (!status) return 'idle';
  const s = status.toLowerCase();
  if (s === 'completed' || s === 'success' || s === 'published' || s === 'live') return 'completed';
  if (s === 'running' || s === 'active' || s === 'developing' || s === 'building') return 'running';
  if (s === 'failed' || s === 'error') return 'failed';
  return 'idle';
}

function renderSkeleton(type) {
  const templates = {
    agentCard: '<div class="agent-card skeleton skeleton-card"></div>',
    pipeline: '<div class="pipeline-container"><div class="pipeline-track">' +
      PIPELINE_PHASES.map(() => '<div class="pipeline-phase"><div class="pipeline-node skeleton" style="width:44px;height:44px;border-radius:50%"></div></div>').join('') +
      '</div></div>',
    opportunity: '<div class="opportunity-card skeleton" style="height:120px"></div>',
    gameCard: '<div class="game-card skeleton" style="height:140px"></div>',
    memoryItem: '<div class="memory-entry skeleton" style="height:80px"></div>',
  };
  return templates[type] || '';
}

function showError(el, msg, detail) {
  el.innerHTML = `
    <div class="error-state">
      <svg class="error-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="12" cy="12" r="10"/>
        <line x1="12" y1="8" x2="12" y2="12"/>
        <line x1="12" y1="16" x2="12.01" y2="16"/>
      </svg>
      <div class="error-message">${msg}</div>
      ${detail ? `<div class="error-detail">${detail}</div>` : ''}
    </div>
  `;
}

function showEmpty(el, message, icon) {
  el.innerHTML = `
    <div class="empty-state">
      <svg class="empty-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
        ${icon || '<circle cx="12" cy="12" r="10"/><path d="M8 12h8"/>'}
      </svg>
      <div class="empty-message">${message}</div>
    </div>
  `;
}

async function fetchJSON(url, options) {
  const res = await fetch(url, options);
  if (!res.ok) {
    const body = await res.text().catch(() => '');
    throw new Error(`${res.status} ${res.statusText}${body ? ': ' + body.slice(0, 100) : ''}`);
  }
  return res.json();
}

function updateTimestamp() {
  const el = $('#lastUpdateTime');
  if (el) el.textContent = new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function updateDocumentTitle(phase) {
  const prefix = phase && phase !== 'idle' ? `[${phase.toUpperCase()}]` : '[IDLE]';
  document.title = `${prefix} GCAgents`;
}

async function renderAgents() {
  const container = $('#agentsContent');
  if (!container) return;

  container.innerHTML = `<div class="agent-grid">${AGENTS.map(() => renderSkeleton('agentCard')).join('')}</div>`;

  try {
    const [statusData, agentsData] = await Promise.all([
      fetchJSON(`${API_BASE}/status`),
      fetchJSON(`${API_BASE}/agents`)
    ]);

    const currentPhase = statusData.phase || 'idle';
    const logs = agentsData.logs || [];
    const stats = agentsData.stats || [];

    updateDocumentTitle(currentPhase);

    const statsMap = {};
    stats.forEach(s => { statsMap[s.node_name] = s; });

    const logsMap = {};
    logs.forEach(l => { logsMap[l.node_name] = l; });

    let html = '<div class="agent-grid">';
    AGENTS.forEach(agent => {
      const stat = statsMap[agent.id] || {};
      const log = logsMap[agent.id] || {};
      const status = log.status || 'idle';
      const statusClass = getStatusClass(status);

      html += `
        <div class="agent-card status-${statusClass}">
          <div class="agent-card-header">
            <div class="agent-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="${agent.icon}"/>
              </svg>
            </div>
            <span class="agent-status-badge ${statusClass}">${status}</span>
          </div>
          <div class="agent-name">${agent.name}</div>
          <div class="agent-stats">
            <div class="agent-stat">
              <div class="agent-stat-value" data-tooltip="${fmtDuration(log.duration_ms) || '--'}">${fmtDuration(log.duration_ms) || '--'}</div>
              <div class="agent-stat-label">Last Run</div>
            </div>
            <div class="agent-stat">
              <div class="agent-stat-value">${stat.runs || 0}</div>
              <div class="agent-stat-label">Runs</div>
            </div>
            <div class="agent-stat">
              <div class="agent-stat-value">${stat.successes || 0}/${stat.failures || 0}</div>
              <div class="agent-stat-label">S/F</div>
            </div>
          </div>
        </div>
      `;
    });
    html += '</div>';
    container.innerHTML = html;

  } catch (err) {
    showError(container, 'Failed to load agents', err.message);
  }
}

async function renderPipeline() {
  const container = $('#pipelineContent');
  if (!container) return;

  container.innerHTML = `<div class="pipeline-container"><div class="pipeline-track">${PIPELINE_PHASES.map(() => '<div class="pipeline-phase"><div class="pipeline-node skeleton" style="width:44px;height:44px;border-radius:50%"></div></div>').join('')}</div></div>`;

  try {
    const [statusData, historyData] = await Promise.all([
      fetchJSON(`${API_BASE}/status`),
      fetchJSON(`${API_BASE}/pipeline/history`)
    ]);

    const currentPhase = statusData.phase || 'idle';
    const currentIdx = PIPELINE_PHASES.findIndex(p => p.id === currentPhase);
    const hasErrors = statusData.errors && statusData.errors.length > 0;

    const historyMap = {};
    (historyData || []).forEach(h => { historyMap[h.phase] = h; });

    let html = '<div class="pipeline-container"><div class="pipeline-track">';

    PIPELINE_PHASES.forEach((phase, i) => {
      let cls = 'upcoming';
      if (i < currentIdx) cls = 'completed';
      else if (i === currentIdx) cls = hasErrors ? 'error' : 'current';

      const hist = historyMap[phase.id];
      const tooltip = hist ? `${fmtRelativeTime(hist.updated_at)}${hist.errors?.length ? ' - ' + hist.errors[0] : ''}` : '';

      html += `
        <div class="pipeline-phase ${cls}" data-tooltip="${tooltip}">
          <div class="pipeline-node">
            ${cls === 'completed' ?
              '<svg class="node-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><polyline points="20 6 9 17 4 12"/></svg>' :
              `<svg class="node-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="${AGENTS.find(a => a.id === phase.id)?.icon || ''}"/></svg>`
            }
          </div>
          <div class="pipeline-phase-name">${phase.label}</div>
        </div>
      `;
    });

    html += '</div></div>';
    container.innerHTML = html;

  } catch (err) {
    showError(container, 'Failed to load pipeline', err.message);
  }
}

async function renderMarket() {
  const container = $('#marketContent');
  if (!container) return;

  container.innerHTML = '<div class="market-grid"></div>';
  const grid = container.querySelector('.market-grid');

  try {
    const [reportData, signalsData] = await Promise.all([
      fetchJSON(`${API_BASE}/market/report`),
      fetchJSON(`${API_BASE}/market/latest`)
    ]);

    const analysis = reportData?.raw_analysis || 'No analysis available yet. The market scanner will populate this as it runs.';
    const opportunities = (reportData?.opportunities || []).slice(0, 3);
    const signals = (signalsData || []).slice(0, 20);

    grid.innerHTML = `
      <div class="market-analysis">
        <div class="market-analysis-header">
          <span class="market-analysis-title">AI Analysis</span>
          <span class="market-analysis-badge">${reportData?.signals_count || 0} signals</span>
        </div>
        <div class="market-analysis-content">${analysis}</div>
      </div>
      <div class="opportunities-section">
        <div class="opportunities-title">Top Opportunities</div>
        ${opportunities.length > 0 ? opportunities.map(opp => `
          <div class="opportunity-card">
            <div class="opportunity-header">
              <span class="opportunity-name">${opp.name || 'Unnamed'}</span>
              <span class="opportunity-score">${(opp.market_opportunity_score || 0).toFixed(1)}</span>
            </div>
            <div class="opportunity-genre">${opp.genre || 'General'}</div>
            <div class="opportunity-description">${opp.description || 'No description available.'}</div>
            <div class="opportunity-meta">
              <span>
                <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>
                ${opp.estimated_dev_hours ? `${opp.estimated_dev_hours}h` : '--'}
              </span>
              <span>
                <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M13 7h4a2 2 0 012 2v4M3 5a2 2 0 012-2h4m0 0v4m0-4L8 13m4-4L3 9"/></svg>
                ${opp.differentiation || 'Standard'}
              </span>
            </div>
          </div>
        `).join('') : '<div class="empty-state"><div class="empty-message">No opportunities detected yet.</div></div>'}
      </div>
      <div class="signals-section">
        <div class="signals-title">Latest Signals</div>
        <div class="signals-table-container">
          ${signals.length > 0 ? `
            <table class="signals-table">
              <thead>
                <tr>
                  <th>Source</th>
                  <th>Type</th>
                  <th>Title</th>
                  <th>Genre</th>
                  <th>Score</th>
                  <th>Time</th>
                </tr>
              </thead>
              <tbody>
                ${signals.map(s => `
                  <tr>
                    <td><span class="signal-source">${s.source || '--'}</span></td>
                    <td><span class="signal-type">${s.signal_type || '--'}</span></td>
                    <td class="signal-title">${s.title || '--'}</td>
                    <td>${s.genre || '--'}</td>
                    <td class="signal-score">${(s.score || 0).toFixed(1)}</td>
                    <td class="signal-time" data-tooltip="${s.captured_at ? new Date(s.captured_at).toLocaleString() : ''}">${fmtRelativeTime(s.captured_at)}</td>
                  </tr>
                `).join('')}
              </tbody>
            </table>
          ` : '<div class="empty-state"><div class="empty-message">No signals captured yet.</div></div>'}
        </div>
      </div>
    `;

  } catch (err) {
    showError(grid, 'Failed to load market data', err.message);
  }
}

async function renderProjects() {
  const container = $('#projectsContent');
  if (!container) return;

  container.innerHTML = `<div class="games-grid">${[1,2,3].map(() => renderSkeleton('gameCard')).join('')}</div>`;

  try {
    const [statusData, projectsData] = await Promise.all([
      fetchJSON(`${API_BASE}/status`),
      fetchJSON(`${API_BASE}/projects`)
    ]);

    const games = statusData.games || [];
    const projects = projectsData || [];

    if (games.length === 0 && projects.length === 0) {
      showEmpty(container, 'No game projects yet. They will appear as the pipeline creates them.');
      return;
    }

    const projectsMap = {};
    projects.forEach(p => { projectsMap[p.id] = p; });

    const allGames = [...games];
    if (projects.length > games.length) {
      projects.forEach(p => {
        if (!allGames.find(g => g.name === p.name)) {
          allGames.push({ name: p.name, status: p.status });
        }
      });
    }

    let html = '<div class="games-grid">';
    allGames.forEach(game => {
      const project = projects.find(p => p.name === game.name) || {};
      const statusClass = getStatusClass(game.status);

      html += `
        <div class="game-card" data-game-name="${game.name || ''}">
          <div class="game-header">
            <div class="game-info">
              <div class="game-name">${game.name || 'Unnamed Game'}</div>
              <div class="game-genre">${project.genre || game.genre || 'General'}</div>
            </div>
            <span class="game-status ${statusClass}">${game.status || 'unknown'}</span>
          </div>
          <div class="game-build-info">
            <div class="build-stat">
              <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M13 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V9z"/><polyline points="13 2 13 9 20 9"/></svg>
              <span class="build-stat-value">${game.file_count || 0}</span>
              <span class="build-stat-label">files</span>
            </div>
            <div class="build-stat">
              <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
              <span class="build-stat-value">${fmtFileSize(game.dist_size)}</span>
              <span class="build-stat-label">size</span>
            </div>
          </div>
          <div class="game-footer">
            <div class="game-footer-left">
              <button class="play-btn" data-play="${game.name || ''}" title="Preview Game">▶</button>
            </div>
            ${project.itch_url ? `
              <a href="${project.itch_url}" class="game-url" target="_blank" rel="noopener">
                <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
                Play on itch.io
              </a>
            ` : '<span></span>'}
            ${project.id ? `<button class="gdd-toggle" data-project-id="${project.id}">View GDD</button>` : ''}
          </div>
          ${project.id ? `<div class="gdd-preview" id="gdd-preview-${project.id}"></div>` : ''}
        </div>
      `;
    });
    html += '</div>';
    container.innerHTML = html;

    container.querySelectorAll('.gdd-toggle').forEach(btn => {
      btn.addEventListener('click', async () => {
        const projectId = btn.dataset.projectId;
        const preview = $(`#gdd-preview-${projectId}`);
        if (!preview) return;

        if (preview.classList.contains('visible')) {
          preview.classList.remove('visible');
          btn.textContent = 'View GDD';
          return;
        }

        preview.innerHTML = '<div class="skeleton" style="height:60px"></div>';
        preview.classList.add('visible');
        btn.textContent = 'Hide GDD';

        try {
          const gddData = await fetchJSON(`${API_BASE}/gdd/${projectId}`);
          const content = gddData?.gdd ? JSON.stringify(gddData.gdd, null, 2) : 'No GDD data available.';
          preview.innerHTML = `<pre>${content.slice(0, 1000)}${content.length > 1000 ? '...' : ''}</pre>`;
        } catch {
          preview.innerHTML = '<pre style="color:var(--accent-red)">Failed to load GDD.</pre>';
        }
      });
    });

    container.querySelectorAll('.play-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const gameName = btn.dataset.play;
        if (gameName) openPreview(gameName);
      });
    });

  } catch (err) {
    showError(container, 'Failed to load projects', err.message);
  }
}

async function renderMemory() {
  const container = $('#memoryContent');
  if (!container) return;

  container.innerHTML = `<div class="memory-list">${[1,2,3].map(() => renderSkeleton('memoryItem')).join('')}</div>`;

  try {
    const memories = await fetchJSON(`${API_BASE}/memory`);

    if (!memories || memories.length === 0) {
      showEmpty(container, 'No company memories yet. They will appear as the system learns.', '<path d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>');
      return;
    }

    const sorted = [...memories].sort((a, b) => (b.importance || 0) - (a.importance || 0));

    let html = '<div class="memory-list">';
    sorted.forEach(m => {
      const content = typeof m.content === 'string' ? m.content :
        (m.content?.summary || m.content?.text || JSON.stringify(m.content || {}).slice(0, 150));
      const importance = Math.round((m.importance || 0) * 100);

      html += `
        <div class="memory-entry">
          <span class="memory-category">${m.category || 'general'}</span>
          <div class="memory-content">
            <div class="memory-title">${m.title || 'Untitled'}</div>
            <div class="memory-preview">${content}</div>
          </div>
          <div class="memory-meta">
            <span class="memory-time" data-tooltip="${m.created_at ? new Date(m.created_at).toLocaleString() : ''}">${fmtRelativeTime(m.created_at)}</span>
            <div class="importance-container">
              <span class="importance-label">Importance</span>
              <div class="importance-bar">
                <div class="importance-fill" style="width:${importance}%"></div>
              </div>
            </div>
          </div>
        </div>
      `;
    });
    html += '</div>';
    container.innerHTML = html;

  } catch (err) {
    showError(container, 'Failed to load memory', err.message);
  }
}

function toggleSection(sectionId) {
  const section = $(`#${sectionId}`);
  if (section) {
    section.classList.toggle('collapsed');
  }
}

async function triggerPipeline() {
  const btn = $('#runPipelineBtn');
  if (!btn) return;

  btn.classList.add('running');
  btn.textContent = 'Running...';
  pipelineRunning = true;

  try {
    await fetchJSON(`${API_BASE}/pipeline/run`);
  } catch {
    btn.classList.remove('running');
    btn.textContent = '▶ Run';
    pipelineRunning = false;
    return;
  }

  if (pipelineStatusInterval) clearInterval(pipelineStatusInterval);
  pipelineStatusInterval = setInterval(checkPipelineStatus, PIPELINE_POLL_INTERVAL);
  checkPipelineStatus();
}

async function toggleForever() {
  const btn = $('#foreverToggleBtn');
  if (!btn) return;

  if (foreverActive) {
    // Stop forever mode
    btn.disabled = true;
    btn.textContent = 'Stopping...';
    try {
      await fetchJSON(`${API_BASE}/pipeline/stop`, { method: 'POST' });
    } catch { /* ignore */ }
    foreverActive = false;
    btn.classList.remove('active');
    btn.textContent = '⟳ 24/7 OFF';
    btn.disabled = false;
  } else {
    // Start forever mode
    btn.disabled = true;
    btn.textContent = 'Starting...';
    try {
      await fetchJSON(`${API_BASE}/pipeline/run-forever?interval=3600`, { method: 'POST' });
      foreverActive = true;
      btn.classList.add('active');
      btn.textContent = '● 24/7 ON';
    } catch {
      btn.textContent = '⟳ 24/7 OFF';
    }
    btn.disabled = false;
  }
}

async function checkPipelineStatus() {
  const btn = $('#runPipelineBtn');
  const foreverBtn = $('#foreverToggleBtn');
  if (!btn) return;

  try {
    const status = await fetchJSON(`${API_BASE}/pipeline/status`);

    if (foreverBtn) {
      foreverActive = status.forever_running;
      if (foreverActive) {
        foreverBtn.classList.add('active');
        foreverBtn.textContent = '● 24/7 ON';
      } else {
        foreverBtn.classList.remove('active');
        foreverBtn.textContent = '⟳ 24/7 OFF';
      }
    }

    if (status.mode === 'forever') {
      btn.classList.add('running');
      btn.textContent = 'Running...';
      pipelineRunning = true;
      return;
    }

    if (!status.running) {
      if (pipelineStatusInterval) {
        clearInterval(pipelineStatusInterval);
        pipelineStatusInterval = null;
      }
      pipelineRunning = false;
      btn.classList.remove('running');

      if (status.status === 'completed') {
        btn.classList.add('completed');
        btn.textContent = '✓ Done';
        setTimeout(() => {
          btn.classList.remove('completed');
          btn.textContent = '▶ Run';
        }, 3000);
      } else if (status.status === 'failed') {
        btn.classList.add('failed');
        btn.textContent = '✗ Failed';
        setTimeout(() => {
          btn.classList.remove('failed');
          btn.textContent = '▶ Run';
        }, 5000);
      } else {
        btn.textContent = '▶ Run';
      }

      refreshAll();
    }
  } catch {
  }
}

function openPreview(gameName) {
  const modal = $('#previewModal');
  const iframe = $('#previewIframe');
  if (!modal || !iframe) return;

  iframe.src = `/games-preview/${gameName}/dist/index.html`;
  modal.classList.add('visible');
}

function closePreview() {
  const modal = $('#previewModal');
  const iframe = $('#previewIframe');
  if (!modal || !iframe) return;

  modal.classList.remove('visible');
  setTimeout(() => { iframe.src = ''; }, 300);
}

let chatTarget = 'ceo';
let chatHistory = [];

async function renderChat() {
  const container = $('#chatMessages');
  if (!container) return;

  try {
    const messages = await fetchJSON(`${API_BASE}/chat/history?limit=100`);
    chatHistory = messages.filter(m => m.agent_name === chatTarget);
    container.innerHTML = '';

    chatHistory.forEach(msg => {
      const isUser = msg.role === 'user';
      const roleClass = msg.agent_name ? msg.agent_name.toLowerCase() : 'system';
      container.innerHTML += `
        <div class="chat-message ${isUser ? 'user' : 'agent'}">
          <span class="chat-message-role ${roleClass}">${isUser ? 'You' : (msg.agent_name || 'Agent')}</span>
          <div class="chat-message-bubble">${escapeHtml(msg.content)}</div>
        </div>
      `;
    });

    container.scrollTop = container.scrollHeight;

    $$('.chat-tab').forEach(tab => {
      tab.addEventListener('click', () => {
        $$('.chat-tab').forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        chatTarget = tab.dataset.agent;
        renderChat();
      });
    });

    const sendBtn = $('#chatSendBtn');
    if (sendBtn) {
      sendBtn.onclick = sendChatMessage;
    }

    const chatInput = $('#chatInput');
    if (chatInput) {
      chatInput.onkeydown = (e) => {
        if (e.key === 'Enter') sendChatMessage();
      };
    }

  } catch (err) {
    container.innerHTML = '<div class="error-state"><div class="error-message">Failed to load chat</div></div>';
  }
}

async function sendChatMessage() {
  const input = $('#chatInput');
  const container = $('#chatMessages');
  if (!input || !container) return;

  const content = input.value.trim();
  if (!content) return;

  const roleClass = chatTarget;
  container.innerHTML += `
    <div class="chat-message user">
      <span class="chat-message-role ${roleClass}">You</span>
      <div class="chat-message-bubble">${escapeHtml(content)}</div>
    </div>
  `;
  container.scrollTop = container.scrollHeight;
  input.value = '';

  try {
    await fetchJSON(`${API_BASE}/chat/send`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content, target_agent: chatTarget }),
    });
    await renderChat();
  } catch (err) {
    container.innerHTML += `
      <div class="chat-message user">
        <span class="chat-message-role ${roleClass}">Error</span>
        <div class="chat-message-bubble" style="color:var(--accent-red)">Failed to send message</div>
      </div>
    `;
  }
}

let lastEventId = 0;
let eventPollInterval = null;

function startEventPolling() {
  if (eventPollInterval) return;
  loadEvents();
  eventPollInterval = setInterval(loadEvents, 5000);
}

async function loadEvents() {
  const container = $('#eventLogContainer');
  if (!container) return;

  try {
    const events = await fetchJSON(`${API_BASE}/events?limit=200`);
    if (!events || events.length === 0) return;

    const maxId = Math.max(...events.map(e => e.id || 0));
    if (maxId > lastEventId) {
      const newEvents = events.filter(e => (e.id || 0) > lastEventId);
      newEvents.forEach(e => appendEventLine(e));
      lastEventId = maxId;
    }
  } catch {}
}

function appendEventLine(event) {
  const container = $('#eventLogContainer');
  if (!container) return;

  const time = event.created_at
    ? new Date(event.created_at).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
    : '--:--:--';
  const line = document.createElement('div');
  line.className = 'event-line';
  line.innerHTML = `
    <span class="event-time">${time}</span>
    <span class="event-type-badge event-type-${event.event_type || 'system'}">${event.event_type || 'system'}</span>
    <span class="event-severity severity-${event.severity || 'info'}">●</span>
    <span class="event-title">${escapeHtml(event.title || '')}</span>
    ${event.detail ? `<span class="event-detail"> — ${escapeHtml(event.detail).slice(0, 120)}</span>` : ''}
  `;
  container.appendChild(line);
  container.scrollTop = container.scrollHeight;
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

async function refreshAll() {
  const btn = $('.refresh-btn');
  if (btn) {
    btn.classList.add('refreshing');
  }

  updateTimestamp();
  await Promise.allSettled([
    renderAgents(),
    renderPipeline(),
    renderMarket(),
    renderProjects(),
    renderMemory(),
    renderChat(),
    loadEvents(),
  ]);

  if (btn) {
    setTimeout(() => btn.classList.remove('refreshing'), 500);
  }
}

function init() {
  $$('.section-header').forEach(header => {
    const section = header.closest('.section');
    if (section) {
      header.addEventListener('click', () => {
        section.classList.toggle('collapsed');
      });
    }
  });

  const refreshBtn = $('#refreshBtn');
  if (refreshBtn) {
    refreshBtn.addEventListener('click', () => {
      refreshAll();
    });
  }

  const runPipelineBtn = $('#runPipelineBtn');
  if (runPipelineBtn) {
    runPipelineBtn.addEventListener('click', triggerPipeline);
  }

  const foreverToggleBtn = $('#foreverToggleBtn');
  if (foreverToggleBtn) {
    foreverToggleBtn.addEventListener('click', toggleForever);
  }

  const previewCloseBtn = $('#previewCloseBtn');
  if (previewCloseBtn) {
    previewCloseBtn.addEventListener('click', closePreview);
  }

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closePreview();
  });

  startEventPolling();
  renderChat();
  loadEvents();

  refreshAll();

  setInterval(() => {
    const btn = $('.refresh-btn');
    if (btn && !btn.classList.contains('refreshing')) {
      btn.classList.add('refresh-pulse');
      setTimeout(() => btn.classList.remove('refresh-pulse'), 2000);
    }
  }, (pipelineRunning ? PIPELINE_FAST_REFRESH : REFRESH_INTERVAL) - 5000);
}

document.addEventListener('DOMContentLoaded', init);