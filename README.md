# Spotify to Plex

Spotify to Plex is a tool that automatically synchronizes your user-created Spotify playlists with your Plex Media Server. It supports:
- Parallel processing for faster playlist updates.
- Importing playlists from Lidarr or manual input.
- Preserving cover art and metadata.
- Running on Docker or as a standalone Python app.

> **Important Notice:** As of November 27, 2024, the Spotify API no longer allows access to Spotify‑generated playlists (e.g. Daily Mix, Discover Weekly). Only user‑created playlists are supported.

## Prerequisites & Dependencies

- **Spotify Developer Account:** Create an app to obtain your Client ID and Client Secret.
- **Plex Server:** Obtain your Plex token from [Plex Support](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/).
- **Lidarr (Optional):** For Lidarr playlist imports, configure the API key and URL.
- **Python 3.10+** or later.
- **Docker** (if you choose the containerized deployment).

## Installation

### 1. Docker (Recommended)

#### Using Docker Compose

1. Create a `docker-compose.yaml` file:
    ```yaml
    services:
      spotify-to-plex:
        image: ghcr.io/lammersbjorn/spotify-to-plex:latest
        container_name: spotify-to-plex
        env_file:
          - .env
        restart: unless-stopped
        volumes:
          - ./cache:/cache # Persist cache data
          - ./logs:/app/logs # Persist logs
        healthcheck:
          test: ["CMD", "poetry", "run", "spotify-to-plex", "diagnose"]
          interval: 1m
          timeout: 10s
          retries: 3
          start_period: 1m
        user: appuser
    ```

2. Create an `.env` file:
    ```bash
    curl -o .env https://raw.githubusercontent.com/lammersbjorn/spotify-to-plex/main/.env.example
    nano .env
    ```

3. Start the service:
    ```bash
    docker compose up -d
    ```

Alternatively, use these Docker commands:
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

### 2. Local Python Installation

1. Install Poetry:
    ```bash
    curl -sSL https://install.python-poetry.org | python3 -
    ```

2. Clone the repository and install dependencies:
    ```bash
    git clone https://github.com/lammersbjorn/spotify-to-plex.git
    cd spotify-to-plex
    poetry install
    ```

3. Configure the application:
    ```bash
    cp .env.example .env
    nano .env
    ```

4. Run the application help:
    ```bash
    poetry run spotify-to-plex --help
    ```

## Configuration

### Required API Access

