"""Entry point for Typer application."""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Get the directory containing the script
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from .env file with explicit path
# Make sure dotenv is loaded before any other imports
load_dotenv(dotenv_path=os.path.join(BASE_DIR, ".env"))

# Set Spotipy environment variables based on your config
if os.environ.get("SPOTIFY_CLIENT_ID"):
    os.environ["SPOTIPY_CLIENT_ID"] = os.environ["SPOTIFY_CLIENT_ID"]
if os.environ.get("SPOTIFY_CLIENT_SECRET"):
    os.environ["SPOTIPY_CLIENT_SECRET"] = os.environ["SPOTIFY_CLIENT_SECRET"]

import typer
import datetime
from typing import Union, Dict, Any, Optional

from spotify_to_plex.config import Config
from spotify_to_plex.modules.spotify_to_plex import main as sp_module
from spotify_to_plex.modules.spotify.main import SpotifyClass
from spotify_to_plex.modules.plex.main import PlexClass
from spotify_to_plex.utils.cache import clear_cache
from spotify_to_plex.utils.logging_utils import (
    setup_logging, log_info, log_debug, log_warning, log_error,
    log_success, log_header, Symbols, perform_task, get_version,
    console_lock
)

# Set up logging with simplified console format
setup_logging(log_level="INFO")

# Get version from Git or fallback to default
version = get_version()

# Log application startup with version info
log_info(f"Spotify to Plex v{version} starting up", Symbols.MUSIC)
log_debug(f"Environment variables loaded. SPOTIFY_CLIENT_ID present: "
          f"{'✓' if os.environ.get('SPOTIFY_CLIENT_ID') else '✗'}", file_only=True)

# Create Typer app with rich output formatting
app = typer.Typer(
    help="Sync Spotify playlists to Plex Media Server",
    add_completion=False,
)


@app.command()
def sync_lidarr_imports(
    parallel: bool = typer.Option(
        True, help="Process playlists in parallel for increased speed"
    ),
    parallel_count: int = typer.Option(
        Config.MAX_PARALLEL_PLAYLISTS,
        help="Maximum number of playlists to process in parallel"
    ),
    clear_caches: bool = typer.Option(
        False, help="Clear all caches before syncing"
    ),
) -> None:
    """Sync all playlists currently being pulled via Lidarr."""
    log_info(f"Starting Lidarr playlist sync", Symbols.SYNC)
    log_header("Synchronizing Lidarr Playlists")

    if clear_caches:
        log_info("Clearing caches before syncing...", Symbols.CACHE)
        clear_cache()
        log_success("Cache cleared before sync")

    sp_instance = sp_module.SpotifyToPlex(
        lidarr=True,
        playlist_id=None,
        parallel=parallel,
        parallel_count=parallel_count,
    )
    sp_instance.run()


@app.command()
def sync_manual_lists(
    parallel: bool = typer.Option(
        True, help="Process playlists in parallel for increased speed"
    ),
    parallel_count: int = typer.Option(
        Config.MAX_PARALLEL_PLAYLISTS,
        help="Maximum number of playlists to process in parallel"
    ),
    clear_caches: bool = typer.Option(
        False, help="Clear all caches before syncing"
    ),
) -> None:
    """Sync all playlists specified in configuration."""
    log_info(f"Starting manual playlist sync", Symbols.SYNC)
    log_header("Synchronizing Manual Playlists")

    if clear_caches:
        log_info("Clearing caches before syncing...", Symbols.CACHE)
        clear_cache()
        log_success("Cache cleared before sync")

    sp_instance = sp_module.SpotifyToPlex(
        lidarr=False,
        playlist_id=None,
        parallel=parallel,
        parallel_count=parallel_count,
    )
    sp_instance.run()


@app.command()
def sync_playlist(
    playlist_id: str = typer.Argument(..., help="Spotify playlist ID to sync"),
    clear_caches: bool = typer.Option(
        False, help="Clear all caches before syncing"
    ),
) -> None:
    """Sync a specific playlist by its Spotify ID."""
    version = get_version()
    log_info(f"Starting sync for playlist ID: {playlist_id} (commit: {version})", Symbols.SYNC)
    log_header(f"Synchronizing Playlist: {playlist_id}")

    if clear_caches:
        log_info("Clearing caches before syncing...", Symbols.CACHE)
        clear_cache()
        log_success("Cache cleared before sync")

    sp_instance = sp_module.SpotifyToPlex(lidarr=False, playlist_id=playlist_id, parallel=False)
    sp_instance.run()


