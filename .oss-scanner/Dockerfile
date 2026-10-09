# Build image for Anthropic's OSS Scanner (https://github.com/anthropics/oss-scanner).
# Mirrors the "Test Python" job in .github/workflows/unified-pipeline.yml: Ubuntu 24.04,
# the uv.lock environment with the dev and vad extras, and the pytest suite.
# The scan runs without network, so everything the tests need is installed here.
FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates git build-essential pkg-config python3-dev \
      xdotool gir1.2-appindicator3-0.1 libcairo2-dev libcairo-gobject2 \
      libgirepository1.0-dev libgirepository-2.0-dev gobject-introspection \
      gir1.2-glib-2.0 gir1.2-gtk-3.0 portaudio19-dev unzip \
    && rm -rf /var/lib/apt/lists/*

# uv minor is pinned by [tool.uv] required-version in pyproject.toml.
COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /uvx /usr/local/bin/

# scanner contract: the checkout lives inside the image, at /src
COPY . /src
WORKDIR /src

# Keep uv's managed Python inside the image and never let uv reach for the network later.
ENV UV_PYTHON_INSTALL_DIR=/opt/uv-python \
    UV_LINK_MODE=copy
RUN uv sync --locked --extra dev --extra vad

# Make the project venv the default interpreter, so `python`, `pytest` and `vocalinux` work offline.
ENV VIRTUAL_ENV=/src/.venv \
    PATH=/src/.venv/bin:$PATH \
    PYTHONPATH=/src \
    UV_OFFLINE=1 \
    UV_NO_SYNC=1
ENV GI_TYPELIB_PATH=/usr/lib/x86_64-linux-gnu/girepository-1.0:/usr/lib/aarch64-linux-gnu/girepository-1.0:/usr/lib/girepository-1.0

# Run the suite once so we know the image works; a failing test must not fail the build.
RUN python -m pytest -q -p no:cacheprovider tests/ || echo "WARNING: pytest reported failures"
