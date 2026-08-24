"""
AI log access for generator output.

The generator returns `debug()` output under `logs`, bucketed by AI owner then
by entity. Two lines the AI already emits every own turn carry the search
statistics a tuning harness has to watch (see ml/TODO.md §2.3):

    ComboExplorer: 177 combos, best=P0:Stay score=29109 <Combo: [...
    ##MARKER##T2|n:Claudius|o:14555876/19000000|hp:3388/3512|tp:1/31|...

`parse_turn_stats` reads them back. Nothing here costs the AI an operation:
both lines were there before this module existed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Log levels the generator uses for `debugW()` / `debugE()` and their system
# equivalents.
LOG_WARNING_TYPES = {2, 7}
LOG_ERROR_TYPES = {3, 8}

# FarmerLog system-log codes worth naming when they show up.
LOG_CODES = {
    1000: "NO_WEAPON_EQUIPPED",
    1001: "CHIP_NOT_EQUIPPED",
    1002: "CHIP_NOT_EXISTS",
    1003: "WEAPON_NOT_EXISTS",
    1004: "WEAPON_NOT_EQUIPPED",
    1006: "LOADOUT_NOT_FOUND",
    1007: "SET_LOADOUT_OUT_OF_HOOK",
    1008: "ACTION_DENIED_IN_HOOK",
}

MARKER = "##MARKER##"

_COMBOS = re.compile(r"^ComboExplorer: (\d+) combos,")
_MARKER = re.compile(r"^" + re.escape(MARKER) + r"T(\d+)\|n:([^|]*)\|o:(\d+)/(\d+)\|")


def collect_logs(result: dict) -> list[tuple[int, int, str]]:
    """Flatten the generator's log buckets into (entity id, level, text).

    Entries are `[entityId, level, message, ...]`; system logs append a
    FarmerLog code and its parameters, and carry an empty message. Every
    entity shares bucket "0" because the CLI never sets `aiOwner`, so the
    entity id inside the entry is the only way to tell them apart.
    """
    out = []
    for bucket in (result.get("logs") or {}).values():
        for entries in bucket.values():
            for entry in entries:
                if len(entry) < 3:
                    continue
                text = str(entry[2])
                if not text and len(entry) >= 4:
                    code = entry[3]
                    params = entry[4] if len(entry) > 4 else []
                    text = f"{LOG_CODES.get(code, code)} {params}"
                out.append((entry[0], entry[1], text))
    return out


@dataclass
class TurnStats:
    """What one entity's search did on one of its turns."""

    entity_id: int
    turn: int
    name: str
    ops: int         # operations spent when Benchmark.display() ran
    max_ops: int     # the turn's budget (cores x 1M)
    combos: int      # ComboExplorer evaluations; -1 if the line was not seen

    @property
    def ops_ratio(self) -> float:
        return self.ops / self.max_ops if self.max_ops > 0 else 0.0


def parse_turn_stats(result: dict) -> list[TurnStats]:
    """Read per-turn search statistics out of the AI's own debug lines.

    The `ComboExplorer:` summary precedes the `##MARKER##` line of the same
    turn for the same entity, so the count is held until the marker closes
    the turn. A turn with no ComboExplorer line (a bulb, a crash before the
    summary) reports `combos = -1` rather than 0, which would be a real,
    alarming measurement.
    """
    pending: dict[int, int] = {}
    stats: list[TurnStats] = []
    for eid, _level, text in collect_logs(result):
        m = _COMBOS.match(text)
        if m:
            pending[eid] = int(m.group(1))
            continue
        m = _MARKER.match(text)
        if m:
            stats.append(TurnStats(
                entity_id=eid,
                turn=int(m.group(1)),
                name=m.group(2),
                ops=int(m.group(3)),
                max_ops=int(m.group(4)),
                combos=pending.pop(eid, -1),
            ))
    return stats
