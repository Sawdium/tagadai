#!/usr/bin/env python3
"""
Danger Probe - measure how well MapDanger predicts the damage actually taken.

The danger map is a *conditional worst case*: for each enemy it picks the best
damage-per-TP item and spends that enemy's TP on it, respecting use limits,
until the TP runs out. It answers "what could this cell cost me if every enemy
went fully offensive", NOT "what will this cell cost me".

So the gap between predicted and realized is not an error and is not measured
here. A cell chosen well is one the enemy decides not to attack from -- it
buffs instead -- and the danger going unspent is the map doing its job. Only
one number is a defect:

    **when is the realized damage ABOVE the danger that was predicted?**

That is the bound being wrong, and it is the only thing this tool scores.
Everything else it prints (how much was left on the table, how often nothing
happened) is context for reading the breaches, never a quality signal.

    predicted  the Danger of the cell our leek finishes its turn on, logged by
               the probe block in `tagadalive/main` (Benchmark.DEBUG_DANGER)
    realized   the HP actually taken off that leek before its next turn, read
               victim-side out of the fight's action list

Usage:
    python -m src.tools.dangerprobe --seeds 40
    python -m src.tools.dangerprobe --seeds 40 --leek Claudius --leek2 Claudias
    python -m src.tools.dangerprobe --seeds 100 --jobs 8 --csv danger.csv
    python -m src.tools.dangerprobe --csv danger.csv --report-only  # re-analyse

The AI tree is copied to `.dangerprobe/` with the probe flag flipped on, so the
shipped `tagadalive/` keeps paying zero operations for it and live fight logs
stay clean. The copy is rebuilt on every run -- never edit it.
"""

from __future__ import annotations

import argparse
import csv
import re
import json
import shutil
import statistics
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, asdict
from pathlib import Path

from src.common.config import get_paths
from src.common.errors import TagadAIError
from src.localfight.pool import LeekPool, LeekRef
from src.localfight.runner import RunnerError, run_fight_raw
from src.tools.localfight import build_scenario, collect_logs, link_ai_tree

PROBE_TREE = ".dangerprobe"
PROBE_AI = f"{PROBE_TREE}/main"
PROBE_TAG = "DNGP|"
# MapDanger._logEarlyExit's debugW, e.g.
#   "leek T12 MapDanger Phase2 early exit @4.2M | E:3/7 (JCGloomy:3/7) | S:1/1 | D:0/0"
# The round-robin walks item index i across all enemies and stops the moment
# 35% of the turn budget is gone, so E:3/7 means items 4..7 -- ordered by
# damage-per-TP, so the cheap-per-TP but heavy-hitting ones -- were never given
# a reach map at all, and `computeDanger` skips them silently.
EARLY_EXIT = re.compile(r"T(\d+) MapDanger (\w+) early exit .*?\| E:(\d+)/(\d+)")

# Action codes, generator-side (src/localfight/parser.py carries the full note).
NEW_TURN = 6
LEEK_TURN = 7
END_TURN = 8
DEATH = 5
SUMMON = 9                     # [9, owner, summon_id, cell, result]
USE_CHIP = 12                  # [12, chip_id, cell, success] -- caster is the current actor
# What actually comes off our HP, matched to what `Damages.computeDanger` puts
# in `Danger.dmg`: EFFECT_DAMAGE -> 101 and EFFECT_LIFE_DAMAGE -> 109.
#
# 107 (NOVA) is NOT HP. `EffectNovaDamage` calls `removeLife(0, value, ...)`:
# pv is zero and the whole value goes to erosion, capped at the HP already
# missing. It lowers MAX life, current life never moves. Counting it as damage
# taken invents breaches out of nothing -- on a science build it is the largest
# number in the log (808 against 146 of real damage, on the first turn checked).
#
# 108 (DAMAGE_RETURN) is the recoil of our own attack, which the danger map
# never claimed to predict. Recorded separately so a breach caused by recoil is
# recognisable instead of being blamed on the model.
INSTANT_CODES = {101, 109}
POISON_CODES = {110, 111}      # POISON and AFTEREFFECT both land on 110
NOVA_CODE = 107                # max-life erosion, tracked but never a breach
RETURN_CODE = 108
HEAL_CODE = 103


# ------------------------------------------------------------------ AI tree


