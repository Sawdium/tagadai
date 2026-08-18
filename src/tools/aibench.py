#!/usr/bin/env python3
"""
AI Bench - decide whether an AI change actually helped.

Runs one AI against another head to head over a range of seeds, on the same
leek build for both sides, and reports a win rate. Every seed is played twice
with the sides swapped, because the generator gives the first team the first
turn and that alone is worth a few percent.

Usage:
    python -m src.tools.aibench --account tagadargb --ai tagadargb/main
    python -m src.tools.aibench --account tagadargb \\
        --ai tagadargb/main --ai2 tagadargb-old/main --seeds 40

With no --ai2 it plays the AI against itself, which is the calibration run:
anything far off 50% means the seed set is too small to trust.

Exit code is 0 when --ai is at least as good as --ai2, 1 when it is worse, so
this can gate a commit.
"""

import argparse
import json
import statistics
import sys
from concurrent.futures import ThreadPoolExecutor

from src.common import LeekWarsAPI, load_credentials
from src.common.errors import TagadAIError
from src.localfight.runner import RunnerError, run_fight_raw
from src.tools.localfight import (
    build_entity,
    build_scenario,
    collect_logs,
    link_ai_tree,
    resolve_leeks,
)

# Generator log levels that mean the AI misbehaved rather than just talked.
ERROR_LEVELS = {3, 8}


def play(entities: list[dict], seed: int, turns: int, timeout: float) -> dict:
    """Run one fight and reduce it to the few numbers we compare on."""
    scenario = build_scenario(entities, seed, turns)
    result = json.loads(run_fight_raw(json.dumps(scenario), timeout=timeout))

    # `winner` is a 0-based TEAM INDEX here, not the website's 1-based team
    # number: 0 is the first entity, -1 a draw.
    winner = result.get("winner", -1)
    errors = sum(1 for _, level, _ in collect_logs(result) if level in ERROR_LEVELS)

    damage = [0, 0]
    actions = (result.get("fight") or {}).get("actions") or []
    actor = None
    for a in actions:
        if not isinstance(a, list) or not a:
            continue
        if a[0] == 7:                     # LEEK_TURN: whose turn it is now
            actor = a[1]
        elif a[0] == 101 and actor is not None and len(a) > 2:
            # LIFE_LOST is credited to whoever is currently acting.
            victim = a[1]
            if victim != actor and 0 <= actor < 2:
                damage[actor] += a[2]

    return {
        "winner": winner,
        "turns": sum(1 for a in actions if isinstance(a, list) and a and a[0] == 6) + 1,
        "errors": errors,
        "damage": damage,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Head-to-head benchmark of two AI revisions")
    parser.add_argument("--ai", default="tagadargb/main", help="AI under test")
    parser.add_argument("--ai2", help="baseline AI (default: same as --ai)")
    parser.add_argument("--leek", help="leek whose build both sides use (default: first)")
    parser.add_argument("--seeds", type=int, default=24, help="seeds to play (default: 24)")
    parser.add_argument("--first-seed", type=int, default=1)
    parser.add_argument("--turns", type=int, default=64, help="max turns before a draw")
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("--jobs", type=int, default=4, help="fights to run in parallel")
    parser.add_argument("--account", help="Override LEEKWARS_LOGIN (password from .env)")
    args = parser.parse_args()

    baseline = args.ai2 or args.ai

    try:
        login, password = load_credentials()
        if args.account:
            login = args.account
        api = LeekWarsAPI()
        api.login(login, password)

        # Both sides fight with the SAME build, so the only difference is code.
        # An account with a single leek is the normal case here, so the leek is
        # simply cloned onto both teams rather than going through resolve_leeks,
        # which insists on two distinct ones.
        leeks = list(api.refresh_farmer()["leeks"].values())
        if args.leek:
            leek = next((l for l in leeks
                         if str(l["id"]) == args.leek
                         or l["name"].lower() == args.leek.lower()), None)
            if leek is None:
                names = ", ".join(f"{l['name']} ({l['id']})" for l in leeks)
                raise TagadAIError(f"No leek '{args.leek}'. Available: {names}")
        elif leeks:
            leek = leeks[0]
        else:
            raise TagadAIError("That account has no leeks")

        for ai in {args.ai, baseline}:
            link_ai_tree(ai)

        # Side 0 plays first, so each seed is played once each way.
        normal = [build_entity(api, leek["id"], 1, args.ai),
                  build_entity(api, leek["id"], 2, baseline)]
        swapped = [build_entity(api, leek["id"], 1, baseline),
                   build_entity(api, leek["id"], 2, args.ai)]

        jobs = []
        for i in range(args.seeds):
            seed = args.first_seed + i
            jobs.append((normal, seed, 0))     # index of the AI under test
            jobs.append((swapped, seed, 1))

        with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
            outcomes = list(pool.map(
                lambda j: (play(j[0], j[1], args.turns, args.timeout), j[2]),
                jobs,
            ))
    except (TagadAIError, RunnerError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    wins = losses = draws = errors = 0
    turns: list[int] = []
    dealt: list[int] = []
    taken: list[int] = []
    for result, side in outcomes:
        errors += result["errors"]
        turns.append(result["turns"])
        dealt.append(result["damage"][side])
        taken.append(result["damage"][1 - side])
        if result["winner"] == side:
            wins += 1
        elif result["winner"] < 0:
            draws += 1
        else:
            losses += 1

    played = len(outcomes)
    decided = wins + losses
    rate = 100.0 * wins / decided if decided else 0.0

    print(f"{args.ai}  vs  {baseline}")
    print(f"  fights   {played} ({args.seeds} seeds, both sides)")
    print(f"  record   {wins}W {losses}L {draws}D")
    print(f"  win rate {rate:.1f}% of decided fights")
    print(f"  turns    median {statistics.median(turns):.0f}, max {max(turns)}")
    print(f"  damage   dealt {statistics.mean(dealt):.0f} avg, taken {statistics.mean(taken):.0f} avg")
    if errors:
        print(f"  ERRORS   {errors} AI error log lines — fix before trusting this")
    if draws:
        print(f"  note     {draws} draws are excluded from the win rate")

    return 0 if wins >= losses else 1


if __name__ == "__main__":
    sys.exit(main())
