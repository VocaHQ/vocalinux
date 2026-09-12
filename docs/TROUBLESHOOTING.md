# Troubleshooting

Common install and runtime problems. Install overview: [INSTALL.md](INSTALL.md). Support channels: [SUPPORT.md](../SUPPORT.md).

Always try once with debug logs:

```bash
vocalinux --debug
```

## Command not found: `vocalinux`

```bash
# Official install wrappers
export PATH="$HOME/.local/bin:$PATH"
vocalinux

# Or run the venv binary
~/.local/share/vocalinux/venv/bin/vocalinux

# Source checkout
source venv/bin/activate
vocalinux
```

## No audio / microphone not working

1. Check system sound settings and mute state
2. List capture devices: `arecord -l`
3. Run `vocalinux --debug` and confirm the selected device
4. Reset a bad device index: set `audio.device_index` to `null` in `~/.config/vocalinux/config.json`
5. Bluetooth mics: try a wired device to isolate SCO capture issues

## GTK / AppIndicator / `No module named gi`

Recreate the venv with system site packages:

```bash
sudo apt install python3-gi python3-gi-cairo   # Debian/Ubuntu example
# tray: gir1.2-ayatanaappindicator3-0.1  or  gir1.2-appindicator3-0.1

deactivate 2>/dev/null || true
rm -rf venv
/usr/bin/python3 -m venv venv --system-site-packages
source venv/bin/activate
pip install -e .
```

On GNOME, enable the AppIndicator extension if the tray icon never appears:

```bash
# Debian/Ubuntu
sudo apt install gnome-shell-extension-appindicator
# Fedora
sudo dnf install gnome-shell-extension-appindicator
# Arch
sudo pacman -S gnome-shell-extension-appindicator

gnome-extensions enable appindicatorsupport@rgcjonas.gmail.com
# log out/in if needed
```

Refresh icons:

```bash
gtk-update-icon-cache -f -t ~/.local/share/icons/hicolor
vocalinux --debug
```

## Text not injected into apps

**X11:**

```bash
sudo apt install xdotool   # or distro equivalent
xdotool type "hello"
```

**Wayland:**

```bash
sudo apt install wtype wl-clipboard xclip xsel
wtype "hello"
printf "bonjour" | xsel --clipboard --input
```

**KDE Plasma Wayland:** `wtype` may fail if the compositor does not expose a virtual keyboard to normal clients. Prefer **System Settings → Keyboard → Virtual Keyboard → IBus Wayland**, then restart Vocalinux (or log out/in).

Install IBus if needed:

```bash
# Ubuntu/Debian
sudo apt install ibus
# Fedora
sudo dnf install ibus
# Arch
sudo pacman -S ibus
```

Compositor-specific notes: [DISTRO_COMPATIBILITY.md](DISTRO_COMPATIBILITY.md).

## Model download fails

Models download on first use. Manual VOSK example:

```bash
mkdir -p ~/.local/share/vocalinux/models
cd ~/.local/share/vocalinux/models
wget https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip
unzip vosk-model-small-en-us-0.15.zip
```

More VOSK models: https://alphacephei.com/vosk/models
whisper.cpp models are managed from Settings or first-run download.

## `libwhisper.so` / pywhispercpp load errors

```bash
# Unresolved libs
ldd $(find ~/.local/share/vocalinux/venv -name '*.so' -path '*/pywhispercpp*' 2>/dev/null | head -1) | grep 'not found'

# Rebuild whisper.cpp bindings via installer
./install.sh --auto --rebuild-whispercpp

# Or switch to VOSK temporarily
vocalinux --engine vosk
```

## Old process still running after update

Stop via the tray, or use the lock-file PID (do **not** use `pkill -f vocalinux`; it can kill editors and shells):

```bash
kill "$(tr -d '[:space:]' < "${XDG_DATA_HOME:-$HOME/.local/share}/vocalinux/instance.lock")"
kill "$(tr -d '[:space:]' < "${XDG_DATA_HOME:-$HOME/.local/share}/vocalinux-ibus/engine.pid")"
vocalinux
```

## Clean reinstall

```bash
./uninstall.sh --keep-config --keep-data
curl -fsSL https://raw.githubusercontent.com/VocaHQ/vocalinux/main/install.sh -o /tmp/vl.sh
bash /tmp/vl.sh
```

## Distro PyGObject not importable in the venv

The distro `python3-gi` / `python3-gobject` package is installed, but `venv/` was built by a different Python than the one it targets. Current `install.sh` ignores an activated virtualenv and rebuilds a mismatched `venv/`. Otherwise:

```bash
deactivate 2>/dev/null || true
rm -rf venv
./install.sh
```

On systems with several system interpreters: `SYSTEM_PYTHON=/usr/bin/python3.12 ./install.sh`.

## Still stuck

- [SUPPORT.md](../SUPPORT.md)
- [GitHub Issues](https://github.com/VocaHQ/vocalinux/issues)
- [Discussions](https://github.com/VocaHQ/vocalinux/discussions)
- [Discord](https://discord.gg/t6muquAJbm)
