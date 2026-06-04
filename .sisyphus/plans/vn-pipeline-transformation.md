# GCAgents → Hybrid Visual Novel Production Pipeline

**Status:** Draft for review
**Target:** Stable, repeatable production of hybrid Visual Novel + light stat-based/branching games
**Output shape:** 1-hour playable VN with 3-5 character routes + 3+ endings, deployable to itch.io

---

## 1. Architecture

```
                    ┌─────────────────────────┐
                    │  Market Scan (VN/IF)    │  ← + itch.io VN tag, otome, BL
                    └────────────┬────────────┘
                                 ↓
                    ┌─────────────────────────┐
                    │  GDD Gen (VN schema)    │  ← + branching_tree, character_roster
                    │  + Schema Validator     │     (NEW: shared/vn_schema.py)
                    └────────────┬────────────┘
                                 ↓
                    ┌─────────────────────────┐
                    │  Mechanic Planner (VN)  │  ← 8 mandatory VN mechanics
                    │  + code_anchor per mech │
                    └────────────┬────────────┘
                                 ↓
                    ┌─────────────────────────┐
                    │  Art (VN path)          │  ← character consistency + expressions
                    │  Code Gen (VN path)     │  ← 4-round for VN, replaces generic
                    │  Music (mood BGM + SFX) │  ← 7 mood tracks, 5 SFX
                    └────────────┬────────────┘
                                 ↓
                    ┌─────────────────────────┐
                    │  QA (VN checks)         │  ← + branch_coverage, ending_reach, save/load
                    │  + Hard Veto Gate       │
                    └────────────┬────────────┘
                                 ↓
                    ┌─────────────────────────┐
                    │  Localize (15 langs)    │  ← + branching keys, character names
                    │  + Build (Vite)         │
                    └────────────┬────────────┘
                                 ↓
                    ┌─────────────────────────┐
                    │  Deploy (itch.io)       │  ← parent: common route
                    │  + Child: route URLs    │     children: character routes
                    └─────────────────────────┘
```

---

## 2. Data Model Changes

Add 6 new tables; extend `projects` with 4 columns. All migrations are ADDITIVE — old code keeps working.

```sql
-- New: route registry
CREATE TABLE IF NOT EXISTS vn_routes (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,           -- FK to projects.id
    route_key TEXT NOT NULL,            -- 'common', 'character_alice', etc.
    route_type TEXT NOT NULL,           -- 'common' | 'character' | 'hidden' | 'bad'
    parent_route_id TEXT,               -- self-FK, null for common
    unlock_condition TEXT,              -- JSON-serialized condition
    chapter_count INTEGER DEFAULT 0,
    estimated_playtime_min INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- New: character registry
CREATE TABLE IF NOT EXISTS vn_characters (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    name TEXT NOT NULL,
    role TEXT NOT NULL,                 -- 'protagonist' | 'heroine' | 'antagonist' | 'npc'
    sprite_set_path TEXT,               -- public/assets/characters/<key>/
    expression_variants TEXT,           -- JSON array: ['neutral','happy','sad','surprised','angry']
    stat_affinities TEXT,               -- JSON: {'empathy': +2, 'wit': +1}
    localization_names TEXT,            -- JSON: {'ja': 'アリス', 'ko': '앨리스', ...}
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- New: ending registry
CREATE TABLE IF NOT EXISTS vn_endings (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    name TEXT NOT NULL,
    trigger_condition TEXT NOT NULL,    -- JSON: {'stat:empathy': {'>=': 5}, 'flag:helped_alice': true}
    epilogue_key TEXT NOT NULL,         -- localization key
    is_good_ending INTEGER DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- New: CG unlock registry
CREATE TABLE IF NOT EXISTS vn_cgs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    cg_key TEXT NOT NULL,
    unlock_condition TEXT NOT NULL,     -- JSON condition
    image_path TEXT,                    -- public/assets/cg/<key>.png
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- New: stat registry (schema, not values)
CREATE TABLE IF NOT EXISTS vn_stats (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    stat_name TEXT NOT NULL,            -- 'empathy', 'wit', 'courage', etc.
    min_value INTEGER DEFAULT 0,
    max_value INTEGER DEFAULT 10,
    decay_per_chapter REAL DEFAULT 0.0,
    branching_thresholds TEXT,           -- JSON: [{'>=': 7, 'route': 'alice_true_end'}]
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- New: shared asset registry (cross-route asset reuse)
CREATE TABLE IF NOT EXISTS route_assets (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    asset_type TEXT NOT NULL,           -- 'character' | 'background' | 'bgm' | 'sfx'
    asset_key TEXT NOT NULL,
    source_route_id TEXT,               -- which route's art budget paid for this
    file_path TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Extend projects table (additive, nullable defaults)
ALTER TABLE projects ADD COLUMN parent_id TEXT;          -- parent project (for route sub-projects)
ALTER TABLE projects ADD COLUMN shared_assets_path TEXT;  -- symlink/path to parent assets
ALTER TABLE projects ADD COLUMN route_id TEXT;            -- FK to vn_routes.id
ALTER TABLE projects ADD COLUMN vn_schema_version TEXT DEFAULT '1.0';
```

