#!/usr/bin/env python3
"""
Local Fight Tool - run tagadalive offline against real leek builds.

Pulls two of your leeks' live builds (stats + weapons + chips) from the API and
runs them through the local Java generator, with no fight cost and no rate
limit. Useful for smoke-testing the AI after a refactor.

Usage:
    python -m src.tools.localfight                       # first two leeks
    python -m src.tools.localfight Claudius Claudias     # by name (or id)
    python -m src.tools.localfight --ai tagadalive/main --seed 42
    python -m src.tools.localfight --logs                # dump AI debug output
    python -m src.tools.localfight --json                # raw generator output

Notes:
    - The AI path is relative to the generator directory. The tool symlinks
      the tree named by the path's first segment in there, so `tagadalive/main`
      and `tagadargb/main` both resolve and `include('auto')` works
      folder-relative from either.
    - Weapons and chips go in as the ITEM template ids the site API reports.
      The generator registers each weapon under `weapons.json.item`, not under
      the json key, so item ids are what `Weapons.getWeapon()` expects.
"""

import argparse
import json
import sys

from src.common import LeekWarsAPI, load_credentials
from src.common.config import get_paths
from src.common.errors import TagadAIError
from src.localfight.logs import LOG_ERROR_TYPES, LOG_WARNING_TYPES, collect_logs  # noqa: F401 (re-exported)
from src.localfight.runner import RunnerError, run_fight_raw

DEFAULT_AI = "tagadalive/main"

# leekscript AILog levels. 1/2/3 come from the AI's own debug()/debugW()/debugE();
# 6/7/8 are the same levels raised by the engine itself (unknown weapon, chip
# not equipped...), which is where silent build problems surface.
def link_ai_tree(ai_path: str) -> None:
    """Expose the AI tree an `--ai` path lives in inside the generator dir.

    The generator's NativeFileSystem roots every path at its own working
    directory and rejects anything that escapes it, so the tree has to be
    reachable from there. A symlink is enough: paths are normalized textually
    before the check, and the read follows the link.

    The tree is the first segment of the AI path, so `tagadalive/main` and
    `tagadargb/main` each link their own directory. A tree that is not at the
    repo root is looked up under `.cache/variants/`, where
    `src.tuning.variant` writes rewritten copies of tagadalive.
    """
    tree = ai_path.split("/")[0]
    if not tree or tree in (".", ".."):
        raise TagadAIError(f"Cannot tell which AI tree {ai_path!r} belongs to")

    paths = get_paths()
    link = paths.generator_dir / tree
    target = paths.root / tree
    if not target.is_dir():
        target = paths.variants_dir / tree
    if not target.is_dir():
        raise TagadAIError(f"No local AI tree at {paths.root / tree} or {target}")
    if link.is_symlink():
        if link.readlink() == target or link.resolve() == target:
            return
        link.unlink()
    elif link.exists():
        raise TagadAIError(f"{link} exists and is not a symlink; remove it first")
    link.symlink_to(target)


def resolve_leeks(api: LeekWarsAPI, wanted: list[str]) -> list[dict]:
    """Resolve leek names or ids against the logged-in farmer's leeks."""
    leeks = list(api.refresh_farmer()["leeks"].values())

    if not wanted:
        chosen = leeks[:2]
    else:
        chosen = []
        for w in wanted:
            match = next(
                (l for l in leeks if str(l["id"]) == w or l["name"].lower() == w.lower()),
                None,
            )
            if match is None:
                names = ", ".join(f"{l['name']} ({l['id']})" for l in leeks)
                raise TagadAIError(f"No leek '{w}'. Available: {names}")
            chosen.append(match)

    if len(chosen) != 2:
        raise TagadAIError(f"Need exactly 2 leeks, got {len(chosen)}")
    return chosen


def templates(equipment) -> list[int]:
    """Item template ids from a leek's `weapons` / `chips` list."""
    return [e["template"] if isinstance(e, dict) else e for e in equipment or []]


def known_equipment() -> tuple[set[int], set[int]]:
    """(weapon ids, chip ids) the generator's data files define.

    Weapons are registered under their `item` field, chips under the json key.
    Both are what the site API calls a `template`, confusingly — a chip's API
    `template` is the generator's chip id, NOT the `template` field inside
    chips.json. Do not "fix" this by mapping through that field: it silently
    swaps every chip for an unrelated one.

    Anything else is dropped with a stderr line we never see, leaving the leek
    silently unarmed, so we check up front instead.
    """
    data = get_paths().generator_dir / "data"
    weapons = json.loads((data / "weapons.json").read_text())
    chips = json.loads((data / "chips.json").read_text())
    return {w["item"] for w in weapons.values()}, {int(k) for k in chips}


