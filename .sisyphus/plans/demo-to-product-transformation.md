# GCAgents: Demo → Mature Product Transformation Spec

**Status:** Draft for review
**Author:** Sisyphus + Metis strategic analysis
**Goal:** Transform GCAgents from a fast demo-generator into a batch-production system for mature, shippable web mini-games.

---

## 1. Executive Summary

The system is **~60% of the way** to a product company. The architecture is sound, the throughput is impressive (5-15 min/game, 2000-3000 LOC Phaser 4), and the agent infrastructure is well-designed. The remaining 40% is **integration, verification, and operational discipline — not new features**.

**The single most important insight:** The system currently has a *fast, no-veto* production model. It will happily mark an unplayable game (e.g., Block Merge's 60-px click-offset bug) as "complete" because no agent has the authority to say "this is not shippable." **The transformation is fundamentally about adding a hard quality gate**, not about adding more agents or features.

**Estimated effort:** 6-10 weeks for one engineer full-time. **Top quick win:** Fix B1 (platform_urls persistence) and B2 (memory category mismatch) in 1 day combined — these unlock dashboard visibility and cross-project learning respectively.

---

## 2. The Gap: Demo vs Product

| Dimension | Current (Demo) | Target (Product) | Gap to Close |
|---|---|---|---|
| Click hit rate | 0% (60-px offset ships) | ≥95% on known elements | Coordinate-convention enforcement + hit-region test |
| Mechanic completeness | 30-50% (LLM drops with "for simplicity") | 100% (grep-verified per GDD) | Mechanic manifest contract |
| Game loop | No game-over, no win condition | Start → Play → Lose/Win → Restart in 60s | Mandatory game-over check + simulation |
| Asset integrity | 404s on bgm.js, sfx.js, art paths | All referenced assets exist pre-build | Pre-flight asset check |
| Code organization | 41 .ts files, duplicates (Board.ts in 2 dirs) | ≤15 .ts files, single source of truth | File-count cap + 2-round gen (not 4) |
| Cross-platform | Only itch.io URL stored | itch + CrazyGames + Pokí URLs persisted | platform_urls DB column |
| Cost awareness | $0 enforcement, defaults to $5/mo budget | Per-game cost visible, total budget enforced | Wire check_budget_available into LLM client |
| Memory & learning | Lessons exist but 0% consumed | Cross-project lessons surface in prompts | Fix category mismatch (B2) |
| Verification | 168 unit tests, 0 integration | Tests cover playability, click flow, asset existence | Add tests/integration/ with real playthroughs |
| Throughput | 1 game in 5-10 min (prototype) | 3-5 games/week at acceptance-criteria quality | Quality engine + parallel orchestration |

**The pattern:** the system can produce output fast, but it doesn't know when output is "good enough" to ship. Every fix below is in service of teaching the system what "good enough" means.

---

## 3. Quality Bar: 12-Criterion Acceptance Test

A generated game is "mature" only if **all 12 criteria pass**:

| # | Criterion | How to verify |
|---|-----------|---------------|
| 1 | **Functional playability** — click on every GDD-listed input changes `__TEST__` state | Playwright click + assert |
| 2 | **Mechanic completeness** — 100% of GDD mechanics have a code reference | grep across bundle |
| 3 | **Game loop closure** — Start → Play → Lose-or-Win → Restart reachable in 60s | Playwright simulation |
| 4 | **Asset completeness** — every load.image/GameBGM/GameSFX reference resolves | Pre-build asset check |
| 5 | **Coordinate consistency** — visual bbox matches click hitbox (≤2px) | Playwright click known elements |
| 6 | **Build hygiene** — `npm run build` zero warnings, no `any`, ≤15 .ts files | Build pipeline |
| 7 | **Cross-platform deployability** — runs in Chromium + Firefox + 1 mobile | Browser test matrix |
| 8 | **Visual quality floor** — ≥1 tween, ≥1 particle, ≥1 sound effect, consistent palette | Static inspection |
| 9 | **Session length** — median play session ≥3 min | `__TEST__.sessionTime` |
| 10 | **`__TEST__` contract compliance** — all 6 fields populated; `enemyTypesSeen` non-empty after 30s | AST-grep + runtime |
| 11 | **Post-deploy observability** — each deploy registers metrics + analytics beacons fire | DB row + endpoint hit |
| 12 | **Feedback ingestion** — published game collects comments within 24h, categorized | feedback_collector hook |

**Anti-criteria** (what "mature" is NOT):
- "It compiled" ≠ mature (ceo-1780397376 compiled and is unplayable)
- "QA passed" ≠ mature (pixel-diff passed despite 0% click hit rate)
- "It's on itch.io" ≠ mature
- "Many files = complex" ≠ mature (41 files with duplicates < 15 unique files)
- "Prototype mode works" ≠ mature (it's a dodge-template smoke test, not AI generation)

---

## 4. Hidden Requirements (the 10 things that must be fixed)

These are problems the user didn't explicitly mention but the system silently needs:

| # | Issue | File:Line | Why it matters |
|---|-------|-----------|----------------|
| **H1** | `platform_urls` not persisted | `persistence.py:170-189` (schema), `scheduler.py:1080-1084` | Multi-platform deploy is publish-only; URLs vanish |
| **H2** | Memory lesson category schema mismatch | `memory.py:234-269` vs `code_generator.py:409` | Every project starts from zero context |
| **H3** | Global coordinate convention missing | `Board.ts:52` vs `GameScene.ts:50` | 100% of grid games have click-offset bugs |
| **H4** | `__TEST__` contract drift | Bundle search: `enemyTypesSeen`/`powerupsUsed`/`isGameOver` count = 0 | QA gameplay-depth check is bypassed |
| **H5** | Audio asset 404s | `public/assets/audio/` empty; index.html references bgm.js/sfx.js | Silent runtime failure |
| **H6** | Mechanic truncation | `GameScene.ts:70` admits "Not implemented for simplicity" | 30-50% of GDD mechanics silently dropped |
| **H7** | No feedback loop | `feedback_collector.py` exists but not in scheduler tick | Published games never get updated |
| **H8** | No cost ceiling | `check_budget_available` never called from agents | 5 games/month blows $5 budget |
| **H9** | Project ID collision | `data/games/` has 2x "Merge Pet Paradise" folders | Mass production wastes money on duplicates |
| **H10** | 4-round generation creates duplicates | `Board.ts` in both `entities/` and `systems/` | 60% of files are dead/duplicate |

---

## 5. 9 Critical Decisions to Make

| # | Decision | Recommendation | Rationale |
|---|----------|----------------|-----------|
| **D1** | **Multi-round vs single-shot generation** | **2 rounds** (scaffold+config then full impl). Drop rounds 3-4. | 4 rounds = 4 chances to break integration. Round 2-4 re-implement what round 1 just did. |
| **D2** | **Quality vs speed** | **3-5 games/week, quality-tuned** | 1/week doesn't justify ops cost; 5+/week is unachievable today. 3-5 matches `max_dev_projects=3` policy. |
| **D3** | **Auto-publish vs human gate** | **Tiered**: auto-publish to itch (low risk), require approval for CrazyGames/Poki | Mass production needs ≥1 no-touch path. itch is lowest-stakes. |
| **D4** | **Custom art vs procedural** | **Procedural Phaser shapes as default, ComfyUI as upgrade** | Reliability > polish. ComfyUI depends on a local server; not always up. |
| **D5** | **Real BGM (Suno) vs procedural** | **Procedural Web Audio default, Suno opt-in** | License risk + availability. Most successful web games ship procedural. |
| **D6** | **Templates per genre vs freeform** | **5 genre templates** (puzzle, runner, shooter, defense, idle) with strong guidance | Freeform produces 41-file games with broken integration. Templates constrain LLM to make the *right* decisions. |
| **D7** | **Memory consolidation frequency** | **Per-project at publish, prune weekly** | Mid-frequency, mid-volume gives best signal-to-noise. |
| **D8** | **Auto-cancel vs human cancel** | **Auto-cancel on Tier-1 failure (3+ QA fails), auto-pause on cost overrun (>80% budget)** | Decides fast. Reduces 5-gate friction by 60%. |
| **D9** | **Code review skill value** | **Demote to soft check or kill** | Current 500-token glm-4-flash review is theatre, not quality control. |

---

## 6. 6-Phase Roadmap

### Phase 1 — Foundation Fixes (1 week, sequential)
*Goal: fix the 5 known blocking bugs. No new features.*

- 1A: Fix H1 — add `platform_urls` column to `projects` table, save on deploy. Test: deploy to fake 3 platforms, assert all 3 URLs in DB.
- 1B: Fix H2 — choose `lesson:programmer` as canonical, update `memory.py:264`. Test: run code gen with prior project, assert lessons appear in prompt.
- 1C: Fix H3 — add `__GAME_CONFIG__` single source of truth in `config.ts`, document in PROGRAMMER_SYSTEM_PROMPT. Test: 3 sample games, click known block positions, assert hit.
- 1D: Fix H8 — wire `check_budget_available` into LLM client. Test: budget=$0, attempt code gen, assert refusal.
- 1E: Fix H9 — use `uuid.uuid4().hex[:8]` as project_id; friendly name as separate `display_name`.

**Exit criteria:** 168 unit tests + 3 new integration tests pass.

### Phase 2 — Real Verification (1-2 weeks, can run in parallel with Phase 3)
*Goal: build the 12-criterion acceptance test as automated gates.*

- 2A: Add `mechanic_completeness_check` to QA.
- 2B: Add `asset_existence_check` — pre-build, all `this.load.image()` / audio references must resolve.
- 2C: Add `gameplay_flow_check` — Playwright simulates 60s of play, asserts game-over screen reached.
- 2D: Add `__TEST__` schema validator — AST-grep for the 6 required fields, fail build if missing.
- 2E: Add `file_count_check` — fail if >15 .ts files.
- 2F: Add `click_region_check` — for grid games, click every grid cell, assert hit rate ≥95%.
- 2G: Add `asset_404_check` — Playwright captures console errors, fail on 404.

**Exit criteria:** All 7 verifiers integrated. Manual run on 3 existing games: 1/3 pass, 2/3 fail with specific reasons.

### Phase 3 — Pipeline Restructure (2-3 weeks, sequential)
*Goal: replace 4-round generation with 2-round + 5 genre templates.*

- 3A: Drop rounds 3-4. Round 1 = scaffold + config + file manifest. Round 2 = full implementation in 1 call. Manifest enforces file paths.
- 3B: Build 5 genre templates:
  - **puzzle** (match-3, merge, sokoban)
  - **runner** (endless, side-scroller)
  - **shooter** (top-down, bullet-hell)
  - **defense** (tower, lane)
  - **idle** (clicker, merge-idle)
  Each template: pre-cooked coordinate system, game-over pattern, progress pattern, sample palette.
- 3C: Switch default art fallback from "Phaser shapes" to "genre template visuals" (curated palettes + tween patterns).
- 3D: Auto-gen procedural audio per genre (chiptune for arcade, ambient for puzzle, etc.) as default.

**Exit criteria:** Run 10 projects through new pipeline, measure:
- File count: median ≤15 (was 41)
- Acceptance test pass rate: ≥50%
- Cost per game: ≤$5

### Phase 4 — Iteration Loop (1 week, parallel with Phase 5)
*Goal: published games receive feedback and update automatically.*

- 4A: Wire `feedback_collector` into scheduler tick (every 30 ticks).
- 4B: Add update-phase routing for live games with ≥2 unprocessed feedback items.
- 4C: Add version bump + changelog on each update.

**Exit criteria:** 1 published game receives feedback → update task created → updated version deployed.

### Phase 5 — Operator Visibility (1 week)
*Goal: dashboard shows pipeline health, cost, and lesson effectiveness.*

- 5A: Per-project cost + time-in-phase + last-error view.
- 5B: Live project list with health (passing acceptance test? Y/N).
- 5C: Lesson effectiveness (count + how often referenced in prompts).
- 5D: CFO tick — weekly spend report.

**Exit criteria:** Dashboard renders all 4 views. CFO report generated automatically.

### Phase 6 — Production Hardening (1-2 weeks, gated)
*Goal: validate end-to-end with 5 production-quality games.*

- 6A: Run 5 projects through full cycle. Measure: time, cost, playability rate, session length.
- 6B: Iterate on top failure mode (whichever acceptance criterion fails most).
- 6C: Tune genre templates based on real playability data.
- 6D: Set `production_mode` flag that disables debug logging + forces stricter gates.

**Exit criteria:** 3 of 5 projects pass all 12 acceptance criteria. Median cost ≤$5. Median time-to-deploy ≤90 min.

---

## 7. Success Metrics (5 Tiers)

**Tier 1 — "It works":** 95% of generated games pass 12-criterion test. 100% of completed games have working itch.io URL.

**Tier 2 — "It plays":** Median play session ≥3 min. 10% of players reach level 2+. Game-over rate <80% in first 30s.

**Tier 3 — "It monetizes":** ≥1 game/week published. ≥1% of completed games have ≥10 plays in first week. Cost per game ≤$5.

**Tier 4 — "It learns":** Memory lessons accumulate: 50+ `lesson:programmer` entries after 30 projects. File count: 41 → ≤15. Dedup rate >95%.

**Tier 5 — "It scales":** 3+ projects in parallel without scheduler timeout. Tick interval ≤5 min for full cycle. Cost per cycle ≤$3.

**Key KPIs:**
- **Playability rate** = `games_passing_acceptance_test / games_generated`. Target: ≥0.7
- **Time-to-deploy** = `deploy_time - proposal_creation_time`. Target: ≤90 min
- **Cost-per-game** = `api_cost_total / games_completed`. Target: ≤$5
- **Lesson utilization** = `lessons_referenced_in_prompts / lessons_in_db`. Target: ≥0.3 (currently 0)
- **Cross-platform reach** = `unique_platforms_with_successful_deploy / platforms_attempted`. Target: ≥0.6

---

## 8. Top Risks & Mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| **LLM regression** — every prompt change risks breaking what works | HIGH | Feature-flag new pipeline, A/B run both for 2 weeks, compare acceptance test pass rate |
| **Cost overrun during transition** — burn 2-3× normal cost while iterating | HIGH | Hard $20 budget cap during Phase 1-3; relax only after acceptance test is reliable |
| **Genre template sameness** — if templates too rigid, all games look the same | MEDIUM | Start with 2 templates, iterate to 5 based on playability data + LLM creativity guard |
| **Quality bar too high to hit** — 12 criteria is ambitious | MEDIUM | Phase 6 is gated; if 3/5 don't pass, lower Tier 2 thresholds (session length) before rejecting template design |
| **Suno licensing** — commercial use unclear | LOW | Use procedural Web Audio as default; Suno only as opt-in with user license confirmation |
| **Platform policy** — CrazyGames/Poki have strict content review | LOW | Research first; add content-policy check before auto-deploy to these platforms |

---

## 9. Recommended First Slice

**Phase 1 + 2 = ~2.5 weeks. After this, the system is "quality-controllable" even if slow. That's the product-grade threshold.**

Specifically, week 1:
- **Day 1**: Fix H1 (platform_urls) — 4-hour data model change.
- **Day 2**: Fix H2 (memory categories) — 1-hour schema fix + 1-hour consumer update.
- **Day 3-4**: Fix H3 (coordinate convention) — declare `__GAME_CONFIG__`, document in system prompt, add 3 sample games to test.
- **Day 5**: Fix H8 (cost ceiling) — wire `check_budget_available` into LLM client.
- **End of week 1**: All 5 known blocking bugs fixed. 168 + 3 new tests pass.

Week 2-3: build the 7 verifiers in Phase 2. After week 3, **no unplayable game can be marked complete**.

---

## 10. Open Questions for the User

1. **Quality bar:** Is "Itch.io featured" quality the target, or just "deployable, plays for 3+ min, no critical bugs"? (Affects Phase 3 template design)
2. **Throughput:** Is 3-5 games/week the target, or 1/week at higher quality? (Affects Phase 6 cadence)
3. **Platform priority:** Is itch.io the primary platform for the next 3 months, with CrazyGames/Poki as stretch goals? (Affects H1 + D3)
4. **Human gates:** Should the 5 existing decision gates be reduced to 2 (publish to non-itch + cancel)? (Affects D3)
5. **Code review skill:** Demote to soft check, kill, or upgrade to a real model? (Affects D9)

---

## 11. Sign-off Checklist

Before we start Phase 1, please confirm:

- [ ] Quality bar (12 criteria) is the right definition of "mature" for our context
- [ ] 6-phase roadmap sequencing makes sense
- [ ] Phase 1+2 as first slice (2.5 weeks) is approved
- [ ] Decisions D1-D9 are accepted as recommended, or alternative chosen
- [ ] Open questions above are answered

**Once signed off, I will:**
1. Use the `plan` agent to write a detailed task breakdown for Phase 1
2. Use `momus` to review the plan for verifiability
3. Wait for your final go-ahead before writing any code