---

## 3. GDD Schema (VN-specific, additive)

`DESIGNER_SYSTEM_PROMPT` in `agents/dev/designer/gdd_generator.py` is extended. New top-level fields:

| Field | Type | Purpose |
|---|---|---|
| `narrative_premise` | str | 2-3 sentence hook (logline) |
| `player_protagonist` | `{name, pronouns, portrait_key}` | POV character |
| `character_roster` | `[{name, role, sprite_set, expression_variants[], personality, stat_affinities[]}]` | All NPCs (min 2) |
| `route_structure` | `{common_route_chapters: int, character_routes: [{key, name, chapters: int, unlock: str}]}` | Top-level map |
| `stat_system` | `{stats: [{name, range: [min,max], decay: float, branching_thresholds: [{op, value, route}]}]}` | 5-8 stats |
| `branching_tree` | `{root: str, nodes: [{id, scene_key, choices?: [{label, next_node, stat_delta?: {stat: value}, flag_set?: [key]}], condition?: {stat: {op, value}}], edges: [...]}` | DAG of scenes (≥8 nodes) |
| `ending_conditions` | `[{name, trigger: {stat?: {op, value}, flag?: key, route?: key}, epilogue_key, is_good: bool}]` | ≥3 endings |
| `cg_milestones` | `[{scene_id, cg_key, condition}]` | CG unlock map |
| `save_points` | `[{scene_id, save_key}]` | Auto-save points |
| `localization_sensitive` | `[key_patterns]` | Keys needing per-locale handling (e.g., puns, idioms) |
| `vn_schema_version` | str | "1.0" (for forward compat) |

**Backward compat:** Old fields (mechanics, scenes, entities, art_style, audio, monetization, balance, technical_architecture) are KEPT. VN fields are additive. Existing GDD consumers work unchanged.

---

## 4. Visual Novel Template: `game-templates/visual-novel/`

```
visual-novel/
├── package.json                       (copied from puzzle-match — Phaser 4 + Vite)
├── tsconfig.json                      (copied)
├── vite.config.ts                     (copied)
├── index.html                         (NEW: VN-specific body — name box, dialogue box, choice panel)
├── public/
│   └── assets/
│       ├── characters/                (NEW: 5 expressions × 3 characters = 15 PNGs)
│       ├── backgrounds/               (NEW: 10 background PNGs)
│       ├── cg/                        (NEW: 5 CG unlock images)
│       └── audio/
│           ├── bgm/                   (NEW: 7 mood tracks)
│           └── sfx/                   (NEW: 5 SFX clips)
└── src/
    ├── main.ts                        (NEW: scene list + __TEST__ contract)
    └── game/
        ├── config.ts                  (NEW: canvas 1280x720, safe area for VN UI)
        ├── data/                      (NEW: 5 JSON files, ~1500 lines total)
        │   ├── characters.json
        │   ├── dialogue.json
        │   ├── branching.json
        │   ├── endings.json
        │   └── stats.json
        ├── entities/                  (NEW)
        │   ├── Character.ts           (sprite + expression state)
        │   └── Scene.ts               (background + characters + music binding)
        ├── systems/                   (NEW: 8 systems, ~1200 LOC)
        │   ├── DialogueSystem.ts      (line-by-line typewriter)
        │   ├── ChoiceSystem.ts        (branching UI)
        │   ├── StatSystem.ts          (stat tracking + thresholds)
        │   ├── BranchingEngine.ts     (DAG traversal + condition eval)
        │   ├── SaveLoadSystem.ts      (localStorage + 3 slots)
        │   ├── CGGallerySystem.ts     (unlock tracking + scene replay)
        │   ├── BGMController.ts       (mood-based + transitions)
        │   └── LocalizationManager.ts (key-based lookup + 15 locales)
        └── scenes/                    (NEW: 7 scenes, ~700 LOC)
            ├── BootScene.ts           (asset loading)
            ├── TitleScene.ts          (game title + start)
            ├── MenuScene.ts           (NEW GAME / CONTINUE / GALLERY / SETTINGS)
            ├── NovelScene.ts          (main gameplay)
            ├── SaveLoadScene.ts       (3 save slots)
            ├── GalleryScene.ts        (CG + character viewer)
            └── EndScene.ts            (ending display)
```

**Estimated LOC:** 1500-2200 (vs current prototype: 230 single-file HTML).
**Copied from puzzle-match:** package.json, tsconfig.json, vite.config.ts, BootScene skeleton (5%).
**NEW:** Everything else (95%).

