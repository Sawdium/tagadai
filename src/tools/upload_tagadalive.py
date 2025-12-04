#!/usr/bin/env python3
"""
Upload tagadalive LS4 code to LeekWars.
Creates folder structure and uploads all files.
"""

import os
import sys
import time
from dotenv import load_dotenv

# Add parent to path for import
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

    # Build folder structure
    # We need: API, Model, Model/GameObject, Model/Const, Model/Combos,
    #          Controlers, Controlers/Maps, Services, AI
    folder_ids = {0: 0}  # Root

    folders_needed = set()
    for folder_path, _ in FILES_TO_UPLOAD:
        if folder_path:
            parts = folder_path.split("/")
            for i in range(len(parts)):
                folders_needed.add("/".join(parts[:i+1]))

    print(f"\nFolders needed: {sorted(folders_needed)}")

    # Create folders
    for folder_path in sorted(folders_needed, key=lambda x: x.count("/")):
        parts = folder_path.split("/")
        folder_name = parts[-1]
        parent_path = "/".join(parts[:-1]) if len(parts) > 1 else ""
        parent_id = folder_ids.get(parent_path, 0)

        # Check if exists
        full_name = folder_path  # Use full path for lookup
        if folder_name in existing_folders:
            folder_ids[folder_path] = existing_folders[folder_name]
            print(f"  Folder '{folder_path}' exists (id: {existing_folders[folder_name]})")
        else:
            result = api.create_folder(folder_name, parent_id)
            folder_ids[folder_path] = result["id"]
            existing_folders[folder_name] = result["id"]
            print(f"  Created folder '{folder_path}' (id: {result['id']})")
            time.sleep(0.3)  # Rate limiting

    print(f"\nFolder IDs: {folder_ids}")

    # Create and upload files
    print("\nUploading files...")
    for folder_path, filename in FILES_TO_UPLOAD:
        folder_id = folder_ids.get(folder_path, 0)
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

        # Get or create AI file
        if key in existing_ais:
            ai_id = existing_ais[key]
            print(f"  Updating '{folder_path}/{filename}' (id: {ai_id})...", end="")
        else:
            result = api.create_ai(filename, folder_id, version=4)
            ai_id = result["id"]
            existing_ais[key] = ai_id
            print(f"  Created '{folder_path}/{filename}' (id: {ai_id})...", end="")
            time.sleep(0.3)

        # Upload code
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
        print("You can now assign this AI to your leek in the game.")

    return main_ai_id


if __name__ == "__main__":
    main()
