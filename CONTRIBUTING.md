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
- **Type checker**: mypy (strict aspirational; currently `--strict=false`).

```bash
ruff check .          # lint
ruff format .         # auto-format
mypy orchestrator shared agents dashboard  # type check
```

## Running Tests

```bash
pytest tests/ -v                          # run all tests
pytest tests/ -v --cov --cov-report=term-missing  # with coverage (gate: 60%)
```

Tests use `pytest-asyncio` in `strict` mode. Each test gets a fresh SQLite
database via the `tmp_db` fixture — the production `data/gcagents.db` is never
touched.

### Test Markers

- `@pytest.mark.unit` — Pure unit tests (no I/O, fast).
- `@pytest.mark.integration` — Tests with DB or external dependencies.
- `@pytest.mark.slow` — Tests that take >1s.

## Pull Request Process

1. Create a feature branch from `main`.
2. Make your changes with clear, atomic commits.
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
- **Task types**: `market_scan`, `design_game`, `art_gen`, `generate_music`,
  `develop`, `develop_simple`, `qa`, `build`, `localize`, `deploy`.
