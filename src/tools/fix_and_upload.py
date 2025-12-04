#!/usr/bin/env python3
"""
Fix tagadalive LS4 code (remove circular includes) and re-upload to LeekWars.
"""

import os
import sys
import re
import time
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(__file__))
from aisync import LeekWarsAPI

# Files to upload in order (from auto include list)
FILES_TO_UPLOAD = [
    ("API", "compatibility"),
    ("Model/GameObject", "Cell"),
    ("Model/GameObject", "Entity"),
    ("Model/GameObject", "EntityEffect"),
    ("Model/GameObject", "Item"),
    ("Model/GameObject", "ItemEffect"),
    ("Model/GameObject", "TargetType"),
    ("Model/Const", "Stats"),
    ("Controlers", "Fight"),
    ("Controlers", "Board"),
    ("Controlers", "Items"),
    ("Controlers/Maps", "MapPath"),
    ("Controlers/Maps", "MapDanger"),
    ("Controlers/Maps", "MapAction"),
    ("Model/Combos", "Danger"),
    ("Model/Combos", "Position"),
    ("Model/Combos", "Action"),
    ("Model/Combos", "Consequences"),
    ("Model/Combos", "Combo"),
    ("Model/Combos", "EffectOverTime"),
    ("Services", "Damages"),
    ("Services", "Targets"),
    ("Services", "Sort"),
    ("Services", "Benchmark"),
    ("AI", "Scoring"),
    ("AI", "AI"),
    ("", "auto"),
    ("", "main"),
]

TAGADALIVE_DIR = "/home/tagada/Desktop/tagadai/tagadalive"


def fix_code(code: str, is_main: bool = False) -> str:
    """Remove circular auto includes from non-main files."""
    if is_main:
        return code

    # Remove include('../auto'), include('../../auto'), etc.
    code = re.sub(r"include\s*\(['\"]\.\./?['\"]?\)?['\"]?auto['\"]?\s*\)\s*;?\s*\n?", "", code)
    code = re.sub(r"include\s*\(['\"]\.\.\/\.\.\/auto['\"]?\s*\)\s*;?\s*\n?", "", code)
    code = re.sub(r"include\s*\(['\"]\.\.\/auto['\"]?\s*\)\s*;?\s*\n?", "", code)

    return code


def main():
    load_dotenv()
    login = os.getenv("LEEKWARS_LOGIN")
    password = os.getenv("LEEKWARS_PASSWORD")

    if not login or not password:
        print("ERROR: Missing credentials in .env", file=sys.stderr)
        sys.exit(1)

    api = LeekWarsAPI()
    api.login(login, password)
    print(f"Logged in as {api.farmer['name']}")

    # Get existing structure
    data = api.get_farmer_ais()
    existing_folders = {f["name"]: f["id"] for f in data.get("folders", [])}
    existing_ais = {}
    for ai in data.get("ais", []):
        folder_id = ai.get("folder", 0)
        key = (folder_id, ai["name"])
        existing_ais[key] = ai["id"]

    # Build folder lookup
    folder_ids = {0: 0}
    for f in data.get("folders", []):
        folder_ids[f["name"]] = f["id"]

    # Map folder paths to IDs
    folder_path_to_id = {
        "": 0,
        "API": existing_folders.get("API", 0),
        "Model": existing_folders.get("Model", 0),
        "Model/GameObject": existing_folders.get("GameObject", 0),
        "Model/Const": existing_folders.get("Const", 0),
        "Model/Combos": existing_folders.get("Combos", 0),
        "Controlers": existing_folders.get("Controlers", 0),
        "Controlers/Maps": existing_folders.get("Maps", 0),
        "Services": existing_folders.get("Services", 0),
        "AI": existing_folders.get("AI", 0),
    }

    print(f"Folder mapping: {folder_path_to_id}")

    # Upload files with fixed code
    print("\nRe-uploading files with fixes...")
    for folder_path, filename in FILES_TO_UPLOAD:
        folder_id = folder_path_to_id.get(folder_path, 0)
        key = (folder_id, filename)

        # Read file content
        if folder_path:
            file_path = os.path.join(TAGADALIVE_DIR, folder_path, filename)
        else:
            file_path = os.path.join(TAGADALIVE_DIR, filename)

        if not os.path.exists(file_path):
            print(f"  WARNING: File not found: {file_path}")
            continue

        with open(file_path, "r", encoding="utf-8") as f:
            code = f.read()

        # Fix code (remove circular includes)
        is_main = filename == "main"
        is_auto = filename == "auto"
        if not is_main and not is_auto:
            original_len = len(code)
            code = fix_code(code)
            if len(code) != original_len:
                print(f"  Fixed circular include in {folder_path}/{filename}")

        # Get AI ID
        if key in existing_ais:
            ai_id = existing_ais[key]
        else:
            print(f"  ERROR: No AI found for {folder_path}/{filename}")
            continue

        # Upload code
        print(f"  Uploading '{folder_path}/{filename}' (id: {ai_id})...", end="")
        api.save_ai(ai_id, code)
        print(" OK")
        time.sleep(0.2)

    # Check validity
    print("\nChecking AI validity...")
    data = api.get_farmer_ais()
    invalid_count = 0
    main_ai_id = None
    for ai in data.get("ais", []):
        if ai["name"] == "main":
            main_ai_id = ai["id"]
        if not ai.get("valid"):
            invalid_count += 1
            print(f"  INVALID: {ai['name']} (id: {ai['id']})")

    if invalid_count == 0:
        print("  All AI files are VALID!")
    else:
        print(f"  {invalid_count} AI files have errors")

    if main_ai_id:
        print(f"\nMain AI ID: {main_ai_id}")

    return main_ai_id


if __name__ == "__main__":
    main()
