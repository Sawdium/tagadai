"""
Centralized credential management for TagadAI.

Loads credentials from environment variables with consistent error handling.
"""

import os
from typing import Tuple
from dotenv import load_dotenv

from .errors import ConfigError


def load_credentials(require: bool = True) -> Tuple[str, str]:
    """
    Load LeekWars credentials from environment.

    Args:
        require: If True, raise ConfigError when credentials are missing.
                 If False, return empty strings for missing credentials.

    Returns:
        Tuple of (login, password)

    Raises:
        ConfigError: If require=True and credentials are missing.
    """
    load_dotenv()

    login = os.getenv("LEEKWARS_LOGIN", "")
    password = os.getenv("LEEKWARS_PASSWORD", "")

    if require and (not login or not password):
        missing = []
        if not login:
            missing.append("LEEKWARS_LOGIN")
        if not password:
            missing.append("LEEKWARS_PASSWORD")
        raise ConfigError(
            f"Missing credentials in .env: {', '.join(missing)}\n"
            "Create a .env file with LEEKWARS_LOGIN and LEEKWARS_PASSWORD"
        )

    return login, password
