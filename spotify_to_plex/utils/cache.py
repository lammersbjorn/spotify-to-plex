"""Caching utilities for API responses.

This module provides decorators and functions to cache API responses either in memory
or on disk. It helps reduce API calls and improve performance by storing results
for a configurable time period.

Typical usage:
    @cache_result(ttl=3600, use_disk=True)
    def fetch_data_from_api(param1, param2):
        # API call implementation
        pass
"""
from __future__ import annotations

from collections.abc import Callable
import functools
import hashlib
import json
from pathlib import Path
import pickle
import time
from typing import Any, Optional, TypeVar, cast

from loguru import logger

from spotify_to_plex.config import Config

# Type variables for better typing
T = TypeVar("T")  # Return type of the cached function
CacheDict = dict[str, tuple[float, Any]]  # More explicit Dict/Tuple vs dict/tuple

# Global in-memory cache
_MEMORY_CACHE: CacheDict = {}


def _get_cache_dir() -> Path:
	"""Get the directory to store cache files.

	Uses the CACHE_DIR environment variable if set, otherwise
	defaults to ~/.cache/spotify-to-plex

	Returns:
	    Path: The cache directory path.

	Raises:
	    PermissionError: If the directory cannot be created due to permission issues.
	"""
	try:
		if Config.CACHE_DIR:
			cache_dir = Path(Config.CACHE_DIR)
		else:
			cache_dir = Path.home() / ".cache" / "spotify-to-plex"

		cache_dir.mkdir(parents=True, exist_ok=True)
		return cache_dir
	except PermissionError as e:
		logger.error(f"Cannot create cache directory: {e}")
		raise


def _get_cache_key(func: Callable, args: tuple, kwargs: dict) -> str:
	"""Generate a unique cache key based on function name and arguments.

	Args:
	    func: The function being cached.
	    args: Positional arguments to the function.
	    kwargs: Keyword arguments to the function.

	Returns:
	    str: A hexadecimal MD5 hash that uniquely identifies this function call.
	"""
	# Create a string representation of the function and its arguments
	key_parts = [
		func.__module__,
		func.__name__,
		str(args),
		str(sorted(kwargs.items())),
	]
	key_string = json.dumps(key_parts, sort_keys=True)

	# Hash the string to get a fixed-length key
	return hashlib.md5(key_string.encode()).hexdigest()


def cache_result(
	ttl: Optional[int] = None, use_disk: bool = False
) -> Callable[[Callable[..., T]], Callable[..., T]]:
	"""Decorator to cache function results in memory or on disk.

	Args:
	    ttl: Time to live in seconds. If None, uses Config.CACHE_TTL
	    use_disk: Whether to store cache on disk instead of memory.

	Returns:
	    Callable: A decorator function that wraps the target function with caching.

	Example:
	    >>> @cache_result(ttl=3600, use_disk=True)
	    >>> def expensive_function(param):
	    >>>     return some_expensive_operation(param)
	"""

	def decorator(func: Callable[..., T]) -> Callable[..., T]:
		@functools.wraps(func)
		def wrapper(*args: Any, **kwargs: Any) -> T:
			# Skip caching if disabled
			if not Config.ENABLE_CACHE:
				logger.debug(f"Cache disabled, directly calling {func.__name__}")
				return func(*args, **kwargs)

			# Determine TTL
			cache_ttl = ttl if ttl is not None else Config.CACHE_TTL

			# Generate cache key
			cache_key = _get_cache_key(func, args, kwargs)

			# Try to get from cache first
			cached_result = _get_from_cache(func, cache_key, cache_ttl, use_disk)
			if cached_result is not None:
				return cast(T, cached_result)

			# Cache miss or expired, call the function
			logger.debug(f"Cache miss for {func.__name__}, executing function")
			result = func(*args, **kwargs)

			# Store result in cache
			_store_in_cache(func, cache_key, result, use_disk)

			return result

		return wrapper

	return decorator


def _get_from_cache(
	func: Callable, cache_key: str, cache_ttl: int, use_disk: bool
) -> Optional[Any]:
	"""Retrieve a value from the cache if it exists and is not expired.

	Args:
	    func: The function associated with the cache entry.
	    cache_key: The unique key for the cache entry.
	    cache_ttl: Time-to-live in seconds.
	    use_disk: Whether to check disk cache instead of memory.

	Returns:
	    The cached result if found and not expired, None otherwise.
	"""
	if use_disk:
		# Disk-based cache lookup
		try:
			cache_file = _get_cache_dir() / f"{cache_key}.cache"
			if cache_file.exists():
				try:
					with open(cache_file, "rb") as f:
						timestamp, result = pickle.load(f)
						if time.time() - timestamp <= cache_ttl:
							logger.debug(f"Cache hit for {func.__name__} (disk cache)")
							return result
						logger.debug(f"Cache expired for {func.__name__} (disk cache)")
				except (pickle.PickleError, EOFError) as e:
					logger.warning(f"Failed to load cache for {func.__name__}: {e}")
				except OSError as e:
					logger.warning(
						f"File error when loading cache for {func.__name__}: {e}"
					)
		except Exception as e:
			logger.warning(f"Unexpected error accessing disk cache: {e}")
	else:
		# Memory-based cache lookup
		if cache_key in _MEMORY_CACHE:
			timestamp, result = _MEMORY_CACHE[cache_key]
			if time.time() - timestamp <= cache_ttl:
				logger.debug(f"Cache hit for {func.__name__} (memory cache)")
				return result
			logger.debug(f"Cache expired for {func.__name__} (memory cache)")

	return None


def _store_in_cache(
	func: Callable, cache_key: str, result: Any, use_disk: bool
) -> None:
	"""Store a result in the cache.

	Args:
	    func: The function associated with the cache entry.
	    cache_key: The unique key for the cache entry.
	    result: The value to cache.
	    use_disk: Whether to store in disk cache instead of memory.
	"""
	current_time = time.time()

	if use_disk:
		try:
			cache_file = _get_cache_dir() / f"{cache_key}.cache"
			with open(cache_file, "wb") as f:
				pickle.dump((current_time, result), f)
			logger.debug(f"Stored result in disk cache for {func.__name__}")
		except (pickle.PickleError, TypeError) as e:
			logger.warning(f"Failed to pickle result for {func.__name__}: {e}")
		except OSError as e:
			logger.warning(f"File error when writing cache for {func.__name__}: {e}")
	else:
		_MEMORY_CACHE[cache_key] = (current_time, result)
		logger.debug(f"Stored result in memory cache for {func.__name__}")


def clear_cache() -> None:
	"""Clear all caches (memory and disk).

	Removes all entries from the in-memory cache and deletes all cache files from disk.

	Raises:
	    OSError: If there's a problem accessing or deleting cache files.
	"""
	global _MEMORY_CACHE
	_MEMORY_CACHE = {}
	logger.info("Memory cache cleared")

	try:
		cache_dir = _get_cache_dir()
		if cache_dir.exists():
			deleted_count = 0
			failed_count = 0
			for cache_file in cache_dir.glob("*.cache"):
				try:
					cache_file.unlink()
					deleted_count += 1
				except OSError as e:
					logger.warning(f"Failed to delete cache file {cache_file}: {e}")
					failed_count += 1

			logger.info(
				f"Disk cache cleared: {deleted_count} files deleted, {failed_count} failed"
			)
	except OSError as e:
		logger.error(f"Error while clearing disk cache: {e}")
		raise
