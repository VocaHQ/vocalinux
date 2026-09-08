# Contributing to Vocalinux

Thanks for your interest in contributing. This guide covers setup, style, testing, and pull requests.

## Code of conduct

Participation is covered by our [Code of Conduct](CODE_OF_CONDUCT.md). Be respectful and constructive.

## Ways to contribute

- **Report bugs** - [Open an issue](https://github.com/VocaHQ/vocalinux/issues/new?template=bug_report.md)
- **Suggest features** - [Feature request](https://github.com/VocaHQ/vocalinux/issues/new?template=feature_request.md) or [Discussions](https://github.com/VocaHQ/vocalinux/discussions)
- **Improve documentation** - Fixes and clarity are always useful
- **Fix bugs or add features** - Check [open issues](https://github.com/VocaHQ/vocalinux/issues), especially [`good first issue`](https://github.com/VocaHQ/vocalinux/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22)

## Development setup

### Automated (recommended)

```bash
git clone https://github.com/YOUR-USERNAME/vocalinux.git
cd vocalinux
./install.sh --dev
```

This installs system dependencies, creates a venv from the system Python, installs the package in editable mode with dev tools, and runs the test suite.

`install.sh` always builds `venv/` from the system Python (`/usr/bin/python3`, or `$SYSTEM_PYTHON`), because distro PyGObject is only importable from that interpreter. It ignores an activated virtualenv, so you can run it from a shell that still has uv's `.venv` active. See [The two environments](#the-two-environments).

### Manual setup

1. Fork and clone the repository.

2. Install system dependencies (examples):

   **Ubuntu 24.04+** (`just deps` pip-builds PyGObject 3.56 from the lock):
   ```bash
   sudo apt update
   sudo apt install -y python3-pip python3-gi python3-gi-cairo \
       gir1.2-gtk-3.0 libgirepository-2.0-dev libgirepository1.0-dev \
       python3-dev portaudio19-dev python3-venv xdotool
   ```

   **Debian 12** cannot pip-build PyGObject 3.56 (glib 2.74). Use `./install.sh --dev` for tests and running from source, then `venv/bin/pytest` / `venv/bin/python -m vocalinux.main --debug`.
   ```bash
   sudo apt install -y python3-pip python3-gi python3-gi-cairo \
       gir1.2-gtk-3.0 libgirepository1.0-dev libcairo2-dev \
       python3-dev portaudio19-dev python3-venv xdotool
   ```

   **Debian 13+:**
   ```bash
   sudo apt install -y python3-pip python3-gi python3-gi-cairo \
       gir1.2-gtk-3.0 libgirepository-2.0-dev libcairo2-dev \
       python3-dev portaudio19-dev python3-venv xdotool
   ```

   AppIndicator (system tray):
   ```bash
   # Older Ubuntu:
   sudo apt install -y gir1.2-appindicator3-0.1
   # Debian 12+ or newer Ubuntu:
   sudo apt install -y gir1.2-ayatanaappindicator3-0.1
   ```

3. Create the environment and install:

   ```bash
   # Requires uv (https://docs.astral.sh/uv/); creates .venv/ with dev + vad extras
   just deps
   ```

   `just deps` compiles PyGObject from the lock into `.venv`. That needs `libgirepository-2.0-dev` (Ubuntu 24.04+). Debian 12 cannot build it; use Option 1 and the installer `venv/` instead.

4. Run:

   ```bash
   just run-source-debug
   ```

5. Optional pre-commit hooks:

   ```bash
   uv run --no-sync pre-commit install
   ```

   Hooks are optional. CI runs the same checks.

### The two environments

The repository uses two virtual environments on purpose. Do not merge them:

| Directory | Created by | Python | Used for |
|-----------|-----------|--------|----------|
| `.venv/`  | `just deps` (uv) | pinned in `.python-version` | dev tooling: pytest, black, mypy, `just` recipes |
| `venv/`   | `./install.sh` | the system Python | running the installed app, which needs distro PyGObject |

`gi` (PyGObject) is the reason. `just deps` / `uv sync` build it from source into `.venv/`, which works wherever glib 2.80+ and `libgirepository-2.0-dev` are present (Arch, Fedora, Ubuntu 24.04 with that package, CI). Debian 12 cannot build PyGObject 3.56; use `./install.sh --dev` and `venv/bin/pytest`. `install.sh` never reuses `.venv/`: it builds `venv/` from the system Python with `--system-site-packages`, and rebuilds it if another interpreter created it. Set `SYSTEM_PYTHON=/usr/bin/python3.12 ./install.sh` on systems that ship several system interpreters.

## Making changes

### Branch naming

```bash
git checkout main
git pull origin main
git checkout -b feature/your-feature-name
# or fix/, docs/, refactor/, test/
```

Never push directly to `main`. Open a pull request for every change.

### Code style

| Tool | Role |
|------|------|
| Black | Formatting (line length 100) |
| isort | Import sorting (black profile) |
| flake8 | Linting |
| mypy | Type checking (`just typecheck`) |

```bash
just format    # black + isort
just lint      # flake8 + black --check + isort --check
just typecheck # mypy src/
```

### Project structure

```
vocalinux/
├── src/vocalinux/            # Application
│   ├── main.py
│   ├── speech_recognition/   # Engines + command processor
│   ├── text_injection/       # X11 / Wayland injection
│   ├── ui/                   # GTK tray, settings, config
│   └── utils/
├── tests/
├── resources/                # Icons and sounds
├── docs/
├── packaging/                # AppImage, AUR, Flatpak
├── snap/                     # Snap recipe
└── web/                      # Marketing site (Next.js)
```

| Task | Start here |
|------|------------|
| Voice command | `src/vocalinux/speech_recognition/command_processor.py` |
| UI | `src/vocalinux/ui/` |
| Recognition engines | `src/vocalinux/speech_recognition/recognition_manager.py` |
| Text injection | `src/vocalinux/text_injection/text_injector.py` |
| Settings / config | `src/vocalinux/ui/config_manager.py`, `settings_dialog.py` |

## Testing

```bash
just test
just test-cov
uv run --extra dev --extra vad --group lint pytest tests/test_command_processor.py
```

- Place tests in `tests/` as `test_*.py`
- Aim for solid coverage on new code (roughly 80%+)
- Use `pytest-mock` via the `mocker` fixture

```python
def test_command_processor_new_line(mocker):
    """Test that 'new line' command returns correct action."""
    processor = CommandProcessor()
    result = processor.process("new line")
    assert result.action == "new_line"
```

### Remote API test server

```bash
python scripts/test_remote_server.py
python scripts/test_remote_server.py --port 9000
python scripts/test_remote_server.py --delay 2
```

Endpoints:

- whisper.cpp style: `http://localhost:8080/inference`
- OpenAI-compatible: `http://localhost:8080/v1/audio/transcriptions`

In Settings → Speech Model, select **Remote API**, set the server URL, choose the endpoint format, and use **Test Connection**.

## Pull requests

> Automated agents may append three robot emoji (🤖) to the PR title to opt into the agent fast-track merge path when that process is active.

### Before you open a PR

- [ ] Style checks pass (`just lint`, `just typecheck`)
- [ ] Tests pass (`just test`)
- [ ] Docs updated when behavior or install steps change
- [ ] Commits use [Conventional Commits](https://www.conventionalcommits.org/)

```
type(scope): short description

Longer description if needed.

Fixes #123
```

Types: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`

Examples:

```
feat(commands): add "select all" voice command
fix(tray): resolve icon not updating on Wayland
docs(readme): update installation instructions
```

### Submit

1. Push your branch to your fork
2. Open a PR against `main` and fill out the template
3. Link related issues
4. Wait for CI; address review feedback
5. Maintainers squash-merge when approved

## Releases

Maintainers follow [docs/RELEASE_PROCESS.md](docs/RELEASE_PROCESS.md) (version files, docs, website, tag, automated publish). Do not tag releases from feature branches.

## Community

- [SUPPORT.md](SUPPORT.md) - where to get help
- [Discord](https://discord.gg/t6muquAJbm) - fastest place to talk with maintainers and other contributors
- [GitHub Discussions](https://github.com/VocaHQ/vocalinux/discussions)
- [GitHub Issues](https://github.com/VocaHQ/vocalinux/issues)
- [@vocahq on X](https://x.com/vocahq)

## License

Contributions are licensed under the [GNU Affero General Public License v3.0](LICENSE)
(AGPL-3.0), matching the other [VocaHQ](https://github.com/VocaHQ) distribution
projects ([VocaMac](https://github.com/VocaHQ/vocamac),
[VocaPhone](https://github.com/VocaHQ/vocaphone),
[VocaGateway](https://github.com/VocaHQ/vocagateway)). By opening a pull request, you
agree that your contribution may be distributed under that license.
