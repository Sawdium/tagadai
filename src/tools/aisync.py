#!/usr/bin/env python3
"""
AI Sync Tool - Manage AI code files on LeekWars.

Usage:
    python -m src.tools.aisync list                     # List all AI files
    python -m src.tools.aisync get <ai_id>              # Download AI code to stdout
    python -m src.tools.aisync get <ai_id> -o file.ls   # Download AI code to file
    python -m src.tools.aisync put <ai_id> <file>       # Upload code from file to AI
    python -m src.tools.aisync put <ai_id> -            # Upload code from stdin to AI
    python -m src.tools.aisync new <name> [folder_id]   # Create new AI file
    python -m src.tools.aisync rename <ai_id> <name>    # Rename AI file
    python -m src.tools.aisync delete <ai_id>           # Delete AI file
    python -m src.tools.aisync download <dir>           # Download all AI files to directory
"""

import os
import sys
import json
import argparse
import requests
from typing import Optional
from dotenv import load_dotenv


class LeekWarsAPI:
    """API client for AI management."""

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

    def get_farmer_ais(self) -> dict:
        """Get all AI files and folders."""
        r = self.session.get(f"{self.BASE_URL}/ai/get-farmer-ais")
        return r.json()

    def get_ai(self, ai_id: int) -> dict:
        """Get AI details including code."""
        r = self.session.get(f"{self.BASE_URL}/ai/get/{ai_id}")
        data = r.json()
        if "error" in data:
            raise Exception(f"Failed to get AI: {data.get('error')}")
        return data

    def save_ai(self, ai_id: int, code: str) -> dict:
        """Save code to an AI file."""
        r = self.session.post(
            f"{self.BASE_URL}/ai/save",
            data={"ai_id": ai_id, "code": code}
        )
        data = r.json()
        if "error" in data:
            raise Exception(f"Failed to save AI: {data.get('error')}")
        return data

    def create_ai(self, name: str, folder_id: int = 0, version: int = 4) -> dict:
        """Create a new AI file."""
        r = self.session.post(
            f"{self.BASE_URL}/ai/new-name",
            data={"folder_id": folder_id, "version": str(version), "name": name}
        )
        data = r.json()
        if "error" in data:
            raise Exception(f"Failed to create AI: {data.get('error')}")

        return {"id": data["ai"]["id"], "name": name}

    def rename_ai(self, ai_id: int, name: str) -> dict:
        """Rename an AI file."""
        r = self.session.post(
            f"{self.BASE_URL}/ai/rename",
            data={"ai_id": ai_id, "new_name": name}
        )
        data = r.json()
        if "error" in data:
            raise Exception(f"Failed to rename AI: {data.get('error')}")
        return data

    def create_folder(self, name: str, parent_id: int = 0) -> dict:
        """Create a new folder."""
        r = self.session.post(
            f"{self.BASE_URL}/ai-folder/new/{parent_id}",
            data={"folder_id": parent_id}
        )
        data = r.json()
        if "error" in data:
            raise Exception(f"Failed to create folder: {data.get('error')}")

        folder_id = data["id"]

        # Rename it
        r = self.session.post(
            f"{self.BASE_URL}/ai-folder/rename/{folder_id}/{name}",
            data={"folder_id": folder_id, "new_name": name}
        )

        return {"id": folder_id, "name": name}

    def delete_ai(self, ai_id: int) -> dict:
        """Delete an AI file."""
        r = self.session.delete(
            f"{self.BASE_URL}/ai/delete",
            data={"ai_id": ai_id}
        )
        data = r.json()
        if "error" in data:
            raise Exception(f"Failed to delete AI: {data.get('error')}")
        return data


