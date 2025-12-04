# TagadAI - LeekWars Intelligent Combat System

## Project Overview

This project creates an autonomous AI system for LeekWars, a browser-based programming game where players write JavaScript-like code (LeekScript) to control "leeks" in automated battles.

**Core Mission**: Build an intelligent agent that:
1. Launches fights via the LeekWars API
2. Analyzes fight results by interpreting action logs
3. Learns from outcomes and updates AI code to improve performance
4. Iterates continuously toward optimal combat strategies

## Directory Structure

```
tagadai/
├── CLAUDE.md                 # This file - project guidelines
├── docs/
│   └── LEEKWARS_API.md       # Complete API reference (extracted from source)
├── src/
│   └── tools/                # CLI tools for interacting with LeekWars
│       ├── status.py         # Account status display
│       ├── fight.py          # Run fights (test or real)
│       └── aisync.py         # Upload/download AI code
├── leekwars_gardener/        # REFERENCE ONLY - Python API wrapper
├── tagadalive/               # ACTIVE AI DEVELOPMENT - LeekScript v4 combat AI
│   ├── AI/                   # Decision engine & scoring
│   ├── Model/                # Entity, Item, Cell, Combo classes
│   ├── Controlers/           # Fight logic, pathfinding, danger maps
│   ├── Services/             # Damage calc, targeting, benchmarks
│   ├── TESTS/                # AI unit tests
│   ├── TODO.md               # Static analysis issues tracker
│   └── main                  # Entry point
├── data/                     # Fight history, analysis results
└── tests/                    # Test suite
```

## Important Constraints

### Reference Code - DO NOT MODIFY

#### leekwars_gardener/
Python tool for automating LeekWars account management. Use as **reference only**:
- `lwapi.py` - API endpoint patterns and authentication
- `main.py` - Fight orchestration patterns
- `utils.py` - Constants and data structures
- **Never edit these files**

## Active AI Development

### tagadalive/
Combat AI written in **LeekScript v4** (~30 core files, modular architecture). This is the active codebase for AI development:

**Core files**:
- `main` - Entry point, decision loop
- `AI/AI` - Core strategy: greedy multi-position search with consequence prediction
- `AI/Scoring` - Weighted coefficient system for action evaluation, duration caching
- `Model/` - Entity, Item, Cell, Action, Combo classes
- `Controlers/Maps/` - Pathfinding, danger maps, action generation
- `Services/Damages` - Damage calculation with shields/erosion

**Key patterns**: Consequence simulation, danger map caching, dual-phase exploration (offense vs offense+defense).

**LeekScript v4 features used**:
- Full variable/method typing (zero runtime cost - empirically tested)
- Array vs Map distinction (`Board` class replaces old `Map`)
- Typed function parameters and return types
- Nullable types with `?` suffix and `!` force-unwrap

**Language notes**:
- **LS4 null coercion**: `null` is coerced to `0` in numeric contexts (arithmetic, comparisons)
- **Type annotations are FREE**: Empirically tested - zero runtime operation cost
- Cell 1312 (`Cell.SELF_CAST_ID`) is sentinel for self-cast actions (outside valid range 0-612)

**TODO.md**: Tracks static analysis issues and improvements

## CLI Tools

Python tools in `src/tools/` for interacting with LeekWars. Run from project root.

### Account Status
```bash
python -m src.tools.status          # Human-readable account overview
python -m src.tools.status --json   # JSON output for programmatic use
```
Shows: farmer name, talent, habs, fights available, leeks (with levels/talent/capital), AI files.

### Fight
```bash
python -m src.tools.fight                    # Test fight vs Domingo (FREE - use this for testing!)
python -m src.tools.fight --json             # Output raw fight JSON
python -m src.tools.fight --real             # REAL solo fight (costs 1 fight)
python -m src.tools.fight --real --farmer    # REAL farmer fight (costs 1 fight)
```
Outputs fight summary: winner, damage dealt/received, turn-by-turn breakdown.

