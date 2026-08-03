#!/usr/bin/env python3
"""
Boss Fight Tool - Create a boss squad and launch a boss fight via WebSocket.

Usage:
    python -m src.tools.boss                          # Nasu (boss 1), all leeks
    python -m src.tools.boss --boss 2                 # Fennel King
    python -m src.tools.boss --boss 3                 # Evil Pumpkin
    python -m src.tools.boss --leeks 128883,131291    # Only specific leeks
    python -m src.tools.boss --wait                   # Wait for fight result
    python -m src.tools.boss --with tagadanar          # Multi-account (same password)
    python -m src.tools.boss --with tagadanar,tagadalone  # Multiple extra accounts
    python -m src.tools.boss --join LaLongueTerre --as tagadanar  # Auto-join player's lobby
"""

import argparse
import json
import os
import sys
import time
import threading

import websocket

from src.common import LeekWarsAPI, load_credentials

# WebSocket message IDs (from leek-wars frontend source)
GARDEN_BOSS_CREATE_SQUAD = 66
GARDEN_BOSS_JOIN_SQUAD = 67
GARDEN_BOSS_ADD_LEEK = 68
GARDEN_BOSS_ATTACK = 71
GARDEN_BOSS_LISTEN = 72
GARDEN_BOSS_SQUADS = 73
GARDEN_BOSS_SQUAD_JOINED = 74
GARDEN_BOSS_SQUAD = 76
GARDEN_BOSS_NO_SUCH_SQUAD = 77
GARDEN_BOSS_STARTED = 78
GARDEN_BOSS_LEFT = 82
GARDEN_BOSS_LEAVE_SQUAD = 75

BOSS_NAMES = {1: "Nasu Samurai", 2: "Fennel King", 3: "Evil Pumpkin"}


