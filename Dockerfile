FROM python:3.11-slim-bullseye

# Set metadata labels
LABEL org.opencontainers.image.title="Spotify to Plex"
LABEL org.opencontainers.image.description="Syncs Spotify playlists to Plex Media Server"
LABEL org.opencontainers.image.source="https://github.com/lammersbjorn/spotify-to-plex"

# Set environment variables
ENV SRC_DIR="/app" \
    POETRY_VERSION="2.1.1" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    POETRY_HOME="/opt/poetry" \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    POETRY_NO_INTERACTION=1 \
    CRON_SCHEDULE="@daily" \
    DOCKER="True"

# Accept commit SHA as a build argument
# This will be automatically set by GitHub Actions during build
ARG COMMIT_SHA="unknown"
ENV COMMIT_SHA=${COMMIT_SHA}

# Create a non-root user and working directory
RUN groupadd -r appuser && useradd -r -g appuser -d ${SRC_DIR} appuser \
    && mkdir -p ${SRC_DIR} \
    && chown -R appuser:appuser ${SRC_DIR}

WORKDIR ${SRC_DIR}

# Install system dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       curl \
       wget \
       ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry
RUN curl -sSL https://install.python-poetry.org | POETRY_HOME=${POETRY_HOME} python3 - --version ${POETRY_VERSION} \
    && ln -s ${POETRY_HOME}/bin/poetry /usr/local/bin/poetry

# Install supercronic
RUN wget -O /usr/local/bin/supercronic https://github.com/aptible/supercronic/releases/download/v0.1.11/supercronic-linux-amd64 \
    && chmod +x /usr/local/bin/supercronic

# Copy configuration files first to leverage layer caching
COPY --chown=appuser:appuser pyproject.toml poetry.lock ./

# Install dependencies only - this layer will be cached unless dependencies change
RUN poetry install --no-root --without dev

# Copy application code
COPY --chown=appuser:appuser spotify_to_plex/ ./spotify_to_plex/
COPY --chown=appuser:appuser README.md ./

# Install the application
RUN poetry install --without dev

# Copy entrypoint script
COPY --chown=appuser:appuser entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/entrypoint.sh

# Log the commit SHA during the build
RUN echo "Built from commit SHA: ${COMMIT_SHA}"

# Switch to non-root user for better security
USER appuser

# Execute entrypoint script
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
