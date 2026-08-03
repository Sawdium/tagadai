"""
LeekWars weapon and chip ID mappings.

Source: LeekWars API (fetched 2025-12-24)

IMPORTANT: Fight actions use DIFFERENT ID systems for weapons vs chips!
- Weapons: Use ITEM IDs (from /api/weapon/get-all)
- Chips: Use TEMPLATE IDs (from /api/chip/get-templates)

This was verified by comparing fight action data with API responses:
- SET_WEAPON [13, 9] -> weapon item 9 = destroyer (correct for ~lvl 100 fights)
- USE_CHIP [12, 43, ...] -> chip template 43 = rocky_bulb (item 43 doesn't exist)
"""

# Weapon ID -> info mapping (ITEM IDs - used directly in fight actions)
# Source: /api/weapon/get-all
WEAPONS = {
    1: {"name": "pistol", "level": 1, "cost": 3, "range": "1-7"},
    2: {"name": "machine_gun", "level": 8, "cost": 4, "range": "1-6"},
    3: {"name": "double_gun", "level": 45, "cost": 4, "range": "2-7"},
    4: {"name": "shotgun", "level": 16, "cost": 5, "range": "1-5"},
    5: {"name": "magnum", "level": 27, "cost": 5, "range": "1-8"},
    6: {"name": "laser", "level": 38, "cost": 6, "range": "2-9"},
    7: {"name": "grenade_launcher", "level": 135, "cost": 6, "range": "4-7"},
    8: {"name": "flame_thrower", "level": 90, "cost": 6, "range": "2-8"},
    9: {"name": "destroyer", "level": 85, "cost": 6, "range": "1-6"},
    10: {"name": "gazor", "level": 297, "cost": 8, "range": "2-7"},
    11: {"name": "electrisor", "level": 211, "cost": 7, "range": "7-7"},
    12: {"name": "m_laser", "level": 299, "cost": 8, "range": "5-12"},
    13: {"name": "b_laser", "level": 95, "cost": 5, "range": "2-8"},
    14: {"name": "katana", "level": 257, "cost": 7, "range": "1-1"},
    15: {"name": "broadsword", "level": 30, "cost": 5, "range": "1-1"},
    16: {"name": "axe", "level": 110, "cost": 6, "range": "1-1"},
    17: {"name": "j_laser", "level": 153, "cost": 5, "range": "5-11"},
    18: {"name": "illicit_grenade_launcher", "level": 136, "cost": 6, "range": "4-7"},
    19: {"name": "mysterious_electrisor", "level": 212, "cost": 7, "range": "7-7"},
    20: {"name": "unbridled_gazor", "level": 298, "cost": 8, "range": "2-7"},
    21: {"name": "revoked_m_laser", "level": 300, "cost": 8, "range": "5-12"},
    22: {"name": "rifle", "level": 271, "cost": 7, "range": "7-9"},
    23: {"name": "rhino", "level": 187, "cost": 5, "range": "2-4"},
    24: {"name": "explorer_rifle", "level": 272, "cost": 7, "range": "7-9"},
    25: {"name": "lightninger", "level": 237, "cost": 9, "range": "6-10"},
    27: {"name": "neutrino", "level": 12, "cost": 4, "range": "2-6"},
    29: {"name": "bazooka", "level": 169, "cost": 11, "range": "8-12"},
    32: {"name": "dark_katana", "level": 258, "cost": 7, "range": "1-1"},
    33: {"name": "enhanced_lightninger", "level": 238, "cost": 9, "range": "6-10"},
    34: {"name": "unstable_destroyer", "level": 86, "cost": 6, "range": "1-6"},
    35: {"name": "sword", "level": 75, "cost": 6, "range": "1-1"},
    36: {"name": "heavy_sword", "level": 288, "cost": 15, "range": "1-1"},
    37: {"name": "odachi", "level": 50, "cost": 9, "range": "1-1"},
    38: {"name": "excalibur", "level": 100, "cost": 12, "range": "1-1"},
    39: {"name": "scythe", "level": 200, "cost": 15, "range": "1-1"},
    40: {"name": "quantum_rifle", "level": 281, "cost": 10, "range": "5-10"},
}

