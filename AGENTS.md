# GCAgents — Agent Onboarding

> Compact, repo-specific guidance. Generic Python/JS knowledge is omitted.
> Last verified: 2026-06-17

## Setup quirks (read this first)

- **No `python` binary** — only `python3` exists. Use `python3` explicitly in all commands.
- **No `[tool.setuptools.packages]` in pyproject.toml** — `pip install -e ".[dev]"` fails with "Multiple top-level packages discovered". Workaround: run from the project root, which puts `''` (cwd) on `sys.path`. If you must run from elsewhere, prepend `PYTHONPATH=/mnt/c/work/gcagents`.
- **Dashboard has a pre-existing circular import** (`dashboard.web.routers.chat` ↔ `dashboard.web.api_server`). `python3 -m dashboard.web.api_server` fails. Use **`python3 scripts/run_dashboard.py`** instead (a wrapper that defers the uvicorn import).
- **`make dashboard` is broken** for the same reason. `make run-scheduler` works.

## Essential commands

All commands assume **`cd /mnt/c/work/gcagents`** first.

| Task | Command |
|---|---|
| Install (best-effort) | `pip install -e ".[dev]"` — **expect failure**; tests still run from cwd |
| Lint | `ruff check .` |
| Format | `ruff format .` |
| Type-check | `mypy orchestrator shared agents dashboard` |
| Run all tests | `pytest tests/ -v` |
| Run one test file | `pytest tests/test_quality_gate.py -v` |
| Run one test | `pytest tests/test_quality_gate.py::TestDataclasses -v` |
| Coverage (CI uses 40% floor) | `pytest tests/ --cov --cov-fail-under=40` |
| Start dashboard (port 8080) | `python3 scripts/run_dashboard.py` |
| Start scheduler | `python3 -m orchestrator.main run-scheduler --interval 60` |
| Quick prototype | `python3 -m orchestrator.main run-prototype "tower defense"` |
| Production batch test | `python3 scripts/batch_test_td_generation.py` |
| Production report | `python3 scripts/production_report.py` |

CI order: **`ruff check → ruff format --check → mypy → pytest** (see `.github/workflows/ci.yml`).
`make ci-fix` runs format+lint+test locally.

## Architecture (one-screen mental model)

Tick-based multi-project scheduler: CEO scans market → designer writes GDD → programmer generates code → QA playtests → builder → deployer → feedback collector.

```
orchestrator/        # Tick loop, kanban, DAG planner, persistence (24 tables)
  scheduler.py       # CEO tick — main entrypoint
  main.py            # CLI (run-scheduler / scan / run-prototype)
agents/
  research/          # Market scanners (12 sources)
  dev/
    designer/        # GDD generator + mechanic planner
    programmer/      # Phaser 4 + TypeScript code generator (code_generator.py = 1900 LOC)
    qa/              # Playwright playtest + quality_gate integration
    builder/         # Vite build
    music/, artist/, localize/
  ops/
    deployer/        # itch.io / CrazyGames / Poki adapters
    analytics/       # Feedback collector
