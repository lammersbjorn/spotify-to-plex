"""Main module for syncing Spotify to Plex playlists."""

import re
from datetime import datetime, timezone

from loguru import logger

from spotify_to_plex.config import Config
from spotify_to_plex.modules.lidarr.main import LidarrClass
from spotify_to_plex.modules.plex.main import PlexClass
from spotify_to_plex.modules.spotify.main import SpotifyClass


class SpotifyToPlex:
    """Handles syncing playlists from Spotify to Plex."""

    def __init__(
        self: "SpotifyToPlex",
        *,
        lidarr: bool,
        playlist_id: str | None,
    ) -> None:
        """Initialize services and determine playlists to sync.

        Args:
            lidarr: Whether to fetch playlists from Lidarr.
            playlist_id: Specific playlist ID to sync (if provided).
        """
        # Check configuration warnings
        warnings = Config.validate()
        for warning in warnings:
            logger.warning(f"Configuration warning: {warning}")

        self.spotify_service = SpotifyClass()
        self.plex_service = PlexClass()

        # Initialize default user from Plex before fetching user list
        self.default_user: str = self.plex_service.plex.myPlexAccount().username
        self.user_list = self.get_user_list()
        self.worker_count: int = Config.WORKER_COUNT
        self.replace_existing = Config.PLEX_REPLACE
        self.sync_lists: list[str] = []

        if playlist_id:
            self.sync_lists = [playlist_id]
        else:
            self.lidarr_service = LidarrClass()
            self.lidarr = lidarr
            self.get_sync_lists()

    def get_user_list(self: "SpotifyToPlex") -> list[str]:
        """Retrieve the list of Plex users from configuration.

        Returns:
            List of Plex usernames to process.
        """
        plex_users = Config.PLEX_USERS
        user_list = (
            [u.strip() for u in plex_users.split(",") if u.strip()]
            if plex_users
            else []
        )
        if not user_list:
            user_list.append(self.default_user)
        logger.debug(f"Users to process: {user_list}")
        return user_list

    def get_sync_lists(self: "SpotifyToPlex") -> None:
        """Retrieve the lists of playlist IDs from Lidarr or the config."""
        if self.lidarr:
            playlists = self.lidarr_service.playlist_request()
            self.sync_lists = [
                playlist_id for playlist in playlists for playlist_id in playlist
            ]
            logger.info(f"Retrieved {len(self.sync_lists)} playlists from Lidarr")
        else:
            manual_playlists = Config.MANUAL_PLAYLISTS
            self.sync_lists = [
                pl.strip() for pl in manual_playlists.split(",") if pl.strip()
            ]
            logger.info(
                f"Using {len(self.sync_lists)} manually configured playlists",
            )

    def process_for_user(self: "SpotifyToPlex", user: str) -> None:
        """Sync playlists for a given Plex user.

        Args:
            user: The Plex username.
        """
        logger.info(f"Processing for user: {user}")

        # Switch to the specified user if not the default user
        if user != self.default_user:
            try:
                self.plex_service.plex = self.plex_service.plex.switchUser(user)
                logger.debug(f"Successfully switched to Plex user: {user}")
            except Exception as exc:
                logger.error(f"Failed to switch to Plex user {user}: {exc}")
                return

        # Process playlists sequentially
        for playlist in self.sync_lists:
            try:
                self._process_playlist(playlist)
            except Exception as exc:
                logger.exception(f"Error processing playlist {playlist}: {exc}")

    def run(self: "SpotifyToPlex") -> None:
        """Run the sync process for all users."""
        if not self.sync_lists:
            logger.warning("No playlists to sync!")
            return

        logger.info(
            f"Starting sync process for {len(self.sync_lists)} playlists "
            f"and {len(self.user_list)} users",
        )

        # Simple progress tracking with a single progress bar
        for i, user in enumerate(self.user_list):
            print(f"\nProcessing user {i+1}/{len(self.user_list)}: {user}")
            self.process_for_user(user)
            print(f"Completed user {i+1}/{len(self.user_list)}: {user}")

        print("\n✅ Sync process completed!")
        logger.info("Sync process completed")

    def _process_playlist(self: "SpotifyToPlex", playlist: str) -> None:
        """Process a single playlist: fetch data from Spotify and update Plex.

        Args:
            playlist: The playlist URL or ID.
        """
        try:
            playlist_id = self.extract_playlist_id(playlist)

            # Get playlist name from Spotify
            playlist_name = self.spotify_service.get_playlist_name(playlist_id)
            if not playlist_name:
                logger.error(f"Could not retrieve name for playlist ID '{playlist_id}'")
                return

            print(f"\n→ Processing playlist: {playlist_name}")

            # Step 1: Get tracks from Spotify
            print("  • Fetching tracks from Spotify...")

            # Add date to dynamic playlists like Discover Weekly
            if "Discover Weekly" in playlist_name or "Daily Mix" in playlist_name:
                current_date = datetime.now(timezone.utc).strftime("%B %d")
                playlist_name = f"{playlist_name} {current_date}"
                logger.debug(f"Added date to dynamic playlist: {playlist_name}")

            # Get tracks from Spotify
            spotify_tracks = self.spotify_service.get_playlist_tracks(playlist_id)
            if not spotify_tracks:
                logger.warning(f"No tracks found in Spotify playlist '{playlist_name}'")
                print("  ❌ No tracks found in Spotify playlist")
                return

            print(f"  ✓ Found {len(spotify_tracks)} tracks on Spotify")

            # Step 2: Get cover art
            print("  • Getting cover art...")
            cover_url = self.spotify_service.get_playlist_poster(playlist_id)
            print("  ✓ Cover art retrieved")

            # Step 3: Match tracks in Plex
            print("  • Matching tracks in Plex...")
            plex_tracks = self.plex_service.match_spotify_tracks_in_plex(spotify_tracks)
            if not plex_tracks:
                logger.warning(
                    f"No matching tracks found in Plex for playlist '{playlist_name}'",
                )
                print("  ❌ No matching tracks found in Plex")
                return

            print(
                f"  ✓ Matched {len(plex_tracks)}/{len(spotify_tracks)} tracks in Plex"
            )

            # Step 4: Create or update playlist in Plex
            print("  • Creating/updating playlist in Plex...")
            result = self.plex_service.create_or_update_playlist(
                playlist_name,
                playlist_id,
                plex_tracks,
                cover_url,
            )

            if result:
                print(f"  ✅ Successfully processed: {playlist_name}")
                logger.info(
                    f"Successfully processed playlist '{playlist_name}' with "
                    f"{len(plex_tracks)} tracks",
                )
            else:
                print(f"  ❌ Failed to process: {playlist_name}")
                logger.error(f"Failed to create or update playlist '{playlist_name}'")

        except Exception as exc:
            print(f"  ❌ Error processing playlist: {exc}")
            logger.exception(f"Error processing playlist '{playlist}': {exc}")
            raise

    @staticmethod
    def extract_playlist_id(playlist_url: str) -> str:
        """Extract the Spotify playlist ID from a URL.

        Args:
            playlist_url: A URL or ID of the playlist.

        Returns:
            The extracted playlist ID.
        """
        # Remove query parameters
        if "?" in playlist_url:
            playlist_url = playlist_url.split("?")[0]

        # Extract ID from URL format
        playlist_match = re.search(r"playlist[/:]([a-zA-Z0-9]+)", playlist_url)
        if playlist_match:
            return playlist_match.group(1)

        # If not a URL, assume it's already an ID
        return playlist_url