**Always prefer test fights** (no `--real` flag) when testing AI code - they're free and unlimited.

### AI Code Sync
```bash
python -m src.tools.aisync list                  # List all AI files with IDs
python -m src.tools.aisync get <ai_id>           # Download AI code to stdout
python -m src.tools.aisync get <ai_id> -o f.ls   # Download AI code to file
python -m src.tools.aisync put <ai_id> <file>    # Upload code from file
python -m src.tools.aisync put <ai_id> -         # Upload code from stdin
python -m src.tools.aisync new <name>            # Create new AI file
python -m src.tools.aisync rename <ai_id> <name> # Rename AI file
```

## LeekWars API Reference

> **Full API documentation**: See [docs/LEEKWARS_API.md](docs/LEEKWARS_API.md) for complete endpoint reference.

### Base URL
```
https://leekwars.com/api
```

### Authentication
```python
# Login - returns JWT token
POST /farmer/login-token/
Body: {"login": "username", "password": "password"}
Response: {"token": "jwt_token", "farmer": {...}}

# All subsequent requests use Bearer token
Headers: {"Authorization": "Bearer <token>"}
```

### Core Endpoints

#### Fight Management
```python
# Get opponents for solo fights (leek vs leek)
GET /garden/get-leek-opponents/{leek_id}

# Get opponents for farmer fights
GET /garden/get-farmer-opponents

# Get opponents for team fights
GET /garden/get-composition-opponents/{composition_id}

# Launch fights
POST /garden/start-solo-fight/{leek_id}/{enemy_id}
POST /garden/start-farmer-fight/{enemy_id}
POST /garden/start-team-fight/{enemy_id}

# Get fight results (poll until winner != -1)
GET /fight/get/{fight_id}
# Add ?logs=true for debug output from AI
```

#### AI Code Management
```python
# Get all AI files
GET /ai/get-farmer-ais

# Get specific AI code
GET /ai/get/{ai_id}

# Create new AI file (folder_id=0 for root)
POST /ai/new/{folder_id}/false
Body: {"name": "filename", "version": "11"}

# Save AI code
POST /ai/save
Body: {"ai_id": id, "code": "leekscript_code"}

# Rename AI
POST /ai/rename
Body: {"ai_id": id, "name": "new_name"}
```

#### Leek Management
```python
# Get leek details
GET /leek/get/{leek_id}

# Spend capital points
POST /leek/spend-capital
Body: {"leek_id": id, "characteristic": "life|strength|...", "amount": n}

# Leek registers (persistent storage, 100 max per leek)
GET /leek/get-registers/{leek_id}
POST /leek/set-register/{leek_id}/{key}/{value}
DELETE /leek/delete-register/{leek_id}/{key}
```

## Fight Result Structure

Fight results from `/fight/get/{id}` contain the complete battle log:

```json
{
  "winner": 1,           // -1=pending, 0=draw, 1=team1 wins, 2=team2 wins
  "fight": 12345,        // fight_id
  "map": {...},          // battlefield layout
  "leeks": [...],        // participant details
  "team1": [1, 2],       // leek IDs on team 1
  "team2": [3, 4],       // leek IDs on team 2
  "actions": [...],      // chronological action log
  "report": {            // talent changes
    "farmer1": {"talent": 1500, "talent_gain": 5},
    "farmer2": {"talent": 1480, "talent_gain": -5}
  }
}
```

### Action Types (in `actions` array)

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

### Leek Object Structure
```json
{
  "id": 123,
  "name": "MyLeek",
  "team": 1,
  "level": 50,
  "life": 500,           // max HP
  "force": 100,          // strength
  "agility": 80,
  "frequency": 50,
  "pt": 10,              // action points
  "pm": 5,               // movement points
  "cellPos": 42,         // starting cell
  "farmer": 456,
  "valid_ai": true
}
```

