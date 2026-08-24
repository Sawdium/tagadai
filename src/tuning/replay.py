"""
Replay a fight's action log into Texel states, so real LeekWars fights can
feed the fit without playing anything.

A fight replay (`/fight/get` -> `data`, or the generator's `fight` document)
carries every leek's starting stats and the full action list. Walking the
actions reproduces, at every `LEEK_TURN`, exactly the numbers the AI's probe
logs (`TXL|` lines, src/tuning/texel.py): life, max life, shields, buffed
stats, total TP/MP. `validate` proves that on local fights where both are
available; `export` then applies it to the scraped database.

What the log says (generator action/*.java, effect/*.java):
- damage `[101|108|109|110|111, target, pv, erosion]`: life -= pv, max -= erosion;
  `[107, target, pv, erosion]` nova: pv is what max life loses, life untouched.
- `[103, target, pv]` heal; `[104, target, v]` vitality: life += v and max += v;
  `[112, target, v]` nova vitality: max += v only.
- `[301|302, item, logId, caster, target, type, value, turns, ...]` add effect:
  `value` is a magnitude; the sign comes from the type (shackles and
  vulnerabilities subtract). `[14, logId, added]` stacks onto it,
  `[304, logId, newValue]` rewrites it (liberation), `[303, logId]` ends it.
- `[105, owner, target, cell, life, maxLife]` resurrect; `[5, id]` death.

Bulbs are skipped: `[9, ...]` names the summon but not its stats, and the
fit only uses leeks anyway.
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional

from src.common.errors import TagadAIError

STATS = ["HP", "HPMAX", "ABSSHIELD", "RELSHIELD", "DMGRETURN", "STR", "MGC", "SNC", "RST", "WSD", "AGI", "TP", "MP"]

# Effect type -> (stat, sign). Types that change no observed stat are absent.
EFFECT_STAT: dict[int, tuple[str, int]] = {
    3: ("STR", +1), 38: ("STR", +1), 19: ("STR", -1),
    4: ("AGI", +1), 41: ("AGI", +1), 47: ("AGI", -1),
    5: ("RELSHIELD", +1), 54: ("RELSHIELD", +1), 26: ("RELSHIELD", -1),
    6: ("ABSSHIELD", +1), 37: ("ABSSHIELD", +1), 29: ("ABSSHIELD", +1), 27: ("ABSSHIELD", -1),
    7: ("MP", +1), 31: ("MP", +1), 17: ("MP", -1),
    8: ("TP", +1), 32: ("TP", +1), 18: ("TP", -1),
    20: ("DMGRETURN", +1),
    21: ("RST", +1), 42: ("RST", +1),
    22: ("WSD", +1), 44: ("WSD", +1), 48: ("WSD", -1),
    39: ("MGC", +1), 24: ("MGC", -1),
    40: ("SNC", +1),
}
DAMAGE_CODES = {101, 108, 109, 110, 111}
NOVA = 107
# Codes that mean "the acting leek is now doing things": the start-of-turn
# bookkeeping (poison ticks, expiries) is over once one of these shows up.
ACTION_CODES = {10, 12, 13, 16, 100, 102, 203, 205, 8}
# tagadalive casts manumission BEFORE init() when it starts a turn shackled,
# so the probe runs after that cast, its shackle removals and its own +TP
# effect. The snapshot skips all of it. `[12, chip, ...]` carries the CHIP id
# (100), while the effect it adds carries the ITEM template (174).
CHIP_MANUMISSION = 100
ITEM_MANUMISSION = 174


@dataclass
class Leek:
    id: int
    team: int
    alive: bool = True
    stats: dict[str, int] = field(default_factory=dict)


@dataclass
class Snapshot:
    turn: int
    actor: int
    leeks: dict[int, dict[str, int]]     # alive leeks only


class Replay:
    def __init__(self, leeks: list[dict]):
        self.leeks: dict[int, Leek] = {}
        for l in leeks:
            if l.get("summon") or l.get("type", 0) not in (0, 1):
                continue
            base = {
                "HP": l["life"], "HPMAX": l["life"], "ABSSHIELD": 0, "RELSHIELD": 0, "DMGRETURN": 0,
                "STR": l["strength"], "MGC": l["magic"], "SNC": l["science"], "RST": l["resistance"],
                "WSD": l["wisdom"], "AGI": l["agility"], "TP": l["tp"], "MP": l["mp"],
            }
            self.leeks[int(l["id"])] = Leek(int(l["id"]), int(l["team"]), True, base)
        self.effects: dict[int, tuple[int, str, int]] = {}   # logId -> (target, stat, signed value)
        self.turn = 0
        self.unknown: set[int] = set()

    def _bump(self, target: int, stat: str, delta: int) -> None:
        leek = self.leeks.get(target)
        if leek is not None:
            leek.stats[stat] += delta

    def apply(self, a: list) -> None:
        code = a[0]
        if code == 6:
            self.turn = a[1]
        elif code == 5:
            if a[1] in self.leeks:
                self.leeks[a[1]].alive = False
        elif code in DAMAGE_CODES:
            self._bump(a[1], "HP", -a[2])
            if len(a) > 3 and a[3]:
                self._erode(a[1], a[3])
        elif code == NOVA:
            self._erode(a[1], a[2])
        elif code == 103:
            self._bump(a[1], "HP", a[2])
        elif code == 104:
            # Vitality raises max AND current life; nova vitality (112) max only.
            self._bump(a[1], "HPMAX", a[2])
            self._bump(a[1], "HP", a[2])
        elif code == 112:
            self._bump(a[1], "HPMAX", a[2])
        elif code in (301, 302):
            _, _item, log_id, _caster, target, etype, value, _turns = a[:8]
            spec = EFFECT_STAT.get(etype)
            if spec is None:
                if etype not in (1, 2, 9, 10, 11, 12, 13, 14, 15, 16, 23, 25, 28, 30, 33, 34, 35, 36, 43, 45, 46, 49, 50, 51, 52, 53, 55, 56, 57, 58, 59, 60, 61, 63):
                    self.unknown.add(etype)
                return
            stat, sign = spec
            self.effects[log_id] = (target, stat, sign * value)
            self._bump(target, stat, sign * value)
        elif code == 14:
            eff = self.effects.get(a[1])
            if eff:
                target, stat, signed = eff
                sign = 1 if signed >= 0 else -1
                self.effects[a[1]] = (target, stat, signed + sign * a[2])
                self._bump(target, stat, sign * a[2])
        elif code == 304:
            eff = self.effects.get(a[1])
            if eff:
                target, stat, signed = eff
                sign = 1 if signed >= 0 else -1
                new = sign * a[2]
                self.effects[a[1]] = (target, stat, new)
                self._bump(target, stat, new - signed)
        elif code == 303:
            eff = self.effects.pop(a[1], None)
            if eff:
                target, stat, signed = eff
                self._bump(target, stat, -signed)
        elif code == 105:
            _, _owner, target, _cell, life, max_life = a[:6]
            if target in self.leeks:
                l = self.leeks[target]
                l.alive = True
                l.stats["HP"], l.stats["HPMAX"] = life, max_life

    def _erode(self, target: int, erosion: int) -> None:
        leek = self.leeks.get(target)
        if leek is not None:
            leek.stats["HPMAX"] = max(1, leek.stats["HPMAX"] - erosion)

    def snapshot(self, actor: int) -> Snapshot:
        return Snapshot(self.turn, actor, {i: dict(l.stats) for i, l in self.leeks.items() if l.alive})


def replay_states(leeks: list[dict], actions: list[list]) -> Iterator[Snapshot]:
    """One snapshot per leek turn, taken once the start-of-turn bookkeeping is done.

    The AI's probe runs after `init()`, i.e. after poison has ticked and
    expired effects are gone but before the leek acts. So the snapshot is
    taken at the first *action* following `[7, id]`, or at `[8, id]` if the
    leek did nothing.
    """
    r = Replay(leeks)
    pending: Optional[int] = None
    skipping = False       # inside the pre-init manumission and its removals
    for a in actions:
        code = a[0]
        if pending is not None:
            if code == 12 and a[1] == CHIP_MANUMISSION and not skipping:
                skipping = True
            elif skipping and (code in (303, 308, 100) or (code == 302 and a[1] == ITEM_MANUMISSION)):
                pass
            elif code in ACTION_CODES or code == 7:
                if pending in r.leeks and r.leeks[pending].alive:
                    yield r.snapshot(pending)
                pending = None
                skipping = False
        if code == 7:
            pending = a[1]
            skipping = False
        r.apply(a)
    if pending is not None and pending in r.leeks and r.leeks[pending].alive:
        yield r.snapshot(pending)
    if r.unknown:
        print(f"warning: effect types not mapped: {sorted(r.unknown)}", file=sys.stderr)


# --------------------------------------------------------------- validate


def validate_local(seeds: int = 2) -> int:
    """Play probe fights locally and diff replayed states against the TXL lines."""
    from src.localfight.batch import GeneratorPool
    from src.localfight.logs import collect_logs
    from src.localfight.pool import LeekPool
    from src.tools.localfight import build_scenario
    from src.tuning.texel import PROBE_TAG, probe_ai

    ai = probe_ai()
    pool = LeekPool()
    a, b = pool.resolve("Claudius"), pool.resolve("Claudias")
    mismatches = compared = 0
    with GeneratorPool(workers=2) as gen:
        for seed in range(1, seeds + 1):
            ents = [pool.entity(a, 1, ai), pool.entity(b, 2, ai)]
            res = gen.run(json.dumps(build_scenario(ents, seed, 64)))
            fight = res["fight"]
            probe = {}
            for eid, _lvl, text in collect_logs(res):
                if text.startswith(PROBE_TAG):
                    parts = text[len(PROBE_TAG):].split("|")
                    turn = int(parts[0])
                    probe[(turn, eid)] = {int(f.split(":")[0]): [int(x) for x in f.split(":")[3:]]
                                         for f in parts[2:] if f.split(":")[2] == "0"}
            for snap in replay_states(fight["leeks"], fight["actions"]):
                truth = probe.get((snap.turn, snap.actor))
                if truth is None:
                    continue
                for eid, vals in truth.items():
                    got = snap.leeks.get(eid)
                    if got is None:
                        print(f"seed {seed} T{snap.turn} actor {snap.actor}: leek {eid} alive in probe, dead in replay")
                        mismatches += 1
                        continue
                    for name, v in zip(STATS, vals):
                        compared += 1
                        if got[name] != v:
                            mismatches += 1
                            print(f"seed {seed} T{snap.turn} actor {snap.actor} leek {eid} {name}: replay {got[name]} probe {v}")
    print(f"{compared} values compared, {mismatches} mismatches")
    return mismatches


# ----------------------------------------------------------------- export


def fight_rows(fight: dict) -> list[dict]:
    """Texel CSV rows for one website fight document (the `/fight/get` wrapper)."""
    data = fight["data"]
    winner = fight.get("winner", -1)          # website: 0 draw, 1 team1, 2 team2
    if winner not in (0, 1, 2):
        return []
    leeks = [l for l in data["leeks"] if not l.get("summon")]
    team_of = {int(l["id"]): int(l["team"]) for l in leeks}
    # `data.leeks[].id` is renumbered 0,1,...; the real ids live in leeks1/leeks2.
    label = ",".join("+".join(f"{l['name']}#{l['id']}" for l in fight.get(k, [])) for k in ("leeks1", "leeks2"))
    farmer_of = {int(l["id"]): int(l.get("farmer", 0)) for l in leeks}
    rows = []
    for snap in replay_states(leeks, data["actions"]):
        team = team_of[snap.actor]
        win = 0.5 if winner == 0 else (1.0 if winner == team else 0.0)
        for eid, stats in snap.leeks.items():
            rows.append({
                "matchup": label, "seed": fight["id"], "orientation": 0,
                "turn": snap.turn, "logger": snap.actor, "logger_team": team, "win": win,
                "entity": eid, "side": 1 if team_of[eid] == team else -1, "bulb": 0,
                "farmer": farmer_of[snap.actor], "enemy_farmer": next(farmer_of[e] for e in team_of if team_of[e] != team),
                **stats,
            })
    return rows


def export(db_path: Path, out: Path, level: int = 301, limit: Optional[int] = None) -> int:
    db = sqlite3.connect(db_path)
    q = ("select fight_id, json_data from fights where team1_levels=? and team2_levels=? "
         "and json_data is not null order by fight_id")
    if limit:
        q += f" limit {int(limit)}"
    n_rows = n_fights = 0
    fields = ["matchup", "seed", "orientation", "turn", "logger", "logger_team", "win",
              "entity", "side", "bulb", "farmer", "enemy_farmer", *STATS]
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for fid, raw in db.execute(q, (level, level)):
            try:
                fight = json.loads(raw)
                rows = fight_rows(fight)
            except (KeyError, TypeError, ValueError) as e:
                print(f"skip fight {fid}: {e}", file=sys.stderr)
                continue
            for r in rows:
                w.writerow(r)
            n_rows += len(rows)
            n_fights += 1
            if n_fights % 500 == 0:
                print(f"\r  {n_fights} fights, {n_rows} rows", end="", file=sys.stderr)
    print(f"\n{n_fights} fights, {n_rows} rows -> {out}", file=sys.stderr)
    return n_rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate", help="replay local probe fights and diff against the TXL lines")
    v.add_argument("--seeds", type=int, default=2)
    e = sub.add_parser("export", help="replay scraped fights into a Texel CSV")
    e.add_argument("--db", type=Path, default=Path("data/fights.db"))
    e.add_argument("--out", type=Path, default=Path("data/texel_site.csv"))
    e.add_argument("--level", type=int, default=301)
    e.add_argument("--limit", type=int)
    args = ap.parse_args()
    try:
        if args.cmd == "validate":
            return 1 if validate_local(args.seeds) else 0
        export(args.db, args.out, args.level, args.limit)
    except TagadAIError as err:
        print(f"error: {err}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
