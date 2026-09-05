# AGENTS.md — Vocalinux

Voice dictation for Linux: GTK 3 tray app (Python) plus a Next.js marketing site in `web/`. Default speech engine is **whisper.cpp** (`pywhispercpp`); OpenAI Whisper, Vosk, and a user-configured remote API are optional. Do not invent features, user counts, or privacy claims.

## Critical: git worktrees for every branch and PR

Never create a branch, commit, or open a pull request in the primary checkout. Always use a linked git worktree so the main working tree stays on `main` and stays clean. Do not `git switch` / `git checkout` a feature branch in the primary directory, and do not leave it dirty.

```bash
git fetch origin
git worktree add /tmp/vocalinux-<task> -b <type>/<short-name> origin/main

# All edits, commits, and `gh pr create` happen inside that worktree.

git worktree remove /tmp/vocalinux-<task>
git worktree prune
```

Rules:

- One worktree per branch, one branch per PR
- Place worktrees **outside** the primary working tree (`/tmp/vocalinux-<task>` or a sibling directory such as `../.worktrees/vocalinux-<task>`)
- Never run two tasks in the same worktree
- Never commit directly to `main`
- Clean up the worktree after the PR is pushed

## Toolchain

| Piece | Current |
|---|---|
| Python | `>=3.11` (`requires-python` in `pyproject.toml`; CI: 3.11–3.14). Floor, classifiers, CI matrix and `install.sh` must agree — `tests/test_python_version_policy.py` |
| GTK | GTK 3 via distro `python3-gi` (PyGObject). Never pip-install it |
| uv | `>=0.12,<0.13` (`[tool.uv]` in `pyproject.toml`). `uv.lock` is the source of truth; CI runs `uv sync --locked` / `uv run --locked`, which fails on drift |
| just | https://just.systems or distro package `just` |
| Format / lint / types | Black + isort (line length 100), flake8 (`E9,F63,F7,F82` only), mypy `src/` (targets 3.11). The three linters live in the `lint` dependency group, not the `dev` extra, so CI can install them without building the project |
| Website | Next.js / TypeScript in `web/` — see `web/AGENTS.md` |

Two virtualenvs, on purpose:

- **`.venv/`** — uv's, for dev tooling. `just deps` syncs it; every other Python `just` recipe uses `uv run --no-sync` so it does not prune extras that `just deps-all` installed. No activation needed.
- **`venv/`** — what `install.sh` builds for the app itself, from the *system* Python so distro `gi` is importable.

Never run `install.sh` from an activated `.venv`: it drops an inherited `VIRTUAL_ENV` from `PATH` and picks `$SYSTEM_PYTHON` (default `/usr/bin/python3`) precisely because a venv built from uv's interpreter cannot see distro PyGObject.

## Setup

```bash
./install.sh --dev                 # system deps + venv + editable install + tests
# non-interactive / no TTY:
./install.sh --dev --auto
./install.sh --dev --auto --no-rebuild-whispercpp   # skip cmake/Vulkan rebuild

source venv/bin/activate
```

Manual venv (must see distro `gi`):

```bash
uv venv --system-site-packages --python /usr/bin/python3
source venv/bin/activate
# exclude pygobject from uv sync/export:
#   --no-install-package pygobject / --no-emit-package pygobject
uv pip install -e ".[dev,vad]"
```

`install.sh` flags: `--engine=whisper_cpp|whisper|vosk|remote_api`, `--test`, `--skip-models`, `--venv-dir=PATH`. Default engine is `whisper_cpp`.

## Commands

```bash
just lint          # flake8 (critical) + black --check + isort --check
just format        # black + isort
just typecheck     # mypy src/
just test          # pytest -v
just test-cov      # pytest --cov=src --cov-report=html
just deps          # sync .venv with dev+vad extras and the lint group
just deps-all      # also whisper/vosk/docs; later recipes use --no-sync so they keep it
just lock          # regenerate uv.lock + requirements/*.txt
just lock-check    # fail if uv.lock is stale vs pyproject.toml
just model-checksums  # refresh pinned model digests after adding a model
just appimage      # build the AppImage in its pinned base image (needs docker)
just appimage-boot fedora:42   # boot that AppImage in a distro container
just aur-gate      # build the AUR PKGBUILD on current Arch (needs docker)
just pre-commit    # pre-commit run --all-files
just run-debug     # vocalinux --debug
just run-source-debug
```

