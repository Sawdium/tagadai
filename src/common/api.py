"""
Unified LeekWars API client.

This module provides a single API client that combines all functionality
previously scattered across status.py, aisync.py, fight.py, and scraper.py.

Usage:
    from src.common import LeekWarsAPI, load_credentials

    api = LeekWarsAPI()
    login, password = load_credentials()
    api.login(login, password)

    # Now use any API method
    status = api.get_garden()
    opponents = api.get_leek_opponents(leek_id)
    ai_code = api.read_ai("main")
    api.write_ai("main", new_code)
"""

import json
import requests
from typing import Optional

from .errors import APIError, AuthenticationError


class LeekWarsAPI:
    """
    Unified API client for LeekWars.

    Verification legend (per-method markers below):
      VERIFIED   — exercised with a successful round-trip in the 2026 API.
      UNVERIFIED — inherited from pre-2026 code, never re-tested. May return
                   no_such_service or require a different payload. The only
                   methods still in this state are ones that irreversibly
                   consume resources (potions, capital, habs) and were
                   deliberately skipped in the verification pass:
                     - use_potion       (consumes a potion instance)
                     - spend_capital    (reversible only via restat potion)
                     - buy_item         (spends habs)

    The AI / ai-folder endpoints are fully path-based — no integer IDs.
    Scenario endpoints also use paths for the `ai` field (confirmed via
    round-trip). See docs/LEEKWARS_API.md for payload details.
    """

    BASE_URL = "https://leekwars.com/api"

    def __init__(self):
        self.session = requests.Session()
        self.token: Optional[str] = None
        self.farmer: Optional[dict] = None

    # =========================================================================
    # Authentication
    # =========================================================================

    def login(self, login: str, password: str) -> dict:
        """[VERIFIED] Authenticate with LeekWars.

        Args:
            login: Username or email
            password: Password

        Returns:
            Farmer data dict

        Raises:
            AuthenticationError: If login fails
        """
        try:
            r = self.session.post(
                f"{self.BASE_URL}/farmer/login-token",
                data={"login": login, "password": password}
            )
            data = r.json()
        except requests.RequestException as e:
            raise APIError(f"Network error during login: {e}")
        except json.JSONDecodeError as e:
            raise APIError(f"Invalid response from server: {e}")

        if "error" in data and len(data) == 1:
            raise AuthenticationError(f"Login failed: {data.get('error')}")

        self.token = data.get("token")
        self.farmer = data.get("farmer")
        self.session.headers["Authorization"] = f"Bearer {self.token}"
        return self.farmer

    @property
    def is_authenticated(self) -> bool:
        """Check if currently authenticated."""
        return self.token is not None

    @property
    def farmer_id(self) -> Optional[int]:
        """Get the logged-in farmer's ID."""
        return self.farmer.get("id") if self.farmer else None

    # =========================================================================
    # Garden & Fights
    # =========================================================================

    def get_garden(self) -> dict:
        """[VERIFIED] Get garden state (includes compositions)."""
        r = self.session.get(f"{self.BASE_URL}/garden/get")
        return self._handle_response(r)

    def get_leek_opponents(self, leek_id: int) -> list:
        """[VERIFIED] Get opponents for solo fights."""
        r = self.session.get(f"{self.BASE_URL}/garden/get-leek-opponents/{leek_id}")
        data = self._handle_response(r)
        return data.get("opponents", [])

    def get_farmer_opponents(self) -> list:
        """[VERIFIED] Get opponents for farmer fights."""
        r = self.session.get(f"{self.BASE_URL}/garden/get-farmer-opponents")
        data = self._handle_response(r)
        return data.get("opponents", [])

    def start_solo_fight(self, leek_id: int, enemy_id: int) -> int:
        """[VERIFIED] Start a solo fight. Consumes 1 fight from the daily pool.

        Payload is body-form {leek_id, target_id} — the old doc listing URL
        path segments is stale. Returns fight ID.
        """
        r = self.session.post(
            f"{self.BASE_URL}/garden/start-solo-fight",
            data={"leek_id": leek_id, "target_id": enemy_id}
        )
        data = self._handle_response(r, "start fight")
        return data["fight"]

    def start_farmer_fight(self, enemy_id: int) -> int:
        """[VERIFIED] Start a farmer fight. Consumes 1 fight from the daily pool.

        Payload is body-form {target_id}. Returns fight ID.
        """
        r = self.session.post(
            f"{self.BASE_URL}/garden/start-farmer-fight",
            data={"target_id": enemy_id}
        )
        data = self._handle_response(r, "start fight")
        return data["fight"]

    def get_fight(self, fight_id: int, with_logs: bool = True) -> dict:
        """[VERIFIED] Get fight data. Optional ?logs=true for debug logs inline."""
        url = f"{self.BASE_URL}/fight/get/{fight_id}"
        if with_logs:
            url += "?logs=true"
        r = self.session.get(url)
        return r.json()

    def get_fight_logs(self, fight_id: int) -> dict:
        """[VERIFIED] Get debug logs for a fight. Keyed by farmer id, then action index."""
        r = self.session.get(f"{self.BASE_URL}/fight/get-logs/{fight_id}")
        return r.json()

    # =========================================================================
    # AI Management (path-based — 2026 API)
    # =========================================================================
    # Files and folders are identified by their full path (e.g. "main",
    # "Model/Combos/Action", "Controlers/Maps"). There are no integer IDs
    # for AI files or folders anymore.

    def get_ai_tree(self) -> dict:
        """[VERIFIED] Get the AI tree from the most recent farmer snapshot.

        Structure: {files: [...], folders: [...], bin: [...], leek_ais: {...}}
        Each file has: path, mtime, valid, version, strict, entrypoint,
                       total_lines, total_chars, scenario.
        Call refresh_farmer() to get a fresh snapshot.
        """
        if not self.farmer:
            raise APIError("Not authenticated — call login() first")
        return self.farmer.get("ai_tree", {}) or {}

    def refresh_farmer(self) -> dict:
        """[VERIFIED] Re-fetch the farmer snapshot (refreshes ai_tree)."""
        r = self.session.get(f"{self.BASE_URL}/farmer/get-from-token")
        data = self._handle_response(r, "refresh farmer")
        self.farmer = data.get("farmer", self.farmer)
        return self.farmer

    def list_ais(self) -> list[dict]:
        """[VERIFIED] List active AI file metadata (excludes bin)."""
        return list(self.get_ai_tree().get("files", []))

    def list_ai_folders(self) -> list[str]:
        """[VERIFIED] List folder paths."""
        return list(self.get_ai_tree().get("folders", []))

    def list_ai_bin(self) -> list[dict]:
        """[VERIFIED] List files in the bin (deleted but recoverable)."""
        return list(self.get_ai_tree().get("bin", []))

    def get_leek_ai_paths(self) -> dict:
        """[VERIFIED] Map of leek_id (int) -> assigned AI path (str)."""
        raw = self.get_ai_tree().get("leek_ais", {}) or {}
        return {int(k): v for k, v in raw.items()}

    def read_ai(self, path: str) -> str:
        """[VERIFIED] Read source code of an AI file by its path."""
        r = self.session.post(
            f"{self.BASE_URL}/ai/read",
            data={"path": path}
        )
        data = self._handle_response(r, f"read AI {path!r}")
        return data.get("code", "")

    def write_ai(self, path: str, code: str) -> dict:
        """[VERIFIED] Save source code to an AI file by path.

        Returns dict with 'result' (compile diagnostics) and 'modified' (mtime ms).
        """
        r = self.session.post(
            f"{self.BASE_URL}/ai/write",
            data={"path": path, "code": code}
        )
        return self._handle_response(r, f"write AI {path!r}")

    def create_ai(self, name: str, folder: str = "", version: int = 4) -> dict:
        """[VERIFIED] Create a new AI file.

        Args:
            name: File name (no path separators)
            folder: Parent folder path ("" for root, e.g. "Model/Combos")
            version: LeekScript version (default 4)

        Returns:
            Dict with 'path' and default 'code'.
        """
        r = self.session.post(
            f"{self.BASE_URL}/ai/create",
            data={"folder": folder, "name": name, "version": str(version)}
        )
        return self._handle_response(r, f"create AI {name!r} in {folder!r}")

    def rename_ai(self, path: str, new_name: str) -> dict:
        """[VERIFIED] Rename an AI file. Returns {'path': <new_full_path>}.

        `new_name` is a bare filename (no slash); the parent folder is
        preserved. Same-name renames fail with 'name_conflict'.
        """
        r = self.session.post(
            f"{self.BASE_URL}/ai/rename",
            data={"path": path, "new_name": new_name}
        )
        return self._handle_response(r, f"rename AI {path!r}")

    def move_ai(self, path: str, dest: str) -> dict:
        """[VERIFIED] Move an AI file to a different folder path.

        Use `dest=''` for root. `dest='/'` is rejected as invalid_path.
        Returns {'path': <new_full_path>}.
        """
        r = self.session.post(
            f"{self.BASE_URL}/ai/move",
            data={"path": path, "dest": dest}
        )
        return self._handle_response(r, f"move AI {path!r} -> {dest!r}")

    def delete_ai(self, path: str) -> dict:
        """[VERIFIED] Move an AI file to the bin. Returns {'trash_name': ...}."""
        r = self.session.delete(
            f"{self.BASE_URL}/ai/delete",
            json={"path": path}
        )
        return self._handle_response(r, f"delete AI {path!r}")

    def restore_ai(self, trash_name: str) -> dict:
        """[VERIFIED] Restore a file from the bin using its trash name.

        Returns {'path': <restored_path>}. The file returns to live tree and
        leaves the bin.
        """
        r = self.session.post(
            f"{self.BASE_URL}/ai/restore",
            data={"trash_name": trash_name}
        )
        return self._handle_response(r, f"restore AI {trash_name!r}")

    def empty_bin(self) -> list:
        """[VERIFIED] Permanently delete every file currently in the bin.

        No body required; returns []. This is irreversible — anything in the
        bin is gone after this call.
        """
        r = self.session.delete(f"{self.BASE_URL}/ai/bin")
        data = r.json()
        if isinstance(data, dict) and "error" in data:
            raise APIError(f"Failed to empty bin: {data.get('error')}")
        return data

    def create_folder(self, path: str) -> list:
        """[VERIFIED] Create an AI folder at the given full path.

        Returns an empty list `[]` on success (not a dict). Creates one level;
        the parent path must already exist.
        """
        r = self.session.post(
            f"{self.BASE_URL}/ai-folder/create",
            data={"path": path}
        )
        data = r.json()
        if isinstance(data, dict) and "error" in data:
            raise APIError(f"Failed to create folder {path!r}: {data.get('error')}")
        return data

    def rename_folder(self, path: str, new_name: str) -> dict:
        """[VERIFIED] Rename an AI folder. Returns {'path': <new_full_path>}."""
        r = self.session.post(
            f"{self.BASE_URL}/ai-folder/rename",
            data={"path": path, "new_name": new_name}
        )
        return self._handle_response(r, f"rename folder {path!r}")

    def delete_folder(self, path: str) -> dict:
        """[VERIFIED] Delete an AI folder (moves it to bin).

        Returns {'trash_name': <path>}. Folder must be empty — if a file was
        just moved out, wait ~1s before deleting to avoid sporadic
        'internal_error' responses from server-side race conditions.
        """
        r = self.session.delete(
            f"{self.BASE_URL}/ai-folder/delete",
            json={"path": path}
        )
        return self._handle_response(r, f"delete folder {path!r}")

    # =========================================================================
    # Test Scenarios
    # =========================================================================

    def get_test_scenarios(self) -> dict:
        """[VERIFIED] Get all test scenarios."""
        r = self.session.get(f"{self.BASE_URL}/test-scenario/get-all")
        return r.json()

    def start_test_fight(self, ai: "int | str", scenario_id: int = 0) -> int:
        """[VERIFIED] Start a test fight against Domingo (or custom scenario).

        Args:
            ai: The AI to test — path string (preferred, e.g. "main") or
                legacy integer ai_id (still accepted by the server).
            scenario_id: Scenario ID (0 for default Domingo scenario)

        Returns:
            Fight ID
        """
        r = self.session.post(
            f"{self.BASE_URL}/ai/test-scenario",
            data={"ai_id": ai, "scenario_id": scenario_id}
        )
        data = self._handle_response(r, "start test fight")
        return data["fight"]

    def create_test_scenario(self, name: str) -> dict:
        """[VERIFIED] Create a new test scenario. Returns {'id': <new_id>}."""
        r = self.session.post(
            f"{self.BASE_URL}/test-scenario/new",
            data={"name": name}
        )
        return self._handle_response(r, "create test scenario")

    def update_test_scenario(self, scenario_id: int, **fields) -> list:
        """[VERIFIED] Update test scenario settings. Returns [] on success.

        Keyword args go into the `data` JSON blob. Accepted keys include:
          type (int), map (int), seed (int), max_turns (int),
          turret_ai_team1 (path str), turret_ai_team2 (path str).
        """
        r = self.session.post(
            f"{self.BASE_URL}/test-scenario/update",
            data={"id": scenario_id, "data": json.dumps(fields)}
        )
        data = r.json()
        if isinstance(data, dict) and "error" in data:
            raise APIError(f"Failed to update test scenario: {data.get('error')}")
        return data

    def delete_test_scenario(self, scenario_id: int) -> list:
        """[VERIFIED] Delete a test scenario. Returns [] on success."""
        r = self.session.delete(
            f"{self.BASE_URL}/test-scenario/delete",
            json={"id": scenario_id}
        )
        data = r.json()
        if isinstance(data, dict) and "error" in data:
            raise APIError(f"Failed to delete test scenario: {data.get('error')}")
        return data

    def add_leek_to_scenario(
        self,
        scenario_id: int,
        leek_id: int,
        team: int,
        ai: "int | str"
    ) -> list:
        """[VERIFIED] Add a leek to a test scenario. Returns [] on success.

        Args:
            scenario_id: Scenario ID
            leek_id: Leek ID (positive for real leeks, negative for test leeks)
            team: 1 for team1, 2 for team2 (scenarios show team1/team2 separately)
            ai: AI path string (e.g. 'main'). Server accepts bare path or
                the built-in '/normal' for no custom AI.
        """
        r = self.session.post(
            f"{self.BASE_URL}/test-scenario/add-leek",
            data={
                "scenario_id": scenario_id,
                "leek": leek_id,
                "team": team,
                "ai": ai
            }
        )
        data = r.json()
        if isinstance(data, dict) and "error" in data:
            raise APIError(f"Failed to add leek to scenario: {data.get('error')}")
        return data

    def delete_leek_from_scenario(self, scenario_id: int, leek_id: int) -> list:
        """[VERIFIED] Remove a leek from a test scenario. Returns [] on success."""
        r = self.session.delete(
            f"{self.BASE_URL}/test-scenario/delete-leek",
            json={"scenario_id": scenario_id, "leek": leek_id}
        )
        data = r.json()
        if isinstance(data, dict) and "error" in data:
            raise APIError(f"Failed to delete leek from scenario: {data.get('error')}")
        return data

    def create_test_leek(self, name: str) -> dict:
        """[VERIFIED] Create a new test leek.

        Returns {'id': <negative_id>, 'data': {skin, level, life, strength,
        wisdom, agility, resistance, science, magic, frequency, cores, ram,
        tp, mp, chips, weapons, ...}}. Keep the `data` dict and pass it to
        update_test_leek to modify stats — the update endpoint rejects
        partial payloads.
        """
        r = self.session.post(
            f"{self.BASE_URL}/test-leek/new",
            data={"name": name}
        )
        return self._handle_response(r, "create test leek")

    def update_test_leek(self, leek_id: int, leek_data: dict) -> list:
        """[VERIFIED] Update a test leek's stats. Returns [] on success.

        IMPORTANT: `leek_data` must be the complete data blob — partial
        updates fail with 'missing_field'. Fetch the current blob from the
        create_test_leek response (or from get_test_scenarios().leeks) and
        merge your changes in.

        Args:
            leek_id: The test leek ID (negative number)
            leek_data: Full data dict (skin, level, life, all stats, chips, weapons).
        """
        r = self.session.post(
            f"{self.BASE_URL}/test-leek/update",
            data={"id": leek_id, "data": json.dumps(leek_data)}
        )
        data = r.json()
        if isinstance(data, dict) and "error" in data:
            raise APIError(f"Failed to update test leek: {data.get('error')}")
        return data

    def delete_test_leek(self, leek_id: int) -> list:
        """[VERIFIED] Delete a test leek. Returns [] on success."""
        r = self.session.delete(
            f"{self.BASE_URL}/test-leek/delete",
            json={"id": leek_id}
        )
        data = r.json()
        if isinstance(data, dict) and "error" in data:
            raise APIError(f"Failed to delete test leek: {data.get('error')}")
        return data

    # =========================================================================
    # Leek
    # =========================================================================

    def get_leek(self, leek_id: int) -> dict:
        """[VERIFIED] Get full leek data including stats and equipment.

        Equipment/stat changes are no longer done piecemeal — see the Loadout
        methods above and src/tools/loadout.py, which apply a whole build
        (weapons + chips + components + restat) in one native call.
        """
        r = self.session.get(f"{self.BASE_URL}/leek/get/{leek_id}")
        return self._handle_response(r, "get leek")

    # =========================================================================
    # Loadouts (équipements) — native build presets
    # =========================================================================
    # A loadout ("set") stores weapons, chips and a stat allocation that can be
    # applied to any leek in one call (optionally restatting). Identified by an
    # integer set_id. Notes discovered by round-trip probing:
    #   - stats{} values are CAPITAL points per characteristic (not the
    #     characteristic value). See src/tools/loadout.py for the conversion.
    #   - components are {index, template} objects (slot 0-7); apply() reinstalls
    #     them on the leek, so they MUST be included or the leek loses the
    #     cores/ram/stat hardware that supplies its extra slots.
    #   - illicit weapons (115-119) and some reward weapons (175, 225) cannot be
    #     stored; they are returned under forgotten_weapons and dropped.

    def get_loadouts(self) -> dict:
        """[VERIFIED] Get all loadouts plus owned weapon/chip template ids.

        Returns {loadouts: [{id, name, icon, weapons[], forgotten_weapons[],
        chips[], components[], stats{}, order}], owned_weapons[], owned_chips[]}.
        """
        r = self.session.get(f"{self.BASE_URL}/loadout/get-all")
        return self._handle_response(r, "get loadouts")

    def create_loadout(self, name: str, icon: "int | str", weapons: list,
                       chips: list, components: list, stats: dict) -> dict:
        """[VERIFIED] Create a loadout. Returns {'set': {...}}.

        weapons/chips/components are template-id lists; stats is a map of
        characteristic -> capital points. All are JSON-encoded in the body.
        """
        r = self.session.post(
            f"{self.BASE_URL}/loadout/create",
            data={
                "name": name, "icon": icon,
                "weapons": json.dumps(weapons),
                "chips": json.dumps(chips),
                "components": json.dumps(components),
                "stats": json.dumps(stats),
            }
        )
        return self._handle_response(r, f"create loadout {name!r}")

    def update_loadout(self, set_id: int, name: str, icon: "int | str",
                       weapons: list, chips: list, components: list,
                       stats: dict) -> dict:
        """[VERIFIED] Overwrite a loadout (HTTP PUT). Returns {'set': {...}}."""
        r = self.session.put(
            f"{self.BASE_URL}/loadout/update",
            data={
                "set_id": set_id, "name": name, "icon": icon,
                "weapons": json.dumps(weapons),
                "chips": json.dumps(chips),
                "components": json.dumps(components),
                "stats": json.dumps(stats),
            }
        )
        return self._handle_response(r, f"update loadout {set_id}")

    def delete_loadout(self, set_id: int) -> dict:
        """[VERIFIED] Delete a loadout by set_id (HTTP DELETE)."""
        r = self.session.delete(
            f"{self.BASE_URL}/loadout/delete",
            json={"set_id": set_id}
        )
        return self._handle_response(r, f"delete loadout {set_id}")

    def apply_loadout(self, set_id: int, leek_id: int, use_restat: bool = False) -> dict:
        """[VERIFIED] Apply a loadout to a leek (equip weapons/chips, and when
        use_restat is true, restat the leek to the loadout's stat allocation).

        This is the native replacement for build.py's manual strip/restat/
        re-equip. use_restat is required by the server; pass False to only swap
        gear, True to also reallocate capital (consumes a restat potion).
        """
        r = self.session.post(
            f"{self.BASE_URL}/loadout/apply",
            data={"set_id": set_id, "leek_id": leek_id,
                  "use_restat": "true" if use_restat else "false"}
        )
        return self._handle_response(r, f"apply loadout {set_id} to leek {leek_id}")

    # =========================================================================
    # Helpers
    # =========================================================================

    def _handle_response(self, response: requests.Response, action: str = "API call") -> dict:
        """
        Handle API response with consistent error handling.

        Args:
            response: The requests Response object
            action: Description of the action for error messages

        Returns:
            Parsed JSON response

        Raises:
            APIError: If the response contains an error
        """
        try:
            data = response.json()
        except json.JSONDecodeError as e:
            raise APIError(f"Invalid JSON response for {action}: {e}")

        if "error" in data:
            raise APIError(f"Failed to {action}: {data.get('error')}")

        return data
