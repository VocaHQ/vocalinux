# AGENTS.md - Vocalinux

Guidelines for AI agents working on this codebase.

## Project Overview

Vocalinux is a voice dictation system for Linux. It uses:
- **Python 3.9+** for the main application
- **GTK 3** (via PyGObject) for the desktop UI and system tray
- **whisper.cpp** (default), **OpenAI Whisper**, and **Vosk** for speech recognition
- **Next.js/TypeScript** for the website (in `web/`)

### Key Dependencies
- `pywhispercpp` - Python bindings for whisper.cpp (default engine)
- `vosk` - Lightweight speech recognition (optional, `[vosk]` extra)
- `pyaudio` - Audio capture
- `PyGObject` - GTK integration (distro `python3-gi` only — never pip; see Dependency Management)
- `psutil` - Process utilities (required by pywhispercpp)

## Build & Test Commands

### Python

```bash
# Install in development mode
./install.sh --dev
# Or manually:
pip install -e ".[dev]"

# Dependency lock files (see "Dependency Management" below)
just lock          # regenerate uv.lock + requirements/*.txt after changing deps
just lock-check    # fail if uv.lock is stale relative to pyproject.toml

# Run all tests
pytest

# Run a single test file
pytest tests/test_command_processor.py

# Run a single test function
pytest tests/test_command_processor.py::TestCommandProcessor::test_initialization

# Run tests with verbose output
pytest -v

# Run tests with coverage
pytest --cov=src --cov-report=html

# Run tests excluding slow/integration tests
pytest -m "not slow"
pytest -m "not integration"

# Lint (check only)
just lint
# Or manually:
flake8 src/ tests/ --select=E9,F63,F7,F82
black --check --diff src/ tests/
isort --check-only --diff --profile black src/ tests/

# Auto-format code
just format
# Or manually:
black src/ tests/
isort --profile black src/ tests/

# Type checking
just typecheck
# Or: mypy src/

# Run the application
vocalinux --debug
# Or from source: python -m vocalinux.main --debug
```

### Website (Next.js)

Website-specific agent notes, product truth, and design system live under `web/`:

- `web/AGENTS.md` — commands and layout map
- `web/PRODUCT.md` — product claims / audience for the site
- `web/DESIGN.md` — visual system for marketing UI

```bash
cd web
npm install
npm run dev      # Development server
npm run build    # Production build
npm run lint     # ESLint
npm run test     # Jest tests
```

## Dependency Management (uv + lockfiles)

All dependency versions are pinned. The source of truth is `uv.lock`; the
`requirements/*.txt` files are generated hash-pinned exports consumed by `install.sh`,
the AppImage build, and CI. **Never edit `requirements/*.txt` by hand** — change
`pyproject.toml` (or `requirements/whisper.in` for the whisper engine), run `just lock`,
and commit the result together with the manifest change. uv itself is version-pinned
via `[tool.uv]` in `pyproject.toml`.

- **PyGObject always comes from the distro** (`python3-gi` through a
  `--system-site-packages` venv). It cannot be pip-installed on Ubuntu 24.04, and
  uv-managed interpreters do not see the distro gi — create venvs with
  `uv venv --system-site-packages --python /usr/bin/python3`, and exclude the package
  in uv sync/export (`--no-install-package pygobject` / `--no-emit-package pygobject`).
- **vosk** is the optional `[vosk]` extra. It is wheel-only on PyPI (no sdist), so it
  can never be part of a source-buildable lock. `install.sh --engine=vosk` installs it.
- **Whisper engine (CPU torch)**: `requirements/whisper.txt` is compiled from
  `requirements/whisper.in`, where `torch`/`torchaudio` are pinned together to `+cpu`
  local versions — PyPI's CUDA-bundled wheels win resolution over the CPU index
  regardless of index order, and torchaudio lags torch on the CPU index. Bump the pair
  together.
- **pywhispercpp**: pinned in `install.sh` via `PYWHISPERCPP_VERSION` — keep it in sync
  with `uv.lock` when bumping.
- Background, phase checklists, and open work: `docs/PACKAGING_PLAN.md`, epic #701.

## Code Style Guidelines

### Formatting

- **Line length**: 100 characters
- **Formatter**: Black
- **Import sorter**: isort (black-compatible profile)
- **Linter**: flake8

### Import Order

Use isort with black profile. Imports should be grouped:
1. Standard library (`import os`, `from typing import ...`)
2. Third-party packages (`import gi`, `from vosk import Model`)
3. Local imports (`from vocalinux.common_types import ...`)

### Type Hints

Use type hints for all function signatures. Use `Protocol` for interfaces (see `common_types.py`).

### Naming Conventions