def build_entity(api: LeekWarsAPI, leek_id: int, team: int, ai: str) -> dict:
    """Snapshot a leek's live build as a generator scenario entity."""
    leek = api.get_leek(leek_id)
    weapons = templates(leek.get("weapons"))
    chips = templates(leek.get("chips"))

    known_weapons, known_chips = known_equipment()
    unknown = [w for w in weapons if w not in known_weapons]
    unknown += [c for c in chips if c not in known_chips]
    if unknown:
        print(f"warning: {leek['name']} has equipment the generator doesn't know "
              f"(items {unknown}); re-run scripts/setup_generator.sh to refresh data/",
              file=sys.stderr)

    return {
        "id": leek_id,
        "name": leek["name"],
        "ai": ai,
        "type": 1,
        "farmer": team,
        "team": team,
        "level": leek["level"],
        "life": leek["total_life"],
        "strength": leek["total_strength"],
        "agility": leek["total_agility"],
        "resistance": leek["total_resistance"],
        "science": leek["total_science"],
        "magic": leek["total_magic"],
        "wisdom": leek["total_wisdom"],
        "frequency": leek["total_frequency"],
        "tp": leek["total_tp"],
        "mp": leek["total_mp"],
        "cores": leek["total_cores"],
        "ram": leek["total_ram"],
        "weapons": weapons,
        "chips": chips,
    }


def build_scenario(entities: list[dict], seed: int | None, max_turns: int) -> dict:
    scenario = {
        "farmers": [{"id": 1, "name": "P1", "country": "fr"},
                    {"id": 2, "name": "P2", "country": "fr"}],
        "teams": [{"id": 1, "name": "T1"}, {"id": 2, "name": "T2"}],
        "entities": [[entities[0]], [entities[1]]],
        "max_turns": max_turns,
    }
    if seed is not None:
        scenario["random_seed"] = seed
    return scenario


def report(result: dict, entities: list[dict], show_logs: bool) -> int:
    fight = result["fight"]
    # The generator's winner is a 0-based TEAM INDEX (-1 draw, -2 everyone
    # alive wins), not the website API's 1-based team number.
    winner = result["winner"]
    names = [e["name"] for e in entities]
    # The generator renumbers entities to 0, 1, ... in the report; log entries
    # use those ids, not our scenario leek ids.
    by_id = {l["id"]: l["name"] for l in fight.get("leeks", [])}
    label = {-1: "draw", -2: "all survivors"}.get(winner) or (
        names[winner] if 0 <= winner < len(names) else f"team {winner}"
    )

    print(f"{names[0]} vs {names[1]}")
    print(f"  winner:   {label}")
    print(f"  turns:    {result['duration']}")
    print(f"  compile:  {result['compilation_time'] / 1e9:.1f}s   "
          f"exec: {result['execution_time'] / 1e9:.1f}s")

    dead = fight.get("dead") or {}
    for entity in entities:
        state = "dead" if dead.get(str(entity["id"])) else "alive"
        print(f"  {entity['name']:<12} {state}")

    ops = fight.get("ops") or {}
    if ops:
        print("  ops:      " + ", ".join(f"{k}={v:,}" for k, v in sorted(ops.items())))

    logs = collect_logs(result)
    errors = [(eid, text) for eid, level, text in logs if level in LOG_ERROR_TYPES]
    warnings = [(eid, text) for eid, level, text in logs if level in LOG_WARNING_TYPES]
    print(f"  logs:     {len(logs)} lines, {len(errors)} errors, {len(warnings)} warnings")
    for eid, text in (errors + warnings)[:10]:
        name = by_id.get(eid, f"#{eid}")
        print(f"    ! {name}: {text}")

    if show_logs:
        print("\n--- AI logs ---")
        for eid, level, text in logs:
            name = by_id.get(eid, f"#{eid}")
            print(f"[{level}] {name}: {text}")

    return 1 if errors else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a local fight between two of your leeks")
    parser.add_argument("leeks", nargs="*", help="two leek names or ids (default: first two)")
    parser.add_argument("--ai", default=DEFAULT_AI, help=f"AI path in the generator (default: {DEFAULT_AI})")
    parser.add_argument("--ai2", help="AI for the second leek (default: same as --ai). "
                                      "Use it to pit two revisions against each other.")
    parser.add_argument("--seed", type=int, help="random seed (omit for a random fight)")
    parser.add_argument("--turns", type=int, default=64, help="max turns before draw")
    parser.add_argument("--timeout", type=float, default=600.0, help="generator timeout in seconds")
    parser.add_argument("--logs", action="store_true", help="print all AI debug output")
    parser.add_argument("--json", action="store_true", help="print the raw generator JSON")
    parser.add_argument("--account", help="Override LEEKWARS_LOGIN (password from .env)")
    args = parser.parse_args()

    try:
        login, password = load_credentials()
        if args.account:
            login = args.account
        api = LeekWarsAPI()
        api.login(login, password)

        chosen = resolve_leeks(api, args.leeks)
        ais = [args.ai, args.ai2 or args.ai]
        entities = [
            build_entity(api, leek["id"], team, ais[team - 1])
            for team, leek in enumerate(chosen, start=1)
        ]

        for ai in set(ais):
            link_ai_tree(ai)
        scenario = build_scenario(entities, args.seed, args.turns)
        raw = run_fight_raw(json.dumps(scenario), timeout=args.timeout)
    except (TagadAIError, RunnerError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if args.json:
        print(raw)
        return 0

    return report(json.loads(raw), entities, args.logs)


if __name__ == "__main__":
    sys.exit(main())
