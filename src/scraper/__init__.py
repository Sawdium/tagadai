"""
LeekWars fight scraper module.

Politely downloads fight data from the LeekWars API for ML training.
"""

from .scraper import FightScraper, ScraperStatus, get_scraper
from .db import FightDatabase

__all__ = ["FightScraper", "FightDatabase", "ScraperStatus", "get_scraper"]