def build_probe_tree(source: str = "tagadalive") -> None:
    """Copy the AI tree with Benchmark.DEBUG_DANGER flipped to true."""
    root = get_paths().root
    src, dst = root / source, root / PROBE_TREE
    if not src.is_dir():
        raise TagadAIError(f"No AI tree at {src}")
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(".git", "__pycache__"))

    bench = dst / "Services" / "Benchmark"
    text = bench.read_text()
    flag = "static final boolean DEBUG_DANGER = false"
    if flag not in text:
        raise TagadAIError(
            f"{bench} has no `{flag}` line -- the probe block in `main` and the "
            "flag in Services/Benchmark must both exist for this tool to work."
        )
    bench.write_text(text.replace(flag, flag.replace("false", "true"), 1))

    if PROBE_TAG not in (dst / "main").read_text():
        raise TagadAIError(
            f"{dst / 'main'} has no `{PROBE_TAG}` debug line -- nothing would be "
            "logged. Restore the probe block at the end of `main`."
        )


# ------------------------------------------------------------- one fight


@dataclass
class Observation:
    """One (leek, turn) prediction and what actually happened to it."""

    seed: int
    fight: int
    leek: int
    name: str
    turn: int
    cell: int
    pred_dmg: int          # Danger.dmg     -- instant HP damage predicted
    pred_psn: int          # Danger.psnDmg  -- damage-over-time predicted
    hp: int                # HP at the end of our turn
    max_hp: int
    tp_left: int
    mp_left: int
    enemies: int
    allies: int
    is_bulb: int
    nearest: int           # cell distance to the closest live enemy, -1 if none
    raw_dmg: int           # same cell, danger computed without the combo's consequences
    raw_psn: int
    abs_shield: int        # our shields as the danger map read them, at turn start
    rel_shield: int
    enemy_items: int       # offensive items the map kept for the enemies
    enemy_mapped: int      # of those, how many got a reach map before the budget cap
    near_mp: int           # MP the map credited the closest enemy with (its CURRENT MP)
    near_max_mp: int       # MP that enemy will actually have on its turn
    psn_turn: int          # DoT already on us per turn when the turn started
    psn_total: int         # ... and over its whole remaining duration
    # Defaulted so CSVs written before these columns existed still read back.
    post_abs: int = 0      # shields computeDanger starts from (post-combo, via consequences)
    post_rel: int = 0
    ally_has_shield: int = 0  # BattleState.allyHasShield -- gate 1
    libe_mapped: int = 0      # enemies holding a liberation coverage map -- gate 2
    real_instant: int = 0  # HP taken between our END_TURN and our next LEEK_TURN
    real_poison: int = 0   # poison ticks over the same window plus our own turn
    real_return: int = 0   # our attack's recoil, excluded from `real_instant`
    real_nova: int = 0     # max-life erosion taken; not HP, never a breach
    healed: int = 0        # HP put back over the window (a heal hides damage)
    enemy_summons: int = 0 # bulbs the enemy called up INSIDE the window -- entities
                           # that did not exist when the danger was computed
    # Defaulted so a CSV written before this column existed still reads back.
    danger_items_done: int = 0   # enemy item rounds the danger map completed this turn
    danger_items_total: int = 0  # ... out of this many. done < total = budget truncation
    enemy_chips: str = ""  # chip templates the enemies cast inside the window, ';'-joined.
                           # The bound assumes every TP goes into the best
                           # damage-per-TP item; anything here is TP the enemy
                           # spent otherwise -- and a TP refund or a strength buff
                           # makes the rest of its turn hit harder than modelled.
    censored: int = 0      # 1 = we died, or the fight ended, inside the window

    # The bound is on the TOTAL, not on either component. `computeDanger`
    # spends each enemy's TP greedily on its best damage-per-TP item, so a
    # poison build's whole budget lands in `psnDmg` and `dmg` stays 0 even
    # though the enemy will in fact fire a weapon too. Scoring uses
    # `dmg + psnDmg` (Danger.score), and that sum is what has to hold.

    @property
    def predicted(self) -> int:
        return self.pred_dmg + self.pred_psn

    @property
    def realized(self) -> int:
        """HP the ENEMIES took off us over the window.

        Two corrections, both mandatory:

        * ally healing is already subtracted from the prediction by the ally
          branch of `computeDanger`, so it has to come off here too;
        * poison already ticking on us when the turn started is not something a
          cell's Danger claims to bound -- it lands on us wherever we stand.
          Left in, it swamps the measurement: of 208 breaches in the first
          20-seed run, 154 were pure pre-existing poison, at a median distance
          of 15 cells from the nearest enemy.
        """
        own_dot = max(0, self.psn_turn)
        return (self.real_instant + max(0, self.real_poison - own_dot)
                - self.healed)

    @property
    def violation(self) -> int:
        """HP by which reality beat the worst case. 0 when the bound held."""
        return max(0, self.realized - self.predicted)

    @property
    def slack(self) -> int:
        """HP the bound had to spare. Negative when it was breached."""
        return self.predicted - self.realized

    @property
    def instant_violation(self) -> int:
        """Component split: the instant part alone against `dmg` alone."""
        return max(0, (self.real_instant - self.healed) - self.pred_dmg)