## LeekScript Reference

LeekScript is the language used to program leek AI. It's similar to JavaScript with game-specific functions.

### Language Features
- Weakly typed (var keyword)
- Functions are first-class objects
- Supports classes and OOP (v2+)
- Arrays and maps
- Standard control flow (if/else, for, while)

### Core Combat Functions

```javascript
// Entity information
getCell()                    // Your cell position
getCell(entity)              // Entity's cell position
getLife()                    // Your current HP
getLife(entity)              // Entity's current HP
getLevel(entity)             // Entity's level
getTotalLife(entity)         // Entity's max HP

// Movement
getMP()                      // Your remaining movement points
moveToward(entity)           // Move toward entity (uses all MP)
moveToward(entity, n)        // Move n cells toward entity
moveAwayFrom(entity)         // Move away from entity
moveTowardCell(cell)         // Move toward specific cell
getCellDistance(cell1, cell2) // Distance between cells

// Combat
getTP()                      // Your remaining action points
getNearestEnemy()            // Get closest enemy entity
getEnemies()                 // Get array of all enemies
getAllies()                  // Get array of all allies
setWeapon(WEAPON_CONSTANT)   // Equip weapon
useWeapon(entity)            // Attack with equipped weapon
useChip(CHIP_CONSTANT, entity) // Use chip on entity

// Weapon/Chip info
getWeaponCost(weapon)        // TP cost
getWeaponMinRange(weapon)    // Minimum range
getWeaponMaxRange(weapon)    // Maximum range
getChipCost(chip)            // TP cost for chip

// Communication
say(message)                 // Display message in fight (COSTS 1 TP - avoid!)
debug(value)                 // Log to debug output (with ?logs=true) - FREE
debugW(value)                // Warning level debug output - FREE
debugE(value)                // Error level debug output - FREE

// IMPORTANT: Always use debug() instead of say() for logging!
// say() costs 1 action point per call, debug() is free.

// Utility
randInt(min, max)            // Random integer
arraySort(array, key)        // Sort array
```

### Common Constants
```javascript
// Weapons
WEAPON_PISTOL, WEAPON_MACHINE_GUN, WEAPON_SHOTGUN,
WEAPON_MAGNUM, WEAPON_LASER, WEAPON_GRENADE_LAUNCHER,
WEAPON_ELECTRISOR, WEAPON_DESTROYER, WEAPON_RIFLE...

// Chips (spells)
CHIP_SPARK, CHIP_FLASH, CHIP_LIGHTNING,
CHIP_BANDAGE, CHIP_CURE, CHIP_REGENERATION,
CHIP_SHIELD, CHIP_ARMOR, CHIP_WALL,
CHIP_ACCELERATION, CHIP_TELEPORTATION...

// Return codes
USE_SUCCESS, USE_FAILED, USE_NOT_ENOUGH_TP,
USE_INVALID_TARGET, USE_INVALID_POSITION
```

### Example AI Pattern
```javascript
// Basic combat AI
var enemy = getNearestEnemy()
if (enemy != null) {
    // Move into range
    var dist = getCellDistance(getCell(), getCell(enemy))
    if (dist > getWeaponMaxRange(WEAPON_PISTOL)) {
        moveToward(enemy)
    }

    // Attack while we have TP
    setWeapon(WEAPON_PISTOL)
    while (getTP() >= getWeaponCost(WEAPON_PISTOL)) {
        var result = useWeapon(enemy)
        if (result != USE_SUCCESS) break
    }
}
```

## Analysis Strategy

### Fight Analysis Goals
1. **Action Efficiency**: Track TP/MP usage per turn
2. **Damage Analysis**: Calculate damage dealt vs received
3. **Positioning**: Analyze movement patterns and positioning
4. **Decision Points**: Identify key moments that determined outcome
5. **Opponent Patterns**: Learn from enemy AI behaviors