1.  **Spotify API**

    *   Visit [Spotify Developer Dashboard](https://developer.spotify.com/dashboard/)
    *   Create a new application
    *   Copy the Client ID and Client Secret
2.  **Plex API**

    *   Get your [Plex token](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/)
    *   Note your Plex server URL (e.g., `http://localhost:32400`)
3.  **Lidarr API (Optional)**

    *   In Lidarr: Settings → General → Security
    *   Copy your API Key and server URL

### Environment Variables

| Variable                  | Description                                            | Default       | Required                         |
| :------------------------ | :----------------------------------------------------- | :------------ | :------------------------------- |
| `SPOTIFY_CLIENT_ID`       | Spotify Client ID                                      | -             | Yes                              |
| `SPOTIFY_CLIENT_SECRET`   | Spotify Client Secret                                  | -             | Yes                              |
| `PLEX_TOKEN`              | Plex authentication token                                | -             | Yes                              |
| `PLEX_SERVER_URL`         | URL of your Plex server                                | -             | Yes                              |
| `PLEX_REPLACE`            | Replace existing playlists                             | `false`       | No                               |
| `PLEX_USERS`              | Comma-separated Plex users                             | Owner account | No                               |
| `MANUAL_PLAYLISTS`        | Comma-separated Spotify playlist IDs                   | -             | Only if `LIDARR_SYNC=false`      |
| `LIDARR_API_KEY`          | Lidarr API key                                         | -             | Only if `LIDARR_SYNC=true`       |
| `LIDARR_API_URL`          | Lidarr server URL                                        | -             | Only if `LIDARR_SYNC=true`       |
| `LIDARR_SYNC`             | Enable Lidarr sync                                     | `false`       | No                               |
| `MAX_PARALLEL_PLAYLISTS`  | Maximum number of playlists to process in parallel     | `3`           | No                               |
| `FIRST_RUN`               | Run sync at container start                            | `false`       | No                               |
| `CRON_SCHEDULE`           | Schedule using cron syntax                             | `0 1 * * *`   | No                               |
| `ENABLE_CACHE`            | Enable API response caching                            | `true`        | No                               |
| `CACHE_TTL`               | Cache time-to-live in seconds                          | `3600`        | No                               |
| `CACHE_DIR`               | Custom cache directory path                            | `~/.cache/spotify-to-plex` | No                |

## Usage

### Command Line Interface

- **Sync playlists from Lidarr:**
    ```bash
    poetry run spotify-to-plex sync-lidarr-imports [--parallel/--no-parallel] [--parallel-count N] [--clear-caches]
    ```

- **Sync manually specified playlists:**
    ```bash
    poetry run spotify-to-plex sync-manual-lists [--parallel/--no-parallel] [--parallel-count N] [--clear-caches]
    ```

- **Sync a specific playlist by ID:**
    ```bash
    poetry run spotify-to-plex sync-playlist PLAYLIST_ID [--clear-caches]
    ```

- **Clear caches:**
    ```bash
    poetry run spotify-to-plex clear-caches
    ```

- **Run diagnostics:**
    ```bash
    poetry run spotify-to-plex diagnose
    ```

### Docker Commands

- **Manual sync:**
    ```bash
    docker exec spotify-to-plex poetry run spotify-to-plex sync-manual-lists
    ```

- **View logs:**
    ```bash
    docker logs spotify-to-plex
    ```

- **Updating the container:**
    ```bash
    docker pull ghcr.io/lammersbjorn/spotify-to-plex:latest
    docker rm -f spotify-to-plex
    docker run -d --name spotify-to-plex --env-file .env ghcr.io/lammersbjorn/spotify-to-plex:latest
    ```

Or, if using Docker Compose:

```bash
docker compose pull
docker compose up -d
```

## Advanced Configuration

### Playlist Management
- **Adding Tracks:** New tracks are added to existing playlists.
- **Replacing Playlists:** Set `PLEX_REPLACE=true` in your `.env` to have playlists deleted and recreated on each sync.

### Performance Tuning
- **Parallel Processing:** Adjust the `--parallel` and `--parallel-count` options.
- **Caching:** Enable caching with `ENABLE_CACHE` and adjust `CACHE_TTL` (in seconds) in your `.env` file.

### Scheduling
- Set `CRON_SCHEDULE` (default is `0 1 * * *`) in your `.env` using standard cron syntax:
  - Every 6 hours: `0 */6 * * *`
  - Every Monday at midnight: `0 0 * * 1`
  - Every 30 minutes: `*/30 * * * *`

### Docker Cache and Logs
- **Cache:** Stored under `/cache` (persisted via Docker volume).
- **Logs:** Found in `/app/logs` (configure your host paths in Docker Compose as desired).

## Troubleshooting

### Common Issues

1. **404 Not Found Errors:**
   - Verify the playlist ID is correct and the playlist is public.
   - Remember that generated playlists (e.g. Discover Weekly) are no longer available via Spotify API.

2. **No Tracks in Plex:**
   - Ensure that your music files are correctly tagged.
   - Confirm Plex has indexed your library.

3. **API Authentication Errors:**
   - Double-check your API credentials in `.env`.
   - Ensure the Spotify application has proper permissions.

4. **Processing Stalls (0%):**
   - Try using the `--no-parallel` option.
   - Run the `diagnose` command to examine connections.
   - Consider clearing caches with `clear-caches`.

### Diagnostic Tools

Run the diagnostics to verify Spotify and Plex connections, cache status, and configuration integrity:
```bash
poetry run spotify-to-plex diagnose
```

### Logs

- **Docker:** Use `docker logs spotify-to-plex`.
- **Local:** Check the log file (`spotify_to_plex.log` or logs under `/app/logs`).

## License

GPL-3.0 License — see the LICENSE file for details.

---

**Disclaimer:** This project is not affiliated with or endorsed by Spotify or Plex. Use this tool in accordance with the terms of use of each service.
