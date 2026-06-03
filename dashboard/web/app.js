const API_BASE = '/api';
const REFRESH_INTERVAL = 15000;
const PIPELINE_POLL_INTERVAL = 3000;
const PIPELINE_FAST_REFRESH = 5000;
let pipelineRunning = false;
let pipelineStatusInterval = null;
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
      const projectName = log.project_name || '';
      const error = log.error || '';

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
          ${projectName ? `<div class="agent-project">${escapeHtml(projectName)}</div>` : ''}
          ${error ? `<div class="agent-error" title="${escapeHtml(error)}">⚠ ${escapeHtml(error).slice(0, 40)}${error.length > 40 ? '...' : ''}</div>` : ''}
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

async function renderPerformance() {
  const summaryEl = $('#performanceSummary');
  const tableEl = $('#performanceTable');
  const feedbackEl = $('#feedbackList');
  if (!summaryEl || !tableEl) return;

  let itchData = { stats: [] };
  let inAppData = { projects: [] };
  try {
    [itchData, inAppData] = await Promise.all([
      fetchJSON(`${API_BASE}/itch/stats`),
      fetchJSON(`${API_BASE}/analytics/summary`),
    ]);
  } catch {
    summaryEl.innerHTML = '<div class="analytics-empty">Failed to load performance data.</div>';
    return;
  }

  const itchStats = itchData.stats || [];
  const inAppProjects = inAppData.projects || [];

  const totalDownloads = itchStats.reduce((s, g) => s + (g.downloads_count || 0), 0);
  const totalViews = itchStats.reduce((s, g) => s + (g.views_count || 0), 0);
  const totalPlays = inAppProjects.reduce((s, p) => s + ((p.metrics && p.metrics.play_count && p.metrics.play_count.value) || 0), 0);

  summaryEl.innerHTML = `
    <div class="analytics-card">
      <div class="analytics-card-value">${totalDownloads.toLocaleString()}</div>
      <div class="analytics-card-label">itch.io Downloads</div>
      <div class="analytics-card-sub">across ${itchStats.length} published</div>
    </div>
    <div class="analytics-card">
      <div class="analytics-card-value">${totalViews.toLocaleString()}</div>
      <div class="analytics-card-label">itch.io Views</div>
      <div class="analytics-card-sub">page impressions</div>
    </div>
    <div class="analytics-card">
      <div class="analytics-card-value">${totalPlays.toLocaleString()}</div>
      <div class="analytics-card-label">In-App Plays</div>
      <div class="analytics-card-sub">from dashboard preview</div>
    </div>
  `;

  if (itchStats.length === 0) {
    tableEl.innerHTML = '<div class="performance-empty">No itch.io stats yet. Click refresh below to fetch.</div>';
  } else {
    tableEl.innerHTML = `
      <table class="performance-data-table">
        <thead>
          <tr>
            <th>Game</th>
            <th>itch.io</th>
            <th>Downloads</th>
            <th>Views</th>
            <th>Purchases</th>
            <th>Updated</th>
          </tr>
        </thead>
        <tbody>
          ${itchStats.map(g => `
            <tr>
              <td>${escapeHtml(g.title)}</td>
              <td>${g.itch_url ? `<a href="${g.itch_url}" target="_blank" rel="noopener">open ↗</a>` : '-'}</td>
              <td>${(g.downloads_count || 0).toLocaleString()}</td>
              <td>${(g.views_count || 0).toLocaleString()}</td>
              <td>${(g.purchases_count || 0).toLocaleString()}</td>
              <td>${g.fetched_at ? g.fetched_at.replace('T', ' ').slice(0, 16) : '-'}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
      <div class="performance-actions">
        <button id="refreshItchBtn" class="refresh-itch-btn">↻ Refresh from itch.io</button>
      </div>
    `;
    const btn = $('#refreshItchBtn');
    if (btn) {
      btn.addEventListener('click', async () => {
        btn.disabled = true;
        btn.textContent = 'Refreshing...';
        try {
          await fetchJSON(`${API_BASE}/itch/refresh`, { method: 'POST' });
          await renderPerformance();
        } catch (err) {
          alert('Failed: ' + (err.message || 'Unknown error'));
          btn.disabled = false;
          btn.textContent = '↻ Refresh from itch.io';
        }
      });
    }
  }

  if (feedbackEl) {
    try {
      let feedback = [];
      for (const p of inAppProjects) {
        const fb = await fetchJSON(`${API_BASE}/feedback/${p.id}`);
        if (fb && fb.length > 0) {
          feedback = feedback.concat(fb.map(f => ({ ...f, project_name: p.name })));
        }
      }
      if (feedback.length === 0) {
        feedbackEl.innerHTML = '<div class="feedback-empty">No feedback yet.</div>';
      } else {
        feedback.sort((a, b) => new Date(b.posted_at || b.created_at) - new Date(a.posted_at || a.created_at));
        feedbackEl.innerHTML = feedback.map(f => {
          const cat = f.category || 'other';
          return `
            <div class="feedback-item">
              <div class="feedback-item-header">
                <span class="feedback-author">${escapeHtml(f.author || 'Anonymous')}</span>
                <span class="feedback-project">${escapeHtml(f.project_name || '')}</span>
                <span class="feedback-category">${cat}</span>
              </div>
              <div class="feedback-text">${escapeHtml(f.text || '')}</div>
            </div>
          `;
        }).join('');
      }
    } catch {
      feedbackEl.innerHTML = '<div class="feedback-empty">Failed to load feedback.</div>';
    }
  }
}

async function renderFinance() {
  const summaryContainer = $('#financeSummary');
  const breakdownContainer = $('#financeBreakdown');
  if (!summaryContainer || !breakdownContainer) return;

  summaryContainer.innerHTML = '<div class="finance-card skeleton" style="height:80px"></div>'.repeat(4);

  try {
    const data = await fetchJSON(`${API_BASE}/finance/summary?days=30`);
    const usage = data.usage || {};
    const budgets = data.budgets || [];

    const totalCost = usage.total_cost || 0;
    const totalTokens = usage.total_tokens || 0;
    const byModel = usage.by_model || {};
    const dailyTrend = usage.daily_trend || [];

    const modelNames = Object.keys(byModel);
    const topModel = modelNames.length > 0
      ? modelNames.reduce((a, b) => (byModel[a].cost > byModel[b].cost ? a : b))
      : null;

    const monthlyBudget = budgets.find(b => b.category === 'monthly');
    const budgetLimit = monthlyBudget ? monthlyBudget.budget_limit_usd : 0;
    const budgetSpent = monthlyBudget ? monthlyBudget.spent_usd : totalCost;
    const budgetPct = budgetLimit > 0 ? Math.round((budgetSpent / budgetLimit) * 100) : 0;

    summaryContainer.innerHTML = `
      <div class="finance-card">
        <div class="finance-card-value">$${totalCost.toFixed(2)}</div>
        <div class="finance-card-label">Total Cost (30d)</div>
      </div>
      <div class="finance-card">
        <div class="finance-card-value">${(totalTokens / 1000).toFixed(1)}K</div>
        <div class="finance-card-label">Total Tokens</div>
      </div>
      <div class="finance-card">
        <div class="finance-card-value">${topModel || '--'}</div>
        <div class="finance-card-label">Top Model</div>
        <div class="finance-card-sub">$${topModel ? byModel[topModel].cost.toFixed(3) : '0'}</div>
      </div>
      <div class="finance-card">
        <div class="finance-card-value">${budgetLimit > 0 ? budgetPct + '%' : '--'}</div>
        <div class="finance-card-label">Budget Used</div>
        ${budgetLimit > 0 ? `<div class="finance-card-sub">$${budgetSpent.toFixed(2)} / $${budgetLimit}</div>` : ''}
      </div>
    `;

    if (totalCost > 0) {
      let chartHtml = '<div class="finance-chart">';

      const byAgent = usage.by_agent || {};
      const agentEntries = Object.entries(byAgent)
        .sort((a, b) => b[1].cost - a[1].cost)
        .slice(0, 6);
      if (agentEntries.length > 0) {
        chartHtml += '<div class="finance-chart-section">';
        chartHtml += '<div class="finance-chart-title">By Agent</div>';
        agentEntries.forEach(([name, data]) => {
          const pct = ((data.cost / totalCost) * 100).toFixed(1);
          chartHtml += `
            <div class="finance-bar-row">
              <div class="finance-bar-label">${escapeHtml(name)}</div>
              <div class="finance-bar-track">
                <div class="finance-bar-fill" style="width:${pct}%"></div>
              </div>
              <div class="finance-bar-value">$${data.cost.toFixed(3)} · ${pct}%</div>
            </div>
          `;
        });
        chartHtml += '</div>';
      }

      const modelEntries = Object.entries(byModel)
        .sort((a, b) => b[1].cost - a[1].cost);
      if (modelEntries.length > 0) {
        chartHtml += '<div class="finance-chart-section">';
        chartHtml += '<div class="finance-chart-title">By Model</div>';
        modelEntries.forEach(([name, data]) => {
          const pct = ((data.cost / totalCost) * 100).toFixed(1);
          chartHtml += `
            <div class="finance-bar-row">
              <div class="finance-bar-label">${escapeHtml(name)}</div>
              <div class="finance-bar-track">
                <div class="finance-bar-fill" style="width:${pct}%"></div>
              </div>
              <div class="finance-bar-value">$${data.cost.toFixed(3)} · ${pct}%</div>
            </div>
          `;
        });
        chartHtml += '</div>';
      }

      chartHtml += '</div>';
      breakdownContainer.innerHTML = chartHtml;
    } else {
      breakdownContainer.innerHTML = '<div class="finance-empty">No cost data yet.</div>';
    }

  } catch (err) {
    summaryContainer.innerHTML = '<div class="finance-empty">Failed to load finance data.</div>';
    breakdownContainer.innerHTML = '';
  }
}

let allDecisionHistory = [];


async function loadDecisionHistory() {
  const container = $('#decisionHistoryList');
  if (!container) return;

  container.innerHTML = '<div class="decision-history-empty">Loading decisions...</div>';

  try {
    allDecisionHistory = await fetchJSON(`${API_BASE}/decisions/history`);
    renderDecisionHistoryList();
  } catch (err) {
    container.innerHTML = '<div class="decision-history-empty">Failed to load decision history.</div>';
  }
}

function renderDecisionHistoryList() {
  const container = $('#decisionHistoryList');
  if (!container) return;

  const typeFilter = $('#decisionTypeFilter')?.value || '';
  const statusFilter = $('#decisionStatusFilter')?.value || '';

  let filtered = allDecisionHistory;
  if (typeFilter) filtered = filtered.filter(d => d.decision_type === typeFilter);
  if (statusFilter) filtered = filtered.filter(d => d.status === statusFilter);

  if (filtered.length === 0) {
    container.innerHTML = '<div class="decision-history-empty">No matching decisions.</div>';
    return;
  }

  const typeLabels = {
    new_project: 'New Project',
    publish: 'Publish',
    cancel: 'Cancel',
    budget_overrun: 'Budget Overrun',
    direction_change: 'Direction Change',
  };

  const typeColors = {
    new_project: 'var(--accent-cyan)',
    publish: 'var(--accent-green)',
    cancel: 'var(--accent-red)',
    budget_overrun: 'var(--accent-amber)',
    direction_change: 'var(--accent-purple)',
  };

  let html = '';
  filtered.forEach(d => {
    const type = d.decision_type || 'unknown';
    const typeLabel = typeLabels[type] || type;
    const typeColor = typeColors[type] || 'var(--text-muted)';
    const statusClass = d.status === 'approved' ? 'status-approved' : 'status-rejected';

    html += `
      <div class="decision-history-item ${statusClass}">
        <div class="decision-history-header">
          <span class="decision-history-type" style="color:${typeColor}">${typeLabel}</span>
          <span class="decision-history-status ${statusClass}">${d.status}</span>
        </div>
        <div class="decision-history-question">${escapeHtml(d.question || '')}</div>
        ${d.human_response ? `<div class="decision-history-response">Response: ${escapeHtml(d.human_response)}</div>` : ''}
        <div class="decision-history-meta">
          <span>${fmtRelativeTime(d.resolved_at)}</span>
          ${d.project_id ? `<span>Project #${d.project_id}</span>` : ''}
        </div>
      </div>
    `;
  });

  container.innerHTML = html;
}

function _renderQaBadge(qaResult, projectId) {
  if (!qaResult || typeof qaResult !== 'object') return '';
  const failCount = qaResult.fail_count || 0;
  const passed = qaResult.passed;
  if (passed === true) {
    return '<div class="qa-badge qa-passed">QA ✓ PASS</div>';
  }
  if (passed === false) {
    const scoreStr = qaResult.checks?.playtest?.score !== undefined
      ? ` (${(qaResult.checks.playtest.score * 100).toFixed(0)}%)` : '';
    return `<div class="qa-badge qa-failed" data-qa-project="${escapeHtml(projectId || '')}">QA ✗ FAIL${scoreStr}${failCount > 0 ? ` ×${failCount}` : ''}</div>`;
  }
  if (failCount > 0 && passed === null) {
    return `<div class="qa-badge qa-failed" data-qa-project="${escapeHtml(projectId || '')}">QA ✗ ×${failCount}</div>`;
  }
  return '';
}

function _renderQaDetail(qaResult) {
  if (!qaResult) return '';
  const lines = [];
  if (qaResult.errors) lines.push(`<div>❌ ${escapeHtml(qaResult.errors)}</div>`);
  if (qaResult.warnings) lines.push(`<div>⚠ ${escapeHtml(qaResult.warnings)}</div>`);
  if (qaResult.passed) lines.push(`<div>✅ ${escapeHtml(qaResult.passed)}</div>`);

  const checks = qaResult.checks || {};
  const playtest = checks.playtest;
  if (playtest) {
    lines.push('<div class="qa-section"><div class="qa-section-title">Playtest</div>');
    if (playtest.score !== undefined) lines.push(`<div class="qa-score">Score: ${(playtest.score * 100).toFixed(0)}%</div>`);
    if (playtest.duration_ms) lines.push(`<div class="qa-meta">Duration: ${playtest.duration_ms}ms</div>`);
    if (playtest.checks) {
      playtest.checks.forEach(c => {
        const icon = c.passed ? '✓' : '✗';
        const cls = c.passed ? 'qa-check-pass' : 'qa-check-fail';
        lines.push(`<div class="qa-check ${cls}">${icon} ${escapeHtml(c.name)}${c.detail ? ': ' + escapeHtml(c.detail) : ''}</div>`);
      });
    }
    lines.push('</div>');
  }

  const structOk = checks.project_structure;
  const buildOk = checks.build_artifacts;
  if (structOk !== undefined || buildOk !== undefined) {
    lines.push('<div class="qa-section"><div class="qa-section-title">Checks</div>');
    if (structOk !== undefined) lines.push(`<div class="qa-check ${structOk ? 'qa-check-pass' : 'qa-check-fail'}">${structOk ? '✓' : '✗'} Project Structure</div>`);
    if (buildOk !== undefined) lines.push(`<div class="qa-check ${buildOk ? 'qa-check-pass' : 'qa-check-fail'}">${buildOk ? '✓' : '✗'} Build Artifacts</div>`);
    lines.push('</div>');
  }

  return lines.length ? `<div class="qa-detail-panel">${lines.join('')}</div>` : '';
}

function toggleProjectCard(projectId) {
  const card = document.querySelector(`.project-card[data-project-id="${projectId}"]`);
  if (!card) return;
  card.classList.toggle('collapsed');
  const toggle = card.querySelector('.project-card-toggle');
  if (toggle) {
    toggle.textContent = card.classList.contains('collapsed') ? '▸' : '▾';
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
              <div class="project-card collapsed ${p.awaiting_decision ? 'awaiting-decision' : ''}" data-project-id="${p.id}">
                <div class="project-card-header" onclick="toggleProjectCard('${p.id}')">
                  <span class="project-name">${escapeHtml(p.name || 'Unnamed')}</span>
                  <span class="project-card-toggle">▸</span>
                </div>
                <div class="project-card-meta">
                  <span class="project-genre-badge">${p.genre || 'General'}</span>
                </div>
                <div class="project-progress">
                  <div class="project-progress-bar" style="width:${p.progress || 0}%"></div>
                </div>
                <div class="project-phase-indicator">${phaseLabels[phase] || phase}</div>
                ${_renderQaBadge(p.qa_result, p.id)}
                ${_renderQaDetail(p.qa_result)}
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

    const seen = new Map();
    const uniqueTasks = [];
    for (const t of projectTasks) {
      const key = `${t.project_id}:${t.task_type}`;
      const existing = seen.get(key);
      if (!existing || new Date(t.created_at) > new Date(existing.created_at)) {
        if (existing) {
          const idx = uniqueTasks.indexOf(existing);
          if (idx !== -1) uniqueTasks.splice(idx, 1);
        }
        seen.set(key, t);
        uniqueTasks.push(t);
      }
    }

    if (!uniqueTasks || uniqueTasks.length === 0) {
      container.innerHTML = '';
      showEmpty(container.parentElement, '没有活跃任务。任务会在项目推进时出现。', '<path d="M12 20V10"/><path d="M18 20V4"/><path d="M6 20v-4"/>');
      return;
    }

    let html = '<div class="task-list">';
    uniqueTasks.forEach(task => {
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

    const opportunities = (reportData?.opportunities || []).slice(0, 3);
    const signals = (signalsData || []).slice(0, 20);
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

function _renderGameCard(p, di, isLive) {
  const phaseLabel = isLive ? 'live' : (p.phase || 'unknown');
  return `
    <div class="game-card ${isLive ? 'game-card-live' : 'game-card-built'}" data-game-name="${escapeHtml(p.name || '')}">
      <div class="game-header">
        <div class="game-info">
          <div class="game-name">${escapeHtml(p.name || 'Unnamed Game')}</div>
          <div class="game-genre">${escapeHtml(p.genre || 'General')}</div>
        </div>
        <span class="game-status-tag ${isLive ? 'status-live' : 'status-built'}">${isLive ? 'Live' : phaseLabel}</span>
      </div>
      <div class="game-build-info">
        <div class="build-stat">
          <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M13 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V9z"/><polyline points="13 2 13 9 20 9"/></svg>
          <span class="build-stat-value">${di.files}</span>
          <span class="build-stat-label">files</span>
        </div>
        <div class="build-stat">
          <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
          <span class="build-stat-value">${fmtFileSize(di.size)}</span>
          <span class="build-stat-label">size</span>
        </div>
      </div>
      ${_renderQaBadge(p.qa_result, p.id)}
      ${_renderQaDetail(p.qa_result)}<div class="game-footer">
        <div class="game-footer-left">
          <button class="play-btn" data-play-dir="${escapeHtml((p.code_path || '').split('/').pop())}" data-play="${escapeHtml(p.name || '')}" title="Preview Game">▶</button>
        </div>
        ${p.itch_url ? `
          <a href="${p.itch_url}" class="game-url" target="_blank" rel="noopener">
            <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
            itch.io
          </a>
        ` : ''}
      </div>
    </div>
  `;
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

    const gamesOnDisk = statusData.games || [];
    const projects = projectsData || [];
    const diskMap = {};
    gamesOnDisk.forEach(g => { diskMap[g.name] = g; });

    const diskInfo = (p) => {
      const dirName = (p.code_path || '').split('/').pop();
      const d = diskMap[dirName] || {};
      return { files: d.file_count || 0, size: d.dist_size || 0 };
    };

    const liveProjects = projects.filter(p => p.phase === 'live');
    const builtProjects = projects.filter(p =>
      p.phase !== 'live' && p.code_path && p.phase !== 'developing' && p.phase !== 'designing' && p.phase !== 'cancelled'
    );

    if (liveProjects.length === 0 && builtProjects.length === 0) {
      showEmpty(container, 'No game projects yet. They will appear as the pipeline creates them.');
      return;
    }

    let html = '';

    if (liveProjects.length > 0) {
      html += '<div class="games-section-label"><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/></svg> Live on itch.io</div>';
      html += '<div class="games-grid">';
      liveProjects.forEach(p => {
        const di = diskInfo(p);
        html += _renderGameCard(p, di, true);
      });
      html += '</div>';
    }

    if (builtProjects.length > 0) {
      html += '<div class="games-section-label"><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14.7 6.3a1 1 0 000 1.4l1.6 1.6a1 1 0 001.4 0l3.77-3.77a6 6 0 01-7.94 7.94l-6.91 6.91a2.12 2.12 0 01-3-3l6.91-6.91a6 6 0 017.94-7.94l-3.76 3.76z"/></svg> Built (not published)</div>';
      html += '<div class="games-grid">';
      builtProjects.forEach(p => {
        const di = diskInfo(p);
        html += _renderGameCard(p, di, false);
      });
      html += '</div>';
    }

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
        const dir = btn.dataset.playDir;
        const gameName = btn.dataset.play;
        if (dir) openPreview(dir, gameName);
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

async function toggleScheduler() {
  const btn = $('#schedulerToggleBtn');
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
  } else {
    btn.disabled = true;
    btn.textContent = '启动中...';
    try {
      await fetchJSON(`${API_BASE}/pipeline/run-scheduler?interval=60`, { method: 'POST' });
      schedulerActive = true;
      btn.classList.add('active');
      btn.textContent = '🏢 上班中';
    } catch (err) {
      console.error('Failed to start scheduler:', err);
      alert('Failed to start scheduler: ' + err.message);
      btn.textContent = '💼 开始上班';
    } finally {
      btn.disabled = false;
    }
  }
}

async function checkPipelineStatus() {
  try {
    const status = await fetchJSON(`${API_BASE}/pipeline/status`);

    const schedulerBtn = $('#schedulerToggleBtn');
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

    pipelineRunning = status.running;
    updateChatInputState();
  } catch {
  }
}

function updateChatInputState() {
  const input = $('#chatInput');
  const btn = $('#chatSendBtn');
  const area = document.querySelector('.chat-input-area');
  if (!input || !btn) return;

  if (schedulerActive) {
    input.disabled = false;
    input.placeholder = 'Send a message...';
    btn.disabled = false;
    if (area) area.classList.remove('chat-input-disabled');
  } else {
    input.disabled = true;
    input.placeholder = 'Start work to chat with CEO';
    btn.disabled = true;
    if (area) area.classList.add('chat-input-disabled');
  }
}

function openPreview(dirName, gameName) {
  const modal = $('#previewModal');
  const iframe = $('#previewIframe');
  if (!modal || !iframe) return;

  iframe.src = `/games-preview/${encodeURIComponent(dirName)}/dist/index.html`;
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
  if (!schedulerActive) {
    return;
  }
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
    renderPerformance(),
    renderFinance(),
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

  const schedulerToggleBtn = $('#schedulerToggleBtn');
  if (schedulerToggleBtn) {
    schedulerToggleBtn.addEventListener('click', toggleScheduler);
  }

  const previewCloseBtn = $('#previewCloseBtn');
  if (previewCloseBtn) {
    previewCloseBtn.addEventListener('click', closePreview);
  }

  const decisionTypeFilter = $('#decisionTypeFilter');
  if (decisionTypeFilter) {
    decisionTypeFilter.onchange = () => renderDecisionHistoryList();
  }

  const decisionStatusFilter = $('#decisionStatusFilter');
  if (decisionStatusFilter) {
    decisionStatusFilter.onchange = () => renderDecisionHistoryList();
  }

  loadDecisionHistory();

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      closePreview();
      closeDocModal();
    }
  });

  startEventPolling();
  renderChat();
  loadEvents();

  checkPipelineStatus();
  pipelineStatusInterval = setInterval(checkPipelineStatus, PIPELINE_POLL_INTERVAL);

  refreshAll();
  setInterval(refreshAll, REFRESH_INTERVAL);

  setInterval(() => {
    const btn = $('.refresh-btn');
    if (btn && !btn.classList.contains('refreshing')) {
      btn.classList.add('refresh-pulse');
      setTimeout(() => btn.classList.remove('refresh-pulse'), 2000);
    }
  }, (pipelineRunning ? PIPELINE_FAST_REFRESH : REFRESH_INTERVAL) - 5000);
}

document.addEventListener('DOMContentLoaded', init);

let lastKnownPendingDecisions = 0;

async function loadPolicy() {
  try {
    const policy = await fetchJSON(`${API_BASE}/policy`);
    const budget = document.getElementById('policyBudget');
    const genres = document.getElementById('policyGenres');
    const autoPublish = document.getElementById('policyAutoPublish');
    const autoCancel = document.getElementById('policyAutoCancel');
    const requireApproval = document.getElementById('policyRequireApproval');
    const workStart = document.getElementById('policyWorkStart');
    const workEnd = document.getElementById('policyWorkEnd');
    const devProjects = document.getElementById('policyDevProjects');
    const liveProjects = document.getElementById('policyLiveProjects');
    const timeout = document.getElementById('policyTimeout');
    const timeoutAction = document.getElementById('policyTimeoutAction');

    if (budget) budget.value = policy.budget_limit_usd || 5;
    if (genres) genres.value = (policy.preferred_genres || []).join(', ');
    if (autoPublish) autoPublish.checked = policy.auto_publish !== false;
    if (autoCancel) autoCancel.checked = policy.auto_cancel !== false;
    if (requireApproval) requireApproval.checked = policy.require_new_project_approval !== false;
    if (workStart) workStart.value = policy.working_hours_start || 9;
    if (workEnd) workEnd.value = policy.working_hours_end || 23;
    if (devProjects) devProjects.value = policy.max_dev_projects || 3;
    if (liveProjects) liveProjects.value = policy.max_live_projects || 5;
    if (timeout) timeout.value = policy.decision_timeout_hours || 24;
    if (timeoutAction) timeoutAction.value = policy.timeout_action || 'reject';
  } catch (err) {
    console.error('Failed to load policy:', err);
  }
}

async function savePolicy() {
  const btn = document.getElementById('policySaveBtn');
  const status = document.getElementById('policyStatus');
  if (!btn || !status) return;

  const genresRaw = document.getElementById('policyGenres')?.value || '';
  const genres = genresRaw.split(',').map(g => g.trim()).filter(g => g);

  const policy = {
    budget_limit_usd: parseFloat(document.getElementById('policyBudget')?.value) || 5,
    preferred_genres: genres,
    auto_publish: document.getElementById('policyAutoPublish')?.checked ?? true,
    auto_cancel: document.getElementById('policyAutoCancel')?.checked ?? true,
    require_new_project_approval: document.getElementById('policyRequireApproval')?.checked ?? true,
    working_hours_start: parseInt(document.getElementById('policyWorkStart')?.value) || 9,
    working_hours_end: parseInt(document.getElementById('policyWorkEnd')?.value) || 23,
    max_dev_projects: parseInt(document.getElementById('policyDevProjects')?.value) || 3,
    max_live_projects: parseInt(document.getElementById('policyLiveProjects')?.value) || 5,
    decision_timeout_hours: parseInt(document.getElementById('policyTimeout')?.value) || 24,
    timeout_action: document.getElementById('policyTimeoutAction')?.value || 'reject',
  };

  btn.disabled = true;
  btn.textContent = 'Saving...';

  try {
    await fetchJSON(`${API_BASE}/policy`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(policy),
    });
    status.textContent = '✓ Saved';
    status.className = 'policy-status success';
    setTimeout(() => { status.textContent = ''; status.className = 'policy-status'; }, 2000);
  } catch (err) {
    status.textContent = '✗ Failed: ' + err.message;
    status.className = 'policy-status error';
  }

  btn.disabled = false;
  btn.textContent = 'Save Policy';
}

function requestNotificationPermission() {
  if ('Notification' in window && Notification.permission === 'default') {
    Notification.requestPermission();
  }
}

function checkAndNotifyDecisions(pendingCount) {
  if (pendingCount > lastKnownPendingDecisions && pendingCount > 0) {
    if ('Notification' in window && Notification.permission === 'granted') {
      new Notification('GCAgents', {
        body: `${pendingCount} 个待决策 — 点击 Dashboard 查看`,
        icon: '/favicon.ico',
      });
    }
  }
  lastKnownPendingDecisions = pendingCount;
}

async function checkPendingDecisions() {
  try {
    const decisions = await fetchJSON(`${API_BASE}/decisions`);
    const pending = Array.isArray(decisions) ? decisions.length : 0;
    checkAndNotifyDecisions(pending);
    updatePendingBanner(pending);
  } catch {}
}

function updatePendingBanner(count) {
  const banner = $('#pendingBanner');
  if (!banner) return;
  if (count > 0) {
    const textEl = banner.querySelector('.pending-banner-text');
    if (textEl) {
      textEl.textContent = `You have ${count} pending decision${count > 1 ? 's' : ''} waiting — go to Executive Chat to respond`;
    }
    banner.style.display = 'flex';
  } else {
    banner.style.display = 'none';
  }
}

function scrollToChat() {
  const chat = $('#chatSection');
  if (!chat) return;
  const header = chat.querySelector('.section-header');
  if (chat.classList.contains('collapsed') && header) {
    header.click();
  }
  setTimeout(() => {
    chat.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, 50);
}

const originalInit = init;
init = function() {
  originalInit();
  requestNotificationPermission();
  loadPolicy();
  setInterval(checkPendingDecisions, 30000);
};