# Chip TEMPLATE ID -> info mapping (TEMPLATE IDs - used in fight actions)
# Source: /api/chip/get-templates + /api/chip/get-all for details
# Type: 1=damage, 2=heal, 3=damage_return, 4=shield, 5=buff, 6=poison, 7=debuff, 8=summon, 9=utility
CHIPS = {
    1: {"name": "bandage", "level": 3, "type": 2, "cost": 2, "item_id": 3},
    2: {"name": "cure", "level": 20, "type": 2, "cost": 4, "item_id": 4},
    3: {"name": "drip", "level": 56, "type": 2, "cost": 5, "item_id": 10},
    4: {"name": "regeneration", "level": 122, "type": 2, "cost": 8, "item_id": 35},
    5: {"name": "vaccine", "level": 80, "type": 2, "cost": 6, "item_id": 11},
    6: {"name": "shock", "level": 2, "type": 1, "cost": 2, "item_id": 1},
    7: {"name": "flash", "level": 24, "type": 1, "cost": 3, "item_id": 6},
    8: {"name": "lightning", "level": 180, "type": 1, "cost": 4, "item_id": 33},
    9: {"name": "spark", "level": 19, "type": 1, "cost": 3, "item_id": 18},
    10: {"name": "flame", "level": 29, "type": 1, "cost": 4, "item_id": 5},
    11: {"name": "meteorite", "level": 160, "type": 1, "cost": 8, "item_id": 36},
    12: {"name": "pebble", "level": 4, "type": 1, "cost": 2, "item_id": 19},
    13: {"name": "rock", "level": 13, "type": 1, "cost": 5, "item_id": 7},
    14: {"name": "rockfall", "level": 77, "type": 1, "cost": 5, "item_id": 32},
    15: {"name": "ice", "level": 9, "type": 1, "cost": 4, "item_id": 2},
    16: {"name": "stalactite", "level": 50, "type": 1, "cost": 6, "item_id": 30},
    17: {"name": "iceberg", "level": 100, "type": 1, "cost": 7, "item_id": 31},
    18: {"name": "shield", "level": 35, "type": 4, "cost": 4, "item_id": 20},
    19: {"name": "helmet", "level": 10, "type": 4, "cost": 3, "item_id": 21},
    20: {"name": "armor", "level": 74, "type": 4, "cost": 6, "item_id": 22},
    21: {"name": "wall", "level": 18, "type": 4, "cost": 3, "item_id": 23},
    22: {"name": "rampart", "level": 117, "type": 4, "cost": 5, "item_id": 24},
    23: {"name": "fortress", "level": 194, "type": 4, "cost": 6, "item_id": 29},
    24: {"name": "protein", "level": 6, "type": 5, "cost": 3, "item_id": 8},
    25: {"name": "steroid", "level": 134, "type": 5, "cost": 7, "item_id": 25},
    26: {"name": "doping", "level": 207, "type": 5, "cost": 5, "item_id": 26},
    27: {"name": "stretching", "level": 17, "type": 5, "cost": 3, "item_id": 9},
    28: {"name": "warm_up", "level": 127, "type": 5, "cost": 7, "item_id": 28},
    29: {"name": "reflexes", "level": 197, "type": 5, "cost": 5, "item_id": 27},
    30: {"name": "leather_boots", "level": 22, "type": 5, "cost": 3, "item_id": 14},
    31: {"name": "winged_boots", "level": 175, "type": 5, "cost": 6, "item_id": 13},
    32: {"name": "seven_league_boots", "level": 203, "type": 5, "cost": 4, "item_id": 12},
    33: {"name": "motivation", "level": 14, "type": 5, "cost": 4, "item_id": 15},
    34: {"name": "adrenaline", "level": 156, "type": 5, "cost": 1, "item_id": 16},
    35: {"name": "rage", "level": 226, "type": 5, "cost": 4, "item_id": 17},
    36: {"name": "liberation", "level": 60, "type": 9, "cost": 5, "item_id": 34},
    37: {"name": "teleportation", "level": 200, "type": 9, "cost": 9, "item_id": 59},
    38: {"name": "armoring", "level": 68, "type": 2, "cost": 5, "item_id": 67},
    39: {"name": "inversion", "level": 150, "type": 9, "cost": 4, "item_id": 68},
    40: {"name": "puny_bulb", "level": 48, "type": 8, "cost": 6, "item_id": 73},
    41: {"name": "fire_bulb", "level": 190, "type": 8, "cost": 14, "item_id": 74},
    42: {"name": "healer_bulb", "level": 174, "type": 8, "cost": 14, "item_id": 75},
    43: {"name": "rocky_bulb", "level": 105, "type": 8, "cost": 10, "item_id": 76},
    44: {"name": "iced_bulb", "level": 130, "type": 8, "cost": 12, "item_id": 77},
    45: {"name": "lightning_bulb", "level": 280, "type": 8, "cost": 16, "item_id": 78},
    46: {"name": "metallic_bulb", "level": 230, "type": 8, "cost": 16, "item_id": 79},
    47: {"name": "remission", "level": 170, "type": 2, "cost": 5, "item_id": 80},
    48: {"name": "carapace", "level": 141, "type": 4, "cost": 5, "item_id": 81},
    49: {"name": "resurrection", "level": 301, "type": 2, "cost": 18, "item_id": 84},
    50: {"name": "devil_strike", "level": 171, "type": 1, "cost": 6, "item_id": 85},
    51: {"name": "whip", "level": 119, "type": 5, "cost": 4, "item_id": 88},
    52: {"name": "loam", "level": 111, "type": 2, "cost": 4, "item_id": 89},
    53: {"name": "fertilizer", "level": 205, "type": 2, "cost": 6, "item_id": 90},
    54: {"name": "acceleration", "level": 143, "type": 5, "cost": 4, "item_id": 91},
    55: {"name": "slow_down", "level": 98, "type": 7, "cost": 3, "item_id": 92},
    56: {"name": "ball_and_chain", "level": 184, "type": 7, "cost": 5, "item_id": 93},
    57: {"name": "tranquilizer", "level": 65, "type": 7, "cost": 3, "item_id": 94},
    58: {"name": "soporific", "level": 145, "type": 7, "cost": 5, "item_id": 95},
    59: {"name": "fracture", "level": 240, "type": 7, "cost": 4, "item_id": 106},
    60: {"name": "solidification", "level": 40, "type": 5, "cost": 6, "item_id": 96},
    61: {"name": "venom", "level": 42, "type": 6, "cost": 4, "item_id": 97},
    62: {"name": "toxin", "level": 125, "type": 6, "cost": 5, "item_id": 98},
    63: {"name": "plague", "level": 210, "type": 6, "cost": 6, "item_id": 99},
    64: {"name": "thorn", "level": 132, "type": 3, "cost": 4, "item_id": 100},
    65: {"name": "mirror", "level": 246, "type": 3, "cost": 5, "item_id": 101},
    66: {"name": "ferocity", "level": 107, "type": 5, "cost": 5, "item_id": 102},
    67: {"name": "collar", "level": 182, "type": 5, "cost": 5, "item_id": 103},
    68: {"name": "bark", "level": 234, "type": 5, "cost": 5, "item_id": 104},
    69: {"name": "burning", "level": 209, "type": 1, "cost": 5, "item_id": 105},
    70: {"name": "antidote", "level": 114, "type": 9, "cost": 3, "item_id": 110},
    71: {"name": "punishment", "level": 147, "type": 1, "cost": 5, "item_id": 114},
    72: {"name": "covetousness", "level": 139, "type": 5, "cost": 2, "item_id": 120},
    73: {"name": "vampirization", "level": 177, "type": 2, "cost": 6, "item_id": 121},
    74: {"name": "precipitation", "level": 192, "type": 5, "cost": 3, "item_id": 122},
    75: {"name": "alteration", "level": 53, "type": 1, "cost": 3, "item_id": 141},
    76: {"name": "plasma", "level": 290, "type": 1, "cost": 9, "item_id": 143},
    77: {"name": "wizard_bulb", "level": 215, "type": 8, "cost": 15, "item_id": 142},
    78: {"name": "jump", "level": 70, "type": 9, "cost": 4, "item_id": 144},
    79: {"name": "covid", "level": 220, "type": 6, "cost": 8, "item_id": 152},
    80: {"name": "elevation", "level": 228, "type": 2, "cost": 6, "item_id": 154},
    81: {"name": "knowledge", "level": 32, "type": 5, "cost": 5, "item_id": 155},
    82: {"name": "wizardry", "level": 166, "type": 5, "cost": 6, "item_id": 156},
    83: {"name": "repotting", "level": 163, "type": 9, "cost": 4, "item_id": 157},
    84: {"name": "therapy", "level": 260, "type": 2, "cost": 7, "item_id": 158},
    85: {"name": "mutation", "level": 83, "type": 2, "cost": 7, "item_id": 159},
    86: {"name": "desintegration", "level": 223, "type": 1, "cost": 8, "item_id": 160},
    87: {"name": "transmutation", "level": 252, "type": 2, "cost": 8, "item_id": 161},
    88: {"name": "grapple", "level": 120, "type": 9, "cost": 3, "item_id": 162},
    89: {"name": "boxing_glove", "level": 140, "type": 9, "cost": 3, "item_id": 163},
    92: {"name": "tactician_bulb", "level": 270, "type": 8, "cost": 16, "item_id": 166},
    93: {"name": "savant_bulb", "level": 250, "type": 8, "cost": 16, "item_id": 167},
    94: {"name": "serum", "level": 199, "type": 2, "cost": 8, "item_id": 168},
    95: {"name": "crushing", "level": 158, "type": 7, "cost": 6, "item_id": 169},
    96: {"name": "brainwashing", "level": 266, "type": 7, "cost": 6, "item_id": 170},
    97: {"name": "arsenic", "level": 285, "type": 6, "cost": 8, "item_id": 171},
    98: {"name": "bramble", "level": 278, "type": 3, "cost": 4, "item_id": 172},
    99: {"name": "dome", "level": 243, "type": 4, "cost": 9, "item_id": 173},
    100: {"name": "manumission", "level": 149, "type": 9, "cost": 6, "item_id": 174},
    104: {"name": "prism", "level": 92, "type": 5, "cost": 6, "item_id": 276},
    105: {"name": "shuriken", "level": 50, "type": 1, "cost": 6, "item_id": 411},
    106: {"name": "kemuridama", "level": 50, "type": 9, "cost": 8, "item_id": 412},
    107: {"name": "fire_ball", "level": 100, "type": 1, "cost": 6, "item_id": 413},
    108: {"name": "trebuchet", "level": 100, "type": 1, "cost": 12, "item_id": 414},
    109: {"name": "awakening", "level": 200, "type": 2, "cost": 0, "item_id": 415},
    110: {"name": "thunder", "level": 200, "type": 1, "cost": 8, "item_id": 416},
    111: {"name": "kill", "level": 100, "type": 1, "cost": 1, "item_id": 417},
    112: {"name": "apocalypse", "level": 1, "type": 1, "cost": 5, "item_id": 418},
    113: {"name": "divine_protection", "level": 1, "type": 9, "cost": 5, "item_id": 419},
    114: {"name": "exasperation", "level": 1, "type": 0, "cost": 0, "item_id": 425},
}

