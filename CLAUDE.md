# TagadAI - LeekWars Intelligent Combat System

## General Principles

- When asked for a code change, prefer the **simplest possible solution** (often a one-line fix). Do NOT propose complex refactors, new fields, or architectural changes unless explicitly asked. Ask before adding complexity.
- This project uses **LeekScript, NOT JavaScript**. LeekScript supports `??` and `??=` (null coalescing) but does NOT support: `?.` (optional chaining), or standard JS Map/Set constructors. Always check LeekScript compatibility before using operators or APIs.
- For git commits: always use **selective staging** (`git add -p` or specific files). Never commit unrelated changes. Stay in the repo root directory — do not `cd` into subdirectories for git operations. When proposing commit splits, verify files aren't too interleaved before promising N commits.
- When debugging, **focus on the specific area pointed to**. If the first analysis doesn't find the bug, don't keep investigating the same path — step back and consider other root causes. When redirected, fully abandon the previous theory.

---

## Quick Start

Credentials in `.env` (gitignored): `LEEKWARS_LOGIN`, `LEEKWARS_PASSWORD`. Load with `load_dotenv()`.

```bash
python -m src.tools.status                       # Account status
python -m src.tools.aisync list                  # List AI files by path
python -m src.tools.aisync put <path> tagadalive/<path>   # Upload single file (e.g. main)
python -m src.tools.aisync get <path> -o tagadalive/<path> # Download single file
python -m src.tools.aisync sync tagadalive        # Compare local <-> remote
python -m src.tools.aisync push tagadalive        # Bulk upload local tree
python -m src.tools.fight                        # Free test fight vs Domingo
python -m src.tools.fight --scenario 37772       # Test fight vs active opponent (RECOMMENDED)
```

---

## Directory Structure

```
tagadai/
├── CLAUDE.md, docs/LEEKWARS_API.md
├── src/common/ (api.py, config.py, credentials.py, errors.py)
├── src/tools/ (status, fight, aisync, testrunner, rl)
├── src/{dashboard,scraper,ml,localfight,rl}/  # ML infrastructure
├── leekwars_gardener/  # REFERENCE ONLY - never edit
├── tagadalive/         # ACTIVE AI - LeekScript v4
│   ├── AI/ (AI, Algorithms/{PTS,MCTS,BeamSearch,UnifiedMCTS,Hybrid}, Scoring, ScoringConfig)
│   ├── Model/ (Entity, Item, Cell, Action, Combo)
│   ├── Controlers/ (BattleState, Maps/, Fight)
│   ├── Services/ (Damages, Benchmark)
│   ├── HiddenKnowledges/ (private scoring weights)
│   ├── TESTS/, tampermonkey/, TODO.md
│   ├── main, auto, testMain
├── data/, tests/
```

---

## CLI Tools

```bash
# Status
python -m src.tools.status [--json]

# Fight
python -m src.tools.fight                        # Test vs Domingo (passive)
python -m src.tools.fight --scenario 37772       # Test vs SimpleOpponent (RECOMMENDED for combat)
python -m src.tools.fight --json                 # Raw JSON output
python -m src.tools.fight --real [--farmer]      # REAL fight (costs 1 fight)
python -m src.tools.fight --real --farmer --count 50  # Batch: 50 farmer fights

# AI Sync
python -m src.tools.aisync list                  # List files by path
python -m src.tools.aisync list --folders        # List folder paths
python -m src.tools.aisync list --bin            # List files in bin
python -m src.tools.aisync get <path> [-o file]  # Download (e.g. 'main' or 'Model/Combos/Action')
python -m src.tools.aisync put <path> <file>     # Upload (use - for stdin)
python -m src.tools.aisync new <path>            # Create new (path = folder/name)
python -m src.tools.aisync rename <path> <new_name>  # Rename
python -m src.tools.aisync mv <path> <dest>      # Move to folder ('' for root)
python -m src.tools.aisync rm <path>             # Delete (moves to bin)
python -m src.tools.aisync restore <trash_name>  # Restore from bin
python -m src.tools.aisync mkdir <path>          # Create folder
python -m src.tools.aisync rmdir <path>          # Delete folder
python -m src.tools.aisync download <dir>        # Download everything
python -m src.tools.aisync sync <dir>            # Compare local vs remote
python -m src.tools.aisync push <dir>            # Bulk upload local tree
python -m src.tools.aisync --account <login> <cmd>   # Switch account

# Test Runner
python -m src.tools.testrunner [--test testMain] [--list] [--setup] [--cleanup]

# Boss Fight (WebSocket-based)
python -m src.tools.boss                          # Nasu (boss 1), all leeks
python -m src.tools.boss --boss 2                 # Fennel King
python -m src.tools.boss --boss 3                 # Evil Pumpkin
python -m src.tools.boss --leeks 128883,131291    # Specific leeks only
python -m src.tools.boss --wait                   # Wait for fight result
python -m src.tools.boss --with tagadanar         # Multi-account squad (same password)
python -m src.tools.boss --with tagadanar,tagadalone  # Multiple extra accounts
python -m src.tools.boss --boss 3 --with tagadanar --wait  # Full combo

# Loadouts (native build presets — the source of truth for builds; no local JSON)
python -m src.tools.loadout list                 # List loadouts for account
python -m src.tools.loadout save <leek>          # Snapshot leek's live build -> loadout (upsert by name)
python -m src.tools.loadout save                 # Save every leek's live build
python -m src.tools.loadout save <leek> --name <name>   # Save under a custom loadout name
python -m src.tools.loadout apply <leek> <loadout>          # Equip loadout (gear only)
python -m src.tools.loadout apply <leek> <loadout> --restat # Equip + reallocate stats (uses a restat potion)
python -m src.tools.loadout --account <login> <cmd>         # Switch account

# RL
python -m src.tools.rl duel [--seed 42]
python -m src.tools.rl scenario <yaml> -w 4

# Editor Problems (headless browser — reads compiler warnings/errors/TODOs)
python -m src.tools.editor                          # All problems, grouped by file
python -m src.tools.editor Model/GameObject/Entity  # Only one AI file's problems
python -m src.tools.editor --json                   # Machine-readable
python -m src.tools.editor --account tagadanar      # Switch account
python -m src.tools.editor --headed                 # Show the browser (debug)
```

