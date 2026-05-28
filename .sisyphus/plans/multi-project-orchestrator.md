# Multi-Project Orchestrator + Decision Gates + Enhanced Market Analysis

## Overview

Refactor GCAgents from a single linear pipeline to a multi-project orchestration system
with human decision gates, enhanced market intelligence, and async task execution.

## Current State

- Linear 13-node LangGraph: coo_check → collect_feedback → scan → evaluate → design → art → cfo_check → develop → qa → build → deploy → version → END
- Single CompanyState with one current_proposal, one phase
- CEO evaluates → picks ONE opportunity → runs it to completion
- Chat is one-way: user sends message → CEO reads next cycle → no multi-turn
- Market scanner: 5 fetchers (itch_rss, statkraken, google_play, reddit, app_store)
- 3 sources configured but NOT implemented: itch_api, plugplay, x_trends
- All agent nodes follow `async def(state: CompanyState) -> dict` pattern

## Architecture Target

```
                    ┌─────────────┐
                    │   CEO 大脑   │  ← tick-based scheduler
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
        ┌──────────┐ ┌──────────┐ ┌──────────┐
        │ Project A │ │ Project B │ │ Project C │
        │ 调研中    │ │ 开发中    │ │ 待批准    │
        └──────────┘ └──────────┘ └──────────┘
              │            │            │
              ▼            ▼            ▼
        Task Queue   Task Queue   ⏸ 等待人类决策
```

---

## Feature List (Implementation Order)

### F1: Multi-Project Data Model

**Files to change**: `shared/models.py`, `orchestrator/state.py`, `orchestrator/persistence.py`

**What**:
- Add `ProjectState` model: per-project phase, progress, context, decision gates
- Add `DecisionPoint` model: pending decisions with type, question, options, context
- Add `TaskRecord` model: task queue entries with status, progress, logs
- Add DB tables: `projects`, `decisions`, `tasks`
- Add CRUD persistence functions for all three
- Keep existing `CompanyState` as global state but add `projects: list[str]` (project IDs)
- Keep existing tables (game_projects, etc.) — projects table is the orchestration layer

**Schema**:
```sql
CREATE TABLE projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    genre TEXT,
    phase TEXT NOT NULL DEFAULT 'scanning',
    progress REAL DEFAULT 0.0,
    proposal TEXT,
    gdd TEXT,
    code_path TEXT,
    art_status TEXT DEFAULT 'pending',
    qa_result TEXT,
    itch_url TEXT,
    version TEXT DEFAULT '0.0.0',
    awaiting_decision TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE decisions (
    id TEXT PRIMARY KEY,
    project_id TEXT REFERENCES projects(id),
    decision_type TEXT NOT NULL,
    question TEXT NOT NULL,
    options TEXT NOT NULL,
    context TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    human_response TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    resolved_at TEXT
);

CREATE TABLE tasks (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    task_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    progress REAL DEFAULT 0.0,
    params TEXT,
    result TEXT,
    error TEXT,
    started_at TEXT,
    completed_at TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
```

**Deliverable**: New models + tables + CRUD functions. Existing code still works (no breakage).

---

### F2: Decision Gate System

**Files to change**: `orchestrator/decision_gate.py` (new), `orchestrator/persistence.py`

**What**:
- Define 5 decision types: new_project, publish, cancel, budget_overrun, direction_change
- `create_decision(project_id, type, question, options, context)` → writes to DB + sends chat message
- `resolve_decision(decision_id, response)` → updates DB + notifies CEO
- `get_pending_decisions()` → list all unresolved
- `get_project_decision(project_id)` → get blocking decision for a project

**Decision Flow**:
1. CEO reaches decision point → calls `create_decision()`
2. Decision appears in chat as special message with buttons
3. Human clicks approve/reject/discuss → API call resolves decision
4. CEO next tick reads resolved decision → proceeds or stops

**Deliverable**: Decision gate module + API endpoints + chat integration.

---

### F3: CEO Scheduler (Tick-Based Multi-Project)

**Files to change**: `orchestrator/nodes/ceo.py`, `orchestrator/main.py`, `orchestrator/state.py`

