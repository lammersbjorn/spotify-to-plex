##############################
# Stage 1: Builder
##############################
FROM python:3.13-slim AS builder

# Set environment variables for building
ENV SRC_DIR="/app" \
    POETRY_VERSION="2.1.1" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    POETRY_HOME="/opt/poetry" \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    POETRY_NO_INTERACTION=1 \
    CACHE_DIR="/cache" \
    LOGS_DIR="/app/logs"

# Create non-root user and working directory
RUN groupadd -r appuser && useradd -r -g appuser -d ${SRC_DIR} appuser \
    && mkdir -p ${SRC_DIR} ${CACHE_DIR} ${LOGS_DIR}
WORKDIR ${SRC_DIR}

# Install system and build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
       curl wget ca-certificates build-essential cargo \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry
RUN curl -sSL https://install.python-poetry.org | POETRY_HOME=${POETRY_HOME} python3 - --version ${POETRY_VERSION} \
    && ln -s ${POETRY_HOME}/bin/poetry /usr/local/bin/poetry

# Copy dependency files and install production dependencies only
COPY --chown=appuser:appuser pyproject.toml poetry.lock ./
RUN poetry install --no-root --only=main

# Copy application code and entrypoint script
COPY --chown=appuser:appuser spotify_to_plex/ ./spotify_to_plex/
COPY --chown=appuser:appuser README.md ./
COPY --chown=appuser:appuser entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/entrypoint.sh

##############################
# Stage 2: Final Image
##############################
FROM python:3.13-slim

# Build arguments
ARG COMMIT_SHA="dev"
ENV COMMIT_SHA=${COMMIT_SHA}

# Set environment variables for runtime
ENV SRC_DIR="/app" \
    CACHE_DIR="/cache" \
    LOGS_DIR="/app/logs" \
    CRON_SCHEDULE="0 1 * * *" \
    FIRST_RUN="false" \
    PYTHONUNBUFFERED=1
COPY --from=builder /opt/poetry /opt/poetry
ENV PATH="/opt/poetry/bin:$PATH"

# Install supercronic for scheduled tasks
ENV SUPERCRONIC_URL=https://github.com/aptible/supercronic/releases/download/v0.2.33/supercronic-linux-amd64

RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates wget \
    && wget -q "$SUPERCRONIC_URL" -O /usr/local/bin/supercronic \
    && chmod +x /usr/local/bin/supercronic \
    && apt-get remove -y wget \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user and working directory
RUN groupadd -r appuser && useradd -r -g appuser -d ${SRC_DIR} appuser \
    && mkdir -p ${SRC_DIR} ${CACHE_DIR} ${LOGS_DIR} \
    && chown -R appuser:appuser ${SRC_DIR} ${CACHE_DIR} ${LOGS_DIR}

WORKDIR ${SRC_DIR}

# Copy built application from builder stage
COPY --from=builder ${SRC_DIR} ${SRC_DIR}
COPY --from=builder /usr/local/bin/entrypoint.sh /usr/local/bin/entrypoint.sh

# Define volume mount points
VOLUME ["${CACHE_DIR}", "${LOGS_DIR}"]

# Set up healthcheck
HEALTHCHECK --interval=60s --timeout=10s --start-period=60s --retries=3 \
  CMD poetry run spotify-to-plex diagnose > /dev/null || exit 1

# Switch to non-root user
USER appuser

# Execute entrypoint script
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