class BossFighter:
    def __init__(self, token: str, boss_id: int, leek_ids: list[int],
                 extra_accounts: list[dict] | None = None):
        self.token = token
        self.boss_id = boss_id
        self.leek_ids = leek_ids
        self.extra_accounts = extra_accounts or []
        self.fight_id = None
        self.done = threading.Event()
        self.error = None

    def _join_squad(self, squad_id: str, account: dict, ready_event: threading.Event):
        """Connect a secondary account, join squad, add leeks, stay connected."""
        login = account["login"]
        ws = None
        try:
            ws = websocket.create_connection(
                "wss://leekwars.com/ws",
                timeout=30,
                header=[f"Sec-WebSocket-Protocol: leek-wars, {account['token']}"],
            )
            print(f"  [{login}] WebSocket connected")
            ws.send(json.dumps([GARDEN_BOSS_LEAVE_SQUAD]))
            time.sleep(0.3)
            ws.send(json.dumps([GARDEN_BOSS_JOIN_SQUAD, squad_id, account["leek_ids"]]))

            ws.settimeout(15)
            joined = False
            for _ in range(20):
                msg = ws.recv()
                data = json.loads(msg)
                if not isinstance(data, list) or len(data) < 1:
                    continue
                msg_id = data[0]
                if msg_id == GARDEN_BOSS_SQUAD_JOINED:
                    print(f"  [{login}] Joined squad")
                    for lid in account["leek_ids"]:
                        ws.send(json.dumps([GARDEN_BOSS_ADD_LEEK, lid]))
                        time.sleep(0.2)
                    print(f"  [{login}] Added {len(account['leek_ids'])} leeks")
                    joined = True
                    break
                elif msg_id == GARDEN_BOSS_NO_SUCH_SQUAD:
                    print(f"  [{login}] Error: squad not found")
                    break
                elif msg_id == GARDEN_BOSS_STARTED:
                    joined = True
                    break

            # Signal main thread that we're ready
            ready_event.set()

            if not joined:
                return

            # Keep WS alive until fight starts or main signals done
            ws.settimeout(2)
            while not self.done.is_set():
                try:
                    msg = ws.recv()
                    data = json.loads(msg)
                    if isinstance(data, list) and data[0] == GARDEN_BOSS_STARTED:
                        break
                except websocket.WebSocketTimeoutException:
                    continue
                except Exception:
                    break
        except Exception as e:
            print(f"  [{login}] Error: {e}")
            ready_event.set()  # Unblock main thread even on error
        finally:
            if ws:
                ws.close()

    def run(self):
        locked = len(self.extra_accounts) == 0
        # Connect inside the error path: a timeout here must feed the caller's
        # retry loop, not crash the process and lose the run.
        try:
            ws = websocket.create_connection(
                "wss://leekwars.com/ws",
                timeout=15,
                header=[f"Sec-WebSocket-Protocol: leek-wars, {self.token}"],
            )
        except Exception as e:
            self.error = f"Connect failed: {e}"
            print(f"  {self.error}")
            self.done.set()
            return None
        print("  WebSocket connected")

        try:
            # Leave any orphaned squad from a previous session
            ws.send(json.dumps([GARDEN_BOSS_LEAVE_SQUAD]))
            time.sleep(1)

            print(f"  Creating squad for {BOSS_NAMES.get(self.boss_id, f'Boss {self.boss_id}')}...")
            ws.send(json.dumps([GARDEN_BOSS_CREATE_SQUAD, self.boss_id, locked, self.leek_ids]))

            ws.settimeout(30)
            for _ in range(40):
                msg = ws.recv()
                data = json.loads(msg)
                if not isinstance(data, list) or len(data) < 1:
                    continue

                msg_id = data[0]
                payload = data[1] if len(data) > 1 else None

                if msg_id == GARDEN_BOSS_SQUAD:
                    if isinstance(payload, dict):
                        cnt = payload.get("engaged_count", "?")
                        print(f"  [squad] engaged_count={cnt}")

                elif msg_id == GARDEN_BOSS_SQUAD_JOINED:
                    squad_id = payload.get("id", "?") if isinstance(payload, dict) else "?"
                    print(f"  Squad joined (id={squad_id})")

                    if self.extra_accounts:
                        # Calculate expected total leeks
                        expected_count = len(self.leek_ids)
                        for acc in self.extra_accounts:
                            expected_count += len(acc["leek_ids"])

                        # Join accounts one at a time: lobby order = fight order,
                        # so parallel joins would randomize the leek play order.
                        for account in self.extra_accounts:
                            evt = threading.Event()
                            t = threading.Thread(
                                target=self._join_squad,
                                args=(str(squad_id), account, evt),
                                daemon=True,
                            )
                            t.start()
                            evt.wait(timeout=15)

                        self.extra_accounts = []

                        # Wait for server to confirm all leeks via engaged_count
                        engaged = 0
                        deadline = time.time() + 15
                        ws.settimeout(2)
                        while engaged < expected_count and time.time() < deadline:
                            try:
                                update = ws.recv()
                                udata = json.loads(update)
                                if isinstance(udata, list) and udata[0] == GARDEN_BOSS_SQUAD:
                                    upayload = udata[1] if len(udata) > 1 else {}
                                    if isinstance(upayload, dict):
                                        engaged = upayload.get("engaged_count", engaged)
                                        print(f"  [squad update] engaged_count={engaged}/{expected_count}")
                            except websocket.WebSocketTimeoutException:
                                continue
                        ws.settimeout(30)

                        if engaged < expected_count:
                            print(f"  WARNING: Only {engaged}/{expected_count} leeks in lobby! Aborting.")
                            ws.send(json.dumps([GARDEN_BOSS_LEAVE_SQUAD]))
                            self.error = f"Incomplete lobby: {engaged}/{expected_count} leeks"
                            break

                    print("  Launching attack...")
                    ws.send(json.dumps([GARDEN_BOSS_ATTACK]))

                elif msg_id == GARDEN_BOSS_STARTED:
                    if isinstance(payload, list) and len(payload) > 0:
                        self.fight_id = payload[0]
                    elif isinstance(payload, dict):
                        self.fight_id = payload.get("fight")
                    elif isinstance(payload, (int, float)):
                        self.fight_id = int(payload)
                    print(f"  Boss fight started! Fight ID: {self.fight_id}")
                    break

                elif msg_id == GARDEN_BOSS_NO_SUCH_SQUAD:
                    self.error = "No such squad"
                    print(f"  Error: {self.error}")
                    break

                else:
                    print(f"  [msg {msg_id}] {json.dumps(payload, default=str)[:200] if payload else ''}")

        except websocket.WebSocketTimeoutException:
            self.error = "Timeout waiting for response"
        except Exception as e:
            self.error = str(e)
        finally:
            self.done.set()  # Signal join threads to exit
            ws.close()

        return self.fight_id


