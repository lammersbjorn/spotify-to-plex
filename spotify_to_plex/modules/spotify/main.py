"""Module for interacting with the Spotify API."""

import time
import re
from typing import Dict, List, Optional, Tuple, Any

import httpx
import spotipy
from loguru import logger
from spotipy.oauth2 import SpotifyClientCredentials

from spotify_to_plex.config import Config
from spotify_to_plex.utils.cache import cache_result

# HTTP status codes
HTTP_UNAUTHORIZED = 401
HTTP_NOT_FOUND = 404
HTTP_RATE_LIMIT = 429

class SpotifyClass:
    """Encapsulates Spotify API operations."""

    def __init__(self: "SpotifyClass") -> None:
        """Initialize Spotify API client."""
        # Initialize credentials and client
        self.spotify_id = Config.SPOTIFY_CLIENT_ID
        self.spotify_key = Config.SPOTIFY_CLIENT_SECRET
        self.request_timeout = 30  # seconds

        client_credentials_manager = SpotifyClientCredentials()
        self.sp = spotipy.Spotify(
            client_credentials_manager=client_credentials_manager,
            requests_timeout=self.request_timeout,  # Longer timeout for stability
        )

    def connect_spotify(self: "SpotifyClass") -> spotipy.Spotify:
        """Establish a connection to the Spotify API using client credentials authentication.

        This authentication method only allows accessing public data that doesn't require
        user permissions. For user-specific data, a different authentication flow
        would be required.

        Returns:
            An authenticated Spotify client with application-level access.
        """
        try:
            # Create a custom session for better timeout handling
            session = httpx.Client(timeout=self.request_timeout)

            auth_manager = SpotifyClientCredentials(
                client_id=self.spotify_id,
                client_secret=self.spotify_key,
            )
            spotify = spotipy.Spotify(auth_manager=auth_manager, requests_session=session)

            # Test the connection with a simple public data request
            logger.debug("Testing Spotify API connection...")
            spotify.search(q="test", limit=1, type="track")
            logger.debug("Spotify API connection successful")
        except spotipy.exceptions.SpotifyException as e:
            logger.error(f"Failed to connect to Spotify API: {e}")
            if e.http_status == HTTP_UNAUTHORIZED:
                logger.error(
                    "Authentication failed. Check your SPOTIFY_CLIENT_ID and "
                    "SPOTIFY_CLIENT_SECRET values",
                )
            elif e.http_status == HTTP_RATE_LIMIT:
                logger.error(
                    "Rate limit exceeded. Please wait before making more requests",
                )

            # Return a dummy client that will be handled gracefully when used
            return spotipy.Spotify()
        except Exception as exc:
            logger.error(
                f"Unexpected error connecting to Spotify API: {type(exc).__name__}: {exc}",
            )
            return spotipy.Spotify()
        else:
            logger.debug(
                "Successfully connected to Spotify API using client credentials",
            )
            return spotify

    def _execute_with_retry(self, func: callable, *args, **kwargs) -> Any:
        """Execute a function with retry logic for API calls.

        Args:
            func: The function to call
            *args: Positional arguments for the function
            **kwargs: Keyword arguments for the function

        Returns:
            The result of the function call

        Raises:
            Exception: If all retries fail
        """
        max_retries = 3
        retry_delay = 2

        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except spotipy.exceptions.SpotifyException as e:
                if e.http_status == HTTP_RATE_LIMIT:
                    # Rate limited - wait longer on each retry
                    wait_time = retry_delay * (attempt + 1)
                    logger.warning(f"Rate limited by Spotify API. Waiting {wait_time}s before retry {attempt+1}/{max_retries}")
                    time.sleep(wait_time)
                    continue
                elif attempt < max_retries - 1:
                    # Other Spotify errors - retry with backoff
                    wait_time = retry_delay * (attempt + 1)
                    logger.warning(f"Spotify API error: {e}. Retrying in {wait_time}s ({attempt+1}/{max_retries})")
                    time.sleep(wait_time)
                    continue
                else:
                    # Max retries reached
                    logger.error(f"Spotify API error after {max_retries} attempts: {e}")
                    raise
            except Exception as e:
                # Non-Spotify errors - don't retry
                logger.error(f"Error calling Spotify API: {e}")
                raise

        # This should never be reached but just in case
        raise Exception(f"Failed after {max_retries} attempts")

    @cache_result(ttl=3600)  # Cache for 1 hour using memory
    def get_playlist_name(self: "SpotifyClass", playlist_id: str) -> str | None:
        """Retrieve the name of a Spotify playlist.

        Args:
            playlist_id: The Spotify playlist ID.

        Returns:
            The playlist name if available, else None.
        """
        try:
            # More targeted API request (just get the name)
            playlist = self.sp.playlist(playlist_id, fields="name")
            name = playlist.get("name")
            if name:
                logger.debug(f"Retrieved playlist name: '{name}'")
                return name
        except spotipy.exceptions.SpotifyException as e:
            # Improve 404 error handling
            if hasattr(e, 'http_status') and e.http_status == HTTP_NOT_FOUND:
                logger.error(f"Playlist not found: '{playlist_id}'. It may have been deleted or made private.")
                # Return None explicitly for 404 so callers can handle this specifically
                return None
            elif "not find" in str(e).lower() or "not exist" in str(e).lower():
                logger.error(f"Playlist not found: '{playlist_id}'. Error message: {e}")
                return None
            else:
                logger.error(f"Error fetching playlist '{playlist_id}': {e}")
                raise
        except Exception as exc:
            logger.exception(f"Error retrieving playlist name for ID {playlist_id}: {exc}")
            return None

        logger.warning(f"Playlist {playlist_id} has no name")
        return None

    @cache_result(ttl=7200, use_disk=True)
    def get_playlist_tracks(
        self: "SpotifyClass", playlist_id: str
    ) -> list[tuple[str, str]]:
        """Get all track names and artist names from a Spotify playlist.

        Args:
            playlist_id: Spotify playlist ID.

        Returns:
            List of (track_name, artist_name) tuples.
        """
        tracks: list[tuple[str, str]] = []
        try:
            # Use retry logic for API call
            results = self._execute_with_retry(self.sp.playlist_tracks, playlist_id)

            total_tracks = results.get("total", 0)
            logger.debug(
                f"Fetching {total_tracks} tracks from Spotify playlist {playlist_id}",
            )

            # Track progress for large playlists
            fetched_count = 0

            while results:
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

                fetched_count += len(results.get("items", []))

                # Log progress for large playlists
                if total_tracks > 100:
                    logger.debug(f"Fetched {fetched_count}/{total_tracks} tracks from playlist")

                # Get next batch if available - with retry
                if results.get("next"):
                    results = self._execute_with_retry(self.sp.next, results)
                else:
                    results = None

            logger.debug(
                f"Retrieved {len(tracks)}/{total_tracks} tracks from Spotify playlist",
            )

        except spotipy.exceptions.SpotifyException as e:
            if hasattr(e, 'http_status') and e.http_status == HTTP_NOT_FOUND:
                logger.warning(
                    f"Playlist {playlist_id} not found (404). "
                    "It may have been deleted or made private.",
                )
            else:
                logger.exception(
                    f"Error fetching tracks from Spotify for playlist {playlist_id}: {e}",
                )
        except Exception as exc:
            logger.exception(
                f"Error fetching tracks from Spotify for playlist {playlist_id}: {exc}",
            )

        return tracks

    @cache_result(ttl=86400)  # Cache for 24 hours using memory (covers rarely change)
    def get_playlist_poster(self: "SpotifyClass", playlist_id: str) -> str | None:
        """Retrieve the cover art URL for a Spotify playlist.

        Args:
            playlist_id: The Spotify playlist ID.

        Returns:
            The cover art URL if found, else None.
        """
        try:
            playlist_data = self._execute_with_retry(
                self.sp.playlist,
                playlist_id,
                fields="images"
            )

            if playlist_data and playlist_data.get("images"):
                image_url = playlist_data["images"][0].get("url")
                if image_url:
                    logger.debug(f"Retrieved cover art URL for playlist {playlist_id}")
                    return image_url
        except spotipy.exceptions.SpotifyException as e:
            if hasattr(e, 'http_status') and e.http_status == HTTP_NOT_FOUND:
                logger.warning(
                    f"Playlist {playlist_id} not found (404). "
                    "It may have been deleted or made private.",
                )
            else:
                logger.exception(
                    f"Error retrieving cover art for playlist {playlist_id}: {e}",
                )
            return None
        except Exception as exc:
            logger.exception(
                f"Error retrieving cover art for playlist {playlist_id}: {exc}",
            )
            return None

        logger.debug(f"No cover art found for playlist {playlist_id}")
        return None
