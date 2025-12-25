"""
Fight metadata extraction for build analysis.

Extracts equipment usage and behavioral patterns from fight action logs.
"""

from dataclasses import dataclass, field
from typing import Optional

# Import fresh mappings from official API (2025)
from .item_mappings import (
    WEAPONS,
    CHIPS,
    CHIP_TYPES,
    get_weapon_name,
    get_chip_name,
    get_weapon_info,
    get_chip_info,
    get_chip_type_name,
)

# Action types from fight logs
ACTION_START_FIGHT = 0
ACTION_DEATH = 5
ACTION_NEW_TURN = 6
ACTION_LEEK_TURN = 7
ACTION_END_TURN = 8
ACTION_SUMMON = 9
ACTION_MOVE_TO = 10
ACTION_USE_CHIP = 12  # [12, chip_id, cell, success]
ACTION_SET_WEAPON = 13  # [13, weapon_id]
ACTION_USE_WEAPON = 16  # [16, cell, success]
ACTION_LIFE_LOST = 101
ACTION_LIFE_GAIN = 103
ACTION_ADD_EFFECT = 301


def get_weapons() -> dict[int, dict]:
    """Get all weapons mapping."""
    return WEAPONS


def get_chips() -> dict[int, dict]:
    """Get all chips mapping."""
    return CHIPS


# Chip type classification
CHIP_TYPE_DAMAGE = 1
CHIP_TYPE_HEAL = 2
CHIP_TYPE_SHIELD = 4
CHIP_TYPE_BUFF = 5
CHIP_TYPE_POISON = 6
CHIP_TYPE_DEBUFF = 7
CHIP_TYPE_SUMMON = 8
CHIP_TYPE_UTILITY = 9


@dataclass
class LeekFightMetadata:
    """Extracted metadata for one leek in one fight."""

    fight_id: int
    leek_id: int
    entity_id: int  # Fight-local entity ID
    level: int = 0  # Individual leek level

    # Leek stats (from fight start)
    strength: int = 0
    agility: int = 0
    magic: int = 0
    resistance: int = 0
    wisdom: int = 0
    science: int = 0
    frequency: int = 0
    life: int = 0
    tp: int = 0
    mp: int = 0

    # Equipment used (actually fired/cast in fight)
    weapons_used: list[int] = field(default_factory=list)
    chips_used: list[int] = field(default_factory=list)

    # Usage counts
    weapon_actions: int = 0
    chip_actions: int = 0
    move_actions: int = 0
    summon_actions: int = 0

    # Damage breakdown (estimated from effects)
    physical_damage: int = 0  # Damage via weapons
    magic_damage: int = 0  # Damage via damage chips
    poison_damage: int = 0  # Damage via poison chips
    heal_done: int = 0

    # Efficiency metrics
    total_tp_spent: int = 0
    total_mp_spent: int = 0

    # Behavioral patterns
    total_cells_moved: int = 0
    turns_alive: int = 0

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return {
            "fight_id": self.fight_id,
            "leek_id": self.leek_id,
            "entity_id": self.entity_id,
            "level": self.level,
            # Stats
            "strength": self.strength,
            "agility": self.agility,
            "magic": self.magic,
            "resistance": self.resistance,
            "wisdom": self.wisdom,
            "science": self.science,
            "frequency": self.frequency,
            "life": self.life,
            "tp": self.tp,
            "mp": self.mp,
            "weapons_used": list(set(self.weapons_used)),  # Dedupe
            "chips_used": list(set(self.chips_used)),
            "weapon_actions": self.weapon_actions,
            "chip_actions": self.chip_actions,
            "move_actions": self.move_actions,
            "summon_actions": self.summon_actions,
            "physical_damage": self.physical_damage,
            "magic_damage": self.magic_damage,
            "poison_damage": self.poison_damage,
            "heal_done": self.heal_done,
            "total_tp_spent": self.total_tp_spent,
            "total_mp_spent": self.total_mp_spent,
            "total_cells_moved": self.total_cells_moved,
            "turns_alive": self.turns_alive,
        }