class BossWatcher:
    """Watch for a specific player's boss lobby and auto-join with an account."""

    def __init__(self, token: str, leek_ids: list[int], target_farmer: str, boss_id: int):
        self.token = token
        self.leek_ids = leek_ids
        self.target_farmer = target_farmer.lower()
        self.boss_id = boss_id

    def run(self):
        while True:
            fight_id = self._watch_once()
            if fight_id:
                print(f"\nFight #{fight_id}: https://leekwars.com/fight/{fight_id}")
            print(f"\nWaiting for next {self.target_farmer} lobby...\n")
            time.sleep(2)

    def _watch_once(self):
        ws = websocket.create_connection(
            "wss://leekwars.com/ws",
            timeout=15,
            header=[f"Sec-WebSocket-Protocol: leek-wars, {self.token}"],
        )
        print("  WebSocket connected, listening for squads...")
        ws.send(json.dumps([GARDEN_BOSS_LISTEN]))

        fight_id = None
        joined = False
        joined_squad_id = None
        try:
            ws.settimeout(5)
            while True:
                try:
                    msg = ws.recv()
                except websocket.WebSocketTimeoutException:
                    continue
                data = json.loads(msg)
                if not isinstance(data, list) or len(data) < 1:
                    continue
                msg_id = data[0]
                payload = data[1] if len(data) > 1 else None

                if msg_id == GARDEN_BOSS_SQUADS:
                    # payload is a dict keyed by boss ID: {"1": [...], "2": [...], "3": [...]}
                    if not isinstance(payload, dict):
                        continue
                    squads = payload.get(str(self.boss_id), [])
                    if not isinstance(squads, list):
                        squads = []

                    if joined:
                        # Check if our squad is still there, if not we got kicked/dissolved
                        still_there = any(
                            isinstance(s, dict) and s.get("id") == joined_squad_id
                            for s in squads
                        )
                        if not still_there:
                            print(f"  Squad {joined_squad_id} gone, back to listening...")
                            joined = False
                            joined_squad_id = None
                        continue

                    for squad in squads:
                        if not isinstance(squad, dict):
                            continue
                        farmers = squad.get("farmers", [])
                        farmer_names = [f.get("name", "").lower() if isinstance(f, dict) else ""
                                        for f in farmers]
                        if self.target_farmer in farmer_names:
                            joined_squad_id = squad.get("id")
                            print(f"  Found {self.target_farmer}'s squad (id={joined_squad_id})! Joining...")
                            ws.send(json.dumps([GARDEN_BOSS_JOIN_SQUAD, joined_squad_id, self.leek_ids]))
                            joined = True
                            break

                elif msg_id == GARDEN_BOSS_SQUAD_JOINED:
                    print(f"  Joined squad!")
                    for lid in self.leek_ids:
                        ws.send(json.dumps([GARDEN_BOSS_ADD_LEEK, lid]))
                    print(f"  Added {len(self.leek_ids)} leeks")

                elif msg_id == GARDEN_BOSS_STARTED:
                    if isinstance(payload, list) and len(payload) > 0:
                        fight_id = payload[0]
                    elif isinstance(payload, dict):
                        fight_id = payload.get("fight")
                    elif isinstance(payload, (int, float)):
                        fight_id = int(payload)
                    print(f"  Boss fight started! Fight ID: {fight_id}")
                    break

                elif msg_id in (GARDEN_BOSS_NO_SUCH_SQUAD, GARDEN_BOSS_LEFT):
                    print(f"  Squad gone/left, back to listening...")
                    joined = False
                    joined_squad_id = None

                elif msg_id == GARDEN_BOSS_SQUAD:
                    if joined and isinstance(payload, dict):
                        cnt = payload.get("engaged_count", "?")
                        print(f"  [squad update] engaged_count={cnt}")

        except Exception as e:
            print(f"  Connection error: {e}")
        finally:
            ws.close()

        return fight_id


