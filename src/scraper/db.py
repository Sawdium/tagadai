"""
SQLite database for storing scraped fight data.
"""

import sqlite3
import json
from pathlib import Path
from datetime import datetime
from typing import Optional, Iterator
from dataclasses import dataclass


# Default database location
DEFAULT_DB_PATH = Path(__file__).parent.parent.parent / "data" / "fights.db"

# Data freshness cutoff: Feb 20, 2024 - important gameplay change (item restrictions)
# Data before this date may not be representative of current game balance
DATA_FRESHNESS_CUTOFF = 1708387200  # 2024-02-20 00:00:00 UTC


@dataclass
class FightRecord:
    """A fight record from the database."""
    fight_id: int
    json_data: dict
    winner: int
    fight_type: int  # 0=solo, 1=farmer, 2=team
    context: int  # 0=test, 1=challenge, 2=garden, 3=tournament
    team1_levels: int
    team2_levels: int
    duration: int  # turns
    fight_date: Optional[int]  # Unix timestamp of when fight occurred
    downloaded_at: str


class FightDatabase:
    """SQLite database for fight storage."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        """Create a connection with proper settings for concurrent access."""
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA busy_timeout=30000;")  # 30 second timeout
        return conn

    def _init_db(self):
        """Initialize database schema."""
        with self._connect() as conn:
            # Enable WAL mode for better concurrent access
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.executescript("""
                -- Main fights table (fight_date added via migration for existing DBs)
                CREATE TABLE IF NOT EXISTS fights (
                    fight_id INTEGER PRIMARY KEY,
                    json_data TEXT NOT NULL,
                    winner INTEGER,
                    fight_type INTEGER,
                    context INTEGER,
                    team1_levels INTEGER,
                    team2_levels INTEGER,
                    duration INTEGER,
                    fight_date INTEGER,  -- Unix timestamp of when fight occurred
                    downloaded_at TEXT NOT NULL
                );

                -- Scraper progress tracking
                CREATE TABLE IF NOT EXISTS scraper_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                -- Discovered fight IDs queue
                CREATE TABLE IF NOT EXISTS fight_queue (
                    fight_id INTEGER PRIMARY KEY,
                    source TEXT,  -- e.g., "leek:64172" or "farmer:512"
                    priority INTEGER DEFAULT 0,
                    added_at TEXT NOT NULL
                );

                -- Players we've fetched history for
                CREATE TABLE IF NOT EXISTS scraped_players (
                    player_type TEXT,  -- "leek" or "farmer"
                    player_id INTEGER,
                    talent INTEGER,
                    last_scraped TEXT,
                    PRIMARY KEY (player_type, player_id)
                );

                -- Index for filtering
                CREATE INDEX IF NOT EXISTS idx_fights_type ON fights(fight_type);
                CREATE INDEX IF NOT EXISTS idx_fights_context ON fights(context);
                CREATE INDEX IF NOT EXISTS idx_fights_winner ON fights(winner);
                CREATE INDEX IF NOT EXISTS idx_queue_priority ON fight_queue(priority DESC);

                -- Leek observations from fights (authoritative stats at fight time)
                -- Indexed by fight_id + leek_id since same leek can have different stats in different fights
                CREATE TABLE IF NOT EXISTS leek_observations (
                    fight_id INTEGER NOT NULL,
                    leek_id INTEGER NOT NULL,
                    farmer_id INTEGER,
                    level INTEGER,
                    talent INTEGER,  -- From outer leeks (leeks1/leeks2), authoritative
                    team INTEGER,
                    won BOOLEAN,
                    -- Combat stats at fight time (from data.leeks)
                    life INTEGER,
                    strength INTEGER,
                    agility INTEGER,
                    wisdom INTEGER,
                    resistance INTEGER,
                    magic INTEGER,
                    science INTEGER,
                    frequency INTEGER,
                    tp INTEGER,
                    mp INTEGER,
                    starting_cell INTEGER,  -- cellPos from data.leeks
                    -- Fight outcome stats (from report)
                    damage_dealt INTEGER,  -- td from report
                    damage_blocked INTEGER,  -- tb from report
                    dead BOOLEAN,  -- from report
                    -- Metadata
                    fight_context INTEGER,  -- 0=test, 1=challenge, 2=garden, 3=tournament
                    fight_type INTEGER,  -- 0=solo, 1=farmer, 2=team
                    observed_at TEXT NOT NULL,
                    PRIMARY KEY (fight_id, leek_id)
                );

                -- Indexes for leek analysis
                CREATE INDEX IF NOT EXISTS idx_leek_obs_leek ON leek_observations(leek_id);
                CREATE INDEX IF NOT EXISTS idx_leek_obs_level ON leek_observations(level);
                CREATE INDEX IF NOT EXISTS idx_leek_obs_farmer ON leek_observations(farmer_id);

                -- Aggregated level statistics (updated periodically)
                CREATE TABLE IF NOT EXISTS level_stats (
                    level INTEGER PRIMARY KEY,
                    count INTEGER DEFAULT 0,
                    mean_talent REAL DEFAULT 0,
                    std_talent REAL DEFAULT 0,
                    mean_strength REAL DEFAULT 0,
                    mean_agility REAL DEFAULT 0,
                    mean_wisdom REAL DEFAULT 0,
                    mean_resistance REAL DEFAULT 0,
                    mean_magic REAL DEFAULT 0,
                    win_rate REAL DEFAULT 0,
                    updated_at TEXT
                );

                -- Discovery queue for leeks found in fights
                CREATE TABLE IF NOT EXISTS leek_discovery_queue (
                    leek_id INTEGER PRIMARY KEY,
                    farmer_id INTEGER,
                    level INTEGER,
                    priority_score REAL DEFAULT 0,
                    discovered_in_fight INTEGER,
                    added_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_discovery_priority ON leek_discovery_queue(priority_score DESC);

                -- Fight metadata for build analysis (equipment usage)
                CREATE TABLE IF NOT EXISTS fight_leek_metadata (
                    fight_id INTEGER NOT NULL,
                    leek_id INTEGER NOT NULL,
                    entity_id INTEGER,
                    level INTEGER DEFAULT 0,  -- Individual leek level

                    -- Leek stats (from fight start)
                    strength INTEGER DEFAULT 0,
                    agility INTEGER DEFAULT 0,
                    magic INTEGER DEFAULT 0,
                    resistance INTEGER DEFAULT 0,
                    wisdom INTEGER DEFAULT 0,
                    science INTEGER DEFAULT 0,
                    frequency INTEGER DEFAULT 0,
                    life INTEGER DEFAULT 0,
                    tp INTEGER DEFAULT 0,
                    mp INTEGER DEFAULT 0,

                    -- Equipment used (JSON arrays)
                    weapons_used TEXT,  -- JSON array of weapon IDs
                    chips_used TEXT,    -- JSON array of chip IDs

                    -- Usage counts
                    weapon_actions INTEGER DEFAULT 0,
                    chip_actions INTEGER DEFAULT 0,
                    move_actions INTEGER DEFAULT 0,
                    summon_actions INTEGER DEFAULT 0,

                    -- Damage breakdown
                    physical_damage INTEGER DEFAULT 0,
                    magic_damage INTEGER DEFAULT 0,
                    poison_damage INTEGER DEFAULT 0,
                    heal_done INTEGER DEFAULT 0,

                    -- Efficiency
                    total_tp_spent INTEGER DEFAULT 0,
                    total_mp_spent INTEGER DEFAULT 0,
                    total_cells_moved INTEGER DEFAULT 0,
                    turns_alive INTEGER DEFAULT 0,

                    -- Metadata
                    extracted_at TEXT NOT NULL,

                    PRIMARY KEY (fight_id, leek_id)
                );

                CREATE INDEX IF NOT EXISTS idx_metadata_leek ON fight_leek_metadata(leek_id);

                -- Aggregated equipment statistics (cached, refreshable)
                CREATE TABLE IF NOT EXISTS equipment_stats (
                    level_bucket TEXT NOT NULL,  -- '1-10', '11-20', ..., '301'
                    fight_type INTEGER,          -- 0=solo, 1=farmer, 2=team, NULL=all
                    item_type TEXT NOT NULL,     -- 'weapon' or 'chip'
                    item_id INTEGER NOT NULL,
                    item_name TEXT,

                    -- Stats
                    use_count INTEGER DEFAULT 0,      -- Times used across all fights
                    leek_count INTEGER DEFAULT 0,     -- Unique leeks using this item
                    total_damage INTEGER DEFAULT 0,   -- Estimated damage from this item

                    -- Computed at refresh time
                    computed_at TEXT NOT NULL,

                    PRIMARY KEY (level_bucket, fight_type, item_type, item_id)
                );

                CREATE INDEX IF NOT EXISTS idx_equipment_bucket ON equipment_stats(level_bucket);
                CREATE INDEX IF NOT EXISTS idx_equipment_item ON equipment_stats(item_type, item_id);

                -- Metadata extraction progress tracking
                CREATE TABLE IF NOT EXISTS metadata_extraction_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                -- Migration: Add fight_date column if it doesn't exist
                -- SQLite doesn't have IF NOT EXISTS for ALTER TABLE, so we check first
            """)

            # Check if fight_date column exists and add if not
            cursor = conn.execute("PRAGMA table_info(fights)")
            columns = [row[1] for row in cursor.fetchall()]
            if 'fight_date' not in columns:
                conn.execute("ALTER TABLE fights ADD COLUMN fight_date INTEGER")

            # Create index on fight_date (after migration ensures column exists)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_fights_date ON fights(fight_date)")

            # Migration: Add level column to fight_leek_metadata if it doesn't exist
            cursor = conn.execute("PRAGMA table_info(fight_leek_metadata)")
            metadata_columns = [row[1] for row in cursor.fetchall()]
            if 'level' not in metadata_columns:
                conn.execute("ALTER TABLE fight_leek_metadata ADD COLUMN level INTEGER DEFAULT 0")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_metadata_level ON fight_leek_metadata(level)")

            # Migration: Add stat columns to fight_leek_metadata
            stat_columns = ['strength', 'agility', 'magic', 'resistance', 'wisdom', 'science', 'frequency', 'life', 'tp', 'mp']
            for col in stat_columns:
                if col not in metadata_columns:
                    conn.execute(f"ALTER TABLE fight_leek_metadata ADD COLUMN {col} INTEGER DEFAULT 0")

            conn.executescript("""
                -- Tournament exploration tracking
                CREATE TABLE IF NOT EXISTS tournament_exploration (
                    tournament_id INTEGER PRIMARY KEY,
                    tournament_type TEXT,  -- 'solo', 'farmer', 'team'
                    tournament_date INTEGER,  -- Unix timestamp
                    leeks_found INTEGER DEFAULT 0,
                    low_level_leeks INTEGER DEFAULT 0,  -- Level < 200
                    explored_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_tournament_date ON tournament_exploration(tournament_date DESC);
            """)

    def has_fight(self, fight_id: int) -> bool:
        """Check if a fight is already in the database."""
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT 1 FROM fights WHERE fight_id = ?", (fight_id,)
            )
            return cursor.fetchone() is not None

    def save_fight(self, fight_id: int, data: dict) -> bool:
        """Save a fight to the database. Returns True if saved, False if already exists."""
        if self.has_fight(fight_id):
            return False

        # Extract metadata for filtering
        winner = data.get("winner", -1)
        fight_type = data.get("type", -1)
        context = data.get("context", -1)
        fight_date = data.get("date")  # Unix timestamp when fight occurred

        # Calculate total levels
        team1_levels = sum(l.get("level", 0) for l in data.get("leeks1", []))
        team2_levels = sum(l.get("level", 0) for l in data.get("leeks2", []))

        # Count turns (find max NEW_TURN action)
        # Actions are nested under data["data"]["actions"]
        duration = 0
        fight_data = data.get("data", {})
        for action in fight_data.get("actions", []):
            if isinstance(action, list) and len(action) >= 2 and action[0] == 6:
                duration = max(duration, action[1])

        with self._connect() as conn:
            conn.execute(
                """INSERT INTO fights
                   (fight_id, json_data, winner, fight_type, context,
                    team1_levels, team2_levels, duration, fight_date, downloaded_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    fight_id,
                    json.dumps(data),
                    winner,
                    fight_type,
                    context,
                    team1_levels,
                    team2_levels,
                    duration,
                    fight_date,
                    datetime.now().isoformat(),
                ),
            )
        return True

    def get_fight(self, fight_id: int) -> Optional[FightRecord]:
        """Get a specific fight by ID."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM fights WHERE fight_id = ?", (fight_id,)
            )
            row = cursor.fetchone()
            if row:
                return FightRecord(
                    fight_id=row["fight_id"],
                    json_data=json.loads(row["json_data"]),
                    winner=row["winner"],
                    fight_type=row["fight_type"],
                    context=row["context"],
                    team1_levels=row["team1_levels"],
                    team2_levels=row["team2_levels"],
                    duration=row["duration"],
                    fight_date=row["fight_date"] if "fight_date" in row.keys() else None,
                    downloaded_at=row["downloaded_at"],
                )
            return None

    def iter_fights(
        self,
        fight_type: Optional[int] = None,
        context: Optional[int] = None,
        min_levels: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> Iterator[FightRecord]:
        """Iterate over fights with optional filtering."""
        query = "SELECT * FROM fights WHERE 1=1"
        params = []

        if fight_type is not None:
            query += " AND fight_type = ?"
            params.append(fight_type)
        if context is not None:
            query += " AND context = ?"
            params.append(context)
        if min_levels is not None:
            query += " AND (team1_levels + team2_levels) >= ?"
            params.append(min_levels)

        query += " ORDER BY fight_id DESC"

        if limit:
            query += " LIMIT ?"
            params.append(limit)

        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(query, params)
            for row in cursor:
                yield FightRecord(
                    fight_id=row["fight_id"],
                    json_data=json.loads(row["json_data"]),
                    winner=row["winner"],
                    fight_type=row["fight_type"],
                    context=row["context"],
                    team1_levels=row["team1_levels"],
                    team2_levels=row["team2_levels"],
                    duration=row["duration"],
                    fight_date=row["fight_date"] if "fight_date" in row.keys() else None,
                    downloaded_at=row["downloaded_at"],
                )

    # Queue management
    def add_to_queue(self, fight_ids: list[int], source: str, priority: int = 0) -> int:
        """
        Add fight IDs to the download queue, skipping already-downloaded fights.

        Returns number of fights actually added.
        """
        if not fight_ids:
            return 0

        with self._connect() as conn:
            # Batch-check which fights already exist in DB (fast with PRIMARY KEY index)
            placeholders = ",".join("?" * len(fight_ids))
            cursor = conn.execute(
                f"SELECT fight_id FROM fights WHERE fight_id IN ({placeholders})",
                fight_ids,
            )
            already_downloaded = set(row[0] for row in cursor)

            # Also check which are already in queue
            cursor = conn.execute(
                f"SELECT fight_id FROM fight_queue WHERE fight_id IN ({placeholders})",
                fight_ids,
            )
            already_queued = set(row[0] for row in cursor)

            # Filter to only new fights
            new_fights = [
                fid for fid in fight_ids
                if fid not in already_downloaded and fid not in already_queued
            ]

            if not new_fights:
                return 0

            now = datetime.now().isoformat()
            conn.executemany(
                """INSERT INTO fight_queue (fight_id, source, priority, added_at)
                   VALUES (?, ?, ?, ?)""",
                [(fid, source, priority, now) for fid in new_fights],
            )
            return len(new_fights)

    def peek_from_queue(self) -> Optional[int]:
        """Get the next fight ID from queue without removing it."""
        with self._connect() as conn:
            cursor = conn.execute(
                """SELECT fight_id FROM fight_queue
                   WHERE fight_id NOT IN (SELECT fight_id FROM fights)
                   ORDER BY priority DESC, added_at ASC
                   LIMIT 1"""
            )
            row = cursor.fetchone()
            return row[0] if row else None

    def remove_from_queue(self, fight_id: int):
        """Remove a fight from the queue (call after successful download)."""
        with self._connect() as conn:
            conn.execute("DELETE FROM fight_queue WHERE fight_id = ?", (fight_id,))

    def delay_in_queue(self, fight_id: int):
        """Move a fight to the back of the queue (for pending fights)."""
        with self._connect() as conn:
            # Update added_at to current time to move it to the back
            conn.execute(
                "UPDATE fight_queue SET added_at = datetime('now'), priority = -1 WHERE fight_id = ?",
                (fight_id,)
            )

    def pop_from_queue(self) -> Optional[int]:
        """Get and remove the next fight ID from the queue (legacy - prefer peek/remove)."""
        fight_id = self.peek_from_queue()
        if fight_id:
            self.remove_from_queue(fight_id)
        return fight_id

    def queue_size(self) -> int:
        """Get number of fights in queue (excluding already downloaded)."""
        with self._connect() as conn:
            cursor = conn.execute(
                """SELECT COUNT(*) FROM fight_queue
                   WHERE fight_id NOT IN (SELECT fight_id FROM fights)"""
            )
            return cursor.fetchone()[0]

    def cleanup_queue(self) -> dict:
        """
        Remove stale entries from queues (already downloaded/scraped).

        Returns dict with cleanup counts.
        """
        with self._connect() as conn:
            # Clean fight queue: remove fights already downloaded
            cursor = conn.execute("""
                DELETE FROM fight_queue
                WHERE fight_id IN (SELECT fight_id FROM fights)
            """)
            fights_removed = cursor.rowcount

            # Clean discovery queue: remove leeks already scraped
            cursor = conn.execute("""
                DELETE FROM leek_discovery_queue
                WHERE leek_id IN (
                    SELECT player_id FROM scraped_players
                    WHERE player_type = 'leek'
                )
            """)
            discovery_removed = cursor.rowcount

            return {
                "fight_queue_cleaned": fights_removed,
                "discovery_queue_cleaned": discovery_removed,
            }

    # Player tracking
    def mark_player_scraped(self, player_type: str, player_id: int, talent: int = 0):
        """Mark a player as having had their history scraped."""
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO scraped_players
                   (player_type, player_id, talent, last_scraped)
                   VALUES (?, ?, ?, ?)""",
                (player_type, player_id, talent, datetime.now().isoformat()),
            )

    def is_player_scraped(self, player_type: str, player_id: int) -> bool:
        """Check if we've already scraped a player's history."""
        with self._connect() as conn:
            cursor = conn.execute(
                """SELECT 1 FROM scraped_players
                   WHERE player_type = ? AND player_id = ?""",
                (player_type, player_id),
            )
            return cursor.fetchone() is not None

    # State management
    def set_state(self, key: str, value: str):
        """Set a scraper state value."""
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO scraper_state (key, value) VALUES (?, ?)",
                (key, value),
            )

    def get_state(self, key: str, default: str = "") -> str:
        """Get a scraper state value."""
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT value FROM scraper_state WHERE key = ?", (key,)
            )
            row = cursor.fetchone()
            return row[0] if row else default

    # Statistics
    def get_stats(self) -> dict:
        """Get database statistics."""
        with self._connect() as conn:
            stats = {}

            # Total fights
            cursor = conn.execute("SELECT COUNT(*) FROM fights")
            stats["total_fights"] = cursor.fetchone()[0]

            # By type
            cursor = conn.execute(
                "SELECT fight_type, COUNT(*) FROM fights GROUP BY fight_type"
            )
            stats["by_type"] = {row[0]: row[1] for row in cursor}

            # By context
            cursor = conn.execute(
                "SELECT context, COUNT(*) FROM fights GROUP BY context"
            )
            stats["by_context"] = {row[0]: row[1] for row in cursor}

            # Queue size
            stats["queue_size"] = self.queue_size()

            # Players scraped
            cursor = conn.execute("SELECT COUNT(*) FROM scraped_players")
            stats["players_scraped"] = cursor.fetchone()[0]

            # Database file size
            stats["db_size_mb"] = round(self.db_path.stat().st_size / 1024 / 1024, 2)

            # Leek observations count
            cursor = conn.execute("SELECT COUNT(*) FROM leek_observations")
            stats["leek_observations"] = cursor.fetchone()[0]

            # Unique leeks observed
            cursor = conn.execute("SELECT COUNT(DISTINCT leek_id) FROM leek_observations")
            stats["unique_leeks"] = cursor.fetchone()[0]

            # Discovery queue
            cursor = conn.execute("SELECT COUNT(*) FROM leek_discovery_queue")
            stats["discovery_queue"] = cursor.fetchone()[0]

            return stats

    # Leek observation tracking
    def extract_and_save_leek_observations(self, fight_id: int, fight_data: dict) -> list[int]:
        """
        Extract leek observations from fight data and save to DB.
        Returns list of newly discovered leek IDs.

        Fight data has TWO leek sources that must be correlated:
        - leeks1/leeks2 (outer): Real leek IDs, talent, farmer_id
        - data.leeks (inner): Combat stats (life, strength, etc.) but fight-local entity IDs

        We also extract outcome data from report.leeks1/report.leeks2:
        - td (damage dealt), tb (damage blocked), dead
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
                    "td": leek.get("td", 0),  # damage dealt
                    "tb": leek.get("tb", 0),  # damage blocked
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
                # Skip summons (bulbs, etc)
                if leek.get("summon", False):
                    continue

                name = leek.get("name")
                if not name:
                    continue

                # Look up real leek ID from outer data
                outer = name_to_outer.get(name, {})
                real_leek_id = outer.get("id")
                if not real_leek_id:
                    # Fallback: might be a summon or edge case
                    continue

                # Get report data for this leek
                report_data = name_to_report.get(name, {})

                team = leek.get("team", 0)
                won = (winner == team)

                # Check if this leek is new to us
                cursor = conn.execute(
                    "SELECT 1 FROM leek_observations WHERE leek_id = ? LIMIT 1",
                    (real_leek_id,)
                )
                if cursor.fetchone() is None:
                    new_leeks.append(real_leek_id)

                # Insert or update observation
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
                        outer.get("talent", 0),  # From outer leeks, authoritative
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
                        leek.get("cellPos", 0),  # Starting position
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
        """Peek next leek from discovery queue without removing. Returns (leek_id, farmer_id, level) or None."""
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
        """Remove a leek from the discovery queue (call after successful scrape)."""
        with self._connect() as conn:
            conn.execute("DELETE FROM leek_discovery_queue WHERE leek_id = ?", (leek_id,))

    def pop_from_discovery_queue(self) -> Optional[tuple[int, int, int]]:
        """Legacy: Get and remove next leek. Prefer peek + remove pattern."""
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
            # Calculate stats per level
            conn.execute("""
                INSERT OR REPLACE INTO level_stats
                (level, count, mean_talent, std_talent, mean_strength, mean_agility,
                 mean_wisdom, mean_resistance, mean_magic, win_rate, updated_at)
                SELECT
                    level,
                    COUNT(DISTINCT leek_id) as count,
                    AVG(strength + agility + wisdom + resistance + magic + science) as mean_talent,
                    0 as std_talent,  -- TODO: calculate std
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
        """
        Calculate priority score for a leek based on DATA DIVERSITY needs.

        Higher score = more urgent to scrape for balanced training data.
        Priority is based on:
        1. Under-represented levels get MASSIVE boost
        2. Level 301 gets lowest priority (usually over-represented)
        3. Win rate and stats are secondary factors
        """
        # Get observation counts by level bracket
        bracket_counts = self.get_level_bracket_counts()

        # Determine which bracket this level falls into
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

        # Calculate diversity bonus based on under-representation
        bracket_data = bracket_counts.get(bracket, {"count": 0})
        bracket_count = bracket_data.get("count", 0)

        # Get total observations
        total_obs = sum(b.get("count", 0) for b in bracket_counts.values())

        if total_obs == 0:
            # No data yet - all levels equally important
            diversity_bonus = 100
        else:
            # Calculate expected count (uniform distribution across 7 brackets)
            expected_count = total_obs / 7

            if bracket_count < expected_count:
                # Under-represented: massive bonus
                # The more under-represented, the higher the bonus
                scarcity_ratio = expected_count / max(bracket_count, 1)
                diversity_bonus = min(500, 100 * scarcity_ratio)  # Cap at 500
            else:
                # Over-represented: minimal bonus or penalty
                excess_ratio = bracket_count / expected_count
                diversity_bonus = max(10, 100 / excess_ratio)  # Min 10, decreases with excess

        # Level 301 special case: if we have >50% level 301, heavily penalize
        level_301_ratio = self.get_level_301_ratio()
        if level == 301 and level_301_ratio > 0.3:
            # Reduce priority significantly for level 301 when over-represented
            diversity_bonus = diversity_bonus * (1 - level_301_ratio)

        # Add small bonus for win rate (good players have more interesting fights)
        win_bonus = win_rate * 20

        return diversity_bonus + win_bonus

    # Analytics methods
    def get_level_distribution(self, fight_type: Optional[int] = None) -> list[dict]:
        """Get fight count per level, optionally filtered by fight type."""
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
        """Get the most common stat distributions (builds) for a level."""
        with self._connect() as conn:
            params = [level]
            type_filter = ""
            if fight_type is not None:
                type_filter = "AND fight_type = ?"
                params.append(fight_type)

            # Bucket stats into ranges to find "build archetypes"
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

    # Tournament exploration tracking
    def is_tournament_explored(self, tournament_id: int) -> bool:
        """Check if a tournament has been explored."""
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT 1 FROM tournament_exploration WHERE tournament_id = ?",
                (tournament_id,)
            )
            return cursor.fetchone() is not None

    def mark_tournament_explored(
        self,
        tournament_id: int,
        tournament_type: str,
        tournament_date: int,
        leeks_found: int,
        low_level_leeks: int
    ):
        """Mark a tournament as explored."""
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO tournament_exploration
                   (tournament_id, tournament_type, tournament_date, leeks_found,
                    low_level_leeks, explored_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (tournament_id, tournament_type, tournament_date, leeks_found,
                 low_level_leeks, datetime.now().isoformat())
            )

    def get_tournament_exploration_stats(self) -> dict:
        """Get tournament exploration statistics."""
        with self._connect() as conn:
            cursor = conn.execute("""
                SELECT
                    COUNT(*) as total_explored,
                    MIN(tournament_date) as oldest_date,
                    MAX(tournament_date) as newest_date,
                    SUM(leeks_found) as total_leeks,
                    SUM(low_level_leeks) as total_low_level
                FROM tournament_exploration
            """)
            row = cursor.fetchone()
            return {
                "tournaments_explored": row[0] or 0,
                "oldest_date": row[1],
                "newest_date": row[2],
                "leeks_from_tournaments": row[3] or 0,
                "low_level_from_tournaments": row[4] or 0,
            }

    def get_last_explored_tournament_id(self) -> Optional[int]:
        """Get the most recently explored tournament ID."""
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT MAX(tournament_id) FROM tournament_exploration"
            )
            row = cursor.fetchone()
            return row[0] if row and row[0] else None

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
        """
        Get fight counts grouped by date bucket.

        Args:
            bucket: "day", "week", or "month"

        Returns list of {"date": "YYYY-MM", "count": N, "levels_avg": X}
        """
        with self._connect() as conn:
            if bucket == "day":
                date_format = "%Y-%m-%d"
            elif bucket == "week":
                date_format = "%Y-W%W"
            else:  # month
                date_format = "%Y-%m"

            # Calculate avg level per leek
            # Approximate leek counts: solo=2, farmer=4, team=6, royale=10
            cursor = conn.execute(f"""
                SELECT
                    strftime('{date_format}', fight_date, 'unixepoch') as period,
                    COUNT(*) as count,
                    AVG(
                        CASE
                            WHEN team2_levels = 0 THEN team1_levels * 1.0 / NULLIF(team1_levels / 301 + 1, 0)
                            ELSE (team1_levels + team2_levels) * 1.0 /
                                CASE fight_type
                                    WHEN 0 THEN 2   -- solo: 1v1
                                    WHEN 1 THEN 4   -- farmer: ~2v2
                                    WHEN 2 THEN 6   -- team: ~3v3
                                    ELSE 10         -- royale/other
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
                if row[0]  # Skip NULL periods
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
        """Get counts of old vs recent data based on the Feb 20, 2024 cutoff.

        Data before this date may not reflect current game balance due to
        item restriction changes.
        """
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
            total = row[3] or 1  # Avoid division by zero
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

    # ==================== Metadata Extraction ====================

    def save_fight_metadata(self, metadata_list: list[dict]) -> int:
        """
        Save extracted fight metadata to database.

        Args:
            metadata_list: List of metadata dicts from extract_fight_metadata

        Returns:
            Number of records saved
        """
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
                        # Stats
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
                        # Equipment
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
            # Total fights
            cursor = conn.execute("SELECT COUNT(*) FROM fights")
            total_fights = cursor.fetchone()[0]

            # Fights with metadata extracted (unique fight_ids)
            cursor = conn.execute(
                "SELECT COUNT(DISTINCT fight_id) FROM fight_leek_metadata"
            )
            extracted_fights = cursor.fetchone()[0]

            # Last processed fight_id
            cursor = conn.execute(
                "SELECT value FROM metadata_extraction_state WHERE key = 'last_fight_id'"
            )
            row = cursor.fetchone()
            last_fight_id = int(row[0]) if row else 0

            # Last extraction time
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
        """
        Get fights that don't have metadata extracted yet.

        Returns list of (fight_id, fight_data) tuples.
        """
        with self._connect() as conn:
            # Find fights without metadata
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
        """
        Get equipment usage statistics by level bucket.

        Returns:
            {bucket: {"weapons": {id: {"name": str, "count": int, "pct": float}}, ...}}
        """
        with self._connect() as conn:
            # Join metadata with observations to get level
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

            from collections import defaultdict

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

            # Filter by min sample size and convert to percentages
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
                        )[:20]  # Top 20
                    },
                    "chips": {
                        c: {"count": cnt, "pct": round(cnt / sample * 100, 1)}
                        for c, cnt in sorted(
                            data["chips"].items(),
                            key=lambda x: x[1],
                            reverse=True
                        )[:30]  # Top 30
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
        """
        Compute equipment co-occurrence matrix.

        Returns which weapons/chips are used together by the same leek.

        Args:
            level_bucket: Filter by level bucket (e.g., "91-100", "301")
            fight_type: Filter by fight type (0=solo, 1=farmer, 2=team)
            min_cooccurrence: Minimum co-occurrence count to include

        Returns:
            {"items": [...], "matrix": [[...]], "counts": {...}}
        """
        from collections import defaultdict

        with self._connect() as conn:
            # Build query with filters using individual leek level from metadata
            query = """
                SELECT m.weapons_used, m.chips_used
                FROM fight_leek_metadata m
            """
            params: list = []
            conditions = []

            # Filter by individual leek level (from metadata)
            if level_bucket:
                if level_bucket == "301":
                    conditions.append("m.level = 301")
                else:
                    parts = level_bucket.split("-")
                    if len(parts) == 2:
                        conditions.append("m.level >= ? AND m.level <= ?")
                        params.extend([int(parts[0]), int(parts[1])])

            # Filter by fight type (need to join fights table)
            if fight_type is not None:
                query += " JOIN fights f ON m.fight_id = f.fight_id"
                conditions.append("f.fight_type = ?")
                params.append(fight_type)

            if conditions:
                query += " WHERE " + " AND ".join(conditions)

            cursor = conn.execute(query, params)

            # Count co-occurrences
            cooccurrence: dict[tuple, int] = defaultdict(int)
            item_counts: dict[str, int] = defaultdict(int)

            for row in cursor:
                weapons = json.loads(row[0] or "[]")
                chips = json.loads(row[1] or "[]")

                # Create item keys with prefixes
                items = [f"W:{w}" for w in set(weapons)] + [f"C:{c}" for c in set(chips)]

                # Count individual items
                for item in items:
                    item_counts[item] += 1

                # Count pairs
                for i, item_a in enumerate(items):
                    for item_b in items[i + 1:]:
                        pair = tuple(sorted([item_a, item_b]))
                        cooccurrence[pair] += 1

            # Filter by minimum co-occurrence and build matrix
            # Get top items by count
            top_items = sorted(item_counts.items(), key=lambda x: x[1], reverse=True)[:30]
            item_list = [item for item, _ in top_items]

            # Build matrix
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
