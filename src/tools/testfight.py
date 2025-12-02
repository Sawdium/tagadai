#!/usr/bin/env python3
"""
Test Fight Tool - Run a test fight against Domingo and analyze results.

Usage:
    python -m src.tools.testfight                    # Run test fight vs Domingo (default)
    python -m src.tools.testfight --real             # Run real solo fight (uses fight count)
    python -m src.tools.testfight --real --farmer    # Run real farmer fight
    python -m src.tools.testfight --json             # Output raw JSON
    python -m src.tools.testfight --strategy worst   # Pick weakest opponent for real fights
"""

import os
import sys
import json
import time
import argparse
import requests
from dataclasses import dataclass
from typing import Optional
from dotenv import load_dotenv


# Action type constants (from fight logs)
ACTION_START_FIGHT = 0
ACTION_USE_WEAPON = 1
ACTION_USE_CHIP = 2
ACTION_NEW_TURN = 6
ACTION_LEEK_TURN = 7
ACTION_MOVE_TO = 10
ACTION_SET_WEAPON = 12
ACTION_TP_LOST = 100
ACTION_LIFE_LOST = 101
ACTION_MP_LOST = 102
ACTION_LIFE_WIN = 103
ACTION_STRENGTH_WIN = 104
ACTION_SUMMON = 200
ACTION_DEATH = 210
ACTION_ADD_EFFECT = 301
ACTION_REMOVE_EFFECT = 302


class LeekWarsAPI:
    """API client for fight operations."""

    BASE_URL = "https://leekwars.com/api"

    def __init__(self):
        self.session = requests.Session()
        self.token: Optional[str] = None
        self.farmer: Optional[dict] = None

    def login(self, login: str, password: str) -> dict:
        r = self.session.post(
            f"{self.BASE_URL}/farmer/login-token",
            data={"login": login, "password": password}
        )
        data = r.json()
        if "error" in data and len(data) == 1:
            raise Exception(f"Login failed: {data.get('error')}")
        self.token = data.get("token")
        self.farmer = data.get("farmer")
        self.session.headers["Authorization"] = f"Bearer {self.token}"
        return self.farmer

    def get_leek_opponents(self, leek_id: int) -> list:
        r = self.session.get(f"{self.BASE_URL}/garden/get-leek-opponents/{leek_id}")
        data = r.json()
        return data.get("opponents", [])

    def get_farmer_opponents(self) -> list:
        r = self.session.get(f"{self.BASE_URL}/garden/get-farmer-opponents")
        data = r.json()
        return data.get("opponents", [])

    def start_solo_fight(self, leek_id: int, enemy_id: int) -> int:
        r = self.session.post(f"{self.BASE_URL}/garden/start-solo-fight/{leek_id}/{enemy_id}")
        data = r.json()
        if "error" in data:
            raise Exception(f"Failed to start fight: {data.get('error')}")
        return data["fight"]

    def start_farmer_fight(self, enemy_id: int) -> int:
        r = self.session.post(f"{self.BASE_URL}/garden/start-farmer-fight/{enemy_id}")
        data = r.json()
        if "error" in data:
            raise Exception(f"Failed to start fight: {data.get('error')}")
        return data["fight"]

    def get_fight(self, fight_id: int, with_logs: bool = True) -> dict:
        url = f"{self.BASE_URL}/fight/get/{fight_id}"
        if with_logs:
            url += "?logs=true"
        r = self.session.get(url)
        return r.json()

    def get_test_scenarios(self) -> dict:
        """Get all test scenarios."""
        r = self.session.get(f"{self.BASE_URL}/test-scenario/get-all")
        return r.json()

    def start_test_fight(self, ai_id: int, scenario_id: int = 0) -> int:
        """Start a test fight against Domingo (or custom scenario).

        Default scenario_id=0 creates an auto-generated scenario with:
        - Team 1: Your leek with the specified AI
        - Team 2: Domingo (bot id -1, ai -2)
        """
        r = self.session.post(
            f"{self.BASE_URL}/ai/test-scenario",
            data={"ai_id": ai_id, "scenario_id": scenario_id}
        )
        data = r.json()
        if "error" in data:
            raise Exception(f"Failed to start test fight: {data.get('error')}")
        return data["fight"]

    def get_farmer_ais(self) -> dict:
        """Get all AI files."""
        r = self.session.get(f"{self.BASE_URL}/ai/get-farmer-ais")
        return r.json()


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
        # Test fights don't support ?logs=true parameter
        result = api.get_fight(fight_id, with_logs=not is_test)

        # If we got an error with logs, retry without
        if "error" in result and not is_test:
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