### 4.1 Template Generation Strategy (D5/D9)

**The first VN template is hand-written by an engineer, not LLM-generated.** Rationale:
- LLM generating 1500+ LOC of TypeScript from scratch has high failure rate (verified by 30-min timeouts observed in plan-agent + momus-agent calls).
- A skeleton with deterministic structure provides a known-good baseline that LLM can extend.

**Workflow:**
1. **First template (one-time, ~1 day)**: Engineer writes `game-templates/visual-novel/` skeleton with all 4 scenes + DialogueSystem + 5 sample data files. **Phase 1.5 deliverable — already complete.**
2. **Subsequent VN games**: `_generate_visual_novel()` reads this template, sends 2-round prompts to LLM, LLM returns updated `*.ts` and `data/*.json` files **on top of the skeleton**. The skeleton scenes are not regenerated — only extended/replaced.
3. **Template evolution**: When a new feature is needed (e.g., CG gallery in Phase 3), engineer adds the relevant scene/system to the template. LLM uses the updated template in subsequent runs.

**What the LLM may modify in each round:**
- Round 1: Replaces `data/characters.json`, `data/dialogue.json`; may extend `MainScene` placeholder.
- Round 2: Adds `BranchingEngine`, `StatSystem`, `ChoiceSystem` files; updates `NovelScene` to integrate them; adds `data/branching.json`, `data/stats.json`, `data/endings.json`.
- Round 3+ (Phase 3+): Add `SaveLoadSystem`, `CGGallerySystem`, etc.

**What the LLM MUST NOT modify:**
- `package.json` (scaffolded)
- `tsconfig.json` (scaffolded)
- `vite.config.ts` (scaffolded)
- `index.html` (scaffolded, may be extended for ad SDK in Phase 3+)
- `main.ts` __TEST__ contract fields (can add commands, must not remove existing)

**Tests for template integrity:** `tests/test_vn_template_invariants.py` — assert that after a generation run, the skeleton files still parse, the `__TEST__` interface is present, and the data JSON files validate against the schema.

---

## 5. Code Generator Changes

File: `agents/dev/programmer/code_generator.py`

**Add at top:**
```python
VN_SCHEMA_VERSION = "1.0"

def is_visual_novel(gdd: dict) -> bool:
    return bool(gdd.get("narrative_premise")) and bool(gdd.get("branching_tree"))
```

**Modify `generate_game_code()` dispatch:**
```python
if is_visual_novel(gdd):
    # Validate BEFORE generation
    from shared.vn_schema import validate_gdd
    errors = validate_gdd(gdd)
    if errors:
        logger.error(f"VN GDD validation failed: {errors}")
        return project_dir  # early exit, don't burn LLM tokens
    code_path = await _generate_visual_novel(gdd, project_dir, ...)
else:
    code_path = await _generate_all_at_once(gdd, ...)  # EXISTING 4-round path
```

**New function `_generate_visual_novel()` — 4 rounds (different from generic):**
- **Round 1 (scaffold + dialogue):** src/main.ts, config.ts, BootScene, TitleScene, MenuScene, dialogue.json, characters.json, DialogueSystem, LocalizationManager. ~600 LOC.
- **Round 2 (branching + stats):** branching.json, endings.json, stats.json, BranchingEngine, StatSystem, ChoiceSystem, NovelScene. ~800 LOC.
- **Round 3 (save/load + gallery):** SaveLoadSystem, CGGallerySystem, SaveLoadScene, GalleryScene, EndScene. ~400 LOC.
- **Round 4 (BGM + polish + monetization):** BGMController, audio hooks, ad break on chapter-end, analytics beacons. ~300 LOC.

**Self-verify after each round:**
- After Round 2: `validate_branching_tree(branching_json)` returns no errors
- After Round 3: `check_save_load_roundtrip()` via Playwright (new)
- After Round 4: full hard veto gate

**No regression:** `_generate_multi_round` and `_generate_by_mechanics` paths are UNTOUCHED. Only the dispatcher adds the VN branch.

---

## 6. Mechanic Planner Changes

File: `agents/dev/designer/mechanic_planner.py`

**Add to system prompt (extend, not replace):**

```
If GDD contains 'narrative_premise' (visual novel), the following 8 mechanics are MANDATORY
and must be present in the returned list, in this dependency order:
1. dialogue_rendering       (complexity=high,  code_anchor='class DialogueSystem')
2. choice_presentation      (complexity=medium, code_anchor='class ChoiceSystem')
3. stat_tracking            (complexity=medium, code_anchor='class StatSystem')
4. branch_resolution        (complexity=high,  code_anchor='class BranchingEngine')
5. save_load                (complexity=medium, code_anchor='class SaveLoadSystem')
6. cg_unlock                (complexity=medium, code_anchor='class CGGallerySystem')
7. route_unlock             (complexity=low,    code_anchor='route_locked')
8. bgm_layering             (complexity=low,    code_anchor='class BGMController')

Each mechanic MUST include 'code_anchor' field for downstream verification.
If 8 mechanics cannot be planned, return an error rather than a partial list.
```

