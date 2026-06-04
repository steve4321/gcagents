# Contributing to GCAgents

Thank you for your interest in contributing! This guide covers the basics.

## Development Setup

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Start backing services (optional — SQLite works without Docker)
docker compose up -d

# Configure API keys
cp .env.example .env  # then fill in your keys
```

## Code Style

- **Python 3.11+** with type hints on all public functions.
- **Formatter**: ruff (line-length 100).
- **Linter**: ruff with rules `E, F, I, N, W, UP`.
- **Type checker**: mypy (strict aspirational; currently `continue-on-error`).

```bash
ruff check .          # lint
ruff format .         # auto-format
mypy orchestrator shared agents dashboard  # type check
```

### Error Handling Conventions

- **Never** use bare `except Exception: pass`. Catch specific exception types and log.
- Non-critical failures (event emission, telemetry) should not crash the main loop but must log at `debug` or `warning` level.
- Use `from loguru import logger` for all logging.

### Security Conventions

- **Path validation**: All file paths from LLM output must be validated with `is_relative_to()` before writing.
- **Input validation**: Use FastAPI `Query()`, `Field()` validators for all user-controlled parameters.
- **Action allowlists**: CEO actions from LLM responses must be checked against an explicit allowlist.
- **No hardcoded secrets**: Use `shared/config.py` or environment variables for all configuration.

## Running Tests

```bash
pytest tests/ -v                          # run all tests (168 tests)
pytest tests/ -v --cov --cov-report=term-missing  # with coverage (gate: 60%)
pytest tests/test_scheduler.py -v         # run specific test module
pytest -k "test_is_paused" -v             # run tests matching name
```

Tests use `pytest-asyncio` in `strict` mode. Each test gets a fresh SQLite
database via the `tmp_db` fixture — the production `data/gcagents.db` is never
touched.

### Test Markers

- `@pytest.mark.unit` — Pure unit tests (no I/O, fast).
- `@pytest.mark.integration` — Tests with DB or external dependencies.
- `@pytest.mark.slow` — Tests that take >1s.

### Test Coverage

| Module | Test File | Coverage |
|---|---|---|
| Persistence | `test_persistence.py` | Comprehensive (40+ tests) |
| Memory | `test_memory.py` | Good |
| Scheduler | `test_scheduler.py` | Helpers + pause mechanism |
| Decision Gate | `test_decision_gate.py` | Good |
| Complexity | `test_complexity.py` | Good |
| Scanner | `test_scanner.py` | Good |
| Code Generator | `test_code_generator.py` | Basic |
| API Server | `test_api_server.py` | Minimal (GET endpoints only) |
| Config | `test_config.py` | Basic |
| Models | `test_models.py` | Basic |
| Exceptions | `test_exceptions.py` | Basic |
| LLM Client | `test_llm_client.py` | Retry logic |
| Nodes | `test_nodes.py` | CFO/COO basic |

**Gap areas**: API server POST/WebSocket tests, agent integration tests, planner/kanban tests.

## Pull Request Process

1. Create a feature branch from `master`.
2. Make your changes with clear, atomic commits (semantic style: `feat:`, `fix:`, `chore:`).
3. Ensure `ruff check`, `ruff format --check`, and `pytest` all pass.
4. Open a PR with a description of what changed and why.

## Architecture Overview

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full technical documentation
including system design, agent nodes, database schema, and API reference.

## Key Conventions

- **CEO-only interaction**: User talks to CEO; CFO/COO are internal nodes.
- **Decision gates**: 5 types of human approval (`new_project`, `publish`,
  `cancel`, `budget_overrun`, `direction_change`).
- **3-layer error recovery**: retry → strategy change → human decision.
- **Kanban task board**: CAS-based claiming (not FIFO queue) with states:
  `triaged → claimed → running → completed/failed/blocked`.
- **Task types**: `market_scan`, `design_game`, `art_gen`, `generate_music`,
  `develop`, `develop_simple`, `qa`, `build`, `localize`, `deploy`.
- **Verification**: Every agent output verified via the verification framework
  (3 modes: strict, soft, advisory).
- **Event sourcing**: All scheduler actions emit events to the append-only event store.

## Project Module Map

| Directory | Purpose |
|---|---|
| `orchestrator/` | CEO scheduler, kanban, planner, event store, persistence, decision gates |
| `agents/` | AI agents — research, design, art, code, QA, music, localize, deploy |
| `shared/` | Events, sandbox, verification, model router, context manager, code graph, messaging |
| `skills/` | Pluggable agent capabilities (code review, etc.) |
| `tools/` | Agent tool definitions (migration in progress) |
| `dashboard/web/` | FastAPI backend (38+ endpoints) + vanilla HTML/CSS/JS frontend |
| `config/` | `agents.yaml` (model routing), `sources.yaml` (12 market sources) |
| `tests/` | pytest suite (168 tests, 14 files) |
