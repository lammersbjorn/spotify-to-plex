#!/bin/bash
set -e

# Print environment information
echo "Starting Spotify to Plex v${COMMIT_SHA}"
echo "Running with Poetry $(poetry --version)"
echo "Using cron schedule: ${CRON_SCHEDULE}"

# Create logs directory if it doesn't exist
mkdir -p ${LOGS_DIR}
# Create cache directory if it doesn't exist
mkdir -p ${CACHE_DIR}
# Ensure correct permissions
chown -R appuser:appuser ${CACHE_DIR} ${LOGS_DIR}

# Create a crontab file
echo "# Spotify to Plex sync crontab" > /tmp/crontab
echo "${CRON_SCHEDULE} cd ${SRC_DIR} && echo \$(date '+[%Y-%m-%d %H:%M:%S]') && poetry run spotify-to-plex sync-lidarr-imports >> ${LOGS_DIR}/lidarr_sync.log 2>&1" >> /tmp/crontab
echo "${CRON_SCHEDULE} cd ${SRC_DIR} && echo \$(date '+[%Y-%m-%d %H:%M:%S]') && poetry run spotify-to-plex sync-manual-lists >> ${LOGS_DIR}/manual_sync.log 2>&1" >> /tmp/crontab

# Run initial sync if FIRST_RUN is enabled
if [[ "${FIRST_RUN}" == "True" || "${FIRST_RUN}" == "true" || "${FIRST_RUN}" == "1" ]]; then
    echo "Running initial sync as requested by FIRST_RUN setting"
    poetry run spotify-to-plex sync-lidarr-imports
    poetry run spotify-to-plex sync-manual-lists
fi

# Start the cron daemon
echo "Starting supercronic with schedule: ${CRON_SCHEDULE}"
exec supercronic -debug /tmp/crontab