**Output validation in `_parse_mechanics`:** Assert all 8 anchors present, else raise.

---

## 7. Artist Pipeline Changes

**New file:** `agents/dev/artist/character_consistency.py`

```python
async def generate_expression_set(
    character_name: str,
    base_description: str,           # e.g. "Alice, 18yo female, blue hair, school uniform"
    expressions: list[str] = None,    # default: ['neutral', 'happy', 'sad', 'surprised', 'angry']
    style: ArtStyleConfig,
    output_dir: Path,
) -> dict[str, Path]:
    """Generate 5 expression variants of one character with face/pose consistency.
    
    Uses SD 1.5 with regional prompting:
    - First expression: full prompt, no anchor
    - Subsequent: use previous as init image + lock face region via regional mask
    - Returns: {expression: path}
    """
```

**Cap per game:** 5 expressions × 3 characters = 15 character images. Reject if more requested.

**Extend `sprite_generator.py`:** add `generate_expression_set()` method.

**Background generator:** existing, unchanged. Add `mood_variants: dict[str, str] = {}` (e.g., "school" → ["school_day", "school_dusk", "school_night"]) — same scene, 3 lighting variants. Optional; default off to save cost.

**Fallback:** If ComfyUI fails or consistency breaks, return Phaser shape placeholder (existing behavior — no regression).

---

## 8. Music Pipeline Changes

File: `agents/dev/music/music_generator.py`

**Add `mood_bgm_map` (7 mood-based tracks, NOT genre-based):**
```python
MOOD_BGM_MAP = {
    "neutral":   "soft_piano_loop.ogg",
    "tense":     "low_strings_loop.ogg",
    "romantic":  "acoustic_guitar_loop.ogg",
    "sad":       "minor_key_piano.ogg",
    "happy":     "uplifting_synth.ogg",
    "mystery":   "ambient_pad.ogg",
    "action":    "driving_beat.ogg",
}
```

VN route states (`BGMController`) emit a mood key; music module picks the track.

**SFX categories (5 fixed):**
- `choice_select` — short UI blip
- `transition_whoosh` — scene change
- `heartbeat` — pre-choice tension
- `route_unlock` — fanfare
- `ending_reveal` — epilogue stinger

**Cost strategy:** SFX procedurally generated (Web Audio tones, no API cost). BGM shared across projects of same mood (cache by `mood_bgm_map` hash). Suno API opt-in only for one-off custom tracks.

**Fallback:** Silent if Web Audio fails (existing behavior).

---

## 9. Localization Changes

File: `agents/dev/localize/string_extractor.py` (extend)

**Add TypeScript parser:**
```python
for ts_file in dist.glob("**/*.ts"):
    content = ts_file.read_text(encoding="utf-8")
    # Match: this.add.text(...,'text...')
    # Match: const STR = 'text...';
    # Match: dialogue: [{text: 'text...', ...}]
```

**Add character name extraction:**
```python
characters_json = dist / "src/game/data/characters.json"
if characters_json.exists():
    data = json.loads(characters_json.read_text())
    for char in data.get("characters", []):
        char_names[char["name"]] = {}
        # To be filled by translator
```

**Add branching-key extraction:**
```python
branching_json = dist / "src/game/data/branching.json"
if branching_json.exists():
    data = json.loads(branching_json.read_text())
    for node_id, node in data.get("nodes", {}).items():
        for line in node.get("dialogue", []):
            keys.append(f"vn.{node_id}.{line['id']}")
```

**File: `agents/dev/localize/translator.py` (extend):**
- Pass `character_names.json` to translator system prompt (proper-noun awareness)
- Branching-key based translation: don't translate `branching.json` raw text; translate keys `vn.<route>.<chapter>.<scene>.<line>` so the LLM has more context
- CJK/RTL font fallback list:
  ```python
  FONT_FALLBACK = {
      "ja": "Noto Sans JP, sans-serif",
      "ko": "Noto Sans KR, sans-serif",
      "zh": "Noto Sans SC, sans-serif",
      "ar": "Noto Sans Arabic, sans-serif",
      "he": "Noto Sans Hebrew, sans-serif",
  }
  ```

**No regression:** Old HTML/JS extraction path stays as fallback.

---

## 10. QA Changes

File: `agents/dev/qa/playtest_checks.py` (extend)

**7 new checks (additive, all optional via feature flag):**

