"""Module for interacting with the Spotify API."""


import spotipy
from loguru import logger
from spotipy import Spotify
from spotipy.oauth2 import SpotifyClientCredentials

from spotify_to_plex.config import Config

# HTTP status code constants
HTTP_UNAUTHORIZED = 401
HTTP_RATE_LIMIT = 429
HTTP_NOT_FOUND = 404


class SpotifyClass:
    """Handles interactions with the Spotify API."""

    def __init__(self: "SpotifyClass") -> None:
        """Initialize the Spotify client using Client ID and Client Secret from config."""
        self.spotify_id = Config.SPOTIFY_CLIENT_ID
        self.spotify_key = Config.SPOTIFY_CLIENT_SECRET

        if not self.spotify_id or not self.spotify_key:
            logger.warning(
                "Spotify Client ID or Client Secret not properly configured",
            )
            logger.warning(
                "Please set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET in your .env file",
            )

        self.sp = self.connect_spotify()

    def connect_spotify(self: "SpotifyClass") -> Spotify:
        """Establish a connection to the Spotify API using client credentials authentication.

        This authentication method only allows accessing public data that doesn't require
        user permissions. For user-specific data, a different authentication flow
        would be required.

        Returns:
            An authenticated Spotify client with application-level access.
        """
        try:
            auth_manager = SpotifyClientCredentials(
                client_id=self.spotify_id,
                client_secret=self.spotify_key,
            )
            spotify = spotipy.Spotify(auth_manager=auth_manager)

            # Test the connection with a simple public data request
            spotify.search(q="test", limit=1, type="track")
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

    def get_playlist_tracks(
        self: "SpotifyClass",
        playlist_id: str,
    ) -> list[tuple[str, str]]:
        """Fetch tracks from the given Spotify playlist.

        Args:
            playlist_id: The Spotify playlist ID.

        Returns:
            A list of tuples with track name and artist name.
        """
        tracks: list[tuple[str, str]] = []
        try:
            results = self.sp.playlist_tracks(playlist_id)
            total_tracks = results.get("total", 0)
            logger.debug(
                f"Fetching {total_tracks} tracks from Spotify playlist {playlist_id}",
            )

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

                # Get next batch if available
                results = self.sp.next(results) if results.get("next") else None

            logger.debug(
                f"Retrieved {len(tracks)}/{total_tracks} tracks from Spotify playlist",
            )

        except spotipy.exceptions.SpotifyException as e:
            if e.http_status == HTTP_NOT_FOUND:
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

    def get_playlist_name(self: "SpotifyClass", playlist_id: str) -> str | None:
        """Retrieve the name of a Spotify playlist.

        Args:
            playlist_id: The Spotify playlist ID.

        Returns:
            The playlist name if available, else None.
        """
        try:
            playlist_data = self.sp.playlist(playlist_id, fields="name")
            name = playlist_data.get("name")
            if name:
                logger.debug(f"Retrieved playlist name: '{name}'")
                return name
        except spotipy.exceptions.SpotifyException as e:
            if e.http_status == HTTP_NOT_FOUND:
                logger.warning(
                    f"Playlist {playlist_id} not found (404). "
                    "It may have been deleted or made private.",
                )
            else:
                logger.exception(
                    f"Error retrieving playlist name for ID {playlist_id}: {e}",
                )
            return None
        except Exception as exc:
            logger.exception(
                f"Error retrieving playlist name for ID {playlist_id}: {exc}",
            )
            return None

        logger.warning(f"Playlist {playlist_id} has no name")
        return None

    def get_playlist_poster(self: "SpotifyClass", playlist_id: str) -> str | None:
        """Retrieve the cover art URL for a Spotify playlist.

        Args:
            playlist_id: The Spotify playlist ID.

        Returns:
            The cover art URL if found, else None.
        """
        try:
            playlist_data = self.sp.playlist(playlist_id, fields="images")

            if playlist_data and playlist_data.get("images"):
                image_url = playlist_data["images"][0].get("url")
                if image_url:
                    logger.debug(f"Retrieved cover art URL for playlist {playlist_id}")
                    return image_url
        except spotipy.exceptions.SpotifyException as e:
            if e.http_status == HTTP_NOT_FOUND:
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
