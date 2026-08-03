#!/usr/bin/env python3
"""
Account Status Tool — displays current state of a LeekWars account.

Usage:
    python -m src.tools.status          # Human-readable
    python -m src.tools.status --json   # JSON
    python -m src.tools.status --account tagadalton   # Switch account
"""

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field

from src.common import LeekWarsAPI, load_credentials
from src.common.errors import TagadAIError


@dataclass
class LeekInfo:
    id: int
    name: str
    level: int
    talent: int
    capital: int
    ai_path: str | None     # From ai_tree.leek_ais (canonical)
    in_garden: bool


@dataclass
class AIFile:
    path: str
    version: int
    valid: bool
    total_lines: int
    total_chars: int
    scenario: int | None = None


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
    team_id: int | None
    team_name: str | None
    leeks: list[LeekInfo]
    ai_files: list[AIFile]
    ai_folders: list[str]
    ai_bin: list[dict] = field(default_factory=list)


def get_status(api: LeekWarsAPI) -> AccountStatus:
    farmer = api.farmer
    tree = api.get_ai_tree()
    leek_ai_map = api.get_leek_ai_paths()

    ai_files = [
        AIFile(
            path=f["path"],
            version=f.get("version", 4),
            valid=f.get("valid", False),
            total_lines=f.get("total_lines", 0),
            total_chars=f.get("total_chars", 0),
            scenario=f.get("scenario"),
        )
        for f in tree.get("files", [])
    ]

    leeks = []
    for leek_id, leek in (farmer.get("leeks") or {}).items():
        lid = int(leek_id)
        leeks.append(LeekInfo(
            id=lid,
            name=leek["name"],
            level=leek["level"],
            talent=leek["talent"],
            capital=leek["capital"],
            ai_path=leek_ai_map.get(lid),
            in_garden=leek.get("in_garden", False),
        ))
    leeks.sort(key=lambda x: x.level, reverse=True)

    team = farmer.get("team") or {}
    return AccountStatus(
        farmer_id=farmer["id"],
        farmer_name=farmer["login"],
        talent=farmer["talent"],
        total_level=farmer["total_level"],
        habs=farmer["habs"],
        crystals=farmer.get("crystals", 0),
        fights_available=farmer["fights"],
        in_garden=farmer.get("in_garden", 0) == 1,
        team_id=team.get("id"),
        team_name=team.get("name"),
        leeks=leeks,
        ai_files=ai_files,
        ai_folders=sorted(tree.get("folders", [])),
        ai_bin=list(tree.get("bin", [])),
    )


def format_human_readable(s: AccountStatus) -> str:
    lines = []
    lines.append("=" * 60)
    lines.append(f"ACCOUNT: {s.farmer_name} (ID: {s.farmer_id})")
    lines.append("=" * 60)

    lines.append("")
    lines.append("FARMER STATS:")
    lines.append(f"  Talent:      {s.talent}")
    lines.append(f"  Total Level: {s.total_level}")
    lines.append(f"  Habs:        {s.habs:,}")
    lines.append(f"  Crystals:    {s.crystals}")
    lines.append(f"  Fights:      {s.fights_available}")
    lines.append(f"  In Garden:   {'Yes' if s.in_garden else 'No'}")
    if s.team_name:
        lines.append(f"  Team:        {s.team_name} (ID: {s.team_id})")

    lines.append("")
    lines.append(f"LEEKS ({len(s.leeks)}):")
    for leek in s.leeks:
        gm = "[G]" if leek.in_garden else "[ ]"
        cap = f" (!!{leek.capital} capital)" if leek.capital > 0 else ""
        ai = f" -> {leek.ai_path}" if leek.ai_path else " -> NO AI"
        lines.append(f"  {gm} {leek.name} Lv{leek.level} (T:{leek.talent}){cap}{ai}")

    lines.append("")
    valid = sum(1 for ai in s.ai_files if ai.valid)
    lines.append(f"AI FILES ({len(s.ai_files)} total, {valid} valid):")

    by_folder: dict[str, list[AIFile]] = {}
    for ai in s.ai_files:
        folder = ai.path.rsplit("/", 1)[0] if "/" in ai.path else ""
        by_folder.setdefault(folder, []).append(ai)

    for folder in sorted(by_folder):
        label = folder if folder else "(root)"
        lines.append(f"  [{label}]")
        for ai in sorted(by_folder[folder], key=lambda x: x.path):
            name = ai.path.rsplit("/", 1)[-1]
            mark = "+" if ai.valid else "-"
            lines.append(f"    {mark} {name} (v{ai.version}, {ai.total_lines} lines)")

    if s.ai_bin:
        lines.append("")
        lines.append(f"BIN ({len(s.ai_bin)}):")
        for b in s.ai_bin:
            lines.append(f"  - {b['path']}")

    lines.append("")
    lines.append("=" * 60)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Display LeekWars account status")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--account", help="Override LEEKWARS_LOGIN (password from .env)")
    args = parser.parse_args()

    try:
        login, password = load_credentials()
        if args.account:
            login = args.account
        api = LeekWarsAPI()
        api.login(login, password)
        status = get_status(api)

        if args.json:
            print(json.dumps(asdict(status), indent=2))
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
