"""
Database schema definitions and migrations.
"""

import sqlite3


def init_schema(conn: sqlite3.Connection):
    """Initialize database schema with all tables and indexes."""
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
        CREATE TABLE IF NOT EXISTS leek_observations (
            fight_id INTEGER NOT NULL,
            leek_id INTEGER NOT NULL,
            farmer_id INTEGER,
            level INTEGER,
            talent INTEGER,
            team INTEGER,
            won BOOLEAN,
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
            starting_cell INTEGER,
            damage_dealt INTEGER,
            damage_blocked INTEGER,
            dead BOOLEAN,
            fight_context INTEGER,
            fight_type INTEGER,
            observed_at TEXT NOT NULL,
            PRIMARY KEY (fight_id, leek_id)
        );

        -- Indexes for leek analysis
        CREATE INDEX IF NOT EXISTS idx_leek_obs_leek ON leek_observations(leek_id);
        CREATE INDEX IF NOT EXISTS idx_leek_obs_level ON leek_observations(level);
        CREATE INDEX IF NOT EXISTS idx_leek_obs_farmer ON leek_observations(farmer_id);

        -- Aggregated level statistics
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

        -- Fight metadata for build analysis
        CREATE TABLE IF NOT EXISTS fight_leek_metadata (
            fight_id INTEGER NOT NULL,
            leek_id INTEGER NOT NULL,
            entity_id INTEGER,
            level INTEGER DEFAULT 0,
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
            weapons_used TEXT,
            chips_used TEXT,
            weapon_actions INTEGER DEFAULT 0,
            chip_actions INTEGER DEFAULT 0,
            move_actions INTEGER DEFAULT 0,
            summon_actions INTEGER DEFAULT 0,
            physical_damage INTEGER DEFAULT 0,
            magic_damage INTEGER DEFAULT 0,
            poison_damage INTEGER DEFAULT 0,
            heal_done INTEGER DEFAULT 0,
            total_tp_spent INTEGER DEFAULT 0,
            total_mp_spent INTEGER DEFAULT 0,
            total_cells_moved INTEGER DEFAULT 0,
            turns_alive INTEGER DEFAULT 0,
            extracted_at TEXT NOT NULL,
            PRIMARY KEY (fight_id, leek_id)
        );

        CREATE INDEX IF NOT EXISTS idx_metadata_leek ON fight_leek_metadata(leek_id);

        -- Aggregated equipment statistics
        CREATE TABLE IF NOT EXISTS equipment_stats (
            level_bucket TEXT NOT NULL,
            fight_type INTEGER,
            item_type TEXT NOT NULL,
            item_id INTEGER NOT NULL,
            item_name TEXT,
            use_count INTEGER DEFAULT 0,
            leek_count INTEGER DEFAULT 0,
            total_damage INTEGER DEFAULT 0,
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

        -- Tournament exploration tracking
        CREATE TABLE IF NOT EXISTS tournament_exploration (
            tournament_id INTEGER PRIMARY KEY,
            tournament_type TEXT,
            tournament_date INTEGER,
            leeks_found INTEGER DEFAULT 0,
            low_level_leeks INTEGER DEFAULT 0,
            explored_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_tournament_date ON tournament_exploration(tournament_date DESC);
    """)


def run_migrations(conn: sqlite3.Connection):
    """Run database migrations for schema updates."""
    # Migration: Add fight_date column if it doesn't exist
    cursor = conn.execute("PRAGMA table_info(fights)")
    columns = [row[1] for row in cursor.fetchall()]
    if 'fight_date' not in columns:
        conn.execute("ALTER TABLE fights ADD COLUMN fight_date INTEGER")

    # Create index on fight_date
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
