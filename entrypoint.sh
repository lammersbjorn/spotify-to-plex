#!/bin/bash
set -e

# Print environment information
echo "Starting Spotify to Plex v${COMMIT_SHA}"
echo "Running with Poetry $(poetry --version)"
echo "Using cron schedule: ${CRON_SCHEDULE}"

# Create logs directory if it doesn't exist
mkdir -p ${SRC_DIR}/logs

# Redirect cron output to a log file to avoid conflicting with stdout/stderr
LOG_DIR="${SRC_DIR}/logs"
LIDARR_LOG="${LOG_DIR}/lidarr_sync.log"
MANUAL_LOG="${LOG_DIR}/manual_sync.log"
ERROR_LOG="${LOG_DIR}/error.log"
UNAVAILABLE_LOG="${LOG_DIR}/unavailable_playlists.log"

# Create a crontab file with proper logging
echo "# Spotify to Plex sync crontab" > /tmp/crontab
echo "${CRON_SCHEDULE} cd ${SRC_DIR} && echo \"\$(date '+[%Y-%m-%d %H:%M:%S]') Starting Lidarr sync\" >> ${LIDARR_LOG} 2>&1 && poetry run spotify-to-plex sync-lidarr-imports >> ${LIDARR_LOG} 2>&1 || echo \"\$(date '+[%Y-%m-%d %H:%M:%S]') Error in Lidarr sync\" >> ${ERROR_LOG}" >> /tmp/crontab
echo "${CRON_SCHEDULE} cd ${SRC_DIR} && echo \"\$(date '+[%Y-%m-%d %H:%M:%S]') Starting manual sync\" >> ${MANUAL_LOG} 2>&1 && poetry run spotify-to-plex sync-manual-lists >> ${MANUAL_LOG} 2>&1 || echo \"\$(date '+[%Y-%m-%d %H:%M:%S]') Error in manual sync\" >> ${ERROR_LOG}" >> /tmp/crontab

# Run initial healthcheck
echo "Running healthcheck to verify connections..."
poetry run spotify-to-plex healthcheck

# Run initial sync if FIRST_RUN is enabled
if [[ "${FIRST_RUN}" == "True" || "${FIRST_RUN}" == "true" || "${FIRST_RUN}" == "1" ]]; then
    echo "Running initial sync as requested by FIRST_RUN setting"

    # Run Lidarr sync if enabled
    if [[ "${LIDARR_SYNC}" == "True" || "${LIDARR_SYNC}" == "true" || "${LIDARR_SYNC}" == "1" ]]; then
        echo "Starting Lidarr sync..."
        poetry run spotify-to-plex sync-lidarr-imports || echo "Warning: Some errors occurred during Lidarr sync. Check logs for details."
    fi

    # Run manual sync if playlists are configured
    if [[ -n "${MANUAL_PLAYLISTS}" ]]; then
        echo "Starting manual playlist sync..."
        poetry run spotify-to-plex sync-manual-lists || echo "Warning: Some errors occurred during manual sync. Check logs for details."
    fi

    # Check for any 404 errors and log unavailable playlists
    echo "Checking for unavailable playlists..."
    grep -E "Playlist .* not found \(404\)" ${LOG_DIR}/spotify_to_plex.log | sort | uniq > ${UNAVAILABLE_LOG}
    UNAVAILABLE_COUNT=$(wc -l < ${UNAVAILABLE_LOG})

    if [[ ${UNAVAILABLE_COUNT} -gt 0 ]]; then
        echo "WARNING: ${UNAVAILABLE_COUNT} playlists are unavailable or no longer exist."
        echo "Check ${UNAVAILABLE_LOG} for details, and consider updating your playlist configuration."
        echo "Note: As of November 2024, Spotify-generated playlists are no longer accessible via API."
    fi
fi

# Start the cron daemon with improved output
echo "Starting supercronic with schedule: ${CRON_SCHEDULE}"
exec supercronic -quiet /tmp/crontab
