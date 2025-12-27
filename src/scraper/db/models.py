"""
Database models and dataclasses.
"""

from dataclasses import dataclass
from typing import Optional


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
