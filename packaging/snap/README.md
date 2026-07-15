# Vocalinux Snap packaging

Snap packaging for Ubuntu and other snap-enabled distros (issue
[#48](https://github.com/jatinkrmalik/vocalinux/issues/48)).

Recipe: [`snap/snapcraft.yaml`](../../snap/snapcraft.yaml)
GUI assets: [`snap/gui/`](../../snap/gui/)

## Status

| Item | State |
|------|--------|
| Snapcraft recipe in-repo | Yes (`snap/snapcraft.yaml`) |
| Published on Snap Store | **Not yet** (requires maintainer Snapcraft login + name ownership) |
| Intended first channel | `edge`, then promote to `stable` after validation |
| Confinement | `strict` (first ship) |
| Default engine | whisper.cpp (`pywhispercpp`); VOSK may install via project deps; OpenAI Whisper/torch **not** bundled |

Until the store listing exists, prefer the [install script](../../docs/INSTALL.md) or
PyPI. After publish:

```bash
# Testing channel (first publish target)
sudo snap install vocalinux --edge

# After promotion
sudo snap install vocalinux

# Microphone (if not auto-connected)
sudo snap connect vocalinux:audio-record
```

## Strategy (how we publish)

### Agent / repo work (done in this packaging)

1. Ship a current `snap/snapcraft.yaml` (version from `src/vocalinux/version.py`, not the stale 0.2.0 draft on #48).
2. Align plugs and staged tools with real runtime needs and Flatpak lessons.
3. Document build, install, limitations, and human-only store steps.
4. Keep secrets out of git (no Snapcraft credentials in CI until a dedicated store token is added later).

### Human-only Snap Store steps (maintainer)

These cannot be finished without a Snapcraft account that owns the name:

1. Create / log in at [snapcraft.io](https://snapcraft.io/) (`snapcraft login`).
2. Register the name if free: `snapcraft register vocalinux`.
3. Build a release snap (local or CI): `snapcraft pack` from a clean tree.
4. Upload: `snapcraft upload --release=edge vocalinux_*.snap` (or upload then `snapcraft release`).
5. Fill store listing: description, screenshots, license, contact, category.
6. Test on a real Ubuntu desktop: install `--edge`, mic permission, tray, dictate into another app.
7. Promote to `candidate` / `stable` when ready: `snapcraft release vocalinux <rev> stable`.
8. Add the Snap Store badge to the README once the public listing is live.
9. Optional later: CI with a Snap Store export token for continuous `edge` publishes.

### Channel path

```
local pack  →  upload to edge  →  manual QA  →  candidate (optional)  →  stable
```

Use `grade: devel` while shipping beta builds to non-stable channels. Set
`grade: stable` in the recipe before promoting a build intended for the
`stable` channel (store policy).

## Confinement and interfaces

**Decision: `strict` first**, not `classic`.

Reasons:

- Matches the security story users expect from the Snap Store.
- Mirrors Flatpak’s sandboxed first ship (X11 injection + mic + network, no `/dev/input`).
- Classic requires a manual store review and is harder to justify for a v1 listing.

| Need | Interface / mechanism | Notes |
|------|----------------------|--------|
| GTK tray / desktop | `gnome` extension (`desktop`, `desktop-legacy`, `unity7`, …) | AppIndicator/GTK from gnome-42 platform (do not stage a second GLib) |
| Display | `x11`, `wayland` (from extension) | Injection prefers X11/XWayland + xdotool; IBus D-Bus when available |
| Microphone | `audio-record` (+ `pulseaudio` legacy) | May need `snap connect` |
| Feedback sounds | `audio-playback` | Short UI tones |
| Model download | `network` | First-run / Settings downloads |
| Remote API engine | `network` / `network-bind` | Optional; not the primary path |
| GPU / Vulkan | `opengl` (extension) | whisper.cpp acceleration when available |
| Config / models | snap-private `HOME` (`~/snap/vocalinux/…`) | Same code paths (`~/.config`, `~/.local/share`) remap automatically |
| Global hotkeys | `raw-input` (manual connect) | `sudo snap connect vocalinux:raw-input` then restart; tray works without it |

If strict confinement blocks text injection or required desktop integration after
real-device testing, escalate deliberately:

1. Document the failure with compositor + interface list.
2. Consider extra interfaces or a reduced feature set.
3. Only then evaluate `classic` / store review (last resort).

## What is not in this snap (v1)

- OpenAI Whisper + PyTorch/CUDA (optional extra; huge).
- Privileged global shortcuts via evdev.
- Guaranteed native Wayland injection on every compositor (same class of limits as Flatpak; XWayland/xdotool and IBus paths are the supported sandboxed routes).
- Automatic Snap Store upload from CI (needs a human-provisioned token).

## Local build

Requirements:

- `snapcraft` (classic): `sudo snap install snapcraft --classic`
- A build provider: LXD **or** Multipass (snapcraft will prompt to set one up)

From the repository root:

```bash
snapcraft pack
# produces vocalinux_<version>_<arch>.snap

# Optional local install (dangerous on a daily driver — prefer a VM)
sudo snap install --dangerous ./vocalinux_*.snap
sudo snap connect vocalinux:audio-record
vocalinux --debug
```

Clean rebuild:

```bash
snapcraft clean
snapcraft pack
```

### If snapcraft / LXD / Multipass cannot run

Validate the recipe structure with the unit test:

```bash
pytest tests/test_snap_packaging.py -v
```

That test loads `snap/snapcraft.yaml` and asserts name, version source policy,
plugs, and staged injection helpers. It does **not** replace a real `snapcraft pack`.

## Relation to Flatpak

| Topic | Flatpak (`packaging/flatpak`) | Snap (this tree) |
|-------|-------------------------------|------------------|
| Engine scope | whisper.cpp first | whisper.cpp first (+ VOSK dep possible) |
| Mic | `pulseaudio` socket | `audio-record` / pulse |
| Injection | x11 + xdotool/xsel | stage xdotool/xsel/xclip; x11 via gnome extension |
| Hotkeys | no `/dev/input` | same |
| Models | network + app data dir | network + `~/snap/vocalinux/` |
| Store | Flathub (separate track) | Snap Store |

## Maintainer checklist (publish day)

- [ ] `snapcraft login`
- [ ] `snapcraft register vocalinux` (if name still free)
- [ ] Version in `src/vocalinux/version.py` matches the release you intend to ship
- [ ] `snapcraft pack` succeeds on amd64 (and arm64 if you support it)
- [ ] Upload to `edge` and install with `sudo snap install vocalinux --edge`
- [ ] Verify: tray icon, mic permission, model download, type into gedit/browser
- [ ] Store listing assets uploaded
- [ ] Promote to `stable` when satisfied
- [ ] README Snap badge + docs flipped from “not published yet” to live commands
