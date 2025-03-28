"""Module for interacting with the Plex API."""

import datetime
import functools
import time
from typing import Dict, List, Optional, Tuple

import httpx
from loguru import logger
from plexapi.audio import Artist, Track
from plexapi.exceptions import Unauthorized
from plexapi.playlist import Playlist
from plexapi.server import PlexServer

from spotify_to_plex.config import Config
from spotify_to_plex.utils.cache import cache_result

# Magic numbers as constants
MAX_DISPLAY_MISSING = 10
CHUNK_SIZE = 300


class PlexClass:
    """Encapsulates Plex operations."""

    def __init__(self: "PlexClass") -> None:
        """Initialize Plex connection using configuration values."""
        self.plex_url = Config.PLEX_SERVER_URL
        self.plex_token = Config.PLEX_TOKEN
        self.replacement_policy = Config.PLEX_REPLACE
        self._track_index = {}  # Cache for track lookup
        self._artist_index = {}  # Cache for artist lookup

        if not self.plex_url or not self.plex_token:
            logger.warning("Plex credentials not properly configured")

        self.plex = self.connect_plex()

    def connect_plex(self: "PlexClass") -> PlexServer:
        """Connect to the Plex server.

        Returns:
            An instance of PlexServer.
        """
        try:
            # Create a custom session with disabled certificate verification
            # Security note: This is necessary for self-signed certificates
            # nosec below tells security tools to ignore this intentional behavior
            session = httpx.Client(verify=False)  # nosec
            server = PlexServer(
                self.plex_url,
                self.plex_token,
                session=session,
            )
        except Unauthorized:
            logger.error("Failed to connect to Plex: Unauthorized. Check your token.")
            raise
        except Exception as e:
            logger.exception(f"Failed to connect to Plex server: {e}")
            raise
        else:
            logger.debug(
                f"Successfully connected to Plex server: {server.friendlyName}",
            )
            return server

    @functools.lru_cache(maxsize=1)  # Cache the music library
    def get_music_library(self):
        """Get the Plex music library with caching."""
        return self.plex.library.section("Music")

    def _build_track_index(self) -> None:
        """Build an index of all tracks for faster lookup."""
        if self._track_index:
            return  # Index already built

        start_time = time.time()
        logger.debug("Building track index...")

        try:
            music = self.get_music_library()

            # Create a normalized lookup table for tracks
            # Format: {(lowercase_title, lowercase_artist): track_obj}
            for artist in music.searchArtists():
                artist_name_lower = artist.title.lower()
                self._artist_index[artist_name_lower] = artist

                # Pre-fetch all tracks for this artist
                try:
                    for track in artist.tracks():
                        track_name_lower = track.title.lower()
                        key = (track_name_lower, artist_name_lower)
                        self._track_index[key] = track
                except Exception as e:
                    logger.debug(f"Error getting tracks for artist {artist.title}: {e}")

            elapsed = time.time() - start_time
            logger.info(f"Track index built with {len(self._track_index)} tracks in {elapsed:.2f} seconds")

        except Exception as e:
            logger.error(f"Failed to build track index: {e}")

    def match_spotify_tracks_in_plex(
        self: "PlexClass",
        spotify_tracks: list[tuple[str, str]],
    ) -> list[Track]:
        """Match Spotify tracks in the Plex music library.

        Args:
            spotify_tracks: List of tuples (track name, artist name) from Spotify.

        Returns:
            List of matched Plex Track objects.
        """
        start_time = time.time()
        logger.info(f"Matching {len(spotify_tracks)} Spotify tracks in Plex")

        # Log warning if there are a lot of tracks to match
        if len(spotify_tracks) > 200:
            logger.warning(f"Large playlist with {len(spotify_tracks)} tracks may take a while to process")

        # Build the index only if we need it (more than 10 tracks to match)
        if len(spotify_tracks) > 10 and not self._track_index:
            self._build_track_index()

        # Set batch size for progress reporting
        batch_size = max(1, min(50, len(spotify_tracks) // 10))
        matched_tracks: list[Track] = []
        missing_tracks: list[tuple[str, str]] = []
        total_tracks = len(spotify_tracks)

        # Use direct search for small playlists, index for larger ones
        use_index = len(self._track_index) > 0

        # Process tracks in batches with progress reporting
        for i, (track_name, artist_name) in enumerate(spotify_tracks):
            # Report progress every batch_size tracks
            if i % batch_size == 0 and i > 0:
                elapsed = time.time() - start_time
                tracks_per_sec = i / elapsed if elapsed > 0 else 0
                eta = (total_tracks - i) / tracks_per_sec if tracks_per_sec > 0 else "unknown"
                eta_str = f"{eta:.1f}s" if isinstance(eta, float) else eta
                logger.debug(
                    f"Matching progress: {i}/{total_tracks} tracks ({i/total_tracks*100:.1f}%), "
                    f"speed: {tracks_per_sec:.1f} tracks/sec, ETA: {eta_str}"
                )

            # Try to match the track
            track_found = False
            track_name_lower = track_name.lower()
            artist_name_lower = artist_name.lower()

            # First try: Direct index lookup (fastest)
            if use_index:
                key = (track_name_lower, artist_name_lower)
                if key in self._track_index:
                    matched_tracks.append(self._track_index[key])
                    track_found = True
                    continue

            # Second try: Quick search by artist
            if use_index and artist_name_lower in self._artist_index:
                # Try direct search for this track within the artist
                try:
                    direct_results = self.get_music_library().searchTracks(
                        title=track_name,
                        artist=artist_name,
                        maxresults=1  # Limit to just 1 result for speed
                    )
                    if direct_results:
                        matched_tracks.append(direct_results[0])
                        # Add to our index for future lookups
                        if use_index:
                            self._track_index[key] = direct_results[0]
                        track_found = True
                        continue
                except Exception:
                    # Continue to next method if this fails
                    pass

            # Third try: Full library search (slowest)
            if not track_found:
                try:
                    # Use a more targeted search with both title and artist
                    direct_results = self.get_music_library().searchTracks(
                        title=track_name,
                        maxresults=5,  # Get a few results for better matching
                    )

                    # Manual filtering for better artist match
                    for track in direct_results:
                        if hasattr(track, 'originalTitle') and track.originalTitle.lower() == track_name_lower:
                            # Perfect track name match
                            matched_tracks.append(track)
                            if use_index:
                                self._track_index[key] = track
                            track_found = True
                            break

                        # Check if any artist name is a match
                        artists = []
                        if hasattr(track, 'artist') and track.artist:
                            artists = [track.artist]
                        elif hasattr(track, 'artists') and track.artists:
                            artists = track.artists

                        for artist in artists:
                            artist_name_matches = (
                                hasattr(artist, 'title') and
                                (artist.title.lower() == artist_name_lower or
                                 artist_name_lower in artist.title.lower() or
                                 artist.title.lower() in artist_name_lower)
                            )
                            if artist_name_matches:
                                matched_tracks.append(track)
                                if use_index:
                                    self._track_index[key] = track
                                track_found = True
                                break

                        if track_found:
                            break
                except Exception as exc:
                    logger.debug(
                        f"Error in direct search for '{track_name}' by '{artist_name}': {exc}",
                    )

            # Track not found
            if not track_found:
                missing_tracks.append((track_name, artist_name))

        # Final stats
        elapsed_total = time.time() - start_time
        tracks_per_sec = total_tracks / elapsed_total if elapsed_total > 0 else 0
        success_percentage = (
            (len(matched_tracks) / total_tracks) * 100 if total_tracks > 0 else 0
        )

        logger.info(
            f"Matched {len(matched_tracks)}/{total_tracks} tracks "
            f"({success_percentage:.2f}%) in {elapsed_total:.1f}s "
            f"({tracks_per_sec:.1f} tracks/sec)"
        )

        if missing_tracks:
            display_count = min(len(missing_tracks), MAX_DISPLAY_MISSING)
            logger.debug(
                f"Missing tracks: {missing_tracks[:display_count]}"
                f"{'...' if len(missing_tracks) > display_count else ''}",
            )

        return matched_tracks

    @cache_result(ttl=3600, use_disk=True)
    def set_cover_art(self: "PlexClass", playlist: Playlist, cover_url: str) -> bool:
        """Set cover art for a Plex playlist.

        Args:
            playlist: The Plex playlist object.
            cover_url: URL of the cover image.

        Returns:
            True if successful, False otherwise.
        """
        if not cover_url:
            return False

        try:
            playlist.uploadPoster(url=cover_url)
        except Exception as exc:
            logger.warning(
                f"Failed to set cover art for playlist '{playlist.title}': {exc}",
            )
            return False
        else:
            logger.debug(f"Successfully set cover art for playlist '{playlist.title}'")
            return True

    def create_playlist(
        self: "PlexClass",
        playlist_name: str,
        playlist_id: str,
        tracks: list[Track],
        cover_url: str | None,
    ) -> Playlist | None:
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
                f"{len(initial_tracks)} initial tracks",
            )
            new_playlist = self.plex.createPlaylist(playlist_name, items=initial_tracks)

            # Add playlist description/summary
            summary = (
                f"Playlist auto-created by spotify_to_plex on {now.strftime('%m/%d/%Y')}.\n"
                f"Source: Spotify, Playlist ID: {playlist_id}"
            )
            new_playlist.editSummary(summary=summary)

            # Set cover art if available
            if cover_url:
                self.set_cover_art(new_playlist, cover_url)

            # Add remaining tracks in chunks
            while remaining_tracks:
                chunk, remaining_tracks = (
                    remaining_tracks[:CHUNK_SIZE],
                    remaining_tracks[CHUNK_SIZE:],
                )
                logger.debug(
                    f"Adding {len(chunk)} more tracks to playlist '{playlist_name}'",
                )
                new_playlist.addItems(chunk)
        except Exception as exc:
            logger.exception(f"Error creating playlist '{playlist_name}': {exc}")
            return None
        else:
            logger.info(
                f"Successfully created playlist '{playlist_name}' with {len(tracks)} tracks",
            )
            return new_playlist

    def update_playlist(
        self: "PlexClass",
        existing_playlist: Playlist,
        playlist_id: str,
        tracks: list[Track],
        cover_url: str | None,
    ) -> Playlist | None:
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
                    f"Deleting existing playlist '{existing_playlist.title}' for replacement",
                )
                existing_playlist.delete()
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
                f"Playlist updated by spotify_to_plex on {now.strftime('%m/%d/%Y')}.\n"
                f"Source: Spotify, Playlist ID: {playlist_id}"
            )
            existing_playlist.editSummary(summary=summary)

            # Update cover art
            if cover_url:
                self.set_cover_art(existing_playlist, cover_url)

            # Add new tracks
            if tracks:
                # We might want to check for duplicates here
                existing_playlist.addItems(tracks)
                logger.debug(f"Added {len(tracks)} tracks to existing playlist")
        except Exception as exc:
            logger.exception(
                f"Error updating playlist '{existing_playlist.title}': {exc}",
            )
            return None
        else:
            logger.info(f"Successfully updated playlist '{existing_playlist.title}'")
            return existing_playlist

    @cache_result(ttl=60)  # Short cache as playlists may change
    def find_playlist_by_name(self: "PlexClass", playlist_name: str) -> Playlist | None:
        """Find a Plex playlist by name.

        Args:
            playlist_name: The name of the playlist.

        Returns:
            A matching Plex Playlist, or None if not found.
        """
        try:
            playlists = self.plex.playlists()
            for playlist in playlists:
                if playlist_name == playlist.title:
                    logger.debug(f"Found existing playlist '{playlist_name}'")
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
        tracks: list[Track],
        cover_url: str | None,
    ) -> Playlist | None:
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