- **Classes**: `PascalCase` (e.g., `CommandProcessor`, `ConfigManager`)
- **Functions/methods**: `snake_case` (e.g., `process_text`, `load_config`)
- **Constants**: `UPPER_SNAKE_CASE` (e.g., `CONFIG_DIR`, `DEFAULT_CONFIG`)
- **Private methods**: `_leading_underscore` (e.g., `_compile_patterns`)
- **Module-level logger**: `logger = logging.getLogger(__name__)`

### Docstrings

Use triple-quoted docstrings for modules, classes, and public functions:

```python
"""Configuration manager for Vocalinux."""

class ConfigManager:
    """Manager for user configuration settings."""

    def load_config(self):
        """Load configuration from the config file."""
```

### Error Handling

Use specific exception types, log errors with context:

```python
try:
    with open(CONFIG_FILE, "r") as f:
        user_config = json.load(f)
except json.JSONDecodeError as e:
    logger.error(f"Invalid JSON in config file: {e}")
```

### Logging

Each module should have its own logger:

```python
import logging
logger = logging.getLogger(__name__)
```

## Testing Guidelines

- Place tests in `tests/` directory
- Name test files as `test_*.py`, functions as `test_*`
- Use `unittest.TestCase` or plain pytest functions
- Use `pytest-mock` for mocking (via `mocker` fixture)

### Test Markers

```python
@pytest.mark.slow          # Long-running tests
@pytest.mark.integration   # Integration tests
@pytest.mark.audio         # Requires audio hardware
```

## Project Structure

```
src/vocalinux/
├── main.py                    # Application entry point
├── version.py                 # Version info
├── common_types.py            # Shared types/enums/protocols
├── speech_recognition/
│   ├── recognition_manager.py # VOSK/Whisper/whisper.cpp management
│   └── command_processor.py   # Voice command processing
├── text_injection/
│   └── text_injector.py       # X11/Wayland text injection
├── ui/
│   ├── tray_indicator.py      # System tray icon
│   ├── settings_dialog.py     # Settings GUI
│   ├── config_manager.py      # Configuration handling
│   └── keyboard_backends/     # Keyboard input handling
└── utils/
    ├── resource_manager.py    # Resource utilities
    ├── whispercpp_model_info.py   # whisper.cpp model metadata & hardware detection
    └── vosk_model_info.py         # VOSK model metadata
```

## Release Process

See `docs/RELEASE_PROCESS.md` for detailed release instructions.

Quick summary:
1. Update version in `src/vocalinux/version.py`
2. Update version references in README.md, docs/INSTALL.md, docs/UPDATE.md
3. Update web/src/app/page.tsx and web/package.json
4. Run `just lint` to verify code quality
5. Create branch `release/vX.Y.Z-PHASE`
6. Commit with `chore(release): prepare vX.Y.Z-PHASE`
7. Push and create PR
8. After merge, create and push tag: `git tag -a vX.Y.Z-PHASE -m "Release X.Y.Z-PHASE"`
9. GitHub Actions will build and publish automatically

## Commit Message Format

Follow Conventional Commits:

```
type(scope): short description

Longer description if needed.

Fixes #123
```

