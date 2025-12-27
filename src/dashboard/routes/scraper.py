"""
Scraper API routes.
"""

from typing import Optional

from fastapi import FastAPI, Request
from pydantic import BaseModel


# Scraper imports
try:
    from ...scraper import FightScraper, FightDatabase, get_scraper
    SCRAPER_AVAILABLE = True
except ImportError:
    SCRAPER_AVAILABLE = False
    get_scraper = None


class ScraperConfig(BaseModel):
    delay: float = 1.0


def register_scraper_routes(app: FastAPI):
    """Register scraper-related routes."""

    @app.get("/api/scraper/status")
    async def get_scraper_status():
        """Get scraper status and statistics."""
        if not SCRAPER_AVAILABLE:
            return {"error": "Scraper module not available", "status": "unavailable"}
        scraper = get_scraper()
        return scraper.get_stats()

    @app.post("/api/scraper/start")
    async def start_scraper(config: ScraperConfig):
        """Start the scraper."""
        if not SCRAPER_AVAILABLE:
            return {"success": False, "error": "Scraper module not available"}

        from ...scraper import FightScraper, FightDatabase
        from ...scraper import scraper as scraper_module

        scraper_module._scraper = FightScraper(delay=config.delay)
        scraper = get_scraper()

        if scraper.is_running():
            return {"success": False, "error": "Scraper already running"}

        success = scraper.start()
        return {"success": success, "message": "Scraper started" if success else "Failed to start"}

    @app.post("/api/scraper/stop")
    async def stop_scraper():
        """Stop the scraper."""
        if not SCRAPER_AVAILABLE:
            return {"success": False, "error": "Scraper module not available"}
        scraper = get_scraper()
        scraper.stop()
        return {"success": True, "message": "Scraper stopped"}

    @app.post("/api/scraper/pause")
    async def pause_scraper():
        """Pause/resume the scraper."""
        if not SCRAPER_AVAILABLE:
            return {"success": False, "error": "Scraper module not available"}
        scraper = get_scraper()
        if scraper.stats.status.value == "paused":
            scraper.resume()
            return {"success": True, "paused": False}
        else:
            scraper.pause()
            return {"success": True, "paused": True}

    @app.post("/api/scraper/delay")
    async def set_scraper_delay(request: Request):
        """Update scraper delay live."""
        if not SCRAPER_AVAILABLE:
            return {"success": False, "error": "Scraper module not available"}
        try:
            body = await request.json()
            delay = float(body.get("delay", 1.0))
            if delay < 0.1:
                return {"success": False, "error": "Delay must be >= 0.1 seconds"}
            if delay > 60:
                return {"success": False, "error": "Delay must be <= 60 seconds"}
            scraper = get_scraper()
            old_delay = scraper.delay
            scraper.delay = delay
            return {"success": True, "old_delay": old_delay, "new_delay": delay}
        except (ValueError, TypeError) as e:
            return {"success": False, "error": f"Invalid delay value: {e}"}

    @app.get("/api/scraper/database")
    async def get_scraper_database_stats():
        """Get detailed database statistics."""
        if not SCRAPER_AVAILABLE:
            return {"error": "Scraper module not available"}
        scraper = get_scraper()
        return scraper.db.get_stats()

    @app.get("/api/scraper/analytics/levels")
    async def get_level_distribution(fight_type: Optional[int] = None):
        """Get observation counts per level."""
        if not SCRAPER_AVAILABLE:
            return {"error": "Scraper module not available"}
        scraper = get_scraper()
        return {
            "distribution": scraper.db.get_level_distribution(fight_type),
            "fight_types": scraper.db.get_fight_type_distribution(),
        }

    @app.get("/api/scraper/analytics/level/{level}")
    async def get_level_stats(level: int, fight_type: Optional[int] = None):
        """Get detailed stats for a specific level."""
        if not SCRAPER_AVAILABLE:
            return {"error": "Scraper module not available"}
        scraper = get_scraper()
        return {
            "stats": scraper.db.get_stats_by_level(level, fight_type),
            "builds": scraper.db.get_popular_builds(level, fight_type),
        }

    @app.get("/api/scraper/analytics/overview")
    async def get_analytics_overview():
        """Get overview analytics data."""
        if not SCRAPER_AVAILABLE:
            return {"error": "Scraper module not available"}
        scraper = get_scraper()
        return {
            "fight_types": scraper.db.get_fight_type_distribution(),
            "contexts": scraper.db.get_context_distribution(),
            "level_distribution": scraper.db.get_level_distribution(),
        }

    @app.get("/api/scraper/analytics/exploration")
    async def get_exploration_stats():
        """Get tournament exploration and level distribution stats."""
        if not SCRAPER_AVAILABLE:
            return {"error": "Scraper module not available"}
        scraper = get_scraper()
        tournament_stats = scraper.db.get_tournament_exploration_stats()
        level_brackets = scraper.db.get_level_bracket_counts()
        level_301_ratio = scraper.db.get_level_301_ratio()

        return {
            "tournaments": tournament_stats,
            "level_brackets": level_brackets,
            "level_301_ratio": round(level_301_ratio, 3),
        }

    @app.get("/api/scraper/analytics/dates")
    async def get_date_distribution(bucket: str = "month"):
        """Get fight counts grouped by date."""
        if not SCRAPER_AVAILABLE:
            return {"error": "Scraper module not available"}
        if bucket not in ("day", "week", "month"):
            bucket = "month"
        scraper = get_scraper()
        return {
            "distribution": scraper.db.get_fight_date_distribution(bucket),
            "date_range": scraper.db.get_fight_date_range(),
            "freshness": scraper.db.get_data_freshness_stats(),
        }
