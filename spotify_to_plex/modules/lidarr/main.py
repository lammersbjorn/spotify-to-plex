"""Module to interact with the Lidarr API for playlist imports."""

from typing import Any

import httpx
from loguru import logger

from spotify_to_plex.config import Config


class LidarrClass:
    """Handles communication with the Lidarr API."""

    def __init__(self: "LidarrClass") -> None:
        """Initialize Lidarr connection using configuration."""
        self.url: str = Config.LIDARR_API_URL
        self.api_key: str = Config.LIDARR_API_KEY
        self.headers: dict[str, str] = {"X-Api-Key": self.api_key}

        if not self.url or self.api_key == "":
            logger.warning("Lidarr API credentials not properly configured")

    def lidarr_request(
        self: "LidarrClass",
        endpoint_path: str,
    ) -> dict[str, Any] | None:
        """Make a generic request to the Lidarr API.

        Args:
            endpoint_path: The API endpoint path.

        Returns:
            Parsed JSON response if successful, else None.
        """
        url = f"{self.url.rstrip('/')}/{endpoint_path.lstrip('/')}"
        logger.debug(f"Making Lidarr API request to: {url}")

        try:
            response = httpx.get(url=url, headers=self.headers, timeout=30.0)
            response.raise_for_status()
        except httpx.RequestError as e:
            logger.exception(f"Network error during Lidarr API call: {e}")
            return None
        except httpx.HTTPStatusError as e:
            logger.exception(f"HTTP status error during Lidarr API call: {e}")
            return None
        except Exception as e:
            logger.exception(f"Unexpected error during Lidarr API call: {e}")
            return None
        else:
            return response.json()

    def playlist_request(self: "LidarrClass") -> list[list[str]]:
        """Request and process playlists from Lidarr.

        Returns:
            A list of lists containing playlist IDs.
        """
        endpoint = "/api/v1/importlist"
        raw_playlists = self.lidarr_request(endpoint_path=endpoint)

        if not raw_playlists:
            logger.warning("No playlists data received from Lidarr")
            return []

        spotify_playlists: list[list[str]] = []

        for entry in raw_playlists:
            if entry.get("listType") != "spotify":
                continue

            for field in entry.get("fields", []):
                if field.get("name") == "playlistIds":
                    playlist_ids = field.get("value", [])
                    if playlist_ids:
                        spotify_playlists.append(playlist_ids)
                        logger.debug(
                            f"Found Spotify playlist IDs in Lidarr: {playlist_ids}",
                        )

        if not spotify_playlists:
            logger.debug("No Spotify playlists found in Lidarr response")

        return spotify_playlists
