# GCAgents

Autonomous AI game company — researches markets, designs, develops, and publishes web mini-games, with human-in-the-loop approval gates.

---

## Architecture

```
GCAgents System
====================================================================

  CEO Scheduler (tick-based, multi-project)
  ┌──────────────────────────────────────────────────────────────┐
  │  Each tick: process instructions → check decision gates     │
  │  → advance projects → execute tasks → update memory         │
  └───────┬──────────┬──────────┬──────────┬───────────────────┘
          │          │          │          │
      ┌───▼───┐  ┌──▼────┐ ┌───▼──┐ ┌────▼─────┐
      │Project│  │Project│ │Proj C│ │ Market   │
      │   A   │  │   B   │ │   D  │ │ Scanner  │
      │(dev)  │  │(design)│ │(paused)│ │ (12 src) │
      └───────┘  └────────┘ └──────┘ └──────────┘
          │          │          │          │
  ┌───────────────────────────────────────────────────────────┐
  │              Task Queue (scan/design/art/code/qa/build)   │
  └───────────────────────────────────────────────────────────┘

  ┌─────────────┐     ┌─────────────────────────────────────┐
  │  Dashboard  │     │  AI Models                          │
  │  (FastAPI)  │     │  glm-4-flash (analysis) · deepseek  │
  │  localhost  │     │  (code) · ComfyUI/SD (art)           │
  │  :8080      │     └─────────────────────────────────────┘
  └─────────────┘     ┌─────────────────────────────────────┐
  ┌─────────────┐     │  12 Market Sources                  │
  │   SQLite    │     │  itch · reddit · steamspy · tiktok  │
  │   (local)   │     │  youtube · producthunt · ...        │
  └─────────────┘     └─────────────────────────────────────┘
====================================================================
```

---

## Features

- **Multi-project scheduler** — CEO agent manages multiple game projects in parallel, each on its own lifecycle track
- **12 market data sources** — itch.io, Reddit, SteamSpy, TikTok, YouTube, Google Play, App Store, X/Twitter, and more with cross-source correlation analysis
- **5 human approval gates** — new project start, publishing, cancellation, budget overrun, and direction change require human sign-off
- **3-layer error recovery** — retry with feedback, strategy change, then human decision point
- **Mechanic planning layer** — GDD is decomposed into ordered mechanics; code generated per-mechanic for reliability
- **AI art pipeline** — ComfyUI + Stable Diffusion 1.5 generates backgrounds, sprites, and UI icons
- **Automated playtesting** — Playwright runs 8 verification checks against every build
- **Prototype mode** — generate a playable demo in ~5 minutes using colored rectangles/emoji as placeholder art
- **Auto-localization** — game UI strings translated to 15 languages
- **Programmatic music** — Web Audio oscillator-based BGM per genre (Suno API optional)
- **Executive chat** — talk to CEO through the Dashboard (CFO/COO run as internal nodes); receive decision cards you can approve/reject
- **Document viewer** — view all agent work artifacts (proposal, GDD, market scan, art/music/QA/build reports) in a document modal per project
- **Scheduler pause/resume** — pause the scheduler with a "⏸ 下班" button on the dashboard; resume with "▶ 上班"
- **Inline approval** — approve/reject projects and view documents directly from project cards on the board
- **Layered memory** — short-term events vs. long-term lessons; project context preserved across sessions

---

## Tech Stack

| Layer | Technology | Purpose |
|---|---|---|
| Orchestration | Python 3.11 + LangGraph | Multi-project scheduling, state machine |
| Analysis AI | Zhipu glm-4-flash (free) | Market analysis, game design, CFO evaluation |
| Code AI | DeepSeek Coder | Phaser 4 + TypeScript game generation |
| Art AI | ComfyUI + Stable Diffusion 1.5 | Game asset generation |
| Game Engine | Phaser 4 + TypeScript + Vite | Web mini-game runtime |
| Dashboard | FastAPI + HTML/CSS/JS | Project board, task monitor, decision cards, document viewer, CEO reports |
| Vector Store | ChromaDB | Memory search and long-term lesson retrieval |
| Cache | Redis | Task queue, ephemeral state |
| Database | SQLite (async) | Projects, decisions, tasks, logs, financial records |
| Deployment | Butler CLI | itch.io publishing |