# Chip type descriptions
CHIP_TYPES = {
    0: "special",
    1: "damage",
    2: "heal",
    3: "damage_return",
    4: "shield",
    5: "buff",
    6: "poison",
    7: "debuff",
    8: "summon",
    9: "utility",
}


def get_weapon_name(weapon_id: int) -> str:
    """Get weapon name by ID (item ID for weapons)."""
    if weapon_id in WEAPONS:
        return WEAPONS[weapon_id]["name"]
    return f"weapon_{weapon_id}"


def get_chip_name(chip_id: int) -> str:
    """Get chip name by ID (template ID for chips)."""
    if chip_id in CHIPS:
        return CHIPS[chip_id]["name"]
    return f"chip_{chip_id}"


def get_weapon_info(weapon_id: int) -> dict:
    """Get full weapon info by ID (item ID)."""
    return WEAPONS.get(weapon_id, {"name": f"weapon_{weapon_id}", "level": 0, "cost": 0, "range": "?"})


def get_chip_info(chip_id: int) -> dict:
    """Get full chip info by ID (template ID)."""
    return CHIPS.get(chip_id, {"name": f"chip_{chip_id}", "level": 0, "type": 0, "cost": 0})


def get_chip_type_name(type_id: int) -> str:
    """Get chip type name."""
    return CHIP_TYPES.get(type_id, "unknown")


