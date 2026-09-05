# Vocalinux Flatpak Packaging

Manifest and AppStream metadata for building Vocalinux as a Flatpak.

## Current Scope

The manifest ships the default `whisper_cpp` engine only. VOSK is omitted because
the PyPI package is wheel-only (no sdist), so a Flathub-ready VOSK build would
need to compile VOSK and its native deps from source.

Global keyboard shortcuts use **evdev** (`/dev/input`).
Text injection uses **wl-copy** + **ydotool Ctrl+V** (instant paste into native
Wayland apps). Character-by-character `ydotool type` is only a fallback.
`xdotool` remains for pure X11/XWayland clients.

Permissions: `--socket=wayland` (clipboard), `--socket=x11` (xdotool fallback),
`--device=all` (evdev hotkeys + uinput; Flatpak has no narrower uinput flag).

## Local Build

```bash
# one-time runtime/SDK
flatpak install flathub org.gnome.Platform//50 org.gnome.Sdk//50

# from repo root — add flags as needed:
#   --user --install     install for the current user
#   --repo=repo          export a local repo (then bundle or lint)
#   --compose-url-policy=full --mirror-screenshots-url=https://dl.flathub.org/media
flatpak-builder --force-clean build-dir packaging/flatpak/com.vocalinux.Vocalinux.yml

flatpak run com.vocalinux.Vocalinux --debug

# single-file bundle (after a --repo=repo build)
flatpak build-bundle repo vocalinux.flatpak com.vocalinux.Vocalinux
# elsewhere: flatpak install --user vocalinux.flatpak
```

Lint (needs `org.flatpak.Builder`):

```bash
flatpak run --command=flatpak-builder-lint org.flatpak.Builder manifest packaging/flatpak/com.vocalinux.Vocalinux.yml
flatpak run --command=flatpak-builder-lint org.flatpak.Builder builddir build-dir
flatpak run --command=flatpak-builder-lint org.flatpak.Builder repo repo   # if you used --repo=repo
```

Prefer `flatpak run` after `--install` for GUI testing. On GNOME runtimes with
glycin loaders, `flatpak-builder --run` can fail to load themed SVG icons for an
uninstalled stable app ID; it is still fine for non-GUI smokes:

```bash
flatpak-builder --run build-dir packaging/flatpak/com.vocalinux.Vocalinux.yml \
  python3 -c 'from pywhispercpp.model import Model; print("pywhispercpp ok")'
```

## Python Dependencies

`python3-dependencies.yaml` is generated with `flatpak-pip-generator` (offline
builds). Regenerate when `pyproject.toml` deps change:

```bash
pipx run flatpak-pip-generator \
  --runtime org.gnome.Sdk//50 \
  --yaml \
  --ignore-pkg 'vosk>=0.3.45' "PyGObject; sys_platform == 'linux'" \
  --output packaging/flatpak/python3-dependencies \
  pywhispercpp pydub pynput evdev requests tqdm numpy pyaudio python-xlib psutil lxml \
  meson-python pyproject-metadata
```

`python3-build-dependencies.yaml` is a small hand-maintained helper so
`--no-build-isolation` builds can import `mesonpy` before NumPy is built.

## Flathub Submission Notes

Read this first: the submission,
[flathub/flathub#9368](https://github.com/flathub/flathub/pull/9368), was
**closed on 2026-07-23** on policy grounds — the generative-AI policy, plus a
"tray-only application" reading. Nothing below was the reason it failed, and
re-submitting without addressing that is a repeat. See
[#167](https://github.com/VocaHQ/vocalinux/issues/167) for the channel decision.

1. Change the `vocalinux` module source from `type: dir` to a tagged release:

   ```yaml
   sources:
     - type: git
       url: https://github.com/VocaHQ/vocalinux.git
       tag: v0.16.2
       commit: <release-commit-sha>
   ```

2. Keep build-time network access disabled; only declared sources.
3. Re-run AppStream validation and `flatpak-builder` locally.
4. Be ready to justify sandbox permissions (IBus and StatusNotifier D-Bus talk names).

## Manifest Details

- Runtime / SDK: `org.gnome.Platform//50`, `org.gnome.Sdk//50`
- Mic: `--socket=pulseaudio` · GPU: `--device=dri` · models: `--share=network`
- Input: `--device=all` (evdev hotkeys + ydotool/`uinput`)
- Injection: packaged `wl-copy`, `ydotool`/`ydotoold`, plus `xdotool`/`xsel` fallback
- Display: `--socket=wayland` (clipboard) and `--socket=x11` (xdotool fallback)
- IBus: `--talk-name=org.freedesktop.IBus`
- Tray: `--talk-name=org.kde.StatusNotifierWatcher`

Config and models use Flatpak XDG dirs under `~/.var/app/com.vocalinux.Vocalinux/`.
