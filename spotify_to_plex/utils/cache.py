"""Caching utilities for API responses."""
import functools
import hashlib
import json
import os
import pickle
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional, TypeVar, cast

from loguru import logger

from spotify_to_plex.config import Config

# Type variables for better typing
T = TypeVar("T")
CacheDict = Dict[str, tuple[float, Any]]

# Global in-memory cache
_MEMORY_CACHE: CacheDict = {}


def _get_cache_dir() -> Path:
    """Get the directory to store cache files.

    Uses the CACHE_DIR environment variable if set, otherwise
    defaults to ~/.cache/spotify-to-plex

    Returns:
        Path: The cache directory path
    """
    if Config.CACHE_DIR:
        cache_dir = Path(Config.CACHE_DIR)
    else:
        cache_dir = Path.home() / ".cache" / "spotify-to-plex"

    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def _get_cache_key(func: Callable, args: tuple, kwargs: dict) -> str:
    """Generate a unique cache key based on function name and arguments."""
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


def cache_result(ttl: Optional[int] = None, use_disk: bool = False):
    """Decorator to cache function results in memory or on disk.

    Args:
        ttl: Time to live in seconds. If None, uses Config.CACHE_TTL
        use_disk: Whether to store cache on disk instead of memory
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            # Skip caching if disabled
            if not Config.ENABLE_CACHE:
                return func(*args, **kwargs)

            # Determine TTL
            cache_ttl = ttl if ttl is not None else Config.CACHE_TTL

            # Generate cache key
            cache_key = _get_cache_key(func, args, kwargs)

            if use_disk:
                # Disk-based cache lookup
                cache_file = _get_cache_dir() / f"{cache_key}.cache"
                if cache_file.exists():
                    try:
                        with open(cache_file, "rb") as f:
                            timestamp, result = pickle.load(f)
                            if time.time() - timestamp <= cache_ttl:
                                logger.debug(f"Cache hit for {func.__name__}")
                                return cast(T, result)
                    except (pickle.PickleError, EOFError, OSError):
                        logger.debug(f"Failed to load cache for {func.__name__}")
            else:
                # Memory-based cache lookup
                if cache_key in _MEMORY_CACHE:
                    timestamp, result = _MEMORY_CACHE[cache_key]
                    if time.time() - timestamp <= cache_ttl:
                        logger.debug(f"Cache hit for {func.__name__}")
                        return cast(T, result)

            # Cache miss or expired, call the function
            result = func(*args, **kwargs)

            # Store result in cache
            if use_disk:
                try:
                    with open(_get_cache_dir() / f"{cache_key}.cache", "wb") as f:
                        pickle.dump((time.time(), result), f)
                except (pickle.PickleError, OSError):
                    logger.debug(f"Failed to write cache for {func.__name__}")
            else:
                _MEMORY_CACHE[cache_key] = (time.time(), result)

            return result

        return wrapper

    return decorator


def clear_cache() -> None:
    """Clear all caches (memory and disk)."""
    global _MEMORY_CACHE
    _MEMORY_CACHE = {}

    cache_dir = _get_cache_dir()
    if cache_dir.exists():
        for cache_file in cache_dir.glob("*.cache"):
            try:
                cache_file.unlink()
            except OSError:
                pass

    logger.info("Cache cleared")
