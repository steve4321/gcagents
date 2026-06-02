const API_BASE = '/api';
const REFRESH_INTERVAL = 15000;
const PIPELINE_POLL_INTERVAL = 3000;
const PIPELINE_FAST_REFRESH = 5000;
let pipelineRunning = false;
let pipelineStatusInterval = null;
let foreverActive = false;
let schedulerActive = false;
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

async function renderProjectBoard() {
  const container = $('#projectBoard');
  if (!container) return;

  container.innerHTML = '<div class="project-board-skeleton"></div>';

  try {
    const projects = await fetchJSON(`${API_BASE}/orchestrator/projects`);

    if (!projects || projects.length === 0) {
      container.innerHTML = '';
      showEmpty(container.parentElement, 'No projects yet. Projects will appear as the pipeline creates them.', '<rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/>');
      return;
    }

    const phases = ['backlog', 'scanning', 'designing', 'developing', 'testing', 'building', 'publishing', 'live'];
    const phaseLabels = {
      backlog: 'Backlog', scanning: 'Scanning', designing: 'Design',
      developing: 'Develop', testing: 'Test', building: 'Build',
      publishing: 'Publish', live: 'Live', paused: 'Paused', cancelled: 'Cancelled',
    };

    let html = '<div class="project-board">';
    phases.forEach(phase => {
      const phaseProjects = projects.filter(p => p.phase === phase);
      html += `
        <div class="board-column">
          <div class="board-column-header">
            <span class="board-column-name">${phaseLabels[phase] || phase}</span>
            <span class="board-column-count">${phaseProjects.length}</span>
          </div>
          <div class="board-column-cards">
            ${phaseProjects.length > 0 ? phaseProjects.map(p => `
              <div class="project-card ${p.awaiting_decision ? 'awaiting-decision' : ''}" data-project-id="${p.id}">
                <div class="project-card-header">
                  <span class="project-name">${escapeHtml(p.name || 'Unnamed')}</span>
                </div>
                <div class="project-card-meta">
                  <span class="project-genre-badge">${p.genre || 'General'}</span>
                </div>
                <div class="project-progress">
                  <div class="project-progress-bar" style="width:${p.progress || 0}%"></div>
                </div>
                <div class="project-phase-indicator">${phaseLabels[phase] || phase}</div>
                <div class="project-card-actions">
                  <button class="card-btn card-btn-docs" onclick="openProjectDocs('${p.id}', '${escapeHtml(p.name)}')">📄 文档</button>
                </div>
              </div>
            `).join('') : '<div class="board-column-empty">No projects</div>'}
          </div>
        </div>
      `;
    });
    html += '</div>';
    container.innerHTML = html;

  } catch (err) {
    showError(container, 'Failed to load projects', err.message);
  }
}

