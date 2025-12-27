"""
Metadata extraction operations.
"""

import json
from datetime import datetime
from typing import Optional
from collections import defaultdict


class MetadataRepository:
    """Repository for metadata extraction."""

    def __init__(self, connect_fn):
        self._connect = connect_fn

    def save_fight_metadata(self, metadata_list: list[dict]) -> int:
        """Save extracted fight metadata to database. Returns number of records saved."""
        if not metadata_list:
            return 0

        now = datetime.now().isoformat()
        saved = 0

        with self._connect() as conn:
            for meta in metadata_list:
                conn.execute(
                    """INSERT OR REPLACE INTO fight_leek_metadata
                       (fight_id, leek_id, entity_id, level,
                        strength, agility, magic, resistance, wisdom, science, frequency, life, tp, mp,
                        weapons_used, chips_used,
                        weapon_actions, chip_actions, move_actions, summon_actions,
                        physical_damage, magic_damage, poison_damage, heal_done,
                        total_tp_spent, total_mp_spent, total_cells_moved, turns_alive,
                        extracted_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        meta.get("fight_id"),
                        meta.get("leek_id"),
                        meta.get("entity_id"),
                        meta.get("level", 0),
                        meta.get("strength", 0),
                        meta.get("agility", 0),
                        meta.get("magic", 0),
                        meta.get("resistance", 0),
                        meta.get("wisdom", 0),
                        meta.get("science", 0),
                        meta.get("frequency", 0),
                        meta.get("life", 0),
                        meta.get("tp", 0),
                        meta.get("mp", 0),
                        json.dumps(meta.get("weapons_used", [])),
                        json.dumps(meta.get("chips_used", [])),
                        meta.get("weapon_actions", 0),
                        meta.get("chip_actions", 0),
                        meta.get("move_actions", 0),
                        meta.get("summon_actions", 0),
                        meta.get("physical_damage", 0),
                        meta.get("magic_damage", 0),
                        meta.get("poison_damage", 0),
                        meta.get("heal_done", 0),
                        meta.get("total_tp_spent", 0),
                        meta.get("total_mp_spent", 0),
                        meta.get("total_cells_moved", 0),
                        meta.get("turns_alive", 0),
                        now,
                    ),
                )
                saved += 1

        return saved

    def get_metadata_extraction_progress(self) -> dict:
        """Get metadata extraction progress."""
        with self._connect() as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM fights")
            total_fights = cursor.fetchone()[0]

            cursor = conn.execute(
                "SELECT COUNT(DISTINCT fight_id) FROM fight_leek_metadata"
            )
            extracted_fights = cursor.fetchone()[0]

            cursor = conn.execute(
                "SELECT value FROM metadata_extraction_state WHERE key = 'last_fight_id'"
            )
            row = cursor.fetchone()
            last_fight_id = int(row[0]) if row else 0

            cursor = conn.execute(
                "SELECT value FROM metadata_extraction_state WHERE key = 'last_extraction_time'"
            )
            row = cursor.fetchone()
            last_extraction_time = row[0] if row else None

            return {
                "total_fights": total_fights,
                "extracted_fights": extracted_fights,
                "remaining_fights": total_fights - extracted_fights,
                "progress_percent": round(
                    extracted_fights / total_fights * 100, 2
                ) if total_fights > 0 else 0,
                "last_fight_id": last_fight_id,
                "last_extraction_time": last_extraction_time,
            }

    def set_metadata_extraction_state(self, key: str, value: str):
        """Set metadata extraction state value."""
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO metadata_extraction_state (key, value) VALUES (?, ?)",
                (key, value),
            )

    def get_fights_needing_metadata(self, batch_size: int = 100) -> list[tuple[int, dict]]:
        """Get fights that don't have metadata extracted yet."""
        with self._connect() as conn:
            cursor = conn.execute(
                """SELECT f.fight_id, f.json_data
                   FROM fights f
                   LEFT JOIN fight_leek_metadata m ON f.fight_id = m.fight_id
                   WHERE m.fight_id IS NULL
                   ORDER BY f.fight_id
                   LIMIT ?""",
                (batch_size,)
            )
            return [(row[0], json.loads(row[1])) for row in cursor.fetchall()]

    def get_equipment_usage_by_level(
        self,
        fight_type: Optional[int] = None,
        min_sample_size: int = 10,
    ) -> dict[str, dict]:
        """Get equipment usage statistics by level bucket."""
        with self._connect() as conn:
            type_filter = ""
            params: list = []
            if fight_type is not None:
                type_filter = "AND o.fight_type = ?"
                params.append(fight_type)

            cursor = conn.execute(f"""
                SELECT
                    CASE
                        WHEN o.level = 301 THEN '301'
                        ELSE CAST(((o.level - 1) / 10) * 10 + 1 AS TEXT) || '-' ||
                             CAST(((o.level - 1) / 10) * 10 + 10 AS TEXT)
                    END as bucket,
                    m.weapons_used,
                    m.chips_used,
                    COUNT(*) as sample_count
                FROM fight_leek_metadata m
                JOIN leek_observations o ON m.fight_id = o.fight_id AND m.leek_id = o.leek_id
                WHERE o.level > 0 {type_filter}
                GROUP BY bucket, m.weapons_used, m.chips_used
            """, params)

            buckets: dict[str, dict] = defaultdict(lambda: {
                "weapons": defaultdict(int),
                "chips": defaultdict(int),
                "sample_size": 0,
            })

            for row in cursor:
                bucket = row[0]
                weapons = json.loads(row[1] or "[]")
                chips = json.loads(row[2] or "[]")
                count = row[3]

                buckets[bucket]["sample_size"] += count
                for w in weapons:
                    buckets[bucket]["weapons"][w] += count
                for c in chips:
                    buckets[bucket]["chips"][c] += count

            result = {}
            for bucket, data in buckets.items():
                if data["sample_size"] < min_sample_size:
                    continue

                sample = data["sample_size"]
                result[bucket] = {
                    "sample_size": sample,
                    "weapons": {
                        w: {"count": c, "pct": round(c / sample * 100, 1)}
                        for w, c in sorted(
                            data["weapons"].items(),
                            key=lambda x: x[1],
                            reverse=True
                        )[:20]
                    },
                    "chips": {
                        c: {"count": cnt, "pct": round(cnt / sample * 100, 1)}
                        for c, cnt in sorted(
                            data["chips"].items(),
                            key=lambda x: x[1],
                            reverse=True
                        )[:30]
                    },
                }

            return result

    def get_metadata_stats(self) -> dict:
        """Get metadata table statistics."""
        with self._connect() as conn:
            cursor = conn.execute("""
                SELECT
                    COUNT(*) as total_records,
                    COUNT(DISTINCT fight_id) as unique_fights,
                    COUNT(DISTINCT leek_id) as unique_leeks,
                    SUM(weapon_actions) as total_weapon_actions,
                    SUM(chip_actions) as total_chip_actions,
                    AVG(turns_alive) as avg_turns_alive
                FROM fight_leek_metadata
            """)
            row = cursor.fetchone()
            return {
                "total_records": row[0] or 0,
                "unique_fights": row[1] or 0,
                "unique_leeks": row[2] or 0,
                "total_weapon_actions": row[3] or 0,
                "total_chip_actions": row[4] or 0,
                "avg_turns_alive": round(row[5] or 0, 2),
            }

    def get_equipment_cooccurrence(
        self,
        level_bucket: Optional[str] = None,
        fight_type: Optional[int] = None,
        min_cooccurrence: int = 10,
    ) -> dict:
        """Compute equipment co-occurrence matrix."""
        with self._connect() as conn:
            query = """
                SELECT m.weapons_used, m.chips_used
                FROM fight_leek_metadata m
            """
            params: list = []
            conditions = []

            if level_bucket:
                if level_bucket == "301":
                    conditions.append("m.level = 301")
                else:
                    parts = level_bucket.split("-")
                    if len(parts) == 2:
                        conditions.append("m.level >= ? AND m.level <= ?")
                        params.extend([int(parts[0]), int(parts[1])])

            if fight_type is not None:
                query += " JOIN fights f ON m.fight_id = f.fight_id"
                conditions.append("f.fight_type = ?")
                params.append(fight_type)

            if conditions:
                query += " WHERE " + " AND ".join(conditions)

            cursor = conn.execute(query, params)

            cooccurrence: dict[tuple, int] = defaultdict(int)
            item_counts: dict[str, int] = defaultdict(int)

            for row in cursor:
                weapons = json.loads(row[0] or "[]")
                chips = json.loads(row[1] or "[]")

                items = [f"W:{w}" for w in set(weapons)] + [f"C:{c}" for c in set(chips)]

                for item in items:
                    item_counts[item] += 1

                for i, item_a in enumerate(items):
                    for item_b in items[i + 1:]:
                        pair = tuple(sorted([item_a, item_b]))
                        cooccurrence[pair] += 1

            top_items = sorted(item_counts.items(), key=lambda x: x[1], reverse=True)[:30]
            item_list = [item for item, _ in top_items]

            matrix = []
            for item_a in item_list:
                row = []
                for item_b in item_list:
                    if item_a == item_b:
                        row.append(item_counts.get(item_a, 0))
                    else:
                        pair = tuple(sorted([item_a, item_b]))
                        count = cooccurrence.get(pair, 0)
                        row.append(count if count >= min_cooccurrence else 0)
                matrix.append(row)

            return {
                "items": item_list,
                "matrix": matrix,
                "counts": dict(item_counts),
                "level_bucket": level_bucket,
                "fight_type": fight_type,
            }
