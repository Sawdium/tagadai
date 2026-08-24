#!/usr/bin/env python3
"""
AI Bench - decide whether an AI change actually helped.

Plays AI **A** (`--ai`) against AI **B** (`--ai2`) over a range of seeds. Each
seed is played twice, with the two AIs swapped between the two sides, and the
two fights of a seed are kept together as a *pair* -- that pairing is the whole
point, and pooling it away is what made the previous version blind.

Why the pairing matters
-----------------------
The generator draws turn order in `StartOrder.compute` from the seeded RNG, and
that draw depends only on the entities' frequency, so it consumes the same RNG
values in both orientations of a seed: the same *team slot* moves first both
times. On a mirrored build the two fights of a seed are therefore exact
reflections of each other, and two identical AIs are FORCED to score 1W-1L on
every seed. Pooled over N seeds that is exactly 50%, no matter how big N is,
and no matter how different the AIs are -- the pooled rate mostly measures the
seat advantage, not the code.

What carries signal is *discordance between the two orientations of a seed*:

    sweep_A   A wins both orientations  (A wins even from the bad seat)
    sweep_B   B wins both orientations
    split     one each, or a draw       (carries no information)

Under the null "the two AIs are behaviourally interchangeable", the swap makes
sweep_A and sweep_B equally likely, so conditional on the number of discordant
pairs D the count of A-sweeps is Binomial(D, 0.5). The exact two-sided binomial
on those D pairs is the right small-sample test -- this is the exact form of
McNemar's test. "0 of 24 pairs discordant" is a real measurement (no behavioural
difference detected), where "12W-12L over 24 fights" was noise.

Usage
-----
    # calibration: the same AI against itself on a mirrored build.
    # MUST come out 0 sweeps / 0 sweeps.
    python -m src.tools.aibench --ai tagadalive/main --leek Claudius --seeds 8

    # A vs B on a mirrored build
    python -m src.tools.aibench --ai tagadalive/main --ai2 tagadargb/main

    # non-mirror: different builds on the two sides, which frees the seat draw
    # from the symmetry that forces 1W-1L
    python -m src.tools.aibench --ai tagadalive/main --ai2 tagadargb/main \\
        --leek Claudius --vs tagadagain:JCGloomy

    # a whole opponent panel: every --pair is A-build vs B-build
    python -m src.tools.aibench --ai tagadalive/main --ai2 tagadargb/main \\
        --pair Claudius,tagadagain:JCGloomy \\
        --pair Claudias,tagadagain:RebeccaSyphilis \\
        --pair Claudios,tagadalone:twogether --seeds 6

Leeks are named `account:Name` (or plain `Name` on the default `.env` account;
the four `tagadagain` / `tagadalone` leeks are also found by bare name).

Exit code is 0 unless the test is significant AND B is the winner, so this can
gate a commit.
"""

import argparse
import json
import math
import statistics
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Optional
from dataclasses import dataclass

from src.common.errors import TagadAIError
from src.localfight.pool import LeekPool, LeekRef
from src.localfight.batch import GeneratorPool
from src.localfight.runner import RunnerError, run_fight_raw
from src.tools.localfight import build_scenario, collect_logs, link_ai_tree

# Generator log levels that mean the AI misbehaved rather than just talked.
ERROR_LEVELS = {3, 8}

# Every action that takes HP off somebody, as `[code, victim_fid, hp, erosion]`
# (generator `ActionDamage` / `DamageType`). Victim-side accounting needs no
# attribution at all -- a[1] always names who lost the HP -- which is why the
# old "credit it to whoever LEEK_TURN last named" logic is gone: it missed
# poison, nova and damage-return entirely (on a magic build code 101 is barely
# 1% of the HP that moves) and booked self-damage to the wrong side.
DAMAGE_CODES = {
    101,   # LOST_LIFE   direct
    107,   # NOVA_DAMAGE
    108,   # DAMAGE_RETURN
    109,   # LIFE_DAMAGE
    110,   # POISON_DAMAGE  (the generator also emits AFTEREFFECT as 110)
    111,   # AFTEREFFECT    (reserved upstream; kept so a future split counts)
}
HEAL_CODES = {103}            # HEAL, `[103, target, hp]`
VITALITY_CODES = {104, 112}   # VITALITY / NOVA_VITALITY, raise current AND max
NEW_TURN = 6