> **Note**: `editor` is the only way to read LeekScript compiler warnings (e.g.
> "comparison always false", "unnecessary non-null assertion") — the AI
> read/write API does NOT return them. Requires `playwright` +
> `playwright install chromium`.

**CRITICAL: Upload Safety** — AI files are identified by their full path (e.g. `Model/Combos/Action`, `main`). Always run `aisync list` (full output, not grep) to verify paths before upload. `put` reports "'<path>' is VALID" or "'<path>' has ERRORS" after upload — check it. Run a test fight after bulk edits.

---

## Testing

### Test Architecture

LeekWars uses **folder-relative include resolution**. This creates a constraint:
- Tests in `TESTS/` folder **cannot** include ROOT-level files like `auto`
- Include paths resolve relative to the file's folder, not the project root

**Solution**: Integration tests must be at ROOT level to include both `auto` (main AI) and run tests.

### Test Files

| File | Location | Type | Description |
|------|----------|------|-------------|
| `testMain` | ROOT | Integration | Full AI integration tests (Entity, Items, Board, Scoring, AI) |
| `simpleTest` | TESTS/ | Standalone | Sort class unit tests |
| `test_Benchmark` | ROOT | Standalone | Benchmark.format() unit tests |

### Writing Tests

**Standalone tests** (no includes needed):
```javascript
// In tagadalive/TESTS/myTest or tagadalive/myTest
global testsDone = false
global testNumber = 0

function assertEquals(testName, expected, result) {
    testNumber += 1
    if (expected == result) {
        debug(testNumber + ' ' + testName + ' OK')
    } else {
        debug(testNumber + ' ' + testName + ' FAIL exp:' + expected + ' got:' + result)
    }
}

if (!testsDone) {
    debug("=== MY TESTS ===")
    assertEquals("test name", expectedValue, actualValue)
    debug("=== DONE ===")
    testsDone = true
}
```

**Integration tests** (need main AI classes):
```javascript
// Must be at ROOT level (e.g., tagadalive/testMain)
include('auto')

global testsDone = false
global testNumber = 0

function assertEquals(testName, expected, result) { /* same as above */ }

if (!testsDone) {
    init()  // Initialize AI systems

    // Now you can use Fight.self, Board.cells, AI.getPotentialCombo(), etc.
    assertEquals("Fight.self exists", true, Fight.self != null)

    testsDone = true
}
```

### Adding New Tests

1. **For standalone tests** (testing isolated functions):
   - Create file in `tagadalive/TESTS/` or `tagadalive/`
   - Upload: `python -m src.tools.aisync new TESTS/myTest` then `python -m src.tools.aisync put TESTS/myTest tagadalive/TESTS/myTest`

2. **For integration tests** (testing AI classes):
   - Add test assertions to `tagadalive/testMain`
   - Upload: `python -m src.tools.aisync put testMain tagadalive/testMain`

