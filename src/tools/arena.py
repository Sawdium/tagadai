#!/usr/bin/env python3
"""
Arena Tool - Auto-join the LeekWars arena (battle royale room) via WebSocket.

The arena is an always-open room: once 10+ leeks are registered, a 20s
countdown starts and the fight auto-launches. Registration is tied to the
WebSocket connection, so this tool stays connected while registered.

Usage:
    python -m src.tools.arena                                # First leek, no mode vote
    python -m src.tools.arena --type chest                   # Vote chest hunt mode
    python -m src.tools.arena --account tagadagain --type chest  # gloomy autojoins chest hunt
    python -m src.tools.arena --leek gloomy                  # Pick leek by name (or ID)
    python -m src.tools.arena --once                         # Exit after one fight
    python -m src.tools.arena --colossus                     # Willing to join colossus fights
"""

import argparse
import json
import sys
import time

import websocket

from src.common import LeekWarsAPI, load_credentials

# WebSocket message IDs (from leek-wars frontend src/model/socket.ts)
ARENA_REGISTER = 28
ARENA_UPDATE = 29
ARENA_START = 30
ARENA_LEAVE = 31
ARENA_CHAT_NOTIF = 32
PONG = 33
WRONG_TOKEN = 57
CONNECTED_COUNT = 91

MAX_PLAYERS = 20

# Mode vote (from leek-wars frontend src/model/arena.ts ARENA_MODE_LABELS)
ARENA_TYPES = {"any": -1, "br": 0, "war": 1, "chest": 2, "colossus": 3}
TYPE_NAMES = {v: k for k, v in ARENA_TYPES.items()}

# NOTE: do NOT send the frontend's app-level PING [90] — the production server
# closes the connection on it. Protocol-level WS pings are used instead.
PING_INTERVAL = 50  # seconds


class ArenaSession:
    """One WebSocket session: register a leek, wait until a fight starts."""

    def __init__(self, token: str, leek_id: int, preference: int, colossus: bool):
        self.token = token
        self.leek_id = leek_id
        self.preference = preference
        self.colossus = colossus
        self.fight_id = None
        self.ws = None

    def _register(self):
        self.ws.send(json.dumps(
            [ARENA_REGISTER, self.leek_id, self.preference, self.colossus]))

    def leave(self):
        try:
            if self.ws:
                self.ws.send(json.dumps([ARENA_LEAVE]))
        except Exception:
            pass

    def run(self):
        """Connect, register, and block until a fight starts or the socket dies.

        Returns the fight ID, or None on connection loss (caller reconnects).
        """
        self.ws = websocket.create_connection(
            "wss://leekwars.com/ws",
            timeout=15,
            header=[f"Sec-WebSocket-Protocol: leek-wars, {self.token}"],
        )
        print("  WebSocket connected, registering in arena...")
        # Clear any stale registration from a previous session first
        self.ws.send(json.dumps([ARENA_LEAVE]))
        time.sleep(0.3)
        self._register()

        last_progress = -1
        last_countdown = -2
        last_ping = time.time()
        self.ws.settimeout(2)
        try:
            while True:
                if time.time() - last_ping > PING_INTERVAL:
                    self.ws.ping()
                    last_ping = time.time()
                try:
                    msg = self.ws.recv()
                except websocket.WebSocketTimeoutException:
                    continue

                data = json.loads(msg)
                if not isinstance(data, list) or len(data) < 1:
                    continue
                msg_id = data[0]
                payload = data[1] if len(data) > 1 else None

                if msg_id == ARENA_UPDATE:
                    # payload = [progress, countdown, {leek_id: leek}]
                    if not isinstance(payload, list):
                        continue
                    progress = payload[0] if len(payload) > 0 else 0
                    countdown = payload[1] if len(payload) > 1 else -1
                    if progress != last_progress or countdown != last_countdown:
                        status = f"  [arena] {progress}/{MAX_PLAYERS} leeks"
                        if isinstance(countdown, (int, float)) and countdown >= 0:
                            status += f" — launching in {countdown}s"
                        print(status)
                        last_progress = progress
                        last_countdown = countdown

                elif msg_id == ARENA_START:
                    # payload = [fight_id, garden_flag]
                    if isinstance(payload, list) and len(payload) > 0:
                        self.fight_id = payload[0]
                    elif isinstance(payload, (int, float)):
                        self.fight_id = int(payload)
                    print(f"  Arena fight started! Fight ID: {self.fight_id}")
                    return self.fight_id

                elif msg_id == ARENA_LEAVE:
                    # Server dropped our registration — re-register
                    print("  [arena] Removed from room, re-registering...")
                    self._register()

                elif msg_id == WRONG_TOKEN:
                    print("  Token expired, reconnecting...")
                    return None

                elif msg_id in (PONG, ARENA_CHAT_NOTIF, CONNECTED_COUNT):
                    continue

        finally:
            try:
                self.ws.close()
            except Exception:
                pass

        return None


def resolve_leek(farmer: dict, leek_arg: str | None) -> tuple[int, str]:
    """Resolve --leek (name or ID) to (id, name). Default: first leek."""
    leeks = farmer.get("leeks", {})
    if not leeks:
        raise SystemExit("ERROR: account has no leeks")
    if leek_arg is None:
        lid = next(iter(leeks))
        return int(lid), leeks[lid].get("name", f"#{lid}")
    for lid, leek in leeks.items():
        if leek.get("name", "").lower() == leek_arg.lower() or str(lid) == leek_arg:
            return int(lid), leek.get("name", f"#{lid}")
    names = ", ".join(l.get("name", "?") for l in leeks.values())
    raise SystemExit(f"ERROR: leek '{leek_arg}' not found. Have: {names}")


def main():
    parser = argparse.ArgumentParser(description="Auto-join the LeekWars arena")
    parser.add_argument("--account", help="Override LEEKWARS_LOGIN (password from .env)")
    parser.add_argument("--leek", help="Leek name or ID (default: first leek)")
    parser.add_argument("--type", dest="arena_type", default="any",
                        choices=sorted(ARENA_TYPES),
                        help="Arena mode vote: br, war, chest, colossus, any (default: any)")
    parser.add_argument("--colossus", action="store_true",
                        help="Willing to join colossus fights")
    parser.add_argument("--once", action="store_true",
                        help="Exit after the first fight (default: re-register forever)")
    args = parser.parse_args()

    login, password = load_credentials()
    if args.account:
        login = args.account

    preference = ARENA_TYPES[args.arena_type]

    while True:
        api = LeekWarsAPI()
        farmer = api.login(login, password)
        leek_id, leek_name = resolve_leek(farmer, args.leek)

        print(f"Logged in as {farmer.get('login', '?')}")
        print(f"Leek: {leek_name} (#{leek_id})")
        print(f"Mode vote: {args.arena_type}"
              + (" (+colossus)" if args.colossus else ""))
        print()

        session = ArenaSession(api.token, leek_id, preference, args.colossus)
        try:
            fight_id = session.run()
        except KeyboardInterrupt:
            print("\n  Leaving arena...")
            session.leave()
            time.sleep(0.5)
            return
        except Exception as e:
            print(f"  Connection error: {e}", file=sys.stderr)
            fight_id = None

        if fight_id:
            print(f"\nFight #{fight_id}: https://leekwars.com/fight/{fight_id}")
            if args.once:
                return
            print("\nRe-registering for next arena...\n")
            time.sleep(3)
        else:
            print("  Reconnecting in 5s...")
            time.sleep(5)


if __name__ == "__main__":
    main()
