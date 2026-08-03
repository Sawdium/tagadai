#!/usr/bin/env python3
"""
Loadout Tool - Manage native LeekWars loadouts (équipements / build presets).

Loadouts are the game's built-in build feature and our single source of truth
for builds (no more local JSON snapshots): a saved set of weapons + chips +
components + stat allocation that can be applied to any leek in one call,
optionally restatting. This is the native replacement for the old manual
strip / restat-potion / re-equip workflow.

Usage:
    python -m src.tools.loadout list [--account <login>]
    python -m src.tools.loadout save [leek] [--name <name>] [--account <login>]
    python -m src.tools.loadout apply <leek> <loadout> [--restat] [--account <login>]

`save` snapshots a leek's LIVE build into a loadout named after it (omit the leek
to save every leek). It upserts by name — it never deletes other loadouts, so
hand-tuned loadouts on the website (e.g. the PotiMalef boss build) are safe.

`apply` equips a loadout onto a leek; with --restat it also reallocates capital.

Stat fidelity: loadout stats are CAPITAL points per characteristic, not the
characteristic value the leek API reports. We convert value -> capital with the
LeekWars COSTS table below (validated: every level-301 leek totals 2113 capital).

Caveats:
    - non-storable weapons (illicit 115-119, reward 175/225/506) can't sit in the
      active set; the server routes them to the loadout's forgotten_weapons slot
    - components are {index, template} objects; apply() reinstalls them, so they
      are always included (omitting them would strip the leek's cores/ram)
"""

import sys
import time
import argparse

from src.common import LeekWarsAPI, load_credentials
from src.common.errors import TagadAIError, APIError

API_DELAY = 0.35

# LeekWars characteristic cost table (src/model/leek.ts COSTS), as
# (bought_points_threshold, capital, value_per_capital). Within a tier, each
# `capital` buys `sup` characteristic points, i.e. cost = points * capital / sup.
COSTS = {
    "life":       [(0, 1, 4), (1000, 1, 3), (2000, 1, 2)],
    "strength":   [(0, 1, 2), (200, 1, 1), (400, 2, 1), (600, 3, 1)],
    "wisdom":     [(0, 1, 2), (200, 1, 1), (400, 2, 1), (600, 3, 1)],
    "agility":    [(0, 1, 2), (200, 1, 1), (400, 2, 1), (600, 3, 1)],
    "resistance": [(0, 1, 2), (200, 1, 1), (400, 2, 1), (600, 3, 1)],
    "science":    [(0, 1, 2), (200, 1, 1), (400, 2, 1), (600, 3, 1)],
    "magic":      [(0, 1, 2), (200, 1, 1), (400, 2, 1), (600, 3, 1)],
    "frequency":  [(0, 1, 1)],
    "cores":      [(i, 20 + 10 * i, 1) for i in range(9)],
    "ram":        [(i, 20 + 10 * i, 1) for i in range(9)],
    "tp":         [(i, 30 + 5 * i, 1) for i in range(15)],
    "mp":         [(i, 20 + 20 * i, 1) for i in range(9)],
}

# Innate (free) characteristic floor a fresh leek has before spending capital.
# Capital only pays for points bought above this baseline.
BASELINE = {
    "life": 1000, "strength": 0, "wisdom": 0, "agility": 0, "resistance": 0,
    "science": 0, "magic": 0, "frequency": 100, "tp": 10, "mp": 3,
    "cores": 1, "ram": 6,
}

# Weapons that can never be stored in a loadout (server moves them to
# forgotten_weapons): the illicit black-market weapons (115-119) plus special
# reward/event weapons (175 explorer rifle, 225 enhanced lightninger). This is
# only a cosmetic pre-filter for the plan output — the create/update response's
# forgotten_weapons is the authoritative list and is always reported.
NON_STORABLE_WEAPONS = {115, 116, 117, 118, 119, 175, 225, 506}