@dataclass
class FightSummary:
    """Parsed fight summary."""
    fight_id: int
    winner: int  # 0=draw, 1=team1, 2=team2
    we_won: bool
    total_turns: int

    # Our stats
    our_team: list[dict]
    our_damage_dealt: int
    our_damage_received: int
    our_healing_done: int

    # Enemy stats
    enemy_team: list[dict]
    enemy_damage_dealt: int

    # Per-turn breakdown
    turns: list[dict]

    # AI debug logs (if available)
    logs: list[str]

    # Raw data for deep analysis
    raw_actions: list


def parse_fight(result: dict, our_farmer_id: int) -> FightSummary:
    """Parse fight result into structured summary."""

    # Handle nested data structure (test fights have actions under 'data')
    fight_data = result.get("data", {})
    actions = result.get("actions") or fight_data.get("actions", [])

    # Get leeks - either from root 'leeks' or from 'data.leeks' (test fights)
    leeks_list = result.get("leeks") or fight_data.get("leeks", [])
    # Also check leeks1/leeks2 format
    if not leeks_list:
        leeks_list = result.get("leeks1", []) + result.get("leeks2", [])

    # Build leeks dict - handle both id formats (int or string keys)
    # Test fights use internal ids (0, 1, 2...) while real fights use real leek IDs
    leeks = {}
    for l in leeks_list:
        lid = l.get("id")
        if lid is not None:
            leeks[lid] = l

    # Get team IDs from team1/team2 arrays
    team1_ids = set(result.get("team1", []))
    team2_ids = set(result.get("team2", []))

    # If no team arrays, derive from leeks data
    if not team1_ids and not team2_ids:
        for l in leeks_list:
            team = l.get("team", 0)
            lid = l.get("id")
            if team == 1:
                team1_ids.add(lid)
            elif team == 2:
                team2_ids.add(lid)

    # Find our team by checking farmer_id
    our_team_num = 0

    # Check farmers1/farmers2 structure (common in test fights)
    farmers1 = result.get("farmers1", {})
    farmers2 = result.get("farmers2", {}) or []

    if str(our_farmer_id) in farmers1 or our_farmer_id in farmers1:
        our_team_num = 1
    elif isinstance(farmers2, dict) and (str(our_farmer_id) in farmers2 or our_farmer_id in farmers2):
        our_team_num = 2
    else:
        # Fallback: check leeks for farmer field
        for lid in team1_ids:
            if leeks.get(lid, {}).get("farmer") == our_farmer_id:
                our_team_num = 1
                break
        if our_team_num == 0:
            for lid in team2_ids:
                if leeks.get(lid, {}).get("farmer") == our_farmer_id:
                    our_team_num = 2
                    break

    # Default to team 1 if still unknown (shouldn't happen)
    if our_team_num == 0:
        our_team_num = 1

    our_ids = team1_ids if our_team_num == 1 else team2_ids
    enemy_ids = team2_ids if our_team_num == 1 else team1_ids

    our_team = [leeks[lid] for lid in our_ids if lid in leeks]
    enemy_team = [leeks[lid] for lid in enemy_ids if lid in leeks]

    winner = result.get("winner", 0)
    we_won = (winner == our_team_num)

    # Actions already extracted above

    our_damage_dealt = 0
    our_damage_received = 0
    our_healing = 0
    enemy_damage_dealt = 0

    current_turn = 0
    turns = []
    current_turn_data = {"turn": 0, "events": []}

    for action in actions:
        if not action:
            continue
        action_type = action[0]

        if action_type == ACTION_NEW_TURN:
            if current_turn_data["events"]:
                turns.append(current_turn_data)
            current_turn = action[1]
            current_turn_data = {"turn": current_turn, "events": []}

        elif action_type == ACTION_LEEK_TURN:
            leek_id = action[1]
            leek = leeks.get(leek_id, {})
            tp = action[2] if len(action) > 2 else 0
            mp = action[3] if len(action) > 3 else 0
            current_turn_data["events"].append({
                "type": "turn_start",
                "leek": leek.get("name", f"#{leek_id}"),
                "leek_id": leek_id,
                "is_ours": leek_id in our_ids,
                "tp": tp,
                "mp": mp
            })

        elif action_type == ACTION_USE_WEAPON:
            leek_id = action[1]
            weapon_id = action[3] if len(action) > 3 else 0
            success = action[4] == 0 if len(action) > 4 else True
            leek = leeks.get(leek_id, {})
            current_turn_data["events"].append({
                "type": "weapon",
                "leek": leek.get("name", f"#{leek_id}"),
                "is_ours": leek_id in our_ids,
                "weapon_id": weapon_id,
                "success": success
            })

        elif action_type == ACTION_USE_CHIP:
            leek_id = action[1]
            chip_id = action[3] if len(action) > 3 else 0
            success = action[4] == 0 if len(action) > 4 else True
            leek = leeks.get(leek_id, {})
            current_turn_data["events"].append({
                "type": "chip",
                "leek": leek.get("name", f"#{leek_id}"),
                "is_ours": leek_id in our_ids,
                "chip_id": chip_id,
                "success": success
            })

        elif action_type == ACTION_LIFE_LOST:
            target_id = action[1]
            damage = action[2] if len(action) > 2 else 0
            leek = leeks.get(target_id, {})

            if target_id in our_ids:
                our_damage_received += damage
                enemy_damage_dealt += damage
            else:
                our_damage_dealt += damage

            current_turn_data["events"].append({
                "type": "damage",
                "leek": leek.get("name", f"#{target_id}"),
                "is_ours": target_id in our_ids,
                "amount": damage
            })

        elif action_type == ACTION_LIFE_WIN:
            target_id = action[1]
            amount = action[2] if len(action) > 2 else 0
            leek = leeks.get(target_id, {})

            if target_id in our_ids:
                our_healing += amount

            current_turn_data["events"].append({
                "type": "heal",
                "leek": leek.get("name", f"#{target_id}"),
                "is_ours": target_id in our_ids,
                "amount": amount
            })

        elif action_type == ACTION_DEATH:
            leek_id = action[1]
            leek = leeks.get(leek_id, {})
            current_turn_data["events"].append({
                "type": "death",
                "leek": leek.get("name", f"#{leek_id}"),
                "is_ours": leek_id in our_ids
            })

        elif action_type == ACTION_MOVE_TO:
            leek_id = action[1]
            leek = leeks.get(leek_id, {})
            cells_moved = len(action[3]) if len(action) > 3 and action[3] else 0
            current_turn_data["events"].append({
                "type": "move",
                "leek": leek.get("name", f"#{leek_id}"),
                "is_ours": leek_id in our_ids,
                "cells": cells_moved
            })

    # Add last turn
    if current_turn_data["events"]:
        turns.append(current_turn_data)

    # Extract logs
    logs = []
    for leek in result.get("leeks", []):
        if leek.get("farmer") == our_farmer_id and leek.get("logs"):
            logs.extend(leek["logs"])

    return FightSummary(
        fight_id=result.get("fight", result.get("id", 0)),
        winner=winner,
        we_won=we_won,
        total_turns=current_turn,
        our_team=our_team,
        our_damage_dealt=our_damage_dealt,
        our_damage_received=our_damage_received,
        our_healing_done=our_healing,
        enemy_team=enemy_team,
        enemy_damage_dealt=enemy_damage_dealt,
        turns=turns,
        logs=logs,
        raw_actions=actions
    )


