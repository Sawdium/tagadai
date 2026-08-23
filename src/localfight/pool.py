"""
Multi-account leek pool for local fights.

The owner's leeks are spread over three LeekWars accounts that share one
password, so any benchmark that wants a *panel* of opponents (rather than one
leek cloned onto both teams) has to log into more than one account. This module
hides that: a leek is named `account:Name` — or just `Name` for the default
account from `.env` — and the pool logs in lazily, caches the session, and
caches each leek's live build so a 40-seed run does not hammer `/leek/get`.

    pool = LeekPool()
    ref = pool.resolve("tagadagain:JCGloomy")
    entity = pool.entity(ref, team=1, ai="tagadalive/main")

Cores are pinned explicitly here rather than left to whatever the scenario
default is: the generator's op budget is `cores * 1_000_000` (EntityAI.java),
`EntityInfo.cores` defaults to 0 when the key is absent, and this owner's leeks
run 15 to 22 cores. Benchmarking an AI with the wrong budget silently measures
a different, weaker agent, so `entity()` asserts the value it emits.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from src.common import LeekWarsAPI, load_credentials
from src.common.errors import TagadAIError
from src.tools.localfight import build_entity

# Aliases that mean "whatever LEEKWARS_LOGIN says".
DEFAULT_ALIASES = {"", "default", "tagadai", "-"}

# Leeks known to live off the default account, so `--leek JCGloomy` can find
# them without the user having to remember which login owns what. Purely a
# convenience: an explicit `account:Name` always wins.
KNOWN_ACCOUNTS = {
    "jcgloomy": "tagadagain",
    "rebeccasyphilis": "tagadagain",
    "kellogs": "tagadagain",
    "kevintoucourt": "tagadagain",
    "twogether": "tagadalone",
    "4lone": "tagadalone",
}


@dataclass(frozen=True)
class LeekRef:
    """A leek identified by the account that owns it."""

    account: str
    id: int
    name: str

    def __str__(self) -> str:
        return f"{self.account}:{self.name}"


@dataclass
class LeekPool:
    """Lazily-authenticated, cached access to leeks across several accounts."""

    default_login: str = ""
    password: str = ""
    _apis: dict[str, LeekWarsAPI] = field(default_factory=dict, init=False)
    _leeks: dict[str, list[dict]] = field(default_factory=dict, init=False)
    _entities: dict[tuple[str, int], dict] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        login, password = load_credentials()
        self.default_login = self.default_login or login
        self.password = self.password or password

    # -- accounts ---------------------------------------------------------

    def _login_for(self, account: str) -> str:
        return self.default_login if account.lower() in DEFAULT_ALIASES else account

    def api(self, account: str) -> LeekWarsAPI:
        login = self._login_for(account)
        api = self._apis.get(login)
        if api is None:
            api = LeekWarsAPI()
            api.login(login, self.password)
            self._apis[login] = api
        return api

    def leeks(self, account: str) -> list[dict]:
        login = self._login_for(account)
        if login not in self._leeks:
            self._leeks[login] = list(self.api(account).refresh_farmer()["leeks"].values())
        return self._leeks[login]

    # -- resolution -------------------------------------------------------

    def resolve(self, spec: str) -> LeekRef:
        """`account:Name`, `account:id`, `Name` or `id` -> a LeekRef.

        A bare name is looked up on the default account first, then on the
        account KNOWN_ACCOUNTS points at, so the historical single-account
        usage keeps working unchanged.
        """
        account, sep, wanted = spec.rpartition(":")
        if not wanted:
            raise TagadAIError(f"Empty leek spec {spec!r}")

        candidates = [account] if sep else self._candidate_accounts(wanted)
        tried = []
        for acct in candidates:
            for leek in self.leeks(acct):
                if str(leek["id"]) == wanted or leek["name"].lower() == wanted.lower():
                    return LeekRef(self._login_for(acct), int(leek["id"]), leek["name"])
            tried.append(self._login_for(acct))

        known = ", ".join(
            f"{self._login_for(a)}:{l['name']}" for a in tried for l in self.leeks(a)
        )
        raise TagadAIError(f"No leek {wanted!r} on {' or '.join(tried)}. Available: {known}")

    def _candidate_accounts(self, wanted: str) -> list[str]:
        hint = KNOWN_ACCOUNTS.get(wanted.lower())
        return ["", hint] if hint else [""]

    def first(self, account: str = "") -> LeekRef:
        leeks = self.leeks(account)
        if not leeks:
            raise TagadAIError(f"Account {self._login_for(account)} has no leeks")
        return LeekRef(self._login_for(account), int(leeks[0]["id"]), leeks[0]["name"])

    # -- builds -----------------------------------------------------------

    def cores(self, ref: LeekRef) -> int:
        """The leek's live core count, i.e. its op budget in millions."""
        return int(self._build(ref)["cores"])

    def _build(self, ref: LeekRef, attempts: int = 4) -> dict:
        """Cached `build_entity` output, team/ai still to be filled in."""
        key = (ref.account, ref.id)
        if key not in self._entities:
            api = self.api(ref.account)
            last: Exception | None = None
            for i in range(attempts):
                try:
                    self._entities[key] = build_entity(api, ref.id, 1, "")
                    break
                except TagadAIError as e:          # /leek/get is rate limited
                    last = e
                    if "rate_limit" not in str(e):
                        raise
                    time.sleep(2 * (i + 1))
            else:
                raise TagadAIError(f"Could not fetch {ref}: {last}")
        return self._entities[key]

    def entity(self, ref: LeekRef, team: int, ai: str) -> dict:
        """A scenario entity for this leek, on `team`, driven by `ai`.

        The op budget is asserted rather than assumed: a missing or zero
        `cores` would hand the AI no operations at all and quietly benchmark
        something that is not the AI under test.
        """
        entity = dict(self._build(ref))
        entity.update(farmer=team, team=team, ai=ai)

        cores = entity.get("cores")
        if not isinstance(cores, int) or cores <= 0:
            raise TagadAIError(
                f"{ref} reports cores={cores!r}; the generator would give its AI "
                f"{(cores or 0) * 1_000_000} operations. Refusing to benchmark."
            )
        return entity