**Types**: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`

**Examples**:
```
feat(commands): add "select all" voice command
fix(tray): resolve icon not updating on Wayland
docs(readme): update installation instructions
```

## Branch Naming

- `feature/` - New features
- `fix/` - Bug fixes
- `docs/` - Documentation updates
- `refactor/` - Code refactoring
- `test/` - Test additions/updates
- `release/` - Release preparation (e.g., `release/v0.7.0-beta`)

## Important Rules

- **Never push directly to `main`** - Always create a branch and PR
- **All changes require a PR** - Even small fixes and documentation updates
- **Wait for CI to pass** before merging PRs
- **Squash merge** PRs to keep history clean

## Cursor Cloud specific instructions

The startup update script keeps a Python venv (`venv/`) and `web/node_modules` in sync. Standard commands live in the sections above and in `web/AGENTS.md`; notes below are the non-obvious gotchas for this environment.

- **Activate the venv first.** Python tooling (`vocalinux`, `pytest`, `just lint`, `mypy`) lives in `venv/`. Run `source venv/bin/activate` (or prefix with `./venv/bin/`) before use.
- **The startup venv sync can strip dev extras.** If `pytest`/`black` suddenly vanish from `venv/`, the update script recreated a minimal venv — restore with `uv pip install -e ".[dev,vad]" --python ./venv/bin/python`. `uv` itself lives at `~/.local/bin/uv` (not always on `PATH` in non-interactive shells).
- **The venv must be created with `--system-site-packages`.** GTK/`PyGObject` come from the apt package `python3-gi`; installing `PyGObject` from pip fails on Ubuntu 24.04 because the pinned version needs `girepository-2.0` (glib 2.80+), which the distro doesn't ship. The update script already creates the venv this way — don't drop that flag.
- **`black --check` prints a Python-version warning.** `pyproject.toml` targets py314 but the VM runs Python 3.12; Black still reports "All done" and lint passes. This warning is benign.
- **Desktop app is a GTK tray app.** An XFCE session (`xfwm4` + `xfce4-panel`) runs on `DISPLAY=:1`. Always give the app the session env: `DISPLAY=:1`, `DBUS_SESSION_BUS_ADDRESS=autolaunch:`, `XDG_RUNTIME_DIR=/run/user/1000`, `XDG_CURRENT_DESKTOP=XFCE`. Single-instance lock lives at `~/.local/share/vocalinux/instance.lock`; delete it after killing a stale instance. Kill instances by explicit PID (never `pkill -f`).
- **Pre-installed agent skills (not committed to the repo).** The `humanizer` and `ponytail` skills live in this VM at `~/.cursor/skills/<name>/SKILL.md` (user-level, baked into the environment snapshot), so Cursor auto-discovers them for every session on this repo without adding them to git.

### Running / using the desktop GUI end-to-end in the VM

Convenience: this VM has an idempotent bring-up script at `~/.local/bin/vocalinux-gui-env.sh` (installed in the environment, not committed to the repo) that performs both steps below — run it once per boot, then launch the app. The manual steps are documented here as the source of truth in case the script is unavailable.

Two things are missing from the base session and must be set up once per boot (packages already installed; these are runtime/session steps, not for the update script):

1. **System tray (StatusNotifierWatcher).** The panel ships no tray by default, so the AppIndicator icon can't appear. Add the `systray` plugin and (re)start the panel: `xfconf-query -c xfce4-panel -p /plugins/plugin-6 -t string -s systray --create`, append `6` to `/panels/panel-1/plugin-ids`, then start the panel detached (`setsid bash -c xfce4-panel …`). Verify `org.kde.StatusNotifierWatcher` is on the session bus before launching the app. Keep the systray `size-max` unset or a sane value (e.g. 22); `size-max=0` renders zero-sized (invisible) icons.
   - **AppIndicator + SVG icons must both be present or the icon shows blank.** The GI runtime comes from `gir1.2-ayatanaappindicator3-0.1` (+ `gir1.2-notify-0.7`). VocaLinux's tray/app icons are SVG, so `librsvg2-common` (the gdk-pixbuf SVG loader) is required — without it the icon registers on the bus but renders empty and the panel logs `gdk-pixbuf does not provide SVG support`. `scripts/check-system-deps.sh` should report `✓ AppIndicator/Ayatana GI runtime` and `✓ All critical dependencies found!`.
2. **Virtual microphone (no audio server by default).** Create `/run/user/1000` (chown to your uid), start PulseAudio (`pulseaudio --start --exit-idle-time=-1`), then `pactl load-module module-null-sink sink_name=virtmic` + `module-virtual-source source_name=virtmic_src master=virtmic.monitor`, `pactl set-default-source virtmic_src`, and write `~/.asoundrc` with `pcm.!default pulse` / `ctl.!default pulse` so PyAudio sees an input device. Feed speech in with `paplay --device=virtmic <file.wav>`.

Also set `audio.device_index` to `null` in `~/.config/vocalinux/config.json` (a stale index prevents opening the stream).

**Dictation control is Right-Alt hold by default and stateful for toggle mode.** Default activation is hold `Right Alt` (Option) in push-to-talk mode (`shortcuts` in the config). Existing installs keep whatever is already saved in `~/.config/vocalinux/config.json`. The app catches synthetic X key events (`xdotool key Alt_R`), so it can be driven from a script. For push-to-talk: focus the target window → hold Right Alt → `paplay` the wav → release Right Alt → wait for whisper.cpp transcription + xdotool injection into the focused window. If testing toggle mode instead, launch a fresh (idle) app instance; toggle state persists across dictations, and any stray configured key tap will flip recording.

- **Headless-only speech check (no GUI/audio setup):** drive the pipeline programmatically — transcribe with `from pywhispercpp.model import Model` and format via `vocalinux.speech_recognition.command_processor.CommandProcessor`. The first transcription downloads the ~74MB whisper.cpp `tiny` model (needs network); it is cached afterward.
- **Website dev server:** `cd web && npm run dev -- -H 0.0.0.0 -p 3456` (per `web/AGENTS.md`). Lint currently reports 3 pre-existing `@next/next/no-html-link-for-pages` errors in `src/components/seo-subpage-shell.tsx`; typecheck, tests, and build are clean.
- **Running `install.sh` here:** use `./install.sh --dev --auto` — `--auto` forces non-interactive mode (the Shell has no TTY) and it reuses the existing `venv/`. It also runs the full `pytest` suite and installs a wrapper at `~/.local/bin/vocalinux` (that dir is not on `PATH`; call the wrapper by full path or add it). Pass `--no-rebuild-whispercpp` to skip the lengthy cmake/Vulkan rebuild and reuse the pip-installed `pywhispercpp`.
