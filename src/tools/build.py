#!/usr/bin/env python3
"""
Build Management Tool - Save and restore leek builds (stats + equipment).

Usage:
    python -m src.tools.build save <leek> <name>           # Snapshot current build
    python -m src.tools.build list [leek]                   # List saved builds
    python -m src.tools.build show <leek> <name>            # Display build details
    python -m src.tools.build restore <leek> <name>         # Restore (with confirmation)
    python -m src.tools.build restore <leek> <name> --yes   # Skip confirmation
"""

import sys
import json
import time
import argparse
from datetime import datetime
from pathlib import Path

from src.common import LeekWarsAPI, load_credentials
from src.common.errors import TagadAIError, APIError


BUILDS_DIR = Path("data/builds")
API_DELAY = 0.35  # seconds between API calls to avoid rate limiting

STAT_KEYS = [
    "life", "strength", "wisdom", "agility", "resistance",
    "frequency", "science", "magic", "tp", "mp", "cores", "ram",
]


# =============================================================================
# Helpers
# =============================================================================

def resolve_leek(farmer: dict, name: str) -> tuple[int, dict]:
    """Resolve leek name (case-insensitive) to (id, data) from farmer login data."""
    name_lower = name.lower()
    for leek_id, leek in farmer.get("leeks", {}).items():
        if leek["name"].lower() == name_lower:
            return int(leek_id), leek
    available = [l["name"] for l in farmer.get("leeks", {}).values()]
    raise TagadAIError(f"Leek '{name}' not found. Available: {', '.join(available)}")


def builds_dir_for(leek_name: str) -> Path:
    """Get the builds directory for a leek."""
    return BUILDS_DIR / leek_name


def load_build(leek_name: str, build_name: str) -> dict:
    """Load a saved build from disk."""
    path = builds_dir_for(leek_name) / f"{build_name}.json"
    if not path.exists():
        raise TagadAIError(f"Build '{build_name}' not found for {leek_name}")
    return json.loads(path.read_text())


def save_build_file(leek_name: str, build_name: str, data: dict):
    """Save a build to disk."""
    d = builds_dir_for(leek_name)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{build_name}.json"
    path.write_text(json.dumps(data, indent=2))
    return path


def snapshot_build(api: LeekWarsAPI, leek_id: int, leek_name: str) -> dict:
    """Create a build snapshot from the current leek state."""
    leek = api.get_leek(leek_id)

    stats = {}
    for key in STAT_KEYS:
        stats[key] = leek.get(key, 0)

    weapons = []
    for w in leek.get("weapons", []):
        if w is not None:
            weapons.append({"template": w.get("template"), "instance_id": w.get("id")})

    chips = []
    for c in leek.get("chips", []):
        if c is not None:
            chips.append({"template": c.get("template"), "instance_id": c.get("id")})

    components = []
    for comp in leek.get("components", []):
        if comp is not None:
            components.append({"template": comp.get("template"), "instance_id": comp.get("id")})

    return {
        "version": 1,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "leek_id": leek_id,
        "leek_name": leek_name,
        "level": leek.get("level", 0),
        "capital": leek.get("capital", 0),
        "stats": stats,
        "weapons": weapons,
        "chips": chips,
        "components": components,
    }


def find_restat_potion(farmer: dict) -> int | None:
    """Find a restat potion in farmer inventory. Returns potion instance ID."""
    for potion in farmer.get("potions", []):
        # Template 49 = restat potion (effect type 1)
        if potion.get("template") == 49:
            return potion.get("id")
    return None


def find_inventory_item(items: list, template: int, used_counts: dict) -> int | None:
    """Find an inventory item by template, respecting quantity limits.

    used_counts tracks how many times each item ID has been used so far.
    """
    for item in items:
        if item.get("template") == template:
            item_id = item["id"]
            used = used_counts.get(item_id, 0)
            available = item.get("quantity", 1)
            if used < available:
                used_counts[item_id] = used + 1
                return item_id
    return None


# =============================================================================
# Commands
# =============================================================================

