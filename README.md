# GCAgents

**GCAgents — Autonomous AI Game Company**

 researches markets, designs, develops, and publishes web mini-games, with human-in-the-loop approval gates.

---

## Architecture

```
GCAgents System
====================================================================

  CEO Scheduler (tick-based, multi-project)
  ┌──────────────────────────────────────────────────────────────┐
  │  Each tick: check gates → claim tasks (CAS) → execute DAG    │
  │  → verify outputs → update memory → emit events              │
  └───────┬────────────┬────────────┬────────────┬───────────────┘
          │            │            │            │
      ┌───▼───┐   ┌───▼────┐  ┌───▼───┐  ┌──────▼──────┐
      │Project│   │Project│  │Proj C │  │   Market    │
      │   A   │   │   B   │  │ (idle)│  │  Scanner   │
      │(build)│   │(design)│  │       │  │  (12 src)  │
      └───────┘   └────────┘  └────────┘  └─────────────┘

  ┌──────────────────────────────────────────────────────────────┐
  │  Kanban Board (CAS-based task claiming, not FIFO)            │
  │  States: pending → claimed → running → verify → done         │
  └──────────┬───────────────┬────────────────┬──────────────────┘
             │               │                │
        ┌────▼────┐    ┌─────▼────┐    ┌──────▼──────┐
        │  DAG    │    │ Verification│  │ Event Store  │
        │ Planner │    │ Framework   │  │ (append-only)│
        │(waves)  │    │(strict/soft/│  │              │
        └─────────┘    │ advisory)   │  └──────────────┘
                       └─────────────┘

  ┌──────────────┐     ┌────────────────────────────────────────┐
  │  Dashboard   │     │  Model Router (cost-aware selection)   │
  │  FastAPI     │     │  MiniMax-M3 (analysis) · DeepSeek Coder│
  │  :8080       │     │  (code) · ComfyUI/SD (art) · GLM-4-flash│
  └──────────────┘     └────────────────────────────────────────┘
  ┌──────────────┐     ┌────────────────────────────────────────┐
  │   SQLite     │     │  Skills System                         │
  │  (async)     │     │  Pluggable conditionally-activated     │
  │  18 tables   │     │  agent capabilities                    │
  └──────────────┘     └────────────────────────────────────────┘
====================================================================
```

---

## Features

- **Multi-project scheduler** — CEO manages multiple games in parallel, each on its own lifecycle track
- **12 market data sources** — cross-source correlation analysis across itch.io, Reddit, SteamSpy, TikTok, YouTube, Google Play, App Store, X/Twitter, Product Hunt, and more
- **5 human approval gates** — new project, publish, cancel, budget, and direction change require human sign-off
- **3-layer error recovery** — retry with feedback, strategy change, then human escalation
- **Kanban task board** — CAS-based claiming replaces FIFO queue; tasks transition through pending → claimed → running → verify → done
- **DAG execution planner** — wave-based parallel execution with dependency tracking across mechanics
- **Event sourcing** — immutable event log with replay capability; every state change recorded as append-only event
- **Verification framework** — 3-mode verification of every agent output (strict/soft/advisory)
- **Model router** — 6-tier cost-aware AI model selection (strong/fast/cheap/code/art/audio)
- **Context manager** — 4-layer progressive LLM context compression for long-running projects
- **Sandbox execution** — subprocess isolation with resource limits for untrusted code
- **Code graph** — PageRank-ranked dependency analysis for TypeScript projects
- **Agent messaging** — SQLite-backed inter-agent mailbox with guaranteed delivery
- **Skills system** — pluggable, conditionally-activated agent capabilities with dependency resolution
- **Mechanic planning layer** — GDD decomposed into ordered mechanics; per-mechanic code generation with dependency tracking
- **AI art pipeline** — ComfyUI + SD 1.5 with 5 style presets for backgrounds, sprites, and UI icons
- **Automated playtesting** — Playwright 8-point verification against every build
- **Prototype mode** — 5-minute playable demos using colored rectangles and emoji as placeholder art
- **Auto-localization** — game UI strings translated to 15 languages
- **Programmatic music** — Web Audio BGM per genre with optional Suno API integration
- **Executive chat** — CEO-only interaction through decision cards; approve/reject through dashboard
- **Document viewer** — view all agent work artifacts (proposal, GDD, market scan, reports) in-dashboard
- **Scheduler pause/resume** — file-based pause mechanism via dashboard; state preserved across pauses
- **Layered memory** — short-term events + long-term lessons + project context; fully queryable
- **Security** — API key auth, path traversal protection, input validation, CEO action allowlist

---

## Tech Stack

| Layer | Technology | Purpose |
|---|---|---|
| Orchestration | Python 3.11+ async | Multi-project tick scheduler |
| Task Queue | Kanban board (SQLite) | CAS-based task claiming |
| Execution | DAG Planner | Wave-based parallel execution |
| Event Store | SQLite append-only | Immutable event log |
| Analysis AI | MiniMax-M3 / GLM-4-flash | Market analysis, game design |
| Code AI | DeepSeek Coder | Phaser 4 + TypeScript generation |
| Art AI | ComfyUI + SD 1.5 | Game asset generation |
| Verification | Playwright + custom | Multi-mode output verification |
| Game Engine | Phaser 4 + TypeScript + Vite | Web mini-game runtime |
| Dashboard | FastAPI + HTML/CSS/JS | 38+ API endpoints |
| Database | SQLite (async SQLAlchemy) | 18 tables, full company operations |

