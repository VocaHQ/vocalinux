# Linux Distribution Compatibility

## Implementation Status

The cross-distribution compatibility improvements have been implemented in phases:

| Phase | Status | Description |
|-------|--------|-------------|
| Phase 1 | ✅ Complete | Dynamic GI_TYPELIB_PATH detection using pkg-config, multi-arch support, ALSA library fallbacks |
| Phase 2 | ✅ Complete | Enhanced distro detection (Gentoo, Alpine, Void, Solus, Mageia) |
| Phase 3 | ✅ Complete | System dependency checker, improved error messages |
| Phase 4 | 🟡 Partial | pkg-config as a core dependency ✅. The CI distro matrix covers six containers, but it checks detection logic, shell syntax and `--help` — it never runs the installer, and the container jobs are `continue-on-error`. Real install runs are tracked as phase 2.4 of [#701](https://github.com/VocaHQ/vocalinux/issues/701) |
| **Phase 5** | ✅ **Complete** | **Fixed remaining hardcoded GI_TYPELIB_PATH values in install.sh and CI workflow** |
| **Phase 6** | ✅ **Complete** | **Added wrapper script verification tests, updated documentation** |
| **Phase 7** | ✅ **Complete** | **Flatpak packaging (whisper.cpp engine) for universal distribution support — see [`packaging/flatpak/`](../packaging/flatpak/README.md). Not on Flathub: submission [flathub#9368](https://github.com/flathub/flathub/pull/9368) closed 2026-07-23 on policy grounds; channel tracked in [#167](https://github.com/VocaHQ/vocalinux/issues/167).** |
| Phase 8 | 📋 Planned | Snap packaging for Ubuntu Software Store |

## Technical Implementation

### Dynamic GI_TYPELIB_PATH Detection

The installer now uses a robust multi-step approach to detect the correct GI_TYPELIB_PATH across different distributions:

1. **Primary Method**: Uses `pkg-config --variable=typelibdir gobject-introspection-1.0` (most reliable)
2. **Fallback Paths**: Checks common distribution-specific paths in priority order:
   - Ubuntu/Debian multi-arch: `/usr/lib/x86_64-linux-gnu/girepository-1.0`
   - ARM64: `/usr/lib/aarch64-linux-gnu/girepository-1.0`
   - Fedora/RHEL: `/usr/lib64/girepository-1.0`
   - Arch/Generic: `/usr/lib/girepository-1.0`
   - Local installs: `/usr/local/lib/girepository-1.0`

3. **Architecture Support**: Detected paths for x86_64, ARM64, ARMHF, RISC-V, POWER, and s390x

### Wrapper Scripts

The installer creates wrapper scripts (`~/.local/bin/vocalinux` and `~/.local/bin/vocalinux-gui`) that:
- Set the correct `GI_TYPELIB_PATH` environment variable
- Handle input group permissions for Wayland keyboard shortcuts
- Provide seamless cross-distro compatibility

### Desktop Entry

The `.desktop` entry is automatically configured with the detected `GI_TYPELIB_PATH`, ensuring the application launches correctly from the application menu regardless of distribution.

## Officially Supported Distributions

These distributions are tested and known to work well with Vocalinux. A
derivative is judged by the Python it ships rather than by its own version
number, which rarely tracks the base release, and `install.sh` checks the
interpreter rather than the release label.

| Distribution | Version | Status | Notes |
|--------------|---------|--------|-------|
| Ubuntu | 24.04+ | ✅ Full Support | 22.04 ships Python 3.10, below the 3.11 floor |
| Debian | 12+, Testing | ✅ Full Support | Primary target; use Ayatana AppIndicator |
| Fedora | 42+ | ✅ Good Support | Uses lib64 paths; 42 is the oldest Fedora upstream still supports, and the one in the CI matrix |
| Arch Linux | Rolling | ✅ Good Support | Community tested, rolling release compatible |
| openSUSE | Tumbleweed | ✅ Good Support | Good support with zypper package manager |
| Linux Mint | On Ubuntu 24.04+ | ✅ Good Support | Mint 22 qualifies; Mint 21 is on Ubuntu 22.04, below the floor |
| Pop!_OS | 24.04+ | ✅ Good Support | Uses Ubuntu's own numbering |
| elementary OS | On Ubuntu 24.04+ | ✅ Good Support | elementary 8 qualifies; 7 is on Ubuntu 22.04 |
| Zorin OS | On Ubuntu 24.04+ | ✅ Good Support | Zorin 17 is on Ubuntu 22.04, below the floor |
| Manjaro | Rolling | ✅ Good Support | Arch base, inherits Arch compatibility |
| EndeavourOS | Rolling | ✅ Good Support | Arch base, inherits Arch compatibility |

## Experimental Support

These distributions may work but have known limitations or are less tested:

| Distribution | Status | Known Issues |
|--------------|--------|--------------|
| Gentoo | ⚠️ Experimental | No package manager support, manual install required. Packages are compiled from source which takes longer. |
| Alpine Linux | ⚠️ Experimental | Uses musl libc (not glibc). Some Python packages may not have pre-built wheels and may need to be compiled. |
| Void Linux | ⚠️ Experimental | Untested, manual install required. Uses xbps package manager. |
| Solus | ⚠️ Experimental | Untested, manual install required. Uses eopkg package manager. |
| Mageia | ⚠️ Experimental | Untested, uses dnf/urpmi package managers. |

## Not Supported

These distributions are known to be incompatible:

| Distribution | Status | Reason |
|--------------|--------|--------|
| NixOS | ❌ Not Supported | Completely different filesystem layout (/nix/store), incompatible with standard installer |

## Requirements by Distribution

### Ubuntu/Debian-based
```bash
sudo apt install -y python3-gi gir1.2-gtk-3.0 gir1.2-gdkpixbuf-2.0 \
  portaudio19-dev python3-dev python3-venv pkg-config
```

**Note for Debian 12+:** Use `gir1.2-ayatanaappindicator3-0.1` instead of `gir1.2-appindicator3-0.1`

### Debian-specific notes

Debian's standard repositories differ from Ubuntu in a few ways that matter for Vocalinux:

**pywhispercpp build prerequisites** — On a clean Debian install the following packages are not
pulled in transitively (unlike Ubuntu) but are required when `pywhispercpp` must be compiled
from source (e.g. for GPU support):

```bash
sudo apt install -y libssl-dev autoconf automake libtool patchelf
```

The installer now installs these automatically, but if you hit a CMake error like
`Could not find OpenSSL` during a manual reinstall, add the above first.

**ydotool** — `ydotool` is not packaged in Debian's standard repos. The installer falls back
gracefully to IBus or `wtype` for most Wayland compositors. KDE Plasma Wayland users should
first select **IBus Wayland** in **System Settings -> Keyboard -> Virtual Keyboard**. If you
specifically need `ydotool` as a fallback, compile it from source:

```bash
sudo apt install -y git cmake libevdev-dev
git clone https://github.com/ReimuNotMoe/ydotool.git /tmp/ydotool
cmake -S /tmp/ydotool -B /tmp/ydotool/build
sudo cmake --build /tmp/ydotool/build --target install
sudo systemctl enable --now ydotoold
```

**Scoped source builds** — If you need to force `pywhispercpp` to rebuild from source, use the
package-scoped flag to avoid compiling unrelated deps like NumPy from source (which takes a very
long time and can fail):

```bash
source ~/.local/share/vocalinux/venv/bin/activate
PYWHISPERCPP_CLEAN=1 pip install --force-reinstall --no-binary=pywhispercpp pywhispercpp
deactivate
```

**Verifying libwhisper.so resolution** — If Vocalinux starts with
`libwhisper.so.1: cannot open shared object file`, check for unresolved symbols:

```bash
ldd $(find ~/.local/share/vocalinux/venv -name '*.so' -path '*/pywhispercpp*' 2>/dev/null | head -1) | grep 'not found'
```

If any libraries are listed, re-run the installer with `--rebuild-whispercpp` or switch to
the VOSK engine (`--engine=vosk`) as a fully-packaged alternative.

### Fedora/RHEL-based
```bash
sudo dnf install -y python3-gobject gtk3-devel gobject-introspection-devel \
  portaudio-devel python3-devel python3-virtualenv pkg-config
```

### Arch Linux-based
```bash
sudo pacman -S --needed python-gobject gtk3 gobject-introspection \
  portaudio python pkg-config
```

### openSUSE
```bash
PYVER=$(python3 -c 'import sys; print(f"python{sys.version_info.major}{sys.version_info.minor}")')

sudo zypper install -y \
  "${PYVER}-pip" "${PYVER}-gobject" "${PYVER}-gobject-cairo" \
  "${PYVER}-devel" "${PYVER}-virtualenv" \
  gtk3 typelib-1_0-AyatanaAppIndicator3-0_1 libayatana-appindicator3-1 \
  typelib-1_0-Notify-0_7 libnotify4 \
  gobject-introspection-devel portaudio-devel pkg-config cmake wget curl unzip \
  xdotool wtype

# Optional: only needed for whisper.cpp Vulkan GPU builds
sudo zypper install -y vulkan-tools vulkan-devel shaderc
```

**Note:** openSUSE Tumbleweed often uses versioned Python package names such as
`python313-devel`. The `-devel` suffix means development headers for compiling
native dependencies; it does **not** mean beta or unstable packages. If
`${PYVER}-virtualenv` is unavailable on your snapshot, try `${PYVER}-venv`.

### Gentoo
```bash
sudo emerge dev-python/pygobject:3 x11-libs/gtk+:3 dev-libs/libayatana-appindicator \
  media-libs/portaudio dev-lang/python:3.11
```

**Note:** Gentoo compiles packages from source, which will take longer.

### Alpine Linux
```bash
sudo apk add py3-gobject3 py3-pip gtk+3.0 py3-cairo portaudio-dev \
  py3-virtualenv pkgconf
```

**Note:** Alpine uses musl libc. Some Python packages may need to be compiled from source.

### Void Linux
```bash
sudo xbps-install -Sy python3-pip python3-gobject gtk+3 libappindicator \
  gobject-introspection portaudio-devel python3-devel pkg-config
```

### Solus
```bash
sudo eopkg install python3-pip python3-gobject gtk3 libappindicator \
  gobject-introspection-devel portaudio-devel python3-virtualenv pkg-config
```

### Mageia
```bash
sudo dnf install -y python3-gobject gtk3-devel gobject-introspection-devel \
  portaudio-devel python3-devel python3-virtualenv pkg-config
# or
sudo urpmi -y python3-gobject gtk3-devel gobject-introspection-devel \
  portaudio-devel python3-devel python3-virtualenv pkg-config
```

## PyPI, pip, and pipx Installation

The PyPI package is useful when you want a standard Python package install, or
when you want to manage Vocalinux with `pipx`. However, **Vocalinux requires
system desktop packages** that cannot be installed by pip or pipx.

Use the official installer when possible. It installs the required system
packages, creates the virtual environment, installs Vocalinux, sets up desktop
integration, and downloads the default speech model:

```bash
curl -fsSL https://raw.githubusercontent.com/VocaHQ/vocalinux/main/install.sh | bash
```

### Important: Install System Packages First

Before running `pip install vocalinux`, `pip install "vocalinux[vosk]"`, or
`pipx install vocalinux`, you **must** install the required system packages:

#### Ubuntu/Debian
```bash
sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1 \
  libgirepository1.0-dev libcairo2-dev portaudio19-dev python3-dev \
  python3-venv pkg-config xdotool wtype wl-clipboard xclip xsel
```

On Ubuntu 24.04+ or Pop!_OS, install `libgirepository-2.0-dev` if
`libgirepository1.0-dev` is not available.

#### Fedora
```bash
sudo dnf install python3-gobject gtk3 gtk3-devel libayatana-appindicator-gtk3 \
  gobject-introspection-devel portaudio-devel python3-devel \
  python3-virtualenv pkg-config xdotool wtype wl-clipboard xclip xsel
```

#### Arch Linux
```bash
sudo pacman -S python-gobject gtk3 libayatana-appindicator gobject-introspection \
  python-cairo portaudio python-virtualenv pkg-config xdotool wtype wl-clipboard xclip xsel
```

#### openSUSE
```bash
PYVER=$(python3 -c 'import sys; print(f"python{sys.version_info.major}{sys.version_info.minor}")')

sudo zypper install "${PYVER}-gobject" "${PYVER}-gobject-cairo" gtk3 \
  typelib-1_0-AyatanaAppIndicator3-0_1 libayatana-appindicator3-1 \
  typelib-1_0-Notify-0_7 libnotify4 \
  portaudio-devel "${PYVER}-devel" "${PYVER}-virtualenv" pkg-config xdotool wtype wl-clipboard xclip xsel
```

### pip Installation Steps

1. **Install system packages** (see above for your distribution)

2. **Create a virtual environment with system site-packages enabled**:
   ```bash
   python3 -m venv ~/.local/share/vocalinux-pypi/venv --system-site-packages
   source ~/.local/share/vocalinux-pypi/venv/bin/activate
   pip install --upgrade pip setuptools wheel
   ```

   `--system-site-packages` lets the venv use distro-provided GTK bindings such
   as `python3-gi`, which are often more reliable than building PyGObject from
   source in a venv.

3. **Install Vocalinux from PyPI**:
   ```bash
   pip install vocalinux
   # vosk engine: pip install "vocalinux[vosk]"
   ```

4. **Run Vocalinux**:
   ```bash
   vocalinux
   ```

### pipx Installation Steps

1. **Install system packages** (see above for your distribution)

2. **Install pipx** (if not already installed):
   ```bash
   # Ubuntu/Debian
   sudo apt install pipx
   pipx ensurepath

   # Fedora
   sudo dnf install pipx
   pipx ensurepath

   # Arch Linux
   sudo pacman -S pipx
   pipx ensurepath
   ```

3. **Install Vocalinux**:
   ```bash
   pipx install vocalinux
   # vosk engine: pipx install "vocalinux[vosk]"
   ```

4. **Run Vocalinux**:
   ```bash
   vocalinux
   ```

### Why System Packages Are Required

Vocalinux uses GTK3 for its GUI, AppIndicator/Ayatana for the system tray icon,
PortAudio for microphone capture, and tools such as `xdotool`, `wtype`, and clipboard utilities (`wl-clipboard`, `xclip`, `xsel`) for
text injection and layout-independent Wayland paste fallback. These are system libraries and desktop tools that must be
installed with your distribution's package manager. Python packages from PyPI
can provide Python bindings, but they do not provide the underlying GTK
typelibs, tray support, audio development libraries, or text injection binaries.

### Troubleshooting pip/pipx Installation

If `vocalinux` fails to start:

1. **Check for missing system packages** - The error message will indicate which packages are missing
2. **Verify GI_TYPELIB_PATH** - In rare cases, you may need to set this environment variable:
   ```bash
   export GI_TYPELIB_PATH=/usr/lib/x86_64-linux-gnu/girepository-1.0
   vocalinux
   ```
3. **Check package metadata** - Run `pip show vocalinux` or
   `pipx runpip vocalinux show vocalinux` to confirm which version was installed.
4. **Check Python dependencies** - Run `pip check` inside the venv, or
   `pipx runpip vocalinux check` for pipx.

If Vocalinux reports that a speech recognition model is missing, open Settings
and download a model, or use the official installer to download the default model
during setup.

### Recommended Alternative

For the best experience with automatic dependency handling, use the official installer:
```bash
curl -fsSL https://raw.githubusercontent.com/VocaHQ/vocalinux/main/install.sh | bash
```

This installer automatically detects your distribution and installs all required system packages.

## Text Injection Tools

Vocalinux requires text injection tools to work with X11 or Wayland:

### For X11
- **xdotool**: Required for X11 sessions

### For Wayland
- **IBus**: Recommended for KDE Plasma Wayland and generally the most reliable direct text input path
- **wtype**: Recommended for wlroots-style Wayland compositors such as sway
- **ydotool**: Universal alternative that works with both X11 and Wayland. Current distro packages use the per-user `ydotool.service`; source builds can install the system-level `ydotoold.service`. Vocalinux uses clipboard paste with `wl-clipboard`, `xclip`, or `xsel` to avoid non-US layout scrambling.
- **xdotool**: May work via XWayland fallback

### Installation by Distribution
```bash
# Ubuntu/Debian/Fedora/Arch/openSUSE
sudo apt install xdotool wtype wl-clipboard xclip xsel     # Ubuntu/Debian
sudo dnf install xdotool wtype wl-clipboard xclip xsel     # Fedora
sudo pacman -S xdotool wtype wl-clipboard xclip xsel       # Arch
sudo zypper install xdotool wtype wl-clipboard xclip xsel  # openSUSE
```

Ubuntu releases which package `ydotool` install a **user** unit named
`ydotool.service`. Enable it only for the account running Vocalinux:

```bash
sudo apt install ydotool
sudo usermod -aG input $USER  # then log out and back in
systemctl --user enable --now ydotool.service
```

Do **not** use `sudo systemctl --global enable ydotool.service`. Global user-unit
enablement also starts the input-injection daemon for the display-manager greeter
and other accounts. If it was previously enabled globally, repair the setup with:

```bash
sudo systemctl --global disable ydotool.service
systemctl --user enable --now ydotool.service
```

The command is different for the Debian source-build path documented above: the
upstream install supplies the system unit `ydotoold.service`, so
`sudo systemctl enable --now ydotoold.service` is correct only for that route.

## Manual Installation

For unsupported or experimental distributions:

1. **Run the dependency checker:**
   ```bash
   bash scripts/check-system-deps.sh
   ```

2. **Install missing dependencies** using your package manager based on the checker output

3. **Run the installer with --skip-system-deps:**
   ```bash
   ./install.sh --skip-system-deps
   ```

4. **Or install from source in a virtual environment:**
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -e .[whisper]
   ```

## Desktop Environment Compatibility

| Desktop Environment | Status | Notes |
|---------------------|--------|-------|
| GNOME | ✅ Full Support | Primary target, uses AppIndicator |
| KDE Plasma | ✅ Full Support | On Wayland, select IBus Wayland in System Settings -> Keyboard -> Virtual Keyboard |
| Xfce | ✅ Full Support | Works with AppIndicator |
| Cinnamon | ✅ Full Support | Works with AppIndicator |
| MATE | ✅ Full Support | Works with AppIndicator |
| LXQt | ✅ Full Support | Works with AppIndicator |
| sway | ✅ Good Support | Wayland native, uses wtype |
| i3 | ✅ Good Support | X11, uses xdotool |
| Hyprland | ⚠️ Experimental | Wayland, may need wtype configuration |

### Autostart Compatibility

Vocalinux uses **XDG autostart desktop entries** for "Start on Login".

- Desktop-session autostart file location:
  - `$XDG_CONFIG_HOME/autostart/vocalinux.desktop`, or
  - `~/.config/autostart/vocalinux.desktop` (fallback)
- This launches Vocalinux as a user GUI app after login.
- Vocalinux does **not** create a `systemd` service/unit for this feature.

Practical caveat:

- Mainstream desktop environments generally honor XDG autostart.
- Minimal/custom WM sessions may need an explicit autostart manager or WM startup hook.

## Display Server

| Display Server | Status | Notes |
|----------------|--------|-------|
| X11 | ✅ Full Support | Uses xdotool for text injection |
| Wayland | ✅ Full Support | Uses IBus, wtype, ydotool, or xdotool fallback depending on compositor |
| XWayland | ✅ Full Support | Automatically detected, falls back to xdotool if needed |

## Architecture Support

| Architecture | Status | Notes |
|--------------|--------|-------|
| x86_64 (AMD64) | ✅ Full Support | Primary target |
| arm64 (AArch64) | ✅ Good Support | Tested on Raspberry Pi, ARM64 servers |
| armhf | ⚠️ Experimental | Limited testing |
| riscv64 | ⚠️ Experimental | Limited testing, may need to compile dependencies |

## Reporting Issues

When reporting issues, please include:

1. **Distribution information:**
   ```bash
   cat /etc/os-release
   ```

2. **Desktop environment:**
   ```bash
   echo $XDG_CURRENT_DESKTOP
   echo $SESSION_TYPE
   ```

3. **Dependency checker output:**
   ```bash
   bash scripts/check-system-deps.sh
   ```

4. **Python version:**
   ```bash
   python3 --version
   ```

5. **Error messages or logs:**
   - Any error messages from the installer
   - Output from running `vocalinux-gui` from terminal
   - Relevant journal logs if applicable

6. **Steps to reproduce:**
   - What you were trying to do
   - What happened instead
   - Expected behavior

## Testing Checklist

Use this checklist when testing on a new distribution:

### Pre-Install
- [ ] Run dependency checker: `bash scripts/check-system-deps.sh`
- [ ] Note missing packages
- [ ] Check desktop environment
- [ ] Check display server (X11/Wayland)

### Installation
- [ ] Run installer: `./install.sh`
- [ ] Check for errors during installation
- [ ] Verify virtual environment was created
- [ ] Check wrapper scripts exist

### Post-Install
- [ ] Launch from terminal: `~/.local/bin/vocalinux-gui`
- [ ] Launch from application menu
- [ ] Verify tray icon appears
- [ ] Test keyboard shortcuts (Hold Right Alt by default)
- [ ] Test audio recording
- [ ] Test text injection in different applications
- [ ] Test Settings dialog opens correctly
- [ ] Test model download if using Whisper

### Known Issues to Watch For
- AppIndicator not showing in tray
- Audio device not detected
- Text injection not working
- Model download failures
- Permission errors with udev/input

## Contributing Compatibility Fixes

If you successfully get Vocalinux working on an unsupported or experimental distribution:

1. Test thoroughly using the checklist above
2. Document any distribution-specific requirements
3. Submit a PR with:
   - Distribution detection logic (if needed)
   - Package installation commands
   - Any patches or workarounds required
   - Update to this compatibility document

## See Also

- [Installation Guide](../README.md#installation)
- [Manual Installation](MANUAL_INSTALL.md)
- [Troubleshooting](TROUBLESHOOTING.md)
- [GitHub Issue Tracker](https://github.com/VocaHQ/vocalinux/issues)
