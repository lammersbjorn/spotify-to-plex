#!/bin/bash
set -euo pipefail

# Print environment information
echo "Starting Spotify to Plex v${COMMIT_SHA:-unknown}"

if ! command -v poetry &> /dev/null; then
    echo "ERROR: Poetry is not installed or not in PATH"
    exit 1
fi

echo "Running with Poetry $(poetry --version 2>/dev/null || echo 'unknown')"
echo "Using cron schedule: ${CRON_SCHEDULE:-0 1 * * *}"

# Create directories with appropriate permissions
mkdir -p "${LOGS_DIR:-/app/logs}"
mkdir -p "${CACHE_DIR:-/cache}"

# Create a crontab file
crontab_file="/tmp/crontab"
echo "# Spotify to Plex sync crontab" > "$crontab_file"

# Add jobs to crontab with proper logging
{
    echo "${CRON_SCHEDULE:-0 1 * * *} cd \"${SRC_DIR:-/app}\" && echo \$(date '+[%Y-%m-%d %H:%M:%S]') && poetry run spotify-to-plex sync-lidarr-imports >> \"${LOGS_DIR:-/app/logs}/lidarr_sync.log\" 2>&1"
    echo "${CRON_SCHEDULE:-0 1 * * *} cd \"${SRC_DIR:-/app}\" && echo \$(date '+[%Y-%m-%d %H:%M:%S]') && poetry run spotify-to-plex sync-manual-lists >> \"${LOGS_DIR:-/app/logs}/manual_sync.log\" 2>&1"
} >> "$crontab_file"

# Run initial sync if FIRST_RUN is enabled
first_run="${FIRST_RUN:-false}"
if [[ "$first_run" =~ ^(True|true|1|yes|y|on)$ ]]; then
    echo "Running initial sync as requested by FIRST_RUN setting"

    if command -v poetry &> /dev/null; then
        if [[ "${LIDARR_SYNC:-false}" =~ ^(True|true|1|yes|y|on)$ ]]; then
            echo "Running initial Lidarr sync..."
            poetry run spotify-to-plex sync-lidarr-imports || echo "WARNING: Initial Lidarr sync failed"
        fi

        echo "Running initial manual playlists sync..."
        poetry run spotify-to-plex sync-manual-lists || echo "WARNING: Initial manual sync failed"
    else
        echo "ERROR: Cannot run initial sync - Poetry not found"
    fi
fi

# Start the cron daemon or execute provided command
if [ "$#" -eq 0 ]; then
    echo "Starting supercronic with schedule: ${CRON_SCHEDULE:-0 1 * * *}"
    if command -v supercronic &> /dev/null; then
        exec supercronic -debug "$crontab_file"
    else
        echo "ERROR: supercronic not found. Cannot start scheduled jobs."
        exit 1
    fi
else
    exec "$@"
fi
