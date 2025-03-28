"""Module for interacting with the Plex API.

This module provides the PlexClass to encapsulate Plex operations. All public
methods include Google‑style docstrings and type hints.
"""

import datetime
import functools
import time
from typing import Any, Optional

import httpx
from loguru import logger
from plexapi.audio import Track
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
		"""Initialize Plex connection using configuration values.

		Raises:
		    ValueError: If Plex URL or token is missing.
		"""
		self.plex_url: str = Config.PLEX_SERVER_URL
		self.plex_token: str = Config.PLEX_TOKEN
		self.replacement_policy: bool = Config.PLEX_REPLACE
		self._track_index: dict[tuple[str, str], Track] = {}
		self._artist_index: dict[str, Any] = {}

		if not self.plex_url or not self.plex_token:
			logger.error("Plex credentials are missing")
			raise ValueError("Missing Plex credentials")
		self.plex = self.connect_plex()

	def connect_plex(self: "PlexClass") -> PlexServer:
		"""Connect to the Plex server.

		Returns:
		    PlexServer: Connected PlexServer instance.

		Raises:
		    Unauthorized: On invalid Plex token.
		    httpx.HTTPError: For network or HTTP errors.
		"""
		try:
			# Always use verify=False for local Plex servers to handle self-signed certificates
			session = httpx.Client(verify=False)

			# Set the urllib3 warning filter to ignore insecure request warnings
			import urllib3
			urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

			logger.debug(f"Connecting to Plex server at {self.plex_url} (SSL verification disabled)")
			server = PlexServer(self.plex_url, self.plex_token, session=session)
		except Unauthorized:
			logger.error("Failed to connect to Plex: Unauthorized. Check your token.")
			raise
		except httpx.HTTPError as err:
			logger.exception(f"HTTP error connecting to Plex server: {err}")
			raise
		except Exception as err:
			logger.exception(f"Failed to connect to Plex server: {err}")
			raise
		else:
			logger.debug(
				f"Successfully connected to Plex server: {server.friendlyName}"
			)
			return server

	@functools.lru_cache(maxsize=1)
	def get_music_library(self) -> Any:
		"""Retrieve the Plex music library section.

		Returns:
		    Any: The Plex music library.
		"""
		return self.plex.library.section("Music")

	def _build_track_index(self: "PlexClass") -> None:
		"""Build index of tracks for faster lookup."""
		if self._track_index:
			return
		start_time = time.time()
		logger.debug("Building track index...")
		try:
			music = self.get_music_library()
			for artist in music.searchArtists():
				artist_name_lower = artist.title.lower()
				self._artist_index[artist_name_lower] = artist
				try:
					for track in artist.tracks():
						key = (track.title.lower(), artist_name_lower)
						self._track_index[key] = track
				except Exception as track_err:
					logger.debug(
						f"Error retrieving tracks for artist {artist.title}: {track_err}"
					)
			elapsed = time.time() - start_time
			logger.info(
				f"Track index built with {len(self._track_index)} tracks in {elapsed:.2f}s"
			)
		except Exception as err:
			logger.error(f"Failed to build track index: {err}")

	def match_spotify_tracks_in_plex(
		self: "PlexClass", spotify_tracks: list[tuple[str, str]]
	) -> list[Track]:
		"""Match Spotify tracks in the Plex music library.

		Args:
		    spotify_tracks (List[Tuple[str, str]]): List of tuples (track name, artist name).

		Returns:
		    List[Track]: List of matched Plex Track objects.
		"""
		start_time = time.time()
		logger.info(f"Matching {len(spotify_tracks)} Spotify tracks in Plex")

		if len(spotify_tracks) > 200:
			logger.warning(
				f"Large playlist with {len(spotify_tracks)} tracks may take a while to process"
			)

		if len(spotify_tracks) > 10 and not self._track_index:
			self._build_track_index()

		total_tracks = len(spotify_tracks)
		batch_size = max(1, min(50, total_tracks // 10))
		matched_tracks: list[Track] = []
		missing_tracks: list[tuple[str, str]] = []
		use_index = bool(self._track_index)

		for i, (track_name, artist_name) in enumerate(spotify_tracks):
			# Report progress using logging only.
			if i and i % batch_size == 0:
				elapsed = time.time() - start_time
				tracks_per_sec = i / elapsed if elapsed > 0 else 0
				eta = (
					(total_tracks - i) / tracks_per_sec
					if tracks_per_sec > 0
					else float("inf")
				)
				eta_str = f"{eta:.1f}s" if eta != float("inf") else "unknown"
				logger.debug(
					f"Matching progress: {i}/{total_tracks} tracks ({i/total_tracks*100:.1f}%), "
					f"speed: {tracks_per_sec:.1f} tracks/sec, ETA: {eta_str}"
				)

			key = (track_name.lower(), artist_name.lower())
			# First try: Direct index lookup.
			if use_index and key in self._track_index:
				matched_tracks.append(self._track_index[key])
				continue

			# Second try: Quick search by artist.
			if use_index and artist_name.lower() in self._artist_index:
				try:
					results = self.get_music_library().searchTracks(
						title=track_name,
						artist=artist_name,
						maxresults=1,
					)
					if results:
						matched_tracks.append(results[0])
						self._track_index[key] = results[0]
						continue
				except Exception as err:
					logger.debug(
						f"Artist-based search error for '{track_name}' by '{artist_name}': {err}"
					)

			# Third try: Full library search.
			try:
				results = self.get_music_library().searchTracks(
					title=track_name,
					maxresults=5,
				)
				track_found = False
				for track in results:
					if (
						getattr(track, "originalTitle", "").lower()
						== track_name.lower()
					):
						matched_tracks.append(track)
						self._track_index[key] = track
						track_found = True
						break
					artists = (
						[track.artist]
						if hasattr(track, "artist") and track.artist
						else getattr(track, "artists", [])
					)
					for artist in artists:
						if hasattr(artist, "title") and (
							artist.title.lower() == artist_name.lower()
							or artist_name.lower() in artist.title.lower()
							or artist.title.lower() in artist_name.lower()
						):
							matched_tracks.append(track)
							self._track_index[key] = track
							track_found = True
							break
					if track_found:
						break
			except Exception as err:
				logger.debug(
					f"Full library search error for '{track_name}' by '{artist_name}': {err}"
				)

			if key not in self._track_index:
				missing_tracks.append((track_name, artist_name))

		elapsed_total = time.time() - start_time
		tracks_per_sec = total_tracks / elapsed_total if elapsed_total > 0 else 0
		success_percentage = (
			(len(matched_tracks) / total_tracks) * 100 if total_tracks else 0
		)
		logger.info(
			f"Matched {len(matched_tracks)}/{total_tracks} tracks ({success_percentage:.2f}%) in "
			f"{elapsed_total:.1f}s ({tracks_per_sec:.1f} tracks/sec)"
		)
		if missing_tracks:
			display_count = min(len(missing_tracks), MAX_DISPLAY_MISSING)
			logger.debug(
				f"Missing tracks: {missing_tracks[:display_count]}{'...' if len(missing_tracks) > display_count else ''}"
			)
		return matched_tracks

	@cache_result(ttl=3600, use_disk=True)
	def set_cover_art(self: "PlexClass", playlist: Playlist, cover_url: str) -> bool:
		"""Set cover art for a Plex playlist.

		Args:
		    playlist (Playlist): The Plex playlist object.
		    cover_url (str): URL of the cover image.

		Returns:
		    bool: True if successful, False otherwise.
		"""
		if not cover_url:
			return False

		try:
			playlist.uploadPoster(url=cover_url)
		except Exception as err:
			logger.warning(
				f"Failed to set cover art for playlist '{playlist.title}': {err}"
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
		cover_url: Optional[str],
	) -> Optional[Playlist]:
		"""Create a new Plex playlist with the specified tracks.

		Args:
		    playlist_name (str): Name of the new playlist.
		    playlist_id (str): Source Spotify playlist ID.
		    tracks (List[Track]): List of Plex Track objects.
		    cover_url (Optional[str]): Cover art URL.

		Returns:
		    Optional[Playlist]: The newly created Plex Playlist, or None if creation failed.
		"""
		now = datetime.datetime.now(datetime.timezone.utc)
		try:
			initial_tracks = tracks[:CHUNK_SIZE]
			remaining_tracks = tracks[CHUNK_SIZE:]
			logger.debug(
				f"Creating new playlist '{playlist_name}' with {len(initial_tracks)} initial tracks"
			)
			new_playlist = self.plex.createPlaylist(playlist_name, items=initial_tracks)
			summary = (
				f"Playlist auto-created by spotify_to_plex on {now.strftime('%m/%d/%Y')}.\n"
				f"Source: Spotify, Playlist ID: {playlist_id}"
			)
			new_playlist.editSummary(summary=summary)
			if cover_url:
				self.set_cover_art(new_playlist, cover_url)
			while remaining_tracks:
				chunk, remaining_tracks = (
					remaining_tracks[:CHUNK_SIZE],
					remaining_tracks[CHUNK_SIZE:],
				)
				logger.debug(
					f"Adding {len(chunk)} more tracks to playlist '{playlist_name}'"
				)
				new_playlist.addItems(chunk)
		except Exception as err:
			logger.exception(f"Error creating playlist '{playlist_name}': {err}")
			return None
		else:
			logger.info(
				f"Successfully created playlist '{playlist_name}' with {len(tracks)} tracks"
			)
			return new_playlist

	def update_playlist(
		self: "PlexClass",
		existing_playlist: Playlist,
		playlist_id: str,
		tracks: list[Track],
		cover_url: Optional[str],
	) -> Optional[Playlist]:
		"""Update an existing Plex playlist with new tracks.

		Args:
		    existing_playlist (Playlist): The existing Plex playlist.
		    playlist_id (str): Source Spotify playlist ID.
		    tracks (List[Track]): List of Plex Track objects.
		    cover_url (Optional[str]): Cover art URL.

		Returns:
		    Optional[Playlist]: The updated Plex Playlist, or None if update failed.
		"""
		now = datetime.datetime.now(datetime.timezone.utc)
		try:
			if self.replacement_policy:
				logger.debug(
					f"Deleting existing playlist '{existing_playlist.title}' for replacement"
				)
				existing_playlist.delete()
				return self.create_playlist(
					existing_playlist.title, playlist_id, tracks, cover_url
				)
			logger.debug(f"Updating existing playlist '{existing_playlist.title}'")
			summary = (
				f"Playlist updated by spotify_to_plex on {now.strftime('%m/%d/%Y')}.\n"
				f"Source: Spotify, Playlist ID: {playlist_id}"
			)
			existing_playlist.editSummary(summary=summary)
			if cover_url:
				self.set_cover_art(existing_playlist, cover_url)
			if tracks:
				existing_playlist.addItems(tracks)
				logger.debug(f"Added {len(tracks)} tracks to existing playlist")
		except Exception as err:
			logger.exception(
				f"Error updating playlist '{existing_playlist.title}': {err}"
			)
			return None
		else:
			logger.info(f"Successfully updated playlist '{existing_playlist.title}'")
			return existing_playlist

	@cache_result(ttl=60)
	def find_playlist_by_name(
		self: "PlexClass", playlist_name: str
	) -> Optional[Playlist]:
		"""Find a Plex playlist by name.

		Args:
		    playlist_name (str): The name of the playlist.

		Returns:
		    Optional[Playlist]: A matching Plex Playlist, or None if not found.
		"""
		try:
			for playlist in self.plex.playlists():
				if playlist.title == playlist_name:
					logger.debug(f"Found existing playlist '{playlist_name}'")
					return playlist
		except Exception as err:
			logger.exception(f"Error finding playlist '{playlist_name}': {err}")
			return None
		logger.debug(f"No existing playlist found with name '{playlist_name}'")
		return None

	def create_or_update_playlist(
		self: "PlexClass",
		playlist_name: str,
		playlist_id: str,
		tracks: list[Track],
		cover_url: Optional[str],
	) -> Optional[Playlist]:
		"""Create or update a Plex playlist based on whether it exists already.

		Args:
		    playlist_name (str): The name of the playlist.
		    playlist_id (str): The Spotify playlist ID.
		    tracks (List[Track]): List of Plex Track objects.
		    cover_url (Optional[str]): Cover art URL.

		Returns:
		    Optional[Playlist]: The created or updated Plex Playlist.
		"""
		if not tracks:
			logger.warning(f"No tracks to add to playlist '{playlist_name}'")
			return None
		try:
			existing_playlist = self.find_playlist_by_name(playlist_name)
			if existing_playlist is not None:
				return self.update_playlist(
					existing_playlist, playlist_id, tracks, cover_url
				)
			return self.create_playlist(playlist_name, playlist_id, tracks, cover_url)
		except Exception as err:
			logger.exception(
				f"Error creating/updating playlist '{playlist_name}': {err}"
			)
			return None