# ---------------------------------------------------------------- one fight


@dataclass
class Fight:
    """One played fight, reduced to what the statistics need."""

    winner: int                # 0-based slot index, <0 for a draw
    turns: int
    errors: int
    hp_lost: list[int]         # HP taken off each slot
    healed: list[int]          # HP put back on each slot
    hp_frac: list[float]       # HP remaining / max HP at the end

    def net_swing(self, side: int) -> int:
        """Net HP `side` removed from the other one, healing netted out."""
        other = 1 - side
        return (self.hp_lost[other] - self.healed[other]) - (
            self.hp_lost[side] - self.healed[side]
        )


def measure(result: dict) -> Fight:
    """Reduce a raw generator result to a Fight, by victim-side accounting."""
    fight = result.get("fight") or {}
    actions = fight.get("actions") or []
    leeks = fight.get("leeks") or []

    # The generator renumbers entities 0,1,... in scenario order, and every
    # damage/heal action names that renumbered id. Slot index == that id here
    # because each team holds exactly one entity.
    slot = {int(l["id"]): i for i, l in enumerate(leeks)}
    base = [int(l.get("life", 0)) for l in leeks]

    n = max(2, len(leeks))
    lost = [0] * n
    healed = [0] * n
    vitality = [0] * n
    eroded = [0] * n

    for a in actions:
        if not isinstance(a, list) or len(a) < 3:
            continue
        code = a[0]
        i = slot.get(a[1])
        if i is None:
            continue
        if code in DAMAGE_CODES:
            lost[i] += a[2]
            if len(a) > 3 and isinstance(a[3], int):
                eroded[i] += a[3]
        elif code in HEAL_CODES:
            healed[i] += a[2]
        elif code in VITALITY_CODES:
            vitality[i] += a[2]

    frac = []
    for i in range(n):
        life = base[i] if i < len(base) else 0
        top = life + vitality[i] - eroded[i]
        cur = life + vitality[i] + healed[i] - lost[i]
        frac.append(max(0.0, min(1.0, cur / top)) if top > 0 else 0.0)

    return Fight(
        winner=result.get("winner", -1),
        turns=sum(1 for a in actions if isinstance(a, list) and a and a[0] == NEW_TURN),
        errors=sum(1 for _, lvl, _ in collect_logs(result) if lvl in ERROR_LEVELS),
        hp_lost=lost[:2],
        healed=healed[:2],
        hp_frac=frac[:2],
    )


def play(entities: list[dict], seed: int, turns: int, timeout: float,
         gen: Optional[GeneratorPool] = None) -> Fight:
    scenario = json.dumps(build_scenario(entities, seed, turns))
    if gen is not None:
        return measure(gen.run(scenario))
    return measure(json.loads(run_fight_raw(scenario, timeout=timeout)))


# ---------------------------------------------------------------- statistics


def binom_exact_two_sided(a: int, b: int) -> float:
    """Two-sided exact binomial p-value for `a` successes in `a+b` at p=0.5.

    This is the exact McNemar test applied to the discordant pairs: only they
    carry information, and the normal approximation is not usable at the tens
    of pairs a local benchmark can afford.
    """
    n = a + b
    if n == 0:
        return 1.0
    k = min(a, b)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / (2 ** n)
    return min(1.0, 2 * tail)


@dataclass
class Pair:
    """The two orientations of one seed, kept together."""

    seed: int
    fights: list[Fight]        # index 0: A on slot 0. index 1: A on slot 1.
    a_slots: list[int]         # which slot A held in each fight

    def a_wins(self) -> list[bool]:
        return [f.winner == s for f, s in zip(self.fights, self.a_slots)]

    def b_wins(self) -> list[bool]:
        return [f.winner == 1 - s for f, s in zip(self.fights, self.a_slots)]

    @property
    def verdict(self) -> str:
        if all(self.a_wins()):
            return "sweep_A"
        if all(self.b_wins()):
            return "sweep_B"
        return "split"


# ---------------------------------------------------------------- the run


