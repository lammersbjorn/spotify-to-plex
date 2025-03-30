"""Module for interacting with the Spotify API.

This module encapsulates Spotify API operations including authenticating,
retrieving playlist details, and rate‑limited API calls. All methods now include
Google‑style docstrings and comprehensive type hints.
"""

from collections.abc import Callable
import logging
import time
from typing import Any, Optional, TypeVar

import httpx
from loguru import logger
import spotipy
from spotipy.exceptions import SpotifyException
from spotipy.oauth2 import SpotifyClientCredentials

from spotify_to_plex.config import Config
from spotify_to_plex.utils.cache import cache_result

logging.getLogger("spotipy.client").setLevel(logging.CRITICAL)

# HTTP status codes
HTTP_UNAUTHORIZED = 401
HTTP_NOT_FOUND = 404
HTTP_RATE_LIMIT = 429

# API retry configuration
MAX_RETRIES = 3
BASE_RETRY_DELAY = 2  # seconds

# Cache TTL values (in seconds)
PLAYLIST_NAME_CACHE_TTL = 3600  # 1 hour
PLAYLIST_TRACKS_CACHE_TTL = 7200  # 2 hours
PLAYLIST_POSTER_CACHE_TTL = 86400  # 24 hours

# Type variable for generic function return type
T = TypeVar("T")


