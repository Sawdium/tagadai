"""
Item property extraction for generalizable NN features.

Instead of using item IDs (which don't generalize to unseen items),
we extract item properties like damage type, range, cost, etc.
"""

from dataclasses import dataclass
from typing import Optional

from src.scraper.item_mappings import WEAPONS, CHIPS


@dataclass
class ItemProperties:
    """Normalized item properties for NN input."""

    # Item type flags
    is_weapon: float = 0.0
    is_chip: float = 0.0
    is_move: float = 0.0
    is_end: float = 0.0

    # Effect type flags
    is_damage: float = 0.0
    is_heal: float = 0.0
    is_shield: float = 0.0
    is_buff: float = 0.0
    is_poison: float = 0.0
    is_debuff: float = 0.0
    is_summon: float = 0.0
    is_utility: float = 0.0
    is_damage_return: float = 0.0

    # Damage type
    is_physical: float = 0.0  # Weapons use strength
    is_magic: float = 0.0     # Chips use magic

    # Normalized costs and ranges (0-1 scale)
    tp_cost_norm: float = 0.0  # cost / 20 (max ~20 TP)
    min_range_norm: float = 0.0  # range / 12
    max_range_norm: float = 0.0  # range / 12

    # Other properties
    has_aoe: float = 0.0
    level_req_norm: float = 0.0  # level / 301

    def to_vector(self) -> list[float]:
        """Convert to feature vector."""
        return [
            self.is_weapon,
            self.is_chip,
            self.is_move,
            self.is_end,
            self.is_damage,
            self.is_heal,
            self.is_shield,
            self.is_buff,
            self.is_poison,
            self.is_debuff,
            self.is_summon,
            self.is_utility,
            self.is_damage_return,
            self.is_physical,
            self.is_magic,
            self.tp_cost_norm,
            self.min_range_norm,
            self.max_range_norm,
            self.has_aoe,
            self.level_req_norm,
        ]

    @staticmethod
    def vector_size() -> int:
        return 20


def get_item_properties(
    item_id: Optional[int],
    is_weapon: bool = False,
    is_move: bool = False,
    is_end: bool = False,
) -> ItemProperties:
    """
    Extract properties from an item ID.

    Args:
        item_id: Weapon ID or Chip template ID
        is_weapon: True if this is a weapon (uses WEAPONS dict)
        is_move: True if this is a move action (no item)
        is_end: True if this is end turn (no item)

    Returns:
        ItemProperties with normalized values
    """
    props = ItemProperties()

    if is_move:
        props.is_move = 1.0
        return props

    if is_end:
        props.is_end = 1.0
        return props

    if item_id is None:
        return props

    if is_weapon:
        props.is_weapon = 1.0
        props.is_physical = 1.0
        props.is_damage = 1.0

        info = WEAPONS.get(item_id, {})
        if info:
            props.tp_cost_norm = info.get('cost', 5) / 20.0
            props.level_req_norm = info.get('level', 1) / 301.0

            # Parse range string like "1-7"
            range_str = info.get('range', '1-1')
            if '-' in range_str:
                parts = range_str.split('-')
                props.min_range_norm = int(parts[0]) / 12.0
                props.max_range_norm = int(parts[1]) / 12.0
            else:
                props.min_range_norm = 1 / 12.0
                props.max_range_norm = 7 / 12.0
    else:
        # Chip
        props.is_chip = 1.0
        props.is_magic = 1.0

        info = CHIPS.get(item_id, {})
        if info:
            props.tp_cost_norm = info.get('cost', 3) / 20.0
            props.level_req_norm = info.get('level', 1) / 301.0

            # Type classification
            chip_type = info.get('type', 1)
            if chip_type == 1:
                props.is_damage = 1.0
            elif chip_type == 2:
                props.is_heal = 1.0
            elif chip_type == 3:
                props.is_damage_return = 1.0
            elif chip_type == 4:
                props.is_shield = 1.0
            elif chip_type == 5:
                props.is_buff = 1.0
            elif chip_type == 6:
                props.is_poison = 1.0
            elif chip_type == 7:
                props.is_debuff = 1.0
            elif chip_type == 8:
                props.is_summon = 1.0
            elif chip_type == 9:
                props.is_utility = 1.0

            # Chips typically have range 1-7 (self) or 1-X
            # We don't have range in CHIPS, estimate from type
            if chip_type == 2:  # heal - typically on self or allies
                props.min_range_norm = 0.0
                props.max_range_norm = 5 / 12.0
            elif chip_type == 5:  # buff - typically on self
                props.min_range_norm = 0.0
                props.max_range_norm = 1 / 12.0
            else:
                props.min_range_norm = 1 / 12.0
                props.max_range_norm = 7 / 12.0

    return props


def get_move_properties() -> ItemProperties:
    """Get properties for a move action."""
    return get_item_properties(None, is_move=True)


def get_end_properties() -> ItemProperties:
    """Get properties for end turn action."""
    return get_item_properties(None, is_end=True)
