#!/usr/bin/env python3
"""
Fight Tool - Run fights and analyze results.

Default: Test fight vs Domingo (FREE, no fight cost) - use this for testing AI code!

Usage:
    python -m src.tools.fight                    # Test fight vs Domingo (default, FREE)
    python -m src.tools.fight --real             # Real solo fight (COSTS 1 fight)
    python -m src.tools.fight --real --farmer    # Real farmer fight (COSTS 1 fight)
    python -m src.tools.fight --json             # Output raw JSON
    python -m src.tools.fight --strategy worst   # Pick weakest opponent for real fights
    python -m src.tools.fight --list             # List saved fight logs
    python -m src.tools.fight --review <id>      # Review a saved fight by ID
    python -m src.tools.fight --no-save          # Don't save fight to log
"""

import sys
import json
import time
import argparse
from datetime import datetime
from pathlib import Path

from src.common import LeekWarsAPI, load_credentials, get_project_root
from src.common.errors import TagadAIError
from src.common.fight_parser import FightSummary, parse_fight, format_summary

# Log directory for fight results
FIGHT_LOG_DIR = get_project_root() / "data" / "fights"


def select_opponent(opponents: list, strategy: str) -> dict:
    """Select opponent based on strategy."""
    if not opponents:
        raise Exception("No opponents available in garden")

    if strategy == "random":
        import random
        return random.choice(opponents)
    elif strategy == "best":
        return max(opponents, key=lambda x: x.get("talent", 0))
    else:  # worst (default)
        return min(opponents, key=lambda x: x.get("talent", 0))


def wait_for_fight(api: LeekWarsAPI, fight_id: int, timeout: int = 120, is_test: bool = False) -> dict:
    """Poll until fight is complete."""
    start = time.time()
    while time.time() - start < timeout:
        # Try with logs first, fall back without if error
        result = api.get_fight(fight_id, with_logs=True)

        # If we got an error with logs, retry without
        if "error" in result:
            result = api.get_fight(fight_id, with_logs=False)

        # Check for winner - can be 0 (draw), 1, or 2 (but not None/-1)
        winner = result.get("winner")
        if winner is not None and winner != -1:
            return result
        # Also check status field (status=2 means finished)
        if result.get("status") == 2:
            return result
        time.sleep(2)
    raise Exception(f"Fight {fight_id} timed out after {timeout}s")


def fetch_fight_logs(api: LeekWarsAPI, fight_id: int) -> dict:
    """Fetch debug logs from the separate logs endpoint."""
    try:
        logs = api.get_fight_logs(fight_id)
        if "error" in logs:
            return {}
        return logs
    except Exception:
        return {}


def save_fight_log(fight_id: int, result: dict, summary: FightSummary, is_test: bool = False):
    """Save fight result to log directory."""
    FIGHT_LOG_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    fight_type = "test" if is_test else "real"
    filename = f"{timestamp}_{fight_id}_{fight_type}.json"

    log_data = {
        "fight_id": fight_id,
        "timestamp": timestamp,
        "type": fight_type,
        "result": result,
        "api_logs": summary.api_logs,
        "summary": {
            "fight_id": summary.fight_id,
            "winner": summary.winner,
            "we_won": summary.we_won,
            "total_turns": summary.total_turns,
            "our_damage_dealt": summary.our_damage_dealt,
            "our_damage_received": summary.our_damage_received,
            "our_healing_done": summary.our_healing_done,
            "errors": summary.errors,
            "messages": summary.messages,
            "debug_output": summary.debug_output,
        }
    }

    log_path = FIGHT_LOG_DIR / filename
    with open(log_path, "w") as f:
        json.dump(log_data, f, indent=2)

    print(f"Saved to: {log_path}", file=sys.stderr)
    return log_path


def list_fight_logs():
    """List all saved fight logs."""
    if not FIGHT_LOG_DIR.exists():
        print("No fight logs found.")
        return

    logs = sorted(FIGHT_LOG_DIR.glob("*.json"), reverse=True)
    if not logs:
        print("No fight logs found.")
        return

    print(f"{'ID':>12}  {'Type':>6}  {'Result':>6}  {'Dmg':>6}  {'Rcv':>6}  {'Turns':>5}  Date")
    print("-" * 70)

    for log_path in logs[:20]:  # Show last 20
        try:
            with open(log_path) as f:
                data = json.load(f)

            fight_id = data.get("fight_id", "?")
            fight_type = data.get("type", "?")
            summary = data.get("summary", {})

            result = "WIN" if summary.get("we_won") else ("DRAW" if summary.get("winner") == 0 else "LOSS")
            dmg = summary.get("our_damage_dealt", 0)
            rcv = summary.get("our_damage_received", 0)
            turns = summary.get("total_turns", 0)
            timestamp = data.get("timestamp", "?")

            print(f"{fight_id:>12}  {fight_type:>6}  {result:>6}  {dmg:>6}  {rcv:>6}  {turns:>5}  {timestamp}")
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            print(f"  (error reading {log_path.name}: {e})")

    if len(logs) > 20:
        print(f"  ... and {len(logs) - 20} more")


