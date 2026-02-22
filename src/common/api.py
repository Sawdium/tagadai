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
    ai_code = api.get_ai(ai_id)
"""

import json
import requests
from typing import Optional

from .errors import APIError, AuthenticationError


class LeekWarsAPI:
    """
    Unified API client for LeekWars.

    Combines all API functionality:
    - Authentication (login)
    - Garden operations (opponents, fights)
    - AI management (list, get, save, create, rename, delete)
    - Test scenarios (create, update, delete, manage leeks)
    - Fight retrieval and logs
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
        """
        Authenticate with LeekWars.

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
        """Get garden state (includes compositions)."""
        r = self.session.get(f"{self.BASE_URL}/garden/get")
        return self._handle_response(r)

    def get_leek_opponents(self, leek_id: int) -> list:
        """Get opponents for solo fights."""
        r = self.session.get(f"{self.BASE_URL}/garden/get-leek-opponents/{leek_id}")
        data = self._handle_response(r)
        return data.get("opponents", [])

    def get_farmer_opponents(self) -> list:
        """Get opponents for farmer fights."""
        r = self.session.get(f"{self.BASE_URL}/garden/get-farmer-opponents")
        data = self._handle_response(r)
        return data.get("opponents", [])

    def start_solo_fight(self, leek_id: int, enemy_id: int) -> int:
        """
        Start a solo fight.

        Returns:
            Fight ID
        """
        r = self.session.post(f"{self.BASE_URL}/garden/start-solo-fight/{leek_id}/{enemy_id}")
        data = self._handle_response(r, "start fight")
        return data["fight"]

    def start_farmer_fight(self, enemy_id: int) -> int:
        """
        Start a farmer fight.

        Returns:
            Fight ID
        """
        r = self.session.post(f"{self.BASE_URL}/garden/start-farmer-fight/{enemy_id}")
        data = self._handle_response(r, "start fight")
        return data["fight"]

    def get_fight(self, fight_id: int, with_logs: bool = True) -> dict:
        """
        Get fight data.

        Args:
            fight_id: The fight ID
            with_logs: Include debug logs in response

        Returns:
            Fight data dict
        """
        url = f"{self.BASE_URL}/fight/get/{fight_id}"
        if with_logs:
            url += "?logs=true"
        r = self.session.get(url)
        return r.json()

    def get_fight_logs(self, fight_id: int) -> dict:
        """
        Get debug logs for a fight (separate endpoint).

        Returns logs indexed by farmer and action, containing debug(), debugW(), debugE() output.
        """
        r = self.session.get(f"{self.BASE_URL}/fight/get-logs/{fight_id}")
        return r.json()

    # =========================================================================
    # AI Management
    # =========================================================================

    def get_farmer_ais(self) -> dict:
        """Get all AI files and folders for the farmer."""
        r = self.session.get(f"{self.BASE_URL}/ai/get-farmer-ais")
        return r.json()

    def get_ai(self, ai_id: int) -> dict:
        """
        Get AI details including code.

        Returns:
            Dict with 'ai' key containing AI data
        """
        r = self.session.get(f"{self.BASE_URL}/ai/get/{ai_id}")
        return self._handle_response(r, "get AI")

    def save_ai(self, ai_id: int, code: str) -> dict:
        """Save code to an AI file."""
        r = self.session.post(
            f"{self.BASE_URL}/ai/save",
            data={"ai_id": ai_id, "code": code}
        )
        return self._handle_response(r, "save AI")

    def create_ai(self, name: str, folder_id: int = 0, version: int = 4) -> dict:
        """
        Create a new AI file.

        Args:
            name: AI file name
            folder_id: Parent folder ID (0 for root)
            version: LeekScript version (default: 4)

        Returns:
            Dict with 'id' and 'name'
        """
        r = self.session.post(
            f"{self.BASE_URL}/ai/new-name",
            data={"folder_id": folder_id, "version": str(version), "name": name}
        )
        data = self._handle_response(r, "create AI")
        return {"id": data["ai"]["id"], "name": name}

    def rename_ai(self, ai_id: int, name: str) -> dict:
        """Rename an AI file."""
        r = self.session.post(
            f"{self.BASE_URL}/ai/rename",
            data={"ai_id": ai_id, "new_name": name}
        )
        return self._handle_response(r, "rename AI")

    def delete_ai(self, ai_id: int) -> dict:
        """Delete an AI file."""
        r = self.session.delete(
            f"{self.BASE_URL}/ai/delete",
            json={"ai_id": ai_id}
        )
        return self._handle_response(r, "delete AI")

    def move_ai(self, ai_id: int, folder_id: int) -> dict:
        """
        Move an AI file to a different folder.

        Args:
            ai_id: AI file ID
            folder_id: Target folder ID (0 for root)

        Returns:
            Empty dict on success
        """
        r = self.session.post(
            f"{self.BASE_URL}/ai/change-folder",
            data={"ai_id": ai_id, "folder_id": folder_id}
        )
        # This endpoint returns [] on success, not a dict
        return {"success": True}

    def create_folder(self, name: str, parent_id: int = 0) -> dict:
        """
        Create a new AI folder.

        Returns:
            Dict with 'id' and 'name'
        """
        r = self.session.post(
            f"{self.BASE_URL}/ai-folder/new/{parent_id}",
            data={"folder_id": parent_id}
        )
        data = self._handle_response(r, "create folder")
        folder_id = data["id"]

        # Rename it
        self.session.post(
            f"{self.BASE_URL}/ai-folder/rename/{folder_id}/{name}",
            data={"folder_id": folder_id, "new_name": name}
        )

        return {"id": folder_id, "name": name}

    # =========================================================================
    # Test Scenarios
    # =========================================================================

    def get_test_scenarios(self) -> dict:
        """Get all test scenarios."""
        r = self.session.get(f"{self.BASE_URL}/test-scenario/get-all")
        return r.json()

    def start_test_fight(self, ai_id: int, scenario_id: int = 0) -> int:
        """
        Start a test fight against Domingo (or custom scenario).

        Args:
            ai_id: The AI to test
            scenario_id: Scenario ID (0 for default Domingo scenario)

        Returns:
            Fight ID
        """
        r = self.session.post(
            f"{self.BASE_URL}/ai/test-scenario",
            data={"ai_id": ai_id, "scenario_id": scenario_id}
        )
        data = self._handle_response(r, "start test fight")
        return data["fight"]

    def create_test_scenario(self, name: str) -> dict:
        """Create a new test scenario."""
        r = self.session.post(
            f"{self.BASE_URL}/test-scenario/new",
            data={"name": name}
        )
        return r.json()

    def update_test_scenario(
        self,
        scenario_id: int,
        scenario_type: int = 0,
        map_id: int = 0,
        seed: int = 0
    ) -> dict:
        """Update test scenario settings."""
        r = self.session.post(
            f"{self.BASE_URL}/test-scenario/update",
            data={
                "scenario_id": scenario_id,
                "type": scenario_type,
                "map": map_id,
                "seed": seed
            }
        )
        return r.json()

    def delete_test_scenario(self, scenario_id: int) -> dict:
        """Delete a test scenario."""
        r = self.session.delete(
            f"{self.BASE_URL}/test-scenario/delete",
            json={"scenario_id": scenario_id}
        )
        return r.json()

    def add_leek_to_scenario(
        self,
        scenario_id: int,
        leek_id: int,
        team: int,
        ai_id: int
    ) -> dict:
        """
        Add a leek to a test scenario.

        Args:
            scenario_id: Scenario ID
            leek_id: Leek ID
            team: 0 for team1, 1 for team2
            ai_id: AI to use for this leek
        """
        r = self.session.post(
            f"{self.BASE_URL}/test-scenario/add-leek",
            data={
                "scenario_id": scenario_id,
                "leek": leek_id,
                "team": team,
                "ai": ai_id
            }
        )
        return r.json()

    def delete_leek_from_scenario(self, scenario_id: int, leek_id: int) -> dict:
        """Remove a leek from a test scenario."""
        r = self.session.delete(
            f"{self.BASE_URL}/test-scenario/delete-leek",
            json={"scenario_id": scenario_id, "leek": leek_id}
        )
        return r.json()

    def create_test_leek(self, name: str) -> dict:
        """Create a new test leek."""
        r = self.session.post(
            f"{self.BASE_URL}/test-leek/new",
            data={"name": name}
        )
        return r.json()

    def update_test_leek(self, leek_id: int, leek_data: dict) -> dict:
        """
        Update a test leek's stats.

        Args:
            leek_id: The test leek ID (negative number)
            leek_data: Dict with leek properties (level, life, strength, etc.)
        """
        r = self.session.post(
            f"{self.BASE_URL}/test-leek/update",
            data={"id": leek_id, "data": json.dumps(leek_data)}
        )
        return r.json()

    def delete_test_leek(self, leek_id: int) -> dict:
        """Delete a test leek."""
        r = self.session.delete(
            f"{self.BASE_URL}/test-leek/delete",
            json={"leek_id": leek_id}
        )
        return r.json()

    # =========================================================================
    # Leek Equipment & Build Management
    # =========================================================================

    def get_leek(self, leek_id: int) -> dict:
        """Get full leek data including stats and equipment."""
        r = self.session.get(f"{self.BASE_URL}/leek/get/{leek_id}")
        return self._handle_response(r, "get leek")

    def add_weapon(self, leek_id: int, weapon_id: int) -> dict:
        """Equip a weapon on a leek."""
        r = self.session.post(
            f"{self.BASE_URL}/leek/add-weapon",
            data={"leek_id": leek_id, "weapon_id": weapon_id}
        )
        return self._handle_response(r, "add weapon")

    def remove_weapon(self, weapon_id: int) -> dict:
        """Unequip a weapon from a leek."""
        r = self.session.delete(
            f"{self.BASE_URL}/leek/remove-weapon",
            json={"weapon_id": weapon_id}
        )
        return self._handle_response(r, "remove weapon")

    def add_chip(self, leek_id: int, chip_id: int) -> dict:
        """Equip a chip on a leek."""
        r = self.session.post(
            f"{self.BASE_URL}/leek/add-chip",
            data={"leek_id": leek_id, "chip_id": chip_id}
        )
        return self._handle_response(r, "add chip")

    def remove_chip(self, chip_id: int) -> dict:
        """Unequip a chip from a leek."""
        r = self.session.delete(
            f"{self.BASE_URL}/leek/remove-chip",
            json={"chip_id": chip_id}
        )
        return self._handle_response(r, "remove chip")

    def add_component(self, leek_id: int, component_id: int, index: int = 0) -> dict:
        """Equip a component on a leek at a given slot index."""
        r = self.session.post(
            f"{self.BASE_URL}/leek/add-component",
            data={"leek_id": leek_id, "component_id": component_id, "index": index}
        )
        return self._handle_response(r, "add component")

    def remove_component(self, component_id: int) -> dict:
        """Unequip a component from a leek."""
        r = self.session.delete(
            f"{self.BASE_URL}/leek/remove-component",
            json={"component_id": component_id}
        )
        return self._handle_response(r, "remove component")

    def use_potion(self, leek_id: int, potion_id: int) -> dict:
        """Use a potion on a leek (e.g. restat potion)."""
        r = self.session.post(
            f"{self.BASE_URL}/leek/use-potion",
            data={"leek_id": leek_id, "potion_id": potion_id}
        )
        return self._handle_response(r, "use potion")

    def spend_capital(self, leek_id: int, characteristics: dict) -> dict:
        """
        Spend capital points on leek stats.

        Args:
            leek_id: The leek ID
            characteristics: Dict of stat -> bonus points to add (e.g. {"life": 1000, "strength": 350})
        """
        r = self.session.post(
            f"{self.BASE_URL}/leek/spend-capital",
            data={"leek_id": leek_id, "characteristics": json.dumps(characteristics)}
        )
        return self._handle_response(r, "spend capital")

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
