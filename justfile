# Vocalinux justfile
# Convenient commands for development
# Run `just` to list all recipes. Python tooling runs through `uv run` against
# .venv/ — run `just deps` after cloning (requires uv).
#
# Two environments, deliberately separate:
#   .venv/  dev tooling, built by uv from .python-version (3.13).
#   venv/   what `just install` creates, always from the system Python — on
#           distros where PyGObject cannot be pip-built (Ubuntu 24.04, Debian)
#           the distro package is importable only from that interpreter.
#           install.sh ignores an activated .venv and rebuilds
#           venv/ if another interpreter created it, so `just install` is safe to
#           run from any shell. Override with SYSTEM_PYTHON=/usr/bin/python3.12.

# Extras and groups installed by `just deps` and requested by every recipe below.
# `uv run` syncs the environment exactly, so tooling recipes must ask for the
# same set or the dev tools would be uninstalled. CI lints with
# `--only-group lint` instead: that skips the project, whose pyaudio/PyGObject
# need system headers a lint runner has no reason to install.
DEV_EXTRAS := "--extra dev --extra vad --group lint"

# List available recipes
default:
    @just --list

# Install Vocalinux
install:
    ./install.sh

# Install in development mode
install-dev:
    ./install.sh --dev

# Install development dependencies into .venv/ (dev + vad extras)
deps:
    uv sync --extra dev --extra vad --group lint

# Install every optional extra — whisper/vosk engines and docs (CUDA torch, multi-GB)
deps-all:
    uv sync --all-extras

# Run test suite
test:
    @echo "Running tests..."
    uv run {{DEV_EXTRAS}} pytest -v

# Run tests with coverage
test-cov:
    @echo "Running tests with coverage..."
    uv run {{DEV_EXTRAS}} pytest --cov=src --cov-report=html --cov-report=term
    @echo "Coverage report generated in htmlcov/"

# Run linters (flake8, black, isort)
lint:
    @echo "Running flake8..."
    uv run {{DEV_EXTRAS}} flake8 src/ tests/ --count --select=E9,F63,F7,F82 --show-source --statistics
    @echo "Checking black formatting..."
    uv run {{DEV_EXTRAS}} black --check --diff src/ tests/
    @echo "Checking isort..."
    uv run {{DEV_EXTRAS}} isort --check-only --diff --profile black src/ tests/

# Auto-format code (black + isort)
format:
    @echo "Formatting with black..."
    uv run {{DEV_EXTRAS}} black src/ tests/
    @echo "Sorting imports with isort..."
    uv run {{DEV_EXTRAS}} isort --profile black src/ tests/

# Run type checking (mypy)
typecheck:
    @echo "Running mypy..."
    uv run {{DEV_EXTRAS}} mypy src/

# Build distribution packages
build:
    @echo "Building distribution packages..."
    uv build
    @echo "Built packages in dist/"

# Regenerate uv.lock and the hash-pinned requirements/* exports.
# Bump the torch/torchaudio +cpu pins in requirements/whisper.in together
# when you want newer CPU builds (torchaudio on the CPU index lags torch).
lock:
    uv lock
    uv export --no-dev --no-emit-project --no-emit-package pygobject -o requirements/runtime.txt
    uv export --no-dev --extra vad --no-emit-project --no-emit-package pygobject -o requirements/vad.txt
    uv export --extra dev --no-emit-project --no-emit-package pygobject -o requirements/dev.txt
    uv pip compile requirements/whisper.in --generate-hashes --emit-index-url \
        --index-url https://pypi.org/simple \
        --extra-index-url https://download.pytorch.org/whl/cpu \
        --python-platform x86_64-unknown-linux-gnu -o requirements/whisper.txt

# Fail if uv.lock is stale relative to pyproject.toml
lock-check:
    uv lock --check

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
run-source:
    uv run {{DEV_EXTRAS}} python -m vocalinux.main

# Run from source with debug logging
run-source-debug:
    uv run {{DEV_EXTRAS}} python -m vocalinux.main --debug

# Run pre-commit hooks on all files
pre-commit:
    uv run {{DEV_EXTRAS}} pre-commit run --all-files

# Print the current version
version:
    @uv run --no-sync python -c "from src.vocalinux.version import __version__; print(__version__)"