def parse_probe_line(text: str) -> list[int] | None:
    """`DNGP|turn|cell|dmg|psn|hp|maxhp|tp|mp|enemies|allies|bulb|nearest|rawdmg|rawpsn|abs|rel|enemyitems|enemymapped|nearmp|nearmaxmp|psnturn|psntotal|postabs|postrel|hasshield|libemapped`."""
    if not text.startswith(PROBE_TAG):
        return None
    parts = text[len(PROBE_TAG):].split("|")
    if len(parts) != 26:
        return None
    try:
        return [int(p) for p in parts]
    except ValueError:
        return None


def damage_windows(actions: list) -> dict:
    """Per (leek, turn) index of the action slices that follow our turn.

    Window A runs from our END_TURN to our next LEEK_TURN: everything the
    enemies do while we stand on the cell we chose. That is exactly what the
    danger map claims to bound.

    Window B is our own next turn, up to our next END_TURN. Poison ticks land
    there -- they are charged to the victim at the start of its own turn -- so
    `psnDmg` can only be checked against A+B.
    """
    turn = 0
    actor = None
    # (leek, turn) -> [start_of_A, start_of_B, end_of_B]
    marks: dict[tuple[int, int], list[int]] = {}
    open_for: dict[int, tuple[int, int]] = {}   # leek -> its last (leek, turn) key
    for i, a in enumerate(actions):
        code = a[0]
        if code == NEW_TURN:
            turn = a[1]
        elif code == LEEK_TURN:
            actor = a[1]
            key = open_for.get(actor)
            if key is not None and marks[key][1] is None:
                marks[key][1] = i
        elif code == END_TURN:
            leek = a[1]
            key = open_for.get(leek)
            if key is not None and marks[key][2] is None:
                marks[key][2] = i
            key = (leek, turn)
            marks[key] = [i, None, None]
            open_for[leek] = key
    return marks


