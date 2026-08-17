"""Run boss fights in a loop until an account has looted N of an item.

Wraps src.tools.boss (subprocess) and polls the loot account's farmer
resources between fights. The item is given by template id or by name
(resolved against /item/get-all). Stops when the target number of NEW
items (since start) has been looted, or when --max-fights is reached.

Examples:
    python -m src.tools.bossfarm --boss 3 --main tagadanar --with tagadagain \
        --loot-account tagadagain --item lantern --target 20
    python -m src.tools.bossfarm --boss 3 --main tagadanar --with tagadagain \
        --loot-account tagadagain --item 388 --target 20
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time

from src.common.api import LeekWarsAPI
from src.common.credentials import load_credentials


def resolve_item(spec: str) -> tuple[int, str]:
    """Resolve an item spec (template id or name) to (template_id, name).

    Name matching is case-insensitive; exact match wins, otherwise a unique
    substring match is accepted. Ambiguous or unknown names raise SystemExit
    with the candidate list.
    """
    api = LeekWarsAPI()
    raw = api.session.get(f"{api.BASE_URL}/item/get-all").json()
    items = raw.get("items", raw)
    if spec.isdigit():
        template = int(spec)
        entry = items.get(str(template)) or items.get(template)
        if entry is None:
            raise SystemExit(f"Unknown item template id: {template}")
        return template, str(entry.get("name", "?"))
    needle = spec.lower()
    exact = [(int(k), v["name"]) for k, v in items.items()
             if isinstance(v, dict) and str(v.get("name", "")).lower() == needle]
    if len(exact) == 1:
        return exact[0]
    partial = [(int(k), v["name"]) for k, v in items.items()
               if isinstance(v, dict) and needle in str(v.get("name", "")).lower()]
    if len(partial) == 1:
        return partial[0]
    if not partial:
        raise SystemExit(f"No item matches '{spec}'")
    matches = ", ".join(f"{name} (#{tid})" for tid, name in sorted(partial))
    raise SystemExit(f"Ambiguous item '{spec}': {matches}")


def get_resource_count(login: str, password: str, template: int) -> int:
    """Fresh login and return the quantity of a resource template (0 if absent)."""
    api = LeekWarsAPI()
    farmer = api.login(login, password)
    for res in farmer.get("resources", []):
        if res.get("template") == template:
            return int(res.get("quantity", 0))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--boss", type=int, default=3, choices=[1, 2, 3])
    parser.add_argument("--main", required=True,
                        help="Main account login (squad creator, via LEEKWARS_LOGIN)")
    parser.add_argument("--with", dest="with_accounts", default=None,
                        help="Extra account logins for boss.py --with")
    parser.add_argument("--loot-account", required=True,
                        help="Account whose resources are polled")
    parser.add_argument("--item", required=True,
                        help="Item to count: template id or name (e.g. 'lantern' or 388)")
    parser.add_argument("--target", type=int, required=True,
                        help="Stop after this many NEW resources looted since start")
    parser.add_argument("--max-fights", type=int, default=300,
                        help="Safety cap on fights (default: 300)")
    parser.add_argument("--pause", type=int, default=5,
                        help="Seconds between fights (default: 5)")
    args = parser.parse_args()

    _, password = load_credentials()
    template, item_name = resolve_item(args.item)
    baseline = get_resource_count(args.loot_account, password, template)
    print(f"Item: {item_name} (#{template})")
    print(f"Baseline: {args.loot_account} has {baseline}")
    print(f"Target: +{args.target} (stop at {baseline + args.target})")

    boss_cmd = [sys.executable, "-m", "src.tools.boss",
                "--boss", str(args.boss), "--wait"]
    if args.with_accounts:
        boss_cmd += ["--with", args.with_accounts]
    env = dict(os.environ, LEEKWARS_LOGIN=args.main)

    fights = 0
    looted = 0
    while looted < args.target:
        if fights >= args.max_fights:
            print(f"STOP: reached --max-fights={args.max_fights} with {looted}/{args.target} looted")
            return 1
        fights += 1
        print(f"--- Fight {fights} (looted {looted}/{args.target}) ---", flush=True)
        proc = subprocess.run(boss_cmd, env=env, capture_output=True, text=True)
        for line in proc.stdout.splitlines():
            if any(key in line for key in ("Fight #", "FIGHT #", "WARNING", "Attempt")):
                print(f"  {line.strip()}", flush=True)
        if proc.returncode != 0:
            print(f"  boss.py exit {proc.returncode}, retrying in 30s", flush=True)
            time.sleep(30)
            continue
        try:
            count = get_resource_count(args.loot_account, password, template)
        except Exception as e:  # transient API failure: keep farming
            print(f"  resource poll failed ({e}), retrying next loop", flush=True)
            time.sleep(15)
            continue
        gained = count - baseline
        if gained > looted:
            print(f"  LOOT +{gained - looted} -> {gained}/{args.target}", flush=True)
        looted = max(looted, gained)
        time.sleep(args.pause)

    print(f"DONE: {looted}/{args.target} {item_name} looted in {fights} fights "
          f"({args.loot_account} now has {baseline + looted})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
