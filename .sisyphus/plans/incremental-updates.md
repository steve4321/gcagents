# Incremental Content Updates — Implementation Plan

> Status: Draft  
> Created: 2026-06-18  
> Owner: Sisyphus

## Problem

The entire pipeline assumes one-shot generation: design full GDD → generate all code → build → deploy → LIVE (dead). No game can receive incremental content after going LIVE.

This is a fundamental design flaw. Real game production is iterative.

## Discovery

The explore agent mapped 12 one-shot assumptions across the codebase. Three are critical blockers:

| # | Blocker | Location | Impact |
|---|---------|----------|--------|
| B1 | `_copy_template_project` uses `shutil.copytree(dirs_exist_ok=True)` | `code_generator.py:1324` | Destroys all existing project content on every `generate_game_code` call |
| B2 | `mode: "update"` is enqueued by `_collect_and_route_feedback` but never read by `_run_agent` | `scheduler.py:870-884` | The existing feedback→update path is completely broken — the update flag is silently dropped |
| B3 | `_generate_from_template` overwrites ALL data JSON files unconditionally | `code_generator.py:901-1074` | Even if scaffold is guarded, data generation replaces everything |

**Key insight**: B2 means the feedback-driven update loop is already wired but broken. Fixing B2 alone makes the existing update path work. Fixing B1+B2+B3 makes incremental content updates possible.

## Design Principles

1. **Template games first** — template games (TD, puzzle, etc.) separate logic (.ts) from data (.json). Incremental updates = append to JSON. This is the 80% value path.
2. **VN chapters via existing chapter_pipeline** — the standalone system already handles incremental chapter merge. Wire it in later.
3. **Non-template games (LLM-generated) are out of scope** — they need conversion to template-first. Separate future work.
4. **Non-destructive by default** — every file operation must check existence before overwriting.
5. **Content pack as the delta unit** — a structured spec describing what new content to add (new towers, new enemies, new waves, new chapters).

## Architecture

```
SCHEDULER TICK
  └─ _advance_project (LIVE phase)
       └─ check update interval (genre-aware: TD=30d, VN=7d)
            └─ enqueue "content_update" task
                 └─ _run_agent("content_update")
                      ├─ designer.generate_content_expansion()  → content_pack GDD delta
                      ├─ programmer.generate_incremental_data() → new JSON entries
                      ├─ content_merger.merge()                 → append to existing files
                      ├─ quality_gate.run(mode="incremental")   → validate new content
                      ├─ builder.build_game()                   → npm build (non-destructive)
                      └─ deployer.deploy()                      → butler push (upsert)

EXISTING FEEDBACK PATH (also fixed):
  _collect_and_route_feedback()
    └─ enqueue "develop" with mode="update"
         └─ _run_agent("develop", mode="update")
              └─ programmer.generate_game_code(incremental=True)  → skip scaffold, data-only
```

## Implementation Phases

### Phase 1: Fix Broken Update Path + Guard Scaffold (P0 BLOCKER)

**Goal**: Make the existing feedback→update loop stop destroying content.

**Files to change**:

#### 1a. `orchestrator/state.py` — Add `mode` field
```python
class CompanyState(BaseModel):
    # ... existing fields ...
    mode: str = ""  # "" | "update" | "content_update"
```

#### 1b. `orchestrator/scheduler.py:870-884` — Read `mode` from params
```python
async def _run_agent(task_type: str, project_id: str, params: dict) -> dict:
    state = CompanyState(
        # ... existing fields ...
        mode=params.get("mode", ""),
    )
```

#### 1c. `agents/dev/programmer/code_generator.py:1297-1306` — Guard `_scaffold_project`
```python
def _scaffold_project(project_dir: Path, gdd: dict | None = None, *, skip_if_exists: bool = False) -> bool:
    if skip_if_exists and (project_dir / "src").exists():
        existing_ts = list((project_dir / "src").rglob("*.ts"))
        if existing_ts:
            logger.info(f"Scaffold skipped: {len(existing_ts)} existing .ts files")
            return True  # Template was used previously
    # ... existing logic ...
```

#### 1d. `agents/dev/programmer/code_generator.py:83-94` — Pass `skip_if_exists` when mode=update
```python
async def generate_game_code(
    gdd: dict,
    project_dir: Path,
    config: AppConfig,
    build_error: str = "",
    art_assets_path: str = "",
    incremental: bool = False,
) -> Path:
    # ...
    template_used = _scaffold_project(project_dir, gdd, skip_if_exists=incremental)
```

