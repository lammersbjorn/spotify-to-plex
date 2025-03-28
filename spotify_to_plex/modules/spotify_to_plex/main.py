"""Main module for syncing Spotify to Plex playlists."""

import concurrent.futures
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Optional

from loguru import logger
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

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
        playlist_id: Optional[str],
        console: Optional[Console] = None,
    ) -> None:
        """Initialize services and determine playlists to sync.

        Args:
            lidarr: Whether to fetch playlists from Lidarr.
            playlist_id: Specific playlist ID to sync (if provided).
            console: Rich console for output (optional)
        """
        self.start_time = time.time()
        self.console = console or Console()

        # Status tracking
        self.current_status = "Initializing..."
        self.playlist_statuses: dict[str, dict[str, Any]] = {}
        self._status_lock = threading.RLock()

        # Check configuration warnings
        warnings = Config.validate()
        for warning in warnings:
            logger.warning(f"Configuration warning: {warning}")

        if warnings:
            logger.warning(
                f"Found {len(warnings)} configuration issues that might cause problems"
            )

        # Initialize services
        logger.info("Initializing Spotify API connection")
        self.spotify_service = SpotifyClass()

        logger.info("Initializing Plex connection")
        self.plex_service = PlexClass()

        # Initialize default user from Plex before fetching user list
        try:
            self.default_user = self.plex_service.plex.myPlexAccount().username
            logger.info(f"Default Plex user: {self.default_user}")
        except Exception as e:
            logger.error(f"Unable to determine default Plex user: {e}")
            self.default_user = "admin"

        self.user_list = self.get_user_list()
        self.worker_count = max(1, min(Config.WORKER_COUNT, 20))  # Ensure between 1-20
        logger.info(f"Using {self.worker_count} worker threads")

        self.replace_existing = Config.PLEX_REPLACE
        self.seconds_interval = Config.SECONDS_INTERVAL
        self.sync_lists: list[str] = []
        self.processed_count = 0
        self.failed_count = 0
        self.skipped_count = 0
        self.total_matched_tracks = 0
        self.total_spotify_tracks = 0

        if playlist_id:
            self.sync_lists = [playlist_id]
            logger.info(f"Single playlist mode: {playlist_id}")
        else:
            logger.info("Initializing Lidarr connection")
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
        logger.info(f"Will process for users: {', '.join(user_list)}")
        return user_list

    def get_sync_lists(self: "SpotifyToPlex") -> None:
        """Retrieve the lists of playlist IDs from Lidarr or the config."""
        if self.lidarr and Config.LIDARR_SYNC:
            playlists = self.lidarr_service.playlist_request()
            raw_ids = [
                playlist_id for playlist in playlists for playlist_id in playlist
            ]

            # Remove duplicates while preserving order
            seen: set[str] = set()
            self.sync_lists = [x for x in raw_ids if not (x in seen or seen.add(x))]

            logger.info(f"Retrieved {len(self.sync_lists)} playlists from Lidarr")
        else:
            manual_playlists = Config.MANUAL_PLAYLISTS
            raw_ids = [pl.strip() for pl in manual_playlists.split(",") if pl.strip()]

            # Remove duplicates while preserving order
            seen: set[str] = set()
            self.sync_lists = [x for x in raw_ids if not (x in seen or seen.add(x))]

            logger.info(f"Using {len(self.sync_lists)} manually configured playlists")

    def update_status(self, status: str) -> None:
        """Update the current overall status.

        Args:
            status: New status message
        """
        with self._status_lock:
            self.current_status = status

    def update_playlist_status(self, playlist_id: str, status: dict[str, Any]) -> None:
        """Update status for a specific playlist.

        Args:
            playlist_id: Spotify playlist ID
            status: Dictionary with status information
        """
        with self._status_lock:
            self.playlist_statuses[playlist_id] = status

    def process_for_user(
        self: "SpotifyToPlex", user: str, progress: Progress
    ) -> dict[str, int]:
        """Sync playlists for a given Plex user with rich progress reporting.

        Args:
            user: The Plex username.
            progress: Rich progress display

        Returns:
            Dictionary with counts of processed, failed and skipped playlists
        """
        logger.info(f"Processing for user: {user}")
        results = {"processed": 0, "failed": 0, "skipped": 0}

        # Create progress task for this user - simplify the display
        task_id = progress.add_task(
            f"[cyan]User: [bold]{user}[/]",
            total=len(self.sync_lists),
            visible=True,  # Ensure the task is visible
        )

        # Switch to the specified user if not the default user
        if user != self.default_user:
            try:
                logger.debug(f"Switching to Plex user: {user}")
                self.plex_service.plex = self.plex_service.plex.switchUser(user)
                logger.debug(f"Successfully switched to Plex user: {user}")
            except Exception as exc:
                logger.error(f"Failed to switch to Plex user {user}: {exc}")
                # Complete progress task even on error
                progress.update(task_id, completed=len(self.sync_lists))
                return results

        # Process playlists sequentially or with limited concurrency based on settings
        if self.worker_count <= 1:
            # Sequential processing for better display clarity
            for playlist in self.sync_lists:
                result = self._process_playlist(playlist)

                if result == "processed":
                    results["processed"] += 1
                elif result == "failed":
                    results["failed"] += 1
                elif result == "skipped":
                    results["skipped"] += 1

                # Update progress - advance by one step
                progress.update(task_id, advance=1)

                # Add a blank line between playlists for readability
                self.console.print("")

                # Respect rate limiting
                if self.seconds_interval > 0:
                    time.sleep(self.seconds_interval)
        else:
            # Parallel processing with ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=self.worker_count) as executor:
                futures_to_playlists = {}

                # Submit all playlists for processing
                for playlist in self.sync_lists:
                    futures_to_playlists[
                        executor.submit(self._process_playlist, playlist)
                    ] = playlist

                # Wait for each future to complete and update progress
                for future in concurrent.futures.as_completed(futures_to_playlists):
                    playlist_id = futures_to_playlists[future]

                    try:
                        result = future.result()
                        if result == "processed":
                            results["processed"] += 1
                        elif result == "failed":
                            results["failed"] += 1
                        elif result == "skipped":
                            results["skipped"] += 1
                    except Exception as exc:
                        logger.exception(f"Error in playlist processing: {exc}")
                        results["failed"] += 1

                    # Update progress
                    progress.update(task_id, advance=1)

                    # Add a blank line between playlists for readability
                    self.console.print("")

                    # Respect rate limiting
                    if self.seconds_interval > 0:
                        time.sleep(self.seconds_interval)

        # Mark task as completed
        progress.update(task_id, completed=True)
        return results

    def run(self: "SpotifyToPlex") -> None:
        """Run the sync process for all users with improved console output."""
        if not self.sync_lists:
            logger.warning("No playlists to sync!")
            self.console.print(
                "❌ No playlists to sync. Please check your configuration."
            )
            return

        total_playlists = len(self.sync_lists)
        total_users = len(self.user_list)
        start_message = f"🚀 Starting sync process for {total_playlists} playlists and {total_users} users"

        self.console.print(f"[bold green]{start_message}[/bold green]")
        logger.info(start_message)

        # Check known unavailable playlists
        unavailable_count = sum(
            1
            for playlist_id in self.sync_lists
            if playlist_id in self.spotify_service._unavailable_playlists
        )
        if unavailable_count > 0:
            self.console.print(
                f"[yellow]⚠️  {unavailable_count} playlists are known to be unavailable[/yellow]"
            )

        total_stats = {"processed": 0, "failed": 0, "skipped": 0}

        # Create progress display with styling - simplified display
        progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(bar_width=None),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            refresh_per_second=1,  # Lower refresh rate to avoid cluttering output
            transient=False,  # Keep progress display persistent
        )

        # Process users with live progress display
        with progress:
            # Process users sequentially to avoid issues with Plex user switching
            for user in self.user_list:
                user_stats = self.process_for_user(user, progress)

                # Update total stats
                total_stats["processed"] += user_stats["processed"]
                total_stats["failed"] += user_stats["failed"]
                total_stats["skipped"] += user_stats["skipped"]

                # Print user summary - outside progress display
                self.console.print(
                    f"\n✓ Completed user [bold]{user}[/]: {user_stats['processed']} processed, {user_stats['failed']} failed, {user_stats['skipped']} skipped\n"
                )

        # Calculate duration and stats
        duration = time.time() - self.start_time
        minutes, seconds = divmod(int(duration), 60)

        # Calculate match percentage
        match_percentage = 0
        if self.total_spotify_tracks > 0:
            match_percentage = (
                self.total_matched_tracks / self.total_spotify_tracks
            ) * 100

        # Create summary table
        table = Table(title="Sync Results", show_header=True)
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")

        table.add_row("Duration", f"{minutes}m {seconds}s")
        table.add_row("Playlists Processed", str(total_stats["processed"]))
        table.add_row("Playlists Failed", str(total_stats["failed"]))
        table.add_row("Playlists Skipped", str(total_stats["skipped"]))
        table.add_row(
            "Tracks Matched",
            f"{self.total_matched_tracks}/{self.total_spotify_tracks} ({match_percentage:.1f}%)",
        )

        # Show final summary
        self.console.print("\n✅ Sync process completed!")
        self.console.print(table)

        logger.info(
            f"Sync process completed in {minutes}m {seconds}s. "
            f"Processed: {total_stats['processed']}, "
            f"Failed: {total_stats['failed']}, "
            f"Skipped: {total_stats['skipped']}, "
            f"Tracks: {self.total_matched_tracks}/{self.total_spotify_tracks} ({match_percentage:.1f}%)",
        )

    def _process_playlist(self: "SpotifyToPlex", playlist: str) -> str:
        """Process a single playlist: fetch data from Spotify and update Plex."""
        playlist_id = ""
        try:
            playlist_id = self.extract_playlist_id(playlist)
            logger.debug(f"Processing playlist ID: {playlist_id}")

            # Initialize playlist status
            self.update_playlist_status(
                playlist_id,
                {
                    "status": "processing",
                    "name": None,
                    "step": "retrieving name",
                },
            )

            # Get playlist name from Spotify
            playlist_name = self.spotify_service.get_playlist_name(playlist_id)

            # Check if this is an unavailable playlist
            if playlist_id in self.spotify_service._unavailable_playlists:
                reason = self.spotify_service._unavailable_playlists[playlist_id]
                message = f"Playlist '{playlist_name}' is unavailable: {reason}"
                logger.warning(message)
                self.console.print(f"[yellow]⚠️  {message}[/yellow]")
                self.update_playlist_status(
                    playlist_id,
                    {
                        "status": "skipped",
                        "name": playlist_name,
                        "reason": reason,
                    },
                )
                return "skipped"

            if (
                not playlist_name
                or "Error Playlist" in playlist_name
                or "Unavailable Playlist" in playlist_name
            ):
                message = f"Could not retrieve name for playlist ID '{playlist_id}'"
                logger.error(message)
                self.console.print(f"[red]❌ {message}[/red]")
                self.update_playlist_status(
                    playlist_id,
                    {
                        "status": "failed",
                        "name": None,
                        "reason": "Cannot retrieve playlist name",
                    },
                )
                return "failed"

            # Update status with name
            self.update_playlist_status(
                playlist_id,
                {
                    "status": "processing",
                    "name": playlist_name,
                    "step": "fetching tracks",
                },
            )

            logger.info(f"Processing playlist: {playlist_name} ({playlist_id})")
            self.console.print(f"[blue]→ Processing:[/blue] {playlist_name}")

            # Add date to dynamic playlists like Discover Weekly
            if "Discover Weekly" in playlist_name or "Daily Mix" in playlist_name:
                current_date = datetime.now(timezone.utc).strftime("%B %d")
                playlist_name = f"{playlist_name} {current_date}"
                logger.debug(f"Added date to dynamic playlist: {playlist_name}")

            # Get tracks from Spotify
            spotify_tracks = self.spotify_service.get_playlist_tracks(playlist_id)
            if not spotify_tracks:
                message = f"No tracks found in Spotify playlist '{playlist_name}'"
                logger.warning(message)
                self.console.print(f"  [yellow]⚠️  {message}[/yellow]")
                self.update_playlist_status(
                    playlist_id,
                    {
                        "status": "skipped",
                        "name": playlist_name,
                        "reason": "No tracks found in Spotify playlist",
                    },
                )
                return "skipped"

            track_count = len(spotify_tracks)
            logger.info(
                f"Found {track_count} tracks in Spotify playlist '{playlist_name}'"
            )
            self.console.print(
                f"  [green]✓ Found {track_count} tracks on Spotify[/green]"
            )

            # Update status
            self.update_playlist_status(
                playlist_id,
                {
                    "status": "processing",
                    "name": playlist_name,
                    "step": "retrieving cover art",
                    "tracks_found": track_count,
                },
            )

            # Get cover art
            cover_url = self.spotify_service.get_playlist_poster(playlist_id)
            if cover_url:
                logger.debug(f"Cover art retrieved for '{playlist_name}'")
                self.console.print("  [green]✓ Cover art retrieved[/green]")
            else:
                logger.debug(f"No cover art available for '{playlist_name}'")
                self.console.print("  [yellow]⚠️  No cover art available[/yellow]")

            # Update status
            self.update_playlist_status(
                playlist_id,
                {
                    "status": "processing",
                    "name": playlist_name,
                    "step": "matching tracks in Plex",
                    "tracks_found": track_count,
                    "has_cover": cover_url is not None,
                },
            )

            self.console.print("  [blue]→ Matching tracks in Plex...[/blue]")

            # Match tracks in Plex
            plex_tracks = self.plex_service.match_spotify_tracks_in_plex(spotify_tracks)

            # Update totals for statistics
            with self._status_lock:
                self.total_spotify_tracks += track_count
                self.total_matched_tracks += len(plex_tracks)

            match_percentage = (
                (len(plex_tracks) / track_count) * 100 if track_count else 0
            )
            match_message = f"Matched {len(plex_tracks)}/{track_count} tracks ({match_percentage:.1f}%)"
            logger.info(f"{match_message} in Plex for '{playlist_name}'")

            if match_percentage < 10:
                self.console.print(f"  [red]⚠️  {match_message}[/red]")
            elif match_percentage < 50:
                self.console.print(f"  [yellow]⚠️  {match_message}[/yellow]")
            else:
                self.console.print(f"  [green]✓ {match_message}[/green]")

            if not plex_tracks:
                message = (
                    f"No matching tracks found in Plex for playlist '{playlist_name}'"
                )
                logger.warning(message)
                self.console.print(f"  [yellow]⚠️  {message}[/yellow]")
                self.update_playlist_status(
                    playlist_id,
                    {
                        "status": "skipped",
                        "name": playlist_name,
                        "reason": "No matching tracks found in Plex",
                        "tracks_found": track_count,
                        "tracks_matched": 0,
                        "match_percentage": 0,
                    },
                )
                return "skipped"

            # Update status
            self.update_playlist_status(
                playlist_id,
                {
                    "status": "processing",
                    "name": playlist_name,
                    "step": "creating/updating playlist in Plex",
                    "tracks_found": track_count,
                    "tracks_matched": len(plex_tracks),
                    "match_percentage": match_percentage,
                    "has_cover": cover_url is not None,
                },
            )

            self.console.print(
                f"  [blue]→ {'Updating' if self.plex_service.find_playlist_by_name(playlist_name) else 'Creating'} playlist in Plex...[/blue]"
            )

            # Create or update playlist in Plex
            result = self.plex_service.create_or_update_playlist(
                playlist_name,
                playlist_id,
                plex_tracks,
                cover_url,
            )

            if result:
                success_message = f"Successfully processed playlist '{playlist_name}' with {len(plex_tracks)} tracks"
                logger.info(success_message)
                self.console.print(f"  [green]✅ {success_message}[/green]")
                self.update_playlist_status(
                    playlist_id,
                    {
                        "status": "processed",
                        "name": playlist_name,
                        "tracks_found": track_count,
                        "tracks_matched": len(plex_tracks),
                        "match_percentage": match_percentage,
                    },
                )
                return "processed"
            else:
                failure_message = (
                    f"Failed to create or update playlist '{playlist_name}'"
                )
                logger.error(failure_message)
                self.console.print(f"  [red]❌ {failure_message}[/red]")
                self.update_playlist_status(
                    playlist_id,
                    {
                        "status": "failed",
                        "name": playlist_name,
                        "reason": "Failed to create or update playlist in Plex",
                        "tracks_found": track_count,
                        "tracks_matched": len(plex_tracks),
                        "match_percentage": match_percentage,
                    },
                )
                return "failed"

        except Exception as exc:
            error_message = (
                f"Error processing playlist '{playlist or playlist_id}': {exc}"
            )
            logger.exception(error_message)
            self.console.print(f"  [red]❌ {error_message}[/red]")
            self.update_playlist_status(
                playlist_id,
                {
                    "status": "failed",
                    "reason": f"Exception: {exc!s}",
                },
            )
            return "failed"

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

        # Extract ID from various URL formats
        playlist_match = re.search(r"playlist[/:]([a-zA-Z0-9]+)", playlist_url)
        if playlist_match:
            return playlist_match.group(1)

        # Extract ID from open.spotify.com URLs without 'playlist' in path
        spotify_match = re.search(r"spotify\.com/([^/]+)/([a-zA-Z0-9]+)", playlist_url)
        if spotify_match and spotify_match.group(1) in ["playlist", "album"]:
            return spotify_match.group(2)

        # If not a URL, assume it's already an ID
        return playlist_url
