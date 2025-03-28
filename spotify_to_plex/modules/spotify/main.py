"""Module for interacting with the Spotify API."""

import logging
import time
from functools import lru_cache
from typing import Optional

import spotipy
from loguru import logger
from spotipy import Spotify
from spotipy.oauth2 import SpotifyClientCredentials

from spotify_to_plex.config import Config

# HTTP status code constants
HTTP_UNAUTHORIZED = 401
HTTP_RATE_LIMIT = 429
HTTP_NOT_FOUND = 404

# Retry constants
MAX_RETRIES = 3
RETRY_BASE_DELAY = 2
MAX_TRACKS_PER_REQUEST = 100

# Silence the spotipy logger's HTTP errors to avoid duplicate error messages
spotipy_logger = logging.getLogger("spotipy")
spotipy_logger.setLevel(logging.ERROR)  # Only show errors, not DEBUG or INFO


class SpotifyClass:
    """Handles interactions with the Spotify API."""

    def __init__(self: "SpotifyClass") -> None:
        """Initialize the Spotify client using Client ID and Client Secret from config."""
        self.spotify_id = Config.SPOTIFY_CLIENT_ID
        self.spotify_key = Config.SPOTIFY_CLIENT_SECRET
        self._track_cache: dict[str, list[tuple[str, str]]] = {}
        self._name_cache: dict[str, Optional[str]] = {}
        self._image_cache: dict[str, Optional[str]] = {}
        self._last_request_time = 0
        self._min_request_interval = 0.05  # 50ms minimum between requests
        self._unavailable_playlists: dict[
            str, str
        ] = {}  # Map playlist IDs to reason messages

        if not self.spotify_id or not self.spotify_key:
            logger.warning(
                "Spotify Client ID or Client Secret not properly configured",
            )
            logger.warning(
                "Please set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET in your .env file",
            )

        self.sp = self.connect_spotify()

    def connect_spotify(self: "SpotifyClass") -> Spotify:
        """Establish a connection to the Spotify API with retry logic.

        Returns:
            An authenticated Spotify client with application-level access.
        """
        for attempt in range(MAX_RETRIES):
            try:
                auth_manager = SpotifyClientCredentials(
                    client_id=self.spotify_id,
                    client_secret=self.spotify_key,
                    requests_timeout=30,  # Increased timeout for stability
                )
                spotify = spotipy.Spotify(
                    auth_manager=auth_manager,
                    retries=3,  # Built-in retries
                    status_retries=3,
                    backoff_factor=1.0,
                )

                # Test the connection with a simple public data request
                spotify.search(q="test", limit=1, type="track")
                logger.debug(
                    "Successfully connected to Spotify API using client credentials",
                )
                return spotify

            except spotipy.exceptions.SpotifyException as e:
                if attempt < MAX_RETRIES - 1:
                    if e.http_status == HTTP_RATE_LIMIT:
                        retry_after = int(
                            e.headers.get(
                                "Retry-After", RETRY_BASE_DELAY * (attempt + 1)
                            )
                        )
                        logger.warning(
                            f"Rate limit exceeded. Retrying in {retry_after}s (attempt {attempt+1}/{MAX_RETRIES})",
                        )
                        time.sleep(retry_after)
                    else:
                        wait_time = RETRY_BASE_DELAY * (2**attempt)
                        logger.warning(
                            f"Spotify API connection failed. Retrying in {wait_time}s "
                            f"(attempt {attempt+1}/{MAX_RETRIES}): {e}",
                        )
                        time.sleep(wait_time)
                else:
                    if e.http_status == HTTP_UNAUTHORIZED:
                        logger.error(
                            "Authentication failed after retries. Check your SPOTIFY_CLIENT_ID and "
                            "SPOTIFY_CLIENT_SECRET values",
                        )
                    elif e.http_status == HTTP_RATE_LIMIT:
                        logger.error(
                            "Rate limit exceeded after multiple retries. "
                            "Consider adjusting your request frequency.",
                        )
                    else:
                        logger.error(
                            f"Failed to connect to Spotify API after {MAX_RETRIES} attempts: {e}"
                        )

                    # Return a dummy client that will be handled gracefully when used
                    return spotipy.Spotify()
            except Exception as exc:
                if attempt < MAX_RETRIES - 1:
                    wait_time = RETRY_BASE_DELAY * (2**attempt)
                    logger.warning(
                        f"Unexpected error connecting to Spotify API. Retrying in {wait_time}s "
                        f"(attempt {attempt+1}/{MAX_RETRIES}): {exc}",
                    )
                    time.sleep(wait_time)
                else:
                    logger.error(
                        f"Unexpected error connecting to Spotify API after {MAX_RETRIES} attempts: {exc}",
                    )
                    return spotipy.Spotify()

        # This should never happen (for type checking)
        return spotipy.Spotify()

    def _rate_limit_handler(self: "SpotifyClass") -> None:
        """Ensure we don't exceed Spotify's rate limits by adding delays between requests."""
        now = time.time()
        elapsed = now - self._last_request_time

        # If we're making requests too quickly, sleep for a bit
        if elapsed < self._min_request_interval:
            time.sleep(self._min_request_interval - elapsed)

        # Update last request time
        self._last_request_time = time.time()

    def get_playlist_tracks(
        self: "SpotifyClass",
        playlist_id: str,
    ) -> list[tuple[str, str]]:
        """Fetch tracks from the given Spotify playlist with caching and error handling.

        Args:
            playlist_id: The Spotify playlist ID.

        Returns:
            A list of tuples with track name and artist name.
        """
        # Check if playlist is known to be unavailable
        if playlist_id in self._unavailable_playlists:
            logger.info(
                f"Skipping known unavailable playlist {playlist_id}: {self._unavailable_playlists[playlist_id]}"
            )
            return []

        # Check cache first
        if playlist_id in self._track_cache:
            logger.debug(f"Using cached tracks for playlist {playlist_id}")
            return self._track_cache[playlist_id]

        tracks: list[tuple[str, str]] = []
        start_time = time.time()

        try:
            self._rate_limit_handler()

            # Get initial batch and total count
            results = self.sp.playlist_tracks(playlist_id, limit=MAX_TRACKS_PER_REQUEST)
            total_tracks = results.get("total", 0)
            logger.debug(
                f"Fetching {total_tracks} tracks from Spotify playlist {playlist_id}",
            )

            # Process all batches
            batch_count = 0
            while True:
                batch_count += 1

                # Process current batch of tracks
                for item in results.get("items", []):
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

                # Check if we have more batches to fetch
                if not results.get("next"):
                    break

                # Rate limit control before next request
                self._rate_limit_handler()

                # Get next batch
                logger.debug(
                    f"Fetching batch {batch_count+1} of tracks for playlist {playlist_id}"
                )
                results = self.sp.next(results)

            duration = time.time() - start_time
            logger.debug(
                f"Retrieved {len(tracks)}/{total_tracks} tracks from Spotify playlist "
                f"{playlist_id} in {duration:.2f}s",
            )

            # Cache the result for future use
            self._track_cache[playlist_id] = tracks

        except spotipy.exceptions.SpotifyException as e:
            if e.http_status == HTTP_NOT_FOUND:
                message = "The playlist is no longer available or might be private"
                logger.warning(
                    f"Playlist {playlist_id} not found (404). {message}",
                )
                # Mark this playlist as unavailable to avoid repeated lookups
                self._unavailable_playlists[playlist_id] = message
            elif e.http_status == HTTP_RATE_LIMIT:
                retry_after = int(e.headers.get("Retry-After", 5))
                logger.warning(
                    f"Rate limit hit when fetching tracks. Retry after {retry_after} seconds.",
                )
            else:
                logger.exception(
                    f"Spotify API error fetching tracks for playlist {playlist_id}: {e}",
                )
        except Exception as exc:
            logger.exception(
                f"Unexpected error fetching tracks from Spotify for playlist {playlist_id}: {exc}",
            )

        return tracks

    @lru_cache(maxsize=64)
    def get_playlist_name(self: "SpotifyClass", playlist_id: str) -> Optional[str]:
        """Retrieve the name of a Spotify playlist with caching.

        Args:
            playlist_id: The Spotify playlist ID.

        Returns:
            The playlist name if available, else None.
        """
        # Check if playlist is known to be unavailable
        if playlist_id in self._unavailable_playlists:
            return f"Unavailable Playlist ({playlist_id})"

        # Check cache first
        if playlist_id in self._name_cache:
            return self._name_cache[playlist_id]

        for attempt in range(MAX_RETRIES):
            try:
                self._rate_limit_handler()
                playlist_data = self.sp.playlist(playlist_id, fields="name")
                name = playlist_data.get("name")
                if name:
                    logger.debug(f"Retrieved playlist name: '{name}'")
                    self._name_cache[playlist_id] = name
                    return name

                logger.warning(f"Playlist {playlist_id} has no name")
                self._name_cache[playlist_id] = f"Unnamed Playlist ({playlist_id})"
                return self._name_cache[playlist_id]

            except spotipy.exceptions.SpotifyException as e:
                if e.http_status == HTTP_NOT_FOUND:
                    message = "Playlist no longer available or private"
                    # Only log as info since we'll show a user-friendly message elsewhere
                    logger.info(
                        f"Playlist {playlist_id} not found (404). {message}",
                    )
                    # Mark this playlist as unavailable
                    fallback_name = f"Unavailable Playlist ({playlist_id})"
                    self._name_cache[playlist_id] = fallback_name
                    self._unavailable_playlists[playlist_id] = message
                    return fallback_name

                elif e.http_status == HTTP_RATE_LIMIT and attempt < MAX_RETRIES - 1:
                    retry_after = int(
                        e.headers.get("Retry-After", RETRY_BASE_DELAY * (attempt + 1))
                    )
                    logger.warning(
                        f"Rate limit hit when getting playlist name. "
                        f"Retrying in {retry_after}s (attempt {attempt+1}/{MAX_RETRIES})",
                    )
                    time.sleep(retry_after)
                else:
                    logger.error(
                        f"Error retrieving playlist name for ID {playlist_id} (attempt {attempt+1}/{MAX_RETRIES}): {e}",
                    )
                    if attempt == MAX_RETRIES - 1:
                        fallback_name = f"Error Playlist ({playlist_id})"
                        self._name_cache[playlist_id] = fallback_name
                        return fallback_name
            except Exception as exc:
                logger.exception(
                    f"Unexpected error retrieving playlist name for ID {playlist_id} (attempt {attempt+1}/{MAX_RETRIES}): {exc}",
                )
                if attempt == MAX_RETRIES - 1:
                    fallback_name = f"Error Playlist ({playlist_id})"
                    self._name_cache[playlist_id] = fallback_name
                    return fallback_name
                time.sleep(RETRY_BASE_DELAY * (attempt + 1))

        fallback_name = f"Error Playlist ({playlist_id})"
        self._name_cache[playlist_id] = fallback_name
        return fallback_name

    @lru_cache(maxsize=64)
    def get_playlist_poster(self: "SpotifyClass", playlist_id: str) -> Optional[str]:
        """Retrieve the cover art URL for a Spotify playlist with caching.

        Args:
            playlist_id: The Spotify playlist ID.

        Returns:
            The cover art URL if found, else None.
        """
        # Check if playlist is known to be unavailable
        if playlist_id in self._unavailable_playlists:
            return None

        # Check cache first
        if playlist_id in self._image_cache:
            return self._image_cache[playlist_id]

        for attempt in range(MAX_RETRIES):
            try:
                self._rate_limit_handler()
                playlist_data = self.sp.playlist(playlist_id, fields="images")

                if playlist_data and playlist_data.get("images"):
                    image_url = playlist_data["images"][0].get("url")
                    if image_url:
                        logger.debug(
                            f"Retrieved cover art URL for playlist {playlist_id}"
                        )
                        self._image_cache[playlist_id] = image_url
                        return image_url

                logger.debug(f"No cover art found for playlist {playlist_id}")
                self._image_cache[playlist_id] = None
                return None

            except spotipy.exceptions.SpotifyException as e:
                if e.http_status == HTTP_NOT_FOUND:
                    logger.warning(
                        f"Playlist {playlist_id} not found (404) when getting cover art.",
                    )
                    self._image_cache[playlist_id] = None
                    return None

                elif e.http_status == HTTP_RATE_LIMIT and attempt < MAX_RETRIES - 1:
                    retry_after = int(
                        e.headers.get("Retry-After", RETRY_BASE_DELAY * (attempt + 1))
                    )
                    logger.warning(
                        f"Rate limit hit when getting playlist cover art. "
                        f"Retrying in {retry_after}s (attempt {attempt+1}/{MAX_RETRIES})",
                    )
                    time.sleep(retry_after)
                else:
                    logger.error(
                        f"Error retrieving cover art for playlist {playlist_id} (attempt {attempt+1}/{MAX_RETRIES}): {e}",
                    )
                    if attempt == MAX_RETRIES - 1:
                        self._image_cache[playlist_id] = None
                        return None
            except Exception as exc:
                logger.exception(
                    f"Unexpected error retrieving cover art for playlist {playlist_id} (attempt {attempt+1}/{MAX_RETRIES}): {exc}",
                )
                if attempt == MAX_RETRIES - 1:
                    self._image_cache[playlist_id] = None
                    return None
                time.sleep(RETRY_BASE_DELAY * (attempt + 1))

        # This should never happen due to the return in the loop
        return None