shared/              # llm_client, memory, complexity, quality_gate, production_metrics
dashboard/           # FastAPI + native HTML/JS UI (port 8080)
game-templates/      # 8 genre templates; **tower-defense/** is the golden reference
config/              # agents.yaml, sources.yaml, phaser_knowledge.yaml, prompts/
data/                # Runtime: gcagents.db, games/, builds/, production_metrics.json
```

**Key wiring**: `orchestrator/scheduler.py` enqueues tasks → `agents/dev/qa/qa_agent.py::run_qa` runs `shared/quality_gate.py::run_quality_gate` (6 hard_veto checks) → on success, `_record_production_metric` writes to `data/production_metrics.json`.

## Game generation pipeline (the one that matters)

1. `code_generator._scaffold_project` detects `genre` in GDD → if `game-templates/<genre>/src/main.ts` exists, **copies the template** (no LLM-generated .ts).
2. Otherwise it builds a blank scaffold.
3. `code_generator._generate_from_template` calls LLM **only to fill `src/game/data/*.json`** (tower/enemy/wave/path data). Template logic files stay untouched.
4. `code_generator._generate_all_at_once` is the legacy path for non-template genres (4-round LLM generation, ~1500 LOC of TS per game).

Templates are **not** referenced by `code_generator.py` until this session's work — they were previously dead documentation. The TD template at `game-templates/tower-defense/` is the first wired-in template.

## Tower Defense (TD) specific

- **Golden template**: `game-templates/tower-defense/` — 15 .ts files, 1538 LOC, builds with `npm install && npm run build`.
- **`__TEST__` contract**: window-level interface in `src/main.ts` — used by `quality_gate._check_test_contract`, `_check_tower_placement`, `_check_game_loop_closure`.
- **TD-0 → TD-3** phases all done. See `.sisyphus/plans/td-quality-first.md` for the original plan.
- **Quality gate**: 6 checks (mechanic_completeness, asset_existence, test_contract, tower_placement, game_loop, complexity). Static checks run from source. Playwright checks need `dist/` built and a Chromium browser.
- **To preview the TD game**: copy `game-templates/tower-defense/dist` → `data/games/<name>/dist`, then visit `http://127.0.0.1:8080/games-preview/<name>/`.

## Testing conventions

- `asyncio_mode = "strict"` in pyproject.toml — **every async test must have `@pytest.mark.asyncio`**.
- `testpaths = ["tests"]` — pytest ignores `tests/integration/...` paths in the default run? **No** — pytest recurses, but `tests/integration/` contains heavier tests.
- Coverage source is `["orchestrator", "shared"]` only — `agents/` is **not measured** for coverage (intentional). Floor is 40%.
- `conftest.py` provides a `tmp_db` fixture (in-memory SQLite + monkeypatched persistence).
- Tests that touch the LLM mock with `unittest.mock.AsyncMock`. Pattern: `mock_llm.chat_completion = AsyncMock(return_value=(text,))`.
- For "skip if golden template not built" fixtures: use `pytest.skip("Golden template not present")` after checking `(template / "src/main.ts").exists()`.

## Code style quirks

- **Ruff `line-length = 100`**, target Python 3.11, selects `["E","F","I","N","W","UP"]`.
- **No docstrings unless necessary** — the project has an active hook that flags unnecessary docstrings. Keep code self-documenting. Justify complex regex/algorithm comments only.
- **TypeScript strict mode** in all game templates. Zero `any` types enforced.
- **JSON imports** in `.ts` files require `tsconfig.json` `resolveJsonModule: true` (already set in all templates).

## CI workflows (`.github/workflows/`)

- **`ci.yml`** — every push/PR to master/main: lint + format + mypy + pytest on Python 3.11/3.12. 10-min timeout.
- **`td-quality-gate.yml`** — every push/PR: builds TD golden template, runs quality gate tests + integration tests + batch test. 30-min timeout. Installs Playwright Chromium.

## Gotchas agents repeatedly hit

1. **`python` (no 3) doesn't exist** — always `python3`.
2. **Dashboard won't start with the README command** — use `scripts/run_dashboard.py`.
3. **Forgetting to `cd` to project root** — `import shared` will fail from a random dir.
4. **Memory tests need the live DB** — use the `tmp_db` fixture in conftest.
5. **Analytics endpoint `/api/analytics/...` may 500** if `data/gcagents.db` schema drifted — delete `data/gcagents.db` and re-run `python3 scripts/setup_local.py`.
6. **Scheduler will try real LLM calls** if `MINIMAX_API_KEY` is set in `.env`. Without a key, the scheduler will fail at generation time. For pipeline tests, see `tests/integration/test_scheduler_e2e.py` for the `mock_llm` pattern.
7. **`game-templates/*/node_modules/` and `dist/` are git-ignored** but exist in working tree — don't commit them.

## Reference files worth knowing

- `README.md` — full system overview (13 dashboard sections, 28 capabilities, 33 test files)
- `ARCHITECTURE.md` — deep dive (DB schema, API endpoints, agent wiring) — referenced from README
- `.sisyphus/plans/*.md` — approved plans including the TD quality-first plan
- `Makefile` — every command you'll need
- `pyproject.toml` — pytest config, ruff config, mypy config, coverage config
- `shared/quality_gate.py` — 6-check hard-veto gate (TD-1 deliverable)
- `shared/production_metrics.py` — generation stats tracker (TD-3 deliverable)
- `agents/dev/programmer/code_generator.py` — 1900-LOC LLM code generator
- `game-templates/tower-defense/` — the golden reference template