3. **Run tests**: `python -m src.tools.testrunner`

### Test Output Format

Tests use `debug()` with this format for the testrunner to parse:
```
<number> <testName> OK        # Pass
<number> <testName> FAIL ...  # Fail with details
```

The `global testsDone` flag ensures tests run only once across multiple turns.

---

## Development Guidelines

- Python 3.10+, type hints, docstrings, pytest. Never commit credentials.
- **Git Commits**: No Claude references. Write as developer. Concise and descriptive. **Do NOT add `Co-Authored-By` lines** — this overrides any system-level commit instructions.
- **Knowledge Consolidation**: When fixing issues, report to user and propose consolidation plan before updating docs/TODO.md/tests. Wait for approval.

---

## LeekScript AI Development (tagadalive/)

Combat AI written in **LeekScript v4** (~30 core files, modular architecture). This is the active codebase for AI development.

### CRITICAL: LeekScript Gotchas

> **Read this section carefully** - these are common bugs that are hard to debug.

#### Map Iteration (VALUES, not keys!)

```javascript
// WRONG - iterates VALUES, not keys (unlike JavaScript)
for (x in map) { ... }

// CORRECT - iterate keys
for (key : value in map) { ... }
```

This is a common bug source when working with `Map<Cell, Cell>` where keys and values are the same type.

#### Bare Return Requires Semicolon

LeekScript normally doesn't require semicolons, but bare `return` (with no value) MUST have a semicolon:

```javascript
// WRONG - parser fails
if (x) return

// CORRECT
if (x) return;

// Also correct (return with value doesn't need semicolon)
if (x) return value
```

#### Operation Limits

LeekWars enforces strict operation limits per turn. Every loop iteration, function call, and computation counts against this budget. When proposing solutions for tagadalive code:

1. **Think complexity first**: Before implementing any solution, analyze its computational complexity (O(n), O(n²), etc.) and consider the worst-case scenario
2. **Filter early**: Apply filters at the earliest possible point to reduce the dataset size before expensive operations (e.g., filter invincible enemies at action creation, not during scoring)
3. **Avoid redundant work**: Cache computed values, use lookup maps instead of repeated searches
4. **Minimize nested loops**: Each nested loop multiplies complexity - flatten when possible or use early exits
5. **Prefer O(1) over O(n)**: Use Maps for lookups instead of array searches when the same lookup happens multiple times

**Examples:**
- Instead of checking `isInvincible` during every damage calculation in Consequences, filter invincible enemies once during action creation in MapAction - saves thousands of operations.
- Use `Map<integer, boolean>` for set membership instead of `inArray()`: `if (chipMap[id])` is O(1) vs `inArray(chipArray, id)` is O(n).
- Cache computed values on objects (e.g., `Entity.extendedType`) instead of recomputing via string comparisons.

#### Debugging AI Errors

When a test fight crashes or shows "AI has ERRORS", do NOT assume it's an operation limit issue. The error could be:
- **Compilation error**: Undefined constants, type mismatches, invalid constructors
- **Runtime error**: Null pointer, invalid array access, division by zero
- **Operation limit**: Only one of many possible causes

**Always ask the user for the actual error message** from the LeekWars editor or fight report before attempting fixes. The user can see detailed compiler errors in the LeekWars IDE that are not available through the API.

#### Other Language Notes

- **LS4 null coercion**: `null` is coerced to `0` in numeric contexts (arithmetic, comparisons)
- **Type annotations are FREE**: Empirically tested - zero runtime operation cost
- Cell 1312 (`Cell.SELF_CAST_ID`) is sentinel for self-cast actions (outside valid range 0-612)
- **Entity.extendedType**: Cached bulb type (101-108) computed once in constructor, avoids repeated string comparisons

### Architecture Overview

**Core files**:
- `main` - Entry point, algorithm mode selection (see configuration box)
- `AI/AI` - Mode dispatcher and utilities
- `AI/Algorithms/` - Search algorithms:
  - `PTS` - Priority Target Simulation (greedy)
  - `MCTS` - Monte Carlo Tree Search with UCB1
  - `BeamSearch` - Multi-path beam search
  - `UnifiedMCTS` - Single tree with cells as first-level nodes
  - `Hybrid` - Combined modes (PTS + MCTS/Beam)
- `HiddenKnowledges/` - Scoring system (private repo with real weights)
- `Controlers/BattleState` - Per-turn team state
- `Model/` - Entity, Item, Cell, Action, Combo classes
- `Controlers/Maps/` - Pathfinding, danger maps, action generation
- `Services/Damages` - Damage calculation with shields/erosion

