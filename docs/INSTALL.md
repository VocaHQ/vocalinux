# Installation Guide

This guide provides detailed instructions for installing Vocalinux on Linux systems.

## 🚀 Quick Start

### One-liner Installation (Recommended)

```bash
curl -fsSL https://raw.githubusercontent.com/jatinkrmalik/vocalinux/main/install.sh | bash
```

> **Note**: Always installs the latest release with **whisper.cpp** (our default engine). For a specific version, check [GitHub Releases](https://github.com/jatinkrmalik/vocalinux/releases).

That's it! The installer handles everything automatically:
- ✅ Installs whisper.cpp (~1-2 minutes, no heavy dependencies!)
- ✅ Auto-detects your GPU (AMD, Intel, NVIDIA all supported)
- ✅ Installs neural VAD support when ONNX Runtime is available
- ✅ Downloads the default whisper.cpp tiny model (~74MB)
- ✅ Configures everything automatically

> ⏱️ **Installation Time**: ~1-2 minutes (vs 5-10 minutes with old Whisper AI)

### From Source

```bash
git clone https://github.com/jatinkrmalik/vocalinux.git && cd vocalinux && ./install.sh
```

### AppImage (no install, no root)

Download the `.AppImage` for your CPU (`x86_64` or `aarch64`) from
[GitHub Releases](https://github.com/jatinkrmalik/vocalinux/releases), then:

```bash
chmod +x Vocalinux-*-x86_64.AppImage   # or aarch64
./Vocalinux-*-x86_64.AppImage
```

AppImage still needs host text-injection tools (`xdotool` on X11; `wtype` /
`ydotool` / clipboard tools on Wayland), same as the PyPI path. Prefer the
one-liner installer above when you want system deps and models set up for you.

### From PyPI

The PyPI package installs the Python application and Python dependencies, but it
cannot install Linux desktop packages such as GTK typelibs, AppIndicator,
PortAudio, or text injection tools. Install those system packages first, then
install Vocalinux in a virtual environment.

**Ubuntu/Debian:**

```bash
sudo apt install -y \
    python3-venv python3-dev python3-gi python3-gi-cairo \
    gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1 \
    libgirepository1.0-dev libcairo2-dev portaudio19-dev \
    pkg-config xdotool wtype wl-clipboard xclip xsel

python3 -m venv ~/.local/share/vocalinux-pypi/venv --system-site-packages
source ~/.local/share/vocalinux-pypi/venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install vocalinux
vocalinux
```

**Fedora:**

```bash
sudo dnf install -y \
    python3-virtualenv python3-devel python3-gobject gtk3 gtk3-devel \
    libayatana-appindicator-gtk3 gobject-introspection-devel portaudio-devel \
    pkg-config xdotool wtype wl-clipboard xclip xsel

python3 -m venv ~/.local/share/vocalinux-pypi/venv --system-site-packages
source ~/.local/share/vocalinux-pypi/venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install vocalinux
vocalinux
```

**Arch Linux:**

```bash
yay -S vocalinux
```

See [AUR.md](AUR.md). Or via PyPI:

```bash
sudo pacman -S --needed \
    python python-virtualenv python-gobject gtk3 libayatana-appindicator \
    gobject-introspection python-cairo portaudio pkg-config xdotool wtype wl-clipboard xclip xsel

python -m venv ~/.local/share/vocalinux-pypi/venv --system-site-packages
source ~/.local/share/vocalinux-pypi/venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install vocalinux
vocalinux
```

**openSUSE Tumbleweed:**

```bash
PYVER=$(python3 -c 'import sys; print(f"python{sys.version_info.major}{sys.version_info.minor}")')

sudo zypper install -y \
    "${PYVER}-gobject" "${PYVER}-gobject-cairo" gtk3 \
    typelib-1_0-AyatanaAppIndicator3-0_1 libayatana-appindicator3-1 \
    typelib-1_0-Notify-0_7 libnotify4 \
    gobject-introspection-devel portaudio-devel "${PYVER}-devel" \
    "${PYVER}-virtualenv" pkg-config xdotool wtype wl-clipboard xclip xsel

python3 -m venv ~/.local/share/vocalinux-pypi/venv --system-site-packages
source ~/.local/share/vocalinux-pypi/venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install vocalinux
vocalinux
```

If `vocalinux` starts but reports a missing speech model, open Settings and
download a model, or use the recommended installer which downloads the default
model during setup.

On Ubuntu 24.04+ or Pop!_OS, install `libgirepository-2.0-dev` if
`libgirepository1.0-dev` is not available.

## System Requirements

| Requirement | Details |
|-------------|---------|
| **Operating System** | Ubuntu 22.04+ (recommended), Debian 11+, Fedora 38+, Arch Linux |
| **Python** | 3.9 or newer |
| **Display Server** | X11 or Wayland |
| **Hardware** | Microphone for speech input |
| **Disk Space** | ~200MB (including whisper.cpp model) |
| **RAM** | 4GB minimum, works great with 8GB |

### GPU Support (Optional)

**whisper.cpp** supports GPU acceleration via **Vulkan**, which works with:
- ✅ AMD GPUs (RX series, integrated graphics)
- ✅ Intel GPUs (Arc, integrated graphics)
- ✅ NVIDIA GPUs (RTX, GTX series)

No special drivers needed - if your GPU supports Vulkan, whisper.cpp will use it automatically!

To check Vulkan support: `vulkaninfo --summary`

## Installation Options

### Interactive Installation (Recommended)

The new interactive installer guides you through engine selection:

```bash
./install.sh
```

**Choose your engine:**
1. **whisper.cpp** ⭐ (Recommended) - Fast, works with any GPU via Vulkan
2. **Whisper** (OpenAI) - PyTorch-based, NVIDIA GPU only
3. **VOSK** - Lightweight, works on older systems

The installer will auto-detect your hardware and recommend the best option!

### Automatic Installation

Skip the interactive prompts with `--auto`:

```bash
./install.sh --auto                    # Default: whisper.cpp
./install.sh --auto --engine=whisper   # Use OpenAI Whisper
./install.sh --auto --engine=vosk      # Use VOSK only
```

### Development Installation

For contributing or development work:

```bash
./install.sh --dev
```

This installs additional tools: pytest, black, isort, flake8, pre-commit.

### All Installer Options

```bash
./install.sh --help

Installation Modes:
  (no flags)       Interactive mode - guided setup with recommendations
  --auto           Automatic mode - install with defaults (whisper.cpp)
  --auto --engine=whisper   Auto mode with Whisper engine

Options:
  --interactive, -i  Force interactive mode (default)
  --auto           Non-interactive automatic installation
  --engine=NAME    Speech engine: whisper_cpp (default), whisper, vosk
  --dev            Install in development mode with all dev dependencies
  --test           Run tests after installation
  --venv-dir=PATH  Specify custom virtual environment directory
  --skip-models    Skip downloading speech models during installation
  --rebuild-whispercpp     Rebuild/reinstall pywhispercpp even if already installed
  --no-rebuild-whispercpp  Reuse existing pywhispercpp when present (auto-mode default)
  --tag=TAG        Install specific release tag
  --help           Show this help message

Examples:
  ./install.sh                           # Interactive mode (recommended)
  ./install.sh --auto                    # Auto-install with whisper.cpp
  ./install.sh --auto --engine=vosk      # Auto-install VOSK only
  ./install.sh --dev --test              # Dev mode with tests
```

## What the Installer Does

1. **Detects your Linux distribution** and installs appropriate system packages
2. **Creates a Python virtual environment** with system site-packages access
3. **Installs the Vocalinux package** and all dependencies
4. **Installs the speech recognition engine** you selected:
   - **whisper.cpp** (default): High-performance C++ engine with Vulkan GPU support
   - **Whisper**: OpenAI's PyTorch-based engine (NVIDIA GPU only)
   - **VOSK**: Lightweight engine for older systems
5. **Installs neural VAD support** when ONNX Runtime is available, with a safe amplitude-VAD fallback otherwise
6. **Downloads speech recognition models**:
   - whisper.cpp: default ~74MB tiny model; selectable variants range from smaller quantized models to large models
   - Whisper: ~75MB tiny model + PyTorch dependencies (~2.3GB with CUDA)
   - VOSK: ~40MB small model
7. **Installs desktop integration** (icons, .desktop file)
8. **Creates activation script** for easy environment activation

### Installation Time Comparison

| Engine | Download Size | Install Time | GPU Support |
|--------|---------------|--------------|-------------|
| **whisper.cpp** (default) | ~74MB default; variants from ~15MB-3GB | ~1-2 min | AMD, Intel, NVIDIA (Vulkan) |
| Whisper (OpenAI) | ~2.3GB+ | ~5-10 min | NVIDIA only (CUDA) |
| VOSK | ~40MB | ~30 sec | CPU only |

## Running Vocalinux

After installation:

```bash
# If installed via curl (and ~/.local/bin is in PATH):
vocalinux

# Or run directly:
~/.local/share/vocalinux/venv/bin/vocalinux

# If installed from source:
source venv/bin/activate
vocalinux
```

### Command Line Options

```bash
vocalinux --help                  # Show all options
vocalinux --debug                 # Enable debug logging
vocalinux --engine whisper_cpp    # Use whisper.cpp engine (default)
vocalinux --engine whisper        # Use OpenAI Whisper engine
vocalinux --engine vosk           # Use VOSK engine
vocalinux --model tiny            # Use tiny model (default, fastest)
vocalinux --model small           # Use small model
vocalinux --model medium          # Use medium model
vocalinux --model large           # Use large model
vocalinux --model medium.en-q5_0  # Use exact whisper.cpp model variant
vocalinux --model large-v3-turbo  # Use large-v3 Turbo with whisper.cpp
vocalinux --wayland               # Force Wayland compatibility mode
vocalinux --start-minimized       # Start without first-run modal prompts
```

## Autostart Approach

Vocalinux autostart is implemented with **XDG Autostart** (desktop entry), not as a `systemd` background service.

- Enabling **Start on Login** creates `vocalinux.desktop` in:
  - `$XDG_CONFIG_HOME/autostart/`, or
  - `~/.config/autostart/` (fallback)
- The autostart entry launches Vocalinux as a normal user desktop app at login.
- No `systemd --user` unit is created by Vocalinux for this feature.

This keeps behavior aligned with standard Linux desktop sessions and avoids service/session environment mismatches for GUI apps.

## Directory Structure

Vocalinux follows the [XDG Base Directory Specification](https://specifications.freedesktop.org/basedir-spec/basedir-spec-latest.html):

| Directory | Purpose |
|-----------|---------|
| `~/.config/vocalinux/` | Configuration files |
| `~/.local/share/vocalinux/` | Application data, speech models |
| `~/.local/share/applications/` | Desktop entry |
| `~/.local/share/icons/hicolor/scalable/apps/` | Application icons |

## Manual Installation

If you prefer manual installation or the automatic installer doesn't work:

### 1. Install System Dependencies

**Ubuntu:**
```bash
sudo apt update
sudo apt install -y \
    python3-pip python3-venv python3-dev \
    python3-gi python3-gi-cairo \
    gir1.2-gtk-3.0 \
    libgirepository1.0-dev portaudio19-dev \
    wget curl unzip

# For appindicator (system tray icon):
# - On older Ubuntu versions:
sudo apt install -y gir1.2-appindicator3-0.1
# - On newer Ubuntu versions:
sudo apt install -y gir1.2-ayatanaappindicator3-0.1

# For X11
sudo apt install -y xdotool

# For Wayland
sudo apt install -y wtype wl-clipboard xclip xsel
```

**Debian 11/12:**
```bash
sudo apt update
sudo apt install -y \
    python3-pip python3-venv python3-dev \
    python3-gi python3-gi-cairo \
    gir1.2-gtk-3.0 \
    libgirepository1.0-dev libcairo2-dev portaudio19-dev \
    wget curl unzip

# For appindicator (system tray icon):
sudo apt install -y gir1.2-ayatanaappindicator3-0.1

# For X11
sudo apt install -y xdotool

# For Wayland
sudo apt install -y wtype wl-clipboard xclip xsel
```

**Debian 13+:**
```bash
sudo apt update
sudo apt install -y \
    python3-pip python3-venv python3-dev \
    python3-gi python3-gi-cairo \
    gir1.2-gtk-3.0 \
    libgirepository-2.0-dev libcairo2-dev portaudio19-dev \
    wget curl unzip

# For appindicator (system tray icon):
sudo apt install -y gir1.2-ayatanaappindicator3-0.1

# For X11
sudo apt install -y xdotool

# For Wayland
sudo apt install -y wtype wl-clipboard xclip xsel
```

**Fedora:**
```bash
sudo dnf install -y \
    python3-pip python3-devel python3-virtualenv \
    python3-gobject gtk3 libayatana-appindicator-gtk3 \
    gobject-introspection-devel portaudio-devel \
    wget curl unzip xdotool wtype wl-clipboard xclip xsel
```

**Arch Linux:**
```bash
sudo pacman -S --noconfirm \
    python-pip python-gobject gtk3 \
    libayatana-appindicator gobject-introspection \
    python-cairo portaudio python-virtualenv \
    wget curl unzip xdotool wtype wl-clipboard xclip xsel
```

**openSUSE Tumbleweed:**
```bash
PYVER=$(python3 -c 'import sys; print(f"python{sys.version_info.major}{sys.version_info.minor}")')

sudo zypper install -y \
    "${PYVER}-pip" "${PYVER}-gobject" "${PYVER}-gobject-cairo" \
    "${PYVER}-devel" "${PYVER}-virtualenv" \
    gtk3 typelib-1_0-AyatanaAppIndicator3-0_1 libayatana-appindicator3-1 \
    typelib-1_0-Notify-0_7 libnotify4 \
    gobject-introspection-devel portaudio-devel pkg-config cmake \
    wget curl unzip xdotool wtype wl-clipboard xclip xsel

# Optional: only needed for whisper.cpp Vulkan GPU builds
sudo zypper install -y vulkan-tools vulkan-devel shaderc
```

On openSUSE, `-devel` packages are development headers for native Python
dependencies. They are not beta or unstable packages. If `${PYVER}-virtualenv`
is unavailable on your snapshot, try `${PYVER}-venv`.

### 2. Create Virtual Environment

```bash
cd vocalinux
python3 -m venv venv --system-site-packages
source venv/bin/activate
pip install --upgrade pip setuptools wheel
```

### 3. Install Package

```bash
# Standard installation
pip install .

# With Whisper support
pip install ".[whisper]"

# With neural VAD support
pip install ".[vad]"

# Development mode
pip install -e ".[dev,vad]"
```

For PyPI instead of a local checkout, use `pip install vocalinux` after installing
the same system packages and creating the virtual environment with
`--system-site-packages`.

### 4. Set Up Desktop Integration

```bash
# Create directories
mkdir -p ~/.config/vocalinux
mkdir -p ~/.local/share/vocalinux/models
mkdir -p ~/.local/share/applications
mkdir -p ~/.local/share/icons/hicolor/scalable/apps

# Install desktop entry
cp vocalinux.desktop ~/.local/share/applications/
VENV_PATH=$(realpath venv/bin/vocalinux)
sed -i "s|^Exec=vocalinux|Exec=$VENV_PATH|" ~/.local/share/applications/vocalinux.desktop

# Install icons
cp resources/icons/scalable/*.svg ~/.local/share/icons/hicolor/scalable/apps/

# Update icon cache
gtk-update-icon-cache -f -t ~/.local/share/icons/hicolor
```

## About whisper.cpp

### What is whisper.cpp?

**whisper.cpp** is a high-performance C++ port of OpenAI's Whisper speech recognition model. It's now the **default engine** in Vocalinux because it offers significant advantages:

**Performance Benefits:**
- **10x faster installation** - No 2.3GB PyTorch download (just ~74MB model)
- **C++ optimized inference** - Faster than Python-based Whisper
- **True multi-threading** - Uses all CPU cores (no Python GIL limitations)
- **Lower memory usage** - More efficient than PyTorch

**GPU Support:**
- **Vulkan acceleration** - Works with AMD, Intel, and NVIDIA GPUs
- **Automatic backend selection** - Uses Vulkan → CUDA → CPU (in that order)
- **No special drivers** - Just needs standard Vulkan support

**Models:**
whisper.cpp uses OpenAI Whisper models converted to `ggml` format. Vocalinux lets you
pick a top-level size and, for whisper.cpp, a specialization:

- **tiny** (~74MB) - Fastest, good for real-time dictation
- **base** (~141MB) - Good balance of speed and accuracy
- **small** (~465MB) - Better accuracy, still fast
- **medium** (~1.5GB) - High accuracy
- **large** (~3.0GB) - Best accuracy, slower

Available whisper.cpp specializations include:
- **Standard multilingual** - Best default for auto-detect or non-English dictation
- **English-only** - Choose when you dictate only in English
- **Quantized** - Lower memory and smaller downloads with a possible accuracy tradeoff
- **Turbo** - Faster large-v3 option with strong accuracy
- **Legacy large** - Use only if you specifically need an older large model version

Examples of exact whisper.cpp model IDs are `tiny.en`, `small.en-q5_1`,
`medium-q5_0`, `medium.en-q5_0`, `large-v3-turbo`, and `large-v3-turbo-q8_0`.

### Checking GPU Support

To verify your GPU is detected:

```bash
# Check Vulkan support (for AMD, Intel, NVIDIA)
vulkaninfo --summary | grep -i "deviceName"

# In Vocalinux, look for these log messages:
# [INFO] whisper.cpp backend selection priority: Vulkan -> CUDA -> CPU
# [INFO] whisper.cpp using Vulkan GPU backend: AMD Radeon RX 6800
```

### Reusing Existing whisper.cpp Builds

When updating an existing install, the installer checks for a working `pywhispercpp`
installation before rebuilding it. Interactive installs ask whether to rebuild, with
the default set to no. Automatic installs reuse the existing build by default.

```bash
./install.sh --auto                         # Reuse pywhispercpp if already installed
./install.sh --auto --rebuild-whispercpp    # Force a rebuild/reinstall
```

### Switching Engines

If you want to try a different engine after installation:

```bash
# Edit the config file
nano ~/.config/vocalinux/config.json
```

Change the `engine` field:
```json
{
  "speech_recognition": {
    "engine": "whisper_cpp",  // Options: whisper_cpp, whisper, vosk
    "model_size": "tiny"      // Or an exact whisper.cpp ID like medium.en-q5_0
  }
}
```

Or use the GUI: Right-click tray icon → Settings → Speech Engine. For whisper.cpp,
the GUI splits this into **Model Size** and **Specialization**.

## Troubleshooting

### Virtual Environment Issues

**Symptom:** "command not found: vocalinux"

**Solution:**
```bash
# Make sure you've activated the environment
source activate-vocalinux.sh

# Or activate directly
source venv/bin/activate
```

### Audio Input Problems

**Symptom:** "No audio detected" or microphone not working

**Solutions:**
1. Check system audio settings
2. Run `arecord -l` to list audio devices
3. Try with debug mode: `vocalinux --debug`
4. Check microphone permissions

### GTK/AppIndicator Errors

**Symptom:** "No module named gi" or AppIndicator errors

**Solution:**
```bash
# Reinstall GTK dependencies
sudo apt install python3-gi python3-gi-cairo

# For appindicator (system tray icon) - try one of these:
sudo apt install gir1.2-appindicator3-0.1  # For older Debian/Ubuntu
# OR
sudo apt install gir1.2-ayatanaappindicator3-0.1  # For Debian 11+ or newer Ubuntu

# Recreate venv with system packages
rm -rf venv
python3 -m venv venv --system-site-packages
source venv/bin/activate
pip install -e .
```

### Text Injection Not Working

**Symptom:** Recognized text doesn't appear in applications

**Solutions:**

For X11:
```bash
sudo apt install xdotool
# Test: xdotool type "hello"
```

For KDE Plasma Wayland:

1. Install IBus if it is missing:
   ```bash
   # Ubuntu/Debian
   sudo apt install ibus

   # Fedora
   sudo dnf install ibus

   # Arch
   sudo pacman -S ibus
   ```
2. Open **System Settings -> Keyboard -> Virtual Keyboard**.
3. Select **IBus Wayland**.
4. Restart Vocalinux, or log out and back in if text still does not appear.

For Wayland:
```bash
sudo apt install wtype wl-clipboard xclip xsel
# Test: wtype "hello"
# Clipboard fallback test: printf "bonjour" | xsel --clipboard --input
```

On KDE Plasma Wayland, `wtype` may fail because the compositor does not expose
the required virtual keyboard protocol to regular clients. Use **IBus Wayland**
from KDE System Settings for the most reliable direct text injection.

### Model Download Fails

**Symptom:** Can't download speech models

**Solution:**
```bash
# Models will auto-download on first run
# Or manually download:
mkdir -p ~/.local/share/vocalinux/models
cd ~/.local/share/vocalinux/models
wget https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip
unzip vosk-model-small-en-us-0.15.zip
```

Model names with more language and size variety can be found in [VOSK Models](https://alphacephei.com/vosk/models) page.

### Model Download Fails Verification

**Symptom:** `SHA256 mismatch` during install, or "The download was corrupted or
tampered with" in the app

Vocalinux checks every downloaded model against a pinned SHA256 digest and
discards anything that does not match, so this usually means the download was
truncated or a proxy modified it. Retry the download; if it keeps failing on the
same model, check whether you are behind a TLS-inspecting proxy and report it —
see [SECURITY.md](../SECURITY.md) for what the check covers.

### Icons Not Displaying

**Symptom:** Tray icon missing or generic

**Solution:**

On GNOME (including Fedora Workstation and Ubuntu), AppIndicator support is often
disabled until you install and enable the tray extension:

```bash
# Debian/Ubuntu
sudo apt install gnome-shell-extension-appindicator

# Fedora
sudo dnf install gnome-shell-extension-appindicator

# Arch
sudo pacman -S gnome-shell-extension-appindicator

# Then enable (Extensions app, or):
gnome-extensions enable appindicatorsupport@rgcjonas.gmail.com
# Log out and back in if the icon still does not appear
```

Also refresh the icon cache and restart Vocalinux:

```bash
gtk-update-icon-cache -f -t ~/.local/share/icons/hicolor
vocalinux --debug
```

## Uninstallation

### Using the Uninstaller

```bash
./uninstall.sh
```

Options:
- `--keep-config` - Keep configuration files
- `--keep-data` - Keep application data (models, etc.)

### Manual Uninstallation

```bash
# Remove application files
rm -rf venv
rm -f activate-vocalinux.sh

# Remove user data
rm -rf ~/.config/vocalinux
rm -rf ~/.local/share/vocalinux
rm -f ~/.local/share/applications/vocalinux.desktop
rm -f ~/.local/share/icons/hicolor/scalable/apps/vocalinux*.svg

# Update icon cache
gtk-update-icon-cache -f -t ~/.local/share/icons/hicolor
```

## Updating Vocalinux

Already have Vocalinux installed? See the [Update Guide](UPDATE.md) for instructions on upgrading to the latest version.

Quick update command:
```bash
curl -fsSL https://raw.githubusercontent.com/jatinkrmalik/vocalinux/main/install.sh | bash
```

## Getting Help

- 📖 [User Guide](USER_GUIDE.md)
- 📖 [Update Guide](UPDATE.md)
- 🐛 [Report Issues](https://github.com/jatinkrmalik/vocalinux/issues)
- 💬 [Discussions](https://github.com/jatinkrmalik/vocalinux/discussions)
