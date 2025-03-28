"""Main module for syncing Spotify to Plex playlists."""

import concurrent.futures
import re
import sys
import threading
import time
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from loguru import logger
from tqdm import tqdm

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
        parallel: bool = False,
        parallel_count: Optional[int] = None,
    ) -> None:
        """Initialize services and determine playlists to sync.

        Args:
            lidarr: Whether to fetch playlists from Lidarr.
            playlist_id: Specific playlist ID to sync (if provided).
            parallel: Whether to process playlists in parallel.
            parallel_count: Maximum number of playlists to process in parallel.
        """
        # Check configuration warnings
        warnings = Config.validate()
        for warning in warnings:
            logger.warning(f"Configuration warning: {warning}")

        self.spotify_service = SpotifyClass()
        self.plex_service = PlexClass()

        # Initialize default user from Plex before fetching user list
        try:
            self.default_user: str = self.plex_service.plex.myPlexAccount().username
            logger.debug(f"Connected to Plex as user: {self.default_user}")
        except Exception as e:
            logger.error(f"Failed to get Plex username: {e}")
            self.default_user = "default_user"

        self.user_list = self.get_user_list()
        self.replace_existing = Config.PLEX_REPLACE
        self.sync_lists: list[str] = []
        self.parallel = parallel
        # Default to config value if not specified
        self.parallel_count = parallel_count or Config.MAX_PARALLEL_PLAYLISTS
        # Add a status dictionary to track progress
        self.status = {
            "total_playlists": 0,
            "completed_playlists": 0,
            "failed_playlists": 0,
            "current_playlist": "",
        }

        if playlist_id:
            self.sync_lists = [playlist_id]
            # Disable parallel processing for single playlist
            self.parallel = False
        else:
            self.lidarr_service = LidarrClass()
            self.lidarr = lidarr
            self.get_sync_lists()

        # Update total playlists
        self.status["total_playlists"] = len(self.sync_lists)

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

        if self.parallel and len(self.sync_lists) > 1:
            self._process_playlists_parallel(user)
        else:
            self._process_playlists_sequential(user)

    def _process_playlists_sequential(self: "SpotifyToPlex", user: str) -> None:
        """Process playlists sequentially for a user with better progress tracking.

        Args:
            user: The Plex username.
        """
        # Check if we're in an interactive environment for proper progress bar
        use_progress_bar = sys.stdout.isatty()

        # Process playlists sequentially with a progress bar if in interactive mode
        with tqdm(total=len(self.sync_lists), desc=f"Processing playlists for {user}",
                  file=sys.stdout, disable=not use_progress_bar) as pbar:
            for i, playlist in enumerate(self.sync_lists):
                try:
                    self.status["current_playlist"] = playlist
                    pbar.set_description(f"Processing {i+1}/{len(self.sync_lists)}: {playlist[:8]}...")

                    # More verbose logging before processing
                    logger.info(f"Starting playlist {i+1}/{len(self.sync_lists)}: {playlist}")
                    print(f"\n----- Processing playlist {i+1}/{len(self.sync_lists)} -----")

                    # Process with timeout protection
                    success = self._process_playlist_with_timeout(playlist)

                    if success:
                        self.status["completed_playlists"] += 1
                        msg = f"✓ Completed {i+1}/{len(self.sync_lists)}: {playlist[:8]}"
                        pbar.set_description(msg)
                        logger.info(f"Successfully processed playlist: {playlist}")
                        print(f"\n{msg}")
                    else:
                        self.status["failed_playlists"] += 1
                        msg = f"✗ Failed {i+1}/{len(self.sync_lists)}: {playlist[:8]}"
                        pbar.set_description(msg)
                        logger.error(f"Failed to process playlist: {playlist}")
                        print(f"\n{msg}")
                except Exception as exc:
                    self.status["failed_playlists"] += 1
                    logger.exception(f"Error processing playlist {playlist}: {exc}")
                    pbar.set_description(f"✗ Error {i+1}/{len(self.sync_lists)}: {playlist[:8]}")
                    print(f"\n✗ Error processing playlist: {playlist}")
                finally:
                    pbar.update(1)
                    pbar.refresh()

    def _process_playlists_parallel(self: "SpotifyToPlex", user: str) -> None:
        """Process playlists in parallel for a user with better error handling.

        Args:
            user: The Plex username.
        """
        logger.info(f"Processing {len(self.sync_lists)} playlists in parallel (max {self.parallel_count} at a time)")
        print(f"\nProcessing {len(self.sync_lists)} playlists in parallel (max {self.parallel_count} at a time)...")

        # Use a thread pool to process playlists in parallel with timeouts
        completed_count = 0
        failed_count = 0
        active_threads = []
        results = {}

        with tqdm(total=len(self.sync_lists), desc=f"Processing playlists for {user}", file=sys.stdout) as pbar:
            # Process in batches to avoid overwhelming the system
            for i in range(0, len(self.sync_lists), self.parallel_count):
                batch = self.sync_lists[i:i+self.parallel_count]
                threads = []

                # More verbose logging for batch
                print(f"\nStarting batch of {len(batch)} playlists ({i+1}-{min(i+len(batch), len(self.sync_lists))} of {len(self.sync_lists)})")

                # Start a thread for each playlist in the batch
                for playlist in batch:
                    self.status["current_playlist"] = playlist
                    thread = threading.Thread(
                        target=self._process_playlist_thread,
                        args=(playlist, results)
                    )
                    thread.start()
                    threads.append(thread)
                    active_threads.append(thread)

                # Wait for threads to complete with progress updates
                while any(t.is_alive() for t in threads):
                    # Check for newly completed threads
                    newly_completed = sum(1 for t in threads if not t.is_alive() and t in active_threads)
                    if newly_completed > 0:
                        # Update progress
                        pbar.update(newly_completed)
                        # Remove completed threads
                        active_threads = [t for t in active_threads if t.is_alive()]

                        # Update the description to show overall progress
                        current_completed = sum(1 for success in results.values() if success)
                        current_failed = len(results) - current_completed
                        pbar.set_description(f"Completed: {current_completed}, Failed: {current_failed}")

                    pbar.refresh()
                    time.sleep(0.5)

                # Process any remaining updates
                remaining = sum(1 for t in threads if not t.is_alive() and t in active_threads)
                if remaining > 0:
                    pbar.update(remaining)
                    active_threads = [t for t in active_threads if t.is_alive()]

            # Final tally
            completed_count = sum(1 for success in results.values() if success)
            failed_count = len(results) - completed_count
            self.status["completed_playlists"] = completed_count
            self.status["failed_playlists"] = failed_count

            pbar.set_description(f"Completed: {completed_count}, Failed: {failed_count}")

            # Print summary after all playlists
            print(f"\nBatch processing complete: {completed_count} succeeded, {failed_count} failed")
            logger.info(f"Batch processing complete: {completed_count} succeeded, {failed_count} failed")

    def _process_playlist_thread(self, playlist: str, results: dict) -> None:
        """Thread worker to process a playlist and store the result.

        Args:
            playlist: The playlist ID to process
            results: Dictionary to store results (thread-safe)
        """
        try:
            success = self._process_playlist_with_timeout(playlist)
            results[playlist] = success
        except Exception as exc:
            logger.exception(f"Thread error processing playlist {playlist}: {exc}")
            results[playlist] = False

    def _process_playlist_with_timeout(self, playlist: str, timeout: int = 300) -> bool:
        """Process a playlist with a timeout safety mechanism.

        Args:
            playlist: The playlist ID to process
            timeout: Maximum time in seconds to process a playlist

        Returns:
            True if processing succeeded, False otherwise
        """
        try:
            # Create a result container
            result = {"success": False, "exception": None}

            # Define the worker function
            def worker():
                try:
                    self._process_playlist(playlist)
                    result["success"] = True
                except Exception as exc:
                    result["exception"] = exc
                    result["success"] = False

            # Start a thread for the worker
            thread = threading.Thread(target=worker)
            thread.daemon = True
            thread.start()

            # Wait for the thread with timeout
            thread.join(timeout)

            # Check if thread is still running (timed out)
            if thread.is_alive():
                logger.warning(f"Processing timed out after {timeout}s for playlist {playlist}")
                return False

            # Check the result
            if not result["success"]:
                if result["exception"]:
                    logger.error(f"Error processing playlist {playlist}: {result['exception']}")
                return False

            return True

        except Exception as exc:
            logger.exception(f"Error in timeout wrapper for playlist {playlist}: {exc}")
            return False

    def run(self: "SpotifyToPlex") -> None:
        """Run the sync process for all users."""
        if not self.sync_lists:
            logger.warning("No playlists to sync!")
            return

        logger.info(
            f"Starting sync process for {len(self.sync_lists)} playlists "
            f"and {len(self.user_list)} users",
        )

        if self.parallel:
            logger.info(f"Parallel processing enabled with max {self.parallel_count} concurrent playlists")

        # Simple progress tracking for users
        for i, user in enumerate(self.user_list):
            print(f"\nProcessing user {i+1}/{len(self.user_list)}: {user}")
            # Reset playlist counters for this user
            self.status["completed_playlists"] = 0
            self.status["failed_playlists"] = 0

            # Process playlists for this user
            self.process_for_user(user)

            # Display summary for this user
            print(f"Completed user {i+1}/{len(self.user_list)}: {user} - "
                  f"{self.status['completed_playlists']} succeeded, "
                  f"{self.status['failed_playlists']} failed")

        # Calculate total statistics
        total_processed = self.status["completed_playlists"] + self.status["failed_playlists"]
        success_rate = (self.status["completed_playlists"] / max(1, total_processed)) * 100

        print(f"\n✅ Sync process completed! Success rate: {success_rate:.1f}%")
        logger.info(f"Sync process completed with {self.status['completed_playlists']} "
                   f"successes and {self.status['failed_playlists']} failures")

    def _process_playlist(self: "SpotifyToPlex", playlist: str) -> None:
        """Process a single playlist: fetch data from Spotify and update Plex.

        Args:
            playlist: The playlist URL or ID.
        """
        try:
            # Add debug logging to track progress
            logger.debug(f"Starting to process playlist: {playlist}")

            playlist_id = self.extract_playlist_id(playlist)
            logger.debug(f"Extracted playlist ID: {playlist_id}")
            print(f"• Extracted playlist ID: {playlist_id}")

            # Get playlist name from Spotify with timeout
            playlist_name = None
            try:
                print(f"• Getting playlist name from Spotify...")
                playlist_name = self.spotify_service.get_playlist_name(playlist_id)
                print(f"• Playlist name: {playlist_name}")
            except Exception as e:
                logger.error(f"Error getting playlist name: {e}")
                print(f"• Error getting playlist name: {e}")

            if not playlist_name:
                logger.error(f"Could not retrieve name for playlist ID '{playlist_id}'")
                print(f"• Error: Could not retrieve name for playlist ID '{playlist_id}'")
                return

            # Thread-safe logging for parallel operation
            thread_id = ""
            if self.parallel:
                thread_id = f"[Thread-{threading.get_ident() % 100:02d}] "

            logger.info(f"{thread_id}Starting processing of playlist: {playlist_name}")

            # Step 1: Get tracks from Spotify
            print(f"• Fetching tracks from Spotify for '{playlist_name}'...")
            logger.debug(f"{thread_id}Fetching tracks from Spotify...")

            # Add date to dynamic playlists like Discover Weekly
            if "Discover Weekly" in playlist_name or "Daily Mix" in playlist_name:
                current_date = datetime.now(timezone.utc).strftime("%B %d")
                playlist_name = f"{playlist_name} {current_date}"
                logger.debug(f"{thread_id}Added date to dynamic playlist: {playlist_name}")
                print(f"• Added date to dynamic playlist: {playlist_name}")

            # Get tracks from Spotify with proper error handling
            spotify_tracks = []
            try:
                spotify_tracks = self.spotify_service.get_playlist_tracks(playlist_id)
            except Exception as e:
                logger.error(f"{thread_id}Error fetching tracks from Spotify: {e}")
                print(f"• Error fetching tracks from Spotify: {e}")

            if not spotify_tracks:
                logger.warning(f"{thread_id}No tracks found in Spotify playlist '{playlist_name}'")
                print(f"• No tracks found in Spotify playlist '{playlist_name}'")
                return

            logger.info(f"{thread_id}Found {len(spotify_tracks)} tracks on Spotify for '{playlist_name}'")
            print(f"• Found {len(spotify_tracks)} tracks on Spotify for '{playlist_name}'")

            # Step 2: Get cover art
            print(f"• Getting cover art...")
            logger.debug(f"{thread_id}Getting cover art...")
            cover_url = None
            try:
                cover_url = self.spotify_service.get_playlist_poster(playlist_id)
                if cover_url:
                    print(f"• Successfully retrieved cover art")
                else:
                    print(f"• No cover art found")
            except Exception as e:
                logger.warning(f"{thread_id}Error getting cover art: {e}")
                print(f"• Error getting cover art: {e}")

            # Step 3: Match tracks in Plex
            print(f"• Matching tracks in Plex (this may take a while)...")
            logger.debug(f"{thread_id}Matching tracks in Plex...")
            plex_tracks = []
            try:
                plex_tracks = self.plex_service.match_spotify_tracks_in_plex(spotify_tracks)
            except Exception as e:
                logger.error(f"{thread_id}Error matching tracks in Plex: {e}")
                print(f"• Error matching tracks in Plex: {e}")

            if not plex_tracks:
                logger.warning(
                    f"{thread_id}No matching tracks found in Plex for playlist '{playlist_name}'",
                )
                print(f"• No matching tracks found in Plex for playlist '{playlist_name}'")
                return

            match_percentage = (len(plex_tracks) / len(spotify_tracks)) * 100
            logger.info(
                f"{thread_id}Matched {len(plex_tracks)}/{len(spotify_tracks)} tracks in Plex for '{playlist_name}'"
            )
            print(f"• Matched {len(plex_tracks)}/{len(spotify_tracks)} tracks ({match_percentage:.1f}%) in Plex")

            # Step 4: Create or update playlist in Plex
            print(f"• Creating/updating playlist in Plex...")
            logger.debug(f"{thread_id}Creating/updating playlist in Plex...")
            result = False
            try:
                result = self.plex_service.create_or_update_playlist(
                    playlist_name,
                    playlist_id,
                    plex_tracks,
                    cover_url,
                )
            except Exception as e:
                logger.error(f"{thread_id}Error creating/updating playlist: {e}")
                print(f"• Error creating/updating playlist: {e}")

            if result:
                logger.info(
                    f"{thread_id}Successfully processed playlist '{playlist_name}' with "
                    f"{len(plex_tracks)} tracks",
                )
                print(f"• Success! Created/updated playlist '{playlist_name}' with {len(plex_tracks)} tracks")
            else:
                logger.error(f"{thread_id}Failed to create or update playlist '{playlist_name}'")
                print(f"• Failed to create or update playlist '{playlist_name}'")

        except Exception as exc:
            logger.exception(f"Error processing playlist '{playlist}': {exc}")
            print(f"• Error processing playlist: {exc}")
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