def main():
    parser = argparse.ArgumentParser(description="Launch a boss fight")
    parser.add_argument("--boss", type=int, default=1, choices=[1, 2, 3],
                        help="Boss ID: 1=Nasu, 2=Fennel, 3=Pumpkin (default: 1)")
    parser.add_argument("--leeks", type=str, default=None,
                        help="Comma-separated leek IDs (default: all leeks)")
    parser.add_argument("--wait", action="store_true",
                        help="Wait for fight result")
    parser.add_argument("--with", dest="with_accounts", type=str, default=None,
                        help="Extra account logins (comma-sep, same pw). Use account:N to limit leeks")
    parser.add_argument("--join", type=str, default=None,
                        help="Watch for this player's lobby and auto-join")
    parser.add_argument("--as", dest="as_account", type=str, default=None,
                        help="Account to join with (used with --join, same password)")
    args = parser.parse_args()

    # Login main account (or --as account for --join mode)
    login, password = load_credentials()

    if args.join:
        join_login = args.as_account or login
        api = LeekWarsAPI()
        farmer = api.login(join_login, password)
        token = api.token
        print(f"Logged in as {farmer.get('login', '?')}")

        all_leeks = farmer.get("leeks", {})
        if args.leeks:
            leek_ids = [int(x) for x in args.leeks.split(",")]
        else:
            leek_ids = [int(lid) for lid in all_leeks.keys()]
        leek_names = [all_leeks.get(str(lid), {}).get("name", f"#{lid}") for lid in leek_ids]

        boss_name = BOSS_NAMES.get(args.boss, f"Boss {args.boss}")
        print(f"Boss: {boss_name}")
        print(f"Leeks ({len(leek_ids)}): {', '.join(leek_names)}")
        print(f"Watching for: {args.join}")
        print()

        watcher = BossWatcher(token, leek_ids, args.join, args.boss)
        watcher.run()
        return

    api = LeekWarsAPI()
    farmer = api.login(login, password)
    token = api.token

    print(f"Logged in as {farmer.get('login', '?')}")

    # Get leeks
    all_leeks = farmer.get("leeks", {})
    if args.leeks:
        leek_ids = [int(x) for x in args.leeks.split(",")]
        leek_names = [all_leeks.get(str(lid), {}).get("name", f"#{lid}") for lid in leek_ids]
    else:
        leek_ids = [int(lid) for lid in all_leeks.keys()]
        leek_names = [l["name"] for l in all_leeks.values()]

    boss_name = BOSS_NAMES.get(args.boss, f"Boss {args.boss}")
    print(f"Boss: {boss_name}")
    print(f"Leeks ({len(leek_ids)}): {', '.join(leek_names)}")

    # Login extra accounts
    # Syntax: "account" or "account:N" to limit to N leeks
    extra_accounts = []
    if args.with_accounts:
        for entry in args.with_accounts.split(","):
            entry = entry.strip()
            if ":" in entry:
                extra_login, max_str = entry.rsplit(":", 1)
                max_leeks = int(max_str)
            else:
                extra_login = entry
                max_leeks = None
            extra_api = LeekWarsAPI()
            extra_farmer = extra_api.login(extra_login, password)
            extra_leeks = extra_farmer.get("leeks", {})
            extra_leek_ids = [int(lid) for lid in extra_leeks.keys()]
            extra_leek_names = [l["name"] for l in extra_leeks.values()]
            if max_leeks is not None and max_leeks < len(extra_leek_ids):
                extra_leek_ids = extra_leek_ids[:max_leeks]
                extra_leek_names = extra_leek_names[:max_leeks]
            print(f"  + {extra_login}: {', '.join(extra_leek_names)}")
            extra_accounts.append({
                "login": extra_login,
                "token": extra_api.token,
                "leek_ids": extra_leek_ids,
                "farmer_id": extra_farmer.get("id", 0),
            })

    print()

    # Launch boss fight (with retry on connection drop)
    max_retries = 5
    for attempt in range(max_retries):
        fighter = BossFighter(token, args.boss, leek_ids, list(extra_accounts))
        fight_id = fighter.run()

        if not fighter.error:
            break
        if attempt < max_retries - 1:
            print(f"\n  Attempt {attempt + 1} failed: {fighter.error}. Retrying in 3s...",
                  file=sys.stderr)
            time.sleep(3)
        else:
            print(f"\nERROR: {fighter.error} (after {max_retries} attempts)", file=sys.stderr)
            sys.exit(1)

    if fight_id:
        print(f"\nFight #{fight_id}: https://leekwars.com/fight/{fight_id}")

        if args.wait:
            print("Waiting for fight result...")
            from src.tools.fight import wait_for_fight, fetch_fight_logs
            from src.common.fight_parser import parse_fight, format_summary

            result = wait_for_fight(api, fight_id)
            api_logs = fetch_fight_logs(api, fight_id)
            summary = parse_fight(result, farmer.get("id", 0), api_logs=api_logs)
            print(format_summary(summary))
    else:
        print("\nNo fight ID received", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
