"""Configuration loaded exclusively from environment variables."""

import logging
import os


class Config:
    """Application configuration loaded from environment variables."""

    # Version information
    SPOTIFY_TO_PLEX_VERSION = os.environ.get("COMMIT_SHA", "0.0.1")

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
    # Note: WORKER_COUNT is deprecated, use MAX_PARALLEL_PLAYLISTS instead
    MAX_PARALLEL_PLAYLISTS = int(os.environ.get("MAX_PARALLEL_PLAYLISTS", "3"))
    SECONDS_INTERVAL = int(os.environ.get("SECONDS_INTERVAL", "60"))

    # Caching configuration
    ENABLE_CACHE = os.environ.get("ENABLE_CACHE", "true").lower() in (
        "true",
        "1",
        "yes",
        "t",
        "y",
    )
    CACHE_TTL = int(os.environ.get("CACHE_TTL", "3600"))  # Default: 1 hour
    CACHE_DIR = os.environ.get("CACHE_DIR", "")  # Custom cache directory

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

        if cls.MAX_PARALLEL_PLAYLISTS > 5:
            warnings.append(f"High parallelism ({cls.MAX_PARALLEL_PLAYLISTS}) may cause rate limiting")

        return warnings
