# Spotify to Plex

[![Docker Build](https://github.com/lammersbjorn/spotify-to-plex/actions/workflows/docker-image.yml/badge.svg)](https://github.com/lammersbjorn/spotify-to-plex/actions/workflows/docker-image.yml)

Synchronize Spotify playlists to your Plex Media Server automatically.

> **Important Notice:** As of November 27, 2024, Spotify API no longer allows access to Spotify-generated playlists, including Daily Mix, Discover Weekly, and other Spotify-owned content. See [Spotify's announcement](https://developer.spotify.com/blog/2024-11-27-changes-to-the-web-api) for details. User-created playlists remain fully accessible.

## Features

- Sync Spotify playlists to Plex for multiple users
- Import playlists from Lidarr or specify them manually
- Preserve Spotify playlist cover art
- Scheduled automatic synchronization
- Parallel processing for improved performance
- Docker support for easy deployment

## Installation

### Docker (Recommended)

```bash
# Pull the latest image
docker pull ghcr.io/lammersbjorn/spotify-to-plex:latest

# Create a configuration file
curl -o .env https://raw.githubusercontent.com/lammersbjorn/spotify-to-plex/main/.env.example

# Edit the configuration file
nano .env

# Run the container
docker run -d --name spotify-to-plex --env-file .env ghcr.io/lammersbjorn/spotify-to-plex:latest
```

### Python Installation

```bash
# Install Poetry
curl -sSL https://install.python-poetry.org | python3 -

# Clone repository
git clone https://github.com/lammersbjorn/spotify-to-plex.git
cd spotify-to-plex

# Install dependencies
poetry install

# Configure
cp .env.example .env
nano .env

# Run
poetry run spotify-to-plex --help
```

## Configuration

### Required API Access

1. **Spotify API**
   - Visit [Spotify Developer Dashboard](https://developer.spotify.com/dashboard/)
   - Create a new application
   - Copy the Client ID and Client Secret

2. **Plex API**
   - Get your [Plex token](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/)
   - Note your Plex server URL (e.g., `http://localhost:32400`)

3. **Lidarr API (Optional)**
   - In Lidarr: Settings → General → Security
   - Copy your API Key and server URL

### Environment Variables

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `SPOTIFY_CLIENT_ID` | Spotify Client ID | - | Yes |
| `SPOTIFY_CLIENT_SECRET` | Spotify Client Secret | - | Yes |
| `PLEX_TOKEN` | Plex authentication token | - | Yes |
| `PLEX_SERVER_URL` | URL of your Plex server | - | Yes |
| `PLEX_REPLACE` | Replace existing playlists | `false` | No |
| `PLEX_USERS` | Comma-separated Plex users | Owner account | No |
| `MANUAL_PLAYLISTS` | Comma-separated Spotify playlist IDs | - | Only if `LIDARR_SYNC=false` |
| `LIDARR_API_KEY` | Lidarr API key | - | Only if `LIDARR_SYNC=true` |
| `LIDARR_API_URL` | Lidarr server URL | - | Only if `LIDARR_SYNC=true` |
| `LIDARR_SYNC` | Enable Lidarr sync | `false` | No |
| `WORKER_COUNT` | Concurrent threads | `10` | No |
| `SECONDS_INTERVAL` | Sleep interval (seconds) | `60` | No |
| `FIRST_RUN` | Run sync at container start | `false` | No |
| `CRON_SCHEDULE` | Schedule using cron syntax | `0 1 * * *` | No |

## Usage

### Command Line Interface

```bash
# Sync playlists from Lidarr
poetry run spotify-to-plex sync-lidarr-imports

# Sync manually specified playlists
poetry run spotify-to-plex sync-manual-lists

# Sync a specific playlist by ID
poetry run spotify-to-plex sync-playlist 37i9dQZEVXcJZyENOWUFo7

# Show help
poetry run spotify-to-plex --help
```

### Docker Commands

```bash
# Run manual sync
docker exec spotify-to-plex poetry run spotify-to-plex sync-manual-lists

# View logs
docker logs spotify-to-plex

# Update container
docker pull ghcr.io/lammersbjorn/spotify-to-plex:latest
docker rm -f spotify-to-plex
docker run -d --name spotify-to-plex --env-file .env ghcr.io/lammersbjorn/spotify-to-plex:latest
```

## Advanced Configuration

### Playlist Management

- **Adding tracks**: By default, new tracks are added to existing playlists
- **Replacing playlists**: Set `PLEX_REPLACE=true` to delete and recreate playlists on each sync

### Scheduling

Set `CRON_SCHEDULE` using [crontab syntax](https://crontab.guru/):
- Every 6 hours: `0 */6 * * *`
- Every Monday at midnight: `0 0 * * 1`
- Every 30 minutes: `*/30 * * * *`

## Troubleshooting

### Common Issues

1. **404 Not Found Errors**
   - This usually means the playlist no longer exists or is inaccessible
   - Check if the playlist ID is correct and still public/accessible
   - For Spotify-generated playlists, see the important notice about API changes

2. **No tracks found in Plex**
   - Ensure music files are properly tagged with correct metadata
   - Verify Plex has indexed your music library

3. **API Authentication Errors**
   - Check your API credentials in the `.env` file
   - Ensure the Spotify application has the necessary permissions

### Logs

- Docker: `docker logs spotify-to-plex`
- Python: Check `spotify_to_plex.log` in the application directory

### Code Quality

```bash
# Run tests
poetry run pytest

# Lint and format
poetry run ruff check .
poetry run ruff format .
```

## License

GPL-3.0 License - see the LICENSE file for details.

---

**Disclaimer**: This project is not affiliated with or endorsed by Spotify or Plex. Use in accordance with both services' terms of use.