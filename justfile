# Vocalinux justfile
# Convenient commands for development
# Run `just` to list all recipes. Python tooling runs through `uv run` against
# .venv/ — run `just deps` after cloning (requires uv).
#
# Two environments, deliberately separate:
#   .venv/  dev tooling, built by uv from .python-version (3.13). `just deps`
#           pip-builds PyGObject from the lock and needs libgirepository-2.0-dev
#           (Ubuntu 24.04+). Debian 12 cannot build 3.56; use `just install-dev`.
#   venv/   what `just install` creates, always from the system Python so the
#           distro PyGObject package is importable.
#           install.sh ignores an activated .venv and rebuilds
#           venv/ if another interpreter created it, so `just install` is safe to
#           run from any shell. Override with SYSTEM_PYTHON=/usr/bin/python3.12.

# Extras and groups installed by `just deps`. `uv sync` prunes whatever the flags
# do not name — omitting `--group lint` really does uninstall the linters.
# Recipes that run tools use `uv run --no-sync` so they do not undo `just deps-all`
# (whisper/vosk/docs). They depend on `_tooling` for the same reason: with nothing
# left to create .venv/, `uv run --no-sync` on a fresh clone leaves an empty one
# behind and fails with `Failed to spawn: pytest`. CI lints with `--only-group lint`
# instead: that skips the project, whose pyaudio/PyGObject need system headers a
# lint runner has no reason to install.
DEV_EXTRAS := "--extra dev --extra vad --group lint"

# List available recipes
default:
    @just --list

# Create .venv/ and keep it matching the lock. --inexact is what makes this safe
# to run ahead of every recipe: a plain `uv sync` removes extraneous packages, so
# it would uninstall whatever `just deps-all` installed — the very thing the
# --no-sync flags below exist to prevent. `version` skips this; it reads one
# string out of version.py and needs a bare interpreter, not a sync.
[private]
_tooling:
    uv sync --inexact {{DEV_EXTRAS}}

# Install Vocalinux
install:
    ./install.sh

# Install in development mode
install-dev:
    ./install.sh --dev

# Install development dependencies into .venv/ (dev + vad extras)
deps:
    uv sync {{DEV_EXTRAS}}

# Install every optional extra — whisper/vosk engines and docs (CUDA torch, multi-GB)
deps-all:
    uv sync --all-extras --group lint

# Run test suite
test: _tooling
    @echo "Running tests..."
    uv run --no-sync pytest -v

# Run tests with coverage
test-cov: _tooling
    @echo "Running tests with coverage..."
    uv run --no-sync pytest --cov=src --cov-report=html --cov-report=term
    @echo "Coverage report generated in htmlcov/"

# Run linters (flake8, black, isort)
lint: _tooling
    @echo "Running flake8..."
    uv run --no-sync flake8 src/ tests/ --count --select=E9,F63,F7,F82 --show-source --statistics
    @echo "Checking black formatting..."
    uv run --no-sync black --check --diff src/ tests/
    @echo "Checking isort..."
    uv run --no-sync isort --check-only --diff --profile black src/ tests/

# Auto-format code (black + isort)
format: _tooling
    @echo "Formatting with black..."
    uv run --no-sync black src/ tests/
    @echo "Sorting imports with isort..."
    uv run --no-sync isort --profile black src/ tests/

# Run type checking (mypy)
typecheck: _tooling
    @echo "Running mypy..."
    uv run --no-sync mypy src/

# Build distribution packages
build:
    @echo "Building distribution packages..."
    uv build
    @echo "Built packages in dist/"

