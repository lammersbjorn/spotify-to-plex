"""Entry point for Typer application."""

import os
import sys
import time
import logging
from pathlib import Path
from typing import Optional
from contextlib import contextmanager

import typer
from dotenv import load_dotenv
from loguru import logger
from rich import print
from rich.console import Console

# Get the directory containing the script
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from .env file with explicit path
# Make sure dotenv is loaded before any other imports
load_dotenv(dotenv_path=os.path.join(BASE_DIR, ".env"))

# Silence the spotipy logger to avoid duplicate 404 errors
spotipy_logger = logging.getLogger('spotipy.client')
spotipy_logger.setLevel(logging.CRITICAL)  # Only show critical errors, not 404s

# Set Spotipy environment variables based on your config
if os.environ.get("SPOTIFY_CLIENT_ID"):
    os.environ["SPOTIPY_CLIENT_ID"] = os.environ["SPOTIFY_CLIENT_ID"]
if os.environ.get("SPOTIFY_CLIENT_SECRET"):
    os.environ["SPOTIPY_CLIENT_SECRET"] = os.environ["SPOTIFY_CLIENT_SECRET"]

from spotify_to_plex.config import Config
from spotify_to_plex.modules.spotify_to_plex import main as sp_module

# Create console for rich output
console = Console()

# Configure logger with rotation and retention
LOG_DIR = os.path.join(BASE_DIR, "logs")
if not os.path.exists(LOG_DIR):
    try:
        os.makedirs(LOG_DIR)
    except Exception as e:
        console.print(f"[yellow]⚠️  Warning:[/yellow] Could not create logs directory: {e}")

# Default log file
LOG_FILE = os.path.join(LOG_DIR, "spotify_to_plex.log") if os.path.exists(LOG_DIR) else "spotify_to_plex.log"

# Store the ID of our console logger for pausing
console_logger_id = None

# Get version from the environment or fallback to the Config module
# This ensures we get the correct version from GitHub Actions or Docker
VERSION = os.environ.get("COMMIT_SHA")
if not VERSION or VERSION == "unknown":
    # Try to get version from git if running locally
    try:
        import subprocess
        VERSION = subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD']).decode().strip()
    except Exception:
        # Use the version from config as last resort
        VERSION = Config.SPOTIFY_TO_PLEX_VERSION

# Function to disable stderr logging during progress bar display
@contextmanager
def pause_console_logging():
    """Temporarily disable console logging during progress bar output."""
    global console_logger_id

    if console_logger_id is not None:
        logger.remove(console_logger_id)
    try:
        yield
    finally:
        if console_logger_id is not None:
            # Restore console logging
            console_logger_id = logger.add(
                sys.stderr,
                level="INFO",
                format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>"
            )

# Configure logger
logger.remove()  # Remove default handler
logger.add(
    LOG_FILE,
    rotation="10 MB",    # Rotate when file reaches 10MB
    retention="7 days",  # Keep logs for 7 days
    compression="zip",   # Compress rotated logs
    level="DEBUG",
    backtrace=True,
    diagnose=True,
)
# Add stderr logger with a format that doesn't interfere with progress bars
console_logger_id = logger.add(
    sys.stderr,
    level="INFO",
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>"
)

logger.debug("spotify_to_plex v{}", VERSION)
logger.debug(
    "Environment variables loaded. SPOTIFY_CLIENT_ID present: {}",
    "Yes" if os.environ.get("SPOTIFY_CLIENT_ID") else "No",
)

# Create Typer app with custom help
app = typer.Typer(
    help="Sync Spotify playlists to Plex Media Server",
    add_completion=False
)

# Health check state
last_health_status = {"status": "unknown", "timestamp": 0}

@app.command()
def sync_lidarr_imports() -> None:
    """Sync all playlists currently being pulled via Lidarr."""
    logger.info(
        "Running sync_lidarr_imports on commit: {}",
        VERSION,
    )

    console.print(f"[bold green]Spotify to Plex[/bold green] v{VERSION}")
    console.print("[bold]Starting Lidarr playlist sync[/bold]")

    try:
        with pause_console_logging():
            sp_instance = sp_module.SpotifyToPlex(lidarr=True, playlist_id=None, console=console)
            sp_instance.run()
    except Exception as e:
        logger.exception(f"Unhandled error in sync_lidarr_imports: {e}")
        console.print(f"[bold red]❌ Error:[/bold red] {str(e)}")
        sys.exit(1)


