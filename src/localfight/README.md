# Local Fight Runner

Run LeekWars fights offline with the official Java generator. No fight cost, no
rate limit, no API round-trip once the scenario is built — the loop of choice
for smoke-testing `tagadalive` after a refactor and for bulk data generation.

## Prerequisites

Run the setup script once — it clones the generator, downloads a private JDK 25
and Gradle 9 into `.cache/toolchain/`, and builds the JAR:

```bash
scripts/setup_generator.sh          # set up or update
scripts/setup_generator.sh --force  # force a rebuild
```

Nothing is installed system-wide and no sudo is required. Re-run it to pick up
upstream generator changes (including refreshed `data/*.json` item tables).

**Java 25 is mandatory.** The generator is compiled with
`sourceCompatibility = 25`, so its classes are class-file version 69 and will
not load on an older JVM — a system `java` of 21 fails with
`UnsupportedClassVersionError`. `runner.py` therefore never calls a bare
`java`: it resolves one through `get_paths().java_bin`, which prefers
`TAGADAI_JAVA_HOME`, then the JDK under `.cache/toolchain/`, then `JAVA_HOME`,
then `java` on `PATH` — skipping any candidate older than 25.

Point `TAGADAI_JAVA_HOME` at an existing JDK 25+ to skip the download.

## CLI

`src/tools/localfight.py` runs `tagadalive` against two of your own leeks,
using their **live** builds pulled from the API:

```bash
python -m src.tools.localfight                       # first two leeks
python -m src.tools.localfight Claudius Claudias     # by name or id
python -m src.tools.localfight --seed 42             # reproducible
python -m src.tools.localfight --ai tagadalive/testMain
python -m src.tools.localfight --logs                # all AI debug output
python -m src.tools.localfight --json                # raw generator JSON
python -m src.tools.localfight --account tagadanar
```

```
Claudius vs Claudias
  winner:   Claudius
  turns:    13
  compile:  6.0s   exec: 3.1s
  Claudius     alive
  Claudias     dead
  ops:      0=82,630,853, 1=60,357,184
  logs:     102 lines, 0 errors
```

Exit code is 1 when the AI logged errors, so it works in a `&&` chain.

## Library

```python
from src.localfight import Scenario, LeekConfig, run_fight, parse_fight_result

leek1 = LeekConfig(id=1, name="A", farmer=1, team=1, ai="tagadalive/main")
leek2 = LeekConfig(id=2, name="B", farmer=2, team=2, ai="tagadalive/main")
result = run_fight(Scenario(team1=[leek1], team2=[leek2], random_seed=42))
parsed = parse_fight_result(result)
```

| Module | Description |
|--------|-------------|
| `scenario.py` | `Scenario`, `LeekConfig`, `MapConfig` — builds the scenario JSON |
| `runner.py` | `run_fight()` / `run_fight_raw()` — executes the JAR, captures stdout |
| `parser.py` | `parse_fight_result()` — turns raw output into typed records |
| `parallel.py` | `ParallelRunner` — runs batches of fights concurrently |

---

## Throughput: cache, persistent workers, JVM flags

Measured on Claudius vs Claudias, 8 physical cores.

- **Compile cache on.** The generator caches compiled AIs (`ai/AI_<hash>.class`,
  keyed by AI path, invalidated by source mtime). `--nocache` cost 10.3s per
  fight against 3.4s. The first compile of each path in a process runs under
  a lock (`runner._compile_guard`) so parallel JVMs cannot race on the file.
- **Persistent JVMs** (`batch.py`, `java/BatchMain.java`). One-shot JVMs spend
  their CPU JIT-compiling the AI and starve each other in parallel (6 workers:
  2.9s -> 13.3s each). `GeneratorPool` keeps N workers reading scenario paths
  on stdin and printing one outcome JSON per line; results are byte-identical
  to one-shot runs. `ParallelRunner`, `aibench`, `dangerprobe` use it.
- **Flags** (`batch.DEFAULT_JVM_FLAGS`): SerialGC, 2 CPUs, `-Xmx3g`, and C1
  only -- a hot worker takes 4.1s per fight with C1, 10.1s with C2; the AI's
  class is too big for C2 to pay off.

| setup (8 workers)                           | fights/s |
|---------------------------------------------|---------:|
| one-shot JVM, `--nocache` (old default)     |     0.26 |
| one-shot JVM, cached, best flags            |     1.12 |
| persistent pool, C1                         |     2.07 |

`BatchMain` is built on first use into `.cache/batch/`; worker stderr goes to
`.cache/batch/worker-<n>.log`.

## Generator contract

Everything below is behaviour of the generator itself, verified against its
source in `.cache/leek-wars-generator/`. It is not obvious from the JSON and
has cost real debugging time; check here first.

### AI paths and includes