def measure(result: dict, seed: int, names: dict[int, str],
            teams: dict[int, int] | None = None) -> list[Observation]:
    """Join every probe line in the logs to the damage that followed it."""
    fight = result.get("fight") or {}
    actions = fight.get("actions") or []
    marks = damage_windows(actions)
    dead_at: dict[int, int] = {}
    for i, a in enumerate(actions):
        if a[0] == DEATH:
            dead_at.setdefault(a[1], i)

    # Truncation notices, keyed by (leek, turn), read off the same log stream.
    truncated: dict[tuple[int, int], tuple[int, int]] = {}
    for leek, level, text in collect_logs(result):
        m = EARLY_EXIT.search(text)
        if m:
            truncated[(leek, int(m.group(1)))] = (int(m.group(3)), int(m.group(4)))

    out: list[Observation] = []
    for leek, level, text in collect_logs(result):
        row = parse_probe_line(text)
        if row is None:
            continue
        (turn, cell, pdmg, ppsn, hp, maxhp, tp, mp,
         enemies, allies, bulb, nearest, rawdmg, rawpsn,
         absh, relh, eitems, emapped, nmp, nmaxmp, psnturn, psntotal,
         postabs, postrel, hasshield, libemapped) = row
        window = marks.get((leek, turn))
        if window is None:
            continue
        start, mid, end = window
        mid = mid if mid is not None else len(actions)
        end = end if end is not None else len(actions)

        teams = teams or {}
        my_team = teams.get(leek)
        summons = 0
        chips: list[int] = []
        actor = None
        inst = psn = ret = heal = nova = 0
        for i in range(start + 1, end):
            a = actions[i]
            code, victim = a[0], (a[1] if len(a) > 1 else None)
            if code == LEEK_TURN:
                actor = victim
            elif (code == USE_CHIP and i < mid and my_team is not None
                    and teams.get(actor) not in (None, my_team)):
                chips.append(victim)
            if code == SUMMON and i < mid and my_team is not None:
                # a[1] is the OWNER. A bulb summoned after we chose our cell was
                # not in `getEntitiesAfterSelfInOrder()` when the danger for that
                # cell was computed, so nothing it does could have been bounded.
                if teams.get(victim) not in (None, my_team):
                    summons += 1
            if victim != leek:
                continue
            amount = a[2] if len(a) > 2 else 0
            if code in POISON_CODES:
                # Poison is charged to the victim at the start of its own turn,
                # so it can only be checked over window A *and* window B.
                psn += amount
            elif i < mid:
                if code in INSTANT_CODES:
                    inst += amount
                elif code == NOVA_CODE:
                    nova += amount
                elif code == RETURN_CODE:
                    ret += amount
                elif code == HEAL_CODE:
                    heal += amount

        death = dead_at.get(leek)
        censored = int(
            (death is not None and death < mid) or window[1] is None
        )
        out.append(Observation(
            seed=seed, fight=result.get("id", 0), leek=leek,
            name=names.get(leek, str(leek)), turn=turn, cell=cell,
            pred_dmg=pdmg, pred_psn=ppsn, hp=hp, max_hp=maxhp, tp_left=tp,
            mp_left=mp, enemies=enemies, allies=allies, is_bulb=bulb,
            nearest=nearest, raw_dmg=rawdmg, raw_psn=rawpsn,
            abs_shield=absh, rel_shield=relh, enemy_items=eitems,
            enemy_mapped=emapped, near_mp=nmp, near_max_mp=nmaxmp,
            psn_turn=psnturn, psn_total=psntotal, post_abs=postabs,
            post_rel=postrel, ally_has_shield=hasshield, libe_mapped=libemapped,
            real_instant=inst, real_poison=psn,
            real_return=ret, real_nova=nova, healed=heal,
            enemy_summons=summons,
            danger_items_done=truncated.get((leek, turn), (0, 0))[0],
            danger_items_total=truncated.get((leek, turn), (0, 0))[1],
            enemy_chips=";".join(str(c) for c in chips),
            censored=censored,
        ))
    return out


# Generator timings, in seconds, one entry per fight played this run.
TIMINGS: list[tuple[float, float, int]] = []   # (compile, execute, turns)


def play(entities: list[dict], seed: int, turns: int, timeout: float) -> list[Observation]:
    scenario = build_scenario(entities, seed, turns)
    result = json.loads(run_fight_raw(json.dumps(scenario), timeout=timeout))
    TIMINGS.append((result.get("compilation_time", 0) / 1e9,
                    result.get("execution_time", 0) / 1e9,
                    result.get("duration", 0)))
    leeks = (result.get("fight") or {}).get("leeks", [])
    names = {l["id"]: l.get("name", str(l["id"])) for l in leeks}
    teams = {l["id"]: l.get("team") for l in leeks}
    return measure(result, seed, names, teams)


# ------------------------------------------------------------------ report


def load_chip_names() -> dict[int, str]:
    """Chip TEMPLATE -> name, from the generator's own data files.

    `ActionUseChip` logs `chip.getTemplate()`, not the chip id that keys
    `chips.json`. Keying by the id silently mislabels the table: it resolves
    the handful of chips whose id happens to be another chip's template and
    calls everything else unknown.
    """
    path = get_paths().generator_dir / "data" / "chips.json"
    try:
        chips = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return {int(v["template"]): v.get("name", k)
            for k, v in chips.items() if v.get("template") is not None}


def pct(part: int, whole: int) -> float:
    return 100.0 * part / whole if whole else 0.0


