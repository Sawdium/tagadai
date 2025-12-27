"""
API route handlers for the dashboard.
"""

from .training import register_training_routes
from .scraper import register_scraper_routes
from .metadata import register_metadata_routes
from .rl import register_rl_routes
from .nn import register_nn_routes

__all__ = [
    'register_training_routes',
    'register_scraper_routes',
    'register_metadata_routes',
    'register_rl_routes',
    'register_nn_routes',
]