#### 1e. `agents/dev/programmer/agent.py` — Pass `incremental` from state.mode
```python
async def develop_game(state: CompanyState) -> dict:
    is_update = state.mode == "update"
    code_path = await generate_game_code(
        gdd, project_dir, config,
        build_error=build_error,
        art_assets_path=state.art_assets_path or "",
        incremental=is_update,
    )
```

**Verification**: 
- Unit test: `_scaffold_project(skip_if_exists=True)` with existing .ts files → no file modified
- Unit test: `_run_agent` preserves `params["mode"]` into CompanyState
- Existing tests still pass (70/71)

**Deliverable**: Feedback-driven updates no longer destroy existing content. The mode flag reaches the programmer agent.

---

### Phase 2: Incremental Data Generation (P1)

**Goal**: `_generate_from_template` can generate only specific data files, merging new entries with existing content.

**Files to change**:

#### 2a. `agents/dev/programmer/code_generator.py:901-1074` — Add `target_files` + `existing_content` to `_generate_from_template`

New parameter: `target_files: list[str] | None = None`

When `target_files` is set:
- Only regenerate those specific JSON files (e.g., `["towers.json", "waves.json"]`)
- Read ALL existing data files and include them in the prompt as "EXISTING CONTENT"
- LLM prompt changes from "Create NEW themed data files" to "ADD new entries to the specified files while preserving existing entries"

```python
async def _generate_from_template(
    gdd: dict,
    project_dir: Path,
    config: AppConfig,
    model: str,
    max_tokens: int,
    art_assets_path: str = "",
    target_files: list[str] | None = None,
    content_expansion: dict | None = None,
) -> Path:
```

**Prompt structure for incremental mode**:
```
You are ADDING new content to an EXISTING {genre} game.

EXISTING data files (DO NOT modify existing entries):
{existing_files_json}

NEW CONTENT TO ADD (from content expansion spec):
{content_expansion_json}

For each target file, generate the COMPLETE file with BOTH existing and new entries merged.
Target files to regenerate: {target_files}
Files NOT listed above should NOT be returned.

RULES:
- Preserve ALL existing entries unchanged (same IDs, same stats)
- Add new entries with NEW unique IDs (prefix with "v2_" if needed to avoid collision)
- New entries must follow the exact same schema as existing ones
```

**Why generate complete files (not just deltas)?**: The template engine loads JSON files wholesale. A merged file with both old and new entries is simpler and more reliable than patching JSON in-place. The non-destructive guarantee comes from: (a) prompt instructs preservation, (b) we validate that all old entry IDs still exist in the output.

#### 2b. Validation: ID preservation check

After LLM generates merged data files, verify that all existing entry IDs are present in the new files. If any are missing, reject and retry.

```python
def _validate_incremental_merge(
    old_files: dict[str, str], new_files: dict[str, str]
) -> list[str]:
    """Return list of error messages. Empty = valid."""
    errors = []
    for fname, old_content in old_files.items():
        if fname not in new_files:
            continue  # File not targeted for update
        old_data = json.loads(old_content)
        new_data = json.loads(new_files[fname])
        old_ids = _extract_ids(old_data)
        new_ids = _extract_ids(new_data)
        missing = old_ids - new_ids
        if missing:
            errors.append(f"{fname}: missing IDs from previous version: {missing}")
    return errors
```

**Verification**:
- Unit test: Generate 3 towers → incremental update adds 2 more → verify all 5 tower IDs present
- Unit test: Incremental update with conflicting ID → retry generates unique ID
- Integration test: Full game gen → incremental update → build succeeds → quality gate passes

**Deliverable**: Template games can receive new towers/enemies/waves without losing existing content.

---

### Phase 3: Content Expansion Designer (P1)

**Goal**: The designer can generate a "content expansion spec" — what new content to add — given the existing GDD and existing data files.

**Files to change**:

#### 3a. `agents/dev/designer/gdd_generator.py` — New function

```python
async def generate_content_expansion(
    existing_gdd: dict,
    existing_content_summary: dict[str, list[str]],
    config: AppConfig,
    feedback_hints: list[str] | None = None,
) -> dict:
    """Generate a content expansion spec for incremental update.

    Args:
        existing_gdd: The current GDD (title, genre, balance, etc.)
        existing_content_summary: {"towers.json": ["arrow", "cannon", "frost"], ...}
        feedback_hints: Optional player feedback to guide expansion

    Returns:
        {
            "expansion_type": "content_pack",
            "new_towers": [{"id": "v2_laser", "name": "Laser Tower", ...}],
            "new_enemies": [...],
            "new_waves": [...],
            "balance_changes": {...},
            "rationale": "Adding laser tower for mid-game variety..."
        }
    """
```