def cmd_save(api: LeekWarsAPI, args):
    """Save current build as a named snapshot."""
    leek_id, _ = resolve_leek(api.farmer, args.leek)
    build = snapshot_build(api, leek_id, args.leek)
    path = save_build_file(args.leek, args.name, build)

    print(f"Saved build '{args.name}' for {args.leek}")
    print(f"  Level: {build['level']}, Capital: {build['capital']}")
    print(f"  Stats: {', '.join(f'{k}={v}' for k, v in build['stats'].items() if v > 0)}")
    print(f"  Weapons: {len(build['weapons'])}, Chips: {len(build['chips'])}, Components: {len(build['components'])}")
    print(f"  File: {path}")


def cmd_list(api: LeekWarsAPI, args):
    """List saved builds."""
    if args.leek:
        # List builds for specific leek
        d = builds_dir_for(args.leek)
        if not d.exists():
            print(f"No saved builds for {args.leek}")
            return
        builds = sorted(d.glob("*.json"))
        if not builds:
            print(f"No saved builds for {args.leek}")
            return
        print(f"Builds for {args.leek}:")
        for p in builds:
            data = json.loads(p.read_text())
            name = p.stem
            saved = data.get("saved_at", "?")
            level = data.get("level", "?")
            print(f"  {name:20} Lv{level}  saved {saved}")
    else:
        # List all leeks with builds
        if not BUILDS_DIR.exists():
            print("No saved builds")
            return
        leek_dirs = sorted(d for d in BUILDS_DIR.iterdir() if d.is_dir())
        if not leek_dirs:
            print("No saved builds")
            return
        for d in leek_dirs:
            builds = sorted(d.glob("*.json"))
            if builds:
                print(f"{d.name}:")
                for p in builds:
                    data = json.loads(p.read_text())
                    name = p.stem
                    saved = data.get("saved_at", "?")
                    level = data.get("level", "?")
                    print(f"  {name:20} Lv{level}  saved {saved}")


def cmd_show(api: LeekWarsAPI, args):
    """Display build details."""
    build = load_build(args.leek, args.name)

    print(f"Build '{args.name}' for {build['leek_name']}")
    print(f"  Saved: {build['saved_at']}")
    print(f"  Level: {build['level']}, Capital: {build['capital']}")
    print()

    print("Stats:")
    for key, val in build["stats"].items():
        if val > 0:
            print(f"  {key:12} {val:>6}")
    print()

    if build["weapons"]:
        print(f"Weapons ({len(build['weapons'])}):")
        for w in build["weapons"]:
            print(f"  template={w['template']}  id={w['instance_id']}")

    if build["chips"]:
        print(f"Chips ({len(build['chips'])}):")
        for c in build["chips"]:
            print(f"  template={c['template']}  id={c['instance_id']}")

    if build.get("components"):
        print(f"Components ({len(build['components'])}):")
        for comp in build["components"]:
            print(f"  template={comp['template']}  id={comp['instance_id']}")


