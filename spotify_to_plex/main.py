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
def sync_lidarr_imports() -> None:
    """Sync all playlists currently being pulled via Lidarr."""
    logger.debug(
        "Running sync_lidarr_imports on commit: {}",
        Config.SPOTIFY_TO_PLEX_VERSION,
    )
    sp_instance = sp_module.SpotifyToPlex(lidarr=True, playlist_id=None)
    sp_instance.run()


@app.command()
def sync_manual_lists() -> None:
    """Sync all playlists specified in configuration."""
    logger.debug(
        "Running sync_manual_lists on commit: {}",
        Config.SPOTIFY_TO_PLEX_VERSION,
    )
    sp_instance = sp_module.SpotifyToPlex(lidarr=False, playlist_id=None)
    sp_instance.run()


@app.command()
def sync_playlist(
    playlist_id: str = typer.Argument(..., help="Spotify playlist ID to sync"),
) -> None:
    """Sync a specific playlist by its Spotify ID."""
    logger.debug(
        "Running sync_playlist for ID {} on commit: {}",
        playlist_id,
        Config.SPOTIFY_TO_PLEX_VERSION,
    )
    sp_instance = sp_module.SpotifyToPlex(lidarr=False, playlist_id=playlist_id)
    sp_instance.run()


if __name__ == "__main__":
    app()