@app.command()
def sync_manual_lists() -> None:
    """Sync all playlists specified in configuration."""
    logger.info(
        "Running sync_manual_lists on commit: {}",
        VERSION,
    )

    console.print(f"[bold green]Spotify to Plex[/bold green] v{VERSION}")
    console.print("[bold]Starting manual playlist sync[/bold]")

    try:
        with pause_console_logging():
            sp_instance = sp_module.SpotifyToPlex(lidarr=False, playlist_id=None, console=console)
            sp_instance.run()
    except Exception as e:
        logger.exception(f"Unhandled error in sync_manual_lists: {e}")
        console.print(f"[bold red]❌ Error:[/bold red] {str(e)}")
        sys.exit(1)


@app.command()
def sync_playlist(
    playlist_id: str = typer.Argument(..., help="Spotify playlist ID to sync"),
) -> None:
    """Sync a specific playlist by its Spotify ID."""
    logger.info(
        "Running sync_playlist for ID {} on commit: {}",
        playlist_id,
        VERSION,
    )

    console.print(f"[bold green]Spotify to Plex[/bold green] v{VERSION}")
    console.print(f"[bold]Syncing playlist ID:[/bold] {playlist_id}")

    try:
        with pause_console_logging():
            sp_instance = sp_module.SpotifyToPlex(lidarr=False, playlist_id=playlist_id, console=console)
            sp_instance.run()
    except Exception as e:
        logger.exception(f"Unhandled error in sync_playlist: {e}")
        console.print(f"[bold red]❌ Error:[/bold red] {str(e)}")
        sys.exit(1)


@app.command()
def healthcheck() -> None:
    """Verify connections to Spotify and Plex APIs."""
    global last_health_status

    # If we ran a health check recently, use cached results
    if time.time() - last_health_status["timestamp"] < 300:  # 5 minutes cache
        console.print(f"[bold]Last health check:[/bold] {last_health_status['status']}")
        return

    console.print(f"[bold green]Spotify to Plex[/bold green] v{VERSION}")
    console.print("[bold]Running health check...[/bold]")

    health_status = {"spotify": False, "plex": False}
    try:
        # Check Spotify connection
        console.print("• Checking Spotify API connection... ", end="")
        from spotify_to_plex.modules.spotify.main import SpotifyClass
        spotify = SpotifyClass()
        test_result = spotify.sp.search(q="test", limit=1, type="track")
        if test_result and test_result.get("tracks"):
            health_status["spotify"] = True
            console.print("[green]OK[/green]")
        else:
            console.print("[red]Failed[/red]")

        # Check Plex connection
        console.print("• Checking Plex API connection... ", end="")
        from spotify_to_plex.modules.plex.main import PlexClass
        plex = PlexClass()
        sections = plex.plex.library.sections()
        if sections is not None:
            health_status["plex"] = True
            console.print("[green]OK[/green]")
        else:
            console.print("[red]Failed[/red]")

        # Check configurations
        console.print("• Checking configuration... ", end="")
        warnings = Config.validate()
        if not warnings:
            console.print("[green]OK[/green]")
        else:
            console.print(f"[yellow]{len(warnings)} warnings[/yellow]")
            for warning in warnings:
                console.print(f"  - {warning}")

        # Overall status
        if health_status["spotify"] and health_status["plex"]:
            status = "[green]Healthy[/green]"
        elif health_status["spotify"] or health_status["plex"]:
            status = "[yellow]Partially Healthy[/yellow]"
        else:
            status = "[red]Unhealthy[/red]"

        console.print(f"\n[bold]Status:[/bold] {status}")

        # Update cache
        last_health_status = {
            "status": status,
            "timestamp": time.time()
        }

    except Exception as e:
        logger.exception(f"Error in healthcheck: {e}")
        console.print(f"[bold red]❌ Error:[/bold red] {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    app()
