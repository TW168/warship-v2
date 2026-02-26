# Dockerfile — Warship production image
#
# Uses python:3.12-slim as base and copies the uv binary from the official image
# for fast, reproducible dependency installation via uv.lock.

FROM python:3.12-slim

# Copy the uv binary from Astral's official image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Set working directory
WORKDIR /app

# Install dependencies first (layer cached unless pyproject.toml or uv.lock changes)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Copy the rest of the application source
COPY . .

# Expose the port Dokploy will route traffic to
EXPOSE 8088

# Run the production server (no hot reload, optimized for containerized environments)
CMD ["uv", "run", "fastapi", "run", "main.py", "--host", "0.0.0.0", "--port", "8088"]