def orientations(
    pool: LeekPool, build_a: LeekRef, build_b: LeekRef, ai_a: str, ai_b: str
) -> list[tuple[list[dict], int]]:
    """The two (entity list, slot-of-A) orientations of a seed.

    Slot 0 always carries `build_a` and slot 1 `build_b`; what swaps is which
    AI drives which. On a mirror (build_a == build_b) that is the same thing as
    swapping sides. On a non-mirror panel it swaps build *and* seat together,
    which is what controls both advantages with two fights instead of four.
    """
    return [
        ([pool.entity(build_a, 1, ai_a), pool.entity(build_b, 2, ai_b)], 0),
        ([pool.entity(build_a, 1, ai_b), pool.entity(build_b, 2, ai_a)], 1),
    ]


def run(args, pool: LeekPool, matchups: list[tuple[LeekRef, LeekRef]]) -> list[Pair]:
    baseline = args.ai2 or args.ai
    for ai in {args.ai, baseline}:
        link_ai_tree(ai)

    jobs = []
    for m, (build_a, build_b) in enumerate(matchups):
        for entities, a_slot in orientations(pool, build_a, build_b, args.ai, baseline):
            for i in range(args.seeds):
                jobs.append((m, args.first_seed + i, a_slot, entities))

    with GeneratorPool(workers=args.jobs, timeout=args.timeout) as gen, \
            ThreadPoolExecutor(max_workers=gen.workers) as pool_exec:
        played = list(pool_exec.map(
            lambda j: play(j[3], j[1], args.turns, args.timeout, gen),
            jobs,
        ))

    # Re-assemble the pairs: a pair is (matchup, seed) and its two members are
    # the two orientations, i.e. the two a_slot values.
    grouped: dict[tuple[int, int], dict[int, Fight]] = {}
    for (m, seed, a_slot, _), fight in zip(jobs, played):
        grouped.setdefault((m, seed), {})[a_slot] = fight

    return [Pair(seed, [by_slot[0], by_slot[1]], [0, 1])
            for (_, seed), by_slot in sorted(grouped.items())
            if len(by_slot) == 2]


# ---------------------------------------------------------------- reporting


def summarise(pairs: list[Pair]) -> dict:
    sweep_a = sum(1 for p in pairs if p.verdict == "sweep_A")
    sweep_b = sum(1 for p in pairs if p.verdict == "sweep_B")
    split = len(pairs) - sweep_a - sweep_b

    fights = [(f, s) for p in pairs for f, s in zip(p.fights, p.a_slots)]
    wins = sum(1 for f, s in fights if f.winner == s)
    draws = sum(1 for f, _ in fights if f.winner < 0)
    losses = len(fights) - wins - draws

    winner_hp = [f.hp_frac[f.winner] for f, _ in fights if 0 <= f.winner < 2]

    return {
        "seeds": len(pairs),
        "sweep_A": sweep_a,
        "sweep_B": sweep_b,
        "split": split,
        "discordant": sweep_a + sweep_b,
        "p_value": binom_exact_two_sided(sweep_a, sweep_b),
        "fights": len(fights),
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "errors": sum(f.errors for f, _ in fights),
        "net_hp_swing": statistics.mean(f.net_swing(s) for f, s in fights) if fights else 0.0,
        "winner_hp_left": statistics.mean(winner_hp) if winner_hp else 0.0,
        "turns_median": statistics.median(f.turns for f, _ in fights) if fights else 0,
        "turns_max": max((f.turns for f, _ in fights), default=0),
    }