@app.command()
def clear_caches() -> None:
    """Clear all cached API responses and data."""
    log_info("Clearing all caches...", Symbols.CACHE)
    clear_cache()
    log_success("All caches have been cleared")


@app.command()
def diagnose() -> None:
    """Run diagnostic checks on the Spotify and Plex connections."""
    log_header("Running Diagnostics")
    log_info("Running diagnostics", Symbols.SEARCH)

    # Check Spotify API
    log_header("Spotify API")
    try:
        log_info("Testing Spotify API connection...", Symbols.SPOTIFY)
        spotify = SpotifyClass()
        if hasattr(spotify.sp, 'me'):
            # Try a simple API call
            result = spotify.sp.search(q="test", limit=1, type="track")

        if result and result.get('tracks') and result['tracks'].get('items'):
            track_name = result['tracks']['items'][0]['name']
            artist_name = result['tracks']['items'][0]['artists'][0]['name']
            log_success("Spotify API connection successful")
            log_info(f"Found track: '{track_name}' by '{artist_name}'", Symbols.MUSIC)
            # Print nice formatted result, but avoid double-logging
            with console_lock:
                print(f"  └─ Found: \"{track_name}\" by {artist_name}")
        else:
            log_warning("Spotify API connected but returned no results")
    except Exception as e:
        log_error(f"Spotify API connection error: {e}")

    # Check Plex API
    log_header("Plex API")
    try:
        log_info("Testing Plex API connection...", Symbols.PLEX)
        plex = PlexClass()
        server_info = plex.plex.machineIdentifier

        log_success("Plex API connection successful")
        server_name = plex.plex.friendlyName
        log_info(f"Server: {server_name}", Symbols.PLEX)
        # Print nice formatted result, but avoid double-logging
        with console_lock:
            print(f"  └─ Connected to server: {server_name}")

        # Check music library
        try:
            log_info("Testing Plex Music library...", Symbols.PLEX)
            music = plex.plex.library.section("Music")
            artist_count = len(music.searchArtists(maxresults=1))
            album_count = len(music.searchAlbums(maxresults=1))
            track_count = len(music.searchTracks(maxresults=1))

            log_success("Music library accessible")
            log_info("Confirmed presence of artists, albums, and tracks", console_only=True)
            # Print nice formatted results
            with console_lock:
                print(f"  └─ Music library is accessible")
        except Exception as e:
            log_warning(f"Error accessing Plex Music library: {e}")
    except Exception as e:
        log_error(f"Plex API connection error: {e}")

    # Check cache status
    log_header("Cache Status")
    from spotify_to_plex.utils.cache import _get_cache_dir
    log_info("Checking cache files...", Symbols.CACHE)
    cache_dir = _get_cache_dir()
    cache_files = list(cache_dir.glob("*.cache"))

    log_success(f"Cache directory: {cache_dir}")
    log_info(f"{len(cache_files)} cache files found", console_only=True)
    # Print nice formatted results
    with console_lock:
        print(f"  └─ {len(cache_files)} cache files at {cache_dir}")

    # Check configuration
    log_header("Configuration")
    log_info("Validating configuration...", Symbols.CONFIG)
    warnings = Config.validate()

    if warnings:
        log_warning("Configuration warnings found:")
        with console_lock:
            for i, warning in enumerate(warnings):
                log_warning(f"- {warning}", console_only=True)
                print(f"  {i+1}. {warning}")
    else:
        log_success("Configuration valid")
        with console_lock:
            print(f"  └─ All configuration parameters are valid")

    log_header("Performance Settings")
    log_info(f"Max parallel playlists: {Config.MAX_PARALLEL_PLAYLISTS}")
    log_info(f"Caching enabled: {Config.ENABLE_CACHE}")
    log_info(f"Cache TTL: {Config.CACHE_TTL} seconds")

    # Summary with nice formatting
    log_header("Diagnostics Summary")
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_info("Diagnostics complete")
    log_info("For detailed information check the log file", console_only=True)
    log_info(f"Diagnostics completed at {now}", Symbols.FINISH, console_only=True)

    with console_lock:
        print("\n┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓")
        print(f"┃  {Symbols.FINISH} Diagnostics completed at {now} ┃")
        print(f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛")


if __name__ == "__main__":
    app()