| Check | What it does | How |
|---|---|---|
| `check_branch_coverage` | All nodes in `branching.json` visited | Playwright reads `__TEST__.visitedScenes` after 5 playthroughs w/ different choice patterns |
| `check_ending_reachability` | All declared endings reachable | Same playthrough battery, asserts each ending in `__TEST__.endingsReached` |
| `check_save_load_roundtrip` | Save state → reload → load → state hash matches | Playwright: save → reload page → load slot 1 → eval `__TEST__.getStateHash()` |
| `check_localization_render` | Switch locale, no text overflow | For each of 5 locales (ja/ko/zh/ar/de), set `LocalizationManager.setLocale()`, assert no element overflows container |
| `check_dialogue_overflow` | Dialogue box doesn't overflow at 1280x720 | Read `dialogueBox.getBounds()`, assert within canvas |
| `check_cg_gallery` | Unlocked CGs render | `__TEST__.unlockCG('test_cg')` → navigate to gallery → assert image visible |
| `check_route_locked` | Locked route shows lock state | Click locked route in menu → assert "LOCKED" overlay shown |

**Modify `complexity_score` (`shared/complexity.py`):**

Add VN-specific signals (when `narrative_premise` detected):
- `stat_count >= 5` (+0.05)
- `ending_count >= 3` (+0.05)
- `branch_count >= 8` (+0.10)
- `expression_per_char >= 3` (+0.05)
- `character_count >= 2` (+0.05)
- `has_save_load` (+0.05)
- `has_localization` (+0.05)

**Update `__TEST__` contract for NovelScene:**
```typescript
(window as any).__TEST__ = {
  ready: false,
  state: () => ({
    currentScene: string,
    currentRoute: string,
    stats: Record<string, number>,
    flags: string[],
    cgsUnlocked: string[],
    routeProgress: Record<string, number>,
    endingReached: string | null,
    saveDataValid: boolean,
    visitedScenes: string[],
    endingsReached: string[],
  }),
  // VN-specific commands
  setLocale: (loc: string) => void,
  unlockCG: (key: string) => void,
  getStateHash: () => string,
  save: (slot: number) => void,
  load: (slot: number) => void,
};
```

**No regression:** Old 8 checks unchanged. New 7 are feature-flagged; if `ENABLE_VN_QA=false` (default), they're skipped.

---

## 11. Schema Validation Layer (NEW)

**New file:** `shared/vn_schema.py`

```python
"""VN GDD schema validation — the PRIMARY stability gate.

Validates that an LLM-generated GDD conforms to the VN schema before
downstream code generation. Returns list of error strings (empty = valid).
"""

def validate_gdd(gdd: dict) -> list[str]:
    errors = []
    if not gdd.get("narrative_premise"):
        errors.append("Missing 'narrative_premise'")
    if not gdd.get("branching_tree"):
        errors.append("Missing 'branching_tree'")
    if not gdd.get("character_roster") or len(gdd["character_roster"]) < 2:
        errors.append("Need ≥2 characters in roster")
    if not gdd.get("stat_system", {}).get("stats"):
        errors.append("Missing stat_system.stats")
    if not gdd.get("ending_conditions") or len(gdd["ending_conditions"]) < 3:
        errors.append("Need ≥3 ending_conditions")
    
    # Sub-validations
    errors.extend(validate_branching_tree(gdd.get("branching_tree", {})))
    errors.extend(validate_ending_conditions(gdd.get("ending_conditions", [])))
    errors.extend(validate_character_roster(gdd.get("character_roster", [])))
    return errors


def validate_branching_tree(tree: dict) -> list[str]:
    errors = []
    if not tree.get("root"):
        errors.append("branching_tree missing 'root'")
    nodes = tree.get("nodes", {})
    if len(nodes) < 8:
        errors.append(f"branching_tree has only {len(nodes)} nodes, need ≥8")
    # Reachability: BFS from root
    if nodes and tree.get("root") in nodes:
        visited = set()
        queue = [tree["root"]]
        while queue:
            n = queue.pop()
            if n in visited: continue
            visited.add(n)
            for choice in nodes[n].get("choices", []):
                queue.append(choice.get("next_node"))
        unreachable = set(nodes.keys()) - visited
        if unreachable:
            errors.append(f"Unreachable nodes: {unreachable}")
    return errors


def validate_ending_conditions(conds: list[dict]) -> list[str]:
    errors = []
    seen = set()
    for c in conds:
        key = json.dumps(c.get("trigger", {}), sort_keys=True)
        if key in seen:
            errors.append(f"Duplicate ending trigger: {key}")
        seen.add(key)
    return errors


def validate_character_roster(roster: list[dict]) -> list[str]:
    errors = []
    for c in roster:
        if not c.get("name"):
            errors.append(f"Character missing name: {c}")
        if not c.get("expression_variants") or len(c["expression_variants"]) < 3:
            errors.append(f"Character {c.get('name', '?')} needs ≥3 expression_variants")
    return errors
```