# Building on the host instead ships the host's glibc and GTK, which is how the
# published AppImage ended up unable to start on Debian 12 or Ubuntu 22.04.
#
# Build the AppImage as CI does, in the pinned base image (needs docker)
appimage: build
    bash packaging/appimage/docker-build.sh dist/*.whl "$(grep -oP '__version__\s*=\s*"\K[^"]+' src/vocalinux/version.py)" dist

# Start the built AppImage in a distro container, as the CI matrix does. Pick a
# distro older than the build image to test the glibc floor, or newer to test
# that the bundle does not break the host binaries it spawns.
#
# Boot the built AppImage on a distro, e.g. `just appimage-boot fedora:42`
appimage-boot distro="debian:12":
    docker run --rm -v "$PWD/dist:/dist:ro" -v "$PWD/packaging/appimage:/pk:ro" {{distro}} bash /pk/boot-test.sh "/dist/$(basename "$(ls dist/*.AppImage)")"

# Build the AUR package from this checkout on current Arch, as the CI gate
# does. Answers "does this commit build on Arch" — the tag tarball source= is
# swapped for a git archive of HEAD (needs docker).
#
# The checkout is mounted at its own path, and the main .git with it when this
# is a linked worktree: a worktree's .git is a pointer to a gitdir outside the
# tree, so git archive inside the container cannot see the objects without it.
aur-gate:
    #!/usr/bin/env bash
    set -euo pipefail
    COMMON="$(cd "$(git rev-parse --git-common-dir)" && pwd)"
    ARGS=(--rm -v "$PWD:$PWD:ro" -e REPO="$PWD")
    if [ "$COMMON" != "$PWD/.git" ]; then
        ARGS+=(-v "$COMMON:$COMMON:ro")
    fi
    docker run "${ARGS[@]}" archlinux:latest bash "$PWD/packaging/aur/build-test.sh"

# Regenerate uv.lock and the hash-pinned requirements/* exports.
# Bump the torch/torchaudio +cpu pins in requirements/whisper.in together
# when you want newer CPU builds (torchaudio on the CPU index lags torch).
lock:
    uv lock
    uv export --no-dev --no-emit-project --no-emit-package pygobject -o requirements/runtime.txt
    uv export --no-dev --extra vad --no-emit-project --no-emit-package pygobject -o requirements/vad.txt
    # --group lint too: the linters live in a dependency group, not in the dev
    # extra, so exporting the extra alone produced a file that reproduced
    # neither `just deps` nor what CI lints with.
    uv export --extra dev --group lint --no-emit-project --no-emit-package pygobject -o requirements/dev.txt
    uv pip compile requirements/whisper.in --generate-hashes --emit-index-url \
        --index-url https://pypi.org/simple \
        --extra-index-url https://download.pytorch.org/whl/cpu \
        --python-platform x86_64-unknown-linux-gnu -o requirements/whisper.txt
    # Compiled rather than exported: what the AppImage bundles on top of the
    # lock, and what builds it, are pinned away from uv.lock on purpose --
    # see requirements/appimage.in. --universal so one file covers both arches.
    uv pip compile requirements/appimage.in --universal --no-deps --generate-hashes \
        -o requirements/appimage.txt
    uv pip compile requirements/appimage-tools.in --universal --no-deps --generate-hashes \
        -o requirements/appimage-tools.txt

# Fail if uv.lock is stale relative to pyproject.toml
lock-check:
    uv lock --check

# Refresh the pinned model digests. whisper.cpp digests come from Hugging Face
# `lfs` metadata and cost no bandwidth; VOSK is pinned by the bytes we fetch, so
# every zip not already in the manifest is downloaded. A first run, or any run
# with --refresh, pulls ~21.9GB and takes ~30 minutes.
# Run after adding a model to vosk_model_info.py or whispercpp_model_info.py.
model-checksums: _tooling
    uv run --no-sync python scripts/generate-model-checksums.py

# Remove build artifacts
clean:
    @echo "Cleaning build artifacts..."
    rm -rf build/
    rm -rf dist/
    rm -rf *.egg-info
    rm -rf src/*.egg-info
    find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
    find . -type f -name "*.pyc" -delete
    find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
    find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
    rm -rf htmlcov/
    rm -f .coverage
    rm -f coverage.xml
    @echo "Clean complete"

# Run the installed application
run:
    vocalinux

# Run the installed application with debug logging
run-debug:
    vocalinux --debug

# Run from source
run-source: _tooling
    uv run --no-sync python -m vocalinux.main

# Run from source with debug logging
run-source-debug: _tooling
    uv run --no-sync python -m vocalinux.main --debug

# Run pre-commit hooks on all files
pre-commit: _tooling
    uv run --no-sync pre-commit run --all-files

# Print the current version
version:
    @uv run --no-sync python -c "from src.vocalinux.version import __version__; print(__version__)"
