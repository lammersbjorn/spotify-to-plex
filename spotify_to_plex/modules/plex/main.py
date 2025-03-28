"""Module for interacting with the Plex API."""

import datetime
import time
from functools import lru_cache
from typing import Dict, List, Optional, Tuple, Union

import httpx
from loguru import logger
from plexapi.audio import Track
from plexapi.exceptions import BadRequest, NotFound, Unauthorized
from plexapi.playlist import Playlist
from plexapi.server import PlexServer

from spotify_to_plex.config import Config

# Magic numbers as constants
MAX_DISPLAY_MISSING = 10
CHUNK_SIZE = 300
MAX_RETRIES = 3
RETRY_DELAY = 2


class PlexClass:
    """Encapsulates Plex operations."""

    def __init__(self: "PlexClass") -> None:
        """Initialize Plex connection using configuration values."""
        self.plex_url = Config.PLEX_SERVER_URL
        self.plex_token = Config.PLEX_TOKEN
        self.replacement_policy = Config.PLEX_REPLACE
        self._track_cache: Dict[str, List[Track]] = {}
        self._playlist_cache: Dict[str, Playlist] = {}

        if not self.plex_url or not self.plex_token:
            logger.warning("Plex credentials not properly configured")

        self.plex = self.connect_plex()

    def connect_plex(self: "PlexClass") -> PlexServer:
        """Connect to the Plex server with retry logic.

        Returns:
            An instance of PlexServer.
        """
        attempt = 0
        last_exception = None

        while attempt < MAX_RETRIES:
            try:
                # Create a custom session with disabled certificate verification
                # for self-signed certificates
                session = httpx.Client(
                    verify=False,  # nosec
                    timeout=30.0,  # Increased timeout for stability
                )
                server = PlexServer(
                    self.plex_url,
                    self.plex_token,
                    session=session,
                )
                # Test connection by accessing account
                _ = server.myPlexAccount()
                logger.debug(
                    f"Successfully connected to Plex server: {server.friendlyName}"
                )
                return server

            except Unauthorized:
                logger.error("Failed to connect to Plex: Unauthorized. Check your token.")
                raise  # Authorization errors won't be fixed by retrying

            except (httpx.ConnectError, httpx.TimeoutException) as e:
                attempt += 1
                last_exception = e
                retry_seconds = RETRY_DELAY * attempt
                logger.warning(
                    f"Connection to Plex failed (attempt {attempt}/{MAX_RETRIES}). "
                    f"Retrying in {retry_seconds}s: {str(e)}"
                )
                time.sleep(retry_seconds)

            except Exception as e:
                logger.exception(f"Failed to connect to Plex server: {e}")
                raise

        if last_exception:
            logger.error(f"Failed to connect to Plex after {MAX_RETRIES} attempts")
            raise last_exception

        # This should never happen (for type checking)
        raise ConnectionError("Failed to connect to Plex server")

    @lru_cache(maxsize=32)
    def _search_artist(self, music_library, artist_name: str) -> List:
        """Search for an artist in the music library with caching.

        Args:
            music_library: Plex music library section
            artist_name: Name of the artist to search for

        Returns:
            List of artist search results
        """
        try:
            return music_library.search(title=artist_name)
        except Exception as exc:
            logger.debug(f"Error searching for artist '{artist_name}': {exc}")
            return []

    def match_spotify_tracks_in_plex(
        self: "PlexClass",
        spotify_tracks: List[Tuple[str, str]],
    ) -> List[Track]:
        """Match Spotify tracks in the Plex music library with improved performance.

        Args:
            spotify_tracks: List of tuples (track name, artist name) from Spotify.

        Returns:
            List of matched Plex Track objects.
        """
        logger.info(f"Matching {len(spotify_tracks)} Spotify tracks in Plex")
        matched_tracks: List[Track] = []
        missing_tracks: List[Tuple[str, str]] = []
        total_tracks = len(spotify_tracks)
        start_time = time.time()

        # Cache key for tracks
        cache_key = ":".join([f"{artist}|{track}" for track, artist in spotify_tracks[:5]])
        if cache_key in self._track_cache:
            logger.info("Using cached track results")
            return self._track_cache[cache_key]

        try:
            music_library = self.plex.library.section("Music")
        except NotFound:
            logger.error("Music library not found in Plex")
            return []
        except Exception as exc:
            logger.error(f"Failed to access Music library in Plex: {exc}")
            return []

        artist_cache = {}  # Cache for search results per artist
        track_cache = {}   # Cache for direct track searches

        # Group tracks by artist to reduce API calls
        tracks_by_artist = {}
        for track_name, artist_name in spotify_tracks:
            if artist_name not in tracks_by_artist:
                tracks_by_artist[artist_name] = []
            tracks_by_artist[artist_name].append(track_name)

        # Process each artist
        for artist_name, track_names in tracks_by_artist.items():
            if artist_name not in artist_cache:
                artist_cache[artist_name] = self._search_artist(music_library, artist_name)

            artist_results = artist_cache[artist_name]

            if not artist_results:
                # All tracks from this artist will be missing
                for track_name in track_names:
                    missing_tracks.append((track_name, artist_name))
                continue

            # Try to find tracks for this artist
            artist_tracks = {}

            # Get all tracks from all artists that match this name
            for artist_item in artist_results:
                try:
                    for track in artist_item.tracks():
                        track_lower = track.title.lower()
                        if track_lower not in artist_tracks:
                            artist_tracks[track_lower] = track
                except Exception as exc:
                    logger.debug(f"Error accessing tracks for artist '{artist_name}': {exc}")

            # Match each track name against the retrieved tracks
            for track_name in track_names:
                track_lower = track_name.lower()
                if track_lower in artist_tracks:
                    matched_tracks.append(artist_tracks[track_lower])
                else:
                    # Try direct search as fallback
                    search_key = f"{track_name}:{artist_name}"
                    if search_key not in track_cache:
                        try:
                            results = music_library.searchTracks(
                                title=track_name,
                                artist=artist_name,
                            )
                            track_cache[search_key] = results[0] if results else None
                        except Exception as exc:
                            logger.debug(
                                f"Error in direct search for '{track_name}' by '{artist_name}': {exc}"
                            )
                            track_cache[search_key] = None

                    if track_cache[search_key]:
                        matched_tracks.append(track_cache[search_key])
                    else:
                        missing_tracks.append((track_name, artist_name))

        # Cache results for future use with same playlist
        if matched_tracks:
            self._track_cache[cache_key] = matched_tracks

        duration = time.time() - start_time
        success_percentage = (len(matched_tracks) / total_tracks) * 100 if total_tracks > 0 else 0

        logger.info(
            f"Matched {len(matched_tracks)}/{total_tracks} tracks "
            f"({success_percentage:.2f}%) in {duration:.2f} seconds"
        )

        if missing_tracks:
            display_count = min(len(missing_tracks), MAX_DISPLAY_MISSING)
            logger.debug(
                f"First {display_count} missing tracks: "
                f"{missing_tracks[:display_count]}"
                f"{'...' if len(missing_tracks) > display_count else ''}"
            )

        return matched_tracks

    def set_cover_art(self: "PlexClass", playlist: Playlist, cover_url: str) -> bool:
        """Set cover art for a Plex playlist with retry logic.

        Args:
            playlist: The Plex playlist object.
            cover_url: URL of the cover image.

        Returns:
            True if successful, False otherwise.
        """
        if not cover_url:
            return False

        for attempt in range(MAX_RETRIES):
            try:
                playlist.uploadPoster(url=cover_url)
                logger.debug(f"Successfully set cover art for playlist '{playlist.title}'")
                return True
            except Exception as exc:
                logger.warning(
                    f"Attempt {attempt+1}/{MAX_RETRIES} failed to set cover art "
                    f"for playlist '{playlist.title}': {exc}"
                )
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY)

        logger.error(f"Failed to set cover art for playlist '{playlist.title}' after {MAX_RETRIES} attempts")
        return False

    def create_playlist(
        self: "PlexClass",
        playlist_name: str,
        playlist_id: str,
        tracks: List[Track],
        cover_url: Optional[str],
    ) -> Optional[Playlist]:
        """Create a new Plex playlist with the specified tracks.

        Args:
            playlist_name: Name of the new playlist.
            playlist_id: Source Spotify playlist ID.
            tracks: List of Plex Track objects.
            cover_url: Cover art URL.

        Returns:
            The newly created Plex Playlist, or None if creation failed.
        """
        now = datetime.datetime.now(datetime.timezone.utc)
        try:
            # Create playlist with first batch of tracks (up to chunk_size)
            initial_tracks = tracks[:CHUNK_SIZE]
            remaining_tracks = tracks[CHUNK_SIZE:]

            logger.debug(
                f"Creating new playlist '{playlist_name}' with "
                f"{len(initial_tracks)} initial tracks"
            )

            new_playlist = self.plex.createPlaylist(playlist_name, items=initial_tracks)

            # Add playlist description/summary
            summary = (
                f"Playlist auto-created by spotify_to_plex v{Config.SPOTIFY_TO_PLEX_VERSION} "
                f"on {now.strftime('%Y-%m-%d at %H:%M:%S')}.\n"
                f"Source: Spotify, Playlist ID: {playlist_id}"
            )
            new_playlist.editSummary(summary=summary)

            # Set cover art if available
            if cover_url:
                self.set_cover_art(new_playlist, cover_url)

            # Add remaining tracks in chunks
            for chunk_num, i in enumerate(range(0, len(remaining_tracks), CHUNK_SIZE)):
                chunk = remaining_tracks[i:i+CHUNK_SIZE]
                logger.debug(
                    f"Adding chunk {chunk_num+1} with {len(chunk)} more tracks to playlist '{playlist_name}'"
                )
                new_playlist.addItems(chunk)
                # Brief pause between chunks to avoid overwhelming the server
                time.sleep(0.5)

        except BadRequest as e:
            if "already exists" in str(e).lower():
                logger.error(f"Playlist '{playlist_name}' already exists. Please use update instead.")
                return None
            logger.exception(f"Bad request creating playlist '{playlist_name}': {e}")
            return None
        except Exception as exc:
            logger.exception(f"Error creating playlist '{playlist_name}': {exc}")
            return None
        else:
            logger.info(
                f"Successfully created playlist '{playlist_name}' with {len(tracks)} tracks"
            )
            # Cache the new playlist
            self._playlist_cache[playlist_name] = new_playlist
            return new_playlist

    def update_playlist(
        self: "PlexClass",
        existing_playlist: Playlist,
        playlist_id: str,
        tracks: List[Track],
        cover_url: Optional[str],
    ) -> Optional[Playlist]:
        """Update an existing Plex playlist with new tracks.

        Args:
            existing_playlist: The existing Plex playlist.
            playlist_id: Source Spotify playlist ID.
            tracks: List of Plex Track objects.
            cover_url: Cover art URL.

        Returns:
            The updated Plex Playlist.
        """
        now = datetime.datetime.now(datetime.timezone.utc)

        try:
            # If replacement policy is enabled, delete and recreate
            if self.replacement_policy:
                logger.debug(
                    f"Deleting existing playlist '{existing_playlist.title}' for replacement"
                )
                existing_playlist.delete()
                # Clear from cache
                if existing_playlist.title in self._playlist_cache:
                    del self._playlist_cache[existing_playlist.title]
                return self.create_playlist(
                    existing_playlist.title,
                    playlist_id,
                    tracks,
                    cover_url,
                )

            # Otherwise update the existing playlist
            logger.debug(f"Updating existing playlist '{existing_playlist.title}'")

            # Update summary
            summary = (
                f"Playlist updated by spotify_to_plex v{Config.SPOTIFY_TO_PLEX_VERSION} "
                f"on {now.strftime('%Y-%m-%d at %H:%M:%S')}.\n"
                f"Source: Spotify, Playlist ID: {playlist_id}"
            )
            existing_playlist.editSummary(summary=summary)

            # Update cover art
            if cover_url:
                self.set_cover_art(existing_playlist, cover_url)

            # Check for duplicates when not replacing
            if tracks:
                # Get existing tracks to avoid duplicates
                try:
                    existing_tracks = {track.ratingKey: track for track in existing_playlist.items()}
                    logger.debug(f"Playlist has {len(existing_tracks)} existing tracks")

                    # Filter out tracks that already exist in the playlist
                    new_tracks = [track for track in tracks if track.ratingKey not in existing_tracks]
                    logger.debug(f"Adding {len(new_tracks)} new tracks to playlist (filtered {len(tracks) - len(new_tracks)} duplicates)")

                    # Add new tracks in chunks
                    for i in range(0, len(new_tracks), CHUNK_SIZE):
                        chunk = new_tracks[i:i+CHUNK_SIZE]
                        if chunk:
                            existing_playlist.addItems(chunk)
                            time.sleep(0.5)  # Brief pause between chunks

                except Exception as e:
                    logger.warning(f"Error filtering duplicates, adding all tracks: {e}")
                    # Fallback to adding all tracks if filtering fails
                    for i in range(0, len(tracks), CHUNK_SIZE):
                        chunk = tracks[i:i+CHUNK_SIZE]
                        existing_playlist.addItems(chunk)
                        time.sleep(0.5)  # Brief pause between chunks

        except Exception as exc:
            logger.exception(
                f"Error updating playlist '{existing_playlist.title}': {exc}"
            )
            return None
        else:
            logger.info(f"Successfully updated playlist '{existing_playlist.title}'")
            # Update cache
            self._playlist_cache[existing_playlist.title] = existing_playlist
            return existing_playlist

    def find_playlist_by_name(self: "PlexClass", playlist_name: str) -> Optional[Playlist]:
        """Find a Plex playlist by name with caching.

        Args:
            playlist_name: The name of the playlist.

        Returns:
            A matching Plex Playlist, or None if not found.
        """
        # Check cache first
        if playlist_name in self._playlist_cache:
            logger.debug(f"Found playlist '{playlist_name}' in cache")
            return self._playlist_cache[playlist_name]

        try:
            playlists = self.plex.playlists()
            for playlist in playlists:
                if playlist_name == playlist.title:
                    logger.debug(f"Found existing playlist '{playlist_name}'")
                    # Add to cache
                    self._playlist_cache[playlist_name] = playlist
                    return playlist
        except Exception as exc:
            logger.exception(f"Error finding playlist '{playlist_name}': {exc}")
            return None
        else:
            logger.debug(f"No existing playlist found with name '{playlist_name}'")
            return None

    def create_or_update_playlist(
        self: "PlexClass",
        playlist_name: str,
        playlist_id: str,
        tracks: List[Track],
        cover_url: Optional[str],
    ) -> Optional[Playlist]:
        """Create or update a Plex playlist based on whether it exists already.

        Args:
            playlist_name: The name of the playlist.
            playlist_id: The Spotify playlist ID.
            tracks: List of Plex Track objects.
            cover_url: Cover art URL.

        Returns:
            The created or updated Plex Playlist.
        """
        if not tracks:
            logger.warning(f"No tracks to add to playlist '{playlist_name}'")
            return None

        try:
            existing_playlist = self.find_playlist_by_name(playlist_name)
        except Exception as exc:
            logger.exception(f"Error checking for existing playlist: {exc}")
            return None
        else:
            if existing_playlist is not None:
                return self.update_playlist(
                    existing_playlist,
                    playlist_id,
                    tracks,
                    cover_url,
                )
            return self.create_playlist(
                playlist_name,
                playlist_id,
                tracks,
                cover_url,
            )
