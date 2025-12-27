"""
Custom exception types for TagadAI.

Provides a consistent exception hierarchy across all modules.
"""


class TagadAIError(Exception):
    """Base exception for all TagadAI operations."""
    pass


class APIError(TagadAIError):
    """Error from LeekWars API calls."""
    pass


class AuthenticationError(APIError):
    """Authentication/login failure."""
    pass


class FightError(TagadAIError):
    """Error during fight execution or parsing."""
    pass


class ConfigError(TagadAIError):
    """Configuration error (missing files, invalid settings)."""
    pass
