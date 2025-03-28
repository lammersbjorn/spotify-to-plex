"""Module for interacting with the Lidarr API for playlist imports.

This module provides a client that communicates with the Lidarr API and processes
playlist data. All public methods include Google‑style docstrings and type hints.
"""

from typing import Any, Optional

import httpx
from loguru import logger

from spotify_to_plex.config import Config


class LidarrClass:
	"""Handles communication with the Lidarr API.

	Attributes:
	    url (str): The base URL for the Lidarr API.
	    api_key (str): The API key for authentication.
	    headers (Dict[str, str]): HTTP headers with the API key for requests.
	"""

	def __init__(self: "LidarrClass") -> None:
		"""Initialize the Lidarr connection using configuration.

		Raises:
		    Warning: If the API URL or API key is not properly configured.
		"""
		self.url: str = Config.LIDARR_API_URL
		self.api_key: str = Config.LIDARR_API_KEY
		self.headers: dict[str, str] = {"X-Api-Key": self.api_key}

		if not self.url or not self.api_key:
			logger.warning("Lidarr API credentials not properly configured")

	def lidarr_request(
		self: "LidarrClass", endpoint_path: str
	) -> Optional[dict[str, Any]]:
		"""Make a GET request to a specified Lidarr endpoint.

		Args:
		    endpoint_path (str): The endpoint path.

		Returns:
		    Optional[Dict[str, Any]]: The parsed JSON response or None on failure.

		Raises:
		    httpx.RequestError: For network-related errors.
		    ValueError: If JSON decoding fails.
		"""
		url = f"{self.url.rstrip('/')}/{endpoint_path.lstrip('/')}"
		logger.debug(f"Making Lidarr API request to: {url}")

		try:
			with httpx.Client(timeout=30.0) as client:
				response = client.get(url=url, headers=self.headers)
				response.raise_for_status()
				return response.json()
		except httpx.HTTPStatusError as http_err:
			logger.exception(f"HTTP status error during Lidarr API call: {http_err}")
			return None
		except httpx.RequestError as req_err:
			logger.exception(f"Network error during Lidarr API call: {req_err}")
			return None
		except ValueError as json_err:
			logger.exception(f"Invalid JSON response from Lidarr API: {json_err}")
			return None

	def playlist_request(self: "LidarrClass") -> list[list[str]]:
		"""Retrieve Spotify playlist IDs from Lidarr import lists.

		Returns:
		    List[List[str]]: A list (per import list) of Spotify playlist IDs.

		Raises:
		    httpx.RequestError: For network-related errors.
		"""
		endpoint = "/api/v1/importlist"
		raw_playlists = self.lidarr_request(endpoint_path=endpoint)

		if not raw_playlists:
			logger.warning("No playlists data received from Lidarr")
			return []

		spotify_playlists: list[list[str]] = []
		for entry in raw_playlists:
			if entry.get("listType") != "spotify":
				continue
			for field in entry.get("fields", []):
				if field.get("name") == "playlistIds":
					playlist_ids = field.get("value", [])
					if playlist_ids:
						spotify_playlists.append(playlist_ids)
						logger.debug(
							f"Found Spotify playlist IDs in Lidarr: {playlist_ids}"
						)

		if not spotify_playlists:
			logger.debug("No Spotify playlists found in Lidarr response")
		return spotify_playlists