def value_to_capital(stat: str, value: int) -> int:
    """Convert a characteristic value (as the leek API reports it) to the
    capital points a loadout stores. Floored so we never over-allocate past the
    leek's capital budget; the <1pt rounding loss is benign on apply.
    """
    bought = value - BASELINE.get(stat, 0)
    if bought <= 0:
        return 0
    tiers = COSTS[stat]
    cap = 0.0
    for i, (step, capital, sup) in enumerate(tiers):
        lo = step
        hi = tiers[i + 1][0] if i + 1 < len(tiers) else bought
        hi = min(hi, bought)
        if hi > lo:
            cap += (hi - lo) * capital / sup
    return int(cap)


def build_to_loadout_stats(build_stats: dict) -> dict:
    """Map a saved build's characteristic values to a loadout's capital map,
    dropping characteristics that cost nothing (at or below baseline)."""
    out = {}
    for stat in COSTS:
        cap = value_to_capital(stat, build_stats.get(stat, 0))
        if cap > 0:
            out[stat] = cap
    return out


def build_from_leek(leek: dict) -> dict:
    """Read a leek's LIVE equipment+stats off the website into the same shape as
    a saved build dict. Null slots (left by an unequip) are filtered out."""
    return {
        "weapons": [{"template": w["template"]} for w in leek.get("weapons", []) if w],
        "chips": [{"template": c["template"]} for c in leek.get("chips", []) if c],
        "components": [{"template": c["template"]} for c in leek.get("components", []) if c],
        "stats": {k: leek.get(k, 0) for k in COSTS},
    }


def loadout_from_build(build: dict) -> dict:
    """Turn a saved build dict into loadout parts (weapons, chips, components,
    stats). Components are {index, template} objects keyed by slot — the server
    requires this shape and apply() re-installs them on the leek, so they must
    be present or the leek loses its cores/ram/stat hardware.

    All weapons are sent in `weapons`; the server auto-sorts non-storable ones
    (illicit / reward weapons) into the loadout's forgotten_weapons slot — so we
    keep them rather than dropping them. `active`/`forgotten` are split here only
    for display; `weapons` is the combined list to send (active first, like the
    game UI does with [...weapons, ...forgotten])."""
    active, forgotten = [], []
    for w in build.get("weapons", []):
        t = w["template"]
        (forgotten if t in NON_STORABLE_WEAPONS else active).append(t)
    chips = [c["template"] for c in build.get("chips", [])]
    components = [{"index": i, "template": c["template"]}
                 for i, c in enumerate(build.get("components", []))]
    stats = build_to_loadout_stats(build.get("stats", {}))
    return {"weapons": active + forgotten, "active": active,
            "forgotten": forgotten, "chips": chips,
            "components": components, "stats": stats}


def leeks_for_account(farmer: dict) -> list[tuple[int, str]]:
    return [(int(lid), l["name"]) for lid, l in farmer.get("leeks", {}).items()]


# =============================================================================
# Commands
# =============================================================================

def cmd_list(api: LeekWarsAPI, args):
    data = api.get_loadouts()
    los = data.get("loadouts", [])
    print(f"{len(los)} loadout(s) for {api.farmer['login']}:")
    for lo in los:
        st = ", ".join(f"{k}={v}" for k, v in lo["stats"].items())
        forgotten = f" forgotten={lo['forgotten_weapons']}" if lo.get("forgotten_weapons") else ""
        print(f"  #{lo['id']:<5} {lo['name']:<18} weapons={lo['weapons']} "
              f"chips={len(lo['chips'])}{forgotten}")
        if st:
            print(f"         stats(capital): {st}")