def report(args, s: dict, panel: list[str], alpha: float) -> None:
    baseline = args.ai2 or args.ai
    print(f"A = {args.ai}")
    print(f"B = {baseline}")
    for line in panel:
        print(f"    {line}")
    print(f"    {s['seeds']} seeds x 2 orientations = {s['fights']} fights")
    print()

    print("PAIRED RESULT  (the headline)")
    print(f"  seed-pairs      {s['seeds']}")
    print(f"  A sweeps        {s['sweep_A']}   (A wins BOTH orientations of the seed)")
    print(f"  B sweeps        {s['sweep_B']}")
    print(f"  split           {s['split']}   (one each, or a draw - carries no information)")
    print(f"  discordant      {s['discordant']}   (only these enter the test)")
    print("  H0: the two AIs are behaviourally interchangeable, so a seed decided")
    print("      the same way from both seats is equally likely to be swept by")
    print("      either of them  -> sweep_A ~ Binomial(discordant, 0.5)")
    print(f"  exact two-sided binomial (McNemar)   p = {s['p_value']:.4f}")
    if s["discordant"] == 0:
        print(f"  => no behavioural difference detected in {s['seeds']} seed-pairs")
    elif s["p_value"] < alpha:
        better = "A" if s["sweep_A"] > s["sweep_B"] else "B"
        print(f"  => reject H0 at alpha={alpha}: {better} is stronger")
    else:
        print(f"  => cannot reject H0 at alpha={alpha}: no difference demonstrated")
    print()

    print("RAW FIGHT RECORD  (secondary - pooling throws the pairing away)")
    decided = s["wins"] + s["losses"]
    rate = 100.0 * s["wins"] / decided if decided else 0.0
    print(f"  {s['fights']} fights: {s['wins']}W {s['losses']}L {s['draws']}D  ({rate:.1f}% of decided)")
    if any("[mirror]" in line for line in panel):
        print("  On a mirrored build two identical AIs are FORCED to 1W-1L per seed,")
        print("  so a pooled 50% here means nothing on its own.")
    print()

    print("DIAGNOSTIC MARGINS  (strength signals only - NOT tuning objectives)")
    print(f"  net HP swing     {s['net_hp_swing']:+.0f} per fight, A's favour "
          f"(HP removed from B minus HP removed from A, healing netted)")
    print(f"  winner HP left   {100 * s['winner_hp_left']:.1f}% of max")
    print(f"  turns to decide  median {s['turns_median']:.0f}, max {s['turns_max']}")
    if s["errors"]:
        print()
        print(f"  ERRORS   {s['errors']} AI error log lines - fix before trusting any of this")


# ---------------------------------------------------------------- entry point


def resolve_panel(pool: LeekPool, args) -> list[tuple[LeekRef, LeekRef]]:
    if args.pair:
        out = []
        for spec in args.pair:
            left, _, right = spec.partition(",")
            if not right:
                raise TagadAIError(f"--pair wants 'buildA,buildB', got {spec!r}")
            out.append((pool.resolve(left.strip()), pool.resolve(right.strip())))
        return out

    build_a = pool.resolve(args.leek) if args.leek else pool.first(args.account or "")
    build_b = pool.resolve(args.vs) if args.vs else build_a
    return [(build_a, build_b)]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Paired head-to-head benchmark of two AI revisions",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--ai", default="tagadalive/main", help="AI under test (A)")
    parser.add_argument("--ai2", help="baseline AI (B; default: same as --ai, a calibration run)")
    parser.add_argument("--leek", help="build for side A ('Name' or 'account:Name')")
    parser.add_argument("--vs", help="build for side B (default: same as --leek, a mirror)")
    parser.add_argument("--pair", action="append", metavar="A,B",
                        help="a matchup 'buildA,buildB'; repeatable, for an opponent panel")
    parser.add_argument("--seeds", type=int, default=24, help="seeds per matchup (default: 24)")
    parser.add_argument("--first-seed", type=int, default=1)
    parser.add_argument("--turns", type=int, default=64, help="max turns before a draw")
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("--alpha", type=float, default=0.05, help="significance level")
    parser.add_argument("--jobs", type=int, default=None,
                        help="fights to run in parallel (default: physical cores)")
    parser.add_argument("--account", help="Override LEEKWARS_LOGIN (password from .env)")
    parser.add_argument("--json", action="store_true", help="machine-readable summary")
    args = parser.parse_args()

    try:
        pool = LeekPool(default_login=args.account or "")
        matchups = resolve_panel(pool, args)
        panel = []
        for a, b in matchups:
            mirror = "  [mirror]" if a == b else ""
            panel.append(f"{a} [{pool.cores(a)} cores = {pool.cores(a)}M ops] "
                         f"vs {b} [{pool.cores(b)} cores = {pool.cores(b)}M ops]{mirror}")
        pairs = run(args, pool, matchups)
    except (TagadAIError, RunnerError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    s = summarise(pairs)
    if args.json:
        print(json.dumps({"a": args.ai, "b": args.ai2 or args.ai,
                          "panel": panel, **s}, indent=2))
    else:
        report(args, s, panel, args.alpha)

    # Fail only on a demonstrated regression, never on noise.
    worse = s["p_value"] < args.alpha and s["sweep_B"] > s["sweep_A"]
    return 1 if worse else 0


if __name__ == "__main__":
    sys.exit(main())