### Metrics to Extract
```python
# Per-fight metrics
total_damage_dealt = sum(action[4] for action in actions if action[0] == 101 and is_enemy(action[1]))
total_damage_received = sum(action[4] for action in actions if action[0] == 101 and is_ally(action[1]))
turns_survived = max(action[1] for action in actions if action[0] == 6)
tp_efficiency = total_damage_dealt / total_tp_spent
movement_efficiency = # cells moved toward enemy vs away

# Aggregated metrics
win_rate_by_opponent_level = {}
average_damage_per_turn = {}
common_loss_patterns = []
```

## AI Generation Strategy

### Iterative Improvement Loop
1. **Baseline**: Start with simple combat AI
2. **Fight**: Run multiple fights against varied opponents
3. **Analyze**: Extract performance metrics from results
4. **Identify**: Find patterns in wins vs losses
5. **Generate**: Modify AI code to address weaknesses
6. **Validate**: Test changes against similar opponents
7. **Repeat**: Continue iteration

### Code Generation Approaches
- **Template-based**: Parameterized AI templates
- **Rule extraction**: Convert analysis insights to code rules
- **Strategy switching**: Multiple strategies selected by context
- **LLM-assisted**: Use Claude to suggest code improvements

## Development Guidelines

### Code Style
- Python 3.10+ for main project
- Type hints for all functions
- Docstrings for public APIs
- pytest for testing

### Error Handling
- Graceful handling of API rate limits
- Retry logic for transient failures
- Logging of all API interactions
- Save fight data locally for offline analysis

### Security
- Never commit credentials
- Use environment variables for secrets
- Rate limit API calls responsibly

### Git Commits
- Do NOT include Claude references in commit messages (no "Generated with Claude", no "Co-Authored-By: Claude")
- Write commit messages as if written by the developer
- Keep messages concise and descriptive

## Key Resources

- **[docs/LEEKWARS_API.md](docs/LEEKWARS_API.md)** - Complete local API reference (use this first!)
- [LeekWars Official](https://leekwars.com/)
- [API Documentation](https://leekwars.com/help/api)
- [LeekScript Docs](https://leekwars.com/help/documentation)
- [LeekWars GitHub](https://github.com/leek-wars)
- [Fight Generator](https://github.com/leek-wars/leek-wars-generator)
- [Community API Docs](https://github.com/LeBezout/LEEK-WARS)

## Getting Started

1. Credentials are stored in `.env` (gitignored, 600 permissions):
   ```bash
   # .env format:
   LEEKWARS_LOGIN=your_email
   LEEKWARS_PASSWORD=your_password
   ```

2. Load credentials in Python:
   ```python
   from dotenv import load_dotenv
   import os

   load_dotenv()
   login = os.getenv("LEEKWARS_LOGIN")
   password = os.getenv("LEEKWARS_PASSWORD")
   ```

3. Study AI code:
   ```bash
   # Main AI logic
   cat tagadalive/AI/AI
   # Scoring system
   cat tagadalive/AI/Scoring
   # Static analysis issues
   cat tagadalive/TODO.md
   ```

4. Sync AI code to/from LeekWars:
   ```bash
   # List AI files on account
   python -m src.tools.aisync list
   # Upload a file
   python -m src.tools.aisync put <ai_id> tagadalive/<path>
   # Download a file
   python -m src.tools.aisync get <ai_id> -o tagadalive/<path>
   ```

5. Test AI changes:
   ```bash
   # Run FREE test fight vs Domingo
   python -m src.tools.fight
   ```

## TODO / Roadmap

- [ ] API client with full endpoint coverage
- [ ] Fight launcher with opponent selection strategies
- [ ] Fight result parser and action decoder
- [ ] Metrics extraction and aggregation
- [ ] Fight history database
- [ ] Analysis dashboard / reporting
- [ ] AI code generator (template-based)
- [ ] Learning loop orchestrator
- [ ] Advanced: LLM-assisted code improvement