# Item template ID -> name mapping (unified namespace used by leek equipment API)
# Source: /api/item/get-all (fetched 2026-03-10)
# Covers weapons, chips, components, hats, potions, pomps, materials, etc.
ITEM_TEMPLATES = {
    1: "chip_shock", 2: "chip_ice", 3: "chip_bandage", 4: "chip_cure",
    5: "chip_flame", 6: "chip_flash", 7: "chip_rock", 8: "chip_protein",
    9: "chip_stretching", 10: "chip_drip", 11: "chip_vaccine",
    12: "chip_seven_league_boots", 13: "chip_winged_boots", 14: "chip_leather_boots",
    15: "chip_motivation", 16: "chip_adrenaline", 17: "chip_rage", 18: "chip_spark",
    19: "chip_pebble", 20: "chip_shield", 21: "chip_helmet", 22: "chip_armor",
    23: "chip_wall", 24: "chip_rampart", 25: "chip_steroid", 26: "chip_doping",
    27: "chip_reflexes", 28: "chip_warm_up", 29: "chip_fortress",
    30: "chip_stalactite", 31: "chip_iceberg", 32: "chip_rockfall",
    33: "chip_lightning", 34: "chip_liberation", 35: "chip_regeneration",
    36: "chip_meteorite", 37: "weapon_pistol", 38: "weapon_machine_gun",
    39: "weapon_double_gun", 40: "weapon_destroyer", 41: "weapon_shotgun",
    42: "weapon_laser", 43: "weapon_grenade_launcher", 44: "weapon_electrisor",
    45: "weapon_magnum", 46: "weapon_flame_thrower", 47: "weapon_m_laser",
    48: "weapon_gazor", 59: "chip_teleportation", 60: "weapon_b_laser",
    67: "chip_armoring", 68: "chip_inversion", 73: "chip_puny_bulb",
    74: "chip_fire_bulb", 75: "chip_healer_bulb", 76: "chip_rocky_bulb",
    77: "chip_iced_bulb", 78: "chip_lightning_bulb", 79: "chip_metallic_bulb",
    80: "chip_remission", 81: "chip_carapace", 84: "chip_resurrection",
    85: "chip_devil_strike", 88: "chip_whip", 89: "chip_loam",
    90: "chip_fertilizer", 91: "chip_acceleration", 92: "chip_slow_down",
    93: "chip_ball_and_chain", 94: "chip_tranquilizer", 95: "chip_soporific",
    96: "chip_solidification", 97: "chip_venom", 98: "chip_toxin",
    99: "chip_plague", 100: "chip_thorn", 101: "chip_mirror",
    102: "chip_ferocity", 103: "chip_collar", 104: "chip_bark",
    105: "chip_burning", 106: "chip_fracture", 107: "weapon_katana",
    108: "weapon_broadsword", 109: "weapon_axe", 110: "chip_antidote",
    114: "chip_punishment", 115: "weapon_j_laser",
    116: "weapon_illicit_grenade_launcher", 117: "weapon_mysterious_electrisor",
    118: "weapon_unbridled_gazor", 119: "weapon_revoked_m_laser",
    120: "chip_covetousness", 121: "chip_vampirization", 122: "chip_precipitation",
    141: "chip_alteration", 142: "chip_wizard_bulb", 143: "chip_plasma",
    144: "chip_jump", 151: "weapon_rifle", 152: "chip_covid",
    153: "weapon_rhino", 154: "chip_elevation", 155: "chip_knowledge",
    156: "chip_wizardry", 157: "chip_repotting", 158: "chip_therapy",
    159: "chip_mutation", 160: "chip_desintegration", 161: "chip_transmutation",
    162: "chip_grapple", 163: "chip_boxing_glove", 166: "chip_tactician_bulb",
    167: "chip_savant_bulb", 168: "chip_serum", 169: "chip_crushing",
    170: "chip_brainwashing", 171: "chip_arsenic", 172: "chip_bramble",
    173: "chip_dome", 174: "chip_manumission", 175: "weapon_explorer_rifle",
    180: "weapon_lightninger", 182: "weapon_neutrino", 184: "weapon_bazooka",
    187: "weapon_dark_katana", 225: "weapon_enhanced_lightninger",
    226: "weapon_unstable_destroyer", 276: "chip_prism", 277: "weapon_sword",
    278: "weapon_heavy_sword",
    # Components
    290: "core", 291: "core2", 292: "core3",
    293: "battery", 294: "iron_plate", 295: "amazonite_plate",
    296: "obsidian_plate", 297: "spring", 298: "copper_spring",
    299: "elinvar_spring", 300: "ssd", 301: "nuclear_core",
    302: "fan", 303: "sdcard", 304: "cd",
    305: "neural_core", 306: "neural_core_pro", 307: "power_supply",
    308: "chiyembekezo", 309: "uzoma", 310: "kirabo",
    311: "limbani", 312: "thokozani", 313: "ram",
    314: "ram2", 315: "ram3", 316: "motherboard",
    317: "propulsor", 318: "propulsor2", 319: "morus",
    320: "hylocereus", 321: "apple", 322: "nephelium",
    323: "blue_mango", 324: "watercooling", 374: "soursop",
    375: "hokajin", 381: "motherboard2", 382: "motherboard3",
    383: "switch", 384: "switch2", 385: "rgb",
    406: "recovery_core", 407: "recovery_ram",
    408: "weapon_odachi", 409: "weapon_excalibur", 410: "weapon_scythe",
    411: "chip_shuriken", 412: "chip_kemuridama", 413: "chip_fire_ball",
    414: "chip_trebuchet", 415: "chip_awakening", 416: "chip_thunder",
    417: "chip_kill", 418: "chip_apocalypse", 419: "chip_divine_protection",
    425: "chip_exasperation", 428: "weapon_quantum_rifle",
}


def get_item_name(item_template_id: int) -> str:
    """Get human-readable item name from item template ID (unified namespace).

    Strips the type prefix (weapon_, chip_) and replaces underscores with spaces.
    Returns 'unknown_<id>' for unmapped IDs.
    """
    raw = ITEM_TEMPLATES.get(item_template_id)
    if raw is None:
        return f"unknown_{item_template_id}"
    # Strip type prefix for readability
    for prefix in ("weapon_", "chip_", "component_"):
        if raw.startswith(prefix):
            return raw[len(prefix):].replace("_", " ")
    return raw.replace("_", " ")