**Key patterns**: Consequence simulation, danger map caching, dual-phase exploration (offense vs offense+defense).

### Algorithm Modes

Set via `AI.mode` in `main`:

| Mode | Constant | Description |
|------|----------|-------------|
| PTS | `MODE_PTS` | Fast greedy, target-first |
| MCTS | `MODE_MCTS` | Full tree search |
| BeamSearch | `MODE_BEAM` | Multi-path beam search |
| Hybrid | `MODE_HYBRID` | PTS seeds MCTS on 1 cell |
| Hybrid Guided | `MODE_HYBRID_GUIDED` | PTS guides MCTS cell order |
| Hybrid Beam | `MODE_HYBRID_BEAM` | PTS guides BeamSearch |
| Unified MCTS | `MODE_UNIFIED_MCTS` | Single tree with cells as first-level **[DEFAULT]** |

See [docs/ALGORITHMS.md](docs/ALGORITHMS.md) for detailed algorithm documentation.

### Scoring System Architecture

Modular, ML-tunable scoring system:

```
HiddenKnowledges/     # Private repo - real weights (public repo has placeholders)
├── ScoringConfig     # ML-tunable constants: weights, thresholds, duration tables
├── EntityCoefs       # Base coefficient tables per entity type
├── ScoringModifiers  # Pure modifier functions (lifeRatio, levelRatio, etc.)
└── Scoring           # Façade: caches, getDynamicCoef(), getEffectiveDuration()

Controlers/
└── BattleState       # Per-turn team state: composition, flags, ratios, danger
```

- **ScoringConfig**: All tunable constants (KILL_VALUE, W_DANGER_*, duration_mitigation maps)
- **EntityCoefs**: `baseCoefs[entityType][stat]` lookup tables
- **BattleState**: Team composition (countFire, countHealer...), flags (enemyHasStr), ratios
- **ScoringModifiers**: Stateless functions (getLifeRatioModifier, getWinningModifier, etc.)
- **Scoring**: Orchestrates refresh(), provides getDynamicCoef() with all modifiers applied

> **Note**: The public tagadalive repo contains placeholder scoring files with neutral values.
> Real weights are in the private `HiddenKnowledges` repo. See `HiddenKnowledges/README.md` for setup.

### LeekScript v4 Features Used

- Full variable/method typing (zero runtime cost - empirically tested)
- Array vs Map distinction (`Board` class replaces old `Map`)
- Typed function parameters and return types
- Nullable types with `?` suffix and `!` force-unwrap

### Tampermonkey Tools

Browser userscripts in `tagadalive/tampermonkey/` for analyzing fight reports. Provides real-time visualization of AI debug output.

**Purpose**: When viewing a fight report on LeekWars, these scripts display a panel showing:
- Turn-by-turn algorithm stats (adapts to mode: MCTS, BeamSearch, or PTS)
- Algorithm comparison banner (shows winner in hybrid modes: PTS vs MCTS/Beam)
- Performance profiler (operation counts per function, grouped by category)
- Combo analysis (top-scored action sequences with score breakdown)
- Resource tracking (HP, TP, MP, cell position)
- Error detection (AI crashes with stack traces)

**Architecture**: 6 modular Tampermonkey scripts that load in sequence:
- `lwa-core.user.js` - Shared state and helpers
- `lwa-styles.user.js` - CSS styling
- `lwa-parser.user.js` - Log parsing
- `lwa-ui.user.js` - UI rendering
- `lwa-charts.user.js` - Chart.js visualizations
- `lwa-main.user.js` - Initialization

**Documentation**: See `tagadalive/tampermonkey/README.md` for installation and usage details.

### TODO.md

`tagadalive/TODO.md` tracks static analysis issues and improvements for the LeekScript codebase.

---

## Reference: LeekWars API

Full docs: [docs/LEEKWARS_API.md](docs/LEEKWARS_API.md). Base URL: `https://leekwars.com/api`. Auth: `POST /farmer/login-token/` → JWT Bearer token.

