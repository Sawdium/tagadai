"""
Leek observation and discovery operations.
"""

from datetime import datetime
from typing import Optional


class LeekRepository:
    """Repository for leek observations and discovery."""

    def __init__(self, connect_fn, get_level_bracket_counts_fn=None, get_level_301_ratio_fn=None):
        self._connect = connect_fn
        self._get_level_bracket_counts = get_level_bracket_counts_fn
        self._get_level_301_ratio = get_level_301_ratio_fn

    def extract_and_save_leek_observations(self, fight_id: int, fight_data: dict) -> list[int]:
        """
        Extract leek observations from fight data and save to DB.
        Returns list of newly discovered leek IDs.
        """
        winner = fight_data.get("winner", -1)
        fight_type = fight_data.get("type", -1)
        context = fight_data.get("context", -1)

        # Build name → {real_id, talent, farmer_id} map from outer leeks
        outer_leeks = fight_data.get("leeks1", []) + fight_data.get("leeks2", [])
        name_to_outer = {}
        for leek in outer_leeks:
            name = leek.get("name")
            if name:
                name_to_outer[name] = {
                    "id": leek.get("id"),
                    "talent": leek.get("talent", 0),
                    "farmer": leek.get("farmer"),
                }

        # Build name → {td, tb, dead} map from report
        report = fight_data.get("report", {})
        report_leeks = report.get("leeks1", []) + report.get("leeks2", [])
        name_to_report = {}
        for leek in report_leeks:
            name = leek.get("name")
            if name:
                name_to_report[name] = {
                    "td": leek.get("td", 0),
                    "tb": leek.get("tb", 0),
                    "dead": leek.get("dead", False),
                }

        # Get inner leeks with combat stats
        data = fight_data.get("data", {})
        inner_leeks = data.get("leeks", [])

        if not inner_leeks:
            return []

        now = datetime.now().isoformat()
        new_leeks = []

        with self._connect() as conn:
            for leek in inner_leeks:
                if leek.get("summon", False):
                    continue

                name = leek.get("name")
                if not name:
                    continue

                outer = name_to_outer.get(name, {})
                real_leek_id = outer.get("id")
                if not real_leek_id:
                    continue

                report_data = name_to_report.get(name, {})
                team = leek.get("team", 0)
                won = (winner == team)

                # Check if this leek is new
                cursor = conn.execute(
                    "SELECT 1 FROM leek_observations WHERE leek_id = ? LIMIT 1",
                    (real_leek_id,)
                )
                if cursor.fetchone() is None:
                    new_leeks.append(real_leek_id)

                conn.execute(
                    """INSERT OR REPLACE INTO leek_observations
                       (fight_id, leek_id, farmer_id, level, talent, team, won,
                        life, strength, agility, wisdom, resistance, magic, science, frequency,
                        tp, mp, starting_cell, damage_dealt, damage_blocked, dead,
                        fight_context, fight_type, observed_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        fight_id,
                        real_leek_id,
                        outer.get("farmer") or leek.get("farmer"),
                        leek.get("level", 0),
                        outer.get("talent", 0),
                        team,
                        won,
                        leek.get("life", 0),
                        leek.get("strength", 0),
                        leek.get("agility", 0),
                        leek.get("wisdom", 0),
                        leek.get("resistance", 0),
                        leek.get("magic", 0),
                        leek.get("science", 0),
                        leek.get("frequency", 0),
                        leek.get("tp", 0),
                        leek.get("mp", 0),
                        leek.get("cellPos", 0),
                        report_data.get("td", 0),
                        report_data.get("tb", 0),
                        report_data.get("dead", False),
                        context,
                        fight_type,
                        now,
                    ),
                )

        return new_leeks

    def add_to_discovery_queue(
        self,
        leek_id: int,
        farmer_id: int,
        level: int,
        priority_score: float,
        discovered_in_fight: int
    ):
        """Add a leek to the discovery queue for future history scraping."""
        with self._connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO leek_discovery_queue
                   (leek_id, farmer_id, level, priority_score, discovered_in_fight, added_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (leek_id, farmer_id, level, priority_score, discovered_in_fight,
                 datetime.now().isoformat()),
            )

    def peek_from_discovery_queue(self) -> Optional[tuple[int, int, int]]:
        """Peek next leek from discovery queue. Returns (leek_id, farmer_id, level) or None."""
        with self._connect() as conn:
            cursor = conn.execute(
                """SELECT leek_id, farmer_id, level FROM leek_discovery_queue
                   WHERE leek_id NOT IN (SELECT player_id FROM scraped_players WHERE player_type = 'leek')
                   ORDER BY priority_score DESC
                   LIMIT 1"""
            )
            row = cursor.fetchone()
            return (row[0], row[1], row[2]) if row else None

    def remove_from_discovery_queue(self, leek_id: int):
        """Remove a leek from the discovery queue."""
        with self._connect() as conn:
            conn.execute("DELETE FROM leek_discovery_queue WHERE leek_id = ?", (leek_id,))

    def pop_from_discovery_queue(self) -> Optional[tuple[int, int, int]]:
        """Legacy: Get and remove next leek."""
        result = self.peek_from_discovery_queue()
        if result:
            self.remove_from_discovery_queue(result[0])
        return result

    def get_leek_stats(self, leek_id: int) -> Optional[dict]:
        """Get aggregated stats for a leek from observations."""
        with self._connect() as conn:
            cursor = conn.execute(
                """SELECT
                       level,
                       COUNT(*) as fights,
                       SUM(won) as wins,
                       AVG(strength) as avg_strength,
                       AVG(agility) as avg_agility,
                       MAX(observed_at) as last_seen
                   FROM leek_observations
                   WHERE leek_id = ?
                   GROUP BY leek_id""",
                (leek_id,)
            )
            row = cursor.fetchone()
            if row:
                return {
                    "level": row[0],
                    "fights": row[1],
                    "wins": row[2],
                    "win_rate": row[2] / row[1] if row[1] > 0 else 0,
                    "avg_strength": row[3],
                    "avg_agility": row[4],
                    "last_seen": row[5],
                }
            return None

    def get_level_stats(self, level: int) -> Optional[dict]:
        """Get cached stats for a level."""
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT * FROM level_stats WHERE level = ?", (level,)
            )
            row = cursor.fetchone()
            if row:
                return {
                    "level": row[0],
                    "count": row[1],
                    "mean_talent": row[2],
                    "std_talent": row[3],
                }
            return None

    def update_level_stats(self):
        """Recalculate level statistics from observations."""
        with self._connect() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO level_stats
                (level, count, mean_talent, std_talent, mean_strength, mean_agility,
                 mean_wisdom, mean_resistance, mean_magic, win_rate, updated_at)
                SELECT
                    level,
                    COUNT(DISTINCT leek_id) as count,
                    AVG(strength + agility + wisdom + resistance + magic + science) as mean_talent,
                    0 as std_talent,
                    AVG(strength) as mean_strength,
                    AVG(agility) as mean_agility,
                    AVG(wisdom) as mean_wisdom,
                    AVG(resistance) as mean_resistance,
                    AVG(magic) as mean_magic,
                    AVG(CASE WHEN won THEN 1.0 ELSE 0.0 END) as win_rate,
                    datetime('now')
                FROM leek_observations
                WHERE level > 0
                GROUP BY level
            """)

    def calculate_priority_score(self, level: int, total_stats: int, win_rate: float) -> float:
        """Calculate priority score for a leek based on DATA DIVERSITY needs."""
        if not self._get_level_bracket_counts or not self._get_level_301_ratio:
            return 100.0  # Default priority

        bracket_counts = self._get_level_bracket_counts()

        if level <= 50:
            bracket = "1-50"
        elif level <= 100:
            bracket = "51-100"
        elif level <= 150:
            bracket = "101-150"
        elif level <= 200:
            bracket = "151-200"
        elif level <= 250:
            bracket = "201-250"
        elif level <= 300:
            bracket = "251-300"
        else:
            bracket = "301"

        bracket_data = bracket_counts.get(bracket, {"count": 0})
        bracket_count = bracket_data.get("count", 0)
        total_obs = sum(b.get("count", 0) for b in bracket_counts.values())

        if total_obs == 0:
            diversity_bonus = 100
        else:
            expected_count = total_obs / 7
            if bracket_count < expected_count:
                scarcity_ratio = expected_count / max(bracket_count, 1)
                diversity_bonus = min(500, 100 * scarcity_ratio)
            else:
                excess_ratio = bracket_count / expected_count
                diversity_bonus = max(10, 100 / excess_ratio)

        level_301_ratio = self._get_level_301_ratio()
        if level == 301 and level_301_ratio > 0.3:
            diversity_bonus = diversity_bonus * (1 - level_301_ratio)

        win_bonus = win_rate * 20
        return diversity_bonus + win_bonus