def coverage(rows: list[Observation]) -> dict:
    """The worst-case statistics: how often, and by how much, reality wins."""
    n = len(rows)
    exposed = [r for r in rows if r.predicted > 0 or r.realized > 0]
    breaches = [r for r in rows if r.violation > 0]
    blind = [r for r in breaches if r.predicted == 0]
    over = [r for r in rows if r.predicted > 0 and r.realized <= 0]
    split = [r for r in rows if r.instant_violation > 0 and r.violation == 0]
    return {
        "observations": n,
        "exposed": len(exposed),
        "breaches": len(breaches),
        "breach_rate": pct(len(breaches), len(exposed)),
        "blind_spots": len(blind),
        "predicted_nothing_happened": len(over),
        "split_only": len(split),
        "breach_hp_median": statistics.median([r.violation for r in breaches]) if breaches else 0,
        "breach_hp_max": max((r.violation for r in breaches), default=0),
        "breach_frac_median": statistics.median(
            [r.realized / r.predicted for r in breaches if r.predicted > 0]
        ) if any(r.predicted > 0 for r in breaches) else 0.0,
        "unspent_frac_median": statistics.median(
            [r.realized / r.predicted for r in exposed if r.predicted > 0]
        ) if any(r.predicted > 0 for r in exposed) else 0.0,
        # Overshoot measured against the leek's own max HP: 40 HP on a 3700 HP
        # leek and 400 are the same breach rate and very different problems.
        "breach_pct_hp_median": statistics.median(
            [100.0 * r.violation / r.max_hp for r in breaches]) if breaches else 0.0,
        "breach_pct_hp_max": max(
            (100.0 * r.violation / r.max_hp for r in breaches), default=0.0),
        "breach_over_10pct": sum(1 for r in breaches if r.violation * 10 > r.max_hp),
    }


