#!/usr/bin/env python3
"""
Account Status Tool - Displays current state of LeekWars account.

Usage:
    python -m src.tools.status          # Human-readable output
    python -m src.tools.status --json   # JSON output for programmatic use
"""

import sys
import json
import argparse
from dataclasses import dataclass, asdict
from typing import Optional

from src.common import LeekWarsAPI, load_credentials
from src.common.errors import TagadAIError


@dataclass
class LeekInfo:
    id: int
    name: str
    level: int
    talent: int
    capital: int
    ai_id: Optional[int]
    ai_name: Optional[str]
    in_garden: bool


@dataclass
class AIFile:
    id: int
    name: str
    version: int
    valid: bool
    folder_id: int


@dataclass
class AccountStatus:
    farmer_id: int
    farmer_name: str
    talent: int
    total_level: int
    habs: int
    crystals: int
    fights_available: int
    in_garden: bool
    team_id: Optional[int]
    team_name: Optional[str]
    leeks: list[LeekInfo]
    ai_files: list[AIFile]
    ai_folders: list[dict]


def get_status(api: LeekWarsAPI) -> AccountStatus:
    """Fetch and compile complete account status."""
    farmer = api.farmer

    # Get AI files
    ai_data = api.get_farmer_ais()
    ai_files = []
    ai_folders = []
    ai_map = {}  # id -> name mapping

    for ai in ai_data.get("ais", []):
        ai_files.append(AIFile(
            id=ai["id"],
            name=ai["name"],
            version=ai.get("version", 1),
            valid=ai.get("valid", False),
            folder_id=ai.get("folder", 0)
        ))
        ai_map[ai["id"]] = ai["name"]

    for folder in ai_data.get("folders", []):
        ai_folders.append({
            "id": folder["id"],
            "name": folder["name"],
            "parent": folder.get("folder", 0)
        })

    # Build leek info
    leeks = []
    for leek_id, leek in farmer.get("leeks", {}).items():
        ai_id = leek.get("ai")
        leeks.append(LeekInfo(
            id=int(leek_id),
            name=leek["name"],
            level=leek["level"],
            talent=leek["talent"],
            capital=leek["capital"],
            ai_id=ai_id,
            ai_name=ai_map.get(ai_id) if ai_id else None,
            in_garden=leek.get("in_garden", False)
        ))

    # Sort leeks by level descending
    leeks.sort(key=lambda x: x.level, reverse=True)

    # Team info
    team_id = farmer.get("team", {}).get("id") if farmer.get("team") else None
    team_name = farmer.get("team", {}).get("name") if farmer.get("team") else None

    return AccountStatus(
        farmer_id=farmer["id"],
        farmer_name=farmer["login"],
        talent=farmer["talent"],
        total_level=farmer["total_level"],
        habs=farmer["habs"],
        crystals=farmer.get("crystals", 0),
        fights_available=farmer["fights"],
        in_garden=farmer.get("in_garden", 0) == 1,
        team_id=team_id,
        team_name=team_name,
        leeks=leeks,
        ai_files=ai_files,
        ai_folders=ai_folders
    )


def format_human_readable(status: AccountStatus) -> str:
    """Format status for human reading."""
    lines = []

    # Header
    lines.append("=" * 60)
    lines.append(f"ACCOUNT: {status.farmer_name} (ID: {status.farmer_id})")
    lines.append("=" * 60)

    # Farmer stats
    lines.append("")
    lines.append("FARMER STATS:")
    lines.append(f"  Talent:      {status.talent}")
    lines.append(f"  Total Level: {status.total_level}")
    lines.append(f"  Habs:        {status.habs:,}")
    lines.append(f"  Crystals:    {status.crystals}")
    lines.append(f"  Fights:      {status.fights_available}")
    lines.append(f"  In Garden:   {'Yes' if status.in_garden else 'No'}")
    if status.team_name:
        lines.append(f"  Team:        {status.team_name} (ID: {status.team_id})")

    # Leeks
    lines.append("")
    lines.append(f"LEEKS ({len(status.leeks)}):")
    for leek in status.leeks:
        garden_mark = "[G]" if leek.in_garden else "[ ]"
        capital_warn = f" (!!{leek.capital} capital)" if leek.capital > 0 else ""
        ai_info = f" -> {leek.ai_name}" if leek.ai_name else " -> NO AI"
        lines.append(f"  {garden_mark} {leek.name} Lv{leek.level} (T:{leek.talent}){capital_warn}{ai_info}")

    # AI Files summary
    lines.append("")
    valid_count = sum(1 for ai in status.ai_files if ai.valid)
    lines.append(f"AI FILES ({len(status.ai_files)} total, {valid_count} valid):")

    # Group by folder
    folders_dict = {0: "root"}
    for folder in status.ai_folders:
        folders_dict[folder["id"]] = folder["name"]

    by_folder: dict[int, list[AIFile]] = {}
    for ai in status.ai_files:
        by_folder.setdefault(ai.folder_id, []).append(ai)

    for folder_id, ais in sorted(by_folder.items()):
        folder_name = folders_dict.get(folder_id, f"folder_{folder_id}")
        lines.append(f"  [{folder_name}]")
        for ai in sorted(ais, key=lambda x: x.name):
            valid_mark = "+" if ai.valid else "-"
            lines.append(f"    {valid_mark} {ai.name} (v{ai.version}, id:{ai.id})")

    lines.append("")
    lines.append("=" * 60)

    return "\n".join(lines)


def to_json(status: AccountStatus) -> str:
    """Convert status to JSON string."""
    data = asdict(status)
    return json.dumps(data, indent=2)


def main():
    parser = argparse.ArgumentParser(description="Display LeekWars account status")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        login, password = load_credentials()
        api = LeekWarsAPI()
        api.login(login, password)
        status = get_status(api)

        if args.json:
            print(to_json(status))
        else:
            print(format_human_readable(status))

    except TagadAIError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
