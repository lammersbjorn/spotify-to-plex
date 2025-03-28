"""Module to interact with the Lidarr API for playlist imports."""

import time
from functools import lru_cache
from typing import Any, Optional

import httpx
from loguru import logger

from spotify_to_plex.config import Config

# Constants
MAX_RETRIES = 3
RETRY_DELAY = 2


class LidarrClass:
    """Handles communication with the Lidarr API."""

    def __init__(self: "LidarrClass") -> None:
        """Initialize Lidarr connection using configuration."""
        self.url: str = Config.LIDARR_API_URL
        self.api_key: str = Config.LIDARR_API_KEY
        self.headers: dict[str, str] = {"X-Api-Key": self.api_key}
        self._playlist_cache: Optional[list[list[str]]] = None
        self._last_fetch_time = 0
        self._cache_ttl = 3600  # Cache TTL in seconds (1 hour)

        # Connection pooling with httpx Client
        self.client = httpx.Client(
            headers=self.headers,
            timeout=30.0,
            verify=False,  # nosec - Allow self-signed certificates for local instances
        )

        if not self.url or self.api_key == "":
            logger.warning("Lidarr API credentials not properly configured")
        else:
            logger.debug(f"Lidarr API configured with URL: {self.url}")

    @lru_cache(maxsize=8)
    def lidarr_request(
        self: "LidarrClass",
        endpoint_path: str,
    ) -> Optional[dict[str, Any]]:
        """Make a generic request to the Lidarr API with retry logic.

        Args:
            endpoint_path: The API endpoint path.

        Returns:
            Parsed JSON response if successful, else None.
        """
        url = f"{self.url.rstrip('/')}/{endpoint_path.lstrip('/')}"
        logger.debug(f"Making Lidarr API request to: {url}")

        for attempt in range(MAX_RETRIES):
            try:
                response = self.client.get(url=url)
                response.raise_for_status()
                return response.json()

            except httpx.RequestError as e:
                wait_time = RETRY_DELAY * (attempt + 1)
                logger.warning(
                    f"Network error during Lidarr API call (attempt {attempt+1}/{MAX_RETRIES}). "
                    f"Retrying in {wait_time}s: {e}",
                )
                if attempt < MAX_RETRIES - 1:
                    time.sleep(wait_time)
                else:
                    logger.exception(
                        f"Network error during Lidarr API call after {MAX_RETRIES} attempts: {e}"
                    )
                    return None

            except httpx.HTTPStatusError as e:
                wait_time = RETRY_DELAY * (attempt + 1)
                logger.warning(
                    f"HTTP status error {e.response.status_code} during Lidarr API call "
                    f"(attempt {attempt+1}/{MAX_RETRIES}). Retrying in {wait_time}s: {e}",
                )
                if attempt < MAX_RETRIES - 1:
                    time.sleep(wait_time)
                else:
                    logger.exception(
                        f"HTTP status error during Lidarr API call after {MAX_RETRIES} attempts: {e}"
                    )
                    return None

            except Exception as e:
                wait_time = RETRY_DELAY * (attempt + 1)
                logger.warning(
                    f"Unexpected error during Lidarr API call (attempt {attempt+1}/{MAX_RETRIES}). "
                    f"Retrying in {wait_time}s: {e}",
                )
                if attempt < MAX_RETRIES - 1:
                    time.sleep(wait_time)
                else:
                    logger.exception(
                        f"Unexpected error during Lidarr API call after {MAX_RETRIES} attempts: {e}"
                    )
                    return None

        return None

    def playlist_request(self: "LidarrClass") -> list[list[str]]:
        """Request and process playlists from Lidarr with caching.

        Returns:
            A list of lists containing playlist IDs.
        """
        current_time = time.time()

        # Return cached results if they're still valid
        if (
            self._playlist_cache is not None
            and (current_time - self._last_fetch_time) < self._cache_ttl
        ):
            logger.debug("Using cached Lidarr playlist data")
            return self._playlist_cache

        logger.debug("Fetching fresh playlist data from Lidarr")
        endpoint = "/api/v1/importlist"
        raw_playlists = self.lidarr_request(endpoint_path=endpoint)

        if not raw_playlists:
            logger.warning("No playlists data received from Lidarr")
            return []

        spotify_playlists: list[list[str]] = []

        for entry in raw_playlists:
            if entry.get("listType") != "spotify":
                logger.debug(
                    f"Skipping non-Spotify import list type: {entry.get('listType', 'unknown')}"
                )
                continue

            name = entry.get("name", "Unknown List")
            logger.debug(f"Processing Spotify import list: {name}")

            for field in entry.get("fields", []):
                if field.get("name") == "playlistIds":
                    playlist_ids = field.get("value", [])
                    if playlist_ids:
                        spotify_playlists.append(playlist_ids)
                        logger.debug(
                            f"Found {len(playlist_ids)} Spotify playlist IDs in Lidarr list '{name}': {playlist_ids}",
                        )

        if not spotify_playlists:
            logger.warning("No Spotify playlists found in Lidarr response")

        # Update cache
        self._playlist_cache = spotify_playlists
        self._last_fetch_time = current_time

        return spotify_playlists
