"""Module for interacting with the Plex API."""

import datetime

import httpx
from loguru import logger
from plexapi.audio import Track
from plexapi.exceptions import Unauthorized
from plexapi.playlist import Playlist
from plexapi.server import PlexServer

from spotify_to_plex.config import Config

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

    # This function is complex but necessary as is - would need deeper refactoring
    # to address complexity issues
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
        logger.info(f"Matching {len(spotify_tracks)} Spotify tracks in Plex")
        matched_tracks: list[Track] = []
        missing_tracks: list[tuple[str, str]] = []
        total_tracks = len(spotify_tracks)

        try:
            music_library = self.plex.library.section("Music")
        except Exception as exc:
            logger.error(f"Failed to access Music library in Plex: {exc}")
            return []

        artist_cache = {}  # Cache for search results per artist

        for track_name, artist_name in spotify_tracks:
            if artist_name not in artist_cache:
                try:
                    artist_cache[artist_name] = music_library.search(title=artist_name)
                except Exception as exc:
                    logger.debug(f"Error searching for artist '{artist_name}': {exc}")
                    artist_cache[artist_name] = []
            artist_results = artist_cache[artist_name]

            if not artist_results:
                missing_tracks.append((track_name, artist_name))
                continue

            track_found = False
            for artist_item in artist_results:
                try:
                    tracks = artist_item.tracks()
                    for track in tracks:
                        # Case insensitive matching
                        if track.title.lower() == track_name.lower():
                            matched_tracks.append(track)
                            track_found = True
                            break
                except Exception as exc:
                    logger.debug(
                        f"Error accessing tracks for artist '{artist_name}': {exc}",
                    )
                    continue

                if track_found:
                    break

            if not track_found:
                # Try a more direct search as fallback
                try:
                    direct_results = music_library.searchTracks(
                        title=track_name,
                        artist=artist_name,
                    )
                    if direct_results:
                        matched_tracks.append(direct_results[0])
                        track_found = True
                except Exception as exc:
                    logger.debug(
                        "Error in direct search for "
                        f"'{track_name}' by '{artist_name}': {exc}",
                    )

            if not track_found:
                missing_tracks.append((track_name, artist_name))

        success_percentage = (
            (len(matched_tracks) / total_tracks) * 100 if total_tracks > 0 else 0
        )
        logger.info(
            f"Matched {len(matched_tracks)}/{total_tracks} tracks "
            f"({success_percentage:.2f}%)",
        )

        if missing_tracks:
            display_count = min(len(missing_tracks), MAX_DISPLAY_MISSING)
            logger.debug(
                f"Missing tracks: {missing_tracks[:display_count]}"
                f"{'...' if len(missing_tracks) > display_count else ''}",
            )

        return matched_tracks

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
