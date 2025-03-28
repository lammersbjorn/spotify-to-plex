"""Entry point for Typer application."""

import os
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
from loguru import logger

from spotify_to_plex.config import Config
from spotify_to_plex.modules.spotify_to_plex import main as sp_module
from spotify_to_plex.modules.spotify.main import SpotifyClass
from spotify_to_plex.modules.plex.main import PlexClass
from spotify_to_plex.utils.cache import clear_cache

# Configure logger
logger.remove()
logger.add("spotify_to_plex.log", rotation="12:00", level="DEBUG")
logger.debug("spotify_to_plex v{}", Config.SPOTIFY_TO_PLEX_VERSION)
logger.debug(
    "Environment variables loaded. SPOTIFY_CLIENT_ID present: {}",
    "Yes" if os.environ.get("SPOTIFY_CLIENT_ID") else "No",
)

app = typer.Typer(help="Sync Spotify playlists to Plex Media Server")


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
    logger.debug(
        "Running sync_lidarr_imports on commit: {}",
        Config.SPOTIFY_TO_PLEX_VERSION,
    )

    if clear_caches:
        clear_cache()

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
    logger.debug(
        "Running sync_manual_lists on commit: {}",
        Config.SPOTIFY_TO_PLEX_VERSION,
    )

    if clear_caches:
        clear_cache()

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
    logger.debug(
        "Running sync_playlist for ID {} on commit: {}",
        playlist_id,
        Config.SPOTIFY_TO_PLEX_VERSION,
    )

    if clear_caches:
        clear_cache()

    sp_instance = sp_module.SpotifyToPlex(lidarr=False, playlist_id=playlist_id, parallel=False)
    sp_instance.run()


@app.command()
def clear_caches() -> None:
    """Clear all cached API responses and data."""
    clear_cache()
    typer.echo("All caches have been cleared.")


@app.command()
def diagnose() -> None:
    """Run diagnostic checks on the Spotify and Plex connections."""
    typer.echo("Running diagnostics...")

    # Check Spotify API
    typer.echo("\nTesting Spotify API connection:")
    try:
        spotify = SpotifyClass()
        if hasattr(spotify.sp, 'me'):
            # Try a simple API call
            result = spotify.sp.search(q="test", limit=1, type="track")
            if result and result.get('tracks') and result['tracks'].get('items'):
                typer.echo("✅ Spotify API connection successful")
                typer.echo(f"   Found track: {result['tracks']['items'][0]['name']} by "
                          f"{result['tracks']['items'][0]['artists'][0]['name']}")
            else:
                typer.echo("⚠️  Spotify API connected but returned no results")
        else:
            typer.echo("❌ Spotify API connection failed - check your credentials")
    except Exception as e:
        typer.echo(f"❌ Spotify API connection error: {e}")

    # Check Plex API
    typer.echo("\nTesting Plex API connection:")
    try:
        plex = PlexClass()
        server_info = plex.plex.machineIdentifier
        typer.echo(f"✅ Plex API connection successful")
        typer.echo(f"   Server: {plex.plex.friendlyName}")

        # Check music library
        try:
            music = plex.plex.library.section("Music")
            artist_count = len(music.searchArtists(maxresults=1))
            album_count = len(music.searchAlbums(maxresults=1))
            track_count = len(music.searchTracks(maxresults=1))
            typer.echo(f"   Music library accessible. Found artists, albums, and tracks.")
        except Exception as e:
            typer.echo(f"⚠️  Error accessing Plex Music library: {e}")
    except Exception as e:
        typer.echo(f"❌ Plex API connection error: {e}")

    # Check cache status
    typer.echo("\nChecking cache status:")
    from spotify_to_plex.utils.cache import _get_cache_dir
    cache_dir = _get_cache_dir()
    cache_files = list(cache_dir.glob("*.cache"))
    typer.echo(f"✅ Cache directory: {cache_dir}")
    typer.echo(f"   {len(cache_files)} cache files found")

    # Check configuration
    typer.echo("\nChecking configuration:")
    warnings = Config.validate()
    if warnings:
        typer.echo("⚠️  Configuration warnings:")
        for warning in warnings:
            typer.echo(f"   - {warning}")
    else:
        typer.echo("✅ Configuration valid")

    typer.echo("\nPerformance configuration:")
    typer.echo(f"   Max parallel playlists: {Config.MAX_PARALLEL_PLAYLISTS}")
    typer.echo(f"   Caching enabled: {Config.ENABLE_CACHE}")
    typer.echo(f"   Cache TTL: {Config.CACHE_TTL} seconds")

    typer.echo("\nDiagnostics complete. If you're experiencing issues, check the log file for details.")


if __name__ == "__main__":
    app()