The CLI generator installs `NativeFileSystem`, whose root folder is the
**generator's own working directory** (`runner.py` sets `cwd=GENERATOR_DIR`,
which is also required for the generator to find its `data/*.json`). Paths that
escape that root are rejected outright by `resolveSafe()`, so `../../tagadalive`
does not work.

`src/tools/localfight.py` therefore symlinks `tagadalive/` into the generator
directory and uses the AI path `tagadalive/main`. Normalization is textual and
the read follows the link, so the symlink passes the escape check.

- `include('auto')` resolves **relative to the including file's folder**, same
  as on the site — so the tree works unmodified.
- Includes are extensionless because the files on disk are extensionless;
  `findFile()` takes the name verbatim.
- Every file loaded this way is compiled at `LeekScript.LATEST_VERSION` (4).
  `ai_version` / `ai_strict` in the scenario only apply to the `ai_path` branch,
  which the CLI never takes.

### Scenario JSON

`Scenario.fromFile()` reads exactly: `random_seed`, `max_turns`, `farmers`,
`teams`, `entities`. Notably **`map` is ignored** — `MapConfig` is serialized
but never parsed, so every local fight uses a randomly generated map. Only the
per-entity `cell` influences placement.

Per entity, the fields that matter:

| Field | Effect |
|-------|--------|
| `weapons` | **ITEM template ids** (see below) |
| `chips` | chip ids, identical to item template ids |
| `cores` | operation budget: `cores × 1_000_000` per turn |
| `ram` | memory budget: `min(50, ram) × 8_000_000` |
| `life` | total AND starting HP |
| `type` | 1 = leek (0 is `Leek.class` indexing, don't use it) |
| `farmer`, `team` | must match an entry in `farmers` / `teams` |

A level-301 leek runs at 18-19 cores, i.e. an 18-19M op budget — matching the
site. Leaving `cores` at the dataclass default of 1 gives the AI 1M ops and it
will blow the limit immediately.

### Weapon ids are ITEM ids, chip ids are not

The generator loads `data/weapons.json` (keyed by *weapon* id) but registers
each weapon under its `item` field:

```java
Weapons.addWeapon(new Weapon(weapon.get("item").intValue(), ...));
```

So `Weapons.getWeapon(37)` is the **pistol** (item 37 / weapon 1), not the
odachi (weapon 37). Scenario `weapons` therefore take the same ids the site API
reports in `leek.weapons[].template` — pass them straight through.

Chips are registered under the JSON key, and for chips the chip id and the item
template id are the same number (verified across all 109), so those also pass
through unchanged.

Getting this wrong is **silent**: `Weapons.getWeapon()` returns null, the
generator writes `No such weapon: N` to a stderr stream nobody reads, and the
leek fights bare-handed. `localfight.py` validates both lists against
`data/weapons.json` / `data/chips.json` up front and warns.

### Result format

```json
{"fight": {"actions": [], "leeks": [], "map": {}, "dead": {}, "ops": {}},
 "logs": {}, "winner": 0, "duration": 16,
 "analyze_time": 0, "compilation_time": 0, "execution_time": 0}
```

- **`winner` is a 0-based TEAM INDEX**, not the website API's 1-based team
  number: `0` = first team, `-1` = draw, `-2` = every survivor wins.
- `leeks[].id` is **renumbered** to 0, 1, 2… — the scenario's leek ids do not
  survive. `dead` is keyed by the original ids.
- `ops` is the cumulative operation count per entity across the whole fight,
  not the per-turn budget.
- Times are nanoseconds.

### Logs

`logs` is keyed by `aiOwner`, and the CLI never sets it (only
`Scenario.setEntityAI()` does, which is a server path). Every entity's output
therefore lands in **bucket `"0"`**; disambiguate by the entity id inside each
entry, not by the bucket.

Within a bucket, keys are action indices and each entry is one of:

```
[entityId, type, text]                    # debug()/debugW()/debugE()
[entityId, type, text, key, [params]]     # system log, `key` is a FarmerLog code
```

`type` 0 standard, 1 debug-warning, 2 warning, 3 error, 4 system error.
Useful `key` values from `FarmerLog`: 1000 `NO_WEAPON_EQUIPPED`,
1001 `CHIP_NOT_EQUIPPED`, 1003 `WEAPON_NOT_EXISTS`, 1006 `LOADOUT_NOT_FOUND`.

### Action ids

`ActionType` in `parser.py` mirrors the generator's `action/Action.java`. These
are **not** the ids the website API reports for the same events (there
`USE_WEAPON` is 1 and `USE_CHIP` is 2); keep the two straight when moving code
between local fights and scraped fights.

Damage arrives under several ids depending on source: `101 LOST_LIFE`,
`107 NOVA_DAMAGE`, `108 DAMAGE_RETURN`, `109 LIFE_DAMAGE`,
`110 POISON_DAMAGE`, `111 AFTEREFFECT`. `parser.py` currently only counts
`101`, so a poison/magic build reports `damage_dealt = 0`.