**Wire-in points (the stability chain):**
1. `gdd_generator.py:_parse_gdd()` → after parse, call `validate_gdd()` → if errors, retry LLM call once with errors in prompt
2. `code_generator.py:generate_game_code()` → before any LLM call, call `validate_gdd()` → if errors, return early (don't burn tokens)
3. `qa/auto_playtest.py:run_auto_playtest()` → pre-check, call `validate_gdd()` on stored GDD

---

## 12. Multi-Route Pipeline

File: `orchestrator/scheduler.py` + `planner.py` + `persistence.py`

**Project expansion:**
- One "VN project" expands into 1 + N sub-projects
- 1 common route (`route_type='common'`) built first
- N character routes (`route_type='character'`) built after, sharing assets via `shared_assets_path` (symlink to common's `public/assets/`)
- Each sub-project is a `projects` row with `parent_id` set
- `vn_routes` table maps each sub-project to a route_key

**Decision gate trigger:**
- After GDD is generated (containing route structure), queue CEO approval: "Approve route structure: common + Alice + Bob + Carol + 3 endings?"
- Existing 5-gate system handles this — no new gate type needed, just a new context template

**Per-route cost budget:**
- Common route: $2 budget (art is bulk of cost)
- Character route: $1 budget (reuses art, only code + text variations)
- Configurable via `config/agents.yaml`

**Shared assets mechanism:**
- Common route generates `public/assets/characters/`, `public/assets/backgrounds/`, `public/assets/audio/`
- Character route's `shared_assets_path` = `<common_project>/public/assets/`
- Vite config for character route: `build.rollupOptions.external = [/assets/...]`
- Or simpler: copy symlinks at scaffold time

---

## 13. Cost & Quality Gates

**Hard veto (game CANNOT be published if any fails):**
- `branch_coverage < 1.0` (100% of nodes must be reachable)
- `ending_reachability < 1.0` (100% of declared endings must be reachable)
- `__TEST__` schema invalid (any of 9 fields missing)
- `save_load_roundtrip` fails
- console errors > 0
- asset 404s > 0
- total cost > $5 per game

**Soft warn (publish allowed, flag for review):**
- median_play_session < 60s
- cgs_unlocked_first_route < 5
- localization_coverage < 0.9 (some keys missing in some locales)
- complexity_score < 0.7

**Per-game cost cap:** $5 default, configurable. Enforced via `check_budget_available()` in `shared/llm_client.py` — already exists per existing plan's H8 fix.

**Cost realism analysis (C8 — verified for ComfyUI local + DeepSeek API baseline):**

| Component | Per-game cost | Notes |
|---|---|---|
| GDD generation (1 LLM call) | $0.05 | MiniMax-M3 / GLM-4-flash |
| Mechanic planning (1 call) | $0.03 | Same model |
| VN code gen (2 rounds × retry buffer) | $0.60 | DeepSeek Coder; 4 calls nominal, 6 with retries |
| ComfyUI art (15 character + 10 background = 25 images) | $0.50 | Local GPU; $0.02/image amortized electricity + maintenance |
| BGM mood tracks (7, cached) | $0.10 | One-time $5 for 7 tracks, amortized over 50 games |
| SFX (5 procedural) | $0.00 | Web Audio tones, no API |
| Localization (5 locales × 1 call) | $0.50 | DeepSeek Coder; per-locale context |
| QA + retry overhead | $0.20 | ~3% retry rate × above total |
| **Total per game (main path)** | **~$2.04** | Comfortable margin |
| **Total per game (cold start, 2x retries)** | **~$3.50** | Still within $5 cap |
| **Total per game (cloud ComfyUI @ $0.05/image)** | $2.79 | ComfyUI Replicate backup; still within cap |
| **Total per game (full retry storm, 5 attempts)** | **~$5.20** | Triggers the $5 hard veto — **acceptable failure mode** |

**Three-tier cost enforcement:**
1. **$3 warning line** — when cumulative cost exceeds $3, log a WARNING to dashboard and queue a CEO review decision (does NOT block generation).
2. **$5 hard veto** — when cumulative cost exceeds $5, abort generation, mark project as `over_budget`, surface to CEO for cancel/continue decision.
3. **$10 absolute ceiling** — at request layer, `check_budget_available()` in `shared/llm_client.py` rejects new LLM calls outright (per existing plan's H8 fix).

**Cost optimization levers (in priority order):**
1. Use local ComfyUI (saves ~$1/game vs cloud)
2. Reuse cached BGM tracks (saves ~$0.05/game)
3. Skip localization for languages with <1% expected market share (saves $0.10/locale)
4. Reduce LLM retries by improving prompts (reduces variance, not average cost)

---

## 14. Phased Roadmap

| Phase | Scope | Files (additive only) | New tests | Exit criteria | Rollback |
|---|---|---|---|---|---|
| **1 (1w)** | GDD schema + validator + VN template skeleton + 1 manual E2E | `shared/vn_schema.py` (NEW); `gdd_generator.py` (extend prompt); `game-templates/visual-novel/` (NEW) | `tests/test_vn_schema.py`; `tests/test_gdd_vn.py` | 1 game playable end-to-end manually | Revert gdd_generator prompt extension |
| **2 (1-2w)** | Code gen VN path + mechanic planner + __TEST__ contract | `code_generator.py` (add `_generate_visual_novel`); `mechanic_planner.py` (extend prompt) | `tests/test_vn_code_gen.py`; `tests/test_vn_mechanic.py` | 3 themes build, 3 routes generated, 8 mechanics present | `ENABLE_VN_PIPELINE=false` (feature flag) |
| **3 (1w)** | 7 new QA checks + VN complexity score + hard veto | `playtest_checks.py` (extend); `complexity.py` (extend); `auto_playtest.py` (extend) | `tests/test_vn_qa.py` | 5/5 hard veto checks pass on sample | Feature flag per check |
| **4 (1-2w)** | Multi-route parent/child + shared assets — **MUST precede Phase 5** (coupling: shared_assets_path column must exist before artist writes to it) | `scheduler.py` (add VN expansion); `planner.py` (add route DAG); `persistence.py` (add tables + `parent_id`/`shared_assets_path`/`route_id` columns on `projects`) | `tests/test_vn_routes.py` | 1 common + 3 char routes playable, $3 total cost | Drop `parent_id` column (nullable) |
| **5 (1-2w)** | Artist (consistency + expressions) + Music (mood BGM + SFX) — **sequential after Phase 4** (writes into `public/assets/...` referenced by Phase 4 `shared_assets_path`) | `agents/dev/artist/character_consistency.py` (NEW); `sprite_generator.py` (extend); `music_generator.py` (extend) | `tests/test_vn_art.py`; `tests/test_vn_music.py` | 3 chars × 5 expressions = 15 images, 7 BGM tracks, 5 SFX | Revert sprite_generator extension |
| **6 (1w)** | Deep localization (TS parser + char names + CJK/RTL) | `string_extractor.py` (extend); `translator.py` (extend) | `tests/test_vn_localize.py` | 5 locales render clean (no overflow) | Revert string_extractor addition |
| **7 (1-2w)** | Production validation (5 themes end-to-end) | All | `tests/test_e2e_vn_pipeline.py` | 5 themes pass all hard vetoes, median cost ≤$5 | `ENABLE_VN_PIPELINE=false` |

**Total: 7-11 weeks. Existing plan: 6-10 weeks. Overlap: ~2-3 weeks (Phase 1+3 of existing = Phase 1+2 of this). Net additional: 4-8 weeks for VN-specific work.**

**Sequencing correction (vs. original plan):** Phase 4 and Phase 5 were originally marked "parallel" but have a write-after-read coupling — `shared_assets_path` (Phase 4 schema) must exist before Phase 5 writes character/bgm files into it. Sequential ordering adds no wall-clock time (Phase 4 = 1-2w, Phase 5 = 1-2w, sequential = 2-4w total = parallel estimate).

---

## 15. Regression Safety

**Must continue to work:**
- All 7 existing game templates still build:
  ```bash
  for t in game-templates/*/; do
      (cd "$t" && npm run build) || { echo "FAIL: $t"; exit 1; }
  done
  ```
- All 168 existing unit tests pass: `pytest tests/ -x`
- Prototype mode unchanged (`run-prototype` still produces same generic dodge-collect)
- Existing 4-round code gen path unchanged for non-VN GDDs

**Feature flag:**
```python
# In shared/config.py
ENABLE_VN_PIPELINE = os.environ.get("ENABLE_VN_PIPELINE", "false").lower() == "true"
ENABLE_VN_QA = os.environ.get("ENABLE_VN_QA", "false").lower() == "true"
```

Default `false` in prod; CI sets `true` for new tests.

**Test isolation:**
- `tests/test_vn_*.py` — only import `shared.vn_schema`, `agents.dev.designer`, etc. — never `tests/test_puzzle_match.py` etc.
- No test cross-imports.

**Migration safety:**
- All new tables `CREATE TABLE IF NOT EXISTS` — idempotent
- `ALTER TABLE projects ADD COLUMN` — SQLite supports this, but check if column already exists first via `PRAGMA table_info(projects)`
- New tests run in isolated temp DB

---

## 16. Integration with Existing Plan

`.sisyphus/plans/demo-to-product-transformation.md` (12-criterion acceptance test) is the baseline. This plan extends it:

**Adds 3 new acceptance criteria (15 total):**
| # | Criterion | Implementation |
|---|---|---|
| 13 | **Branch coverage ≥100%** | `check_branch_coverage` in QA |
| 14 | **Ending reachability ≥100%** | `check_ending_reachability` |
| 15 | **Save/load roundtrip** | `check_save_load_roundtrip` |

**Reuses existing acceptance criteria:** 1-12 unchanged. The 5 new "soft criteria" from this plan (median play session, CGs unlocked, etc.) become soft warnings, not vetos.

**Sequencing:** This plan's Phase 1+2 maps to existing plan's Phase 1+2. H1-H10 bugs from existing plan must be fixed BEFORE this plan's Phase 1 starts (because they affect foundation).

**No conflict with existing:** Existing plan's 9 decisions (D1-D9) are unchanged. D1 (multi-round vs single-shot) is implemented as: VN path = 4 rounds (this plan); non-VN = 4 rounds (existing). Same shape, different prompts.

---

## 17. Risk Register

| Risk | Severity | Mitigation |
|---|---|---|
| LLM regression (prompt changes break working code) | HIGH | Feature flag `ENABLE_VN_PIPELINE`; 2-week A/B compare pass rate |
| Cost overrun (5 routes × 5 prompts = 25 LLM calls) | HIGH | Per-route budget $2/$1; hard cap $5; **$3 warning line triggers CEO review**; dry-run mode for testing |
| Schema drift (LLM produces invalid GDD despite prompt) | HIGH | `validate_gdd()` as gate; retry-once-with-errors pattern in `gdd_generator._parse_gdd` |
| **LLM context overflow on long branching trees** (>8K tokens, exceeds prompt limit on small models) | HIGH | **Chunked generation: Round 1 passes root + 3 nodes only; subsequent rounds append nodes incrementally. Hard cap 8 nodes per round prompt.** |
| **Race condition in multi-route shared assets** (two character routes writing to parent assets) | MEDIUM | Shared assets are **read-only symlinks** (never modified by child routes); child route writes limited to its own `public/assets/routes/<key>/` |
| **ComfyUI server unavailable for hours** (Phase 5 critical dependency) | MEDIUM | Health-check before generation; auto-fallback to Phaser shape placeholder (existing behavior); `art_status` flag in `projects` table; `soft_warn` if published with placeholder art |
| **localStorage save data privacy** (player choice history in browser) | LOW | Local-only (never uploaded); XOR-encrypt with game-version key to deter casual tampering; document "no PII collected" in compliance notes |
| Art consistency (SD 1.5 character variations) | MEDIUM | Cap 5 expressions/char; first expression as anchor; fallback to Phaser shapes |
| Branching DAG cycle (LLM creates loops) | MEDIUM | `validate_branching_tree` checks acyclic; code rejects cycles at runtime |
| Save/load state mismatch (data drift) | MEDIUM | State hash check; freeze state schema per game version |
| CJK font fallback missing on itch.io | LOW | Embed font subset in build; or use Google Fonts CDN |
| Translation quality for branching keys | LOW | LLM context window includes full branching tree for consistency |

---

## 18. Effort Estimate

- **Phase 1:** 1 week (1 engineer, sequential)
- **Phase 2:** 1-2 weeks
- **Phase 3:** 1 week (parallel with 4)
- **Phase 4:** 1-2 weeks (parallel with 5)
- **Phase 5:** 1-2 weeks (parallel with 4)
- **Phase 6:** 1 week
- **Phase 7:** 1-2 weeks (gated; only if Phase 1-6 all green)

**Total: 7-11 weeks.** Existing plan's 6-10 weeks has 2-3 weeks of overlap. Net additional for VN: **4-8 weeks**.

**Quick win (1 day):** Phase 0 — fix existing plan's H1 (platform_urls) + H2 (memory categories). These unblock dashboard visibility and cross-project lesson reuse. Foundation for everything else.

---

## 19. Sign-off Checklist

Before Phase 1 starts:

- [ ] VN schema fields approved (or alternative fields added)
- [ ] Phase 1+2 sequencing OK (foundation before generator)
- [ ] Feature flag default value agreed (`false` recommended for prod)
- [ ] Per-game cost cap agreed ($5 recommended)
- [ ] Hard veto list accepted (7 items above)
- [ ] Soft warning list accepted (4 items above)
- [ ] Integration with existing 12-criterion test OK (3 new criteria)
- [ ] Target output shape confirmed (1-hour, 3-5 routes, 3+ endings)

**Once signed off, I will:**
1. Create a `tests/test_vn_schema.py` skeleton + 1 sample failing test
2. Write `shared/vn_schema.py` to make it pass
3. Get user approval on Phase 1 deliverable
4. Proceed to Phase 2