```bash
pytest
pytest tests/test_command_processor.py
pytest tests/test_command_processor.py::TestCommandProcessor::test_initialization
pytest -m "not slow"
pytest -m "not integration"
python -m vocalinux.main --debug
```

Website: `web/AGENTS.md`, `web/PRODUCT.md`, `web/DESIGN.md`. Do not duplicate site commands here.

## Dependencies (uv)

`uv.lock` is authoritative. `just lock` regenerates it and the hash-pinned `requirements/*.txt` exports. The AppImage build installs from `runtime`/`vad` plus `appimage.txt`; `install.sh` still resolves at install time (phase 2 of #701). **Do not edit `requirements/*.txt` by hand.** Change `pyproject.toml` (or `requirements/whisper.in` for the Whisper engine, `requirements/appimage*.in` for the AppImage), run `just lock`, and commit the lock plus the exports with the manifest change.

| Constraint | Rule |
|---|---|
| PyGObject | Distro `python3-gi` only, via `--system-site-packages`. Pip install fails on Ubuntu 24.04 (`girepository-2.0`). uv-managed interpreters do not see distro `gi` unless the venv is created that way |
| `[vosk]` extra | Wheel-only on PyPI (no sdist). Never part of a source-buildable lock. `install.sh --engine=vosk` installs it |
| Whisper CPU torch | `requirements/whisper.txt` is compiled from `requirements/whisper.in`. Pin `torch`/`torchaudio` together to `+cpu` local versions — PyPI CUDA wheels win resolution regardless of index order, and torchaudio lags torch on the CPU index |
| pywhispercpp | Pinned in `install.sh` as `PYWHISPERCPP_VERSION` (keep in sync with `uv.lock`) |
| `[vad]` extra | `onnxruntime` for Silero VAD |
| AppImage PyGObject | Pinned separately in `requirements/appimage.in`, and below 3.52: the AppImage bundles its own interpreter and builds PyGObject against the base image's girepository-1.0, while uv.lock's 3.56 needs girepository-2.0 (glib 2.80+) |
| AppImage build inputs | Base image, tooling, interpreter, shaderc and the Vulkan headers are pinned in `packaging/appimage/tool_checksums.txt`. Build with `just appimage` (docker) — building on the host ships the host's glibc, which is what kept the AppImage off Debian 12 |
| AppImage boot matrix | `packaging/appimage/boot-test.sh` runs the finished AppImage in distro containers, and the matrix in `unified-pipeline.yml` must keep distros both older and newer than the build image: the old ones prove the glibc floor, the new ones catch a bundle that breaks the host binaries it spawns. A distro added there needs its package recipe in the script — `tests/test_appimage_packaging.py` checks both |
| Speech models | Verified against digests pinned in `src/vocalinux/utils/model_checksums.txt` before install, by both `install.sh` and the runtime downloaders. **Fails closed** — an unpinned model is refused. Regenerate with `just model-checksums` (never by hand); `tests/test_model_checksums.py` fails if it falls behind. whisper.cpp URLs use a pinned Hugging Face commit, never `main` |

Optional extras: `vosk`, `whisper`, `vad`, `dev`.

## Layout

```
src/vocalinux/
├── main.py, version.py, common_types.py
├── single_instance.py          # $XDG_DATA_HOME/vocalinux/instance.lock
├── auto_pause_monitor.py       # unload model while configured apps run
├── model_keepalive.py          # idle unload
├── suspend_handler.py          # logind PrepareForSleep
├── speech_recognition/
│   ├── recognition_manager.py  # whisper.cpp / Whisper / Vosk / remote
│   ├── command_processor.py    # voice commands
│   ├── dictionary_corrector.py  # custom dictionary transcript corrections
│   ├── silero_vad.py
│   └── data/                   # bundled silero_vad.onnx
├── text_injection/
│   ├── text_injector.py        # X11 / clipboard / xdotool
│   └── ibus_engine.py          # Wayland IBus injection
├── ui/
│   ├── tray_indicator.py, settings_dialog.py, first_run_dialog.py
│   ├── config_manager.py, action_handler.py, audio_feedback.py
│   ├── autostart_manager.py, keyboard_shortcuts.py
│   ├── logging_dialog.py, logging_manager.py
│   └── keyboard_backends/      # pynput (X11), evdev (Wayland)
├── utils/
│   ├── paths.py, resource_manager.py
│   ├── update_checker.py, update_monitor.py
│   └── whispercpp_model_info.py, vosk_model_info.py
└── resources/                  # SVG icons + WAV cues (also repo resources/)
```

Also: `tests/`, `docs/`, `packaging/` (AppImage, AUR, Flatpak), `scripts/`, `install.sh`, `uninstall.sh`, `web/`.

| Task | Start here |
|---|---|
| Voice command | `speech_recognition/command_processor.py` |
| Transcript corrections | `speech_recognition/dictionary_corrector.py` |
| Engine / models | `speech_recognition/recognition_manager.py` |
| Text injection | `text_injection/text_injector.py`, `ibus_engine.py` |
| Settings | `ui/config_manager.py`, `ui/settings_dialog.py` |
| Hotkeys | `ui/keyboard_shortcuts.py`, `ui/keyboard_backends/` |

## Style

- Type hints on all function signatures. `Protocol` interfaces live in `common_types.py`
- Imports: stdlib → third-party → local (`isort` black profile)
- Names: `PascalCase` classes, `snake_case` functions, `UPPER_SNAKE_CASE` constants, `_private` methods
- `logger = logging.getLogger(__name__)` per module
- Triple-quoted docstrings on modules, classes, and public functions
- Specific exceptions; log errors with context
- `subprocess` calls that run a **host** binary pass `env=host_env()` (`utils/host_process.py`): a host binary inheriting the AppImage's library paths dies on the wrong GLib. The one spawn of our own interpreter (`start_engine_process`) passes the environment untouched — it needs the bundle. `tests/test_host_process.py` walks the AST and fails on either mistake
- Tests: `tests/test_*.py`, `test_*` functions, `unittest.TestCase` or pytest; `pytest-mock` via `mocker`
- Markers: `@pytest.mark.slow`, `integration`, `audio` (hardware). Default timeout 10s (`pytest-timeout`)

## Git and PRs

Conventional Commits: `type(scope): short description` with optional body and `Fixes #123`.

Types: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`.

```
feat(commands): add "select all" voice command
fix(tray): resolve icon not updating on Wayland
docs(readme): update installation instructions
```

Branch prefixes: `feature/`, `fix/`, `docs/`, `refactor/`, `test/`, `release/` (e.g. `release/v0.7.0-beta`).

- Never push to `main`. Never commit on `main`
- Every change goes through a PR (including docs)
- Wait for CI (`.github/workflows/unified-pipeline.yml`) before asking for merge
- Squash merge
- **Do not merge the PR yourself**
- Fill `.github/PULL_REQUEST_TEMPLATE.md`

Releases: follow `docs/RELEASE_PROCESS.md`. Version source of truth is `src/vocalinux/version.py`; sync README, `docs/INSTALL.md`, `docs/UPDATE.md`, `web/src/app/page.tsx`, `web/package.json`. Prep on `release/vX.Y.Z-PHASE`; tag **after** merge.

## Website

Site-only work: `web/AGENTS.md` (commands, layout map). Product claims: `web/PRODUCT.md`. Visual system: `web/DESIGN.md`. Git/worktree/PR rules are this file — do not duplicate them under `web/`.

## Runtime (any Linux dev machine)

- Create venvs with `--system-site-packages`. Do not drop that flag
- Kill the app by PID, never `pkill -f vocalinux` (matches editors, shells, and cwd paths)
- Stale instance: `$XDG_DATA_HOME/vocalinux/instance.lock` (default `~/.local/share/vocalinux/instance.lock`)
- Default dictation shortcut: hold Right Alt (push-to-talk). Existing `~/.config/vocalinux/config.json` wins
- Headless speech smoke: `pywhispercpp.model.Model` + `CommandProcessor` (first run may download the tiny model)

Update this file when commands, layout, or agent rules change.