**What**:
- Rewrite CEO from "evaluate → pick one → route" to tick-based multi-project scheduler
- Each tick:
  1. Process human instructions from chat
  2. Check pending decisions — skip projects awaiting human
  3. For each active project, advance one step based on its phase
  4. Market scan periodically → if new opportunity found, create decision for human
  5. Generate proactive reports (project completed, budget update, market change)
- `main.py` tick loop replaces single-cycle `run_single_cycle()`
- Each tick handles one step per project (not the full pipeline)

**Key Decision Gates** (must ask human):
- New project start: "市场扫描发现X，推荐Y，是否启动？"
- Project publish: "项目A测试通过，发布到itch.io？"
- Project cancel: "项目C连续失败，取消？"
- Budget overrun: "项目B预算达80%，继续？"
- Direction change: "市场变化，建议调整方向？"

**Deliverable**: New CEO scheduler + tick loop + decision gate integration.

---

### F4: Task Queue & Async Execution

**Files to change**: `orchestrator/task_queue.py` (new), `orchestrator/main.py`

**What**:
- Task queue backed by SQLite `tasks` table
- `enqueue(project_id, task_type, params)` → creates task
- `dequeue()` → picks next pending task
- `update_progress(task_id, progress)` → updates progress
- `complete(task_id, result)` / `fail(task_id, error)`
- Tick loop: dequeue → execute → update → next
- Long-running tasks (develop, art) report progress periodically
- Tasks are atomic units: scan, design, art_gen, develop, qa, build, deploy

**Worker Pattern**:
```
tick:
  for each project not awaiting_decision:
    next_task = determine_next_task(project)
    if next_task:
      enqueue(next_task)
  
  while task = dequeue():
    execute(task)
    update_project_state(project, task.result)
```

**Deliverable**: Task queue module + worker execution in tick loop.

---

### F5: Enhanced Market Analysis

**Files to change**: `agents/research/sources/fetchers.py`, `agents/research/analyzer.py`, `agents/research/scanner.py`, `config/sources.yaml`

**What**:

**5a. New fetchers** (implement the 3 missing ones + add new sources):
- `fetch_itch_api(config)` — itch.io REST API: search games by tag/genre, get popularity data
- `fetch_plugplay(config)` — plugplay.games API: trending web games
- `fetch_x_trends(config)` — X/Twitter trending topics for gaming keywords
- `fetch_steam_spy(config)` — NEW: SteamSpy API (free, no auth): genre stats, player counts
- `fetch_tiktok_tags(config)` — NEW: TikTok trending game tags via web scraping
- `fetch_youtube_trending(config)` — NEW: YouTube gaming trending (RSS or API)
- `fetch_product_hunt(config)` — NEW: Product Hunt gaming category (RSS)

**5b. Smarter analysis**:
- Cross-source correlation: "genre X trending on Reddit AND itch.io AND TikTok"
- Time-series comparison: compare this week vs last week
- Sentiment scoring: Reddit comments → positive/negative/neutral
- Competition density: how many similar games already exist
- Opportunity scoring formula: `score = trend_strength * (1 - competition) * market_size`

**5c. Periodic scanning**:
- Market scan runs on schedule (e.g., every 6 hours) independent of project pipeline
- Results stored in DB with timestamps
- CEO reads latest scan results when deciding new projects
- Dashboard shows market trends over time

**Deliverable**: 7 new fetchers + enhanced analyzer + periodic scan.

---

### F6: Dashboard — Project Board

**Files to change**: `dashboard/web/index.html`, `dashboard/web/app.js`, `dashboard/web/style.css`, `dashboard/web/api_server.py`

**What**:
- New section: "Project Board" (kanban-style) replacing single pipeline timeline
- Columns: Backlog → Designing → Developing → Testing → Live
- Each card shows: project name, genre, progress bar, phase icon, decision badge
- Click card → expand detail (GDD, tasks, history)
- Decision cards pulse/glow when awaiting human input
- New API endpoints:
  - `GET /api/projects/board` — all projects grouped by phase
  - `GET /api/projects/{id}` — single project detail
  - `POST /api/projects/{id}/pause` — pause project
  - `POST /api/projects/{id}/resume` — resume project
  - `POST /api/projects/{id}/cancel` — cancel project

**Deliverable**: Project board section + 5 new API endpoints.

---

### F7: Dashboard — Task Monitor

**Files to change**: `dashboard/web/index.html`, `dashboard/web/app.js`, `dashboard/web/style.css`, `dashboard/web/api_server.py`