**Prompt design**:
- System: "You are a game designer adding new content to an EXISTING game. You must NOT change existing content."
- User: Include existing GDD summary, existing content IDs/names, optional feedback hints
- Output: Structured expansion spec with new entries only

#### 3b. Wire into programmer flow

When `mode == "content_update"`:
1. Designer generates content expansion spec
2. Programmer's `_generate_from_template` receives `content_expansion` dict and `target_files` list
3. Merge and validate

**Verification**:
- Unit test: `generate_content_expansion` returns valid expansion spec
- Unit test: Expansion spec doesn't duplicate existing IDs
- Unit test: Feedback hints influence the expansion (e.g., "too easy" → harder enemies)

**Deliverable**: The system can autonomously decide WHAT new content to add, guided by feedback.

---

### Phase 4: Project Model Versioning (P2)

**Goal**: Track content versions and update history in the DB.

**Files to change**:

#### 4a. `shared/models.py` — Extend ProjectState

```python
class ProjectState(BaseModel):
    # ... existing fields ...
    content_version: int = 0  # Incremented on each content update
    last_content_update: datetime | None = None
    update_mode: str = ""  # "" | "update" | "content_update"
```

#### 4b. `orchestrator/persistence/engine.py` — Add columns to projects table

```sql
ALTER TABLE projects ADD COLUMN content_version INTEGER DEFAULT 0;
ALTER TABLE projects ADD COLUMN last_content_update TEXT;
ALTER TABLE projects ADD COLUMN update_mode TEXT DEFAULT '';
```

Use `CREATE TABLE IF NOT EXISTS` + migration pattern (check column existence via PRAGMA table_info, ALTER if missing). This is already the pattern used elsewhere in engine.py.

#### 4c. `orchestrator/persistence/projects.py` — Update save_project to handle new fields

#### 4d. `orchestrator/persistence/engine.py` — Extend `game_versions` table

```sql
ALTER TABLE game_versions ADD COLUMN change_type TEXT DEFAULT 'full_gen';
ALTER TABLE game_versions ADD COLUMN affected_files TEXT DEFAULT '[]';
```

`change_type` values: `full_gen`, `content_update`, `balance_tweak`, `bug_fix`

**Verification**:
- Migration test: existing DB upgrades without data loss
- Unit test: `content_version` increments on update
- Unit test: `game_versions` records structured change metadata

**Deliverable**: The system tracks what changed, when, and why.

---

### Phase 5: Scheduler LIVE Phase Handling (P1)

**Goal**: The scheduler automatically triggers content updates for LIVE games based on time intervals.

**Files to change**:

#### 5a. `orchestrator/scheduler.py:528-608` — Add LIVE phase branch in `_advance_project`

```python
elif phase == ProjectPhase.LIVE:
    # Check if it's time for a content update
    last_update = project.last_content_update
    interval = _get_update_interval(project.genre)  # TD=30 days, VN=7 days, default=14 days
    if _should_trigger_update(last_update, interval):
        if pid not in active_pids or not await has_active_task(pid, "content_update"):
            await enqueue(pid, "content_update", {
                "project_name": project.name,
                "mode": "content_update",
                "genre": project.genre,
            })
            await update_project_field(pid, "update_mode", "content_update")
```

#### 5b. `orchestrator/scheduler.py:870-998` — Add `content_update` task type to `_run_agent`

```python
elif task_type == "content_update":
    from agents.dev.designer.gdd_generator import generate_content_expansion
    from shared.content_summary import extract_content_summary

    project = await get_project(pid)
    existing_gdd = project.gdd or {}
    code_path = project.code_path
    content_summary = extract_content_summary(Path(code_path))

    expansion = await generate_content_expansion(
        existing_gdd, content_summary, config,
        feedback_hints=params.get("feedback_hints"),
    )

    # Route to programmer for incremental generation
    result = await _run_agent("develop", pid, {
        **params,
        "mode": "content_update",
        "content_expansion": expansion,
        "target_files": list(expansion.get("new_content", {}).keys()),
    })
    return result
```

#### 5c. Genre-aware update intervals

```python
_GENRE_UPDATE_INTERVALS = {
    "visual-novel": 7,   # days
    "tower-defense": 30,
    "puzzle": 21,
    "platformer": 21,
    "runner": 21,
    "shooter": 21,
    "card-game": 14,
    "idle-clicker": 14,
}
```

**Verification**:
- Unit test: LIVE project with old `last_content_update` triggers `content_update` enqueue
- Unit test: LIVE project with recent update does NOT trigger
- Unit test: Genre-specific intervals are respected
- Integration test: Full lifecycle — generate → deploy → LIVE → wait → content_update → deploy

**Deliverable**: Games automatically receive new content on a schedule.

---

