# Vocalinux Flatpak Packaging

Manifest and AppStream metadata for building Vocalinux as a Flatpak.

## GitHub Release bundles

Each `v*` GitHub Release attaches `Vocalinux-<version>-x86_64.flatpak` and
`Vocalinux-<version>-aarch64.flatpak`. That is the easy install path:

```bash
# once: Flathub remote + GNOME runtime (the app itself is not on Flathub)
flatpak remote-add --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
flatpak install flathub org.gnome.Platform//50

flatpak install --user ./Vocalinux-<version>-x86_64.flatpak
flatpak run com.vocalinux.Vocalinux
```

Bundles do **not** auto-update. Vocalinux is **not on Flathub** (submission
[flathub/flathub#9368](https://github.com/flathub/flathub/pull/9368) closed on
policy grounds; we are not re-submitting). A self-hosted VocaHQ remote is the
long-term auto-update path. Until then, download a new bundle from the next
release. Local `flatpak-builder` remains for contributors (below).

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

## Channel: GitHub Releases, not Flathub

Flathub is **not pursued**. The submission,
[flathub/flathub#9368](https://github.com/flathub/flathub/pull/9368), was closed
on 2026-07-23 on policy grounds. See
[#167](https://github.com/VocaHQ/vocalinux/issues/167) for the channel decision
and [#784](https://github.com/VocaHQ/vocalinux/issues/784) for release bundles.
Do not re-submit. Local builds and GitHub Release `.flatpak` assets are the
supported paths.

## Manifest Details

- Runtime / SDK: `org.gnome.Platform//50`, `org.gnome.Sdk//50`
- Mic: `--socket=pulseaudio` · GPU: `--device=dri` · models: `--share=network`
- Input: `--device=all` (evdev hotkeys + ydotool/`uinput`)
- Injection: packaged `wl-copy`, `ydotool`/`ydotoold`, plus `xdotool`/`xsel` fallback
- Display: `--socket=wayland` (clipboard) and `--socket=x11` (xdotool fallback)
- IBus: `--talk-name=org.freedesktop.IBus`
- Tray: `--talk-name=org.kde.StatusNotifierWatcher`

Config and models use Flatpak XDG dirs under `~/.var/app/com.vocalinux.Vocalinux/`.
