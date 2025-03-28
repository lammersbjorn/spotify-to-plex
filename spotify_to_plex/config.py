"""Configuration loaded exclusively from environment variables."""

import logging
import os
import socket
from typing import Dict, List

class Config:
    """Application configuration loaded from environment variables."""

    # Version information - dynamically set during build
    SPOTIFY_TO_PLEX_VERSION = "v2.1.0"  # Default version as fallback

    # Spotify API configuration
    # Spotify Client Secret (keep this secure)
    SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "")
    # Spotify Client ID
    SPOTIFY_CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID", "")

    # Plex configuration
    PLEX_TOKEN = os.environ.get("PLEX_TOKEN", "")
    PLEX_SERVER_URL = os.environ.get("PLEX_SERVER_URL", "")
    PLEX_REPLACE = os.environ.get("PLEX_REPLACE", "False").lower() in (
        "true",
        "1",
        "yes",
        "t",
        "y",
    )
    PLEX_USERS = os.environ.get("PLEX_USERS", "")

    # Lidarr configuration
    LIDARR_API_KEY = os.environ.get("LIDARR_API_KEY", "")
    LIDARR_API_URL = os.environ.get("LIDARR_API_URL", "")
    LIDARR_SYNC = os.environ.get("LIDARR_SYNC", "false").lower() in (
        "true",
        "1",
        "yes",
        "t",
        "y",
    )

    # Performance settings
    WORKER_COUNT = int(os.environ.get("WORKER_COUNT", "10"))
    SECONDS_INTERVAL = int(os.environ.get("SECONDS_INTERVAL", "60"))

    # Playlist configuration
    MANUAL_PLAYLISTS = os.environ.get("MANUAL_PLAYLISTS", "")
    FIRST_RUN = os.environ.get("FIRST_RUN", "False").lower() in (
        "true",
        "1",
        "yes",
        "t",
        "y",
    )

    @classmethod
    def validate(cls: type["Config"]) -> list[str]:
        """Validate configuration and return a list of warnings."""
        warnings = []

        # Log configuration status (without revealing sensitive values)
        logging.debug(
            "DEBUG: Spotify Client ID is %s",
            "set" if cls.SPOTIFY_CLIENT_ID else "not set",
        )
        logging.debug(
            "DEBUG: Spotify Client Secret is %s",
            "set" if cls.SPOTIFY_CLIENT_SECRET else "not set",
        )

        if not cls.SPOTIFY_CLIENT_SECRET or not cls.SPOTIFY_CLIENT_ID:
            warnings.append("Spotify API credentials are missing")

        if not cls.PLEX_TOKEN or not cls.PLEX_SERVER_URL:
            warnings.append("Plex credentials are missing")

        if cls.LIDARR_SYNC and (not cls.LIDARR_API_KEY or not cls.LIDARR_API_URL):
            warnings.append("Lidarr sync is enabled but API credentials are missing")

        if not cls.LIDARR_SYNC and not cls.MANUAL_PLAYLISTS:
            warnings.append("No playlists configured for sync")

        return warnings