---

## Quickstart

```bash
# Clone and install
git clone <repo>
cd gcagents
pip install -e ".[dev]"

# Configure API keys
cp .env.example .env  # then edit .env with your keys

# Run the scheduler
python -m orchestrator.main run-scheduler

# In a second terminal, start the dashboard
python -m dashboard.web.api_server

# Open http://localhost:8080
```

---

## CLI Reference

| Command | Description |
|---|---|
| `python -m orchestrator.main run` | Run a single full cycle (scan → design → dev → deploy) |
| `python -m orchestrator.main run-forever` | 24/7 loop with configurable interval |
| `python -m orchestrator.main run-scheduler` | Tick-based multi-project scheduler (recommended) |
| `python -m orchestrator.main run-scheduler --interval 60` | Scheduler with 60s tick interval |
| `python -m orchestrator.main run-prototype "puzzle game"` | Quick prototype in ~5 minutes |
| `python -m orchestrator.main scan` | Market scan only, no project execution |

---

## Configuration

**`.env`** — API keys and credentials:

```
DEEPSEEK_API_KEY=sk-...        # code generation (DeepSeek Coder)
ZHIPU_API_KEY=...              # analysis/design (GLM-4-flash)
MINIMAX_API_KEY=...            # analysis (MiniMax-M3)
BUTLER_API_KEY=...            # itch.io deployment
BUTLER_USERNAME=...           # itch.io username
SUNO_API_KEY=...              # music generation (optional)
```

**`config/agents.yaml`** — Agent-to-model mappings, cost tiers, and routing rules.

**`config/sources.yaml`** — 12 market data source configurations and polling intervals.

---

## Project Structure

```
gcagents/
├── orchestrator/             # Core orchestration
│   ├── main.py               #   CLI entry (run, run-forever, run-scheduler, scan)
│   ├── scheduler.py          #   CEO multi-project tick scheduler
│   ├── kanban.py             #   CAS-based task board (claim/complete/priority)
│   ├── planner.py            #   DAG execution planner (wave-based)
│   ├── topology.py           #   Mechanic dependency resolver
│   ├── event_store.py        #   Append-only event log with replay
│   ├── decision_gate.py      #   5-type human approval gates
│   ├── prototype_mode.py     #   Quick prototype (~5 min, no art)
│   ├── persistence.py        #   DB schema (projects/tasks/decisions/memory)
│   ├── state.py              #   CompanyState, PipelinePhase, retry metadata
│   ├── model_router.py       #   6-tier cost-aware model selection
│   └── graph/
│       └── pipeline.py      #   Legacy 13-node pipeline
├── agents/                   # AI agents
│   ├── research/
│   │   ├── scanner.py        #   12-source market scanner
│   │   ├── analyzer.py       #   Cross-source correlation, scoring
│   │   └── sources/          #   Source adapters (itch, reddit, steamspy, etc.)
│   └── dev/
│       ├── designer/         #   GDD generation + mechanic planning
│       ├── artist/           #   ComfyUI/SD asset pipeline (sprites, bg, icons)
│       ├── programmer/       #   DeepSeek code generation (Phaser 4 + TypeScript)
│       ├── qa/               #   Playwright auto-playtest (8 checks)
│       ├── music/            #   Web Audio BGM + optional Suno API
│       ├── localize/         #   15-language auto-translation
│       └── builder/          #   Vite build → dist/
├── shared/                   # Shared utilities
│   ├── events.py             #   Event schemas and utilities
│   ├── sandbox.py           #   Subprocess isolation with resource limits
│   ├── verification.py       #   3-mode verification framework
│   ├── model_router.py       #   Model routing client
│   ├── context_manager.py    #   4-layer progressive LLM context compression
│   ├── code_graph.py         #   PageRank-ranked dependency analysis
│   ├── agent_messaging.py    #   SQLite-backed inter-agent mailbox
│   ├── skills/               #   Skills system
│   │   ├── base.py          #   Base skill class
│   │   └── code_review.py   #   Code review skill
│   └── tools/               #   Tool integrations
│       ├── art/             #   Art generation tools
│       ├── code_gen/        #   Code generation tools
│       ├── deploy/          #   Deployment tools (Butler)
│       └── file_ops/        #   File operation tools (stubs)
├── dashboard/web/           # Dashboard
│   ├── api_server.py        #   FastAPI backend (38+ endpoints)
│   ├── index.html           #   Project board, task monitor, decision cards
│   ├── app.js               #   Frontend logic
│   └── style.css            #   Styles
├── config/
│   ├── agents.yaml          #   Agent → model mappings
│   └── sources.yaml        #   12 market sources config
├── scripts/
│   ├── e2e_test.py          #   End-to-end test script
│   └── setup_local.py       #   Local environment setup
├── data/
│   ├── gcagents.db          #   SQLite database (18 tables)
│   └── games/              #   Generated game projects
└── tests/                   # Test suite
    ├── test_*.py            #   168 tests across 14 files
    └── conftest.py          #   Pytest configuration
```

---

## Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) — Full technical documentation (architecture, agents, workflows, database schema, API reference)

---

## Development

```bash
# Run tests (168 tests across 14 files)
pytest tests/

# Lint
ruff check .

# Type check
mypy .
```

---

## License

[MIT](LICENSE)