"""Main module for syncing Spotify playlists to Plex.

This module provides the SpotifyToPlex class that orchestrates fetching playlist
details from Spotify (and optionally Lidarr) and updating Plex playlists. All public
methods now use complete Google‑style docstrings.
"""

from datetime import datetime, timezone
import os
import re
import sys
import threading
import time
from typing import Optional

from loguru import logger

from spotify_to_plex.config import Config
from spotify_to_plex.modules.lidarr.main import LidarrClass
from spotify_to_plex.modules.plex.main import PlexClass
from spotify_to_plex.modules.spotify.main import SpotifyClass
from spotify_to_plex.utils.logging_utils import (
	ProgressBar,
	Symbols,
	console_lock,
	draw_box,
	ensure_newline,
	get_version,
	log_debug,
	log_error,
	log_header,
	log_info,
	log_playlist_step,
	log_step_end,
	log_step_start,
	log_success,
	log_warning,
	set_active_progress_bar,
)


class SpotifyToPlex:
	"""Orchestrates synchronization of Spotify playlists to Plex."""

	def __init__(
		self,
		*,
		lidarr: bool,
		playlist_id: Optional[str],
		parallel: bool = False,
		parallel_count: Optional[int] = None,
	) -> None:
		"""Initialize services and determine playlists to sync.

		Args:
		    lidarr (bool): Whether to fetch playlists from Lidarr.
		    playlist_id (Optional[str]): Specific Spotify playlist ID to sync.
		    parallel (bool): Whether to process playlists in parallel.
		    parallel_count (Optional[int]): Maximum parallel tasks.
		"""
		# Check configuration warnings
		warnings = Config.validate()
		for warning in warnings:
			log_warning(f"Configuration warning: {warning}")

		self.spotify_service = SpotifyClass()
		self.plex_service = PlexClass()
		self.version = get_version()

		# Initialize default user from Plex before fetching user list
		try:
			self.default_user: str = self.plex_service.plex.myPlexAccount().username
			log_debug(f"Connected to Plex as user: {self.default_user}")
		except Exception as e:
			log_error(f"Failed to get Plex username: {e}")
			self.default_user = "default_user"

		self.user_list: list[str] = self._get_user_list()
		self.replace_existing: bool = Config.PLEX_REPLACE
		self.sync_lists: list[str] = []
		self.parallel: bool = parallel
		self.parallel_count: int = parallel_count or Config.MAX_PARALLEL_PLAYLISTS
		self.status: dict[str, int | str] = {
			"total_playlists": 0,
			"completed_playlists": 0,
			"failed_playlists": 0,
			"current_playlist": "",
		}

		if playlist_id:
			self.sync_lists = [playlist_id]
			self.parallel = False  # Disable parallel processing for single playlist
		else:
			self.lidarr_service = LidarrClass()
			self.lidarr = lidarr
			self._get_sync_lists()

		self.status["total_playlists"] = len(self.sync_lists)

	def _get_user_list(self) -> list[str]:
		"""Retrieve the list of Plex users from configuration.

		Returns:
		    List[str]: A list of Plex usernames.
		"""
		plex_users = Config.PLEX_USERS
		user_list = (
			[u.strip() for u in plex_users.split(",") if u.strip()]
			if plex_users
			else []
		)
		if not user_list:
			user_list.append(self.default_user)
		log_debug(f"Users to process: {user_list}", Symbols.USERS)
		return user_list

	def _get_sync_lists(self) -> None:
		"""Retrieve the lists of playlist IDs from Lidarr or the config."""
		if self.lidarr:
			log_info("Fetching playlists from Lidarr...", Symbols.LIST)
			playlists = self.lidarr_service.playlist_request()
			self.sync_lists = [
				playlist_id for playlist in playlists for playlist_id in playlist
			]
			log_info(
				f"Retrieved {len(self.sync_lists)} playlists from Lidarr", Symbols.LIST
			)
		else:
			manual_playlists = Config.MANUAL_PLAYLISTS
			self.sync_lists = [
				pl.strip() for pl in manual_playlists.split(",") if pl.strip()
			]
			log_info(
				f"Using {len(self.sync_lists)} manually configured playlists",
				Symbols.LIST,
			)

	def process_for_user(self, user: str) -> None:
		"""Sync playlists for a given Plex user.

		Args:
		    user (str): The Plex username to sync playlists for.
		"""
		log_info(f"Processing for user: {user}", Symbols.USER)

		if user != self.default_user:
			try:
				log_info(f"Switching to Plex user {user}...", Symbols.USER)
				self.plex_service.plex = self.plex_service.plex.switchUser(user)
				log_debug(f"Successfully switched to Plex user: {user}")
			except Exception as exc:
				log_error(f"Failed to switch to Plex user {user}: {exc}")
				return

		if self.parallel and len(self.sync_lists) > 1:
			self._process_playlists_parallel(user)
		else:
			self._process_playlists_sequential(user)

	def _process_playlists_sequential(self, user: str) -> None:
		"""Process playlists sequentially for a user with better progress tracking.

		Args:
		    user (str): The Plex username to sync playlists for.
		"""
		log_info(
			f"Processing {len(self.sync_lists)} playlists sequentially for {user}",
			Symbols.PROCESSING,
		)

		progress_bar = ProgressBar(
			total=len(self.sync_lists),
			prefix=f"Processing playlists for {user}",
			suffix="",
		)

		for i, playlist in enumerate(self.sync_lists):
			try:
				self.status["current_playlist"] = playlist
				playlist_id_short = (
					playlist[:8] + "..." if len(playlist) > 8 else playlist
				)

				playlist_name = None
				try:
					playlist_id = self.extract_playlist_id(playlist)
					playlist_name = self.spotify_service.get_playlist_name(playlist_id)
					display_name = f"{playlist_id_short} {{{playlist_name}}}"
					progress_bar.prefix = (
						f"[{i+1}/{len(self.sync_lists)}] Processing: {display_name}"
					)
				except Exception:
					progress_bar.prefix = f"[{i+1}/{len(self.sync_lists)}] Processing: {playlist_id_short}"

				progress_bar.update(i)

				if playlist_name:
					log_info(
						f"Processing playlist {i+1}/{len(self.sync_lists)}: {playlist} {{{playlist_name}}}",
						Symbols.MUSIC,
					)
					log_step_start(
						f"Processing playlist: {display_name}",
						i + 1,
						len(self.sync_lists),
					)
				else:
					log_info(
						f"Processing playlist {i+1}/{len(self.sync_lists)}: {playlist}",
						Symbols.MUSIC,
					)
					log_step_start(
						f"Processing playlist: {playlist_id_short}",
						i + 1,
						len(self.sync_lists),
					)

				start_time = time.time()
				success = self._process_playlist_with_timeout(playlist)
				elapsed = time.time() - start_time

				if success:
					self.status["completed_playlists"] += 1
					if playlist_name:
						log_step_end(f"Playlist {display_name}", "completed", elapsed)
						log_success(
							f"Successfully processed playlist: {playlist} {{{playlist_name}}}"
						)
					else:
						log_step_end(
							f"Playlist {playlist_id_short}", "completed", elapsed
						)
						log_success(f"Successfully processed playlist: {playlist}")
				else:
					self.status["failed_playlists"] += 1
					if playlist_name:
						log_step_end(f"Playlist {display_name}", "failed", elapsed)
						log_error(
							f"Failed to process playlist: {playlist} {{{playlist_name}}}"
						)
					else:
						log_step_end(f"Playlist {playlist_id_short}", "failed", elapsed)
						log_error(f"Failed to process playlist: {playlist}")

			except Exception as exc:
				self.status["failed_playlists"] += 1
				logger.exception(f"Error processing playlist {playlist}: {exc}")
				log_error(f"Error processing playlist: {playlist}")

			finally:
				progress_bar.update(i + 1)

		progress_bar.finish()

		with console_lock:
			ensure_newline()

		log_info(
			f"Completed {self.status['completed_playlists']}/{len(self.sync_lists)} playlists for {user}",
			Symbols.FINISH,
		)

	def _process_playlists_parallel(self, user: str) -> None:
		"""Process playlists in parallel for a user with better error handling.

		Args:
		    user (str): The Plex username to sync playlists for.
		"""
		log_info(
			f"Processing {len(self.sync_lists)} playlists in parallel (max {self.parallel_count} at a time)",
			Symbols.PROCESSING,
		)

		completed_count = 0
		failed_count = 0
		active_threads: list[threading.Thread] = []
		results: dict[str, bool] = {}
		threads_lock = threading.RLock()

		progress_bar = ProgressBar(
			total=len(self.sync_lists),
			prefix=f"Parallel processing for {user}",
			suffix="0 completed, 0 failed",
		)

		set_active_progress_bar(progress_bar)

		for i in range(0, len(self.sync_lists), self.parallel_count):
			batch = self.sync_lists[i : i + self.parallel_count]
			threads: list[threading.Thread] = []

			batch_range = f"{i+1}-{min(i+len(batch), len(self.sync_lists))}"
			ensure_newline()
			print(f"\n=== BATCH {batch_range}/{len(self.sync_lists)} ===\n")

			progress_bar.prefix = f"Batch {batch_range}/{len(self.sync_lists)}"

			for playlist in batch:
				self.status["current_playlist"] = playlist
				thread = threading.Thread(
					target=self._process_playlist_thread,
					args=(playlist, results),
				)
				thread.start()
				with threads_lock:
					threads.append(thread)
					active_threads.append(thread)

			while True:
				with threads_lock:
					if not any(t.is_alive() for t in threads):
						break
					newly_completed = [t for t in active_threads if not t.is_alive()]
					if newly_completed:
						active_threads = [t for t in active_threads if t.is_alive()]

				with threads_lock:
					current_completed = sum(
						1 for success in results.values() if success
					)
					current_failed = len(results) - current_completed
					progress_bar.suffix = (
						f"{current_completed} completed, {current_failed} failed"
					)
					progress_bar.update(current_completed + current_failed)

				time.sleep(0.1)

			with threads_lock:
				remaining = [
					t for t in threads if not t.is_alive() and t in active_threads
				]
				if remaining:
					active_threads = [t for t in active_threads if t.is_alive()]
					current_completed = sum(
						1 for success in results.values() if success
					)
					current_failed = len(results) - current_completed
					progress_bar.suffix = (
						f"{current_completed} completed, {current_failed} failed"
					)
					progress_bar.update(current_completed + current_failed)

		with threads_lock:
			completed_count = sum(1 for success in results.values() if success)
			failed_count = len(results) - completed_count
			self.status["completed_playlists"] = completed_count
			self.status["failed_playlists"] = failed_count

		progress_bar.finish()

		with console_lock:
			ensure_newline()

		set_active_progress_bar(None)

		log_info(
			f"Batch processing complete: {completed_count} succeeded, {failed_count} failed",
			Symbols.FINISH,
		)

	def _process_playlist_thread(self, playlist: str, results: dict[str, bool]) -> None:
		"""Thread worker to process a playlist and store the result.

		Args:
		    playlist (str): The playlist ID or URL to process.
		    results (dict[str, bool]): A dictionary to store the result of the processing.
		"""
		try:
			playlist_name = None
			try:
				playlist_id = self.extract_playlist_id(playlist)
				playlist_name = self.spotify_service.get_playlist_name(playlist_id)
				if playlist_name:
					log_debug(
						f"Thread starting for playlist: {playlist_id} {{{playlist_name}}}",
						Symbols.THREAD,
					)
				else:
					log_warning(
						f"Thread starting for playlist: {playlist_id} - Playlist not found",
						Symbols.THREAD,
					)
			except Exception:
				log_debug(f"Thread starting for playlist: {playlist}", Symbols.THREAD)

			success = self._process_playlist_with_timeout(playlist)

			with threading.RLock():
				results[playlist] = success

			display_name = (
				f"{playlist} {{{playlist_name}}}" if playlist_name else playlist
			)
			if success:
				log_info(
					f"Thread successfully processed playlist {display_name}",
					Symbols.SUCCESS,
				)
			else:
				log_error(
					f"Thread failed to process playlist {display_name}", Symbols.ERROR
				)
		except Exception as exc:
			logger.exception(f"Thread error processing playlist {playlist}: {exc}")
			with threading.RLock():
				results[playlist] = False

	def _process_playlist_with_timeout(self, playlist: str, timeout: int = 300) -> bool:
		"""Process a playlist with a timeout safety mechanism.

		Args:
		    playlist (str): The playlist ID or URL to process.
		    timeout (int): The timeout in seconds.

		Returns:
		    bool: True if the playlist was processed successfully, False otherwise.
		"""
		try:
			playlist_name = None
			try:
				playlist_id = self.extract_playlist_id(playlist)
				playlist_name = self.spotify_service.get_playlist_name(playlist_id)
				display_name = f"{playlist} {{{playlist_name}}}"
			except Exception:
				display_name = playlist

			result: dict[str, bool | Exception | None] = {
				"success": False,
				"exception": None,
			}
			result_lock = threading.Lock()

			def worker():
				try:
					self._process_playlist(playlist)
					with result_lock:
						result["success"] = True
				except Exception as exc:
					with result_lock:
						result["exception"] = exc

			thread = threading.Thread(target=worker)
			thread.daemon = True
			thread.start()

			log_debug(
				f"Started processing playlist {display_name} with {timeout}s timeout",
				Symbols.TIME,
			)

			start_time = time.time()
			while thread.is_alive() and (time.time() - start_time) < timeout:
				thread.join(1.0)

			if thread.is_alive():
				log_warning(
					f"Processing timed out after {timeout}s for playlist {display_name}",
					Symbols.TIME,
				)
				return False

			with result_lock:
				if not result["success"]:
					if result["exception"]:
						log_error(
							f"Error processing playlist {display_name}: {result['exception']}"
						)
					return False

			log_debug(
				f"Playlist {display_name} processed within timeout period", Symbols.TIME
			)
			return True

		except Exception as exc:
			log_error(f"Error in timeout wrapper for playlist {playlist}: {exc}")
			return False

	def run(self) -> None:
		"""Run the sync process for all users."""
		if not self.sync_lists:
			log_warning("No playlists to sync!")
			return

		log_header("Starting Sync Process")
		log_info(
			f"Starting sync for {len(self.sync_lists)} playlists "
			f"and {len(self.user_list)} users",
			Symbols.START,
		)

		if self.parallel:
			log_info(
				f"Parallel processing enabled with max {self.parallel_count} concurrent playlists",
				Symbols.PROCESSING,
			)

		start_time = time.time()

		for i, user in enumerate(self.user_list):
			user_start_time = time.time()

			with console_lock:
				print("\n┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓")
				print(f"┃  USER {i+1}/{len(self.user_list)}: {user: <32} ┃")
				print("┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛")

			log_info(
				f"Starting processing for user {i+1}/{len(self.user_list)}: {user}",
				Symbols.USER,
			)

			self.status["completed_playlists"] = 0
			self.status["failed_playlists"] = 0

			self.process_for_user(user)

			user_time = time.time() - user_start_time
			log_info(
				f"Completed user {i+1}/{len(self.user_list)}: {user} in {user_time:.1f}s - "
				f"{self.status['completed_playlists']} succeeded, "
				f"{self.status['failed_playlists']} failed",
				Symbols.SUCCESS,
			)

		total_time = time.time() - start_time
		total_processed = (
			self.status["completed_playlists"] + self.status["failed_playlists"]
		)
		success_rate = (
			(self.status["completed_playlists"] / max(1, total_processed)) * 100
			if total_processed > 0
			else 0
		)

		with console_lock:
			print("\n" + "═" * 60)
			print(f"  {Symbols.FINISH} SYNC PROCESS COMPLETED")
			print("  " + "─" * 30)
			print(f"  • Time taken: {total_time:.1f}s")
			print(f"  • Success rate: {success_rate:.1f}%")
			print(
				f"  • Successful: {self.status['completed_playlists']}/{total_processed}"
			)
			print(f"  • Failed: {self.status['failed_playlists']}/{total_processed}")
			print("═" * 60 + "\n")

		log_info(
			f"Sync process completed in {total_time:.1f}s with {self.status['completed_playlists']} "
			f"successes ({success_rate:.1f}%) and {self.status['failed_playlists']} failures",
			Symbols.FINISH,
		)

	def _process_playlist(self, playlist: str) -> None:
		"""Process a single playlist: fetch data from Spotify and update Plex.

		Args:
		    playlist (str): The playlist ID or URL to process.
		"""
		try:
			log_debug(f"Starting to process playlist: {playlist}", Symbols.SEARCH)
			playlist_id = self.extract_playlist_id(playlist)

			with console_lock:
				title = f" PLAYLIST: {playlist_id} "
				top, content, bottom = draw_box(title, padding=2, extra_width=4)

				print("\n\n")
				print(top)
				print(content)
				print(bottom)
				print()

			log_step_start("Getting playlist details", 1, 4)
			playlist_name = None
			start_time = time.time()

			try:
				playlist_name = self.spotify_service.get_playlist_name(playlist_id)

				if playlist_name:
					display_name = f"{playlist_id} {{{playlist_name}}}"
					log_playlist_step(
						playlist_id,
						playlist_name,
						"Retrieved playlist",
						console_only=True,
					)
					log_step_end(
						"Get playlist details",
						"completed",
						time.time() - start_time,
						f"Playlist name: '{playlist_name}'",
						console_only=True,
					)

					with console_lock:
						title = f" PLAYLIST: {playlist_id} {{{playlist_name}}} "
						top, content, bottom = draw_box(title, padding=2, extra_width=4)
						print("\n")
						print(top)
						print(content)
						print(bottom)
						print()
				else:
					log_error(f"Playlist not found or access denied: '{playlist_id}'")
					log_step_end(
						"Get playlist details",
						"failed (not found)",
						time.time() - start_time,
						console_only=True,
					)
					return
			except Exception as e:
				if "404" in str(e) or "not found" in str(e).lower():
					log_error(
						f"Playlist not found: '{playlist_id}'. It may have been deleted or made private."
					)
				else:
					log_error(f"Error getting playlist name: {e}")
				log_step_end(
					"Get playlist details",
					"failed",
					time.time() - start_time,
					console_only=True,
				)
				return

			if playlist_name and (
				"Discover Weekly" in playlist_name or "Daily Mix" in playlist_name
			):
				current_date = datetime.now(timezone.utc).strftime("%B %d")
				playlist_name = f"{playlist_name} {current_date}"
				log_debug(
					f"Added date to dynamic playlist: {playlist_name}", Symbols.DATE
				)

			log_step_start(
				"Fetching tracks from Spotify", 2, 4, f"Playlist: '{playlist_name}'"
			)
			start_time = time.time()

			spotify_tracks: list[dict] = []
			try:
				spotify_tracks = self.spotify_service.get_playlist_tracks(playlist_id)

				if spotify_tracks:
					ensure_newline()
					with console_lock:
						print(
							f"  {Symbols.TRACKS} Found {len(spotify_tracks)} tracks on Spotify for '{playlist_name}'"
						)
					log_step_end(
						"Fetch tracks",
						"completed",
						time.time() - start_time,
						f"Retrieved {len(spotify_tracks)} tracks",
						console_only=True,
					)
				else:
					log_warning(
						f"No tracks found in Spotify playlist '{playlist_name}'"
					)
					log_step_end(
						"Fetch tracks",
						"failed (no tracks found)",
						time.time() - start_time,
						console_only=True,
					)
					return
			except Exception as e:
				if "404" in str(e) or "not found" in str(e).lower():
					log_error(
						f"Playlist not found: '{playlist_id}'. It may have been deleted or made private."
					)
				else:
					log_error(f"Error fetching tracks from Spotify: {e}")
				log_step_end(
					"Fetch tracks",
					"failed",
					time.time() - start_time,
					console_only=True,
				)
				return

			cover_url: Optional[str] = None
			try:
				log_debug(
					f"Getting cover art for playlist '{playlist_name}'...",
					Symbols.PLAYLIST,
				)
				cover_url = self.spotify_service.get_playlist_poster(playlist_id)
				if cover_url:
					log_debug(f"Retrieved cover art URL for '{playlist_name}'")
				else:
					log_debug(f"No cover art found for playlist '{playlist_name}'")
			except Exception as e:
				log_warning(f"Error getting cover art: {e}")

			log_step_start("Matching tracks in Plex", 3, 4)
			start_time = time.time()

			track_count = len(spotify_tracks)

			plex_tracks: list[dict] = []
			try:
				with open(os.devnull, "w") as null_device:
					old_stderr = sys.stderr
					sys.stderr = null_device
					try:
						plex_tracks = self.plex_service.match_spotify_tracks_in_plex(
							spotify_tracks
						)
					finally:
						sys.stderr = old_stderr

				if plex_tracks:
					match_percentage = (len(plex_tracks) / track_count) * 100
					log_info(
						f"Matched {len(plex_tracks)}/{track_count} tracks "
						f"({match_percentage:.1f}%) in Plex for '{playlist_name}'",
						Symbols.SUCCESS,
						console_only=True,
					)
					log_step_end(
						"Match tracks",
						"completed",
						time.time() - start_time,
						console_only=True,
					)
				else:
					log_warning(
						f"No matching tracks found in Plex for playlist '{playlist_name}'"
					)
					log_step_end(
						"Match tracks",
						"failed (no matches)",
						time.time() - start_time,
						console_only=True,
					)
					return
			except Exception as e:
				log_error(f"Error matching tracks in Plex: {e}")
				log_step_end(
					"Match tracks",
					"failed",
					time.time() - start_time,
					console_only=True,
				)
				return

			log_step_start(
				"Creating/updating Plex playlist", 4, 4, f"Playlist: '{playlist_name}'"
			)
			start_time = time.time()

			try:
				result = self.plex_service.create_or_update_playlist(
					playlist_name,
					playlist_id,
					plex_tracks,
					cover_url,
				)

				if result:
					log_info(
						f"Successfully created/updated playlist '{playlist_name}' with {len(plex_tracks)} tracks",
						Symbols.SUCCESS,
						console_only=True,
					)
					log_step_end(
						"Create/update Plex playlist",
						"completed",
						time.time() - start_time,
						console_only=True,
					)
				else:
					log_error(
						f"Failed to create or update playlist '{playlist_name}'",
						Symbols.ERROR,
					)
					log_step_end(
						"Create/update Plex playlist",
						"failed",
						time.time() - start_time,
						console_only=True,
					)
					return
			except Exception as e:
				log_error(f"Error creating/updating playlist: {e}")
				log_step_end(
					"Create/update Plex playlist",
					"failed",
					time.time() - start_time,
					console_only=True,
				)
				return

		except Exception as exc:
			logger.exception(f"Error processing playlist '{playlist}': {exc}")
			raise

	@staticmethod
	def extract_playlist_id(playlist_url: str) -> str:
		"""Extract the Spotify playlist ID from a URL.

		Args:
		    playlist_url (str): The playlist URL.

		Returns:
		    str: The extracted playlist ID.
		"""
		if "?" in playlist_url:
			playlist_url = playlist_url.split("?")[0]
		match = re.search(r"playlist[/:]([a-zA-Z0-9]+)", playlist_url)
		return match.group(1) if match else playlist_url
