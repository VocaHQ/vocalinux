# Manual installation and PyPI

Use this when the [recommended installer](INSTALL.md) is not a fit, or you want an explicit package list. Prefer `./install.sh` for a normal desktop install.

Related: [DISTRO_COMPATIBILITY.md](DISTRO_COMPATIBILITY.md), [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

## System packages by distribution

Install desktop/system dependencies **before** creating a venv or running `pip install vocalinux`. Pip cannot install GTK typelibs, AppIndicator, PortAudio, or text-injection tools.

### Ubuntu

```bash
sudo apt update
sudo apt install -y \
    python3-pip python3-venv python3-dev \
    python3-gi python3-gi-cairo \
    gir1.2-gtk-3.0 \
    libgirepository1.0-dev portaudio19-dev \
    wget curl unzip

# Tray: older Ubuntu → gir1.2-appindicator3-0.1
#        newer Ubuntu → gir1.2-ayatanaappindicator3-0.1
sudo apt install -y gir1.2-ayatanaappindicator3-0.1

sudo apt install -y xdotool                       # X11
sudo apt install -y wtype wl-clipboard xclip xsel # Wayland helpers
```

On Ubuntu 24.04+ or Pop!_OS, install `libgirepository-2.0-dev` if `libgirepository1.0-dev` is missing.

### Debian 12

```bash
sudo apt update
sudo apt install -y \
    python3-pip python3-venv python3-dev \
    python3-gi python3-gi-cairo \
    gir1.2-gtk-3.0 \
    libgirepository1.0-dev libcairo2-dev portaudio19-dev \
    wget curl unzip \
    gir1.2-ayatanaappindicator3-0.1 \
    xdotool wtype wl-clipboard xclip xsel
```

### Debian 13+

```bash
sudo apt update
sudo apt install -y \
    python3-pip python3-venv python3-dev \
    python3-gi python3-gi-cairo \
    gir1.2-gtk-3.0 \
    libgirepository-2.0-dev libcairo2-dev portaudio19-dev \
    wget curl unzip \
    gir1.2-ayatanaappindicator3-0.1 \
    xdotool wtype wl-clipboard xclip xsel
```

Debian notes (OpenSSL build deps, ydotool, etc.): [DISTRO_COMPATIBILITY.md](DISTRO_COMPATIBILITY.md).

### Fedora

```bash
sudo dnf install -y \
    python3-pip python3-devel python3-virtualenv \
    python3-gobject gtk3 libayatana-appindicator-gtk3 \
    gobject-introspection-devel portaudio-devel \
    wget curl unzip xdotool wtype wl-clipboard xclip xsel
```

### Arch Linux

Prefer the AUR package (`yay -S vocalinux`). Manual packages:

```bash
sudo pacman -S --needed \
    python-pip python-gobject gtk3 \
    libayatana-appindicator gobject-introspection \
    python-cairo portaudio python-virtualenv \
    wget curl unzip xdotool wtype wl-clipboard xclip xsel
```

### openSUSE Tumbleweed

```bash
PYVER=$(python3 -c 'import sys; print(f"python{sys.version_info.major}{sys.version_info.minor}")')

sudo zypper install -y \
    "${PYVER}-pip" "${PYVER}-gobject" "${PYVER}-gobject-cairo" \
    "${PYVER}-devel" "${PYVER}-virtualenv" \
    gtk3 typelib-1_0-AyatanaAppIndicator3-0_1 libayatana-appindicator3-1 \
    typelib-1_0-Notify-0_7 libnotify4 \
    gobject-introspection-devel portaudio-devel pkg-config cmake \
    wget curl unzip xdotool wtype wl-clipboard xclip xsel

# Optional: whisper.cpp Vulkan builds
sudo zypper install -y vulkan-tools vulkan-devel shaderc
```

`-devel` packages are headers for compiling native Python deps, not "beta" packages. If `${PYVER}-virtualenv` is missing, try `${PYVER}-venv`.

### Other distributions

Gentoo, Alpine, Void, Solus, Mageia: [DISTRO_COMPATIBILITY.md](DISTRO_COMPATIBILITY.md).

## Install from a git checkout

Use the **system** Python (`/usr/bin/python3`). Distro PyGObject (`gi`) is compiled for that interpreter only, so a venv from pyenv/conda/uv cannot import it even with `--system-site-packages`.

```bash
cd vocalinux
/usr/bin/python3 -m venv venv --system-site-packages
source venv/bin/activate
pip install --upgrade pip setuptools wheel

pip install .                 # standard
pip install ".[whisper]"      # OpenAI Whisper extra
pip install ".[parakeet]"     # Parakeet (sherpa-onnx)
pip install ".[vad]"          # neural VAD
pip install -e ".[dev,vad]"   # development
```

### Desktop integration

```bash
mkdir -p ~/.config/vocalinux \
         ~/.local/share/vocalinux/models \
         ~/.local/share/applications \
         ~/.local/share/icons/hicolor/scalable/apps

cp vocalinux.desktop ~/.local/share/applications/
VENV_PATH=$(realpath venv/bin/vocalinux)
sed -i "s|^Exec=vocalinux|Exec=$VENV_PATH|" ~/.local/share/applications/vocalinux.desktop

cp resources/icons/scalable/*.svg ~/.local/share/icons/hicolor/scalable/apps/
gtk-update-icon-cache -f -t ~/.local/share/icons/hicolor
```

## Install from PyPI

Same system packages as above, then:

```bash
python3 -m venv ~/.local/share/vocalinux-pypi/venv --system-site-packages
source ~/.local/share/vocalinux-pypi/venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install vocalinux
# vosk engine: pip install "vocalinux[vosk]"
# parakeet engine: pip install "vocalinux[parakeet]"
vocalinux
```

`--system-site-packages` lets the venv use distro GTK bindings (`python3-gi`). Building PyGObject from pip is often painful on Ubuntu/Debian.

If the app starts but no speech model is present, open Settings and download a model, or use the official installer which downloads the default model during setup.

### pipx

```bash
# After system packages are installed:
pipx install vocalinux
vocalinux
```

pipx still cannot install system desktop libraries. Install those first with your package manager.

## Why system packages are required

Vocalinux uses GTK3, AppIndicator/Ayatana, PortAudio, and tools such as `xdotool`, `wtype`, and clipboard utilities. Those come from the distro. PyPI only supplies Python packages and wheels.

## After install

- Run: [INSTALL.md](INSTALL.md#running-vocalinux)
- Engines and models: [USER_GUIDE.md](USER_GUIDE.md)
- Failures: [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
