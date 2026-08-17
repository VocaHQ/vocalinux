# Vocalinux justfile
# Convenient commands for development
# Run `just` to list all recipes. Python tooling (pytest, black, mypy) lives in
# venv/ — run `source venv/bin/activate` first.

# List available recipes
default:
    @just --list

# Install Vocalinux
install:
    ./install.sh

# Install in development mode
install-dev:
    ./install.sh --dev

# Run test suite
test:
    @echo "Running tests..."
    pytest -v

# Run tests with coverage
test-cov:
    @echo "Running tests with coverage..."
    pytest --cov=src --cov-report=html --cov-report=term
    @echo "Coverage report generated in htmlcov/"

# Run linters (flake8, black, isort)
lint:
    @echo "Running flake8..."
    flake8 src/ tests/ --count --select=E9,F63,F7,F82 --show-source --statistics
    @echo "Checking black formatting..."
    black --check --diff src/ tests/
    @echo "Checking isort..."
    isort --check-only --diff --profile black src/ tests/

# Auto-format code (black + isort)
format:
    @echo "Formatting with black..."
    black src/ tests/
    @echo "Sorting imports with isort..."
    isort --profile black src/ tests/

# Run type checking (mypy)
typecheck:
    @echo "Running mypy..."
    mypy src/

# Build distribution packages
build:
    @echo "Building distribution packages..."
    python -m build
    @echo "Built packages in dist/"

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
    python -m vocalinux.main

# Run from source with debug logging
run-source-debug:
    python -m vocalinux.main --debug

# Run pre-commit hooks on all files
pre-commit:
    pre-commit run --all-files

# Print the current version
version:
    @python -c "from src.vocalinux.version import __version__; print(__version__)"