def cmd_save(api: LeekWarsAPI, args):
    """Snapshot a leek's live build into a loadout named after it (upsert by
    name). With no leek argument, saves every leek on the account. Never deletes
    other loadouts."""
    leeks = leeks_for_account(api.farmer)
    if args.leek:
        leeks = [(lid, n) for lid, n in leeks if n.lower() == args.leek.lower()]
        if not leeks:
            raise TagadAIError(f"Leek '{args.leek}' not found. Have: "
                               f"{', '.join(n for _, n in leeks_for_account(api.farmer))}")
    if args.name and len(leeks) > 1:
        raise TagadAIError("--name can only be used when saving a single leek")

    existing = {lo["name"].lower(): lo
                for lo in api.get_loadouts().get("loadouts", [])}

    print(f"Saving {len(leeks)} live build(s) to loadouts for {api.farmer['login']}:")
    for leek_id, leek_name in leeks:
        name = args.name or leek_name
        lo = loadout_from_build(build_from_leek(api.get_leek(leek_id)))
        icon = lo["active"][0] if lo["active"] else 37
        prev = existing.get(name.lower())
        try:
            if prev:
                res = api.update_loadout(prev["id"], name, icon, lo["weapons"],
                                         lo["chips"], lo["components"], lo["stats"])
                verb = "updated"
            else:
                res = api.create_loadout(name, icon, lo["weapons"], lo["chips"],
                                         lo["components"], lo["stats"])
                verb = "created"
            s = res.get("set", {})
            note = ""
            if s.get("forgotten_weapons"):
                note += f"  forgotten={s['forgotten_weapons']}"
            if len(s.get("chips", [])) != len(lo["chips"]):
                note += f"  CHIPS {len(lo['chips'])}->{len(s.get('chips', []))} (some not owned?)"
            if len(s.get("components", [])) != len(lo["components"]):
                note += f"  COMPONENTS {len(lo['components'])}->{len(s.get('components', []))} (some not owned?)"
            print(f"  {verb} #{s.get('id')} {name}  weapons={lo['active']} "
                  f"chips={len(lo['chips'])} components={len(lo['components'])}{note}")
        except APIError as exc:
            print(f"  WARN: failed to save {name}: {exc}")
        time.sleep(API_DELAY)


def cmd_apply(api: LeekWarsAPI, args):
    leeks = {name.lower(): lid for lid, name in leeks_for_account(api.farmer)}
    if args.leek.lower() not in leeks:
        raise TagadAIError(f"Leek '{args.leek}' not found. "
                           f"Have: {', '.join(leeks)}")
    leek_id = leeks[args.leek.lower()]
    los = {lo["name"].lower(): lo for lo in api.get_loadouts().get("loadouts", [])}
    if args.loadout.lower() not in los:
        raise TagadAIError(f"Loadout '{args.loadout}' not found. "
                           f"Have: {', '.join(lo['name'] for lo in los.values())}")
    lo = los[args.loadout.lower()]
    print(f"Applying loadout '{lo['name']}' -> {args.leek} "
          f"(restat={'yes' if args.restat else 'no'})")
    api.apply_loadout(lo["id"], leek_id, use_restat=args.restat)
    print("Applied.")


# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Manage native LeekWars loadouts")
    parser.add_argument("--account", help="Override LEEKWARS_LOGIN (password from .env)")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("list", help="List loadouts")

    p_save = sub.add_parser("save", help="Snapshot leek(s) live build into a "
                                         "loadout named after the leek (upsert)")
    p_save.add_argument("leek", nargs="?", help="Leek name (omit to save all leeks)")
    p_save.add_argument("--name", help="Loadout name (default: leek name; "
                                       "single leek only)")

    p_apply = sub.add_parser("apply", help="Apply a loadout to a leek")
    p_apply.add_argument("leek")
    p_apply.add_argument("loadout")
    p_apply.add_argument("--restat", action="store_true",
                         help="Also reallocate stats (consumes a restat potion)")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    try:
        login, password = load_credentials()
        if args.account:
            login = args.account
        api = LeekWarsAPI()
        api.login(login, password)

        {"list": cmd_list, "save": cmd_save, "apply": cmd_apply}[args.command](api, args)
    except TagadAIError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    except APIError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
