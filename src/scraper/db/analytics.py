"""
Statistics and analytics operations.
"""

from typing import Optional

from .base import DATA_FRESHNESS_CUTOFF


class AnalyticsRepository:
    """Repository for statistics and analytics."""

    def __init__(self, connect_fn, db_path):
        self._connect = connect_fn
        self.db_path = db_path

    def get_stats(self) -> dict:
        """Get database statistics."""
        with self._connect() as conn:
            stats = {}

            cursor = conn.execute("SELECT COUNT(*) FROM fights")
            stats["total_fights"] = cursor.fetchone()[0]

            cursor = conn.execute(
                "SELECT fight_type, COUNT(*) FROM fights GROUP BY fight_type"
            )
            stats["by_type"] = {row[0]: row[1] for row in cursor}

            cursor = conn.execute(
                "SELECT context, COUNT(*) FROM fights GROUP BY context"
            )
            stats["by_context"] = {row[0]: row[1] for row in cursor}

            cursor = conn.execute(
                """SELECT COUNT(*) FROM fight_queue
                   WHERE fight_id NOT IN (SELECT fight_id FROM fights)"""
            )
            stats["queue_size"] = cursor.fetchone()[0]

            cursor = conn.execute("SELECT COUNT(*) FROM scraped_players")
            stats["players_scraped"] = cursor.fetchone()[0]

            stats["db_size_mb"] = round(self.db_path.stat().st_size / 1024 / 1024, 2)

            cursor = conn.execute("SELECT COUNT(*) FROM leek_observations")
            stats["leek_observations"] = cursor.fetchone()[0]

            cursor = conn.execute("SELECT COUNT(DISTINCT leek_id) FROM leek_observations")
            stats["unique_leeks"] = cursor.fetchone()[0]

            cursor = conn.execute("SELECT COUNT(*) FROM leek_discovery_queue")
            stats["discovery_queue"] = cursor.fetchone()[0]

            return stats

    def get_level_distribution(self, fight_type: Optional[int] = None) -> list[dict]:
        """Get fight count per level."""
        with self._connect() as conn:
            if fight_type is not None:
                cursor = conn.execute(
                    """SELECT level, COUNT(*) as count,
                              SUM(won) as wins,
                              COUNT(DISTINCT leek_id) as unique_leeks
                       FROM leek_observations
                       WHERE fight_type = ?
                       GROUP BY level
                       ORDER BY level""",
                    (fight_type,)
                )
            else:
                cursor = conn.execute(
                    """SELECT level, COUNT(*) as count,
                              SUM(won) as wins,
                              COUNT(DISTINCT leek_id) as unique_leeks
                       FROM leek_observations
                       GROUP BY level
                       ORDER BY level"""
                )
            return [
                {"level": row[0], "count": row[1], "wins": row[2], "unique_leeks": row[3]}
                for row in cursor
            ]

    def get_stats_by_level(self, level: int, fight_type: Optional[int] = None) -> dict:
        """Get detailed stats distribution for a specific level."""
        with self._connect() as conn:
            params = [level]
            type_filter = ""
            if fight_type is not None:
                type_filter = "AND fight_type = ?"
                params.append(fight_type)

            cursor = conn.execute(f"""
                SELECT
                    COUNT(*) as observations,
                    COUNT(DISTINCT leek_id) as unique_leeks,
                    AVG(life) as avg_life,
                    AVG(strength) as avg_strength,
                    AVG(agility) as avg_agility,
                    AVG(wisdom) as avg_wisdom,
                    AVG(resistance) as avg_resistance,
                    AVG(magic) as avg_magic,
                    AVG(science) as avg_science,
                    AVG(frequency) as avg_frequency,
                    AVG(tp) as avg_tp,
                    AVG(mp) as avg_mp,
                    AVG(CASE WHEN won THEN 1.0 ELSE 0.0 END) as win_rate,
                    MIN(strength) as min_strength, MAX(strength) as max_strength,
                    MIN(agility) as min_agility, MAX(agility) as max_agility,
                    MIN(wisdom) as min_wisdom, MAX(wisdom) as max_wisdom,
                    MIN(resistance) as min_resistance, MAX(resistance) as max_resistance,
                    MIN(magic) as min_magic, MAX(magic) as max_magic
                FROM leek_observations
                WHERE level = ? {type_filter}
            """, params)

            row = cursor.fetchone()
            if row and row[0] > 0:
                return {
                    "level": level,
                    "observations": row[0],
                    "unique_leeks": row[1],
                    "avg_stats": {
                        "life": round(row[2] or 0, 1),
                        "strength": round(row[3] or 0, 1),
                        "agility": round(row[4] or 0, 1),
                        "wisdom": round(row[5] or 0, 1),
                        "resistance": round(row[6] or 0, 1),
                        "magic": round(row[7] or 0, 1),
                        "science": round(row[8] or 0, 1),
                        "frequency": round(row[9] or 0, 1),
                        "tp": round(row[10] or 0, 1),
                        "mp": round(row[11] or 0, 1),
                    },
                    "win_rate": round(row[12] or 0, 3),
                    "stat_ranges": {
                        "strength": [row[13] or 0, row[14] or 0],
                        "agility": [row[15] or 0, row[16] or 0],
                        "wisdom": [row[17] or 0, row[18] or 0],
                        "resistance": [row[19] or 0, row[20] or 0],
                        "magic": [row[21] or 0, row[22] or 0],
                    }
                }
            return {"level": level, "observations": 0}

    def get_popular_builds(self, level: int, fight_type: Optional[int] = None, limit: int = 5) -> list[dict]:
        """Get the most common stat distributions for a level."""
        with self._connect() as conn:
            params = [level]
            type_filter = ""
            if fight_type is not None:
                type_filter = "AND fight_type = ?"
                params.append(fight_type)

            cursor = conn.execute(f"""
                SELECT
                    CASE
                        WHEN strength > agility AND strength > magic THEN 'Strength'
                        WHEN agility > strength AND agility > magic THEN 'Agility'
                        WHEN magic > strength AND magic > agility THEN 'Magic'
                        ELSE 'Balanced'
                    END as build_type,
                    COUNT(*) as count,
                    AVG(strength) as avg_str,
                    AVG(agility) as avg_agi,
                    AVG(magic) as avg_mag,
                    AVG(wisdom) as avg_wis,
                    AVG(resistance) as avg_res,
                    AVG(CASE WHEN won THEN 1.0 ELSE 0.0 END) as win_rate
                FROM leek_observations
                WHERE level = ? {type_filter}
                GROUP BY build_type
                ORDER BY count DESC
                LIMIT ?
            """, params + [limit])

            return [
                {
                    "build_type": row[0],
                    "count": row[1],
                    "avg_stats": {
                        "strength": round(row[2] or 0, 1),
                        "agility": round(row[3] or 0, 1),
                        "magic": round(row[4] or 0, 1),
                        "wisdom": round(row[5] or 0, 1),
                        "resistance": round(row[6] or 0, 1),
                    },
                    "win_rate": round(row[7] or 0, 3),
                }
                for row in cursor
            ]

    def get_fight_type_distribution(self) -> dict:
        """Get fight counts by type."""
        with self._connect() as conn:
            cursor = conn.execute("""
                SELECT fight_type, COUNT(DISTINCT fight_id) as fights,
                       COUNT(*) as observations
                FROM leek_observations
                GROUP BY fight_type
            """)
            return {
                row[0]: {"fights": row[1], "observations": row[2]}
                for row in cursor
            }

    def get_context_distribution(self) -> dict:
        """Get fight counts by context."""
        with self._connect() as conn:
            cursor = conn.execute("""
                SELECT fight_context, COUNT(DISTINCT fight_id) as fights,
                       COUNT(*) as observations
                FROM leek_observations
                GROUP BY fight_context
            """)
            return {
                row[0]: {"fights": row[1], "observations": row[2]}
                for row in cursor
            }

    def get_level_301_ratio(self) -> float:
        """Get the ratio of level 301 observations to total observations."""
        with self._connect() as conn:
            cursor = conn.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN level = 301 THEN 1 ELSE 0 END) as level_301
                FROM leek_observations
            """)
            row = cursor.fetchone()
            total = row[0] or 0
            level_301 = row[1] or 0
            return level_301 / total if total > 0 else 0.0

    def get_level_bracket_counts(self) -> dict:
        """Get observation counts by level brackets."""
        with self._connect() as conn:
            cursor = conn.execute("""
                SELECT
                    CASE
                        WHEN level <= 50 THEN '1-50'
                        WHEN level <= 100 THEN '51-100'
                        WHEN level <= 150 THEN '101-150'
                        WHEN level <= 200 THEN '151-200'
                        WHEN level <= 250 THEN '201-250'
                        WHEN level <= 300 THEN '251-300'
                        ELSE '301'
                    END as bracket,
                    COUNT(*) as count,
                    COUNT(DISTINCT leek_id) as unique_leeks
                FROM leek_observations
                GROUP BY bracket
                ORDER BY MIN(level)
            """)
            return {
                row[0]: {"count": row[1], "unique_leeks": row[2]}
                for row in cursor
            }

    def get_fight_date_distribution(self, bucket: str = "month") -> list[dict]:
        """Get fight counts grouped by date bucket."""
        with self._connect() as conn:
            if bucket == "day":
                date_format = "%Y-%m-%d"
            elif bucket == "week":
                date_format = "%Y-W%W"
            else:
                date_format = "%Y-%m"

            cursor = conn.execute(f"""
                SELECT
                    strftime('{date_format}', fight_date, 'unixepoch') as period,
                    COUNT(*) as count,
                    AVG(
                        CASE
                            WHEN team2_levels = 0 THEN team1_levels * 1.0 / NULLIF(team1_levels / 301 + 1, 0)
                            ELSE (team1_levels + team2_levels) * 1.0 /
                                CASE fight_type
                                    WHEN 0 THEN 2
                                    WHEN 1 THEN 4
                                    WHEN 2 THEN 6
                                    ELSE 10
                                END
                        END
                    ) as avg_level,
                    MIN(fight_date) as min_date,
                    MAX(fight_date) as max_date
                FROM fights
                WHERE fight_date IS NOT NULL
                GROUP BY period
                ORDER BY period ASC
                LIMIT 100
            """)

            return [
                {
                    "period": row[0],
                    "count": row[1],
                    "avg_level": round(row[2] or 0, 1),
                    "min_date": row[3],
                    "max_date": row[4],
                }
                for row in cursor
                if row[0]
            ]

    def get_fight_date_range(self) -> dict:
        """Get the date range of stored fights."""
        with self._connect() as conn:
            cursor = conn.execute("""
                SELECT
                    MIN(fight_date) as oldest,
                    MAX(fight_date) as newest,
                    COUNT(*) as total,
                    COUNT(fight_date) as with_date
                FROM fights
            """)
            row = cursor.fetchone()
            return {
                "oldest_date": row[0],
                "newest_date": row[1],
                "total_fights": row[2] or 0,
                "fights_with_date": row[3] or 0,
            }

    def get_data_freshness_stats(self) -> dict:
        """Get counts of old vs recent data based on the Feb 20, 2024 cutoff."""
        with self._connect() as conn:
            cursor = conn.execute("""
                SELECT
                    COUNT(*) FILTER (WHERE fight_date IS NULL) as no_date,
                    COUNT(*) FILTER (WHERE fight_date < ?) as old_data,
                    COUNT(*) FILTER (WHERE fight_date >= ?) as recent_data,
                    COUNT(*) as total
                FROM fights
            """, (DATA_FRESHNESS_CUTOFF, DATA_FRESHNESS_CUTOFF))
            row = cursor.fetchone()
            total = row[3] or 1
            old_count = row[1] or 0
            recent_count = row[2] or 0
            no_date_count = row[0] or 0

            return {
                "cutoff_date": DATA_FRESHNESS_CUTOFF,
                "cutoff_label": "2024-02-20",
                "old_count": old_count,
                "recent_count": recent_count,
                "no_date_count": no_date_count,
                "total": total,
                "recent_ratio": round(recent_count / total, 3) if total > 0 else 0,
                "old_ratio": round(old_count / total, 3) if total > 0 else 0,
            }
