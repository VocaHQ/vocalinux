# Installation guide

How to install Vocalinux on Linux. Short overview: [project README](../README.md).

| Path | When to use |
|------|-------------|
| [Recommended installer](#recommended-installer) | Most users |
| [AppImage](#appimage) | Portable binary; no system package install |
| [Distro packages (.deb / .rpm)](#distro-packages-deb--rpm) | Debian 12+, Ubuntu 24.04+, Fedora |
| [AUR](#arch-linux-aur) | Arch / Manjaro |
| [Flatpak](#flatpak) | Release `.flatpak` or local build |
| [Snap](#snap-ubuntu-snap-store) | Ubuntu Snap Store (`--edge`) or GitHub `.snap` |
| [From source](#from-source) | Contributors or custom trees |
| [Manual / PyPI](INSTALL_MANUAL.md) | Full control or pip-only workflows |
| [Troubleshooting](TROUBLESHOOTING.md) | Tray, audio, injection, models |

## Recommended installer

Download, review if you like, then run:

```bash
curl -fsSL https://raw.githubusercontent.com/VocaHQ/vocalinux/main/install.sh -o /tmp/vl.sh
bash /tmp/vl.sh
```

Installs the latest release with **whisper.cpp** by default. For a pinned version, see [GitHub Releases](https://github.com/VocaHQ/vocalinux/releases) or pass `--tag=...`.

The installer:

- Installs whisper.cpp (typically ~1-2 minutes; no full PyTorch stack)
- Detects GPU / Vulkan (AMD, Intel, NVIDIA)
- Installs neural VAD when ONNX Runtime is available
- Downloads the default whisper.cpp tiny model (~74MB), verified against pinned checksums
- Sets up desktop integration and launch wrappers

The source installer uses committed, hash-verified Python dependency exports,
including its pip and source-build tools. GTK/PyGObject still comes from your
distribution, and the venv retains access to system packages. A missing export
or unavailable pinned package causes that installation step to fail; the
existing optional-engine and VAD fallbacks still apply.

Remote installs run the installer from the selected release tag. Older tags
therefore retain their original dependency-install behavior; downloading a new
bootstrap script does not change an older release's pins.

### Installer modes

```bash
./install.sh                              # Interactive (recommended)
./install.sh --auto                       # Defaults: whisper.cpp
./install.sh --auto --engine=whisper      # OpenAI Whisper
./install.sh --auto --engine=faster_whisper  # Faster Whisper (CPU)
./install.sh --auto --engine=vosk         # VOSK only
./install.sh --auto --engine=parakeet     # Parakeet (CPU)
./install.sh --auto --engine=remote_api   # Remote HTTP API
./install.sh --dev                        # Editable install + test tools
./install.sh --help                       # Full flag list
```

| Engine | When to use | Typical install |
|--------|-------------|-----------------|
| **whisper.cpp** (default) | Best default; Vulkan GPU | ~1-2 min, ~74MB model |
| **Whisper** (OpenAI) | PyTorch / CUDA | ~5-10 min, large download |
| **Faster Whisper** | CPU Whisper via CTranslate2 / INT8 | Model sizes like OpenAI Whisper |
| **VOSK** | Low RAM / minimal | ~30 sec, ~40MB |
| **Parakeet** | CPU; 25 European languages | Model ~639MB |
| **Remote API** | User-configured HTTP server | No local model |

Useful flags: `--tag=TAG`, `--skip-models`, `--rebuild-whispercpp`, `--no-rebuild-whispercpp`, `--venv-dir=PATH`, `--test`.

`--engine=NAME` accepts `whisper_cpp` (default), `whisper`, `faster_whisper`, `vosk`, `parakeet`, `remote_api`.

### What the installer does

1. Detects the distribution and installs system packages
2. Creates a Python venv from the system interpreter with `--system-site-packages` (for distro GTK / PyGObject)
3. Installs Vocalinux and the chosen speech engine
4. Optionally installs neural VAD (`onnxruntime`)
5. Downloads a default speech model (checksum-verified)
6. Installs icons, desktop entry, and `~/.local/bin` wrappers

## AppImage

From [GitHub Releases](https://github.com/VocaHQ/vocalinux/releases):

```bash
chmod +x Vocalinux-*-x86_64.AppImage   # or aarch64
./Vocalinux-*-x86_64.AppImage
```

Built against glibc 2.35, so it starts on Debian 12+, Ubuntu 22.04+, Fedora 36+, Arch, and Tumbleweed. Older bases (RHEL 9, Debian 11, Ubuntu 20.04) are below that AppImage floor. The installer and PyPI package still require a distro that ships Python 3.11+, so they are not a workaround for Debian 11 or Ubuntu 20.04.

Still needs host text-injection tools (`xdotool` on X11; `wtype` / `ydotool` / clipboard tools on Wayland). Current AppImages rebuild whisper.cpp with Vulkan and use the host GPU driver (`vulkaninfo --summary`). Prefer the installer when you want system deps, a CUDA build, and models set up automatically.

## Distro packages (.deb / .rpm)

From [GitHub Releases](https://github.com/VocaHQ/vocalinux/releases), pick the file matching your distro and CPU:

```bash
# Debian / Ubuntu (amd64; arm64 files are attached too)
sudo apt install ./vocalinux_*_amd64.deb

# Fedora (x86_64; aarch64 files are attached too)
sudo dnf install ./vocalinux-*.x86_64.rpm
```

These are thin packages: Python, GTK, PyGObject and the AppIndicator typelib come from the distribution, and `apt`/`dnf` resolves them. `xdotool`, `wtype`, `ydotool`, the clipboard tools and IBus are `Recommends`, matching the optional feature set of the other paths. Only `pywhispercpp` and `pynput` are vendored inside the package — `pywhispercpp` is packaged by neither distro and `pynput` is missing on Fedora. They land under `/usr/lib/vocalinux/vendor`, on `sys.path` via the `vocalinux` launcher.

The `.deb` needs a distro that ships Python 3.11+: Debian 12+ and Ubuntu 24.04+ (Ubuntu 22.04 ships 3.10). whisper.cpp runs on CPU in these packages — the PyPI wheel, not the Vulkan build the AppImage carries. There is no auto-update: a new release is a new package install. A PPA and a COPR are not published yet.

On Wayland, the default Right Alt shortcut reads keyboard devices through evdev, so your user needs `input` group membership or the hotkey is silently disabled:

```bash
sudo usermod -aG input $USER   # then log out and back in
```

Joining `input` grants read access to every keyboard and pointer device — X11 needs none of this. The launcher re-execs through `sg input` when `/etc/group` already lists the membership but the current session has not picked it up, so an `usermod` between package install and next login applies without a reboot. The source installer does this step for you; the packages cannot.

## Arch Linux (AUR)

```bash
yay -S vocalinux
```

See [AUR.md](AUR.md).

## Flatpak

Install and auto-update via the self-hosted VocaHQ remote (`flatpak update` picks up each release):

```bash
flatpak install https://vocahq.github.io/vocalinux-flatpak/com.vocalinux.Vocalinux.flatpakref
```

The `.flatpakref` adds the `vocahq` remote and resolves the GNOME runtime through Flathub. Manually instead:

```bash
flatpak remote-add --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
flatpak remote-add --if-not-exists vocahq https://vocahq.github.io/vocalinux-flatpak/vocahq.flatpakrepo
flatpak install vocahq com.vocalinux.Vocalinux
```

Or sideload a GitHub Release bundle (`Vocalinux-<version>-x86_64.flatpak` or `-aarch64.flatpak`) after the Flathub GNOME runtime is present — bundles do not auto-update:

```bash
flatpak install --user ./Vocalinux-<version>-x86_64.flatpak
```

Local build (contributors):

```bash
flatpak install flathub org.gnome.Platform//50 org.gnome.Sdk//50
flatpak-builder --user --install --force-clean build-dir \
  packaging/flatpak/com.vocalinux.Vocalinux.yml
flatpak run com.vocalinux.Vocalinux
```

Whisper.cpp + Vulkan. It is **not on Flathub** (submission [flathub#9368](https://github.com/flathub/flathub/pull/9368) closed 2026-07-23 on policy grounds). Details: [packaging/flatpak/README.md](../packaging/flatpak/README.md).

## Snap (Ubuntu Snap Store)

Listing: [snapcraft.io/vocalinux](https://snapcraft.io/vocalinux) (issue [#48](https://github.com/VocaHQ/vocalinux/issues/48)). Recipe: `snap/snapcraft.yaml`. Tagged `v*` releases attach `vocalinux_<version>_amd64.snap` to the GitHub Release and try Snap Store `edge` and `candidate` when credentials are set. `stable` is promoted from `candidate` after QA.

Store install, once Canonical lists the revision:

```bash
sudo snap install vocalinux --edge
sudo snap connect vocalinux:audio-record   # if mic is not auto-connected
sudo snap connect vocalinux:raw-input      # global keyboard shortcuts (evdev)
sudo snap connect vocalinux:hardware-observe  # list keyboards (/proc/bus/input/devices)
sudo snap connect vocalinux:uinput         # native Wayland typing (ydotool)
```

**v0.18.1** ships ydotool and the `uinput` plug. That plug is super-privileged, so the Store held 0.18.0 for human review (`allow-installation`). Until a 0.18.0+ revision is listed, `snap info vocalinux` still shows **v0.16.2 (rev 7)** on edge. That revision has no `uinput` plug; `sudo snap connect vocalinux:uinput` fails.

Sideload the GitHub `.snap` (amd64) while the Store is waiting:

```bash
sudo snap install --dangerous ./vocalinux_0.18.1_amd64.snap
sudo snap connect vocalinux:audio-record
sudo snap connect vocalinux:raw-input
sudo snap connect vocalinux:hardware-observe
sudo snap connect vocalinux:uinput
```

`--dangerous` is required because this file is not a Store revision. It will not refresh from the Store. After Canonical grants `uinput`, switch to `sudo snap install vocalinux --edge` (or `snap refresh`).

## From source

```bash
git clone https://github.com/VocaHQ/vocalinux.git
cd vocalinux
./install.sh
```

## System requirements

| Requirement | Details |
|-------------|---------|
| **OS** | Ubuntu 24.04+, Debian 12+, Fedora 42+, Arch, openSUSE Tumbleweed |
| **Python** | 3.11 or newer |
| **Display** | X11 or Wayland |
| **Hardware** | Microphone; GPU optional (Vulkan) |
| **Disk** | ~200MB with default whisper.cpp model |
| **RAM** | 4GB minimum; 8GB comfortable |

The distro must ship Python 3.11+ because Vocalinux uses distro PyGObject (`python3-gi`). Ubuntu 22.04 (Python 3.10) and Debian 11 (3.9) are below that floor. Distro matrix: [DISTRO_COMPATIBILITY.md](DISTRO_COMPATIBILITY.md).

### GPU (optional)

whisper.cpp uses Vulkan when available (AMD, Intel, NVIDIA). Check with `vulkaninfo --summary`.

## Running Vocalinux

```bash
vocalinux                                          # if ~/.local/bin is on PATH
~/.local/share/vocalinux/venv/bin/vocalinux        # direct
source venv/bin/activate && vocalinux              # source checkout
```

Or launch from the application menu.

### CLI

```bash
vocalinux --help
vocalinux --version
vocalinux --debug
vocalinux --engine whisper_cpp
vocalinux --engine whisper
vocalinux --engine vosk
vocalinux --engine parakeet
vocalinux --engine remote_api
vocalinux --model tiny
vocalinux --model medium.en-q5_0
vocalinux --model large-v3-turbo
vocalinux --wayland
vocalinux --start-minimized
```

## Autostart

**Start on Login** writes an XDG autostart desktop entry (`~/.config/autostart/`). It does not install a systemd unit. Enable from the first-run dialog, tray menu, or Settings.

## Data locations (XDG)

| Directory | Purpose |
|-----------|---------|
| `~/.config/vocalinux/` | Configuration |
| `~/.local/share/vocalinux/` | Data and speech models |
| `~/.local/share/applications/` | Desktop entry |
| `~/.local/share/icons/hicolor/scalable/apps/` | Icons |

## whisper.cpp (default engine)

Default engine: C++ Whisper port with Vulkan GPU support and lower install cost than the PyTorch Whisper stack.

| Size | Approx. | Use |
|------|---------|-----|
| tiny | ~74MB | Fast dictation (default) |
| base | ~141MB | Balance |
| small | ~465MB | Better accuracy |
| medium | ~1.5GB | High accuracy |
| large | ~3.0GB | Best accuracy |

In Settings → Speech Model, simple setup steers language and speed/accuracy. Expand **Advanced** for engine, **Model Size**, and **Specialization** (multilingual, English-only, quantized, Turbo, legacy large). More detail: [USER_GUIDE.md](USER_GUIDE.md).

Reuse an existing `pywhispercpp` build:

```bash
./install.sh --auto                         # reuse if present
./install.sh --auto --rebuild-whispercpp    # force rebuild
```

Switch engines in Settings → Speech Model (Advanced), or edit `~/.config/vocalinux/config.json` (`engine`: `whisper_cpp` | `whisper` | `vosk` | `parakeet` | `remote_api`).

## Uninstall

From a source checkout, `./uninstall.sh` removes the install and that checkout's `venv/`, `build/`, `dist/`, and Python bytecode. `--keep-config` and `--keep-data` leave `~/.config/vocalinux` and `~/.local/share/vocalinux` in place.

```bash
./uninstall.sh
./uninstall.sh --keep-config
./uninstall.sh --keep-data
```

The website command downloads this same script and runs it:

```bash
curl -fsSL https://raw.githubusercontent.com/VocaHQ/vocalinux/main/uninstall.sh -o /tmp/vul.sh
bash /tmp/vul.sh
```

That removes Vocalinux from your home directory (config, data, launchers, desktop entry, icons). It does not delete `venv/`, `build/`, `dist/`, or `.pyc` files in the directory where you ran it.

From the source checkout, the equivalent by hand:

```bash
rm -rf venv ~/.config/vocalinux ~/.local/share/vocalinux
rm -f activate-vocalinux.sh
rm -f ~/.local/share/applications/vocalinux.desktop
rm -f ~/.local/share/icons/hicolor/scalable/apps/vocalinux*.svg
gtk-update-icon-cache -f -t ~/.local/share/icons/hicolor
```

## Update

See [UPDATE.md](UPDATE.md).

```bash
curl -fsSL https://raw.githubusercontent.com/VocaHQ/vocalinux/main/install.sh -o /tmp/vl.sh
bash /tmp/vl.sh
```

## More documentation

| Doc | Contents |
|-----|----------|
| [INSTALL_MANUAL.md](INSTALL_MANUAL.md) | Manual install, PyPI/pipx, per-distro packages |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | Common failures and fixes |
| [DISTRO_COMPATIBILITY.md](DISTRO_COMPATIBILITY.md) | Support matrix |
| [USER_GUIDE.md](USER_GUIDE.md) | Day-to-day use |
| [SUPPORT.md](../SUPPORT.md) | Where to get help |
| [Documentation index](README.md) | Full list |