---

## Quickstart

```bash
# Clone and install
git clone <repo>
cd gcagents
pip install -e ".[dev]"

# Configure API keys
cp .env.example .env  # then edit .env and fill in:
#   DEEPSEEK_API_KEY=sk-...
#   ZHIPU_API_KEY=...

# Start backing services
docker compose up -d  # postgres, redis, chromadb (comfyui optional with --profile gpu)

# Run the scheduler (multi-project mode)
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
DEEPSEEK_API_KEY=sk-...        # code generation
ZHIPU_API_KEY=...              # analysis/design (glm-4-flash)
BUTLER_API_KEY=...            # itch.io deployment
BUTLER_USERNAME=...           # itch.io username
SUNO_API_KEY=...              # music generation (optional)
```

**`config/agents.yaml`** — Agent-to-model mappings and role assignments.

**`config/sources.yaml`** — 12 market data source configurations and polling intervals.

---

## Project Structure

```
gcagents/
├── orchestrator/             # Core orchestration
│   ├── main.py               #   CLI entry (run, run-forever, run-scheduler, scan)
│   ├── scheduler.py          #   CEO multi-project tick scheduler
│   ├── task_queue.py          #   SQLite-backed task queue
│   ├── decision_gate.py      #   5-type human approval gates
│   ├── prototype_mode.py     #   Quick prototype (~5 min, no art)
│   ├── persistence.py        #   DB schema (projects/tasks/decisions/memory)
│   ├── state.py              #   CompanyState, PipelinePhase, retry metadata
│   └── graph/
│       └── pipeline.py      #   Classic 13-node LangGraph pipeline (legacy)
├── agents/                   # AI agents
│   ├── research/
│   │   ├── scanner.py        #   12-source market scanner
│   │   ├── analyzer.py       #   Cross-source correlation, opportunity scoring
│   │   └── sources/          #   Source adapters (itch, reddit, steamspy, etc.)
│   └── dev/
│       ├── designer/         #   GDD generation + mechanic planning
│       ├── artist/           #   ComfyUI/SD asset pipeline (sprites, bg, icons)
│       ├── programmer/       #   DeepSeek code generation (Phaser 4 + TypeScript)
│       ├── qa/               #   Playwright auto-playtest (8 checks)
│       ├── music/            #   Web Audio BGM + optional Suno API
│       ├── localize/         #   15-language auto-translation
│       └── builder/          #   Vite build → dist/
├── dashboard/web/
│   ├── api_server.py        #   FastAPI backend (41 endpoints)
│   ├── index.html           #   Project board, task monitor, decision cards, document viewer
│   ├── app.js               #   Frontend logic
│   └── style.css            #   Styles
├── shared/
│   ├── config.py            #   pydantic-settings env loading
│   ├── models.py            #   ProjectState, DecisionPoint, TaskRecord
│   ├── memory.py            #   Layered memory (short-term/long-term/project)
│   └── llm_client.py       #   Unified LLM client with token tracking
├── config/
│   ├── agents.yaml          #   Agent → model mappings
│   └── sources.yaml         #   12 market sources config
├── data/
│   ├── gcagents.db          #   SQLite database
│   └── games/              #   Generated game projects
└── .env                    #   API keys (gitignored)
```

---

## Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) — Full technical documentation (architecture, agents, workflows, database schema, API reference)

---

## Development

```bash
# Run tests
pytest tests/

# Lint
ruff check .

# Type check
mypy .
```

---

## License

No license file is currently present in the repository. Add an appropriate license (e.g., MIT) before using this code.

---

## Acknowledgments

Built on LangGraph, FastAPI, Phaser, and ComfyUI.