async function renderTaskMonitor() {
  const container = $('#taskList');
  if (!container) return;

  container.innerHTML = '<div class="task-list-skeleton"></div>';

  try {
    const tasks = await fetchJSON(`${API_BASE}/orchestrator/tasks`);

    // Filter out system tasks, only show project-specific tasks
    const projectTasks = (tasks || []).filter(t => t.project_id && t.project_id !== '__system__');

    if (!projectTasks || projectTasks.length === 0) {
      container.innerHTML = '';
      showEmpty(container.parentElement, '没有活跃任务。任务会在项目推进时出现。', '<path d="M12 20V10"/><path d="M18 20V4"/><path d="M6 20v-4"/>');
      return;
    }

    let html = '<div class="task-list">';
    projectTasks.forEach(task => {
      const statusClass = getStatusClass(task.status);
      const isRunning = task.status === 'running' || task.status === 'pending';
      html += `
        <div class="task-item" data-task-id="${task.id}">
          <span class="task-status-badge ${statusClass}">${task.status || 'unknown'}</span>
          <div class="task-info">
            <span class="task-name">${escapeHtml(task.project_name || 'Unknown Project')}</span>
            <span class="task-type">${task.task_type || 'task'}</span>
          </div>
          <div class="task-progress">
            <div class="task-progress-bar ${isRunning ? 'running' : ''}" style="width:${task.progress || 0}%"></div>
          </div>
          <span class="task-duration">${task.duration ? fmtDuration(task.duration) : '--'}</span>
        </div>
      `;
    });
    html += '</div>';
    container.innerHTML = html;

  } catch (err) {
    showError(container, 'Failed to load tasks', err.message);
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

    const analysis = reportData?.raw_analysis || '暂无分析数据。市场扫描器运行后会自动填充。';
    let analysisHtml = '';
    try {
      const analysisData = typeof analysis === 'string' ? JSON.parse(analysis) : analysis;
      if (Array.isArray(analysisData)) {
        analysisHtml = analysisData.map(item => `
          <div class="analysis-item">
            <h4>${escapeHtml(item.name || '未命名')}</h4>
            <p><strong>类型:</strong> ${escapeHtml(item.genre || '未知')}</p>
            <p>${escapeHtml(item.description || '')}</p>
            ${item.estimated_dev_hours ? `<p><strong>预估开发时间:</strong> ${item.estimated_dev_hours} 小时</p>` : ''}
            ${item.market_opportunity_score ? `<p><strong>市场机会评分:</strong> ${item.market_opportunity_score}</p>` : ''}
          </div>
        `).join('');
      } else if (typeof analysisData === 'object') {
        analysisHtml = `<pre>${escapeHtml(JSON.stringify(analysisData, null, 2))}</pre>`;
      } else {
        analysisHtml = `<p>${escapeHtml(String(analysisData))}</p>`;
      }
    } catch (e) {
      analysisHtml = `<p>${escapeHtml(analysis)}</p>`;
    }
    const opportunities = (reportData?.opportunities || []).slice(0, 3);
    const signals = (signalsData || []).slice(0, 20);

    const sourceMap = {};
    signals.forEach(s => {
      const src = s.source || 'unknown';
      if (!sourceMap[src]) sourceMap[src] = 0;
      sourceMap[src]++;
    });
    const sourceBadges = Object.entries(sourceMap).map(([src, count]) => {
      const active = count > 0;
      return `<div class="source-badge ${active ? 'active' : 'inactive'}">${escapeHtml(src)} <span class="count">(${count})</span></div>`;
    }).join('');

    const genreTrendMap = {};
    signals.forEach(s => {
      const genre = s.genre || 'unknown';
      if (!genreTrendMap[genre]) {
        genreTrendMap[genre] = { rising: 0, stable: 0, declining: 0, total: 0, sources: new Set() };
      }
      genreTrendMap[genre].total++;
      genreTrendMap[genre].sources.add(s.source);
      if (s.score >= 0.7) genreTrendMap[genre].rising++;
      else if (s.score >= 0.4) genreTrendMap[genre].stable++;
      else genreTrendMap[genre].declining++;
    });

    const getTrendBadge = (genre) => {
      const data = genreTrendMap[genre];
      if (!data || data.total === 0) return '';
      if (data.rising > data.declining) return '<div class="trend-badge rising">↑ Rising</div>';
      if (data.declining > data.rising) return '<div class="trend-badge declining">↓ Declining</div>';
      return '<div class="trend-badge stable">→ Stable</div>';
    };

    const getSourceAgreement = (genre) => {
      const data = genreTrendMap[genre];
      if (!data || data.sources.size < 2) return '';
      return `<div class="source-agreement">${data.sources.size} sources confirm</div>`;
    };

    grid.innerHTML = `
      <div class="market-analysis">
        <div class="market-analysis-header">
          <span class="market-analysis-title">市场分析</span>
          <span class="market-analysis-badge">${reportData?.signals_count || 0} 个信号</span>
        </div>
        <div class="market-analysis-content">${analysisHtml}</div>
      </div>
      <div class="market-sources-section">
        <div class="sources-title">数据源状态</div>
        <div class="market-sources">${sourceBadges || '<div class="source-badge inactive">暂无活跃数据源</div>'}</div>
      </div>
      <div class="opportunities-section">
        <div class="opportunities-title">最佳机会</div>
        ${opportunities.length > 0 ? opportunities.map(opp => `
          <div class="opportunity-card">
            <div class="opportunity-header">
              <span class="opportunity-name">${opp.name || '未命名'}</span>
              <span class="opportunity-score">${(opp.market_opportunity_score || 0).toFixed(1)}</span>
            </div>
            <div class="opportunity-genre">${opp.genre || '综合'}${getTrendBadge(opp.genre || '')}</div>
            <div class="opportunity-description">${opp.description || '暂无描述'}</div>
            <div class="opportunity-meta">
              <span>
                <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>
                ${opp.estimated_dev_hours ? `${opp.estimated_dev_hours}h` : '--'}
              </span>
              <span>
                <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M13 7h4a2 2 0 012 2v4M3 5a2 2 0 012-2h4m0 0v4m0-4L8 13m4-4L3 9"/></svg>
                ${opp.differentiation || 'Standard'}
              </span>
              ${getSourceAgreement(opp.genre || '')}
            </div>
          </div>
        `).join('') : '<div class="empty-state"><div class="empty-message">No opportunities detected yet.</div></div>'}
      </div>
      <div class="signals-section">
        <div class="signals-title">最新信号</div>
        <div class="signals-table-container">
          ${signals.length > 0 ? `
            <table class="signals-table">
              <thead>
                <tr>
                  <th>来源</th>
                  <th>类型</th>
                  <th>标题</th>
                  <th>类型</th>
                  <th>评分</th>
                  <th>时间</th>
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
          ` : '<div class="empty-state"><div class="empty-message">暂无信号数据</div></div>'}
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
      showEmpty(container, 'Company Memory stores lessons learned from completed projects (what worked, what failed, market insights). Memories will appear here after the first project finishes.', '<path d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>');
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

async function toggleScheduler() {
  const btn = $('#startSchedulerBtn');
  const stopBtn = $('#stopSchedulerBtn');
  if (!btn) return;

  if (schedulerActive) {
    btn.disabled = true;
    btn.textContent = '下班中...';
    try {
      await fetchJSON(`${API_BASE}/pipeline/stop`, { method: 'POST' });
    } catch { /* ignore */ }
    schedulerActive = false;
    btn.classList.remove('active');
    btn.textContent = '💼 开始上班';
    btn.disabled = false;
    if (stopBtn) stopBtn.style.display = 'none';
  } else {
    btn.disabled = true;
    btn.textContent = '启动中...';
    try {
      await fetchJSON(`${API_BASE}/pipeline/run-scheduler?interval=60`, { method: 'POST' });
      schedulerActive = true;
      btn.classList.add('active');
      btn.textContent = '💼 运行中';
      if (stopBtn) stopBtn.style.display = 'inline-flex';
    } catch (err) {
      console.error('Failed to start scheduler:', err);
      alert('Failed to start scheduler: ' + err.message);
      btn.textContent = '💼 开始上班';
    } finally {
      btn.disabled = false;
    }
  }
}

async function toggleSchedulerPause() {
  const stopBtn = $('#stopSchedulerBtn');
  if (!stopBtn) return;
  const isPaused = stopBtn.dataset.paused === 'true';
  try {
    if (isPaused) {
      await fetchJSON(`${API_BASE}/scheduler/resume`, { method: 'POST' });
      stopBtn.dataset.paused = 'false';
      stopBtn.textContent = '⏸ 下班';
      stopBtn.title = 'Pause scheduler (CEO stops creating new projects, existing ones continue)';
    } else {
      await fetchJSON(`${API_BASE}/scheduler/pause`, { method: 'POST' });
      stopBtn.dataset.paused = 'true';
      stopBtn.textContent = '▶ 上班';
      stopBtn.title = 'Resume scheduler (CEO will start creating new projects again)';
    }
  } catch (err) {
    console.error('Pause toggle failed:', err);
    alert('Pause toggle failed: ' + err.message);
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

    const schedulerBtn = $('#startSchedulerBtn');
    if (schedulerBtn) {
      schedulerActive = status.scheduler_running;
      if (schedulerActive) {
        schedulerBtn.classList.add('active');
        schedulerBtn.textContent = '🏢 上班中';
      } else {
        schedulerBtn.classList.remove('active');
        schedulerBtn.textContent = '💼 开始上班';
      }
    }

    if (status.mode === 'scheduler') {
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

async function openProjectDocs(projectId, projectName) {
  const modal = $('#docModal');
  const title = $('#docModalTitle');
  const body = $('#docModalBody');
  if (!modal) return;

  title.textContent = `${projectName} — 项目文档`;
  body.innerHTML = '<div class="skeleton" style="height:100px"></div>';
  modal.style.display = 'flex';

  try {
    const docs = await fetchJSON(`${API_BASE}/projects/${projectId}/documents`);
    if (!docs || docs.length === 0) {
      body.innerHTML = '<div class="empty-state">暂无文档</div>';
      return;
    }

    let html = '<div class="doc-list">';
    docs.forEach(doc => {
      if (doc.available) {
        html += `
          <div class="doc-item">
            <div class="doc-header" onclick="this.parentElement.classList.toggle('expanded')">
              <span class="doc-icon">📄</span>
              <span class="doc-title">${escapeHtml(doc.title)}</span>
              <span class="doc-type-badge">${doc.type}</span>
              <span class="doc-toggle">▼</span>
            </div>
            <div class="doc-content">
              ${renderDocContent(doc)}
            </div>
          </div>
        `;
      } else {
        html += `
          <div class="doc-item doc-unavailable">
            <div class="doc-header">
              <span class="doc-icon">⬜</span>
              <span class="doc-title">${escapeHtml(doc.title)}</span>
              <span class="doc-type-badge">${doc.type}</span>
              <span class="doc-status">未生成</span>
            </div>
          </div>
        `;
      }
    });
    html += '</div>';
    body.innerHTML = html;
  } catch (err) {
    body.innerHTML = `<div class="error-state">加载失败: ${err.message}</div>`;
  }
}

function renderDocContent(doc) {
  const content = doc.content;
  if (!content) return '<em>空</em>';

  if (typeof content === 'string') {
    return `<pre>${escapeHtml(content)}</pre>`;
  }

  if (doc.type === 'gdd' && typeof content === 'object') {
    let html = '';
    if (content.title) html += `<h4>${escapeHtml(content.title)}</h4>`;
    if (content.summary) html += `<p>${escapeHtml(content.summary)}</p>`;
    if (content.genre) html += `<p><strong>类型:</strong> ${escapeHtml(content.genre)}</p>`;
    if (content.core_loop) {
      html += '<h5>核心循环</h5><ul>';
      (content.core_loop || []).forEach(item => {
        html += `<li>${escapeHtml(typeof item === 'string' ? item : item.name || JSON.stringify(item))}</li>`;
      });
      html += '</ul>';
    }
    if (content.scenes) {
      html += '<h5>场景</h5><ul>';
      (content.scenes || []).forEach(s => {
        html += `<li><strong>${escapeHtml(s.name || s.title || '')}</strong>: ${escapeHtml(s.description || '')}</li>`;
      });
      html += '</ul>';
    }
    if (content.mechanics) {
      html += '<h5>游戏机制</h5><ul>';
      (content.mechanics || []).forEach(m => {
        html += `<li>${escapeHtml(typeof m === 'string' ? m : m.name || JSON.stringify(m))}</li>`;
      });
      html += '</ul>';
    }
    const shown = new Set(['title','summary','genre','scenes','mechanics','core_loop','name','description']);
    const rest = Object.entries(content).filter(([k]) => !shown.has(k));
    if (rest.length > 0) {
      html += `<pre>${escapeHtml(JSON.stringify(Object.fromEntries(rest), null, 2))}</pre>`;
    }
    return html || `<pre>${escapeHtml(JSON.stringify(content, null, 2))}</pre>`;
  }

  if (doc.type === 'proposal' && typeof content === 'object') {
    let html = '';
    if (content.name) html += `<h4>${escapeHtml(content.name)}</h4>`;
    if (content.description) html += `<p>${escapeHtml(content.description)}</p>`;
    if (content.genre) html += `<p><strong>类型:</strong> ${escapeHtml(content.genre)}</p>`;
    if (content.estimated_dev_hours) html += `<p><strong>预估开发时间:</strong> ${content.estimated_dev_hours} 小时</p>`;
    if (content.market_opportunity_score) html += `<p><strong>市场机会评分:</strong> ${content.market_opportunity_score}</p>`;
    if (content.differentiation) html += `<p><strong>差异化:</strong> ${escapeHtml(content.differentiation)}</p>`;
    if (content.reference_games) html += `<p><strong>参考游戏:</strong> ${content.reference_games.map(g => escapeHtml(g)).join(', ')}</p>`;
    return html || `<pre>${escapeHtml(JSON.stringify(content, null, 2))}</pre>`;
  }

  if (doc.type === 'market_scan' && typeof content === 'object') {
    let html = '';
    if (content.summary) html += `<p>${escapeHtml(content.summary)}</p>`;
    if (content.opportunities) {
      html += '<h5>市场机会</h5><ul>';
      (content.opportunities || []).forEach(opp => {
        html += `<li><strong>${escapeHtml(opp.name || opp.genre || '')}</strong>: ${escapeHtml(opp.description || opp.reason || '')}</li>`;
      });
      html += '</ul>';
    }
    if (content.signals_count) html += `<p><strong>数据源:</strong> ${content.signals_count} 个信号</p>`;
    return html || `<pre>${escapeHtml(JSON.stringify(content, null, 2))}</pre>`;
  }

  if (doc.type === 'art_report' && typeof content === 'object') {
    let html = '';
    if (content.summary) html += `<p>${escapeHtml(content.summary)}</p>`;
    if (content.assets) {
      html += '<h5>生成的资源</h5><ul>';
      (content.assets || []).forEach(a => {
        html += `<li>${escapeHtml(a.name || a.type || '')}: ${escapeHtml(a.description || a.status || '')}</li>`;
      });
      html += '</ul>';
    }
    return html || `<pre>${escapeHtml(JSON.stringify(content, null, 2))}</pre>`;
  }

  return `<pre>${escapeHtml(JSON.stringify(content, null, 2))}</pre>`;
}

function closeDocModal() {
  const modal = $('#docModal');
  if (modal) modal.style.display = 'none';
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
      const metadata = msg.metadata_json || {};
      const msgType = metadata.type;

      if (msgType === 'decision') {
        const decisionId = metadata.decision_id || msg.id;
        const resolved = metadata.resolved || false;
        const resolution = metadata.resolution || '';
        container.innerHTML += `
          <div class="chat-message decision-card agent ${resolved ? 'resolved' : ''}" data-decision-id="${decisionId}">
            <div class="decision-header">
              <span class="decision-icon">🔔</span>
              <span class="decision-type">决策请求</span>
              <span class="decision-agent ${roleClass}">${msg.agent_name || 'Agent'}</span>
            </div>
            <div class="decision-question">${escapeHtml(msg.content)}</div>
            ${metadata.context ? `<div class="decision-context">${metadata.context.map(c => `<div class="decision-context-item">${escapeHtml(c)}</div>`).join('')}</div>` : ''}
            ${!resolved ? `
              <div class="decision-actions">
                <button class="decision-btn approve" onclick="respondDecision('${decisionId}', 'approve')">✓ Approve</button>
                <button class="decision-btn reject" onclick="respondDecision('${decisionId}', 'reject')">✗ Reject</button>
                <button class="decision-btn discuss" onclick="respondDecision('${decisionId}', 'discuss')">💬 Discuss</button>
              </div>
            ` : `<div class="decision-resolution">${resolution}</div>`}
          </div>
        `;
      } else if (msgType === 'report') {
        container.innerHTML += `
          <div class="chat-message report agent">
            <div class="report-header">
              <span class="report-icon">📊</span>
              <span class="report-agent ${roleClass}">${msg.agent_name || 'Agent'}</span>
            </div>
            <div class="chat-message-bubble">${escapeHtml(msg.content)}</div>
          </div>
        `;
      } else if (msgType === 'alert') {
        container.innerHTML += `
          <div class="chat-message alert agent">
            <div class="alert-header">
              <span class="alert-icon">⚠️</span>
              <span class="alert-agent ${roleClass}">${msg.agent_name || 'Agent'}</span>
            </div>
            <div class="chat-message-bubble">${escapeHtml(msg.content)}</div>
          </div>
        `;
      } else {
        container.innerHTML += `
          <div class="chat-message ${isUser ? 'user' : 'agent'}">
            <span class="chat-message-role ${roleClass}">${isUser ? 'You' : (msg.agent_name || 'Agent')}</span>
            <div class="chat-message-bubble">${escapeHtml(msg.content)}</div>
          </div>
        `;
      }
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

async function respondDecision(decisionId, response) {
  const card = document.querySelector(`[data-decision-id="${decisionId}"]`);
  if (!card) return;

  if (response === 'discuss') {
    const input = $('#chatInput');
    if (input) {
      input.value = `Re: decision ${decisionId} — `;
      input.focus();
    }
    return;
  }

  try {
    await fetchJSON(`${API_BASE}/decisions/${decisionId}/respond?response=${response}`, {
      method: 'POST',
    });
    await renderChat();
  } catch (err) {
    console.error('Failed to respond to decision:', err);
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
    renderProjectBoard(),
    renderTaskMonitor(),
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

  const startSchedulerBtn = $('#startSchedulerBtn');
  if (startSchedulerBtn) {
    startSchedulerBtn.addEventListener('click', toggleScheduler);
  }

  const quickPrototypeBtn = $('#quickPrototypeBtn');
  if (quickPrototypeBtn) {
    quickPrototypeBtn.addEventListener('click', openPrototypeModal);
  }

  const stopSchedulerBtn = $('#stopSchedulerBtn');
  if (stopSchedulerBtn) {
    stopSchedulerBtn.addEventListener('click', toggleSchedulerPause);
  }

  const previewCloseBtn = $('#previewCloseBtn');
  if (previewCloseBtn) {
    previewCloseBtn.addEventListener('click', closePreview);
  }

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      closePreview();
      closeDocModal();
    }
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

function openPrototypeModal() {
  const modal = document.getElementById('prototypeModal');
  if (modal) modal.classList.add('visible');
  const input = document.getElementById('prototypeInput');
  if (input) input.focus();
}

function closePrototypeModal() {
  const modal = document.getElementById('prototypeModal');
  if (modal) modal.classList.remove('visible');
}

async function submitPrototype() {
  const input = document.getElementById('prototypeInput');
  const statusEl = document.getElementById('prototypeStatus');
  const btn = document.getElementById('prototypeSubmitBtn');
  if (!input || !statusEl || !btn) return;

  const concept = input.value.trim();
  if (!concept) return;

  btn.disabled = true;
  btn.textContent = 'Generating...';
  statusEl.textContent = 'Creating prototype...';
  statusEl.className = 'prototype-status running';

  try {
    const result = await fetchJSON(`${API_BASE}/orchestrator/prototype`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ concept }),
    });

    statusEl.textContent = `Done in ${result.duration_seconds}s — click to play!`;
    statusEl.className = 'prototype-status success';

    btn.textContent = 'Generate';

    closePrototypeModal();
    openPreview(result.project_name);
    refreshAll();
  } catch (err) {
    statusEl.textContent = 'Failed: ' + (err.message || 'Unknown error');
    statusEl.className = 'prototype-status error';
    btn.textContent = 'Generate';
  }

  btn.disabled = false;
}