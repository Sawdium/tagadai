"""
LeekWars API client with rate limiting and authentication.
"""

import os
import time
import threading
import logging
from typing import Optional

import requests
from dotenv import load_dotenv

from .stats import ScraperStats

logger = logging.getLogger(__name__)


class LeekWarsClient:
    """
    LeekWars API client with rate limiting and authentication.

    Features:
    - Polite rate limiting (configurable delay)
    - Automatic retry with exponential backoff
    - Connection pooling via requests.Session
    """

    API_BASE = "https://leekwars.com/api"

    def __init__(
        self,
        delay: float = 1.0,
        stats: Optional[ScraperStats] = None,
        stop_event: Optional[threading.Event] = None,
        pause_event: Optional[threading.Event] = None,
    ):
        """
        Initialize the API client.

        Args:
            delay: Seconds between API requests
            stats: ScraperStats instance for tracking metrics
            stop_event: Threading event to signal stop
            pause_event: Threading event to signal pause (set = not paused)
        """
        self.delay = delay
        self.stats = stats or ScraperStats()
        self._stop_event = stop_event or threading.Event()
        self._pause_event = pause_event or threading.Event()
        self._pause_event.set()  # Not paused by default

        # Request timing tracking
        self._request_times: list[float] = []

        # Session for connection pooling
        self._session = requests.Session()
        self._session.headers["User-Agent"] = "TagadAI/1.0 (ML Training Data Collection)"

        # Authentication
        self._token: Optional[str] = None
        self._authenticated = False

    def try_auto_login(self):
        """Try to authenticate using environment credentials."""
        load_dotenv()
        login = os.getenv("LEEKWARS_LOGIN")
        password = os.getenv("LEEKWARS_PASSWORD")

        if login and password:
            try:
                self.login(login, password)
            except Exception as e:
                logger.warning(f"Auto-login failed: {e}")

    def login(self, login: str, password: str) -> dict:
        """Authenticate with LeekWars API."""
        response = self._session.post(
            f"{self.API_BASE}/farmer/login-token",
            data={"login": login, "password": password}
        )
        response.raise_for_status()
        data = response.json()

        if "error" in data:
            raise ValueError(f"Login failed: {data.get('error')}")

        self._token = data.get("token")
        if self._token:
            self._session.headers["Authorization"] = f"Bearer {self._token}"
            self._authenticated = True
            logger.info(f"Authenticated as {data.get('farmer', {}).get('login', 'unknown')}")

        return data

    @property
    def is_authenticated(self) -> bool:
        """Check if client is authenticated."""
        return self._authenticated

    def _rate_limit(self):
        """Wait for rate limit."""
        self._pause_event.wait()  # Block if paused
        time.sleep(self.delay)

    def request(self, endpoint: str, retries: int = 3) -> Optional[dict]:
        """Make a rate-limited API request with retries."""
        if self._stop_event.is_set():
            return None

        url = f"{self.API_BASE}/{endpoint}"

        for attempt in range(retries):
            if self._stop_event.is_set():
                return None

            self.stats.requests_made += 1
            start = time.time()

            try:
                response = self._session.get(url, timeout=30)
                elapsed = time.time() - start

                # Track request times
                self._request_times.append(elapsed)
                if len(self._request_times) > 100:
                    self._request_times.pop(0)
                self.stats.avg_request_time = sum(self._request_times) / len(self._request_times)

                if response.status_code == 200:
                    data = response.json()
                    if "error" in data:
                        self.stats.last_error = f"API: {data.get('error')}"
                        logger.warning(f"API error for {endpoint}: {data.get('error')}")
                        return None
                    return data
                elif response.status_code == 429:
                    # Rate limited - back off more aggressively
                    self.stats.rate_limit_hits += 1
                    wait = max(10, self.delay * (4 ** attempt))
                    self.stats.rate_limited_until = time.time() + wait
                    self.stats.last_error = f"Rate limited (429)"
                    self.stats.current_action = f"Rate limited! Waiting {wait:.0f}s..."
                    logger.warning(f"Rate limited (hit #{self.stats.rate_limit_hits}), waiting {wait}s...")
                    time.sleep(wait)
                    self.stats.rate_limited_until = None
                    continue
                elif response.status_code == 401:
                    # 401 can mean auth required OR resource doesn't exist/restricted
                    try:
                        data = response.json()
                        if isinstance(data, str):
                            # Specific error like "fight_with_secret_trophy" - skip permanently
                            self.stats.last_error = f"API: {data}"
                            return {"_auth_required": True}
                        elif isinstance(data, dict) and "error" in data:
                            # Dict with error key - skip permanently
                            self.stats.last_error = f"API: {data.get('error')}"
                            return {"_auth_required": True}
                    except Exception:
                        pass
                    if not self._authenticated:
                        logger.warning(f"HTTP 401 for {endpoint} - not authenticated")
                    else:
                        logger.warning(f"HTTP 401 for {endpoint} - token may have expired")
                    self.stats.last_error = f"HTTP 401 - auth required"
                    return {"_auth_required": True}
                elif response.status_code >= 500:
                    # Server error - retry
                    wait = self.delay * (2 ** attempt)
                    self.stats.last_error = f"Server error {response.status_code}"
                    self.stats.current_action = f"Server error, retry in {wait:.0f}s..."
                    logger.warning(f"Server error {response.status_code}, retrying in {wait}s...")
                    time.sleep(wait)
                    continue
                else:
                    # Client error (404, 403, etc) - don't retry
                    self.stats.last_error = f"HTTP {response.status_code}"
                    logger.warning(f"HTTP {response.status_code} for {endpoint}")
                    return None

            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                # Network error - retry with backoff
                wait = self.delay * (2 ** attempt)
                self.stats.last_error = str(e)
                logger.warning(f"Network error for {endpoint}, retrying in {wait}s: {e}")
                time.sleep(wait)
                continue

            except Exception as e:
                # Unexpected error - don't retry
                self.stats.last_error = str(e)
                logger.error(f"Request failed for {endpoint}: {e}")
                return None

            finally:
                self._rate_limit()

        self.stats.last_error = f"All {retries} retries failed"
        logger.error(f"All {retries} retries failed for {endpoint}")
        return None
