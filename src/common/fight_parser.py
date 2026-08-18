"""
Fight parsing for LeekWars API responses.

Parses fight results from the LeekWars API into structured summaries.

Note: This is separate from localfight/parser.py which parses output
from the local Java generator (different action codes and data structure).
"""

from dataclasses import dataclass


# Action type constants, verified twice over: against the generator's own
# Action.java, and against a real fight/get/{id} response.
#
# These were renumbered upstream. USE_WEAPON was 1, USE_CHIP was 2, SET_WEAPON
# was 3 — Action.java still carries the old values commented out as
# USE_WEAPON_OLD. The old numbers appear in no fight log any more, so a parser
# holding them matches nothing and silently reports no weapon or chip use at
# all. Several others moved too: death was 210 and is 5, and 302 used to mean
# "remove effect" but now means "add chip effect", which is worse than a miss.
#
# Two payloads also changed shape. USE_WEAPON and USE_CHIP no longer name the
# acting leek, and LEEK_TURN no longer carries TP/MP — the actor is whoever the
# most recent LEEK_TURN named.
ACTION_START_FIGHT = 0
ACTION_DEATH = 5              # [5, leek_id]
ACTION_NEW_TURN = 6           # [6, turn_number]
ACTION_LEEK_TURN = 7          # [7, leek_id]
ACTION_END_TURN = 8
ACTION_SUMMON = 9
ACTION_MOVE_TO = 10           # [10, leek_id, dest_cell, [path]]
ACTION_KILL = 11
ACTION_USE_CHIP = 12          # [12, chip_id, cell, success]
ACTION_SET_WEAPON = 13        # [13, weapon_id]
ACTION_USE_WEAPON = 16        # [16, cell, success]
ACTION_TP_LOST = 100
ACTION_LIFE_LOST = 101        # [101, target_id, amount, erosion]
ACTION_MP_LOST = 102
ACTION_LIFE_WIN = 103
ACTION_STRENGTH_WIN = 104
ACTION_NOVA_DAMAGE = 107
ACTION_LIFE_DAMAGE = 109
ACTION_POISON_DAMAGE = 110
ACTION_AFTEREFFECT = 111
ACTION_SAY = 203              # [203, message]
ACTION_SHOW_CELL = 205
ACTION_ADD_WEAPON_EFFECT = 301
ACTION_ADD_CHIP_EFFECT = 302
ACTION_REMOVE_EFFECT = 303

# Error action codes
ACTION_ERROR_TOO_MANY_OPS = 1002  # AI interrupted: too many operations consumed
ACTION_ERROR_TIMEOUT = 1003       # AI timeout
ACTION_ERROR_EXCEPTION = 1004     # AI runtime exception

# Error code descriptions
ERROR_DESCRIPTIONS = {
    1002: "AI interrupted: too many operations consumed",
    1003: "AI timeout",
    1004: "AI runtime exception",
    1005: "AI stack overflow",
    1006: "AI invalid operation",
}


@dataclass
class FightSummary:
    """Parsed fight summary from LeekWars API."""
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

    # AI errors (e.g., too many operations, timeout)
    errors: list[dict]

    # AI say() messages
    messages: list[str]

    # AI debug(), debugW(), debugE() output from actions
    debug_output: list[dict]

    # AI debug logs from API (if available) - old format
    logs: list[str]

    # API logs from /fight/get-logs endpoint (debug/debugW/debugE)
    api_logs: dict

    # Raw data for deep analysis
    raw_actions: list