def extract_fight_metadata(fight_id: int, fight_data: dict) -> list[LeekFightMetadata]:
    """
    Extract metadata for each leek from fight action log.

    Args:
        fight_id: The fight ID
        fight_data: The full fight JSON data

    Returns:
        List of LeekFightMetadata, one per non-summon leek
    """
    data = fight_data.get("data", {})
    actions = data.get("actions", [])
    leeks = data.get("leeks", [])

    if not leeks or not actions:
        return []

    # Build entity_id -> leek info mapping
    # Also build name -> (real_leek_id, level) from outer leeks
    outer_leeks = fight_data.get("leeks1", []) + fight_data.get("leeks2", [])
    name_to_info = {
        l.get("name"): {"id": l.get("id"), "level": l.get("level", 0)}
        for l in outer_leeks if l.get("name")
    }

    entity_to_metadata: dict[int, LeekFightMetadata] = {}

    for leek in leeks:
        entity_id = leek.get("id")
        name = leek.get("name", "")
        is_summon = leek.get("summon", False)

        if is_summon:
            continue

        # Only include leeks that are in the outer leeks (leeks1/leeks2)
        # This excludes turrets, obstacles, and other non-player entities
        outer_info = name_to_info.get(name)
        if not outer_info:
            continue  # Skip entities not in leeks1/leeks2 (turrets, etc.)

        real_leek_id = outer_info.get("id", entity_id)
        level = outer_info.get("level") or leek.get("level", 0)

        # Extract stats from inner leek data
        entity_to_metadata[entity_id] = LeekFightMetadata(
            fight_id=fight_id,
            leek_id=real_leek_id,
            entity_id=entity_id,
            level=level,
            # Combat stats
            strength=leek.get("strength", 0),
            agility=leek.get("agility", 0),
            magic=leek.get("magic", 0),
            resistance=leek.get("resistance", 0),
            # Secondary stats
            wisdom=leek.get("wisdom", 0),
            science=leek.get("science", 0),
            frequency=leek.get("frequency", 0),
            # Resources
            life=leek.get("life", 0),
            tp=leek.get("tp", 0),
            mp=leek.get("mp", 0),
        )

    # Track current entity turn and equipped weapon per entity
    current_entity: Optional[int] = None
    entity_weapons: dict[int, int] = {}  # entity_id -> current weapon_id
    entity_turn_count: dict[int, int] = {eid: 0 for eid in entity_to_metadata}

    # Process actions
    for action in actions:
        if not action or not isinstance(action, list):
            continue

        action_type = action[0]

        if action_type == ACTION_LEEK_TURN:
            # [7, entity_id]
            if len(action) > 1:
                current_entity = action[1]
                if current_entity in entity_turn_count:
                    entity_turn_count[current_entity] += 1

        elif action_type == ACTION_SET_WEAPON:
            # [13, weapon_id]
            if len(action) > 1 and current_entity is not None:
                weapon_id = action[1]
                entity_weapons[current_entity] = weapon_id

        elif action_type == ACTION_USE_WEAPON:
            # [16, cell, success]
            if current_entity is not None and current_entity in entity_to_metadata:
                meta = entity_to_metadata[current_entity]
                meta.weapon_actions += 1

                # Record which weapon was used
                weapon_id = entity_weapons.get(current_entity)
                if weapon_id is not None:
                    meta.weapons_used.append(weapon_id)

        elif action_type == ACTION_USE_CHIP:
            # [12, chip_id, cell, success]
            if len(action) > 1 and current_entity is not None and current_entity in entity_to_metadata:
                chip_id = action[1]
                meta = entity_to_metadata[current_entity]
                meta.chip_actions += 1
                meta.chips_used.append(chip_id)

                # Classify chip type
                chips = get_chips()
                chip_info = chips.get(chip_id, {})
                chip_type = chip_info.get("type", 0)

                if chip_type == CHIP_TYPE_SUMMON:
                    meta.summon_actions += 1

        elif action_type == ACTION_MOVE_TO:
            # [10, entity_id, dest_cell, [path]]
            if len(action) > 1:
                entity_id = action[1]
                if entity_id in entity_to_metadata:
                    meta = entity_to_metadata[entity_id]
                    meta.move_actions += 1
                    # Count cells moved
                    if len(action) > 3 and isinstance(action[3], list):
                        meta.total_cells_moved += len(action[3])

        elif action_type == ACTION_LIFE_LOST:
            # [101, entity_id, damage, ...]
            # Attribute damage to current acting entity
            if len(action) > 2 and current_entity is not None and current_entity in entity_to_metadata:
                target_entity = action[1]
                damage = action[2]

                # If target is not the acting entity, it's damage dealt
                if target_entity != current_entity:
                    meta = entity_to_metadata[current_entity]
                    # Rough classification: if last action was weapon, physical; else magic
                    # This is approximate - proper tracking would need more context
                    meta.physical_damage += damage  # Default to physical

        elif action_type == ACTION_LIFE_GAIN:
            # [103, entity_id, heal_amount]
            if len(action) > 2 and current_entity is not None and current_entity in entity_to_metadata:
                target_entity = action[1]
                heal = action[2]
                meta = entity_to_metadata[current_entity]
                meta.heal_done += heal

    # Set turns_alive from turn counts
    for entity_id, meta in entity_to_metadata.items():
        meta.turns_alive = entity_turn_count.get(entity_id, 0)

    return list(entity_to_metadata.values())