### Phase 6: Content Merger Module + Builder Guard (P2)

**Goal**: Dedicated module for non-destructive content merging, and guard the builder from destructive operations.

**Files to create**:

#### 6a. `shared/content_merger.py`

```python
def merge_json_data(
    existing: dict[str, Any],
    new_entries: dict[str, Any],
    id_field: str = "id",
) -> dict[str, Any]:
    """Merge new entries into existing JSON data structure.

    - For dict-with-arrays: append new array items (dedup by id_field)
    - For flat dicts: merge keys (new values override)
    - For scalar values: new value wins
    """
```

#### 6b. Guard builder — `agents/dev/builder/build_agent.py`

The builder is already non-destructive (it just runs `npm install && npm run build`). No changes needed — it operates on whatever is in `project_dir`.

The destructive operation is actually in `shared/npm_runner.py:80`:
```python
shutil.rmtree(project_dir / "node_modules", ignore_errors=True)
```
This is cleanup after build — it's fine for incremental since `npm install` runs every time anyway.

**Verification**:
- Unit test: `merge_json_data` with new towers → existing towers preserved + new ones appended
- Unit test: Conflict (same ID) → new entry wins, old preserved if new doesn't have the field
- Unit test: Empty existing → works as full replacement

**Deliverable**: Reliable, tested content merge logic.

---

### Phase 7: Integration Tests (P1)

**Goal**: End-to-end verification of incremental update flow.

**Test file**: `tests/test_incremental_updates.py`

```python
class TestIncrementalUpdates:
    async def test_feedback_update_preserves_content(self, tmp_db, mock_llm):
        """Feedback-driven update doesn't destroy existing game content."""
        # 1. Generate full game
        # 2. Simulate feedback (2+ bug/feature items)
        # 3. Trigger update
        # 4. Verify: original .ts files unchanged, original data entries present

    async def test_content_update_adds_new_towers(self, tmp_db, mock_llm):
        """Content update adds new towers without removing existing ones."""
        # 1. Generate TD game with template
        # 2. Read towers.json → record tower IDs
        # 3. Trigger content_update
        # 4. Read towers.json → verify old IDs present + new IDs added

    async def test_live_phase_triggers_update(self, tmp_db, mock_llm):
        """LIVE project with stale last_content_update triggers content_update."""
        # 1. Set project to LIVE with old timestamp
        # 2. Run scheduler tick
        # 3. Verify content_update task enqueued

    async def test_build_succeeds_after_update(self, tmp_db, mock_llm):
        """Game builds successfully after incremental update."""
        # 1. Generate + build game
        # 2. Apply incremental update
        # 3. Build again → success

    async def test_quality_gate_incremental_mode(self, tmp_db, mock_llm):
        """Quality gate runs successfully on updated game."""
        # 1. Generate game that passes quality gate
        # 2. Apply incremental update
        # 3. Run quality gate → passes
```

**Deliverable**: Confidence that incremental updates work end-to-end.

---

## Execution Plan

| Phase | Parallelizable? | Estimated LOC | Dependencies |
|-------|----------------|---------------|--------------|
| Phase 1 (fix mode + guard scaffold) | No — sequential, fixes a bug | ~50 | None |
| Phase 2 (incremental data gen) | Yes — with Phase 4 | ~200 | Phase 1 |
| Phase 3 (content expansion designer) | Yes — with Phase 2 | ~150 | Phase 1 |
| Phase 4 (DB schema) | Yes — with Phase 2/3 | ~100 | None |
| Phase 5 (scheduler LIVE) | No — depends on 2+3+4 | ~100 | Phase 2, 3, 4 |
| Phase 6 (content merger + builder) | Yes — with Phase 5 | ~100 | Phase 2 |
| Phase 7 (tests) | After all phases | ~200 | All |

**Parallel execution strategy**:
- Wave 1: Phase 1 (sequential, unblocks everything)
- Wave 2: Phase 2 + Phase 3 + Phase 4 (parallel, 3 agents)
- Wave 3: Phase 5 + Phase 6 (parallel, 2 agents)
- Wave 4: Phase 7 (sequential, validates everything)

## Risks & Mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| LLM generates conflicting IDs in incremental mode | MAJOR | `_validate_incremental_merge` checks ID preservation; retry on failure |
| Quality gate doesn't catch broken incremental content | MEDIUM | Run full quality gate (not incremental-only) until confidence is high |
| Non-template games can't receive incremental updates | KNOWN LIMITATION | Out of scope — future work: convert to template-first |
| DB migration breaks existing data | LOW | ALTER TABLE ADD COLUMN is additive, no data loss |
| Update cadence wrong for specific genre | LOW | Genre-aware intervals table, configurable via config |