def cmd_list(api: LeekWarsAPI, args):
    """List all AI files."""
    data = api.get_farmer_ais()

    # Build folder map
    folders = {0: {"name": "(root)", "parent": None}}
    for folder in data.get("folders", []):
        folders[folder["id"]] = {
            "name": folder["name"],
            "parent": folder.get("folder", 0)
        }

    # Get folder path
    def get_path(folder_id: int) -> str:
        if folder_id == 0:
            return ""
        parts = []
        current = folder_id
        while current != 0 and current in folders:
            parts.append(folders[current]["name"])
            current = folders[current]["parent"] or 0
        return "/".join(reversed(parts))

    # Group AIs by folder
    by_folder: dict[int, list] = {}
    for ai in data.get("ais", []):
        folder_id = ai.get("folder", 0)
        by_folder.setdefault(folder_id, []).append(ai)

    if args.json:
        print(json.dumps(data, indent=2))
        return

    # Print tree
    print("AI FILES:")
    print("-" * 60)

    for folder_id in sorted(by_folder.keys()):
        ais = by_folder[folder_id]
        path = get_path(folder_id) or "(root)"
        print(f"\n[{path}]")

        for ai in sorted(ais, key=lambda x: x["name"]):
            valid = "+" if ai.get("valid") else "-"
            version = ai.get("version", "?")
            print(f"  {valid} {ai['name']:30} id:{ai['id']:8}  v{version}")

    print()
    print(f"Total: {len(data.get('ais', []))} files, {len(data.get('folders', []))} folders")


def cmd_get(api: LeekWarsAPI, args):
    """Download AI code."""
    data = api.get_ai(args.ai_id)
    code = data.get("ai", {}).get("code", "")

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(code)
        print(f"Saved to {args.output}", file=sys.stderr)
    else:
        print(code)


def cmd_put(api: LeekWarsAPI, args):
    """Upload code to AI."""
    if args.file == "-":
        code = sys.stdin.read()
    else:
        with open(args.file, "r", encoding="utf-8") as f:
            code = f.read()

    api.save_ai(args.ai_id, code)
    print(f"Uploaded {len(code)} bytes to AI {args.ai_id}", file=sys.stderr)

    # Check if it's valid now
    data = api.get_farmer_ais()
    for ai in data.get("ais", []):
        if ai["id"] == args.ai_id:
            if ai.get("valid"):
                print(f"AI '{ai['name']}' is VALID", file=sys.stderr)
            else:
                print(f"AI '{ai['name']}' has ERRORS", file=sys.stderr)
            break


def cmd_new(api: LeekWarsAPI, args):
    """Create new AI file."""
    result = api.create_ai(args.name, args.folder_id, version=4)
    print(f"Created AI '{result['name']}' with id:{result['id']}", file=sys.stderr)
    print(result["id"])  # Output just the ID for scripting


def cmd_rename(api: LeekWarsAPI, args):
    """Rename AI file."""
    api.rename_ai(args.ai_id, args.name)
    print(f"Renamed AI {args.ai_id} to '{args.name}'", file=sys.stderr)


def cmd_mkdir(api: LeekWarsAPI, args):
    """Create a folder."""
    result = api.create_folder(args.name, args.parent_id)
    print(f"Created folder '{result['name']}' with id:{result['id']}", file=sys.stderr)
    print(result["id"])  # Output just the ID for scripting


def cmd_delete(api: LeekWarsAPI, args):
    """Delete an AI file."""
    # Get the name first
    data = api.get_farmer_ais()
    name = None
    for ai in data.get("ais", []):
        if ai["id"] == args.ai_id:
            name = ai["name"]
            break

    if not name:
        raise Exception(f"AI {args.ai_id} not found")

    api.delete_ai(args.ai_id)
    print(f"Deleted AI '{name}' (id:{args.ai_id})", file=sys.stderr)


