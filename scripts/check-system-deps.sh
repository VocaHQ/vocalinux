#!/bin/bash
# Check for system dependencies regardless of distro
# Returns helpful error messages with install commands

check_deps() {
    MISSING=0
    WARNINGS=0

    echo "Checking Vocalinux system dependencies..."
    echo ""

    # Check for Python 3.9+
    if command -v python3 >/dev/null 2>&1; then
        PY_VERSION=$(python3 -c "import sys; print('.'.join(map(str, sys.version_info[:2])))")
        echo "✓ Python $PY_VERSION"

        if [ "$(echo "$PY_VERSION" | cut -d. -f1)" -lt 3 ] || \
           [ "$(echo "$PY_VERSION" | cut -d. -f2)" -lt 9 ]; then
            echo "  ✗ Python 3.9+ required, found $PY_VERSION"
            MISSING=1
        fi
    else
        echo "✗ Python 3 not found"
        MISSING=1
    fi

    # Check for pip
    if command -v pip3 >/dev/null 2>&1; then
        echo "✓ pip3"
    else
        echo "✗ pip3 not found"
        MISSING=1
    fi

    # Check for pkg-config
    if command -v pkg-config >/dev/null 2>&1; then
        echo "✓ pkg-config"
    else
        echo "✗ pkg-config not found"
        MISSING=1
    fi

    # Check for GTK3
    if command -v pkg-config >/dev/null 2>&1 && pkg-config --exists gtk+-3.0 2>/dev/null; then
        GTK_VERSION=$(pkg-config --modversion gtk+-3.0 2>/dev/null)
        echo "✓ GTK3 $GTK_VERSION"
    else
        echo "✗ GTK3 development files not found"
        MISSING=1
    fi

    # Check for PyGObject
    if command -v pkg-config >/dev/null 2>&1 && pkg-config --exists gobject-introspection-1.0 2>/dev/null; then
        echo "✓ GObject Introspection"
        GI_TYPELIB_PATH=$(pkg-config --variable=typelibdir gobject-introspection-1.0 2>/dev/null)
        echo "  Typelib path: $GI_TYPELIB_PATH"
    else
        echo "✗ GObject Introspection not found"
        MISSING=1
    fi

    # Check for AppIndicator/Ayatana AppIndicator GI runtime
    if python3 - <<'PY' >/dev/null 2>&1
import importlib
import gi

for namespace in ("AppIndicator3", "AyatanaAppIndicator3", "AyatanaAppindicator3"):
    try:
        gi.require_version(namespace, "0.1")
        importlib.import_module(f"gi.repository.{namespace}")
        raise SystemExit(0)
    except (ImportError, ValueError):
        pass

raise SystemExit(1)
PY
    then
        echo "✓ AppIndicator/Ayatana GI runtime"
    else
        echo "✗ AppIndicator/Ayatana GI runtime not found"
        MISSING=1
    fi

    # Check for PortAudio
    if command -v pkg-config >/dev/null 2>&1 && pkg-config --exists portaudio-2.0 2>/dev/null; then
        PA_VERSION=$(pkg-config --modversion portaudio-2.0 2>/dev/null)
        echo "✓ PortAudio $PA_VERSION"
    else
        echo "⚠ PortAudio development files not found (required for audio)"
        MISSING=1
    fi

    # Check for text injection tools
    echo ""
    echo "Text injection tools (at least one required):"

    if command -v xdotool >/dev/null 2>&1; then
        echo "✓ xdotool (X11)"
    else
        echo "  xdotool not found (X11)"
    fi

    if command -v wtype >/dev/null 2>&1; then
        echo "✓ wtype (Wayland)"
    else
        echo "  wtype not found (Wayland)"
    fi

    if command -v ydotool >/dev/null 2>&1; then
        echo "✓ ydotool (Wayland universal)"
    else
        echo "  ydotool not found (Wayland)"
    fi

    echo ""
    echo "Clipboard tools (recommended for Wayland layout-independent paste fallback):"

    if command -v wl-copy >/dev/null 2>&1; then
        echo "✓ wl-copy (Wayland clipboard)"
    else
        echo "  wl-copy not found (Wayland clipboard)"
    fi

    if command -v xclip >/dev/null 2>&1; then
        echo "✓ xclip (X11/XWayland clipboard)"
    else
        echo "  xclip not found (X11/XWayland clipboard)"
    fi

    if command -v xsel >/dev/null 2>&1; then
        echo "✓ xsel (X11/XWayland clipboard fallback)"
    else
        echo "  xsel not found (X11/XWayland clipboard fallback)"
    fi

    # Detect distribution for install hints
    echo ""
    DETECTED_DISTRO="unknown"
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        DETECTED_DISTRO="$ID"
        DETECTED_DISTRO_LIKE="$ID_LIKE"
    fi

    # Summary
    echo ""
    echo "===================================="
    if [ $MISSING -eq 0 ]; then
        echo "✓ All critical dependencies found!"
        return 0
    else
        echo "✗ Some dependencies are missing"
        echo ""
        echo "Install based on your distribution:"
        echo ""

        # Determine distro family for install hints
        if [[ "$DETECTED_DISTRO" == "ubuntu" || "$DETECTED_DISTRO_LIKE" == *"ubuntu"* || "$DETECTED_DISTRO" == "pop" || "$DETECTED_DISTRO" == "linuxmint" || "$DETECTED_DISTRO" == "elementary" || "$DETECTED_DISTRO" == "zorin" ]]; then
            echo "Ubuntu/Debian-based:"
            echo "  sudo apt update"
            echo "  sudo apt install -y python3-gi gir1.2-gtk-3.0 gir1.2-gdkpixbuf-2.0 portaudio19-dev python3-dev python3-venv pkg-config xdotool wtype wl-clipboard xclip xsel"
        elif [[ "$DETECTED_DISTRO" == "fedora" || "$DETECTED_DISTRO_LIKE" == *"fedora"* || "$DETECTED_DISTRO" == "rhel" || "$DETECTED_DISTRO" == "centos" || "$DETECTED_DISTRO" == "rocky" || "$DETECTED_DISTRO" == "almalinux" ]]; then
            echo "Fedora/RHEL-based:"
            echo "  sudo dnf install -y python3-gobject gtk3-devel libayatana-appindicator-gtk3 gobject-introspection-devel portaudio-devel python3-devel python3-virtualenv pkg-config xdotool wtype wl-clipboard xclip xsel"
        elif [[ "$DETECTED_DISTRO" == "arch" || "$DETECTED_DISTRO_LIKE" == *"arch"* || "$DETECTED_DISTRO" == "manjaro" || "$DETECTED_DISTRO" == "endeavouros" ]]; then
            echo "Arch Linux-based:"
            echo "  sudo pacman -S --needed python-gobject gtk3 libayatana-appindicator gobject-introspection portaudio python pkg-config xdotool wtype wl-clipboard xclip xsel"
        elif [[ "$DETECTED_DISTRO" == "opensuse" || "$DETECTED_DISTRO_LIKE" == *"suse"* ]]; then
            echo "openSUSE:"
            echo "  PYVER=\$(python3 -c 'import sys; print(f\"python{sys.version_info.major}{sys.version_info.minor}\")')"
            echo "  sudo zypper install -y \"\${PYVER}-gobject\" \"\${PYVER}-gobject-cairo\" gtk3 typelib-1_0-AyatanaAppIndicator3-0_1 libayatana-appindicator3-1 typelib-1_0-Notify-0_7 libnotify4 gobject-introspection-devel portaudio-devel \"\${PYVER}-devel\" \"\${PYVER}-virtualenv\" pkg-config xdotool wtype wl-clipboard xclip xsel"
            echo "  If \"\${PYVER}-virtualenv\" is unavailable, try \"\${PYVER}-venv\"."
        elif [[ "$DETECTED_DISTRO" == "gentoo" ]]; then
            echo "Gentoo:"
            echo "  sudo emerge dev-python/pygobject:3 x11-libs/gtk+:3 dev-libs/libayatana-appindicator media-libs/portaudio dev-lang/python:3.9 xdotool wtype"
        elif [[ "$DETECTED_DISTRO" == "alpine" ]]; then
            echo "Alpine Linux:"
            echo "  sudo apk add py3-gobject3 py3-pip gtk+3.0 py3-cairo portaudio-dev py3-virtualenv pkgconf xdotool wtype"
        elif [[ "$DETECTED_DISTRO" == "void" ]]; then
            echo "Void Linux:"
            echo "  sudo xbps-install -Sy python3-pip python3-gobject gtk+3 libappindicator gobject-introspection portaudio-devel python3-devel pkg-config xdotool wtype wl-clipboard xclip xsel"
        elif [[ "$DETECTED_DISTRO" == "solus" ]]; then
            echo "Solus:"
            echo "  sudo eopkg install python3-pip python3-gobject gtk3 libappindicator gobject-introspection-devel portaudio-devel python3-virtualenv pkg-config xdotool wtype wl-clipboard xclip xsel"
        elif [[ "$DETECTED_DISTRO" == "mageia" ]]; then
            echo "Mageia:"
            if command -v dnf >/dev/null 2>&1; then
                echo "  sudo dnf install -y python3-gobject gtk3-devel gobject-introspection-devel portaudio-devel python3-devel python3-virtualenv pkg-config xdotool wtype wl-clipboard xclip xsel"
            else
                echo "  sudo urpmi -y python3-gobject gtk3-devel gobject-introspection-devel portaudio-devel python3-devel python3-virtualenv pkg-config xdotool wtype wl-clipboard xclip xsel"
            fi
        else
            echo "Ubuntu/Debian-based:"
            echo "  sudo apt install -y python3-gi gir1.2-gtk-3.0 portaudio19-dev python3-dev pkg-config xdotool wtype wl-clipboard xclip xsel"
            echo ""
            echo "Fedora/RHEL-based:"
            echo "  sudo dnf install -y python3-gobject gtk3-devel libayatana-appindicator-gtk3 portaudio-devel python3-devel pkg-config xdotool wtype wl-clipboard xclip xsel"
            echo ""
            echo "Arch Linux:"
            echo "  sudo pacman -S python-gobject gtk3 libayatana-appindicator portaudio python pkg-config xdotool wtype wl-clipboard xclip xsel"
        fi

        echo ""
        echo "After installing system dependencies, run the installer again:"
        echo "  ./install.sh"
        return 1
    fi
}

check_deps
