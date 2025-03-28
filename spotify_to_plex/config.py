"""Module for centralized configuration.

This module loads settings exclusively from environment variables with type hints,
defaults, and validates critical configuration parameters.
"""

import logging
import os


class Config:
	"""Application configuration loaded from environment variables."""

	SPOTIFY_TO_PLEX_VERSION: str = os.environ.get("COMMIT_SHA", "0.0.0")
	SPOTIFY_CLIENT_SECRET: str = os.environ.get("SPOTIFY_CLIENT_SECRET", "")
	SPOTIFY_CLIENT_ID: str = os.environ.get("SPOTIFY_CLIENT_ID", "")
	PLEX_TOKEN: str = os.environ.get("PLEX_TOKEN", "")
	PLEX_SERVER_URL: str = os.environ.get("PLEX_SERVER_URL", "")
	PLEX_REPLACE: bool = os.environ.get("PLEX_REPLACE", "False").lower() in (
		"true",
		"1",
		"yes",
		"t",
		"y",
	)
	PLEX_USERS: str = os.environ.get("PLEX_USERS", "")
	LIDARR_API_KEY: str = os.environ.get("LIDARR_API_KEY", "")
	LIDARR_API_URL: str = os.environ.get("LIDARR_API_URL", "")
	LIDARR_SYNC: bool = os.environ.get("LIDARR_SYNC", "false").lower() in (
		"true",
		"1",
		"yes",
		"t",
		"y",
	)
	MAX_PARALLEL_PLAYLISTS: int = int(os.environ.get("MAX_PARALLEL_PLAYLISTS", "3"))
	SECONDS_INTERVAL: int = int(os.environ.get("SECONDS_INTERVAL", "60"))
	ENABLE_CACHE: bool = os.environ.get("ENABLE_CACHE", "true").lower() in (
		"true",
		"1",
		"yes",
		"t",
		"y",
	)
	CACHE_TTL: int = int(os.environ.get("CACHE_TTL", "3600"))
	CACHE_DIR: str = os.environ.get("CACHE_DIR", "")
	MANUAL_PLAYLISTS: str = os.environ.get("MANUAL_PLAYLISTS", "")
	FIRST_RUN: bool = os.environ.get("FIRST_RUN", "False").lower() in (
		"true",
		"1",
		"yes",
		"t",
		"y",
	)

	@classmethod
	def _parse_bool_env(cls, env_var: str, default: str = "False") -> bool:
		"""Parse a boolean environment variable.

		Args:
		    env_var (str): Environment variable name.
		    default (str): Default value.

		Returns:
		    bool: Parsed boolean.
		"""
		return os.environ.get(env_var, default).lower() in (
			"true",
			"1",
			"yes",
			"t",
			"y",
		)

	@classmethod
	def validate(cls: type["Config"]) -> list[str]:
		"""Validate configuration parameters and return warnings.

		Returns:
		    List[str]: List of configuration warnings.
		"""
		warnings: list[str] = []
		logging.debug(
			"Spotify Client ID is %s", "set" if cls.SPOTIFY_CLIENT_ID else "not set"
		)
		logging.debug(
			"Spotify Client Secret is %s",
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
			warnings.append(
				f"High parallelism ({cls.MAX_PARALLEL_PLAYLISTS}) may cause rate limiting"
			)
		return warnings