def parse_fight(result: dict, our_farmer_id: int, api_logs: dict = None) -> FightSummary:
    """Parse fight result into structured summary."""
    if api_logs is None:
        api_logs = {}

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

    # USE_WEAPON and USE_CHIP no longer say who acted, so the actor has to be
    # carried forward from the last LEEK_TURN. USE_WEAPON does not say what
    # fired either, so the weapon in hand is tracked per leek across turns.
    actor_id = None
    actor_weapon = 0
    held_weapon = {}

    # Track errors, messages, and debug output
    errors = []
    messages = []
    debug_output = []

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
            # [7, leek_id]. TP/MP used to ride along here and no longer do;
            # they are only observable now as PT_LOST/PM_LOST deltas.
            leek_id = action[1]
            actor_id = leek_id
            actor_weapon = held_weapon.get(leek_id, 0)
            leek = leeks.get(leek_id, {})
            current_turn_data["events"].append({
                "type": "turn_start",
                "leek": leek.get("name", f"#{leek_id}"),
                "leek_id": leek_id,
                "is_ours": leek_id in our_ids,
            })

        elif action_type == ACTION_SET_WEAPON:
            # [13, weapon_id] by the current actor. Tracked because USE_WEAPON
            # below reports only where the shot landed, never what fired it.
            actor_weapon = action[1] if len(action) > 1 else 0
            if actor_id is not None:
                held_weapon[actor_id] = actor_weapon

        elif action_type == ACTION_USE_WEAPON:
            # [16, cell, success] — no leek, no weapon. Both come from context.
            success = bool(action[2]) if len(action) > 2 else True
            leek = leeks.get(actor_id, {})
            current_turn_data["events"].append({
                "type": "weapon",
                "leek": leek.get("name", f"#{actor_id}"),
                "is_ours": actor_id in our_ids,
                "weapon_id": actor_weapon,
                "cell": action[1] if len(action) > 1 else 0,
                "success": success
            })

        elif action_type == ACTION_USE_CHIP:
            # [12, chip_id, cell, success] — the chip is named, the caster is not.
            chip_id = action[1] if len(action) > 1 else 0
            success = bool(action[3]) if len(action) > 3 else True
            leek = leeks.get(actor_id, {})
            current_turn_data["events"].append({
                "type": "chip",
                "leek": leek.get("name", f"#{actor_id}"),
                "is_ours": actor_id in our_ids,
                "chip_id": chip_id,
                "cell": action[2] if len(action) > 2 else 0,
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

        elif action_type == ACTION_SAY:
            # say() message from AI
            message = action[1] if len(action) > 1 else ""
            messages.append(message)

        # debug()/debugW()/debugE() do NOT appear in the action list. They are
        # served separately and reach us through `api_logs`; the 204/205/206
        # codes this used to watch for do not exist, and 205 is SHOW_CELL.

        elif action_type in ERROR_DESCRIPTIONS:
            # AI error occurred
            leek_id = action[1] if len(action) > 1 else 0
            leek = leeks.get(leek_id, {})
            errors.append({
                "type": action_type,
                "description": ERROR_DESCRIPTIONS.get(action_type, f"Unknown error {action_type}"),
                "leek": leek.get("name", f"#{leek_id}"),
                "leek_id": leek_id,
                "is_ours": leek_id in our_ids,
                "turn": current_turn
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
        errors=errors,
        messages=messages,
        debug_output=debug_output,
        logs=logs,
        api_logs=api_logs,
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

    # AI ERRORS - show prominently at top!
    if summary.errors:
        lines.append("")
        lines.append("!!! AI ERRORS !!!")
        for err in summary.errors:
            owner = "(OUR AI)" if err["is_ours"] else "(ENEMY)"
            lines.append(f"  [{err['leek']}] {owner} Turn {err['turn']}: {err['description']}")
        lines.append("")

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

    # AI say() messages
    if summary.messages:
        lines.append("")
        lines.append("AI MESSAGES (say):")
        for msg in summary.messages[:15]:  # Limit to first 15
            lines.append(f"  {msg}")
        if len(summary.messages) > 15:
            lines.append(f"  ... ({len(summary.messages) - 15} more)")

    # AI debug output (debug/debugW/debugE)
    if summary.debug_output:
        lines.append("")
        lines.append("AI DEBUG OUTPUT:")
        for dbg in summary.debug_output[:30]:  # Limit to first 30
            prefix = {"debug": "  ", "warn": "W ", "error": "E "}.get(dbg["level"], "  ")
            lines.append(f"  {prefix}[T{dbg['turn']}] {dbg['message']}")
        if len(summary.debug_output) > 30:
            lines.append(f"  ... ({len(summary.debug_output) - 30} more)")

    # AI Debug logs from API (old format)
    if summary.logs:
        lines.append("")
        lines.append("AI DEBUG LOGS:")
        for log in summary.logs[:20]:  # Limit to first 20
            lines.append(f"  {log}")
        if len(summary.logs) > 20:
            lines.append(f"  ... ({len(summary.logs) - 20} more)")

    # API logs from /fight/get-logs endpoint (debug/debugW/debugE)
    if summary.api_logs:
        lines.append("")
        lines.append("AI OUTPUT (from report):")
        # api_logs structure: {farmer_id: {action_index: [[?, level, message, ...], ...]}}
        # Level: 0=debug, 1=warn, 2=error (at index 1)
        # Message text at index 2
        all_messages = []
        for farmer_id, farmer_logs in summary.api_logs.items():
            if isinstance(farmer_logs, dict):
                # Sorted by action index to maintain chronological order
                for action_idx in sorted(farmer_logs.keys(), key=lambda x: int(x) if x.isdigit() else 0):
                    messages = farmer_logs[action_idx]
                    if isinstance(messages, list):
                        for msg in messages:
                            if isinstance(msg, list) and len(msg) >= 3:
                                # Format: [unknown, level, message, ...]
                                # Level: 0=mark(?), 1=debug, 2=debugW, 3=debugE
                                level = msg[1]
                                text = msg[2]
                                level_str = {0: "M ", 1: "  ", 2: "W ", 3: "E "}.get(level, "  ")
                                all_messages.append(f"{level_str}{text}")
                            elif isinstance(msg, str):
                                all_messages.append(f"  {msg}")

        for msg in all_messages[:100]:  # Limit to first 100
            lines.append(f"  {msg}")
        if len(all_messages) > 100:
            lines.append(f"  ... ({len(all_messages) - 100} more)")

    lines.append("")
    lines.append("=" * 70)

    return "\n".join(lines)