class SpotifyClass:
	"""Encapsulates Spotify API operations for playlists and track retrieval."""

	def __init__(self) -> None:
		"""Initialize the Spotify API client using configuration settings.

		Raises:
		    SpotifyException: On authentication failure.
		"""
		self.spotify_id: str = Config.SPOTIFY_CLIENT_ID
		self.spotify_key: str = Config.SPOTIFY_CLIENT_SECRET
		self.request_timeout: int = 30
		self.sp = self.connect_spotify()

	def connect_spotify(self) -> spotipy.Spotify:
		"""Establish a connection with the Spotify API.

		Returns:
		    spotipy.Spotify: Authenticated Spotify client.

		Raises:
		    SpotifyException: For authentication issues.
		    httpx.TimeoutException: On connection timeouts.
		    httpx.ConnectError: On network errors.
		"""
		try:
			with httpx.Client(timeout=self.request_timeout) as session:
				auth_manager = SpotifyClientCredentials(
					client_id=self.spotify_id, client_secret=self.spotify_key
				)
				spotify = spotipy.Spotify(
					auth_manager=auth_manager, requests_session=session
				)
				logger.debug("Testing Spotify API connection...")
				spotify.search(q="test", limit=1, type="track")
				logger.debug("Spotify API connection successful")
				return spotify
		except SpotifyException as e:
			logger.error(f"Failed to connect to Spotify API: {e}")
			raise
		except (httpx.TimeoutException, httpx.ConnectError) as exc:
			logger.error(f"Connection error with Spotify API: {exc}")
			raise
		except Exception as exc:
			logger.error(
				f"Unexpected error connecting to Spotify API: {type(exc).__name__}: {exc}"
			)
			raise

	def _execute_with_retry(
		self, func: Callable[..., T], *args: Any, **kwargs: Any
	) -> T:
		"""Execute a function with retry logic for Spotify API calls.

		Args:
		    func (Callable[..., T]): Function to call.

		Returns:
		    T: Result of the function call.

		Raises:
		    SpotifyException: When maximum retries are exceeded.
		"""
		last_exception = None
		for attempt in range(MAX_RETRIES):
			try:
				return func(*args, **kwargs)
			except SpotifyException as e:
				last_exception = e
				if e.http_status == 429:
					# Use Retry-After header if available
					retry_after = None
					if hasattr(e, "headers") and e.headers:
						retry_after = e.headers.get("Retry-After")
					try:
						wait_time = (
							int(retry_after)
							if retry_after is not None
							else BASE_RETRY_DELAY * (attempt + 1)
						)
					except Exception:
						wait_time = BASE_RETRY_DELAY * (attempt + 1)
					logger.warning(
						f"Rate limited by Spotify API. Waiting {wait_time}s before retry {attempt+1}/{MAX_RETRIES}"
					)
					time.sleep(wait_time)
					continue
				elif e.http_status == 404:
					raise
				elif attempt < MAX_RETRIES - 1:
					wait_time = BASE_RETRY_DELAY * (attempt + 1)
					logger.warning(
						f"Spotify API error (code {e.http_status}). Retrying in {wait_time}s ({attempt+1}/{MAX_RETRIES})"
					)
					time.sleep(wait_time)
					continue
				else:
					logger.error(
						f"Spotify API error after {MAX_RETRIES} attempts (code {e.http_status})"
					)
					raise
			except (httpx.TimeoutException, httpx.ConnectError) as e:
				last_exception = e
				if attempt < MAX_RETRIES - 1:
					wait_time = BASE_RETRY_DELAY * (attempt + 1)
					logger.warning(
						f"Connection error: {e}. Retrying in {wait_time}s ({attempt+1}/{MAX_RETRIES})"
					)
					time.sleep(wait_time)
					continue
				logger.error(f"Connection error after {MAX_RETRIES} attempts: {e}")
				raise
		if last_exception:
			raise last_exception
		raise Exception(f"Failed after {MAX_RETRIES} attempts")

	@cache_result(ttl=PLAYLIST_NAME_CACHE_TTL)  # Cache for 1 hour using memory
	def get_playlist_name(self, playlist_id: str) -> Optional[str]:
		"""Retrieve the name of a Spotify playlist.

		Args:
		    playlist_id (str): The Spotify playlist ID.

		Returns:
		    Optional[str]: The playlist name if available, else None.

		Raises:
		    SpotifyException: If there's an error accessing the Spotify API
		"""
		try:
			playlist = self._execute_with_retry(
				self.sp.playlist, playlist_id, fields="name"
			)
			name = playlist.get("name")
			if name:
				logger.debug(f"Retrieved playlist name: '{name}'")
				return name

			logger.warning(f"Playlist {playlist_id} has no name")
			return None

		except SpotifyException as e:
			if hasattr(e, "http_status") and e.http_status == HTTP_NOT_FOUND:
				logger.warning(
					f"Playlist not found: '{playlist_id}'. It may have been deleted or made private."
				)
				return None
			else:
				logger.warning(
					f"Error accessing Spotify playlist '{playlist_id}': code {getattr(e, 'http_status', 'unknown')}"
				)
				raise
		except Exception as exc:
			logger.warning(f"Error retrieving playlist name for ID {playlist_id}")
			logger.debug(f"Exception details: {type(exc).__name__}: {exc}")
			return None

	@cache_result(ttl=PLAYLIST_TRACKS_CACHE_TTL, use_disk=True)
	def get_playlist_tracks(self, playlist_id: str) -> list[tuple[str, str]]:
		"""Get all track names and artist names from a Spotify playlist.

		Args:
		    playlist_id (str): Spotify playlist ID.

		Returns:
		    List[Tuple[str, str]]: List of (track_name, artist_name) tuples.

		Raises:
		    SpotifyException: If there's an error accessing the Spotify API
		"""
		tracks: list[tuple[str, str]] = []
		try:
			results = self._execute_with_retry(self.sp.playlist_tracks, playlist_id)

			total_tracks = results.get("total", 0)
			logger.info(
				f"Fetching {total_tracks} tracks from Spotify playlist {playlist_id}"
			)

			fetched_count = 0

			while results:
				items = results.get("items", [])
				for item in items:
					if not item or not item.get("track"):
						continue

					track = item["track"]
					if not track.get("name") or not track.get("artists"):
						continue

					track_name = track["name"]
					artist_name = (
						track["artists"][0]["name"]
						if track["artists"]
						else "Unknown Artist"
					)
					tracks.append((track_name, artist_name))

				fetched_count += len(items)

				if total_tracks > 100:
					logger.debug(
						f"Fetched {fetched_count}/{total_tracks} tracks from playlist"
					)

				if results.get("next"):
					results = self._execute_with_retry(self.sp.next, results)
				else:
					results = None

			logger.info(
				f"Retrieved {len(tracks)}/{total_tracks} tracks from Spotify playlist {playlist_id}"
			)

		except SpotifyException as e:
			if hasattr(e, "http_status") and e.http_status == HTTP_NOT_FOUND:
				logger.warning(
					f"Playlist {playlist_id} not found. "
					"It may have been deleted or made private."
				)
			else:
				logger.warning(
					f"Error accessing Spotify playlist {playlist_id}: code {getattr(e, 'http_status', 'unknown')}"
				)
		except Exception as exc:
			logger.warning(
				f"Error fetching tracks from Spotify for playlist {playlist_id}"
			)
			logger.debug(f"Exception details: {type(exc).__name__}: {exc}")

		return tracks

	@cache_result(ttl=PLAYLIST_POSTER_CACHE_TTL)  # Cache for 24 hours
	def get_playlist_poster(self, playlist_id: str) -> Optional[str]:
		"""Retrieve the cover art URL for a Spotify playlist.

		Args:
		    playlist_id (str): The Spotify playlist ID.

		Returns:
		    Optional[str]: The cover art URL if found, else None.

		Raises:
		    SpotifyException: If there's an error accessing the Spotify API
		"""
		try:
			playlist_data = self._execute_with_retry(
				self.sp.playlist,
				playlist_id,
				fields="images",
			)

			if playlist_data and playlist_data.get("images"):
				images = playlist_data["images"]
				if images and len(images) > 0:
					image_url = images[0].get("url")
					if image_url:
						logger.debug(
							f"Retrieved cover art URL for playlist {playlist_id}"
						)
						return image_url

			logger.debug(f"No cover art found for playlist {playlist_id}")
			return None

		except SpotifyException as e:
			if hasattr(e, "http_status") and e.http_status == HTTP_NOT_FOUND:
				logger.warning(
					f"Playlist {playlist_id} not found. "
					"It may have been deleted or made private."
				)
			else:
				logger.warning(
					f"Error accessing Spotify playlist {playlist_id}: code {getattr(e, 'http_status', 'unknown')}"
				)
			return None
		except Exception as exc:
			logger.warning(f"Error retrieving cover art for playlist {playlist_id}")
			logger.debug(f"Exception details: {type(exc).__name__}: {exc}")
			return None