def slices(rows: list[Observation]) -> dict[str, dict]:
    """The same coverage stats cut by the conditions that could explain it."""
    def bucket(r: Observation) -> dict[str, str]:
        return {
            "enemies": f"{r.enemies} enemy" if r.enemies < 3 else "3+ enemies",
            "closest enemy MP": (
                "no enemy" if r.near_max_mp < 0 else
                "full MP" if r.near_mp >= r.near_max_mp else
                "spent some" if r.near_mp > 0 else "spent all"),
            "distance": ("adjacent" if 0 <= r.nearest <= 1 else
                         "close 2-6" if r.nearest <= 6 else
                         "far 7+" if r.nearest > 6 else "no enemy"),
            "turn": "T1-3" if r.turn <= 3 else "T4-8" if r.turn <= 8 else "T9+",
            "hp": ("hp<25%" if r.hp * 4 < r.max_hp else
                   "hp<50%" if r.hp * 2 < r.max_hp else "hp>=50%"),
            "who": "bulb" if r.is_bulb else "leek",
            "enemy summoned in window": "yes" if r.enemy_summons else "no",
            "danger map truncated": (
                "yes" if r.danger_items_total and r.danger_items_done < r.danger_items_total
                else "no"),
            "leek": r.name,
        }

    grouped: dict[str, dict[str, list[Observation]]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        for dim, key in bucket(r).items():
            grouped[dim][key].append(r)
    return {dim: {key: coverage(rs) for key, rs in sorted(keys.items())}
            for dim, keys in grouped.items()}


def report(rows: list[Observation], worst: int) -> None:
    live = [r for r in rows if not r.censored]
    print(f"\n  danger model, worst-case coverage")
    print(f"    {len(rows)} observations ({len(rows) - len(live)} censored by a "
          f"death in the window, dropped)")

    c = coverage(live)
    print("    bound = Danger.dmg + Danger.psnDmg   vs   HP the enemies took off us")
    print("    (realized = instant + poison, minus the DoT already ticking on us "
          "and minus ally heals)")
    print(f"    exposed turns (something predicted or something happened): {c['exposed']}")
    print(f"    BREACHES (realized ABOVE the danger predicted): {c['breaches']}  "
          f"= {c['breach_rate']:.1f}% of exposed turns")
    print(f"      median overshoot {c['breach_hp_median']:.0f} HP "
          f"({c['breach_pct_hp_median']:.1f}% of max HP), "
          f"worst {c['breach_hp_max']:.0f} HP ({c['breach_pct_hp_max']:.1f}%)")
    print(f"      breaches costing more than 10% of max HP: {c['breach_over_10pct']}")
    if c["breach_frac_median"]:
        print(f"      median breach took {c['breach_frac_median']:.2f}x what was predicted")
    print(f"    blind spots (predicted 0, took damage): {c['blind_spots']}")
    breaches = [r for r in live if r.violation > 0]
    consequence = [r for r in breaches if r.raw_dmg > r.pred_dmg]
    covered = [r for r in consequence if r.raw_dmg >= r.real_instant]
    print(f"    of those breaches, {len(consequence)} had a non-zero danger before "
          f"the combo's consequences were applied")
    print(f"      ({len(covered)} of them would have held without them: the miss is "
          f"the consequence simulation, not the danger model)")
    print(f"    bound held but the split was wrong (instant beat `dmg`, total held): "
          f"{c['split_only']}")
    print("\n  context, NOT defects -- a danger that goes unspent is a cell the enemy "
          "declined to attack")
    print(f"    turns where damage was predicted and none arrived: "
          f"{c['predicted_nothing_happened']}")
    print(f"    median realized/predicted when the bound held: "
          f"{c['unspent_frac_median']:.2f}")

    print("\n  when the prediction comes in UNDER what actually lands")
    ranked = []
    for dim, keys in slices(live).items():
        for key, st in keys.items():
            if st["exposed"] >= 10:
                ranked.append((st["breach_rate"], dim, key, st))
    for rate, dim, key, st in sorted(ranked, reverse=True):
        print(f"    {dim + ' = ' + key:<32} {rate:5.1f}% of {st['exposed']:>5} "
              f"exposed   median overshoot {st['breach_hp_median']:>5.0f} HP "
              f"({st['breach_pct_hp_median']:.1f}% HP)")

    if breaches:
        print("    breach profile: median abs shield "
              f"{statistics.median([r.abs_shield for r in breaches]):.0f}, rel "
              f"{statistics.median([r.rel_shield for r in breaches]):.0f}, "
              "enemy items kept "
              f"{statistics.median([r.enemy_items for r in breaches]):.0f}, mapped "
              f"{statistics.median([r.enemy_mapped for r in breaches]):.0f}")
        held = [r for r in live if r.violation == 0 and (r.pred_dmg or r.real_instant)]
        if held:
            print("    held profile:   median abs shield "
                  f"{statistics.median([r.abs_shield for r in held]):.0f}, rel "
                  f"{statistics.median([r.rel_shield for r in held]):.0f}, "
                  "enemy items kept "
                  f"{statistics.median([r.enemy_items for r in held]):.0f}, mapped "
                  f"{statistics.median([r.enemy_mapped for r in held]):.0f}")

    print("\n  poison (checked over our turn too, ticks land there)")
    psn = [r for r in live if r.pred_psn > 0 or r.real_poison > 0]
    if psn:
        breached = [r for r in psn if r.real_poison > r.pred_psn]
        print(f"    {len(psn)} turns with poison in play, "
              f"{pct(len(breached), len(psn)):.1f}% of them saw one turn of ticks "
              "exceed the whole predicted poison")
        print("    (`psnDmg` is duration-mitigated -- it stands for several future "
              "turns, so a single turn of ticks should normally come in under it)")
    else:
        print("    none in this sample")

    print("\n  what the enemies spent TP on, breach rate when they did vs when "
          "they did not")
    chip_names = load_chip_names()
    used: dict[int, list[Observation]] = defaultdict(list)
    for r in live:
        for c in {int(x) for x in r.enemy_chips.split(";") if x}:
            used[c].append(r)
    base = pct(sum(1 for r in live if r.violation > 0), len(live))
    rows_by_lift = []
    for chip, rs in used.items():
        if len(rs) < 20:
            continue
        rate = pct(sum(1 for r in rs if r.violation > 0), len(rs))
        rows_by_lift.append((rate - base, rate, chip, len(rs)))
    for lift, rate, chip, n in sorted(rows_by_lift, reverse=True)[:12]:
        print(f"    {chip_names.get(chip, str(chip)):<20} {rate:5.1f}% over {n:>5} turns "
              f"  ({lift:+.1f} pts vs the {base:.1f}% baseline)")

    print(f"\n  worst {worst} breaches (replay with --seed)")
    for r in sorted(live, key=lambda r: -r.violation)[:worst]:
        if r.violation == 0:
            break
        print(f"    seed {r.seed:<12} turn {r.turn:<3} {r.name:<12} cell {r.cell:<4} "
              f"predicted {r.predicted:>5} took {r.realized:>5} "
              f"(+{r.violation}, {r.enemies} enemies, dist {r.nearest}, "
              f"recoil {r.real_return}, erosion {r.real_nova})")


# -------------------------------------------------------------------- main


def write_csv(path: Path, rows: list[Observation]) -> None:
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(asdict(rows[0]).keys()))
        w.writeheader()
        for r in rows:
            w.writerow(asdict(r))


