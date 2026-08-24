"""
Roster: real leeks, as complete packages, for a diverse Texel corpus.

The first corpus had five builds and the fit learned *who* was fighting
(ml/TODO.md §2.0b). Diversity has to come from many real leeks, not from
perturbing one: a leek is a package -- capital stats, components, chips,
weapons -- and the generator only sees the package's final numbers
(`total_*` from `/leek/get`), so that is what `build_entity` snapshots.

Sources, all level ~301 and all reachable with the accounts in `.env`:
- our own leeks on the five accounts;
- their garden opponents (`/garden/get-leek-opponents`, ~5 per leek);
- the ladder top ten (`/ranking/get-home-ranking`).

Only `cores` and `ram` are overridden, to the largest our own leeks carry:
they are the AI's op and memory budget, not part of the build, and ladder
leeks run one core under hyper-specialised AIs. The live values are kept
under `live_cores` / `live_ram` for the record.

    python -m src.tuning.roster gather --out data/roster.json
    python -m src.tuning.roster show data/roster.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from datetime import date
from pathlib import Path

import requests

from src.common.errors import TagadAIError
from src.localfight.pool import LeekPool
from src.tools.localfight import build_entity

ACCOUNTS = ["", "tagadanar", "tagadagain", "tagadalone", "tagadalton"]
STAT_KEYS = ["level", "life", "strength", "agility", "resistance", "science", "magic", "wisdom", "frequency", "tp", "mp"]


def _retry(fn, attempts: int = 6):
    last: Exception | None = None
    for i in range(attempts):
        try:
            out = fn()
            time.sleep(0.35)          # the API allows ~5 calls/s; stay well under
            return out
        except TagadAIError as e:
            last = e
            if "rate_limit" not in str(e):
                raise
            time.sleep(1.5 * (i + 1))
    raise TagadAIError(f"gave up after {attempts} attempts: {last}")


def _signature(e: dict) -> tuple:
    return tuple(e[k] for k in STAT_KEYS) + (tuple(sorted(e["weapons"])), tuple(sorted(e["chips"])))


def gather(accounts: list[str] = ACCOUNTS, ladder: bool = True, garden: bool = True,
           min_level: int = 290) -> dict:
    pool = LeekPool()
    api = pool.api("")
    sources: dict[int, str] = {}
    own: list[dict] = []
    for acct in accounts:
        for leek in pool.leeks(acct):
            sources.setdefault(int(leek["id"]), "own")
            own.append(leek)
    print(f"own leeks: {len(own)}", file=sys.stderr)
    if garden:
        for leek in own:
            opps = _retry(lambda: pool.api(next(a for a in accounts if leek in pool.leeks(a))).get_leek_opponents(int(leek["id"])))
            for o in opps:
                sources.setdefault(int(o["id"]), "garden")
        print(f"+ garden opponents: {sum(1 for s in sources.values() if s == 'garden')}", file=sys.stderr)
    if ladder:
        r = requests.get(f"{api.BASE_URL}/ranking/get-home-ranking",
                         headers={"Authorization": f"Bearer {api.token}"}, timeout=20)
        for l in r.json().get("leeks", []):
            sources.setdefault(int(l["id"]), "ladder")
        print(f"+ ladder top: {sum(1 for s in sources.values() if s == 'ladder')}", file=sys.stderr)

    builds: list[dict] = []
    seen: set[tuple] = set()
    for i, (lid, source) in enumerate(sorted(sources.items())):
        try:
            e = _retry(lambda: build_entity(api, lid, 1, ""))
        except TagadAIError as err:
            print(f"  skip {lid}: {err}", file=sys.stderr)
            continue
        print(f"\r  {i + 1}/{len(sources)} {e['name']:24s}", end="", file=sys.stderr)
        if e["level"] < min_level:
            continue
        sig = _signature(e)
        if sig in seen:
            continue
        seen.add(sig)
        e = {k: v for k, v in e.items() if k not in ("ai", "team", "farmer")}
        e["source"] = source
        e["live_cores"], e["live_ram"] = e.pop("cores"), e.pop("ram")
        builds.append(e)
    print(file=sys.stderr)

    cores = max(b["live_cores"] for b in builds if b["source"] == "own")
    ram = max(b["live_ram"] for b in builds if b["source"] == "own")
    return {"date": date.today().isoformat(), "cores": cores, "ram": ram, "min_level": min_level, "leeks": builds}


def load(path: Path) -> dict:
    return json.loads(Path(path).read_text())


def entity(roster: dict, build: dict, team: int, ai: str) -> dict:
    """A roster build as a scenario entity, on the roster's shared op budget."""
    e = {k: v for k, v in build.items() if k not in ("source", "live_cores", "live_ram")}
    e.update({"ai": ai, "team": team, "farmer": team, "cores": roster["cores"], "ram": roster["ram"]})
    return e


def show(roster: dict) -> None:
    leeks = roster["leeks"]
    print(f"{len(leeks)} builds, level >= {roster['min_level']}, cores {roster['cores']} ram {roster['ram']} ({roster['date']})")
    print("sources:", dict(Counter(b["source"] for b in leeks)))
    print("live cores:", dict(sorted(Counter(b["live_cores"] for b in leeks).items())))

    def arche(b):
        s = {k: b[k] for k in ("strength", "magic", "science", "agility", "resistance", "wisdom")}
        top = max(s, key=s.get)
        return top if s[top] >= 1.5 * sorted(s.values())[-2] else "hybrid"
    print("archetypes (dominant stat):", dict(Counter(arche(b) for b in leeks).most_common()))
    for k in ("life", "strength", "magic", "science", "agility", "resistance", "wisdom", "tp", "mp"):
        vals = sorted(b[k] for b in leeks)
        print(f"  {k:10s} min {vals[0]:5d}  median {vals[len(vals)//2]:5d}  max {vals[-1]:5d}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gather")
    g.add_argument("--out", type=Path, default=Path("data/roster.json"))
    g.add_argument("--no-ladder", action="store_true")
    g.add_argument("--no-garden", action="store_true")
    g.add_argument("--min-level", type=int, default=290)
    s = sub.add_parser("show")
    s.add_argument("path", type=Path)
    args = ap.parse_args()
    try:
        if args.cmd == "gather":
            roster = gather(ladder=not args.no_ladder, garden=not args.no_garden, min_level=args.min_level)
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(roster, indent=1))
            print(f"-> {args.out}", file=sys.stderr)
            show(roster)
        else:
            show(load(args.path))
    except TagadAIError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