def cmd_download(api: LeekWarsAPI, args):
    """Download all AI files to a directory."""
    from pathlib import Path
    import time as time_module

    output_dir = Path(args.directory)
    output_dir.mkdir(parents=True, exist_ok=True)

    data = api.get_farmer_ais()

    # Build folder map - handle nested folders properly
    folders = {0: ""}
    folder_list = data.get("folders", [])

    # Sort folders by parent to ensure parents are processed first
    for folder in sorted(folder_list, key=lambda f: f.get("folder", 0)):
        parent = folder.get("folder", 0)
        parent_path = folders.get(parent, "")
        folders[folder["id"]] = f"{parent_path}/{folder['name']}" if parent_path else folder["name"]

    # Download each AI with rate limiting
    count = 0
    errors = []
    for ai in data.get("ais", []):
        ai_id = ai["id"]
        name = ai["name"]
        folder_id = ai.get("folder", 0)
        folder_path = folders.get(folder_id, "")

        try:
            # Get code
            ai_data = api.get_ai(ai_id)
            code = ai_data.get("ai", {}).get("code", "")

            # Build output path
            if folder_path:
                file_path = output_dir / folder_path / f"{name}.ls"
            else:
                file_path = output_dir / f"{name}.ls"

            file_path.parent.mkdir(parents=True, exist_ok=True)

            with open(file_path, "w", encoding="utf-8") as f:
                f.write(code)

            print(f"  {file_path}", file=sys.stderr)
            count += 1

            # Small delay to avoid rate limiting
            time_module.sleep(0.1)

        except Exception as e:
            errors.append(f"{name}: {e}")
            print(f"  ERROR: {name} - {e}", file=sys.stderr)

    print(f"Downloaded {count} files to {output_dir}", file=sys.stderr)
    if errors:
        print(f"Errors: {len(errors)}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Manage AI code files on LeekWars")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # list
    p_list = subparsers.add_parser("list", help="List all AI files")
    p_list.add_argument("--json", action="store_true", help="Output as JSON")

    # get
    p_get = subparsers.add_parser("get", help="Download AI code")
    p_get.add_argument("ai_id", type=int, help="AI ID to download")
    p_get.add_argument("-o", "--output", help="Output file (default: stdout)")

    # put
    p_put = subparsers.add_parser("put", help="Upload code to AI")
    p_put.add_argument("ai_id", type=int, help="AI ID to update")
    p_put.add_argument("file", help="File to upload (use - for stdin)")

    # new
    p_new = subparsers.add_parser("new", help="Create new AI file")
    p_new.add_argument("name", help="Name for new AI")
    p_new.add_argument("folder_id", type=int, nargs="?", default=0,
                       help="Folder ID (default: root)")

    # rename
    p_rename = subparsers.add_parser("rename", help="Rename AI file")
    p_rename.add_argument("ai_id", type=int, help="AI ID to rename")
    p_rename.add_argument("name", help="New name")

    # mkdir
    p_mkdir = subparsers.add_parser("mkdir", help="Create folder")
    p_mkdir.add_argument("name", help="Folder name")
    p_mkdir.add_argument("parent_id", type=int, nargs="?", default=0,
                         help="Parent folder ID (default: root)")

    # delete
    p_delete = subparsers.add_parser("delete", help="Delete AI file")
    p_delete.add_argument("ai_id", type=int, help="AI ID to delete")

    # download
    p_download = subparsers.add_parser("download", help="Download all AI files")
    p_download.add_argument("directory", help="Output directory")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    load_dotenv()
    login = os.getenv("LEEKWARS_LOGIN")
    password = os.getenv("LEEKWARS_PASSWORD")

    if not login or not password:
        print("ERROR: Missing credentials in .env", file=sys.stderr)
        sys.exit(1)

    try:
        api = LeekWarsAPI()
        api.login(login, password)

        if args.command == "list":
            cmd_list(api, args)
        elif args.command == "get":
            cmd_get(api, args)
        elif args.command == "put":
            cmd_put(api, args)
        elif args.command == "new":
            cmd_new(api, args)
        elif args.command == "rename":
            cmd_rename(api, args)
        elif args.command == "mkdir":
            cmd_mkdir(api, args)
        elif args.command == "delete":
            cmd_delete(api, args)
        elif args.command == "download":
            cmd_download(api, args)

    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