def get_level_bucket(level: int) -> str:
    """Convert level to bucket string for aggregation."""
    if level == 301:
        return "301"
    bucket_start = ((level - 1) // 10) * 10 + 1
    bucket_end = bucket_start + 9
    return f"{bucket_start}-{bucket_end}"


def aggregate_equipment_by_level(
    metadata_list: list[dict],
    level_map: dict[int, int],  # leek_id -> level
) -> dict[str, dict]:
    """
    Aggregate equipment usage by level bucket.

    Args:
        metadata_list: List of metadata dicts from extract_fight_metadata
        level_map: Mapping of leek_id to level

    Returns:
        {bucket: {"weapons": {id: count}, "chips": {id: count}, "sample_size": n}}
    """
    from collections import defaultdict

    buckets: dict[str, dict] = defaultdict(lambda: {
        "weapons": defaultdict(int),
        "chips": defaultdict(int),
        "sample_size": 0,
    })

    for meta in metadata_list:
        leek_id = meta.get("leek_id")
        level = level_map.get(leek_id, 0)

        if level <= 0:
            continue

        bucket = get_level_bucket(level)
        buckets[bucket]["sample_size"] += 1

        for weapon_id in meta.get("weapons_used", []):
            buckets[bucket]["weapons"][weapon_id] += 1

        for chip_id in meta.get("chips_used", []):
            buckets[bucket]["chips"][chip_id] += 1

    # Convert defaultdicts to regular dicts
    return {
        bucket: {
            "weapons": dict(data["weapons"]),
            "chips": dict(data["chips"]),
            "sample_size": data["sample_size"],
        }
        for bucket, data in buckets.items()
    }


def compute_equipment_cooccurrence(
    metadata_list: list[dict],
) -> dict[str, dict[str, int]]:
    """
    Compute co-occurrence matrix for equipment.

    Returns dict of {item_a: {item_b: count}} where item_a and item_b
    were used together in the same fight by the same leek.
    """
    from collections import defaultdict

    cooccurrence: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for meta in metadata_list:
        # Combine weapons and chips, prefixed
        weapons = [f"W:{w}" for w in set(meta.get("weapons_used", []))]
        chips = [f"C:{c}" for c in set(meta.get("chips_used", []))]
        all_items = weapons + chips

        # Count co-occurrences
        for i, item_a in enumerate(all_items):
            for item_b in all_items[i+1:]:
                cooccurrence[item_a][item_b] += 1
                cooccurrence[item_b][item_a] += 1

    return {k: dict(v) for k, v in cooccurrence.items()}