def review_fight(fight_id: int, show_json: bool = False):
    """Review a saved fight by ID."""
    if not FIGHT_LOG_DIR.exists():
        print("No fight logs found.", file=sys.stderr)
        sys.exit(1)

    # Find log file with matching fight ID
    for log_path in FIGHT_LOG_DIR.glob("*.json"):
        if f"_{fight_id}_" in log_path.name:
            with open(log_path) as f:
                data = json.load(f)

            if show_json:
                print(json.dumps(data.get("result", {}), indent=2))
            else:
                # Re-parse and format (need farmer_id, but we can use 0 for display)
                result = data.get("result", {})
                api_logs = data.get("api_logs", {})
                # Try to get farmer_id from the data
                farmer_id = 0
                for leek in result.get("leeks1", []):
                    if leek.get("farmer"):
                        farmer_id = leek["farmer"]
                        break

                summary = parse_fight(result, farmer_id, api_logs=api_logs)
                print(format_summary(summary))
            return

    print(f"Fight #{fight_id} not found in logs.", file=sys.stderr)
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Run a test fight and display results")
    parser.add_argument("--real", action="store_true", help="Run a real fight (uses fight count)")
    parser.add_argument("--leek", type=int, help="Leek ID to fight with (default: first leek)")
    parser.add_argument("--ai", type=int, help="AI ID to test (default: leek's assigned AI)")
    parser.add_argument("--farmer", action="store_true", help="Run farmer fight (only with --real)")
    parser.add_argument("--strategy", choices=["worst", "best", "random"], default="worst",
                        help="Opponent selection for real fights (default: worst)")
    parser.add_argument("--json", action="store_true", help="Output raw fight JSON")
    parser.add_argument("--list", action="store_true", help="List saved fight logs")
    parser.add_argument("--review", type=int, metavar="ID", help="Review a saved fight by ID")
    parser.add_argument("--no-save", action="store_true", help="Don't save fight to log")
    parser.add_argument("--scenario", type=int, help="Test scenario ID (default: 0 for Domingo)")
    parser.add_argument("--count", type=int, default=1, help="Number of fights to run (default: 1)")
    args = parser.parse_args()

    # Handle --list and --review without needing credentials
    if args.list:
        list_fight_logs()
        return

    if args.review:
        review_fight(args.review, show_json=args.json)
        return

    try:
        login, password = load_credentials()
        api = LeekWarsAPI()
        farmer = api.login(login, password)
        farmer_id = farmer["id"]

        print("Logged in.", file=sys.stderr)

        # Pre-resolve leek/AI for non-farmer fights (only once)
        leek_id = args.leek
        ai_id = args.ai
        is_test_fight = not args.real

        if args.real and not args.farmer:
            if not leek_id:
                leeks = farmer.get("leeks", {})
                if not leeks:
                    raise Exception("No leeks on account!")
                leek_id = int(list(leeks.keys())[0])

        if not args.real and not ai_id:
            leeks = farmer.get("leeks", {})
            if args.leek and str(args.leek) in leeks:
                ai_id = leeks[str(args.leek)].get("ai")
            elif leeks:
                ai_id = list(leeks.values())[0].get("ai")
            if not ai_id:
                ai_data = api.get_farmer_ais()
                valid_ais = [a for a in ai_data.get("ais", []) if a.get("valid")]
                if not valid_ais:
                    raise Exception("No valid AI found on account!")
                ai_id = valid_ais[0]["id"]

        wins, losses, draws = 0, 0, 0
        for i in range(args.count):
            prefix = f"[{i+1}/{args.count}] " if args.count > 1 else ""

            if args.real:
                if args.farmer:
                    opponents = api.get_farmer_opponents()
                    opponent = select_opponent(opponents, args.strategy)
                    print(f"{prefix}REAL farmer vs {opponent['name']} (T:{opponent.get('talent', '?')})...", file=sys.stderr)
                    fight_id = api.start_farmer_fight(opponent["id"])
                else:
                    opponents = api.get_leek_opponents(leek_id)
                    opponent = select_opponent(opponents, args.strategy)
                    print(f"{prefix}REAL solo vs {opponent.get('name', '?')} (T:{opponent.get('talent', '?')})...", file=sys.stderr)
                    fight_id = api.start_solo_fight(leek_id, opponent["id"])
            else:
                scenario_id = args.scenario if args.scenario else 0
                scenario_name = f"scenario {scenario_id}" if scenario_id else "Domingo"
                print(f"{prefix}TEST vs {scenario_name} (AI:{ai_id})...", file=sys.stderr)
                fight_id = api.start_test_fight(ai_id, scenario_id=scenario_id)

            print(f"{prefix}Fight #{fight_id}, waiting...", file=sys.stderr)
            result = wait_for_fight(api, fight_id, is_test=is_test_fight)

            api_logs = fetch_fight_logs(api, fight_id) if args.count == 1 else {}
            summary = parse_fight(result, farmer_id, api_logs=api_logs)

            if not args.no_save and args.count == 1:
                save_fight_log(fight_id, result, summary, is_test=is_test_fight)

            if summary.we_won:
                wins += 1
            elif summary.winner == 0:
                draws += 1
            else:
                losses += 1

            if args.count == 1:
                if args.json:
                    print(json.dumps(result, indent=2))
                else:
                    print(format_summary(summary))
            else:
                tag = "WIN" if summary.we_won else ("DRAW" if summary.winner == 0 else "LOSS")
                print(f"{prefix}{tag} (#{fight_id}, {summary.total_turns}t)", file=sys.stderr)

        if args.count > 1:
            print(f"\nResults: {wins}W / {losses}L / {draws}D ({wins}/{args.count})", file=sys.stderr)

    except TagadAIError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