def read_csv(path: Path) -> list[Observation]:
    with path.open() as f:
        text = {"name", "enemy_chips"}
        return [Observation(**{k: (v if k in text else int(v)) for k, v in row.items()})
                for row in csv.DictReader(f)]


def main() -> int:
    p = argparse.ArgumentParser(description="Measure MapDanger's worst-case coverage")
    p.add_argument("--seeds", type=int, default=20, help="number of fights (default 20)")
    p.add_argument("--first-seed", type=int, default=1, help="first seed (default 1)")
    p.add_argument("--leek", default="", help="first leek, `account:Name` (default: first)")
    p.add_argument("--leek2", default="", help="second leek (default: same as --leek)")
    p.add_argument("--turns", type=int, default=64, help="max turns per fight")
    p.add_argument("--jobs", type=int, default=4, help="fights in parallel")
    p.add_argument("--timeout", type=float, default=600.0)
    p.add_argument("--csv", type=Path, help="write/read the observation table")
    p.add_argument("--report-only", action="store_true", help="re-analyse a --csv, run nothing")
    p.add_argument("--worst", type=int, default=10, help="how many breaches to list")
    p.add_argument("--source", default="tagadalive", help="AI tree to copy and probe")
    args = p.parse_args()

    try:
        if args.report_only:
            if not args.csv or not args.csv.exists():
                raise TagadAIError("--report-only needs an existing --csv")
            report(read_csv(args.csv), args.worst)
            return 0

        build_probe_tree(args.source)
        link_ai_tree(PROBE_AI)

        pool = LeekPool()
        ref1 = pool.resolve(args.leek) if args.leek else pool.first()
        ref2 = pool.resolve(args.leek2) if args.leek2 else ref1
        entities = [pool.entity(ref1, team=1, ai=PROBE_AI),
                    pool.entity(ref2, team=2, ai=PROBE_AI)]
        # Two leeks of the same account share an id, and the generator would
        # then log both under one entity. Renumber defensively.
        entities[1]["id"] = entities[1]["id"] + 1 if entities[0]["id"] == entities[1]["id"] \
            else entities[1]["id"]

        seeds = [args.first_seed + i for i in range(args.seeds)]
        print(f"  {ref1} vs {ref2}, {len(seeds)} seeds, AI {PROBE_AI}", file=sys.stderr)
        rows: list[Observation] = []
        with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as ex:
            for got in ex.map(
                lambda s: play(entities, s, args.turns, args.timeout), seeds
            ):
                rows.extend(got)
                print(f"\r  {len(rows)} observations", end="", file=sys.stderr)
        print(file=sys.stderr)

        if not rows:
            raise TagadAIError(
                "No probe lines came back. The copied tree may not have compiled, "
                "or the probe block in `main` is gone -- run a single "
                f"`python -m src.tools.localfight --ai {PROBE_AI} --logs` to see."
            )
        if TIMINGS:
            comp = [t[0] for t in TIMINGS]
            exe = [t[1] for t in TIMINGS]
            print(f"  generator time over {len(TIMINGS)} fights: "
                  f"compile {min(comp):.1f}/{statistics.mean(comp):.1f}/{max(comp):.1f}s, "
                  f"execute {min(exe):.1f}/{statistics.mean(exe):.1f}/{max(exe):.1f}s "
                  f"(min/mean/max)", file=sys.stderr)
        if args.csv:
            write_csv(args.csv, rows)
            print(f"  wrote {args.csv}", file=sys.stderr)
        report(rows, args.worst)
        return 0

    except (TagadAIError, RunnerError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
