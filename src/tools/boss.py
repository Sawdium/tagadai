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
GARDEN_BOSS_ATTACK = 71
GARDEN_BOSS_SQUAD_JOINED = 74
GARDEN_BOSS_SQUAD = 76
GARDEN_BOSS_NO_SUCH_SQUAD = 77
GARDEN_BOSS_STARTED = 78

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

    def _join_squad(self, squad_id: str, account: dict):
        """Connect a secondary account and join the squad."""
        login = account["login"]
        try:
            ws = websocket.create_connection(
                "wss://leekwars.com/ws",
                timeout=15,
                header=[f"Sec-WebSocket-Protocol: leek-wars, {account['token']}"],
            )
            print(f"  [{login}] WebSocket connected")
            ws.send(json.dumps([GARDEN_BOSS_JOIN_SQUAD, squad_id, account["leek_ids"]]))

            ws.settimeout(15)
            for _ in range(20):
                msg = ws.recv()
                data = json.loads(msg)
                if not isinstance(data, list) or len(data) < 1:
                    continue
                msg_id = data[0]
                if msg_id == GARDEN_BOSS_SQUAD_JOINED:
                    print(f"  [{login}] Joined squad")
                    break
                elif msg_id == GARDEN_BOSS_SQUAD:
                    pass  # Squad update
                elif msg_id == GARDEN_BOSS_STARTED:
                    break
                elif msg_id == GARDEN_BOSS_NO_SUCH_SQUAD:
                    print(f"  [{login}] Error: squad not found")
                    break
                else:
                    pass
            # Keep connection alive until fight starts
            try:
                for _ in range(20):
                    msg = ws.recv()
                    data = json.loads(msg)
                    if isinstance(data, list) and data[0] == GARDEN_BOSS_STARTED:
                        break
            except Exception:
                pass
            ws.close()
        except Exception as e:
            print(f"  [{login}] Error: {e}")

    def run(self):
        locked = len(self.extra_accounts) == 0
        ws = websocket.create_connection(
            "wss://leekwars.com/ws",
            timeout=15,
            header=[f"Sec-WebSocket-Protocol: leek-wars, {self.token}"],
        )
        print("  WebSocket connected")

        print(f"  Creating squad for {BOSS_NAMES.get(self.boss_id, f'Boss {self.boss_id}')}...")
        ws.send(json.dumps([GARDEN_BOSS_CREATE_SQUAD, self.boss_id, locked, self.leek_ids]))

        ws.settimeout(30)
        try:
            for _ in range(40):
                msg = ws.recv()
                data = json.loads(msg)
                if not isinstance(data, list) or len(data) < 1:
                    continue

                msg_id = data[0]
                payload = data[1] if len(data) > 1 else None

                if msg_id == GARDEN_BOSS_SQUAD:
                    pass

                elif msg_id == GARDEN_BOSS_SQUAD_JOINED:
                    squad_id = payload.get("id", "?") if isinstance(payload, dict) else "?"
                    print(f"  Squad joined (id={squad_id})")

                    if self.extra_accounts:
                        # Have extra accounts join the squad
                        join_threads = []
                        for account in self.extra_accounts:
                            t = threading.Thread(
                                target=self._join_squad,
                                args=(str(squad_id), account),
                            )
                            t.start()
                            join_threads.append(t)
                        # Wait for all join threads to confirm
                        for t in join_threads:
                            t.join(timeout=15)
                        # Clear so we don't re-join on subsequent SQUAD_JOINED messages
                        self.extra_accounts = []
                        # Drain any pending squad update messages from server
                        ws.settimeout(3)
                        try:
                            while True:
                                update = ws.recv()
                                udata = json.loads(update)
                                if isinstance(udata, list):
                                    print(f"  [squad update] msg {udata[0]}")
                        except websocket.WebSocketTimeoutException:
                            pass
                        ws.settimeout(30)

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
            ws.close()

        return self.fight_id


def main():
    parser = argparse.ArgumentParser(description="Launch a boss fight")
    parser.add_argument("--boss", type=int, default=1, choices=[1, 2, 3],
                        help="Boss ID: 1=Nasu, 2=Fennel, 3=Pumpkin (default: 1)")
    parser.add_argument("--leeks", type=str, default=None,
                        help="Comma-separated leek IDs (default: all leeks)")
    parser.add_argument("--wait", action="store_true",
                        help="Wait for fight result")
    parser.add_argument("--with", dest="with_accounts", type=str, default=None,
                        help="Extra account logins to join squad (comma-separated, same password)")
    args = parser.parse_args()

    # Login main account
    login, password = load_credentials()
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
    extra_accounts = []
    if args.with_accounts:
        for extra_login in args.with_accounts.split(","):
            extra_login = extra_login.strip()
            extra_api = LeekWarsAPI()
            extra_farmer = extra_api.login(extra_login, password)
            extra_leeks = extra_farmer.get("leeks", {})
            extra_leek_ids = [int(lid) for lid in extra_leeks.keys()]
            extra_leek_names = [l["name"] for l in extra_leeks.values()]
            print(f"  + {extra_login}: {', '.join(extra_leek_names)}")
            extra_accounts.append({
                "login": extra_login,
                "token": extra_api.token,
                "leek_ids": extra_leek_ids,
                "farmer_id": extra_farmer.get("id", 0),
            })

    print()

    # Launch boss fight
    fighter = BossFighter(token, args.boss, leek_ids, extra_accounts)
    fight_id = fighter.run()

    if fighter.error:
        print(f"\nERROR: {fighter.error}", file=sys.stderr)
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
