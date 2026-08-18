"""
Scenario generation for local fights.

Defines dataclasses for configuring fight scenarios and
serializing them to the generator's JSON format.

The generator only reads `random_seed`, `max_turns`, `farmers`, `teams` and
`entities` from this JSON — `map` is serialized but ignored by
`Scenario.fromFile()`, so every local fight runs on a randomly generated map.
See src/localfight/README.md for the full generator contract.
"""

from dataclasses import dataclass, field
from typing import Optional
import json
import random


# ITEM template ids, NOT the weapon ids that key data/weapons.json. The
# generator registers each weapon under its `item` field
# (`new Weapon(weapon.get("item")...)` in Generator.java), so `getWeapon(37)`
# is the pistol (item 37 / weapon 1), not the odachi (weapon 37 / item 408).
# These are the same ids the site API reports in `leek.weapons[].template`, so
# a real build can be passed through unchanged. An id the generator doesn't
# know is dropped with a stderr line nobody reads and the leek fights
# bare-handed — validate before running.
ITEM_PISTOL = 37
ITEM_MACHINE_GUN = 38
ITEM_SHOTGUN = 41
ITEM_LASER = 42
ITEM_MAGNUM = 45


@dataclass
class LeekConfig:
    """Configuration for a single leek entity."""

    # Identity
    id: int
    name: str
    farmer: int
    team: int

    # AI
    ai: str = "test/ai/simple.leek"

    # Stats
    level: int = 1
    life: int = 100
    strength: int = 0
    agility: int = 0
    resistance: int = 0
    science: int = 0
    magic: int = 0
    frequency: int = 100
    wisdom: int = 0
    tp: int = 10
    mp: int = 3

    # Resources (required for AI execution). cores sets the per-turn operation
    # budget (cores * 1_000_000) and ram the memory budget
    # (min(50, ram) * 8_000_000). A real level-301 leek runs 18-19 cores; the
    # default of 1 gives tagadalive 1M ops and it blows the limit on turn one.
    cores: int = 1
    ram: int = 6

    # Starting cell. The generator places entities itself when this is None.
    cell: Optional[int] = None

    # Equipment: weapons are ITEM template ids (see the note above), chips are
    # chip ids — which happen to equal their item template ids.
    weapons: list[int] = field(default_factory=lambda: [ITEM_PISTOL])
    chips: list[int] = field(default_factory=list)

    # Entity type (1 = leek, don't use 0)
    type: int = 1

    def to_dict(self) -> dict:
        """Serialize to generator JSON format."""
        d = {
            "id": self.id,
            "name": self.name,
            "ai": self.ai,
            "type": self.type,
            "farmer": self.farmer,
            "team": self.team,
            "level": self.level,
            "life": self.life,
            "strength": self.strength,
            "agility": self.agility,
            "resistance": self.resistance,
            "science": self.science,
            "magic": self.magic,
            "frequency": self.frequency,
            "wisdom": self.wisdom,
            "tp": self.tp,
            "mp": self.mp,
            "cores": self.cores,
            "ram": self.ram,
            "weapons": self.weapons,
            "chips": self.chips,
        }
        if self.cell is not None:
            d["cell"] = self.cell
        return d


@dataclass
class MapConfig:
    """Configuration for the fight map.

    NOT APPLIED: `Scenario.fromFile()` never reads the `map` key, so the
    generator always builds a random map. Kept because the field is part of
    the server-side scenario format.
    """

    id: int = 1
    width: int = 17
    height: int = 17
    type: int = 0
    # Obstacles must be object, not array!
    obstacles: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Serialize to generator JSON format."""
        return {
            "id": self.id,
            "width": self.width,
            "height": self.height,
            "type": self.type,
            "obstacles": self.obstacles,
        }


@dataclass
class Scenario:
    """Complete fight scenario configuration."""

    # Teams of leeks
    team1: list[LeekConfig]
    team2: list[LeekConfig]

    # Map configuration
    map: MapConfig = field(default_factory=MapConfig)

    # Random seed (None = random each time)
    random_seed: Optional[int] = None

    # Maximum turns before draw
    max_turns: int = 64

    def to_dict(self) -> dict:
        """Serialize to generator JSON format."""
        # Build farmers from unique farmer IDs
        farmer_ids = set()
        for leek in self.team1 + self.team2:
            farmer_ids.add(leek.farmer)

        farmers = [
            {"id": fid, "name": f"Player{fid}", "country": "fr"}
            for fid in sorted(farmer_ids)
        ]

        # Build teams
        team_ids = {leek.team for leek in self.team1 + self.team2}
        teams = [{"id": tid, "name": f"Team{tid}"} for tid in sorted(team_ids)]

        # Build entities (grouped by team)
        entities = [
            [leek.to_dict() for leek in self.team1],
            [leek.to_dict() for leek in self.team2],
        ]

        result = {
            "farmers": farmers,
            "teams": teams,
            "entities": entities,
            "map": self.map.to_dict(),
            "max_turns": self.max_turns,
        }

        if self.random_seed is not None:
            result["random_seed"] = self.random_seed

        return result

    def to_json(self, indent: int = 2) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def create_1v1_pistol(
        cls,
        seed: Optional[int] = None,
        ai1: str = "test/ai/simple.leek",
        ai2: str = "test/ai/simple.leek",
        cell1: Optional[int] = None,
        cell2: Optional[int] = None,
    ) -> "Scenario":
        """Create a simple 1v1 pistol scenario for Phase 8 ML training."""
        leek1 = LeekConfig(
            id=1,
            name="Leek1",
            farmer=1,
            team=1,
            ai=ai1,
            cell=cell1,
            weapons=[ITEM_PISTOL],
        )
        leek2 = LeekConfig(
            id=2,
            name="Leek2",
            farmer=2,
            team=2,
            ai=ai2,
            cell=cell2,
            weapons=[ITEM_PISTOL],
        )
        return cls(
            team1=[leek1],
            team2=[leek2],
            random_seed=seed,
        )

    @classmethod
    def create_random_1v1_pistol(
        cls,
        seed: Optional[int] = None,
        ai1: str = "test/ai/simple.leek",
        ai2: str = "test/ai/simple.leek",
    ) -> "Scenario":
        """Create a 1v1 pistol scenario with random starting positions."""
        rng = random.Random(seed)

        # Map is 17x17, cells 0-612 but some are obstacles
        # Pick two random valid cells that aren't too close
        # For simplicity, use cells in reasonable range
        valid_cells = list(range(50, 560))  # Avoid edges
        cell1 = rng.choice(valid_cells)

        # Ensure minimum distance
        while True:
            cell2 = rng.choice(valid_cells)
            # Simple distance check (not exact cell distance)
            if abs(cell2 - cell1) > 30:  # Reasonable starting distance
                break

        return cls.create_1v1_pistol(
            seed=seed,
            ai1=ai1,
            ai2=ai2,
            cell1=cell1,
            cell2=cell2,
        )


def generate_scenarios(
    count: int,
    base_seed: int = 42,
    ai1: str = "test/ai/simple.leek",
    ai2: str = "test/ai/simple.leek",
) -> list[Scenario]:
    """Generate multiple random 1v1 pistol scenarios."""
    return [
        Scenario.create_random_1v1_pistol(
            seed=base_seed + i,
            ai1=ai1,
            ai2=ai2,
        )
        for i in range(count)
    ]
