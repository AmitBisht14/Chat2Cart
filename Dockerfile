# Toolchain image only: Node.js 20 for listener/, Python 3.12 + uv for agent/, and make.
# The source is bind-mounted by compose.yaml, so nothing from the repository is copied in.
FROM node:20-bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends make \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /usr/local/bin/

ENV UV_PYTHON_INSTALL_DIR=/opt/uv-python \
    UV_LINK_MODE=copy
RUN uv python install 3.12

WORKDIR /app