def cmd_restore(api: LeekWarsAPI, args):
    """Restore a saved build."""
    leek_id, leek_data = resolve_leek(api.farmer, args.leek)
    build = load_build(args.leek, args.name)

    # Phase 0: Safety checks
    print("=" * 60)
    print(f"RESTORE BUILD: '{args.name}' -> {args.leek}")
    print("=" * 60)

    # Fetch current state
    current = api.get_leek(leek_id)
    current_level = current.get("level", 0)
    saved_level = build.get("level", 0)

    if current_level != saved_level:
        print(f"  WARNING: Level mismatch! Current={current_level}, Saved={saved_level}")
        if not args.yes:
            resp = input("  Continue anyway? [y/N] ")
            if resp.lower() != "y":
                print("Aborted.")
                return

    # Check restat potion
    potion_id = find_restat_potion(api.farmer)
    if potion_id is None:
        print("ERROR: No restat potion found in inventory!")
        print("Buy one from the market before restoring.")
        sys.exit(1)

    # Show summary — filter null slots left by unequip
    cur_weapons = [w for w in current.get("weapons", []) if w is not None]
    cur_chips = [c for c in current.get("chips", []) if c is not None]
    cur_components = [c for c in current.get("components", []) if c is not None]

    print(f"\nCurrent state:")
    print(f"  Level: {current_level}")
    cur_stats = {k: current.get(k, 0) for k in STAT_KEYS}
    print(f"  Stats: {', '.join(f'{k}={v}' for k, v in cur_stats.items() if v > 0)}")
    print(f"  Weapons: {len(cur_weapons)}, Chips: {len(cur_chips)}, Components: {len(cur_components)}")

    print(f"\nTarget state:")
    print(f"  Level: {saved_level}")
    print(f"  Stats: {', '.join(f'{k}={v}' for k, v in build['stats'].items() if v > 0)}")
    print(f"  Weapons: {len(build['weapons'])}, Chips: {len(build['chips'])}, Components: {len(build.get('components', []))}")

    if not args.yes:
        print(f"\nThis will: strip equipment, use restat potion, reallocate stats, re-equip.")
        resp = input("Proceed? [y/N] ")
        if resp.lower() != "y":
            print("Aborted.")
            return

    # Auto-backup
    backup_name = f"_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    backup = snapshot_build(api, leek_id, args.leek)
    save_build_file(args.leek, backup_name, backup)
    print(f"\nAuto-backup saved as '{backup_name}'")

    # Phase 1: Strip equipment
    print("\nPhase 1: Stripping equipment...")
    errors = []

    for chip in cur_chips:
        chip_id = chip.get("id")
        try:
            api.remove_chip(chip_id)
            print(f"  Removed chip {chip_id}")
        except APIError as e:
            errors.append(f"remove chip {chip_id}: {e}")
            print(f"  WARN: Failed to remove chip {chip_id}: {e}")
        time.sleep(API_DELAY)

    for weapon in cur_weapons:
        weapon_id = weapon.get("id")
        try:
            api.remove_weapon(weapon_id)
            print(f"  Removed weapon {weapon_id}")
        except APIError as e:
            errors.append(f"remove weapon {weapon_id}: {e}")
            print(f"  WARN: Failed to remove weapon {weapon_id}: {e}")
        time.sleep(API_DELAY)

    for comp in cur_components:
        comp_id = comp.get("id")
        try:
            api.remove_component(comp_id)
            print(f"  Removed component {comp_id}")
        except APIError as e:
            errors.append(f"remove component {comp_id}: {e}")
            print(f"  WARN: Failed to remove component {comp_id}: {e}")
        time.sleep(API_DELAY)

    # Phase 2: Restat
    print("\nPhase 2: Using restat potion...")
    time.sleep(API_DELAY)
    try:
        api.use_potion(leek_id, potion_id)
        print(f"  Restat potion used (id={potion_id})")
    except APIError as e:
        print(f"  ERROR: Failed to use restat potion: {e}")
        print("  Aborting. Equipment has been stripped but stats unchanged.")
        print(f"  Use backup '{backup_name}' to restore equipment.")
        sys.exit(1)

    # Phase 3: Re-allocate stats
    print("\nPhase 3: Allocating stats...")
    time.sleep(API_DELAY)

    # Fetch base stats after restat to compute bonus amounts
    base = api.get_leek(leek_id)
    time.sleep(API_DELAY)
    stats_to_spend = {}
    for k in STAT_KEYS:
        target = build["stats"].get(k, 0)
        base_val = base.get(k, 0)
        bonus = target - base_val
        if bonus > 0:
            stats_to_spend[k] = bonus
    try:
        api.spend_capital(leek_id, stats_to_spend)
        print(f"  Allocated: {stats_to_spend}")
    except APIError as e:
        print(f"  ERROR: Failed to allocate stats: {e}")
        print(f"  Stats are reset. Use backup '{backup_name}' or manually fix.")
        sys.exit(1)

    # Phase 4: Re-equip (components first — they add chip/weapon slots)
    print("\nPhase 4: Re-equipping...")

    # Re-login to get fresh farmer data with updated inventory
    time.sleep(API_DELAY)
    login, password = load_credentials()
    api.login(login, password)
    farmer_fresh = api.farmer

    # Collect all available items from farmer inventory
    all_weapons = list(farmer_fresh.get("weapons", []))
    all_chips = list(farmer_fresh.get("chips", []))
    all_components = list(farmer_fresh.get("components", []))

    used_weapon_counts: dict[int, int] = {}
    used_chip_counts: dict[int, int] = {}
    used_comp_counts: dict[int, int] = {}

    # Components first — they add chip/weapon slots
    for idx, comp in enumerate(build.get("components", [])):
        item_id = find_inventory_item(all_components, comp["template"], used_comp_counts)
        if item_id is None:
            errors.append(f"component template {comp['template']} not found in inventory")
            print(f"  WARN: Component template {comp['template']} not in inventory")
            continue
        try:
            api.add_component(leek_id, item_id, index=idx)
            print(f"  Equipped component {item_id} (template={comp['template']}, slot={idx})")
        except APIError as e:
            errors.append(f"add component {item_id}: {e}")
            print(f"  WARN: Failed to equip component {item_id}: {e}")
        time.sleep(API_DELAY)

    for w in build.get("weapons", []):
        item_id = find_inventory_item(all_weapons, w["template"], used_weapon_counts)
        if item_id is None:
            errors.append(f"weapon template {w['template']} not found in inventory")
            print(f"  WARN: Weapon template {w['template']} not in inventory")
            continue
        try:
            api.add_weapon(leek_id, item_id)
            print(f"  Equipped weapon {item_id} (template={w['template']})")
        except APIError as e:
            errors.append(f"add weapon {item_id}: {e}")
            print(f"  WARN: Failed to equip weapon {item_id}: {e}")
        time.sleep(API_DELAY)

    for c in build.get("chips", []):
        item_id = find_inventory_item(all_chips, c["template"], used_chip_counts)
        if item_id is None:
            errors.append(f"chip template {c['template']} not found in inventory")
            print(f"  WARN: Chip template {c['template']} not in inventory")
            continue
        try:
            api.add_chip(leek_id, item_id)
            print(f"  Equipped chip {item_id} (template={c['template']})")
        except APIError as e:
            errors.append(f"add chip {item_id}: {e}")
            print(f"  WARN: Failed to equip chip {item_id}: {e}")
        time.sleep(API_DELAY)

    # Phase 5: Verify
    print("\nPhase 5: Verifying...")
    time.sleep(API_DELAY)
    final = api.get_leek(leek_id)

    discrepancies = []
    for key in STAT_KEYS:
        expected = build["stats"].get(key, 0)
        actual = final.get(key, 0)
        if expected != actual:
            discrepancies.append(f"  {key}: expected={expected}, actual={actual}")

    expected_weapons = len(build.get("weapons", []))
    actual_weapons = len([w for w in final.get("weapons", []) if w is not None])
    if expected_weapons != actual_weapons:
        discrepancies.append(f"  weapons: expected={expected_weapons}, actual={actual_weapons}")

    expected_chips = len(build.get("chips", []))
    actual_chips = len([c for c in final.get("chips", []) if c is not None])
    if expected_chips != actual_chips:
        discrepancies.append(f"  chips: expected={expected_chips}, actual={actual_chips}")

    expected_comps = len(build.get("components", []))
    actual_comps = len([c for c in final.get("components", []) if c is not None])
    if expected_comps != actual_comps:
        discrepancies.append(f"  components: expected={expected_comps}, actual={actual_comps}")

    print()
    if discrepancies:
        print("DISCREPANCIES FOUND:")
        for d in discrepancies:
            print(d)
    else:
        print("All checks passed!")

    if errors:
        print(f"\n{len(errors)} warning(s) during restore:")
        for e in errors:
            print(f"  - {e}")

    print(f"\nBackup available as '{backup_name}' if needed.")
    print("Done.")


# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Manage leek builds (stats + equipment)")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # save
    p_save = subparsers.add_parser("save", help="Save current build")
    p_save.add_argument("leek", help="Leek name")
    p_save.add_argument("name", help="Build name")

    # list
    p_list = subparsers.add_parser("list", help="List saved builds")
    p_list.add_argument("leek", nargs="?", help="Leek name (optional)")

    # show
    p_show = subparsers.add_parser("show", help="Show build details")
    p_show.add_argument("leek", help="Leek name")
    p_show.add_argument("name", help="Build name")

    # restore
    p_restore = subparsers.add_parser("restore", help="Restore a saved build")
    p_restore.add_argument("leek", help="Leek name")
    p_restore.add_argument("name", help="Build name")
    p_restore.add_argument("--yes", "-y", action="store_true", help="Skip confirmation")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    try:
        login, password = load_credentials()
        api = LeekWarsAPI()
        api.login(login, password)

        if args.command == "save":
            cmd_save(api, args)
        elif args.command == "list":
            cmd_list(api, args)
        elif args.command == "show":
            cmd_show(api, args)
        elif args.command == "restore":
            cmd_restore(api, args)

    except TagadAIError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