def format_summary(summary: FightSummary) -> str:
    """Format fight summary for reading."""
    lines = []

    # Header
    lines.append("=" * 70)
    result_str = "WIN" if summary.we_won else ("DRAW" if summary.winner == 0 else "LOSS")
    result_emoji = "✓" if summary.we_won else ("=" if summary.winner == 0 else "✗")
    lines.append(f"FIGHT #{summary.fight_id} - {result_emoji} {result_str}")
    lines.append("=" * 70)

    # Teams
    lines.append("")
    our_names = ", ".join(f"{l['name']} Lv{l.get('level', '?')}" for l in summary.our_team)
    enemy_names = ", ".join(f"{l['name']} Lv{l.get('level', '?')}" for l in summary.enemy_team)
    lines.append(f"OUR TEAM:   {our_names}")
    lines.append(f"ENEMY TEAM: {enemy_names}")

    # Stats
    lines.append("")
    lines.append("COMBAT STATS:")
    lines.append(f"  Turns:           {summary.total_turns}")
    lines.append(f"  Damage Dealt:    {summary.our_damage_dealt}")
    lines.append(f"  Damage Received: {summary.our_damage_received}")
    lines.append(f"  Healing Done:    {summary.our_healing_done}")

    net_damage = summary.our_damage_dealt - summary.our_damage_received
    lines.append(f"  Net Damage:      {net_damage:+d}")

    # Turn-by-turn summary (condensed)
    lines.append("")
    lines.append("TURN SUMMARY:")
    for turn_data in summary.turns:
        turn_num = turn_data["turn"]
        events = turn_data["events"]

        # Summarize this turn
        our_dmg = sum(e["amount"] for e in events if e["type"] == "damage" and not e["is_ours"])
        their_dmg = sum(e["amount"] for e in events if e["type"] == "damage" and e["is_ours"])
        deaths = [e["leek"] for e in events if e["type"] == "death"]

        death_str = f" | Deaths: {', '.join(deaths)}" if deaths else ""
        lines.append(f"  T{turn_num:2d}: We dealt {our_dmg:4d}, took {their_dmg:4d}{death_str}")

    # AI Debug logs
    if summary.logs:
        lines.append("")
        lines.append("AI DEBUG LOGS:")
        for log in summary.logs[:20]:  # Limit to first 20
            lines.append(f"  {log}")
        if len(summary.logs) > 20:
            lines.append(f"  ... ({len(summary.logs) - 20} more)")

    lines.append("")
    lines.append("=" * 70)

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Run a test fight and display results")
    parser.add_argument("--real", action="store_true", help="Run a real fight (uses fight count)")
    parser.add_argument("--leek", type=int, help="Leek ID to fight with (default: first leek)")
    parser.add_argument("--ai", type=int, help="AI ID to test (default: leek's assigned AI)")
    parser.add_argument("--farmer", action="store_true", help="Run farmer fight (only with --real)")
    parser.add_argument("--strategy", choices=["worst", "best", "random"], default="worst",
                        help="Opponent selection for real fights (default: worst)")
    parser.add_argument("--json", action="store_true", help="Output raw fight JSON")
    args = parser.parse_args()

    load_dotenv()
    login = os.getenv("LEEKWARS_LOGIN")
    password = os.getenv("LEEKWARS_PASSWORD")

    if not login or not password:
        print("ERROR: Missing credentials in .env", file=sys.stderr)
        sys.exit(1)

    try:
        api = LeekWarsAPI()
        farmer = api.login(login, password)
        farmer_id = farmer["id"]

        print("Logged in.", file=sys.stderr)

        is_test_fight = False

        if args.real:
            # Real fight (uses fight count)
            if args.farmer:
                opponents = api.get_farmer_opponents()
                opponent = select_opponent(opponents, args.strategy)
                print(f"Starting REAL farmer fight vs {opponent['name']} (T:{opponent.get('talent', '?')})...", file=sys.stderr)
                fight_id = api.start_farmer_fight(opponent["id"])
            else:
                leek_id = args.leek
                if not leek_id:
                    leeks = farmer.get("leeks", {})
                    if not leeks:
                        raise Exception("No leeks on account!")
                    leek_id = int(list(leeks.keys())[0])
                    leek_name = leeks[str(leek_id)]["name"]
                else:
                    leek_name = f"#{leek_id}"

                opponents = api.get_leek_opponents(leek_id)
                opponent = select_opponent(opponents, args.strategy)
                opp_name = opponent.get("name", "Unknown")
                opp_talent = opponent.get("talent", "?")
                print(f"Starting REAL solo fight: {leek_name} vs {opp_name} (T:{opp_talent})...", file=sys.stderr)
                fight_id = api.start_solo_fight(leek_id, opponent["id"])
        else:
            # Test fight against Domingo (default - free, doesn't use fight count)
            ai_id = args.ai
            if not ai_id:
                # Get AI from leek or first valid AI
                leeks = farmer.get("leeks", {})
                if args.leek and str(args.leek) in leeks:
                    ai_id = leeks[str(args.leek)].get("ai")
                elif leeks:
                    first_leek = list(leeks.values())[0]
                    ai_id = first_leek.get("ai")

                if not ai_id:
                    # Fallback: get first valid AI from account
                    ai_data = api.get_farmer_ais()
                    valid_ais = [a for a in ai_data.get("ais", []) if a.get("valid")]
                    if not valid_ais:
                        raise Exception("No valid AI found on account!")
                    ai_id = valid_ais[0]["id"]
                    print(f"Using AI: {valid_ais[0]['name']} (id:{ai_id})", file=sys.stderr)

            print(f"Starting TEST fight vs Domingo (AI id:{ai_id})...", file=sys.stderr)
            fight_id = api.start_test_fight(ai_id, scenario_id=0)
            is_test_fight = True

        print(f"Fight #{fight_id} started, waiting for result...", file=sys.stderr)
        result = wait_for_fight(api, fight_id, is_test=is_test_fight)

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            summary = parse_fight(result, farmer_id)
            print(format_summary(summary))

    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