**What**:
- New section: "Task Monitor" showing active/recent tasks
- Task list with: project name, task type, status badge, progress bar, duration
- Auto-refreshes every 5s when tasks are running
- Filter by project, status, type
- New API endpoints:
  - `GET /api/tasks` — all tasks with filters
  - `GET /api/tasks/{id}` — task detail with logs
  - `GET /api/projects/{id}/tasks` — tasks for a project

**Deliverable**: Task monitor section + 3 new API endpoints.

---

### F8: Dashboard — Decision Cards in Chat

**Files to change**: `dashboard/web/app.js`, `dashboard/web/style.css`, `dashboard/web/api_server.py`

**What**:
- Decision messages appear as special cards in Executive Chat
- Card has: agent avatar, question text, context summary, [批准] [拒绝] [讨论] buttons
- Clicking 批准/拒绝 → `POST /api/decisions/{id}/respond`
- Clicking 讨论 → switches to free-text input mode, agent responds with more detail
- Agent proactive messages: project milestone, budget alert, market change
- New API endpoints:
  - `GET /api/decisions` — pending decisions
  - `POST /api/decisions/{id}/respond` — resolve decision
  - `GET /api/reports` — agent proactive reports

**Deliverable**: Decision card UI in chat + report messages + 3 new API endpoints.

---

### F9: Dashboard — Market Trends

**Files to change**: `dashboard/web/app.js`, `dashboard/web/style.css`, `dashboard/web/api_server.py`

**What**:
- Enhance Market Report section with trend charts
- Genre popularity over time (line chart, last 30 days)
- Source comparison table (which sources agree on trends)
- Signal freshness indicators (last scan time per source)
- New API endpoints:
  - `GET /api/market/trends` — genre trends over time
  - `GET /api/market/sources` — source health/status

**Deliverable**: Enhanced market section + 2 new API endpoints.

---

## Implementation Phases

### Phase A: Foundation (F1 + F2)
- Data models, DB tables, persistence functions
- Decision gate system
- No UI changes, no pipeline changes — purely additive
- **Can be merged independently**

### Phase B: Brain (F3 + F4)
- CEO scheduler rewrite
- Task queue + async execution
- New main.py tick loop
- This replaces the old pipeline — **breaking change, needs feature flag**

### Phase C: Intelligence (F5)
- New market fetchers
- Enhanced analyzer
- Independent of Phase A/B — **can run in parallel**

### Phase D: Dashboard (F6 + F7 + F8 + F9)
- Project board, task monitor, decision cards, market trends
- Depends on Phase A APIs being available
- **F6 + F7 can run in parallel, then F8 + F9**

---

## Dependency Graph

```
F1 (models) ──── F2 (decisions) ──── F3 (CEO scheduler)
     │                                    │
     └──── F4 (task queue) ───────────────┘
                  │
     F5 (market) ─┤ (independent, parallel)
                  │
                  ▼
     F6 (project board) ── F7 (task monitor)
     F8 (decision chat)  ── F9 (market trends)
```

## Estimated Effort

| Feature | Files Changed | Effort |
|---------|--------------|--------|
| F1: Data models | 3 files, ~200 LOC | Medium |
| F2: Decision gates | 2 files, ~150 LOC | Medium |
| F3: CEO scheduler | 3 files, ~300 LOC | Large |
| F4: Task queue | 2 files, ~200 LOC | Medium |
| F5: Market analysis | 4 files, ~500 LOC | Large |
| F6: Project board | 4 files, ~400 LOC | Medium |
| F7: Task monitor | 4 files, ~300 LOC | Medium |
| F8: Decision chat | 3 files, ~250 LOC | Medium |
| F9: Market trends | 3 files, ~200 LOC | Medium |
| **Total** | **~20 files, ~2500 LOC** | **~2-3 days** |

## Constraints
- Games target overseas markets only (no Chinese platforms)
- Games are standalone Web mini-games, zero server dependency
- AI models: analysis/design use free glm-4-flash, code generation uses deepseek-coder
- Dashboard is vanilla HTML + CSS + JS (no frameworks)
- SQLite database (no Docker)
- Itch.io as primary distribution platform
- Important decisions MUST require human approval via decision gates
- All agent nodes keep `async def(state) -> dict` pattern where possible