Key endpoints:
- `GET /garden/get-leek-opponents/{leek_id}` / `get-farmer-opponents` / `get-composition-opponents/{id}`
- `POST /garden/start-solo-fight/{leek_id}/{enemy_id}` / `start-farmer-fight` / `start-team-fight`
- `GET /fight/get/{fight_id}` (add `?logs=true` for debug output)
- AI tree (files + folders + bin + leek_ais): embedded in `POST /farmer/login-token` response under `farmer.ai_tree`
- `POST /ai/read` (body: `{path}`) → `{code}`
- `POST /ai/write` (body: `{path, code}`) → `{result, modified}`
- `POST /ai/create` (body: `{folder, name, version}`) — folder `""` = root
- `POST /ai/rename` (body: `{path, new_name}`), `POST /ai/move` (body: `{path, dest}`)
- `DELETE /ai/delete` (json: `{path}`) → `{trash_name}`, `POST /ai/restore` (body: `{trash_name}`)
- `POST /ai-folder/create` / `rename` / `DELETE /ai-folder/delete` — all take `{path}`

---

## Reference: Fight Result Structure

Fight results from `/fight/get/{id}`:
```json
{"winner": 1, "fight": 12345, "map": {}, "leeks": [], "team1": [1,2], "team2": [3,4], "actions": [], "report": {}}
```
Winner: -1=pending, 0=draw, 1=team1, 2=team2.

### Action Types

| ID | Action | Format | Description |
|----|--------|--------|-------------|
| 0 | START_FIGHT | `[0, team2_size, team1_size]` | Battle begins |
| 1 | USE_WEAPON | `[1, leek_id, cell, weapon_id, fail, [targets]]` | Weapon attack (fail: 0=hit, 1=miss) |
| 2 | USE_CHIP | `[2, leek_id, cell, chip_id, fail, [targets]]` | Chip/spell use |
| 6 | NEW_TURN | `[6, turn_number]` | New round starts |
| 7 | LEEK_TURN | `[7, leek_id, TP, MP]` | Leek's turn begins |
| 10 | MOVE_TO | `[10, leek_id, dest_cell, [path]]` | Movement |
| 100 | PT_LOST | `[100, leek_id, amount]` | Action points spent |
| 101 | LIFE_LOST | `[101, leek_id, damage]` | Damage taken |
| 102 | PM_LOST | `[102, leek_id, amount]` | Movement points spent |
| 103 | LIFE_WIN | `[103, leek_id, amount]` | Health restored |
| 301 | ADD_EFFECT | `[301, weapon, effect_id, src, tgt, type, val, dur]` | Status effect applied |

---

## Reference: LeekScript

### Language Features
- Weakly typed (var keyword), first-class functions, classes/OOP, arrays/maps, standard control flow

### Core Combat Functions

```javascript
// Entity info: getCell([entity]), getLife([entity]), getLevel(entity), getTotalLife(entity)
// Movement: getMP(), moveToward(entity[, n]), moveAwayFrom(entity), moveTowardCell(cell), getCellDistance(c1, c2)
// Combat: getTP(), getNearestEnemy(), getEnemies(), getAllies(), setWeapon(WEAPON), useWeapon(entity), useChip(CHIP, entity)
// Weapon/Chip info: getWeaponCost/MinRange/MaxRange(weapon), getChipCost(chip)
// Debug: debug(v), debugW(v), debugE(v) — FREE. say(msg) costs 1 TP — avoid!
// Utility: randInt(min, max), arraySort(array, key)
```

### Common Constants
Weapons: `WEAPON_PISTOL`, `WEAPON_MACHINE_GUN`, `WEAPON_SHOTGUN`, `WEAPON_MAGNUM`, `WEAPON_LASER`, `WEAPON_GRENADE_LAUNCHER`, `WEAPON_ELECTRISOR`, `WEAPON_DESTROYER`, `WEAPON_RIFLE`...
Chips: `CHIP_SPARK`, `CHIP_FLASH`, `CHIP_LIGHTNING`, `CHIP_BANDAGE`, `CHIP_CURE`, `CHIP_REGENERATION`, `CHIP_SHIELD`, `CHIP_ARMOR`, `CHIP_WALL`, `CHIP_ACCELERATION`, `CHIP_TELEPORTATION`...
Return codes: `USE_SUCCESS`, `USE_FAILED`, `USE_NOT_ENOUGH_TP`, `USE_INVALID_TARGET`, `USE_INVALID_POSITION`

---

## Strategy & Roadmap

Iterative improvement loop: baseline → fight → analyze → identify patterns → modify AI → validate → repeat. Completed: fight DB, dashboard, ML pipeline, local runner. Remaining: full API client, fight launcher, AI code generator, learning loop orchestrator.

## Key Resources

- [docs/LEEKWARS_API.md](docs/LEEKWARS_API.md) — local API reference (use first)
- [leekwars.com](https://leekwars.com/), [API docs](https://leekwars.com/help/api), [LeekScript docs](https://leekwars.com/help/documentation), [GitHub](https://github.com/leek-wars)
